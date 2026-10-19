---
phase: 02-import-preflight-validation
plan: 04
subsystem: import
tags: [preflight, createmeta, deferred-fields, dry-run, rich, exit-codes]
status: complete

requires:
  - phase: 02-import-preflight-validation
    provides: "02-01 run_preflight/render_preflight_report/find_payload_problems; 02-02 createmeta stub contract"
provides:
  - "D-06 caveats: required deferred fields (reporter/assignee/parent/sprint) with a non-blank cell → 'not preflight-validated' caveat, never a problem"
  - "D-10 extension: deferred columns absent from createmeta → off-screen problem"
  - "OQ-4: build_row_payload turns coercion ValueError into a per-row build error"
  - "D-08: build-failed, non-resume-skipped rows listed in PreflightResult.rows when validation runs"
  - "Dry-run exit-code/degrade matrix covered by CLI tests; preview/execution reports printed with markup=False"
affects: [02-03, import]

actuals:
  tokens: 9937
  tasks: 3
  commits: 5
plan_head_before: 40d2dc935dc43ad5aaaa657dce9a135968744459
plan_head_after: 3da87ded4186714b070cc832127370ad2958900f

tech-stack:
  added: []
  patterns:
    - "Deferred-field presence decided from raw source cell (strip non-empty), no live lookups"
    - "Createmeta screen membership decided only via meta.get(field_id) is None (Plan 02 stub contract)"
    - "Caveat-only rows rendered under 'Not preflight-validated:' — excluded from problem_rows and X of Y"
    - "Plain-text reports printed with console.print(..., markup=False)"

key-files:
  created: []
  modified:
    - jiramator/payload_validator.py
    - jiramator/import_preflight.py
    - jiramator/importer.py
    - jiramator/cli.py
    - tests/test_import_preflight.py
    - tests/test_import_cli.py

key-decisions:
  - "Caveat-only rows are printed after problem rows and before the 'X of Y rows have problems' line, so the count stays the final line"
  - "Coercion errors take precedence over the missing-summary error; summary falls back to '<missing summary>' when blank"
  - "When only build-failed rows exist, preflight makes zero client calls and returns status 'problems' (existing no-client-calls test updated from 'passed' to 'problems' per D-08)"
  - "Import preview and execution reports (plain text) are printed with markup=False rather than escaped, since they contain no intentional markup"

patterns-established:
  - "run_preflight merges build-failed rows with schema-checked rows in ascending row order"

requirements-completed: [PRE-01, PRE-04]

coverage:
  - id: D1
    description: "Required reporter + non-blank cell → caveat, dry-run exit 0, no user lookups"
    requirement: PRE-01
    verification:
      - kind: integration
        ref: "tests/test_import_cli.py::TestImportPreflightDryRun::test_required_reporter_prints_caveat_exit_0"
        status: pass
  - id: D2
    description: "Sub-task parent present → caveat; absent → missing required 'Parent' (parent)"
    requirement: PRE-01
    verification:
      - kind: unit
        ref: "tests/test_import_preflight.py::TestPreflightDeferred"
        status: pass
  - id: D3
    description: "Non-numeric number cell → per-row build error, other rows still build"
    requirement: PRE-01
    verification:
      - kind: unit
        ref: "tests/test_import_preflight.py::TestRowBuildCoercionErrors"
        status: pass
  - id: D4
    description: "Dry-run degrade matrix: get_fields failure, createmeta ConnectionError, passed, --preview-rows, --max-rows, --resume, markup, non-ASCII, zero rows, build-failed rows"
    requirement: PRE-04
    verification:
      - kind: integration
        ref: "tests/test_import_cli.py::TestImportPreflightDryRun"
        status: pass
  - id: D5
    description: "Live Jira dry-run with a required Reporter/Parent on a real create screen shows the caveat"
    requirement: PRE-01
    verification:
      - kind: manual_procedural
        ref: "jiramator import --dry-run <synthetic sheet with Reporter column> against live Jira"
        status: unknown

duration: 5min
completed: 2026-10-15
---

# Phase 02 Plan 04: Deferred Caveats, Coercion Errors and Dry-run Matrix Summary

**`import --dry-run` now reports required reporter/assignee/parent/sprint fields that have a cell value as "not preflight-validated" caveats instead of problems. A non-numeric number cell fails only its own row. Rows that fail to build are listed with the schema problems. Every dry-run degrade path and exit code is covered by CLI tests, and the output is safe against Rich markup in cell text.**

## Performance

- **Duration:** ~5 min (2026-10-15T17:32Z → 17:37Z)
- **Tasks:** 3 (tracer + 2 TDD)
- **Files modified:** 6

## Accomplishments

