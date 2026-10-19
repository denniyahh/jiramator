---
phase: 02-import-preflight-validation
verified: 2026-10-15T18:10:00Z
status: human_needed
score: 4/4 must-haves verified (roadmap success criteria); 0 behavior-unverified
covered_files:
  - ".planning/phases/02-import-preflight-validation/02-01-PLAN.md"
  - ".planning/phases/02-import-preflight-validation/02-01-SUMMARY.md"
  - ".planning/phases/02-import-preflight-validation/02-02-PLAN.md"
  - ".planning/phases/02-import-preflight-validation/02-02-SUMMARY.md"
  - ".planning/phases/02-import-preflight-validation/02-03-PLAN.md"
  - ".planning/phases/02-import-preflight-validation/02-03-SUMMARY.md"
  - ".planning/phases/02-import-preflight-validation/02-04-PLAN.md"
  - ".planning/phases/02-import-preflight-validation/02-04-SUMMARY.md"
  - "AGENTS.md"
  - "CHANGELOG.md"
  - "README.md"
  - "jiramator/cli.py"
  - "jiramator/import_preflight.py"
  - "jiramator/importer.py"
  - "jiramator/payload_validator.py"
  - "tests/conftest.py"
  - "tests/test_cli.py"
  - "tests/test_cli_e2e.py"
  - "tests/test_import_cli.py"
  - "tests/test_import_integration.py"
  - "tests/test_import_preflight.py"
  - "tests/test_importer.py"
  - "tests/test_importer_report.py"
  - "tests/test_payload_validator.py"
covered_digest: "v3:sha256:0e75588126767715a925cdb02b656e43ee3d94db08175a34f09e26700cd2addc"
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Live smoke: `jiramator import --dry-run` against real Jira on the 2026-09-02-shaped Risk sheet"
    expected: "Preview prints, then a validation section listing missing 'Fix versions' (fixVersions) on all 6 rows and 'Repositories' (customfield_11941) on rows 2-3 (8 problems), the line '6 of 6 rows have problems', exit code 1, nothing created in Jira"
    why_human: "No live Jira access in this verification environment; this is the roadmap SC1 live replay and cannot be exercised without real credentials/instance"
  - test: "Same sheet with JIRA_TOKEN unset"
    expected: "'Schema validation skipped' printed, exit code 0"
    why_human: "Requires toggling real environment credentials against a live Jira instance"
  - test: "Live smoke abort check: a live `import` (no --dry-run) against real Jira on a sheet with problem rows"
    expected: "Run aborts before creating anything, prints every failing row and 'Aborting — fix the rows above. No issues were created.', exits 1, report status 'failed' with error.type 'Aborted'"
    why_human: "No live Jira access available in this environment; PRE-03's core behavior is thoroughly covered by mocked/stubbed tests (TestImportPreflightLiveAbort, TestRunImportPreflightAbort) but the true live-Jira path (real createmeta shapes, real HTTP errors) is unexercised"
  - test: "Live dry-run with a required Reporter/Parent field against a real Jira create screen"
    expected: "Caveat 'required <Name> (<id>) depends on live <kind> lookup — not preflight-validated' appears under 'Not preflight-validated:', exit code 0"
    why_human: "No live Jira access; D-06 caveat logic is unit/integration-tested against mocked createmeta only"
---

# Phase 2: Import Preflight Validation Verification Report

