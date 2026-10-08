---
status: complete
phase: 01-production-triage
source: work-clone run reports (read-only)
started: 2026-10-02T18:06:14Z
updated: 2026-10-05T14:15:00Z
---

# Phase 1: Production Triage — Findings

## Summary

Source: `~/dev/work_projects/jiramator/.jiramator/runs/*.json`, read in place (python `json` read + `os.stat`). The tallies below cover only the run files listed in the D-03 baseline (`workclone-fingerprint.before`, taken 2026-10-02T18:06:14Z).

total: 184 run reports in the baseline
real-CLI: 37 (joined `run.command` does not contain `pytest`; the other 147 are pytest pollution, TEST-01 class)
failed (real-CLI, `run.status == "failed"`): 9
zero-count failed (real-CLI, failed, every `run.counts` value 0, `run.issues == []`): 5 (INV-03 targets)
partial (real-CLI, not in scope): 6 `import` runs. They end with `ended_at` set and per-row errors recorded, so they are not unrecorded failures.

**INV-03 target set** (the completeness check computes this list from the baseline and requires each name exactly once in the Findings Table):

1. `20260713T135104Z-dm-test`
2. `20260716T162224Z-calcs`
3. `20260717T171429Z-calcs`
4. `20260717T174859Z-calcs`
5. `20260721T121841Z-calcs`

All five targets have the same signature: `status: failed`, counts 0/0/0, `issues: []`, `ended_at: null`. `run_plan` writes a pessimistic `failed` report first. Before INV-04 (plan 01-01), its `except BaseException: _persist(); raise` handler recorded neither the end time nor the cause.

**Method note (Δ):** the report's file mtime is the last `_persist()` call, which for these runs is the error handler. So Δ = mtime − `started_at` is the time-to-failure. All Δ values below were re-measured this session with `os.stat` and match the RESEARCH Evidence Inventory to the millisecond:

- 5–10 ms → exit before any I/O.
- ~1 s → exit during the createmeta round-trip.
- ≥10 s → exit after prompts or network.

The resolved-config hash (`run.resolved_config_hash`, first 8 hex chars shown) identifies identical effective config across runs.

## D-03 work-clone integrity

Baseline file: `.planning/phases/01-production-triage/workclone-fingerprint.before` (persistent disk, gitignored; 195 lines = 3 `S` porcelain lines + 192 `F` file lines, of which 184 are `.jiramator/runs/`)
Baseline taken: 2026-10-02T18:06:14Z, before any evidence read of the work clone
Baseline sha256: a93f59915776f6c20697da209c1ff3d74df715d65e93cd6426aafb4c22913780

The baseline git status contains three pre-existing untracked spreadsheets (`Risk Jira Generation Template.xlsx`, `mass_create_worksheet.xlsx`, `~$Risk Jira Generation Template.xlsx`). These are the user's files and existed before this phase.

Tool: `.planning/phases/01-production-triage/workclone_fingerprint.py`. It is stdlib-only, never imports jiramator, never opens a work-clone file for writing, never changes cwd into the work clone, and calls git only as `git --no-optional-locks -C <root> status --porcelain`.

- `snapshot OUT` writes the baseline.
- `compare BASELINE` classifies each difference as PRODUCTION-RUN (allowed), PHASE-RUN, MODIFIED, DELETED, ADDED-OTHER or STATUS-CHANGED (all of which are violations). It then prints exactly one `INTEGRITY:` line.

A compare run immediately after the snapshot printed `INTEGRITY: identical`. Plans 01-03 and 01-05 re-run the compare. Before they do, they verify that `sha256sum` of the baseline still equals the hash above.

### Phase-close check (plan 01-05, 2026-10-05)

- The baseline sha256 was re-verified and still equals the hash above.
- After snapshot: `.planning/phases/01-production-triage/workclone-fingerprint.after`, 195 lines, sha256 `a93f59915776f6c20697da209c1ff3d74df715d65e93cd6426aafb4c22913780`, which is byte-identical to the baseline.
- `compare` output (verbatim; no classification lines were emitted):

```
INTEGRITY: identical
```

Result: INTEGRITY: identical

## Findings Table

Rows are ordered by report filename timestamp ascending. Filenames carry second-resolution UTC stamps, so ties cannot occur. Rows marked † are **non-zero** failed reports, included so the table covers every failed real-CLI report. The 5 zero-count INV-03 targets are rows 1, 5, 7, 8 and 9. Line numbers are on this branch's HEAD (`bd1b686`, after plan 01-01). Where they moved, RESEARCH's numbers are given in brackets.

