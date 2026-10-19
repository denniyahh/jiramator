# Stack Research

**Domain:** Local stdio MCP server + safety features (rollback, duplicate detection, Markdown preview) added to an existing Python Jira CLI
**Milestone:** v1.1 "MCP Server"
**Researched:** 2026-10-16
**Confidence:** HIGH. Every MCP claim below was checked by installing `mcp==2.3.0` in a scratch venv (Python 3.14 and 3.11), reading the source, and running smoke tests. Every Jira claim was checked against Atlassian's live Cloud v3 OpenAPI spec.

> **Scope:** This file covers only what the new features add. The existing stack (Python 3.11–3.13, click, rich, pydantic v2, PyYAML, requests, openpyxl, charset-normalizer, ruff, pytest) is already validated and is not re-evaluated here.

---

## TL;DR: what changes

1. **Add one runtime dependency, behind an extra:** `mcp>=2.3,<3`. This is the official MCP Python SDK.
2. **The April 2026 research is out of date.** It said `mcp>=1.27`, `FastMCP`, `pytest-asyncio`, and `anyio.to_thread` wrappers. SDK **2.0.0 shipped 2026-07-28** and **renamed `FastMCP` to `MCPServer`**. Importing `mcp.server.fastmcp` on 2.x now raises `ModuleNotFoundError`. The proposal's `mcp>=1.0` pin would also resolve to 2.x and break any v1-style code.
3. **Add no new dev dependency.** Async tests use the **anyio pytest plugin**, which ships with `anyio` and arrives with `mcp`. Do not add `pytest-asyncio`.
4. **No new Jira client library.** Add 2–3 methods to the existing `requests`-based `JiraClient`: `DELETE /rest/api/3/issue/{key}`, an optional `POST /rest/api/3/bulk/issues/delete`, and a paginated helper over the existing `POST /rest/api/3/search/jql`.
5. **No Markdown library.** Build the Markdown preview as a plain string in a pure module. Render it in the terminal with `rich.markdown.Markdown`, which is already installed (rich depends on `markdown-it-py`).

---

## Recommended Stack

### Core Technologies (new)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `mcp` (official MCP Python SDK) | `>=2.3,<3` (latest **2.3.0**, released 2026-10-02) | `jiramator-mcp` stdio server: tool registration, JSON-schema generation, structured output, stdio transport | Canonical SDK maintained by the MCP org. It generates tool input and output schemas from type hints using **Pydantic** (requires `pydantic>=2.12`), so jiramator's existing Pydantic idioms carry over directly. It runs **sync tool functions in a worker thread automatically**, so the sync `planner`/`importer`/`updater`/`JiraClient` stack needs no async rewrite. **Verified:** the server answers both the modern 2026-07-28 protocol and the legacy `initialize` handshake (negotiated `2025-11-25` in a test), so current VS Code, Copilot CLI, and Claude Desktop clients work. |

**Why `<3` and why the `2.3` floor:** 2.0 was a breaking major release. Releases 2.0 → 2.3 shipped within roughly ten weeks (2.0.0 on 07-28, 2.1.0 on 08-24, 2.2.0 on 09-07, 2.3.0 on 10-02), so the SDK is still moving. Flooring at the version we verified and capping the major keeps an unreviewed 3.0 from breaking `pipx` installs. The proposal already names SDK churn as a risk, and isolating everything under `jiramator/mcp/` plus the `[mcp]` extra limits the damage.

### Verified `mcp` 2.x API (what Phase planning should assume)

