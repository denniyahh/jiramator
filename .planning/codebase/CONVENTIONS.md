---
last_mapped_commit: 8c96e59b775dcea4aaa6a50e976c76a64e447907
last_mapped_at: 2026-09-28
---
# Coding Conventions

**Analysis Date:** 2026-09-28

## Naming Patterns

**Files:**

- Lowercase snake_case module names matching their domain concept: `jiramator/jira_client.py`, `jiramator/ticket_builder.py`, `jiramator/config_merge.py`, `jiramator/value_coercion.py`.
- Each source module has a matching `tests/test_<module>.py`. Extra scenario-specific test files add a descriptive suffix: `tests/test_planner_sprint.py`, `tests/test_planner_report.py`, `tests/test_importer_report.py`, `tests/test_ticket_builder_strip_lines.py`.

**Functions:**

- `snake_case`, verb-first: `run_plan()`, `build_all()`, `resolve_value()`, `find_resumable()`, `compute_resolved_hash()`.
- `_` prefix for module-private helpers: `_wrap_field()`, `_truthy()`, `_preflight_validate()`.

**Variables:**

- `snake_case` throughout; no Hungarian notation.
- Public module-level constants are `UPPER_SNAKE_CASE`: `_BULK_BATCH_SIZE`, `SCHEMA_VERSION` (in `jiramator/run_report.py`), `_RETRY_STRATEGY`, `_DEFAULT_TIMEOUT` (`jiramator/jira_client.py`).
- Env-var name constants also `UPPER_SNAKE_CASE` with `_ENV_VAR` suffix: `_CA_BUNDLE_ENV_VAR`, `_RELAX_TLS_STRICT_ENV_VAR` (`jiramator/jira_client.py`).

**Types:**

- Pydantic model classes are `PascalCase` and named after the config/domain concept: `OrgConfig`, `TeamConfig`, `IssueResult`, `RunReport` (`jiramator/config.py`, `jiramator/run_report.py`).
- Custom exceptions are `PascalCase` ending in `Error`: `JiraApiError` (`jiramator/jira_client.py`), `ConfigValidationError` (`jiramator/error_format.py`), `ConfigDriftError` (`jiramator/run_report.py`).

## Code Style

**Formatting:**

- No formatter (Black/Ruff format) is configured — CLAUDE.md states explicitly: "No linter or formatter is configured."
- Style is instead enforced by convention and code review; match surrounding code exactly when editing.

**Linting:**

- No `.ruff.toml`, `.flake8`, or `setup.cfg` lint config present in the repo. Do not assume lint gates exist in CI — `.github/workflows/ci.yml` only runs `python -m pytest -q` across OS/Python matrix (ubuntu/macos/windows × 3.11/3.12/3.13).
- Type-correctness is enforced only through fully-annotated code and pytest, not `mypy` (no mypy config found).

## Import Organization

**Order:**

1. `from __future__ import annotations` — **first line of every source file, no exceptions**.
2. Standard library imports (`os`, `logging`, `time`, `dataclasses`, `typing`).
3. Third-party imports (`requests`, `pydantic`, `rich`, `click`, `urllib3`).
4. Local `jiramator.*` imports, always explicit: `from jiramator.config import OrgConfig`.

**Path Aliases:**

- None. No `sys.path` hacks or import aliases; `pyproject.toml` sets `pythonpath = ["."]` for pytest only, so tests import via `from jiramator.x import Y`.
- **No wildcard imports, no barrel/`__init__.py` re-export files** — `jiramator/__init__.py` is empty/minimal; every consumer imports directly from the defining module.

## Error Handling

**Patterns:**

- Domain-specific exceptions carry structured context, not just a message. Example (`jiramator/jira_client.py`):
  ```python
  class JiraApiError(Exception):
      """Raised when a Jira API call fails.

      Attributes:
          status_code: HTTP status code (None for connection errors).
          errors: Jira field-level error dict (if available).
          message: Human-readable error message.
      """

      def __init__(
          self,
          message: str,
          status_code: int | None = None,
          errors: dict[str, Any] | None = None,
      ) -> None:
          self.status_code = status_code
          self.errors = errors or {}
          super().__init__(message)
  ```
