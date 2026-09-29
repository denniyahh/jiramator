---
id: SEED-260929-t72
status: dormant
planted: 2026-09-29
planted_during: v1.2.9 Hardening (scoping)
trigger_when: v1.3 milestone scoping
scope: Medium
---

# SEED-260929-t72: `update` writes run reports and supports `--resume` like `plan`/`import`

## Why This Matters

A partially failed bulk `update` can't be retried for only the failed rows. Production evidence is thin: `update` has run once in production (2026-07-13, a 2-row test).

## When to Surface

**Trigger:** v1.3 milestone scoping

Candidate for v1.3, moved out of the original (autonomously scoped) v1.3 draft when the
milestone was re-framed as v1.2.9 Hardening. Weigh against the user's own v1.3 candidate list.

## Scope Estimate

Medium (was RESUME-01..04): per-row report, `--resume` auto-latest/path, drift hash + `--force`, backward-compatible report schema. Verify first how much `update` already writes to `.jiramator/runs/`.

## Breadcrumbs

- `jiramator/updater.py`
- `jiramator/run_report.py`
- `jiramator/cli.py (_load_prior_report)`

## Notes

Planted during v1.2.9 re-scoping (2026-09-29).
