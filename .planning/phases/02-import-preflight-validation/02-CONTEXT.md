# Phase 2: Import Preflight Validation - Context

**Gathered:** 2026-10-08
**Status:** Ready for planning. All decisions were auto-selected while the user was away (autopilot) and revised after an adversarial review on 2026-10-09. They are marked `[auto]`. The user should review them before execution, especially D-01 and D-03, which change existing behaviour.

<domain>
## Phase Boundary

`import` validates every row's built payload against Jira's live createmeta schema for that row's project and issue type, before anything is written. It reports every failing row at once (missing required fields, rejected select/option values, plain text where Jira expects ADF), in both `--dry-run` and live runs. Without credentials or Jira access, `--dry-run` still previews and says schema validation was skipped (PRE-01..PRE-04).

Out of scope for this phase:
- User/reporter/assignee lookup correctness. That is Phase 3 (USER-01..04).
- Transport-error wrapping (HYG-05, Phase 4).
- Any change to `plan` or `update` validation behaviour.

</domain>

<decisions>
## Implementation Decisions

All decisions are `[auto]`: chosen by the agent while the user was away. They were revised on 2026-10-09 after an adversarial review by gpt-5.5; see `02-DISCUSSION-LOG.md` § Adversarial review.

### Live-run failure policy
- **D-01:** `[auto]` If preflight finds any problem rows, a live `import` aborts **before creating anything**: it lists every failing row and exits 1. Nothing is written in that case, matching `plan`'s `_preflight_validate` hard stop. The run report records `error.type = "Aborted"` with a problem summary (INV-04 pattern; see D-11 for the full list). This is a deliberate change to the default: today's live import is row-by-row partial-create (`importer.py` ~L407-505, CLI status `partial`). There is no partial "create the valid rows" mode in this phase. — **Reversibility:** costly — a future `--skip-invalid` to restore partial creation would need explicit report-status, resume and test semantics, not just a flag.
- **D-02:** `[auto]` Separate **Jira-unavailable** failures from **row/schema** problems:
  - Errors fetching the project's issue-type list or a schema (auth/permission, network/`RequestException`, Jira 5xx) mean "validation unavailable". The live run warns loudly, saying that row problems may surface as Jira 400s, then proceeds, as `plan` does.
  - A row whose issue type is not creatable in the project (`get_createmeta_fields_by_type_name` raises `JiraApiError` "Issue type '…' is not available", `jira_client.py` ~L594) is a **row problem**, not a degrade. It counts toward the D-01 abort.
  - Implementation: fetch the issue-type list once and match names locally. Don't catch every `JiraApiError` as degrade.

### Dry-run behaviour
- **D-03:** `[auto]` `import --dry-run` with credentials prints the usual mapping preview **plus** a validation section listing every failing row (not capped by `--preview-rows`). It exits **1** when problems are found and 0 when all rows pass, the same as `plan --dry-run`. **This is a deliberate backward-incompatible exit-code change.** Today the dry-run always returns 0, and `tests/test_import_cli.py` asserts that (L26/77/121/163). Planning must update those tests, plus README and CHANGELOG, and call the change out. Exit 0 is kept for "schema validation skipped" (D-04). — **Reversibility:** costly — scripts may come to rely on the new exit code; flipping it back is another breaking change.
- **D-04:** `[auto]` Reuse a single `JiraClient` for `get_fields()` and createmeta, but track the two degrade paths **separately**:
  - If `get_fields()` fails, the preview falls back to aliases only, as today.
  - If createmeta is unavailable per D-02, print `Schema validation skipped: <reason>` and exit 0 (PRE-04).
  - Without credentials, both are skipped and both messages print.
  - Row-level schema problems (D-02, D-10) are never treated as "skipped".

### What gets validated
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

### Reporting format
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope
- `.planning/ROADMAP.md` § Phase 2: goal and 4 success criteria
- `.planning/REQUIREMENTS.md`: PRE-01..PRE-04
- `.planning/STATE.md` § Blockers/Concerns: reuse `payload_validator`; smoke-test against live Jira (mocks missed the 1.2.6 createmeta bugs)
- `AGENTS.md`: conventions, mocking rules, credentials/degrade behaviour

### Evidence (read-only, outside this repo; never write there)
- `~/dev/work_projects/jiramator/.jiramator/runs/20260902T18{3925,4042,4202,4255}Z-calcs.json`: the 2026-09-02 Risk import (6 rows).
  - `183925Z`: 0 created, all 6 skipped.
  - `184042Z`: all 6 failed. Every row was missing `fixVersions`, and rows 2-3 were also missing `customfield_11941` (Repositories).
  - `184202Z`: rows 1/4/5/6 created; rows 2-3 still failed on Repositories.
  - `184255Z`: rows 2-3 created; the others were skipped.
  - **The success-criterion-1 fixture must encode these per-row differences**, and a single dry-run must report all 8 problems across 6 rows at once.

### Prior phase
- `.planning/phases/01-production-triage/01-CONTEXT.md`, `01-TRIAGE-FINDINGS.md`: INV-04 abort recording, redaction (`sanitize_message`), and the D-03 read-only work-clone rule

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `jiramator/payload_validator.py::validate_ticket_payload(fields, field_metadata)`: checks missing required fields, ADF-vs-plain text, and invalid option values. `_SKIP_ALLOWED_VALUES_FIELD_IDS = {"fixVersions"}` exists for `plan` (see D-07).
- `jiramator/planner.py::_validate_payloads_against_jira` (~L438) and `_preflight_validate` (~L479): the per-issue-type schema cache, the problem-string format, the skip-on-JiraApiError/RequestException degrade, and the abort plus `abort_info` recording.
- `jiramator/jira_client.py::get_createmeta_fields_by_type_name` (~L575).
- `jiramator/run_report.py::abort_info`, `sanitize_message`, `credential_secrets`.

### Established Patterns
- `importer.build_preview_report` / `build_row_payload` build `{"fields": ...}` per row. Deferred fields are dropped via `_DEFERRED_FIELDS` / `_DEFERRED_LOGICAL_FIELDS`. `_apply_defaults` injects `bulk_create.defaults` (e.g. `issuetype: Risk`).
- `cli.import_command` dry-run already opportunistically builds `JiraClient(org_config).get_fields()` and degrades with a `⚠ Preview based on field_aliases only` message (~L630-660).

### Integration Points
- `importer.run_import`: insert the preflight **after** the resume skip set is computed (D-08) and before the first create. For dry-run, either `run_import` returns the problems or the CLI calls the validator.
- `cli.import_command`: dry-run output and exit code; live abort persists the report.

</code_context>

<specifics>
## Specific Ideas

- The success-criterion-1 replay can use a fixture shaped like the 2026-09-02 sheet: Risk issue type, rows missing `fixVersions` and `customfield_11941`, against mocked createmeta. Then do a **live smoke test** against real Jira with `--dry-run` only (STATE concern).

</specifics>

<deferred>
## Deferred Ideas

- `--skip-invalid` / create-valid-rows-only mode (see D-01). Revisit if users ask for it.
- Previewing ambiguous user values in dry-run is Phase 3 (USER-04).
- Validating `update` payloads against editmeta. Not in this milestone.

</deferred>

---

*Phase: 02-import-preflight-validation*
*Context gathered: 2026-10-08 (autopilot); revised 2026-10-09 after adversarial review (gpt-5.5). All decisions `[auto]`, pending user review.*
