# Phase 1: Production Triage - Research

**Researched:** 2026-10-02
**Domain:** Forensic triage of run reports + a small, backward-compatible run-report schema extension (Python 3.11+, stdlib dataclasses, click CLI)
**Confidence:** HIGH for INV-02/INV-03 classification and the INV-04 design. MEDIUM for INV-01: the mechanism class is pinned down, but the specific branch needs one human/Jira confirmation.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
**Reproduction method**
- **D-01:** Reproduce with the **current code** (`develop`), against the work clone's real configs (`~/dev/work_projects/jiramator/configs/org/acme.yaml`, `configs/teams/calcs.yaml`), using `plan --dry-run` only.
- **D-02:** `--dry-run` with live credentials is allowed — it reads Jira (createmeta, field metadata, board sprints) but must never write. **No live `plan`/`import`/`update` runs against Jira in this phase.**
- **D-03:** The work clone is **read-only**: copy configs/reports out to a temp dir; never edit, commit, or run from inside `~/dev/work_projects/jiramator`. — **Reversibility:** one-way — it is the production clone the user runs at work; a stray edit or run report there affects real usage.
- **D-04:** Check out an older release tag (e.g. `v1.2.2`…`v1.2.8`, in a throwaway worktree) **only** when current code cannot reproduce a failure and the history suggests it was fixed in between.

**Bar for "done"**
- **D-05:** A failure is resolved as "already fixed by commit X" when the git history **and** a failed→succeeded run pair (same command, seconds/minutes apart, with a changed flag/input) support it. A written rationale citing both is sufficient — no reproduction at the old SHA required.
- **D-06:** **INV-01 (2026-07-21 live `plan`) must be reproduced or concretely explained** — no "probably fixed". It has no follow-up success run and was a live run, so it is the only genuinely open case.
- **D-07:** INV-02: `configs/teams/dm-test.yaml` was deleted, so the original input is unrecoverable. Resolve by (a) checking whether current code can turn any config/alias input into a literal `"Fix versions"` fixVersions value (code path through `fix_version`/`Fix Versions` aliases in `configs/org/acme.yaml`), and (b) if not reproducible, documenting it as config-caused with the evidence. Do not reconstruct dm-test.

