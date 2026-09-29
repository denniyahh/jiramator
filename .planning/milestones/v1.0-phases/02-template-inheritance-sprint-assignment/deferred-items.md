# Phase 02 Deferred Items

Out-of-scope discoveries flagged during execution; not blocking phase completion.

## DEFER-02-01: ConfigValidationError frozen-dataclass interaction with Python 3.14 contextlib

**Found during:** Plan 02-03 Task 3 (full-suite verification).

**Symptom:** `dataclasses.FrozenInstanceError: cannot assign to field '__traceback__'` raised from `contextlib.__exit__` (CPython 3.14 stdlib `contextlib.py:195`) when a `ConfigValidationError` propagates through a `try/except BaseException:` block that wraps a context-managed scope (e.g. `_persist()` callbacks in `run_plan`).

**Root cause:** `jiramator/error_format.py:24` declares `@dataclass(frozen=True)` on `ConfigValidationError`. Python 3.14 `contextlib._BaseExitStack.__exit__` mutates `exc.__traceback__` during exception unwinding, which `frozen=True` blocks via `__setattr__` override.

**Why deferred:** Phase 1 design choice (frozen dataclass for value-equality semantics). Plan 02-03 mitigated the immediate test breakage via fixture updates (`sprints_exist: false` in e2e fixtures, `monkeypatch sys.stdin.isatty` in planner test) per DC-4 one-line-fix budget. A proper fix requires either:
- Dropping `frozen=True` (loses value-equality guarantee), or
- Overriding `__setattr__` to allow only `__traceback__` / `__cause__` / `__context__` writes, or
- Migrating to a non-dataclass exception with explicit `__eq__` / `__hash__`.

This is `error_format.py` hardening — out of scope for ISSUE-01 (sprint-mode resolution).

**Risk if not fixed:** Any future code path that raises `ConfigValidationError` through a `try/except BaseException:` + context-manager combo will surface this error. Currently only `run_plan` does so; new such paths in Phase 3 (MCP server) may re-trigger.

**Suggested fix path:** Phase 3 Plan 0 (foundation refactor) — convert to a regular Exception subclass with explicit `__eq__` / `__hash__` based on `(file, line, field_path, reason)`. ~30 LOC, isolated to `error_format.py` + add a regression test for `__traceback__` assignment.
