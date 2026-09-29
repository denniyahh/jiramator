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
- ✓ CI on Linux/macOS/Windows × Python 3.11–3.13; 653 tests passing — existing

### Active

<!-- Milestone: v1.3 Hardening & Reliability. Hypotheses until shipped. -->

- [ ] User lookups never silently pick the wrong person on ambiguous names
- [ ] `plan` can be re-run without creating duplicate epics/tickets
- [ ] `update` supports run reports and `--resume` like `plan`/`import`
- [ ] Summary-based parent lookup scales to large imports (chunking + pagination)
- [ ] `init` wizard never writes a silent placeholder custom field ID
- [ ] Old run reports can be pruned
- [ ] Config validation errors survive context-manager unwinding on Python 3.14 (v1.0 DEFER-02-01)

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
- **Milestone direction chosen autonomously** (user unavailable during `/gsd-new-project`),
  grounded in `.planning/codebase/CONCERNS.md` and README future work. Revisit if the user
  intends a different direction.

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
| Milestone v1.3 = Hardening & Reliability | Only documented open work; aligns with Core Value (correct & safe to re-run) | — Pending |
| Ambiguous user match → skip + warn (not first result) | Mirrors existing "could not resolve" UX; wrong assignment is worse than none | — Pending |
| `.planning/` stays local (gitignored, `commit_docs: false`) | Personal workflow state never committed to shared branches | ✓ Good |
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
*Last updated: 2026-09-29 after initialization*
