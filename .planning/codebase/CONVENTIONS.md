# Coding Conventions

**Analysis Date:** 2026-04-15

## Naming Patterns

**Files:**
- Use `snake_case.py` for all Python modules: `jira_client.py`, `ticket_builder.py`, `test_config.py`
- Test files mirror source files with `test_` prefix: `config.py` -> `test_config.py`
- Single `conftest.py` at `tests/conftest.py` for shared fixtures

**Functions:**
- Use `snake_case` for all functions and methods
- Prefix private/internal helpers with underscore: `_resolve_org_config_path()`, `_wrap_field()`, `_build_fields_payload()`
- Public API functions have no underscore prefix: `build_all()`, `resolve_value()`, `run_plan()`
- Boolean-returning helpers start with verbs: `_prompt_sprints_exist()`

**Variables:**
- Use `snake_case` for all variables: `epic_keys`, `sprint_label`, `base_vars`
- Constants use `UPPER_SNAKE_CASE`: `WRAPPED_FIELDS`, `KNOWN_TEMPLATE_VARS`, `_BULK_BATCH_SIZE`, `_DEFAULT_TIMEOUT`
- Private module-level constants prefixed with underscore: `_RETRY_STRATEGY`, `_TEMPLATE_VAR_RE`, `_EPIC_REF_RE`

**Types/Classes:**
- Use `PascalCase` for all classes: `OrgConfig`, `TeamConfig`, `SprintConfig`, `EpicTemplate`, `TicketTemplate`
- Exception classes end with `Error`: `JiraApiError`
- Test classes use `Test` prefix with `PascalCase`: `TestOrgConfigParsing`, `TestBuildEpics`

## Code Style

**Formatting:**
- No explicit formatter configured (no `black`, `ruff`, or `yapf` in `pyproject.toml` or config files)
- Indentation: 4 spaces consistently throughout
- Line length: generally kept under ~100 chars, with occasional longer lines for readability (e.g., `test_config.py` line 184)
- Trailing commas used in multi-line collections and function args:
  ```python
  return OrgConfig(
      jira_url="https://example.atlassian.net",
      jira_email_env="JIRA_EMAIL",
      jira_token_env="JIRA_TOKEN",
      custom_fields={
          "story_points": "customfield_10026",
          "epic_link": "customfield_10014",
      },
      sprints={...},
  )
  ```

**Linting:**
- No linter configured (no `.flake8`, `.pylintrc`, `ruff.toml`, or `[tool.ruff]`/`[tool.flake8]` in `pyproject.toml`)
- Single `noqa` comment in the codebase: `jiramator/cli.py` line 118 (`# noqa: E402`)

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first, used in all source files)
2. Standard library imports (`sys`, `os`, `re`, `logging`, `time`, `pathlib`)
3. Third-party imports (`click`, `yaml`, `pydantic`, `requests`, `rich`)
4. Local project imports (`from jiramator.config import ...`)

**Style:**
- Use explicit `from` imports for specific names rather than importing whole modules:
  ```python
  from jiramator.config import OrgConfig, TeamConfig
  from jiramator.jira_client import JiraApiError, JiraClient
  from jiramator.ticket_builder import build_all
  ```
- Group related imports on one line when they come from the same module
- Use `from __future__ import annotations` in every source file for PEP 604 union syntax (`int | None`, `str | Path`)

**Path Aliases:**
- None configured. All imports use direct package paths: `from jiramator.xxx import ...`

## Type Annotations

**Approach:**
- Full type annotations on all function signatures (parameters and return types)
- Use `from __future__ import annotations` to enable modern syntax (`int | None` instead of `Optional[int]`)
- Use `dict[str, Any]`, `list[str]`, `tuple[str, str]` (lowercase generics via future annotations)
- Return type `-> None` always explicit on void functions
- Fixtures in tests sometimes omit return types (acceptable)

**Example from `jiramator/jira_client.py`:**
```python
def create_issues_bulk(
    self,
    payloads: list[dict[str, Any]],
    *,
    batch_size: int = _BULK_BATCH_SIZE,
) -> list[str]:
```

## Error Handling

**Patterns:**
- Raise domain-specific exceptions with descriptive messages: `JiraApiError`, `ValueError`, `KeyError`
- Error messages include actionable context (e.g., available field names, env var names)
- Use `sys.exit(1)` for unrecoverable CLI errors after printing user-friendly messages via `rich.console`
- Config validation errors raised via Pydantic validators (`@field_validator`, `@model_validator`)
- HTTP errors mapped to specific messages by status code (401 -> auth hint, 403 -> permissions, 404 -> not found) in `jiramator/jira_client.py`

