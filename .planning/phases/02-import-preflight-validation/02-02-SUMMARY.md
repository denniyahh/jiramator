---
phase: 02-import-preflight-validation
plan: 02
subsystem: tests
tags: [preflight, createmeta, test-harness, mocks]
status: complete

requires:
  - phase: 02-import-preflight-validation
    provides: "02-01 run_preflight / find_payload_problems contract (field_metadata.get + items())"
provides:
  - "tests/conftest.py: PermissiveFieldMeta(dict) + stub_createmeta(client, issue_types=('Risk',), fields_by_type=None)"
  - "Every live run_import MagicMock client in test_importer_report/test_importer/test_import_integration is createmeta-stubbed"
  - "FakeJiraClient.get_createmeta_issue_types / get_createmeta_fields; _write_import_org_config (issuetype default Task)"
  - "test_cli stub_run_import _FakeResult.preflight = None"
affects: [02-03, 02-04]

actuals:
  tokens: 4451
  tasks: 2
  commits: 2
plan_head_before: e3b68b793eb0ffe294bfadba1c50a666b3d1e7fe
plan_head_after: 40d2dc935dc43ad5aaaa657dce9a135968744459

tech-stack:
  added: []
  patterns:
    - "Permissive createmeta dict: lookups always succeed with non-required, schema-less descriptors; iteration sees only explicit entries"

key-files:
  created: []
  modified:
    - tests/conftest.py
    - tests/test_importer_report.py
    - tests/test_importer.py
    - tests/test_import_integration.py
    - tests/test_cli_e2e.py
    - tests/test_cli.py

key-decisions:
  - "PermissiveFieldMeta.get ignores the caller's default and always returns a permissive descriptor for unknown ids, so off-screen checks (which use .get) never fire unless a test opts in via fields_by_type"
  - "E3 import test uses a separate _write_import_org_config; shared _write_org_config left untouched so plan tests and their config hash are unaffected"

requirements-completed: [PRE-03]

duration: ~6min
completed: 2026-10-15
---

# Phase 02 Plan 02: Createmeta test stub for live import tests Summary

**A shared `stub_createmeta` helper and `PermissiveFieldMeta` dict now give every live import test client permissive createmeta answers. Plan 03 can turn on live preflight without the ~25 existing live-import tests failing on "Issue type … is not available" or off-screen fields.**

## Performance
- Duration: ~6 min
- Tasks: 2/2
- Files modified: 6

## Accomplishments
- `PermissiveFieldMeta(dict)`: any `get`, `[]` or `in` lookup returns `{"name": id, "required": False}` (no schema, no allowedValues). Only the descriptors a test supplies show up in `items()`, iteration and `len()`.
- `stub_createmeta(client, issue_types=("Risk",), fields_by_type=None)` stubs `get_createmeta_issue_types` (ids 10000+) and `get_createmeta_fields` (returns a `PermissiveFieldMeta` per type name).
- Stub calls were added after all 23 live `MagicMock()` clients: 10 in test_importer_report, 12 in test_importer, 1 in test_import_integration. All of these tests use issue type Risk.
- `TestStubCreatemeta` (6 tests) pins the contract, including `validate_ticket_payload(..., report_off_screen_fields=True) == []`.
- FakeJiraClient now has the two createmeta methods. The E3 import test uses `_write_import_org_config`, which sets `bulk_create.defaults.issuetype: Task`.
- `_FakeResult.preflight = None` added in test_cli's `stub_run_import`.

## Task Commits
1. **Task 1 (tracer): stub helper + report tests**: `7983c73`
2. **Task 2: remaining live tests, e2e fake, test_cli stub**: `40d2dc9`

## Tracer gate
Plan 01's `run_preflight` had already landed, so I checked the stub against the real preflight early instead of waiting for Plan 03. I ran `run_import(..., dry_run=True)` with `stub_createmeta(MagicMock())` and the report-test org config and got `status=passed, checked_rows=2, problems=[]`. The e2e `FakeJiraClient` with `_write_import_org_config` also gave `passed`, 1 row checked. These were throwaway scripts and were not committed.

## Verification
- `python -m pytest -q`: 733 passed (727 before plus 6 new `TestStubCreatemeta` tests). The 1 warning is pre-existing (tests/test_integration.py class-scoped fixture) and outside this plan's scope.
- `ruff check .`: All checks passed.
- No `assert` lines were removed. The only deleted line across both diffs is `str(configs["org"]),` in the E3 test, replaced by `str(import_org),`.

## Deviations from Plan
None. The plan was executed as written. `ruff check --fix` sorted imports once in test_importer_report.py.

## Deferred human verification
None. These are test-only changes and make no Jira calls.

## Self-Check: PASSED
- FOUND: tests/conftest.py (`class PermissiveFieldMeta(dict)`, `def stub_createmeta(`)
- FOUND: 7983c73, 40d2dc9 (ancestors of HEAD)
