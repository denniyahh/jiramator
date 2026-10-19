# Roadmap: Jiramator

## Milestones

- ✅ **v1.0 Feature Extensions** — Phases 1-3 (shipped 2026-10-16) — [archive](milestones/v1.0-ROADMAP.md)
- 🚧 **v1.1 MCP Server** — Phases 4-8 (in progress)

## Phases

<details>
<summary>✅ v1.0 Feature Extensions (Phases 1-3) — SHIPPED 2026-10-16</summary>

- [x] Phase 1: Reliability & Robustness (5/5 plans) — completed 2026-04-30
- [x] Phase 2: Template Inheritance & Sprint Assignment (3/3 plans) — completed 2026-04-30
- [x] Phase 3: Accessibility (pivoted from MCP) — delivered outside GSD plans as `jiramator init` wizard (v1.1.0) + non-interactive `plan` (v1.0.1); MCP (INTG-01/03) declined — completed 2026-07-10

</details>

### 🚧 v1.1 MCP Server (In Progress)

**Milestone Goal:** Let users drive Jiramator's `plan`/`import`/`update` from an MCP-aware
AI assistant (Copilot, Claude) in plain English, without losing the preview-before-write
guarantee.

- [ ] **Phase 4: Shared Core & Update Run Reports** - Non-interactive service layer, extended/anchored run reports, safe create retries + run lock, and `update --resume`
- [ ] **Phase 5: Markdown Preview & Duplicate Detection** - Shareable Markdown dry-run export and exact-duplicate detection/skip for `plan` and `import`
- [ ] **Phase 6: Run Rollback (CLI)** - Undo the issues a `plan`/`import` run created, safely and with a rollback report
- [ ] **Phase 7: MCP Server — Read-Only** - Installable `jiramator-mcp` stdio server with discovery, `doctor`, and `preview_*` tools that never write to Jira
- [ ] **Phase 8: MCP Server — Token-Gated Writes & Setup Docs** - Preview-token-gated create/apply/resume tools plus client registration docs

## Phase Details

### Phase 4: Shared Core & Update Run Reports
**Goal**: `plan`/`import`/`update` run through one non-interactive, typed-error core with trustworthy run reports, and `update` runs become recordable and resumable like `plan`/`import`
**Depends on**: Nothing (first phase of v1.1; builds on v1.0 run-report substrate)
**Requirements**: FOUND-06, FOUND-07, FOUND-08, FOUND-09, UPDT-01, UPDT-02
**Success Criteria** (what must be TRUE):
  1. Existing CLI `plan`/`import`/`update` invocations (including `--dry-run`, `--resume`, `--force`) behave exactly as in v1.3.0 — same output, same exit codes, full existing test suite green — while the same operations can be called programmatically with no stdin prompt or process exit (typed errors instead)
  2. Run reports land in the same workspace directory (`JIRAMATOR_WORKDIR`, defaulting relative to the config directory) no matter which directory the user runs from, and record operation type, source spreadsheet path/parameters, and a row-contents digest; a report written by v1.3.0 still resumes without a false drift error
  3. Editing a source spreadsheet's rows after a partial `import`/`update` run causes `--resume` to report drift (overridable with `--force`); re-saving the file without content changes does not
  4. Every `update` run writes a report incrementally per issue; after a mid-run failure, `update --resume` skips already-applied issues and applies only the rest
  5. A create that fails ambiguously (e.g. proxy 502 after Jira accepted it) is not silently retried into a duplicate, and starting a second write against a run that is still `running` is refused with a clear message
**Plans**: TBD

### Phase 5: Markdown Preview & Duplicate Detection
**Goal**: Users can share a readable Markdown dry-run of any operation, and `plan`/`import` previews show — and creation skips — issues that already exist in Jira
**Depends on**: Phase 4
**Requirements**: ISSUE-05, ISSUE-03
**Success Criteria** (what must be TRUE):
  1. User can run `plan`, `import`, or `update` with `--dry-run --markdown PATH` and get a UTF-8 Markdown file (still seeing the normal terminal preview) that renders correctly even when summaries contain Markdown/pipe/special characters
  2. `plan` and `import` previews list which would-be issues already exist in the project (exact summary + issue type + fix version match), including matches beyond the first page of search results and summaries containing JQL-reserved characters; offline dry-runs say duplicates were not checked rather than implying none exist
  3. On a live run, exact duplicates are skipped by default and recorded as skipped (with the existing key) in the run report; `plan` reuses an existing duplicate epic so `$epic:` references in tickets still link to it
  4. Recurring plan tickets whose summaries differ only by PI/version are not falsely flagged as duplicates, and the user can opt out of skipping when they intentionally want duplicates
  5. The duplicates section appears in the Markdown export
