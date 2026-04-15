# Architecture

**Analysis Date:** 2026-04-15

## Pattern Overview

**Overall:** Layered CLI application with clean separation between configuration, business logic, API communication, and user interaction.

**Key Characteristics:**
- Config-driven: All behavior is declarative via YAML configs — no team-specific logic hardcoded
- Two-tier config model: Org-level (shared across teams) + Team-level (per-team ticket templates)
- Pure data transformation layer: `ticket_builder.py` has zero I/O, zero side effects
- Two-phase build: Epics created first to get Jira keys, then remaining tickets use those keys for `$epic:ref` resolution
- Interactive CLI orchestration: `planner.py` handles prompts, previews, confirmations, and creation flow

## Layers

**CLI Layer (Presentation):**
- Purpose: Argument parsing, config file resolution, error display
- Location: `jiramator/cli.py`
- Contains: Click group/commands, config path resolution helpers, Rich console setup
- Depends on: `jiramator/config.py` (config loaders), `jiramator/planner.py` (deferred import)
- Used by: End users via `jiramator` CLI entrypoint

**Configuration Layer (Domain Models):**
- Purpose: Pydantic models for org and team config, YAML loading, template variable and epic ref validation
- Location: `jiramator/config.py`
- Contains: `OrgConfig`, `TeamConfig`, `SprintConfig`, `EpicTemplate`, `TicketTemplate`, loader functions, validation helpers
- Depends on: `pydantic`, `pyyaml`
- Used by: All other layers — this is the shared data model

**Ticket Builder Layer (Business Logic):**
- Purpose: Transform config templates + runtime variables into Jira REST API payloads — pure data transformation, no I/O
- Location: `jiramator/ticket_builder.py`
- Contains: `build_all()`, `build_epics()`, `build_per_release_tickets()`, `build_per_sprint_tickets()`, `resolve_value()`, `_wrap_field()`
- Depends on: `jiramator/config.py` (models and regex patterns)
- Used by: `jiramator/planner.py`

**Jira Client Layer (Infrastructure):**
- Purpose: HTTP communication with Jira REST API — authentication, requests, retry, error handling
- Location: `jiramator/jira_client.py`
- Contains: `JiraClient` dataclass, `JiraApiError` exception, retry strategy, all REST API methods
- Depends on: `jiramator/config.py` (`OrgConfig` for credentials and URL), `requests`
- Used by: `jiramator/planner.py`

**Planner Layer (Orchestration):**
- Purpose: Orchestrate the full interactive PI planning flow — prompts, preview, validation, creation, results display
- Location: `jiramator/planner.py`
- Contains: `run_plan()` entry point, prompt helpers, fix version management, preview/results display, epic/bulk creation
- Depends on: All other layers (`config.py`, `ticket_builder.py`, `jira_client.py`, Rich)
- Used by: `jiramator/cli.py`

## Data Flow

**PI Planning Flow (the core use case):**

1. User runs `jiramator plan --org-config ... --team-config ...`
2. `cli.py` resolves config file paths and loads them via `load_org_config()` / `load_team_config()` into Pydantic models
3. `cli.py` calls `planner.run_plan(org_config, team_config, dry_run=...)` — the deferred import avoids circular deps
4. `planner.py` prompts user for PI number, release count, version strings (Rich prompts)
5. `planner.py` calls `ticket_builder.build_all()` with `epic_keys={}` to generate preview payloads
6. `planner.py` renders Rich Tables for dry-run preview
7. If `--dry-run`: exit here
8. `planner.py` constructs `JiraClient(org_config)` — credentials resolved from env vars at this point
9. `planner.py` checks/creates fix versions in Jira via `client.get_fix_versions()` / `client.create_fix_version()`
10. `planner.py` creates epics one-by-one via `client.create_issue()` → collects `{ref_key: jira_key}` mapping
11. `planner.py` calls `ticket_builder.build_all()` again with real `epic_keys` to resolve `$epic:ref` fields
12. `planner.py` calls `client.create_issues_bulk()` for per-release and per-sprint tickets
13. `planner.py` displays results summary

**Template Resolution Flow:**

1. YAML config has template strings like `"{team_name} {pi_label} - BAU Work"` and `"$epic:misc"`
2. `ticket_builder.resolve_value()` handles two resolution types:
   - `{var}` template interpolation — replaces `{pi_label}`, `{version}`, `{sprint_num}`, `{team_name}`, `{pi_num}` with runtime values
   - `$epic:key` resolution — replaces with real Jira issue key from `epic_keys` dict (or passes through raw if unresolved)
3. `ticket_builder._wrap_field()` converts resolved values into Jira REST API JSON structures (e.g. `"Task"` → `{"name": "Task"}`)
4. `ticket_builder._build_fields_payload()` combines project key, summary, and all resolved+wrapped fields into a `{"fields": {...}}` dict

**State Management:**
- No persistent state — all runtime state is function-scoped
- Config is immutable (Pydantic models)
- Epic keys are the only mutable cross-phase state, passed as a `dict[str, str]` between build phases
- Credentials come from environment variables, resolved on-demand

