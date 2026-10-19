# Requirements: Jiramator

**Defined:** 2026-10-16
**Milestone:** v1.1 MCP Server
**Core Value:** Eliminate repetitive manual Jira issue creation/editing during PI planning
and bulk data intake, without ever surprising the user — every operation shows a preview
before touching Jira.

**Scoping assumptions (made autonomously 2026-10-16, user unavailable — review):**
MCP server is the primary goal (user-stated). From the outstanding backlog, included only
items that directly support safe assistant-driven writes: `update --resume`, FOUND-04,
ISSUE-03, ISSUE-05. Transport is local stdio only. Rollback is CLI-only for v1.1. Research
basis: `.planning/research/SUMMARY.md`.

## v1.1 Requirements

### Foundations (shared core for CLI + MCP)

- [ ] **FOUND-06**: Plan/import/update preview and execution run through a shared,
  non-interactive service layer that raises typed errors instead of exiting the process or
  prompting on stdin, so CLI behavior is unchanged and a long-running MCP server can call it
- [ ] **FOUND-07**: Run reports record the operation type, source spreadsheet path and
  parameters, and a digest of the parsed row contents; reports written by v1.3.0 still
  resume without false drift
- [ ] **FOUND-08**: User's run reports are written to a stable workspace directory
  (`JIRAMATOR_WORKDIR`, defaulting relative to the config directory) regardless of the
  process working directory
- [ ] **FOUND-09**: Issue-create calls are not automatically retried on ambiguous failures
  (e.g. 502 after Jira accepted the request), and a run lock with a `running` report status
  prevents two concurrent writes against the same run

### Update Run Reports

- [ ] **UPDT-01**: User gets a run report for every `update` run, written incrementally per
  issue with the same atomic/redacted-error semantics as `plan`/`import`
- [ ] **UPDT-02**: User can `update --resume` (and `--resume --force`) a failed/partial run,
  skipping already-applied issues, with drift detection on config + row contents

### Preview Export

- [ ] **ISSUE-05**: User can export a dry-run preview of `plan`, `import`, or `update` as
  Markdown (`--markdown PATH`) for sharing; the same renderer produces MCP preview output

### Duplicate Detection

- [ ] **ISSUE-03**: User sees, in the `plan` and `import` preview, which would-be issues
  already exist in the project (exact summary + issue type + fix version match), and exact
  duplicates are skipped at create time by default (plan reuses a duplicate epic so
  `$epic:` refs still resolve); lookup is paginated and JQL-escaped

### Run Rollback

- [ ] **FOUND-04**: User can roll back a run from its report via the CLI: a preview lists
  only issues that run *created* (never `skipped`/pre-existing ones), flags issues modified
  since creation (skipped unless forced), and on confirmation deletes children before
  epics, treats already-deleted as success, reports permission failures clearly, and
  writes a separate rollback report linked to the original

### MCP Server

- [ ] **MCP-01**: User can install the optional `jiramator[mcp]` extra and register the
  `jiramator-mcp` stdio server in an MCP client; running it without the extra prints a
  one-line install hint and exits non-zero
- [ ] **MCP-02**: User can ask the assistant to list available teams and describe a team's
  epics and ticket templates in plain language (`list_teams`, `describe_team`)
- [ ] **MCP-03**: User can get a read-only preview of a plan, import, or update
  (`preview_plan`, `preview_import`, `preview_update`) returning structured counts,
  duplicates, warnings, Markdown, and a `preview_token` — never writing to Jira
- [ ] **MCP-04**: User can check their setup via a `doctor` tool (config found, credentials
  present, Jira reachable, TLS settings) without any secret being returned
- [ ] **MCP-05**: User can run the server in read-only mode (env var) where no write tool
  is registered
- [ ] **MCP-06**: User can create/apply the previewed operation (`create_plan`,
  `create_import`, `apply_update`) only with a valid `preview_token` that is signed,
  single-use, expires, and is bound to the exact operation, config, row contents, and
  arguments; mismatched/stale/reused tokens are rejected with an actionable message
- [ ] **MCP-07**: Write tools are annotated as destructive so MCP clients request user
  approval, and return counts, created keys, and the run report path — never credentials
  or raw Jira payloads
- [ ] **MCP-08**: User can list recent run reports and resume a failed run through the
  assistant (`list_run_reports`, `resume_run`), with resume gated the same way as writes
- [ ] **MCP-09**: The server never writes non-protocol bytes to stdout and never blocks on
  an interactive prompt during a tool call (enforced by tests, including a stdio
  subprocess smoke test)

### Documentation

- [ ] **DOCS-01**: User can follow README/wiki setup docs to register `jiramator-mcp` in
  Copilot (CLI/VS Code) and Claude Desktop on Windows and macOS, including absolute
  executable paths, credential env vars kept out of committed files, and
  `JIRAMATOR_CA_BUNDLE`/`JIRAMATOR_RELAX_TLS_STRICT` passthrough

## Future Requirements

Deferred. Tracked but not in the v1.1 roadmap.

- **MCP-10**: Rollback exposed as MCP tools (`preview_rollback`/`rollback_run`)
- **FOUND-10**: "Soft" rollback (transition + label) for users without Delete permission
- **UPDT-03**: Update reports record prior field values, enabling before→after preview and
  update revert
- **MCP-11**: HTTP/streamable transport for a shared, hosted server
- **MCP-12**: Elicitation-based in-chat confirmation, once client support is reliable
- **CONF-02**: User can diff two team configs to see what changed between PIs
- **ISSUE-02**: User can create sub-tasks linked to parent stories
- **ISSUE-04**: User can run plan for multiple teams in one command
- **IMPT-02**: User can filter rows based on conditions during import
- **IMPT-03**: User can import from multi-sheet Excel files

## Out of Scope

| Feature | Reason |
|---------|--------|
| Hosted/multi-tenant MCP server | v1.1 is local stdio per user; revisit after real usage (MCP-11) |
| Rollback over MCP | Jira Cloud deletes are irreversible; keep the most destructive op behind the CLI for v1.1 (MCP-10) |
| `--force` over MCP | Drift override stays a deliberate CLI action |
| Credentials as tool arguments | Credentials only via env vars in the client config, never in chat |
| PyInstaller binary | Unchanged from v1.0 — no evidence target machines can run unsigned binaries |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-06 | Phase 4 | Pending |
| FOUND-07 | Phase 4 | Pending |
| FOUND-08 | Phase 4 | Pending |
| FOUND-09 | Phase 4 | Pending |
| UPDT-01 | Phase 4 | Pending |
| UPDT-02 | Phase 4 | Pending |
| ISSUE-05 | Phase 5 | Pending |
| ISSUE-03 | Phase 5 | Pending |
| FOUND-04 | Phase 6 | Pending |
| MCP-01 | Phase 7 | Pending |
| MCP-02 | Phase 7 | Pending |
| MCP-03 | Phase 7 | Pending |
| MCP-04 | Phase 7 | Pending |
| MCP-05 | Phase 7 | Pending |
| MCP-09 | Phase 7 | Pending |
| MCP-06 | Phase 8 | Pending |
| MCP-07 | Phase 8 | Pending |
| MCP-08 | Phase 8 | Pending |
| DOCS-01 | Phase 8 | Pending |

**Coverage:**
- v1.1 requirements: 19 total
- Mapped to phases: 19 ✓
- Unmapped: 0

---
*Requirements defined: 2026-10-16*
*Last updated: 2026-10-16 after v1.1 roadmap creation (Phases 4-8)*
