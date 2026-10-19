---
phase: 02-import-preflight-validation
reviewed: 2026-10-15T17:47:29Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - jiramator/cli.py
  - jiramator/import_preflight.py
  - jiramator/importer.py
  - jiramator/payload_validator.py
  - tests/conftest.py
  - tests/test_cli.py
  - tests/test_cli_e2e.py
  - tests/test_import_cli.py
  - tests/test_import_integration.py
  - tests/test_import_preflight.py
  - tests/test_importer.py
  - tests/test_importer_report.py
  - tests/test_payload_validator.py
findings:
  critical: 0
  warning: 2
  info: 2
  total: 4
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-10-15T17:47:29Z
**Depth:** standard
**Files Reviewed:** 13
**Status:** issues_found

## Summary

Reviewed the diff between `8768b35` and `HEAD` implementing import preflight
validation (`import_preflight.py`), the `payload_validator.py` refactor to a
structured `PayloadProblem`/`find_payload_problems` API, the `importer.py`
build-error and abort-before-create changes, and the `cli.py` dry-run/live
wiring. `ruff check .` passes clean and the full test suite (779 tests)
passes. The implementation matches the `02-CONTEXT.md` decisions (D-01
through D-11) closely: Rich-markup injection from spreadsheet-sourced text is
consistently defused via `rich.markup.escape()` at render time, the
`plan`/`import` validator behavior split is achieved via opt-in keyword
arguments with byte-identical defaults for `plan`, and the live-abort/record
path matches the D-11 "one `IssueResult` per failing row" design.

No BLOCKER-level defects were found. Two WARNING-level robustness/consistency
gaps and two INFO-level quality notes are below — all narrow edge cases, not
core-path correctness problems.

## Warnings

### WR-01: Falsy (but non-blank) deferred-field cell values can be misread as blank

**File:** `jiramator/import_preflight.py:139`
**Issue:** `_deferred_present` decides whether a deferred field (reporter,
assignee, parent, sprint) has a "present" raw value with:
```python
if not str(source_row.get(header, "") or "").strip():
    continue
```
Because `0 or ""` evaluates to `""` in Python, a raw cell value that is the
integer `0` (possible for a numeric Sprint-ID column read from an XLSX sheet,
where openpyxl yields `int`/`float` rather than `str`) is treated as blank
here, even though `0` is a legitimate (if degenerate) numeric value elsewhere
in the codebase (e.g. `_SPRINT_ID_RE` matches `"0"`). The practical blast
radius is small (sprint id 0 is not a realistic Jira sprint id), but the same
`or ""` pattern would also swallow a legitimate `False`/`0` value for any
future deferred field. Compare with the same cell being read later in
`run_import`'s create-time resolution loop, which uses
`isinstance(raw_value, str) and raw_value.strip()` — a stricter and more
correct check that doesn't have this falsy-collapse bug.
**Fix:**
```python
raw = source_row.get(header, "")
if not isinstance(raw, str) or not raw.strip():
    continue
```
(mirrors the type-check already used in `run_import`'s own deferred-field
resolution, so a non-string cell is explicitly excluded rather than
silently coerced through `or ""`).

### WR-02: `unavailable` preflight status silently drops already-known build-failed rows from the dry-run report, beyond what `--preview-rows` would show

**File:** `jiramator/import_preflight.py:291-299` (the `except (JiraApiError,
requests.exceptions.RequestException)` handler in `run_preflight`)
**Issue:** `build_failed_rows` is computed unconditionally before the
createmeta fetch attempt, but the `except` handler that produces
`status="unavailable"` returns `rows=[]`, discarding them. When createmeta is
unavailable in **dry-run**, `render_preflight_report` only ever shows the
one-line "Schema validation skipped: …" message for that status — it never
falls back to listing `build_failed_rows`. The only remaining visibility
into those rows is `render_preview_report`'s row listing, which **is**
capped by `--preview-rows` (default 5). D-11 states "The console prints
every failing row, with no truncation" as a general preflight-report
guarantee; this combination (createmeta unavailable + more than
`--preview-rows` build-failed rows) is the one path where that guarantee
silently does not hold in dry-run output, even though the same rows are
still correctly recorded as `failed` IssueResults once a *live* run reaches
the per-row creation loop (confirmed by
`tests/test_importer_report.py::test_unavailable_proceeds_and_records_build_failures_as_today`,
which only exercises the live path, not dry-run rendering with >5 failed
rows).
**Fix:** Either have `run_preflight`'s `unavailable` branch still populate
`rows=build_failed_rows` (status stays `unavailable`, but
`render_preflight_report`'s `unavailable` branch is extended to also print
any carried `build_failed_rows`), or document the gap explicitly in
`render_preflight_report`'s docstring / `02-CONTEXT.md` D-11 so it isn't
assumed to be total.

## Info

### IN-01: `PermissiveFieldMeta.__contains__` always returns `True`, silently disabling `report_off_screen_fields` coverage for any test using the default `stub_createmeta()`

**File:** `tests/conftest.py:62-71`
**Issue:** `find_payload_problems`'s off-screen check is `meta =
field_metadata.get(field_id); if meta is None: …`. Since
`PermissiveFieldMeta.get()` never returns `None` (falls back to a synthetic
descriptor), any `tests/test_importer*.py` test that uses the default
`stub_createmeta(client)` without an explicit `fields_by_type` can never
exercise the D-10 off-screen-field path for *any* field it didn't
deliberately enumerate — this is documented in the class docstring and is
evidently intentional, but it also means most of the "plumbing" tests in
`test_importer.py` (reporter/assignee/parent/sprint resolution) are not
incidentally verifying that preflight doesn't false-positive on fields those
tests happen to send. Low risk since `test_import_preflight.py` covers
off-screen behavior directly, but worth flagging so a future refactor of
`PermissiveFieldMeta` doesn't accidentally start producing off-screen noise
across the whole suite without anyone noticing it was previously suppressed.
**Fix:** No action required; consider a one-line comment at each
`stub_createmeta()` call site in `test_importer.py` noting that off-screen
checks are deliberately bypassed there, to avoid the silent-pass surprising
a future reader debugging a seemingly-unrelated failure.

### IN-02: Duplicate inline SC1 createmeta/sheet fixtures between `tests/test_import_cli.py` and `tests/test_import_preflight.py`

**File:** `tests/test_import_cli.py:567-592`, `tests/test_import_preflight.py:50-75`
**Issue:** `_sc1_createmeta()` and the SC1 sheet-building helpers are
duplicated near-verbatim across the CLI-level and preflight-unit test files
(same field ids, same `repos` list, same row-count assumptions). This is a
reasonable layering choice per `02-CONTEXT.md` ("Test layout … following
AGENTS.md mocking rules" left to the agent's discretion), but the
duplication means a future schema change to the SC1 fixture (e.g. adding a
problem) must be kept in sync by hand across two files with no shared
import, risking silent drift between the CLI-level and unit-level
assertions about the same incident replay.
**Fix:** Extract the shared `_sc1_createmeta()` / sheet-building helpers into
`tests/conftest.py` alongside `stub_createmeta()`, parameterized the same way,
and import from both test modules.

---

_Reviewed: 2026-10-15T17:47:29Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
