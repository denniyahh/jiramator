# Requirements: Jiramator — v1.3 Hardening & Reliability

**Defined:** 2026-09-29
**Core Value:** Bulk Jira writes must be correct and safe to re-run — never silently assign, create, or modify the wrong thing.

> Scope chosen autonomously from `.planning/codebase/CONCERNS.md` + README future work
> (user unavailable at init). Adjust before `/gsd-plan-phase 1` if direction differs.

## v1 Requirements

### User Resolution (USER)

- [ ] **USER-01**: When a reporter/assignee value matches exactly one user by display name (case-insensitive) or email, `import` assigns that user
- [ ] **USER-02**: When a value matches no user exactly and Jira returns multiple fuzzy candidates, `import` skips the field for that row and prints a warning listing the candidates — it never assigns `users[0]`
- [ ] **USER-03**: When Jira returns exactly one fuzzy (non-exact) candidate, `import` skips it with a warning (no silent auto-assign)
- [ ] **USER-04**: `import --dry-run` preview reports ambiguous/unresolved user values when live lookup is available
- [ ] **USER-05**: Unit tests lock in exact-match, ambiguous, single-fuzzy, and no-match behaviors of `find_user_account_id()`

### Plan Re-run Safety (DEDUP)

- [ ] **DEDUP-01**: Before creating, `plan` queries Jira for existing issues in the project whose summary exactly matches each ticket/epic to be created
- [ ] **DEDUP-02**: The `plan` preview marks tickets that already exist in Jira (with their keys) and excludes them from creation by default
- [ ] **DEDUP-03**: User can opt out of duplicate skipping via an explicit flag (e.g. `--allow-duplicates`)
- [ ] **DEDUP-04**: Pre-existing recurring epics found by summary are reused as `$epic:` targets instead of being recreated
- [ ] **DEDUP-05**: Duplicate detection degrades gracefully in `--dry-run` without credentials (preview notes the check was skipped)

### Update Resume (RESUME)

- [ ] **RESUME-01**: `update` writes a run report to `.jiramator/runs/` recording per-row success/failure
- [ ] **RESUME-02**: User can run `update --resume` (auto-latest) or `update --resume <path>` to retry only failed/unprocessed rows
- [ ] **RESUME-03**: `update --resume` refuses on input/config drift (resolved hash mismatch) unless `--force` is passed
- [ ] **RESUME-04**: Existing `plan`/`import` run reports remain loadable (backward-compatible report schema)

### Lookup Scalability (SCALE)

- [ ] **SCALE-01**: `find_issue_keys_by_summaries()` chunks summaries into bounded JQL batches (≈100 per query)
- [ ] **SCALE-02**: `find_issue_keys_by_summaries()` paginates `/rest/api/3/search/jql` via `nextPageToken` until exhausted
- [ ] **SCALE-03**: An `import` with 500+ parent-by-summary rows resolves all matches (verified via mocked multi-page tests)

### Config & Ops Hygiene (HYG)

- [ ] **HYG-01**: `init` wizard prints a visible warning when it cannot detect the Epic Link field instead of silently writing `customfield_XXXXX`
- [ ] **HYG-02**: Loading an org config with a `custom_fields` value not matching `customfield_\d+` (or a known system field) fails with an actionable error
- [ ] **HYG-03**: User can prune run reports older than N days via a CLI command/flag (e.g. `jiramator reports prune --older-than 30d`)
- [ ] **HYG-04**: Pruning supports `--dry-run` listing files that would be deleted
- [ ] **HYG-05**: `ConfigValidationError` propagates through `@contextmanager` / `ExitStack` / `try-except BaseException` scopes on Python 3.11–3.14 without `FrozenInstanceError`, keeping value equality on `(file, line, field_path, reason)` (carried over from v1.0 DEFER-02-01)

## v2 Requirements

Deferred. Tracked but not in current roadmap.

### Live API Drift Detection

- **DRIFT-01**: Opt-in smoke-test suite that runs against a real Jira Cloud sandbox for createmeta, search/jql, bulk create
- **DRIFT-02**: CI job (manual trigger) for the live smoke suite

### Carried over from v1.0 (optional future work)

- **CARRY-01**: `import` applies org `default_fields` (v1.0 Phase 2 deliberately scoped this to `plan` only)
- **CARRY-02**: Sub-task support in `plan` templates
- **CARRY-03**: Config diff command (v1.0 CONF-02)

### Cleanup

- **CLEAN-01**: Remove unused `__version__` from `jiramator/__init__.py`

## Out of Scope

| Feature | Reason |
|---------|--------|
| MCP server / REST API | Declined in v1.0 — superseded by `init` wizard + non-interactive CLI |
| Generic deferred-field hook refactor | Over-engineering for three deferred fields |
| Credential rotation mid-run | No long-running daemon usage |
| Batched epic creation | Handful of epics per PI; not a bottleneck |
| Automatic rollback of partial bulk creates | Resume mechanism is the chosen mitigation |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| USER-01 | Phase 1 | Pending |
| USER-02 | Phase 1 | Pending |
| USER-03 | Phase 1 | Pending |
| USER-04 | Phase 1 | Pending |
| USER-05 | Phase 1 | Pending |
| SCALE-01 | Phase 2 | Pending |
| SCALE-02 | Phase 2 | Pending |
| SCALE-03 | Phase 2 | Pending |
| DEDUP-01 | Phase 2 | Pending |
| DEDUP-02 | Phase 2 | Pending |
| DEDUP-03 | Phase 2 | Pending |
| DEDUP-04 | Phase 2 | Pending |
| DEDUP-05 | Phase 2 | Pending |
| RESUME-01 | Phase 3 | Pending |
| RESUME-02 | Phase 3 | Pending |
| RESUME-03 | Phase 3 | Pending |
| RESUME-04 | Phase 3 | Pending |
| HYG-01 | Phase 4 | Pending |
| HYG-02 | Phase 4 | Pending |
| HYG-03 | Phase 4 | Pending |
| HYG-04 | Phase 4 | Pending |
| HYG-05 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 22 total
- Mapped to phases: 22
- Unmapped: 0 ✓

---
*Requirements defined: 2026-09-29*
*Last updated: 2026-09-29 after roadmap creation*
