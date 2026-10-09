# Phase 2: Import Preflight Validation - Pattern Map

**Mapped:** 2026-10-09
**Files analyzed:** 13 (3 source modified, 1 source new, 7 tests new/modified, 3 docs)
**Analogs found:** 12 / 13 (README/CHANGELOG/AGENTS are doc edits and use their own existing sections)

All analog paths below are git-tracked (`git ls-files jiramator tests configs` checked). `planner.py` is an **analog only**: its diff must stay empty (RESEARCH anti-pattern; plan byte-identity).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `jiramator/payload_validator.py` (modify: `PayloadProblem`, `find_payload_problems`, kwargs on `validate_ticket_payload`) | utility (pure validator) | transform | itself (L95-154) | exact |
| `jiramator/import_preflight.py` (NEW: `PreflightResult`, `run_preflight`, `render_preflight_report`) | service (orchestration) | request-response (createmeta reads) + transform | `jiramator/planner.py::_validate_payloads_against_jira` / `_preflight_validate` (L438-525); `jira_client.get_createmeta_fields_by_type_name` (L575-602) | role-match (exact logic shape) |
| `jiramator/importer.py` (modify: `ImportRunResult.preflight`, hook in `run_import`, abort persistence) | service | batch / CRUD | itself (`run_import` L268-524) + `planner._preflight_validate` abort block | exact |
| `jiramator/cli.py` (modify: `import_command` dry-run client reuse, degrade messages, exit codes, live abort) | controller (CLI) | request-response | itself (`import_command` L571-718) | exact |
| `tests/test_payload_validator.py` (extend) | test | transform | itself (L1-60, L151-185) | exact |
| `tests/test_import_preflight.py` (NEW, incl. SC1 replay fixture) | test | unit | `tests/test_importer_report.py` (fixtures L18-55, MagicMock client) + `tests/test_payload_validator.py` | role-match |
| `tests/test_importer.py`, `tests/test_importer_report.py`, `tests/test_import_integration.py` (stub createmeta on MagicMock clients; new abort/resume tests) | test | batch | `tests/test_importer_report.py` L84-125 | exact |
| `tests/test_import_cli.py` (D-03/D-04 exit codes, live abort, escape, preview_rows) | test | CLI | itself L35-238 | exact |
| `tests/test_cli_e2e.py` (`FakeJiraClient` gains createmeta methods; import config issuetype) | test | CLI e2e | itself L31-95 | exact |
| `tests/conftest.py` (optional `stub_createmeta` helper) | test fixture | — | itself L1-38 | exact |
| `README.md`, `CHANGELOG.md`, `AGENTS.md` | docs | — | existing `[Unreleased]` section (CHANGELOG L6-18); AGENTS § Credentials | n/a |

---

## Pattern Assignments

### `jiramator/payload_validator.py` (utility, transform) — MODIFY

**Analog:** itself. Keep the module pure: no I/O, no imports beyond `typing`/`dataclasses`.

**Module constants to keep and reuse as kwarg defaults** (L18-29):
```python
_SKIP_FIELD_IDS = frozenset({"project"})
...
_SKIP_ALLOWED_VALUES_FIELD_IDS = frozenset({"fixVersions"})
```

**Core loop to move verbatim into `find_payload_problems`** (L119-154). Keep the loop order exactly as it is: required pass over `field_metadata`, then the per-field pass over `fields`. This keeps `plan` output byte-identical.
```python
    problems: list[str] = []

    # 1. Missing required fields (that Jira won't auto-default).
    for field_id, meta in field_metadata.items():
        if field_id in _SKIP_FIELD_IDS:
            continue
        if not meta.get("required"):
            continue
        if meta.get("hasDefaultValue"):
            continue
        if field_id not in fields or fields[field_id] in (None, "", [], {}):
            label = meta.get("name", field_id)
            problems.append(f"missing required field {label!r} ({field_id})")

    # 2. Type/value checks for every field we're actually sending.
    for field_id, value in fields.items():
        if field_id in _SKIP_FIELD_IDS:
            continue
        meta = field_metadata.get(field_id)
        if meta is None:
            continue  # Not on this issue type's create screen — not our call.
        label = f"{meta.get('name', field_id)!r} ({field_id})"
        schema = meta.get("schema", {})
        if _is_textarea_or_richtext(field_id, schema) and not _looks_like_adf(value):
            problems.append(...)
        allowed_values = meta.get("allowedValues")
        if allowed_values and field_id not in _SKIP_ALLOWED_VALUES_FIELD_IDS:
            ...
```
Change points:
- **Required check:** add `if field_id in assume_present_field_ids: continue` before the "missing" test (D-06).
- **`meta is None`:** `if report_off_screen_fields: append(PayloadProblem(field_id, "off_screen", f"{field_id} is not on the create screen for this issue type"))`, then `continue` (D-10).
- **Allowed-values check:** `field_id not in skip_allowed_value_field_ids` replaces the module constant (D-07).
- **Each `problems.append(str)`** becomes `PayloadProblem(field_id=..., kind=..., message=<same string>)`.
- **Optional, import only (Pitfall 3):** treat a whitespace-only ADF doc as missing. This must be behind a kwarg that defaults off.

