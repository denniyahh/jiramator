---
phase: 02-template-inheritance-sprint-assignment
plan: 03
subsystem: planner-cli-config
tags: [sprints, cli, config, tri-state, non-interactive]
requires: [02-02]
provides:
  - "TeamConfig.sprints_exist: bool | None tri-state field"
  - "jiramator.planner._resolve_sprints_exist_mode (4-branch resolver)"
  - "--sprints-exist / --no-sprints-exist Click flag pair on plan command"
  - "run_plan + _run_plan_inner sprints_exist_override kwarg"
affects: [jiramator/config.py, jiramator/planner.py, jiramator/cli.py]
tech-stack:
  added: []
  patterns:
    - "Pydantic field_validator(mode='before') for strict bool|None coercion guard"
    - "Click tri-state flag pair (--foo/--no-foo with default=None)"
    - "Four-branch runtime resolver: CLI override > config field > TTY prompt > error"
key-files:
  created: []
  modified:
    - jiramator/config.py
    - jiramator/planner.py
    - jiramator/cli.py
    - tests/test_config.py
    - tests/test_planner_sprint.py
    - tests/test_planner.py
    - tests/test_cli.py
    - tests/test_cli_e2e.py
decisions:
  - "TeamConfig.sprints_exist defaults to None (tri-state) so absence is distinguishable from explicit False — preserves DC-4 backward compat for existing configs."
  - "Strict bool|None validator (mode='before') rejects 'yes'/1 to honor DC-6 'no fallbacks' rule and STRIDE T-02-13."
  - "Branch-4 ConfigValidationError uses Path('<runtime>') sentinel since the failure is not anchored to a file location — Phase 1 formatter elides line."
  - "Click flag NOT added to import command per RESEARCH §R5: importer doesn't invoke _prompt_sprints_exist."
  - "test_with_board_id_asks_sprint_prompt monkeypatches sys.stdin.isatty=True (DC-4 one-line fix); test_cli_e2e team-config fixture gains sprints_exist: false (deterministic non-TTY path)."
metrics:
  duration_minutes: 18
  completed_date: "2026-04-30"
  tasks_completed: 3
  test_count_added: 22
  total_test_count: 507
---

# Phase 2 Plan 03: Sprint-Mode Resolution Summary

Non-interactive sprint-mode selection via `TeamConfig.sprints_exist` tri-state field, `--sprints-exist/--no-sprints-exist` Click flag, and a four-branch resolver (`_resolve_sprints_exist_mode`) that replaces the unconditional `_prompt_sprints_exist` call in `_run_plan_inner` — delivers ISSUE-01 and unblocks Phase 3 MCP / CI callers without breaking the existing TTY UX.

## What Shipped

**`jiramator/config.py`** — added `TeamConfig.sprints_exist: bool | None = None` with a `field_validator(mode="before")` guard that raises on non-bool/non-None values. Tri-state semantics: `None` means "decide at runtime" (default — preserves existing config compatibility), `True` means "resolve sprints", `False` means "skip resolution".

**`jiramator/planner.py`** — new `_resolve_sprints_exist_mode(team_config, cli_override, console) -> bool` consolidates the sprint-mode decision into a single point with strict priority: (1) CLI override, (2) config field, (3) interactive TTY prompt, (4) `ConfigValidationError`. Existing `_prompt_sprints_exist` is preserved verbatim and reused as branch (3). `run_plan` and `_run_plan_inner` gain `sprints_exist_override: bool | None = None` keyword-only parameters; the call-site at `planner.py:579` (formerly `:536`) now invokes the resolver instead of calling the prompt directly. DC-8 enforcement (no `client.get_board_sprints` call when False) relies on the existing skip branch which is unchanged.

**`jiramator/cli.py`** — `plan` command gains `--sprints-exist/--no-sprints-exist` (Click tri-state, `default=None`). The flag's value is forwarded to `run_plan` as `sprints_exist_override`. Help text documents the four-branch fallback chain. The `import` command intentionally does NOT receive this flag (RESEARCH §R5: no `_prompt_sprints_exist` call site in the importer).

**Test coverage (+22 tests, all green)**:
- `tests/test_config.py::TestTeamConfigSprintsExist` (SE1–SE7): tri-state validation incl. strict-bool rejection (T-02-13 mitigation) and YAML round-trip.
- `tests/test_planner_sprint.py::TestSprintsExistResolution` (S1–S6): all four resolver branches incl. verbatim CONTEXT-line-111 error message check.
- `tests/test_planner_sprint.py::TestSprintsExistIntegration` (II1, II3, II4): DC-8 no-API-call assertion, `run_plan` kwarg forwarding, TTY backward-compat regression.
- `tests/test_cli.py::TestPlanSprintsExistFlag` (CL3–CL8): flag/no-flag forwarding, help text, dry-run smoke, and explicit verification that the flag does NOT leak onto the `import` command.

