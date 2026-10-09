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

---

## Adversarial review (2026-10-09, gpt-5.5 rubber-duck)

12 findings: 3 blocking, 7 should-fix, 2 nits. The orchestrator spot-checked the key claims against the code and the read-only run reports, and they all hold. Disposition:

| # | Finding | Severity | Disposition |
|---|---------|----------|-------------|
| 1 | D-02 "schema fetch failure → proceed" would let an invalid issue type reach live Jira 400s (`get_createmeta_fields_by_type_name` raises JiraApiError for an unknown type) | blocking | D-02 rewritten: unavailable vs row-problem split |
| 2 | D-06: a raw deferred value doesn't guarantee a resolved payload value (lookups skip on failure) | blocking | D-06: field-ID↔deferred-header mapping, plus a non-blocking "not preflight-validated" caveat for required deferred fields; live lookups stay out of scope (Phase 3) |
| 3 | Fields that are sent but not on the create screen are silently skipped by the validator | blocking | New D-10 (import-only caller option) |
| 4 | D-04 "degrade decided once" conflates get_fields and createmeta | should-fix | D-04 tracks the two paths separately |
| 5 | D-03 dry-run exit 1 breaks the existing exit-0 contract and tests | should-fix | Kept exit 1, marked as a deliberate breaking change (costly); tests, README and CHANGELOG to be updated |
| 6 | D-07 shared-constant change risks `plan` | should-fix | D-07: keyword argument whose default preserves `plan`, plus regression tests |
| 7 | D-08: preflight must run after the resume skip set is computed | should-fix | D-08 and the Integration Points entry updated |
| 8 | D-09: the validator can't produce column names | should-fix | D-09: column names best-effort, with mapping rules |
| 9 | Evidence summary imprecise | should-fix | Evidence line rewritten with the per-row shape |
| 10 | D-01 reversibility understated | should-fix | Re-rated costly |
| 11 | Project is fixed per team config | nit | Folded into D-05 |
| 12 | Console and report volume for large sheets | nit | New D-11: full console list; per-row IssueResults in the report |
