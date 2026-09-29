# Roadmap: Jiramator

## Milestones

- 🚧 **v1.3 Hardening & Reliability** - Phases 1-4 (in progress)

## Overview

v1.2.8 is shipped and in active use. v1.3 hardens the three places where a bulk Jira write can
silently go wrong or be impossible to safely retry. First, user lookups stop guessing. Second,
summary search scales and `plan` becomes safe to re-run without duplicates. Third, `update` gains
the same run-report/resume safety net as `plan`/`import`. The milestone closes with config and
ops hygiene: no silent placeholder field IDs, and a way to prune old run reports. Every phase
serves the Core Value: bulk writes must be correct and safe to re-run.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Safe User Resolution** - `import` never assigns a reporter/assignee from an ambiguous or fuzzy user match
- [ ] **Phase 2: Scalable Lookup & Plan Re-run Safety** - Chunked/paginated summary search, then `plan` detects and skips issues that already exist
- [ ] **Phase 3: Update Run Reports & Resume** - `update` records per-row results and can resume failed rows with a drift check
- [ ] **Phase 4: Config & Ops Hygiene** - No silent placeholder field IDs; old run reports can be pruned

## Phase Details

### Phase 1: Safe User Resolution
**Goal**: Reporter/assignee values in `import` resolve to a user only when the match is unambiguous; every other case is skipped with a visible warning
**Depends on**: Nothing (first phase)
**Requirements**: USER-01, USER-02, USER-03, USER-04, USER-05
**Success Criteria** (what must be TRUE):
  1. A spreadsheet row whose reporter/assignee exactly matches one user's display name (case-insensitive) or email is created with that user assigned
  2. A row whose value matches several fuzzy candidates, or exactly one non-exact candidate, is created with that field left unset, and the console warning names the row, the value, and the candidates Jira returned
  3. `import --dry-run` with live credentials lists every ambiguous or unresolved user value before anything is written
  4. The test suite has one test each for exact-match, ambiguous, single-fuzzy, and no-match `find_user_account_id()` outcomes, and none of them resolve to `users[0]`
**Plans**: TBD

### Phase 2: Scalable Lookup & Plan Re-run Safety
**Goal**: Summary-based lookups return complete results at any import size, and `plan` can be re-run for the same PI without creating duplicate epics or tickets
**Depends on**: Nothing (independent of Phase 1); SCALE work comes first inside this phase because DEDUP reuses the same summary search
**Requirements**: SCALE-01, SCALE-02, SCALE-03, DEDUP-01, DEDUP-02, DEDUP-03, DEDUP-04, DEDUP-05
**Success Criteria** (what must be TRUE):
  1. An `import` with 500+ parent-by-summary rows resolves every matching parent. Mocked tests prove queries are chunked (≈100 summaries each) and follow `nextPageToken` until the results are exhausted
  2. Re-running `plan` for a PI that was already created shows existing epics/tickets as "already exists (KEY-123)" in the preview and creates none of them
  3. With `--allow-duplicates` (or equivalent flag), `plan` creates every ticket regardless of existing matches
  4. When a recurring epic already exists in Jira by summary, tickets referencing it via `$epic:` are linked to the existing epic key instead of a newly created epic
  5. `plan --dry-run` without credentials still renders a full preview and clearly states that the duplicate check was skipped
**Plans**: TBD

### Phase 3: Update Run Reports & Resume
**Goal**: A partially failed `update` can be safely retried for only the rows that didn't succeed, with the same safety guarantees as `plan`/`import`
**Depends on**: Nothing (mirrors the existing `run_report.py` / `cli.py` pattern used by `plan`/`import`)
**Requirements**: RESUME-01, RESUME-02, RESUME-03, RESUME-04
**Success Criteria** (what must be TRUE):
  1. After a live `update`, a report in `.jiramator/runs/` records success or failure (with the error) for each row
  2. `update --resume` (latest report) or `update --resume <path>` re-processes only failed/unprocessed rows and leaves already-updated issues untouched
  3. `update --resume` refuses to run when the input spreadsheet or resolved config changed since the original run, and proceeds only with `--force`
  4. Run reports written by v1.2.8 `plan`/`import` still load and resume without errors
**Plans**: TBD

### Phase 4: Config & Ops Hygiene
**Goal**: Misconfigured custom field IDs fail loudly and early, and users can clean up accumulated run reports
**Depends on**: Phase 3 (pruning covers the `update` reports introduced/formalized there)
**Requirements**: HYG-01, HYG-02, HYG-03, HYG-04, HYG-05, HYG-06
**Success Criteria** (what must be TRUE):
  1. When `init` cannot detect the Epic Link field, the wizard prints a visible warning telling the user to fill in the real field ID, and it never silently writes `customfield_XXXXX`
  2. Loading an org config whose `custom_fields` value is neither `customfield_<digits>` nor a known system field fails immediately with an error naming the key, the bad value, and the expected format
  3. `jiramator reports prune --older-than 30d` (or equivalent) deletes run reports older than the threshold and leaves newer ones in place
  4. Adding `--dry-run` to the prune command lists the files it would delete without deleting anything
  5. A `ConfigValidationError` raised inside a `@contextmanager`/`ExitStack` scope surfaces as itself (not `FrozenInstanceError`) on every supported Python, and two errors with equal fields still compare equal — locked by a regression test
  6. `plan --dry-run` with a release count missing from `release_sprint_schedule` prints the builder's actionable error and exits 1 with no traceback
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Safe User Resolution | 0/TBD | Not started | - |
| 2. Scalable Lookup & Plan Re-run Safety | 0/TBD | Not started | - |
| 3. Update Run Reports & Resume | 0/TBD | Not started | - |
| 4. Config & Ops Hygiene | 0/TBD | Not started | - |
