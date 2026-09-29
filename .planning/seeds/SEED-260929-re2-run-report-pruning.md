---
id: SEED-260929-re2
status: dormant
planted: 2026-09-29
planted_during: v1.2.9 Hardening (scoping)
trigger_when: v1.3 milestone scoping
scope: Small
---

# SEED-260929-re2: Command to prune old run reports

## Why This Matters

Run reports accumulate in `.jiramator/runs/` with no cleanup. Note the observed bloat in the work clone (184 files) was mostly test pollution, fixed separately in v1.2.9 — revisit only if real runs accumulate.

## When to Surface

**Trigger:** v1.3 milestone scoping

Candidate for v1.3, moved out of the original (autonomously scoped) v1.3 draft when the
milestone was re-framed as v1.2.9 Hardening. Weigh against the user's own v1.3 candidate list.

## Scope Estimate

Small (was HYG-03/04): `jiramator reports prune --older-than 30d` with `--dry-run`.

## Breadcrumbs

- `jiramator/run_report.py (RUNS_DIR)`

## Notes

Planted during v1.2.9 re-scoping (2026-09-29).
