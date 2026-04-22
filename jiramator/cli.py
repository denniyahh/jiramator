"""Jiramator CLI — Click entrypoint and subcommands.

This module is intentionally thin. It handles argument parsing, config
loading, and error display, then delegates all real work to planner.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from jiramator.config import load_org_config, load_team_config
from jiramator.importer import (
    build_preview_report,
    render_import_execution_report,
    render_preview_report,
    run_import,
)
from jiramator.jira_client import JiraApiError, JiraClient
from jiramator.spreadsheet import read_spreadsheet

console = Console(stderr=True)


def _resolve_org_config_path(path: Path) -> Path:
    """Resolve an org config path that might be a file or directory.

    If *path* is a directory, we look for exactly one .yaml/.yml file inside it.
    If *path* is a file, we return it as-is.

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
                f"No .yaml/.yml files found in org config directory: {path}"
            )
        if len(unique) > 1:
            names = ", ".join(c.name for c in unique)
            raise click.BadParameter(
                f"Multiple org config files found in {path}: {names}. "
                f"Specify the exact file with --org-config."
            )
        return unique[0]

    raise click.BadParameter(f"Org config path does not exist: {path}")


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
    required=True,
    help="Path to team config YAML file.",
)
@click.option(
    "--dry-run",
    "-n",
    is_flag=True,
    default=False,
    help="Show ticket preview and exit without creating anything.",
)
def plan(
    org_config_path: Path,
    team_config_path: Path,
    dry_run: bool,
) -> None:
    """Interactive PI planning — generate tickets for a new PI."""
    # -- Load configs -------------------------------------------------------
    try:
        resolved_org_path = _resolve_org_config_path(org_config_path)
        org_config = load_org_config(resolved_org_path)
    except (click.BadParameter, FileNotFoundError, ValueError) as exc:
        console.print(f"[red bold]Org config error:[/] {exc}")
        sys.exit(1)

    try:
        team_config = load_team_config(team_config_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red bold]Team config error:[/] {exc}")
        sys.exit(1)

    console.print(
        f"[green]✓[/] Loaded org config: [bold]{resolved_org_path}[/]"
    )
    console.print(
        f"[green]✓[/] Loaded team config: [bold]{team_config_path}[/] "
        f"(team={team_config.team_name}, project={team_config.project_key})"
    )

    # -- Hand off to planner ------------------------------------------------
    from jiramator.planner import run_plan  # noqa: E402 — deferred to avoid circular

    run_plan(org_config, team_config, dry_run=dry_run, console=console)


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
    required=True,
    help="Path to team config YAML file.",
)
@click.option(
    "--sheet-name",
    type=str,
    default=None,
    help="Optional worksheet name for XLSX imports.",
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
@click.argument("spreadsheet_path", type=click.Path(exists=True, path_type=Path))
def import_command(
    org_config_path: Path,
    team_config_path: Path,
    sheet_name: str | None,
    dry_run: bool,
    max_rows: int | None,
    preview_rows: int,
    spreadsheet_path: Path,
) -> None:
    """Import Jira issues from a CSV or XLSX spreadsheet."""
    try:
        resolved_org_path = _resolve_org_config_path(org_config_path)
        org_config = load_org_config(resolved_org_path)
    except (click.BadParameter, FileNotFoundError, ValueError) as exc:
        console.print(f"[red bold]Org config error:[/] {exc}")
        sys.exit(1)

    try:
        team_config = load_team_config(team_config_path)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red bold]Team config error:[/] {exc}")
        sys.exit(1)

    try:
        rows = read_spreadsheet(
            spreadsheet_path,
            sheet_name=sheet_name,
            max_rows=max_rows,
        )
    except (ValueError, KeyError) as exc:
        console.print(f"[red bold]Spreadsheet error:[/] {exc}")
        sys.exit(1)

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

    try:
        client = JiraClient(org_config)
        jira_fields = client.get_fields()
        result = run_import(
            rows,
            org_config=org_config,
            team_config=team_config,
            jira_fields=jira_fields,
            client=client,
        )
    except (ValueError, JiraApiError) as exc:
        console.print(f"[red bold]Import error:[/] {exc}")
        sys.exit(1)

    console.print(render_preview_report(result.preview, preview_rows=preview_rows))
    console.print(render_import_execution_report(result))
    if result.failed:
        sys.exit(1)
