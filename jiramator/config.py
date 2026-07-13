"""Pydantic models for org-level and team-level Jiramator configs."""

from __future__ import annotations

import os
import re
import typing
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator, model_validator

from jiramator.error_format import ConfigValidationError, did_you_mean, format_loc
from jiramator.yaml_loader import LINE_KEY, resolve_line, safe_load_with_lines, strip_line_markers

# Known template variables that can appear in {brackets} in config strings.
# The ticket builder will provide concrete values for these at runtime.
KNOWN_TEMPLATE_VARS = frozenset({
    "pi_label",     # e.g. "PI28"
    "pi_num",       # e.g. "28"
    "version",      # e.g. "26.1.1" — only valid in per_release_tickets
    "sprint_num",   # e.g. "1", "6a" — only valid in per_sprint_tickets
    "team_name",    # e.g. "Calcs"
})

# Regex to find {var} template references in strings
_TEMPLATE_VAR_RE = re.compile(r"\{(\w+)\}")

# Regex to find $epic:key references
_EPIC_REF_RE = re.compile(r"^\$epic:(\w+)$")


# ---------------------------------------------------------------------------
# Org config — shared across all teams at a company
# ---------------------------------------------------------------------------


class SprintConfig(BaseModel):
    """Sprint cadence for a PI."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(gt=0, description="Total number of sprints in a PI")
    standard_length_weeks: int = Field(gt=0, description="Length of standard sprints in weeks")
    long_length_weeks: int = Field(gt=0, description="Length of long (extended) sprints in weeks")
    long_sprints: list[int] = Field(
        default_factory=list,
        description="Sprint numbers that use long_length_weeks (1-indexed)",
    )

    @field_validator("long_sprints")
    @classmethod
    def validate_long_sprints(cls, v: list[int], info: Any) -> list[int]:
        """Ensure long sprint numbers are within the valid range."""
        count = info.data.get("count")
        if count is not None:
            for sprint_num in v:
                if sprint_num < 1 or sprint_num > count:
                    raise ValueError(
                        f"long_sprint {sprint_num} is out of range (1-{count})"
                    )
        return v


class BulkCreateConfig(BaseModel):
    """Shared config for ad-hoc bulk issue creation inputs and coercion."""

    model_config = ConfigDict(extra="forbid")

    field_aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Maps source-facing field names/headers to logical field names",
    )
    field_types: dict[str, str] = Field(
        default_factory=dict,
        description="Maps logical or Jira field names to coercion types",
    )
    value_aliases: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Per-field value shorthand -> exact Jira option label, for "
            "single_select/multi_select fields. Keyed by the same field "
            "name used in field_types (logical name or Jira field name). "
            "E.g. code_complexity: {'1': '1. Low', '2': '2. Medium'} lets "
            "source data use '1' while Jira requires the full option "
            "string '1. Low'. Unmapped values pass through unchanged."
        ),
    )
    defaults: dict[str, Any] = Field(
        default_factory=dict,
        description="Default field values applied by bulk-create workflows",
    )
    auto_lookup_unknown_fields: bool = Field(
        default=True,
        description="Whether to use Jira field metadata to resolve unknown fields",
    )
    multi_value_delimiter: str = Field(
        default=",",
        description="Delimiter for splitting multi-value fields from string inputs",
    )


class OrgConfig(BaseModel):
    """Organization-level configuration — Jira instance, custom fields, sprint structure."""

    model_config = ConfigDict(extra="forbid")

    jira_url: HttpUrl = Field(description="Base URL of the Jira instance")
    jira_email_env: str = Field(
        default="JIRA_EMAIL",
        description="Name of the env var containing the Jira user email",
    )
    jira_token_env: str = Field(
        default="JIRA_TOKEN",
        description="Name of the env var containing the Jira API token",
    )
    custom_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of logical field names to Jira custom field IDs",
    )
    bulk_create: BulkCreateConfig = Field(
        default_factory=BulkCreateConfig,
        description="Shared config for ad-hoc bulk issue creation workflows",
    )
    default_fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Locked fields applied to every issue created via `plan` (epics, "
            "per-release tickets, per-sprint tickets) under any team config in "
            "this org. Keys mirror the Jira `fields:` shape on templates "
            "(logical names like `priority` or direct Jira keys like "
            "`customfield_10273`). Same-name keys in team `defaults:` or "
            "template `fields:` are warned and dropped at config-load time. "
            "Phase 2: NOT applied to the `import` command path; see importer.py."
        ),
    )
    sprints: SprintConfig = Field(description="Sprint cadence configuration")

    def get_custom_field_id(self, logical_name: str) -> str:
        """Look up a custom field ID by its logical name.

        Raises KeyError if the logical name is not defined.
        """
        try:
            return self.custom_fields[logical_name]
        except KeyError:
            raise KeyError(
                f"Custom field '{logical_name}' is not defined in org config. "
                f"Available fields: {list(self.custom_fields.keys())}"
            )

    def resolve_credentials(self) -> tuple[str, str]:
        """Read Jira credentials from environment variables.

        Returns (email, token) tuple.
        Raises ValueError if either env var is missing or empty.
        """
        email = os.environ.get(self.jira_email_env, "").strip()
        token = os.environ.get(self.jira_token_env, "").strip()

        missing = []
        if not email:
            missing.append(self.jira_email_env)
        if not token:
            missing.append(self.jira_token_env)

        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                f"Set them before running jiramator."
            )

        return email, token


# ---------------------------------------------------------------------------
# Config loading utilities
# ---------------------------------------------------------------------------


def _unwrap_to_basemodel(annotation: Any) -> type[BaseModel] | None:
    """Extract a nested Pydantic model class from a field annotation.

    Handles plain model types, ``Optional``/``X | None`` unions, and
    ``list[X]`` / ``dict[str, X]`` wrappers — the only shapes used in this
    module's config models.
    """
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin in (list, set, tuple) and args:
        return _unwrap_to_basemodel(args[0])
    if origin is dict and len(args) == 2:
        return _unwrap_to_basemodel(args[1])
    if origin is not None and args:
        # Union / Optional — check each non-None member.
        for arg in args:
            if arg is type(None):
                continue
            found = _unwrap_to_basemodel(arg)
            if found is not None:
                return found
    return None


def _model_at_path(
    root_model: type[BaseModel], loc: tuple[int | str, ...]
) -> type[BaseModel] | None:
    """Walk a Pydantic error ``loc`` path to find the model class at that
    location, so an ``extra_forbidden`` error can suggest a close match
    among *that* model's actual field names.

    Returns ``None`` if the path can't be resolved (e.g. it descends into a
    plain ``dict[str, Any]`` such as a ticket template's ``fields:`` block,
    where arbitrary keys are expected and no suggestion is meaningful).
    """
    current = root_model
    for seg in loc:
        if isinstance(seg, int):
            continue  # list index — item type is unchanged
        field_info = current.model_fields.get(seg)
        if field_info is None:
            return None
        nested = _unwrap_to_basemodel(field_info.annotation)
        if nested is None:
            return None
        current = nested
    return current


def _wrap_validation_error(
    exc: ValidationError,
    *,
    file: Path,
    tagged_raw: object,
    root_model: type[BaseModel] | None = None,
    known_template_vars: frozenset[str] = KNOWN_TEMPLATE_VARS,
) -> ConfigValidationError:
    """Convert the first error in a Pydantic ``ValidationError`` to a
    ``ConfigValidationError`` enriched with line + did-you-mean."""
    first = exc.errors()[0]
    loc = first["loc"]
    msg = first["msg"]
    line = resolve_line(tagged_raw, loc)
    field_path = format_loc(loc) or "<root>"

    # Heuristic: if the failing message mentions an unknown template variable,
    # mine the offender out and propose a close match from KNOWN_TEMPLATE_VARS.
    suggestion: str | None = None
    if "Unknown template variable" in msg:
        # Format from _validate_template_vars:
        #   "Unknown template variable(s) in <ctx>: <names>. Known variables: ..."
        try:
            after = msg.split("Unknown template variable(s) in", 1)[1]
            names_part = after.split(":", 1)[1].split(".", 1)[0]
            offenders = [n.strip() for n in names_part.split(",") if n.strip()]
            if offenders:
                # Suggest for the first offender — the typical case is one typo.
                suggestion = did_you_mean(offenders[0], sorted(known_template_vars))
        except (IndexError, ValueError):
            suggestion = None
    elif first["type"] == "extra_forbidden" and root_model is not None and loc:
        # An unrecognized key was found — e.g. a typo like `custom_fiedls`.
        # Resolve the enclosing model to suggest a close match among its
        # actual field names, mirroring the template-var suggestion above.
        offender = loc[-1]
        if isinstance(offender, str):
            parent_model = _model_at_path(root_model, loc[:-1])
            if parent_model is not None:
                suggestion = did_you_mean(
                    offender, sorted(parent_model.model_fields.keys())
                )

    return ConfigValidationError(
        file=file,
        line=line,
        field_path=field_path,
        reason=msg,
        suggestion=suggestion,
    )


def _load_yaml_with_lines(path: Path, kind: str) -> tuple[dict[str, Any], object]:
    """Open ``path`` and parse it with the line-aware loader.

    Returns ``(clean_dict_for_pydantic, tagged_raw_for_line_resolution)``.

    Raises ``ConfigValidationError`` for: file-not-found, YAML parse errors,
    and non-mapping document roots.
    """
    try:
        with open(path, encoding="utf-8", errors="strict") as f:
            text = f.read()
    except FileNotFoundError as exc:
        raise ConfigValidationError(
            file=path,
            line=None,
            field_path="<file>",
            reason=f"{kind} config not found: {path}",
        ) from exc
    except OSError as exc:
        raise ConfigValidationError(
            file=path,
            line=None,
            field_path="<file>",
            reason=f"Cannot read {kind} config: {exc}",
        ) from exc

    try:
        tagged_raw = safe_load_with_lines(text)
    except yaml.YAMLError as exc:
        # Most YAMLError subclasses (ScannerError, ParserError, etc.) carry
        # a problem_mark with a 0-indexed .line attribute.
        line: int | None = None
        problem_mark = getattr(exc, "problem_mark", None)
        if problem_mark is not None:
            line = problem_mark.line + 1
        detail = str(exc).strip()
        if detail:
            reason = f"YAML parse error ({exc.__class__.__name__}): {detail}"
        else:
            reason = f"YAML parse error: {exc.__class__.__name__}"
        raise ConfigValidationError(
            file=path,
            line=line,
            field_path="<yaml>",
            reason=reason,
        ) from exc

    if not isinstance(tagged_raw, dict):
        raise ConfigValidationError(
            file=path,
            line=1,
            field_path="<root>",
            reason=(
                f"{kind} config must be a YAML mapping, "
                f"got {type(tagged_raw).__name__}"
            ),
        )

    clean = strip_line_markers(tagged_raw)
    return clean, tagged_raw


def load_org_config(path: str | Path) -> tuple[OrgConfig, object]:
    """Load and validate an org config from a YAML file.

    Returns the validated model AND the line-tagged raw tree (the latter is
    consumed by Phase 2 ``merge_configs`` to resolve line numbers when
    emitting org-vs-team conflict warnings).

    Raises ``ConfigValidationError`` for missing files, parse errors,
    non-mapping roots, and Pydantic validation failures (with file:line
    pinpointing and did-you-mean suggestions where applicable).
    """
    path = Path(path)
    clean, tagged = _load_yaml_with_lines(path, kind="Org")
    try:
        return OrgConfig(**clean), tagged
    except ValidationError as exc:
        raise _wrap_validation_error(
            exc, file=path, tagged_raw=tagged, root_model=OrgConfig
        ) from exc


# ---------------------------------------------------------------------------
# Team config — per-team ticket templates and conventions
# ---------------------------------------------------------------------------


def _validate_template_vars(text: str, context: str) -> None:
    """Check that all {var} references in a string are known template variables.

    Raises ValueError with a clear message if unknown variables are found.
    """
    found = set(_TEMPLATE_VAR_RE.findall(text))
    unknown = found - KNOWN_TEMPLATE_VARS
    if unknown:
        raise ValueError(
            f"Unknown template variable(s) in {context}: "
            f"{', '.join(sorted(unknown))}. "
            f"Known variables: {', '.join(sorted(KNOWN_TEMPLATE_VARS))}"
        )


def _collect_epic_refs(fields: dict[str, Any]) -> set[str]:
    """Recursively find all $epic:key references in a fields dict."""
    refs: set[str] = set()
    for value in fields.values():
        if isinstance(value, str):
            m = _EPIC_REF_RE.match(value)
            if m:
                refs.add(m.group(1))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    m = _EPIC_REF_RE.match(item)
                    if m:
                        refs.add(m.group(1))
    return refs


def _collect_template_vars_in_fields(fields: dict[str, Any], context: str) -> None:
    """Validate template variables in all string values within a fields dict."""
    for key, value in fields.items():
        if isinstance(value, str) and not value.startswith("$epic:"):
            _validate_template_vars(value, f"{context}.fields.{key}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str) and not item.startswith("$epic:"):
                    _validate_template_vars(item, f"{context}.fields.{key}[{i}]")


class EpicTemplate(BaseModel):
    """Template for a recurring epic created each PI."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Internal reference key (e.g. 'bau', 'misc')")
    summary: str = Field(description="Epic summary template (supports {variables})")
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Jira field values for the epic — keys are field names or custom field IDs",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary_vars(cls, v: str) -> str:
        _validate_template_vars(v, "epic.summary")
        return v

    @model_validator(mode="after")
    def validate_field_template_vars(self) -> EpicTemplate:
        """Validate template variables in all epic field strings."""
        _collect_template_vars_in_fields(self.fields, f"epic[{self.key}]")
        return self


