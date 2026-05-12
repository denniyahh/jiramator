"""Planner — interactive PI planning orchestration.

This is the brains of the ``plan`` command.  It handles:
    1. Interactive prompts (PI number, fix version count, version strings)
    2. Fix version check-and-create
    3. Ticket payload generation via the builder
    4. Rich Table dry-run preview
    5. Duplicate warning
    6. Confirmation and creation (epics first, then bulk tickets)
    7. Results display

The ``run_plan()`` function is the single entry point, called by ``cli.py``.
It receives already-loaded configs and a ``Console`` for output.  The Jira
client is constructed internally (credentials resolved from env vars at that
point) so that ``--dry-run`` can skip credential resolution entirely.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from jiramator.config import OrgConfig, TeamConfig
from jiramator.error_format import ConfigValidationError
from jiramator.jira_client import JiraApiError, JiraClient
from jiramator.run_report import (
    ConfigDriftError,
    IssueResult,
    RunReport,
    compute_resolved_hash,
    write_report_atomic,
)
from jiramator.ticket_builder import _strip_template_key, build_all

# Default sprint field ID in Jira (overridable via org_config.custom_fields["sprint_field"])
_DEFAULT_SPRINT_FIELD = "customfield_10021"


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def _prompt_pi_number(console: Console) -> tuple[str, str]:
    """Ask the user for the PI number.

    Returns:
        (pi_num, pi_label) — e.g. ("28", "PI28").
    """
    raw = Prompt.ask("[bold]What is the PI number?[/]", console=console)
    raw = raw.strip()
    if not raw:
        console.print("[red]PI number cannot be empty.[/]")
        sys.exit(1)
    # Normalize: "PI28", "pi28", "28" all → pi_num="28", pi_label="PI28"
    pi_num = raw.upper().removeprefix("PI")
    if not pi_num:
        console.print("[red]PI number cannot be empty.[/]")
        sys.exit(1)
    pi_label = f"PI{pi_num}"
    console.print(f"  → pi_label = [cyan]{pi_label}[/]")
    return pi_num, pi_label


def _prompt_fix_versions(console: Console) -> list[str]:
    """Ask the user how many fix versions and their version strings.

    Returns:
        List of version strings (e.g. ["26.1.1", "26.1.2", "26.2.0"]).
    """
    fix_version_count = IntPrompt.ask(
        "[bold]How many fix versions in this PI?[/]", console=console
    )
    if fix_version_count < 1:
        console.print("[red]Fix version count must be at least 1.[/]")
        sys.exit(1)

    versions: list[str] = []
    for i in range(1, fix_version_count + 1):
        v = Prompt.ask(
            f"  Fix version {i}/{fix_version_count} version string",
            console=console,
        )
        v = v.strip()
        if not v:
            console.print(f"[red]Fix version string {i} cannot be empty.[/]")
            sys.exit(1)
        versions.append(v)

    console.print(f"  → versions = [cyan]{versions}[/]")
    return versions


def _prompt_sprints_exist(console: Console) -> bool:
    """Ask whether sprints already exist in Jira.

    Returns:
        True if the user confirms sprints are created.
    """
    return Confirm.ask(
        "[bold]Are the sprints for this PI already created in Jira?[/]",
        default=False,
        console=console,
    )


def _resolve_sprints_exist_mode(
    team_config: TeamConfig,
    cli_override: bool | None,
    console: Console,
) -> bool:
    """Resolve whether sprints exist for the current run (Plan 02-03).

    Priority order (DC-6 — exactly one branch runs per call):
      1. CLI flag (--sprints-exist / --no-sprints-exist) → cli_override
      2. team_config.sprints_exist (config field)
      3. Interactive prompt iff sys.stdin.isatty()
      4. ConfigValidationError otherwise (non-TTY, no flag, no config)

    Returns:
        True if sprints should be resolved, False to skip resolution.

    Raises:
        ConfigValidationError: branch (4) — non-TTY with neither flag nor
            config providing a value.
    """
    if cli_override is not None:
        return cli_override
    if team_config.sprints_exist is not None:
        return team_config.sprints_exist
    if sys.stdin.isatty():
        return _prompt_sprints_exist(console)
    raise ConfigValidationError(
        file=Path("<runtime>"),
        line=None,
        field_path="sprints_exist",
        reason=(
            "Cannot determine whether sprints exist: stdin is not a TTY "
            "and neither --sprints-exist/--no-sprints-exist nor "
            "'sprints_exist:' in team config is set."
        ),
    )


# ---------------------------------------------------------------------------
# Fix version management
# ---------------------------------------------------------------------------


def _check_and_create_fix_versions(
    client: JiraClient,
    project_key: str,
    needed_versions: list[str],
    console: Console,
) -> None:
    """Check existing fix versions and create any that are missing.

    Prompts the user for confirmation before creating.

    Raises:
        SystemExit: If the user declines to create missing versions.
        JiraApiError: On API failure.
    """
    existing = client.get_fix_versions(project_key)
    existing_names = {v["name"] for v in existing}

    missing = [v for v in needed_versions if v not in existing_names]

    if not missing:
        console.print("[green]✓[/] All fix versions already exist.")
        return

    console.print(
        f"\n[yellow]⚠[/] The following fix versions do not exist and will "
        f"be created: [bold]{', '.join(missing)}[/]"
    )
    if not Confirm.ask("Create these fix versions?", default=False, console=console):
        console.print("[red]Aborted.[/] Cannot proceed without fix versions.")
        sys.exit(1)

    for name in missing:
        client.create_fix_version(project_key, name)
        console.print(f"  [green]✓[/] Created fix version: {name}")


# ---------------------------------------------------------------------------
# Preview display
# ---------------------------------------------------------------------------


def _extract_summary(payload: dict[str, Any]) -> str:
    """Get the summary from a ticket payload."""
    return payload.get("fields", {}).get("summary", "<no summary>")


def _extract_field(payload: dict[str, Any], field: str, default: str = "") -> str:
    """Get a display-friendly value from a ticket payload field."""
    fields = payload.get("fields", {})
    value = fields.get(field, default)

    # Unwrap Jira name objects
    if isinstance(value, dict) and "name" in value:
        return value["name"]
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return ", ".join(item.get("name", str(item)) for item in value)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value) if value else default


def _display_preview(
    all_payloads: dict[str, list[dict[str, Any]]],
    versions: list[str],
    org_config: OrgConfig,
    console: Console,
) -> int:
    """Display a Rich Table preview of all tickets to be created.

    Returns:
        Total ticket count.
    """
    total = 0

    # --- Epics ---
    epics = all_payloads["epics"]
    if epics:
        table = Table(title="Epics", title_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Summary", style="bold")
        table.add_column("Ref Key", style="cyan")
        for i, epic in enumerate(epics, 1):
            summary = _extract_summary(epic["payload"])
            table.add_row(str(i), summary, epic["ref_key"])
        console.print(table)
        total += len(epics)

    # --- Per-release tickets ---
    per_release = all_payloads["per_release"]
    if per_release:
        table = Table(title="Per-Release Tickets", title_style="bold blue")
        table.add_column("#", style="dim", width=4)
        table.add_column("Summary", style="bold")
        table.add_column("Type", style="green")
        table.add_column("Fix Version(s)", style="yellow")
        table.add_column("Sprint", style="cyan")
        for i, ticket in enumerate(per_release, 1):
            summary = _extract_summary(ticket)
            issue_type = _extract_field(ticket, "issuetype", "?")
            fix_vers = _extract_field(ticket, "fixVersions", "")
            sprint = ticket.get("_sprint_num", "")
            table.add_row(str(i), summary, issue_type, fix_vers, sprint)
        console.print(table)
        total += len(per_release)

    # --- Per-sprint tickets ---
    per_sprint = all_payloads["per_sprint"]
    if per_sprint:
        table = Table(title="Per-Sprint Tickets", title_style="bold green")
        table.add_column("#", style="dim", width=4)
        table.add_column("Summary", style="bold")
        table.add_column("Type", style="green")
        table.add_column("Sprint", style="cyan")
        for i, ticket in enumerate(per_sprint, 1):
            summary = _extract_summary(ticket)
            issue_type = _extract_field(ticket, "issuetype", "?")
            sprint = ticket.get("_sprint_num", "")
            table.add_row(str(i), summary, issue_type, sprint)
        console.print(table)
        total += len(per_sprint)

    console.print(f"\n[bold]Total tickets to create: {total}[/]")
    return total


# ---------------------------------------------------------------------------
# Sprint resolution
# ---------------------------------------------------------------------------


def _resolve_sprint_ids(
    client: JiraClient,
    org_config: OrgConfig,
    team_config: TeamConfig,
    pi_num: str,
    payloads: list[dict[str, Any]],
    console: Console,
) -> None:
    """Resolve _sprint_num annotations to real Jira sprint IDs.

    Fetches sprints from the configured board, matches them against the
    sprint_name_template, and injects the sprint custom field into each payload.
    The sprint field ID is read from ``org_config.custom_fields["sprint_field"]``,
    falling back to ``customfield_10021`` if not configured.
    Mutates payloads in place. Strips ``_sprint_num`` after resolution.

    Args:
        client: Authenticated Jira client.
        org_config: Organization config (for sprint field ID lookup).
        team_config: Team config with board_id and sprint_name_template.
        pi_num: The PI number (e.g. "28").
        payloads: List of ticket payloads (may contain ``_sprint_num``).
        console: Rich console for output.
    """
    if team_config.board_id is None or not team_config.sprint_name_template:
        return

    # Fetch all active + future sprints from the board
    sprints = client.get_board_sprints(team_config.board_id)

    # Build a mapping of sprint_num → sprint ID by rendering the name template
    # for each possible sprint_num and matching against fetched sprint names.
    sprint_name_to_id = {s["name"]: s["id"] for s in sprints}

    # Collect all unique sprint_num values we need to resolve
    needed_nums = {p["_sprint_num"] for p in payloads if "_sprint_num" in p}

    sprint_num_to_id: dict[str, int] = {}
    unresolved: list[str] = []
    for num in sorted(needed_nums):
        expected_name = team_config.sprint_name_template.format(
            pi_num=pi_num, sprint_num=num,
        )
        if expected_name in sprint_name_to_id:
            sprint_num_to_id[num] = sprint_name_to_id[expected_name]
            console.print(
                f"  [green]✓[/] Sprint {num} → [cyan]{expected_name}[/] (id={sprint_num_to_id[num]})"
            )
        else:
            unresolved.append(num)

    if unresolved:
        console.print(
            f"  [yellow]⚠[/] Could not resolve sprint(s): {', '.join(unresolved)}. "
            f"Those tickets will be created without sprint assignment."
        )

    # Inject sprint IDs into payloads
    sprint_field = org_config.custom_fields.get("sprint_field", _DEFAULT_SPRINT_FIELD)
    for payload in payloads:
        sprint_num = payload.pop("_sprint_num", None)
        if sprint_num and sprint_num in sprint_num_to_id:
            payload["fields"][sprint_field] = sprint_num_to_id[sprint_num]


# ---------------------------------------------------------------------------
# Ticket creation
# ---------------------------------------------------------------------------


def _create_epics(
    client: JiraClient,
    epic_payloads: list[dict[str, Any]],
    console: Console,
) -> dict[str, str]:
    """Create epics one-by-one and collect ref_key → Jira key mapping.

    Epics must be created individually (not bulk) because we need each key
    before we can resolve $epic:ref references in downstream tickets.

    Returns:
        Dict of {ref_key: jira_key} (e.g. {"misc": "CA-5001"}).
    """
    epic_keys: dict[str, str] = {}
    for epic in epic_payloads:
        ref_key = epic["ref_key"]
        jira_key = client.create_issue(epic["payload"])
        epic_keys[ref_key] = jira_key
        console.print(f"  [green]✓[/] Epic [bold]{jira_key}[/] ({ref_key})")

    return epic_keys


def _create_tickets_bulk(
    client: JiraClient,
    payloads: list[dict[str, Any]],
    category: str,
    console: Console,
) -> list[str]:
    """Create tickets via bulk API and display progress.

    Returns:
        List of created Jira issue keys.
    """
    if not payloads:
        return []

    console.print(f"  Creating {len(payloads)} {category} tickets...")
    keys = client.create_issues_bulk(payloads)
    console.print(
        f"  [green]✓[/] Created {len(keys)} {category} tickets"
    )
    return keys


# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------


def _display_results(
    epic_keys: dict[str, str],
    per_release_keys: list[str],
    per_sprint_keys: list[str],
    console: Console,
) -> None:
    """Show a summary of all created tickets."""
    console.print("\n[bold green]═══ Results ═══[/]")

    if epic_keys:
        console.print("\n[bold magenta]Epics:[/]")
        for ref, key in epic_keys.items():
            console.print(f"  {key} ({ref})")

    if per_release_keys:
        console.print(f"\n[bold blue]Per-Release Tickets ({len(per_release_keys)}):[/]")
        console.print(f"  {', '.join(per_release_keys)}")

    if per_sprint_keys:
        console.print(f"\n[bold green]Per-Sprint Tickets ({len(per_sprint_keys)}):[/]")
        console.print(f"  {', '.join(per_sprint_keys)}")

    total = len(epic_keys) + len(per_release_keys) + len(per_sprint_keys)
    console.print(f"\n[bold]Total created: {total}[/]")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_plan(
    org_config: OrgConfig,
    team_config: TeamConfig,
    *,
    dry_run: bool = False,
    console: Console | None = None,
    report_path: Path | None = None,
    prior_report: RunReport | None = None,
    force: bool = False,
    org_config_path: Path | None = None,
    team_config_path: Path | None = None,
    command: list[str] | None = None,
    sprints_exist_override: bool | None = None,
) -> None:
    """Execute the full interactive PI planning flow.

    This is the single entry point called by ``cli.py``.

    Steps:
        1. Prompt for PI number, fix version count, version strings
        2. Drift check vs prior_report (if given) — fail unless force=True
        3. Initialize and persist a starter run report
        4. Build initial payloads (dry-run: epic refs unresolved)
        5. Display preview table
        6. If --dry-run: persist success and exit
        7. Resolve Jira credentials, build client
        8. Check/create fix versions
        9. Warn about duplicates, confirm
        10. Create epics (skip those already created in prior_report)
        11. Rebuild non-epic payloads with real epic keys
        12. Bulk create tickets (skip those already created in prior_report)
        13. Persist final report (status flipped to success/partial/failed)
        14. Display results

    Args:
        report_path: If provided, the run report is written here after every
            state change. ``None`` disables report emission entirely (legacy
            callers and unit tests that don't care about reports).
        prior_report: A previously-emitted report. When present and the
            resolved-config hash matches, ``status="created"`` issues from
            this report are skipped (their template_keys are not re-attempted).
        force: When True, allows resume to proceed even if hashes differ.
            Pass-through from --resume --force in cli.py.
        org_config_path / team_config_path: Source paths recorded in the report
            for resume discovery. cli.py passes them; legacy callers may pass
            None and accept empty strings on disk.
        command: argv-shaped list, recorded for audit. Caller must not put
            secrets on the command line.
    """
    if console is None:
        console = Console(stderr=True)

    # -- Step 1: Interactive prompts ----------------------------------------
    console.print("\n[bold]── PI Planning ──[/]\n")

    pi_num, pi_label = _prompt_pi_number(console)
    versions = _prompt_fix_versions(console)

    # -- Step 2: Drift check ------------------------------------------------
    current_hash = compute_resolved_hash(org_config, team_config, pi_label, versions)
    if (
        prior_report is not None
        and prior_report.resolved_config_hash != current_hash
        and not force
    ):
        raise ConfigDriftError(
            "Config has drifted since the prior run; resume is unsafe.\n"
            f"  prior hash:   {prior_report.resolved_config_hash[:12]}\n"
            f"  current hash: {current_hash[:12]}\n"
            "  Pass --resume --force to override (may create duplicates if refs were renamed)."
        )

    # -- Step 3: Initialize and persist the run report ---------------------
    report = RunReport(
        command=list(command) if command else [],
        started_at=datetime.now(timezone.utc).isoformat(),
        team_config_path=str(team_config_path.resolve()) if team_config_path else "",
        org_config_path=str(org_config_path.resolve()) if org_config_path else "",
        team_name=team_config.team_name,
        pi_label=pi_label,
        versions=list(versions),
        resolved_config_hash=current_hash,
        status="failed",  # pessimistic — flipped at the end
    )

    def _persist() -> None:
        if report_path is not None:
            write_report_atomic(report, report_path)

    # Pre-populate from prior report (carries already-created issues forward)
    prior_created_keys: dict[str, str] = {}
    if prior_report is not None:
        for issue in prior_report.issues:
            if issue.status == "created" and issue.jira_key:
                prior_created_keys[issue.template_key] = issue.jira_key
                report.issues.append(
                    IssueResult(
                        template_key=issue.template_key,
                        kind=issue.kind,
                        status="created",
                        jira_key=issue.jira_key,
                    )
                )
                report.counts["created"] = report.counts.get("created", 0) + 1

    _persist()  # initial write — proof we got this far

    try:
        return _run_plan_inner(
            org_config, team_config, console,
            pi_num=pi_num, pi_label=pi_label, versions=versions,
            dry_run=dry_run,
            report=report, prior_created_keys=prior_created_keys,
            persist=_persist,
            sprints_exist_override=sprints_exist_override,
        )
    except BaseException:
        # Persist whatever state we got to before the exception (covers
        # JiraApiError, KeyboardInterrupt, anything else). The atomic-write
        # contract from Plan 03 guarantees no half-written JSON on disk.
        _persist()
        raise


def _run_plan_inner(
    org_config: OrgConfig,
    team_config: TeamConfig,
    console: Console,
    *,
    pi_num: str,
    pi_label: str,
    versions: list[str],
    dry_run: bool,
    report: RunReport,
    prior_created_keys: dict[str, str],
    persist,
    sprints_exist_override: bool | None = None,
) -> None:
    """Inner pipeline — wrapped by run_plan's try/except for persist-on-error."""
    # Sprint assignment info
    sprints_exist: bool = False
    if team_config.board_id is not None:
        sprints_exist = _resolve_sprints_exist_mode(
            team_config, sprints_exist_override, console
        )
        if sprints_exist:
            console.print(
                "  [dim]Sprint assignment will be attempted after ticket creation.[/]"
            )
        else:
            console.print("  Sprint assignment: [yellow]skipped[/] (not yet created)")
    else:
        console.print(
            "  Sprint assignment: [yellow]skipped[/] (no board_id configured)"
        )

    # -- Step 4–5: Build preview payloads (epic refs unresolved) -----------
    console.print()
    all_payloads = build_all(
        org_config,
        team_config,
        pi_label=pi_label,
        pi_num=pi_num,
        versions=versions,
        epic_keys={},  # unresolved for preview
    )

    total = _display_preview(all_payloads, versions, org_config, console)

    # -- Step 6: Dry-run exit -----------------------------------------------
    if dry_run:
        console.print("\n[yellow]── Dry run ── no tickets created.[/]")
        report.status = "success"
        report.ended_at = datetime.now(timezone.utc).isoformat()
        persist()
        return

    # -- Step 7: Resolve credentials and build client -----------------------
    try:
        client = JiraClient(org_config)
    except ValueError as exc:
        console.print(f"\n[red bold]Credential error:[/] {exc}")
        sys.exit(1)

    # -- Step 8: Fix versions -----------------------------------------------
    needed_versions = list(dict.fromkeys(versions))  # deduplicate, preserve order
    console.print()
    _check_and_create_fix_versions(
        client, team_config.project_key, needed_versions, console
    )

    # -- Step 9: Duplicate warning + confirm --------------------------------
    console.print(
        "\n[yellow bold]⚠ This script does NOT check for duplicates.[/]\n"
        "  Running it again for the same PI will create duplicate tickets."
    )
    if not Confirm.ask(
        f"\nCreate these {total} tickets?", default=False, console=console
    ):
        console.print("[red]Aborted.[/]")
        sys.exit(1)

    # -- Step 10: Create epics (resume-aware) -------------------------------
    console.print("\n[bold]Creating tickets...[/]\n")

    epic_keys: dict[str, str] = dict(team_config.existing_epics)
    if epic_keys:
        for ref_key, jira_key in epic_keys.items():
            console.print(
                f"  [cyan]→[/] Epic [bold]{jira_key}[/] ({ref_key}) [dim]pre-existing[/]"
            )
    # Pull resumed epics into the working epic_keys dict so $epic:ref resolves
    for issue in report.issues:
        if issue.kind == "epic" and issue.status == "created" and issue.jira_key:
            ref_key = issue.template_key.removeprefix("epic:")
            epic_keys.setdefault(ref_key, issue.jira_key)

    try:
        for epic in all_payloads["epics"]:
            tk = epic["_template_key"]
            ref_key = epic["ref_key"]
            if tk in prior_created_keys:
                # Already created in prior run — skip Jira call, message user
                jira_key = prior_created_keys[tk]
                console.print(
                    f"  [dim]↻[/] Epic [bold]{jira_key}[/] ({ref_key}) "
                    f"[dim]resumed (prior run)[/]"
                )
                epic_keys[ref_key] = jira_key
                continue
            # Strip annotation just before send (Jira rejects unknown fields)
            send_payload = {"fields": dict(epic["payload"]["fields"])}
            try:
                jira_key = client.create_issue(send_payload)
            except JiraApiError as exc:
                report.issues.append(
                    IssueResult(
                        template_key=tk, kind="epic",
                        status="failed", error=str(exc),
                    )
                )
                report.counts["failed"] = report.counts.get("failed", 0) + 1
                persist()
                console.print(f"\n[red bold]Failed to create epic {ref_key}:[/] {exc}")
                sys.exit(1)
            epic_keys[ref_key] = jira_key
            report.issues.append(
                IssueResult(
                    template_key=tk, kind="epic",
                    status="created", jira_key=jira_key,
                )
            )
            report.counts["created"] = report.counts.get("created", 0) + 1
            persist()
            console.print(f"  [green]✓[/] Epic [bold]{jira_key}[/] ({ref_key})")
    except SystemExit:
        raise

    # -- Step 11: Rebuild ticket payloads with real epic keys ---------------
    final_payloads = build_all(
        org_config,
        team_config,
        pi_label=pi_label,
        pi_num=pi_num,
        versions=versions,
        epic_keys=epic_keys,
    )

    # -- Step 11b: Sprint assignment ----------------------------------------
    if team_config.board_id is not None and sprints_exist:
        console.print("\n[bold]Resolving sprints...[/]\n")
        all_ticketable = final_payloads["per_release"] + final_payloads["per_sprint"]
        try:
            _resolve_sprint_ids(
                client, org_config, team_config, pi_num, all_ticketable, console
            )
        except JiraApiError as exc:
            console.print(f"\n[yellow]⚠ Sprint resolution failed:[/] {exc}")
            console.print("  Tickets will be created without sprint assignment.")
            for p in final_payloads["per_release"] + final_payloads["per_sprint"]:
                p.pop("_sprint_num", None)
    else:
        # DC-8: when sprints_exist is False, skip _resolve_sprint_ids entirely
        # (no client.get_board_sprints API call). Strip annotation so it
        # doesn't leak into Jira payloads.
        for p in final_payloads["per_release"] + final_payloads["per_sprint"]:
            p.pop("_sprint_num", None)

    # -- Step 12: Bulk create (resume-aware) --------------------------------
    per_release_keys = _bulk_create_with_resume(
        client, final_payloads["per_release"], "per_release",
        prior_created_keys=prior_created_keys,
        report=report, persist=persist, console=console,
    )
    per_sprint_keys = _bulk_create_with_resume(
        client, final_payloads["per_sprint"], "per_sprint",
        prior_created_keys=prior_created_keys,
        report=report, persist=persist, console=console,
    )

    # -- Step 13: Final status flip + persist -------------------------------
    report.ended_at = datetime.now(timezone.utc).isoformat()
    if report.counts.get("failed", 0) == 0 and report.counts.get("created", 0) > 0:
        report.status = "success"
    elif report.counts.get("created", 0) > 0:
        report.status = "partial"
    else:
        report.status = "failed"
    persist()

    # -- Step 14: Results ---------------------------------------------------
    _display_results(epic_keys, per_release_keys, per_sprint_keys, console)


def _bulk_create_with_resume(
    client: JiraClient,
    payloads: list[dict[str, Any]],
    kind: str,
    *,
    prior_created_keys: dict[str, str],
    report: RunReport,
    persist,
    console: Console,
) -> list[str]:
    """Bulk-create tickets with resume support.

    Filters out payloads whose ``_template_key`` is already created in the
    prior report (recorded as already-created in ``report.issues``). Strips
    ``_template_key`` from remaining payloads before sending. On bulk failure,
    every remaining payload is recorded as ``status=failed`` so the user can
    retry just those rows on the next resume.

    Returns:
        List of newly-created Jira keys (does NOT include resumed keys —
        ``_display_results`` shows resumed ones via ``report.issues``).
    """
    if not payloads:
        return []

    remaining: list[dict[str, Any]] = []
    template_keys_in_order: list[str] = []
    for p in payloads:
        tk = p.get("_template_key", "")
        if tk and tk in prior_created_keys:
            # Already recorded by run_plan's pre-population step.
            continue
        remaining.append(p)
        template_keys_in_order.append(tk)

    if not remaining:
        console.print(
            f"  [dim]All {kind} tickets already created in prior run — skipping.[/]"
        )
        return []

    # Strip annotation before send (T-01-16)
    _strip_template_key(remaining)

    console.print(f"  Creating {len(remaining)} {kind} tickets...")
    try:
        keys = client.create_issues_bulk(remaining)
    except JiraApiError as exc:
        # Every remaining ticket is now in unknown state on the Jira side
        # (bulk endpoint is atomic-ish but we conservatively mark all failed
        # so the user retries the whole batch).
        for tk in template_keys_in_order:
            report.issues.append(
                IssueResult(
                    template_key=tk, kind=kind,  # type: ignore[arg-type]
                    status="failed", error=str(exc),
                )
            )
            report.counts["failed"] = report.counts.get("failed", 0) + 1
        persist()
        console.print(f"\n[red bold]Bulk creation failed:[/] {exc}")
        console.print("[yellow]Some tickets may have been created. Check Jira.[/]")
        sys.exit(1)

    for tk, jira_key in zip(template_keys_in_order, keys):
        report.issues.append(
            IssueResult(
                template_key=tk, kind=kind,  # type: ignore[arg-type]
                status="created", jira_key=jira_key,
            )
        )
        report.counts["created"] = report.counts.get("created", 0) + 1
    persist()
    console.print(f"  [green]✓[/] Created {len(keys)} {kind} tickets")
    return keys
