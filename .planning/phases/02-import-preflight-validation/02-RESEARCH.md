# Phase 2: Import Preflight Validation - Research

**Researched:** 2026-10-09
**Domain:** Python CLI (click + rich + requests), Jira Cloud REST v3 createmeta, existing jiramator import pipeline
**Confidence:** HIGH for codebase findings (every claim read this session, with file:line refs). MEDIUM for Jira API shapes (official OpenAPI spec, fetched this session). LOW (`[ASSUMED]`) for live-Jira behaviour that can't be probed offline.

## Summary

Everything this phase needs already exists, split across `plan` and `import`. `payload_validator.validate_ticket_payload()` already does the three checks the phase requires: missing required fields, ADF-vs-plain text, and invalid option values. `JiraClient.get_createmeta_issue_types()` and `get_createmeta_fields()` already page correctly (the 1.2.6 fixes). `run_import()` already computes the resume skip set before it creates anything. The work is to wire these together for `import`, add three caller options to the validator (D-07, D-10, plus a "treat these as present" set for D-06), and change the CLI's exit code and report semantics (D-01, D-03, D-11).

The biggest planning risk is **test churn, not the algorithm**. About 20 existing live `run_import` tests (in `tests/test_importer.py`, `tests/test_importer_report.py`, `tests/test_import_integration.py` and `tests/test_import_cli.py`) pass a bare `MagicMock()` client. I verified that iterating `MagicMock().get_createmeta_issue_types(...)` yields `[]`. Under D-02 and D-05, that means every row becomes "issue type 'Risk' is not available", so every one of those tests would abort. `tests/test_cli_e2e.py::FakeJiraClient` has no `get_createmeta_issue_types` or `get_createmeta_fields` at all, and its import org config has no issuetype default. A shared test helper that stubs createmeta is therefore a Wave-0 prerequisite.

The second risk is keeping `plan` byte-identical. `plan`'s tests mock `get_createmeta_fields_by_type_name` (`tests/test_planner.py:382,475,518,568,597,634,854,872`; `tests/test_planner_report.py:157,603`; `tests/test_cli_e2e.py:89`). D-02 says import must fetch the issue-type list **once** and match names locally, which means calling `get_createmeta_issue_types` and `get_createmeta_fields` directly. So **do not lift `planner._validate_payloads_against_jira` into shared code**. Leave `planner.py` untouched and build an import-specific orchestrator.

**Primary recommendation:** Add a structured-problem API to `payload_validator.py`, with `validate_ticket_payload` kept as a thin wrapper so the strings `plan` sees stay byte-identical. Put a new `jiramator/import_preflight.py` module next to it to own the issue-type list fetch, the per-type schema cache, the unavailable-vs-row-problem split, the column mapping and rendering. Call it from `run_import` right after the resume carry-forward and initial `_persist()`, and before `find_issue_keys_by_summaries`. Return the outcome on `ImportRunResult.preflight` and let `cli.import_command` own the printing, exit code and report status.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All decisions are `[auto]`: chosen by the agent while the user was away. They were revised on 2026-10-09 after an adversarial review by gpt-5.5; see `02-DISCUSSION-LOG.md` § Adversarial review.

#### Live-run failure policy
- **D-01:** `[auto]` If preflight finds any problem rows, a live `import` aborts **before creating anything**: it lists every failing row and exits 1. Nothing is written in that case, matching `plan`'s `_preflight_validate` hard stop. The run report records `error.type = "Aborted"` with a problem summary (INV-04 pattern; see D-11 for the full list). This is a deliberate change to the default: today's live import is row-by-row partial-create (`importer.py` ~L407-505, CLI status `partial`). There is no partial "create the valid rows" mode in this phase. — **Reversibility:** costly — a future `--skip-invalid` to restore partial creation would need explicit report-status, resume and test semantics, not just a flag.
- **D-02:** `[auto]` Separate **Jira-unavailable** failures from **row/schema** problems:
  - Errors fetching the project's issue-type list or a schema (auth/permission, network/`RequestException`, Jira 5xx) mean "validation unavailable". The live run warns loudly, saying that row problems may surface as Jira 400s, then proceeds, as `plan` does.
  - A row whose issue type is not creatable in the project (`get_createmeta_fields_by_type_name` raises `JiraApiError` "Issue type '…' is not available", `jira_client.py` ~L594) is a **row problem**, not a degrade. It counts toward the D-01 abort.
  - Implementation: fetch the issue-type list once and match names locally. Don't catch every `JiraApiError` as degrade.

#### Dry-run behaviour
- **D-03:** `[auto]` `import --dry-run` with credentials prints the usual mapping preview **plus** a validation section listing every failing row (not capped by `--preview-rows`). It exits **1** when problems are found and 0 when all rows pass, the same as `plan --dry-run`. **This is a deliberate backward-incompatible exit-code change.** Today the dry-run always returns 0, and `tests/test_import_cli.py` asserts that (L26/77/121/163). Planning must update those tests, plus README and CHANGELOG, and call the change out. Exit 0 is kept for "schema validation skipped" (D-04). — **Reversibility:** costly — scripts may come to rely on the new exit code; flipping it back is another breaking change.
- **D-04:** `[auto]` Reuse a single `JiraClient` for `get_fields()` and createmeta, but track the two degrade paths **separately**:
  - If `get_fields()` fails, the preview falls back to aliases only, as today.
  - If createmeta is unavailable per D-02, print `Schema validation skipped: <reason>` and exit 0 (PRE-04).
  - Without credentials, both are skipped and both messages print.
  - Row-level schema problems (D-02, D-10) are never treated as "skipped".

#### What gets validated
- **D-05:** `[auto]` Each row is validated against the createmeta schema for `team_config.project_key`. The project is fixed per team config, and multi-project sheets are out of scope. The issue type is the row's own: its Issue Type column, otherwise `bulk_create.defaults.issuetype`. `issuetype` is a `name_object`, `value_coercion.py` ~L9-12/73. Each distinct issue type's schema is fetched once and cached. A row with no resolvable issue type is a row problem.
- **D-06:** `[auto]` Deferred fields (`reporter`, `assignee`, `parent`, and the sprint field via `_DEFERRED_LOGICAL_FIELDS`) are dropped from the built payload (`importer.py` ~L159). They are resolved live only at create time, and skipped with a warning if resolution fails (~L433-496).
  - In the required-field check, a deferred field whose Jira field ID is required counts as present when the row has a non-empty raw value under a header that resolved to it. The check maps the field ID to the deferred header(s) the same way `run_import` builds `deferred_headers`.
  - Preflight makes **no** live user/issue/sprint lookups. Resolving those is Phase 3 (USER-01..04) and later.
  - When a **required** field is satisfied only by an unresolved deferred value, the validation section prints a non-blocking caveat: "required <field> depends on live <user/parent/sprint> lookup — not preflight-validated". The user then knows those rows can still 400.
  - Sub-task/`parent` cases must be tested.
