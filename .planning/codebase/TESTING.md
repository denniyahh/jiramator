---
last_mapped_commit: 8c96e59b775dcea4aaa6a50e976c76a64e447907
last_mapped_at: 2026-09-28
---
# Testing Patterns

**Analysis Date:** 2026-09-28

## Test Framework

**Runner:**

- `pytest` >= 8.0, configured in `pyproject.toml`:
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  pythonpath = ["."]
  ```
- `pytest-mock` >= 3.12 is an available dev dependency, but most tests use stdlib `unittest.mock` (`MagicMock`, `patch`) and pytest's built-in `monkeypatch` fixture directly rather than `pytest-mock`'s `mocker` fixture.

**Assertion Library:**

- Plain `assert` statements (pytest's rewritten assertions) — no `unittest.TestCase` assertion methods, no third-party assertion library.

**Run Commands:**

```bash
python -m pytest -v                                          # all tests, verbose
python -m pytest tests/test_config.py                        # single file
python -m pytest -k "TestBuildEpics"                          # single class/test by name
python -m pytest --cov=jiramator --cov-report=term-missing    # with coverage
python -m pytest -q                                            # CI's invocation (quiet)
```

## Test File Organization

**Location:**

- Fully separated from source: all tests live under `tests/`, mirroring `jiramator/` module names, not co-located with source files.

**Naming:**

- One test file per source module: `tests/test_<module>.py` ↔ `jiramator/<module>.py` (e.g. `tests/test_jira_client.py` ↔ `jiramator/jira_client.py`).
- Additional scenario-focused files split out large or distinct concerns from a single module: `tests/test_planner.py`, `tests/test_planner_report.py`, `tests/test_planner_sprint.py` all test `jiramator/planner.py` from different angles. Same pattern for `test_importer.py`/`test_importer_report.py`, `test_ticket_builder.py`/`test_ticket_builder_strip_lines.py`.
- Cross-module behavior gets its own explicitly-named integration file: `tests/test_integration.py` (config + ticket_builder, no Jira), `tests/test_import_integration.py`, `tests/test_config_inheritance_integration.py`, `tests/test_cli_e2e.py`.

**Structure:**

```
tests/
├── __init__.py
├── conftest.py                          # shared path fixtures (org_config_path, team_config_path)
├── fixtures/
│   └── teams/calcs.yaml                 # tracked stand-in for gitignored configs/teams/
├── test_cli.py                          # CLI flag parsing/error handling (unit, mocked internals)
├── test_cli_e2e.py                      # CLI end-to-end
├── test_config.py                       # Pydantic config model validation
├── test_config_inheritance_integration.py
├── test_config_loader_errors.py
├── test_config_merge.py
├── test_integration.py                  # real configs/org.example + fixtures/teams/calcs.yaml, no mocking
├── test_import_integration.py
├── test_importer.py / test_importer_report.py
├── test_jira_client.py                  # all HTTP mocked
├── test_planner.py / test_planner_report.py / test_planner_sprint.py
├── test_ticket_builder.py / test_ticket_builder_strip_lines.py
├── test_updater.py
├── test_wizard.py                       # Rich prompts + JiraClient mocked
└── ... (one file per remaining module: encoding, error_format, field_resolver,
        payload_validator, run_report, spreadsheet, value_coercion, yaml_loader)
