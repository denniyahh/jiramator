---
phase: 02
review: 02-REVIEW.md
titles: json
findings:
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "Falsy (but non-blank) deferred-field cell values can be misread as blank"
  - id: WR-02
    severity: warning
    disposition: skipped
    title: "`unavailable` preflight status silently drops already-known build-failed rows from the dry-run report"
  - id: IN-01
    severity: info
    disposition: open
    title: "`PermissiveFieldMeta.__contains__` always returns `True`, disabling off-screen coverage for default `stub_createmeta()` tests"
  - id: IN-02
    severity: info
    disposition: open
    title: "Duplicate inline SC1 createmeta/sheet fixtures between test_import_cli.py and test_import_preflight.py"
---

# Phase 02: Code Review Disposition

| ID | Severity | Disposition | Notes |
|----|----------|-------------|-------|
| WR-01 | warning | fixed | `b7b79ae` — `_deferred_present` now uses the same `isinstance(raw, str) and raw.strip()` predicate as `run_import`. Latent in practice (`spreadsheet._coerce_cell` stringifies every cell), but preflight and create-time now agree by construction. Regression test `test_non_string_deferred_cell_is_missing_required` (red before fix with `Sprint: 5`). |
| WR-02 | warning | skipped | By design per D-08: build-failed rows join the preflight report only "whenever validation itself runs". When createmeta is unavailable the run degrades to the pre-1.2.9 behaviour (preview capped by `--preview-rows`; live run records them as failed IssueResults). Revisit only if D-08 is reopened. |
| IN-01 | info | open | Intentional test-stub permissiveness (02-02); off-screen checks are covered by dedicated tests in test_import_preflight.py. |
| IN-02 | info | open | Test-fixture duplication; candidate for a shared conftest helper in Phase 4 hygiene. |
