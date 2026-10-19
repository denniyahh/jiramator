# Feature Research — v1.1 "MCP Server"

**Domain:** Local stdio MCP server + safety features (rollback, duplicate detection, preview export, `update` resume) for a preview-first bulk-Jira CLI
**Researched:** 2026-10-16
**Confidence:** MEDIUM overall
- **HIGH:** claims about jiramator's current code. I read these directly: `run_report.py`, `jira_client.py`, `planner.py`, `importer.py`, `updater.py`.
- **MEDIUM:** MCP protocol facts. These are quoted from the official spec repo (2025-06-18 tools and elicitation pages, the `draft` schema, and the 2026-07-28 changelog). The research seam rates raw web fetches LOW. I raised them to MEDIUM because they come straight from the official spec text.
- **LOW:** how individual MCP clients (VS Code Copilot, Claude Desktop, Claude Code) handle annotations and elicitation. I inferred this and did not test it. Treat it as LOW until checked in a spike.

**Scope note:** This file covers only the NEW v1.1 features. The v1.0 feature landscape is archived in `.planning/milestones/v1.0-research/FEATURES.md`.

---

## 0. What the code already has (dependency baseline, HIGH)

| Existing asset | Where | Relevance to v1.1 |
|---|---|---|
| `RunReport` / `IssueResult` (`template_key`, `kind`, `status`, `jira_key`, `fields`) | `run_report.py` | Rollback reads its targets from here. `update` reports reuse the schema (`IssueKind` already contains `"updated"` and `IssueStatus` already contains `"updated"`). |
| `compute_resolved_hash(org, team, pi_label, versions)` | `run_report.py:421` | The planned basis for `preview_token`. **Gap: it hashes config only, not spreadsheet rows.** For import/update it cannot detect a spreadsheet edited between preview and create. |
| `find_resumable`, `write_report_atomic`, `ConfigDriftError`, redaction helpers | `run_report.py` | Can be reused directly for `update --resume` and `list_run_reports`. |
| `JiraClient.find_issue_keys_by_summaries` (exact-summary JQL lookup) | `jira_client.py:250` | Import already de-duplicates on exact summary (`importer.py:426`). **`plan` does not**: it prints "This script does NOT check for duplicates" (`planner.py:1019`). |
| `PlanInputs`, `make_plan_inputs`, promptless plan | `planner.py` | Already shipped. MCP `preview_plan`/`create_plan` fill `PlanInputs` from tool arguments. |
| `render_preview_report` (import), `render_update_preview_report` (update) | importer/updater | These return plain text. **Plan preview is not a data structure.** It is printed directly as Rich tables inside `_display_preview` (`planner.py:428`). |
| `UpdatePreviewReport` / `RowUpdateResult` | `updater.py` | Shows the *new* payload only. It does not fetch the issue's current values, so there is no before→after diff today. |
| No `delete_issue` on `JiraClient` | — | Rollback needs a new client method and a permission preflight. |

---

## 1. MCP server (`jiramator-mcp`)

### What well-regarded write-capable MCP servers do

| Practice | GitHub MCP server | `sooperset/mcp-atlassian` (most widely used Jira MCP) | Implication for jiramator |
|---|---|---|---|
| Granular tools, one per operation | Yes, grouped into "toolsets" | ~98 tools in groups (`jira_issues`, `jira_projects`, …) | jiramator's coarse workflow tools (preview/create pairs) are a *differentiator*. They fit a narrow, safe workflow better than a raw CRUD surface. Keep the tool count around 10. |
| Read-only mode flag | `--read-only` (it wins even if write tools are named explicitly) | `READ_ONLY_MODE=true` | **Table stakes.** Ship `JIRAMATOR_MCP_READ_ONLY=1` (or `--read-only`). This also gives users a "Phase 1 only" deployment. |
| Tool allow-listing | `--toolsets`, `--tools` | `ENABLED_TOOLS`, `TOOLSETS` | Nice-to-have. A read-only flag covers about 90% of the need. |
| Credentials in the server `env` block, never in tool arguments | Yes | Yes (`JIRA_URL`/`JIRA_USERNAME`/`JIRA_API_TOKEN` in `env`) | Already planned in the proposal (§7). |
| Bulk create as a single tool | n/a | `jira_batch_create_issues` (no preview step) | A token-gated preview → create flow is stronger than anything comparable I found. **Core differentiator.** |
| Deletion exposed | n/a | `jira_delete_issue` (plain tool) | Supports exposing rollback, but only behind the same gate (see §3). |