**Wrapper signature** (RESEARCH § Code Examples; keep the Google docstring style used at L99-117):
```python
def validate_ticket_payload(
    fields: dict[str, Any],
    field_metadata: dict[str, dict[str, Any]],
    *,
    skip_allowed_value_field_ids: frozenset[str] = _SKIP_ALLOWED_VALUES_FIELD_IDS,
    report_off_screen_fields: bool = False,
    assume_present_field_ids: frozenset[str] = frozenset(),
) -> list[str]:
    return [p.message for p in find_payload_problems(fields, field_metadata, ...)]
```
**Dataclass style:** copy `@dataclass(frozen=True)` from `importer.py` L52-63 (`RowBuildResult`).

---

### `jiramator/import_preflight.py` (service, request-response + transform) — NEW

**Analog A:** `jiramator/planner.py` L438-525. It provides the schema cache, problem format, degrade split and abort.
**Analog B:** `jiramator/jira_client.py` L575-602. Copy its casefold match and "not available" message, **inlined** so the issue-type list is fetched once.

**Module header / imports.** Follow the planner.py L26-55 conventions (`from __future__`, explicit imports, `requests` for the exception type, `rich.markup.escape`):
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import requests
from rich.markup import escape

from jiramator.config import OrgConfig
from jiramator.field_resolver import resolve_field_name
from jiramator.jira_client import JiraApiError, JiraClient
from jiramator.payload_validator import PayloadProblem, find_payload_problems
```
Circular-import caution: `importer.py` will import `run_preflight`. So `import_preflight.py` must **not** import from `importer` at module level. Pass `RowBuildResult`s in as `Any`, or import under `TYPE_CHECKING`. The `_DEFERRED_FIELDS` / `_DEFERRED_LOGICAL_FIELDS` sets live in `importer.py` L94-99. Either take them as parameters, or move them to `import_preflight` and have importer re-import them. If you move them, patch tests where they are used (AGENTS.md).

**Schema cache + per-payload loop** (planner.py L463-479). Adapt the cache to key by issue-type **id**:
```python
    schema_cache: dict[str, dict[str, dict[str, Any]]] = {}
    problems: list[str] = []
    for kind in ("epics", "per_release", "per_sprint"):
        for item in all_payloads.get(kind, []):
            fields = _payload_fields(item)
            issuetype_name = fields.get("issuetype", {}).get("name")
            if not issuetype_name:
                continue
            if issuetype_name not in schema_cache:
                schema_cache[issuetype_name] = client.get_createmeta_fields_by_type_name(
                    project_key, issuetype_name
                )
            label = fields.get("summary") or item.get("_template_key") or "(untitled)"
            for message in validate_ticket_payload(fields, schema_cache[issuetype_name]):
                problems.append(f"[{issuetype_name}] {label}: {message}")
```
Import-specific deviations:
- A missing issuetype is a **row problem**, not `continue` (D-05).
- Call `get_createmeta_issue_types` once, then `get_createmeta_fields(project_key, id)` per distinct id. Never call `get_createmeta_fields_by_type_name`: it re-lists types on every call (L588).
- Only fetch when `rows_to_check` is non-empty, so zero-row CLI tests make no createmeta calls.

**Name → id match + "not available" wording** (jira_client.py L588-601). Reuse the wording, but as a row problem:
```python
        match = next(
            (it for it in issue_types
             if str(it.get("name", "")).casefold() == issue_type_name.casefold()),
            None,
        )
        if match is None:
            available = ", ".join(sorted(str(it.get("name", "")) for it in issue_types))
            raise JiraApiError(
                f"Issue type '{issue_type_name}' is not available for "
                f"creation in project {project_key} "
                f"(available: {available or 'none'})."
            )
