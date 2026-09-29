---
phase: 02-template-inheritance-sprint-assignment
plan: 01
subsystem: config
tags: [template-inheritance, merge-engine, pydantic, tdd]
requires:
  - jiramator/yaml_loader.py:safe_load_with_lines
  - jiramator/yaml_loader.py:resolve_line
  - jiramator/yaml_loader.py:strip_line_markers
  - jiramator/yaml_loader.py:LINE_KEY
  - jiramator/error_format.py:ConfigValidationError
provides:
  - jiramator/config_merge.py:canonical_form
  - jiramator/config_merge.py:concat_dedup_lists
  - jiramator/config_merge.py:deep_merge_dicts
  - jiramator/config_merge.py:merge_team_defaults_into_templates
  - jiramator/error_format.py:ConfigConflictWarning
  - jiramator/config.py:TeamDefaults
  - jiramator/config.py:TeamConfig.defaults
affects:
  - jiramator/config.py:load_team_config (now applies team-defaults merge)
tech-stack:
  added: [] # stdlib-only (json, pathlib)
  patterns:
    - earlier-wins recursive dict merge
    - JSON-canonical-form list dedup
    - frozen dataclass for non-Exception warnings
    - Pydantic sub-model wrapper (TeamDefaults)
key-files:
  created:
    - jiramator/config_merge.py
    - tests/test_config_merge.py
  modified:
    - jiramator/config.py
    - jiramator/error_format.py
    - tests/test_config.py
    - tests/test_error_format.py
decisions:
  - Load-time merge (RESEARCH §R4 option a) — TeamConfig returned from load_team_config carries already-merged template fields.
  - merge_team_defaults_into_templates mutates template.fields in place but never mutates source defaults.fields (T-02-06 mitigation).
  - LINE_KEY skipped on both sides of every dict merge as defense-in-depth (T-02-01).
  - Local import of merge module inside load_team_config keeps the dependency direction trivially obvious.
  - load_team_config gains optional console kwarg; default Console(stderr=True) instantiated when None.
metrics:
  duration_minutes: 25
  completed: 2026-04-30
  tests_added: 43
  tests_total_after: 460
  tests_baseline_before: 417
  regressions: 0
---

# Phase 2 Plan 01: Team Template Inheritance Merge Engine — Summary

**One-liner:** Team-internal `defaults:` block merges into every template's `fields` at load time with earlier-wins semantics, list concat-dedup, and stderr conflict warnings — eliminating the ~25 lines of repeated `priority`/`customfield_*` declarations across `calcs.yaml` templates.

## What Shipped

A pure-stdlib merge engine (`jiramator/config_merge.py`) plus `TeamDefaults` Pydantic sub-model and `defaults` field on `TeamConfig`. After Pydantic validation, `load_team_config` calls `merge_team_defaults_into_templates`, which propagates `defaults.fields` into every `recurring_epics`, `per_release_tickets`, and `per_sprint_tickets` entry. Disjoint keys flow through; same-key dict×dict recurses; same-key list×list concat-dedups (multi-select union behavior); same-key scalar/shape-mismatch is earlier-wins with one `ConfigConflictWarning` printed to `Console(stderr=True)` in the canonical Phase 1 plain-text format:

```
<file>:<later-line>: <field-path> — locked by team defaults (<file>:<earlier-line>); later value ignored.
```

Smoke-verified end-to-end against `configs/teams/calcs.yaml`: hoisting `priority: Medium` into a synthetic `defaults:` block, then deleting `priority` from one ticket, results in that ticket's merged `fields["priority"] == "Medium"` while every still-declaring ticket emits exactly one warning.

## How It Was Built (TDD)

Two tasks, each RED → GREEN:

