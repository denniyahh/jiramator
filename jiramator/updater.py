"""Pure spreadsheet-row to Jira-payload transformation for bulk update workflows.

Unlike the import flow (which creates new issues), the update flow requires
a key column identifying existing issues and updates only the fields present
in the spreadsheet row.  Blank cells mean "no change" — they are omitted from
the payload and will NOT clear the existing Jira field value.

Design decisions:
  - ``bulk_create.defaults`` from org config are intentionally NOT applied.
    Defaults exist to fill required fields on creation (e.g. issuetype=Risk);
    applying them during updates would overwrite user-set values.
  - Rows with no resolvable update fields are skipped (not failed), since the
    spreadsheet may contain informational columns alongside Jira fields.
  - Duplicate issue keys are rejected before any live updates, since multiple
    rows for the same Jira issue make overwrite order ambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from jiramator.config import OrgConfig
from jiramator.field_resolver import ResolvedField, build_and_coerce_field_value
from jiramator.jira_client import JiraApiError, JiraClient
from jiramator.value_coercion import should_omit_value


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RowUpdateResult:
    """Pure result of transforming one source row into a Jira update payload."""

    row_number: int
    issue_key: str
    success: bool
    payload: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    resolved_columns: dict[str, ResolvedField] = field(default_factory=dict)


@dataclass(frozen=True)
class UpdatePreviewReport:
    """Aggregate dry-run view across many row builds."""

    total_rows: int
    no_op_rows: int
    failed_rows: int
    mapped_columns: dict[str, str]
    auto_mapped_columns: dict[str, str]
    skipped_columns: list[str]
    row_results: list[RowUpdateResult]


@dataclass(frozen=True)
class UpdateRunResult:
    """Outcome of executing or previewing an update run."""

    preview: UpdatePreviewReport
    updated: list[tuple[int, str]]       # (row_number, issue_key)
    skipped: list[tuple[int, str, str]]  # (row_number, issue_key, reason)
    failed: list[tuple[int, str, str]]   # (row_number, issue_key, error)


# ---------------------------------------------------------------------------
# Row payload builder
# ---------------------------------------------------------------------------


def _is_blank_update_value(value: Any) -> bool:
    """Return True when a spreadsheet cell means "leave existing Jira value unchanged"."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def validate_unique_issue_keys(rows: list[dict[str, Any]], *, key_column: str) -> None:
    """Validate that every non-blank issue key appears at most once.

    Args:
        rows: Spreadsheet rows from ``read_spreadsheet``.
        key_column: Header name that holds the Jira issue key.

    Raises:
        ValueError: If the key column is missing or any non-blank issue key
            appears on more than one row.
    """
    if rows and key_column not in rows[0]:
        raise ValueError(
            f"Key column '{key_column}' not found in spreadsheet. "
            f"Available columns: {', '.join(rows[0])}"
        )

    rows_by_key: dict[str, list[int]] = {}
    for index, row in enumerate(rows, start=1):
        issue_key = str(row.get(key_column, "")).strip()
        if not issue_key:
            continue
        rows_by_key.setdefault(issue_key, []).append(index)

    duplicate_parts = [
        f"{issue_key} appears on rows {', '.join(str(row_num) for row_num in row_numbers)}"
        for issue_key, row_numbers in rows_by_key.items()
        if len(row_numbers) > 1
    ]
    if duplicate_parts:
        raise ValueError(
            "Duplicate Jira keys found. Each issue key may appear only once. "
            + "; ".join(duplicate_parts)
        )


