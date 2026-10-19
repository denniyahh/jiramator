# Architecture Research — v1.1 MCP Server (integration with the existing codebase)

**Domain:** Adding a local stdio MCP front-end, update run reports/resume, rollback,
duplicate detection and Markdown preview export to the existing jiramator CLI
**Researched:** 2026-10-16
**Confidence:** HIGH for integration points (read directly from `jiramator/*.py` at v1.3.0);
MEDIUM for MCP-SDK-specific mechanics (SDK is now at 2.x — see STACK.md for the pin; this
document deliberately keeps SDK details behind one adapter module)

> Scope: only what the six v1.1 features need. The existing five-layer design is described
> in `AGENTS.md`; the v1.0 copy of this file is archived at
> `.planning/milestones/v1.0-research/ARCHITECTURE.md`.

---

## 1. What the code actually looks like today (the facts the plan must respect)

These findings come from reading the source, and several contradict the
assumptions in `docs/mcp-server-proposal.md`:

| # | Fact (file:function) | Consequence for v1.1 |
|---|---|---|
| F1 | `planner.run_plan()` returns **`None`**. The preview exists only as Rich tables drawn by `_display_preview()`, and results go out only through `_display_results()`. | MCP `preview_plan`/`create_plan` and the Markdown export have **no structured data to use**. A structured `PlanPreview`/`PlanRunResult` has to be added. |
| F2 | `planner` calls **`sys.exit(1)`** in 6 places: credential error, `_preflight_validate` field problems, fix-version decline, final-confirm decline, epic create failure, and `_bulk_create_with_resume` bulk failure. | In a long-lived MCP server, `SystemExit` is a `BaseException`. It skips `except Exception` tool wrappers and **can stop the server process**. It has to be turned into a typed exception. |
| F3 | The planner prompts (`Prompt.ask`, `IntPrompt.ask`, `Confirm.ask`) read **stdin**. Under stdio MCP, stdin *is* the JSON-RPC stream. `_resolve_sprints_exist_mode` is safe because it checks `sys.stdin.isatty()` and raises `ConfigValidationError` when stdin isn't a terminal. `_collect_plan_inputs` (when `inputs is None`) and `Confirm.ask` (when `assume_yes=False`) do **not** check. | The MCP layer must **always** pass `inputs=PlanInputs(...)` and `assume_yes=True` (the latter only after token validation). Add a hard guard so a prompt can never be reached when running non-interactively (see §5.3). |
| F4 | All user output goes through `Console(stderr=True)`. Checked: the package has no `print()`, `sys.stdout` or plain `click.echo` writes (`cli._fail` uses `err=True`). Logging is only in `jira_client` and uses the default stderr handler. | **Nothing corrupts stdout today.** The risk is a future regression, so add a protocol smoke test as a guard. MCP adapters should pass a **capturing** `Console(file=io.StringIO())` so progress and warnings come back in the tool result instead of disappearing into the client's stderr log. |
| F5 | For **import**, `cli.import_command` owns the whole run-report lifecycle: building the `RunReport`, the drift check, finalizing status and `write_report_atomic` ("cli owns the lifecycle for import"). `run_import` only appends rows and persists per row. | The MCP layer cannot reuse this without copying cli code, which would break the "no Jira knowledge in front-ends" rule. The lifecycle has to be **extracted out of `cli.py`**. |
| F6 | For **update**, `cli.update_command` builds the report **after the fact** with `_update_report_from_result()`: `resolved_config_hash=""`, `template_key="row-N"`, nothing persisted during the run, no resume. `run_update` has no `report`/`prior_report` parameters. | "Update run reports" isn't greenfield. It is: move the builder out of cli, add per-row atomic persistence inside `run_update`, add a hash, use stable template keys, and add `--resume`. |
| F7 | `compute_resolved_hash(org, team, pi_label, versions)` covers config only. Import calls it as `(org, team, None, [])`, so **spreadsheet contents are not in the hash**. Update stores `""`. | A `preview_token` built only on `compute_resolved_hash` would **not** catch an edited spreadsheet between preview and create. The token needs an extra **inputs digest** (rows, sheet, key column, `sprints_exist`). |
| F8 | `cli.plan` runs `merge_configs(...)` **before** `run_plan`, so the plan hash is computed over the *merged* team config. | The MCP layer must load configs through exactly the same path. Otherwise its tokens and hashes won't match the CLI's, and CLI↔MCP resume breaks with false `ConfigDriftError`. This argues for one shared loader. |
| F9 | `RunReport` has no operation field. `find_resumable(team_config_path)` matches only on `team_config_path`. Plan and import record the **same** team path. Update records the **spreadsheet** path in `team_config_path`. No spreadsheet path, sheet name or key column is recorded for import. | `resume_run(report)` can't tell whether a report is a plan or an import, and can't re-read the import spreadsheet. `list_run_reports` can't label runs. Add `operation`, `source_path` and `params` fields. These are additive: `from_envelope` already drops unknown keys and `SCHEMA_VERSION` stays 1. |
| F10 | `RUNS_DIR = Path(".jiramator/runs")` is **relative to the working directory**. MCP clients start the server with an arbitrary working directory, often `$HOME` or `/`. | Reports land in unpredictable places and `list_run_reports` finds nothing. The runs directory has to resolve to an anchored location (§5.5). |
| F11 | Import is **already duplicate-safe at create time**: `run_import` calls `client.find_issue_keys_by_summaries()` and records duplicates as `status="skipped"` with the *existing* `jira_key`. Plan prints "⚠ This script does NOT check for duplicates." `find_issue_keys_by_summaries` builds one OR-JQL for all summaries with `maxResults=len(unique)`. | ISSUE-03 is: (a) bring that check **forward into preview** for import, (b) add it to plan (new), (c) make the search batch-safe (JQL length, and fuzzy `~` hits using up `maxResults`). |
| F12 | `JiraClient` has no delete method. Plan reports carry already-created issues forward on resume, so the same key shows up in several reports. Import "skipped" rows have a `jira_key` that **jiramator did not create**. `existing_epics` never appear as `created`. | Rollback must delete **only `status == "created"`**, tolerate 404 (already gone), and delete children before epics. Never delete `skipped` keys. |
| F13 | 16 tests patch `jiramator.cli.JiraClient`, 13 patch `jiramator.cli.read_spreadsheet`, 6 patch `jiramator.cli.find_resumable`. 11 tests touch `RUNS_DIR`. | Moving lifecycle code out of cli will break those patches unless the client is **injected**: `client_factory=JiraClient` passed from cli. Keep `RUNS_DIR` as the patchable constant. |

