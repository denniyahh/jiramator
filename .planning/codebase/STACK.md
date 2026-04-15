# Technology Stack

**Analysis Date:** 2026-04-15

## Languages

**Primary:**
- Python >=3.11 — All application code, CLI, tests

**Secondary:**
- YAML — Configuration files (`configs/org/*.yaml`, `configs/teams/*.yaml`)

## Runtime

**Environment:**
- Python 3.11+ (specified in `pyproject.toml` `requires-python = ">=3.11"`)
- No `.python-version` file detected — version management is left to the developer

**Package Manager:**
- pip via setuptools (build-backend: `setuptools.build_meta`)
- Lockfile: **missing** — no `requirements.txt`, `pip.lock`, or `poetry.lock` present. Dependencies are pinned only by minimum version in `pyproject.toml`.

## Frameworks

**Core:**
- Click 8.1+ — CLI framework (`jiramator/cli.py`). Provides command groups, argument parsing, options, and `--version` support.
- Pydantic 2.0+ — Config validation and data modeling (`jiramator/config.py`). All org and team configs are Pydantic `BaseModel` subclasses with field validators and model validators.

**Testing:**
- pytest 8.0+ — Test runner and assertion framework
- pytest-mock 3.12+ — Mocking integration for pytest

**Build/Dev:**
- setuptools 75.0+ — Build system (`pyproject.toml` `[build-system]`)
- Package installs as editable: `pip install -e ".[dev]"`

## Key Dependencies

**Critical:**
- `click` 8.1+ — Entire CLI interface; entrypoint registered as `jiramator = "jiramator.cli:cli"` in `[project.scripts]`
- `pydantic` 2.0+ — Config schema validation, template variable validation, epic reference validation. Uses `BaseModel`, `Field`, `HttpUrl`, `field_validator`, `model_validator`
- `requests` 2.31+ — All Jira REST API communication (`jiramator/jira_client.py`). Uses `Session`, `HTTPAdapter`, basic auth, retry strategy
- `pyyaml` 6.0+ — YAML config file parsing via `yaml.safe_load()` in `jiramator/config.py`
- `rich` 13.0+ — Terminal output: `Console`, `Table`, `Prompt`, `IntPrompt`, `Confirm` used in `jiramator/cli.py` and `jiramator/planner.py`

**Infrastructure:**
- `urllib3` (transitive via requests) — Retry strategy configuration (`urllib3.util.retry.Retry`) in `jiramator/jira_client.py`

## Configuration

**Environment:**
- Credentials are read from environment variables at runtime, never from config files
- Default env var names: `JIRA_EMAIL`, `JIRA_TOKEN` (overridable per org config via `jira_email_env` / `jira_token_env` fields in `configs/org/*.yaml`)
- Credential resolution happens in `OrgConfig.resolve_credentials()` in `jiramator/config.py`

**Build:**
- `pyproject.toml` — Single build/project config file (PEP 621 compliant)
- `[tool.pytest.ini_options]` — pytest config embedded in `pyproject.toml` (`testpaths = ["tests"]`, `pythonpath = ["."]`)
- `[tool.setuptools.packages.find]` — Package discovery configured to include `jiramator*`

**Application Config (YAML):**
- Org config: `configs/org/*.yaml` — Jira URL, credential env var names, custom field mappings, sprint cadence
- Team config: `configs/teams/*.yaml` — Project key, team name, epic templates, ticket templates
- Config loading: `load_org_config()` and `load_team_config()` in `jiramator/config.py`

## Platform Requirements

**Development:**
- Python 3.11+
- pip (for editable install)
- Environment variables: `JIRA_EMAIL`, `JIRA_TOKEN` (only needed for live runs, not dry-run or tests)

**Production:**
- CLI tool — runs locally on developer machines
- No server, container, or deployment infrastructure
- No Dockerfile, CI/CD pipeline, or hosting config detected
- Installed as a Python package with console script entrypoint `jiramator`

---

*Stack analysis: 2026-04-15*