**Plans**: TBD

### Phase 6: Run Rollback (CLI)
**Goal**: Users can safely undo the issues a `plan` or `import` run created, from its run report, via the CLI only
**Depends on**: Phase 5 (needs clean `created` vs `skipped`/duplicate records and the `operation` report field from Phase 4)
**Requirements**: FOUND-04
**Success Criteria** (what must be TRUE):
  1. `jiramator rollback <report>` (or `--latest`) shows a preview by default listing only issues that run created — never skipped/pre-existing duplicates — and deletes nothing without confirmation
  2. Issues modified since creation (edits, comments, worklogs, new children) are flagged and left alone unless the user explicitly forces their inclusion
  3. On confirmation, children are deleted before their epics, already-deleted issues count as success, and missing Delete permission produces a clear, actionable message instead of a stack trace
  4. A separate rollback report linked to the original is written, the original report is unchanged, and rollback refuses `update`/rollback reports
**Plans**: TBD

### Phase 7: MCP Server — Read-Only
**Goal**: Users can install and register `jiramator-mcp` and, in plain English, explore teams, check their setup, and preview any plan/import/update — with zero ability to write to Jira
**Depends on**: Phase 5 (preview output reuses the Markdown renderer and duplicate detection)
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04, MCP-05, MCP-09
**Success Criteria** (what must be TRUE):
  1. After installing `jiramator[mcp]`, user can register `jiramator-mcp` in an MCP client and see its tools; running `jiramator-mcp` without the extra prints a one-line install hint and exits non-zero, and the base CLI install is unaffected
  2. User can ask the assistant "what teams do I have?" and "what does team X's PI plan create?" and get answers from `list_teams`/`describe_team`
  3. User can ask for a preview of a plan, import, or update and receives counts, duplicates, warnings, Markdown, and a `preview_token` — and nothing is written to Jira
  4. User can run the `doctor` tool to see whether config, credentials, Jira reachability, and TLS settings are OK, without any secret appearing in the response
  5. With read-only mode enabled via env var, no write tool is offered; and a stdio subprocess smoke test proves the server never emits non-protocol stdout bytes or blocks on a prompt during any tool call
**Plans**: TBD

### Phase 8: MCP Server — Token-Gated Writes & Setup Docs
**Goal**: Users can have the assistant create/apply exactly what they previewed — and resume failed runs — only after an explicit preview, and can follow docs to set it all up on Windows/macOS
**Depends on**: Phase 7 (token issuance, read side); Phase 4 (update reports for `resume_run` parity); Phase 5 (duplicate detection for retry safety)
**Requirements**: MCP-06, MCP-07, MCP-08, DOCS-01
**Success Criteria** (what must be TRUE):
  1. User can have the assistant run `create_plan`/`create_import`/`apply_update` only with a valid `preview_token`; a token that is expired, reused, forged, or whose config, rows, or arguments changed since preview is rejected with "preview is stale — preview again"-style guidance
  2. MCP clients prompt the user for approval before any write tool runs (destructive annotation), and write results show counts, created keys, and the run report path — never credentials or raw Jira payloads
  3. User can ask the assistant to list recent run reports and resume a failed run, gated by the same token mechanism; there is no `--force` or rollback over MCP
  4. A user following the README/wiki can register `jiramator-mcp` in Copilot (CLI/VS Code) and Claude Desktop on Windows and macOS using absolute executable paths, credential env vars kept out of committed files, and `JIRAMATOR_CA_BUNDLE`/`JIRAMATOR_RELAX_TLS_STRICT` passthrough
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Reliability & Robustness | v1.0 | 5/5 | Complete | 2026-04-30 |
| 2. Template Inheritance & Sprint Assignment | v1.0 | 3/3 | Complete | 2026-04-30 |
| 3. Accessibility (pivoted from MCP) | v1.0 | n/a | Complete | 2026-07-10 |
| 4. Shared Core & Update Run Reports | v1.1 | 0/TBD | Not started | - |
| 5. Markdown Preview & Duplicate Detection | v1.1 | 0/TBD | Not started | - |
| 6. Run Rollback (CLI) | v1.1 | 0/TBD | Not started | - |
| 7. MCP Server — Read-Only | v1.1 | 0/TBD | Not started | - |
| 8. MCP Server — Token-Gated Writes & Setup Docs | v1.1 | 0/TBD | Not started | - |

---
*Updated: 2026-10-16 — v1.1 MCP Server roadmap created (Phases 4-8, 19/19 requirements mapped); v1.0 detail in `milestones/v1.0-ROADMAP.md`*
