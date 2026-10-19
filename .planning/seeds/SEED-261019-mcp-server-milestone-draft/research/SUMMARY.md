# Project Research Summary

**Project:** Jiramator: milestone v1.1 "MCP Server"
**Domain:** Local stdio MCP front-end plus bulk-write safety features (update resume, run rollback, duplicate detection, Markdown preview export) added to an existing sync/`requests`-based Python Jira bulk-automation CLI
**Researched:** 2026-10-16
**Confidence:** HIGH. The codebase facts and the MCP SDK behaviour were checked directly. Jira delete/search semantics and per-client MCP behaviour are MEDIUM (see Gaps).

## Executive Summary

v1.1 puts a natural-language front-end on a tool whose main promise is "never surprise the user." Well-regarded write-capable MCP servers (GitHub MCP, `sooperset/mcp-atlassian`) offer a read-only mode, put credentials only in the client `env` block, and set tool annotations. None of them has a mandatory preview step before writing. Jiramator's small set of workflow tools (about 10), with each write gated by a preview, is a real differentiator, but only if the gate is built properly. All four research files reach the same main conclusion: **the MCP layer is the easy part. The real work is turning today's CLI-shaped core into a frontend-agnostic application service.** Today `run_plan` returns `None`, and its preview exists only as Rich tables. The planner still has 6 `sys.exit(1)` calls and several stdin prompts. The import/update run-report lifecycle lives inside `cli.py`. `update` only writes its report after the fact, with an empty hash. `compute_resolved_hash` ignores spreadsheet contents. The runs directory is relative to the working directory. Any one of these breaks an MCP server, and fixing them also delivers `update --resume` and the shared Markdown renderer.

**Recommended approach.** First, add a new `jiramator/operations.py` service layer, typed exceptions in `errors.py`, a structured `PlanPreview`, and additive `RunReport` fields (`operation`, `source_path`, `source_digest`, `params`, `rollback_of`) behind an unchanged CLI. Next, add the CLI-visible features that build on that layer: `update` reports and resume, a pure Markdown renderer, and duplicate detection. Then put a thin `jiramator/mcp/` adapter on top, using the official SDK at **`mcp>=2.3,<3`** (`MCPServer`, plain `def` tools, a Pydantic model for every result, `ToolError` for actionable errors), installed via an optional `[mcp]` extra. Build it read-only first, then add write tools gated by a **server-issued, HMAC-signed, single-use, time-limited `preview_token`**. The token is bound to the operation, the config hash, an inputs digest (normalized spreadsheet rows plus parameters) and the normalized arguments. Rollback is **CLI-only** in v1.1. It only deletes issues the run created and that nobody has modified since, children first.

**Key risks and mitigations.**
1. **The token proves a preview ran, not that the user consented.** Mitigate with annotations (`readOnlyHint`/`destructiveHint`), single-use plus TTL, server `instructions` telling the model to show the preview and wait, and optional elicitation.
2. **A spreadsheet edited between preview and create.** Mitigate with an inputs digest in both the token and the run report.
3. **Long writes outlive the client timeout and the LLM retries, creating duplicates.** Mitigate with single-use tokens, a run lock plus `running` status, duplicate detection, and **removing POST from urllib3's create retries**.
4. **Rollback deleting work people have since adopted.** Mitigate with created-only scope, a skip-if-modified changelog check, a permission preflight, and dry-run by default.
5. **Stdout pollution and the stale v1 SDK API.** Every v1-era snippet (`FastMCP`) fails on 2.x. Mitigate with a pinned major version and a subprocess smoke test asserting every stdout line is JSON-RPC.

## Key Findings

### Recommended Stack

Add exactly one runtime dependency, behind an extra. Add no new dev dependency, no new Jira library and no Markdown library. Everything else extends what already exists. Detail: [STACK.md](./STACK.md).

