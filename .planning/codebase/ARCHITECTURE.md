---
last_mapped_commit: 8c96e59b775dcea4aaa6a50e976c76a64e447907
last_mapped_at: 2026-09-28
---
<!-- refreshed: 2026-09-28 -->

# Architecture

**Analysis Date:** 2026-09-28

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                       CLI (Click group)                      │
│                     `jiramator/cli.py`                        │
│   plan | import | update | init  — thin: parse, load, wire    │
└──────────┬───────────────────┬──────────────────┬─────────────┘
           │                   │                    │
           ▼                   ▼                    ▼
┌────────────────┐  ┌─────────────────────┐  ┌──────────────────┐
│  Config layer   │  │  Orchestration      │  │  Wizard (init)   │
│ `config.py`     │  │  `planner.py`       │  │ `wizard.py`      │
│ `config_merge.py`│  │  `importer.py`      │  │                  │
│ (Pydantic +     │  │  `updater.py`       │  │                  │
│  YAML validate) │  │                     │  │                  │
└────────┬────────┘  └──────┬──────────────┘  └──────────────────┘
         │                  │
         ▼                  ▼
┌─────────────────────────────────────────────────────────────┐
│              Pure transformation / mapping layer              │
│  `ticket_builder.py` (plan)   `field_resolver.py` +           │
│  `value_coercion.py` (import/update)   `payload_validator.py` │
│  — no I/O, no side effects                                    │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   Jira REST client layer                      │
│                  `jiramator/jira_client.py`                    │
│     auth, retries, TLS handling, all HTTP to Jira Cloud/DC     │
└──────────────────────────┬────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│           Run reports / resume state (side-channel store)     │
│                  `jiramator/run_report.py`                     │
│                  writes JSON to `.jiramator/runs/`             │
└─────────────────────────────────────────────────────────────┘
```

Supporting cross-cutting modules: `spreadsheet.py` (CSV/XLSX ingestion for
`import`/`update`), `encoding.py` (CSV encoding detection), `error_format.py`
(Pydantic validation error → human-readable messages), `yaml_loader.py`
(line-number-tagged YAML for error reporting).

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| CLI entrypoint | Argument parsing, config-path resolution, error display, report lifecycle wiring for `import`/`update` | `jiramator/cli.py` |
| Config models | Pydantic schemas for org/team YAML; all schema validation, template-var checks, `$epic:` ref checks | `jiramator/config.py` |
| Config merge | Layered merge of org `default_fields` → team `defaults` → per-template `fields`; list dedup | `jiramator/config_merge.py` |
| YAML loader | Line-tagged YAML parsing so validation errors can cite source line numbers | `jiramator/yaml_loader.py` |
| Error formatting | Converts Pydantic `ValidationError` + custom checks into `ConfigValidationError` with "did you mean" suggestions | `jiramator/error_format.py` |
| Planner (orchestration) | Full interactive PI-planning flow: collect inputs, drift check, build/preview, create epics/tickets, resume | `jiramator/planner.py` |
| Ticket builder | Pure payload construction for `plan`: template interpolation, epic-ref resolution, ADF wrapping | `jiramator/ticket_builder.py` |
| Importer (orchestration) | Row-by-row payload build + live create for `import`, incl. deferred field lookups (reporter/assignee/parent) | `jiramator/importer.py` |
| Updater (orchestration) | Row-by-row payload build + live update for `update`; unique-key validation | `jiramator/updater.py` |
| Field resolver | Maps spreadsheet header names → Jira field IDs via org config aliases (import/update path) | `jiramator/field_resolver.py` |
| Value coercion | Type coercion + `value_aliases` shorthand → Jira label/ADF mapping (import/update path) | `jiramator/value_coercion.py` |
| Payload validator | Validates built payloads against Jira's live createmeta schema before create/update | `jiramator/payload_validator.py` |
| Jira client | All HTTP communication: auth, retries, TLS, issue/version/createmeta/board endpoints | `jiramator/jira_client.py` |
| Run report | `RunReport`/`IssueResult` models, atomic JSON writes, resolved-config hashing for drift detection, resume discovery | `jiramator/run_report.py` |
| Spreadsheet reader | CSV/XLSX ingestion with encoding detection and header normalization | `jiramator/spreadsheet.py` |
| Encoding detection | Detects CSV encoding (BOM/charset-normalizer) for `import`/`update` | `jiramator/encoding.py` |
| Wizard | Interactive `init` flow: discovers field IDs, writes org/team config skeletons, sets up credentials | `jiramator/wizard.py` |

## Pattern Overview

**Overall:** Layered CLI automation tool — "five-layer design with strict
separation of concerns" (CLI → Config → Builder/Resolver → Client →
Orchestrator), with a parallel path for the spreadsheet-driven commands
(`import`/`update`) that mirrors the `plan` path but swaps the builder layer
for `field_resolver.py` + `value_coercion.py`.

**Key Characteristics:**

- Preview-first: every command supports `--dry-run` and never touches Jira
  in that mode.
- Config-driven: behavior is entirely defined by two YAML layers (org, team);
  no hardcoded project/field knowledge in code.
- Pure-function transformation layer: `ticket_builder.py` has no I/O — same
  inputs always produce same payloads, called twice per `plan` run (once
  with placeholder epic keys for preview, once with real keys post-creation).
- Resumability: long-running bulk operations (`plan`, `import`) persist
  progress to JSON reports and can resume after failure via a config-hash
  drift check.
- Thin CLI: `cli.py` does not contain business logic — it loads configs,
  wires dependencies, and delegates to `planner.run_plan()` /
  `importer.run_import()` / `updater.run_update()`.

## Layers

**CLI (`jiramator/cli.py`):**

- Purpose: Click command group (`plan`, `import`, `update`, `init`); argument
  parsing, config path resolution, top-level error handling
- Location: `jiramator/cli.py`
- Contains: `@cli.command()` functions, `_resolve_*_config_path` helpers,
  report-lifecycle glue for `import`/`update` (plan's lifecycle lives inside
  `planner.run_plan()` instead)
- Depends on: `config.py`, `config_merge.py`, `planner.py`, `importer.py`,
  `updater.py`, `wizard.py`, `run_report.py`, `jira_client.py`,
  `spreadsheet.py`, `error_format.py`
- Used by: the `jiramator` console-script entry point (`pyproject.toml`
  `[project.scripts]`)

**Config (`jiramator/config.py`, `jiramator/config_merge.py`, `jiramator/yaml_loader.py`):**

- Purpose: Load, validate, and merge org/team YAML into typed Pydantic models
- Location: `jiramator/config.py` (models: `OrgConfig`, `TeamConfig`,
  `SprintConfig`, `BulkCreateConfig`, `EpicTemplate`, `TicketTemplate`,
  `TeamDefaults`)
- Contains: Pydantic `BaseModel` classes, `@field_validator`/
  `@model_validator` checks, template-variable validation
  (`_validate_template_vars`), epic-ref collection (`_collect_epic_refs`)
- Depends on: `error_format.py`, `yaml_loader.py`
- Used by: `cli.py`, `planner.py`, `ticket_builder.py`, `field_resolver.py`,
  `value_coercion.py`, `jira_client.py` (for credential env var names)

**Orchestration — plan (`jiramator/planner.py`):**

- Purpose: Runs the full interactive PI-planning flow end-to-end
- Location: `jiramator/planner.py` (single entry point `run_plan()`)
- Contains: input collection prompts, drift check, preview display, fix
  version creation, epic creation, bulk ticket creation, resume logic
  (`_bulk_create_with_resume`)
- Depends on: `ticket_builder.py`, `jira_client.py`, `payload_validator.py`,
  `run_report.py`
- Used by: `cli.py` `plan` command

**Orchestration — import/update (`jiramator/importer.py`, `jiramator/updater.py`):**

- Purpose: Row-by-row spreadsheet-driven create (`import`) or edit (`update`)
  of Jira issues
- Location: `jiramator/importer.py`, `jiramator/updater.py`
- Contains: `build_row_payload`/`build_row_update_payload` (pure), `run_import`/
  `run_update` (I/O, live Jira calls), preview/execution report rendering
- Depends on: `field_resolver.py`, `value_coercion.py`, `jira_client.py`,
  `run_report.py` (import only)
- Used by: `cli.py` `import`/`update` commands

**Pure transformation (`jiramator/ticket_builder.py`, `jiramator/field_resolver.py`, `jiramator/value_coercion.py`):**

- Purpose: Build Jira-ready field payloads from config templates or
  spreadsheet rows with zero I/O
- Location: `jiramator/ticket_builder.py` (plan path), `jiramator/field_resolver.py`
  + `jiramator/value_coercion.py` (import/update path)
- Contains: template interpolation (`resolve_value`), ADF wrapping
  (`_wrap_field`), field-name→ID resolution (`resolve_field_name`), type
  coercion + `value_aliases` (`coerce_field_value`)
- Depends on: `config.py` models only
- Used by: `planner.py` (ticket_builder), `importer.py`/`updater.py`
  (field_resolver, value_coercion)

**Validation (`jiramator/payload_validator.py`):**

- Purpose: Validate a built payload's field values against Jira's live
  createmeta schema before create/update
- Location: `jiramator/payload_validator.py`
- Depends on: nothing but stdlib/dict shapes returned by `jira_client.py`
- Used by: `planner._preflight_validate()`, `importer.py`, `updater.py`

**Client (`jiramator/jira_client.py`):**

- Purpose: All HTTP communication with the Jira REST API — auth, retries,
  TLS handling, error normalization
- Location: `jiramator/jira_client.py` (class `JiraClient`)
- Contains: `create_issue`, `create_issues_bulk`, `update_issue`,
  `get_createmeta_fields`, `get_fix_versions`, `create_fix_version`,
  `find_user_account_id`, `find_issue_keys_by_summaries`,
  `get_board_sprints`, custom `_CustomSslContextAdapter` for corporate TLS
  interception
- Depends on: `config.py` (`OrgConfig` for credentials/URL)
- Used by: `cli.py`, `planner.py`, `importer.py`, `updater.py`, `wizard.py`

**Run reports (`jiramator/run_report.py`):**

- Purpose: Persist run state as JSON for resumability and audit; detect
  config drift between runs via a resolved-config hash
- Location: `jiramator/run_report.py`; data written to `.jiramator/runs/`
  (gitignored)
- Contains: `RunReport`, `IssueResult` dataclasses, `write_report_atomic`,
  `compute_resolved_hash`, `find_resumable`, `default_report_path`
- Depends on: `config.py` models (for hashing)
- Used by: `cli.py`, `planner.py`, `importer.py`

**Spreadsheet I/O (`jiramator/spreadsheet.py`, `jiramator/encoding.py`):**

- Purpose: Read CSV/XLSX into normalized row dicts for `import`/`update`
- Location: `jiramator/spreadsheet.py`, `jiramator/encoding.py`
- Depends on: `openpyxl`, `charset-normalizer`
- Used by: `cli.py` (`import`/`update` commands)

**Wizard (`jiramator/wizard.py`):**

- Purpose: Interactive `init` command — discovers Jira field IDs live,
  writes org/team config skeleton YAML, sets up credential env files
- Location: `jiramator/wizard.py` (entry point `run_init()`)
- Depends on: `jira_client.py`
- Used by: `cli.py` `init` command

## Data Flow

### `plan` — PI planning path

1. `cli.py plan()` loads org/team YAML, merges layers via `merge_configs()`
   (`jiramator/cli.py:375-460`)
2. Hands off to `planner.run_plan()` (`jiramator/planner.py:661`)
3. Collect PI number + fix versions (prompt or `PlanInputs` non-interactive)
4. Compute `resolved_config_hash`; compare to `prior_report` for drift
   (resume safety)
5. `ticket_builder.build_all()` called with empty epic keys → preview payload
   set (`$epic:<ref>` left as literal strings)
6. Display preview table; if `--dry-run`, best-effort validate against
   createmeta and exit
7. Resolve credentials, build `JiraClient`; validate payloads for real
8. Check/create fix versions; confirm; create epics via
   `jira_client.create_issue`
9. `ticket_builder.build_all()` called again with real epic keys resolved
10. Bulk-create remaining tickets (`create_issues_bulk`), skipping any
    `template_key`s already marked `created` in `prior_report` (resume)
11. Persist final `RunReport` to `.jiramator/runs/` (success/partial/failed)
12. Display results table

### `import` — spreadsheet bulk-create path

1. `cli.py import_command()` loads configs, reads spreadsheet via
   `read_spreadsheet()` (`jiramator/cli.py:546`)
2. Drift check against `prior_report` (cli owns this lifecycle for import)
3. `--dry-run`: opportunistically fetch `client.get_fields()` for preview
   accuracy, then `importer.run_import(..., dry_run=True)` — offline-safe
4. Live run: build `JiraClient`, fetch fields, call
   `importer.run_import()` which per-row: `build_row_payload()` (pure) →
   resolve deferred fields (`reporter`/`assignee` via
   `find_user_account_id()`, `parent` via `find_issue_keys_by_summaries()`)
   → `create_issue()`
5. `RunReport` persisted throughout; final status computed from
   created/failed/skipped counts

### `update` — spreadsheet bulk-edit path

1. `cli.py update_command()` loads configs, reads spreadsheet, validates
   unique issue keys (`validate_unique_issue_keys()`)
2. `updater.run_update()`: per-row `build_row_update_payload()` (pure) →
   `client.update_issue()`
3. No resume support (unlike `plan`/`import`)

**State Management:**

- No persistent application state beyond JSON run reports in
  `.jiramator/runs/` (gitignored, per-team-config-path keyed).
- Config is loaded fresh on every invocation; no caching layer.
- `JiraClient` holds a `requests.Session` per invocation; no connection
  pooling across commands.

## Key Abstractions

**Org/Team config split:**

- Purpose: Separate company-wide Jira wiring (URL, custom field IDs, field
  aliases) from per-team ticket definitions (project key, epics, templates)
- Examples: `configs/org.example/example.yaml`, `configs/teams.example/example.yaml`
- Pattern: Two Pydantic models (`OrgConfig`, `TeamConfig` in `jiramator/config.py`)
  loaded independently then merged via `config_merge.merge_configs()`

**Template variables (`{pi_label}`, `{version}`, `{sprint_num}`, `{team_name}`, `{pi_num}`):**

- Purpose: Allow ticket templates to be written once and instantiated per
  PI/version/sprint
- Examples: validated in `jiramator/config.py` (`KNOWN_TEMPLATE_VARS`,
  `_validate_template_vars`), interpolated in
  `jiramator/ticket_builder.py::resolve_value()`
- Pattern: regex-based `{var}` substitution, validated at config-parse time
  so typos fail fast before any API call

**Epic references (`$epic:<ref>`):**

- Purpose: Let per-release/per-sprint tickets reference an epic that may not
  exist yet (created earlier in the same run)
- Examples: `jiramator/config.py::_collect_epic_refs`,
  `jiramator/ticket_builder.py`
- Pattern: two-phase build — refs stay literal in preview/dry-run, resolve to
  real Jira keys only after epic creation completes

**RunReport / resume:**

- Purpose: Make long bulk operations safely resumable after partial failure
- Examples: `jiramator/run_report.py` (`RunReport`, `IssueResult`,
  `compute_resolved_hash`, `find_resumable`)
- Pattern: content-hash the fully resolved config; on `--resume`, skip issues
  already marked `created` unless the hash has drifted (then require
  `--force`)

## Entry Points

**`jiramator` console script:**

- Location: `jiramator/cli.py::cli` (Click group), registered via
  `[project.scripts]` in `pyproject.toml`
- Triggers: invoked from the shell after `pip install -e .`
- Responsibilities: dispatch to `plan`/`import`/`update`/`init` subcommands

**`scripts/dry_run.py`:**

- Location: `scripts/dry_run.py`
- Triggers: manual invocation for local testing/demo without installing the
  package as a console script
- Responsibilities: convenience wrapper for exercising the CLI

**CI entry point:**

- Location: `.github/workflows/ci.yml`, `.github/workflows/jiramator-plan.yml`
- Triggers: GitHub Actions on push/PR (`ci.yml`), and a workflow that
  presumably drives `jiramator plan` (`jiramator-plan.yml`)

## Architectural Constraints

- **Threading:** Single-threaded, synchronous throughout. `jira_client.py`
  uses `requests` with a `Retry`/`HTTPAdapter` for resilience, not
  concurrency. No async/await anywhere in the codebase.
- **Global state:** Minimal — a single module-level `console = Console(stderr=True)`
  in `cli.py`. No other module-level singletons or shared mutable state
  observed.
- **Circular imports:** None observed; `config.py` sits at the bottom of the
  dependency graph (imported by nearly everything, imports only
  `error_format.py`/`yaml_loader.py`).
- **No database:** All state is either in-memory per-invocation or persisted
  as JSON files under `.jiramator/runs/` (gitignored, not committed).
- **No web server:** Purely a CLI; no HTTP server, no long-running process.

## Anti-Patterns

None identified as established patterns in this codebase — see
`CONCERNS.md` (if generated in a separate `concerns` mapping pass) for
specific issues. The codebase's own `CLAUDE.md` explicitly documents its
intended layering and conventions, and source review confirms the layering
is followed consistently (e.g. `ticket_builder.py` has no I/O calls,
`jira_client.py` has no template-interpolation logic).

## Error Handling

**Strategy:** Exceptions carry structured, human-readable messages up to
`cli.py`, which prints via Rich and exits with `sys.exit(1)`. No exception
is silently swallowed except explicitly-scoped fallbacks (e.g. dry-run
degrading to offline preview when Jira is unreachable).

**Patterns:**

- Config validation errors: `ConfigValidationError` (`jiramator/error_format.py`),
  built from Pydantic `ValidationError` plus custom checks, includes
  "did you mean" suggestions (`did_you_mean()`) and source line numbers
  (via `yaml_loader.py` line-tagging)
- Jira API errors: `JiraApiError` (`jiramator/jira_client.py`), wraps all
  HTTP failures with status code + Jira's field-level error dict
- Config drift: `ConfigDriftError` (`jiramator/run_report.py`), raised when
  `--resume` config hash doesn't match the prior run's hash (bypass with
  `--resume --force`)
- CLI-level unrecoverable errors: `_fail()` helper in `cli.py` prints a Rich
  message and calls `sys.exit(1)`
- Degraded-mode fallbacks: `plan --dry-run` and `import --dry-run` catch
  `JiraApiError`/`requests.exceptions.RequestException` around
  opportunistic live lookups and continue with an offline preview instead
  of failing

## Cross-Cutting Concerns

**Logging:** `logging` module used only in `jiramator/jira_client.py` for
operational traceability (HTTP-level). All other user-facing output goes
through `rich.console.Console(stderr=True)` — never bare `print()`.

**Validation:** Two tiers — (1) Pydantic schema validation at config-load
time (`config.py`), (2) live Jira createmeta schema validation at
build/preflight time (`payload_validator.py`, `planner._preflight_validate()`).

**Authentication:** Credentials never stored in config files; read from env
vars named in org config (`jira_email_env`/`jira_token_env`, default
`JIRA_EMAIL`/`JIRA_TOKEN`). Corporate TLS interception supported via
`JIRAMATOR_CA_BUNDLE` and `JIRAMATOR_RELAX_TLS_STRICT` env vars in
`jira_client.py`.

---

*Architecture analysis: 2026-09-28*
