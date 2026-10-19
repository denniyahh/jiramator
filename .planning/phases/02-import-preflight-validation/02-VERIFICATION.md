---
phase: 02-import-preflight-validation
verified: 2026-10-19T15:01:04Z
status: human_needed
score: 4/4 roadmap success criteria verified; 52/53 plan truths verified (1 backstop truth insufficient_spec); 0 behavior-unverified
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
covered_digest: "v3:sha256:9d10acb0cad0178b047e707fe86c4cce529b212796681f12497b17b0a48b4d53"
behavior_unverified: 0
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 4/4 must-haves verified (roadmap success criteria)
  reason: "prior report STALE — covered_digest no longer matched covered files (WR-01 fix 80b02d3 landed after it)"
  gaps_closed: []
  gaps_remaining: []
  regressions: []
human_verification:
  - test: "Live smoke: `jiramator import --dry-run` against real Jira on the 2026-09-02-shaped Risk sheet (02-UAT.md #1; 02-03 backstop truth)"
    expected: "Preview prints, then a validation section listing missing 'Fix versions' (fixVersions) on all 6 rows and 'Repositories' (customfield_11941) on rows 2-3 (8 problems), '6 of 6 rows have problems', exit 1, nothing created in Jira"
    why_human: "No live Jira here; the plan tags this truth `verification: backstop`, so mocked-createmeta tests cannot discharge it"
  - test: "Same sheet with JIRA_TOKEN unset (02-UAT.md #2)"
    expected: "'Schema validation skipped' printed, exit 0"
    why_human: "Reproduced locally with the example config (exit 0, both warnings printed), but the user's real org config/sheet combination is only checkable by the user"
  - test: "Live abort: real `import` (no --dry-run) on a sheet with problem rows (02-UAT.md #3)"
    expected: "Aborts before creating anything, prints every failing row and 'Aborting — fix the rows above. No issues were created.', exit 1, report status 'failed' with error.type 'Aborted'"
    why_human: "Real createmeta response shapes and HTTP errors unexercised; mocked path is green"
  - test: "Live dry-run with a required Reporter/Parent field on a real create screen (02-UAT.md #4)"
    expected: "Caveat 'required <Name> (<id>) depends on live <kind> lookup — not preflight-validated' under 'Not preflight-validated:', exit 0"
    why_human: "D-06 caveat logic only exercised against mocked createmeta"
  - test: "Backstop truth (02-01): option-value comparison is exact code-point equality (no Unicode normalization / casefolding) — confirm Jira's create-time comparison agrees, e.g. submit a select value differing only in case or NFC/NFD form against a real select field"
    expected: "Jira rejects the case/normalization variant (so preflight's exact match is not a false positive), or the assumption is consciously accepted"
    why_human: "Tagged `verification: backstop` (insufficient_spec): no held-out test exists and the claim is about Jira's server behaviour, not this codebase"
  - test: "Resolve flagged prohibitions P-02-01..P-02-05 (judgment-tier; verifier verdict is non-authoritative — see Prohibitions table)"
    expected: "Human confirms or rejects each LLM-judge verdict (all five judged HELD with test evidence)"
    why_human: "Prohibitions arrive `flagged: true, status: unverified`; per ADR-550 D4 they cannot be silently absorbed into a passed verdict"
---

# Phase 2: Import Preflight Validation Verification Report

**Phase Goal:** A user sees every row `import` would fail on — missing required fields, rejected option values, non-ADF rich text — before anything is written to Jira.
**Verified:** 2026-10-19T15:01:04Z
**Status:** human_needed
**Re-verification:** Yes — regeneration of a STALE report (no prior gaps; prior status human_needed). Worktree `jiramator-gsd-phase-02-import-preflight-validation`, branch `gsd/phase-02-import-preflight-validation`, HEAD `80b02d3`.

## Goal Achievement

