"""Ticket builder engine — converts config templates + runtime vars into Jira API payloads.

This module is pure data transformation. No I/O, no API calls. It takes an
OrgConfig, TeamConfig, and runtime variables, and produces a list of dicts
ready for the Jira REST API ``/rest/api/3/issue`` endpoint.

Two-phase build:
    1. ``build_epics()`` → epic payloads (created first so we get real Jira keys)
    2. ``build_tickets()`` → all ticket payloads (uses epic_keys for $epic:ref resolution)

Or use ``build_all()`` for a single-call convenience wrapper.
"""

from __future__ import annotations

from typing import Any

from jiramator.config import OrgConfig, TeamConfig, TicketTemplate, _EPIC_REF_RE, _TEMPLATE_VAR_RE
from jiramator.value_coercion import _adf_paragraph
from jiramator.yaml_loader import strip_line_markers as _strip_line_markers

# ---------------------------------------------------------------------------
# Field type wrapping
# ---------------------------------------------------------------------------
#
# Jira's REST API requires specific JSON structures for certain fields.
# The builder transforms flat config values into the correct shapes.
#
# Why is this in the builder and not the config?  Because the config stores
# logical values ("Task", "Medium", "26.1.1") and the builder produces API
# payloads.  Keeping the config free of API concerns makes it portable.

WRAPPED_FIELDS: dict[str, str] = {
    "issuetype": "name_object",          # {"name": "Task"}
    "priority": "name_object",           # {"name": "Medium"}
    "fixVersions": "name_object_array",  # [{"name": "26.1.1"}, ...]
    "components": "name_object_array",   # [{"name": "Frontend"}, ...]
    # Jira Cloud's REST API v3 requires `description` as Atlassian Document
    # Format (ADF), not a plain string — mirrors value_coercion.py's handling
    # for import/update.
    "description": "adf_text",
}
# ``labels`` is already a string array in Jira — no wrapping needed.
# ``project`` is injected by the builder as {"key": "..."}.
# Custom fields (customfield_*) pass through as plain strings *unless* the
# org config declares them ``adf_text`` in ``bulk_create.field_types`` (see
# ``_adf_custom_field_ids()``) — Jira Cloud rejects plain strings for any
# rich-text/textarea custom field (e.g. "Acceptance Criteria"), not just the
# built-in ``description`` field.


def _adf_custom_field_ids(org_config: OrgConfig) -> frozenset[str]:
    """Determine which Jira custom field IDs require ADF-wrapped text.

    Ticket templates key their ``fields:`` blocks by raw Jira field name
    (e.g. ``customfield_10042``), but ``field_types`` in the org config is
    keyed by logical field name (e.g. ``acceptance_criteria``) — the same
    convention used for import/update coercion. This reverse-maps logical
    names declared ``adf_text`` back to their Jira field IDs via
    ``custom_fields`` so the same declaration works for ``plan`` too.

    Args:
        org_config: Organization config with ``custom_fields`` and
            ``bulk_create.field_types`` mappings.

    Returns:
        Frozenset of Jira custom field IDs (e.g. ``{"customfield_10042"}``)
        that must be rendered as ADF.
    """
    field_types = org_config.bulk_create.field_types
    return frozenset(
        jira_field_id
        for logical_name, jira_field_id in org_config.custom_fields.items()
        if field_types.get(logical_name) == "adf_text"
    )


def _strip_template_key(payloads: list[dict[str, Any]]) -> None:
    """Remove ``_template_key`` annotations in place before sending to Jira.

    The annotation is internal metadata for run-report identity (FOUND-02/03).
    Jira would reject it as an unknown field. Mirrors the ``_sprint_num`` strip
    pattern in :func:`jiramator.planner._resolve_sprint_ids`.
    """
    for p in payloads:
        p.pop("_template_key", None)


