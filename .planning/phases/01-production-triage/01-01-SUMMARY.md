---
phase: 01-production-triage
plan: 01
subsystem: run-reports
tags: [run_report, resume, error-capture, redaction, INV-04]
status: complete

requires: []
provides:
  - "RunReport.error {type, message} run-level failure record (omitted when None)"
  - "error_info / abort_info / ABORTED_ERROR_TYPE / _ERROR_MESSAGE_CAP in run_report.py"
  - "Tolerant RunReport.from_envelope (ignores unknown run/issue keys)"
  - "plan + import record ended_at + error on every crash/abort path before re-raise"
affects: [run-reports, resume, plan, import, production-triage]

actuals:
  tokens: 10900
  tasks: 3
  commits: 3
plan_head_before: 6676bdc80ea6998b916783fe1d9e60c0f83bd197
plan_head_after: bd1b6864bcc7f579fa0f3fd4c38f64b41b6c0f0f

tech-stack:
  added: []
  patterns:
    - "except BaseException as exc: set ended_at/error only-if-None → persist → bare raise"
    - "Abort sites set report.error = abort_info(reason) before sys.exit(1); outer handler keeps it"
    - "Redact (token value, Basic/Bearer credential) BEFORE truncating to 2000 code points"
    - "Autouse conftest fixture redirects RUNS_DIR to tmp_path"

key-files:
  created: []
  modified:
    - jiramator/run_report.py
    - jiramator/planner.py
    - jiramator/importer.py
    - jiramator/cli.py
    - tests/test_run_report.py
    - tests/test_planner_report.py
    - tests/test_importer_report.py
    - tests/test_import_cli.py
    - tests/conftest.py
    - CHANGELOG.md

key-decisions:
  - "INV-04: RunReport.error is an additive optional field; SCHEMA_VERSION stays 1 and error is omitted from the envelope when None so clean reports remain loadable by v1.2.8"
  - "INV-04: from_envelope filters run/issue dicts to known dataclass fields (forward-compatible with future additive keys)"
  - "INV-04: deliberate aborts use error.type='Aborted' with the printed reason; final-confirm decline message locked as 'User declined ticket creation at the final confirmation.'"
  - "INV-04: secrets for redaction = stripped value of os.environ[org_config.jira_token_env] (matches config.py's .strip())"

patterns-established:
  - "Error capture: handlers only READ exc (ConfigValidationError is frozen), never mutate it"

requirements-completed: [INV-04]

coverage:
  - id: D1
    description: "plan crash (KeyboardInterrupt) leaves report with ended_at + {type, message}"
    requirement: INV-04
    verification:
      - kind: unit
        ref: "tests/test_planner_report.py::TestPersistOnError::test_p10_keyboardinterrupt_leaves_valid_report"
        status: pass
  - id: D2
    description: "Every plan abort/API-error path records a distinguishable error (Aborted reasons, JiraApiError, ValueError)"
    requirement: INV-04
    verification:
      - kind: unit
        ref: "tests/test_planner_report.py::TestErrorCapture (8 tests)"
        status: pass
  - id: D3
    description: "import crash inside run_import or before it (ConnectionError from get_fields, ValueError from JiraClient) leaves report with ended_at + error; inner error not overwritten"
    requirement: INV-04
    verification:
      - kind: unit
        ref: "tests/test_importer_report.py::test_i7_keyboardinterrupt_persists; tests/test_import_cli.py::test_live_import_*"
        status: pass
  - id: D4
    description: "Legacy (no error key) and unknown-key envelopes load; reports with error still resumable; schema_version 2 still rejected; resume from legacy report succeeds"
    requirement: INV-04
    verification:
      - kind: unit
        ref: "tests/test_run_report.py::test_26..test_29, test_34, test_4; tests/test_planner_report.py::test_resume_from_legacy_report_without_error_succeeds"
        status: pass
  - id: D5
    description: "error_info truncation (code points + …), empty message kept, Basic/Bearer/token redaction before truncation, non-ASCII round-trip"
    requirement: INV-04
    verification:
      - kind: unit
        ref: "tests/test_run_report.py::TestErrorInfo"
        status: pass

duration: 4min
completed: 2026-10-02
---