### Observable Truths (Roadmap Success Criteria — the contract)

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | SC1: Replaying the 2026-09-02 Risk shape with `--dry-run` lists missing `Fix versions` and `Repositories` per row, no Jira writes | ✓ VERIFIED (mocked) | Read `cli.py` dry-run branch: builds one `JiraClient`, passes `client=client, dry_run=True` to `run_import`, which calls `run_preflight` and returns before any live code; CLI prints `render_preflight_report` and `sys.exit(1)` on `problems`. `test_import_cli.py::TestImportPreflightDryRun::test_sc1_risk_sheet_reports_all_problems_exit_1` PASSED (asserts create_issue/create_issues_bulk/find_issue_keys_by_summaries/find_user_account_id not called); `test_import_preflight.py::TestPreflightProblems::test_sc1_rows_report_eight_problems_with_column_attribution` PASSED. Literal live replay → human item 1 |
| 2 | SC2: Invalid select values and plain-text-for-ADF values reported in the same preview | ✓ VERIFIED | `payload_validator.find_payload_problems` emits `adf` (`_is_textarea_or_richtext` && not `_looks_like_adf`) and `invalid_option` kinds in one pass; `run_preflight` passes `skip_allowed_value_field_ids={"issuetype"}` so fixVersions IS checked (D-07). `test_select_adf_and_fix_version_problems_reported_together` PASSED |
| 3 | SC3: A live `import` reports all failing rows up front instead of one 400 at a time | ✓ VERIFIED | `importer.run_import`: `_persist()` (L383) → `run_preflight` (L389) → on `problems`, one `_record(..., "failed")` per problem row in row order, `report.error = abort_info(...)`, `_persist()`, return — all before `find_issue_keys_by_summaries` (L425) and `create_issue` (L579). `cli.py` sets `status="failed"`, writes report, prints, exits 1 before finalization. `TestImportPreflightLiveAbort::test_live_sc1_aborts_before_create_exit_1`, `TestRunImportPreflightAbort::*` (3) PASSED |
| 4 | SC4: Without credentials, `import --dry-run` still previews and says schema validation was skipped | ✓ VERIFIED | Code path read; `test_dry_run_degrades_gracefully_without_credentials` PASSED (asserts exit 0 + "Schema validation skipped"). **Independently reproduced** with the real CLI: `env -u JIRA_TOKEN -u JIRA_EMAIL jiramator import --dry-run` on example configs → both "Preview based on field_aliases only" and "Schema validation skipped" printed, preview rendered (markup summary `Risk [bold]A[/]` printed literally), exit 0 |

**Score:** 4/4 roadmap SCs verified (0 present-but-behavior-unverified).

### Plan must_haves truths (02-01 … 02-04)

All plan truths were checked against code and named passing tests. Highlights:

| Plan | Truth (abridged) | Status | Evidence |
|---|---|---|---|
| 02-01 | createmeta failure → `unavailable`, "Schema validation skipped", no ✓; get_fields failure alone degrades only the preview | ✓ | `run_preflight` except-block returns `unavailable`; `render_preflight_report` unavailable branch has no ✓; cli separates `get_fields` try. `TestPreflightAvailability::*`, `test_unavailable_says_skipped_without_check_mark` PASSED |
| 02-01 | Unknown / missing issue type is a row problem (casefold match, one fetch per type) | ✓ | `by_casefold`, `schema_by_id` cache; `_NO_ISSUE_TYPE_PROBLEM` |
| 02-01 | `plan` behaviour byte-identical; planner.py unchanged | ✓ | `git diff $(merge-base develop HEAD) HEAD -- jiramator/planner.py` empty; `find_payload_problems` defaults reproduce removed logic line-for-line; `test_field_not_on_screen_skipped`, `test_fix_versions_allowed_values_skipped` PASSED |
| 02-01 | D-10 off-screen wording; D-09 escaped `[IssueType]`; ordering/adjacency/empty edges; Rich markup safety | ✓ | `_row_problem_messages`, `_row_header` (`escape(f'[{issue_type}]')`); `test_off_screen_field_reported_with_column_and_issue_type`, `test_identical_rows_reported_separately_in_row_order`, `test_empty_select_cell_is_only_subject_to_required_check`, `test_markup_in_summary_printed_literally` (both files) PASSED |
| 02-01 | OQ-2 dry-run `--resume` parity | ✓ | dry-run passes `prior_report`; `_prior_created_keys` → `skip_template_keys`; `test_resume_dry_run_skips_rows_already_created` PASSED |
| 02-01 | **Backstop:** option comparison exact code-point equality matches Jira | ⚠️ insufficient_spec | Code does use `value in names` (exact). Whether Jira agrees is unverifiable here → human item 5 |
| 02-02 | Shared `PermissiveFieldMeta`/`stub_createmeta`; FakeJiraClient createmeta; `_FakeResult.preflight=None` | ✓ | `tests/conftest.py`; `TestStubCreatemeta::*` (6), `TestStubCreatemetaThroughPreflight::*` (2) PASSED |
| 02-03 | Abort report: status failed, `error.type=="Aborted"`, one failed IssueResult per problem row, sanitized | ✓ | `_record` sanitizes via `sanitize_message`; `abort_info` sanitizes; `test_abort_error_redacts_token`, `test_mixed_sheet_records_only_failing_rows` PASSED |
| 02-03 | Unavailable on live → loud warning, proceed | ✓ | cli L739-748; `TestImportPreflightLiveUnavailable::*` (3) PASSED |
| 02-03 | Resume semantics; build-failed rows in abort; zero rows → no createmeta call; dedup rows still validated | ✓ | `TestRunImportPreflightResume::*` (7), `test_duplicate_summary_rows_get_separate_entries` PASSED |
| 02-03 | Caveats in abort output, not on passing live runs | ✓ | `test_live_abort_prints_caveats`, `test_live_all_rows_pass_creates_without_caveat_output` PASSED |
| 02-03 | Docs: README/CHANGELOG `[Unreleased]` Breaking/Added/AGENTS | ✓ | CHANGELOG L6-30; README L170, 334-365, 505-507 |
| 02-03 | **Backstop:** live smoke against real Jira | → human item 1 | Not counted as a separate truth (identical to SC1 live replay) |
| 02-04 | D-06 caveats, sub-task parent, deferred off-screen, OQ-4 coercion row errors, D-08 build-failed rows, exit-code matrix, `--preview-rows`/`--max-rows` | ✓ | `TestPreflightDeferred::*` (9 incl. WR-01 regression `test_non_string_deferred_cell_is_missing_required`), `TestRowBuildCoercionErrors::*` (3), `TestPreflightBuildFailures::*` (3), `TestImportPreflightDryRun::*` PASSED |

