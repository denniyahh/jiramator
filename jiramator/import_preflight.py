"""Import preflight: validate every built row against Jira's live createmeta schema.

``run_preflight`` checks each successfully built import row's payload against
the create-screen schema for ``team_config.project_key`` and the row's own
issue type, collecting every problem across every row in one pass.
``render_preflight_report`` turns the result into Rich-markup text.

This module only performs read-only createmeta fetches — it never creates,
edits, or looks up issues, users or sprints.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import requests
from rich.markup import escape

from jiramator.config import OrgConfig
from jiramator.field_resolver import resolve_field_name
from jiramator.jira_client import JiraApiError
from jiramator.payload_validator import PayloadProblem, find_payload_problems

if TYPE_CHECKING:
    from jiramator.importer import RowBuildResult
    from jiramator.jira_client import JiraClient

# The row's issue type is validated by a casefold match against the project's
# createmeta issue-type list (D-02), so the validator's case-sensitive
# allowedValues check must not re-check it (OQ-1). fixVersions IS validated.
_IMPORT_SKIP_ALLOWED_VALUE_FIELD_IDS = frozenset({"issuetype"})

_NO_ISSUE_TYPE_PROBLEM = (
    "no issue type (no Issue Type column value and no bulk_create.defaults.issuetype)"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreflightRow:
    """Preflight outcome for one spreadsheet row."""

    row_number: int
    summary: str
    issue_type: str | None
    problems: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreflightResult:
    """Aggregate preflight outcome for an import run.

    Attributes:
        status: ``passed`` (every checked row is clean), ``problems`` (at
            least one row has problems), ``unavailable`` (createmeta could
            not be fetched — never presented as passed), or ``skipped``.
        reason: Why validation was unavailable/skipped, else ``None``.
        rows: Per-row outcomes in ascending row number.
        checked_rows: Rows validated against createmeta.
        considered_rows: Rows in scope (not resume-skipped), built or not.
    """

    status: Literal["passed", "problems", "unavailable", "skipped"]
    reason: str | None
    rows: list[PreflightRow]
    checked_rows: int
    considered_rows: int

    @property
    def problem_rows(self) -> list[PreflightRow]:
        """Rows with at least one problem."""
        return [row for row in self.rows if row.problems]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alias_headers_by_field_id(org_config: OrgConfig) -> dict[str, list[str]]:
    """Map Jira field id -> field_aliases keys resolving to it, in config order."""
    mapping: dict[str, list[str]] = {}
    for alias in org_config.bulk_create.field_aliases:
        resolved = resolve_field_name(alias, org_config)
        if resolved.jira_field is None:
            continue
        headers = mapping.setdefault(resolved.jira_field, [])
        if alias not in headers:
            headers.append(alias)
    return mapping


def _quote_join(headers: list[str]) -> str:
    return ", ".join(f"'{header}'" for header in headers)


def _missing_required_message(
    problem: PayloadProblem, alias_headers: dict[str, list[str]]
) -> str:
    headers = alias_headers.get(problem.field_id)
    if headers:
        return f"{problem.message} — no value in column(s) {_quote_join(headers)}"
    return f"{problem.message} — no spreadsheet column mapped to this field"


def _row_headers_for_field(row_result: RowBuildResult, field_id: str) -> list[str]:
    """Return the spreadsheet headers in this row that resolved to ``field_id``."""
    return [
        header
        for header, resolved in row_result.resolved_columns.items()
        if resolved.jira_field == field_id
    ]


def _lookup_kind(field_id: str, logical_name: str, deferred_logical_fields: frozenset[str]) -> str:
    """Name the live lookup a deferred field needs at create time."""
    if logical_name in deferred_logical_fields:
        return "sprint"
    if field_id == "parent":
        return "parent"
    return "user"


def _deferred_present(
    row_result: RowBuildResult,
    source_row: dict[str, Any],
    deferred_fields: frozenset[str],
    deferred_logical_fields: frozenset[str],
) -> dict[str, tuple[str, str]]:
    """Return field id -> (header, lookup kind) for deferred fields with a non-blank cell.

    Deferred fields (reporter/assignee/parent/sprint) are dropped from the
    built payload and resolved by a live lookup at create time; preflight
    only checks that the raw cell is non-blank (D-06). No lookup is made.
    """
    present: dict[str, tuple[str, str]] = {}
    for header, resolved in row_result.resolved_columns.items():
        field_id = resolved.jira_field
        if field_id is None:
            continue
        if field_id not in deferred_fields and resolved.logical_name not in deferred_logical_fields:
            continue
        # Same predicate run_import uses at create time, so preflight never
        # treats as "present" a cell the live lookup would skip.
        raw_value = source_row.get(header)
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        present.setdefault(
            field_id,
            (header, _lookup_kind(field_id, resolved.logical_name, deferred_logical_fields)),
        )
    return present


def _row_problem_messages(
    problems: list[PayloadProblem],
    row_result: RowBuildResult,
    issue_type: str,
    alias_headers: dict[str, list[str]],
) -> list[str]:
    messages: list[str] = []
    for problem in problems:
        if problem.kind == "missing_required":
            messages.append(_missing_required_message(problem, alias_headers))
            continue
        headers = _row_headers_for_field(row_result, problem.field_id)
        if problem.kind == "off_screen":
            source = (
                f"column {_quote_join(headers)}" if headers else "bulk_create.defaults"
            )
            messages.append(
                f"{problem.field_id} is mapped from {source} but is not on the "
                f"create screen for {issue_type}"
            )
            continue
        if headers:
            suffix = f" — from column {_quote_join(headers)}"
        else:
            suffix = " — from bulk_create.defaults"
        messages.append(f"{problem.message}{suffix}")
    return messages


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


def run_preflight(
    client: JiraClient,
    *,
    project_key: str,
    row_results: list[RowBuildResult],
    source_rows: list[dict[str, Any]],
    org_config: OrgConfig,
    skip_template_keys: frozenset[str] = frozenset(),
    template_key_fn: Callable[[int, str], str] | None = None,
    deferred_fields: frozenset[str] = frozenset(),
    deferred_logical_fields: frozenset[str] = frozenset(),
) -> PreflightResult:
    """Validate every built import row against Jira's live createmeta schema.

    Fetches the project's creatable issue types once and each distinct issue
    type's field schema once. Rows whose template key is in
    ``skip_template_keys`` (already created by a prior run) are neither
    validated nor counted. If no row needs checking, no client call is made.
    Rows that failed to build are listed with their build error (not
    schema-checked) unless validation is unavailable.

    Args:
        client: Jira client used only for read-only createmeta fetches.
        project_key: Project whose create screens are checked.
        row_results: Per-row build results from ``build_preview_report``.
        source_rows: Raw spreadsheet rows (same order as ``row_results``).
        org_config: Org config, used to attribute fields to column headers.
        skip_template_keys: Template keys of rows a resume would skip.
        template_key_fn: Computes a row's template key from (row_number,
            summary); required for ``skip_template_keys`` to apply.
        deferred_fields: Jira field ids resolved at create time.
        deferred_logical_fields: Logical field names resolved at create time.

    Returns:
        A ``PreflightResult``. Status is ``unavailable`` (with no rows) if
        any createmeta fetch fails.
    """
    in_scope: list[RowBuildResult] = []
    for row_result in row_results:
        if template_key_fn is not None and skip_template_keys:
            key = template_key_fn(row_result.row_number, row_result.summary)
            if key in skip_template_keys:
                continue
        in_scope.append(row_result)

    rows_to_check = [r for r in in_scope if r.success and r.payload]
    considered_rows = len(in_scope)
    # D-08: rows that failed to build are reported with their build error
    # (not schema-checked) whenever validation itself runs.
    build_failed_rows = [
        PreflightRow(
            row_number=r.row_number,
            summary=r.summary,
            issue_type=None,
            problems=[r.error or "Unknown row error"],
        )
        for r in in_scope
        if not (r.success and r.payload)
    ]

    if not rows_to_check:
        return PreflightResult(
            status="problems" if build_failed_rows else "passed",
            reason=None,
            rows=sorted(build_failed_rows, key=lambda row: row.row_number),
            checked_rows=0,
            considered_rows=considered_rows,
        )

    alias_headers = _alias_headers_by_field_id(org_config)
    schema_by_id: dict[str, dict[str, dict[str, Any]]] = {}
    preflight_rows: list[PreflightRow] = []

    try:
        issue_types = client.get_createmeta_issue_types(project_key)
        by_casefold = {
            str(item.get("name", "")).casefold(): item for item in issue_types
        }
        available = ", ".join(sorted(str(item.get("name", "")) for item in issue_types))

        for row_result in sorted(rows_to_check, key=lambda r: r.row_number):
            payload_fields: dict[str, Any] = (row_result.payload or {}).get("fields", {})
            issue_type_value = payload_fields.get("issuetype") or {}
            issue_type_name = (
                issue_type_value.get("name") if isinstance(issue_type_value, dict) else None
            )
            if not issue_type_name:
                preflight_rows.append(
                    PreflightRow(
                        row_number=row_result.row_number,
                        summary=row_result.summary,
                        issue_type=None,
                        problems=[_NO_ISSUE_TYPE_PROBLEM],
                    )
                )
                continue

            issue_type_name = str(issue_type_name)
            match = by_casefold.get(issue_type_name.casefold())
            if match is None:
                preflight_rows.append(
                    PreflightRow(
                        row_number=row_result.row_number,
                        summary=row_result.summary,
                        issue_type=issue_type_name,
                        problems=[
                            f"Issue type '{issue_type_name}' is not available for "
                            f"creation in project {project_key} "
                            f"(available: {available or 'none'})"
                        ],
                    )
                )
                continue

            type_id = str(match.get("id"))
            if type_id not in schema_by_id:
                schema_by_id[type_id] = client.get_createmeta_fields(project_key, type_id)
            field_metadata = schema_by_id[type_id]

            source_row = (
                source_rows[row_result.row_number - 1]
                if 0 < row_result.row_number <= len(source_rows)
                else {}
            )
            deferred = _deferred_present(
                row_result, source_row, deferred_fields, deferred_logical_fields
            )
            problems = find_payload_problems(
                payload_fields,
                field_metadata,
                skip_allowed_value_field_ids=_IMPORT_SKIP_ALLOWED_VALUE_FIELD_IDS,
                report_off_screen_fields=True,
                assume_present_field_ids=frozenset(deferred),
                blank_adf_counts_as_missing=True,
            )
            messages = _row_problem_messages(
                problems, row_result, issue_type_name, alias_headers
            )
            caveats: list[str] = []
            for field_id, (header, kind) in deferred.items():
                meta = field_metadata.get(field_id)
                if meta is None:
                    # D-10: the column maps to a field not on this create screen.
                    messages.append(
                        f"{field_id} is mapped from column '{header}' but is not on "
                        f"the create screen for {issue_type_name}"
                    )
                elif meta.get("required"):
                    name = meta.get("name", field_id)
                    caveats.append(
                        f"required {name} ({field_id}) depends on live {kind} "
                        "lookup — not preflight-validated"
                    )
            preflight_rows.append(
                PreflightRow(
                    row_number=row_result.row_number,
                    summary=row_result.summary,
                    issue_type=issue_type_name,
                    problems=messages,
                    caveats=caveats,
                )
            )
    except (JiraApiError, requests.exceptions.RequestException) as exc:
        return PreflightResult(
            status="unavailable",
            reason=str(exc),
            rows=[],
            checked_rows=0,
            considered_rows=considered_rows,
        )

    all_rows = sorted(preflight_rows + build_failed_rows, key=lambda row: row.row_number)
    has_problems = any(row.problems for row in all_rows)
    return PreflightResult(
        status="problems" if has_problems else "passed",
        reason=None,
        rows=all_rows,
        checked_rows=len(rows_to_check),
        considered_rows=considered_rows,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_preflight_report(result: PreflightResult) -> str:
    """Render a preflight result as Rich-markup text.

    Every summary, issue type, message and reason is escaped; the issue type
    is escaped as the whole ``[...]`` segment so lower-case names such as
    ``risk`` are never swallowed as Rich style tags. Every failing row is
    listed (no preview cap).

    Args:
        result: The preflight result to render.

    Returns:
        Rich-markup text suitable for ``Console.print``.
    """
    if result.status == "unavailable":
        reason = escape(result.reason or "unknown error")
        return (
            "[yellow]⚠ Schema validation skipped: could not fetch Jira create "
            f"metadata ({reason})[/]"
        )
    if result.status == "skipped":
        reason = escape(result.reason or "not run")
        return f"[yellow]⚠ Schema validation skipped: {reason}[/]"
    if result.status == "passed":
        lines = [
            f"[green]✓ Schema validation passed: {result.checked_rows} row(s) "
            "checked against Jira createmeta[/]"
        ]
        lines.extend(_render_caveat_only_rows(result))
        return "\n".join(lines)

    lines = ["[bold red]Schema validation found problems:[/]"]
    for row in result.problem_rows:
        lines.append(_row_header(row))
        for problem in row.problems:
            lines.append(f"  [red]•[/] {escape(problem)}")
        for caveat in row.caveats:
            lines.append(f"  [yellow]⚠[/] {escape(caveat)}")
    lines.extend(_render_caveat_only_rows(result))
    lines.append(
        f"{len(result.problem_rows)} of {result.considered_rows} rows have problems"
    )
    return "\n".join(lines)


def _row_header(row: PreflightRow) -> str:
    header = f"Row {row.row_number} '{escape(row.summary)}'"
    if row.issue_type is not None:
        header += f" {escape(f'[{row.issue_type}]')}"
    return f"{header}:"


def _render_caveat_only_rows(result: PreflightResult) -> list[str]:
    """Render rows with caveats but no problems (D-06) — never counted as problems."""
    caveat_rows = [row for row in result.rows if row.caveats and not row.problems]
    if not caveat_rows:
        return []
    lines = ["[yellow]Not preflight-validated:[/]"]
    for row in caveat_rows:
        lines.append(_row_header(row))
        for caveat in row.caveats:
            lines.append(f"  [yellow]⚠[/] {escape(caveat)}")
    return lines