**Phase Goal:** A user sees every row `import` would fail on — missing required fields, rejected option values, non-ADF rich text — before anything is written to Jira.
**Verified:** 2026-10-15T18:10:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (Roadmap Success Criterion) | Status | Evidence |
|---|---|---|---|
| 1 | SC1: Replaying the 2026-09-02 Risk import shape with `--dry-run` lists missing `Fix versions` and `Repositories` per row, no Jira writes | ✓ VERIFIED | `tests/test_import_cli.py::TestImportPreflightDryRun::test_sc1_risk_sheet_reports_all_problems_exit_1` passes (mocked createmeta, 6 rows / 8 problems, `create_issue`/`create_issues_bulk`/`find_issue_keys_by_summaries`/`find_user_account_id` asserted never called). Live-Jira replay itself is a deferred human-verification item (no live access here) |
| 2 | SC2: Invalid select values and plain-text-for-ADF values are reported in the same preview | ✓ VERIFIED | `jiramator/payload_validator.py` implements `_looks_like_adf`/`_is_textarea_or_richtext`/`invalid_option`/`off_screen` kinds; `tests/test_import_preflight.py::test_select_adf_and_fix_version_problems_reported_together` passes, combining select, ADF and fixVersions problems in one `PreflightResult` |
| 3 | SC3: A live `import` reports all failing rows up front instead of discovering them one 400 at a time | ✓ VERIFIED | `jiramator/importer.py` calls `run_preflight()` after the initial `_persist()` and before `find_issue_keys_by_summaries` (confirmed by reading the live `run_import` body); on `status == "problems"` it records one `failed` IssueResult per row, sets `report.error = abort_info(...)`, persists, and returns before any create call. `jiramator/cli.py` sets `report.status = "failed"` and exits 1 before the partial/success finalization block further down. `tests/test_import_cli.py::TestImportPreflightLiveAbort::test_live_sc1_aborts_before_create_exit_1` asserts report `status=="failed"`, `error.type=="Aborted"`, 6 ordered `failed` issues, and zero create/dedup/user-lookup calls |
| 4 | SC4: Without credentials, `import --dry-run` still previews and says schema validation was skipped | ✓ VERIFIED | `jiramator/cli.py` dry-run branch: on `JiraClient(org_config)` raising `ValueError`, prints both "Preview based on field_aliases only" and "Schema validation skipped: no Jira credentials available", then proceeds to the (client=None) preview with no preflight call, falling through to `return` (exit 0 implicit). `tests/test_import_cli.py::test_dry_run_degrades_gracefully_without_credentials` passes |

