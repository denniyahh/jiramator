# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Jiramator is a config-driven CLI for bulk Jira ticket automation: `plan` (generate a PI's
worth of epics/tickets from templates), `import` (bulk-create issues from CSV/XLSX), and
`update` (bulk-edit existing issues from CSV/XLSX). Everything is preview-first — `--dry-run`
never touches Jira. See README.md for user-facing docs; this file is for working on the
source itself.

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Tests
python -m pytest -v                                          # all tests
python -m pytest tests/test_config.py                        # single file
python -m pytest -k "TestBuildEpics"                          # single class/test by name
python -m pytest --cov=jiramator --cov-report=term-missing    # with coverage
```

No linter or formatter is configured. CI (`.github/workflows/ci.yml`) runs the full suite on
Linux/macOS/Windows × Python 3.11/3.12/3.13 via `pip install -e ".[dev]"` + `python -m pytest -q`.

## Architecture

Five-layer design with strict separation of concerns:

| Layer | File | Role |
|---|---|---|
| CLI | `jiramator/cli.py` | Argument parsing, config loading, error display — thin shell |
| Config | `jiramator/config.py` | Pydantic models for org/team YAML; all validation happens here |
| Builder | `jiramator/ticket_builder.py` | Pure data transformation — no I/O, no side effects |
| Client | `jiramator/jira_client.py` | All HTTP communication with the Jira REST API |
| Planner | `jiramator/planner.py` | Orchestrates the interactive PI planning flow |

`import`/`update` follow a parallel path through `importer.py` / `updater.py`, using
`field_resolver.py` (maps spreadsheet headers → Jira field IDs via org config aliases) and
`value_coercion.py` (type coercion + `value_aliases` shorthand-to-Jira-label mapping) instead
of `ticket_builder.py`.

**Deferred fields (`import` only):** `reporter`, `assignee`, and `parent` can't be coerced from
a raw spreadsheet string the way other fields are — Jira requires a live lookup (user search
for `reporter`/`assignee` via `JiraClient.find_user_account_id()`; exact-key match or
issue-summary search via `JiraClient.find_issue_keys_by_summaries()` for `parent`). `importer.py`
resolves these in `run_import()` at create time rather than in `build_row_payload()`, one Jira
API call per field per row's raw value. An unresolvable value is skipped with a warning; the
rest of the issue is still created.

**`plan` data flow:** `cli.py` loads configs → `planner.run_plan()` → calls
`ticket_builder.build_all()` **twice** (once for preview with empty epic keys, once with real
Jira keys after epics are created) → `JiraClient` for all API calls. This two-phase call is
why `$epic:<ref>` resolution exists: refs stay literal strings in dry-run/preview and resolve
to real issue keys only after epic creation.

**Two-tier config model:**
- `configs/org/` (gitignored, real) / `configs/org.example/` (tracked, generic) — Jira URL,
  custom field ID mappings, `bulk_create.field_aliases` + `value_aliases`, sprint cadence.
  Shared across a company; rarely changes.
- `configs/teams/` (gitignored, real) / `configs/teams.example/` (tracked, generic) — project
  key, team name, epic definitions (`recurring_epics` vs `existing_epics`), ticket templates.
  Per-team, changes every PI.

Both are Pydantic models loaded via `load_org_config()` / `load_team_config()`. Both
`--org-config`/`--team-config` CLI flags accept a file or a directory containing exactly one
`.yaml`/`.yml` (default: `./configs/org/`, `./configs/teams/`).

`config_merge.py` applies a layered merge for `plan`: org `default_fields` → team `defaults` →
per-template `fields`, with list dedup via `concat_dedup_lists`.

**Template & epic reference system:** Template variables (`{pi_label}`, `{version}`,
`{sprint_num}`, `{team_name}`, `{pi_num}`) are validated at config-parse time
(`_TEMPLATE_VAR_RE` in `config.py`) and interpolated at build time (`ticket_builder.resolve_value()`).
Epic references (`$epic:<key>`) in ticket fields resolve to real Jira keys post-epic-creation;
`existing_epics` (pre-existing Jira keys) and `recurring_epics` (created fresh) are mixable but
must not overlap the same ref key.

**Run reports & resume:** `run_report.py` defines `RunReport`/`IssueResult` and
`compute_resolved_hash()` — a hash of the fully-resolved config used to detect drift between a
failed run and a `--resume` attempt. `plan` and `import` write JSON reports to
`.jiramator/runs/` and support `--resume`/`--resume --force`. `update` does not currently
support resume.

**Credentials:** Never stored in config files. Read from env vars (`JIRA_EMAIL`, `JIRA_TOKEN`
by default; overridable per-org config via `jira_email_env`/`jira_token_env`). `plan --dry-run`
opportunistically builds a client to validate every built ticket's fields against Jira's live
createmeta schema (see `payload_validator.py` and `planner._preflight_validate()`). `import --dry-run`
opportunistically fetches `client.get_fields()` so the preview correctly resolves columns that
only match by Jira's live field name (`auto_lookup_unknown_fields`), not just `field_aliases`.
Both degrade gracefully to an offline/unvalidated preview if credentials are missing or Jira is
unreachable, but neither fails because of it. `update --dry-run` *requires* credentials outright
(it fetches live field metadata for coercion preview and fails without them).

**Corporate TLS interception:** `jira_client.py` supports `JIRAMATOR_CA_BUNDLE` (custom CA
bundle path) and `JIRAMATOR_RELAX_TLS_STRICT=1` (relaxes the "Basic Constraints not marked
critical" check only — verification, hostname, and expiry checks stay on) for networks with
TLS-inspecting proxies. See README's Troubleshooting section for the full rationale.

## Code conventions

- Every source file starts with `from __future__ import annotations`. Explicit
  `from jiramator.x import Y` imports only — no wildcards, no barrel files.
- Fully annotated signatures, lowercase generics (`dict[str, Any]`, `list[str] | None`), void
  functions annotate `-> None`.
- `_` prefix for private functions/constants (`_wrap_field`, `_RETRY_STRATEGY`); public
  constants are `UPPER_SNAKE_CASE`.
- All user-facing output goes through `rich.console.Console(stderr=True)` — never `print()`.
  `logging` is reserved for `jira_client.py` only (operational traceability).
- Config validators raise `ValueError` with actionable messages. `JiraApiError` wraps all HTTP
  errors. CLI-level unrecoverable errors: print a Rich message, then `sys.exit(1)`.
- Google-style docstrings (`Args:`, `Returns:`, `Raises:`) on public functions/classes.
- Section dividers in source and test files:
  ```python
  # ---------------------------------------------------------------------------
  # Section Name
  # ---------------------------------------------------------------------------
  ```
- Pydantic: `Field(description=...)` on all fields; `@field_validator` + `@classmethod` for
  single-field checks, `@model_validator(mode="after")` for cross-field checks.

## Testing conventions

- Test classes: `Test<ComponentName>`. Test functions: `test_<behavior>_<expected_result>`
  (e.g. `test_missing_jira_url_raises`, `test_409_conflict_fetches_existing`).
- **Mock HTTP** by replacing `client._session.get`/`.post` with a `MagicMock` returning
  `_mock_response(status_code, json_data)`.
- **Mock Rich prompts** with e.g. `@patch("jiramator.planner.Confirm.ask")`.
- **Mock env vars** with `monkeypatch.setenv`/`.delenv`.
- **Do not mock** Pydantic validation, YAML config loading, or ticket-builder logic — exercise
  those with real inputs.
- `tests/test_integration.py` exercises the shipped `configs/org.example/example.yaml` plus the
  tracked fixture `tests/fixtures/teams/calcs.yaml` (a stable copy of the real Calcs team
  config, since `configs/teams/` is gitignored) via `scope="module"` fixtures, and asserts
  exact ticket counts. If you change that fixture's structure, update the count assertions
  deliberately — they're a regression guard, not incidental.
- Per-file fixtures live at the top of each test file; shared path fixtures
  (`org_config_path`, `team_config_path`) live in `tests/conftest.py`.
