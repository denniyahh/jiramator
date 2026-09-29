---
phase: 01-reliability-robustness
plan: 04
subsystem: run-report-integration
tags: [resume, run-report, drift-detection, persist-on-error, template-key, tdd]
provides:
  - _template_key annotation on every payload returned by build_epics/build_per_release_tickets/build_per_sprint_tickets
  - _strip_template_key() helper mirroring the _sprint_num strip-before-send pattern
  - run_plan(report_path, prior_report, force, org_config_path, team_config_path, command) — full report emission + resume contract
  - run_import(report, report_path, prior_report) — symmetric report emission + resume for the import flow
  - _row_template_key(row_number, summary) helper exposing the imported:row<N>:<sha256[:8]> identity scheme
  - try/except BaseException wrappers in both engines guaranteeing persist-on-error under JiraApiError, KeyboardInterrupt, and any other exception
  - Hash-drift gate via ConfigDriftError before any Jira call (run_plan only — run_import drift is owned by cli.py per Plan 05 design)
affects: [reliability-robustness, plan-01-05-cli-integration]
tech-stack:
  added: []
  patterns:
    - Strip-before-send convention extended (_sprint_num → _sprint_num + _template_key)
    - Pre-pessimistic report initialization (status='failed' until end)
    - Persist-after-state-change idiom (every epic, every bulk batch, every row)
    - Resume carry-forward (prior status='created' → copied into current report.issues + counts)
    - Conservative bulk-failure handling (mark every remaining ticket failed for explicit retry, vs leaving in 'pending' which would silently roll on resume)
key-files:
  created:
    - tests/test_planner_report.py
    - tests/test_importer_report.py
  modified:
    - jiramator/ticket_builder.py
    - jiramator/planner.py
    - jiramator/importer.py
    - tests/test_ticket_builder.py
key-decisions:
  - "Annotate _template_key at the call site of build_per_sprint_tickets, not inside _build_sprint_ticket. Reason: the helper doesn't know its own template_idx and forcing it through the signature would break every existing direct caller in tests. Annotating at the loop call site keeps the helper signature stable while still producing per-template-index keys."
  - "Refactored run_plan into run_plan + _run_plan_inner. The outer function owns prompts, drift check, report initialization, and the BaseException try/except (so KeyboardInterrupt during prompts still leaves a valid report on disk). The inner function owns the build/preview/create pipeline. Splitting at this boundary keeps the persist-on-error wrapper readable and avoids deep nesting."
  - "On bulk-create failure, mark every remaining template_key as status='failed' rather than leaving them as implicit 'pending'. Reason: pending status is reserved for the resume design's future use; using it here would couple Plan 04 to resume-flow design assumptions Plan 05+ might revise. failed+retry-on-resume is the conservative semantic. This matches Plan 04 behavior P5 directly."
  - "_row_template_key combines row_number + sha256(summary)[:8] not just one. Reordering rows changes row_number → re-attempt → Jira existing-summary dedup catches the duplicate; identical summaries are still distinguished by row_number. Pure-summary keying would silently skip legitimately-different rows that happen to share a summary; pure-row-number keying would re-attempt every row whenever a user re-orders rows. The combined form is the conservative compromise documented in the plan."
  - "Importer's report kwarg defaults to None and the engine wraps every report mutation in 'if report is not None'. Reason: cli.py (Plan 05) owns the report lifecycle for run_import (init, pass to engine, finalize) — symmetric to how it owns the lifecycle for run_plan via the report_path kwarg. Letting run_import construct an unused RunReport when no report kwarg is passed would allocate per-call and break the existing test surface."
  - "run_plan's bulk creation builds a fresh send-payload dict (`{'fields': dict(epic['payload']['fields'])}`) for the create_issue call rather than mutating the original payload via `payload.pop('_template_key')`. Reason: the original payload may still be referenced by report-emission code or future preview re-display; mutating it would create order-dependent bugs that don't surface in tests until the dict is iterated twice. _strip_template_key (used by bulk creation) is fine because final_payloads has already served the preview by then."
  - "Test P3 captures the on-disk created count BEFORE each create_issue call, not after. Reason: the planner persists AFTER a successful create_issue. Capturing before-call shows snapshots[0]=0, snapshots[1]=1 — proving the file gets rewritten between calls. Capturing after-call would just show the loop counter. The before-call shape is more diagnostic of the persistence cadence."
  - "Tripwire pattern (raise on every attribute access) used in P8 to verify ConfigDriftError raises before any Jira call. Cleaner than asserting individual mock methods weren't called — any client method invocation trips the wire."
duration: 90min
completed: 2026-04-29
---

# Plan 01-04: Run Report Integration (FOUND-02 + FOUND-03) Summary

**Wired the run-report substrate from Plan 03 into both execution engines (`planner.run_plan` and `importer.run_import`), added the `_template_key` annotation that gives every would-be ticket a deterministic resume identity, and verified end-to-end report emission, resume, drift detection, and persist-on-error semantics. After this plan, every plan/import invocation that passes a `report_path` writes a JSON run report on disk; passing a prior report triggers skip-on-already-created behavior.**

## Performance
- **Duration:** ~90min (3 tasks, RED→GREEN→REFACTOR for each)
- **Tasks:** 3 atomic per-task commits
- **Files modified:** 6 (3 source, 3 test files; 1 source file pre-existed and got annotation+helper, the other 2 source files got new kwargs + persist/resume integration)
- **Test count progression:** 366 baseline → **394 passing** (+28 new: 7 ticket_builder + 10 planner_report + 11 importer_report)