**Example from `jiramator/config.py`:**
```python
def get_custom_field_id(self, logical_name: str) -> str:
    try:
        return self.custom_fields[logical_name]
    except KeyError:
        raise KeyError(
            f"Custom field '{logical_name}' is not defined in org config. "
            f"Available fields: {list(self.custom_fields.keys())}"
        )
```

## Logging

**Framework:** Python standard `logging` module

**Patterns:**
- Module-level logger: `logger = logging.getLogger(__name__)` in `jiramator/jira_client.py`
- Use `logger.info()` for successful operations (issue created, version created, batch progress)
- User-facing output uses `rich.console.Console(stderr=True)` with Rich markup, NOT logging
- Logging is only used in the Jira client layer for operational traceability
- No logging in config.py, ticket_builder.py, or planner.py (they use Console for user output)

## Comments

**When to Comment:**
- Every module has a docstring at the top explaining purpose and responsibilities
- Section dividers use ASCII box-drawing style:
  ```python
  # ---------------------------------------------------------------------------
  # Section Name
  # ---------------------------------------------------------------------------
  ```
- Inline comments explain "why" not "what": `# Deduplicate (a file named x.yaml won't also match *.yml, but be safe)`
- Constants document their purpose inline: `_BULK_BATCH_SIZE = 50`

**Docstrings:**
- Google-style docstrings with `Args:`, `Returns:`, `Raises:` sections
- All public functions and classes have docstrings
- Private helpers have shorter docstrings or one-line summaries
- Example from `jiramator/jira_client.py`:
  ```python
  def create_issue(self, payload: dict[str, Any]) -> str:
      """Create a single Jira issue.

      Args:
          payload: A ``{"fields": {...}}`` dict (output of the ticket builder).

      Returns:
          The created issue key (e.g. "CA-5001").

      Raises:
          JiraApiError: On any API error.
      """
  ```

## Function Design

**Size:** Functions are kept focused and small. The largest function is `run_plan()` in `jiramator/planner.py` (~100 lines) which orchestrates the full flow, but it is clearly sectioned with numbered step comments.

**Parameters:**
- Use keyword-only arguments (after `*`) for boolean flags and optional params:
  ```python
  def run_plan(
      org_config: OrgConfig,
      team_config: TeamConfig,
      *,
      dry_run: bool = False,
      console: Console | None = None,
  ) -> None:
  ```
- Avoid mutable default arguments — use `Field(default_factory=list)` in Pydantic models

**Return Values:**
- Return typed values, not tuples of mixed types (exception: `_prompt_pi_number()` returns `tuple[str, str]`)
- Use `dict[str, list[...]]` for structured multi-category results (e.g., `build_all()`)

## Module Design

**Exports:**
- No `__all__` declarations in any module
- Public API is implicit: non-underscore-prefixed functions and classes
- `jiramator/__init__.py` exports only `__version__`

**Barrel Files:**
- Not used. Each module is imported directly by its consumers.

**Separation of Concerns:**
- `config.py`: Data models and YAML loading (Pydantic models, validation, parsing)
- `ticket_builder.py`: Pure data transformation (template resolution, field wrapping, payload construction) — no I/O
- `jira_client.py`: HTTP layer (REST API calls, retry, error handling) — no business logic
- `planner.py`: Orchestration (interactive prompts, flow control, delegates to builder and client)
- `cli.py`: Thin CLI shell (argument parsing, config loading, error display) — delegates to planner

## Pydantic Patterns

**Model Definition:**
- Use `Field()` with `description` for all model fields
- Use `gt=0`, `ge=0` for numeric constraints
- Use `default_factory=list` for mutable defaults

**Validators:**
- Use `@field_validator` with `@classmethod` for single-field validation
- Use `@model_validator(mode="after")` for cross-field validation
- Validators raise `ValueError` with descriptive messages

**Example from `jiramator/config.py`:**
```python
class TicketTemplate(BaseModel):
    summary: str = Field(description="Ticket summary template")
    fields: dict[str, Any] = Field(default_factory=dict)
    extra_on_long_sprint: int = Field(default=0, ge=0)
    long_sprint_suffix: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_long_sprint_suffix_count(self) -> TicketTemplate:
        if self.extra_on_long_sprint > 0:
            expected = 1 + self.extra_on_long_sprint
            if len(self.long_sprint_suffix) != expected:
                raise ValueError(...)
        return self
```

## CLI Patterns

**Framework:** Click with Rich for output

**Conventions:**
- `@click.group()` for the top-level CLI with version option
- Subcommands use `@cli.command()` with typed `click.Option` and `click.Path`
- Use `click.Path(exists=True, path_type=Path)` for file arguments
- Use Rich `Console(stderr=True)` for all user-facing output (keeps stdout clean for piping)
- Error display: `console.print(f"[red bold]Error type:[/] {exc}")` then `sys.exit(1)`

---

*Convention analysis: 2026-04-15*
