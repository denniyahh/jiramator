---
phase: 02-import-preflight-validation
plan: 03
subsystem: import
tags: [preflight, createmeta, live-import, abort, run-report, resume, docs, breaking-change]
status: complete

requires:
  - phase: 02-import-preflight-validation
    provides: "02-01 run_preflight/render_preflight_report; 02-02 stub_createmeta contract; 02-04 caveats, build-failed rows, coercion row errors"
provides:
  - "PRE-03: live import aborts before any Jira read-for-create or write when any row has problems; report status failed + error type Aborted + one failed IssueResult per problem row; exit 1"
  - "D-02 live degrade: createmeta unavailable → loud yellow warning, import proceeds unchanged"
  - "ImportRunResult.preflight populated on live runs"
  - "README/CHANGELOG/AGENTS docs for the breaking dry-run exit code and live abort"
affects: [import, run-reports, resume]

actuals:
  tokens: 10528
  tasks: 3
  commits: 4
plan_head_before: 3da87ded4186714b070cc832127370ad2958900f
plan_head_after: ea7a7a2210acfd4d4b91f0ebd090dc328d6ace00

tech-stack:
  added: []
  patterns:
    - "Preflight gate placed after the initial _persist() and before find_issue_keys_by_summaries, outside the create-loop try/except"
    - "CLI reads result.preflight via getattr(..., None) so hand-rolled test results never AttributeError"
    - "Abort branch exits before partial/success status finalization, so an aborted run is never 'partial'"

key-files:
  created: []
  modified:
    - jiramator/importer.py
    - jiramator/cli.py
    - tests/test_import_cli.py
    - tests/test_importer_report.py
    - README.md
    - CHANGELOG.md
    - AGENTS.md

key-decisions:
  - "Abort IssueResults use the PreflightRow summary for the template key (equals RowBuildResult.summary, incl. '<missing summary>' for build-failed rows)"
  - "ImportRunResult.failed on abort lists (row, summary, joined problems) for problem rows only; carried-forward created rows stay in report.issues, not in the result tuples"
  - "Live unavailable warning is printed by the CLI (not via render_preflight_report) so it can add the 'Jira 400' consequence; reason is Rich-escaped"
  - "OQ-3 followed literally: rows that would be dedup-skipped are still validated (preflight precedes the summary lookup)"

requirements-completed: [PRE-03, PRE-01, PRE-04]

coverage:
  - id: C1
    description: "SC1 live sheet aborts: exit 1, no create/bulk/summary/user calls, report failed/Aborted with 6 ordered failed entries"
    requirement: PRE-03
    verification:
      - kind: integration
        ref: "tests/test_import_cli.py::TestImportPreflightLiveAbort::test_live_sc1_aborts_before_create_exit_1"
        status: pass
  - id: C2
    description: "Mixed sheet: only failing rows recorded; token redacted; duplicate summaries get separate entries"
    requirement: PRE-03
    verification:
      - kind: unit
        ref: "tests/test_importer_report.py::TestRunImportPreflightAbort"
        status: pass
  - id: C3
    description: "Stub contract through real preflight (stub_createmeta + e2e FakeJiraClient) → passed, zero problems/caveats"
    requirement: PRE-03
    verification:
      - kind: unit
        ref: "tests/test_importer_report.py::TestStubCreatemetaThroughPreflight"
        status: pass
  - id: C4
    description: "Resume semantics, build-failed abort, zero rows, all-pass, unavailable fall-through"
    requirement: PRE-03
    verification:
      - kind: unit
        ref: "tests/test_importer_report.py::TestRunImportPreflightResume"
        status: pass
  - id: C5
    description: "Live createmeta ConnectionError / 403 → warning with 'Jira 400', all rows created, exit 0; markup-safe reason"
    requirement: PRE-04
    verification:
      - kind: integration
        ref: "tests/test_import_cli.py::TestImportPreflightLiveUnavailable"
        status: pass
  - id: C6
    description: "Live smoke: import --dry-run on real 2026-09-02 Risk sheet reports 8 problems / 6 rows, exit 1, no writes; JIRA_TOKEN unset → skipped, exit 0"
    requirement: PRE-01
    verification:
      - kind: manual_procedural
        ref: "human-check (see Deferred Human Verification)"
        status: unknown

duration: 5min
completed: 2026-10-15
---

# Phase 02 Plan 03: Live Import Preflight Abort Summary

**A live `jiramator import` now validates every row it would attempt against Jira createmeta before any create-time read or write. If any row has a problem, it creates nothing, records one failed entry per problem row plus a run-level `Aborted` error, prints every failing row, and exits 1. If createmeta is unavailable, it warns loudly and proceeds as before.**

## Performance

- **Duration:** ~5 min (2026-10-15T17:38Z → 17:43Z)
- **Tasks:** 3 (tracer + TDD + docs)
- **Files modified:** 7

## Accomplishments

- **importer.py (D-01/D-08/D-11).** `run_import` calls `run_preflight(..., skip_template_keys=frozenset(prior_created))` right after the initial `_persist()` and before `find_issue_keys_by_summaries` (line 389 vs 425). On `problems` it:
  - records `_record(tk, "failed", error="; ".join(problems))` in ascending row order (sanitized);
  - sets `report.error = abort_info("Preflight found problems in N of M row(s). No issues were created.")`;
  - persists, then returns with `preflight` set.
  Carried-forward created entries stay in the report. Other statuses fall through unchanged, with `preflight` attached to the result.
