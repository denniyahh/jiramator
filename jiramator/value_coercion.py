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
}


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


def coerce_field_value(field_name: str, raw_value: Any, config: BulkCreateConfig) -> Any:
    """Coerce a raw logical value into the Jira REST payload shape for a field."""
    field_type = config.field_types.get(field_name, _BUILTIN_FIELD_TYPES.get(field_name))

    if field_type == "name_object":
        return {"name": str(raw_value).strip()}

    if field_type == "name_object_array":
        values = split_multi_value(raw_value, config)
        return [{"name": item} for item in values]

    if field_type == "labels":
        return split_multi_value(raw_value, config)

    if field_type == "single_select":
        cleaned = str(raw_value).strip()
        return {"value": cleaned}

    if field_type == "multi_select":
        values = split_multi_value(raw_value, config)
        return [{"value": item} for item in values]

    return raw_value