def build_row_update_payload(
    row: dict[str, Any],
    *,
    row_number: int,
    key_column: str,
    org_config: OrgConfig,
    jira_fields: list[dict[str, Any]] | None = None,
) -> RowUpdateResult:
    """Transform a single source row into a Jira {fields: ...} update payload.

    Args:
        row: Dict of column header → cell value for one spreadsheet row.
        row_number: 1-based row index used in diagnostic messages.
        key_column: The header name whose value is the Jira issue key.
        org_config: Org config for field resolution and coercion.
        jira_fields: Optional live Jira field metadata for auto-resolution.

    Returns:
        A RowUpdateResult.  ``success=False`` when the issue key is missing;
        ``payload=None`` (with ``success=True``) when the row has no fields
        to update (treated as a no-op skip by ``run_update``).
    """
    issue_key = str(row.get(key_column, "")).strip()
    if not issue_key:
        return RowUpdateResult(
            row_number=row_number,
            issue_key="",
            success=False,
            payload=None,
            error=f"Row {row_number}: missing or empty key column '{key_column}'",
        )

    fields: dict[str, Any] = {}
    warnings: list[str] = []
    resolved_columns: dict[str, ResolvedField] = {}

    for source_header, raw_value in row.items():
        if source_header == key_column:
            continue
        if _is_blank_update_value(raw_value):
            continue

        resolved, coerced = build_and_coerce_field_value(
            source_header,
            raw_value,
            org_config,
            jira_fields=jira_fields,
        )
        resolved_columns[source_header] = resolved

        if resolved.jira_field is None:
            warnings.append(
                f"Row {row_number}: skipped unresolved column '{source_header}'"
            )
            continue

        if should_omit_value(coerced):
            continue

        fields[resolved.jira_field] = coerced

    if not fields:
        return RowUpdateResult(
            row_number=row_number,
            issue_key=issue_key,
            success=True,
            payload=None,  # no-op: caller will skip
            warnings=warnings,
            resolved_columns=resolved_columns,
        )

    return RowUpdateResult(
        row_number=row_number,
        issue_key=issue_key,
        success=True,
        payload={"fields": fields},
        warnings=warnings,
        resolved_columns=resolved_columns,
    )


# ---------------------------------------------------------------------------
# Preview report builder
# ---------------------------------------------------------------------------