1. **Task 1 — Merge engine.** RED: 25 unit tests across `TestCanonicalForm`, `TestConcatDedupLists`, `TestDeepMergeDicts`, `TestMergeTeamDefaultsIntoTemplates`, plus 5 `TestConfigConflictWarning` tests in `test_error_format.py`. GREEN: `config_merge.py` + `ConfigConflictWarning` dataclass + `TeamDefaults` Pydantic sub-model and `TeamConfig.defaults` field.
2. **Task 2 — Loader wiring.** RED: `TestTeamDefaultsPydantic` (P1–P6) and `TestTeamDefaultsMergeIntegration` (I1–I6) in `tests/test_config.py` — backward-compat against real `calcs.yaml`, propagation across all three template lists, stderr capture for warnings, list concat through the loader, calcs-style realistic fixture. GREEN: `load_team_config` calls `merge_team_defaults_into_templates` after Pydantic validation; warnings routed through optional `console` kwarg (default `Console(stderr=True)`).

## Commits

| Commit | Phase | Type | Subject |
| --- | --- | --- | --- |
| `576a1d0` | RED  | test | add failing tests for merge engine and ConfigConflictWarning |
| `d2fe473` | GREEN | feat | merge engine and ConfigConflictWarning + TeamDefaults shape |
| `7a9aac3` | RED  | test | add TestTeamDefaults Pydantic + integration tests |
| `2d7fb15` | GREEN | feat | wire merge_team_defaults into load_team_config + integration tests |

## Verification Results

- `pytest tests/test_config_merge.py tests/test_error_format.py tests/test_config.py -v` → **122 passed** (43 new in this plan, 79 existing).
- `pytest -q` (full suite) → **460 passed** in ~1.2s.
- Baseline before plan: 417 passed. New: 43. Regressions: **0**.
- `grep -n "__line__" jiramator/config_merge.py` → 5 hits, all in import / skip-condition / docstring contexts; never propagated into merged dicts (T-02-01 verified).
- Manual smoke: hoisting `priority` into `defaults:` of `calcs.yaml` and removing from one ticket → that ticket's merged `fields["priority"] == "Medium"`; remaining tickets that still declare `priority` get one warning each in the canonical format.

## Acceptance / Done Criteria

| Criterion | Status |
| --- | --- |
| `TeamConfig.defaults: TeamDefaults` exists, defaults to empty | ✅ |
| `load_team_config` applies merge after Pydantic validation, before return | ✅ |
| Same-key conflicts: earlier wins; warning in canonical format on stderr | ✅ |
| Multi-select-shaped lists concat with order-preserving JSON-canonical-form dedup | ✅ |
| Existing 417 tests pass without modification | ✅ |
| `configs/teams/calcs.yaml` loads identically to before this plan (no defaults block) | ✅ |
| `__line__` markers do not propagate into merged template fields | ✅ |
| No new runtime dependency added (stdlib `json` only — DC-3) | ✅ |

## Deviations from Plan

### Auto-fixed test-data issues

**1. [Rule 1 – Test bug] M6 line-resolution expected wrong line.**
- **Found during:** Task 1 GREEN run.
- **Issue:** Test expected `earlier_line == 4` (the YAML line of `fields:` token), but PyYAML's `node.start_mark.line` for nested mappings reports the line of the first child key (line 5: `priority: High`). My initial expectation was based on a misreading of `SafeLineLoader`.
- **Fix:** Updated test expectation to match PyYAML semantics: `earlier_line == 5` and `later_line == 9`. Test comment rewritten to document why.
- **Files modified:** `tests/test_config_merge.py`
- **Commit:** `d2fe473` (rolled into the GREEN commit since the test was the new test being made green).

**2. [Rule 1 – Test bug] P6 calcs.yaml backward-compat test asserted on wrong field.**
- **Found during:** Task 2 RED first run.
- **Issue:** Asserted `len(cfg.recurring_epics) >= 1`, but `calcs.yaml` uses `existing_epics:` (not `recurring_epics:`).
- **Fix:** Generalized to assert `len(recurring_epics + per_release_tickets + per_sprint_tickets) >= 1`.
- **Files modified:** `tests/test_config.py`
- **Commit:** `7a9aac3` (rolled into the RED commit before GREEN).