| # | Report | Command | Classification | Root cause | Disposition | Evidence |
|---|---|---|---|---|---|---|
| 1 | 20260713T135104Z-dm-test | `.venv/bin/jiramator plan --dry-run --team-config configs/teams/dm-test.yaml --pi-number 26.4 --versions 26.4.1,26.4.2 --yes` | input error (expected behaviour, unrecorded) | Non-TTY invocation with `board_id` set, no `--sprints-exist`/`--no-sprints-exist` flag and no `sprints_exist:` in config. `_resolve_sprints_exist_mode` raises `ConfigValidationError` (planner.py:237 [234]). cli prints a clean message, but the pre-INV-04 report recorded nothing | covered by INV-04 (plan 01-01); no code fix | Δ = 5–6 ms (before any I/O). Adjacent: `20260713T135110Z-dm-test` 6 s later adds **only** `--no-sprints-exist`, same hash `b976c5a5`, and succeeds. Behaviour exists since `2932355` (2026-04-30). Assumption A5: non-TTY / agent-driven |
| 2† | 20260713T140620Z-dm-test | `jiramator plan --team-config configs/teams/dm-test.yaml` (live) | config/environment (non-zero: 0/0/18) | `customfield_10273` (API Impact) is not on DM's screens, so Jira returns 400 for all 18 per_release rows | none (config fixed by the user; documented in the dm-test copy header NOTE). Same problem class as Phase 2 PRE-* | Δ = 15.7 s. All 18 rows carry `Field 'customfield_10273' cannot be set…`. Hash `a9f005ae`. Adjacent: `20260713T141121Z` dry-run, then `141438Z` live with the field removed |
| 3† | 20260713T141438Z-dm-test | `jiramator plan --team-config configs/teams/dm-test.yaml` (live) | config/environment + code gap already fixed by `963b5f2` (INV-02; non-zero: 18/0/7) | `PI26.4` umbrella version referenced by the per_sprint template was missing in DM, and v1.1.0 did not pre-create template-only fix versions | already fixed by `963b5f2` (v1.1.1); no new code | See [§INV-02](#inv-02-version-name-fix-versions-is-not-valid). 18 per_release created, 7 per_sprint failed with `Version name 'Fix versions' is not valid`. Hash `17291500` |
| 4† | 20260713T154340Z-dm-test | `jiramator plan --resume --team-config configs/teams/dm-test.yaml --force` | input error (expected behaviour, unrecorded) — non-zero (18 carried) | Resume without `--no-sprints-exist` exits before any new write and records no new rows. Same unrecorded-exit class as row 9 | covered by INV-04 (plan 01-01); no code fix | Δ = 22.0 s. 18 carried `created` issues, no new rows. Hash `17291500`. Adjacent: `20260713T155804Z` resume **+ `--no-sprints-exist`**, same hash, succeeds with 25. Confidence LOW |
| 5 | 20260716T162224Z-calcs | `.venv/bin/jiramator plan --dry-run --pi-number 26.4 --versions 26.4.1` | input error (expected behaviour, unrecorded) | Same as row 1: calcs.yaml has `board_id: 362` and no `sprints_exist` key, non-TTY → `ConfigValidationError` (planner.py:237 [234]) | covered by INV-04 (plan 01-01); no code fix | Δ = 10 ms. Adjacent: `20260716T162236Z-calcs` 12 s later adds **only** `--no-sprints-exist`, same hash `65e09fab`, succeeds. Behaviour since `2932355` |
| 6† | 20260716T171150Z-calcs | `jiramator plan` (live) | code defect already fixed (non-zero: 0/0/18) | `customfield_10042` was sent as a plain string; Jira returns "not valid Atlassian Document Format" | already fixed by `8f9ebf0` (v1.2.4, 2026-07-16 13:20 EDT); no action | Δ = 20.6 s. All 18 rows carry the ADF error. Adjacent: `20260716T172219Z` live, 10 min later, succeeds with 25 (hash `aa0994e1`) |
| 7 | 20260717T171429Z-calcs | `.venv/bin/jiramator plan --dry-run --pi-number 26.4 --versions 26.4.1 --no-sprints-exist` | HYG-04 | 1 release, but calcs.yaml `release_sprint_schedule` has keys `2` and `3` only. `build_per_release_tickets` raises `ValueError("Team 'Calcs' has no release_sprint_schedule entry for 1 release(s) …")` (ticket_builder.py:286-296 [286-295]). cli catches only `ConfigDriftError`/`ConfigValidationError`, so the user sees a raw traceback | attributed to HYG-04 (Phase 4); no new defect | Δ = 8 ms. Schedule introduced by `c5d1fc6` (2026-07-16 14:46 EDT); the earlier single-version dry-runs (`171911Z`/`171916Z` on 07-16) predate it and succeeded. Adjacent: `20260717T171446Z` 17 s later changes **versions** to `26.4.1,26.4.2` (hash `22a86abb`) and succeeds |
| 8 | 20260717T174859Z-calcs | `.venv/bin/jiramator plan --dry-run --pi-number 26.4 --versions 26.4.1,26.4.2 --no-sprints-exist` | already fixed by `24dd6e0` (dev-in-progress artifact) | Live createmeta validation (WIP `70644ec`, 2026-07-17 13:03 EDT) flagged not-yet-created release versions as invalid `fixVersions`. `_preflight_validate` printed the problems, then `persist(); sys.exit(1)` | already fixed by `24dd6e0` (13:59 EDT, adds `_SKIP_ALLOWED_VALUES_FIELD_IDS = frozenset({"fixVersions"})`, payload_validator.py:29); no action | Δ = 1.09 s (createmeta round-trip). Adjacent: `20260717T175148Z` 3 min later, **identical args and hash `22a86abb`**, succeeds. D-05: the pair differs in **code** (working tree before the 17:59 UTC commit), not in flags. The second witness is `24dd6e0`'s commit message: "Confirmed against a real plan run: every not-yet-created release version was flagged as invalid, aborting the run." Confidence MEDIUM (A4) |
| 9 | 20260721T121841Z-calcs | `.venv/bin/jiramator plan` (interactive, live) | user-accepted residual c, d, e, f, g, h, j (FA-INV-01) — see [INV-01 Root cause](#root-cause) | Pre-write abort in a live-only path; no issue writes (JQL 0). The report cannot separate exits c, d, e, f, g, h, j | INV-04 coverage (c, d, f, h); HYG-05 (e, g, j) — closed 2026-10-05 per D-06 | Δ = 10.4 s. Adjacent: `20260721T121731Z` dry-run 70 s earlier, **same hash `fdedcb7e`**, succeeded. No later calcs `plan` run exists to compare (next report is a 2026-09-02 `import`). The identical 25 tickets were already created on 07-16 (`172219Z`) |

## Method

- No jiramator command was run against the work clone, and no Jira call (read or write) was made in this plan.
- Every work-clone access was read-only: `os.walk`/`os.stat`, python `json` reads of run reports, a plain read of `.jiramator/test-configs/dm-test.yaml`, and `git --no-optional-locks -C … status --porcelain`. The cwd was always this repo.
- The D-03 baseline fingerprint was taken first, before any of these evidence reads.
- Real CLI = joined `run.command` does not contain `pytest`. Zero-count = `run.status == "failed"` and every value in `run.counts` is 0.
- Commit SHAs and timestamps come from `git log` in **this** repo, which contains every cited commit.
- Line references were re-checked on this branch's HEAD.
- No credentials appear in any report field cited here.

## INV-02: Version name 'Fix versions' is not valid

**Report:** `20260713T141438Z-dm-test` (Findings Table row 3). Live `plan` started 14:14:52 UTC (10:14 EDT).

### Evidence chain

1. **Report rows.** `run.issues` has 25 rows: 18 `per_release` rows `created` and 7 `per_sprint` rows `failed`. Every failed row's `error` reads `Jira API error (400) while bulk creating issues (batch 1/1). Field errors: … {'fixVersions': "Version name 'Fix versions' is not valid"}`. `run.pi_label = PI26.4`, `run.versions = [26.3.1, 26.3.2, 26.4.0]`.
2. **Surviving config copy.** `~/dev/work_projects/jiramator/.jiramator/test-configs/dm-test.yaml`, mtime 2026-07-13 15:55:04 UTC (11:55 EDT), read in place. Its header NOTE, quoted verbatim:
   > NOTE: per_sprint_tickets uses fixVersions: ["{pi_label}"] on purpose — a PI-umbrella Jira Version (e.g. "PI26.4") separate from the per-release versions (e.g. "26.4.1"). … Unlike release versions, this one isn't typed in via --versions, so planner.py's fix-version step scans every built ticket payload for referenced fixVersions (not just the typed-in release list) and offers to auto-create any that don't exist yet — you'll be prompted to confirm before "PI26.4" is created as a Version in DM.

   The same header documents the earlier `customfield_10273` 400 (row 2).
3. **Same config across the window.** The resolved-config hash `17291500ae85be24…` is identical for:
   - the failing run `141438Z` (14:14 UTC)
   - the resume `154340Z` (15:43 UTC)
   - the successful resume `155804Z` (15:58 UTC, 25 created)

   The copy was saved at 15:55 UTC, inside that window, so it is the config the failing run used. The hash covers the org + team model dumps (`compute_resolved_hash`, run_report.py).
4. **Code fix.** At 10:14 EDT the code was v1.1.0. `963b5f2` ("release: v1.1.1 — fix versions from templates, ADF description, README polish", 2026-07-13 12:15:39 −0400) introduced `_collect_referenced_fix_versions` (planner.py:255; called at :922 on HEAD). The `git show --stat 963b5f2` header, re-run this session:
   ```
   commit 963b5f2a7dec489550a0032509c089ed1063385e
   Date:   Mon Jul 13 12:15:39 2026 -0400
       release: v1.1.1 — fix versions from templates, ADF description, README polish
       - plan: fix versions referenced only inside a ticket template's fields
         (e.g. fixVersions: ["{pi_label}"] on a recurring ticket) are now scanned
         from the built payloads and offered for creation, not just the release
         versions typed in at the --versions prompt.
   ```
   The CHANGELOG entry `## [1.1.1] — 2026-07-13` (CHANGELOG.md:192-199) says a fix version referenced solely inside a ticket template's fields *"would cause a confusing 400 error at ticket-creation time instead of the normal create-with-confirmation flow."* That describes this failure.
5. **D-07(a) falsification: aliases cannot inject the value.** Re-run this session:
   ```
   $ grep -n "field_aliases\|value_aliases" jiramator/ticket_builder.py jiramator/config_merge.py jiramator/planner.py
   (no output; grep exit 1)
   ```
   `plan` never reads `bulk_create.field_aliases`/`value_aliases`. `fixVersions` values come only from template `fields` via `resolve_value` → `_wrap_field` (`name_object_array`). The org-config aliases (`Fix Versions: fixVersions`, etc.) map spreadsheet header **names** to field IDs for `import`/`update` only. They cannot become a `fixVersions` **value** in `plan` (D-07b).
6. **Regression coverage already on HEAD:**
   - tests/test_planner.py:252-284: `TestCollectReferencedFixVersions`
   - tests/test_planner.py:622-626: per_sprint `["{pi_label}"]` umbrella version offered for creation

### Unrecoverable input (D-07)

The original `configs/teams/dm-test.yaml` input is **deleted** from the work clone (`os.path.exists` → False). It was **not reconstructed**. The attribution rests on the surviving `.jiramator/test-configs/dm-test.yaml` copy and the matching hash, and holds without the original file.

### Assumption A1 (encoding: field name vs. value)

Jira's message `Version name 'Fix versions' is not valid` quotes **the field display name** "Fix versions" (Jira Cloud's createmeta name for `fixVersions`, also used in tests/test_payload_validator.py:166). It does not quote the value sent, which was `PI26.4` (from `{pi_label}` per evidence 2 + 3).

**Risk if wrong:** low. If Jira did quote the sent value, the template would have had to hold the literal string "Fix versions". The hash-matched copy contradicts that, and evidence 5 rules out alias injection, so the disposition is unchanged either way.

Related assumption A2: `PI26.4` was created in DM (manually) between 14:15 and 15:58 UTC. It does not affect the disposition.

### Disposition

config/environment + code gap already fixed by 963b5f2 — no new code. The `PI26.4` umbrella version was missing in project DM, and v1.1.0 only checked/created the typed-in `--versions`, not template-referenced fix versions.

## D-NEW-1: JiraClient does not wrap requests exceptions

**Found during:** Phase 1 research (INV-01 exit-point analysis, RESEARCH §D-NEW-1), re-checked in plan 01-02.

**Symptom:** a connection, TLS or timeout error during a live Jira call escapes as a raw `requests.exceptions.*` traceback instead of an actionable `JiraApiError` message. During bulk create, a read timeout after Jira has accepted the batch records **no rows** in the run report. A later `--resume` would then re-create the batch and **duplicate** tickets. That breaks the core value "safe to re-run".

**Root cause:**
- `JiraClient` never catches `requests.exceptions.RequestException`: `grep -n RequestException jiramator/jira_client.py` returns nothing. Yet `JiraApiError` documents `status_code: … (None for connection errors)` (jira_client.py:36-37).
- The callers catch only `JiraApiError`, so a transport error passes straight through. Uncaught sites on HEAD (RESEARCH line numbers in brackets):
  - sprint lookup `_resolve_sprint_ids`: `except JiraApiError` at planner.py:1020 [983]
  - epic `create_issue`: planner.py:977 [942]
  - `create_issues_bulk` in `_bulk_create_with_resume`: planner.py:1107 [1069]
  - `get_fix_versions` / `create_fix_version` have no wrapper at all
- Corporate TLS interception (`JIRAMATOR_CA_BUNDLE`, `JIRAMATOR_RELAX_TLS_STRICT`, AGENTS.md) makes SSL errors a realistic trigger.

**Why not fixed in Phase 1:**
- It fails the D-08 "trivial" bar: the fix touches every `JiraClient` method and the bulk-create retry/resume semantics.
- It fits this milestone's hardening scope (core value "safe to re-run"), so D-10 (GitHub issue for out-of-milestone work) does not apply.

**Disposition:** folded into Phase 4 as **HYG-05** (D-09), with traceability in `.planning/REQUIREMENTS.md` and ROADMAP Phase 4 success criterion 6.

**Escalation:** plan 01-04 records whether INV-01 (row 9) was exit path k, i.e. a transport error during bulk create, with tickets possibly created on 2026-07-21. If it was, HYG-05 becomes the INV-01 disposition and its priority is raised.

## INV-01: 2026-07-21 live plan

**Report:** `20260721T121841Z-calcs.json` (Findings Table row 9). `jiramator plan` (interactive, live) from the work clone's `.venv` (v1.2.8 editable install). `started_at` 12:19:01.541Z, last persist (mtime) 12:19:11.940Z, so **Δ = 10.4 s**. Status `failed`, counts 0/0/0, `issues: []`, `ended_at: null`, hash `fdedcb7e`.

### Inputs

- Config facts (calcs.yaml, copied with `cp -p` to `/tmp/jm-triage/configs/`): `project_key: CA`, `board_id: 362`, no `sprints_exist` key (so a TTY run prompts "Are the sprints … already created?"), `recurring_epics: []` (so no epic writes), `existing_epics: {bau: CA-5078, misc: CA-5079}`, per_sprint `fixVersions: ["{pi_label}"]`, and `release_sprint_schedule` keys `2` and `3` only.
- Interactive answers on 07-21 (from the report): PI `26.4` → `PI26.4`, versions `26.3.1, 26.3.2, 26.4.0` (schedule key `3` exists). Needed fix versions: `26.3.1, 26.3.2, 26.4.0, PI26.4`. 25 tickets in total (18 per_release + 7 per_sprint).
- **Input fidelity check:** the harness runs with the copied configs and these answers produce `resolved_config_hash = fdedcb7ee161…`. That is the same hash as the 07-21 report and the passing 07-21 dry-run (`121731Z`). The harness reproduces the exact effective config of the failed run.
- **Code fidelity:** `git diff v1.2.8 6676bdc -- jiramator/planner.py jiramator/jira_client.py jiramator/config.py` shows only the ruff modernization from `4afba64`: `timezone.utc`→`UTC`, `zip(…, strict=False)`, a removed unused `import time`/`LINE_KEY`, `raise … from None` on a `KeyError`, and an unused `enumerate` index. None of these touch an exit path. `git log --oneline v1.2.8..HEAD -- jiramator/` lists only `4afba64` plus the three INV-04 commits (`85e73f4`, `7df134f`, `bd1b686`). So the pre-01-01 commit `6676bdc` behaves like the v1.2.8 code that ran on 07-21, and it is used for the "before INV-04" table.

### Exit-point table (line numbers on HEAD `bd1b686`)

Every path ends in `run_plan`'s `except BaseException` handler, which persists the report and re-raises. Before INV-04 the handler recorded neither `ended_at` nor a cause.

| # | Step (HEAD line) | Exit | Also in dry-run? | Fits 07-21? | Harness scenario |
|---|---|---|---|---|---|
| a | sprints prompt `_prompt_sprints_exist` (planner.py:204, via `_resolve_sprints_exist_mode` :235) | Ctrl-C / EOF | yes | ✗ the 07-21 dry-run passed this step with the same config on a TTY | `a_ctrl_c_sprints_prompt` |
| b | `build_all` preview (:862) | `ValueError` → traceback | yes | ✗ the same hash passed in the dry-run | `b_builder_value_error` (1 version → no schedule entry) |
| c | `JiraClient(org_config)` (:904-908) | `ValueError` → "Credential error:", `sys.exit(1)` | dry-run degrades to a warning | ✓ only if the creds were absent in that shell | `c_no_credentials` (real JiraClient, JIRA_* unset) |
| d | `_preflight_validate` live (:910, body :473-518) | problems → "✗ Found N field problem(s)", `sys.exit(1)` | yes (same function) | ✓ only if dry-run validation was skipped (no creds or a Jira/connection error) | `d_preflight_problems` |
| e | `_check_and_create_fix_versions` → `get_fix_versions` (:302) | `JiraApiError` or raw `requests` exception → traceback | no | ✓ | `e_get_fix_versions_api_error`, `e2_get_fix_versions_connection_error` |
| f | fix-version confirm (:315-324) | decline → "Aborted. Cannot proceed without fix versions." / Ctrl-C | no | ✓ only if a needed version was missing. All four were used successfully on 07-16 | `f_decline_fix_version_creation` (PI26.4 missing) |
| g | `create_fix_version` (:327) | `JiraApiError` / requests → traceback | no | ✓ same precondition as f | not run separately: same mechanism as e/e2 (uncaught client exception after the same precondition as f) |
| h | duplicate warning + "Create these 25 tickets?" (:936-943, `default=False`) | Enter (No) → "Aborted.", `sys.exit(1)` / Ctrl-C → click "Aborted!" | no | ✓ **leading hypothesis**: the same 25 tickets were already created on 07-16 | `h_decline_final_confirm`, `h2_ctrl_c_final_confirm` |
| i | epic loop (:961) | — | — | n/a: `recurring_epics: []` | — |
| j | `_resolve_sprint_ids` → `get_board_sprints` (:1017 → :554) | `JiraApiError` is caught and the run continues. A requests exception is **not** caught → traceback | no | ✓ only if the user answered "yes, sprints exist" | `j_board_sprints_connection_error` |
| k | `_bulk_create_with_resume` → `create_issues_bulk` (:1106) | `JiraApiError` → `failed` rows (non-zero, ✗). A requests exception (e.g. read timeout) is **not** caught → nothing recorded | no | ✓ dangerous variant: Jira may have created the batch | `k_bulk_read_timeout` |

**Unreachable scenarios / D-04:** none. Every candidate exit (a–h, j, k) was reproduced offline on current code. D-04 is therefore not triggered: no v1.2.8 worktree was needed. The pre-INV-04 view uses `6676bdc`, which is behaviour-identical to v1.2.8 (see Inputs, code fidelity).

### Harness

`/tmp/jm-triage/harness.py`, outside the repo, deleted at phase close. It drives `jiramator plan --org-config … --team-config … --report /tmp/jm-triage/reports/<scenario>.json` through click's `CliRunner`, with cwd `/tmp/jm-triage` and `JIRA_EMAIL`/`JIRA_TOKEN` unset.

- `jiramator.planner.JiraClient` is replaced by an in-memory fake. Scenario c uses the real class, which fails at credential resolution before it builds a session.
- `Prompt.ask`, `IntPrompt.ask` and `Confirm.ask` are scripted with the 07-21 answers.
- `sys.stdin.isatty()` is forced to `True` (a TTY, as on 07-21) through a proxy for `jiramator.planner.sys`. CliRunner swaps `sys.stdin` during invoke, so patching the real stdin would have no effect.
- The harness prints its import path to stderr, and the `jiramator` it imports comes from this repo (or from the throwaway worktree for the "before" run). The fake client recorded **no writes** in any scenario.
- A console tail for each scenario is written to `/tmp/jm-triage/reports*/<scenario>.tail.txt`.

#### Before INV-04 (`6676bdc` ≡ v1.2.8 behaviour; throwaway worktree `/tmp/jm-triage/pre-inv04`, since removed)

```
scenario=a_ctrl_c_sprints_prompt exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=b_builder_value_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=c_no_credentials exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=d_preflight_problems exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=e_get_fix_versions_api_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=e2_get_fix_versions_connection_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=f_decline_fix_version_creation exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=h_decline_final_confirm exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=h2_ctrl_c_final_confirm exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=j_board_sprints_connection_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=k_bulk_read_timeout exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=False error_type=None error_message=
scenario=happy_path_control exit=0 status=success counts=0,0,0 issues=0 ended_at_set=True error_type=None error_message=
```

| Scenario | status | counts | issues | ended_at | error |
|---|---|---|---|---|---|
| a, b, c, d, e, e2, f, h, h2, j, k (all 11) | failed | 0/0/0 | 0 | null | (absent) |
| happy_path_control | success | 0/0/0 | 0 | set | (absent) |

All 11 candidate exits produce **the same report as `20260721T121841Z`**: `status: failed`, counts 0/0/0, `issues: []`, `ended_at: null`, and the same hash `fdedcb7e…`. For example, `reports-before/h_decline_final_confirm.json` has the same envelope and `run` key set as the production report. A read-only python `json` compare shows its values differ only in `command`, `started_at`, `team_config_path` and `org_config_path`. `ended_at: null`, `status`, `counts`, `issues`, `pi_label`, `versions` and `resolved_config_hash` are all equal. The report alone cannot tell the exits apart. INV-04 exists to fix exactly this.

#### After INV-04 (HEAD `bd1b686`, this repo)

```
scenario=a_ctrl_c_sprints_prompt exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=KeyboardInterrupt error_message=
scenario=b_builder_value_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=ValueError error_message=Team 'Calcs' has no release_sprint_schedule entry for 1 release(s) (versions: 26
scenario=c_no_credentials exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=Aborted error_message=Credential error: Missing required environment variable(s): JIRA_EMAIL, JIRA_TOK
scenario=d_preflight_problems exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=Aborted error_message=Found 25 field problem(s); no tickets were created.
scenario=e_get_fix_versions_api_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=JiraApiError error_message=Jira API error (500) while fetching fix versions (simulated)
scenario=e2_get_fix_versions_connection_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=ConnectionError error_message=HTTPSConnectionPool(host='jira.example', port=443): Max retries exceeded (simula
scenario=f_decline_fix_version_creation exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=Aborted error_message=Cannot proceed without fix versions: user declined creating PI26.4
scenario=h_decline_final_confirm exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=Aborted error_message=User declined ticket creation at the final confirmation.
scenario=h2_ctrl_c_final_confirm exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=KeyboardInterrupt error_message=
scenario=j_board_sprints_connection_error exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=ConnectionError error_message=HTTPSConnectionPool(host='jira.example', port=443): Max retries exceeded (simula
scenario=k_bulk_read_timeout exit=1 status=failed counts=0,0,0 issues=0 ended_at_set=True error_type=ReadTimeout error_message=HTTPSConnectionPool(host='jira.example', port=443): Read timed out. (read timeou
scenario=happy_path_control exit=0 status=success counts=0,0,0 issues=0 ended_at_set=True error_type=None error_message=
```

| Scenario | ended_at | error.type | error.message (start) | Last console line(s) |
|---|---|---|---|---|
| a_ctrl_c_sprints_prompt | set | KeyboardInterrupt | (empty) | `Aborted!` (click) |
| b_builder_value_error | set | ValueError | `Team 'Calcs' has no release_sprint_schedule entry for 1 release(s)…` | traceback (HYG-04) |
| c_no_credentials | set | Aborted | `Credential error: Missing required environment variable(s): JIRA_EMAIL, JIRA_TOKEN…` | `Credential error: …` |
| d_preflight_problems | set | Aborted | `Found 25 field problem(s); no tickets were created.` | `Aborting — fix the issues above…` |
| e_get_fix_versions_api_error | set | JiraApiError | `Jira API error (500) while fetching fix versions` | traceback after `✓ All ticket fields look valid.` |
| e2_get_fix_versions_connection_error | set | ConnectionError | `HTTPSConnectionPool(…): Max retries exceeded` | traceback after `✓ All ticket fields look valid.` |
| f_decline_fix_version_creation | set | Aborted | `Cannot proceed without fix versions: user declined creating PI26.4` | `Aborted. Cannot proceed without fix versions.` |
| h_decline_final_confirm | set | Aborted | `User declined ticket creation at the final confirmation.` | `Aborted.` |
| h2_ctrl_c_final_confirm | set | KeyboardInterrupt | (empty) | `Aborted!` (click) |
| j_board_sprints_connection_error | set | ConnectionError | `HTTPSConnectionPool(…): Max retries exceeded` | traceback after `Resolving sprints...` |
| k_bulk_read_timeout | set | ReadTimeout | `HTTPSConnectionPool(…): Read timed out.` | traceback after `Creating 18 per_release tickets...` |
| happy_path_control | set | — | — | `── Dry run ── no tickets created.` |

Result: after INV-04, every one of the 11 failure scenarios records `ended_at` and an `error`. Ten of them can be told apart by `error.type` + `error.message`. **Residual gap:** a (Ctrl-C at the sprints prompt) and h2 (Ctrl-C at the final confirm) both record `KeyboardInterrupt` with an empty message. Only Δ (`ended_at` − `started_at`) and the console tell them apart. For 07-21 this does not matter, because a is already ruled out by the passing dry-run. Plan 01-04 may decide whether this is worth a follow-up (e.g. a "last step" breadcrumb).

Sandbox: all reports are under `/tmp/jm-triage/reports/` (after) and `/tmp/jm-triage/reports-before/` (before). `git worktree list` after the run shows no `/tmp/jm-triage/pre-inv04`. D-03 check: the baseline sha256 still equals `a93f5991…2913780`, and `workclone_fingerprint.py compare` printed `INTEGRITY: identical` (no PRODUCTION-RUN lines).

### Timing argument

- The 07-21 dry-run (`121731Z`, same hash, interactive) took **7.8 s** from `started_at` to its final persist. That covers the sprints prompt, the preview, and the createmeta validation round-trips.
- The live run failed after **10.4 s**: the same steps plus about 2.6 s.
- Exits c (credentials) and d (preflight problems) happen at or right after the point where the dry-run finished. They fit only if the user spent noticeably longer at the sprints prompt on the second run. Also, c would have shown "Skipping field validation (no Jira credentials…)" in the dry-run 70 s earlier from the same shell.
- e/e2 (fix-version GET) and f ("All fix versions already exist" is expected, since all four were used on 07-16) add one short round-trip.
- h fits naturally: about 2–3 s to read "This script does NOT check for duplicates … Create these 25 tickets? [y/N]" and press Enter (default No) or Ctrl-C.
- j and k require answering "yes" at the final confirm. k also requires a bulk POST that hit the read timeout (`_DEFAULT_TIMEOUT * 2` = 60 s, jira_client.py:66/397) or a connection error with retries. A 60 s read timeout cannot fit into 10.4 s, but a fast connection or TLS error can.
- Timing is weak evidence. It favours h, makes a long-timeout k implausible, and does not exclude c/d/e/f/j/fast-k.

### Open question for the checkpoint

The offline evidence narrows 07-21 to c, d, e/e2, f/g, h/h2, j or k. It cannot pick one, because before INV-04 every one of them leaves the same report. Two things only the user or Jira can answer settle it:

1. What did the terminal show last? Each branch prints a unique last line (table above).
2. Did Jira receive writes at 08:19 EDT? A read-only JQL for CA issues created 2026-07-21 08:15–08:30 EDT, plus the CA versions list. Any created issue means k (D-NEW-1/HYG-05, safety-relevant). None created rules out k.

Before any jiramator command runs against the real configs with live credentials (an optional live `--dry-run`), the D-03 sandbox decision (plan 01-03 Task 2) must be recorded here.

### D-03 sandbox decision (plan 01-03 Task 2)

D-03 sandbox decision: jql-only (2026-10-02; orchestrator-selected, user unavailable — reversible)

- **Provenance:** the user was unavailable (autopilot run; the user will review later). The orchestrator picked this option on the user's behalf because it carries zero risk: jiramator is not run with live credentials, and nothing is run from or against the work clone.
- **Reversible:** the `sandbox-dry-run` option (`cd /tmp/jm-triage && jiramator plan --dry-run --org-config configs/org/acme.yaml --team-config configs/teams/calcs.yaml --report /tmp/jm-triage/reports/live-dry-run.json`, installed from this repo) can still be run later if the user wants live confirmation of current-code behaviour.
- **D-03 check at this checkpoint (2026-10-02T18:15Z):** `workclone_fingerprint.py compare workclone-fingerprint.before` → `INTEGRITY: identical`.

### User evidence (2026-10-02 checkpoint)

> **Provenance warning:** none of the answers below is the user's own recollection. The user was unavailable. Each answer is labelled with its source. Plan 01-04 maps this evidence to exits; nothing here is interpreted beyond recording.

**Q1. Last terminal line at ~08:19 EDT on 2026-07-21**
- **UNANSWERED: user unavailable.** This is an **open item for the user** to answer on review (scrollback or recollection; "don't remember" is a valid answer).

**Q2. Read-only Jira check.** Source: **gathered by the orchestrator agent through read-only Atlassian MCP calls on 2026-10-02 (reads only; D-02).** Not user-run and not user-verified.
- JQL `project = CA AND created >= "2026-07-21 00:00" AND created < "2026-07-22 00:00" ORDER BY created ASC` (times in EDT). This window is the whole day, which contains the 08:15–08:30 EDT window. It returned 5 issues:

  | Key | Created (EDT) | Summary / note |
  |---|---|---|
  | CA-5132 | 2026-07-21 10:35:47 | "BAU - Continue platform migration", fixVersion PI26.4 |
  | CA-5133 | 2026-07-21 11:00:07 | — |
  | CA-5134 | 2026-07-21 13:40:07 | — |
  | CA-5135 | 2026-07-21 13:42:40 | fixVersion 26.3.1 |
  | CA-5136 | 2026-07-21 13:46:31 | — |

  The orchestrator characterised all five as single, hand-shaped tickets reported by the user, none in the 08:15–08:30 EDT window. **Orchestrator-stated result:** zero CA issues were created in the 08:15–08:30 EDT window, so the 12:18:41Z (08:18:41 EDT) live run made **no issue writes**.
- CA versions list (`get_project_versions CA`):

  | Version | id | Released | releaseDate |
  |---|---|---|---|
  | 26.3.1 | 41030 | yes | 2026-09-14 |
  | 26.3.2 | 41031 | no | — |
  | 26.4.0 | 40831 | no | 2026-11-07 |
  | PI26.4 | 40823 | no | 2026-11-07 |

  All four needed versions exist. Jira's version API exposes **no creation timestamp**, so this API alone cannot show whether 41030/41031 were created by the 07-21 run (an exit after fix-version creation) or earlier (e.g. the 07-16 run). The id ordering (26.4.0 = 40831 < 26.3.1 = 41030 < 26.3.2 = 41031) is **weak evidence only**.

**Q3. Sandbox dry-run output**
- **N/A: jql-only was chosen** (see D-03 sandbox decision above). No live dry-run was run, `/tmp/jm-triage/reports/live-dry-run.json` does not exist, and nothing was run in the work clone (fingerprint `identical`).

### Narrowing

Plan 01-04 Task 1 (2026-10-02). It applies the plan's locked narrowing rules to every evidence item above. Missing evidence keeps a branch `remaining`, and timing never excludes a branch on its own.

Evidence items used:
- **E1:** the 12:17:31Z dry-run `20260721T121731Z-calcs`, interactive, same hash `fdedcb7e`, success, 7.8 s (run report, read-only)
- **E2:** the CA versions list (orchestrator-gathered, read-only MCP, 2026-10-02). All four needed versions exist; there are **no creation timestamps**
- **E3:** the CA JQL count for 2026-07-21 (orchestrator-gathered, read-only MCP, 2026-10-02). **0 issues** were created 08:15–08:30 EDT, out of 5 that day, all between 10:35 and 13:46 EDT
- **E4:** the user's last-line recollection (Q1). **UNANSWERED** (user unavailable)
- **E5:** the timing, Δ 10.4 s live vs 7.8 s dry-run (supporting context only)
- **E6:** the harness signatures. Before INV-04, all 11 scenarios match the production report, so they cannot discriminate between exits
- **E7:** the calcs.yaml config facts (`recurring_epics: []`, no `sprints_exist` key)
- **E8:** the 07-16 live run `20260716T172219Z` (success, 25 created, versions 26.3.1/26.3.2/26.4.0, PI26.4), as supporting context for f/g

| exit | step | verdict | evidence |
|---|---|---|---|
| a | sprints prompt (Ctrl-C/EOF) | ruled out | E1: the dry-run 70 s earlier with the same hash `fdedcb7e` on a TTY passed the sprints prompt |
| b | `build_all` preview (`ValueError`) | ruled out | E1: the same hash passed `build_all` and printed the 25-ticket preview in the dry-run |
| c | `JiraClient` credentials ("Credential error:") | remaining | The rule needs evidence that the 12:17 dry-run ran live field validation (credentials present, preflight passed). E4 is unanswered and Q3 is N/A, so no such evidence exists. E5 (7.8 s suggests createmeta round-trips) is timing only and cannot exclude |
| d | `_preflight_validate` live ("✗ Found N field problem(s)") | remaining | Same as c: no user or live-dry-run evidence that preflight passed on this config 70 s earlier. Timing (E5) cannot exclude |
| e | `get_fix_versions` (`JiraApiError`/requests traceback) | remaining | Decided only by the last line (E4), which is unanswered. E3 (no writes) is consistent with e |
| f | fix-version confirm declined ("Aborted. Cannot proceed without fix versions.") | remaining | The rule needs E2 to show all four versions existed before 07-21 **and** none was created that day. E2 has no creation timestamps, so the second half cannot be shown. E8 shows all four existed on 07-16; f/g would also need a version deleted between 07-16 and 07-21. That is supporting context, not the evidence the rule requires. The id ordering is weak only |
| g | `create_fix_version` (`JiraApiError`/requests traceback) | remaining | Same evidence gap as f (E2 has no creation dates) |
| h | final "Create these 25 tickets?" declined/Ctrl-C ("Aborted." / "Aborted!") | remaining | Decided only by the last line (E4), which is unanswered. Consistent with E3 (no writes) and with E5/E8 (a re-run of tickets already created on 07-16). None of these excludes or confirms |
| i | epic loop | n/a | E7: `recurring_epics: []`, so there are no epic writes |
| j | `get_board_sprints` (requests traceback) | remaining | Needs the user to have answered "sprints exist" and to have confirmed at h. Neither answer is recorded (E4 unanswered, and the pre-INV-04 report has no prompt answers) |
| k | `create_issues_bulk` transport error after Jira accepted | ruled out | E3: the JQL count is 0. No CA issues were created 08:15–08:30 EDT on 2026-07-21, and none of the day's 5 issues is in or near that window. (A no-write transport failure at the bulk POST is the same class as e/j, D-NEW-1/HYG-05, and stays covered by those branches' owner) |

