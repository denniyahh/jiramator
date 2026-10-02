# Phase 1: Production Triage - Context

**Gathered:** 2026-10-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Every unexplained production failure in the work clone's run reports gets a known root cause,
and each is fixed in this phase, folded into a later v1.2.9 phase, or filed. Plus one small
diagnostic fix (INV-04) so future failures record their cause in the run report.

In scope: INV-01 (2026-07-21 live `plan` failure), INV-02 (`Version name 'Fix versions' is not
valid`), INV-03 (classify every zero-count `failed` report), INV-04 (reports record the error).
Not in scope: import preflight (Phase 2), user resolution (Phase 3), the HYG/TEST fixes
(Phase 4) — triage may *attribute* failures to those, but does not implement them.

</domain>

<decisions>
## Implementation Decisions

### Reproduction method
- **D-01:** Reproduce with the **current code** (`develop`), against the work clone's real configs (`~/dev/work_projects/jiramator/configs/org/acme.yaml`, `configs/teams/calcs.yaml`), using `plan --dry-run` only.
- **D-02:** `--dry-run` with live credentials is allowed — it reads Jira (createmeta, field metadata, board sprints) but must never write. **No live `plan`/`import`/`update` runs against Jira in this phase.**
- **D-03:** The work clone is **read-only**: copy configs/reports out to a temp dir; never edit, commit, or run from inside `~/dev/work_projects/jiramator`. — **Reversibility:** one-way — it is the production clone the user runs at work; a stray edit or run report there affects real usage.
- **D-04:** Check out an older release tag (e.g. `v1.2.2`…`v1.2.8`, in a throwaway worktree) **only** when current code cannot reproduce a failure and the history suggests it was fixed in between.

### Bar for "done"
- **D-05:** A failure is resolved as "already fixed by commit X" when the git history **and** a failed→succeeded run pair (same command, seconds/minutes apart, with a changed flag/input) support it. A written rationale citing both is sufficient — no reproduction at the old SHA required.
- **D-06:** **INV-01 (2026-07-21 live `plan`) must be reproduced or concretely explained** — no "probably fixed". It has no follow-up success run and was a live run, so it is the only genuinely open case.
- **D-07:** INV-02: `configs/teams/dm-test.yaml` was deleted, so the original input is unrecoverable. Resolve by (a) checking whether current code can turn any config/alias input into a literal `"Fix versions"` fixVersions value (code path through `fix_version`/`Fix Versions` aliases in `configs/org/acme.yaml`), and (b) if not reproducible, documenting it as config-caused with the evidence. Do not reconstruct dm-test.

### Disposition of findings
- **D-08:** Trivial defects (small, isolated, test-coverable) are **fixed inside Phase 1**, each with a regression test.
- **D-09:** Larger defects that fit v1.2.9 become **new requirements in Phases 2–4** (update REQUIREMENTS.md traceability + ROADMAP success criteria).
- **D-10:** Defects outside the hardening milestone are filed as **GitHub issues on `denniyahh/jiramator`** (personal repo; not Jira — this is the user's personal project).
- **D-11:** Triage output is a written findings table (one row per failed report: report file, command, classification, root cause, disposition, evidence) — the phase's deliverable for INV-03.

### Run-report error capture (new requirement INV-04)
- **D-12:** Added to this milestone as **INV-04, in Phase 1**: when a command that writes a run report exits on an exception, the report records `ended_at` and the error (exception type + message) before re-raising. Root reason triage is hard today.
- **D-13:** Must stay **backward compatible**: existing reports without the new field(s) must still load and resume (`find_resumable`, `--resume`). New field(s) optional with a default. — **Reversibility:** costly — run-report JSON is read by `--resume` across versions; a breaking schema change strands users' in-flight resumes.

### the agent's Discretion
- Exact field name/shape for the recorded error (e.g. `error: {type, message}` vs flat string) and whether `schema_version` bumps — pick what keeps D-13 true.
- Order of investigating the reports; temp-dir layout for reproduction.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope
- `.planning/ROADMAP.md` §Phase 1 — goal and success criteria
- `.planning/REQUIREMENTS.md` — INV-01..04, and Phases 2–4 requirements that findings may be attributed to (esp. HYG-04 plan traceback)

### Evidence (read-only, outside this repo)
- `~/dev/work_projects/jiramator/.jiramator/runs/` — production run reports. Real CLI runs are those whose `command` does not contain `pytest` (147 of 184 are pytest pollution — see TEST-01). Zero-count `failed` targets: `20260713T135104Z-dm-test.json`, `20260716T162224Z-calcs.json`, `20260717T171429Z-calcs.json`, `20260717T174859Z-calcs.json`, `20260721T121841Z-calcs.json`. INV-02 evidence: `20260713T141438Z-dm-test.json`.
- `~/dev/work_projects/jiramator/configs/org/acme.yaml`, `configs/teams/calcs.yaml` — real (gitignored) configs used by those runs
- `CHANGELOG.md` §1.2.2–1.2.8 and `git log v1.2.2..v1.2.8` — fixes shipped during the failure window (2026-07-13..17)

### Prior milestone
- `.planning/milestones/v1.0-phases/02-template-inheritance-sprint-assignment/2-UAT.md` §Gaps — where the HYG-04 traceback was first found

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `jiramator/run_report.py`: `RunReport` (has `started_at`, `ended_at: str | None`, `status`, `counts`, `issues`), `write_report_atomic()`, `find_resumable()` — INV-04 extends `RunReport`.
- Existing `tests/test_run_report.py` / `tests/test_planner_report.py` cover atomic write, persist-on-error, Ctrl-C — extend these for INV-04.

### Established Patterns
- `planner.run_plan()`: `_persist()` initial write, then `try: _run_plan_inner(...) except BaseException: _persist(); raise` — persists state but **not** the exception or `ended_at`. That is why all 5 target reports show `ended_at: null` with no error. INV-04 belongs here (and the equivalent `import` path in `cli.py` / `importer.py`).
- `RunReport.status` defaults to `"failed"` (pessimistic; v1.0 decision) — a crash before any status flip reads as `failed` with 0 counts, which is exactly the signature being triaged.

### Integration Points
- `jiramator/planner.py` `run_plan()` exception handler; `jiramator/cli.py` import command report wiring (~lines 600–670).
- Builder errors (`ticket_builder.build_per_release_tickets` `ValueError` on missing `release_sprint_schedule` entry) are a likely cause for some 1-version dry-runs (e.g. `20260717T171429Z`, `--versions 26.4.1`) → attribute to HYG-04 if confirmed.

</code_context>

<specifics>
## Specific Ideas

- Observed pattern to test first: each Jul 13/16/17 failure is followed within seconds/minutes by a success after adding `--no-sprints-exist` or changing `--versions` — likely sprint-mode resolution errors or missing `release_sprint_schedule` entries (input errors surfaced as tracebacks), i.e. HYG-04 territory rather than new defects.
- Jul 21 live `plan`: versions `26.3.1, 26.3.2, 26.4.0` (3 releases; calcs has a `release_sprint_schedule` entry for 3), no `--no-sprints-exist`, interactive. Preceded by a successful `plan --dry-run` at 12:17:31 (failure at 12:18:41) — so the failure is in a live-only path: fix-version creation, sprint resolution against board 362, bulk create, or a prompt/interrupt.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-production-triage*
*Context gathered: 2026-10-02*