## Accomplishments
All 8 must-have truths from the plan satisfied:
1. ✓ Every payload from `build_all()` carries `_template_key` (T1–T4 verify shape, uniqueness, multi-template indexing).
2. ✓ `_template_key` is stripped before send (`_strip_template_key` helper; FakeJiraClient asserts no leak in P2 + I1).
3. ✓ `run_plan(report_path=..., prior_report=None)` produces a `RunReport` written after every state change (P1 dry-run, P2 success, P3 incremental, P4 partial, P5 bulk-fail).
4. ✓ Hash-mismatch + `force=False` → `ConfigDriftError` raised before any Jira call (P8 verifies via Tripwire).
5. ✓ Hash-match + `prior_report` → already-created `_template_key` skipped + `epic_keys` pre-populated (P6).
6. ✓ `run_import(prior_report=...)` skips already-created `imported:row<N>:<hash>` rows (I4).
7. ✓ Final status: success / partial / failed by counts (verified across P2, P4, P5, P9).
8. ✓ Persist-on-error mandatory: `KeyboardInterrupt` mid-run leaves valid JSON on disk with status=failed (P10, I7).

Zero regressions: 366 → 394 passing, no test files unchanged in their behavioral assertions.

## Task Commits
1. **Task 1:** `_template_key` annotation in ticket_builder + `_strip_template_key` helper + 7 tests — `9af0d4f`
2. **Task 2:** planner.py emits report incrementally + consumes prior on resume + 10 tests — `679388b`
3. **Task 3:** importer.py emits report + resume support + 11 tests — `9439625`

## Files Created/Modified
- `jiramator/ticket_builder.py` — Added `_strip_template_key` helper (mirrors `_sprint_num` strip pattern). Modified `build_epics` to attach `_template_key=epic:<ref_key>`. Modified `build_per_release_tickets` to use `enumerate` for `template_idx` and emit `per_release[<idx>]:<version>` keys. Modified `build_per_sprint_tickets` to enumerate templates inside the sprint loop and annotate `per_sprint[<idx>]:<sprint_label>` keys at the call site (preserving `_build_sprint_ticket`'s existing signature).
- `jiramator/planner.py` — Refactored `run_plan` into outer (prompts + drift + report init + BaseException wrapper) + `_run_plan_inner` (build/preview/create pipeline). Added `_bulk_create_with_resume` for resume-aware filtering + strip-before-send + per-failure record emission. Resumed-epic keys pre-populate `epic_keys` so downstream `$epic:ref` resolution works.
- `jiramator/importer.py` — Added `_row_template_key(row_number, summary)` helper. `run_import` gained `report`, `report_path`, `prior_report` kwargs. Loop now records every row's outcome to the report (created/skipped/failed branches) and persists atomically per-row. `try/except BaseException` ensures interrupt-during-import leaves a valid report on disk.
- `tests/test_ticket_builder.py` — 7 new tests (T1–T6 + multi-template per_sprint indexing).
- `tests/test_planner_report.py` — 10 new tests, FakeJiraClient test double, P1–P10 covering dry-run, success, incremental emission, partial failure, bulk failure, resume created/failed, drift with/without force, KeyboardInterrupt persist.
- `tests/test_importer_report.py` — 11 new tests including I1–I7, template-key shape, and backward-compatibility for callers without report kwargs.

## Decisions & Deviations
See the `key-decisions` block above for the full record. Highlights:
- **Refactor:** `run_plan` split into outer + inner — the only deviation from the plan's structure (which suggested a single `run_plan` body). Reason: the BaseException wrapper needs to cover the full pipeline including the prompts (so a Ctrl-C at the prompt still produces an empty-but-valid report on disk after report initialization). Splitting keeps the indentation manageable. The split is invisible to callers — the public signature is exactly what the plan specified.
- **Bulk failure semantic:** The plan offered a choice between `pending` and `failed` for tickets in a bulk that didn't go through. Chose `failed` per the plan's documented preference; the reasoning is now also encoded in `_bulk_create_with_resume`'s docstring.
- **Conservative resume identity for imported rows:** `imported:row<N>:<sha256[:8]>` over either pure-row-number or pure-summary alternatives. Plan 04's threat model already documented this as the right call (T-01-15 + T-01-18 reasoning).
- **Test P3 inversion:** Captured snapshots BEFORE create_issue call, not after — fixed during GREEN iteration when after-call captured 0 instead of 1 (the persist happens on return to the planner, not inside the spy). Documented in the test docstring.

## Next Phase Readiness
- Wave 2 complete: 1/1 plan done (01-04). Wave 3 (Plan 01-05, CLI integration) is unblocked.
- Plan 01-05 will add `--report`, `--resume`, `--force`, `--encoding` flags to cli.py. The data and engine surfaces are now exactly what 01-05's plan expects:
  - `default_report_path` for the default location of `--report`.
  - `find_resumable` for `--resume` (with no path arg).
  - `RunReport.from_envelope` for parsing a user-supplied path or the resumable file.
  - `run_plan(report_path=..., prior_report=..., force=...)` and `run_import(report=..., report_path=..., prior_report=...)` accept exactly the kwargs cli.py will pass.
- Phase 1 progress: **4/5 plans complete (80%)**. Plan 01-05 remains.
- Test count: **394 passing** (started Phase 1 at 277, +117 over the phase; +28 in this plan alone). All on the same branch `feature/bulk-create-foundation`.
- The strip-before-send convention is now established with two siblings (`_sprint_num`, `_template_key`). Future plans adding internal payload metadata can follow the same pattern: add the annotation in the builder, add a `_strip_<name>` helper, call it in the engine right before `client.create_*`.