### Prohibitions (flagged, judgment-tier — NON-AUTHORITATIVE verdicts)

| ID | Statement (abridged) | LLM-judge verdict | Evidence |
|---|---|---|---|
| P-02-01 | Preflight never writes to Jira, never does user/issue/sprint lookups | HELD | `import_preflight.py` calls only `get_createmeta_issue_types` / `get_createmeta_fields`; tests assert create/dedup/user/sprint mocks not called (`test_import_preflight.py` L524-526, `test_import_cli.py` L690-693, L979-982) |
| P-02-02 | Unreachable createmeta never presented as passed | HELD | `render_preflight_report` unavailable branch emits only the yellow "skipped" line; `test_unavailable_says_skipped_without_check_mark` |
| P-02-03 | Test-harness changes must not weaken existing assertions | HELD | `git diff <merge-base> HEAD -- tests/` contains **zero** removed `assert` lines |
| P-02-04 | No partial create / no `partial` status on problems | HELD | importer returns before dedup/create; cli sets `failed` before finalization |
| P-02-05 | Caveat-only rows never counted as problems | HELD | `problem_rows` filters on `problems`; `test_caveat_only_rows_never_counted_as_problems` |

Flagged for human confirmation (human item 6) — never silently absorbed.

### Required Artifacts

| Artifact | Status | Details |
|---|---|---|
| `jiramator/import_preflight.py` | ✓ VERIFIED | 445 lines; `PreflightRow`, `PreflightResult`, `run_preflight`, `render_preflight_report`; imported by `importer.py` and `cli.py` |
| `jiramator/payload_validator.py` | ✓ VERIFIED | `PayloadProblem`, `find_payload_problems`; `validate_ticket_payload` wraps it with plan-preserving defaults |
| `jiramator/importer.py` | ✓ VERIFIED | preflight at both dry-run and live sites; abort recording; coercion row errors |
| `jiramator/cli.py` | ✓ VERIFIED | dry-run exit 1 on problems; live abort branch; unavailable warning |
| `tests/conftest.py`, `tests/test_cli_e2e.py`, `tests/test_cli.py` | ✓ VERIFIED | stub helpers wired into live tests |
| `tests/test_import_preflight.py`, `tests/test_import_cli.py` | ✓ VERIFIED | substantive suites, all passing |
| `CHANGELOG.md` | ✓ VERIFIED | `[Unreleased]` Breaking entry |

### Key Link Verification

| From | To | Status | Details |
|---|---|---|---|
| `importer.run_import` (dry-run) | `run_preflight` | ✓ WIRED | called when `client is not None`, with `skip_template_keys` from prior report |
| `importer.run_import` (live) | `run_preflight` | ✓ WIRED | after initial `_persist()` (L383), before `find_issue_keys_by_summaries` (L425) |
| importer abort path | `run_report.abort_info` / `_record`→`sanitize_message` | ✓ WIRED | both sanitize |
| `cli.import_command` | `render_preflight_report` / `ImportRunResult.preflight` | ✓ WIRED | `getattr(result, "preflight", None)` at both sites |
| `run_preflight` | `jira_client` createmeta | ✓ WIRED | issue types once; fields once per distinct type id |
| `run_preflight` | `find_payload_problems` | ✓ WIRED | `assume_present_field_ids=frozenset(deferred)`, off-screen + blank-ADF enabled |