### MCP protocol features relevant here

- **Tool annotations** (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`, `title`):
  - Defaults are pessimistic (`readOnlyHint` defaults to false).
  - The spec says clients **must treat annotations as untrusted** unless the server is trusted.
  - The spec says there **SHOULD** be a human in the loop who can deny tool invocations.
  - So annotations help the client decide when to ask for confirmation, but they are not a security control.
- **`structuredContent` + `outputSchema`:** results can carry typed JSON next to text `content`.
  - Best practice is to return both: a short human/LLM-readable text summary (the Markdown preview) and structured counts, the token, and the report path.
  - The 2026-07-28 spec allows `structuredContent` to be any JSON value and the schemas to use JSON Schema 2020-12.
- **Tool errors:** return `isError: true` with an actionable message, not a protocol error. The LLM can read it and recover (for example "token stale — call preview_import again").
- **Elicitation:**
  - The server can ask the user directly for a flat form of primitive fields; the user can accept, decline, or cancel.
  - Servers **MUST NOT** use it to request sensitive information.
  - In the 2026-07-28 spec, elicitation moved to the Multi Round-Trip Request pattern (`resultType: "input_required"`).
  - Client support is uneven (LOW confidence on which clients support it).
  - **Conclusion:** use elicitation only as an optional enhancement. Never make it the only confirmation path.
- **Cross-call state:** the 2026-07-28 spec removes protocol sessions and says servers needing state should use "explicit, server-minted handles passed as ordinary tool arguments." That is exactly the `preview_token` pattern, so the design matches where the spec is heading.
- **Deprecated (2026-07-28):** Roots, Sampling, Logging. Do not use Roots to find the configs directory. Use `JIRAMATOR_CONFIG_DIR` / a tool argument as the proposal already says, and log to stderr.

### Table stakes

| Feature | Why expected | Complexity | Notes / dependencies |
|---|---|---|---|
| stdio transport, `jiramator-mcp` entry point, `[mcp]` extra | Standard for local servers; Copilot and Claude Desktop/Code expect it | LOW | Nothing may write to **stdout** except the protocol. Rich console output must be routed to stderr or suppressed. `planner` currently prints through a `Console`, so a silent or stderr console has to be injected. |
| Read tools: `list_teams`, `describe_team`, `preview_plan`, `preview_import`, `preview_update`, `list_run_reports` | Users explore before acting; discovery replaces CLI knowledge | MEDIUM | `describe_team` is new summarizing code. `preview_plan` needs a **data** preview (see §5) instead of Rich tables. |
| Write tools: `create_plan`, `create_import`, `apply_update`, `resume_run` | The point of the milestone | MEDIUM | Thin wrappers over `run_plan`, `run_import`, `run_update` and the resume logic. `resume_run` needs `update` reports first (§2). |
| **Annotations on every tool:** reads get `readOnlyHint: true`; writes get `readOnlyHint: false`, `destructiveHint` (true for rollback/update, false for create, which only adds), `openWorldHint: true` | Lets clients decide whether to ask for confirmation; reviewers expect them | LOW | They are hints only. Do not rely on them for safety. |
| **`preview_token` gate** | Structurally forces preview-before-write; the proposal's core idea | MEDIUM | The token must bind to **everything that determines the write**: resolved config hash + PI/versions + **a hash of the normalized spreadsheet rows** (import/update) + team/project + operation kind. `compute_resolved_hash` alone is not enough. A stale or mismatched token returns `isError` with "re-run preview". |
| Text + structured results | The LLM needs a readable summary; the client and tests need typed fields | LOW–MEDIUM | Text = Markdown preview (shared with §5). Structured = `{project_key, counts, warnings, preview_token, sample, report_path, status}`. |
| Actionable `isError` results | Missing creds, unknown team, drift, Jira 4xx: the LLM must relay a fix to the user | LOW | Reuse `error_format.py` and the redaction helpers. **Never echo the token, email, or raw Jira payloads.** |
| Read-only mode (`JIRAMATOR_MCP_READ_ONLY`) | Both reference servers ship one; lets cautious orgs adopt the read side only | LOW | Write tools are simply not registered. |
| File-path inputs for spreadsheets | Passing a sheet through chat is awkward and lossy | LOW | Resolve relative to a configured base dir. Reject paths outside allowed dirs (see anti-features). |
| Bounded output size | Big previews flood context and cost tokens | LOW | Return a sample (first N per category) plus counts. The full Markdown goes to a file path the user can open. |
| Setup docs: VS Code/Copilot `mcp.json`, Claude Desktop, Claude Code `claude mcp add` | Non-programmer audience; registration is the new on-ramp barrier | LOW | Include Windows paths, the pipx-installed `jiramator-mcp` absolute path, the `env` block, a "verify it's connected" step, and read-only mode. |

### Differentiators

| Feature | Value proposition | Complexity | Notes |
|---|---|---|---|
| Token is **short-lived and single-use** (e.g. 15–30 min TTL, consumed on a successful write) | Stops an LLM reusing an old preview hours later, or double-firing a create | LOW | Server-side in-memory map `token → (fingerprint, expiry, op)`. The stdio server is per-user and per-process, so memory is enough. |
| Optional elicitation confirm on write tools ("Create 19 issues in CA? [Confirm]") when the client supports it | A real human-in-the-loop gate, independent of what the LLM claims | MEDIUM | Detect client capability and fall back to token-only. **The token proves a preview ran. It does not prove the user saw it.** Elicitation or the client's own confirmation closes that gap. |
| `preview_*` output contains a ready-to-paste Markdown summary | The assistant can show it verbatim, which reduces LLM mis-paraphrase (the proposal's top risk) | LOW (given §5) | Shared renderer. |
| `describe_team` in plain language ("2 epics, 6 per-release templates, 3 per-sprint; sprint length 2 weeks…") | Lets a PO check they picked the right team without reading YAML | LOW–MEDIUM | |
| Duplicate and rollback information surfaced inside previews ("3 of 19 already exist → will skip") | Makes the safety features visible in chat | LOW (given §4) | |
| MCP **prompts** (e.g. `plan_pi` prompt template) | One-click guided workflow in clients that surface prompts | LOW | Optional, cheap, low risk. |

### Anti-features

| Feature | Why requested | Why problematic | Alternative |
|---|---|---|---|
| Generic `jira_create_issue` / `jira_search` / raw JQL tools | "Make it a full Jira MCP" | Duplicates mcp-atlassian, breaks the "MCP layer has no Jira knowledge" rule, and bypasses previews | Point users to mcp-atlassian for ad-hoc Jira and keep jiramator to workflow tools |
| Single tool with `dry_run: bool` | Fewer tools | The LLM can flip the flag; annotations can't separate safe from unsafe calls | Separate preview/write tools (already decided) |
| Credentials or tokens as tool arguments, or requested via elicitation | "Easier setup in chat" | Leaks into transcripts; the spec forbids sensitive elicitation | `env` block only; the error message tells the user how to set it |
| Config/YAML editing tools | "Let the AI fix my template" | Silent config drift, hard-to-review YAML diffs, invalidates tokens | Out of scope. Point to `jiramator init` and config validation errors |
| Arbitrary file paths (read anywhere / write reports anywhere) | Flexibility | Path traversal; prompt-injected content could make the server read sensitive files | Allow-listed base dirs (config dir, CWD, an explicit `JIRAMATOR_DATA_DIR`) |
| `force: true` drift override exposed over MCP | CLI parity with `--force` | The LLM will "helpfully" force past drift | Keep `--force` CLI-only. MCP tells the user to re-preview |
| HTTP/SSE shared server | Company-wide rollout | Already out of scope; needs multi-user auth | Deferred |
| Relying on Roots/Sampling/Logging | Common in older tutorials | Deprecated in spec 2026-07-28 | Env/tool arguments, stderr logging |

---

## 2. Run reports + `--resume` for `update`

| Category | Feature | Complexity | Notes |
|---|---|---|---|
| Table stakes | `update` writes a `RunReport` (`kind="updated"`, `status` updated/skipped/failed, `jira_key`, `fields` changed) atomically after each row | LOW–MEDIUM | Same `_persist`/`_record` pattern as `run_import`. `IssueKind`/`IssueStatus` already include `"updated"`, so no schema bump is needed. |
| Table stakes | `--resume` skips rows already `updated` and retries `failed`/`pending`; drift check uses a hash of config **plus spreadsheet rows** | MEDIUM | Import keys rows by `row_number`+summary (`_row_template_key`); update should key by **issue key** (unique, already validated by `validate_unique_issue_keys`). |
| Table stakes | `list_run_reports` covers all three commands with command, team, time, status, counts | LOW | Reads `.jiramator/runs/`; skip corrupt files like `find_resumable` does. |
| Differentiator | Record **prior field values** in the update report (fetched before writing) | MEDIUM | Makes update "rollback" (revert) possible later, plus a before→after diff in `preview_update`. Costs one GET per issue, or a batched JQL search with `fields`. Recommend capturing them now even if revert is deferred. |
| Anti-feature | Re-applying already-applied updates on resume "to be safe" | — | Updates are mostly idempotent, but they can overwrite edits made after the run. Skip completed rows. |

---

## 3. Run rollback (FOUND-04)

**Jira facts (MEDIUM, from Jira Cloud REST knowledge; verify in the phase):**
- `DELETE /rest/api/3/issue/{key}` needs the **Delete issues** project permission, which many orgs only give to admins.
- It fails if the issue has subtasks unless `deleteSubtasks=true`.
- Jira Cloud has **no recycle bin for issues**: deletion is permanent.
- Deleting an epic orphans its children (they are not deleted).

| Category | Feature | Complexity | Notes / dependencies |
|---|---|---|---|
| Table stakes | `jiramator rollback <report>` (and `--latest`) targets **only** `status=="created"` issues from that report. Pre-existing epics and skipped duplicates are never touched | MEDIUM | Depends on FOUND-02 reports (exist). `IssueResult.status/jira_key` is all that's needed. |
| Table stakes | Preview first (dry-run by default or explicit confirm): list keys + summaries + count, then the user types the count or `--yes` | LOW | Same preview-first contract as the rest of jiramator. |
| Table stakes | Safety check before deleting: fetch each issue and **skip, with a warning, any issue modified since the run** (`updated` > report `ended_at`), unless `--include-modified` | MEDIUM | Prevents deleting tickets the team has already started using. This is the main trust feature. |
| Table stakes | Delete children before parents: per-sprint/per-release tickets first, epics last; refuse to delete an epic that still has children not created by this run | MEDIUM | Order by `IssueResult.kind`. |
| Table stakes | Permission check: on the first 403, stop and explain "you need the Delete issues permission — ask a Jira admin" instead of 50 identical failures | LOW | |
| Table stakes | Rollback writes its own report (deleted/skipped/failed) and marks the original report as rolled back; rerunning is idempotent (404 = already gone = success) | LOW–MEDIUM | Avoid a schema bump if possible: add an optional field omitted when None, the same trick as `error`. |
| Differentiator | **Soft rollback** mode: transition to a closed/"Won't Do" status and/or add a `jiramator-rolled-back` label instead of deleting | MEDIUM | Works without Delete permission and can be reversed. Status names vary by workflow, so it needs config (`rollback.transition: "Won't Do"`). Strong fit for non-admin POs. |
| Differentiator | Remove fix versions that the run created (planner `_check_and_create_fix_versions`) if no other issues use them | MEDIUM | Needs the run to record versions it created (not recorded today). Defer unless cheap. |
| Differentiator | MCP `preview_rollback` → `rollback_run` (token-gated, `destructiveHint: true`) | LOW (given core) | Highest-risk tool on the server. Consider leaving it **off by default** over MCP (opt in with an env flag). |
| Anti-feature | "Undo" for `update` runs in this milestone | — | Needs prior values (§2 differentiator) plus conflict handling for later edits. Capture the data now and build revert later. |
| Anti-feature | Rollback by JQL/label ("delete everything labeled PI-29") | — | Can reach issues jiramator never created. Always use run-report keys. |
| Anti-feature | Auto-rollback on partial failure | — | Surprises users and destroys the resume path. Resume is the recovery path; rollback is an explicit choice. |

---

## 4. Duplicate detection before create (ISSUE-03)

Current state: import does exact-summary matching per project (skips and records `skipped`). Plan does **nothing** and warns. Resume only protects against duplicates *within* a report lineage.

| Category | Feature | Complexity | Notes / dependencies |
|---|---|---|---|
| Table stakes | **Plan** queries existing issues before create and marks would-be duplicates in the preview ("3 already exist: CA-101…") | MEDIUM | Reuse `find_issue_keys_by_summaries`. Must work during `--dry-run` when Jira is reachable and degrade gracefully when it isn't (project constraint). |
| Table stakes | Match key = project + exact (trimmed) summary + issue type; optionally scoped by fix version for per-release tickets | MEDIUM | Plan summaries are template-interpolated (PI/version/sprint included), so exact match is reliable. Summary alone can false-positive across issue types. |
| Table stakes | Duplicates default to **skip**, recorded as `skipped` with `jira_key` (so `$epic:` refs can bind to the existing epic) | MEDIUM | Re-binding an existing epic key into `epic_keys` lets children link correctly instead of failing. |
| Table stakes | Override: `--allow-duplicates` (CLI) / `on_duplicate: "skip"\|"create"` | LOW | |
| Table stakes | **Fix the lookup's pagination and robustness:** today `maxResults=len(unique_summaries)` with `summary ~` (text search) can return fuzzy matches that use up the page, so exact matches get dropped; OR-chains of hundreds of clauses can exceed JQL length limits | MEDIUM | Batch summaries (e.g. 50 per query), paginate with `nextPageToken` on `/search/jql`, then exact-filter client-side. Bug-class finding (HIGH, from code reading). |
| Differentiator | Duplicate check **within the input** (two rows or templates rendering the same summary) | LOW | Cheap and catches template mistakes. |
| Differentiator | Show duplicates as a separate section in the Markdown/MCP preview, with counts in the structured result | LOW | Depends on §5. |
| Anti-feature | Fuzzy/semantic similarity matching | — | False positives silently skip real work. Non-programmers can't debug similarity thresholds. |
| Anti-feature | Updating the found duplicate ("upsert") | — | Merges create and update semantics and surprises users. `update` exists for that. |
| Anti-feature | Project-wide scans without a summary filter | — | Slow on big projects and rate-limit risk. |

---

## 5. Markdown preview export (ISSUE-05)

| Category | Feature | Complexity | Notes / dependencies |
|---|---|---|---|
| Table stakes | **One shared renderer**: `preview model → Markdown`, used by CLI `--dry-run --export-md <path>` and MCP `preview_*` text content | MEDIUM | **Requires extracting a plan preview data model** out of `_display_preview` (Rich-only today). Import/update already have dataclasses (`PreviewReport`, `UpdatePreviewReport`). This refactor is the real cost and blocks the MCP preview tools, so schedule it first. |
| Table stakes | Content: header (team, project, PI, versions, generated-at, jiramator version), counts, GFM tables per category (epics / per-release / per-sprint, or rows), warnings, duplicates, failed rows with reasons | LOW–MEDIUM | GitHub-Flavored Markdown tables render in Confluence (paste/markdown macro), Slack (partially), Teams, and GitHub. |
| Table stakes | Escape pipes and newlines in cell values, truncate long descriptions | LOW | Cells containing `|` break tables. Common bug. |
| Table stakes | No secrets and no raw payloads/ADF JSON in the export; show summaries and key fields only | LOW | Reuse the redaction helpers. |
| Table stakes | Deterministic output (stable ordering) | LOW | Allows snapshot tests and diffing two previews. |
| Differentiator | Update preview with **before → after** per field | MEDIUM | Depends on fetching current values (§2 differentiator). Very valuable for stakeholder review of bulk edits. |
| Differentiator | `--export-md -` to stdout (pipe to clipboard) | LOW | |
| Differentiator | Execution/rollback reports also exportable as Markdown ("what was created": keys linked to the Jira browse URL) | LOW | Same renderer family. Ideal for posting to the team after PI planning. |
| Anti-feature | HTML/PDF/XLSX export in this milestone | — | ISSUE-05 mentions HTML, but Markdown covers the sharing need. Each extra format is new test surface. Defer HTML. |
| Anti-feature | Publishing straight to Confluence/Slack | — | New credentials, permissions, and APIs. The user pastes it. |
| Anti-feature | Re-implementing Rich tables and Markdown separately | — | They will drift. Keep one model and two thin renderers. |

---

## 6. MCP client setup docs

| Category | Feature | Complexity | Notes |
|---|---|---|---|
| Table stakes | Copy-paste configs for VS Code Copilot (`.vscode/mcp.json` / user settings, `servers` key), Claude Desktop (`claude_desktop_config.json`, `mcpServers` key), Claude Code (`claude mcp add jiramator -- jiramator-mcp` with `-e` env) | LOW | The key names differ between clients (`servers` vs `mcpServers`). This is a frequent setup failure; call it out. (LOW confidence on exact current schemas: verify against each client's docs during the phase.) |
| Table stakes | Install: `pipx install "jiramator[mcp] @ git+…"` or `pipx inject`; how to find the absolute path to `jiramator-mcp` on Windows/macOS | LOW | GUI clients often don't inherit the shell PATH, so use an absolute path. |
| Table stakes | Credentials: `env` block vs. relying on the OS env; a warning not to commit `mcp.json` containing tokens; VS Code `inputs` / prompted secrets where supported | LOW | |
| Table stakes | "First conversation" walkthrough + troubleshooting (server not listed, stdout pollution, creds missing, Windows paths, corporate CA bundle env vars `JIRAMATOR_CA_BUNDLE`) | LOW | |
| Differentiator | `jiramator mcp-config --client vscode\|claude-desktop\|claude-code` prints a ready snippet with resolved absolute paths | LOW–MEDIUM | Removes the hardest setup step for non-programmers. Pairs well with the `init` wizard. |
| Differentiator | `jiramator-mcp --self-test` (loads configs, checks creds, lists tools, exits) | LOW | Lets users debug outside the client. |

---

## Feature Dependencies

```
Plan preview data model (extract from Rich _display_preview)
    └──required-by──> Shared Markdown renderer (ISSUE-05)
                          └──required-by──> MCP preview_* text output
    └──required-by──> MCP preview_plan structured output

Preview fingerprint (config hash + normalized rows + op + inputs)
    └──required-by──> preview_token gate ──required-by──> create_plan / create_import / apply_update
    └──required-by──> update --resume drift check

update run reports (+ issue-key template keys)
    └──required-by──> update --resume ──required-by──> MCP resume_run (all 3 commands)
    └──required-by──> list_run_reports (complete coverage)
    └──enhanced-by──> prior-value capture ──enables──> before→after preview diff, future update revert

Run reports (exist) ──required-by──> Rollback (FOUND-04) ──optional──> MCP rollback tools (opt-in)
JiraClient.delete_issue / get_issue(updated) ──required-by──> Rollback

find_issue_keys_by_summaries (exists; needs batching/pagination fix)
    └──required-by──> Plan duplicate detection (ISSUE-03)
                          └──enhances──> previews (duplicates section), resume safety, rollback (skipped ≠ created)

MCP stdio server skeleton (stdout-clean console injection, read-only mode)
    └──required-by──> all MCP tools

Elicitation confirm ──enhances──> write tools (optional; never sole gate)
--force over MCP ──conflicts──> preview_token drift guarantee
Auto-rollback-on-failure ──conflicts──> resume
```

### Dependency notes
- **Markdown renderer before MCP preview tools:** the MCP text result *is* the Markdown preview. Building the MCP tools first would create a third rendering path.
- **The fingerprint must cover spreadsheet rows:** `compute_resolved_hash` takes only (org, team, pi, versions). Without a rows hash, `create_import` would accept a token from a preview of a *different* version of the file.
- **Duplicate detection before rollback:** rollback must tell "created by this run" apart from "already existed". Correct `skipped` records from duplicate detection prevent rollback from deleting pre-existing issues.
- **`update` reports before `resume_run`:** otherwise `resume_run` only covers 2 of 3 commands.

---

## MVP Definition (v1.1)

### Launch with
- [ ] Plan preview data model + shared Markdown renderer + `--export-md`: unblocks MCP previews; ISSUE-05
- [ ] MCP read-only server (stdio, annotations, read-only mode, structured + text results, stdout-clean)
- [ ] Preview fingerprint (config + rows) + single-use, TTL'd `preview_token`; write tools
- [ ] `update` run reports + `--resume`; `list_run_reports` / `resume_run` across all three commands
- [ ] Plan duplicate detection (exact match, skip-by-default, epic re-binding) + batched/paginated lookup fix
- [ ] Rollback CLI: created-only, preview/confirm, skip-modified, child-before-parent, permission-aware, idempotent
- [ ] Setup docs for VS Code Copilot / Claude Desktop / Claude Code

### Add after validation (v1.1.x)
- [ ] Elicitation confirm on write tools: once a target client is shown to support it
- [ ] Soft rollback (transition/label): when users report missing Delete permission
- [ ] MCP rollback tools (opt-in): after the CLI rollback has proven safe
- [ ] `jiramator mcp-config` snippet generator, `--self-test`
- [ ] Before→after diff in update previews (capture prior values in reports now)

### Future
- [ ] Update revert, HTML export, fix-version cleanup on rollback, HTTP transport

## Feature Prioritization Matrix

| Feature | User value | Cost | Priority |
|---|---|---|---|
| Plan preview model + Markdown renderer | HIGH | MEDIUM | P1 |
| MCP read tools + read-only mode | HIGH | MEDIUM | P1 |
| preview_token (rows-aware, single-use) + write tools | HIGH | MEDIUM | P1 |
| update reports + resume | MEDIUM | LOW–MEDIUM | P1 |
| Plan duplicate detection + lookup fix | HIGH | MEDIUM | P1 |
| Rollback (hard delete, guarded) | MEDIUM | MEDIUM | P1 |
| Setup docs | HIGH | LOW | P1 |
| Prior-value capture in update reports | MEDIUM | LOW–MEDIUM | P2 |
| Elicitation confirm | MEDIUM | MEDIUM | P2 |
| Soft rollback | MEDIUM | MEDIUM | P2 |
| MCP rollback tools | LOW | LOW | P3 |
| mcp-config generator / self-test | MEDIUM | LOW | P2 |
| HTML export, update revert | LOW | MEDIUM–HIGH | P3 |

## Competitor Feature Analysis

| Feature | GitHub MCP server | mcp-atlassian | jiramator approach |
|---|---|---|---|
| Write safety | `--read-only`; per-tool annotations; client confirmation | `READ_ONLY_MODE`, `ENABLED_TOOLS`; no preview step | Read-only mode + mandatory preview_token + annotations + optional elicitation |
| Bulk create | n/a | `jira_batch_create_issues` (no dedup, no report) | Template/sheet-driven, dedup, run report, resume, rollback |
| Delete | n/a | `jira_delete_issue` | Only via run-report-scoped rollback |
| Tool surface | Many granular tools, toolsets | ~98 tools, toolsets | ~10 workflow tools; read-only toggle |
| Prompt-injection posture | "Lockdown mode" filters untrusted content | — | Low exposure (inputs are local config/sheets), but restrict file paths |

## Sources

- MCP spec 2025-06-18 `server/tools.mdx` (annotations untrusted, human in the loop, `structuredContent`/`outputSchema`, `isError`) and `client/elicitation.mdx` (accept/decline/cancel, flat schemas, no sensitive data). github.com/modelcontextprotocol/modelcontextprotocol. Seam tier LOW (webfetch); primary source.
- MCP `schema/draft/schema.ts` `ToolAnnotations` (`readOnlyHint` default false, `destructiveHint`, …).
- MCP spec 2026-07-28 changelog: stateless protocol and server-minted handles as tool arguments; MRTR replaces server-initiated elicitation; Roots/Sampling/Logging deprecated; deterministic `tools/list` order.
- github/github-mcp-server README: `--read-only` (wins over `--tools`), `--toolsets`/`--tools`, lockdown mode.
- sooperset/mcp-atlassian README + `docs/configuration.mdx` + `docs/tools-reference.mdx`: `READ_ONLY_MODE`, `ENABLED_TOOLS`, `TOOLSETS`, `jira_batch_create_issues`, `jira_delete_issue`, `env`-block credentials.
- PyPI `mcp`: current 2.3.0 (requires Python ≥3.10). The proposal's `mcp>=1.0` pin is outdated; STACK research should pick the major version.
- jiramator source (HIGH): `run_report.py`, `jira_client.py:250-290`, `planner.py:428-490, 1017-1040`, `importer.py:244-330, 426-430`, `updater.py:30-75`.
- Jira Cloud delete semantics (permission, `deleteSubtasks`, permanence): from domain knowledge, MEDIUM. Verify during the rollback phase.

---
*Feature research for: jiramator v1.1 MCP Server milestone*
*Researched: 2026-10-16*