---

## 2. Target architecture

```
┌──────────────────────────────── Front-ends (no Jira knowledge) ─────────────────────────────────┐
│  cli.py (Click)                                     jiramator/mcp/ (NEW, [mcp] extra)            │
│   - arg parsing, Rich output, exit codes             - server.py: SDK wiring, main(), tool reg.  │
│   - --dry-run --markdown PATH (NEW)                  - tools.py: arg marshalling → operations    │
│   - update --resume (NEW), rollback cmd (NEW)        - tokens.py: preview_token issue/verify     │
│                                                       - context.py: config-dir/workdir resolve   │
└───────────────┬─────────────────────────────────────────────────┬────────────────────────────────┘
                │                                                 │
┌───────────────▼─────────── Application services (NEW: operations.py) ▼──────────────────────────┐
│  load_plan_context / load_import_context / load_update_context  (single config+merge path)       │
│  preview_plan / preview_import / preview_update      → structured *Preview dataclasses           │
│  execute_plan / execute_import / execute_update      → RunReport lifecycle + typed outcomes      │
│  resume_run(report_path)  rollback_preview / rollback_execute  list_reports                      │
│  (takes client_factory + console; never calls sys.exit; never prompts)                           │
└──────┬──────────────┬──────────────┬──────────────┬──────────────┬──────────────┬────────────────┘
       │              │              │              │              │              │
  planner.py     importer.py    updater.py     duplicates.py   rollback.py   preview_render.py
  (MODIFIED)     (MODIFIED)     (MODIFIED)     (NEW)           (NEW)         (NEW, pure Markdown)
       │              │              │              │              │
       └──────────────┴──────┬───────┴──────────────┴──────────────┘
                             │
           ticket_builder / field_resolver / value_coercion (unchanged)
           run_report.py (MODIFIED: additive fields, digest, runs-dir, list)
           jira_client.py (MODIFIED: delete_issue, batched summary search)
```

### Component responsibilities: new vs modified