class TicketTemplate(BaseModel):
    """Template for a recurring ticket generated per release or per sprint."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(description="Ticket summary template (supports {variables})")
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Jira field values — keys are field names or custom field IDs",
    )
    extra_on_long_sprint: int = Field(
        default=0,
        ge=0,
        description="Additional tickets to create on long sprints (per_sprint only)",
    )
    long_sprint_suffix: list[str] = Field(
        default_factory=list,
        description="Suffixes for sprint_num on long sprints (e.g. ['a', 'b'])",
    )
    sprint_group: str | None = Field(
        default=None,
        description="Sprint group for release-sprint mapping (e.g. 'pre', 'post'). "
                    "Used with release_sprint_map to assign per-release tickets to sprints.",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary_vars(cls, v: str) -> str:
        _validate_template_vars(v, "ticket.summary")
        return v

    @model_validator(mode="after")
    def validate_long_sprint_suffix_count(self) -> TicketTemplate:
        """If extra_on_long_sprint > 0, we need exactly 1 + extra suffixes."""
        if self.extra_on_long_sprint > 0:
            expected = 1 + self.extra_on_long_sprint
            if len(self.long_sprint_suffix) != expected:
                raise ValueError(
                    f"extra_on_long_sprint={self.extra_on_long_sprint} requires "
                    f"{expected} long_sprint_suffix entries (original + extras), "
                    f"got {len(self.long_sprint_suffix)}: {self.long_sprint_suffix}"
                )
        return self


class TeamDefaults(BaseModel):
    """Per-team baseline ``fields`` block, merged into every template
    (recurring_epics, per_release_tickets, per_sprint_tickets) under this
    team config at load time.

    Same-name keys in template ``fields:`` are warned and dropped at load
    time — no override mechanism (Phase 2 CONTEXT G-1, "locked is locked").

    Future-proofing: the wrapper sub-model (rather than a bare
    ``dict[str, Any]``) leaves room to add other shared template defaults
    (e.g. ``summary_prefix``) without restructuring.
    """

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Locked fields applied to every template in this team config. "
            "Same-name keys in template fields are warned and dropped at "
            "load time."
        ),
    )


class TeamConfig(BaseModel):
    """Team-level configuration — project key, epics, ticket templates."""

    model_config = ConfigDict(extra="forbid")

    project_key: str = Field(description="Jira project key (e.g. 'CA')")
    team_name: str = Field(description="Human-readable team name (e.g. 'Calcs')")
    board_id: int | None = Field(
        default=None,
        description="Jira board ID for sprint assignment (optional)",
    )
    sprint_name_template: str | None = Field(
        default=None,
        description="Sprint name pattern for matching (e.g. 'CA Sprint {pi_num}.{sprint_num}')",
    )
    sprints_exist: bool | None = Field(
        default=None,
        description=(
            "Whether sprints for the PI already exist in Jira at `plan` time. "
            "Tri-state: `None` (default) means 'ask interactively when running on a "
            "TTY, error on non-TTY'; `True` means resolve sprints; `False` means "
            "skip sprint resolution entirely (no Jira board API call). The CLI flag "
            "`--sprints-exist / --no-sprints-exist` overrides this field at runtime. "
            "When set to `False`, no Jira sprint API call is made even if `board_id` "
            "is configured (Plan 02-03, DC-8)."
        ),
    )

    @field_validator("sprints_exist", mode="before")
    @classmethod
    def _strict_bool_or_none(cls, v: object) -> bool | None:
        """Reject non-bool/non-None values (no string coercion — Plan 02-03 SE5)."""
        if v is None or isinstance(v, bool):
            return v
        raise ValueError(
            f"sprints_exist must be a boolean or null, got {type(v).__name__}: {v!r}"
        )
    release_sprint_map: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Maps version → {sprint_group: sprint_number} for per-release sprint assignment. "
                    "e.g. {'26.2.1': {'pre': 2, 'post': 3}}",
    )

    defaults: TeamDefaults = Field(
        default_factory=TeamDefaults,
        description=(
            "Team-internal default fields merged into all templates in "
            "this team config (recurring_epics, per_release_tickets, "
            "per_sprint_tickets). Locked at load time per Phase 2 G-1."
        ),
    )

    existing_epics: dict[str, str] = Field(
        default_factory=dict,
        description="Pre-existing epic keys to reuse instead of creating (ref_key → Jira key, e.g. {bau: CA-1234})",
    )
    recurring_epics: list[EpicTemplate] = Field(
        default_factory=list,
        description="Epics to create at the start of each PI",
    )
    per_release_tickets: list[TicketTemplate] = Field(
        default_factory=list,
        description="Tickets generated once per release version",
    )
    per_sprint_tickets: list[TicketTemplate] = Field(
        default_factory=list,
        description="Tickets generated once per sprint",
    )

    @field_validator("recurring_epics")
    @classmethod
    def validate_unique_epic_keys(cls, v: list[EpicTemplate]) -> list[EpicTemplate]:
        keys = [e.key for e in v]
        dupes = [k for k in keys if keys.count(k) > 1]
        if dupes:
            raise ValueError(f"Duplicate epic keys: {set(dupes)}")
        return v

    @model_validator(mode="after")
    def validate_no_epic_key_overlap(self) -> TeamConfig:
        """Ensure no key appears in both existing_epics and recurring_epics."""
        recurring_keys = {e.key for e in self.recurring_epics}
        overlap = recurring_keys & set(self.existing_epics)
        if overlap:
            raise ValueError(
                f"Epic key(s) defined in both existing_epics and recurring_epics: "
                f"{', '.join(sorted(overlap))}. Each key must appear in only one."
            )
        return self

    @model_validator(mode="after")
    def validate_epic_refs(self) -> TeamConfig:
        """Ensure all $epic:key references point to defined recurring_epics or existing_epics."""
        epic_keys = {e.key for e in self.recurring_epics} | set(self.existing_epics)
        all_templates = self.per_release_tickets + self.per_sprint_tickets

        for i, tmpl in enumerate(all_templates):
            refs = _collect_epic_refs(tmpl.fields)
            unknown = refs - epic_keys
            if unknown:
                raise ValueError(
                    f"Ticket template '{tmpl.summary}' references undefined epic(s): "
                    f"{', '.join(sorted(unknown))}. "
                    f"Defined epics: {', '.join(sorted(epic_keys))}"
                )
        return self

    @model_validator(mode="after")
    def validate_field_template_vars(self) -> TeamConfig:
        """Validate template variables in all ticket template fields."""
        for i, tmpl in enumerate(self.per_release_tickets):
            _collect_template_vars_in_fields(
                tmpl.fields, f"per_release_tickets[{i}]"
            )
        for i, tmpl in enumerate(self.per_sprint_tickets):
            _collect_template_vars_in_fields(
                tmpl.fields, f"per_sprint_tickets[{i}]"
            )
        return self

    def get_epic_keys(self) -> list[str]:
        """Return the list of all epic reference keys (recurring + existing)."""
        return [e.key for e in self.recurring_epics] + list(self.existing_epics.keys())


def load_team_config(path: str | Path) -> tuple[TeamConfig, object]:
    """Load and validate a team config; return ``(model, tagged_raw)``.

    NOTE (Phase 02-02): the team-defaults → template merge is NOT performed
    here anymore. Callers MUST invoke ``merge_configs(org, team, ...)``
    (see ``jiramator.config_merge``) to obtain a merged ``TeamConfig`` whose
    template ``fields`` carry the inherited org/team-default values. Loading
    without merging yields a ``TeamConfig`` whose template ``fields`` reflect
    the raw YAML — no inheritance applied.

    Args:
        path: Path to the team-config YAML file.

    Returns:
        ``(model, tagged_raw)`` — the validated ``TeamConfig`` and the
        line-tagged YAML tree (consumed by ``merge_configs`` for
        conflict-warning line resolution).

    Raises:
        ConfigValidationError: For missing files, parse errors,
            non-mapping roots, and Pydantic validation failures (with
            file:line pinpointing and did-you-mean suggestions for
            typo'd template variables).
    """
    path = Path(path)
    clean, tagged = _load_yaml_with_lines(path, kind="Team")
    try:
        return TeamConfig(**clean), tagged
    except ValidationError as exc:
        raise _wrap_validation_error(
            exc, file=path, tagged_raw=tagged, root_model=TeamConfig
        ) from exc