**Score:** 4/4 roadmap success criteria verified (0 present-but-behavior-unverified)

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| PRE-01 | 02-01, 02-04 | Dry-run checks every row's payload against createmeta; lists missing required fields | ✓ SATISFIED | `run_preflight()`/`render_preflight_report()` in `import_preflight.py`; D-06/D-08/OQ-4 extensions in 02-04; full suite green (780 passed) |
| PRE-02 | 02-01 | Same preview reports invalid select/option values and plain-text-for-ADF | ✓ SATISFIED | `find_payload_problems()` `invalid_option`/`adf` kinds; `TestPreflightProblems::test_select_adf_and_fix_version_problems_reported_together` passes |
| PRE-03 | 02-02 (prerequisite), 02-03 (implementation) | Live import runs the same check before creating anything, reports all failing rows at once | ✓ SATISFIED | **Note:** REQUIREMENTS.md/02-02-SUMMARY marked PRE-03 "complete" at the 02-02 stub-prerequisite stage (per the task notes), which is misleading in isolation — 02-02 only prepared test fixtures and performed no live-abort wiring. The actual live-abort implementation lands in 02-03 (`importer.py` preflight-then-abort gate, `cli.py` exit/status handling) and is verified above (Truth #3) and by `TestImportPreflightLiveAbort`/`TestRunImportPreflightAbort`/`TestRunImportPreflightResume`/`TestStubCreatemetaThroughPreflight`, all passing. PRE-03 is genuinely satisfied as of 02-03, independent of the premature status mark |
| PRE-04 | 02-01, 02-04 | Without credentials/Jira access, dry-run still previews and states validation was skipped | ✓ SATISFIED | Verified above (Truth #4); 02-04 adds the full degrade/exit-code matrix (`get_fields` failure, createmeta `ConnectionError`, `--preview-rows`, `--max-rows`, `--resume`) covered by `TestImportPreflightDryRun` (12+ tests, all passing) |

No orphaned requirements: REQUIREMENTS.md phase-2 mapping (PRE-01..04) exactly matches the four plans' declared `requirements:` frontmatter.

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `jiramator/import_preflight.py` | `PreflightRow`, `PreflightResult`, `run_preflight()`, `render_preflight_report()` | ✓ VERIFIED | 445 lines; all four symbols present and substantive (read in full); no stub markers |
| `jiramator/payload_validator.py` | `PayloadProblem`, `find_payload_problems()`; plan-preserving `validate_ticket_payload` | ✓ VERIFIED | 273 lines; ADF/option/off-screen/missing-required kinds implemented; `git diff develop -- jiramator/planner.py` empty, confirming plan behaviour untouched |
| `jiramator/importer.py` | live preflight hook + abort recording | ✓ VERIFIED | `run_preflight()` called at both dry-run and live call sites; abort path records per-row failures and `abort_info` |
| `jiramator/cli.py` | live abort branch (exit 1, status failed) and unavailable warning | ✓ VERIFIED | Confirmed by direct read: abort sets `report.status = "failed"`, writes, prints, exits 1, before the generic success/partial/failed finalization block |
| `tests/test_import_preflight.py` | unit tests incl. SC1 replay fixture and render tests | ✓ VERIFIED | 39 tests collected across TestPreflightProblems/TestPreflightDeferred/TestRowBuildCoercionErrors/TestPreflightBuildFailures etc., all passing |
| `CHANGELOG.md` | `[Unreleased]` breaking-change entry | ✓ VERIFIED | `### Changed` **Breaking** entry documents dry-run exit 1 and live abort-before-create |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `jiramator/importer.py::run_import` (live) | `jiramator/import_preflight.py::run_preflight` | called after initial `_persist()`, before `find_issue_keys_by_summaries` | ✓ WIRED | Confirmed by reading `importer.py` lines ~380-420: `_persist()` call precedes `preflight = run_preflight(...)`, which precedes `client.find_issue_keys_by_summaries(...)` |
| `jiramator/importer.py` abort path | `jiramator/run_report.py::abort_info` / `_record`→`sanitize_message` | `report.error = abort_info(...)`; per-row `_record(tk, "failed", error=...)` | ✓ WIRED | Both present; `_record` sanitizes error text via `sanitize_message(kw["error"], secrets=secrets)` before appending |
| `jiramator/cli.py::import_command` | `ImportRunResult.preflight` | `status == "problems"` → write report (status failed) → print → `sys.exit(1)` before finalization | ✓ WIRED | Confirmed; both dry-run and live call sites use `getattr(result, "preflight", None)` so hand-rolled test stubs never `AttributeError` |
| `jiramator/import_preflight.py::run_preflight` | `jiramator/jira_client.py` | `get_createmeta_issue_types` once + `get_createmeta_fields` per distinct type id | ✓ WIRED | Confirmed: `schema_by_id` dict caches per `type_id`; `test_sc1_risk_sheet_reports_all_problems_exit_1` asserts `get_createmeta_issue_types.assert_called_once()` and `get_createmeta_fields.assert_called_once()` for a single-issue-type sheet |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full suite passes | `.venv/bin/python -m pytest -q` | 780 passed | ✓ PASS |
| Lint clean | `.venv/bin/ruff check .` | All checks passed! | ✓ PASS |
| `planner.py` byte-identical to develop | `git diff develop -- jiramator/planner.py` | empty | ✓ PASS |
| WR-01 regression (deferred-field falsy-but-non-blank fix) | `pytest tests/test_import_preflight.py -k test_non_string_deferred_cell_is_missing_required` | 1 passed | ✓ PASS |
| SC1 live-abort end-to-end (mocked) | `pytest tests/test_import_cli.py::TestImportPreflightLiveAbort tests/test_import_cli.py::TestImportPreflightLiveUnavailable` | 6 passed | ✓ PASS |
| PRE-02 combined-problems test | `pytest tests/test_import_preflight.py -k test_select_adf_and_fix_version_problems_reported_together` | 1 passed, 38 deselected | ✓ PASS |

### Probe Execution

Not applicable — this phase has no `scripts/*/tests/probe-*.sh` style probes; the project's own pytest suite is the verification harness and was run directly above.

### Anti-Patterns Found

None. Scanned `jiramator/import_preflight.py`, `jiramator/payload_validator.py`, `jiramator/importer.py`, `jiramator/cli.py` for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/"not yet implemented" — zero matches.

### Code Review Disposition (02-REVIEW-DISPOSITION.md)

| ID | Severity | Disposition | Verified |
|---|---|---|---|
| WR-01 | warning | fixed (`b7b79ae`) | ✓ Confirmed — `_deferred_present` now shares the `isinstance(raw, str) and raw.strip()` predicate with `run_import`; regression test passes |
| WR-02 | warning | skipped by design (D-08) | Accepted per CONTEXT — build-failed rows only join the report when validation itself runs; this is a documented, deliberate scope boundary, not a gap |
| IN-01 | info | open | Non-blocking — intentional test-stub permissiveness, covered elsewhere |
| IN-02 | info | open | Non-blocking — test-fixture duplication, deferred to Phase 4 hygiene |

### Human Verification Required

The four items below require a live Jira instance, which is unavailable in this verification environment. All automated (mocked/stubbed) equivalents pass. Per the phase's own 02-03-SUMMARY and 02-04-SUMMARY, these were already flagged by the executor as deferred human verification, not skipped silently.

1. **Live SC1 dry-run smoke test**
   **Test:** Run `jiramator import --dry-run` against real Jira on the 2026-09-02-shaped Risk sheet.
   **Expected:** Validation section lists missing Fix versions (all 6 rows) and Repositories (rows 2-3), `6 of 6 rows have problems`, exit 1, no writes.
   **Why human:** No live Jira credentials/instance in this environment; this is the literal roadmap SC1 wording ("Replaying the 2026-09-02 Risk import shape").

2. **Live dry-run with no credentials**
   **Test:** Same sheet, `JIRA_TOKEN` unset.
   **Expected:** "Schema validation skipped", exit 0.
   **Why human:** Requires a real environment-credential toggle against live Jira.

3. **Live abort smoke test**
   **Test:** Run a live `jiramator import` (no `--dry-run`) against real Jira with problem rows present.
   **Expected:** Aborts before any create call; prints every failing row and "Aborting — fix the rows above. No issues were created."; exits 1; report `status=="failed"`, `error.type=="Aborted"`.
   **Why human:** No live Jira access; the mocked-client path (`TestImportPreflightLiveAbort`) is thoroughly green, but real Jira createmeta response shapes and real HTTP error types are unexercised here.

4. **Live caveat smoke test (D-06)**
   **Test:** `import --dry-run` against real Jira with a required Reporter/Parent field and a non-blank source cell.
   **Expected:** Caveat printed under "Not preflight-validated:", exit 0.
   **Why human:** No live Jira access; only mocked createmeta exercised in this environment.

### Gaps Summary

No functional gaps. All four roadmap success criteria and all four PRE-0X requirements are satisfied by code that is present, substantive, and wired, backed by a green 780-test suite and clean ruff. The one documentation inaccuracy found (PRE-03 marked "Complete" in REQUIREMENTS.md as of 02-02, before the live-abort implementation in 02-03 existed) does not affect the current state of the codebase — PRE-03 is now genuinely implemented and tested as of 02-03's commits, and REQUIREMENTS.md's current "Complete" marking is accurate at time of verification. Status is `human_needed` solely because the phase's core safety behavior (no live writes until validated; live abort) has not been exercised against a real Jira instance, which is outside this environment's capability and was already flagged as deferred by the executing agent.

---

_Verified: 2026-10-15T18:10:00Z_
_Verifier: the agent (gsd-verifier)_
