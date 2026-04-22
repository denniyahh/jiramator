"""Shared field resolution for bulk-create workflows.

Resolves source-facing field names (YAML logical names, spreadsheet headers)
into final Jira field names/IDs using org config aliases, custom field mappings,
and optional Jira field metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jiramator.config import OrgConfig


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


def _jira_field_lookup(source_name: str, jira_fields: list[dict[str, Any]]) -> tuple[str, str, str] | None:
    for field in jira_fields:
        if field.get("name") == source_name:
            field_id = field.get("id")
            if isinstance(field_id, str):
                return source_name, field_id, "jira_exact"

    normalized_source = normalize_field_name(source_name)
    for field in jira_fields:
        field_name = field.get("name")
        field_id = field.get("id")
        if isinstance(field_name, str) and isinstance(field_id, str):
            if normalize_field_name(field_name) == normalized_source:
                return normalized_source, field_id, "jira_normalized"

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
        jira_match = _jira_field_lookup(source_name, jira_fields)
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
