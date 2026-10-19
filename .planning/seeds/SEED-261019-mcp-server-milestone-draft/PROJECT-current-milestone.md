## Current Milestone: v1.1 MCP Server

**Goal:** Let users drive Jiramator's `plan`/`import`/`update` from an MCP-aware AI
assistant (Copilot, Claude) in plain English, without losing the preview-before-write
guarantee.

**Target features:**
- Local stdio MCP server (`jiramator-mcp`, optional `[mcp]` extra) exposing read-only
  discovery + `preview_*` tools for plan/import/update
- Write tools (`create_plan`/`create_import`/`apply_update`/`resume_run`) gated by a
  `preview_token` tied to `compute_resolved_hash` drift detection
- Run reports + `--resume` for `update` (parity so `resume_run`/`list_run_reports`
  cover all three commands)
- Run rollback (FOUND-04) — undo the issues a run created
- Duplicate detection before create (ISSUE-03)
- Markdown preview export (ISSUE-05) — shared renderer for CLI `--dry-run` and
  MCP `preview_*` results
- MCP setup docs (client registration for Copilot/Claude)

**Key context:** Reverses the v1.0 Phase 3 decision to decline MCP (see Key
Decisions). The prerequisite refactor — promptless `plan` core (`PlanInputs`) —
already shipped in v1.0.1. Design baseline: `docs/mcp-server-proposal.md`. HTTP/SSE
shared-server transport deferred.