| Concern | v2 API (verified against 2.3.0) | Notes for jiramator |
|---|---|---|
| Server class | `from mcp.server.mcpserver import MCPServer` → `mcp = MCPServer("jiramator", instructions="...", version=__version__, lifespan=...)` | `instructions=` is shown to the assistant. Use it to state the rule: "always call `preview_*` and show the user before any `create_*`/`apply_*`." |
| Tool decorator | `@mcp.tool(name=None, title=None, description=None, annotations=ToolAnnotations(...), structured_output=None)`. Must be **called**: `@mcp.tool()`; bare `@mcp.tool` raises `TypeError`. | The description defaults to the docstring. Google-style docstrings (the repo convention) work as-is. |
| Tool annotations | `from mcp_types import ToolAnnotations`; `ToolAnnotations(readOnlyHint=True)` for discovery/preview tools, `ToolAnnotations(readOnlyHint=False, destructiveHint=True)` for `create_*`/`apply_*`/`resume_run`/rollback | Clients such as VS Code and Claude use these hints to auto-approve read tools and require user confirmation for destructive ones. That backs up the `preview_token` gate at the client level. Note: on 2.x model attributes are snake_case (`read_only_hint`), but the camelCase constructor aliases work. |
| Structured output | Return a **Pydantic `BaseModel`**. The SDK emits `outputSchema` plus `structuredContent` and also a JSON text block for older clients. | **Verified:** a model return type gives `output_schema` set and `structured_content` filled. A bare `-> dict` gave **no** output schema. **Rule: every tool returns a Pydantic result model** (`PreviewResult`, `CreateResult`, …) with `Field(description=...)`, which matches the repo's Pydantic conventions. |
| Sync functions | A plain `def` tool is run via `anyio.to_thread.run_sync(...)` inside the SDK (`mcpserver/utilities/func_metadata.py`). Verified: the tool body ran in "AnyIO worker thread". | **Don't** write `async def` tools wrapping `to_thread` yourself, and don't make core code async. Plain `def` tools calling `run_plan`/`run_import`/`run_update` directly is the right shape. Blocking `requests` calls are fine. |
| Lifespan / shared state | `lifespan: Callable[[MCPServer], AbstractAsyncContextManager[T]]`. Inside a tool, take a `ctx: Context` param (`from mcp.server.mcpserver import Context`) and read `ctx.request_context.lifespan_context`. Verified. | Use the lifespan for **cheap, immutable startup state only**: the resolved config dir (`JIRAMATOR_CONFIG_DIR`), the runs dir, and a preview-token store. **Don't** build a `JiraClient` at startup. Credentials or the network may be missing, and dry-run must degrade gracefully per tool, as the CLI does today. |
| Errors | `raise ToolError("…")` (`mcp.server.mcpserver.exceptions`) becomes `isError=True` with the message shown to the model. **Any other exception is hidden** behind "Error executing tool X" and its text is not sent. | Map the actionable domain errors (`ConfigValidationError`, `ConfigDriftError`, stale or missing `preview_token`, `JiraApiError` without secrets) to `ToolError` with the same plain-English text the CLI prints. Anything unexpected stays opaque by design, which is a useful default against leaking secrets. |
| Run (stdio) | `mcp.run()` (default `transport="stdio"`) is **synchronous** and calls `anyio.run` internally. | `def main() -> None: build_server().run()` → `[project.scripts] jiramator-mcp = "jiramator.mcp.server:main"`. HTTP/SSE also exist on `run()` but are out of scope. |
| Progress / logging to client | `await ctx.report_progress(n, total)`, `await ctx.info(...)` (async only) | Optional. With sync tools, skip progress for v1.1. Bulk create is chunked and fast enough. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `anyio` | comes with `mcp` (4.15.x) | Async runtime under the SDK; its **pytest plugin** (`@pytest.mark.anyio`) runs async tests | Only in `tests/test_mcp_*.py`. Never import it in core modules. |
| `rich.markdown.Markdown` | already installed (`rich>=13`) | Render the ISSUE-05 Markdown preview in the terminal for `--dry-run --format markdown`, or show Markdown next to the existing Rich tables | CLI display only. Writing the `.md` file and returning the MCP payload use the raw string. |
| `requests` | already installed | New `JiraClient.delete_issue` / `bulk_delete_issues` / paginated `search_jql` methods | FOUND-04 rollback and ISSUE-03 duplicate detection. |
| `hashlib` / `hmac` / `secrets` (stdlib) | stdlib | `preview_token` = `sha256(compute_resolved_hash(...) + inputs digest)`, compared with `hmac.compare_digest` | Token gate. No JWT or crypto library is needed. The token is a drift fingerprint, not an auth credential. Optionally salt it with a per-process `secrets.token_hex()` so tokens cannot be forged across server restarts. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest` + anyio plugin | In-memory MCP protocol tests | `from mcp import Client`; `async with Client(server) as c: r = await c.call_tool("preview_plan", {...}); r.structured_content`. Passing an `MCPServer` instance connects **in-process with no subprocess and no JSON-RPC framing**. Set `pytestmark = pytest.mark.anyio` and an `anyio_backend` fixture returning `"asyncio"`. **Verified passing.** |
| Same, stdio smoke | One end-to-end protocol test of the real entry point | `Client(StdioServerParameters(command=sys.executable, args=["-m", "jiramator.mcp.server"]))`, then `list_tools()`. **Verified passing**, including with `mode="legacy"` (old-client handshake). Keep it to one test because subprocess spawning is slow and Windows CI is the flakiest leg. |
| `npx @modelcontextprotocol/inspector` | Manual, interactive tool debugging | Docs and dev workflow only. Not a project dependency. |
| ruff | unchanged | The new `jiramator/mcp/` package must follow the same rules (`from __future__ import annotations`, etc.). |

---

## Installation / packaging changes

```toml
# pyproject.toml
[project.optional-dependencies]
mcp = ["mcp>=2.3,<3"]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "ruff>=0.16,<0.17",
    "mcp>=2.3,<3",        # so the default CI install (`pip install -e ".[dev]"`) runs MCP tests
]