**Core technologies:**
- **`mcp>=2.3,<3` (official MCP Python SDK), `[mcp]` extra only.** Use `from mcp.server.mcpserver import MCPServer, Context`. SDK 2.0 (2026-07-28) **removed `FastMCP`**, so the proposal's `mcp>=1.0` pin and the April v1.0 research are obsolete. The SDK runs plain `def` tools in a worker thread, so the core needs no async rewrite. Pydantic return models produce `outputSchema` plus `structuredContent`. `ToolError` is shown to the model, while other exceptions stay opaque. Verified on Python 3.11 and with legacy-handshake clients.
- **Console script `jiramator-mcp = "jiramator.mcp.server:main"`.** It is installed even without the extra, so `main()` must catch `ImportError` and print a one-line install hint to stderr.
- **Stdlib `hmac`/`hashlib`/`secrets`** for the preview token. No JWT or crypto library.
- **Existing `requests` `JiraClient`, plus 2 methods.** `delete_issue` (`DELETE /rest/api/3/issue/{key}`, where 404 means already deleted and 403 gets a permission hint) and a **paginated, batched** `search/jql` helper (`nextPageToken`, about 25–50 summaries per query). Skip the bulk-delete API: it needs the global "Make bulk changes" permission.
- **`rich.markdown.Markdown`** (already installed) for optional terminal display. The Markdown itself is built as plain strings.
- **Tests: the anyio pytest plugin** (ships with `mcp`) plus an in-process `mcp.Client(server)`. Add exactly one stdio subprocess smoke test. **Do not add `pytest-asyncio`.** Add `mcp` to the `[dev]` extra so CI runs the MCP tests, and add a separate job that installs without `[mcp]`.

Side effects to accept: the `[mcp]` extra pulls in starlette/uvicorn/httpx2/pyjwt/cryptography (and pywin32 on Windows), and raises the effective pydantic floor to 2.12. Both are reasons to keep MCP optional.

### Expected Features

Detail: [FEATURES.md](./FEATURES.md).

**Must have (table stakes):**
- stdio `jiramator-mcp` with read tools: `list_teams`, `describe_team`, `preview_plan`, `preview_import`, `preview_update`, `list_run_reports`.
- Write tools: `create_plan`, `create_import`, `apply_update`, `resume_run`, all requiring a `preview_token`.
- Correct annotations on every tool. Results carry both structured data and Markdown text. Errors use `isError` with actionable, redacted messages.
- **Read-only mode** (`JIRAMATOR_MCP_READ_ONLY=1`: write tools are not registered at all). Both reference servers have this.
- Bounded output: counts, a sample of N rows, and a path to the full `.md` file.
- File-path inputs restricted to allow-listed roots and `.csv`/`.xlsx`.
- A `doctor`/`server_info` read tool: resolved workspace, configs found, whether credential env vars are present (yes/no only), CA bundle, Jira connectivity.
- `update` run reports written per row, `update --resume`/`--force`, and `list_run_reports`/`resume_run` covering all three commands.
- ISSUE-03: `plan` duplicate check (new; today it prints "does NOT check for duplicates"), import duplicates shown in the preview, and the lookup pagination/escaping bug fixed. `--allow-duplicates` to override.
- FOUND-04: `jiramator rollback <report>|--latest`. Preview first. Created-only. Skips modified issues. Deletes children before epics. Permission preflight. Idempotent. Writes its own report.
- ISSUE-05: one shared Markdown renderer used by CLI `--dry-run --markdown PATH` and all MCP `preview_*` results. Escapes cell content, writes UTF-8, deterministic output.
- Setup docs for VS Code Copilot (`servers`), Claude Desktop (`mcpServers`) and Claude Code (`claude mcp add`). Absolute executable paths, the `env` block (including `JIRAMATOR_CA_BUNDLE`), no plaintext tokens in workspace files.

**Should have (differentiators, include where cheap):**
- Single-use, TTL'd token (treated here as a must; see Pitfalls).
- Every preview echoes back the normalized inputs (PI label, versions, resolved path, sheet, row count, resolved `sprints_exist`, fix versions that would be created).
- Duplicates and side effects shown inside previews and covered by the token.
- Capture **prior field values** in `update` reports now. That enables a later before→after diff and update revert at low marginal cost.
- Execution and rollback reports exportable as Markdown, with keys linked to Jira.
- An MCP `plan_pi` prompt template (cheap, optional).