```

**Degrade split** (planner.py L497-504). Wrap **only** the two fetch calls in this `try` (D-02):
```python
    try:
        problems = _validate_payloads_against_jira(client, project_key, all_payloads)
    except JiraApiError as exc:
        console.print(f"  [yellow]⚠ Skipping field validation (Jira error): {exc}[/]")
        return
    except requests.exceptions.RequestException as exc:
        console.print(f"  [yellow]⚠ Skipping field validation (connection error): {exc}[/]")
        return
```
Here, return `PreflightResult(status="unavailable", reason=str(exc))` instead of printing. Leave printing to `render_preflight_report` and the CLI.

**Deferred header discovery** (importer.py L360-367). Make a per-row version for D-06 presence and keep the `.strip()` emptiness rule from L443:
```python
    for row_result in preview.row_results:
        for source_header, resolved in row_result.resolved_columns.items():
            if resolved.jira_field in deferred_headers:
                deferred_headers[resolved.jira_field].add(source_header)
            if resolved.logical_name in _DEFERRED_LOGICAL_FIELDS:
                sprint_field_headers.add(source_header)
                sprint_jira_field = resolved.jira_field
```

**Alias → field map for missing-required column hints (D-09).** Use `resolve_field_name(alias, org_config)` (`field_resolver.py` L84-89; returns `ResolvedField(source_name, logical_name, jira_field, resolution_source)`, L18-24) with `jira_fields=None`.

**Rendering.** Return plain text, the same as `render_preview_report` (importer.py L527-554: build `lines`, then `"\n".join(lines)`). Escape summary, header, issue type and message with `escape()` (Pitfall 6). Print failure bullets as `[red]•[/]` (planner.py L511), the caveat as `[yellow]⚠`, and the pass line as `[green]✓` (planner.py L507). The format is `Row N 'summary' [IssueType]:` + bullets + `X of Y rows have problems` (D-09). There is **no** `preview_rows` cap.

---

### `jiramator/importer.py` (service, batch) — MODIFY

**Analog:** itself + planner.py abort block.

**Result dataclass to extend** (L78-85). Add `preflight: PreflightResult | None = None` **with a default** so the existing constructors at L295 and L519 still work:
```python
@dataclass(frozen=True)
class ImportRunResult:
    preview: PreviewReport
    created: list[tuple[int, str, str]]
    skipped: list[tuple[int, str, str]]
    failed: list[tuple[int, str, str]]
```

**Imports to extend** (L15-22). Add `abort_info`:
```python
from jiramator.run_report import (
    IssueResult,
    RunReport,
    credential_secrets,
    error_info,
    sanitize_message,
    write_report_atomic,
)
```

**Dry-run early return to restructure** (L294-298). Run preflight when `client is not None`. Keep `client=None` legal (status `skipped`). Per OQ-2, also apply the resume skip set in dry-run.
```python
    if dry_run:
        return ImportRunResult(preview=preview, created=[], skipped=[], failed=[])

    if client is None:
        raise ValueError("client is required for live imports")
```

**Resume skip set** (L301-319; compute before preflight, D-08) and **`_record` / `_persist`** (L321-338). `_record` already sanitizes per-row errors (D-11):
```python
    def _record(tk: str, status: str, **kw: Any) -> None:
        if report is None:
            return
        if kw.get("error"):
            # Same redaction + cap as run.error (INV-04 / WR-03).
            kw["error"] = sanitize_message(kw["error"], secrets=secrets)
        report.issues.append(
            IssueResult(template_key=tk, kind="imported", status=status, **kw)  # type: ignore[arg-type]
        )
        report.counts[status] = report.counts.get(status, 0) + 1

    _persist()  # initial write reflecting prior-carry-forward
    # >>> INSERT PREFLIGHT HERE (before find_issue_keys_by_summaries at L344) <<<
