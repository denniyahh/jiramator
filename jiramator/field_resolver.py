"""Shared field resolution for bulk-create and bulk-update workflows.

Resolves source-facing field names (YAML logical names, spreadsheet headers)
into final Jira field names/IDs using org config aliases, custom field mappings,
and optional Jira field metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jiramator.config import OrgConfig
from jiramator.value_coercion import coerce_field_value


@dataclass(frozen=True)
class ResolvedField:
    """Result of resolving a source-facing field name to a Jira field."""

    source_name: str
    logical_name: str
    jira_field: str | None
    resolution_source: str


def normalize_field_name(name: str) -> str:
    """Normalize a field/header name conservatively for matching.

    Rules:
    - strip leading/trailing whitespace
    - collapse internal whitespace
    - lowercase
    """
    return " ".join(name.strip().split()).lower()


def _alias_lookup(source_name: str, org_config: OrgConfig) -> tuple[str, str] | None:
    aliases = org_config.bulk_create.field_aliases
    if source_name in aliases:
        return aliases[source_name], "alias"

    normalized_source = normalize_field_name(source_name)
    for alias_name, logical_name in aliases.items():
        if normalize_field_name(alias_name) == normalized_source:
            return logical_name, "alias_normalized"

    return None


def _resolve_logical_to_jira_field(logical_name: str, org_config: OrgConfig) -> str:
    try:
        return org_config.get_custom_field_id(logical_name)
    except KeyError:
        return logical_name


def _jira_field_lookup(
    source_name: str,
    jira_fields: list[dict[str, Any]],
    org_config: OrgConfig,
) -> tuple[str, str, str] | None:
    custom_field_reverse = {jira_id: logical_name for logical_name, jira_id in org_config.custom_fields.items()}

    for field in jira_fields:
        if field.get("name") == source_name:
            field_id = field.get("id")
            if isinstance(field_id, str):
                logical_name = custom_field_reverse.get(field_id, source_name)
                return logical_name, field_id, "jira_exact"

    normalized_source = normalize_field_name(source_name)
    for field in jira_fields:
        field_name = field.get("name")
        field_id = field.get("id")
        if isinstance(field_name, str) and isinstance(field_id, str):
            if normalize_field_name(field_name) == normalized_source:
                logical_name = custom_field_reverse.get(field_id, normalized_source)
                return logical_name, field_id, "jira_normalized"

    return None


def resolve_field_name(
    source_name: str,
    org_config: OrgConfig,
    *,
    jira_fields: list[dict[str, Any]] | None = None,
) -> ResolvedField:
    """Resolve a source-facing field name to a final Jira field name/ID."""
    aliases = org_config.bulk_create.field_aliases
    if source_name in aliases:
        logical_name = aliases[source_name]
        return ResolvedField(
            source_name=source_name,
            logical_name=logical_name,
            jira_field=_resolve_logical_to_jira_field(logical_name, org_config),
            resolution_source="alias",
        )

    if source_name.startswith("customfield_"):
        return ResolvedField(
            source_name=source_name,
            logical_name=source_name,
            jira_field=source_name,
            resolution_source="direct",
        )

    if source_name in org_config.custom_fields:
        return ResolvedField(
            source_name=source_name,
            logical_name=source_name,
            jira_field=org_config.custom_fields[source_name],
            resolution_source="direct",
        )

    standard_fields = {"summary", "description", "issuetype", "priority", "labels", "fixVersions", "components", "assignee"}
    if source_name in standard_fields:
        return ResolvedField(
            source_name=source_name,
            logical_name=source_name,
            jira_field=source_name,
            resolution_source="direct",
        )

    normalized_alias_match = _alias_lookup(source_name, org_config)
    if normalized_alias_match is not None:
        logical_name, resolution_source = normalized_alias_match
        return ResolvedField(
            source_name=source_name,
            logical_name=logical_name,
            jira_field=_resolve_logical_to_jira_field(logical_name, org_config),
            resolution_source=resolution_source,
        )

    if jira_fields:
        jira_match = _jira_field_lookup(source_name, jira_fields, org_config)
        if jira_match is not None:
            logical_name, jira_field, resolution_source = jira_match
            return ResolvedField(
                source_name=source_name,
                logical_name=logical_name,
                jira_field=jira_field,
                resolution_source=resolution_source,
            )

    return ResolvedField(
        source_name=source_name,
        logical_name=source_name,
        jira_field=None,
        resolution_source="unresolved",
    )


def resolve_fields_map(
    source_names: list[str],
    org_config: OrgConfig,
    *,
    jira_fields: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, ResolvedField], list[str]]:
    """Resolve multiple source-facing field names and collect unresolved ones."""
    resolved: dict[str, ResolvedField] = {}
    unresolved: list[str] = []

    for source_name in source_names:
        result = resolve_field_name(source_name, org_config, jira_fields=jira_fields)
        resolved[source_name] = result
        if result.jira_field is None:
            unresolved.append(source_name)

    return resolved, unresolved


def build_and_coerce_field_value(
    source_header: str,
    raw_value: Any,
    org_config: OrgConfig,
    *,
    jira_fields: list[dict[str, Any]] | None = None,
) -> tuple[ResolvedField, Any]:
    """Resolve a source header to a Jira field and coerce its value.

    Used by both the import (create) and update flows to avoid duplicating
    field resolution + coercion logic.

    Args:
        source_header: Column name from the spreadsheet or YAML template.
        raw_value: Raw cell value (string, number, etc.).
        org_config: Org config providing aliases, custom field IDs, and
            bulk_create settings (field_types, auto_lookup_unknown_fields).
        jira_fields: Optional live Jira field metadata for auto-resolution.

    Returns:
        A (ResolvedField, coerced_value) tuple.  ``coerced_value`` is None
        when the field could not be resolved.
    """
    effective_jira_fields = jira_fields if org_config.bulk_create.auto_lookup_unknown_fields else None
    resolved = resolve_field_name(source_header, org_config, jira_fields=effective_jira_fields)
    if resolved.jira_field is None:
        return resolved, None

    if resolved.logical_name in org_config.bulk_create.field_types:
        coercion_key = resolved.logical_name
    else:
        coercion_key = resolved.jira_field

    coerced = coerce_field_value(coercion_key, raw_value, org_config.bulk_create)
    return resolved, coerced
