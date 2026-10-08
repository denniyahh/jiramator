# Jiramator

## What This Is

Jiramator is a config-driven Python CLI for bulk Jira ticket automation: `plan` generates a
Program Increment's worth of epics/tickets from YAML templates, `import` bulk-creates issues
from CSV/XLSX, and `update` bulk-edits existing issues from CSV/XLSX. It is used by
Acme teams (starting with Calcs) to replace manual, error-prone PI setup and
spreadsheet-driven ticket churn. Everything is preview-first — `--dry-run` never touches Jira.

## Core Value

Bulk Jira writes must be **correct and safe to re-run** — never silently assign, create, or
modify the wrong thing. A preview that matches what the live run will actually do is the
contract users rely on.

## Requirements

### Validated

<!-- Shipped in v1.0–v1.2.8 and in active use. -->

- ✓ `plan`: generate epics + per-release + per-sprint tickets from org/team YAML config — existing
- ✓ `plan`: template variables (`{pi_label}`, `{version}`, `{sprint_num}`, `{team_name}`, `{pi_num}`) validated at parse time — existing
- ✓ `plan`: `$epic:<ref>` resolution with mixable `recurring_epics` / `existing_epics` — existing
- ✓ `plan`: sprint assignment via board sprint lookup; configurable sprint field — existing
- ✓ `plan`: live createmeta field validation in dry-run and live runs (graceful offline degrade) — existing
- ✓ `import`: CSV/XLSX bulk create with field alias resolution + `auto_lookup_unknown_fields` — existing
- ✓ `import`: deferred live resolution of reporter/assignee (user search), parent (key/summary), sprint (name→ID) — existing
- ✓ `update`: CSV/XLSX bulk edit with value coercion and `value_aliases` — existing
- ✓ Run reports in `.jiramator/runs/` with `--resume` / `--resume --force` drift check for `plan` and `import` — existing
- ✓ `plan` non-interactive mode (`--pi-number`/`--versions`/`--yes`) — v1.0 (FOUND-05/INTG-02)
- ✓ Template inheritance: org `default_fields` → team `defaults` → template `fields` — v1.0
- ✓ `init` interactive setup wizard for org/team config — v1.0 (CONF-01)
- ✓ Corporate TLS interception support (`JIRAMATOR_CA_BUNDLE`, `JIRAMATOR_RELAX_TLS_STRICT`) — existing
- ✓ CI on Linux/macOS/Windows × Python 3.11–3.13; 699 tests passing — existing (Phase 1 count)
- ✓ Unexplained production `plan` failures are root-caused (INV-01 user-accepted residual, INV-02 config + already-fixed code gap, INV-03 all 5 zero-count failures classified) — Phase 1
- ✓ Crashed/aborted `plan`/`import` runs record `ended_at` + `error` in the run report, with credential redaction across `plan`/`import`/`update` reports (INV-04) — Phase 1

### Active

<!-- Milestone: v1.2.9 Hardening (1.2.x patch releases). Hypotheses until shipped. -->

- [ ] `import` validates every row against Jira's schema before writing (as `plan` does)
- [ ] User lookups never silently pick the wrong person on ambiguous names
- [ ] Build/config errors surface as clean messages, never tracebacks or silent placeholders
- [ ] The test suite never writes into the real run-report directory
- [ ] Jira connection/TLS/timeout errors surface as `JiraApiError`, and a bulk-create transport error marks the batch failed in the report (HYG-05, emerged in Phase 1 triage)

v1.3 candidates (features) are parked as seeds in `.planning/seeds/`.

### Out of Scope

- MCP server / REST API entry point — reviewed and declined in v1.0; superseded by `init` wizard + non-interactive CLI
- Generic deferred-field resolution hook refactor — over-engineering for three fields (ISSUES.md)
- Credential rotation / long-running daemon mode — not a current usage pattern (CONCERNS.md)
- Batching epic creation — only a handful of epics per PI; not a bottleneck
- Web UI / GitHub Actions form productization — experimental, often blocked by enterprise policy

## Context

- Prior GSD milestone **v1.0** (Reliability, Template Inheritance, Accessibility — 3 phases,
  8 plans, complete) is archived in `.planning/milestones/v1.0-*`, imported from the work
  clone (`~/dev/work_projects/jiramator`). This personal clone is the primary dev repo; the
  work clone is the production/corporate-sharing copy.