## Verification

- `pytest tests` — **507 passed**, 0 failed (485 baseline + 22 new).
- `grep -n "_prompt_sprints_exist" jiramator/planner.py` — exactly 2 hits: definition (`:100`) and reuse inside `_resolve_sprints_exist_mode` branch 3 (`:138`). ✓
- `grep -n "sprints_exist_override" jiramator/cli.py jiramator/planner.py` — 7 hits: option declaration, CLI fn signature, CLI → run_plan forwarding, run_plan signature, run_plan → inner forwarding, inner signature, inner → resolver call. ✓ (≥4 expected)
- All success criteria met: tri-state preserves `absence ≠ explicit False`; resolver is the single decision point (DC-6); DC-8 verified via `assert_not_called` mock; backward compat (DC-4) holds for existing TTY users with no flag and no config field.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Test fixture drift] Two existing tests broke under the new non-TTY error branch**

- **Found during:** Task 3 verification (full pytest run after CLI wiring).
- **Issue:** `tests/test_planner.py::test_with_board_id_asks_sprint_prompt` and `tests/test_cli_e2e.py::TestE1/E2` exercised `run_plan` under pytest (where `sys.stdin.isatty()` returns False). Pre-Plan 02-03, the unconditional `_prompt_sprints_exist` was patched directly via `Confirm.ask`. Post-resolver, branch 3 (TTY) is skipped and branch 4 (ConfigValidationError) fires — surfaced as `FrozenInstanceError` because Python 3.14's `contextlib` cannot mutate `__traceback__` on a `frozen=True` dataclass exception (pre-existing latent issue in `error_format.py`, exposed by the new exception path through `run_plan`'s `try/except BaseException` + `_persist`).
- **Fix:** Per DC-4 ("at most a one-line addition"), updated the two test fixtures rather than refactoring `ConfigValidationError`:
  - `tests/test_planner.py:565`: added `@patch("jiramator.planner.sys.stdin.isatty", return_value=True)` so the existing TTY-prompt assertion remains meaningful.
  - `tests/test_cli_e2e.py::_write_team_config`: added `sprints_exist: false` to the team-config YAML so CliRunner-driven e2e tests take the deterministic config branch.
- **Files modified:** `tests/test_planner.py`, `tests/test_cli_e2e.py`.
- **Commit:** `be9d6ed`.
- **Note:** The `FrozenInstanceError` ↔ Python 3.14 contextlib interaction is a pre-existing fragility in `error_format.py:24` (`@dataclass(frozen=True)`) that surfaced because Plan 02-03 introduces a new ConfigValidationError raise-site reachable through the `run_plan` `try/except BaseException` + `_persist` path. Logged to `deferred-items.md` for future hardening — out of scope for this plan (which delivers ISSUE-01, not error_format hardening).

## Threat Coverage

- **T-02-12 (Spoofing — non-TTY hangs):** mitigated by branch (4) `ConfigValidationError`; verified by S6.
- **T-02-13 (Tampering — string coercion):** mitigated by `field_validator("sprints_exist", mode="before")`; verified by SE5.
- **T-02-14 (Repudiation):** accepted — existing run-report `command:` field captures `sys.argv` for audit.
- **T-02-15 (Info disclosure):** accepted — branch-4 error uses `<runtime>` placeholder, no path leak.
- **T-02-16 (DoS — TTY hang):** accepted — branch (3) preserves existing UX; net improvement for non-TTY callers.
- **T-02-17 (EoP — silent skip):** mitigated — "Sprint assignment: skipped (not yet created)" console message preserved on the False path.

## Self-Check: PASSED

Commits:
- `ec73e87 test(02-03): add failing tests for sprints_exist tri-state, resolver, and CLI flag` ✓
- `65e3755 feat(02-03): add TeamConfig.sprints_exist tri-state field with strict bool|None validator` ✓
- `13f909f feat(02-03): add _resolve_sprints_exist_mode 4-branch resolver + sprints_exist_override plumbing` ✓
- `be9d6ed feat(02-03): add --sprints-exist/--no-sprints-exist Click flag pair to plan command` ✓

Files all present (verified via grep checks above). Phase 2 complete: 8 of 8 plans done.
