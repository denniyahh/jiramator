# Jiramator

## What This Is

A Python CLI tool that automates mass Jira issue creation for product owners and scrum masters during PI (Program Increment) planning. Users define organization-level and team-level configurations in YAML, and Jiramator creates epics, stories, and other issue types in bulk via Jira APIs — eliminating the repetitive manual entry of dozens of issues per planning cycle.

## Core Value

Eliminate repetitive manual Jira issue creation during PI planning by turning declarative YAML configs into bulk-created, correctly-linked Jira issues in one command.

## Requirements

### Validated

- ✓ CLI entrypoint with `plan` subcommand — existing
- ✓ Org-level YAML config (Jira URL, credentials, custom fields, sprint cadence) — existing
- ✓ Team-level YAML config (project key, team name, epic templates, ticket templates) — existing
- ✓ Pydantic-based config validation with template variable and epic ref checking — existing
- ✓ Template variable interpolation (`{pi_label}`, `{version}`, `{sprint_num}`, etc.) — existing
- ✓ Epic reference system (`$epic:ref` resolved after epic creation) — existing
- ✓ Two-phase build: epics first, then remaining tickets with resolved epic keys — existing
- ✓ Jira REST API client with auth, retry, and error handling — existing
- ✓ Bulk issue creation via Jira REST API — existing
- ✓ Fix version management (check/create in Jira) — existing
- ✓ Interactive CLI flow with Rich (prompts, preview tables, confirmations) — existing
- ✓ Dry-run mode for previewing without creating — existing
- ✓ Credentials from environment variables (never in config files) — existing

### Active

- [ ] Spreadsheet import (CSV/Excel to Jira issues)
- [ ] MCP API integration (primary API path, REST as fallback)
- [ ] Template inheritance (org defaults → team overrides → issue type templates)
- [ ] General hardening (tests, error handling, polish across modules)

### Out of Scope

- Confluence automation — future vision, not current milestone
- Real-time Jira sync / webhook listeners — not a monitoring tool
- Web UI — CLI-first tool
- Mobile support — desktop CLI only

## Context

- Brownfield project with working core PI planning flow
- Used by the author (PO) today; intended for broader audience (POs, scrum masters, tech leads)
- MCP is the preferred primary API path going forward, with REST as fallback
- Config model uses template inheritance: org sets defaults, teams override, issue type templates inherit from both
- Existing test suite and GitHub Actions CI pipeline in place
- Python 3.11+, Click, Pydantic 2.0+, requests, Rich, PyYAML

## Constraints

- **API compatibility**: Must work with Jira Cloud REST API v2/v3 and Jira MCP API
- **Auth model**: Credentials via environment variables only — no secrets in config files
- **Python**: >=3.11 (established in pyproject.toml)
- **Config format**: YAML for all user-facing configuration

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| MCP as primary API, REST as fallback | MCP provides richer integration; REST is stable and well-understood | — Pending |
| Template inheritance (org → team → issue type) | Eliminates repetitive field entry across configs | — Pending |
| Click for CLI framework | Already in use, well-suited for command groups | ✓ Good |
| Pydantic for config validation | Strong typing, clear error messages, already in use | ✓ Good |
| Two-phase build (epics first) | Epic keys needed for child ticket linking | ✓ Good |

## Open Questions

| Question | Why It Matters | Criticality | Status |
|----------|----------------|-------------|--------|
| What MCP capabilities are available for Jira issue creation? | Determines if MCP can fully replace REST or only supplement it | Critical | Pending |
| What spreadsheet formats need support (CSV, XLSX, both)? | Scope of import feature | Medium | Pending |
| How should template inheritance conflicts be resolved? | Affects config UX and predictability | Medium | Pending |

---
*Last updated: 2026-04-27 after initialization*