- **D-06 deferred caveats.** `find_payload_problems` now applies `assume_present_field_ids` in the required-field check. Preflight treats a deferred field as present when a column resolves to it and the raw cell is non-blank after stripping. If createmeta marks that field required, the row gets the caveat `required <Name> (<id>) depends on live <user|parent|sprint> lookup — not preflight-validated`. A whitespace-only cell is still reported as a missing required field. Preflight makes no user, issue or sprint lookups.
- **D-10 extension.** A deferred column whose field is not in the createmeta (`meta.get(id) is None`) is reported as `<id> is mapped from column '<header>' but is not on the create screen for <Type>`.
- **Rendering.** Caveats print with a yellow ⚠ under problem rows. Rows that have only caveats print under `Not preflight-validated:`, for both passing and failing runs. They are never counted in `X of Y rows have problems`.
- **OQ-4.** In `build_row_payload`, a coercion `ValueError` now produces `Row N: column '<header>': could not convert value '<raw>' (<exc>)`. Before, it aborted the whole preview.
- **D-08.** When validation runs, rows that failed to build (and were not skipped by resume) are listed with their build error and no issue-type bracket, and the status becomes `problems`. An `unavailable` result still returns no rows. If only build-failed rows exist, preflight makes no client calls.
- **Dry-run matrix (Task 3).** 10 new CLI tests cover:
  - `get_fields` failure that still validates and exits 1
  - createmeta `ConnectionError` that skips validation, exits 0 and shows no ✓
  - a clean sheet that passes
  - `--preview-rows 1`, which still lists every failing row
  - `--max-rows 2`
  - `--resume`, which matches a live resume (5 of 5)
  - a summary containing markup, printed literally
  - a non-ASCII summary
  - a sheet with zero rows, which makes no createmeta calls
  - a build-failed row
- **Markup safety.** The plain-text import preview and execution reports are now printed with `markup=False`.

## Task Commits

1. **Task 1 (tracer): D-06 caveats end to end**: `e8783a6` (feat). Tracer gate (auto mode): the full suite (742) and ruff passed, so the plan expanded into Tasks 2 and 3.
2. **Task 2 (TDD): OQ-4 + D-08**
   - RED `3b47d42` (test): 8 behavioural failures
   - GREEN `ebe0b01` (feat)
3. **Task 3 (TDD): PRE-04 matrix + markup safety**
   - RED `780ab5c` (test): orphan `[/]` raised MarkupError
   - GREEN `3da87de` (fix)

## TDD Gate Compliance

- Task 2: the RED commit `3b47d42` failed on assertions and an uncaught `ValueError`, not on import or collection errors. GREEN is `ebe0b01`.
- Task 3: the RED commit `780ab5c` failed because a `MarkupError` crashed the dry-run. The other matrix tests already passed, since Plans 01 and 02 had implemented that behaviour. GREEN is `3da87de`.
- REFACTOR: none needed.

## Verification

- `python -m pytest -q`: **761 passed** (733 before this plan, +28)
- `ruff check .`: All checks passed
- `git diff develop -- jiramator/planner.py`: empty
- Acceptance counts:
  - `-k "deferred or parent"`: 8
  - `-k "TestRowBuildCoercionErrors or TestPreflightBuildFailures"`: 9
  - `-k TestImportPreflightDryRun`: 12
  - `-k "max_rows or resume"`: 2
  - `-k degrades_gracefully`: 2

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 – Bug] Import preview crashed on Rich markup in cell text**
- **Found during:** Task 3
- **Issue:** `render_preview_report` output (plain text containing raw summaries) was printed through Rich markup parsing. A summary such as `Synthetic risk [/] 2` raised `MarkupError` and the dry-run died with a traceback. 02-01-SUMMARY had recorded that this preview also drops markup tags such as `[bold]`.
- **Fix:** print the preview and the execution report with `console.print(..., markup=False)` (dry-run and live). Added an orphan-close-tag case to the CLI markup test.
- **Files modified:** jiramator/cli.py, tests/test_import_cli.py
- **Commit:** 3da87de

**2. [Rule 1 – Contract update] Existing test `test_no_rows_to_check_makes_no_client_calls`**
- **Issue:** It asserted `status == "passed"` for two rows that fail to build. D-08 makes those rows problems.
- **Fix:** now asserts `status == "problems"`. The zero-client-calls assertion is unchanged.
- **Commit:** 3b47d42

**3. [Test-only] Rich wraps lines at 80 columns in CliRunner**
- The caveat line wraps, so the CLI tests compare against whitespace-normalised output (`_flat`). Real terminals wrap in the same way. Only the presentation is affected.

## Known Stubs

None. `assume_present_field_ids`, `source_rows`, `deferred_fields` and `deferred_logical_fields`, which 02-01 accepted but did not use, are now wired.

## Deferred Issues / Notes

- **Human verification (deferred, no live Jira access):** run `import --dry-run` against live Jira with a synthetic sheet whose issue type requires Reporter (or a Sub-task requiring Parent). Confirm the caveat appears under `Not preflight-validated:` and the exit code is 0.
- Plan 03 (live-abort rendering) is not part of this plan. Caveats will show in live-abort output once Plan 03 renders the same report.

## Threat Flags

None. No new endpoints or calls. T-02-08 is mitigated (caveats, build errors and summaries are escaped, and the preview is printed with `markup=False`). T-02-09 is mitigated (caveat-only rows are in a separate section and never counted). T-02-10 is mitigated (the existing drift check runs before the prior report is used, and the resume test uses a real hash).

## Self-Check: PASSED

- FOUND: jiramator/import_preflight.py, jiramator/importer.py, jiramator/payload_validator.py, jiramator/cli.py, tests/test_import_preflight.py, tests/test_import_cli.py, 02-04-SUMMARY.md
- FOUND commits: e8783a6, 3b47d42, ebe0b01, 780ab5c, 3da87de (all ancestors of HEAD)