- **cli.py.** Uses `getattr(result, "preflight", None)`, so there are now 2 call sites (dry-run and live).
  - On `problems`, it sets `ended_at`, keeps status `failed`, writes the report, prints the preview (markup=False) and the preflight section, then prints `Aborting — fix the rows above. No issues were created.` and exits 1. All of this happens before the partial/success finalization.
  - On `unavailable`, it prints `⚠ Schema validation skipped: could not fetch Jira create metadata (<escaped reason>). Row problems may surface as Jira 400 errors during creation.` and continues.
  - A passing live run prints no preflight section, so it shows no caveats.
- **Tests (+18).**
  - `TestImportPreflightLiveAbort` (3): SC1 abort, caveats shown on abort, and a passing run with a required-reporter caveat that does not print it.
  - `TestImportPreflightLiveUnavailable` (3): ConnectionError, 403, and markup in the reason.
  - `TestRunImportPreflightAbort` (3): mixed sheet, redaction, and duplicate summaries / OQ-3.
  - `TestStubCreatemetaThroughPreflight` (2).
  - `TestRunImportPreflightResume` (7).
  - Migrated `test_live_mode_continues_after_row_failure_and_reports_summary` to use `stub_createmeta`, `issuetype` in the payloads and `resolved_columns={}`. All of its original assertions are kept.
- **Docs.**
  - README: credentials paragraph, a new "Preflight validation" block in the import section, and the two Troubleshooting rows.
  - CHANGELOG `[Unreleased]`: a `### Changed` **Breaking** entry and a `### Added` preflight entry.
  - AGENTS.md: `import_preflight.py` added to the import path and to the Credentials paragraph.

## Task Commits

1. **Task 1 (tracer): live abort end-to-end** — `583ec75` (feat). The tracer gate re-ran `<verify>` and it passed before expanding.
2. **Task 2: unavailable warn-and-proceed + resume/build-failed semantics** — `be172bd` (test, RED) and `e4ef6df` (feat, GREEN)
3. **Task 3: docs + phase gate** — `ea7a7a2` (docs)

## TDD Gate Compliance (Task 2)

- RED `be172bd`: 3 new CLI unavailable-warning tests failed because the output had no "Schema validation skipped". The 7 importer-level behaviour tests already passed, because Task 1's wiring implemented them. Those are characterization tests for D-08/D-11, recorded honestly here.
- GREEN `e4ef6df`: all 10 pass, and the full suite passes (779).

## Decisions Made

- The abort template key is built from the `PreflightRow.summary`. It equals the build summary, so `<missing summary>` is used for build-failed rows.
- The live unavailable warning is printed directly by the CLI rather than through `render_preflight_report`, so that it can state the consequence ("Jira 400").
- OQ-3 is followed literally: a row whose summary already exists in Jira is still validated and can cause the abort.

## Deviations from Plan

**1. [Process] The Task 2 cli.py edit was briefly drafted during Task 1**, then removed before the Task 1 commit so that each commit stays atomic. There is no functional deviation.

**2. [Test shape] e2e FakeJiraClient check uses lower-case `summary` headers.** With `_write_import_org_config` there is no `Summary` alias, so a `Summary` header is unresolved and the row fails to build. The e2e import sheets use lower-case `summary` (the standard field), so the test does the same.

Otherwise the plan was executed as written.

## Deferred Human Verification

Live smoke check. It is read-only and the agent did not run it. Run:

```
.venv/bin/jiramator import --dry-run --org-config <explicit org config path> --team-config <explicit team config path> <2026-09-02 Risk sheet>
```

Expect:
- the preview, then a validation section listing missing 'Fix versions' (fixVersions) on all 6 rows and 'Repositories' (customfield_11941) on rows 2–3 (8 problems);
- the line "6 of 6 rows have problems";
- exit code 1;
- nothing created in Jira.

Then repeat with `JIRA_TOKEN` unset and expect "Schema validation skipped" and exit 0.

Also: the external wiki pages **"Import and Update Details"** and **"Run Reports and Resuming"** are outside the repo and need a manual update for the dry-run exit code and the live abort semantics.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints are added. Preflight makes only read-only createmeta calls, which already existed. Per-row errors and the run error go through `sanitize_message` / `abort_info`, and the redaction test covers them (T-02-05). The abort returns before any write (T-02-06).

## Verification

- `.venv/bin/python -m pytest -q` → 779 passed (was 761)
- `.venv/bin/ruff check .` → clean
- `git diff develop -- jiramator/planner.py` → empty (`phase-gate-ok`)
- `grep -n 'getattr(result, "preflight", None)' jiramator/cli.py` → 2 lines

## Self-Check: PASSED

- FOUND: jiramator/importer.py, jiramator/cli.py, tests/test_import_cli.py, tests/test_importer_report.py, README.md, CHANGELOG.md, AGENTS.md
- FOUND commits: 583ec75, be172bd, e4ef6df, ea7a7a2 (all ancestors of HEAD)
