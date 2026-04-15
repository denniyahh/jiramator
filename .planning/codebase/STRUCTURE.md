# Codebase Structure

**Analysis Date:** 2026-04-15

## Directory Layout

```
jiramator/                      # Repository root
├── configs/                    # YAML configuration files
│   ├── org/                    # Organization-level configs (one per company)
│   │   └── marketaxess.yaml    # MarketAxess org config (Jira URL, custom fields, sprints)
│   └── teams/                  # Team-level configs (one per team)
│       └── calcs.yaml          # Calcs team config (project key, epics, ticket templates)
├── jiramator/                  # Python package — all source code
│   ├── __init__.py             # Package marker, version string
│   ├── cli.py                  # Click CLI entrypoint and subcommands
│   ├── config.py               # Pydantic config models, YAML loading, validation
│   ├── jira_client.py          # Jira REST API client (HTTP, auth, retry, errors)
│   ├── planner.py              # Interactive PI planning orchestration
│   └── ticket_builder.py       # Pure-function ticket payload generation
├── tests/                      # All test files
│   ├── __init__.py             # Package marker (empty)
│   ├── conftest.py             # Shared pytest fixtures (config file paths)
│   ├── fixtures/               # Test fixture directory (currently empty)
│   ├── test_config.py          # Tests for config parsing and validation
│   ├── test_integration.py     # End-to-end tests with real config files
│   ├── test_jira_client.py     # Tests for Jira API client (HTTP mocked)
│   ├── test_planner.py         # Tests for planner orchestration (prompts mocked)
│   └── test_ticket_builder.py  # Tests for ticket payload generation
├── pyproject.toml              # Build config, dependencies, CLI entrypoint
├── README.md                   # User documentation with config reference
├── .gitignore                  # Standard Python gitignore
├── .hermes/                    # Agent state directory (gitignored)
│   └── plans/                  # Planning documents
└── .planning/                  # GSD planning documents
    └── codebase/               # Codebase analysis documents
```

## Directory Purposes

**`configs/`:**
- Purpose: Declarative YAML configuration files that drive all ticket generation behavior
- Contains: Two subdirectories: `org/` for organization-level configs, `teams/` for team-level configs
- Key files: `configs/org/marketaxess.yaml`, `configs/teams/calcs.yaml`
- Note: Users add new configs here to support new organizations and teams. Each org has one file; each team has one file.

**`jiramator/`:**
- Purpose: Python package containing all application source code (5 modules, ~1,580 lines total)
- Contains: CLI, config models, Jira client, planner orchestration, ticket builder engine
- Key files: `jiramator/planner.py` (434 lines, largest module — orchestration logic), `jiramator/jira_client.py` (376 lines), `jiramator/config.py` (317 lines), `jiramator/ticket_builder.py` (330 lines), `jiramator/cli.py` (120 lines)

**`tests/`:**
- Purpose: Complete test suite (~2,540 lines across 5 test files)
- Contains: Unit tests (config, builder, client), orchestration tests (planner), integration tests (real configs)
- Key files: `tests/test_planner.py` (631 lines), `tests/test_config.py` (611 lines), `tests/test_ticket_builder.py` (537 lines)

**`tests/fixtures/`:**
- Purpose: Reserved directory for test fixture files (currently empty)
- Contains: Nothing yet — test data is inline in test files or uses real config files from `configs/`

## Key File Locations

**Entry Points:**
- `jiramator/cli.py`: Click CLI group and `plan` subcommand — the user-facing entry point
- `jiramator/planner.py:run_plan()`: Internal entry point for the planning flow, called by CLI
- `jiramator/ticket_builder.py:build_all()`: Entry point for ticket payload generation

**Configuration:**
- `pyproject.toml`: Build system (setuptools), Python >=3.11 requirement, dependencies, CLI entrypoint (`jiramator = jiramator.cli:cli`), pytest config
- `configs/org/marketaxess.yaml`: Organization config — Jira URL, credential env var names, custom field IDs, sprint cadence
- `configs/teams/calcs.yaml`: Team config — project key, team name, epic templates, per-release ticket templates, per-sprint ticket templates with long sprint expansion

**Core Logic:**
- `jiramator/config.py`: All Pydantic models (`OrgConfig`, `TeamConfig`, `SprintConfig`, `EpicTemplate`, `TicketTemplate`), YAML loaders (`load_org_config()`, `load_team_config()`), template variable validation
- `jiramator/ticket_builder.py`: Template interpolation (`resolve_value()`), field wrapping for Jira API (`_wrap_field()`, `WRAPPED_FIELDS`), payload builders (`build_epics()`, `build_per_release_tickets()`, `build_per_sprint_tickets()`)
- `jiramator/jira_client.py`: `JiraClient` dataclass with REST API methods (`create_issue()`, `create_issues_bulk()`, `get_fix_versions()`, `create_fix_version()`, `get_board_sprints()`, `get_project()`), `JiraApiError` exception
- `jiramator/planner.py`: Interactive prompt helpers, fix version management, preview display with Rich Tables, epic creation, bulk ticket creation, results display