| Component | Status | Responsibility in v1.1 |
|---|---|---|
| `jiramator/operations.py` | **NEW** | The frontend-agnostic application service, playing the same role `PlanInputs` played in v1.0. Owns config loading + `merge_configs`, spreadsheet reading, report lifecycle (create → drift check → persist → finalize), and resume/rollback entry points. Both cli and MCP call it. Raises typed exceptions and never calls `sys.exit`. |
| `jiramator/mcp/__init__.py`, `server.py` | **NEW** | `main()` entry point (`jiramator-mcp`). Builds the SDK server, registers tools, runs the stdio transport. **Only file that imports the `mcp` SDK.** |
| `jiramator/mcp/tools.py` | **NEW** | One function per tool: validate args → call `operations.*` → turn dataclasses into JSON-safe dicts + Markdown. Converts `JiramatorError` subclasses into tool errors. |
| `jiramator/mcp/tokens.py` | **NEW** | `issue_token(op, resolved_hash, inputs_digest)` / `verify_token(...)`. Stdlib only (`hmac`, `hashlib`, `secrets`, `time`). |
| `jiramator/mcp/context.py` | **NEW** | Resolves `JIRAMATOR_CONFIG_DIR` → org dir + teams dir, team-name → path (for `list_teams`), and the anchored working directory. |
| `jiramator/preview_render.py` | **NEW** | Pure functions turning a preview/result dataclass into a **Markdown string**: `render_plan_preview_md`, `render_import_preview_md`, `render_update_preview_md`, `render_run_report_md`, `render_rollback_preview_md`. No Rich, no I/O. Used by cli `--markdown` and by every MCP `preview_*` result. |
| `jiramator/duplicates.py` | **NEW** | `find_existing_by_summary(client, project_key, summaries) -> DuplicateReport` (batched), plus pure `annotate_plan_duplicates(all_payloads, existing)`. Read-only. |
| `jiramator/rollback.py` | **NEW** | Pure `build_rollback_plan(report) -> RollbackPlan` (created-only, children before epics, deduplicated across a resume chain). `execute_rollback(plan, client, report, persist)` deletes in order and records results in its own RunReport (`operation="rollback"`). |
| `planner.py` | **MODIFIED** | (1) Add `build_plan_preview(org, team, inputs, *, client=None) -> PlanPreview` (build_all + optional createmeta validation + optional duplicates, **returns** problems instead of printing/exiting). (2) `_display_preview` renders a `PlanPreview`. (3) Replace the 6 `sys.exit(1)` calls with `raise PlanAborted(reason)` (report.error is already set before each one). (4) `run_plan` returns `PlanRunResult(report, epic_keys, per_release_keys, per_sprint_keys)`. (5) Duplicate skip/reuse in epic and ticket creation. (6) A `non_interactive` guard on prompts. |
| `importer.py` | **MODIFIED** | `build_preview_report` gets an optional `existing_summaries` so preview shows duplicates. Move the summary lookup behind `duplicates.find_existing_by_summary`. Text renderers stay as they are (CLI output unchanged). |
| `updater.py` | **MODIFIED** | `run_update` gets `report`, `report_path`, `prior_report` parameters and per-row `_record`/`_persist`, mirroring `run_import`. Stable `template_key = f"updated:{issue_key}"` (keys are already validated unique). Resume skips `status == "updated"`. |
| `run_report.py` | **MODIFIED** | Additive `RunReport` fields: `operation: Literal["plan","import","update","rollback"] \| None`, `source_path: str \| None`, `source_digest: str \| None`, `params: dict[str, Any]`, `rollback_of: str \| None`. New `compute_inputs_digest(rows, **params)`, `runs_dir()` (anchored, still honours `RUNS_DIR`), `list_reports(limit, operation)`. `find_resumable(path, *, operation=None)`, where legacy reports with no `operation` are inferred from `command` argv. `IssueStatus` gains `"deleted"`. |
| `jira_client.py` | **MODIFIED** | `delete_issue(key) -> Literal["deleted","not_found"]` (DELETE `/rest/api/3/issue/{key}`; 404 → `not_found`, 403 → `JiraApiError` with a permission hint). `find_issue_keys_by_summaries` batches about 50 summaries per JQL and pages, so exact matches aren't lost when fuzzy `~` hits fill `maxResults`. |
| `cli.py` | **MODIFIED** | Becomes thinner: `import_command`/`update_command` delegate the lifecycle to `operations` (passing `client_factory=JiraClient` so existing patches keep working). Adds `--markdown PATH` on all three `--dry-run` paths, `update --resume/--force`, a `rollback` command (preview by default, `--yes` to execute), and `--allow-duplicates` on plan/import. Catches `JiramatorError` → `_fail`. |
| `pyproject.toml` | **MODIFIED** | `[project.optional-dependencies] mcp = [...]` and `[project.scripts] jiramator-mcp = "jiramator.mcp.server:main"`. |
| `ticket_builder`, `field_resolver`, `value_coercion`, `payload_validator`, `config*`, `spreadsheet`, `wizard` | unchanged | — |

---

## 3. Recommended project structure (delta only)

```
jiramator/
├── operations.py        # NEW  application services shared by cli + mcp
├── preview_render.py    # NEW  pure Markdown renderers (ISSUE-05)
├── duplicates.py        # NEW  summary-based existing-issue detection (ISSUE-03)
├── rollback.py          # NEW  rollback planning + execution (FOUND-04)
├── errors.py            # NEW  JiramatorError, PlanAborted, PreviewTokenError, NonInteractiveError
├── planner.py           # MOD
├── importer.py          # MOD
├── updater.py           # MOD
├── run_report.py        # MOD
├── jira_client.py       # MOD
├── cli.py               # MOD
└── mcp/                 # NEW  (only imported when [mcp] extra installed)
    ├── __init__.py
    ├── server.py        # SDK wiring + main(); the ONLY module importing `mcp`
    ├── tools.py         # tool adapters → operations.*
    ├── tokens.py        # preview_token HMAC
    └── context.py       # config-dir / workdir / team discovery
tests/
├── test_operations.py, test_preview_render.py, test_duplicates.py, test_rollback.py
└── mcp/ test_tools.py, test_tokens.py, test_stdio_smoke.py   # skip if `mcp` not importable
```

**Structure rationale:**
- **Flat modules for the core.** The repo convention is flat `jiramator/*.py`, so the new core modules stay flat. Only the MCP adapter gets a sub-package, because it's optional and depends on a fast-moving SDK, and isolating it limits the blast radius.
- **`errors.py` is shared.** Both front-ends map the same exception types to their own output: CLI → `_fail` + exit 1, MCP → tool error.
- **Markdown rendering doesn't live in `importer.py`/`updater.py` next to the existing text renderers.** One renderer module that sees all three preview types keeps the formatting consistent and lets CLI and MCP produce byte-identical Markdown (the core ISSUE-05 requirement).