- Pydantic validators raise plain `ValueError` with an actionable, user-readable message (never a generic "invalid value"). Seen throughout `jiramator/config.py` in `@field_validator`/`@model_validator` methods, e.g. duplicate epic key detection: `raise ValueError(f"Duplicate epic keys: {set(dupes)}")`.
- `jiramator/error_format.py` defines `ConfigValidationError` to reformat raw Pydantic `ValidationError` output into a message readable by non-Python users (surfaced by the CLI).
- CLI-level unrecoverable errors follow a strict two-step pattern: print a Rich-formatted message to the `Console(stderr=True)`, then `sys.exit(1)`. Never raise unhandled exceptions out of `cli.py` commands.
- HTTP layer: `JiraClient` methods never let `requests` exceptions leak — they catch and re-raise as `JiraApiError` with structured `errors`/`status_code`, so callers only need to catch one exception type.
- Retry policy is centralized in `jiramator/jira_client.py`'s module-level `_RETRY_STRATEGY` (a `urllib3.util.retry.Retry`): retries on `429`, `502`, `503`, `504` with exponential backoff (`backoff_factor=1.0`), `raise_on_status=False` because status codes are handled manually after the request returns.

## Logging

**Framework:** Python stdlib `logging`, but scoped narrowly.

**Patterns:**

- `logging` is used **only** in `jiramator/jira_client.py` (`logger = logging.getLogger(__name__)`) for low-level operational traceability of HTTP calls/retries.
- Everywhere else, **all user-facing output goes through `rich.console.Console(stderr=True)`** — never bare `print()`, never `logging` outside the Jira client. When adding output in `cli.py`, `planner.py`, `importer.py`, `updater.py`, `wizard.py`, use a Rich `Console` instance, matching existing call sites.

## Comments

**When to Comment:**

- Inline comments explain *why*, not *what* — e.g. explaining a workaround (`# requests.adapters.HTTPAdapter doesn't accept an ssl_context kwarg directly...`) or a non-obvious tradeoff (retry backoff timing: `# 1s, 2s, 4s`).
- Section divider comments are used consistently in both source and test files to group logically related code:
  ```python
  # ---------------------------------------------------------------------------
  # Section Name
  # ---------------------------------------------------------------------------
  ```
  Seen in `jiramator/jira_client.py` (`# Errors`, `# Client`), `tests/test_jira_client.py` (`# Fixtures`, `# Client initialization`), and consistently across other test files.

**JSDoc/TSDoc (docstrings):**

- Google-style docstrings (`Args:`, `Returns:`, `Raises:`) required on all public functions and classes. Example from `JiraApiError` above shows the `Attributes:` variant used on classes/dataclasses.
- Module-level docstrings explain the module's single responsibility and explicitly state what it does *not* do (e.g. `jira_client.py`'s docstring: "It does NOT do any template interpolation or payload building — that's the ticket_builder's job.").

## Function Design

**Size:** Functions are kept single-purpose per the five-layer architecture (see ARCHITECTURE.md); no enforced line-count limit but the layering itself keeps functions focused — CLI functions parse/dispatch only, builder functions transform only, client functions do I/O only.

**Parameters:** Fully annotated signatures always — every parameter and return type is typed, including `Optional`-style unions written in modern lowercase syntax (`dict[str, Any]`, `list[str] | None`, `int | None`). Void functions explicitly annotate `-> None`.

**Return Values:** Prefer typed Pydantic models or dataclasses over raw dicts/tuples for anything crossing a module boundary (`OrgConfig`, `TeamConfig`, `RunReport`, `IssueResult`). Internal pure-transform helpers may return plain `dict`/`list` structures (e.g. `ticket_builder.py`'s payload dicts) since they're consumed immediately by `jira_client.py`.

## Module Design

**Exports:** No `__all__` lists observed; modules are small and focused enough that all top-level public names are implicitly exported. Consumers always import specific names explicitly (`from jiramator.config import OrgConfig`), never the module wildcard.

**Barrel Files:** None — `jiramator/__init__.py` does not re-export submodule contents. Each module is imported directly by its full path.

**Pydantic model conventions (`jiramator/config.py`):**

- Every field declares `Field(description=...)` — descriptions double as user-facing documentation when config validation errors are surfaced.
- `@field_validator` + `@classmethod` for single-field checks (e.g. `long_sprints`, `summary`, `sprints_exist` with `mode="before"` for type coercion before validation).
- `@model_validator(mode="after")` for cross-field checks that need the fully-constructed model (e.g. epic key uniqueness across `recurring_epics`/`existing_epics`).
- `ConfigDict`, `HttpUrl`, `ValidationError` imported directly from `pydantic` — no compatibility shims for Pydantic v1.

---

*Convention analysis: 2026-09-28*