```

**Abort recording.** Copy planner.py L515-525, but **return** instead of `sys.exit` so the CLI owns the exit:
```python
    if report is not None:
        report.error = abort_info(
            f"Found {len(problems)} field problem(s): " + "; ".join(problems)
            + ". No tickets were created.",
            secrets=secrets,
        )
    persist()
    sys.exit(1)
```
For import: call `_record(tk, "failed", error="; ".join(msgs))` for each failing row in `preview.row_results` order. Build-failed rows use `result.error` (same as L410-415). The template key is `_row_template_key(result.row_number, result.summary)` (L240). Set `report.error = abort_info("Preflight found problems in N of M row(s). No issues were created.", secrets=secrets)`, then `_persist()` and return `ImportRunResult(..., preflight=pre)`. Keep the carried-forward `created` entries.

**Do not** put the abort inside the `try/except BaseException` at L403-517. That handler sets `error_info`, but since `report.error` is already set it would only re-persist. Put the preflight before that block.

---

### `jiramator/cli.py` (controller, request-response) — MODIFY

**Analog:** itself, `import_command` L571-718.

**Current dry-run block to split per D-04** (L622-660):
```python
        jira_fields = None
        try:
            jira_fields = JiraClient(org_config).get_fields()
        except ValueError as exc:
            console.print(
                f"[yellow]⚠ Preview based on field_aliases only (no Jira "
                f"credentials available): {exc}[/]"
            )
        except (JiraApiError, requests.exceptions.RequestException) as exc:
            console.print(
                f"[yellow]⚠ Preview based on field_aliases only (could not "
                f"reach Jira): {exc}[/]"
            )

        result = run_import(rows, ..., jira_fields=jira_fields, client=None, dry_run=True)
        console.print(render_preview_report(result.preview, preview_rows=preview_rows))
        return
```
Target shape: see RESEARCH § Pattern 6. Construct `client` and `get_fields()` in **separate** try blocks, and pass `client=client`, `prior_report=prior_report`. Then print `render_preflight_report(...)`. Exit codes: `problems` → `sys.exit(1)`; `skipped`/`unavailable` → print `Schema validation skipped: <reason>` and return 0; `passed` → return 0. Wrap the existing `{exc}` interpolations in `escape()`. The new import `from rich.markup import escape` is already used in planner.py L36.

**Live-run exception arms to stay clear of** (L686-698): `except (ValueError, JiraApiError)` → `_record_import_failure` + `_fail("Import error: …")`. The preflight abort must come back as a *result*, not an exception.

**Finalization to short-circuit on abort** (L700-718; Pitfall 5):
```python
    report.ended_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    failed_count = report.counts.get("failed", 0)
    ...
    if failed_count == 0:
        report.status = "success"
    elif created_count > 0 or skipped_count > 0 or failed_count > 0:
        report.status = "partial"
    ...
    write_report_atomic(report, report_path)
    console.print(render_preview_report(result.preview, preview_rows=preview_rows))
    console.print(render_import_execution_report(result))
    if result.failed:
        sys.exit(1)
```
Abort branch, placed **before** this block:
1. Set `report.ended_at` and keep `report.status = "failed"` (the constructor default at L677).
2. `write_report_atomic`.
3. Print the preview + preflight report + `Aborting — fix the rows above. No issues were created.`
4. `sys.exit(1)`.

Live `unavailable` → print the loud yellow warning (the D-02 wording that row problems may surface as Jira 400s), then continue to the normal finalization.

---

### `tests/test_payload_validator.py` (test) — EXTEND

**Analog:** itself. Imports (L1-5), section dividers, `Test<Component>` classes, and plain dict `fields`/`meta` inputs:
```python
from __future__ import annotations

from jiramator.payload_validator import validate_ticket_payload

class TestMissingRequiredFields:
    def test_missing_required_field_flagged(self):
        fields = {"project": {"key": "CA"}, "summary": "Test"}
        meta = {"customfield_10273": {"name": "API Impact", "required": True, "hasDefaultValue": False}}
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1
```
**Pins that must stay unmodified and green** (default kwargs): `test_field_not_on_screen_skipped` (L151-155) and `test_fix_versions_allowed_values_skipped` (L157-171). Add twins that use the kwargs: `skip_allowed_value_field_ids=frozenset()` flags `26.4.1` (D-07), and `report_off_screen_fields=True` flags `customfield_99999` (D-10). Also add `assume_present_field_ids` and a `find_payload_problems` `kind` test.

---

### `tests/test_import_preflight.py` (test) — NEW

**Analog:** `tests/test_importer_report.py` L1-55. It shows the real Pydantic config construction (no mocking of config, per AGENTS.md) and a MagicMock client:
```python
from __future__ import annotations