---

## 4. Architectural patterns

### Pattern 1: Application-service extraction with injected client factory

**What:** Move the "load → hash → report → run → finalize" sequence out of `cli.py` into `operations.py`. The Jira client constructor is a parameter.
**When:** Every operation that both cli and MCP call (plan, import, update, resume, rollback).
**Trade-offs:** One more module and a large but mechanical cli diff. The payoff is that the MCP layer stays tiny and the CLI and MCP paths can't drift apart. Injecting `client_factory` keeps the 16 `jiramator.cli.JiraClient` test patches valid (fact F13).

```python
# operations.py
def execute_import(
    ctx: ImportContext, *, token_digest: str | None = None,
    client_factory: Callable[[OrgConfig], JiraClient] = JiraClient,
    report_path: Path | None = None, prior_report: RunReport | None = None,
    force: bool = False, allow_duplicates: bool = False, command: list[str] | None = None,
) -> ImportOutcome: ...

# cli.py — patch targets unchanged
outcome = execute_import(ctx, client_factory=JiraClient, ...)
```

### Pattern 2: Build-structured, render-at-edge

**What:** Every preview is a frozen dataclass first: the existing `PreviewReport` and `UpdatePreviewReport`, plus new `PlanPreview`, `DuplicateReport` and `RollbackPlan`. Renderers are separate pure functions: Rich (existing, cli), plain text (existing), Markdown (new).
**When:** Every preview and every run result.
**Trade-offs:** `planner._display_preview` has to be split into build + render. That's the only real refactor in planner, and `build_all` is already pure, so the risk is low.

```python
@dataclass(frozen=True)
class PlanPreview:
    project_key: str
    pi_label: str
    versions: list[str]
    payloads: dict[str, list[dict[str, Any]]]   # build_all output, epic refs unresolved
    counts: dict[str, int]                       # epics / per_release / per_sprint / total
    validation: Literal["ok", "problems", "skipped"]
    validation_problems: list[str]
    validation_skipped_reason: str | None
    duplicates: dict[str, str]                   # summary -> existing key (empty if not checked)
    sprints_exist: bool
    resolved_hash: str
```

`_run_plan_inner` then becomes: `preview = build_plan_preview(...)` → `_display_preview(preview, console)` → `if preview.validation == "problems": raise PlanAborted(...)` → continue. Dry-run behaviour stays the same: an unreachable Jira gives `validation="skipped"`, while real problems are still a hard stop in both modes.

### Pattern 3: Typed aborts instead of `sys.exit`

**What:** `errors.py` defines `class JiramatorError(Exception)` with subclasses `PlanAborted`, `NonInteractiveError`, `PreviewTokenError`, `DriftError`. (`run_report.ConfigDriftError` is kept and re-exported/aliased for compatibility.) Each of the 6 `sys.exit(1)` sites in planner already sets `report.error` and persists **before** exiting, so swapping to `raise PlanAborted(msg)` keeps the on-disk behaviour. `run_plan`'s outer `except BaseException` still records `ended_at`, and it keeps an `error` that was already set.
**When:** Anywhere orchestration code currently exits.
**Trade-offs:** cli has to catch `JiramatorError` → `_fail(str(exc))`. Tests that assert `SystemExit` from `run_plan` directly need updating; tests that go through `CliRunner` still see exit code 1.

### Pattern 4: Stateless HMAC preview token over (operation, config hash, inputs digest)

See §5.1. The token is recomputed on the write side from the write tool's own arguments, so a token can't authorize anything other than exactly what was previewed.

---

## 5. Design decisions in detail

### 5.1 `preview_token` design (recommended)

**Token payload:**
`v1.<op>.<issued_at_unix>.<hex(HMAC_SHA256(server_key, op|resolved_hash|inputs_digest|issued_at))[:32]>`

| Component | Plan | Import | Update |
|---|---|---|---|
| `resolved_hash` | `compute_resolved_hash(org, merged_team, pi_label, versions)` (unchanged; same value the CLI writes) | `compute_resolved_hash(org, team, None, [])` (unchanged) | `compute_resolved_hash(org, <empty TeamConfig sentinel>, None, [])`, or org-only via a new `compute_org_hash(org)`. **Pick `compute_org_hash`**: update has no team config. |
| `inputs_digest` = `compute_inputs_digest(...)` | `{"sprints_exist": <resolved bool>, "allow_duplicates": bool}` | sha256 of canonical-JSON **rows as read** (after `read_spreadsheet` normalization) + `sheet_name`, `max_rows`, `allow_duplicates` | sha256 of canonical rows + `key_column`, `sheet_name`, `max_rows` |

**Verification on `create_*`/`apply_*`:**
1. Re-load configs and the spreadsheet from the write tool's arguments, using the same `operations.load_*_context`.
2. Recompute `resolved_hash` and `inputs_digest`.
3. `hmac.compare_digest` against the token. If they don't match → `PreviewTokenError("config or spreadsheet changed since preview — run preview_* again")`.
4. Reject if `now - issued_at > 30 min` (configurable `JIRAMATOR_MCP_TOKEN_TTL`).
5. Only then call `operations.execute_*(..., assume_yes=True)`.