Remaining exits: c, d, e, f, g, h, j

### Proposed root cause

More than one exit remains, so Task 1 picks no single branch. **The user decides at the plan 01-04 Task 2 checkpoint (D-06).** The remaining set, with each exit's classification and owner from the plan's outcome mapping:

| exit | classification | owner |
|---|---|---|
| c | environment (credentials/connectivity), unrecorded | INV-04 coverage (shipped in plan 01-01) |
| d | environment (credentials/connectivity), unrecorded | INV-04 coverage |
| e | code defect D-NEW-1 (transport error unwrapped), no writes | HYG-05 (Phase 4) |
| f | expected behaviour (user declined fix-version creation), unrecorded | INV-04 coverage |
| g | code defect D-NEW-1 (transport error unwrapped), no writes | HYG-05 (Phase 4) |
| h | expected behaviour (user declined; tickets already created 2026-07-16), unrecorded | INV-04 coverage |
| j | code defect D-NEW-1 (transport error unwrapped), no writes | HYG-05 (Phase 4) |

Evidence chain common to all remaining exits:
- Δ is 10.4 s for the live run vs 7.8 s for the dry-run.
- The hash `fdedcb7e` is shared with the passing dry-run, so the config and inputs are identical.
- The production report has 0/0/0 counts, `issues: []` and `ended_at: null`.
- Before INV-04, all 11 harness signatures are identical to the production report.
- User evidence: Q1 is unanswered (user unavailable).
- The orchestrator-gathered read-only JQL found 0 CA issues created 08:15–08:30 EDT, so no issue writes happened and k is excluded.
- The safety-relevant outcome (duplicate tickets from a transport error after Jira accepted the batch) **did not happen** on 2026-07-21.