from unittest.mock import MagicMock

from jiramator.config import BulkCreateConfig, OrgConfig, TeamConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _org_config() -> OrgConfig:
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={"api_impact": "customfield_10273"},
        bulk_create=BulkCreateConfig(
            field_aliases={"Summary": "summary", "API Impact": "api_impact", "Issue Type": "issuetype"},
            field_types={"issuetype": "name_object", "api_impact": "multi_select"},
            defaults={"issuetype": "Risk", "api_impact": "No"},
        ),
        sprints={"count": 6, "standard_length_weeks": 2, "long_length_weeks": 3, "long_sprints": [6]},
    )

def _team_config() -> TeamConfig:
    return TeamConfig(project_key="CA", team_name="Calcs")
```
**SC1 fixture:** load the real `configs/org.example/example.yaml` + `tests/fixtures/teams/calcs.yaml` (conftest `org_config_path` / `team_config_path`, conftest.py L12-25). Use the mocked createmeta exactly as in RESEARCH § SC1 replay fixture. Expect 8 problems over 6 rows, and that `create_issue`, `find_issue_keys_by_summaries` and `find_user_account_id` are `assert_not_called()`. Summaries are synthetic, never real ones.

---

### `tests/test_importer.py`, `tests/test_importer_report.py`, `tests/test_import_integration.py` — MODIFY (Pitfall 1)

**Analog for live-client setup** (test_importer_report.py L87-104):
```python
        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-1", "CA-2"]
        report = _new_report()
        report_path = tmp_path / "r.json"
        run_import(rows, org_config=_org_config(), team_config=_team_config(),
                   jira_fields=[], client=client, report=report, report_path=report_path)
        env = _read_report(report_path)
        run = env["run"]
```
Add to every live MagicMock client:
```python
client.get_createmeta_issue_types.return_value = [{"id": "1", "name": "Risk"}]
client.get_createmeta_fields.return_value = {}
```
Put this in a helper, either `stub_createmeta(client, ...)` in conftest or per-file.

**New abort test assertions.** Model them on test_planner_report.py L690-705:
```python
        assert run["error"]["type"] == "Aborted"
        msg = run["error"]["message"]
        assert msg.startswith("Found ")
        assert "customfield_99999" in msg
        assert msg.endswith("No tickets were created.")
        assert run["ended_at"] is not None
```
For import, also assert one `IssueResult` per failing row with `status == "failed"`, no entries for passing rows, and `client.create_issue.assert_not_called()`.

---

### `tests/test_import_cli.py` (test, CLI) — MODIFY

**Analog:** itself. CliRunner fixture (L17-19), monkeypatch targets **where used** (`jiramator.cli.JiraClient`, `jiramator.importer.build_preview_report`, `jiramator.cli.render_preview_report`), and the invoke shape (L35-83):
```python
        mock_client = MagicMock()
        mock_client.get_fields.return_value = []
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=mock_client))
        result = runner.invoke(cli, ["import", "--org-config", str(org_config_path),
                                     "--team-config", str(team_config_path), "--dry-run", str(sheet_path)])
        assert result.exit_code == 0
```
- **No-creds test** (L85-122): `MagicMock(side_effect=ValueError("JIRA_TOKEN env var not set"))`. Add `assert "Schema validation skipped" in result.output`.
- **get_fields-500 test** (L124-163): `JiraApiError("Server Error", status_code=500)`. Assert the aliases-only warning, and that preflight still runs.
- **`test_live_mode_continues_after_row_failure_and_reports_summary`** (L192-238): its fake `row_results` payloads are `{"fields": {"summary": "Risk A"}}`. Add `"issuetype": {"name": "Risk"}` and the createmeta stub. Note that `MagicMock` row results have no real `resolved_columns`, so set `resolved_columns={}`.
- **New tests:** an exit-1 dry-run with problems (SC1), a live abort (report status `failed`, `create_issue` not called), live-unavailable proceeds, `--preview-rows 1` still lists every failing row, and a summary containing `[bold]` is escaped.

---

### `tests/test_cli_e2e.py` (test, e2e) — MODIFY

**Analog:** itself, `FakeJiraClient` L31-95. Add next to the existing `get_createmeta_fields_by_type_name` stub (L90-95):
```python
    def get_createmeta_fields_by_type_name(
        self, project_key: str, issue_type_name: str
    ) -> dict[str, dict]:
        # No metadata configured — nothing to check against, so the
        # pre-flight validator finds zero problems for every payload.
        return {}