**Why HMAC with a per-process random key (`secrets.token_bytes(32)` at `main()`), rather than a bare `sha256:` hash as the proposal sketched:**
- A bare hash of public inputs is something an LLM could in principle **forge or replay** from an older conversation. An HMAC token is only valid if *this* server process issued it. That is a real guarantee that a preview was run, which is the whole point of the gate.
- It's **stateless**: there's no token store, no cleanup, and nothing on disk. If the server restarts, old tokens become invalid, which is the right outcome (re-preview).
- The TTL bounds staleness of **live Jira state**. Drift in duplicates, sprints or fix versions isn't covered by the hashes; that's accepted and documented.

**What the token deliberately does *not* cover:** live Jira state (an issue edited between `preview_update` and `apply_update`, a new duplicate). The write path re-runs duplicate detection and createmeta validation anyway, so those are caught at execution time rather than by the token.

**Store the digest in the report:** `RunReport.source_digest = inputs_digest`. `resume_run` can then refuse to resume an import/update whose spreadsheet changed since the original run, unless `force=True`. This closes the F7 gap for **CLI resume too**, without changing `compute_resolved_hash`. Changing that function would invalidate every existing report's hash and force `--force` on resumes.

**`resume_run` token:** `resume_run` writes to Jira, so it is also gated. `list_run_reports` / `describe_run(report)` (read-only) return a token over `(op="resume", report_path, report.resolved_config_hash, report.source_digest)`. A dedicated `preview_resume` tool is cleaner. Recommendation: **fold it into `list_run_reports`** (one token per resumable entry) to stay within the proposal's tool budget. That decision belongs in phase planning.

### 5.2 Where Markdown rendering lives

