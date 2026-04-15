# Testing Patterns

**Analysis Date:** 2026-04-15

## Test Framework

**Runner:**
- pytest >= 8.0
- Config: `pyproject.toml` `[tool.pytest.ini_options]`

**Assertion Library:**
- pytest native assertions (no third-party assertion library)

**Mocking:**
- `pytest-mock` >= 3.12 (available but tests use `unittest.mock` directly)
- `unittest.mock.MagicMock`, `unittest.mock.patch`

**Run Commands:**
```bash
python -m pytest -v          # Run all tests (verbose)
python -m pytest             # Run all tests (quiet)
python -m pytest tests/test_config.py  # Run single file
python -m pytest -k "TestBuildEpics"   # Run by class name
```

## Test File Organization

**Location:**
- Separate `tests/` directory at project root (not co-located with source)
- Test path configured in `pyproject.toml`: `testpaths = ["tests"]`
- Python path includes project root: `pythonpath = ["."]`

**Naming:**
- Test files: `test_<module_name>.py` mirroring source module names
- Test classes: `Test<ComponentName>` with PascalCase
- Test functions: `test_<behavior_description>` with snake_case

**Structure:**
```
tests/
    __init__.py             # Empty (marks as package)
    conftest.py             # Shared fixtures (paths to config files)
    fixtures/               # Empty directory (reserved for future test data)
    test_config.py          # Tests for jiramator/config.py (167 tests)
    test_ticket_builder.py  # Tests for jiramator/ticket_builder.py
    test_jira_client.py     # Tests for jiramator/jira_client.py
    test_planner.py         # Tests for jiramator/planner.py
    test_integration.py     # End-to-end tests with real config files
```

**File-to-Source Mapping:**
| Test File | Source File | Focus |
|-----------|------------|-------|
| `tests/test_config.py` | `jiramator/config.py` | Pydantic models, validation, YAML loading |
| `tests/test_ticket_builder.py` | `jiramator/ticket_builder.py` | Template resolution, field wrapping, payload generation |
| `tests/test_jira_client.py` | `jiramator/jira_client.py` | HTTP client, error handling, pagination |
| `tests/test_planner.py` | `jiramator/planner.py` | Orchestration flow, prompts, creation logic |
| `tests/test_integration.py` | All modules | End-to-end with real YAML configs |

## Test Structure

**Suite Organization:**
- Tests are grouped into classes by component/behavior
- Each class has a descriptive docstring explaining what it tests
- Classes within a file are separated by ASCII section dividers

```python
# ---------------------------------------------------------------------------
# OrgConfig parsing
# ---------------------------------------------------------------------------


class TestOrgConfigParsing:
    """Tests for OrgConfig model validation."""

    def test_valid_config(self, org_config_data: dict) -> None:
        cfg = OrgConfig(**org_config_data)
        assert str(cfg.jira_url) == "https://example.atlassian.net/"
        assert cfg.jira_email_env == "JIRA_EMAIL"

    def test_missing_jira_url_raises(self) -> None:
        with pytest.raises(Exception):
            OrgConfig(sprints={...})
```

**Patterns:**
- Use `pytest.raises(ExceptionType, match="regex pattern")` for error testing
- Use `match=` to verify error message content, not just exception type
- Multiple assertions per test when checking a single logical outcome
- Return type annotations `-> None` on test methods

## Fixtures

**Shared Fixtures (conftest.py):**

`tests/conftest.py` provides path fixtures for real config files:
```python
FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIGS_DIR = Path(__file__).parent.parent / "configs"

@pytest.fixture
def org_config_path():
    """Path to the MarketAxess org config."""
    return CONFIGS_DIR / "org" / "marketaxess.yaml"

@pytest.fixture
def team_config_path():
    """Path to the Calcs team config."""
    return CONFIGS_DIR / "teams" / "calcs.yaml"
```

**Per-File Fixtures:**

Each test file defines its own fixtures inline. Fixtures are defined at the top of the file before test classes.

