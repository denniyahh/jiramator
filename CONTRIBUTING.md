# Contributing to Jiramator

Thanks for your interest in improving Jiramator! This doc covers everything
needed to develop, test, and extend the codebase. If you're looking for
day-to-day *usage* instructions instead, see [README.md](README.md).

## Development setup

**Prerequisites:** Python 3.11–3.13.

```bash
git clone https://github.com/dkim_mktx/jiramator.git && cd jiramator

# Recommended: a dedicated virtualenv for this repo, separate from any
# personal Jiramator instance you may also have installed
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Editable install with dev dependencies (pytest, pytest-mock)
pip install -e ".[dev]"
```

`pip install -e ".[dev]"` is only for people modifying the source or running
the test suite — end users only need `pip install -e .` (see the README's
[Quick Start](README.md#quick-start)).

## Running tests

```bash
python -m pytest -v                                          # all tests
python -m pytest tests/test_config.py                        # single file
python -m pytest -k "TestBuildEpics"                          # single class
python -m pytest --cov=jiramator --cov-report=term-missing    # with coverage
```

Run the full suite after changing config, import, coercion, or Jira client
behavior. The exact test count changes over time; rely on pytest's own output
rather than any hardcoded number in the docs.

No linter or formatter is currently configured for this project.

### Testing conventions

- Test classes are named `Test<ComponentName>`; test functions follow
  `test_<behavior>_<expected_result>` (e.g. `test_missing_jira_url_raises`,
  `test_409_conflict_fetches_existing`).
- **Mock HTTP** by replacing `client._session.get` / `client._session.post`
  with a `MagicMock` returning `_mock_response(status_code, json_data)`.
- **Mock Rich prompts** with e.g. `@patch("jiramator.planner.Confirm.ask")`.
- **Mock env vars** with pytest's `monkeypatch.setenv` / `monkeypatch.delenv`.
- **Do not mock** Pydantic validation, config YAML loading, or ticket builder
  logic — test those with real inputs.
- `tests/test_integration.py` exercises the shipped example configs
  (`configs/org.example/example.yaml`, `tests/fixtures/teams/calcs.yaml`) via
  `scope="module"` fixtures, and asserts exact ticket counts. If you change
  the fixture's structure, update those assertions deliberately — they're a
  regression guard, not incidental.
- Per-file fixtures live at the top of each test file; shared path fixtures
  live in `tests/conftest.py`.

## Continuous integration

Every push and pull request runs the full test suite on Linux, macOS, and
Windows against Python 3.11, 3.12, and 3.13 — see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml). CI installs with
`pip install -e ".[dev]"` and runs `python -m pytest -q`.

## Architecture

Five-layer design with strict separation of concerns:

| Layer | File | Role |
|---|---|---|
| CLI | `jiramator/cli.py` | Argument parsing, config loading, error display — thin shell |
| Config | `jiramator/config.py` | Pydantic models for org/team YAML; all validation happens here |
| Builder | `jiramator/ticket_builder.py` | Pure data transformation — no I/O, no side effects |
| Client | `jiramator/jira_client.py` | All HTTP communication with the Jira REST API |
| Planner | `jiramator/planner.py` | Orchestrates the interactive PI planning flow |

**Data flow:** `cli.py` loads configs → hands off to `planner.run_plan()` →
calls `ticket_builder.build_all()` twice (once for preview with empty epic
keys, once with real Jira keys after epics are created) → uses `JiraClient`
for all API calls.

**Two-tier config model:** `configs/org/` and `configs/teams/` (both
gitignored) hold real, local configuration — Jira URL, custom field IDs,
sprint cadence, project keys, ticket templates. `configs/org.example/` and
`configs/teams.example/` (both tracked) ship generic, secret-free starting
points. Both tiers are Pydantic models loaded via `load_org_config()` /
`load_team_config()`.

## Code conventions

- **Imports:** every source file starts with `from __future__ import
  annotations` (enables modern union syntax like `int | None`). Use explicit
  `from jiramator.x import Y` imports — no wildcard imports, no barrel files.
- **Type annotations:** all function signatures are fully annotated, using
  lowercase generics (`dict[str, Any]`, `list[str]`). Void functions always
  annotate `-> None`.
- **Private symbols:** prefix with `_` for private functions (`_wrap_field`,
  `_build_fields_payload`) and private constants (`_RETRY_STRATEGY`,
  `_TEMPLATE_VAR_RE`). Public constants use `UPPER_SNAKE_CASE`.
- **User-facing output:** use `rich.console.Console(stderr=True)` everywhere —
  never `print()`, never `logging` outside `jira_client.py`. `logging` is
  reserved for the Jira client layer only (operational traceability).
- **Error handling:** raise `ValueError` with actionable messages from config
  validators. `JiraApiError` wraps all HTTP errors. `sys.exit(1)` after
  printing a Rich error message for unrecoverable CLI errors.
- **Docstrings:** Google-style (`Args:`, `Returns:`, `Raises:`) on all public
  functions and classes. Module-level docstrings explain purpose and
  responsibilities.
- **Section dividers** in source and test files:
  ```python
  # ---------------------------------------------------------------------------
  # Section Name
  # ---------------------------------------------------------------------------
  ```
- **Pydantic patterns:** use `Field(description=...)` on all model fields. Use
  `@field_validator` with `@classmethod` for single-field validation,
  `@model_validator(mode="after")` for cross-field validation. Validators
  raise `ValueError` with descriptive messages.
- **CLI patterns:** `@click.Path(exists=True, path_type=Path)` for file
  arguments. Rich console for all output.

A more detailed version of these conventions (kept in sync for AI coding
assistants) lives in [`.github/copilot-instructions.md`](.github/copilot-instructions.md).

## Roadmap / future enhancements

Shipped as of v1.0.0:
- `plan`, `import`, and `update` commands
- Run reports + `--resume` with config-drift protection (`plan`, `import`)
- Template inheritance (org `default_fields` → team `defaults` → template `fields`)
- Sprint assignment for `plan` (via `board_id` + `sprint_name_template`)
- Pre-existing epic reuse (`existing_epics`) and release→sprint mapping
- CSV encoding auto-detection with `--encoding` override

Ideas for future work, roughly in order of expected value — pick one up if
you'd like to contribute:

- **`setup` subcommand** — interactive wizard to generate org and team config
  files step by step (a big win for non-technical first-time setup).
- **Field-discovery helper** — a command to list/search your Jira instance's
  custom field IDs so you don't have to hand-map them from the REST API.
- **MCP server** — drive `plan`/`import`/`update` from an AI assistant
  (Copilot, Claude) in natural language, removing the CLI/YAML barrier. See
  the design proposal in [`docs/mcp-server-proposal.md`](docs/mcp-server-proposal.md).
- **Duplicate detection for `plan`** — query Jira for existing tickets
  matching summary + PI label before creating, and skip them automatically.
  (`import` already skips exact-summary duplicates; `plan` does not.)
- **`--yes` flag** — skip confirmation prompts for scripted/CI usage.
- **Sub-task support** — allow `type: Sub-task` with a `parent` field linking
  to a parent issue (not just epic linking).
- Broader README examples and operational playbooks.

## Submitting changes

- Keep pull requests focused — one logical change per PR.
- Run the full test suite (`python -m pytest -v`) before opening a PR; CI
  will re-run it across all supported OS/Python combinations regardless.
- Follow the code conventions above so diffs stay easy to review.
- If you touch config schema, template resolution, or Jira payload building,
  add or update tests rather than relying on manual verification alone.
