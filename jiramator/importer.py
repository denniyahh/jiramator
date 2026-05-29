"""Pure spreadsheet-row to Jira-payload transformation for bulk import workflows."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jiramator.config import OrgConfig, TeamConfig
from jiramator.field_resolver import ResolvedField, build_and_coerce_field_value, resolve_field_name
from jiramator.jira_client import JiraApiError, JiraClient
from jiramator.run_report import IssueResult, RunReport, write_report_atomic
from jiramator.value_coercion import coerce_field_value, should_omit_value


# ---------------------------------------------------------------------------
# Phase 02-02 scope note — Template inheritance does NOT apply to imports.
#
# Org ``default_fields`` (locked, org-wide — see jiramator/config.py:OrgConfig)
# is consumed by the ``plan`` command via jiramator.config_merge.merge_configs.
# The ``import`` command does NOT call merge_configs and does NOT apply
# ``default_fields`` to row payloads. The existing ``bulk_create.defaults``
# (gap-fill semantics, applied below in ``_apply_defaults``) is unchanged.
#
# Rationale: Phase 2 ships team-internal ``defaults:`` (highest user value),
# org ``default_fields`` (cross-team locking for ``plan`` runs), and sprint-mode
# config (orthogonal). Importer parity for ``default_fields`` requires
# threading a Console through ``build_row_payload`` and is deferred to a
# follow-up phase to keep Phase 2 scope bounded. See:
#   .planning/phases/02-template-inheritance-sprint-assignment/02-PATTERNS.md §11
# ---------------------------------------------------------------------------


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


@dataclass(frozen=True)
class ImportRunResult:
    """Outcome of executing or previewing an import run."""

    preview: PreviewReport
    created: list[tuple[int, str, str]]
    skipped: list[tuple[int, str, str]]
    failed: list[tuple[int, str, str]]


_DIRECT_FIELDS = {"summary", "description"}
_DEFERRED_FIELDS = {"reporter"}


def _build_resolved_value(
    source_header: str,
    raw_value: Any,
    org_config: OrgConfig,
    *,
    jira_fields: list[dict[str, Any]] | None = None,
) -> tuple[ResolvedField, Any]:
    return build_and_coerce_field_value(
        source_header, raw_value, org_config, jira_fields=jira_fields,
    )


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

        if resolved.jira_field in _DEFERRED_FIELDS:
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


def _row_template_key(row_number: int, summary: str) -> str:
    """Return the deterministic template_key for an imported row.

    Shape: ``imported:row<N>:<8-char-sha256-prefix-of-summary>``.

    Why include both row_number and summary-hash:
      - row_number alone breaks when the user reorders rows in the spreadsheet.
      - summary alone collides when two rows share an identical summary (legal
        in CSV though discouraged).
      - Combining them: reordering invalidates resume for those rows (they get
        re-attempted, where Jira's existing-summary dedup catches duplicates),
        AND duplicate-summary rows are still distinguished by row_number. This
        is the conservative choice — see Plan 01-04 §Task 3 behavior notes.
    """
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:8]
    return f"imported:row{row_number}:{digest}"


def run_import(
    rows: list[dict[str, Any]],
    *,
    org_config: OrgConfig,
    team_config: TeamConfig,
    jira_fields: list[dict[str, Any]] | None,
    client: JiraClient | None,
    dry_run: bool = False,
    report: RunReport | None = None,
    report_path: Path | None = None,
    prior_report: RunReport | None = None,
) -> ImportRunResult:
    """Execute a duplicate-safe row-by-row import, or just preview it in dry-run mode.

    Args:
        report: A RunReport that this function will append per-row results to
            and re-persist after every row. cli.py constructs this; legacy
            callers may pass None to skip report emission entirely.
        report_path: Where to write the report. Combined with ``report`` to
            enable per-row atomic persistence.
        prior_report: When provided, rows whose template_key appears with
            ``status="created"`` are skipped (their prior IssueResults are
            carried forward into ``report``). Failed/pending entries are
            re-attempted.
    """
    preview = build_preview_report(
        rows,
        org_config=org_config,
        team_config=team_config,
        jira_fields=jira_fields,
    )

    if dry_run:
        return ImportRunResult(preview=preview, created=[], skipped=[], failed=[])

    if client is None:
        raise ValueError("client is required for live imports")

    # ---- Resume skip-set + carry-forward of prior-created issues --------
    prior_created: dict[str, str] = {}
    if prior_report is not None:
        for issue in prior_report.issues:
            if (
                issue.kind == "imported"
                and issue.status == "created"
                and issue.jira_key
            ):
                prior_created[issue.template_key] = issue.jira_key
                if report is not None:
                    report.issues.append(
                        IssueResult(
                            template_key=issue.template_key,
                            kind="imported",
                            status="created",
                            jira_key=issue.jira_key,
                        )
                    )
                    report.counts["created"] = report.counts.get("created", 0) + 1

    def _persist() -> None:
        if report is not None and report_path is not None:
            write_report_atomic(report, report_path)

    def _record(tk: str, status: str, **kw: Any) -> None:
        if report is None:
            return
        report.issues.append(
            IssueResult(template_key=tk, kind="imported", status=status, **kw)  # type: ignore[arg-type]
        )
        report.counts[status] = report.counts.get(status, 0) + 1

    _persist()  # initial write reflecting prior-carry-forward

    successful_rows = [
        result for result in preview.row_results
        if result.success and result.payload
    ]
    seen_summaries = client.find_issue_keys_by_summaries(
        team_config.project_key,
        [result.summary for result in successful_rows],
    )

    created: list[tuple[int, str, str]] = []
    skipped: list[tuple[int, str, str]] = []
    failed: list[tuple[int, str, str]] = []

    source_rows_by_number = {index: row for index, row in enumerate(rows, start=1)}

    # Discover which source header(s) resolved to reporter, so we can look up
    # the value by the actual header name rather than hardcoding "Reporter".
    reporter_headers: set[str] = set()
    for row_result in preview.row_results:
        for source_header, resolved in row_result.resolved_columns.items():
            if resolved.jira_field == "reporter":
                reporter_headers.add(source_header)

    try:
        for result in preview.row_results:
            tk = _row_template_key(result.row_number, result.summary)

            # ---- Resume skip ------------------------------------------------
            if tk in prior_created:
                # Already recorded above via carry-forward; mirror into the
                # legacy ImportRunResult so callers see consistent state.
                created.append((result.row_number, result.summary, prior_created[tk]))
                continue

            # ---- Failed-build branch ---------------------------------------
            if not result.success or result.payload is None:
                err = result.error or "Unknown row error"
                failed.append((result.row_number, result.summary, err))
                _record(tk, "failed", error=err)
                _persist()
                continue

            # ---- Existing-in-Jira dedup branch -----------------------------
            existing_key = seen_summaries.get(result.summary)
            if existing_key:
                skipped.append((result.row_number, result.summary, existing_key))
                _record(tk, "skipped", jira_key=existing_key)
                _persist()
                continue

            # ---- Build send payload ----------------------------------------
            payload = {
                "fields": dict(result.payload["fields"]),
            }
            source_row = source_rows_by_number.get(result.row_number, {})
            for header in reporter_headers:
                reporter_value = source_row.get(header)
                if isinstance(reporter_value, str) and reporter_value.strip():
                    account_id = client.find_user_account_id(reporter_value)
                    if account_id:
                        payload["fields"]["reporter"] = {"accountId": account_id}
                    break

            # ---- Create -----------------------------------------------------
            try:
                created_key = client.create_issue(payload)
            except JiraApiError as exc:
                err = str(exc)
                failed.append((result.row_number, result.summary, err))
                _record(tk, "failed", error=err)
                _persist()
                continue

            seen_summaries[result.summary] = created_key
            created.append((result.row_number, result.summary, created_key))
            _record(tk, "created", jira_key=created_key)
            _persist()
    except BaseException:
        # Persist whatever we got before the exception (KeyboardInterrupt et al).
        _persist()
        raise

    return ImportRunResult(
        preview=preview,
        created=created,
        skipped=skipped,
        failed=failed,
    )


def render_preview_report(report: PreviewReport, *, preview_rows: int = 5) -> str:
    """Render a plain-text preview report for CLI output."""
    lines = [
        "Import preview",
        f"total_rows={report.total_rows} successful={report.successful_rows} failed={report.failed_rows}",
    ]

    if report.mapped_columns:
        mapped = ", ".join(f"{src}->{dst}" for src, dst in sorted(report.mapped_columns.items()))
        lines.append(f"mapped_columns: {mapped}")
    if report.auto_mapped_columns:
        auto_mapped = ", ".join(
            f"{src}->{dst}" for src, dst in sorted(report.auto_mapped_columns.items())
        )
        lines.append(f"auto_mapped_columns: {auto_mapped}")
    if report.skipped_columns:
        lines.append(f"skipped_columns: {', '.join(report.skipped_columns)}")

    for row in report.row_results[:preview_rows]:
        if row.success:
            lines.append(f"Row {row.row_number}: {row.summary}")
        else:
            lines.append(f"Row {row.row_number}: ERROR {row.error}")
        for warning in row.warnings:
            lines.append(f"  warning: {warning}")

    return "\n".join(lines)


def render_import_execution_report(result: ImportRunResult) -> str:
    """Render a plain-text execution summary for CLI output."""
    lines = [
        "Import execution summary",
        f"created={len(result.created)} skipped={len(result.skipped)} failed={len(result.failed)}",
    ]

    for row_number, summary, issue_key in result.created:
        lines.append(f"Row {row_number}: created {issue_key} for '{summary}'")
    for row_number, summary, issue_key in result.skipped:
        lines.append(
            f"Row {row_number}: duplicate summary already exists as {issue_key} for '{summary}'"
        )
    for row_number, summary, error in result.failed:
        lines.append(f"Row {row_number}: failed to create '{summary}' - {error}")

    return "\n".join(lines)