[project.scripts]
jiramator     = "jiramator.cli:cli"
jiramator-mcp = "jiramator.mcp.server:main"   # NEW
```

```bash
# Users (pipx, the primary install path). The extra must be named explicitly:
pipx install "jiramator[mcp] @ git+https://…/jiramator.git"
# or add to an existing pipx install:
pipx inject jiramator "mcp>=2.3,<3"
```

**Entry point when the extra is missing:** `jiramator-mcp` is installed even without `[mcp]`, because scripts are not gated by extras. `jiramator/mcp/server.py:main()` should catch `ImportError` on `mcp` and print a one-line Rich **stderr** message ("install with `pipx install 'jiramator[mcp] @ …'`"), then exit 1. No traceback.

**Dependency weight of the extra (verified install):** `mcp` 2.3.0 pulls `anyio`, `httpx2`, `jsonschema`, `mcp-types`, `opentelemetry-api`, `pydantic>=2.12`, `pyjwt[crypto]` (therefore `cryptography`), `python-multipart`, `sse-starlette`, `starlette`, `uvicorn`, `typing-inspection`, and `pywin32` on Windows only. Most of this serves HTTP transport and auth, which stdio doesn't use, but the extra can't be slimmed. This is the main reason to keep `mcp` **optional** and out of the base CLI install.

**Pydantic floor interaction:** the base `pydantic>=2.0` floor stays. In environments with `[mcp]` installed, resolution forces `pydantic>=2.12`. Today's configs are fine with that, but CI (which installs `[dev]`, now including `mcp`) will always test against ≥2.12.

---

## Jira REST endpoints for the new features (verified against the live Cloud v3 OpenAPI spec)

| Feature | Endpoint | Key facts |
|---|---|---|
| **FOUND-04 rollback** (primary) | `DELETE /rest/api/3/issue/{issueIdOrKey}?deleteSubtasks=true` | `204` on success. `400` if the issue has subtasks and `deleteSubtasks=false` (the default). `403` without the **Delete issues** *project* permission. `404` if already gone. **Treat 404 as "already rolled back"** so rollback is idempotent. Delete **children before epics**: reverse creation order from the run report. |
| FOUND-04 rollback (optional fast path) | `POST /rest/api/3/bulk/issues/delete` body `{"selectedIssueIdsOrKeys": [...], "sendBulkNotification": false}` → `201` with `taskId`. Poll `GET /rest/api/3/bulk/queue/{taskId}` until `status: COMPLETE` (returns `processedAccessibleIssues`, `invalidOrInaccessibleIssueCount`). | Up to **1,000 issues** per request. **Also needs the *global* "Make bulk changes" permission**, which many PO/SM users won't have. Recommendation: **use per-issue DELETE as the default** (it needs only project permissions and fails per issue, which suits a run-report model). Add bulk delete only if real runs are large. Always pass `sendBulkNotification=false` so a rollback doesn't spam the team. |
| **ISSUE-03 duplicate detection** | `POST /rest/api/3/search/jql` body `{"jql": ..., "fields": ["summary","issuetype","status"], "maxResults": 100, "nextPageToken": ...}`, then loop while `isLast` is false | Already used by `find_issue_keys_by_summaries`. The old `GET/POST /rest/api/3/search` is **gone (410)**. JQL **must be bounded** (always include `project = X`). Pagination uses an opaque **`nextPageToken`** (no `startAt`/`total`). Default `fields` is `id` only, so request `summary` explicitly. |
| ISSUE-03 (cheap pre-check, optional) | `POST /rest/api/3/search/approximate-count` | Estimate only. Fine for "N possible duplicates" in a preview, not for correctness. |
| Read-after-write (rollback verify / resume) | `reconcileIssues: [ids]` on `search/jql` (max 50 ids) | Search is **eventually consistent**. Issues created seconds ago may not appear. Matters for "re-run duplicate check right after a partial create" and post-rollback verification. Prefer `GET /rest/api/3/issue/{key}` for per-key existence checks. |

**Existing-code gap to fix during ISSUE-03 (found while researching):** `find_issue_keys_by_summaries` sets `maxResults=len(unique_summaries)` with no pagination. `summary ~ "\"…\""` is a **phrase/contains** match, not exact, so a common summary can return more hits than requested, and exact matches past the first page are silently dropped. Duplicate detection should reuse a **paginated** search helper, request a sensible page size, and filter to exact (normalized) summary matches client-side, which the current code already does for the returned page. Also chunk the OR-clauses (for example 50 summaries per JQL) to stay under JQL size and complexity limits.

---

## Markdown preview (ISSUE-05): no new dependency

- Add a **pure** renderer module (for example `jiramator/preview_markdown.py`): `render_plan_markdown(...)`, `render_import_markdown(PreviewReport)`, `render_update_markdown(UpdatePreviewReport) -> str`. It belongs to the Builder layer (no I/O). The CLI writes it to `--output preview.md` and/or displays it via `rich.markdown.Markdown`. MCP `preview_*` tools return it as a `markdown: str` field on the Pydantic result model. That gives one renderer shared by CLI and MCP, as the milestone requires.
- GitHub-flavored pipe tables are fine for Copilot, Claude, and VS Code chat. **Escape `|` and newlines** in cell values (summaries and descriptions from spreadsheets contain them) and truncate long cells. That is the only real complexity and needs about 10 lines of helper code, not a library.
- The existing `importer.render_preview_report` / `updater.render_update_preview_report` return plain text. Refactor them to share the same intermediate `PreviewReport` data instead of parsing their text.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `mcp>=2.3,<3` (official SDK, `MCPServer`) | `fastmcp` (standalone PrefectHQ project, now **4.1.0**) | Only if the project later needs its extras (server composition, proxying, OpenAPI-to-MCP, hosted auth). For a 10-tool local stdio server it adds a second, faster-churning major-version stream with no benefit. The official SDK already absorbed the FastMCP-style decorator API. |
| `mcp>=2.3,<3` | Pin `mcp>=1.27,<2` (v1 `FastMCP` API) | Only if a target client turned out to require a pre-2.x quirk. Testing showed the 2.x server handles the legacy handshake, so there's no reason to start new code on a superseded major. |
| Plain `def` tools (SDK threads them) | `async def` tools + manual `anyio.to_thread.run_sync` | Never for this codebase. The SDK already does it, and doing it by hand adds noise and doubles the threading. |
| anyio pytest plugin | `pytest-asyncio` 1.4.0 | Only if the suite later needs asyncio-specific fixtures. Adding it next to the anyio plugin risks two plugins claiming the same async tests. If installed anyway, run with `-p no:asyncio` or mark tests explicitly. |
| Per-issue `DELETE` for rollback | Bulk delete API | When runs regularly exceed ~200 issues **and** users have global bulk-change permission. |
| Hand-built Markdown strings | `tabulate`, `py-markdown-table`, `jinja2` templates | Not needed. The output is a few headings and tables. Jinja is defensible only if users get to customize preview templates, which isn't in scope. |

---

## What NOT to Use / Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `from mcp.server.fastmcp import FastMCP` (any v1 snippet, including the v1.0 research and most blog posts) | **Raises `ModuleNotFoundError` on mcp 2.x.** Most web examples are still v1. | `from mcp.server.mcpserver import MCPServer, Context` |
| `mcp>=1.0` / `mcp>=1.27` unbounded pins (proposal and v1.0 research) | Resolve to 2.x today, so v1 code breaks on install. Unbounded on the top, so a future 3.0 breaks `pipx` installs again. | `mcp>=2.3,<3` |
| `create_connected_server_and_client_session` / hand-wired memory streams for tests | v1-era test helpers. `mcp.shared.memory` now exposes only low-level stream creation. | `mcp.Client(server_instance)` (in-process) |
| Anything writing to **stdout** in code reachable from a tool: `print()`, `Console()` without `stderr=True`, Click `echo` | In stdio mode stdout **is** the JSON-RPC channel. One stray byte corrupts the session. The current code is clean (every `Console(...)` is `stderr=True`, no `print()`), so keep it that way. | `Console(stderr=True)` / `logging` to stderr. Optionally add a test that asserts stdout stays empty during a tool call. |
| Rich `Prompt.ask` / `Confirm.ask` reachable from a tool | **stdin is the transport**. A prompt would block forever or swallow protocol bytes. `planner.py` still calls `Confirm.ask` unless `assume_yes`, and calls `_prompt_*` helpers when `PlanInputs` fields are missing. | MCP tools must call the `PlanInputs`/`assume_yes=True` paths only, and raise `ToolError` for missing inputs. Add a regression test that patches `rich.prompt.*.ask` to raise during MCP tool calls. |
| A `JiraClient` built in the lifespan, or credentials as tool arguments | Breaks graceful degradation and leaks secrets into chat transcripts. | Build the client per tool call from env vars (supplied via the MCP client's `env` block), as the CLI does. |
| HTTP/SSE/streamable-http transports, `AuthSettings`, OAuth providers | Out of scope (stdio only). Large attack surface. | `mcp.run()` (stdio default) |
| Python `jira` / `atlassian-python-api` libraries for delete/search | Duplicates the existing `JiraClient`, which already handles retries, TLS-interception options, and error wrapping. | 2–3 new `JiraClient` methods |
| `pytest-asyncio` added to `dev` | Redundant with the anyio plugin; risk of double collection. | `@pytest.mark.anyio` |

---

## Stack Patterns by Variant

**If a tool previews (read-only):**
- Plain `def`, `annotations=ToolAnnotations(readOnlyHint=True)`, returns a Pydantic model with `counts`, `sample`, `warnings`, `markdown`, `preview_token`.
- Degrades to an offline preview when credentials or Jira are missing (matches `plan`/`import --dry-run`). `preview_update` must raise `ToolError` without credentials (matches `update --dry-run`).

**If a tool writes (`create_plan`/`create_import`/`apply_update`/`resume_run`/rollback):**
- `annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True)`. Required `preview_token: str`. Recompute the token from the same inputs, compare with `hmac.compare_digest`, and on mismatch `raise ToolError("Preview is stale…call preview_* again")`.
- Returns `status`, `created`/`failed`, `report_path`, never raw Jira payloads.

**If rollback runs:**
- Mark rollback in the run report (new status, or a sibling `-rollback.json`) so a later `--resume` cannot re-create rolled-back issues by accident, and so rollback itself is resumable.

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `mcp` 2.3.0 | Python ≥3.10 (verified import on **3.11.17** and 3.14) | Covers the CI matrix 3.11–3.13. `pywin32>=311` is pulled on Windows (wheels exist for 3.11–3.13). |
| `mcp` 2.3.0 | `pydantic>=2.12` | Narrows the effective pydantic floor when the extra is installed. No conflict with current code. |
| `mcp` 2.3.0 | `anyio>=4.9` (py<3.14) | Supplies the pytest plugin used by tests. |
| `mcp` 2.3.0 server | Clients using protocol `2026-07-28` (modern) **and** legacy `initialize` (negotiated `2025-11-25`) | Verified over stdio both ways. Covers Copilot CLI / VS Code / Claude Desktop regardless of client SDK age. |
| Jira Cloud REST v3 | `search/jql` (enhanced search) | Already in use. The legacy `/search` returns 410. Jira **Data Center/Server** has no `search/jql` or bulk-delete API. The project already targets Cloud only, so keep it that way and state it in the MCP docs. |

---

## Sources

- PyPI JSON API (queried 2026-10-16): `mcp` 2.3.0 (2026-10-02; 2.0.0 2026-07-28; last 1.x = 1.30.0 2026-09-07), `fastmcp` 4.1.0, `pytest-asyncio` 1.4.0, `anyio` 4.15.1. **HIGH**
- `mcp` 2.3.0 installed source: `mcp/server/fastmcp.py` (removal shim + migration URL `https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver`), `mcp/server/mcpserver/server.py` (`MCPServer.__init__`, `tool()`, `run()`), `tools/base.py` (error semantics), `utilities/func_metadata.py` (sync → `anyio.to_thread.run_sync`), `mcp/client/client.py` (`Client` in-process/stdio/`mode`). **HIGH**
- Local executed verification: in-process `Client(server)` structured output + lifespan context + `ToolError`; pytest anyio in-proc + stdio subprocess tests (2 passed); legacy-mode stdio handshake; Python 3.11 import. **HIGH**
- Atlassian Jira Cloud platform REST v3 OpenAPI (`developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json`, fetched 2026-10-16): `DELETE /issue/{issueIdOrKey}`, `POST /bulk/issues/delete` + `IssueBulkDeletePayload`, `GET /bulk/queue/{taskId}`, `POST /search/jql` + `SearchAndReconcileRequestBean`/`Results`, `POST /search/approximate-count`. **HIGH**
- Repository code read for integration points: `jiramator/jira_client.py` (`find_issue_keys_by_summaries`, existing endpoints), `run_report.compute_resolved_hash`, `planner.py` prompt sites, `Console(stderr=True)` usage, `importer/updater` preview renderers. **HIGH**
- Superseded: `.planning/milestones/v1.0-research/STACK.md` (2026-04-27). Its `mcp>=1.27` / `FastMCP` / `pytest-asyncio` guidance is **obsolete**.