- Remotes: personal `origin` (denniyahh/jiramator, PUBLIC) is canonical for local dev branches. The work clone's `origin` (work-account/jiramator, PRIVATE) is a custom fork: core code syncs one way (personal → work, e.g. `git push work develop:develop` from the personal repo, which has remote `work`). Work-only files (e.g. `fc1ea30` real Calcs team config on work `main`) never go to personal `origin`. Work-fork git/gh needs `GH_TOKEN=$(gh auth token -u work-account)`, because the gh credential helper uses the active denniyahh account. Fetch the work clone with `--no-tags`: the v1.2.5 tag objects differ (same commit), so a tag fetch fails with 'would clobber'.
- Brownfield: v1.2.8, codebase map in `.planning/codebase/` (mapped 2026-09-28 at `8c96e59`).
- Five-layer architecture (CLI / Config / Builder / Client / Planner) plus parallel
  `importer`/`updater` path via `field_resolver` + `value_coercion`.
- Jira Cloud API shape drift is the historically fragile area (CHANGELOG 1.2.6: createmeta key
  and pagination bugs were invisible to mocked tests). Changes to `jira_client.py` should be
  smoke-tested against live Jira.
- Recurring theme: "friendly name vs. internal ID" mismatches (sprint, epic link, users).
- `find_user_account_id()` falls back to `users[0]` on non-exact match with no warning
  (`jira_client.py:~313`).
- `find_issue_keys_by_summaries()` builds one unbounded OR'd JQL with `maxResults=len(...)`
  and no pagination.
- `wizard.py:156` falls back to `customfield_XXXXX`.
- Milestone scope was first drafted autonomously (user unavailable at init), then reviewed and
  re-framed with the user as v1.2.9 Hardening against production run-report evidence.

## Constraints

- **Tech stack**: Python ≥3.11, Click, Pydantic, Rich, requests — keep existing stack
- **Compatibility**: Existing org/team YAML configs and run-report JSON must keep loading (backward compatible)
- **Safety**: Preview-first; `--dry-run` never writes to Jira
- **Conventions**: `from __future__ import annotations`, Rich stderr console for output, `logging` only in `jira_client.py`, Google docstrings (see CLAUDE.md)
- **Testing**: Mock HTTP via `client._session`; don't mock Pydantic/YAML/builder logic; integration ticket counts are a regression guard
- **Credentials**: env vars only, never in config

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Hardening milestone = v1.2.9 (patch releases), features deferred to v1.3 seeds | Autonomous v1.3 draft reviewed with user: evidence-backed fixes only; v1.2.5 was taken by an existing tag | ✓ Good |
| Ambiguous user match → skip + warn (not first result) | Mirrors existing "could not resolve" UX; wrong assignment is worse than none | — Pending |
| `.planning/` stays local (gitignored, `commit_docs: false`) | Personal workflow state never committed to shared branches | ✓ Good |
| Each phase runs in its own worktree: `wsx new gsd/phase-NN-<slug>` off `develop`, merged back `--no-ff` per phase; GSD `branching_strategy: none` inside it, `git.base_branch: develop`, `workflow.use_worktrees: true` for executor isolation | Global rule: never commit to integration branches, all dev in dedicated worktrees. GSD's `phase` strategy would `git switch` in the current worktree and fork from `origin/HEAD` (`main`) | ✓ Good |
| INV-01 closed as a user-accepted residual (exits c, d, e, f, g, h, j) rather than a single guessed cause | The report alone could not distinguish the exits; JQL shows no writes, so no duplicate-ticket harm. INV-04 now records each exit distinctly; HYG-05 owns the transport-error branches | ✓ Good |
| Credential redaction errs on over-redaction (any word after `basic`/`bearer`, except "Basic Constraints") | Leak safety outweighs diagnostic fidelity; the real Jira token is also caught by exact match | ✓ Good (accepted in UAT 2026-10-05) |
| Abort reasons may be more informative in the report than on screen; fix-version decline console line now names the versions | Plan's "equal to console" + "console unchanged" criteria were over-literal; additive changes only, exit codes unchanged | ✓ Good (accepted in UAT 2026-10-08) |
| Skip domain research | Brownfield hardening of a well-mapped codebase; codebase map suffices | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-08 after Phase 1*