- **D-07:** `[auto]` `fixVersions`: `import` never creates versions, and its values are `[{"name": …}]` (`value_coercion.py` ~L76-78). So a version name missing from createmeta `allowedValues` **is** reported for `import`.
  - Implementation: turn `_SKIP_ALLOWED_VALUES_FIELD_IDS` into a `validate_ticket_payload` keyword argument, e.g. `skip_allowed_value_field_ids`. It defaults to `frozenset({"fixVersions"})`, so `plan`'s behaviour and output stay byte-identical. `import` passes an empty set.
  - Regression tests: `plan` still accepts not-yet-created versions, and `import` rejects unknown version names.
- **D-08:** `[auto]` Ordering and scope:
  - In `run_import`, compute the resume prior-created skip set **before** preflight. Schema-validate only rows that built successfully and won't be skipped on resume.
  - Dry-run without resume validates every row that built successfully.
  - Rows that fail at build time (e.g. missing summary) keep their existing error and appear in the combined failing-rows report, but are not schema-checked.
- **D-10:** `[auto]` (new, from review) In `import`, a field that **is** in a row's payload but is **absent** from that issue type's createmeta is a row problem: "<field> is mapped from column '<header>' but is not on the create screen for <IssueType>". Today `validate_ticket_payload` silently skips such fields (`payload_validator.py` ~L133-135), and Jira rejects them at create. Make this a caller option (default off) so `plan` is unchanged.

#### Reporting format
- **D-09:** `[auto]` Group problems per row as `Row N 'summary' [IssueType]:`, with one bullet per problem, then a total: `X of Y rows have problems`.
  - Problem strings come from the validator and use Jira field display names and IDs.
  - Column names are **best-effort**. For fields that were sent, the source header comes from `RowBuildResult.resolved_columns` (header → field). For missing required fields, show the Jira name/id plus the configured alias/logical name that would map to it, if any; otherwise show "no spreadsheet column mapped to this field".
