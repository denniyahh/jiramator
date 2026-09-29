---
id: SEED-260929-nbp
status: dormant
planted: 2026-09-29
planted_during: v1.2.9 Hardening (scoping)
trigger_when: v1.3 milestone scoping
scope: Medium
---

# SEED-260929-nbp: Opt-in smoke suite against a real Jira sandbox for API-shape drift

## Why This Matters

All tests mock HTTP; the 1.2.6 createmeta key and pagination bugs were invisible to mocks and only surfaced in live use.

## When to Surface

**Trigger:** v1.3 milestone scoping

Candidate for v1.3, moved out of the original (autonomously scoped) v1.3 draft when the
milestone was re-framed as v1.2.9 Hardening. Weigh against the user's own v1.3 candidate list.

## Scope Estimate

Medium (was DRIFT-01/02): opt-in marker/suite for createmeta, search/jql, bulk create; manual-trigger CI job.

## Breadcrumbs

- `tests/test_jira_client.py`
- `.planning/codebase/CONCERNS.md (Test Coverage Gaps)`

## Notes

Planted during v1.2.9 re-scoping (2026-09-29).
