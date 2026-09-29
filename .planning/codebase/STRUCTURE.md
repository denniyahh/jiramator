---
last_mapped_commit: 8c96e59b775dcea4aaa6a50e976c76a64e447907
last_mapped_at: 2026-09-28
---
# Codebase Structure

**Analysis Date:** 2026-09-28

## Directory Layout

```
jiramator/
├── jiramator/                  # Source package (flat module layout, no subpackages)
│   ├── cli.py                  # Click entrypoint — all subcommands
│   ├── config.py               # Pydantic models for org/team YAML
│   ├── config_merge.py         # Layered config merge (org → team → template)
│   ├── yaml_loader.py          # Line-tagged YAML loading (for error messages)
│   ├── error_format.py         # ValidationError → human-readable messages
│   ├── planner.py              # `plan` command orchestration
│   ├── ticket_builder.py       # Pure payload builder for `plan`
│   ├── importer.py             # `import` command orchestration + payload build
│   ├── updater.py              # `update` command orchestration + payload build
│   ├── field_resolver.py       # Spreadsheet header → Jira field ID mapping
│   ├── value_coercion.py       # Type coercion + value_aliases (import/update)
│   ├── payload_validator.py    # Validate payloads against Jira createmeta schema
│   ├── jira_client.py          # Jira REST API client (all HTTP)
│   ├── run_report.py           # RunReport/IssueResult, resume/drift detection
│   ├── spreadsheet.py          # CSV/XLSX reading
│   ├── encoding.py             # CSV encoding detection
│   ├── wizard.py               # `init` command — interactive config scaffolding
│   └── __init__.py             # Package marker (exports version only)
├── tests/                      # pytest suite, mirrors jiramator/ one file per module
│   ├── conftest.py              # Shared fixtures
│   ├── fixtures/                # Static test data (CSV encodings, YAML errors, team configs)
│   ├── test_<module>.py         # Unit tests per source module
│   ├── test_cli.py / test_cli_e2e.py   # CLI-level tests
│   ├── test_import_cli.py / test_import_integration.py
│   └── test_integration.py      # End-to-end test against configs/org.example + fixture team config
├── configs/                    # Config templates (tracked) + real configs (gitignored)
│   ├── org.example/             # Tracked, generic org config sample
│   ├── teams.example/           # Tracked, generic team config sample
│   ├── org/                     # Gitignored — real org config (created by `jiramator init`)
│   └── teams/                   # Gitignored — real team configs (created by `jiramator init`)
├── docs/                       # User-facing docs and sample spreadsheets
│   ├── mcp-server-proposal.md
│   └── samples/                 # mass-creation-sample.xlsx, mass-update-sample.xlsx
├── scripts/
│   └── dry_run.py               # Manual/local invocation helper
├── .github/
│   ├── workflows/ci.yml         # Test matrix: Linux/macOS/Windows × Py 3.11/3.12/3.13
│   ├── workflows/jiramator-plan.yml   # CI workflow driving `jiramator plan`
│   └── copilot-instructions.md  # Copilot-specific repo guidance
├── .jiramator/                 # Gitignored — run reports written by `plan`/`import`
│   └── runs/                    # JSON RunReport files, timestamp+team-named
├── .planning/                  # Gitignored — GSD planning docs (this analysis lives here)
├── CLAUDE.md                   # Architecture + conventions reference for AI agents
├── README.md                   # User-facing documentation
├── CONTRIBUTING.md             # Contribution guidelines
├── CHANGELOG.md                # Release history
├── ISSUES.md                   # Known issues tracker
└── pyproject.toml              # Package metadata, dependencies, console-script entry point
```

## Directory Purposes

**`jiramator/` (package root):**

- Purpose: All application source code
- Contains: 17 flat `.py` modules — no subpackages, no nested layers
- Key files: `cli.py` (entrypoint), `config.py` (schema), `jira_client.py`
  (all HTTP)

**`tests/`:**

- Purpose: pytest suite, one `test_<module>.py` per source module plus
  CLI/integration-level tests
- Contains: unit tests, e2e CLI tests (`test_cli_e2e.py`), integration tests
  against real config shape (`test_integration.py`,
  `test_config_inheritance_integration.py`, `test_import_integration.py`)
- Key files: `conftest.py` (shared fixtures), `fixtures/` (static test data)

**`tests/fixtures/`:**

- Purpose: Static input data used across tests
- Contains: `csv_encodings/` (encoding-detection test files), `teams/calcs.yaml`
  (stable tracked copy of a real team config, since `configs/teams/` is
  gitignored), `yaml_errors/` (malformed YAML for error-path tests)

**`configs/org.example/` and `configs/teams.example/`:**

- Purpose: Tracked, generic templates showing the config schema
- Contains: `example.yaml` per directory; `org.example/acme.yaml` is a
  second real-shaped example
- Committed: yes (these are the `.example` variants)

**`configs/org/` and `configs/teams/`:**

- Purpose: Real, company/team-specific configs used at runtime
- Generated: by `jiramator init` (`wizard.py`)
- Committed: no — gitignored (`configs/org/`, `configs/teams/` in `.gitignore`)

**`docs/`:**

- Purpose: User-facing supplementary documentation and sample spreadsheets
  for `import`/`update`
- Contains: `mcp-server-proposal.md` (design doc), `samples/*.xlsx`

**`scripts/`:**

- Purpose: Developer convenience scripts not part of the installed package
- Contains: `dry_run.py`

**`.jiramator/runs/`:**

- Purpose: Persisted JSON run reports for resume/drift-detection
- Generated: at runtime by `plan`/`import`
- Committed: no — gitignored

