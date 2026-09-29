---
id: SEED-260929-5k3
status: dormant
planted: 2026-09-29
planted_during: v1.2.9 Hardening (scoping)
trigger_when: v1.3 milestone scoping
scope: Trivial
---

# SEED-260929-5k3: Remove unused `__version__` from `jiramator/__init__.py`

## Why This Matters

Dead code duplicating `pyproject.toml`'s version; Click reads package metadata.

## When to Surface

**Trigger:** v1.3 milestone scoping

Candidate for v1.3, moved out of the original (autonomously scoped) v1.3 draft when the
milestone was re-framed as v1.2.9 Hardening. Weigh against the user's own v1.3 candidate list.

## Scope Estimate

Trivial (was CLEAN-01) — bundle with any change touching `__init__.py`.

## Breadcrumbs

- `jiramator/__init__.py`

## Notes

Planted during v1.2.9 re-scoping (2026-09-29).