Every remaining owner already exists. INV-04 (shipped) now records each of these exits with a distinct `error.type`/`error.message`. HYG-05 (Phase 4) owns the transport-error branches e/g/j.

No out-of-milestone defects found (D-10)

### Decision (plan 01-04 Task 2)

INV-01 decision: accept-residual (2026-10-05)
Issue filing: none drafted

### Root cause

The root cause of `20260721T121841Z-calcs` is the user-accepted residual set FA-INV-01 (decided 2026-10-05): exits c, d, e, f, g, h and j. No single exit is named. Each exit is listed with its classification and owner, in letter order:

| exit | classification | owner |
|---|---|---|
| c | environment (credentials/connectivity), unrecorded | INV-04 coverage |
| d | environment (credentials/connectivity), unrecorded | INV-04 coverage |
| e | code defect D-NEW-1 (transport error unwrapped), no writes | HYG-05 |
| f | expected behaviour (user declined fix-version creation), unrecorded | INV-04 coverage |
| g | code defect D-NEW-1 (transport error unwrapped), no writes | HYG-05 |
| h | expected behaviour (user declined; tickets already created 2026-07-16), unrecorded | INV-04 coverage |
| j | code defect D-NEW-1 (transport error unwrapped), no writes | HYG-05 |

Exits a, b and k are ruled out and i is not applicable (see `### Narrowing`). Evidence common to the residual set:
- Δ is 10.4 s for the live run vs 7.8 s for the dry-run `20260721T121731Z`, which shares hash `fdedcb7e`.
- The report has 0/0/0 counts, `issues: []` and `ended_at: null`.
- The JQL result is 0 CA issues created 08:15–08:30 EDT, so the run made no issue writes and no duplicate tickets resulted.
- Q1 (the user's last-line recollection) is unanswered, so the report cannot separate the remaining exits.

### Disposition

- **INV-04 coverage** (shipped in plan 01-01) owns c, d, f and h: any future occurrence records a distinct `error.type`/`error.message` in the run report.
- **HYG-05** (Phase 4) owns e, g and j: transport errors surface as `JiraApiError` and mark the batch's rows as failed.
- No out-of-milestone defects found (D-10)

### Flagged assumptions

- **FA-INV-01-EP:** the GSD spec-less edge-probe fallback produced one INV-01 row with requirement_id INV-01, category unclassified, status unresolved and probe "unclassified — review manually". No automated edge case was derived for INV-01. The `### Narrowing` table is the manual review it asks for.
- **FA-INV-01:** user-accepted residual, decided 2026-10-05. Residual set: c (INV-04), d (INV-04), e (HYG-05), f (INV-04), g (HYG-05), h (INV-04), j (HYG-05).