**Defer (v1.1.x / v2+):**
- Elicitation confirm on write tools. Only once a target client is shown to support it, and never as the only gate.
- Soft rollback (transition to "Won't Do" plus a label). Becomes a must if users lack Delete permission (see Gaps).
- MCP rollback tools (`preview_rollback`/`rollback_run`, opt-in).
- `jiramator mcp-config --client …` snippet generator and `--self-test`.
- Update revert, HTML export, fix-version cleanup on rollback, HTTP/SSE transport.
- **Anti-features (never):** generic `jira_create_issue`/raw JQL tools; a `dry_run: bool` flag on one tool; credentials as tool arguments or via elicitation; config-editing tools; `force` exposed over MCP; fuzzy/semantic duplicate matching; upsert-on-duplicate; rollback by JQL or label; automatic rollback on partial failure.

### Architecture Approach

Add an **application-service layer** (`operations.py`) between the front-ends and the existing Builder/Client/Planner/Importer/Updater layers. Both `cli.py` and `jiramator/mcp/` call the same `load_*_context`, `preview_*`, `execute_*`, `resume_run`, `preview_rollback`/`execute_rollback` and `list_reports` functions. These take an injected `client_factory`, which keeps the 16 test patches of `jiramator.cli.JiraClient` valid, and a `console`. They never call `sys.exit` and never prompt. Previews are frozen dataclasses rendered at the edge (Rich for the CLI, pure Markdown for export and MCP). Core modules never import `jiramator.mcp`, and `mcp/server.py` is the only module that imports the SDK. Detail: [ARCHITECTURE.md](./ARCHITECTURE.md).

**Major components:**
1. **`operations.py` (new).** The single config-load and `merge_configs` path, which keeps CLI and MCP hashes identical. Owns spreadsheet reading, the full run-report lifecycle (moved out of `cli.py`), resume and rollback entry points.
2. **`errors.py` (new).** `JiramatorError` with subclasses `PlanAborted`, `NonInteractiveError`, `PreviewTokenError` and `DriftError` (aliased to `ConfigDriftError`). The CLI maps these to `_fail`/exit 1; MCP maps them to `ToolError`.
3. **`planner.py` (modified).** `build_plan_preview() -> PlanPreview`. The 6 `sys.exit` calls become `raise PlanAborted`. `run_plan` returns `PlanRunResult`. An `interactive=False` guard covers prompts. Duplicate epic reuse is rebound **before** the final `build_all(..., epic_keys=...)`.
4. **`run_report.py` (modified, additive only, `SCHEMA_VERSION` stays 1).** New fields: `operation`, `source_path`, `source_digest`, `params`, `rollback_of`. New statuses: `IssueStatus` `"deleted"` and `RunStatus` `"running"`. New functions: `compute_inputs_digest`, `compute_org_hash`, an anchored `runs_dir()` (`JIRAMATOR_WORKDIR`, defaulting to the parent of `JIRAMATOR_CONFIG_DIR`), `list_reports`, and `find_resumable(..., operation=)`. **Do not change `compute_resolved_hash`**, because that would invalidate every existing report.
5. **`preview_render.py`, `duplicates.py`, `rollback.py` (new, pure or near-pure).** Markdown renderers over dataclasses; a batched, exact-filtered existing-issue lookup; `build_rollback_plan` (created-only, deduplicated, children first) plus executor.
6. **`jiramator/mcp/` (new, optional).** `server.py` (SDK wiring, lifespan holding only cheap immutable state, no `JiraClient` at startup), `tools.py` (argument marshalling to `operations`, with a redaction decorator at the adapter boundary), `tokens.py` (HMAC issue/verify with a per-process key, a consumed-token set behind a `threading.Lock`), and `context.py` (workspace, config-dir and team resolution; never `os.chdir`).

### Critical Pitfalls

Detail: [PITFALLS.md](./PITFALLS.md) (23 pitfalls, phase-mapped).

