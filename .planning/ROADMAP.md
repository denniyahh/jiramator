# Roadmap: Jiramator

## Milestones

- ✅ **v1.0 Feature Extensions** - Phases 1-3 (shipped 2026-07-10; archived in `milestones/v1.0-*`)
- 🚧 **v1.2.9 Hardening** - Phases 1-4 (in progress)

## Overview

v1.2.8 is shipped and in production use. v1.2.9 hardens the paths where production runs have
actually failed or could silently go wrong, shipped as 1.2.x patch releases. It starts by triaging
the unexplained failures in the work clone's run reports, since findings may reshape later
phases. Then `import` gains the same pre-write schema validation `plan` already has — the
highest-value fix, given the 2026-09-02 Risk import needed four attempts. User lookups stop
guessing. The milestone closes with small error/config hygiene fixes and isolating tests from
the real run-report directory. Feature work is parked as v1.3 candidate seeds.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Production Triage** - Root-cause the unexplained `plan` failures in production run reports
- [ ] **Phase 2: Import Preflight Validation** - `import` validates every row against Jira's createmeta schema before writing
- [ ] **Phase 3: Safe User Resolution** - `import` never assigns a reporter/assignee from an ambiguous or fuzzy user match
- [ ] **Phase 4: Error, Config & Test Hygiene** - Clean errors instead of tracebacks, validated field IDs, tests isolated from real run reports

## Phase Details

### Phase 1: Production Triage
**Goal**: Every unexplained production failure in the work clone's run reports has a known root cause, and each is either fixed, folded into a later phase, or filed
**Depends on**: Nothing (first phase; findings may add requirements to Phases 2–4)
**Requirements**: INV-01, INV-02, INV-03, INV-04
**Success Criteria** (what must be TRUE):
  1. The 2026-07-21 live `plan` failure (`20260721T121841Z-calcs.json`) has a written root cause, reproduced or explained from the report and code
  2. The `Version name 'Fix versions' is not valid` error is attributed to config or code; if code, it is fixed with a regression test
  3. Each zero-count `failed` report from 2026-07-16/17/21 is classified (HYG-04 traceback, config error, or new defect) and any new defect has a requirement or issue
  4. A `plan` or `import` that crashes leaves a run report with `ended_at` and the exception type/message; pre-existing reports still load and `--resume` still works
**Plans**: TBD

### Phase 2: Import Preflight Validation
**Goal**: A user sees every row `import` would fail on — missing required fields, rejected option values, non-ADF rich text — before anything is written to Jira
**Depends on**: Phase 1 (triage may surface related import defects)
**Requirements**: PRE-01, PRE-02, PRE-03, PRE-04
**Success Criteria** (what must be TRUE):
  1. Replaying the 2026-09-02 Risk import shape with `--dry-run` lists the missing `Fix versions` and `Repositories` fields per row, with no Jira writes
  2. Invalid select values and plain-text-for-ADF values are reported in the same preview
  3. A live `import` reports all failing rows up front instead of discovering them one 400 at a time
  4. Without credentials, `import --dry-run` still previews and says schema validation was skipped
**Plans**: TBD

### Phase 3: Safe User Resolution
**Goal**: Reporter/assignee values in `import` resolve to a user only when the match is unambiguous; every other case is skipped with a visible warning
**Depends on**: Phase 2 (ambiguous-user warnings appear in the same preflight preview)
**Requirements**: USER-01, USER-02, USER-03, USER-04, USER-05
**Success Criteria** (what must be TRUE):
  1. An exact display-name (case-insensitive) or email match to one user assigns that user
  2. Multiple fuzzy candidates, or one non-exact candidate: the field is left unset and a warning lists row, value and candidates
  3. `import --dry-run` with credentials lists ambiguous/unresolved user values before any write
  4. Tests cover exact, ambiguous, single-fuzzy and no-match cases; none resolve to `users[0]`
**Plans**: TBD

### Phase 4: Error, Config & Test Hygiene
**Goal**: Misconfiguration and build errors fail loudly and cleanly, and the test suite never pollutes real run reports
**Depends on**: Phase 1 (triage may attribute failures to HYG-04)
**Requirements**: HYG-01, HYG-02, HYG-03, HYG-04, TEST-01
**Success Criteria** (what must be TRUE):
  1. When `init` cannot detect the Epic Link field it prints a visible warning and never silently writes `customfield_XXXXX`
  2. An invalid `custom_fields` value fails config loading with an error naming the key, the value and the expected format
  3. A `ConfigValidationError` raised inside a `@contextmanager`/`ExitStack` scope surfaces as itself on every supported Python, and equal errors still compare equal — locked by a regression test
  4. `plan --dry-run` with a release count missing from `release_sprint_schedule` prints the builder's actionable error and exits 1 with no traceback
  5. A full `pytest` run leaves the working tree's `.jiramator/runs/` unchanged
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Production Triage | 0/TBD | Not started | - |
| 2. Import Preflight Validation | 0/TBD | Not started | - |
| 3. Safe User Resolution | 0/TBD | Not started | - |
| 4. Error, Config & Test Hygiene | 0/TBD | Not started | - |
