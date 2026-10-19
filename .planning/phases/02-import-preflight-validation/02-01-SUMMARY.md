---
phase: 02-import-preflight-validation
plan: 01
subsystem: import
tags: [preflight, createmeta, payload-validation, dry-run, rich]
status: complete

requires:
  - phase: 01-production-triage
    provides: run reports, sanitize_message, resume/drift check for import
provides:
  - "jiramator/import_preflight.py: PreflightRow, PreflightResult (+problem_rows), run_preflight(), render_preflight_report()"
  - "payload_validator: PayloadProblem, find_payload_problems(); validate_ticket_payload keyword-only kwargs with plan-preserving defaults"
  - "ImportRunResult.preflight; importer._prior_created_keys(); dry-run runs preflight with the prior-report skip set"
  - "import --dry-run exits 1 when preflight finds problems; prints 'Schema validation skipped' when it cannot run"
affects: [02-02, 02-03, 02-04, import, plan]

actuals:
  tokens: 14210
  tasks: 2
  commits: 3
plan_head_before: 8768b35ea1c2baf7b99d1961af75c19512317ea8
plan_head_after: e3b68b793eb0ffe294bfadba1c50a666b3d1e7fe

tech-stack:
  added: []
  patterns:
    - "Structured validator (PayloadProblem) with a string wrapper that keeps plan output identical"
    - "Preflight never presents unavailable createmeta as passed (distinct status + 'Schema validation skipped')"
    - "Rich escaping of the whole bracketed issue-type segment: escape(f\"[{issue_type}]\")"

key-files:
  created:
    - jiramator/import_preflight.py
    - tests/test_import_preflight.py
  modified:
    - jiramator/payload_validator.py
    - jiramator/importer.py
    - jiramator/cli.py
    - tests/test_import_cli.py
    - tests/test_payload_validator.py

key-decisions:
  - "OQ-1 applied: import skips the allowedValues check only for issuetype (casefold match against the createmeta issue-type list already covers it); fixVersions IS validated for import"
  - "OQ-5 applied: any createmeta fetch failure (issue-type list or any per-type field fetch) makes the whole preflight 'unavailable' — no partial results"
  - "Missing-required suffix lists ALL field_aliases keys that resolve to the field, in config order (e.g. 'fix_version', 'Fix Version', 'Fix Versions'), as the plan specifies"
  - "Off-screen/ADF/option problems are attributed to the row's own resolved headers; if none, to 'bulk_create.defaults'"

patterns-established:
  - "run_preflight makes zero client calls when no row reaches schema validation"

requirements-completed: [PRE-01, PRE-02, PRE-04]

coverage:
  - id: D1
    description: "SC1 dry-run replay: 8 problems over 6 rows in one run, '6 of 6 rows have problems', exit 1, no writes/lookups"
    requirement: PRE-01
    verification:
      - kind: integration
        ref: "tests/test_import_cli.py::TestImportPreflightDryRun::test_sc1_risk_sheet_reports_all_problems_exit_1"
        status: pass
  - id: D2
    description: "Invalid select value, plain text for ADF field and unknown fixVersions reported together, with source column"
    requirement: PRE-02
    verification:
      - kind: unit
        ref: "tests/test_import_preflight.py::TestPreflightProblems::test_select_adf_and_fix_version_problems_reported_together"
        status: pass
  - id: D3
    description: "No credentials: aliases-only preview + 'Schema validation skipped', exit 0"
    requirement: PRE-04
    verification:
      - kind: integration
        ref: "tests/test_import_cli.py::TestImportCommand::test_dry_run_degrades_gracefully_without_credentials"
        status: pass
  - id: D4
    description: "Real Jira dry-run of the SC1 sheet shows the 8 problems"
    requirement: PRE-01
    verification:
      - kind: manual_procedural
        ref: "jiramator import --dry-run <synthetic Risk sheet> against live Jira (work clone)"
        status: unknown

duration: 5min
completed: 2026-10-15
---

# Phase 02 Plan 01: Import Preflight (dry-run) Summary

**`import --dry-run` now validates every built row against Jira's live createmeta for the row's own issue type, lists every failing row in one run (missing required fields with column hints, bad select options, plain text where ADF is required, unknown fix versions, off-screen fields), and exits 1 when it finds problems.**

## Performance

- **Duration:** ~5 min (wall clock measured between first and last commit-phase checks)
- **Started:** 2026-10-15T17:24Z
- **Completed:** 2026-10-15
- **Tasks:** 2 (tracer + TDD)
- **Files modified:** 7 (2 created)

## Accomplishments

