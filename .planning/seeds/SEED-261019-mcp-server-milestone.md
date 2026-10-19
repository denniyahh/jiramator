---
id: SEED-261019-mcp
status: dormant
planted: 2026-10-19
planted_during: v1.2.9 Hardening (Phase 02 verifying)
trigger_when: next milestone scoping after v1.2.9 (user's stated top priority)
scope: Large
---

# SEED-261019-mcp: MCP server milestone (drafted)

## Why This Matters

User-stated top priority for the next milestone (2026-10-16): drive `plan`/`import`/`update`
from an MCP-aware assistant (Copilot, Claude) in plain English, keeping preview-before-write.
Reverses the v1.0 "MCP declined" decision — the `init` wizard and promptless `plan` core now
cover the on-ramp barriers that blocked it.

## When to Surface

**Trigger:** next milestone scoping (`/gsd-new-milestone`) after v1.2.9 closes.

## Scope Estimate

Large — drafted as 5 phases / 19 requirements. A full draft exists alongside this seed in
`SEED-261019-mcp-server-milestone-draft/`:

- `PROJECT-current-milestone.md` — goal + target features
- `REQUIREMENTS.md` — FOUND-06..09, UPDT-01..02, ISSUE-03, ISSUE-05, FOUND-04, MCP-01..09, DOCS-01
- `ROADMAP.md` — phases: shared core + update resume → Markdown preview + duplicates →
  rollback (CLI) → MCP read-only → MCP token-gated writes + docs
- `research/` — STACK/FEATURES/ARCHITECTURE/PITFALLS/SUMMARY (2026-10-16)

The draft was written against a stale `.planning` copy in the work clone (phase numbering
4–8, milestone label "v1.1"); renumber/relabel when adopting. It overlaps existing seeds
`SEED-260929-t72` (update resume), `-kx3` (duplicate detection), `-wo2` (summary lookup
scaling) — fold them in rather than duplicating.

## Breadcrumbs

- `docs/mcp-server-proposal.md` (design baseline; its `mcp>=1.0` pin is stale)
- Key research findings: MCP SDK is now 2.x (`FastMCP` → `MCPServer`, pin `mcp>=2.3,<3`);
  `compute_resolved_hash` ignores spreadsheet rows, so preview tokens must also digest rows;
  `jira_client` retries create POSTs (duplicate risk); `find_issue_keys_by_summaries`
  `maxResults` bug.

## Notes

Planted 2026-10-19 when the misplaced work-clone `personal-workspace` was removed.
