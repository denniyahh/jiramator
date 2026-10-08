# Phase 2: Import Preflight Validation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-08
**Phase:** 02-import-preflight-validation
**Areas discussed:** Live-run failure policy, Dry-run behaviour, What gets validated, Reporting format
**Mode:** autopilot. The user was unavailable, so every area was auto-selected and resolved to the recommended option.

---

## Live-run failure policy

| Option | Description | Selected |
|--------|-------------|----------|
| Abort all, write nothing | Same as `plan`'s preflight hard stop; fix the sheet and re-run | ✓ (recommended) |
| Create valid rows, report invalid | Partial import; resume picks up the rest later | |
| Abort by default + `--skip-invalid` opt-in | Adds a new flag | |

**User's choice:** [auto] Abort all (D-01). Schema-fetch failure on a live run: warn and proceed, as `plan` does (D-02).

## Dry-run behaviour

| Option | Description | Selected |
|--------|-------------|----------|
| Full failing-row list, exit 1 on problems | Same as `plan --dry-run` | ✓ (recommended) |
| Full list, always exit 0 | Preview-only semantics | |

**User's choice:** [auto] exit 1 on problems; when there are no credentials or Jira is unreachable, say "schema validation skipped" and exit 0 (D-03, D-04).

## What gets validated

| Option | Description | Selected |
|--------|-------------|----------|
| Per-row issue type, deferred fields count as present when a raw value exists, no live lookups | Avoids false "required" hits for assignee/parent/sprint; keeps Phase 3 scope separate | ✓ (recommended) |
| Resolve deferred fields live during preflight | Duplicates Phase 3 work and costs extra API calls | |

**User's choice:** [auto] D-05, D-06. fixVersions values are validated for import, because import never creates versions (D-07). Rows that fail to build are listed too; rows a resume would skip are not validated (D-08).

## Reporting format

| Option | Description | Selected |
|--------|-------------|----------|
| Grouped per row with source column name and a total | Easy to find each problem in the spreadsheet | ✓ (recommended) |
| Flat list as in `plan` | Consistent with `plan` but harder to map back to rows | |

**User's choice:** [auto] D-09

## the agent's Discretion
- Where the shared validation helper lives, the console styling, and the test layout.

## Deferred Ideas
- `--skip-invalid` mode; dry-run preview of ambiguous user values (Phase 3); validating `update` payloads against editmeta.