**Disposition of findings**
- **D-08:** Trivial defects (small, isolated, test-coverable) are **fixed inside Phase 1**, each with a regression test.
- **D-09:** Larger defects that fit v1.2.9 become **new requirements in Phases 2–4** (update REQUIREMENTS.md traceability + ROADMAP success criteria).
- **D-10:** Defects outside the hardening milestone are filed as **GitHub issues on `denniyahh/jiramator`** (personal repo; not Jira — this is the user's personal project).
- **D-11:** Triage output is a written findings table (one row per failed report: report file, command, classification, root cause, disposition, evidence) — the phase's deliverable for INV-03.

**Run-report error capture (new requirement INV-04)**
- **D-12:** Added to this milestone as **INV-04, in Phase 1**: when a command that writes a run report exits on an exception, the report records `ended_at` and the error (exception type + message) before re-raising. Root reason triage is hard today.
- **D-13:** Must stay **backward compatible**: existing reports without the new field(s) must still load and resume (`find_resumable`, `--resume`). New field(s) optional with a default. — **Reversibility:** costly — run-report JSON is read by `--resume` across versions; a breaking schema change strands users' in-flight resumes.

### the agent's Discretion
- Exact field name/shape for the recorded error (e.g. `error: {type, message}` vs flat string) and whether `schema_version` bumps — pick what keeps D-13 true.
- Order of investigating the reports; temp-dir layout for reproduction.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INV-01 | Root cause of the 2026-07-21 live `plan` failure (`20260721T121841Z-calcs.json`) identified, then fixed or filed | §INV-01: mtime-based failure timing (10.4 s after `started_at`), a list of every exit point in the live path that leaves this signature, and a short list of candidates to settle with one user/Jira-read checkpoint. Side finding: unwrapped `requests` exceptions in the live path (defect D-NEW-1) |
| INV-02 | `Version name 'Fix versions' is not valid` attributed to config or code | §INV-02: a surviving copy of dm-test.yaml (`.jiramator/test-configs/dm-test.yaml`) has the same resolved-config hash window as the failed run. The value sent was `"{pi_label}"`→`PI26.4`, which was missing in DM. The code gap was fixed in v1.1.1 (`963b5f2`) about 2 h later. `plan` cannot produce a literal "Fix versions" value |
| INV-03 | Every zero-count `failed` report classified | §Findings Table draft: all 5 targets classified with evidence, plus the 4 non-zero failed reports for completeness |
| INV-04 | Crashing `plan`/`import` records `ended_at` + error; old reports still load/resume | §INV-04: current schema, the strict `cls(**run)` loader, exact insertion points (planner.py:790, importer.py:497, cli.py:662), field shape, tests to extend |
</phase_requirements>

## Project Constraints (from AGENTS.md / .github/copilot-instructions.md)

`.github/copilot-instructions.md` only points to AGENTS.md. Directives from AGENTS.md that apply here [VERIFIED: AGENTS.md read this session]:
- Every source file starts with `from __future__ import annotations`. Use explicit imports and fully annotated signatures with lowercase generics.
- All user-facing output goes through `rich.console.Console(stderr=True)`, never `print()`. `logging` only in `jira_client.py`.
- CLI unrecoverable errors: print a Rich message, then `sys.exit(1)`.
- Google-style docstrings. Use the `# ----` section dividers in source and tests.
- Tests: `Test<Component>` classes, `test_<behavior>_<expected>` names. Patch symbols where they are **used** (e.g. `jiramator.planner.JiraClient`, `jiramator.planner.Confirm.ask`). Don't mock Pydantic, YAML loading or the builder.
- Lint: `ruff check .` (E,F,W,I,UP,B; E501 ignored). **Do not run `ruff format`.**
- CI: Linux/macOS/Windows × Python 3.11/3.12/3.13, `python -m pytest -q`.
- `tests/test_integration.py` count assertions (25 tickets) are a regression guard. Don't change the fixture casually.

## Summary

All five zero-count `failed` reports share one signature: `status: "failed"`, all counts 0, `issues: []`, `ended_at: null`. They come from two mechanisms:
1. `run_plan` writes a pessimistic `failed` report first (planner.py:778).
2. Its `except BaseException: _persist(); raise` handler (planner.py:790-795) records neither `ended_at` nor the cause.

The fastest way to recover what the report doesn't say is the **report file's mtime**. It equals the last `_persist()` call, which is the error handler, so `mtime − started_at` gives time-to-failure. I measured it for every target with `stat` (read-only):
- 5–10 ms → crashed before any I/O.
- ~1 s → crashed during the createmeta fetch.
- ~10 s → crashed after prompts and network.

Combined with the adjacent succeeded runs and `git log v1.1.0..v1.2.8`, four of the five targets classify with HIGH/MEDIUM confidence.

INV-02 is settled by a source not mentioned in CONTEXT.md. `~/dev/work_projects/jiramator/.jiramator/test-configs/dm-test.yaml` (mtime 2026-07-13 11:55 EDT) is a saved copy of the dm-test config, made inside the window where the run reports show the resolved-config hash unchanged (`17291500…` at 14:14 UTC failure and 15:58 UTC success). Its header comments describe the exact failure and the intended fix. The per-sprint template sends `fixVersions: ["{pi_label}"]` → `PI26.4`, which did not exist in project DM. Pre-v1.1.1 code only checked/created the typed-in `--versions`, so the 7 per-sprint tickets got a Jira 400. Only per_sprint failed, while all 18 per_release tickets (existing versions) were created. v1.1.1 (`963b5f2`, same day 12:15 EDT) added `_collect_referenced_fix_versions`, which is still on HEAD with tests. `plan` never consults `field_aliases`/`value_aliases` (grep: no occurrences in ticket_builder.py/config_merge.py/planner.py). So no alias can inject a literal "Fix versions" into a plan payload. The quoted name appears to be Jira's field display name ("Fix versions"), not the sent value [ASSUMED]. Disposition: config/environment, plus a code gap already fixed. No new code.

INV-01 (07-21 live `plan`) cannot be pinned to one branch from the report alone. A dry-run with the **same resolved-config hash** passed 70 s earlier. The live run failed **10.4 s** after `started_at` with nothing recorded. Calcs has `recurring_epics: []`, so there are no epic writes. Every live-only exit before the first recorded write therefore fits; they are listed in §INV-01. The strongest explanation is circumstantial. The identical 25 tickets for the same PI and versions had already been created on 2026-07-16 (`20260716T172219Z`, success, 25 created). A re-run hits the "does NOT check for duplicates … Create these 25 tickets?" prompt, which defaults to **No**, so a decline or Ctrl-C produces exactly this signature. To meet D-06, the planner needs one `checkpoint:human-verify`: (a) the user's recollection or terminal scrollback, and/or (b) a read-only Jira check that no CA issues/versions were created 2026-07-21 12:19 UTC, plus an offline harness run that reproduces each candidate signature. The investigation also surfaced a real defect, D-NEW-1. `JiraClient` does not wrap `requests` exceptions. Outside `_preflight_validate`, a connection/TLS error escapes as a raw traceback. In `_bulk_create_with_resume` it escapes the `except JiraApiError`, so a timed-out bulk create (which may have succeeded server-side) records **nothing**.

**Primary recommendation:** Build the findings doc from the draft table below. Implement INV-04 as an optional `error: dict[str, str] | None = None` on `RunReport` without bumping `schema_version`, plus a tolerant `from_envelope`. Set `ended_at` + `error` in the three exception handlers. Close INV-01 with a human-verify checkpoint backed by the offline harness at `/tmp/jm-triage/harness.py`. File or fold D-NEW-1.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Run-report schema + tolerant load | `run_report.py` (stdlib model/IO) | — | Single source of truth for envelope; `find_resumable` + `from_envelope` live here |
| Record error on `plan` crash | `planner.run_plan` (orchestrator) | `run_report` helper | `run_plan` owns `report` + `_persist`; handler at planner.py:790 |
| Record error on `import` crash | `importer.run_import` (inner) + `cli.import_command` (outer) | `run_report` helper | cli owns the report lifecycle for import; importer owns the per-row persist |
| User-facing error display | `cli.py` | — | Stays unchanged; INV-04 only adds persistence |
| Triage findings | `.planning/phases/01-production-triage/` doc | GitHub issues / REQUIREMENTS.md | D-10/D-11 |

## Evidence Inventory (read-only, verified this session)

Real CLI runs are reports whose `command` doesn't contain `pytest`. I listed all of them with a python one-liner over `~/dev/work_projects/jiramator/.jiramator/runs/*.json`. `mtime` comes from `stat` [VERIFIED: stat + json read this session]. Times are UTC; mtime was converted from EDT (−04:00).

| Report | Command (after `jiramator`) | started_at | last persist (mtime) | Δ | status / counts | hash[:8] |
|---|---|---|---|---|---|---|
| 20260713T135104Z-dm-test | `plan --dry-run --team-config configs/teams/dm-test.yaml --pi-number 26.4 --versions 26.4.1,26.4.2 --yes` | 13:51:04.886 | 13:51:04.892 | **6 ms** | failed 0/0/0 | b976c5a5 |
| ↳ next: 20260713T135110Z | same **+ `--no-sprints-exist`** | 13:51:10.510 | 13:51:10.530 | — | success | b976c5a5 (same) |
| 20260713T140620Z-dm-test | `plan --team-config …dm-test.yaml` (live) | 14:06:31 | 14:06:46 | 15 s | failed 0/0/**18** | a9f005ae |
| 20260713T141438Z-dm-test (INV-02) | `plan --team-config …dm-test.yaml` (live) | 14:14:52 | 14:15:12 | 20 s | failed **18**/0/**7** | 17291500 |
| 20260713T154340Z-dm-test | `plan --resume --team-config … --force` | 15:43:56 | 15:44:18 | 22 s | failed 18(carried)/0/0, 18 issues | 17291500 |
| ↳ 20260713T155804Z | `plan --resume … --force --no-sprints-exist` | 15:58:21 | 15:58:39 | — | **success 25** | 17291500 |
| 20260716T162224Z-calcs | `plan --dry-run --pi-number 26.4 --versions 26.4.1` | 16:22:24.555 | 16:22:24.565 | **10 ms** | failed 0/0/0 | 65e09fab |
| ↳ next: 20260716T162236Z | same **+ `--no-sprints-exist`** | 16:22:36.530 | 16:22:36.548 | — | success | 65e09fab (same) |
| 20260716T171150Z-calcs | `plan` (live) | 17:12:02 | 17:12:23 | 21 s | failed 0/0/**18** (ADF customfield_10042) | c3270a77 |
| ↳ 20260716T172219Z | `plan` (live) | 17:22:29 | 17:22:54 | — | **success 25** (versions 26.3.1, 26.3.2, 26.4.0) | aa0994e1 |
| 20260717T171429Z-calcs | `plan --dry-run --pi-number 26.4 --versions 26.4.1 --no-sprints-exist` | 17:14:29.574 | 17:14:29.582 | **8 ms** | failed 0/0/0 | 6ec35ca4 |
| ↳ next: 20260717T171446Z | `--versions 26.4.1,26.4.2 --no-sprints-exist` (**versions changed**) | 17:14:46.042 | 17:14:46.676 | 0.63 s | success | 22a86abb |
| 20260717T174859Z-calcs | `plan --dry-run --pi-number 26.4 --versions 26.4.1,26.4.2 --no-sprints-exist` | 17:48:59.327 | 17:49:00.421 | **1.09 s** | failed 0/0/0 | 22a86abb |
| ↳ next: 20260717T175148Z | **identical args, identical hash** | 17:51:48.176 | 17:51:49.172 | 1.0 s | success | 22a86abb |
| 20260721T121731Z-calcs | `plan --dry-run` (interactive) | 12:17:52.871 | 12:18:00.710 | 7.8 s | success | fdedcb7e |
| **20260721T121841Z-calcs** (INV-01) | `plan` (interactive, live) | 12:19:01.541 | 12:19:11.940 | **10.4 s** | failed 0/0/0 | fdedcb7e (same as dry-run) |

Notes:
- Filename stamp vs `started_at`: cli.py computes `default_report_path()` (cli.py:430-431) **before** `run_plan` prompts for PI/versions, and `started_at` is set after the prompts (planner.py report init). The 20 s gap on 07-21 (12:18:41 → 12:19:01) is the interactive PI/version prompt time. Non-interactive runs show ≈0 gap [VERIFIED: cli.py:430-431, planner.py:745-756 read].
- Code version: the work clone's installed dist is `jiramator-1.2.8.dist-info`, an editable install of the work clone, and its `pyproject.toml` has `version = "1.2.8"`. Its first reflog entry is 2026-07-23, so the 07-21 run used v1.2.8-era code. `git diff v1.2.8 HEAD -- jiramator/` is only ruff modernization (`timezone.utc`→`UTC`, `zip(strict=False)`, removed unused import), so **HEAD planner behaviour == v1.2.8** [VERIFIED: diff read this session].
- Work-clone `develop` = `8c96e59` (the v1.2.8 feature merge), which exists in this repo. The work clone is where these features were developed and tested live, so working-tree states between commits are plausible [VERIFIED: packed-refs read].

## Findings Table — DRAFT for D-11 deliverable

| # | Report | Classification | Root cause | Disposition | Evidence | Conf. |
|---|---|---|---|---|---|---|
| 1 | 20260713T135104Z-dm-test | **Input error (expected behaviour), unrecorded** | Non-TTY invocation (agent-driven: relative `.venv/bin/jiramator`, `--yes`), `board_id` set, no `--sprints-exist` flag and no `sprints_exist:` in config → `_resolve_sprints_exist_mode` raises `ConfigValidationError` (planner.py:234). `run_plan` persists, cli prints a clean message (`_fail`, cli.py:462-463) | Covered by INV-04 (report will now carry the error). No code fix | Δ = 6 ms (before any I/O); next run 6 s later adds only `--no-sprints-exist`, **same hash**, succeeds. Behaviour exists since `2932355` (2026-04-30) | HIGH |
| 2 | 20260716T162224Z-calcs | Same as #1 | Same as #1. calcs.yaml has `board_id: 362` and no `sprints_exist` key | Same as #1 | Δ = 10 ms; next run 12 s later adds only `--no-sprints-exist`, same hash, succeeds | HIGH |
| 3 | 20260717T171429Z-calcs | **HYG-04** (builder `ValueError` → raw traceback) | `--versions 26.4.1` = 1 release; calcs.yaml `release_sprint_schedule` has keys `2` and `3` only → `build_per_release_tickets` raises `ValueError("Team 'Calcs' has no release_sprint_schedule entry for 1 release(s) …")` (ticket_builder.py:286-295). cli.py:445-463 catches only `ConfigDriftError`/`ConfigValidationError` → traceback | Attribute to HYG-04 (Phase 4). No new defect | Δ = 8 ms; schedule introduced by `c5d1fc6` (2026-07-16 14:46 EDT); calcs.yaml mtime 2026-07-16 14:43 EDT. The 07-16 single-version dry-runs at 16:22/17:19 UTC (12:22/13:19 EDT) predate the change and succeeded; the next run changes versions to 2 and succeeds | HIGH |
| 4 | 20260717T174859Z-calcs | **Already fixed by `24dd6e0`** (dev-in-progress artifact) | Live createmeta validation (WIP `70644ec`, 13:03 EDT) flagged not-yet-created release versions as invalid `fixVersions` → `_preflight_validate` prints problems, `persist(); sys.exit(1)` (planner.py:463-502). `24dd6e0` (13:59 EDT) adds `_SKIP_ALLOWED_VALUES_FIELD_IDS = frozenset({"fixVersions"})`; its message says "Confirmed against a real plan run: every not-yet-created release version was flagged as invalid, aborting the run." | Already fixed; cite commit. No action | Δ = 1.09 s (createmeta round-trip, not a pure-local crash). Identical args **and** hash succeeded at 17:14 UTC (committed WIP read the wrong JSON key `data.get("values")` → empty metadata → nothing flagged) and at 17:51 UTC (working-tree fix before the 17:59 UTC commit). D-05 note: the pair differs in **code**, not flag; the commit message is the second witness | MEDIUM |
| 5 | **20260721T121841Z-calcs** | **Open: pre-write abort in live-only path** (see §INV-01) | Narrowed to the live-only exits after preview in §INV-01; leading hypothesis is a user decline/Ctrl-C at the duplicate-warning confirm | Needs checkpoint (D-06). If the cause is a `requests` exception → D-NEW-1 | Same hash as passing dry-run 70 s earlier; Δ = 10.4 s; 25 identical tickets already created 07-16 | MEDIUM |
| 6* | 20260713T141438Z-dm-test | **Config/environment + code gap already fixed (INV-02)** | See §INV-02 | Already fixed by `963b5f2` (v1.1.1) | See §INV-02 | HIGH |
| 7* | 20260713T140620Z-dm-test | Config error | `customfield_10273` (API Impact) not on DM screens → 400 for all 18 | None (config fixed; documented in dm-test copy header). Phase 2 PRE-* class of problem | Error text in report; dm-test copy header NOTE | HIGH |
| 8* | 20260716T171150Z-calcs | Code defect, already fixed | `customfield_10042` sent as plain string → "not valid ADF" | Fixed by `8f9ebf0` (v1.2.4, 13:20 EDT); success 10 min later (`172219Z`, 13:22 EDT) | Error text; commit time | HIGH |
| 9* | 20260713T154340Z-dm-test | Unrecorded pre-write exit on resume (non-zero carried counts) | Resume without `--no-sprints-exist`, Δ 22 s, no new rows. Same unrecorded-exit class as #5 | Covered by INV-04; next resume with `--no-sprints-exist` succeeded. Optional row | Report + mtime | LOW |

\* Not zero-count. Including them costs one row each and makes the table cover "every failed report". Rows 1–5 are the INV-03 scope.

## INV-01: 2026-07-21 live `plan` — exit-point analysis

Inputs: calcs.yaml (`board_id: 362`, no `sprints_exist`, `recurring_epics: []`, `existing_epics: {bau: CA-5078, misc: CA-5079}`, per_sprint `fixVersions: ["{pi_label}"]`), versions `26.3.1, 26.3.2, 26.4.0` (schedule key `3` exists) [VERIFIED: calcs.yaml read this session].

Each path below ends with `run_plan`'s `except BaseException: _persist(); raise` (planner.py:790-795). Line numbers are on HEAD [VERIFIED: planner.py read this session].

| # | Step (HEAD line) | Exit | Signature 0-count & `ended_at: null`? | Also in dry-run? | Fits 07-21? |
|---|---|---|---|---|---|
| a | sprints prompt `_resolve_sprints_exist_mode` (planner.py:208-243, prompt :201) | Ctrl-C / EOF | yes | yes | ✗ dry-run passed this step with the same config (TTY) |
| b | `build_all` preview (:833) | `ValueError` → traceback | yes | yes | ✗ same hash passed in dry-run |
| c | `client = JiraClient(org_config)` (:873-877) | `ValueError` → "Credential error", `sys.exit(1)` | yes | dry-run *degrades* (:852-859) | ✓ only if creds were absent in that shell (dry-run would have printed "Skipping field validation (no Jira credentials…)") |
| d | `_preflight_validate` live (:879, body :463-502) | problems → `persist(); sys.exit(1)` | yes | yes (same function) | ✓ only if dry-run validation was *skipped* (no creds / Jira or connection error → warning, :483-490) |
| e | `_check_and_create_fix_versions` → `client.get_fix_versions` (:297) | `JiraApiError` **or raw `requests` exception** → traceback | yes | no | ✓ |
| f | fix-version confirm (:310-314) | decline → `sys.exit(1)` / Ctrl-C | yes | no | ✓ only if a needed version (`26.3.1`, `26.3.2`, `26.4.0`, `PI26.4`) was missing/renamed. All were used successfully on 07-16 |
| g | `client.create_fix_version` (:317) | `JiraApiError`/requests → traceback | yes | no | ✓ same precondition as f |
| h | **duplicate warning + "Create these 25 tickets?"** (:899-908, `default=False`) | decline (Enter) → "Aborted." `sys.exit(1)` / Ctrl-C | yes | no | ✓ **leading hypothesis**: identical 25 tickets already created 07-16 |
| i | epic loop (:910-964) | — | — | — | n/a: `recurring_epics: []` |
| j | `_resolve_sprint_ids` → `get_board_sprints` (:976-990) | `JiraApiError` caught → continue; **requests exception NOT caught** → traceback | yes | no | ✓ (if user answered "yes, sprints exist") |
| k | `_bulk_create_with_resume` → `create_issues_bulk` (:1067-1084) | `JiraApiError` → records `failed` rows (non-zero) ✗; **requests exception (e.g. read timeout) NOT caught** → nothing recorded | yes, **even if Jira created the tickets** | no | ✓ dangerous variant: must be ruled out with a Jira read |

How to distinguish the remaining candidates (c, d, e, f/g, h, j, k):
- **Timing (weak):** 10.4 s from `started_at` covers the sprints prompt + preview + createmeta validation (the dry-run spent 7.8 s on the same) + ~2.6 s extra. That fits c/d (fast) poorly unless the human paused at the sprints prompt. It fits h (fix versions all exist → "✓ All fix versions already exist" → Enter at the default-No prompt) well.
- **Jira state (strong, read-only):** CA issues with `created` in 2026-07-21 12:19–12:30 UTC, and CA versions list. If any of the 25 summaries were created that day, it's **k** (D-NEW-1, a safety defect). If none were created, a–g/j/h remain, and k is ruled out.
- **User recollection / terminal scrollback (strong):** the printed last line is unique per branch: "Credential error:", "✗ Found N field problem(s)", a traceback (`requests.exceptions…` / `JiraApiError`), "Cannot proceed without fix versions", or "Aborted.".
- **Offline mechanism reproduction (permitted, no writes):** `/tmp/jm-triage/harness.py` (created in this session; configs copied to `/tmp/jm-triage/configs/`). It drives `jiramator plan` via click's `CliRunner` with `jiramator.planner.JiraClient` replaced by an in-memory fake, `Confirm.ask` scripted and `sys.stdin.isatty` patched. Scenarios: 1-version dry-run (#3), non-TTY without the sprints flag (#1/#2), live decline at final confirm (h), Ctrl-C at confirm, no creds (c), `get_fix_versions` API error (e), decline fix-version creation (f), happy path control. **Not executed this session:** the sandbox denied installing deps / using an interpreter with `click`. Run it after `pip install -e ".[dev]"`. Expected: every one of these leaves `status=failed, counts 0, issues [], ended_at null`, i.e. the report alone cannot distinguish them, which is the motivation for INV-04.

**Recommended disposition path for the planner:**
1. Task: run the harness (or turn it into a pytest), paste the signature table into the findings doc.
2. `checkpoint:human-verify`: ask the user what the terminal showed at 08:19 EDT 2026-07-21, and/or have the user run a read-only JQL (`project = CA AND created >= "2026-07-21 08:15" AND created <= "2026-07-21 08:30"`, user's TZ) and check the CA versions list. Whether the agent may run a read-only JQL with credentials itself is a D-02 judgement call: it is a read, but not a `--dry-run`. Default to user-run.
3. Outcome mapping: h/f (user abort) → "expected behaviour, unrecorded → INV-04". c/d → "environment (creds/connectivity), unrecorded → INV-04". e/j/k → D-NEW-1 confirmed → fix or fold.

### D-NEW-1 (new defect found during research)

`JiraClient` never wraps `requests.exceptions.RequestException`. `grep -n RequestException jiramator/jira_client.py` returns nothing, although `JiraApiError` documents `status_code: None for connection errors` (jira_client.py:36-37) [VERIFIED: jira_client.py:33-50 read]. Consequences:
- **Live `plan`:** connection/TLS/timeout errors in `get_fix_versions`, `create_fix_version`, `get_board_sprints` (outside `_resolve_sprint_ids`' `except JiraApiError`, :983), `create_issue` (epics, `except JiraApiError` :942), and `create_issues_bulk` (`except JiraApiError` :1069) escape as raw tracebacks.
- In bulk create, a **read timeout after Jira accepted the batch** records no rows. `--resume` would then re-create the batch → **duplicates**. This conflicts with the project core value ("safe to re-run").
- Corporate TLS interception (`JIRAMATOR_CA_BUNDLE`, `JIRAMATOR_RELAX_TLS_STRICT`) makes SSL errors a realistic trigger [CITED: AGENTS.md §Corporate TLS interception].

Recommended disposition: **D-09 → new requirement in Phase 4** (e.g. "HYG-05: Jira connection/TLS/timeout errors surface as `JiraApiError` with an actionable message, and a bulk-create transport error marks the batch rows as `failed`/`unknown` in the run report, not unrecorded"). It is not trivial: it touches every client method and the retry semantics, so it does not meet the D-08 bar. Escalate to a Phase 1 fix only if the Jira read shows path k actually happened.

## INV-02: `Version name 'Fix versions' is not valid`

**Evidence chain** [VERIFIED: reports, dm-test copy, git show read this session]:
1. `20260713T141438Z-dm-test.json` (live plan, 14:14:52 UTC = 10:14 EDT): 18 per_release **created**, 7 per_sprint **failed**. Every failed row carries `errors: {'fixVersions': "Version name 'Fix versions' is not valid"}`.
2. Surviving config copy `~/dev/work_projects/jiramator/.jiramator/test-configs/dm-test.yaml` (mtime 2026-07-13 11:55 EDT). Its per_sprint template has `fixVersions: ["{pi_label}"]`, and every per_release template has `fixVersions: ["{version}"]`. Header comment, verbatim: *"NOTE: per_sprint_tickets uses fixVersions: ["{pi_label}"] on purpose — a PI-umbrella Jira Version (e.g. "PI26.4") … Unlike release versions, this one isn't typed in via --versions, so planner.py's fix-version step scans every built ticket payload for referenced fixVersions … and offers to auto-create any that don't exist yet"*. That describes the v1.1.1 behaviour being written that morning.
3. The resolved-config hash `17291500…` is identical for the failed run (14:14 UTC), the resume (15:43 UTC) and the successful resume (15:58 UTC). The copy was saved at 15:55 UTC, inside that window, so it is the config the failing run used. The hash covers the org + team model dumps, `compute_resolved_hash` run_report.py:270-300.
4. Code at 10:14 EDT was v1.1.0. `_collect_referenced_fix_versions` was introduced by `963b5f2` "release: v1.1.1 — fix versions from templates…" on 2026-07-13 12:15 EDT. The CHANGELOG entry: *"a fix version referenced solely inside a ticket template's fields … would cause a confusing 400 error at ticket-creation time instead of the normal create-with-confirmation flow."* That is this failure.
5. Code-path falsification for D-07(a): the `plan` builder never reads `bulk_create.field_aliases`/`value_aliases`. `grep -n "field_aliases\|value_aliases" jiramator/ticket_builder.py jiramator/config_merge.py jiramator/planner.py` returns nothing. `fixVersions` values come only from template `fields` via `resolve_value` → `_wrap_field` `name_object_array` (ticket_builder.py:33-41, 89-121). The acme.yaml aliases `fix_version: fixVersions` / `Fix Version: fixVersions` / `Fix Versions: fixVersions` map header **names** to field IDs for `import`/`update` (field_resolver.py:39, 91) and cannot become a fixVersions **value** in `plan` [VERIFIED: grep + files read].
6. Regression coverage already exists: tests/test_planner.py:252-284 (`_collect_referenced_fix_versions`) and :622-626 (per_sprint `["{pi_label}"]` umbrella version).

**Conclusion:** config/environment. The `PI26.4` version didn't exist in DM, combined with a code gap (umbrella versions not pre-created) that was **fixed by `963b5f2` (v1.1.1)**. The literal "Fix versions" in the message is Jira's field display name; the sent value was `PI26.4` [ASSUMED: inferred from (1)+(2)+(3); Jira Cloud's createmeta name for `fixVersions` is "Fix versions", as also used in tests/test_payload_validator.py:166]. Disposition: documented, no new code. The success at 15:58 UTC with the same hash implies `PI26.4` was created in DM manually in between [ASSUMED]. Per CONTEXT D-07, don't reconstruct dm-test, only cite the surviving copy. Copying it is fine; editing or deleting it in the work clone is not.

## INV-04: Run-report error capture

### Current schema and loader (verbatim) [VERIFIED: jiramator/run_report.py read this session]
- run_report.py:40: `SCHEMA_VERSION: int = 1`
- run_report.py:84-116 `RunReport` fields: `schema_version: int = SCHEMA_VERSION`, `command: list[str]`, `started_at: str = ""`, `ended_at: str | None = None`, `team_config_path: str = ""`, `org_config_path: str = ""`, `team_name: str = ""`, `pi_label: str | None = None`, `versions: list[str]`, `resolved_config_hash: str = ""`, `status: RunStatus = "failed"`, `counts: dict[str, int]` (default `{"created": 0, "skipped": 0, "failed": 0}`), `issues: list[IssueResult]`.
- run_report.py:118-124 `to_envelope`: `{"schema_version": self.schema_version, "run": asdict(self)}`.
- run_report.py:127-142 `from_envelope`: rejects `obj.get("schema_version") != SCHEMA_VERSION` with `ValueError`, then `run["issues"] = [IssueResult(**i) ...]` and **`return cls(**run)`**. An unknown key raises `TypeError`.
- run_report.py:212-262 `find_resumable`: reads raw JSON, uses only `run["status"]`, `run["team_config_path"]`, `run["started_at"]`, and skips on `(OSError, json.JSONDecodeError, KeyError, ValueError, TypeError)`. **Unaffected by new fields.**
- cli.py:111-126 `_load_report_file`: `RunReport.from_envelope`, mapping `(ValueError, KeyError, TypeError)` → `_fail("Resume report incompatible: …")`.
- tests/test_run_report.py:74-77 `test_4_schema_version_two_rejected` asserts schema 2 is rejected ("reserved for a future migration plan").

### Recommended shape (agent's discretion → decision)
- **Do not bump `schema_version`.** Bumping to 2 makes every pre-INV-04 jiramator reject new reports, current code rejects any value ≠ 1, and test_4 encodes that contract. An additive optional field is not a migration.
- Add `error: dict[str, str] | None = None` to `RunReport`, as the **last** field so positional construction stays safe. Shape: `{"type": "<ExceptionClassName>", "message": "<str(exc)>"}`. A plain dict needs no `from_envelope` conversion (unlike a nested dataclass) and `asdict` serialises it unchanged. JSON: `"error": null` or `"error": {"type": "KeyboardInterrupt", "message": ""}`.
- **Make `from_envelope` tolerant of unknown keys:** filter `run` to `{f.name for f in dataclasses.fields(cls)}`, and likewise for `IssueResult`. This doesn't help already-shipped v1.2.8 read new reports: v1.2.8's `cls(**run)` hits `TypeError` and shows "Resume report incompatible". It does make every **future** additive field forward-compatible. Document the one-way downgrade caveat in CHANGELOG ("reports written by ≥1.2.9 can't be resumed by ≤1.2.8"). Alternative if strict downgrade-safety matters: omit the `error` key when `None` (custom `to_envelope`). Then success reports stay byte-compatible with v1.2.8, and only crash reports carry the key. Recommended: **omit-when-None**. It's cheap and keeps clean reports readable by old versions. Flag for user confirmation (A3).
- `message`: `str(exc)`, truncated to a sane cap (e.g. 2,000 chars with a `…` marker). JiraApiError bulk messages are already huge (the 07-13 rows carry ~3 KB each). Never store a traceback (security §).
- `SystemExit`: the handler sees `SystemExit(1)` for every deliberate abort (`sys.exit(1)` at planner.py:143,148,165,176,314,502,877,908,952,1084). `{"type": "SystemExit", "message": "1"}` is useless for triage. Recommended: a small `_abort(report, reason)` pattern, or set `report.error = {"type": "Aborted", "message": "<the reason printed>"}` immediately before each in-pipeline `sys.exit(1)` in `_run_plan_inner` / helpers, and have `run_plan`'s handler fill `error` **only if still `None`**. This is what would have made INV-01 self-explanatory: "Aborted: user declined ticket creation" vs "Credential error: …". Keep the type string for these as `"SystemExit"` or a stable label. Planner picks; the test asserts it.
- `ended_at`: set in the handler with the same format the code path already uses. Planner uses `datetime.now(UTC).isoformat()`; cli import uses `.isoformat().replace("+00:00", "Z")`, so keep each path's existing format.
- `status`: leave pessimistic `failed`. Optional nicety, not required by INV-04: if `counts["created"] > 0`, set `partial`. **Don't**: `find_resumable` treats both identically, and changing it widens scope.

### Exact insertion points
| Command | Location (HEAD) | Today | Change |
|---|---|---|---|
| `plan` | planner.py:790-795 `except BaseException: _persist(); raise` | persists state only | `except BaseException as exc: report.ended_at = report.ended_at or now; if report.error is None: report.error = _error_info(exc); _persist(); raise` |
| `plan` aborts | planner.py:310-314, 463-502, 873-877, 904-908, 940-952, 1067-1084 | print + `sys.exit(1)` | set `report.error` reason first. `_check_and_create_fix_versions`/`_preflight_validate`/`_bulk_create_with_resume` need `report` passed in, or return-a-reason. `_preflight_validate` already takes `persist` |
| `import` inner | importer.py:497-500 `except BaseException: _persist(); raise` | persists state only | same as plan handler (`report` may be `None` → guard) |
| `import` outer | cli.py:662-669 `except (ValueError, JiraApiError)` | sets `ended_at`, writes, `_fail` | add `report.error = …`. **Gap:** `JiraClient(...)`/`client.get_fields()` (cli.py:651-652) raising `requests` exceptions or `KeyboardInterrupt` → **no report is written at all** (the initial `_persist` lives inside `run_import`). Broaden to `except BaseException as exc` with the same body, re-raising non-`SystemExit` after the write. Keep `_fail` for the existing two types |
| `update` | cli.py:829 | `update` has no resume; report written after the run | Out of INV-04's literal scope ("plan or import"). Optional: same helper for consistency |

Put the helper in run_report.py (stdlib-only module, fits there):
```python
# Source: proposed; mirrors existing run_report.py conventions
_ERROR_MESSAGE_CAP = 2000

def error_info(exc: BaseException) -> dict[str, str]:
    """Return a JSON-safe ``{"type", "message"}`` record for *exc*."""
    message = str(exc)
    if len(message) > _ERROR_MESSAGE_CAP:
        message = message[:_ERROR_MESSAGE_CAP] + "…"
    return {"type": type(exc).__name__, "message": message}
```

### Tests to extend (all exist, read this session)
- `tests/test_run_report.py` `TestEnvelopeRoundTrip` (:31-88): add
  - round-trip with `error` set;
  - **legacy envelope without `error` loads** (`error is None`). Use a literal dict copied from a real 07-21 report shape: `{"schema_version": 1, "run": {… no "error" …}}`;
  - unknown extra key in `run` is ignored;
  - omit-when-None serialisation (if chosen).
- `TestFindResumable` (:164-295): a report with an `error` object is still discovered.
- `tests/test_planner_report.py` `TestPersistOnError` (:536-565, `test_p10_keyboardinterrupt_leaves_valid_report`): extend to assert `ended_at` is not None and `error == {"type": "KeyboardInterrupt", …}`. Add:
  - a builder `ValueError` case: team config with a schedule missing the release count, no mocks of the builder;
  - a user-decline (`Confirm.ask` → False) case asserting the abort reason;
  - a `TestResume` case resuming from a legacy report without `error`.
- `tests/test_importer_report.py` `TestPersistOnInterrupt.test_i7_keyboardinterrupt_persists` (:347-390): assert `ended_at` + `error`. `TestBackwardCompat` (:392) stays green.
- `tests/test_import_cli.py`: CLI-level import where `get_fields` raises `requests.exceptions.ConnectionError` → a report file exists with `error.type == "ConnectionError"`. Patch `jiramator.cli.JiraClient`.
- Use `tmp_path` for every `report_path`. Don't let tests write to `.jiramator/runs/`; that's TEST-01's whole complaint.

## Standard Stack

No new dependencies. Everything uses stdlib (`dataclasses`, `json`, `datetime`) plus existing deps (click, rich, requests, pydantic, pytest) [VERIFIED: pyproject.toml/AGENTS.md]. **Package Legitimacy Audit: not applicable — this phase installs no external packages.**

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---|---|---|---|
| Atomic report write on crash | new file IO in handlers | `write_report_atomic` (run_report.py) via the existing `_persist` closures | Already Ctrl-C-safe (tempfile + `os.replace`, unlinks tmp on BaseException) |
| Schema migration machinery | `schema_version` 2 + migrator | additive optional field + tolerant reader | D-13; test_4 contract |
| Reproducing live failures | live `plan` runs | fake `JiraClient` + `CliRunner` harness, `plan --dry-run` against copied configs | D-02/D-03 |
| Failure timing | guessing | report mtime − `started_at` | mtime = last `_persist()` = error handler |

## Common Pitfalls

1. **Running anything with cwd inside the work clone.** `RUNS_DIR = Path(".jiramator/runs")` is **cwd-relative** (run_report.py:41), so a dry-run from there writes a report into production. Copy configs to `/tmp/jm-triage/` and run from there with `--report /tmp/...` (D-03).
2. **Touching mtimes.** `cp` without `-p`, or any write in the runs dir, destroys the timing evidence. Copy with `cp -p` if copying reports; prefer reading in place.
3. **`from_envelope` strictness.** Adding a field without the tolerant filter still works for new→new. Forgetting omit-when-None makes every new report unreadable by v1.2.8 `--resume`.
4. **`SystemExit` swallowing the real reason.** Recording only `type(exc)` gives "SystemExit: 1" for 10 different aborts. Set the reason before `sys.exit`.
5. **Double-setting `ended_at`/`error`.** Inner paths that already set `ended_at` (dry-run success :868, final :1009) must not be overwritten. Use `if report.error is None`.
6. **Patch location.** Patch `jiramator.planner.JiraClient`, `jiramator.planner.Confirm.ask`, `jiramator.cli.JiraClient` (AGENTS.md).
7. **Credentials in error messages.** `requests` exception strings include URLs, not headers. Still, never serialise tracebacks, locals or env.
8. **Integration counts.** Don't touch `tests/fixtures/teams/calcs.yaml` for the builder-ValueError test. Build a TeamConfig in-test or use a tmp YAML.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|---|---|---|---|---|
| Python | tests | ✓ | 3.13.15 (worktree `.venv`) | — |
| ruff | lint | ✓ | 0.16.9 | — |
| pytest/click/rich in `.venv` | tests, harness | ✗ (deps not installed in worktree venv; install was sandbox-denied) | — | `pip install -e ".[dev]"` as first task |
| `JIRA_EMAIL`/`JIRA_TOKEN` | optional D-02 dry-run with live reads | ✗ unset in this shell | — | Offline harness. User-run dry-run/JQL at checkpoint |
| Work-clone evidence | triage | ✓ read-only | — | — |

## Verification Approach (nyquist_validation is false; brief)

- Quick: `python -m pytest tests/test_run_report.py tests/test_planner_report.py tests/test_importer_report.py tests/test_import_cli.py -q`
- Full: `python -m pytest -q` and `ruff check .`
- Findings doc: one row per failed report (rows 1–5 mandatory, 6–9 recommended). Each row cites the report filename, Δ timing, adjacent run, and commit SHA / file:line. Verify by re-running the listing one-liner (in RESEARCH §Evidence) and checking every zero-count `failed` real-CLI report appears exactly once.
- Harness: `cd /tmp/jm-triage && python harness.py` → paste the output into the findings doc as the INV-01 mechanism evidence. After INV-04 lands, re-run it and confirm each scenario now records `ended_at` + `error`. That shows the fix on real configs.
- Post-merge: check the D-09 traceability edits (REQUIREMENTS.md + ROADMAP) for D-NEW-1, and the GitHub issue link if D-10.

## Security Domain

| ASVS | Applies | Control |
|---|---|---|
| V5 Input validation | yes (loading JSON reports) | Tolerant `from_envelope` must still validate `schema_version` and ignore, not `eval`/execute, unknown keys. `find_resumable` already skips malformed files |
| V7 Error handling & logging | **yes** | Store exception **type + truncated message only**. No tracebacks, locals or env. Cap length |
| V8 Data protection | yes | Reports live in `.jiramator/runs/` (gitignored: `.gitignore:49` `.jiramator/`). Messages may contain Jira URLs, issue summaries or account IDs, the same class of data already in `issues[].error` |
| V2/V3/V4/V6 | no | no auth/session/crypto changes |

| Threat | STRIDE | Mitigation |
|---|---|---|
| Credential leakage into report via exception text | Information disclosure | Only `str(exc)`; JiraClient never puts tokens in messages [ASSUMED: not audited for every `_handle_error` path]. Do not record `repr(exc.request)`/headers |
| Forged report triggering resume of wrong team | Tampering | Unchanged: `find_resumable` path-matches + hash drift check |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|---|---|---|
| A1 | Jira's "Version name 'Fix versions' is not valid" quotes the field display name, not the sent value (`PI26.4`) | INV-02 | Low: the conclusion (missing umbrella version, fixed in v1.1.1) stands on the hash/copy evidence. If Jira quotes the value, the template literally held "Fix versions", which the hash-matched copy contradicts |
| A2 | `PI26.4` was created manually in DM between 14:15 and 15:58 UTC on 07-13 | INV-02 | None for disposition |
| A3 | Omit-`error`-when-None is preferred over always emitting `"error": null` | INV-04 | Medium: affects downgrade-resume compatibility; confirm with user |
| A4 | The 174859 abort came from uncommitted working-tree code between `70644ec` and `24dd6e0` | Findings #4 | Low: the disposition "already fixed" is the same either way |
| A5 | 135104/162224 were non-TTY (agent-driven) invocations | Findings #1–2 | Low: a 6–10 ms exit is impossible with a human-answered prompt |
| A6 | Exception messages from JiraClient never contain credentials | Security | Medium: audit `_handle_error` before shipping |
| A7 | The harness scenarios produce the predicted signatures (not executed) | INV-01 | Low: code reading is direct; the run is the confirmation |

## Open Questions

1. **What did the terminal show at 08:19 EDT on 2026-07-21?** (INV-01, blocking D-06.) Recommendation: a human-verify checkpoint, plus a user-run read-only JQL for CA issues created then. **(RESOLVED)** Plan 01-03 collects the evidence at its Task 2 `checkpoint:decision` (D-03 sandbox) and Task 3 `checkpoint:human-verify` (recollection, JQL, CA versions list). Plan 01-04 narrows the exits against that evidence and stops at a `checkpoint:decision` before it closes INV-01.
2. **D-NEW-1 disposition:** new Phase 4 requirement (recommended) vs GitHub issue vs Phase 1 fix (only if path k is confirmed). **(RESOLVED)** Plan 01-02 Task 2 folds it into Phase 4 as HYG-05 (D-09). Plan 01-04 marks HYG-05 as production-confirmed if INV-01 turns out to be exit k.
3. **Error shape for deliberate aborts:** `type: "SystemExit"` + reason vs `type: "Aborted"`. The planner picks one and the tests lock it. **(RESOLVED)** Plan 01-01 uses `ABORTED_ERROR_TYPE = "Aborted"` + the printed reason through `abort_info()`, and its tests lock that shape.

## Sources

### Primary (HIGH)
- `jiramator/run_report.py`, `planner.py`, `cli.py`, `importer.py`, `ticket_builder.py:265-300`, `jira_client.py:33-50, 360-440` on HEAD `6676bdc`
- Work clone (read-only): `.jiramator/runs/*.json` (content + `stat` mtimes), `configs/teams/calcs.yaml`, `configs/org/acme.yaml`, `.jiramator/test-configs/dm-test.yaml`, `.git/packed-refs`, `.git/logs/HEAD`, `.venv/.../jiramator-1.2.8.dist-info`
- `git show 963b5f2` (v1.1.1), `24dd6e0`, `70644ec:jiramator/{planner,jira_client}.py`, `git log -S` for `_collect_referenced_fix_versions`, `_resolve_sprints_exist_mode`, `release_sprint_schedule`, `_preflight_validate`, `except BaseException`; `git diff v1.2.8 HEAD -- jiramator/`
- tests: `test_run_report.py`, `test_planner_report.py`, `test_importer_report.py`, `test_planner.py:252-284,622-626`

### Secondary / Tertiary
- None. No web sources were needed; this is a codebase-forensics phase.

## Metadata
- Standard stack: HIGH (no new deps)
- Architecture/INV-04 design: HIGH (loader/handlers read directly)
- Classification #1–3, #6–8: HIGH. #4: MEDIUM. #5 (INV-01): MEDIUM pending checkpoint
- Research date: 2026-10-02. Valid until the code in `run_report.py`/`planner.py` changes (stable)
- Artifact: `/tmp/jm-triage/{harness.py,configs/}`, temp copies of real configs. Delete after the phase; they contain internal Jira URLs and field IDs, but no credentials.
