"""Shared Jira value coercion for bulk-create workflows."""

from __future__ import annotations

from typing import Any

from jiramator.config import BulkCreateConfig

_BUILTIN_FIELD_TYPES = {
    "issuetype": "name_object",
    "priority": "name_object",
    "fixVersions": "name_object_array",
    "components": "name_object_array",
    "labels": "labels",
    # Jira Cloud's REST API v3 requires `description` as Atlassian Document
    # Format (ADF), not a plain string — a bare string is rejected with
    # "The field value is not valid Atlassian Document Format (ADF) content."
    "description": "adf_text",
    # Jira rejects a summary containing line breaks ("The summary is invalid
    # because it contains newline characters."), which multi-line spreadsheet
    # cells routinely produce.
    "summary": "single_line",
    # Spreadsheet cells are read as strings ("2", "0.5"), but Jira rejects a
    # string for a number field ("Operation value must be a number"). This
    # covers offline previews; live runs also infer `number` from Jira's
    # field schema (see `resolve_field_type`).
    "story_points": "number",
}

# Jira field `schema.type` values (from /rest/api/3/field) mapped to the
# coercion type they require when no explicit/built-in type applies.
_SCHEMA_FIELD_TYPES = {
    "number": "number",
}


def has_builtin_field_type(field_name: str) -> bool:
    """Return whether jiramator ships a default coercion type for a field name."""
    return field_name in _BUILTIN_FIELD_TYPES


def resolve_field_type(
    field_name: str,
    config: BulkCreateConfig,
    *,
    jira_schema: dict[str, Any] | None = None,
) -> str | None:
    """Determine the coercion type for a field.

    Precedence: org ``field_types`` > built-in defaults > live Jira schema.

    Args:
        field_name: Logical name or Jira field ID used as the coercion key.
        config: Bulk-create config holding explicit ``field_types``.
        jira_schema: Optional ``schema`` dict for the field from Jira's
            ``/rest/api/3/field`` metadata.

    Returns:
        The coercion type name, or None to pass the value through unchanged.
    """
    explicit = config.field_types.get(field_name)
    if explicit:
        return explicit
    builtin = _BUILTIN_FIELD_TYPES.get(field_name)
    if builtin:
        return builtin
    if jira_schema:
        return _SCHEMA_FIELD_TYPES.get(jira_schema.get("type"))
    return None


def to_single_line(value: Any) -> str:
    """Join a possibly multi-line value into one line, dropping blank lines."""
    lines = (line.strip() for line in str(value).splitlines())
    return " ".join(line for line in lines if line)


def split_multi_value(value: Any, config: BulkCreateConfig) -> list[str]:
    """Split scalar/list inputs into a cleaned list of string values."""
    if value is None:
        return []

    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(config.multi_value_delimiter)

    result: list[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned:
            result.append(cleaned)
    return result


def should_omit_value(value: Any) -> bool:
    """Return True when a field value should be omitted from the payload."""
    return value is None or value == "" or value == []


def _adf_paragraph(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _resolve_value_alias(field_name: str, value: str, config: BulkCreateConfig) -> str:
    """Translate a shorthand value to its exact Jira option label, if aliased.

    Looks up ``config.value_aliases[field_name]``. Values with no matching
    alias entry pass through unchanged — this is additive and never breaks
    a field that already sends exact Jira option strings.
    """
    aliases = config.value_aliases.get(field_name, {})
    return aliases.get(value, value)


def coerce_field_value(
    field_name: str,
    raw_value: Any,
    config: BulkCreateConfig,
    *,
    jira_schema: dict[str, Any] | None = None,
) -> Any:
    """Coerce a raw logical value into the Jira REST payload shape for a field.

    Args:
        field_name: Logical name or Jira field ID used as the coercion key.
        raw_value: Raw value (typically a spreadsheet cell string).
        config: Bulk-create config holding ``field_types`` and aliases.
        jira_schema: Optional live Jira ``schema`` dict for the field, used to
            infer a type (e.g. ``number``) when none is configured.

    Returns:
        The value shaped for the Jira REST payload.
    """
    field_type = resolve_field_type(field_name, config, jira_schema=jira_schema)

    if field_type == "name_object":
        return {"name": str(raw_value).strip()}

    if field_type == "name_object_array":
        values = split_multi_value(raw_value, config)
        return [{"name": item} for item in values]

    if field_type == "labels":
        return split_multi_value(raw_value, config)

    if field_type == "single_select":
        cleaned = str(raw_value).strip()
        cleaned = _resolve_value_alias(field_name, cleaned, config)
        return {"value": cleaned}

    if field_type == "multi_select":
        values = split_multi_value(raw_value, config)
        values = [_resolve_value_alias(field_name, item, config) for item in values]
        return [{"value": item} for item in values]

    if field_type == "single_line":
        return to_single_line(raw_value)

    if field_type == "adf_text":
        return _adf_paragraph(str(raw_value).strip())

    if field_type == "number":
        cleaned = str(raw_value).strip()
        number = float(cleaned)
        return int(number) if number.is_integer() else number

    return raw_value
