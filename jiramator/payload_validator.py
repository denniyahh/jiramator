"""Validates built ticket payloads against Jira's live field schema.

This module is pure data checking — no I/O, no API calls. It takes a
``fields`` payload (as built by ``ticket_builder.py``) and a field-metadata
dict (as fetched by ``JiraClient.get_createmeta_fields_by_type_name()``) and
reports mismatches: missing required fields, plain strings where Jira expects
Atlassian Document Format (ADF), and values that don't match a select field's
allowed options.

Fetching the metadata is the client's job; calling this from both ``plan``'s
dry-run and live-run is the planner's job (see ``planner._preflight_validate``).
"""

from __future__ import annotations

from typing import Any

# Fields the builder always injects itself (project, summary) or that Jira
# computes/derives and never expects the caller to check against createmeta.
_SKIP_FIELD_IDS = frozenset({"project"})


def _is_textarea_or_richtext(field_id: str, schema: dict[str, Any]) -> bool:
    """Return whether a createmeta field schema is a rich-text/ADF field.

    Jira Cloud's REST v3 API always expects ADF for the built-in
    ``description`` field (its createmeta ``schema.type`` is reported as
    plain ``"string"``, which is misleading) and for any custom "Paragraph"
    (multi-line text / textarea) field — mirrors the same detection already
    used in ``ticket_builder.WRAPPED_FIELDS``/``_adf_custom_field_ids``.
    """
    if field_id == "description" or schema.get("system") == "description":
        return True
    custom_type = schema.get("custom") or ""
    return "textarea" in custom_type or schema.get("type") == "richtext"


def _looks_like_adf(value: Any) -> bool:
    """Return whether a value already looks like an ADF document dict."""
    return isinstance(value, dict) and value.get("type") == "doc"


def _allowed_value_tokens(allowed_values: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    """Split a createmeta ``allowedValues`` list into (names, ids) sets."""
    names = set()
    ids = set()
    for entry in allowed_values:
        if not isinstance(entry, dict):
            continue
        name = entry.get("value") or entry.get("name")
        if name is not None:
            names.add(str(name))
        entry_id = entry.get("id")
        if entry_id is not None:
            ids.add(str(entry_id))
    return names, ids


def _check_option_value(
    value: Any, names: set[str], ids: set[str], field_label: str
) -> str | None:
    """Check one option-style value against a field's allowed values.

    Returns a problem message, or ``None`` if the value is acceptable.
    """
    if isinstance(value, dict):
        candidate = value.get("value") or value.get("name")
        candidate_id = value.get("id")
        if candidate_id is not None and str(candidate_id) in ids:
            return None
        if candidate is not None and str(candidate) in names:
            return None
        return (
            f"{field_label}: value {value!r} is not one of the allowed options"
        )
    if isinstance(value, str):
        if value in names:
            return None
        return (
            f"{field_label}: value {value!r} is not one of the allowed options "
            f"({', '.join(sorted(names)) or 'none configured'})"
        )
    return None  # unrecognized shape — not our job to second-guess it


def validate_ticket_payload(
    fields: dict[str, Any],
    field_metadata: dict[str, dict[str, Any]],
) -> list[str]:
    """Check one built ticket's ``fields`` payload against Jira's createmeta schema.

    Args:
        fields: The resolved ``fields`` dict as built by ``ticket_builder.py``
            (already wrapped — e.g. ``{"name": "Task"}`` for issuetype).
        field_metadata: Jira field id -> createmeta field descriptor, as
            returned by ``JiraClient.get_createmeta_fields_by_type_name()``.
            Each descriptor may include ``required``, ``hasDefaultValue``,
            ``schema`` (with ``type``/``custom``), and ``allowedValues``.

    Returns:
        Human-readable problem descriptions. Empty list means no problems
        were found (note: this is best-effort — it can't catch everything
        Jira might reject, only the common cases: missing required fields,
        ADF-vs-plain-string mismatches, and invalid select-field values).
    """
    problems: list[str] = []

    # 1. Missing required fields (that Jira won't auto-default).
    for field_id, meta in field_metadata.items():
        if field_id in _SKIP_FIELD_IDS:
            continue
        if not meta.get("required"):
            continue
        if meta.get("hasDefaultValue"):
            continue
        if field_id not in fields or fields[field_id] in (None, "", [], {}):
            label = meta.get("name", field_id)
            problems.append(f"missing required field {label!r} ({field_id})")

    # 2. Type/value checks for every field we're actually sending.
    for field_id, value in fields.items():
        if field_id in _SKIP_FIELD_IDS:
            continue
        meta = field_metadata.get(field_id)
        if meta is None:
            continue  # Not on this issue type's create screen — not our call.

        label = f"{meta.get('name', field_id)!r} ({field_id})"
        schema = meta.get("schema", {})
        if _is_textarea_or_richtext(field_id, schema) and not _looks_like_adf(value):
            problems.append(
                f"{label} requires Atlassian Document Format (ADF) content, "
                f"got {type(value).__name__}"
            )

        allowed_values = meta.get("allowedValues")
        if allowed_values:
            names, ids = _allowed_value_tokens(allowed_values)
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                message = _check_option_value(candidate, names, ids, label)
                if message:
                    problems.append(message)

    return problems