**Testing:**
- `tests/conftest.py`: Shared fixtures — `org_config_path`, `team_config_path` pointing to real config files
- `tests/test_config.py`: 611 lines — comprehensive config model validation, YAML loading, template vars, epic refs, credential resolution
- `tests/test_ticket_builder.py`: 537 lines — resolve_value, field wrapping, all builder functions, build_all integration
- `tests/test_jira_client.py`: 410 lines — client init, all API methods, error handling edge cases (all HTTP mocked)
- `tests/test_planner.py`: 631 lines — prompt helpers, fix version management, preview display, dry-run flow, full creation flow, sprint handling, error scenarios
- `tests/test_integration.py`: 330 lines — loads real MarketAxess/Calcs configs, runs full build pipeline, verifies exact counts and payloads

## Naming Conventions

**Files:**
- Source modules: `snake_case.py` (e.g. `jira_client.py`, `ticket_builder.py`)
- Test files: `test_<module>.py` pattern matching the source module name (e.g. `test_config.py` for `config.py`)
- Config files: `<name>.yaml` — org configs named after the organization, team configs named after the team

**Directories:**
- All lowercase, no separators (e.g. `configs/`, `tests/`)
- Config subdirectories reflect hierarchy: `configs/org/`, `configs/teams/`

## Where to Add New Code

**New CLI Subcommand:**
- Add the command function in `jiramator/cli.py` using `@cli.command()` decorator
- If the subcommand has significant logic, create a dedicated orchestrator module (like `planner.py`) and call it from the CLI command
- Tests: `tests/test_<subcommand>.py`

**New Team Configuration:**
- Create YAML file at `configs/teams/<team_name>.yaml`
- Follow the structure of `configs/teams/calcs.yaml`
- The file is validated at load time by `TeamConfig` Pydantic model — no code changes needed

**New Organization Configuration:**
- Create YAML file at `configs/org/<org_name>.yaml`
- Follow the structure of `configs/org/marketaxess.yaml`
- The file is validated at load time by `OrgConfig` Pydantic model — no code changes needed

**New Ticket Template Type (beyond per-release / per-sprint):**
- Add a new `list[TicketTemplate]` field to `TeamConfig` in `jiramator/config.py`
- Add a corresponding `build_per_<type>_tickets()` function in `jiramator/ticket_builder.py`
- Add the new category to `build_all()` return dict in `jiramator/ticket_builder.py`
- Handle the new category in `planner.py` (preview display, creation, results)
- Tests in `tests/test_config.py`, `tests/test_ticket_builder.py`, `tests/test_planner.py`

**New Jira API Operation:**
- Add the method to `JiraClient` in `jiramator/jira_client.py`
- Follow existing patterns: use `self._url()`, `self._session`, `self._handle_error()`, `_DEFAULT_TIMEOUT`
- Tests in `tests/test_jira_client.py` using `_mock_response()` helper

**New Template Variable:**
- Add to `KNOWN_TEMPLATE_VARS` frozenset in `jiramator/config.py`
- Provide the value in the `variables` dict construction in `jiramator/ticket_builder.py:build_all()`
- If it's context-specific (like `version` for per-release), set it in the appropriate builder function

**Utilities / Shared Helpers:**
- Currently, shared code lives in the module where it's most relevant (e.g. regex patterns in `config.py`)
- No separate `utils.py` exists — if one is needed, create it at `jiramator/utils.py`
- Pure helper functions (no dependencies on config models) are good candidates for a utils module

## Special Directories

**`jiramator.egg-info/`:**
- Purpose: Generated package metadata from `pip install -e .`
- Generated: Yes (by setuptools)
- Committed: No (gitignored via `*.egg-info/`)

**`.hermes/`:**
- Purpose: Agent state and planning documents
- Generated: Yes
- Committed: No (gitignored)

**`.planning/`:**
- Purpose: GSD codebase analysis documents
- Generated: Yes (by analysis tools)
- Committed: Up to user preference

**`.pytest_cache/`:**
- Purpose: Pytest cache for incremental test runs
- Generated: Yes
- Committed: No (gitignored)

**`tests/fixtures/`:**
- Purpose: Reserved for test fixture files
- Generated: No
- Committed: Yes (but currently empty — tests use inline data or real config files)

---

*Structure analysis: 2026-04-15*
