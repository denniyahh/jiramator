---
phase: 01-reliability-robustness
plan: 01
subsystem: config-validation
tags: [yaml, pydantic, error-formatting, line-tracking, did-you-mean]
provides:
  - Line-aware YAML loader (SafeLineLoader) injecting __line__ on every parsed mapping
  - resolve_line walking Pydantic loc tuples through the tagged structure
  - ConfigValidationError frozen dataclass + Exception subclass with file:line:field — reason format
  - format_loc converting Pydantic loc tuples to a.b[0].c.d field paths
  - did_you_mean PEP-657-style spelling suggestions via difflib
  - load_org_config / load_team_config raising ConfigValidationError (not FileNotFoundError/ValueError)
  - strip_line_markers (yaml_loader) + _strip_line_markers wiring in _build_fields_payload to prevent __line__ leakage into Jira payloads (Pitfall 1, STRIDE T-01-01)
affects: [reliability-robustness, all future yaml-config phases]
tech-stack:
  added: []
  patterns:
    - Line-tracking subclass of yaml.SafeLoader (SafeLineLoader)
    - Tagged-tree + clean-tree split (parse once with markers, strip for Pydantic, retain tagged for line resolution)
    - ValidationError → ConfigValidationError adapter with first-error semantics
    - Defensive strip at API boundary (ticket_builder strips before payload assembly)
key-files:
  created:
    - jiramator/yaml_loader.py
    - jiramator/error_format.py
    - tests/test_yaml_loader.py
    - tests/test_error_format.py
    - tests/test_config_loader_errors.py
    - tests/test_ticket_builder_strip_lines.py
    - tests/fixtures/yaml_errors/missing_required.yaml
    - tests/fixtures/yaml_errors/extra_forbidden.yaml
    - tests/fixtures/yaml_errors/nested_typo.yaml
    - tests/fixtures/yaml_errors/yaml_parse_error.yaml
  modified:
    - jiramator/config.py
    - jiramator/ticket_builder.py
    - tests/test_config.py
key-decisions:
  - "strip_line_markers lives in yaml_loader.py (single source of truth); ticket_builder imports it as _strip_line_markers to satisfy plan's naming convention."
  - "_wrap_validation_error surfaces only the first Pydantic error (singular ConfigValidationError per the plan); did-you-mean suggestion mined heuristically from 'Unknown template variable' messages."
  - "Non-mapping document root reports line=1 + field_path='<root>'; OS errors report line=None + field_path='<file>'; YAML parse errors report line from problem_mark.line+1 + field_path='<yaml>'."
  - "extra_forbidden.yaml fixture kept as a regression target only — Pydantic default extra='ignore' means no error is raised today; documented inline."
duration: 1.5h
completed: 2026-04-28
---

# Plan 01-01: Actionable Config Validation Errors (FOUND-01) Summary

**Replaced opaque `pydantic.ValidationError` traces with single-line, file:line-pinpointed, field-path-aware error messages and closed the `__line__`-leakage attack surface from Jira payloads.**

## Performance
- **Duration:** ~1.5h
- **Tasks:** 3 (all completed) + S1–S4 wiring addendum
- **Files modified:** 13 (4 source, 4 test, 4 fixture, 1 existing test updated)

## Accomplishments
- All 5 must-have truths from the plan satisfied:
  1. ✓ YAML errors name file, 1-indexed line, dotted field path.
  2. ✓ Typo on `{sprint_n}` produces `(did you mean 'sprint_num'?)` suggestion.
  3. ✓ YAML parse errors include the line where pyyaml stopped.
  4. ✓ Built ticket payloads never contain `__line__` (verified end-to-end on real Calcs config via S4).
  5. ✓ Zero regressions: 277 baseline tests still pass; total 324 passing.
- 47 new tests across 4 new test files (12 yaml_loader + 15 error_format + 8 config_loader_errors + 12 ticket_builder_strip_lines).
- STRIDE T-01-01 (Tampering: marker leaking into Jira fields) mitigated and integration-tested.

## Task Commits
1. **Task 1: Line-aware YAML loader + Pydantic-loc resolver** — `3850970`
2. **Task 2: ConfigValidationError + format_loc + did_you_mean** — `5545db1`
3. **Task 3: Wire loader + error format into config loaders, defuse __line__ leak** — `a4157f2`
4. **Addendum: S1–S4 Pitfall 1 wiring tests** — `e54c844`

## Files Created/Modified
- `jiramator/yaml_loader.py` — SafeLineLoader, safe_load_with_lines, resolve_line, strip_line_markers, LINE_KEY constant.
- `jiramator/error_format.py` — ConfigValidationError frozen dataclass, format_loc, did_you_mean (difflib-backed).
- `jiramator/config.py` — _wrap_validation_error adapter; _load_yaml_with_lines shared helper; load_org_config/load_team_config rewritten to raise ConfigValidationError for all error paths (file-not-found, OS read, YAML parse, non-mapping root, Pydantic validation).
- `jiramator/ticket_builder.py` — Imports strip_line_markers as _strip_line_markers; applies it in _build_fields_payload before iterating template_fields.
- `tests/test_yaml_loader.py` — 12 tests for loader + resolver (1-indexing, nested, list-of-mapping, deterministic wrapper, edge cases).
- `tests/test_error_format.py` — 15 tests for ConfigValidationError __str__ shape, path resolution, immutability, format_loc shapes, did_you_mean phrasing.
- `tests/test_config_loader_errors.py` — 8 tests covering all 4 error fixtures + nonexistent-file + non-mapping-root + full rendered-string spot-check.
- `tests/test_ticket_builder_strip_lines.py` — 12 tests: 8 unit tests of _strip_line_markers + S1–S3 _build_fields_payload integration + S4 full build_all on real shipped configs.
- `tests/test_config.py` — 4 existing loader-error tests updated from FileNotFoundError/ValueError to ConfigValidationError.
- `tests/fixtures/yaml_errors/{missing_required,extra_forbidden,nested_typo,yaml_parse_error}.yaml` — minimal hand-authored fixtures.

## Decisions & Deviations
- **Decision:** `strip_line_markers` is the single canonical implementation in `yaml_loader.py`; `ticket_builder.py` aliases it as `_strip_line_markers` to satisfy the plan's naming. Avoids duplication while honoring the plan's locality requirement.
- **Decision:** `extra_forbidden.yaml` fixture exists for future regression coverage even though Pydantic's default `extra='ignore'` does not raise today — documented inline.
- **Decision:** Used Python 3.11+ `dataclass(frozen=True)` on an Exception subclass; project pyproject pins `>=3.11` so this is supported.
- **Deviation (minor):** Plan listed only Tasks 1–3 but referenced S1–S4 tests in the integration section. Added them as a fourth commit (`e54c844`) to fully realize Pitfall 1 coverage and the STRIDE T-01-01 mitigation evidence the plan requires.

## Next Phase Readiness
- Plans 01-02 (existing-epics whitespace tolerance) and 01-03 (next/another plan in Wave 1) can proceed in parallel — no file overlaps with 01-01.
- The `ConfigValidationError` raise contract is now stable; any future config validator can reuse `_wrap_validation_error` with its own known-set for did-you-mean.
- The `LINE_KEY` defuse pattern (strip-at-boundary) is documented in `_build_fields_payload` for future Jira-payload assembly sites.