def _wrap_field(field_name: str, value: Any, adf_custom_field_ids: frozenset[str] = frozenset()) -> Any:
    """Apply Jira field-type wrapping to a resolved value.

    Args:
        field_name: The Jira field name (e.g. "issuetype", "fixVersions").
        value: The already-resolved value (template vars interpolated, etc.).
        adf_custom_field_ids: Custom field IDs (e.g. "customfield_10042")
            that the org config declares as ``adf_text`` — see
            :func:`_adf_custom_field_ids`.

    Returns:
        The value wrapped in the appropriate Jira JSON structure.
    """
    if field_name in adf_custom_field_ids:
        wrap_type = "adf_text"
    else:
        wrap_type = WRAPPED_FIELDS.get(field_name)
    if wrap_type is None:
        return value

    if wrap_type == "name_object":
        return {"name": value}
    elif wrap_type == "name_object_array":
        if isinstance(value, list):
            return [{"name": item} for item in value]
        return [{"name": value}]
    elif wrap_type == "adf_text":
        return _adf_paragraph(str(value).strip())

    return value  # pragma: no cover — unreachable with current WRAPPED_FIELDS


# ---------------------------------------------------------------------------
# Template resolution
# ---------------------------------------------------------------------------


def resolve_value(
    value: Any,
    variables: dict[str, str],
    epic_keys: dict[str, str],
) -> Any:
    """Resolve a single config value by interpolating templates and epic refs.

    Args:
        value: A config value — could be a string, number, list, etc.
        variables: Runtime template variables (pi_label, version, etc.).
        epic_keys: Mapping of epic ref keys to Jira issue keys
                   (e.g. {"misc": "CA-5001"}).

    Returns:
        The resolved value, ready for field wrapping.
    """
    if isinstance(value, str):
        # Check for $epic:ref first (exact match on the whole string)
        epic_match = _EPIC_REF_RE.match(value)
        if epic_match:
            ref_key = epic_match.group(1)
            return epic_keys.get(ref_key, value)  # fall back to raw if unresolved

        # Template interpolation — replace all {var} occurrences
        if _TEMPLATE_VAR_RE.search(value):
            result = value
            for var_name, var_value in variables.items():
                result = result.replace(f"{{{var_name}}}", str(var_value))
            return result

        return value

    if isinstance(value, list):
        return [resolve_value(item, variables, epic_keys) for item in value]

    # Numbers, booleans, None — pass through
    return value


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _build_fields_payload(
    template_fields: dict[str, Any],
    summary: str,
    project_key: str,
    variables: dict[str, str],
    epic_keys: dict[str, str],
    adf_custom_field_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Build a complete ``fields`` dict for a Jira issue creation payload.

    Resolves all template variables and epic refs, applies field-type wrapping,
    and injects ``project`` and ``summary``.

    Args:
        adf_custom_field_ids: Custom field IDs the org config declares
            ``adf_text`` — see :func:`_adf_custom_field_ids`.
    """
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "summary": resolve_value(summary, variables, epic_keys),
    }

    # Defuse Pitfall 1: line-aware YAML loader injects __line__ on every
    # parsed mapping; Pydantic dict[str, Any] fields pass it through. Strip
    # before resolution so it never reaches Jira's REST API.
    template_fields = _strip_line_markers(template_fields)

    for field_name, raw_value in template_fields.items():
        resolved = resolve_value(raw_value, variables, epic_keys)
        fields[field_name] = _wrap_field(field_name, resolved, adf_custom_field_ids)

    return fields


def build_epics(
    org_config: OrgConfig,
    team_config: TeamConfig,
    variables: dict[str, str],
) -> list[dict[str, Any]]:
    """Build Jira payloads for all recurring epics.

    Args:
        org_config: Organization config (for custom field IDs).
        team_config: Team config with epic templates.
        variables: Runtime variables (must include pi_label, team_name, etc.).

    Returns:
        List of {"ref_key": str, "payload": {"fields": {...}}} dicts.
        ``ref_key`` is the epic's internal reference (e.g. "misc") used later
        to populate ``epic_keys`` after creation.
    """
    epics = []
    adf_custom_field_ids = _adf_custom_field_ids(org_config)
    for epic_tmpl in team_config.recurring_epics:
        fields = _build_fields_payload(
            epic_tmpl.fields,
            epic_tmpl.summary,
            team_config.project_key,
            variables,
            {},
            adf_custom_field_ids,
        )
        # Epics must always be created as Jira Epic issues, regardless of what
        # might be present in the template fields.
        fields["issuetype"] = {"name": "Epic"}
        epics.append({
            "ref_key": epic_tmpl.key,
            "_template_key": f"epic:{epic_tmpl.key}",
            "payload": {"fields": fields},
        })
    return epics


def build_per_release_tickets(
    org_config: OrgConfig,
    team_config: TeamConfig,
    variables: dict[str, str],
    versions: list[str],
    epic_keys: dict[str, str],
) -> list[dict[str, Any]]:
    """Build ticket payloads for per-release templates × versions.

    Args:
        org_config: Organization config.
        team_config: Team config with per_release_tickets templates.
        variables: Base runtime variables (version will be overridden per iteration).
        versions: List of release version strings (e.g. ["26.1.1", "26.1.2", "26.2.0"]),
            in release order — used both to interpolate `{version}` and, via
            `len(versions)`, to select the matching `release_sprint_schedule`
            entry (sprint numbers are then applied by position, not by the
            literal version string).
        epic_keys: Mapping of epic ref keys to Jira issue keys.

    Returns:
        List of {"fields": {...}, "_sprint_num": str|None} payloads, one per template × version.
    """
    tickets = []
    adf_custom_field_ids = _adf_custom_field_ids(org_config)
    release_count = len(versions)
    schedule = team_config.release_sprint_schedule.get(release_count)
    for position, version in enumerate(versions):
        version_vars = {**variables, "version": version}
        for template_idx, tmpl in enumerate(team_config.per_release_tickets):
            fields = _build_fields_payload(
                tmpl.fields,
                tmpl.summary,
                team_config.project_key,
                version_vars,
                epic_keys,
                adf_custom_field_ids,
            )
            # Resolve sprint number from release_sprint_schedule + sprint_group,
            # applied to `versions` by position (not by literal version string) —
            # so the same schedule is reused every PI once the release count is
            # known, instead of hand-editing a version-keyed map each quarter.
            sprint_num = None
            if tmpl.sprint_group:
                if schedule is None:
                    raise ValueError(
                        f"Team '{team_config.team_name}' has no "
                        f"release_sprint_schedule entry for {release_count} "
                        f"release(s) (versions: {', '.join(versions)}), but "
                        f"per_release_tickets[{template_idx}] declares "
                        f"sprint_group={tmpl.sprint_group!r}. Add a "
                        f"release_sprint_schedule: {{{release_count}: [...]}} "
                        "entry to the team config."
                    )
                sprint_num = schedule[position].get(tmpl.sprint_group)
            ticket: dict[str, Any] = {
                "fields": fields,
                "_template_key": f"per_release[{template_idx}]:{version}",
            }
            if sprint_num is not None:
                ticket["_sprint_num"] = str(sprint_num)
            tickets.append(ticket)
    return tickets


def _build_sprint_ticket(
    tmpl: TicketTemplate,
    project_key: str,
    variables: dict[str, str],
    epic_keys: dict[str, str],
    sprint_label: str,
    adf_custom_field_ids: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Build a single per-sprint ticket payload.

    Args:
        tmpl: The ticket template.
        project_key: Jira project key.
        variables: Base runtime variables.
        epic_keys: Epic ref → Jira key mapping.
        sprint_label: The sprint_num value (e.g. "3", "6a", "6b").
        adf_custom_field_ids: Custom field IDs the org config declares
            ``adf_text`` — see :func:`_adf_custom_field_ids`.

    Returns:
        A {"fields": {...}} payload dict.
    """
    sprint_vars = {**variables, "sprint_num": sprint_label}
    fields = _build_fields_payload(
        tmpl.fields,
        tmpl.summary,
        project_key,
        sprint_vars,
        epic_keys,
        adf_custom_field_ids,
    )
    return {"fields": fields, "_sprint_num": sprint_label}


def build_per_sprint_tickets(
    org_config: OrgConfig,
    team_config: TeamConfig,
    variables: dict[str, str],
    epic_keys: dict[str, str],
) -> list[dict[str, Any]]:
    """Build ticket payloads for per-sprint templates across all sprints.

    Handles long sprint expansion: when a sprint number is in
    ``org_config.sprints.long_sprints`` and a template has
    ``extra_on_long_sprint > 0``, generates additional tickets with suffixed
    sprint numbers (e.g. "6a", "6b" instead of plain "6").

    Args:
        org_config: Organization config (for sprint count and long sprint info).
        team_config: Team config with per_sprint_tickets templates.
        variables: Base runtime variables.
        epic_keys: Epic ref → Jira key mapping.

    Returns:
        List of {"fields": {...}} payloads.
    """
    tickets = []
    sprint_cfg = org_config.sprints
    long_sprint_set = set(sprint_cfg.long_sprints)
    adf_custom_field_ids = _adf_custom_field_ids(org_config)

    for sprint_num in range(1, sprint_cfg.count + 1):
        is_long = sprint_num in long_sprint_set

        for template_idx, tmpl in enumerate(team_config.per_sprint_tickets):
            if is_long and tmpl.extra_on_long_sprint > 0:
                # Long sprint with extras — generate suffixed tickets
                # e.g. extra_on_long_sprint=1, suffixes=["a","b"] → "6a" and "6b"
                for suffix in tmpl.long_sprint_suffix:
                    sprint_label = f"{sprint_num}{suffix}"
                    ticket = _build_sprint_ticket(
                        tmpl, team_config.project_key,
                        variables, epic_keys, sprint_label,
                        adf_custom_field_ids,
                    )
                    ticket["_template_key"] = f"per_sprint[{template_idx}]:{sprint_label}"
                    tickets.append(ticket)
            else:
                # Standard sprint or template without extras
                sprint_label = str(sprint_num)
                ticket = _build_sprint_ticket(
                    tmpl, team_config.project_key,
                    variables, epic_keys, sprint_label,
                    adf_custom_field_ids,
                )
                ticket["_template_key"] = f"per_sprint[{template_idx}]:{sprint_label}"
                tickets.append(ticket)

    return tickets


def build_all(
    org_config: OrgConfig,
    team_config: TeamConfig,
    pi_label: str,
    pi_num: str,
    versions: list[str],
    epic_keys: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Build all ticket payloads in a single call.

    This is the main entry point for the planner. It constructs the runtime
    variables dict from the provided arguments and delegates to the individual
    builders.

    Args:
        org_config: Organization config.
        team_config: Team config.
        pi_label: PI label (e.g. "PI28").
        pi_num: PI number (e.g. "28").
        versions: Release version strings.
        epic_keys: Epic ref → Jira key mapping.
                   Pass ``{}`` for dry-run (epic refs will be unresolved).

    Returns:
        Dict with keys "epics", "per_release", "per_sprint", each mapping
        to a list of payloads.
    """
    variables: dict[str, str] = {
        "pi_label": pi_label,
        "pi_num": pi_num,
        "team_name": team_config.team_name,
    }

    return {
        "epics": build_epics(org_config, team_config, variables),
        "per_release": build_per_release_tickets(
            org_config, team_config, variables, versions, epic_keys,
        ),
        "per_sprint": build_per_sprint_tickets(
            org_config, team_config, variables, epic_keys,
        ),
    }