## Key Abstractions

**Config Models (Pydantic):**
- Purpose: Strongly-typed, validated configuration with clear org vs team boundaries
- Examples: `OrgConfig` in `jiramator/config.py`, `TeamConfig` in `jiramator/config.py`
- Pattern: Pydantic `BaseModel` with `Field()`, `field_validator()`, and `model_validator()` for cross-field validation

**Template System:**
- Purpose: Allow YAML configs to reference runtime values via `{variable}` syntax
- Examples: `{pi_label}`, `{version}`, `{sprint_num}`, `{team_name}`, `{pi_num}`
- Pattern: Regex-based `_TEMPLATE_VAR_RE` in `jiramator/config.py` validates at parse time; `resolve_value()` in `jiramator/ticket_builder.py` interpolates at build time

**Epic Reference System:**
- Purpose: Allow ticket templates to link to recurring epics before epic Jira keys exist
- Examples: `"$epic:misc"` in ticket `fields` → resolved to `"CA-5001"` after epic creation
- Pattern: `_EPIC_REF_RE` regex in `jiramator/config.py`; two-phase build in `jiramator/ticket_builder.py`

**Field Wrapping:**
- Purpose: Bridge between simple config values and Jira REST API's nested JSON structures
- Examples: `WRAPPED_FIELDS` dict in `jiramator/ticket_builder.py` — `"issuetype"` → `name_object`, `"fixVersions"` → `name_object_array`
- Pattern: Lookup table mapping field names to wrapping strategies

**JiraClient:**
- Purpose: Encapsulate all HTTP communication with Jira, including auth, retry, pagination, and error handling
- Examples: `JiraClient` dataclass in `jiramator/jira_client.py`
- Pattern: `dataclass` with `__post_init__` for session setup; `requests.Session` with `HTTPAdapter` retry strategy

## Entry Points

**CLI Entrypoint:**
- Location: `jiramator/cli.py:cli` (Click group)
- Triggers: `jiramator` console script (registered in `pyproject.toml` `[project.scripts]`)
- Responsibilities: Version display, routing to subcommands

**`plan` Subcommand:**
- Location: `jiramator/cli.py:plan` (Click command)
- Triggers: `jiramator plan --org-config ... --team-config ... [--dry-run]`
- Responsibilities: Load configs, resolve org config path, hand off to `planner.run_plan()`

**Planner Entry Point:**
- Location: `jiramator/planner.py:run_plan()`
- Triggers: Called by `cli.py:plan` with loaded configs
- Responsibilities: Full interactive PI planning flow (steps 1–11 described in Data Flow above)

**Builder Entry Point:**
- Location: `jiramator/ticket_builder.py:build_all()`
- Triggers: Called by `planner.py` (twice: once for preview, once with real epic keys)
- Responsibilities: Construct runtime variables dict, delegate to `build_epics()`, `build_per_release_tickets()`, `build_per_sprint_tickets()`

## Error Handling

**Strategy:** Fail-fast with clear, user-friendly messages displayed via Rich console. Errors from different layers are caught and wrapped at the planner level.

**Patterns:**
- **Config validation errors:** Pydantic `ValidationError` and custom `ValueError` raised during config loading; caught in `cli.py` with `sys.exit(1)` and Rich error display
- **Credential errors:** `OrgConfig.resolve_credentials()` raises `ValueError` if env vars missing/empty; caught in `planner.py` constructor call
- **Jira API errors:** `JiraApiError` custom exception in `jiramator/jira_client.py` with `status_code` and `errors` attributes; handles 401/403/404 specifically, generic for others; caught in `planner.py` at epic creation and bulk creation phases
- **HTTP retry:** Automatic retry on 429/502/503/504 via `urllib3.util.retry.Retry` in `jiramator/jira_client.py` (3 retries, exponential backoff)
- **Bulk partial failure:** `JiraApiError` raised if Jira returns partial errors in bulk create response; already-created issues are NOT rolled back (documented behavior)
- **User abort:** `sys.exit(1)` when user declines confirmations (fix version creation, duplicate warning)
- **409 Conflict:** Fix version already exists → silently fetched and returned (idempotent)

## Cross-Cutting Concerns

**Logging:** Python `logging` module in `jiramator/jira_client.py` (`logger = logging.getLogger(__name__)`). Used for API call tracing (issue creation, fix version creation). No logging in other modules — user-facing output uses Rich console.

**Validation:** Two-phase validation: (1) Pydantic model validators at config parse time catch schema errors, unknown template vars, undefined epic refs, long sprint suffix mismatches; (2) Jira API validates field values at creation time, surfaced via `JiraApiError`.

**Authentication:** Basic auth (email + API token) resolved from environment variables at `JiraClient.__post_init__`. Env var names are configurable in org config (`jira_email_env`, `jira_token_env`). Credentials never stored in config files.

---

*Architecture analysis: 2026-04-15*
