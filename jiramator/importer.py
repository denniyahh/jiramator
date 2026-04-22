"""Pure spreadsheet-row to Jira-payload transformation for bulk import workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jiramator.config import OrgConfig, TeamConfig
from jiramator.field_resolver import ResolvedField, resolve_field_name
from jiramator.value_coercion import coerce_field_value, should_omit_value


@dataclass(frozen=True)
class RowBuildResult:
    """Pure result of transforming one source row into a Jira payload."""

    row_number: int
    summary: str
    success: bool
    payload: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    resolved_columns: dict[str, ResolvedField] = field(default_factory=dict)


@dataclass(frozen=True)
class PreviewReport:
    """Aggregate dry-run view across many row builds."""

    total_rows: int
    successful_rows: int
    failed_rows: int
    mapped_columns: dict[str, str]
    auto_mapped_columns: dict[str, str]
    skipped_columns: list[str]
    row_results: list[RowBuildResult]


_DIRECT_FIELDS = {"summary", "description"}


def _build_resolved_value(
    source_header: str,
    raw_value: Any,
    org_config: OrgConfig,
    *,
    jira_fields: list[dict[str, Any]] | None = None,
) -> tuple[ResolvedField, Any]:
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


def _apply_defaults(
    fields: dict[str, Any],
    org_config: OrgConfig,
) -> None:
    for logical_name, raw_value in org_config.bulk_create.defaults.items():
        resolved = resolve_field_name(logical_name, org_config)
        jira_field = resolved.jira_field
        if jira_field is None or jira_field in fields:
            continue
        coerced = coerce_field_value(logical_name, raw_value, org_config.bulk_create)
        if not should_omit_value(coerced):
            fields[jira_field] = coerced


def build_row_payload(
    row: dict[str, Any],
    *,
    row_number: int,
    org_config: OrgConfig,
    team_config: TeamConfig,
    jira_fields: list[dict[str, Any]] | None = None,
) -> RowBuildResult:
    """Transform a single source row into a Jira {fields: ...} payload."""
    fields: dict[str, Any] = {
        "project": {"key": team_config.project_key},
    }
    warnings: list[str] = []
    resolved_columns: dict[str, ResolvedField] = {}

    for source_header, raw_value in row.items():
        if raw_value is None or raw_value == "":
            continue

        resolved, coerced = _build_resolved_value(
            source_header,
            raw_value,
            org_config,
            jira_fields=jira_fields,
        )
        resolved_columns[source_header] = resolved

        if resolved.jira_field is None:
            warnings.append(f"Row {row_number}: skipped unresolved column '{source_header}'")
            continue

        if resolved.jira_field == "assignee" and not isinstance(coerced, dict):
            warnings.append(
                f"Row {row_number}: skipped unsupported assignee value for column '{source_header}'; expected a Jira user object"
            )
            continue

        if should_omit_value(coerced):
            continue

        if resolved.jira_field in _DIRECT_FIELDS:
            fields[resolved.jira_field] = str(raw_value).strip()
        else:
            fields[resolved.jira_field] = coerced

    _apply_defaults(fields, org_config)

    summary = str(fields.get("summary", "")).strip()
    if not summary:
        return RowBuildResult(
            row_number=row_number,
            summary="<missing summary>",
            success=False,
            payload=None,
            warnings=warnings,
            error=f"Row {row_number}: required field 'summary' is missing or empty",
            resolved_columns=resolved_columns,
        )

    return RowBuildResult(
        row_number=row_number,
        summary=summary,
        success=True,
        payload={"fields": fields},
        warnings=warnings,
        error=None,
        resolved_columns=resolved_columns,
    )


def build_preview_report(
    rows: list[dict[str, Any]],
    *,
    org_config: OrgConfig,
    team_config: TeamConfig,
    jira_fields: list[dict[str, Any]] | None = None,
) -> PreviewReport:
    """Build row payloads in dry-run mode and summarize mapping behavior."""
    row_results: list[RowBuildResult] = []
    mapped_columns: dict[str, str] = {}
    auto_mapped_columns: dict[str, str] = {}
    skipped_columns: set[str] = set()

    for index, row in enumerate(rows, start=1):
        result = build_row_payload(
            row,
            row_number=index,
            org_config=org_config,
            team_config=team_config,
            jira_fields=jira_fields,
        )
        row_results.append(result)

        for source_header, resolved in result.resolved_columns.items():
            if resolved.jira_field is None:
                skipped_columns.add(source_header)
            elif resolved.resolution_source in {"alias", "alias_normalized", "direct"}:
                mapped_columns.setdefault(source_header, resolved.jira_field)
            elif resolved.resolution_source.startswith("jira_"):
                auto_mapped_columns.setdefault(source_header, resolved.jira_field)

        for warning in result.warnings:
            if "skipped unresolved column '" in warning:
                skipped_columns.add(warning.split("skipped unresolved column '", 1)[1][:-1])

    successful_rows = sum(1 for result in row_results if result.success)
    failed_rows = len(row_results) - successful_rows

    return PreviewReport(
        total_rows=len(rows),
        successful_rows=successful_rows,
        failed_rows=failed_rows,
        mapped_columns=mapped_columns,
        auto_mapped_columns=auto_mapped_columns,
        skipped_columns=sorted(skipped_columns),
        row_results=row_results,
    )