### Data-Flow Trace (Level 4)

| Artifact | Data | Source | Real data | Status |
|---|---|---|---|---|
| preflight section (cli) | `PreflightResult.rows` | live `client.get_createmeta_*` over built row payloads | yes (no static fallback; failure → explicit `unavailable`) | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Full suite (run once) | `.venv/bin/python -m pytest -q -rA` | 780 passed | ✓ PASS |
| Lint | `.venv/bin/ruff check .` | All checks passed | ✓ PASS |
| planner.py unchanged vs merge-base | `git diff 88c9e5d HEAD -- jiramator/planner.py` | empty | ✓ PASS |
| SC4 real CLI, no credentials | `env -u JIRA_TOKEN -u JIRA_EMAIL jiramator import --org-config configs/org.example/example.yaml --team-config configs/teams.example/example.yaml --dry-run s.csv` | both warnings, preview, exit 0 | ✓ PASS |
| WR-01 fix present | `git show 80b02d3` | `_deferred_present` uses `isinstance(raw_value, str) and raw_value.strip()`; regression test passes | ✓ PASS |

### Probe Execution

Not applicable — no `scripts/*/tests/probe-*.sh` probes declared or present.

### Requirements Coverage

| Requirement | Source Plan(s) | Status | Evidence |
|---|---|---|---|
| PRE-01 | 02-01, 02-03, 02-04 | ✓ SATISFIED | SC1 + 02-04 truths |
| PRE-02 | 02-01 | ✓ SATISFIED | SC2 |
| PRE-03 | 02-02 (prereq), 02-03 | ✓ SATISFIED | SC3 |
| PRE-04 | 02-01, 02-03, 02-04 | ✓ SATISFIED | SC4 (also reproduced via real CLI) |

All four IDs in REQUIREMENTS.md mapped to Phase 2 are claimed by plans; no orphans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `jiramator/*` (4 phase files), `tests/conftest.py` | — | TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER | — | none found |
| `02-REVIEW-DISPOSITION.md` | WR-01 row | cites fix commit `b7b79ae`, which does not exist in this repo (actual: `80b02d3`) | ℹ️ Info | stale hash after rebase; doc-only |
| branch vs `develop` | — | `develop` has advanced (Release v1.2.9, v1.3.0; `planner.py` +95 lines) since merge-base `88c9e5d` | ℹ️ Info | rebase/merge needed before ship; CHANGELOG `[Unreleased]` and the "v1.2.9 Hardening" milestone label now collide with the released v1.2.9 tag. Not a goal gap |

### Code Review Disposition

WR-01 fixed (`80b02d3`, verified); WR-02 skipped by design per D-08 (accepted — `test_unavailable_drops_build_failed_rows` pins the behaviour); IN-01/IN-02 open info, non-blocking.

### Human Verification Required

1. **Live SC1 dry-run smoke** — real Jira, 2026-09-02 Risk sheet → 8 problems / 6 rows, exit 1, no writes. (UAT #1)
2. **No-credential dry-run on the real org config** → "Schema validation skipped", exit 0. (UAT #2)
3. **Live abort smoke** → nothing created, abort message, exit 1, report failed/Aborted. (UAT #3)
4. **Live D-06 caveat** — required Reporter/Parent on a real create screen → caveat, exit 0. (UAT #4)
5. **Backstop: exact option-value comparison** — confirm Jira rejects case/normalization variants of a select value, or accept the assumption.
6. **Prohibitions P-02-01..05** — confirm the non-authoritative HELD verdicts above.

Items 1-4 are already persisted in `02-UAT.md` (all pending); items 5-6 are new in this regeneration (the prior report omitted the 02-01 backstop truth and the flagged prohibitions).

### Gaps Summary

No functional gaps. Every roadmap SC and PRE-01..04 is backed by present, substantive, wired code and passing named tests (780 passed, ruff clean); SC4 was additionally reproduced through the real CLI. Status is `human_needed` because live-Jira behaviour (UAT 1-4), one backstop truth about Jira's option comparison, and five flagged judgment-tier prohibitions cannot be discharged automatically. Before shipping, the branch also needs to be reconciled with `develop`, which has moved on to v1.3.0.

---

_Verified: 2026-10-19T15:01:04Z_
_Verifier: the agent (gsd-verifier)_
