# Phase 2: Import Preflight Validation - Context

**Gathered:** 2026-10-08
**Status:** Ready for planning. All decisions were auto-selected while the user was away (autopilot) and are marked `[auto]`. The user should review them before execution.

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

### Live-run failure policy
- **D-01:** `[auto]` If preflight finds any row with problems, a live `import` aborts **before creating anything**. It lists every failing row and exits 1. Nothing is ever written in that case, which matches `plan`'s `_preflight_validate` hard stop. The abort is recorded in the run report as `error.type = "Aborted"` with the problem list, per the INV-04 pattern. There is no partial "create the valid rows" mode in this phase. The user fixes the sheet and re-runs, which is the loop the 2026-09-02 evidence shows, minus the one-400-at-a-time discovery. — **Reversibility:** reversible — a `--skip-invalid` opt-in can be added later without changing the default.
- **D-02:** `[auto]` If the schema fetch itself fails during a **live** run (Jira error or connection error), the run warns that validation was skipped and proceeds, the same as `plan`. The create calls will surface any real problem, and HYG-05 owns transport errors.

### Dry-run behaviour
- **D-03:** `[auto]` `import --dry-run` with credentials prints the usual mapping preview **plus** a validation section that lists every failing row, not capped by `--preview-rows`. It exits **1** when problems are found and 0 when all rows pass, the same as `plan --dry-run`.
- **D-04:** `[auto]` Without credentials, or when Jira can't be reached, `--dry-run` prints the existing aliases-only preview, adds an explicit line `Schema validation skipped: <reason>`, and exits 0 (PRE-04). One `JiraClient` is reused for both `get_fields()` and the createmeta fetch, so the degrade path is decided once.

### What gets validated
- **D-05:** `[auto]` Validate each row against the createmeta schema for `team_config.project_key` and **that row's** issue type: from the row's Issue Type column, otherwise from `bulk_create.defaults.issuetype`. Fetch each distinct issue type's schema once and cache it. A row with no resolvable issue type is reported as a problem rather than skipped.
- **D-06:** `[auto]` Deferred fields (`reporter`, `assignee`, `parent`, and the sprint field) are left out of the payload at build time. For the **required-field check**, a deferred field counts as present when the row has a non-empty raw value for it. Preflight makes **no** live user/issue/sprint lookups; resolution stays at create time, and Phase 3 owns ambiguous users.
- **D-07:** `[auto]` `fixVersions`: unlike `plan`, `import` never creates versions, so a fix-version name not in createmeta `allowedValues` **is** reported as a problem. `payload_validator` only skips allowed-value checks for `fixVersions` because of `plan`. Make that skip a caller option, not a module constant, so `plan` behaves the same as before.
- **D-08:** `[auto]` Rows that already fail at build time (e.g. a missing summary) keep their existing error and are also listed in the failing-rows report. They aren't schema-checked. Rows that a `--resume` run would skip because they were already created are **not** validated, since only rows that would be attempted are checked.

### Reporting format
- **D-09:** `[auto]` Problems are grouped per row as `Row N 'summary' [IssueType]:` with one bullet per problem, followed by a total like `X of Y rows have problems`. Problem strings come from `validate_ticket_payload` and use field display names. Each row also shows the spreadsheet header that mapped to a field, where it's known, so the user can find the column.

### the agent's Discretion
- Where the shared "validate many payloads" helper lives. One option is to lift `planner._validate_payloads_against_jira` into `payload_validator` as a payload-list API that both `plan` and `import` call, keeping `plan` output byte-identical.
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
- `~/dev/work_projects/jiramator/.jiramator/runs/20260902T18{3925,4042,4202,4255}Z-calcs.json`: the 2026-09-02 Risk import. 0 → 6 failed (Fix versions required / Repositories `customfield_11941` required) → 4 created + 2 failed → 2 created. This is the shape success criterion 1 must replay.

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
- `importer.run_import`: insert the preflight after `build_preview_report` and before the first create, for live runs. For dry-run, either `run_import` returns the problems or the CLI calls the validator. Resume skip-set is computed in `run_import`.
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
*Context gathered: 2026-10-08 (autopilot; all decisions `[auto]`, pending user review)*