**3. [Rule 1 – Fixture conflict] I5 calcs-style fixture inherited stale per_sprint_tickets.**
- **Found during:** Task 2 GREEN.
- **Issue:** Base `team_config_data` fixture defines a `per_sprint_tickets[0]` with `customfield_10014: $epic:misc`, which collides with the same key being hoisted into `defaults.fields`. The intent of I5 is "zero warnings on a clean hoist."
- **Fix:** I5 explicitly clears `per_sprint_tickets = []` before loading.
- **Files modified:** `tests/test_config.py`
- **Commit:** `2d7fb15` (rolled into the GREEN commit).

### Requirement-marking scope

The plan frontmatter declares `requirements: [TMPL-01, TMPL-02]`, but `REQUIREMENTS.md` defines TMPL-01 as covering BOTH org-locked default fields AND team-internal default fields. **Plan 02-01 ships only the team-internal half**; the org-locked half is Plan 02-02 work.

- **TMPL-02** ships fully (stderr conflict warnings at config-load time + visible team-internal `defaults:` block).
- **TMPL-01** is **partially shipped** (team-internal half done, org half pending Plan 02-02).

**Action:** This SUMMARY marks TMPL-02 complete; TMPL-01 stays open until Plan 02-02 lands the org `default_fields` half. The `state.add-decision` queue records this scoping.

## Out-of-Scope Items (Logged for Plan 02-02 / 02-03)

- Org-level `default_fields:` block on `OrgConfig` and the `merge_configs(org, team)` orchestrator. (Plan 02-02.)
- Sprint-mode resolution (`sprints_exist` + `--sprints-exist/--no-sprints-exist`). (Plan 02-03.)
- Importer-side application of org `default_fields` for `bulk_create` rows. (Plan 02-02 may include or defer per RESEARCH.md §R2.)

## Threat Surface Status

All five `mitigate` items in the plan's `<threat_model>` are covered:

| ID | Disposition | Status |
| --- | --- | --- |
| T-02-01 | mitigate | ✅ `LINE_KEY` skipped on both sides in `deep_merge_dicts`; tested by D7. |
| T-02-02 | accept | ✅ Documented; structural dedup is correct behavior. |
| T-02-03 | accept | ✅ Same channel as Phase 1. |
| T-02-04 | accept | ✅ Mirrors Phase 1 path-rendering; `_rel` falls back to absolute. |
| T-02-05 | accept | ✅ No new surface. |
| T-02-06 | mitigate | ✅ Test M5 asserts `defaults.fields` unchanged after merge; engine builds fresh `out` dict. |

No new threat surface introduced beyond what is in the register.

## Self-Check: PASSED

**Files claimed → verified on disk:**

- `jiramator/config_merge.py` — FOUND.
- `jiramator/error_format.py` — FOUND (extended with `ConfigConflictWarning`).
- `jiramator/config.py` — FOUND (extended with `TeamDefaults` + `defaults` field + merge call in `load_team_config`).
- `tests/test_config_merge.py` — FOUND (new, 26 tests).
- `tests/test_config.py` — FOUND (extended with `TestTeamDefaultsPydantic` + `TestTeamDefaultsMergeIntegration`).
- `tests/test_error_format.py` — FOUND (extended with `TestConfigConflictWarning`).

**Commits claimed → verified in git log:**

- `576a1d0` — FOUND (`test(02-01): add failing tests for merge engine and ConfigConflictWarning`).
- `d2fe473` — FOUND (`feat(02-01): merge engine and ConfigConflictWarning + TeamDefaults shape`).
- `7a9aac3` — FOUND (`test(02-01): add TestTeamDefaults Pydantic + integration tests`).
- `2d7fb15` — FOUND (`feat(02-01): wire merge_team_defaults into load_team_config + integration tests`).