1. **Token ≠ consent; replayable tokens.** A bare `sha256:` + `compute_resolved_hash` token (the proposal's sketch) is deterministic and can be forged or replayed. **Avoid:** HMAC with a per-process key over `(op, resolved_hash, inputs_digest, normalized_args, issued_at)`, a TTL of about 15–30 min, single use, annotations, server `instructions`, and success text written as facts rather than instructions to the model.
2. **Hash ignores the spreadsheet** (import passes `(org, team, None, [])`; update stores `""`). **Avoid:** `compute_inputs_digest` over normalized rows plus sheet, key column and limits. Store it as `RunReport.source_digest` so CLI `--resume` also detects spreadsheet drift.
3. **`sys.exit`/`Prompt.ask`/`Confirm.ask` reachable from tools.** `SystemExit` is a `BaseException`. Prompts read stdin, which is the transport. **Avoid:** typed exceptions; explicit inputs for `sprints_exist` and fix-version creation, shown in the preview; a guard test that runs every tool with `*.ask` and `sys.exit` patched to raise.
4. **Timeouts, retries and duplicates.** Sync tool threads can't be cancelled. urllib3 currently **retries create POSTs on 502/504** (from proxies), which creates silent duplicates. **Avoid:** remove POST from create retries (verify, then retry); add a run lock plus `RunStatus="running"` so an active run isn't treated as resumable (today's default status is `failed`); single-use tokens; duplicate detection before MCP writes.
5. **Rollback destroys adopted work. Jira Cloud has no recycle bin for issues.** **Avoid:** delete only `status=="created"` from `operation in {plan, import}` (never `skipped` keys); check changelog/comments/worklog/children and skip anything modified unless `--include-modified`; never pass `deleteSubtasks=true` blindly; preflight `mypermissions` for DELETE_ISSUES; dry-run by default; 404 counts as success; the original report is never changed.
6. **Duplicate lookup is wrong today.** `maxResults=len(summaries)` with fuzzy `summary ~` drops exact matches that land on page 2. Reserved characters (`[ ] ( ) & : -`) aren't escaped. Search lags right after creation. Recurring summaries cause false positives. **Avoid:** narrowed JQL (project + issuetype, plus fixVersion where templated), batching, `nextPageToken` pagination, full escaping, NFC/casefold/smart-quote normalization before comparing, cross-checking local run reports, and a three-state result in dry-run (checked / skipped-offline / error).
7. **Working directory and environment when the client launches the server, plus credential leakage.** **Avoid:** an explicit workspace root, failing fast with an actionable error, the `doctor` tool, absolute executable paths in docs, VS Code `${input:…}`/`envFile`, and `sanitize_message` applied to every MCP error path.

## Implications for Roadmap

Suggested structure: **8 phases**, linear. This matches the "sequential inline execution" pattern recorded in STATE.md. Ordering principle: **build the shared foundations, then finish all CLI-visible safety features, then MCP read, then MCP write.** That way every MCP write tool sits on top of resume, Markdown and duplicate detection that are already proven. Rollback has no MCP dependency and can move anywhere after Phase 4.

### Phase 1: Core Seams & Report Foundations (no user-visible change)
**Rationale:** Every later feature needs structured previews, typed errors, a shared lifecycle and the extended report schema. Doing it once, behind an unchanged CLI and the 710-test suite, is the safest refactor (ARCH step A; PITFALLS "P-Core must come first").
**Delivers:** `errors.py`; `operations.py` with `load_*_context`, `execute_import`/`execute_update` moved out of `cli.py` with an injected `client_factory`; `PlanPreview` + `build_plan_preview`; `sys.exit` → `PlanAborted`; `run_plan` returns `PlanRunResult`; `interactive=False` guard with explicit `sprints_exist`/`create_missing_fix_versions` inputs; additive `RunReport` fields; `compute_inputs_digest`/`compute_org_hash`; anchored `runs_dir()`; `list_reports`; `RunStatus="running"` plus run lock with stale-pid detection; **POST removed from create retries**; a test that loads a v1.0 report fixture.
**Addresses:** prerequisites for every v1.1 feature.
**Avoids:** Pitfalls 2, 3, 5, 9 (retry), 16; Anti-patterns 1, 2, 4.

### Phase 2: `update` Run Reports + `--resume`
**Rationale:** The smallest complete user of the new `operations` lifecycle, so it proves the extraction. `resume_run`/`list_run_reports` parity across all three commands depends on it.
**Delivers:** Per-row atomic persistence in `run_update`, mirroring `run_import`; stable `template_key="updated:<KEY>"`; `compute_org_hash` + `source_digest` drift check; CLI `update --resume/--force`; capture of prior field values (cheap now, enables revert later); `_update_report_from_result` removed once counts match.
**Addresses:** milestone item "update run reports + --resume".
**Avoids:** Pitfall 9 (crash mid-run leaves no record; lost update on resume after spreadsheet edits).

### Phase 3: Markdown Preview Export (ISSUE-05)
**Rationale:** MCP `preview_*` text output *is* this renderer. Building it before MCP avoids a third rendering path. Low risk.
**Delivers:** Pure `preview_render.py` (plan/import/update previews, run report, rollback plan); `--markdown PATH` on all three `--dry-run` paths in addition to the existing output; escaping and truncation; UTF-8 writes with `\n` line endings; ADF flattened to plain text; golden-file tests with hostile strings.
**Avoids:** Pitfalls 14, 21; Anti-pattern 6 (scraping Rich output).

### Phase 4: Duplicate Detection (ISSUE-03)
**Rationale:** Must land **before MCP writes**: an assistant retrying a timed-out create is the most likely source of duplicates. It also produces the distinct `skipped`-with-key records that rollback relies on to avoid deleting pre-existing issues.
**Delivers:** `duplicates.py`; batched, paginated, escaped lookup (also fixes the shared `parent` lookup bug); scoped match key; normalization; local run-report cross-check; plan epic reuse and ticket skip; import duplicates shown in preview; three-state status in offline dry-run; `--allow-duplicates`, included in the inputs digest; a duplicates section in the Markdown output.
**Avoids:** Pitfalls 8, 18.

### Phase 5: MCP Server: Read-Only Tools
**Rationale:** Writes nothing, so it's safe to dogfood right away. It checks workspace anchoring, stdout cleanliness, SDK wiring and token *issuance* before anything can write.
**Delivers:** `[mcp]` extra + `jiramator-mcp` entry point (with the missing-extra hint); `mcp/server.py`, `context.py`, `tools.py`, `tokens.py` (issue only); `list_teams`, `describe_team`, `preview_plan/import/update`, `list_run_reports`, `doctor`; read-only mode; Pydantic result models; strict input models (`extra="forbid"`, did-you-mean on team names); path allow-list; capped samples; capturing console; adapter-level redaction; subprocess JSON-RPC smoke test on all 3 operating systems; prompt/exit guard test; a CI job without `[mcp]`.
**Uses:** `mcp>=2.3,<3` `MCPServer`, plain `def` tools, `ToolAnnotations(readOnlyHint=True)`, the anyio test plugin.
**Avoids:** Pitfalls 4, 10, 12, 13, 15, 17, 19, 20.

### Phase 6: MCP Server: Token-Gated Write Tools
**Rationale:** Needs update reports (Phase 2) for `resume_run` parity, duplicate detection (Phase 4) for retry safety, and the read side (Phase 5) for tokens.
**Delivers:** `tokens.verify` (HMAC compare, TTL, single use, argument binding; any mismatch gives "preview is stale — call preview_* again"); `create_plan`, `create_import`, `apply_update`, `resume_run` (token from `list_run_reports`); `destructiveHint` annotations; run lock returns `in_progress` on a concurrent write; server `instructions` require showing the preview and waiting for confirmation; results return status, counts, `report_path` and Markdown; no `force` over MCP. Decide on a soft cap or async return for very large runs.
**Avoids:** Pitfalls 1, 2, 5, 11.

### Phase 7: Run Rollback (FOUND-04), CLI-only
**Rationale:** Needs the `operation` field from Phase 1 and the clean `skipped` vs `created` split from Phase 4. Independent of MCP. Kept CLI-only because it is the most destructive operation in the product.
**Delivers:** `JiraClient.delete_issue`; `mypermissions` preflight; `rollback.py` (created-only, deduplicated across a resume chain, children before epics); per-issue safety classification (`safe`/`modified`/`has_children`/`gone`/`forbidden`); `jiramator rollback <report>|--latest` (preview by default, `--yes`, `--include-modified`); a rollback report with `rollback_of`, original report unchanged; `--resume` refuses rolled-back issues unless `--force`; fix versions never touched; refuses `update`/`rollback` reports.
**Avoids:** Pitfalls 6, 7, 23; Anti-pattern 5.

### Phase 8: Distribution & MCP Setup Docs
**Rationale:** Documents what actually shipped. Client config schemas change often, so verify them last.
**Delivers:** pipx install/inject commands with the extras-plus-git-URL syntax; copy-paste configs for VS Code Copilot, Claude Desktop and Claude Code on Windows and macOS (absolute paths, forward slashes, `env` block including the CA bundle/TLS variables, `${input:…}`/`envFile`, user scope); a "first conversation" walkthrough; troubleshooting (client log locations, the `doctor` tool, timeouts); token and read-only-mode semantics; rollback permission notes; `.gitignore` template additions in `init`; `AGENTS.md`/`CLAUDE.md` architecture update (operations layer + MCP front-end).
**Avoids:** Pitfalls 10, 11, 17, 19.

### Phase Ordering Rationale

- **Dependencies:** Phase 1 → (2, 3) → 4 → 5 → 6. Phase 7 needs only 1 and 4. Phase 8 comes last. Phases 2 and 3 are independent of each other.
- **Grouping:** All CLI features (2–4, 7) reuse the same `operations` lifecycle, so the CLI and MCP paths can't drift apart. Splitting MCP into read (5) and write (6) means the first MCP release has no write risk and can be dogfooded.
- **Pitfall avoidance:** Every prerequisite for safe MCP writes (typed aborts, inputs digest, run lock, retry fix, duplicate detection) exists before Phase 6. Rollback is kept off the MCP surface.
- **Optional reorder:** If rollback is wanted earlier for user value, run Phase 7 straight after Phase 4. It has no MCP dependency.

### Research Flags

Phases likely needing `/gsd-plan-phase --research-phase <N>`:
- **Phase 4 (Duplicates):** Jira Cloud text-search escaping rules, `search/jql` eventual consistency and `reconcileIssues`, and the exact scoped match key for recurring plan summaries. Verify against the user's live Jira instance.
- **Phase 6 (MCP write):** per-client tool-call timeouts and progress-notification behaviour (VS Code Copilot, Claude Desktop/Code), elicitation support (LOW confidence), and the decision on a large-run soft cap or async return.
- **Phase 7 (Rollback):** whether target users actually have DELETE_ISSUES on their projects. If not, soft rollback (transition plus label) moves from deferred into scope. Also whether a "Won't Do"/"Cancelled" transition exists per project.
- **Phase 8 (Docs):** current `mcp.json`/`claude_desktop_config.json` schemas, `inputs`/`envFile`, and log locations on Windows and macOS.

Phases with standard patterns (skip research):
- **Phase 1:** needs careful *planning*, not external research. Include an explicit test-migration task for the patched targets (`jiramator.cli.JiraClient`, `read_spreadsheet`, `find_resumable`, `RUNS_DIR`) and the `SystemExit` assertions.
- **Phases 2, 3:** mirror existing `run_import` patterns; pure rendering.
- **Phase 5:** the SDK 2.3 API was verified end-to-end in STACK.md (server, tools, structured output, lifespan, errors, in-process plus stdio tests). Planning can use those notes directly.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | `mcp` 2.3.0 installed and smoke-tested (in-process, stdio, legacy handshake, Python 3.11); Jira endpoints checked against the live Cloud v3 OpenAPI spec. |
| Features | MEDIUM | Codebase baseline HIGH; MCP spec facts MEDIUM (primary source via web fetch); client handling of annotations and elicitation LOW (inferred, untested). |
| Architecture | HIGH | Integration facts F1–F13 read directly from v1.3.0 source and test greps. SDK mechanics deliberately isolated behind one adapter. |
| Pitfalls | HIGH | Code-level traps verified (retry config, `maxResults`, default `failed` status, hash inputs, fd diversion in the SDK). Jira delete/permission/search-lag and client timeout figures are MEDIUM. |

**Overall confidence:** HIGH for the build plan and ordering; MEDIUM for client-behaviour and live-Jira assumptions, which are concentrated in Phases 4, 6, 7 and 8.

### Gaps to Address

The research files disagreed on several points. The **decision column below is binding for planning unless the user overrides it.**

| Conflict | Positions | Decision |
|---|---|---|
| Token mechanism | Stateless HMAC (ARCH) vs in-memory token map (FEATURES/PITFALLS) | **HMAC with a per-process key** (no store needed for validity) **+ TTL + an in-memory consumed set** for single use. Bind to op + config hash + inputs digest + normalized args. |
| Inputs digest basis | Raw file bytes (PITFALLS) vs normalized rows (ARCH) | **Normalized rows as read by `read_spreadsheet` + sheet/key column/limits + resolved path.** Excel re-saves change the bytes without changing the content. |
| Duplicate default policy | Skip (FEATURES/ARCH) vs warn (PITFALLS, citing recurring summaries) | **Skip by default for scoped exact matches** (project + issuetype + normalized summary, plus fixVersion where templated), **always shown in the preview and covered by the token**; the `on_duplicate: skip\|create\|fail` override applies to both CLI and MCP. Import keeps today's skip behaviour. Phase 4 must check that plan templates without PI/version tokens in their summary aren't wrongly skipped. |
| Marking rolled-back issues | Mutate the original report to `rolled_back` (PITFALLS) vs append-only `rollback_of` (ARCH) | **Append-only.** The rollback report has `rollback_of`, and resume/duplicate/rollback logic consults rollback reports pointing at the original. |
| Report "kind" field name | `command` (PITFALLS) vs `operation` (ARCH) | **`operation`.** `command` already holds argv. Infer it for legacy reports. |
| Rollback over MCP | All three lean CLI-only | **CLI-only in v1.1**; MCP rollback deferred and opt-in. |

Other gaps:
- **Delete permission on the real instance** is unknown. Check it before or early in Phase 7. If POs lack it, promote soft rollback into scope.
- **Client timeouts/progress and elicitation support** are untested. Spike them in Phase 6 research. Design must not depend on either.
- **Large-run behaviour over MCP** (more than ~100 issues): soft cap and async return vs. blocking call. Decide in Phase 6.
- **`resume_run` token source**: whether to fold it into `list_run_reports` or add a dedicated `preview_resume` (the tool-budget trade-off). Decide in Phase 6.
- **Jira Data Center/Server is unsupported** (no `search/jql`). State this explicitly in the Phase 8 docs.
- **Phase 2 UAT (7 scenarios) is still pending from v1.0.** It is not in v1.1 scope, but Phase 1 refactors code it would exercise. Consider running it as a regression baseline before Phase 1.

## Sources

### Primary (HIGH confidence)
- `mcp` 2.3.0 wheel source + local executed tests: `mcp/server/mcpserver/server.py`, `tools/base.py`, `utilities/func_metadata.py` (sync → `anyio.to_thread.run_sync`), `server/stdio.py` (fd diversion), `server/fastmcp.py` (removal shim), `client/client.py`. Also the PyPI release history (2.0.0 2026-07-28 → 2.3.0 2026-10-02; last 1.x = 1.30.0).
- Atlassian Jira Cloud REST v3 OpenAPI (fetched 2026-10-16): `DELETE /issue/{key}`, `POST /bulk/issues/delete`, `GET /bulk/queue/{taskId}`, `POST /search/jql` (+ `reconcileIssues`), `POST /search/approximate-count`.
- Jiramator v1.3.0 source: `run_report.py`, `jira_client.py` (retry strategy, `find_issue_keys_by_summaries`), `planner.py` (prompts, `sys.exit` sites, `_display_preview`), `importer.py`, `updater.py`, `cli.py` (lifecycle, hash call sites, relative defaults); test patch-target greps.
- Project docs: `.planning/PROJECT.md`, `docs/mcp-server-proposal.md` (baseline; its token sketch and `mcp>=1.0` pin are superseded), `AGENTS.md`.

### Secondary (MEDIUM confidence)
- MCP spec 2025-06-18 (tools, elicitation), draft `ToolAnnotations` schema, 2026-07-28 changelog (stateless protocol and server-minted handles; Roots/Sampling/Logging deprecated).
- `github/github-mcp-server` and `sooperset/mcp-atlassian` READMEs/docs (read-only mode, toolsets, env-block credentials, batch create and delete tools).
- Jira Cloud permission and delete semantics (DELETE_ISSUES, `deleteSubtasks`, no issue recycle bin, `mypermissions`), text-search reserved characters.

### Tertiary (LOW confidence, validate in-phase)
- Per-client behaviour: VS Code Copilot / Claude Desktop / Claude Code handling of annotations, elicitation, tool-call timeouts (TS SDK 60 s default), `inputs`/`envFile`, log locations.
- Superseded: `.planning/milestones/v1.0-research/*` (`mcp>=1.27`, `FastMCP`, `pytest-asyncio` guidance is obsolete).

---
*Research completed: 2026-10-16*
*Ready for roadmap: yes*