```

## Test Structure

**Suite Organization:**

```python
"""Tests for the Jira REST API client.

All HTTP calls are mocked — no real Jira API traffic.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from jiramator.config import OrgConfig
from jiramator.jira_client import JiraApiError, JiraClient, _BULK_BATCH_SIZE

# ---------------------------------------------------------------------------

# Fixtures

# ---------------------------------------------------------------------------

@pytest.fixture()
def org_config() -> OrgConfig:
    """A minimal org config for testing."""
    ...

# ---------------------------------------------------------------------------

# Client initialization

# ---------------------------------------------------------------------------

class TestClientInit:
    """Test client construction and credential resolution."""

    def test_creates_session_with_auth(self, client: JiraClient, org_config: OrgConfig) -> None:
        assert client._session.auth == ("test@example.com", "fake-token-12345")

    def test_missing_credentials_raises(self, org_config, monkeypatch) -> None:
        ...
```

**Naming conventions (from CLAUDE.md, verified in source):**

- Test classes: `Test<ComponentName>` grouping related behaviors (e.g. `TestClientInit`, `TestBuildEpics`).
- Test functions: `test_<behavior>_<expected_result>` — describes the scenario and the assertion, e.g. `test_missing_jira_url_raises`, `test_409_conflict_fetches_existing`, `test_strips_trailing_slash_from_url`.

**Patterns:**

- File-level module docstring states what is/isn't mocked in that file (e.g. "All HTTP calls are mocked — no real Jira API traffic.").
- Section-divider comments (`# --- Section Name ---`) group fixtures separately from test classes, and group test classes by feature area within a file.
- Fixtures used only by one file live at the top of that file; fixtures shared across many files (`org_config_path`, `team_config_path`) live in `tests/conftest.py`.

## Mocking

**Framework:** `unittest.mock` (`MagicMock`, `patch`) plus pytest's `monkeypatch` fixture. `pytest-mock` is installed but rarely used directly.

**Patterns:**

Mocking HTTP (`tests/test_jira_client.py`):

```python
def _mock_response(status_code: int = 200, json_data: Any = None, ok: bool | None = None) -> MagicMock:
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = ok if ok is not None else (200 <= status_code < 300)
    resp.json.return_value = json_data or {}
    return resp

# In a test:

client._session.get = MagicMock(return_value=_mock_response(409, {"errors": {...}}))
```

Mocking Rich interactive prompts (`tests/test_wizard.py`):

```python
@patch("jiramator.wizard.Prompt.ask")
@patch("jiramator.wizard.IntPrompt.ask")
@patch("jiramator.wizard.JiraClient")
def test_something(self, mock_jira_cls, mock_int, mock_prompt, console, tmp_path, monkeypatch):
    monkeypatch.setattr("jiramator.wizard.os.environ", {})
    mock_client = MagicMock()
    mock_jira_cls.return_value = mock_client
    ...
```

Mocking env vars:

```python
monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
monkeypatch.setenv("JIRA_TOKEN", "fake-token-12345")
monkeypatch.delenv("JIRA_TOKEN", raising=False)
```

Stubbing internal call sites for CLI wiring tests (`tests/test_cli.py`), recording invocation args instead of asserting on a `MagicMock`'s call log:

```python
@pytest.fixture
def stub_run_plan(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``jiramator.cli.run_plan`` with a recorder that captures kwargs."""
    captured: dict[str, Any] = {}

    def _recorder(*args: Any, **kwargs: Any) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr("jiramator.cli.run_plan", _recorder)
    return captured
```

Custom fake/test-double instead of MagicMock, when call ordering/state matters (`tests/test_planner_report.py`):

```python
"""Uses an inline FakeJiraClient (test double, not MagicMock) so we can:

  - record create_issue/create_issues_bulk calls and assert no _template_key leaks
  - inject failures after the Nth call to test partial-state persistence
  - simulate KeyboardInterrupt mid-run to verify atomic write under signal

"""
```

CLI end-to-end testing uses Click's own test harness:

```python
from click.testing import CliRunner

@pytest.fixture
def runner() -> CliRunner:
    # Click 8.2+ separates stderr/stdout by default; mix_stderr was removed
    return CliRunner()