`jiramator/preview_render.py`, pure and stdlib-only. Rules:
- Input is always a dataclass (`PlanPreview`, `PreviewReport`, `UpdatePreviewReport`, `RunReport`, `RollbackPlan`), never a console or raw payloads from the caller.
- Output is a `str` of GitHub-flavoured Markdown: a summary header (project, counts, validation state), a **duplicates** section, a **warnings** section, then tables per category. Large sets are truncated with an explicit "… N more rows" line. The `max_rows` parameter defaults to the CLI's `--preview-rows` for the CLI and something like 25 for MCP, to keep tool results inside the client's context budget.
- Escape `|` and newlines in summary cells. Summaries come from user spreadsheets.
- Never render credentials or full payloads. Field **names** are fine; ADF bodies are not (they're large and could include pasted secrets).
- **CLI:** `--markdown PATH` on `plan/import/update --dry-run` writes the file **in addition to** the existing Rich/text output. Existing output is unchanged, so no golden tests break.
- **MCP:** each `preview_*` returns `{"summary": {...structured...}, "markdown": "...", "preview_token": "..."}`. The assistant shows the Markdown to the user before asking for confirmation.

### 5.3 Non-interactive guard (stdin safety)

Add `interactive: bool = True` to `run_plan`. When `False`:
- `inputs is None` → `NonInteractiveError("PlanInputs required")`
- any `Confirm.ask` reached while `assume_yes is False` → `NonInteractiveError`
- `_resolve_sprints_exist_mode` already raises when stdin isn't a TTY. Leave it as is, but MCP should resolve `sprints_exist` explicitly (tool arg → config → board auto-detect) and **put the resolved value in the preview result**, so the user sees and confirms it.

`operations.execute_plan` always passes `interactive=False`. The CLI keeps today's interactive default.

### 5.4 Output capture for MCP

The orchestrators accept a `console` (`run_plan`, `merge_configs`, `_preflight_validate`). MCP tools create `Console(file=io.StringIO(), width=120, force_terminal=False, color_system=None)` per call and return the captured text as `log` (capped, run through `sanitize_message`). Nothing reaches stdout. `run_import`/`run_update` don't print at all.

**Guard test:** run `python -m jiramator.mcp.server` as a subprocess, do the initialize → list_tools → `list_teams` round trip, and assert every stdout line parses as JSON-RPC. That catches any future `print()`.

### 5.5 Anchoring `.jiramator/runs/` for MCP

`run_report.runs_dir() -> Path` returns `Path(os.environ["JIRAMATOR_WORKDIR"]) / RUNS_DIR` when the variable is set, and `RUNS_DIR` (relative) otherwise. `default_report_path`, `find_resumable` and the new `list_reports` use it. For the MCP server, `context.py` defaults `JIRAMATOR_WORKDIR` to the **parent of `JIRAMATOR_CONFIG_DIR`**: if configs live in `~/jiramator/configs`, runs go to `~/jiramator/.jiramator/runs`. That's the same place a user running the CLI from `~/jiramator` writes to, so the two front-ends see each other's reports.

Don't `os.chdir` in the server. It's process-global and hides bugs.

### 5.6 Duplicate detection (ISSUE-03) data flow

```
preview (dry-run or MCP preview_*):
  build payloads ──► summaries ──► duplicates.find_existing_by_summary(client)  [best-effort; offline → "not checked"]
                                         │
                                         ▼
                         PlanPreview.duplicates / PreviewReport.duplicates  → rendered in Rich + Markdown

execute:
  re-check (authoritative, live) ──► policy:
     plan epics       : duplicate epic → REUSE existing key into epic_keys (so $epic:ref resolves), record status="skipped", jira_key=existing
     plan tickets     : duplicate → skip, record status="skipped", jira_key=existing
     import rows      : unchanged behaviour (already skip+record) — now just via duplicates.py
     --allow-duplicates / allow_duplicates=True : bypass (and is part of inputs_digest)
```

Plan duplicates are only meaningful per PI. Summaries already contain `{pi_label}`/`{version}`, so a PI-scoped exact-summary match is the right key. **Note:** reusing a duplicate epic changes the rebuilt `$epic:` resolution. This must happen **before** the `final_payloads = build_all(..., epic_keys=epic_keys)` call in `_run_plan_inner`.

`skipped` entries with a `jira_key` are exactly what rollback must **not** delete (F12). Keep that status distinct.

### 5.7 Update run reports + `--resume` data flow

```
cli update / mcp apply_update
  └─► operations.execute_update(ctx, prior_report?)
        ├─ report = RunReport(operation="update", source_path=spreadsheet, source_digest=digest,
        │                     params={key_column, sheet_name, max_rows},
        │                     resolved_config_hash=compute_org_hash(org), team_name=f"update:{stem}")
        ├─ drift: prior.resolved_config_hash != current or prior.source_digest != digest → DriftError unless force
        ├─ run_update(rows, ..., report=report, report_path=path, prior_report=prior)
        │     per row: skip if prior has template_key "updated:<KEY>" with status "updated"
        │              else client.update_issue → _record("updated"|"failed"|"skipped") → _persist()
        │     except BaseException: ended_at + error_info → _persist → re-raise   (mirror run_import)
        └─ finalize status (success/partial/failed), persist
```

Delete `_update_report_from_result` from cli once the counts stay identical (`updated/skipped/failed`). Keep its `fields=[...]` per-issue list; it's what makes update reports auditable.

### 5.8 Rollback (FOUND-04) data flow

```
rollback <report.json | --latest>  (cli; preview by default)
  └─► operations.preview_rollback(report_path)
        ├─ load report (+ follow the resume chain? NO — see note) 
        ├─ refuse if report.operation in {"update","rollback"}  (no before-values recorded → cannot undo an update)
        ├─ rollback.build_rollback_plan(report): created-only, de-dup keys,
        │    order: per_sprint, per_release, imported → epics last
        └─ RollbackPlan → Rich + Markdown preview (+ token for MCP)
  └─► operations.execute_rollback(plan) (with --yes / token)
        ├─ new RunReport(operation="rollback", rollback_of=<path>)
        ├─ for key in plan: client.delete_issue(key) → record "deleted" | "skipped"(not_found) | "failed"(403 etc.), persist per issue
        └─ finalize; original report is NOT mutated (append-only audit trail)
```

Resume chain note: a resumed plan report already carries forward every issue created by earlier runs (`run_plan` pre-populates `report.issues` from `prior_report`). The **latest** report in a chain is therefore a complete record, so rollback of the latest report is enough, and there's no need to walk backwards. When rolling back an older report that was later resumed, warn: "a newer run (X) includes these issues."

**Update rollback is out of scope for v1.1.** It would need `IssueResult` to capture pre-update values. This is a deliberate schema decision and should be deferred.

**MCP exposure:** the milestone tool list does **not** include a rollback tool. Recommendation: ship rollback **CLI-only** in v1.1 and expose it to MCP later as `preview_rollback`/`rollback_run` behind the same token gate. Rollback deletes data, which is the highest-risk operation an LLM could trigger.

---

## 6. MCP request flow (end to end)

```
Assistant ──preview_import(team="calcs", path="C:/…/risks.xlsx")──► mcp/tools.py
   tools.py: validate args; ctx = operations.load_import_context(config_dir, team, path)
             preview = operations.preview_import(ctx, client_factory=JiraClient)   # best-effort live fields + duplicates
             token  = tokens.issue_token("import", ctx.resolved_hash, ctx.inputs_digest)
   ◄── {summary:{rows, ok, failed, mapped_columns, duplicates:[…]}, markdown:"…", preview_token:"v1.import.…", log:"…"}

User confirms ──► Assistant ──create_import(team, path, preview_token)──► tools.py
   ctx = operations.load_import_context(...)           # re-read file NOW
   tokens.verify_token("import", ctx.resolved_hash, ctx.inputs_digest, token)  → PreviewTokenError on mismatch/expiry
   outcome = operations.execute_import(ctx, client_factory=JiraClient, command=["jiramator-mcp","create_import",…])
   ◄── {status, created, skipped(duplicates), failed, report_path, markdown:render_run_report_md(outcome.report)}
```

`describe_team` and `list_teams` are read-only adapters over `load_team_config` + `merge_configs`. They return template names and counts, not raw YAML (least privilege, and smaller results).

---

## 7. Anti-patterns to avoid

### Anti-pattern 1: MCP tools that copy cli.py's import/update lifecycle
**What people do:** Paste `import_command`'s report construction into `mcp/tools.py` to "keep cli untouched."
**Why it's wrong:** You end up with two report lifecycles. Hash, status logic and error capture drift apart, and CLI↔MCP resume breaks (F5, F8).
**Do this instead:** Extract it into `operations.py` first, then make both front-ends call it.

### Anti-pattern 2: Catching `SystemExit` in the MCP adapter as the fix
**What people do:** `except SystemExit: return {"error": "aborted"}`.
**Why it's wrong:** The reason only exists as console text, and other code paths that call `sys.exit` stay landmines. `except BaseException` blocks also swallow KeyboardInterrupt and cancellation.
**Do this instead:** `PlanAborted(reason)` (Pattern 3). Keep a last-resort `SystemExit` → tool-error conversion in `server.py` only as a backstop, with a test asserting it never triggers.

### Anti-pattern 3: Using `compute_resolved_hash` alone as the preview token
**What people do:** Follow the proposal literally: `preview_token = "sha256:" + compute_resolved_hash(...)`.
**Why it's wrong:** It's blind to spreadsheet edits (F7) and doesn't cover `sprints_exist` or duplicate policy. It's also forgeable and replayable.
**Do this instead:** HMAC over `(op, resolved_hash, inputs_digest, issued_at)` (§5.1).

### Anti-pattern 4: Changing `compute_resolved_hash` to include rows
**Why it's wrong:** Every existing import report on disk would mismatch, so users get `ConfigDriftError` on their next `--resume` and are trained to use `--force`.
**Do this instead:** Add a separate `source_digest` field and check it alongside the hash.

### Anti-pattern 5: Rollback deleting every `jira_key` in a report
**Why it's wrong:** Import `skipped` rows (and plan duplicates from v1.1 onward) record keys of **pre-existing** issues. Deleting them destroys work jiramator never created.
**Do this instead:** Delete only `status == "created"`, and only from `operation in {"plan","import"}`.

### Anti-pattern 6: Rendering Markdown from Rich output
**What people do:** Use `Console(record=True)` + `export_text()` and wrap it in a code fence.
**Why it's wrong:** It isn't real Markdown (tables become box-drawing characters), it breaks in chat clients, and it couples the preview format to terminal width.
**Do this instead:** Write pure renderers over dataclasses (Pattern 2).

---

## 8. Scaling considerations

This is a single-user local tool, so the realistic limits are Jira API limits and LLM context size, not server load.

| Concern | Realistic size | Approach |
|---|---|---|
| Tool-result size | A 500-row import preview | Return counts + the first N rows + Markdown truncated with "… N more". Point to `--markdown` export for the full set. |
| Duplicate search | Plan ~25–60 summaries; import up to hundreds or thousands | Batch about 50 summaries per JQL, and page with `nextPageToken` on `/search/jql`. Exact-match filtering already happens client-side. |
| Rollback | Up to ~60 deletes (plan) / hundreds (import) | Sequential deletes with the existing retry session, persisting the report per issue. No bulk-delete endpoint is needed. |
| Long `create_plan` calls | Tens of seconds | Acceptable for stdio. Run sync work so it doesn't block the transport (follow the SDK's threading model for sync tools; check against the pinned version in STACK.md). |

