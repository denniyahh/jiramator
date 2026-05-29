# Copilot Instructions

## Build & Install

```bash
pip install -e ".[dev]"
```

## Tests

```bash
python -m pytest -v                          # all tests
python -m pytest tests/test_config.py        # single file
python -m pytest -k "TestBuildEpics"         # single class
python -m pytest --cov=jiramator --cov-report=term-missing  # with coverage
```

No linter or formatter is configured.

## Architecture

Five-layer design with strict separation of concerns:

| Layer | File | Role |
|---|---|---|
| CLI | `jiramator/cli.py` | Argument parsing, config loading, error display — thin shell |
| Config | `jiramator/config.py` | Pydantic models for org/team YAML; all validation happens here |
| Builder | `jiramator/ticket_builder.py` | Pure data transformation — no I/O, no side effects |
| Client | `jiramator/jira_client.py` | All HTTP communication with Jira REST API |
| Planner | `jiramator/planner.py` | Orchestrates the interactive PI planning flow |

**Data flow:** `cli.py` loads configs → hands off to `planner.run_plan()` → calls `ticket_builder.build_all()` twice (once for preview with empty epic keys, once with real Jira keys after epics are created) → uses `JiraClient` for all API calls.

**Two-tier config model:** Local org config (`configs/org/`, gitignored) holds Jira URL, custom field IDs, sprint cadence. Shipped org examples live in `configs/org.example/`. Team config (`configs/teams/`) holds project key, epic definitions, and ticket templates. Both are Pydantic models loaded via `load_org_config()` / `load_team_config()`.

## Key Conventions

**Imports:** Every source file starts with `from __future__ import annotations` (enables modern union syntax `int | None`). Use explicit `from jiramator.x import Y` imports — no wildcard imports, no barrel files.

**Type annotations:** All function signatures are fully annotated. Use lowercase generics (`dict[str, Any]`, `list[str]`) enabled by the future import. Void functions always annotate `-> None`.

**Private symbols:** Prefix with `_` for private functions (`_wrap_field`, `_build_fields_payload`) and private constants (`_RETRY_STRATEGY`, `_TEMPLATE_VAR_RE`). Public constants use `UPPER_SNAKE_CASE`.

**User-facing output:** Use `rich.console.Console(stderr=True)` everywhere — never `print()`, never `logging` outside `jira_client.py`. `logging` is reserved for the Jira client layer only (operational traceability).

**Error handling:** Raise `ValueError` with actionable messages from config validators. `JiraApiError` wraps all HTTP errors. `sys.exit(1)` after printing a Rich error message for unrecoverable CLI errors.

**Docstrings:** Google-style (`Args:`, `Returns:`, `Raises:`) on all public functions and classes. Module-level docstrings explain purpose and responsibilities.

**Section dividers** in source and test files:
```python
# ---------------------------------------------------------------------------
# Section Name
# ---------------------------------------------------------------------------
```

**Pydantic patterns:** Use `Field(description=...)` on all model fields. Use `@field_validator` with `@classmethod` for single-field validation, `@model_validator(mode="after")` for cross-field validation. Validators raise `ValueError` with descriptive messages.

**CLI patterns:** `@click.Path(exists=True, path_type=Path)` for file arguments. Rich console for all output.

## Testing Conventions

Test classes are named `Test<ComponentName>`, test functions follow `test_<behavior>_<expected_result>` (e.g., `test_missing_jira_url_raises`, `test_409_conflict_fetches_existing`).

- **Mock HTTP** by replacing `client._session.get` / `client._session.post` with `MagicMock` returning `_mock_response(status_code, json_data)`.
- **Mock Rich prompts** with `@patch("jiramator.planner.Confirm.ask")` etc.
- **Mock env vars** with pytest `monkeypatch.setenv` / `monkeypatch.delenv`.
- **Do not mock** Pydantic validation, config YAML loading, or ticket builder logic — test those with real inputs.
- Integration tests in `test_integration.py` use the shipped `configs/org.example/example.yaml` and `configs/teams/calcs.yaml` via `scope="module"` fixtures. Exact ticket counts (2 epics, 18 per-release, 7 per-sprint = 27 total) are asserted.

Per-file fixtures are defined at the top of each test file. Shared path fixtures live in `tests/conftest.py`.

## Template & Epic Reference System

Template variables (`{pi_label}`, `{version}`, `{sprint_num}`, `{team_name}`, `{pi_num}`) are validated at config parse time via `_TEMPLATE_VAR_RE` and interpolated at build time in `ticket_builder.resolve_value()`.

Epic references (`$epic:<key>`) in ticket field values are resolved to real Jira issue keys after epics are created. In dry-run mode they remain as literal strings. This two-phase resolution is why `build_all()` is called twice.

## Credentials

Never stored in config files. Always read from environment variables (`JIRA_EMAIL`, `JIRA_TOKEN` by default; overridable per-org config via `jira_email_env` / `jira_token_env`).
