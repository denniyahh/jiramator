---
last_mapped_commit: 8c96e59b775dcea4aaa6a50e976c76a64e447907
last_mapped_at: 2026-09-28
---
# Technology Stack

**Analysis Date:** 2026-09-28

## Languages

**Primary:**

- Python ≥3.11 (declared in `pyproject.toml` `requires-python`) - entire codebase, package `jiramator/`
- CI matrix tests against 3.11, 3.12, 3.13 (`.github/workflows/ci.yml`); local dev environment observed running Python 3.14.0

**Secondary:**

- YAML - configuration format for org/team configs (`configs/org.example/`, `configs/teams/`, loaded via `jiramator/yaml_loader.py`)
- Bash - CI/workflow scripting (`.github/workflows/*.yml`), `scripts/` directory

## Runtime

**Environment:**

- CPython, no async runtime — synchronous, single-process CLI
- No containerization (no `Dockerfile` present)

**Package Manager:**

- `pip` with `setuptools` build backend (`pyproject.toml` → `[build-system] requires = ["setuptools>=75.0"]`)
- No lockfile present (no `requirements.txt`, `poetry.lock`, or `uv.lock`) — dependency versions are range-pinned in `pyproject.toml` only
- Installed editable in CI/dev via `pip install -e ".[dev]"`

## Frameworks

**Core:**

- `click` ≥8.1 - CLI framework; command group defined in `jiramator/cli.py` (`@click.group()` → `cli`, subcommands `plan`, `import`, `update`)
- `pydantic` ≥2.0 - config schema validation/parsing throughout `jiramator/config.py` (`OrgConfig`, `TeamConfig`, `SprintConfig`, `EpicTemplate`, `TicketTemplate`, etc.)
- `rich` ≥13.0 - terminal output formatting/progress (used in `jiramator/cli.py`, `jiramator/wizard.py`, `jiramator/planner.py`, `jiramator/spreadsheet.py`, `jiramator/config.py`, `jiramator/config_merge.py`, `jiramator/payload_validator.py`, `jiramator/ticket_builder.py`)

**Testing:**

- `pytest` ≥8.0 - test runner, config in `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["."]`)
- `pytest-mock` ≥3.12 - mocking fixtures used across `tests/`

**Build/Dev:**

- `setuptools` ≥75.0 - build backend, package discovery via `[tool.setuptools.packages.find] include = ["jiramator*"]`
- No separate lint/format tool config detected (no `.eslintrc`, `.prettierrc`, `ruff.toml`, or `pyproject.toml` `[tool.ruff]`/`[tool.black]` section found)

## Key Dependencies

**Critical:**

- `requests` ≥2.31,<none-pinned-upper - HTTP client for all Jira REST API calls, wrapped in `jiramator/jira_client.py` (`JiraClient` class using `requests.Session`)
- `urllib3` (transitive via `requests`) - `Retry` strategy imported directly in `jiramator/jira_client.py` (`from urllib3.util.retry import Retry`) for automatic retry on 429/502/503/504
- `pyyaml` ≥6.0 - YAML parsing for org/team config files, `jiramator/yaml_loader.py`
- `openpyxl` ≥3.1 - reads `.xlsx` spreadsheets for the `import`/`update` commands, `jiramator/spreadsheet.py`
- `charset-normalizer` ≥3,<4 - encoding auto-detection for CSV imports, `jiramator/encoding.py` (`detect_encoding`)

**Infrastructure:**

- None (no database, cache, or message queue clients) — Jiramator is a stateless CLI that talks directly to the Jira REST API and reads/writes local files only

## Configuration

**Environment:**

- Jira credentials are resolved from environment variables at runtime, not hardcoded: env var *names* are configurable per-org via `jira_email_env` / `jira_token_env` fields in `OrgConfig` (`jiramator/config.py`), defaulting to `JIRA_EMAIL` / `JIRA_TOKEN`
- `OrgConfig.resolve_credentials()` (`jiramator/config.py`) reads and validates both are present, raising `ValueError` listing missing vars
- Optional TLS-compatibility env vars for corporate proxies, read in `jiramator/jira_client.py`:
  - `JIRAMATOR_CA_BUNDLE` - path to alternate CA bundle
  - `JIRAMATOR_RELAX_TLS_STRICT` - relaxes `ssl.VERIFY_X509_STRICT` for non-conformant intercepting CAs
- `.envrc` present (direnv) — only switches local `gh` CLI account identity, not app secrets; `.envrc` itself is gitignored
- No `.env` file present in repo (gitignored via `.gitignore` pattern `.env`)

**Build:**

- `pyproject.toml` - single source of truth for dependencies, build system, CLI entry point (`[project.scripts] jiramator = "jiramator.cli:cli"`), and pytest config
- No `tsconfig.json`/JS build config (project is pure Python)

**App config (YAML, not secrets):**

- Two-tier config model: org-level (`configs/org.example/`, real org configs gitignored under `configs/org/`) and team-level (`configs/teams/`, gitignored; example fixtures under `tests/fixtures/teams/`)
- Config loading/merging logic: `jiramator/config.py`, `jiramator/config_merge.py`, `jiramator/yaml_loader.py`

## Platform Requirements

**Development:**

- Python ≥3.11 interpreter
- `pip install -e ".[dev]"` for editable install with test dependencies
- Cross-platform: CI matrix explicitly tests `ubuntu-latest`, `windows-latest`, `macos-latest` (`.github/workflows/ci.yml`)

**Production:**

- No hosted deployment target — Jiramator is distributed/run as a local CLI tool (`jiramator` console script) or invoked non-interactively from a GitHub Actions workflow_dispatch form (`.github/workflows/jiramator-plan.yml`, marked as a spike/prototype)
- Network egress required to reach the configured Jira Cloud instance (`jira_url` in org config) over HTTPS

---

*Stack analysis: 2026-09-28*