- **D-11:** `[auto]` (new, from review) Volume and persistence:
  - The console prints every failing row, with no truncation.
  - On a live abort, the full list is persisted by recording **one `IssueResult` per failing row** (`status="failed"`, error = that row's joined problems, sanitized via `sanitize_message`), because `abort_info` caps the run-level message at 2,000 characters. The run-level `error` carries the summary. Rows that pass get no entry, since they weren't attempted.
  - A following `--resume` revalidates and attempts every row. Nothing was created, so the skip set is empty.
  - `--max-rows` limits the rows validated, the same as built.

### the agent's Discretion
- Where the shared "validate many payloads" helper lives. One option is to lift `planner._validate_payloads_against_jira` into `payload_validator` as a payload-list API used by both callers, keeping `plan` output byte-identical.
- The exact console styling. Follow the existing Rich `[red]•[/]` / `[yellow]⚠` conventions.
- Test layout (`tests/test_importer*.py`, `tests/test_import_cli.py`), following AGENTS.md mocking rules.

### Deferred Ideas (OUT OF SCOPE)
- `--skip-invalid` / create-valid-rows-only mode (see D-01). Revisit if users ask for it.
- Previewing ambiguous user values in dry-run is Phase 3 (USER-04).
- Validating `update` payloads against editmeta. Not in this milestone.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PRE-01 | `import --dry-run` with credentials checks every row's payload against Jira's createmeta schema for its project and issue type, and lists each row's missing required fields before anything is written | Validator required-field check (`payload_validator.py:117-127`); per-row issue type from the payload (`importer.py:170` `_apply_defaults`); issue-type list + fields endpoints (`jira_client.py:487-573`); D-06 deferred mapping (§ Pattern 3); SC1 fixture (§ Validation Architecture) |
| PRE-02 | The same preview reports select/option values Jira will reject, and plain-text values where Jira expects ADF | Validator ADF check (`payload_validator.py:137-143`) and allowedValues check (`:145-152`); D-07 kwarg; unknown-type pass-through in `value_coercion.py:101` means unmapped paragraph fields reach the validator as plain `str`, so they are caught |
| PRE-03 | A live `import` runs the same check before creating anything and reports every failing row at once | Hook point `importer.py:338` (after resume carry-forward `:301-338`, before `:344` dedup lookup); D-11 per-row `IssueResult` via existing `_record` closure (`importer.py:327-336`); CLI abort branch (§ Pattern 5) |
| PRE-04 | Without credentials or Jira access, `import --dry-run` still previews and states that schema validation was skipped | CLI dry-run client construction `cli.py:630-660` restructured per D-04 (§ Pattern 6); `JiraClient.__post_init__` raises `ValueError` on missing creds (`jira_client.py:146-147` via `resolve_credentials`) |
</phase_requirements>

## Project Constraints (from AGENTS.md / copilot-instructions.md)

`.github/copilot-instructions.md` only defers to `AGENTS.md`. Actionable directives from `AGENTS.md`:

- Every source file starts with `from __future__ import annotations`. Use explicit `from jiramator.x import Y` imports, with no wildcards or barrels.
- Fully annotate signatures with lowercase generics. Void functions are annotated `-> None`. Use Google-style docstrings on public functions.
- Prefix private names with `_`; public constants are `UPPER_SNAKE_CASE`. Use the `# ----` section dividers.
- **All user-facing output goes through `rich.console.Console(stderr=True)`; never `print()`.** `logging` is reserved for `jira_client.py`.
- CLI-level unrecoverable errors print a Rich message, then `sys.exit(1)`. All HTTP errors are wrapped in `JiraApiError`.
- Lint with `ruff check .` (`E,F,W,I,UP,B`). **Don't run `ruff format`.**
- Tests: classes are named `Test<Component>`, functions `test_<behavior>_<expected>`. Mock HTTP via `client._session.get` returning `_mock_response`. Mock env with `monkeypatch`. **Don't mock** Pydantic, YAML loading or builder logic; use real inputs.
- **Patch symbols where they are used** (e.g. `jiramator.importer.build_preview_report`). Ruff removes unused re-imports, which breaks patches aimed at them.
- Never store credentials in config. Dry-run degrade behaviour is documented in AGENTS.md § Credentials. **AGENTS.md's sentence "`import --dry-run` opportunistically fetches `client.get_fields()`…" must be updated by this phase.**
- Read-only rule (Phase 1 D-03): never write under `~/dev/work_projects`. Don't copy gitignored `configs/org/` or `configs/teams/` values.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fetch issue-type list + per-type field schema | Client (`jira_client.py`) | — | All HTTP stays in the client (AGENTS.md layer table); the methods already exist |
| Pure payload-vs-schema checks (required / ADF / options / off-screen / assume-present) | `payload_validator.py` (pure) | — | Already pure and no-I/O by design (module docstring L1-12) |
| Per-row orchestration: which rows, which issue type, schema cache, unavailable-vs-row split, deferred mapping, column mapping | New `import_preflight.py` | `importer.run_import` calls it | `importer.py` is already 578 lines; keeps `planner.py` untouched |
| Resume skip set, per-row `IssueResult`, report persistence on abort | `importer.run_import` | `cli.import_command` (status / ended_at / exit) | `run_import` already owns `_record` / `_persist`; CLI owns the report lifecycle (`cli.py:616,662`, "cli owns the lifecycle for import") |
| Console rendering, exit codes, degrade messages | `cli.import_command` + a `render_*` function | — | Same pattern as `render_preview_report` / `render_import_execution_report` |

## Standard Stack

No new packages. Everything is already a dependency (`pyproject.toml:12-30`) `[VERIFIED: pyproject.toml read this session]`.

| Library | Use in this phase |
|---------|-------------------|
| requests | Already used by `JiraClient`. Catch `requests.exceptions.RequestException` as "unavailable", because the client does **not** wrap transport errors (HYG-05 is Phase 4) |
| rich | Console output; use `rich.markup.escape` for user/Jira text (see Pitfall 6) |
| click | `CliRunner` in tests; exit codes |
| pytest 8 / pytest-mock | Tests (installed into `.venv` this session: 699 passed baseline) |

**Installation:** none. (The worktree `.venv` was empty. I ran `pip install -e ".[dev]"`, which is the documented dev install, and the baseline is `699 passed`; `ruff check .` reports "All checks passed!".)

## Package Legitimacy Audit

Not applicable: this phase installs no external packages.
**Packages removed due to [SLOP] verdict:** none. **Packages flagged [SUS]:** none.

## Jira createmeta API shape (what the validator consumes)

Source: the official Jira Cloud v3 OpenAPI spec, `https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json`, fetched this session `[CITED]`.

- `GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes` returns `PageOfCreateMetaIssueTypes`: `{issueTypes: [...], startAt, maxResults, total}`. Each item has `id`, `name`, `subtask`, etc. (spec example: `{"id":"1","name":"Bug","subtask":false,...}`). `maxResults` defaults to 50, max 200. There is no `isLast` key, matching the comment at `jira_client.py:514-516`.
- `GET /rest/api/3/issue/createmeta/{projectIdOrKey}/issuetypes/{issueTypeId}` returns `PageOfCreateMetaIssueTypeWithField`: `{fields: [FieldCreateMetadata], startAt, maxResults, total}`. The spec also lists a `results` array; jiramator reads `fields` (`jira_client.py:562`), the 1.2.6 fix.
- `FieldCreateMetadata` has required keys `fieldId`, `key`, `name`, `operations`, `required`, `schema`; optional keys `allowedValues` (array, **items untyped**), `hasDefaultValue`, `defaultValue`, `autoCompleteUrl`, `configuration`.
- `JsonTypeBean` (`schema`) has required `type`, plus optional `items` (element type when `type == "array"`), `system`, `custom` (custom field type URI), `customId`, `configuration`.
- The old `GET /rest/api/3/issue/createmeta` is marked `deprecated: true` in the spec. jiramator doesn't use it.

`allowedValues` entry shapes are not specified in the spec. From the validator code and common Jira Cloud behaviour `[ASSUMED]`:

| Field kind | `schema` | `allowedValues` entry | Payload jiramator builds |
|---|---|---|---|
| single select | `type: option`, `custom: …:select` | `{id, value}` | `{"value": "X"}` (`single_select`, `value_coercion.py:83-86`) |
| multi select / checkboxes | `type: array, items: option` | `{id, value}` | `[{"value": …}]` |
| cascading select | `type: option-with-child` | `{id, value, children: [{id, value}]}` | not produced by coercion; if hand-built, **child is not validated** (verified below) |
| fixVersions / versions | `type: array, items: version` | `{id, name, released, archived, …}` | `[{"name": …}]` |
| priority / issuetype / components | `priority` / `issuetype` / `array of component` | `{id, name}` | `{"name": …}` |
| labels | `type: array, items: string` | none | `["a","b"]`, no option check |
| paragraph (textarea) | `type: string`, `custom: …:textarea` | none | ADF doc when `adf_text`, else raw `str`, which is flagged |

**"Repositories" (`customfield_11941`):** the tracked `configs/org.example/example.yaml` and `acme.yaml` map `repositories: customfield_11941` with `field_types.repositories: adf_text` and alias `Repositories: repositories` `[VERIFIED: configs/org.example/acme.yaml:35,73,98 — "repositories:         customfield_11941", "Repositories: repositories", "repositories: adf_text"]`. So in this org it is a **paragraph/textarea field** sent as ADF. `validate_ticket_payload` covers it fully: required (missing → flagged) and ADF (plain → flagged). A plugin-backed or cascading Repositories field would only get the required check `[ASSUMED]`.

Validator behaviours I verified by running code this session (`.venv/bin/python`):
- `{"issuetype":{"name":"risk"}}` against allowedValues `[{"name":"Risk"}]` produces `"'Issue Type' (issuetype): value {'name': 'risk'} is not one of the allowed options"`. Matching is **case-sensitive** (see Pitfall 2).
- Cascading `{"value":"A","child":{"value":"ZZ"}}` produces `[]`: the child isn't checked.
- A plain string `"B"` sent to a select produces `"... value 'B' is not one of the allowed options (A)"`.
- `fixVersions` with an unknown name and the default skip produces `[]`; a missing required `fixVersions` produces `"missing required field 'Fix versions' (fixVersions)"`.

## Architecture Patterns

### System Architecture Diagram

```
CSV/XLSX ─► read_spreadsheet (max_rows) ─► rows
                                            │
cli.import_command ── JiraClient(org)? ─────┼── ValueError ─► "Preview based on field_aliases only" + "Schema validation skipped: no credentials"
         │ get_fields() (degrade #1)        │
         ▼                                  ▼
   run_import(rows, client, dry_run, prior_report, report…)
         │
         ├─► build_preview_report ─► RowBuildResult[] (payload, resolved_columns, error)
         ├─► prior_created skip-set + carry-forward (live; dry-run if --resume, see OQ-2)
         ├─► import_preflight.run_preflight(client, project_key, row_results, rows, skip_keys, org_config)
         │       ├─ rows_to_check = built OK ∧ not resume-skipped
         │       ├─ issuetype per row = payload.fields.issuetype.name  (missing → row problem)
         │       ├─ client.get_createmeta_issue_types(project)  ──JiraApiError/RequestException──► UNAVAILABLE(reason)
         │       ├─ casefold match → id     (no match → row problem "not available… (available: …)")
         │       ├─ client.get_createmeta_fields(project, id)  cached per id ──error──► UNAVAILABLE(reason)
         │       ├─ payload_validator.find_payload_problems(fields, meta, skip_allowed=∅,
         │       │        report_off_screen=True, assume_present=deferred-required ids)
         │       └─ map field_id → header(s) / alias(es) / "no spreadsheet column mapped"
         │     returns PreflightResult{status: passed|problems|unavailable|skipped, rows[], caveats[]}
         │
         ├─ dry_run ─► return ImportRunResult(preview, preflight=…)
         ├─ live & problems ─► _record(tk,"failed",error=joined problems) per failing row (+ build failures),
         │                     report.error = abort_info(summary); _persist(); return ImportRunResult(aborted)
         ├─ live & unavailable ─► warning carried on result; continue
         └─ live & passed ─► find_issue_keys_by_summaries … deferred lookups … create_issue loop (unchanged)
                                            │
cli: render_preview_report + render_preflight_report ─► exit 1 if problems (dry-run & live) else 0
```

### Recommended Project Structure

```
jiramator/
├── payload_validator.py   # + PayloadProblem dataclass, find_payload_problems(...); validate_ticket_payload wraps it
├── import_preflight.py    # NEW: PreflightResult, run_preflight(), render_preflight_report()
├── importer.py            # run_import hook; ImportRunResult.preflight field
├── cli.py                 # dry-run client reuse + degrade messages; abort/exit handling
└── planner.py             # UNCHANGED
tests/
├── test_payload_validator.py   # + kwargs tests (D-07, D-10, assume_present, structured API)
├── test_import_preflight.py    # NEW: unit tests incl. SC1 replay fixture
├── test_importer*.py, test_import_integration.py  # add createmeta stub to MagicMock clients
├── test_import_cli.py          # D-03/D-04 exit codes + messages; live abort report
└── test_cli_e2e.py             # FakeJiraClient gains createmeta methods; import config gains issuetype
```

### Pattern 1: Structured validator, string wrapper preserves `plan`

**What:** Add a `PayloadProblem` (frozen dataclass: `field_id: str`, `kind: Literal["missing_required","adf","invalid_option","off_screen"]`, `message: str`) and `find_payload_problems(fields, field_metadata, *, skip_allowed_value_field_ids=_SKIP_ALLOWED_VALUES_FIELD_IDS, report_off_screen_fields=False, assume_present_field_ids=frozenset())`. `validate_ticket_payload(fields, field_metadata, **same kwargs)` returns `[p.message for p in find_payload_problems(...)]`.

**Why:** D-09 needs to attach column names by field id. Parsing `"(customfield_11941)"` back out of message strings is fragile. With defaults unchanged, the message text and order for `plan` are identical. Keep loop order exactly as now: the missing-required pass iterates `field_metadata`, then the per-field pass iterates `fields`.

**Off-screen message (D-10):** the validator emits `f"{field_id} is not on the create screen for this issue type"`. The validator doesn't know the header or issue type, so `import_preflight` rewrites it into the D-10 wording using `kind == "off_screen"`.

**Skip set for off-screen:** `_SKIP_FIELD_IDS` (`project`) is still skipped. `issuetype` and `summary` are always in createmeta for a creatable type `[ASSUMED]`; if not, flagging them is correct.

### Pattern 2: Issue type per row, fetched once

The row's issue type is already in the payload. An `Issue Type` column resolves to `issuetype` via the alias, is coerced to `{"name": …}` (`value_coercion.py:9-10,73-74`), and is placed by `build_row_payload` (`importer.py:162-165`). Otherwise `_apply_defaults` fills `bulk_create.defaults.issuetype` (`importer.py:113-125`, `:170`), but only when the field is absent (`if jira_field is None or jira_field in fields: continue`). So read `payload["fields"].get("issuetype", {}).get("name")`. There's no need to re-resolve.

```python
# Source: pattern from jira_client.get_createmeta_fields_by_type_name (jira_client.py:575-602), split so the list is fetched once
issue_types = client.get_createmeta_issue_types(project_key)          # may raise → UNAVAILABLE
by_casefold = {str(it.get("name", "")).casefold(): it for it in issue_types}
schema_by_id: dict[str, dict[str, dict[str, Any]]] = {}
for row in rows_to_check:
    name = (row.payload["fields"].get("issuetype") or {}).get("name")
    if not name: row_problem("no issue type (no Issue Type column value and no bulk_create.defaults.issuetype)")
    match = by_casefold.get(str(name).casefold())
    if match is None: row_problem(f"Issue type '{name}' is not available for creation in project {project_key} (available: {', '.join(sorted(...)) or 'none'})")
    if match["id"] not in schema_by_id:
        schema_by_id[match["id"]] = client.get_createmeta_fields(project_key, match["id"])   # may raise → UNAVAILABLE
```

Only call `get_createmeta_issue_types` when `rows_to_check` is non-empty. That keeps the existing zero-row dry-run CLI tests at exit 0 with no createmeta calls.

### Pattern 3: Deferred-field "present" mapping (D-06)

`run_import` builds `deferred_headers` across **all** rows' `resolved_columns` (`importer.py:358-367`). For per-row presence you need the per-row form:

- `build_row_payload` only records `resolved_columns[header]` for **non-empty** cells (`importer.py:144-153`: `if raw_value is None or raw_value == "": continue` comes before `resolved_columns[source_header] = resolved`). But whitespace-only cells *are* recorded, and `run_import` treats them as empty (`raw_value.strip()`, e.g. `importer.py:443`). So: a deferred field id `F` is present for a row iff some `(header, resolved)` in `row_result.resolved_columns` has (`resolved.jira_field == F` and `F in _DEFERRED_FIELDS`) or (`resolved.logical_name in _DEFERRED_LOGICAL_FIELDS` and `resolved.jira_field == F`), **and** `str(source_row[header]).strip()` is non-empty.
- Pass those ids as `assume_present_field_ids` so the required check is satisfied. Then, for each such id that is `required` in that type's meta, emit the D-06 caveat (`user` for reporter/assignee, `parent` for parent, `sprint` for the sprint field). Caveats are non-blocking and don't count toward "X of Y rows have problems".
- Extend D-10 (recommended): a deferred field with a raw value whose id is **not** in the type's createmeta (e.g. an `Assignee` column for an issue type whose create screen lacks assignee) will 400 at create. Report it as off-screen too. The deferred id is known without any lookup.
- Sub-task: the `issueTypes` items carry `subtask: true` `[CITED: OpenAPI example]`. Whether createmeta lists `parent` as `required: true` for sub-tasks is `[ASSUMED]`. Test both: a parent column present (caveat, no problem) and absent (missing required `parent`).

### Pattern 4: Column mapping for messages (D-09)

- **Sent field:** invert `row_result.resolved_columns` to `jira_field -> [headers]`. If the field came from `bulk_create.defaults` (not in `resolved_columns`), label it `from bulk_create.defaults`.
- **Missing required field:** compute once per run: `{resolve_field_name(alias, org_config).jira_field: [alias…] for alias in org_config.bulk_create.field_aliases}` (`field_resolver.py:89-157`). Use `jira_fields=None` here so it's deterministic. If the id is in the map, say `(map a column named 'Fix Version' / 'Fix Versions' / 'fix_version')`; else `no spreadsheet column mapped to this field`. For example, with the example config `fixVersions` maps from `fix_version`, `Fix Version`, `Fix Versions`, and `customfield_11941` from `Repositories`.

### Pattern 5: Live hook in `run_import` and abort persistence (D-01, D-08, D-11)

Insert after `_persist()  # initial write reflecting prior-carry-forward` (`importer.py:338`) and **before** `seen_summaries = client.find_issue_keys_by_summaries(...)` (`importer.py:344`):

1. `skip_keys = set(prior_created)` (already computed at `:301-325`).
2. `pre = run_preflight(...)`.
3. If `pre.status == "problems"`: for each row in `preview.row_results` order, if the row failed to build, `_record(tk, "failed", error=result.error)`; if it has schema problems, `_record(tk, "failed", error="; ".join(problem messages))`. `_record` already sanitizes via `sanitize_message` (`importer.py:330-332`). Set `report.error = abort_info(f"Preflight found problems in {n} of {m} row(s). No issues were created.", secrets=secrets)`. `abort_info` is not imported in importer yet; add the import from `run_report`. Then `_persist()` and return `ImportRunResult(preview, created=[carried-forward…], skipped=[], failed=[...], preflight=pre)`.
4. If `"unavailable"`: keep going and carry `pre` on the result so the CLI prints the loud warning.

Carried-forward `created` entries from a resumed prior run are already in `report.issues` by step 2. **Keep them.** A later `--resume` must still skip those rows. D-11's "skip set is empty" only holds when the aborted run wasn't itself a resume.

**CLI side** (`cli.py:676-718`): after `run_import` returns, if `result.preflight` has problems, then: print the preview and preflight report; set `report.ended_at`; keep `report.status = "failed"` (the default; **do not** run the `partial` branch at `:707-713`); `write_report_atomic`; print `Aborting — fix the rows above. No issues were created.`; `sys.exit(1)`. Returning a result (rather than raising) avoids the `except (ValueError, JiraApiError)` / `except BaseException` arms at `cli.py:688-698`, which would overwrite nothing (`error` is already set) but would print `Import error:`. `find_resumable` treats `failed` as resumable (`run_report.py:395-396`), so `--resume` auto-discovers the aborted report.

### Pattern 6: CLI dry-run client reuse (D-03, D-04, PRE-04)

Restructure `cli.py:630-660`:

```python
# Source: existing cli.py:638-649 degrade messages, split per D-04
client = None; jira_fields = None
try:
    client = JiraClient(org_config)
except ValueError as exc:
    console.print(f"[yellow]⚠ Preview based on field_aliases only (no Jira credentials available): {escape(str(exc))}[/]")
    console.print(f"[yellow]⚠ Schema validation skipped: no Jira credentials available ({escape(str(exc))})[/]")
if client is not None:
    try:
        jira_fields = client.get_fields()
    except (JiraApiError, requests.exceptions.RequestException) as exc:
        console.print(f"[yellow]⚠ Preview based on field_aliases only (could not reach Jira): {escape(str(exc))}[/]")
result = run_import(rows, ..., client=client, dry_run=True, prior_report=prior_report)
console.print(render_preview_report(result.preview, preview_rows=preview_rows))
# then render preflight: skipped/unavailable → "Schema validation skipped: <reason>", exit 0; problems → full list, exit 1; passed → "✓ …", exit 0
```

`run_import(dry_run=True)` must stop returning before preflight (today it returns at `importer.py:294-295`). Run preflight when `client is not None`. Keep `client=None` legal for dry-run (`tests/test_importer.py:657`, `tests/test_import_integration.py:97`), which gives preflight `status="skipped"`.

### Anti-Patterns to Avoid

- **Lifting `planner._validate_payloads_against_jira` and switching `plan` to `get_createmeta_issue_types`:** this breaks about 10 plan tests that mock `get_createmeta_fields_by_type_name`, and risks plan output drift. Leave `planner.py` alone.
- **Catching every `JiraApiError` as "unavailable":** D-02 forbids it. Only the two fetch calls are in the unavailable `try`. Issue-type mismatch is decided locally.
- **Calling `get_createmeta_fields_by_type_name` per type:** it re-fetches the whole issue-type list every call (`jira_client.py:588`).
- **Running preflight after `find_issue_keys_by_summaries` or the parent/sprint lookups:** that wastes Jira reads before an abort.
- **Printing raw summaries or Jira text through `console.print`:** Rich markup injection (Pitfall 6).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Required / ADF / option checks | New validator | `payload_validator` + kwargs | Already tested (`tests/test_payload_validator.py`, 18 tests) |
| Createmeta paging | New HTTP loop | `get_createmeta_issue_types` / `get_createmeta_fields` | 1.2.6 pagination bugs already fixed and tested (`tests/test_jira_client.py:515-625`) |
| Header → field resolution for aliases | String matching | `field_resolver.resolve_field_name` | Handles normalized aliases and custom_fields |
| Redaction / capping of per-row errors | Ad-hoc | `_record` → `sanitize_message`; `abort_info` | INV-04 / WR-03 semantics |
| Report atomic write | `json.dump` | `write_report_atomic` | Atomic + tmp cleanup |
| Rich escaping | regex | `rich.markup.escape` | Already used in `planner.py:36` |

## Common Pitfalls

### Pitfall 1: Existing live tests use bare `MagicMock()` clients, so every row aborts
**What goes wrong:** `MagicMock().get_createmeta_issue_types()` iterates as `[]` (verified). The type list is empty, so "Risk not available" fires and every live `run_import` test aborts with `created == []`.
**Affected:** `tests/test_importer.py:346-655` (12 tests), `tests/test_importer_report.py:87-470` (~11 tests), `tests/test_import_integration.py:196`, `tests/test_import_cli.py:192-238` (`test_live_mode_continues_after_row_failure_and_reports_summary`: its fake `row_results` payloads have **no issuetype**, so it needs `issuetype` added as well as the stub), and `tests/test_cli_e2e.py:337` (`FakeJiraClient` lacks the methods, so `AttributeError` propagates through `except BaseException`; its org config has no `defaults.issuetype`).
**How to avoid:** a Wave-0 helper, e.g. `tests/conftest.py::stub_createmeta(client, {"Risk": {}})`, setting `get_createmeta_issue_types.return_value=[{"id":"1","name":"Risk"}]` and `get_createmeta_fields.return_value={}`. Add the two methods to `FakeJiraClient` and add `bulk_create: {defaults: {issuetype: Task}}` (or an Issue Type column) to its import config.

### Pitfall 2: Case-sensitive issuetype allowedValues produce false positives
Issue type lookup is casefold (`jira_client.py:589-592`), but the validator's option check is exact-case (verified: `risk` vs `Risk` is flagged). If createmeta includes `allowedValues` on the `issuetype` field `[ASSUMED]`, a sheet saying `risk` gets an extra problem. Whether Jira itself accepts `{"name":"risk"}` is `[ASSUMED]` (unknown). **Recommendation:** import passes `skip_allowed_value_field_ids=frozenset({"issuetype"})`, since issuetype validity is already established by the local list match (D-02). Note this still differs from D-07's "empty set"; see OQ-1.

### Pitfall 3: Whitespace-only cells become a "present" but empty ADF doc
Verified: `{"Repositories": "  "}` builds `customfield_11941: {"type":"doc",…"text":""}`. The required check sees a non-empty dict and passes, but Jira will likely reject it as empty or required `[ASSUMED]`. Similarly, `"  "` in a select becomes `{"value": ""}`. **Avoid:** in import, treat ADF docs whose text content is all whitespace as missing (an import-only validator option, or strip in `build_row_payload`). Add a fixture row with `" "`.

### Pitfall 4: A non-numeric `number` cell crashes the whole build
Verified: `"Overall Risk Value": "abc"` makes `build_row_payload` raise `ValueError: could not convert string to float` (`value_coercion.py:97-100` is not caught). Dry-run then dies with a traceback (`cli.py:651` has no try), and live gets `Import error:`. That contradicts "report every failing row". **Recommend** catching coercion `ValueError` per cell in `build_row_payload` and turning it into a row build error. It's a small, adjacent fix; confirm scope (OQ-4).

### Pitfall 5: Live finalization would mark an abort `partial`
`cli.py:707-713` sets `partial` whenever `failed_count > 0`. The abort path must return before that and keep `failed`, plus `error.type == "Aborted"`.

### Pitfall 6: Rich markup in summaries
Verified: `console.print("x [bold]y[/] [/link]")` raises `MarkupError`; `[bold]` in a summary is silently eaten. Render functions return plain text that `cli.py` prints via `console.print` (`cli.py:659,715`). Escape summary, header, issue type and Jira message text with `rich.markup.escape`. `[Risk]` alone happens to render literally (verified), but don't rely on that.

### Pitfall 7: Createmeta pagination and caching
Both endpoints page by `total/startAt` (no `isLast`); handled in the client. Cache by issue-type **id** after the casefold match, so `Risk` and `risk` share one fetch. With N distinct types you get 1 + N GETs. Retries (`_RETRY_STRATEGY`, 429/502/503/504 × 3, `jira_client.py:58-64`) can make an unavailable Jira take about 7 s plus 3 × 30 s timeouts before degrading. That's acceptable, but don't add your own retries.

### Pitfall 8: Mock-only confidence (STATE concern)
1.2.6 shipped validation that was a silent no-op because mocks used the wrong JSON key. This phase is mock-tested, so the plan **must** end with a human `checkpoint:human-verify`: run `jiramator import --dry-run` against real Jira on the 2026-09-02 Risk sheet shape **from the user's work clone, read-only**, and confirm all 8 problems appear. The executor must not do this (no live Jira from the agent; no writes under `~/dev/work_projects`).

### Pitfall 9: Rows dedup-skipped by summary are still validated
D-08 only excludes resume-skipped rows. In the 2026-09-02 sequence, run `184255Z` skipped rows 1/4/5/6 through **summary dedup** (`find_issue_keys_by_summaries`, `importer.py:344,427-432`), not resume. If one of those already-existing rows failed preflight (e.g. a version since archived), the whole re-run would abort even though that row would never be created. See OQ-3.

## Code Examples

### Validator kwargs (preserves plan)
```python
# Source: jiramator/payload_validator.py:95-154 (current), extended
def validate_ticket_payload(
    fields: dict[str, Any],
    field_metadata: dict[str, dict[str, Any]],
    *,
    skip_allowed_value_field_ids: frozenset[str] = _SKIP_ALLOWED_VALUES_FIELD_IDS,
    report_off_screen_fields: bool = False,
    assume_present_field_ids: frozenset[str] = frozenset(),
) -> list[str]:
    return [p.message for p in find_payload_problems(
        fields, field_metadata,
        skip_allowed_value_field_ids=skip_allowed_value_field_ids,
        report_off_screen_fields=report_off_screen_fields,
        assume_present_field_ids=assume_present_field_ids,
    )]
# In find_payload_problems: required-check treats field_id in assume_present_field_ids as present;
# `if meta is None:` → `if report_off_screen_fields: append(off_screen)`; then `continue` (as today).
```

### Report shape on live abort (fits existing schema)
```python
# Source: run_report.py:57-59 Literals — IssueStatus includes "failed"; IssueKind includes "imported"; ABORTED_ERROR_TYPE = "Aborted" (:55)
_record(tk, "failed", error="missing required field 'Fix versions' (fixVersions) — no column …; …")
report.error = abort_info("Preflight found problems in 6 of 6 row(s). No issues were created.", secrets=secrets)
_persist()
```

Verified values `[VERIFIED: jiramator/run_report.py:53-59]`, quoted verbatim: `_ERROR_MESSAGE_CAP: int = 2000`, `ABORTED_ERROR_TYPE: str = "Aborted"`, `IssueStatus = Literal["created", "updated", "skipped", "failed", "pending"]`, `RunStatus = Literal["success", "partial", "failed"]`, `IssueKind = Literal["epic", "per_release", "per_sprint", "imported", "updated"]`.

Verified deferred constants `[VERIFIED: jiramator/importer.py:94,99]`: `_DEFERRED_FIELDS = {"reporter", "assignee", "parent"}`, `_DEFERRED_LOGICAL_FIELDS = {"sprint_field"}`. Validator constants `[VERIFIED: jiramator/payload_validator.py:20,29]`: `_SKIP_FIELD_IDS = frozenset({"project"})`, `_SKIP_ALLOWED_VALUES_FIELD_IDS = frozenset({"fixVersions"})`.

## Existing tests and docs this phase touches

**Must change:**
- `tests/test_import_cli.py:192` (`test_live_mode_continues_after_row_failure_and_reports_summary`): stub createmeta and add `issuetype` to the fake payloads. It still exercises the post-preflight 400 path, which remains valid.
- All live `run_import` tests listed in Pitfall 1, plus `tests/test_cli_e2e.py` `FakeJiraClient` and its import config.

**Do not need to change, but should be strengthened** (D-03's line list is partly inaccurate): `tests/test_import_cli.py:77,121,163` are dry-run tests whose patched preview has `row_results = []`. With the "only fetch when rows exist" rule they stay exit 0. `:26` is `--help`. Add assertions: `:121` (no creds) must contain `Schema validation skipped`; `:163` (get_fields 500) must contain the aliases-only warning, and preflight must still run. Add new exit-1 tests.

**Pin `plan` byte-identity** (must stay green, unmodified): `tests/test_payload_validator.py:151` (`test_field_not_on_screen_skipped`, default off), `:157` (`test_fix_versions_allowed_values_skipped`), `:172`; `tests/test_planner_report.py:690-704` (`"Found "…"field problem(s): "…"customfield_99999"…endswith("No tickets were created.")`); and all `test_planner*.py` tests that mock `get_createmeta_fields_by_type_name`. Run `git diff --stat jiramator/planner.py` and expect it to be empty.

**Docs:**
- `README.md:157-170` (credentials paragraph: import now validates schema; dry-run exit 1 on problems).
- `README.md:318-334`, `:337-370` (import section: preflight + abort-before-create replaces "creates issues row by row").
- `README.md:470` (Troubleshooting "Not sure…" row) and the `400 Bad Request` row (`:466`).
- `CHANGELOG.md` `[Unreleased]`: a `### Changed` entry flagged **breaking**, covering the dry-run exit code and the live abort-before-create, plus `### Added`.
- `AGENTS.md` § Credentials, the paragraph about import dry-run.
- The external wiki pages "Import and Update Details" and "Run Reports and Resuming" (`README.md:445-448`) are out of repo. Flag them for the user.

## Runtime State Inventory

Not a rename/refactor phase, so this section is omitted. One related note on report compatibility: aborted reports use the existing schema (no new keys), so older jiramator versions can still load them.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `allowedValues` entry shapes per field kind (option `{id,value}`, version `{id,name,…}`) | API shape | Option check silently passes/fails wrongly; mitigated by the live smoke test |
| A2 | createmeta's `issuetype` field carries `allowedValues` (makes Pitfall 2 real) | Pitfall 2 | If absent, the skip is harmless |
| A3 | Jira's acceptance of a case-mismatched issuetype name | Pitfall 2 | Could let a 400 through if we skip and Jira is strict |
| A4 | `parent` is listed `required` in createmeta for sub-task types | Pattern 3 | Sub-task tests model the wrong shape |
| A5 | Jira rejects an empty-text ADF doc for a required paragraph | Pitfall 3 | If accepted, flagging it is a false positive |
| A6 | Repositories in other orgs could be plugin/cascading (only the required check covered) | API shape | Gaps limited to option-child validation |

## Open Questions (RESOLVED)

1. **OQ-1: issuetype allowedValues under D-07's "import passes an empty set".**
   - What we know: the type match is casefold and the option check is case-sensitive (verified).
   - Recommendation: import passes `frozenset({"issuetype"})`. Validity is already enforced by the local list match. Flag this as a small refinement of D-07 for user sign-off.
   - **RESOLVED (Plan 02-01):** adopted — import passes `skip_allowed_value_field_ids=frozenset({"issuetype"})`; fixVersions is still validated (D-07). Listed in 02-01 context as a user-reviewable assumption.
2. **OQ-2: `import --dry-run --resume`.**
   - What we know: today dry-run ignores `prior_report` (`cli.py:651-657`), and D-08 only defines dry-run *without* resume.
   - Recommendation: pass `prior_report` in dry-run and apply the same skip set, so the preview predicts the live run.
   - **RESOLVED (Plans 02-01, 02-04):** adopted (low cost) — the CLI passes `prior_report` to the dry-run `run_import`, which applies the same prior-created skip set via `_prior_created_keys`; dry-run validates exactly the rows a live resume would attempt. Tested in 02-04 Task 3 (`5 of 5 rows have problems` with row 1 created in the prior report); documented in README by 02-03 Task 3.
3. **OQ-3: should summary-dedup-skipped rows be excluded from preflight?** (Pitfall 9)
   - Recommendation: keep D-08 as written (validate them) for now. Planner should note it; changing it requires moving `find_issue_keys_by_summaries` before preflight.
   - **RESOLVED (Plan 02-03):** D-08 followed literally — dedup-skipped rows are validated and can cause the abort; recorded as a must-have edge truth and user-reviewable assumption.
4. **OQ-4: coercion `ValueError` → row build error** (Pitfall 4).
   - Recommendation: include it. It's small and directly serves "every failing row". Otherwise defer explicitly.
   - **RESOLVED (Plan 02-04 Task 2):** included — `build_row_payload` turns a coercion `ValueError` into a per-row build error (`Row N: column '<header>': could not convert value …`); the row is listed in the failing-rows report.
5. **OQ-5: one unavailable type fetch among several.**
   - Recommendation: treat the whole preflight as unavailable (simple; matches plan's all-or-nothing `try`).
   - **RESOLVED (Plan 02-01):** adopted — any issue-type-list or per-type field fetch failure makes the whole preflight `unavailable` (dry-run: skip message, exit 0; live: loud warning and proceed per 02-03).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | all | ✓ | 3.13.15 (.venv) | — |
| pytest / ruff | tests/lint | ✓ (after `pip install -e ".[dev]"` into the worktree `.venv` this session) | per pyproject (`ruff>=0.16,<0.17`) | system `pytest`/`ruff` under mise |
| Live Jira + creds | SC1 smoke test | ✗ for agent (forbidden) | — | Human checkpoint in the user's work clone, dry-run only |

## Validation Architecture

(`workflow.nyquist_validation` is `false` in config. This section is included because the orchestrator explicitly requested it.)

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ≥ 8 (+ pytest-mock), click `CliRunner` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths=["tests"]`, `pythonpath=["."]`) |
| Quick run command | `.venv/bin/python -m pytest -q tests/test_payload_validator.py tests/test_import_preflight.py tests/test_importer.py tests/test_importer_report.py tests/test_import_cli.py` |
| Full suite command | `.venv/bin/python -m pytest -q && .venv/bin/ruff check .` (baseline: 699 passed) |

### SC1 replay fixture (synthetic; never copy real summaries)
Use the real tracked configs `configs/org.example/example.yaml` + `tests/fixtures/teams/calcs.yaml` (project `CA`, `defaults.issuetype: Risk`, `Repositories → customfield_11941 adf_text`). Build a 6-row CSV/XLSX with headers `Summary, Repositories, Fix Version`:
- `Fix Version` is empty on all 6 rows.
- `Repositories` is filled on rows 1, 4, 5, 6 and empty on rows 2 and 3.

Mock the client:
- `get_createmeta_issue_types → [{"id":"10100","name":"Risk"}]`
- `get_createmeta_fields → {"summary":{required,…}, "issuetype":{required,…}, "project":{required}, "fixVersions":{"name":"Fix versions","required":True,"hasDefaultValue":False,"schema":{"type":"array","items":"version"},"allowedValues":[{"id":"1","name":"26.1.1"}]}, "customfield_11941":{"name":"Repositories","required":True,"hasDefaultValue":False,"schema":{"type":"string","custom":"com.atlassian.jira.plugin.system.customfieldtypes:textarea"}}}`

Expected: exactly 8 problems over 6 rows: `fixVersions` on every row, plus `customfield_11941` on rows 2 and 3. Output ends with `6 of 6 rows have problems`. `create_issue`, `create_issues_bulk`, `find_issue_keys_by_summaries` and `find_user_account_id` are not called.

### Phase Requirements → Test Map
| Req / SC | Behavior | Type | Automated Command | File Exists? |
|--------|----------|------|-------------------|-------------|
| PRE-01 / SC1 | Dry-run lists missing Fix versions (×6) + Repositories (rows 2,3), no writes, exit 1 | CLI | `pytest tests/test_import_cli.py -k "preflight and sc1" -x` | ❌ Wave 0 |
| PRE-01 | Missing-required mapped to alias headers / "no spreadsheet column mapped" | unit | `pytest tests/test_import_preflight.py -k column -x` | ❌ |
| PRE-01 / D-06 | Deferred required (reporter/parent/sprint) present → caveat, not problem; absent → problem; sub-task parent | unit | `pytest tests/test_import_preflight.py -k deferred -x` | ❌ |
| PRE-02 / SC2 | Invalid select value + plain-text-for-ADF + unknown fixVersion reported in same preview | unit+CLI | `pytest tests/test_import_preflight.py -k "option or adf or fix_version" -x` | ❌ |
| D-07 | plan still accepts unknown versions; import rejects | unit | `pytest tests/test_payload_validator.py -k "fix_versions" -x` | ✅ (extend) |
| D-10 | Off-screen field reported in import only; default off | unit | `pytest tests/test_payload_validator.py -k off_screen -x` | ✅ `:151` pins default |
| D-02 | Unknown issue type = row problem; issue-type/field fetch JiraApiError/RequestException = unavailable | unit | `pytest tests/test_import_preflight.py -k "unavailable or issue_type" -x` | ❌ |
| PRE-03 / SC3 / D-01 / D-11 | Live import with problems: create_issue never called; report status `failed`, `error.type=="Aborted"`, one failed IssueResult per failing row (sanitized), exit 1, all rows printed | CLI+report | `pytest tests/test_import_cli.py tests/test_importer_report.py -k abort -x` | ❌ |
| D-08 | Resume: prior-created rows not validated; build-failed rows listed but not schema-checked | report | `pytest tests/test_importer_report.py -k "preflight and resume" -x` | ❌ |
| D-02 live | Unavailable → warning + creates proceed | CLI | `pytest tests/test_import_cli.py -k "live and unavailable" -x` | ❌ |
| PRE-04 / SC4 / D-04 | No creds → both skip messages, preview printed, exit 0; get_fields fails but createmeta works → aliases warning + validation runs | CLI | `pytest tests/test_import_cli.py -k "dry_run" -x` | ✅ (extend `:84`,`:124`) |
| D-09 / D-11 | Every failing row printed regardless of `--preview-rows`; `X of Y rows have problems`; markup escaped | CLI | `pytest tests/test_import_cli.py -k "preview_rows or escape" -x` | ❌ |
| plan unchanged | plan tests green; planner.py diff empty | regression | `pytest tests/test_planner.py tests/test_planner_report.py tests/test_cli_e2e.py -q` | ✅ |
| SC1 live | Real Jira dry-run shows 8 problems | manual | human-verify in work clone | manual-only (live Jira forbidden to agent) |

### Sampling Rate
- **Per task commit:** the quick run command.
- **Per wave merge:** the full suite + ruff.
- **Phase gate:** full suite green, plus the human live dry-run smoke checkpoint.

### Wave 0 Gaps
- [ ] `tests/conftest.py` (or a per-file helper): `stub_createmeta(client, types_to_fields)`; apply it to every MagicMock live client (Pitfall 1).
- [ ] `tests/test_cli_e2e.py::FakeJiraClient`: add `get_createmeta_issue_types` / `get_createmeta_fields`; give the import test an issuetype.
- [ ] `tests/test_import_preflight.py`: new file with an SC1 fixture builder.

## Security Domain

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (indirect) | Credentials only from env (`resolve_credentials`); never printed. Degrade messages print `str(ValueError)`, which names the env var, not the value |
| V3 Session Management | no | — |
| V4 Access Control | no | Jira enforces; 401/403 → "unavailable" |
| V5 Input Validation | yes | This phase *is* input validation of untrusted spreadsheet cells; escape before Rich rendering |
| V6 Cryptography | no | — |
| V7 Error handling / logging | yes | Per-row errors via `sanitize_message`; run error via `abort_info` (2,000-char cap, token/Basic redaction) |

| Pattern | STRIDE | Mitigation |
|---------|--------|-----------|
| Rich markup injection from cell/summary text (console spoofing or crash) | Tampering / DoS | `rich.markup.escape` on all interpolated user and Jira text |
| Jira error text echoing credentials into the report | Info disclosure | `_record` → `sanitize_message`; `abort_info(..., secrets=credential_secrets(org))` |
| Very large sheets → huge console/report | DoS (local) | Accepted by D-11; per-row errors capped at 2,000 chars each |

## Sources

### Primary (HIGH)
- Read this session: `jiramator/payload_validator.py` (full), `planner.py:1-60,420-560,880-935`, `importer.py` (full), `cli.py:1-260,520-780`, `jira_client.py:30-250,487-649`, `run_report.py:50-420`, `field_resolver.py`, `value_coercion.py`, `spreadsheet.py:17-60`, `tests/test_import_cli.py` (full), `tests/test_importer.py` (fixtures, `TestRunImport`), `tests/test_importer_report.py:1-63`, `tests/test_import_integration.py` (full), `tests/test_cli_e2e.py:25-120,336-381`, `tests/test_payload_validator.py`, `tests/test_planner_report.py:595-705`, `tests/test_jira_client.py:515-670`, `CHANGELOG.md`, `README.md`, `configs/org.example/*.yaml`.
- Code probes run in `.venv` (outputs quoted in Pitfalls 1–4 and 6).
- Evidence (read-only): `~/dev/work_projects/jiramator/.jiramator/runs/20260902T18{3925,4042,4202,4255}Z-calcs.json`. Shape confirmed: 184042Z had 6 failed rows, all `fixVersions` required, and rows 2–3 also `customfield_11941` (8 problems). 184202Z created 4 and failed rows 2–3. 184255Z created 2 and dedup-skipped 4. No values copied here.

### Secondary (MEDIUM)
- Jira Cloud REST v3 OpenAPI (`developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json`): `FieldCreateMetadata`, `JsonTypeBean`, `PageOfCreateMetaIssueTypes`, `PageOfCreateMetaIssueTypeWithField`, and endpoint params (fetched via curl; no MCP research providers were enabled).

### Tertiary (LOW)
- `allowedValues` per-kind shapes and live-Jira acceptance behaviours (Assumptions A1–A6).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH. No new deps; verified against pyproject and the installed venv.
- Architecture / hook points: HIGH. Every line ref read this session.
- Jira API shapes: MEDIUM. Official spec, but `allowedValues` items are untyped there.
- Pitfalls: HIGH for 1, 2, 3, 4, 5 and 6 (reproduced by running code). MEDIUM for 7 and 9.

**Research date:** 2026-10-09
**Valid until:** 2026-11-08 (stable codebase; re-check if `importer.py` / `cli.py` change before planning)
