---
id: SEED-260929-wo2
status: dormant
planted: 2026-09-29
planted_during: v1.2.9 Hardening (scoping)
trigger_when: v1.3 milestone scoping
scope: Small
---

# SEED-260929-wo2: Chunk and paginate summary-based issue lookups for large imports

## Why This Matters

`find_issue_keys_by_summaries()` builds one unbounded OR'd JQL with `maxResults=len(summaries)` and no `nextPageToken` pagination. Real imports so far are 2–6 rows, so this is speculative until imports get large; it is a prerequisite for `plan` duplicate detection.

## When to Surface

**Trigger:** v1.3 milestone scoping

Candidate for v1.3, moved out of the original (autonomously scoped) v1.3 draft when the
milestone was re-framed as v1.2.9 Hardening. Weigh against the user's own v1.3 candidate list.

## Scope Estimate

Small (was SCALE-01..03): ~100 summaries per JQL batch, paginate `/rest/api/3/search/jql`. Smoke-test against live Jira (mocks missed the 1.2.6 API-shape bugs).

## Breadcrumbs

- `jiramator/jira_client.py:find_issue_keys_by_summaries`
- `.planning/codebase/CONCERNS.md (Performance Bottlenecks)`

## Notes

Planted during v1.2.9 re-scoping (2026-09-29).
