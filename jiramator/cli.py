"""Jiramator CLI — Click entrypoint and subcommands.

This module is intentionally thin. It handles argument parsing, config
loading, error display, and report-lifecycle wiring, then delegates
all real work to planner.py and importer.py.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from rich.console import Console

from jiramator.config import load_org_config, load_team_config
from jiramator.config_merge import merge_configs
from jiramator.error_format import ConfigValidationError
from jiramator.importer import (
    build_preview_report,
    render_import_execution_report,
    render_preview_report,
    run_import,
)
from jiramator.jira_client import JiraApiError, JiraClient
from jiramator.planner import PlanInputs, make_plan_inputs, run_plan
from jiramator.run_report import (
    ConfigDriftError,
    IssueResult,
    RunReport,
    compute_resolved_hash,
    default_report_path,
    find_resumable,
    write_report_atomic,
)
from jiramator.spreadsheet import read_spreadsheet
from jiramator.updater import (
    UpdateRunResult,
    render_update_execution_report,
    render_update_preview_report,
    run_update,
    validate_unique_issue_keys,
)

console = Console(stderr=True)


def _resolve_config_dir_path(path: Path, *, kind: str, flag: str) -> Path:
    """Resolve a config path that might be a file or directory.

    If *path* is a directory, we look for exactly one .yaml/.yml file inside it.
    If *path* is a file, we return it as-is.

    Args:
        path: The file or directory to resolve.
        kind: Human-readable label for error messages (e.g. "Org", "Team").
        flag: The CLI flag name to suggest when a directory is ambiguous
              (e.g. "--org-config", "--team-config").

    Raises:
        click.BadParameter: If the path is invalid or ambiguous.
    """
    if path.is_file():
        return path

    if path.is_dir():
        candidates = sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml"))
        # Deduplicate (a file named x.yaml won't also match *.yml, but be safe)
        seen: set[Path] = set()
        unique: list[Path] = []
        for c in candidates:
            resolved = c.resolve()
            if resolved not in seen:
                seen.add(resolved)
                unique.append(c)

        if len(unique) == 0:
            raise click.BadParameter(
                f"No .yaml/.yml files found in {kind.lower()} config directory: {path}"
            )
        if len(unique) > 1:
            names = ", ".join(c.name for c in unique)
            raise click.BadParameter(
                f"Multiple {kind.lower()} config files found in {path}: {names}. "
                f"Specify the exact file with {flag}."
            )
        return unique[0]

    raise click.BadParameter(f"{kind} config path does not exist: {path}")


def _resolve_org_config_path(path: Path) -> Path:
    """Resolve an org config path that might be a file or directory."""
    return _resolve_config_dir_path(path, kind="Org", flag="--org-config")


def _resolve_team_config_path(path: Path) -> Path:
    """Resolve a team config path that might be a file or directory."""
    return _resolve_config_dir_path(path, kind="Team", flag="--team-config")


def _fail(message: str) -> None:
    """Print *message* to stderr (plain text, no Rich markup) and exit 1."""
    click.echo(message, err=True)
    sys.exit(1)


def _load_report_file(path: Path) -> RunReport:
    """Load and validate a run-report envelope from *path*.

    Exits 1 with a clear stderr message on missing file, parse error,
    or schema-version mismatch. Never raises.
    """
    if not path.exists():
        _fail(f"Resume report not found: {path}")
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"Could not parse resume report: {path} — {exc}")
    try:
        return RunReport.from_envelope(envelope)
    except (ValueError, KeyError, TypeError) as exc:
        _fail(f"Resume report incompatible: {exc}")


def _load_prior_report(
    resume_arg: str | None, team_config_path: Path
) -> RunReport | None:
    """Resolve --resume into a RunReport (or None if not requested).

    - ``resume_arg is None``: user didn't pass --resume → return None.
    - ``resume_arg == "auto"``: user passed --resume with no value → use
      ``find_resumable`` to discover the most recent partial/failed run
      for this team config; exit 1 if none found.
    - Any other string: treat as a path and load that report explicitly.
    """
    if resume_arg is None:
        return None
    if resume_arg == "auto":
        candidate = find_resumable(team_config_path)
        if candidate is None:
            resolved = team_config_path.resolve()
            _fail(
                f"No resumable run found for {resolved} in .jiramator/runs/. "
                f"Use --resume <path> to specify explicitly, "
                f"or run without --resume to start fresh."
            )
        return _load_report_file(candidate)
    return _load_report_file(Path(resume_arg))


def _update_report_from_result(
    result: UpdateRunResult,
    *,
    command: list[str],
    started_at: str,
    ended_at: str,
    spreadsheet_path: Path,
    org_config_path: Path,
) -> RunReport:
    """Build a persistent run report for a bulk-update result."""
    updated_fields_by_row: dict[int, list[str]] = {}
    for row_result in result.preview.row_results:
        if row_result.payload is None:
            continue
        updated_fields_by_row[row_result.row_number] = sorted(
            row_result.payload.get("fields", {}).keys()
        )

    report = RunReport(
        command=command,
        started_at=started_at,
        ended_at=ended_at,
        team_config_path=str(spreadsheet_path.resolve()),
        org_config_path=str(org_config_path.resolve()),
        team_name=f"update:{spreadsheet_path.stem}",
        pi_label=None,
        versions=[],
        resolved_config_hash="",
        status="failed",
        counts={
            "updated": len(result.updated),
            "skipped": len(result.skipped),
            "failed": len(result.failed),
        },
    )

    for row_number, issue_key in result.updated:
        report.issues.append(
            IssueResult(
                template_key=f"row-{row_number}",
                kind="updated",
                status="updated",
                jira_key=issue_key,
                fields=updated_fields_by_row.get(row_number, []),
            )
        )
    for row_number, issue_key, reason in result.skipped:
        report.issues.append(
            IssueResult(
                template_key=f"row-{row_number}",
                kind="updated",
                status="skipped",
                jira_key=issue_key or None,
                error=reason,
                fields=updated_fields_by_row.get(row_number, []),
            )
        )
    for row_number, issue_key, error in result.failed:
        report.issues.append(
            IssueResult(
                template_key=f"row-{row_number}",
                kind="updated",
                status="failed",
                jira_key=issue_key or None,
                error=error,
                fields=updated_fields_by_row.get(row_number, []),
            )
        )

    if len(result.failed) == 0:
        report.status = "success"
    elif len(result.updated) > 0 or len(result.skipped) > 0:
        report.status = "partial"
    else:
        report.status = "failed"

    return report


@click.group()
@click.version_option(package_name="jiramator")
def cli() -> None:
    """Jiramator — config-driven Jira ticket automation."""


@cli.command()
@click.option(
    "--org-config",
    "-o",
    "org_config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("./configs/org/"),
    show_default=True,
    help="Path to org config file or directory containing one.",
)
@click.option(
    "--team-config",
    "-t",
    "team_config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("./configs/teams/"),
    show_default=True,
    help="Path to team config file, or a directory containing exactly one.",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    default=False,
    help="Show ticket preview and exit without creating anything.",
)
@click.option(
    "--report",
    "report_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to write run report. Default: .jiramator/runs/<UTC>-<team>.json",
)
@click.option(
    "--sprints-exist/--no-sprints-exist",
    "sprints_exist_override",
    default=None,
    help=(
        "Whether sprints for this PI already exist in Jira. "
        "If unset, falls back to 'sprints_exist:' in the team config, "
        "then to an interactive prompt (or errors if stdin is not a TTY). "
        "Use --no-sprints-exist for sprintless runs (no Jira board API call)."
    ),
)
@click.option(
    "--pi-number",
    "pi_number",
    default=None,
    type=click.STRING,
    help="PI number (e.g. 29). Provide with --versions to run non-interactively. "
    "If omitted, you are prompted.",
)
@click.option(
    "--versions",
    "versions_csv",
    default=None,
    type=click.STRING,
    help="Comma-separated fix versions (e.g. 26.2.1,26.2.2). Provide with "
    "--pi-number to run non-interactively. If omitted, you are prompted.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompts (fix-version creation and final create). "
    "For non-interactive/automated runs. Use with care — this writes to Jira.",
)
@click.option(
    "--resume",
    "resume_arg",
    is_flag=False,
    flag_value="auto",
    default=None,
    type=click.STRING,
    help="Resume a previous failed/partial run. Pass --resume to auto-find "
    "the latest, or --resume <path> for a specific report.",
)
@click.option(
    "--force",
    "force",
    is_flag=True,
    default=False,
    help="With --resume: ignore the resolved-config-hash drift check. "
    "Use only if you understand the risk of duplicate creation.",
)
def plan(
    org_config_path: Path,
    team_config_path: Path,
    dry_run: bool,
    report_path: Path | None,
    sprints_exist_override: bool | None,
    pi_number: str | None,
    versions_csv: str | None,
    assume_yes: bool,
    resume_arg: str | None,
    force: bool,
) -> None:
    """PI planning — generate tickets for a new PI.

    Runs interactively by default. Provide --pi-number and --versions (and
    --yes for writes) to run fully non-interactively, e.g. from CI or an
    MCP front-end.
    """
    # -- Load configs -------------------------------------------------------
    try:
        resolved_org_path = _resolve_org_config_path(org_config_path)
        org_config, org_tagged = load_org_config(resolved_org_path)
    except ConfigValidationError as exc:
        _fail(str(exc))
    except (click.BadParameter, FileNotFoundError, ValueError) as exc:
        _fail(f"Org config error: {exc}")

    try:
        team_config_path = _resolve_team_config_path(team_config_path)
        team_config, team_tagged = load_team_config(team_config_path)
    except ConfigValidationError as exc:
        _fail(str(exc))
    except (click.BadParameter, FileNotFoundError, ValueError) as exc:
        _fail(f"Team config error: {exc}")

    # -- Apply Phase 02-02 layered merge: org → team-defaults → templates --
    team_config = merge_configs(
        org_model=org_config,
        org_tagged_raw=org_tagged,
        org_file=resolved_org_path,
        team_model=team_config,
        team_tagged_raw=team_tagged,
        team_file=team_config_path,
        console=console,
    )

    console.print(
        f"[green]✓[/] Loaded org config: [bold]{resolved_org_path}[/]"
    )
    console.print(
        f"[green]✓[/] Loaded team config: [bold]{team_config_path}[/] "
        f"(team={team_config.team_name}, project={team_config.project_key})"
    )

    # -- Resolve resume + report path --------------------------------------
    prior_report = _load_prior_report(resume_arg, team_config_path)
    if report_path is None:
        report_path = default_report_path(team_config_path)

    # -- Build non-interactive inputs if provided --------------------------
    plan_inputs: PlanInputs | None = None
    if pi_number is not None or versions_csv is not None:
        if pi_number is None or versions_csv is None:
            _fail("--pi-number and --versions must be provided together.")
        try:
            plan_inputs = make_plan_inputs(pi_number, versions_csv.split(","))
        except ValueError as exc:
            _fail(str(exc))

    # -- Hand off to planner -----------------------------------------------
    try:
        run_plan(
            org_config,
            team_config,
            dry_run=dry_run,
            console=console,
            report_path=report_path,
            prior_report=prior_report,
            force=force,
            org_config_path=resolved_org_path,
            team_config_path=team_config_path,
            command=list(sys.argv),
            sprints_exist_override=sprints_exist_override,
            inputs=plan_inputs,
            assume_yes=assume_yes,
        )
    except ConfigDriftError as exc:
        _fail(str(exc))
    except ConfigValidationError as exc:
        _fail(str(exc))


@cli.command(name="import")
@click.option(
    "--org-config",
    "-o",
    "org_config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("./configs/org/"),
    show_default=True,
    help="Path to org config file or directory containing one.",
)
@click.option(
    "--team-config",
    "-t",
    "team_config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("./configs/teams/"),
    show_default=True,
    help="Path to team config file, or a directory containing exactly one.",
)
@click.option(
    "--sheet-name",
    type=str,
    default=None,
    help="Optional worksheet name for XLSX files (defaults to the first sheet).",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    default=False,
    help="Preview import payloads and exit without creating issues.",
)
@click.option(
    "--max-rows",
    type=int,
    default=None,
    help="Limit the number of spreadsheet rows read.",
)
@click.option(
    "--preview-rows",
    type=int,
    default=5,
    show_default=True,
    help="Number of prepared rows to include in preview output.",
)
@click.option(
    "--encoding",
    "encoding_override",
    type=click.STRING,
    default=None,
    help="Force a specific encoding for CSV reads (bypasses auto-detection). "
    "Common values: utf-8, utf-8-sig, cp1252, utf-16-le.",
)
@click.option(
    "--report",
    "report_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to write run report. Default: .jiramator/runs/<UTC>-<team>.json",
)
@click.option(
    "--resume",
    "resume_arg",
    is_flag=False,
    flag_value="auto",
    default=None,
    type=click.STRING,
    help="Resume a previous import. Pass --resume to auto-find latest, "
    "or --resume <path> for a specific report.",
)
@click.option(
    "--force",
    "force",
    is_flag=True,
    default=False,
    help="With --resume: ignore the resolved-config-hash drift check. "
    "Use only if you understand the risk of duplicate creation.",
)
@click.argument("spreadsheet_path", type=click.Path(exists=True, path_type=Path))
def import_command(
    org_config_path: Path,
    team_config_path: Path,
    sheet_name: str | None,
    dry_run: bool,
    max_rows: int | None,
    preview_rows: int,
    encoding_override: str | None,
    report_path: Path | None,
    resume_arg: str | None,
    force: bool,
    spreadsheet_path: Path,
) -> None:
    """Import Jira issues from a CSV or XLSX spreadsheet."""
    try:
        resolved_org_path = _resolve_org_config_path(org_config_path)
        org_config, _ = load_org_config(resolved_org_path)
    except ConfigValidationError as exc:
        _fail(str(exc))
    except (click.BadParameter, FileNotFoundError, ValueError) as exc:
        _fail(f"Org config error: {exc}")

    try:
        team_config_path = _resolve_team_config_path(team_config_path)
        team_config, _ = load_team_config(team_config_path)
    except ConfigValidationError as exc:
        _fail(str(exc))
    except (click.BadParameter, FileNotFoundError, ValueError) as exc:
        _fail(f"Team config error: {exc}")

    try:
        rows = read_spreadsheet(
            spreadsheet_path,
            sheet_name=sheet_name,
            max_rows=max_rows,
            encoding_override=encoding_override,
        )
    except (ValueError, KeyError) as exc:
        _fail(f"Spreadsheet error: {exc}")

    # -- Resolve resume + report path --------------------------------------
    prior_report = _load_prior_report(resume_arg, team_config_path)
    if report_path is None:
        report_path = default_report_path(team_config_path)

    # Drift check (cli owns the lifecycle for import; run_import doesn't).
    current_hash = compute_resolved_hash(org_config, team_config, None, [])
    if (
        prior_report is not None
        and prior_report.resolved_config_hash != current_hash
        and not force
    ):
        _fail(
            "Config has drifted since the prior import; resume is unsafe.\n"
            f"  prior hash:   {prior_report.resolved_config_hash[:12]}\n"
            f"  current hash: {current_hash[:12]}\n"
            "  Pass --resume --force to override."
        )

    if dry_run:
        result = run_import(
            rows,
            org_config=org_config,
            team_config=team_config,
            jira_fields=None,
            client=None,
            dry_run=True,
        )
        console.print(render_preview_report(result.preview, preview_rows=preview_rows))
        return

    # Build a report for live runs (cli owns the lifecycle for import).
    report = RunReport(
        command=list(sys.argv),
        started_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        team_config_path=str(team_config_path.resolve()),
        org_config_path=str(resolved_org_path.resolve()),
        team_name=team_config.team_name,
        pi_label=None,
        versions=[],
        resolved_config_hash=current_hash,
        status="failed",
    )

    try:
        client = JiraClient(org_config)
        jira_fields = client.get_fields()
        result = run_import(
            rows,
            org_config=org_config,
            team_config=team_config,
            jira_fields=jira_fields,
            client=client,
            report=report,
            report_path=report_path,
            prior_report=prior_report,
        )
    except (ValueError, JiraApiError) as exc:
        # Persist the (possibly partial) report before exiting.
        report.ended_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        try:
            write_report_atomic(report, report_path)
        except OSError:
            pass
        _fail(f"Import error: {exc}")

    # Finalize report status.
    report.ended_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    failed_count = report.counts.get("failed", 0)
    created_count = report.counts.get("created", 0)
    skipped_count = report.counts.get("skipped", 0)

    if failed_count == 0:
        report.status = "success"
    elif created_count > 0 or skipped_count > 0 or failed_count > 0:
        report.status = "partial"
    else:
        report.status = "failed"
    write_report_atomic(report, report_path)

    console.print(render_preview_report(result.preview, preview_rows=preview_rows))
    console.print(render_import_execution_report(result))
    if result.failed:
        sys.exit(1)


@cli.command(name="update")
@click.option(
    "--org-config",
    "-o",
    "org_config_path",
    type=click.Path(exists=True, path_type=Path),
    default=Path("./configs/org/"),
    show_default=True,
    help="Path to org config file or directory containing one.",
)
@click.option(
    "--key-column",
    type=str,
    default="Key",
    show_default=True,
    help="Spreadsheet column header that contains the Jira issue key.",
)
@click.option(
    "--sheet-name",
    type=str,
    default=None,
    help="Optional worksheet name for XLSX files (defaults to the first sheet).",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    default=False,
    help="Preview update payloads and exit without modifying issues. Still "
    "requires valid Jira credentials and network access (fetches field "
    "metadata for coercion), unlike 'plan'/'import' dry-run.",
)
@click.option(
    "--max-rows",
    type=int,
    default=None,
    help="Limit the number of spreadsheet rows read.",
)
@click.option(
    "--preview-rows",
    type=int,
    default=5,
    show_default=True,
    help="Number of prepared rows to include in preview output.",
)
@click.option(
    "--encoding",
    "encoding_override",
    type=click.STRING,
    default=None,
    help="Force a specific encoding for CSV reads (bypasses auto-detection).",
)
@click.option(
    "--report",
    "report_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to write run report. Default: .jiramator/runs/<UTC>-<spreadsheet>.json",
)
@click.argument("spreadsheet_path", type=click.Path(exists=True, path_type=Path))
def update_command(
    org_config_path: Path,
    key_column: str,
    sheet_name: str | None,
    dry_run: bool,
    max_rows: int | None,
    preview_rows: int,
    encoding_override: str | None,
    report_path: Path | None,
    spreadsheet_path: Path,
) -> None:
    """Bulk-update existing Jira issues from a CSV or XLSX spreadsheet.

    The spreadsheet must have a key column (default: 'Key') containing Jira
    issue keys (e.g. CA-4646).  All other columns are resolved to Jira fields
    using org config aliases and updated on the corresponding issue.

    Blank cells mean 'no change' — they are omitted from the update payload
    and will NOT clear the existing Jira field value.
    """
    try:
        resolved_org_path = _resolve_org_config_path(org_config_path)
        org_config, _ = load_org_config(resolved_org_path)
    except ConfigValidationError as exc:
        _fail(str(exc))
    except (click.BadParameter, FileNotFoundError, ValueError) as exc:
        _fail(f"Org config error: {exc}")

    try:
        rows = read_spreadsheet(
            spreadsheet_path,
            sheet_name=sheet_name,
            max_rows=max_rows,
            encoding_override=encoding_override,
        )
    except (ValueError, KeyError) as exc:
        _fail(f"Spreadsheet error: {exc}")

    if not rows:
        console.print("[yellow]No rows found in spreadsheet.[/]")
        return

    try:
        validate_unique_issue_keys(rows, key_column=key_column)
    except ValueError as exc:
        _fail(str(exc))

    if report_path is None:
        report_path = default_report_path(spreadsheet_path)

    if dry_run:
        try:
            client = JiraClient(org_config)
            jira_fields = client.get_fields()
            result = run_update(
                rows,
                key_column=key_column,
                org_config=org_config,
                jira_fields=jira_fields,
                client=None,
                dry_run=True,
            )
        except (ValueError, JiraApiError) as exc:
            _fail(f"Update dry-run error: {exc}")
        console.print(render_update_preview_report(result.preview, preview_rows=preview_rows))
        return

    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        client = JiraClient(org_config)
        jira_fields = client.get_fields()
        result = run_update(
            rows,
            key_column=key_column,
            org_config=org_config,
            jira_fields=jira_fields,
            client=client,
        )
    except (ValueError, JiraApiError) as exc:
        _fail(f"Update error: {exc}")

    ended_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report = _update_report_from_result(
        result,
        command=list(sys.argv),
        started_at=started_at,
        ended_at=ended_at,
        spreadsheet_path=spreadsheet_path,
        org_config_path=resolved_org_path,
    )
    write_report_atomic(report, report_path)

    console.print(render_update_preview_report(result.preview, preview_rows=preview_rows))
    console.print(render_update_execution_report(result))
    if result.failed:
        sys.exit(1)