```
New methods: `get_createmeta_issue_types(self, project_key) -> list[dict]` returning e.g. `[{"id": "1", "name": "Task"}]`, and `get_createmeta_fields(self, project_key, issue_type_id) -> dict` returning `{}`. The import test (L337-381) writes a sheet with only `summary`. Give its org config `bulk_create.defaults.issuetype` so the row has a resolvable type (D-05). Otherwise it becomes a row problem, and the test's expected `exit_code == 0` breaks.

---

## Shared Patterns

### Degrade vs. hard-stop split
**Source:** `jiramator/planner.py` L497-525
**Apply to:** `import_preflight.run_preflight`, `cli.import_command`
Only the `JiraApiError` / `requests.exceptions.RequestException` raised by the **fetch** calls count as unavailable. Everything else is a row problem.

### Redaction + abort recording (INV-04)
**Source:** `jiramator/run_report.py` L238-298 (`sanitize_message`, `abort_info` → `{"type": "Aborted", "message": …}`, cap 2000); `importer._record` L326-336
**Apply to:** the live abort in `importer.run_import`. Per-row errors go through `_record` (already sanitized). The run-level summary goes through `abort_info(..., secrets=credential_secrets(org_config))`.

### Report persistence
**Source:** `write_report_atomic` (run_report.py L301); `importer._persist` L321-323; `cli._record_import_failure` L114-129 (swallows `OSError`)
**Apply to:** abort paths. Never use `json.dump` directly.

### Console output
**Source:** `cli.console = Console(stderr=True)` (cli.py L51); styles `[yellow]⚠ …[/]`, `[red]•[/]`, `[green]✓`, `[red bold]Aborting[/]` (planner.py L496-514)
**Apply to:** all new output. Never use `print()`. Wrap user and Jira text in `rich.markup.escape`. Render functions return plain strings (importer.py L527-578).

### Code conventions (AGENTS.md)
`from __future__ import annotations` first; explicit imports; fully typed signatures with lowercase generics; `_private` helpers; Google docstrings on public functions; `# ----` section dividers in source and tests; frozen dataclasses for results.

### Test mocking rules (AGENTS.md)
Patch where the symbol is used (`jiramator.cli.JiraClient`, `jiramator.importer.build_preview_report`). Use `MagicMock` clients for importer-level tests. Don't mock Pydantic or config loading. Use `monkeypatch` for env vars. The conftest autouse `_isolate_runs_dir` already sandboxes `.jiramator/runs`.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| D-06 deferred "assume present" + caveat logic (inside `import_preflight.py`) | service | transform | No existing code maps deferred headers to required createmeta ids. Build it from importer.py L360-367 header discovery plus RESEARCH § Pattern 3. |
| D-09 missing-required → alias hint map | service | transform | No reverse alias index exists. Build it with `field_resolver.resolve_field_name` per RESEARCH § Pattern 4. |
| Docs (`README.md` L157-170/L318-370/L466-470, `CHANGELOG.md` `[Unreleased]` → `### Changed` **breaking** + `### Added`, `AGENTS.md` § Credentials import-dry-run sentence) | docs | — | Edit in place, following the existing CHANGELOG bullet style (bold lead sentence, wrapped prose; CHANGELOG L8-18). |

## Metadata

**Analog search scope:** `jiramator/` (payload_validator, planner, importer, cli, jira_client, run_report, field_resolver), `tests/` (test_payload_validator, test_import_cli, test_importer_report, test_cli_e2e, test_planner_report, conftest)
**Files scanned:** 13
**Pattern extraction date:** 2026-10-09
**Guardrail:** `git diff --stat jiramator/planner.py` must be empty at the end of the phase.