```python
# From tests/test_config.py
@pytest.fixture
def org_config_data() -> dict:
    """Minimal valid org config data."""
    return {
        "jira_url": "https://example.atlassian.net",
        "jira_email_env": "JIRA_EMAIL",
        "jira_token_env": "JIRA_TOKEN",
        "custom_fields": {"story_points": "customfield_10026"},
        "sprints": {
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    }

@pytest.fixture
def tmp_org_config(tmp_path: Path, org_config_data: dict) -> Path:
    """Write a valid org config YAML to a temp file and return the path."""
    p = tmp_path / "org.yaml"
    p.write_text(yaml.dump(org_config_data))
    return p
```

**Fixture Scoping:**
- Most fixtures use default function scope
- Integration test fixtures use `scope="module"` for expensive config loading:
  ```python
  @pytest.fixture(scope="module")
  def org_config():
      return load_org_config(_ORG_CONFIG_PATH)
  ```

## Mocking

**Framework:** `unittest.mock` (MagicMock, patch)

**Patterns:**

1. **Mock HTTP responses** (for `jiramator/jira_client.py`):
```python
def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    ok: bool | None = None,
) -> MagicMock:
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = ok if ok is not None else (200 <= status_code < 300)
    resp.json.return_value = json_data or {}
    return resp
```

2. **Mock session methods** by replacing `client._session.get` / `client._session.post`:
```python
client._session.post = MagicMock(
    return_value=_mock_response(201, {"key": "CA-101", "id": "50001"})
)
key = client.create_issue(payload)
assert key == "CA-101"
```

3. **Mock Rich prompts** with `@patch` decorator for interactive flow:
```python
@patch("jiramator.planner.Confirm.ask", return_value=True)
@patch("jiramator.planner.Prompt.ask")
@patch("jiramator.planner.IntPrompt.ask")
def test_full_creation(
    self, mock_int_prompt, mock_prompt, mock_confirm, ...
):
    mock_prompt.side_effect = ["28", "26.1.1"]
    mock_int_prompt.return_value = 1
    mock_confirm.side_effect = [True, True]
```

4. **Mock JiraClient** with spec:
```python
@pytest.fixture()
def mock_client() -> MagicMock:
    """A fully mocked JiraClient."""
    client = MagicMock(spec=JiraClient)
    return client
```

5. **Environment variables** via `monkeypatch`:
```python
def test_credentials_from_env(self, org_config_data, monkeypatch):
    monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "secret-token-123")

def test_missing_email_raises(self, org_config_data, monkeypatch):
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
```

**What to Mock:**
- HTTP responses (never make real API calls)
- Rich interactive prompts (`Prompt.ask`, `IntPrompt.ask`, `Confirm.ask`)
- JiraClient construction in planner tests
- Environment variables for credential tests

**What NOT to Mock:**
- Pydantic models and validation (test real validation)
- Config loading from YAML (use `tmp_path` for temp files)
- Ticket builder logic (pure functions, test with real inputs)
- Integration between config -> builder (tested in `test_integration.py`)

## Fixtures and Factories

**Test Data:**
- Config data is constructed as dicts in fixtures, not loaded from JSON/YAML fixture files
- `tests/fixtures/` directory exists but is empty (reserved)
- Real config files at `configs/org/marketaxess.yaml` and `configs/teams/calcs.yaml` are used in integration tests
- `tmp_path` (pytest built-in) used for temp file fixtures

**Location:**
- Per-file fixtures: defined at top of each test file in a `# Fixtures` section
- Shared fixtures: `tests/conftest.py`
- Real config data: `configs/` directory

## Coverage

**Requirements:** No coverage threshold enforced

**Configuration:**
- `.coverage` and `htmlcov/` are in `.gitignore` (coverage tooling expected but not configured)
- No `[tool.coverage]` section in `pyproject.toml`

**Run Coverage:**
```bash
python -m pytest --cov=jiramator --cov-report=term-missing
python -m pytest --cov=jiramator --cov-report=html
```

## Test Types