```

**What to Mock:**

- HTTP calls: replace `client._session.get` / `.post` with a `MagicMock` returning `_mock_response(status_code, json_data)`.
- Rich interactive prompts: `@patch("jiramator.planner.Confirm.ask")`, `@patch("jiramator.wizard.Prompt.ask")`, etc.
- Environment variables: `monkeypatch.setenv` / `.delenv`.
- Internal orchestration functions when testing a thinner layer around them (e.g. `cli.py` tests stub `run_plan`/`run_import` rather than exercising the full planner).

**What NOT to Mock (explicit project rule, from CLAUDE.md):**

- Do not mock Pydantic validation — exercise `OrgConfig`/`TeamConfig` with real inputs and let real validators run.
- Do not mock YAML config loading — use real files (`configs/org.example/`, `tests/fixtures/teams/calcs.yaml`) or `tmp_path`-written YAML.
- Do not mock ticket-builder logic — call `build_all()`/`build_epics()` for real and assert on the resulting payload structures/counts.

## Fixtures and Factories

**Test Data:**

- Shared path fixtures in `tests/conftest.py`:
  ```python
  @pytest.fixture
  def org_config_path():
      """Path to the example org config."""
      return CONFIGS_DIR / "org.example" / "example.yaml"

  @pytest.fixture
  def team_config_path():
      """Path to the Calcs team config fixture.

      Lives under tests/fixtures/ (tracked) rather than configs/teams/
      (gitignored, personal/team-specific) so the test suite is reproducible
      on a fresh clone regardless of local config state.
      """
      return FIXTURES_DIR / "teams" / "calcs.yaml"
  ```
- Per-file fixtures (e.g. `org_config`, `client`) are declared at the top of each test file, scoped to that file's needs — not centralized unless used across multiple files.
- `tests/test_integration.py` uses `scope="module"` fixtures to build the real config objects once per module (parses `configs/org.example/example.yaml` + `tests/fixtures/teams/calcs.yaml`), then asserts exact ticket/payload counts as a regression guard — deliberately update these counts when the fixture's structure changes, don't silently adjust them.

**Location:**

- `tests/fixtures/` holds tracked, stable stand-ins for gitignored real configs (`tests/fixtures/teams/calcs.yaml` mirrors the real Calcs team's `configs/teams/` file structure so the suite is reproducible on a fresh clone).

## Coverage

**Requirements:** No coverage threshold enforced in CI — `pytest-cov` is not even a declared dependency in `pyproject.toml`'s `dev` extras; `--cov` usage is developer-invoked only (see CLAUDE.md command list). If `pytest-cov` isn't installed locally, install it ad hoc (`pip install pytest-cov`) before running the coverage command.

**View Coverage:**

```bash
python -m pytest --cov=jiramator --cov-report=term-missing
```

## Test Types

**Unit Tests:**

- Most files are unit tests scoped to a single module, with all cross-module collaborators mocked (e.g. `test_jira_client.py` mocks the `requests.Session`, `test_wizard.py` mocks `JiraClient` and Rich prompts).

**Integration Tests:**

- `tests/test_integration.py`: real config parsing (`load_org_config`/`load_team_config`) + real `ticket_builder.build_all()`/`build_epics()` against shipped example configs — no Jira API involved, exact payload-count assertions.
- `tests/test_import_integration.py`, `tests/test_config_inheritance_integration.py`: same "real config, real transform logic, mocked I/O boundary only" philosophy applied to `import`/config-layering flows.
- `tests/test_cli_e2e.py`: exercises the CLI command surface more end-to-end than `test_cli.py`'s wiring-only unit tests.

**E2E Tests:**

- No browser/UI E2E framework (this is a CLI tool). "E2E" here means full CLI invocation via `CliRunner` down through real config loading and ticket building, with only the Jira HTTP boundary mocked/absent. See `.github/workflows/jiramator-plan.yml` for a GitHub Actions–driven manual dry-run spike that exercises the packaged CLI in `preview` mode as a human-facing E2E smoke test (not part of the pytest suite).

## Common Patterns

**Async Testing:**

- Not applicable — the codebase is fully synchronous (no `asyncio` usage found in `jiramator/` or `tests/`).

**Error Testing:**

```python

# Generic exception with a class-based inline comment noting the real Pydantic type:

with pytest.raises(Exception):  # ValidationError
    OrgConfig(...)

# Precise exception + message substring match:

with pytest.raises(ValueError, match="out of range"):
    SprintConfig(count=1, standard_length_weeks=2, long_length_weeks=3, long_sprints=[99])
```

- HTTP error paths assert on `JiraApiError.status_code` / `.errors` directly rather than just message text, since those attributes carry the structured Jira response detail callers depend on.
- CLI error paths assert on `result.exit_code` and `result.output` (via Click's `CliRunner`) rather than catching exceptions directly, matching the "CLI exits 1 with a printed message" convention from CONVENTIONS.md.

---

*Testing analysis: 2026-09-28*