def build_update_preview_report(
    rows: list[dict[str, Any]],
    *,
    key_column: str,
    org_config: OrgConfig,
    jira_fields: list[dict[str, Any]] | None = None,
) -> UpdatePreviewReport:
    """Build row payloads in dry-run mode and summarise mapping behaviour.

    Args:
        rows: Spreadsheet rows from ``read_spreadsheet``.
        key_column: Header name that holds the Jira issue key.
        org_config: Org config for field resolution and coercion.
        jira_fields: Optional live Jira field metadata.

    Returns:
        An ``UpdatePreviewReport`` summarising mapping and row results.

    Raises:
        ValueError: If ``key_column`` is not present in any row.
    """
    validate_unique_issue_keys(rows, key_column=key_column)

    row_results: list[RowUpdateResult] = []
    mapped_columns: dict[str, str] = {}
    auto_mapped_columns: dict[str, str] = {}
    skipped_columns: set[str] = set()

    for index, row in enumerate(rows, start=1):
        issue_key_raw = str(row.get(key_column, "")).strip()
        try:
            result = build_row_update_payload(
                row,
                row_number=index,
                key_column=key_column,
                org_config=org_config,
                jira_fields=jira_fields,
            )
        except (TypeError, ValueError) as exc:
            result = RowUpdateResult(
                row_number=index,
                issue_key=issue_key_raw,
                success=False,
                payload=None,
                error=f"Row {index}: could not build update payload: {exc}",
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

    no_op_rows = sum(
        1 for r in row_results if r.success and r.payload is None
    )
    failed_rows = sum(1 for r in row_results if not r.success)

    return UpdatePreviewReport(
        total_rows=len(rows),
        no_op_rows=no_op_rows,
        failed_rows=failed_rows,
        mapped_columns=mapped_columns,
        auto_mapped_columns=auto_mapped_columns,
        skipped_columns=sorted(skipped_columns),
        row_results=row_results,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_update(
    rows: list[dict[str, Any]],
    *,
    key_column: str,
    org_config: OrgConfig,
    jira_fields: list[dict[str, Any]] | None,
    client: JiraClient | None,
    dry_run: bool = False,
) -> UpdateRunResult:
    """Execute a row-by-row bulk update, or just preview it in dry-run mode.

    Args:
        rows: Spreadsheet rows from ``read_spreadsheet``.
        key_column: Header name that holds the Jira issue key.
        org_config: Org config for field resolution and coercion.
        jira_fields: Optional live Jira field metadata.
        client: Jira client (required unless ``dry_run=True``).
        dry_run: If True, build payloads but make no API calls.

    Returns:
        An ``UpdateRunResult`` with the preview and per-row outcomes.

    Raises:
        ValueError: If ``key_column`` is missing or ``client`` is None for
            a live run.
    """
    preview = build_update_preview_report(
        rows,
        key_column=key_column,
        org_config=org_config,
        jira_fields=jira_fields,
    )

    if dry_run:
        return UpdateRunResult(preview=preview, updated=[], skipped=[], failed=[])

    if client is None:
        raise ValueError("client is required for live updates")

    updated: list[tuple[int, str]] = []
    skipped: list[tuple[int, str, str]] = []
    failed: list[tuple[int, str, str]] = []

    for result in preview.row_results:
        if not result.success:
            err = result.error or "Unknown row error"
            failed.append((result.row_number, result.issue_key, err))
            continue

        if result.payload is None:
            skipped.append((result.row_number, result.issue_key, "no fields to update"))
            continue

        try:
            client.update_issue(result.issue_key, result.payload)
        except JiraApiError as exc:
            failed.append((result.row_number, result.issue_key, str(exc)))
            continue

        updated.append((result.row_number, result.issue_key))

    return UpdateRunResult(preview=preview, updated=updated, skipped=skipped, failed=failed)


# ---------------------------------------------------------------------------
# Report renderers
# ---------------------------------------------------------------------------


def render_update_preview_report(report: UpdatePreviewReport, *, preview_rows: int = 5) -> str:
    """Render a plain-text preview report for CLI output."""
    lines = [
        "Update preview",
        (
            f"total_rows={report.total_rows} "
            f"no_op={report.no_op_rows} "
            f"failed={report.failed_rows}"
        ),
    ]

    if report.mapped_columns:
        mapped = ", ".join(
            f"{src}->{dst}" for src, dst in sorted(report.mapped_columns.items())
        )
        lines.append(f"mapped_columns: {mapped}")
    if report.auto_mapped_columns:
        auto_mapped = ", ".join(
            f"{src}->{dst}" for src, dst in sorted(report.auto_mapped_columns.items())
        )
        lines.append(f"auto_mapped_columns: {auto_mapped}")
    if report.skipped_columns:
        lines.append(f"skipped_columns: {', '.join(report.skipped_columns)}")

    for row in report.row_results[:preview_rows]:
        if not row.success:
            lines.append(f"Row {row.row_number} ({row.issue_key}): ERROR {row.error}")
        elif row.payload is None:
            lines.append(f"Row {row.row_number} ({row.issue_key}): no-op (no fields to update)")
        else:
            field_count = len(row.payload.get("fields", {}))
            lines.append(f"Row {row.row_number} ({row.issue_key}): {field_count} field(s) to update")
        for warning in row.warnings:
            lines.append(f"  warning: {warning}")

    return "\n".join(lines)


def render_update_execution_report(result: UpdateRunResult) -> str:
    """Render a plain-text execution summary for CLI output."""
    lines = [
        "Update execution summary",
        f"updated={len(result.updated)} skipped={len(result.skipped)} failed={len(result.failed)}",
    ]

    for row_number, issue_key in result.updated:
        lines.append(f"Row {row_number}: updated {issue_key}")
    for row_number, issue_key, reason in result.skipped:
        lines.append(f"Row {row_number} ({issue_key}): skipped — {reason}")
    for row_number, issue_key, error in result.failed:
        lines.append(f"Row {row_number} ({issue_key}): failed — {error}")

    return "\n".join(lines)
