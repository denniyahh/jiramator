---
id: SEED-260929-kx3
status: dormant
planted: 2026-09-29
planted_during: v1.2.9 Hardening (scoping)
trigger_when: v1.3 milestone scoping
scope: Large
---

# SEED-260929-kx3: `plan` detects and skips issues that already exist in Jira

## Why This Matters

Re-running `plan` for the same PI outside the run-report resume path can create duplicate epics/tickets. `import` already skips exact-summary duplicates; `plan` does not. Top item in CONTRIBUTING's future-work list.

## When to Surface

**Trigger:** v1.3 milestone scoping

Candidate for v1.3, moved out of the original (autonomously scoped) v1.3 draft when the
milestone was re-framed as v1.2.9 Hardening. Weigh against the user's own v1.3 candidate list.

## Scope Estimate

Large (was 5 requirements, DEDUP-01..05): exact-summary match via search/jql + client-side filter (`summary ~` is fuzzy), preview marks existing keys, `--allow-duplicates` opt-out, reuse found recurring epics as `$epic:` targets, graceful offline degrade. Depends on the summary-lookup scaling seed.

## Breadcrumbs

- `jiramator/planner.py`
- `jiramator/jira_client.py:find_issue_keys_by_summaries`
- `CONTRIBUTING.md (Roadmap / future enhancements)`

## Notes

Planted during v1.2.9 re-scoping (2026-09-29).