**Unit Tests (4 files, ~170 tests):**
- `tests/test_config.py`: Pydantic model validation — valid inputs, invalid inputs, edge cases, YAML loading
- `tests/test_ticket_builder.py`: Pure function testing — template resolution, field wrapping, payload generation
- `tests/test_jira_client.py`: HTTP client with mocked responses — success paths, error codes, pagination, batching
- `tests/test_planner.py`: Orchestration with mocked prompts and client — dry-run, full flow, error handling

**Integration Tests (1 file, ~28 tests):**
- `tests/test_integration.py`: Loads real `configs/org/marketaxess.yaml` and `configs/teams/calcs.yaml`, runs the full config parse -> validate -> build pipeline
- Tests exact ticket counts (2 epics, 18 per-release, 7 per-sprint = 27 total)
- Verifies resolved field values (summaries, labels, fixVersions, epic links)
- Tests dry-run mode (empty epic_keys, unresolved references)
- No Jira API calls — only config + builder tested end-to-end

**E2E Tests:**
- Not present. No CLI invocation tests (Click's `CliRunner` is not used)
- The planner's `run_plan()` is tested with mocked prompts and client, which is the closest to E2E

## Common Patterns

**Async Testing:**
- Not applicable (codebase is synchronous)

**Error Testing:**
```python
def test_missing_email_raises(self, org_config_data, monkeypatch):
    monkeypatch.delenv("JIRA_EMAIL", raising=False)
    monkeypatch.setenv("JIRA_TOKEN", "token")
    cfg = OrgConfig(**org_config_data)
    with pytest.raises(ValueError, match="JIRA_EMAIL"):
        cfg.resolve_credentials()
```

**Validation Error Testing:**
```python
def test_long_sprint_out_of_range_raises(self) -> None:
    with pytest.raises(ValueError, match="out of range"):
        SprintConfig(
            count=6,
            standard_length_weeks=2,
            long_length_weeks=3,
            long_sprints=[7],
        )
```

**SystemExit Testing (for CLI abort paths):**
```python
def test_user_aborts_at_confirmation(self, ...):
    mock_confirm.return_value = False
    with pytest.raises(SystemExit):
        run_plan(org_config, team_config, dry_run=False, console=console)
    mock_client.create_issue.assert_not_called()
```

**Parametric Count Verification:**
```python
def test_grand_total(self, all_payloads):
    total = (
        len(all_payloads["epics"])
        + len(all_payloads["per_release"])
        + len(all_payloads["per_sprint"])
    )
    assert total == 27
```

**Multiple Batch Side Effects:**
```python
def test_multiple_batches(self, client):
    batch1_resp = _mock_response(201, {"issues": [...], "errors": []})
    batch2_resp = _mock_response(201, {"issues": [...], "errors": []})
    batch3_resp = _mock_response(201, {"issues": [...], "errors": []})
    client._session.post = MagicMock(
        side_effect=[batch1_resp, batch2_resp, batch3_resp]
    )
    keys = client.create_issues_bulk(payloads, batch_size=3)
    assert client._session.post.call_count == 3
```

## Test Naming Conventions

**Pattern:** `test_<what>_<expected_behavior>` or `test_<scenario>`

Examples from the codebase:
- `test_valid_config` — happy path
- `test_missing_jira_url_raises` — error path (ends with `_raises`)
- `test_epic_ref_unresolved_falls_back` — specific behavior description
- `test_409_conflict_fetches_existing` — HTTP status + behavior
- `test_dry_run_no_client` — mode + assertion
- `test_long_sprint_suffix_count_mismatch_raises` — validation edge case

## Test Count Summary

Total: **198 tests** across 5 test files:

| File | Approximate Tests | Focus |
|------|-------------------|-------|
| `tests/test_config.py` | ~65 | Config models, validation, YAML loading |
| `tests/test_ticket_builder.py` | ~40 | Template resolution, field wrapping, builders |
| `tests/test_jira_client.py` | ~30 | HTTP client, error handling, pagination |
| `tests/test_planner.py` | ~35 | Orchestration flow, prompts, creation |
| `tests/test_integration.py` | ~28 | End-to-end with real configs |

---

*Testing analysis: 2026-04-15*