- New `jiramator/import_preflight.py`: `run_preflight` fetches the issue-type list once and each distinct type's field schema once (casefold match, so `Risk`/`risk` share a fetch). Unknown or missing issue types are row problems. A fetch failure returns `unavailable`. With no rows to check, it makes zero client calls.
- `render_preflight_report`: `Row N 'summary' [IssueType]:` with every summary, message and reason escaped, and the whole bracket segment escaped. Lists every failing row (no preview cap) and ends with `X of Y rows have problems`. Prints `✓ … passed` or `⚠ Schema validation skipped: …`.
- `payload_validator.find_payload_problems` returns structured `PayloadProblem`s. New options: `skip_allowed_value_field_ids`, `report_off_screen_fields` (decided only via `field_metadata.get`, per the Plan 02 stub contract) and `blank_adf_counts_as_missing`. `assume_present_field_ids` is accepted but does nothing until Plan 04. With default options, `validate_ticket_payload` returns exactly what `plan` returned before.
- `run_import` dry-run runs preflight when it has a client and passes the prior report's created-row skip set, so `--dry-run --resume` validates the same rows a live resume would (OQ-2). `_prior_created_keys` is shared with the live path, and the live carry-forward behaviour is unchanged.
- CLI dry-run builds one `JiraClient` and reuses it for `get_fields()` and createmeta. With no credentials it prints both the aliases-only warning and `Schema validation skipped: no Jira credentials available (…)`. If `get_fields()` fails, only the preview degrades. Exits 1 iff the status is `problems` (D-03).

## Task Commits

1. **Task 1 (tracer): SC1 dry-run end to end**: `7f2fc12` (feat). Tracer gate in auto mode: verify re-run passed (71 targeted tests, planner unchanged), so the plan expanded into Task 2.
2. **Task 2 (TDD): PRE-02 / D-07 / D-10 checks, attribution, unit tests**
   - RED: `a4a7deb` (test). 5 failing assertions (off-screen, blank ADF, column suffixes)
   - GREEN: `e3b68b7` (feat)

## TDD Gate Compliance

- RED commit `a4a7deb` (`test(02-01)`). Failures were AssertionErrors on the new behaviour, not import or collection errors.
- GREEN commit `e3b68b7` (`feat(02-01)`). Full suite green.
- REFACTOR: none needed.

## Verification

- `python -m pytest -q`: **727 passed** (baseline 699, +28)
- `ruff check .`: All checks passed
- `git diff develop -- jiramator/planner.py`: empty. Pinned tests `test_field_not_on_screen_skipped` and `test_fix_versions_allowed_values_skipped` pass unmodified.
- `git diff develop -- tests/test_payload_validator.py`: additions only
- `tests/test_import_preflight.py`: 21 tests (6 in TestPreflightRender, including the literal `[risk]` check)

## Deviations from Plan

1. **[Rule 3 – sequencing] Validator flag code was written first and then taken out again for Task 1.** `report_off_screen_fields` and `blank_adf_counts_as_missing` were removed from the Task 1 commit and restored in the Task 2 GREEN commit, so the TDD RED step genuinely failed. The split is as planned; this is only recorded for transparency.
2. **[Rule 1 – acceptance] Changed the test import style to keep the diff additive.** The first RED commit changed the existing `from jiramator.payload_validator import …` line, which broke the "additions only" acceptance criterion. The GREEN commit fixes this with a separate `from jiramator import payload_validator` import, so the original line is untouched.

## Known Stubs

- `find_payload_problems(assume_present_field_ids=…)` and `run_preflight(source_rows, deferred_fields, deferred_logical_fields)` are accepted but unused. This is intentional: Plan 04 (D-06 deferred-required caveats) uses them. They do not block this plan's goal.

## Deferred Issues / Notes

- **Pre-existing, out of scope:** the existing `render_preview_report` mapping preview (`Row N: <summary>`) does not escape Rich markup, so a summary such as `[bold]x[/]` loses its tags in the *preview* section. The new preflight section prints it correctly. Plan 04 or a follow-up could fix this.
- **Human verification (deferred, no live Jira access):** run a live `import --dry-run` of a synthetic SC1-shaped Risk sheet against real Jira and confirm the 8 problems, `6 of 6 rows have problems` and exit 1.
- **Unresolved assumption (from plan):** degrade triggers beyond no-credentials, `get_fields` failure and createmeta HTTP/network failure (e.g. a malformed createmeta body without `fields`) are not handled specially.

## Threat Flags

None. No new endpoints or write paths. Preflight only calls the read-only `get_createmeta_issue_types` and `get_createmeta_fields`. The T-02-01 and T-02-03 mitigations are implemented and tested. For T-02-02, exception text is escaped and no token interpolation was added.

## Self-Check: PASSED

- FOUND: jiramator/import_preflight.py, tests/test_import_preflight.py, 02-01-SUMMARY.md
- FOUND commits: 7f2fc12, a4a7deb, e3b68b7 (all ancestors of HEAD)