# Phase 01 Plan 01: Run-report error capture (INV-04) Summary

**`plan` and `import` now write `ended_at` and a sanitized `error: {type, message}` to the run report on every crash or deliberate abort (`Aborted` + printed reason) before re-raising unchanged, with no schema bump and clean reports byte-compatible with v1.2.8.**

## Performance

- **Duration:** ~4 min (recorded wall clock)
- **Completed:** 2026-10-02
- **Tasks:** 3/3 (Task 1 tracer — gate passed in auto mode, verify re-run green before expansion)
- **Files modified:** 10

## Accomplishments

- `run_report.py`: `RunReport.error` (last field), `_ERROR_MESSAGE_CAP=2000`, `ABORTED_ERROR_TYPE="Aborted"`, `_sanitize_message` (token + `Basic`/`Bearer` redaction, then code-point cap with `…`), `error_info`, `abort_info`; `to_envelope` drops `error` when None; `from_envelope` filters unknown keys.
- `planner.py`: `run_plan` handler records `ended_at`/`error` (if-None guards) then re-raises; abort sites (fix-version decline, preflight problems, credential error, final-confirm decline) record `Aborted` reasons; epic and bulk `JiraApiError` record the exception. New `_token_secrets` helper; `report=` kwarg on `_check_and_create_fix_versions`/`_preflight_validate`; `secrets=` kwarg on `_bulk_create_with_resume`.
- `importer.py` handler records `ended_at` (Z format) + `error`; `cli.py` import command adds a sibling `except BaseException` clause and a `_record_import_failure` helper so crashes before `run_import` also leave a report.
- CHANGELOG `[Unreleased]` entry including the ≤1.2.8 resume caveat.

## Task Commits

1. **Task 1 (tracer): plan crash → report records ended_at + error; legacy reports load** — `85e73f4`
2. **Task 2: deliberate plan aborts record the printed reason** — `7df134f`
3. **Task 3: import records ended_at + error on any crash** — `bd1b686`

## Verification

- `python -m pytest -q` → 676 passed
- `ruff check .` → All checks passed!
- `.jiramator/runs` before/after diff of the full suite → empty
- `tests/fixtures/` untouched; `tests/test_integration.py` passes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Pre-existing tests leaked reports into the repo's `.jiramator/runs`**
- **Found during:** Task 3 (acceptance criterion "tests wrote only to tmp_path")
- **Issue:** Pre-existing tests that invoke `plan`/`import` without `--report` (e.g. `test_live_mode_continues_after_row_failure_and_reports_summary`) wrote default-path reports to `./.jiramator/runs`, so the before/after diff could never be empty. None of the leaked files came from the new tests (all had `error: None`).
- **Fix:** Added an autouse fixture `_isolate_runs_dir` in `tests/conftest.py` that points `jiramator.run_report.RUNS_DIR` at `tmp_path/.jiramator/runs` (keeps `test_C1` path-shape assertion valid; tests that set `RUNS_DIR` themselves still override it). Removed the 6 stray report files that this session's own test runs had created (directory was empty at start).
- **Files modified:** tests/conftest.py (not in plan's files_modified)
- **Commit:** bd1b686

**2. [Minor] Extra tests beyond the plan list**
- Added `test_30b_cap_measured_in_code_points`, `test_32b_redaction_before_truncation`, `test_32c_abort_info_uses_aborted_label`, and `test_live_import_inner_error_not_overwritten_by_cli`, which cover must-have truths that the planned tests did not exercise directly (code-point cap, redact-before-truncate, the cli not overwriting an inner error).

**3. [Implementation detail] `abort_info` import deferred to Task 2**
- Task 1 removed `abort_info` from planner's import (ruff F401, since it was unused at that point); Task 2 added it back once it was in use.

## Issues Encountered

- `pytest` was missing from `.venv`, so ran `pip install -e ".[dev]"` (allowed by the constraints).

## Next Phase Readiness

- Future failed runs now explain themselves from the report alone. The other production-triage plans can tell an `Aborted` final-confirm decline (the INV-01 leading hypothesis: zero counts, empty issues) apart from a crash.

## Self-Check: PASSED

- All 10 modified files present; commits 85e73f4, 7df134f, bd1b686 found in `git log`.