---

## 9. Integration points summary

### External
| Service | Pattern | Notes |
|---|---|---|
| Jira REST `DELETE /rest/api/3/issue/{key}` | New `JiraClient.delete_issue` | Needs the "Delete Issues" project permission, which is often **not** granted to regular users. 403 must give a clear message and be recorded as `failed`, not crash the run. |
| Jira `POST /rest/api/3/search/jql` | Existing, batched | `~` is a fuzzy text match; keep the client-side exact filter. |
| MCP client (Copilot / Claude Desktop) | stdio, `jiramator-mcp` console script | Credentials come in via the client config's `env` block. Never accept them as tool args. |

### Internal boundaries
| Boundary | Communication | Notes |
|---|---|---|
| `cli.py` ↔ `operations.py` | Direct call; `client_factory` injected | cli maps `JiramatorError` → `_fail`. |
| `mcp/tools.py` ↔ `operations.py` | Direct call; capturing Console | Same functions, `interactive=False`. |
| `mcp/tools.py` ↔ `mcp/tokens.py` | Pure | The server key lives in a module-level variable set by `server.main()`. |
| `operations.py` ↔ `planner/importer/updater` | Direct call | Orchestrators gain `report`/`prior_report` params (updater) and typed exceptions (planner). |
| `operations.py` ↔ `preview_render.py` | Pure | Called by both front-ends; the CLI only when `--markdown` is passed. |
| `rollback.py` ↔ `run_report.py` | Reads `RunReport`, writes a new one | The original report is never mutated. |

---

## 10. Suggested build order (dependency-aware)

```
A  Core seams ───────────┬──► B  update reports + --resume ──┬──► F  MCP write tools + tokens + resume_run
   (operations.py,       │                                    │
    errors.py, planner   ├──► C  Markdown renderer + --markdown┤
    PlanPreview/raise,   │                                    │
    RunReport fields,    ├──► D  duplicate detection ─────────┤
    runs_dir)            │                                    │
                         └──► E  MCP read-only (needs A, C) ──┘
                              G  rollback (needs A + RunReport.operation; independent of MCP) 
                              H  docs (after E/F/G)
```