## Key File Locations

**Entry Points:**

- `jiramator/cli.py`: Click group `cli`, registered as the `jiramator`
  console script in `pyproject.toml` (`[project.scripts]`)
- `scripts/dry_run.py`: manual local-run helper

**Configuration:**

- `pyproject.toml`: package metadata, dependencies, console-script entry
  point, pytest config (`[tool.pytest.ini_options]`)
- `configs/org.example/example.yaml`, `configs/teams.example/example.yaml`:
  config schema templates
- `.envrc`, `.env` (gitignored): local credential env vars (`JIRA_EMAIL`,
  `JIRA_TOKEN`)

**Core Logic:**

- `jiramator/config.py`: all Pydantic schema/validation
- `jiramator/planner.py`: `plan` command orchestration (`run_plan()`)
- `jiramator/importer.py` / `jiramator/updater.py`: spreadsheet-driven flows
- `jiramator/jira_client.py`: all Jira REST API calls

**Testing:**

- `tests/`: full suite, run via `python -m pytest -v`
- `tests/test_integration.py`: exercises real `configs/org.example/example.yaml`
  + `tests/fixtures/teams/calcs.yaml`, asserts exact ticket counts

## Naming Conventions

**Files:**

- Module name matches its primary responsibility, singular noun or verb
  phrase: `jira_client.py`, `ticket_builder.py`, `field_resolver.py`,
  `value_coercion.py`, `run_report.py`
- Test files: `test_<module>.py` mirroring the source module name
  (e.g. `jiramator/planner.py` → `tests/test_planner.py`,
  `tests/test_planner_report.py`, `tests/test_planner_sprint.py` for
  focused sub-areas of a large module)

**Directories:**

- `configs/<kind>.example/`: tracked template variant, suffix `.example`
- `configs/<kind>/`: real, gitignored variant, no suffix
- Flat package layout: no subpackages under `jiramator/` regardless of
  module count (17 modules, largest is `planner.py` at 1096 lines)

**Functions:**

- Public functions: `snake_case`, verb-first (`build_row_payload`,
  `resolve_field_name`, `run_import`)
- Private/internal helpers: `_snake_case` prefix (`_resolve_config_dir_path`,
  `_wrap_field`, `_build_fields_payload`)
- Public constants: `UPPER_SNAKE_CASE` (`KNOWN_TEMPLATE_VARS`,
  `_TEMPLATE_VAR_RE` — note some constants keep the `_` prefix if
  module-private)

**Classes:**

- Pydantic models: `PascalCase`, noun (`OrgConfig`, `TeamConfig`,
  `SprintConfig`, `EpicTemplate`, `TicketTemplate`)
- Result/data containers: `PascalCase` dataclasses (`RunReport`,
  `IssueResult`, `RowBuildResult`, `PreviewReport`, `ImportRunResult`)
- Exceptions: `PascalCase` + `Error`/`Warning` suffix (`JiraApiError`,
  `ConfigValidationError`, `ConfigDriftError`, `ConfigConflictWarning`)

**Test naming:**

- Test classes: `Test<ComponentName>`
- Test functions: `test_<behavior>_<expected_result>` (e.g.
  `test_missing_jira_url_raises`, `test_409_conflict_fetches_existing`)

## Where to Add New Code

**New CLI command:**

- Implementation: add a `@cli.command()` function in `jiramator/cli.py`,
  keep it thin — delegate real logic to a new or existing orchestration
  module
- Tests: `tests/test_cli.py` or `tests/test_cli_e2e.py`

**New config field:**

- Schema: add to the relevant Pydantic model in `jiramator/config.py`
  (`OrgConfig` for company-wide, `TeamConfig`/`TicketTemplate`/`EpicTemplate`
  for per-team)
- If merge-relevant: update `jiramator/config_merge.py`
- Update both `configs/org.example/example.yaml` and/or
  `configs/teams.example/example.yaml` to document the new field
- Tests: `tests/test_config.py`, `tests/test_config_merge.py`

**New Jira API interaction:**

- Implementation: add a method to `JiraClient` in `jiramator/jira_client.py`
- Tests: `tests/test_jira_client.py` (mock `client._session.get`/`.post`)

**New payload-building logic (plan path):**

- Implementation: `jiramator/ticket_builder.py` (keep pure — no I/O)
- Tests: `tests/test_ticket_builder.py`

**New payload-building logic (import/update path):**

- Implementation: `jiramator/field_resolver.py` (field mapping) or
  `jiramator/value_coercion.py` (value transformation)
- Tests: `tests/test_field_resolver.py`, `tests/test_value_coercion.py`

**Utilities:**

- Shared helpers: prefer adding a focused new module at the `jiramator/`
  root over growing an existing large module further (`planner.py` is
  already 1096 lines); if truly cross-cutting and small, consider
  `error_format.py` (already houses string-diagnostic helpers like
  `did_you_mean`)

## Special Directories

**`.jiramator/`:**

- Purpose: Runtime-generated JSON run reports (resume/drift state)
- Generated: Yes
- Committed: No (gitignored)

**`.planning/`:**

- Purpose: GSD planning docs, including this codebase map
- Generated: Yes (by GSD tooling)
- Committed: No (gitignored)

**`configs/org/`, `configs/teams/`:**

- Purpose: Real, secret-adjacent config (project keys, custom field IDs,
  epic keys)
- Generated: Yes, via `jiramator init`
- Committed: No (gitignored)

**`.pytest_cache/`, `__pycache__/`:**

- Purpose: pytest/Python bytecode caches
- Generated: Yes
- Committed: No (gitignored)

---

*Structure analysis: 2026-09-28*
