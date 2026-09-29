# Requirements: Jiramator — v1.2.9 Hardening

**Defined:** 2026-09-29 (re-scoped from the autonomous v1.3 draft after review with the user)
**Core Value:** Bulk Jira writes must be correct and safe to re-run — never silently assign, create, or modify the wrong thing.

Hardening only — fixes and small safety additions, shipped as 1.2.x patch releases. Every
requirement is backed by production evidence (work clone `.jiramator/runs/`) or a verified code
defect. Feature work moved to v1.3 candidate seeds in `.planning/seeds/`.

## v1.2.9 Requirements

### Production Triage (INV)

- [ ] **INV-01**: The root cause of the live `plan` failure on 2026-07-21 (work clone report `20260721T121841Z-calcs.json`, status `failed`, 0 created/failed) is identified and either fixed here or filed
- [ ] **INV-02**: The root cause of `fixVersions: Version name 'Fix versions' is not valid` (2026-07-13 `plan`, dm-test) is identified as config or code, and fixed or documented
- [ ] **INV-03**: Every `failed` run with 0 counts in the work clone's reports (2026-07-16, 07-17, 07-21) is classified: covered by HYG-04, config error, or a new defect

### Import Preflight (PRE)

- [ ] **PRE-01**: `import --dry-run` with credentials checks every row's payload against Jira's createmeta schema for its project and issue type, and lists each row's missing required fields before anything is written
- [ ] **PRE-02**: The same preview reports select/option values Jira will reject, and plain-text values where Jira expects ADF
- [ ] **PRE-03**: A live `import` runs the same check before creating anything and reports every failing row at once, instead of surfacing them one Jira 400 at a time
- [ ] **PRE-04**: Without credentials or Jira access, `import --dry-run` still previews and states that schema validation was skipped (same degrade behaviour as `plan`)

### User Resolution (USER)

- [ ] **USER-01**: When a reporter/assignee value matches exactly one user by display name (case-insensitive) or email, `import` assigns that user
- [ ] **USER-02**: When a value matches no user exactly and Jira returns multiple fuzzy candidates, `import` skips the field for that row and warns, listing the candidates — it never assigns `users[0]`
- [ ] **USER-03**: When Jira returns exactly one fuzzy (non-exact) candidate, `import` skips it with a warning (no silent auto-assign)
- [ ] **USER-04**: `import --dry-run` preview reports ambiguous/unresolved user values when live lookup is available
- [ ] **USER-05**: Unit tests lock in exact-match, ambiguous, single-fuzzy, and no-match behaviours of `find_user_account_id()`

### Error & Config Hygiene (HYG)

- [ ] **HYG-01**: `init` wizard prints a visible warning when it cannot detect the Epic Link field, instead of silently writing `customfield_XXXXX`
- [ ] **HYG-02**: Loading an org config with a `custom_fields` value not matching `customfield_\d+` (or a known system field) fails with an actionable error
- [ ] **HYG-03**: `ConfigValidationError` propagates through `@contextmanager` / `ExitStack` / `try-except BaseException` scopes on Python 3.11–3.14 without `FrozenInstanceError`, keeping value equality on `(file, line, field_path, reason)` (v1.0 DEFER-02-01)
- [ ] **HYG-04**: When `plan` fails to build tickets (e.g. a builder `ValueError` such as a missing `release_sprint_schedule` entry for the given release count), it prints the actionable message via the Rich console and exits 1 — never a Python traceback

### Test Hygiene (TEST)

- [ ] **TEST-01**: Running the test suite never writes run reports into the working tree's `.jiramator/runs/` (147 of 184 reports in the work clone came from pytest)

## Future Requirements

Deferred to v1.3 candidates — see `.planning/seeds/` (surface at `/gsd-new-milestone`):
`plan` duplicate detection, `update` run reports + `--resume`, summary-lookup chunking/pagination,
run-report pruning, `import` org `default_fields`, sub-task support, config diff, live-Jira drift
smoke suite, dead `__version__` removal.

## Out of Scope

| Feature | Reason |
|---------|--------|
| MCP server / REST API | Declined in v1.0 — superseded by `init` wizard + non-interactive CLI |
| Generic deferred-field hook refactor | Over-engineering for three deferred fields |
| Credential rotation mid-run | No long-running daemon usage |
| Batched epic creation | Handful of epics per PI; not a bottleneck |
| Automatic rollback of partial bulk creates | Resume mechanism is the chosen mitigation |
| New features of any kind | v1.2.9 is hardening only; features are v1.3 candidates |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INV-01 | Phase 1 | Pending |
| INV-02 | Phase 1 | Pending |
| INV-03 | Phase 1 | Pending |
| PRE-01 | Phase 2 | Pending |
| PRE-02 | Phase 2 | Pending |
| PRE-03 | Phase 2 | Pending |
| PRE-04 | Phase 2 | Pending |
| USER-01 | Phase 3 | Pending |
| USER-02 | Phase 3 | Pending |
| USER-03 | Phase 3 | Pending |
| USER-04 | Phase 3 | Pending |
| USER-05 | Phase 3 | Pending |
| HYG-01 | Phase 4 | Pending |
| HYG-02 | Phase 4 | Pending |
| HYG-03 | Phase 4 | Pending |
| HYG-04 | Phase 4 | Pending |
| TEST-01 | Phase 4 | Pending |

**Coverage:**
- v1.2.9 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-09-29*
*Last updated: 2026-09-29 after re-scoping v1.3 → v1.2.9 Hardening*