| Step | Content | Depends on | Why here |
|---|---|---|---|
| **A. Core seams (no user-visible change)** | `errors.py`; `operations.py` with `load_*_context` + `execute_import`/`execute_update` lifted from cli (with `client_factory`); planner `build_plan_preview` + `PlanPreview`, `sys.exit` → `PlanAborted`, `run_plan` returns a result, `interactive` guard; `RunReport` additive fields + `compute_inputs_digest` + `runs_dir()` + `list_reports`. | — | Every later feature needs structured previews, typed errors and a shared lifecycle. Doing it once, behind an unchanged CLI and the existing 710-test suite, is the safest refactor. |
| **B. Update run reports + `--resume`** | Per-row persistence in `run_update`, stable keys, `compute_org_hash`, source digest, CLI `--resume/--force`. | A | `resume_run`/`list_run_reports` must cover all three commands (milestone goal). It is also the smallest end-to-end user of the new `operations` lifecycle, so it proves the extraction. |
| **C. Markdown preview export (ISSUE-05)** | `preview_render.py` + `--markdown PATH` on all dry-runs. | A (needs `PlanPreview`) | MCP `preview_*` results depend on it, so build it before E. Low risk, and can run in parallel with B. |
| **D. Duplicate detection (ISSUE-03)** | `duplicates.py`, batched search, plan epic reuse/ticket skip, import preview surfacing, `--allow-duplicates`, rendering in C's Markdown. | A, C | Must land **before MCP writes (F)**: an assistant retrying a timed-out `create_plan` is the most likely duplicate source. |
| **E. MCP read-only** | `[mcp]` extra, `jiramator-mcp`, `context.py`, `list_teams`, `describe_team`, `preview_plan/import/update` (with tokens issued but no write tools yet), stdio smoke test. | A, C (D adds duplicates to previews) | It's safe to dogfood straight away, and it validates config-dir/workdir anchoring and the stdout-clean guarantee before anything can write. |
| **F. MCP write tools** | `tokens.verify`, `create_plan`, `create_import`, `apply_update`, `list_run_reports`, `resume_run`. | B, D, E | Needs update reports (B) for `resume_run` parity, dedup (D) for safety, and the read side (E) for tokens. |
| **G. Rollback (FOUND-04)** | `jira_client.delete_issue`, `rollback.py`, CLI `rollback` (preview by default, `--yes`). | A (`operation` field), and B if update reports should be refused cleanly | Independent of MCP, so it can run in parallel with E/F. Keep it CLI-only in v1.1 (§5.8). |
| **H. Docs** | MCP client registration (Copilot + Claude), `JIRAMATOR_CONFIG_DIR`/`JIRAMATOR_WORKDIR`, token semantics, rollback permissions, AGENTS.md architecture table update (sixth front-end layer + `operations.py`). | E, F, G | Documents what actually shipped. |

**Research flags for phases:**
- **A:** Needs careful planning, not external research. The cli → operations move touches the most-patched test targets (F13). Plan an explicit test-migration task.
- **E/F:** Need phase-level research on the **pinned MCP SDK version's API**: tool registration, structured output, how sync tools are run, and error-result shape. The SDK moved to 2.x and this document intentionally doesn't depend on its API.
- **G:** Verify against the live Jira instance that the target users actually have *Delete Issues* permission. If not, rollback may need to fall back to a "transition to Won't Do + label" mode, which is a scope decision.
- **B, C, D:** Standard patterns that mirror existing `run_import` code. Unlikely to need research.

---

## Sources

- Source read in full or in part at v1.3.0: `jiramator/run_report.py` (all), `updater.py` (all), `importer.py` (all), `planner.py` (`PlanInputs`, prompts, `_resolve_sprints_exist_mode`, `_display_preview`, `_validate_payloads_against_jira`, `_preflight_validate`, `run_plan`, `_run_plan_inner`, `_bulk_create_with_resume`), `cli.py` (`_fail`, `_load_prior_report`, `_update_report_from_result`, `plan`, `import_command`, `update_command`), `jira_client.py` (`find_issue_keys_by_summaries`, `update_issue`), `config_merge.py` (console usage), `pyproject.toml`. Confidence: HIGH.
- Repo greps: no `print()` or stdout writes in `jiramator/`; test patch-target counts in `tests/`. Confidence: HIGH.
- `AGENTS.md`, `.planning/PROJECT.md`, `docs/mcp-server-proposal.md` (design baseline; its `sha256:` token sketch is superseded by §5.1). Confidence: HIGH.
- PyPI `mcp` package index: latest 2.3.0, with a 1.x → 2.x major-version line present. SDK API details are deferred to STACK.md / phase research. Confidence: MEDIUM.
- Jira Cloud REST v3 delete-issue / search-jql semantics (DELETE issue, 404 on missing, permission-gated; `/search/jql` POST with token paging). This is from training knowledge and wasn't re-verified this session. Confidence: MEDIUM. Verify in phase G/D.

---
*Architecture research for: jiramator v1.1 MCP Server milestone*
*Researched: 2026-10-16*
