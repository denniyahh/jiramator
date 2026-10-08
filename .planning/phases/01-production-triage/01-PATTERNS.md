# Phase 1: Production Triage - Pattern Map

**Mapped:** 2026-10-02
**Files analyzed:** 9 (4 source modified, 4 tests extended, 1 findings doc created)
**Analogs found:** 9 / 9 (every source and test file is its own analog and gets extended in place. The findings doc has a planning-doc analog.)

> Every line number is on HEAD `6676bdc`. All source and test analogs are git-tracked (checked with `git ls-files`). `.planning/` is gitignored (`.gitignore:46`), so the planning-doc analogs are local files and are not tracked source.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `jiramator/run_report.py` (modify: `error` field, tolerant `from_envelope`, `error_info()` helper, optional omit-when-None `to_envelope`) | model / utility (stdlib dataclass + JSON IO) | file-I/O, transform | itself: `RunReport` L84-142, `IssueResult` L69-79 | exact |
| `jiramator/planner.py` (modify: `run_plan` handler L790-795 and abort reasons before each `sys.exit(1)`) | service / orchestrator | request-response + event (exception) | itself: `run_plan` L745-795; existing `ended_at` sets L868, L1009 | exact |
| `jiramator/importer.py` (modify: `run_import` handler L497-500) | service | batch, file-I/O | itself L313-325, L484-500; mirrors planner handler | exact |
| `jiramator/cli.py` (modify: import outer handler L651-669; plan handler L444-463 is display only, so no change) | controller (click CLI) | request-response | itself L637-669; `_fail` L106-109; `_load_report_file` L111-126 | exact |
| `tests/test_run_report.py` (extend) | test | file-I/O | `TestEnvelopeRoundTrip` L31-81, `TestFindResumable` L164+ | exact |
| `tests/test_planner_report.py` (extend) | test | request-response | `TestPersistOnError` L536-561, helpers L168-186 | exact |
| `tests/test_importer_report.py` (extend) | test | batch | `TestPersistOnInterrupt` L349-385 | exact |
| `tests/test_import_cli.py` (extend: CLI-level crash before `run_import` writes a report) | test | request-response | `test_live_mode_continues_after_row_failure_and_reports_summary` L190-240 | exact |
| `.planning/phases/01-production-triage/01-TRIAGE-FINDINGS.md` (create; D-11 deliverable, name at the planner's discretion) | doc | — | `.planning/milestones/v1.0-phases/02-.../2-UAT.md` (frontmatter + Summary/Gaps) and `deferred-items.md` (finding write-up); table draft in `01-RESEARCH.md` §Findings Table | role-match |

Possible extra edits:
- `CHANGELOG.md` `## [Unreleased]`: add an entry for INV-04 plus the downgrade-resume caveat. Analog is the existing `### Added` / `### Fixed` bullets at L6-18.
- `.planning/REQUIREMENTS.md` / `ROADMAP.md`: D-NEW-1 traceability (D-09). These are planning docs, so no code pattern applies.

---

## Pattern Assignments

### `jiramator/run_report.py` (model, file-I/O)

**Analog:** itself.

**Module conventions** (L21-34): stdlib only. The docstring L1-19 lists the "Public surface", so add `error_info` to that list.
```python
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
```
To filter on field names you will need `fields` from `dataclasses`. Import it explicitly: `from dataclasses import asdict, dataclass, field, fields`.

**Constants section style** (L36-46). Put `_ERROR_MESSAGE_CAP` here, under the existing divider:
```python
# ---------------------------------------------------------------------------
# Constants and type aliases
# ---------------------------------------------------------------------------

SCHEMA_VERSION: int = 1
RUNS_DIR: Path = Path(".jiramator/runs")
```
Do **not** bump `SCHEMA_VERSION`. `tests/test_run_report.py:74-77` (`test_4_schema_version_two_rejected`) locks that contract.

**Dataclass field pattern** (L102-116). Add `error` as the **last** field, after `issues`, and document it in the `Fields:` docstring block (L87-101):
```python
    status: RunStatus = "failed"
    counts: dict[str, int] = field(
        default_factory=lambda: {"created": 0, "skipped": 0, "failed": 0}
    )
    issues: list[IssueResult] = field(default_factory=list)
    # NEW (INV-04):
    # error: dict[str, str] | None = None
```
Watch the name collision: `IssueResult.error: str | None` (L77) already exists as a per-row string. A run-level `error` dict is a different field on a different class, so keep the docstrings clear about which is which.

**Envelope serialise / parse to modify** (L118-142):
```python
    def to_envelope(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "run": asdict(self)}

    @classmethod
    def from_envelope(cls, obj: dict[str, Any]) -> RunReport:
        if obj.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported run report schema_version: {obj.get('schema_version')}; "
                f"this version of jiramator only reads schema_version={SCHEMA_VERSION}."
            )
        run = dict(obj["run"])  # shallow copy — don't mutate caller's dict
        run["issues"] = [IssueResult(**i) for i in run.get("issues", [])]
        return cls(**run)
```
Changes:
1. **Tolerant read.** Filter `run` to `{f.name for f in fields(cls)}` and each issue dict to `{f.name for f in fields(IssueResult)}` before `**`. Keep the schema check exactly as it is.
2. **Omit-when-None (A3, needs user confirmation).** In `to_envelope`, `run = asdict(self); if run.get("error") is None: run.pop("error", None)`. This keeps success reports byte-compatible with v1.2.8 `cls(**run)`.

**Helper.** Add it in a new divider section, e.g. `# Error capture`, between "Dataclasses" and "Atomic write". Use the Google-style docstring and follow RESEARCH §INV-04:
```python
def error_info(exc: BaseException) -> dict[str, str]:
    """Return a JSON-safe ``{"type", "message"}`` record for *exc*. ..."""
    message = str(exc)
    if len(message) > _ERROR_MESSAGE_CAP:
        message = message[:_ERROR_MESSAGE_CAP] + "…"
    return {"type": type(exc).__name__, "message": message}
```
Never store tracebacks, `repr(exc.request)`, or locals.

**Unaffected (do not touch):** `find_resumable` L212-262 only reads `status`/`team_config_path`/`started_at` from raw JSON, and its skip tuple `(OSError, json.JSONDecodeError, KeyError, ValueError, TypeError)` already absorbs anything odd. `write_report_atomic` L149-182 is already Ctrl-C-safe. Reuse it and don't add new IO.

---

### `jiramator/planner.py` (orchestrator, exception path)

**Analog:** itself, `run_plan` L745-795.

**Imports** (L26-40). `datetime`/`UTC` are already imported. Extend the existing `from jiramator.run_report import ...` line with `error_info`.

**Report init + `_persist` closure** (L745-773):
```python
    report = RunReport(
        command=list(command) if command else [],
        started_at=datetime.now(UTC).isoformat(),
        ...
        status="failed",  # pessimistic — flipped at the end
    )

    def _persist() -> None:
        if report_path is not None:
            write_report_atomic(report, report_path)
```

**Handler to change** (L777-795):
```python
    _persist()  # initial write — proof we got this far

    try:
        return _run_plan_inner(
            org_config, team_config, console,
            ...
            report=report, prior_created_keys=prior_created_keys,
            persist=_persist,
            ...
        )
    except BaseException:
        # Persist whatever state we got to before the exception (covers
        # JiraApiError, KeyboardInterrupt, anything else). ...
        _persist()
        raise
```
Target shape: `except BaseException as exc:` → `if report.ended_at is None: report.ended_at = datetime.now(UTC).isoformat()` → `if report.error is None: report.error = error_info(exc)` → `_persist()` → `raise`.

**`ended_at` format for plan** (L868 dry-run success, L1009 final): `datetime.now(UTC).isoformat()`, which ends in `+00:00`, **not** `Z`. Keep the format each path already uses.

**Abort sites that need a reason set *before* `sys.exit(1)`** (so the handler doesn't record `SystemExit: 1`):

| Line | Site | Has `report` in scope? |
|---|---|---|
| 143, 148, 165, 176 | input/prompt helpers before the report exists (pre-`run_plan` report init) | no. These run before L745, so no report is written yet. Leave them |
| 310-314 | `_check_and_create_fix_versions` decline ("Cannot proceed without fix versions") | no. Add a `report` kwarg or catch at the call site L893 |
| 494-502 | `_preflight_validate` field problems (`persist(); sys.exit(1)`) | gets `persist` only. Add a `report` kwarg, or set the reason at callers L862/L879 |
| 873-877 | live `JiraClient(org_config)` → "Credential error" | yes (`_run_plan_inner` has `report`) |
| 904-908 | duplicate-warning confirm declined → "Aborted." (the leading INV-01 hypothesis) | yes |
| ~940-952 | epic creation `JiraApiError` | yes |
| 1067-1084 | `_bulk_create_with_resume` `JiraApiError` | yes (`report` kwarg) |

Existing abort idiom to copy (L904-908):
```python
    if not assume_yes and not Confirm.ask(
        f"\nCreate these {total} tickets?", default=False, console=console
    ):
        console.print("[red]Aborted.[/]")
        sys.exit(1)
```
Insert `report.error = {"type": "<label>", "message": "<same text printed>"}` (or a small `_abort_reason(report, msg)` helper) right before `sys.exit(1)`. The label (`"SystemExit"` vs `"Aborted"`) is open question 3. Pick one and lock it in tests.

**Existing `requests` catch precedent** (L483-490), useful context for D-NEW-1. Do not implement D-NEW-1 in this phase unless path k is confirmed:
```python
    except JiraApiError as exc:
        console.print(f"  [yellow]⚠ Skipping field validation (Jira error): {exc}[/]")
        return
    except requests.exceptions.RequestException as exc:
        console.print(f"  [yellow]⚠ Skipping field validation (connection error): {exc}[/]")
        return
```

**Pitfall (DEFER-02-01, `.planning/milestones/v1.0-phases/02-.../deferred-items.md`):** `ConfigValidationError` is a `@dataclass(frozen=True)` exception that already propagates through this `except BaseException`. The handler must only *read* `exc` (`type(exc).__name__`, `str(exc)`) and never assign attributes on it.

---

### `jiramator/importer.py` (service, batch)

**Analog:** itself, plus the planner handler above.

**Imports** (L13): `from jiramator.run_report import IssueResult, RunReport, write_report_atomic`. Add `error_info`. importer.py does **not** import `datetime` today (checked), so add `from datetime import UTC, datetime` to the stdlib import group.

**Persist closure** (L313-325). Note that `report` is **optional** here:
```python
    def _persist() -> None:
        if report is not None and report_path is not None:
            write_report_atomic(report, report_path)
    ...
    _persist()  # initial write reflecting prior-carry-forward
```

**Handler to change** (L497-500):
```python
    except BaseException:
        # Persist whatever we got before the exception (KeyboardInterrupt et al).
        _persist()
        raise
```
Target shape: same as planner, guarded with `if report is not None:`. For `ended_at`, use the import path's format `datetime.now(UTC).isoformat().replace("+00:00", "Z")` (see cli.py L640/L663).

---

### `jiramator/cli.py` (controller, import outer handler)

**Analog:** itself, L637-669.

**Report construction + outer try** (L637-669):
```python
    report = RunReport(
        command=list(sys.argv),
        started_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        ...
        status="failed",
    )

    try:
        client = JiraClient(org_config)
        jira_fields = client.get_fields()
        result = run_import(rows, ..., report=report, report_path=report_path, prior_report=prior_report)
    except (ValueError, JiraApiError) as exc:
        # Persist the (possibly partial) report before exiting.
        report.ended_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        try:
            write_report_atomic(report, report_path)
        except OSError:
            pass
        _fail(f"Import error: {exc}")
```
Changes:
- Add `report.error = error_info(exc)` (guarded by `if report.error is None`, because `run_import`'s handler may already have set it) in the existing branch.
- Add a second `except BaseException as exc:` with the same persist body, then `raise`. This covers `requests` errors / `KeyboardInterrupt` from `JiraClient(...)`/`get_fields()` (L651-652), which today write **no report at all**. Keep `_fail(...)` only for the existing `(ValueError, JiraApiError)` pair. Don't catch `SystemExit` from `_fail` itself: order the clauses so `_fail` is outside the broad handler, or re-raise `SystemExit` untouched.
- Import `error_info` in the existing `from jiramator.run_report import (...)` block (L29-37). Keep it alphabetical; ruff `I` will check.

**Error display helpers (unchanged, reference):** `_fail` L106-109 (`click.echo(message, err=True); sys.exit(1)`), and `_load_report_file` L111-126, which maps `(ValueError, KeyError, TypeError)` → "Resume report incompatible". The tolerant `from_envelope` makes the `TypeError` branch rarer, so leave the mapping as it is.

**Plan wiring (no change):** L444-463 catches only `ConfigDriftError` / `ConfigValidationError` → `_fail`. Builder `ValueError` tracebacks belong to HYG-04 (Phase 4) and are out of scope here.

---

### `tests/test_run_report.py` (test, file-I/O)

**Analog:** `TestEnvelopeRoundTrip` L31-81, `TestFindResumable` L164+.

**Imports** (L7-24): add `error_info` to the `from jiramator.run_report import (...)` block.

**Round-trip pattern to copy** (L39-66):
```python
        roundtripped = RunReport.from_envelope(
            json.loads(json.dumps(original.to_envelope()))
        )
        assert asdict(roundtripped) == asdict(original)
```
New tests, named in the existing `test_<n>_<behavior>` style (continue numbering or use descriptive names):
- round-trip with `error={"type": "KeyboardInterrupt", "message": ""}`
- a legacy literal envelope with no `error` key loads, giving `error is None`
- an unknown extra key in `run` (and in an issue dict) is ignored
- omit-when-None: `"error" not in RunReport().to_envelope()["run"]` (if A3 is chosen)
- `error_info` truncation at the cap, ending with `…`

**find_resumable fixture pattern** (L176-196). Copy the `monkeypatch.setattr("jiramator.run_report.RUNS_DIR", runs)` + `_emit(...)` helper and add a report carrying `error`. It must still be discovered.

---

### `tests/test_planner_report.py` (test, request-response)

**Analog:** `TestPersistOnError.test_p10_keyboardinterrupt_leaves_valid_report` L537-561.

**Helpers to reuse** (L168-186). `confirm_yes=False` drives the decline path:
```python
def _patch_prompts(*, pi="28", n_versions=1, versions=("26.1.1",), confirm_yes=True):
    return [
        patch("jiramator.planner.Prompt.ask", side_effect=[pi, *versions]),
        patch("jiramator.planner.IntPrompt.ask", return_value=n_versions),
        patch("jiramator.planner.Confirm.ask", return_value=confirm_yes),
    ]

def _run_with_patches(patches, fn): ...
def _read_report(path: Path) -> dict: ...
```

**Test body pattern** (L537-561):
```python
        report_path = tmp_path / "r.json"
        fake = FakeJiraClient(interrupt_create_issue_after=1)
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                with pytest.raises(KeyboardInterrupt):
                    run_plan(org_config, team_config, dry_run=False, console=console,
                             report_path=report_path)

        _run_with_patches(patches, go)
        run = _read_report(report_path)["run"]
        assert run["status"] == "failed"
```
Extend and add:
- p10: also assert `run["ended_at"] is not None` and `run["error"]["type"] == "KeyboardInterrupt"`.
- Decline at "Create these N tickets?": `_patch_prompts(confirm_yes=False)`, `pytest.raises(SystemExit)`, assert the recorded abort reason. This is the INV-01 signature.
- Builder `ValueError`: build a `TeamConfig` in-test with a `release_sprint_schedule` missing the release count. Don't mock the builder, and **don't** touch `tests/fixtures/teams/calcs.yaml` (integration count guard).
- Resume from a legacy report with no `error` key. Copy the `TestResume` (L385+) setup.

**Fixtures** (L40-80): `org_config`, `team_config`, `console`, and the `FakeJiraClient` test double (L86+, `interrupt_create_issue_after`, `fail_bulk`). Reuse them as they are.

---

### `tests/test_importer_report.py` (test, batch)

**Analog:** `TestPersistOnInterrupt.test_i7_keyboardinterrupt_persists` L349-385.
```python
        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = create_with_interrupt
        report = _new_report()
        report_path = tmp_path / "r.json"
        with pytest.raises(KeyboardInterrupt):
            run_import(rows, org_config=_org_config(), team_config=_team_config(),
                       jira_fields=[], client=client, report=report, report_path=report_path)
        run = _read_report(report_path)["run"]
        assert run["counts"]["created"] >= 1
```
Add assertions for `ended_at` (ends with `Z`) and `error.type == "KeyboardInterrupt"`. `TestBackwardCompat` (L392+, `report=None`) must stay green; it exercises the `if report is not None` guard. Helpers are `_org_config()`, `_team_config()`, `_read_report`, `_new_report` (L21-57).

---

### `tests/test_import_cli.py` (test, CLI request-response)

**Analog:** `test_live_mode_continues_after_row_failure_and_reports_summary` L190-240.
```python
        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: rows)
        client = MagicMock()
        client.get_fields.return_value = []
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda org_config: client)
        result = runner.invoke(cli, ["import", "--org-config", str(org_config_path),
                                     "--team-config", str(team_config_path), str(sheet_path)])
        assert result.exit_code == 1
```
New case: `client.get_fields.side_effect = requests.exceptions.ConnectionError("boom")`, pass `--report <tmp_path>/r.json`, then assert the file exists and `run["error"]["type"] == "ConnectionError"`. Patch `jiramator.cli.JiraClient` (the place it is used, per AGENTS.md). The `runner` fixture is at L16-18, and `org_config_path`/`team_config_path` come from `tests/conftest.py`. Always pass `--report` into `tmp_path` so no test writes into `.jiramator/runs/` (TEST-01).

---

### `.planning/phases/01-production-triage/01-TRIAGE-FINDINGS.md` (doc)

**Analogs:** `2-UAT.md` (YAML frontmatter `status/phase/source/started/updated`, then `## Summary` counts block and `## Gaps`), and `deferred-items.md` (per-finding `## ID: title` with **Found during / Symptom / Root cause / Why deferred / Suggested fix path**).

**Content source:** `01-RESEARCH.md` §Findings Table (rows 1-5 mandatory, 6-9 recommended), with the D-11 columns: report file, command, classification, root cause, disposition, evidence. Add an INV-01 section (exit-point table a-k plus the human-verify outcome), an INV-02 section (evidence chain 1-6), and a D-NEW-1 write-up in the `deferred-items.md` style with its disposition (D-09 requirement link or D-10 GitHub issue URL).

---

## Shared Patterns

### Persist-on-error (apply to planner.py, importer.py, cli.py)
**Source:** `jiramator/planner.py` L790-795, `jiramator/importer.py` L497-500.
Always `except BaseException as exc:` → set `ended_at` only if it is unset → set `error` only if it is `None` → `_persist()` / `write_report_atomic` → bare `raise`. Never swallow. The inner handler fills it first and the outer handler (cli import) must not overwrite.

### Timestamp format (per path, don't unify)
- plan: `datetime.now(UTC).isoformat()` (planner.py L747, L868, L1009)
- import: `datetime.now(UTC).isoformat().replace("+00:00", "Z")` (cli.py L640, L663)

### User-facing output
`console.print(...)` with Rich markup (`[red]Aborted.[/]`). Use `_fail()` in cli.py for unrecoverable errors. Never `print()`. INV-04 adds persistence only and leaves displayed messages unchanged.

### Test patching location
`jiramator.planner.JiraClient`, `jiramator.planner.Confirm.ask`, `jiramator.cli.JiraClient`, `jiramator.cli.read_spreadsheet`: patch where the symbol is used. Every `report_path` goes under `tmp_path`.

### Section dividers
Use `# ----...` / `# Name` / `# ----...` in new source sections and new test classes (e.g. run_report.py L36-38, test_planner_report.py L532-534).

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| — | — | — | Every file is modified in place or has a doc analog. The offline harness `/tmp/jm-triage/harness.py` is outside the repo, so it is not mapped. If the planner turns it into a pytest, use the `CliRunner` + `monkeypatch.setattr("jiramator.planner.JiraClient", ...)` pattern from `tests/test_import_cli.py` L190-240 and `FakeJiraClient` from `tests/test_planner_report.py` L86+ |

## Metadata

**Analog search scope:** `jiramator/` (run_report, planner, importer, cli), `tests/` (test_run_report, test_planner_report, test_importer_report, test_import_cli), `.planning/milestones/v1.0-phases/`, `CHANGELOG.md`
**Files scanned:** 12
**Pattern extraction date:** 2026-10-02
