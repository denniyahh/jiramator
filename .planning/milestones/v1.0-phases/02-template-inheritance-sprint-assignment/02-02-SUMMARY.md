---
phase: 02-template-inheritance-sprint-assignment
plan: 02
subsystem: config
tags: [template-inheritance, merge-engine, org-locking, cli-wiring, tdd]
requires:
  - jiramator/config_merge.py:deep_merge_dicts
  - jiramator/config_merge.py:concat_dedup_lists
  - jiramator/config_merge.py:canonical_form
  - jiramator/error_format.py:ConfigConflictWarning
  - jiramator/yaml_loader.py:resolve_line
  - jiramator/yaml_loader.py:LINE_KEY
provides:
  - jiramator/config.py:OrgConfig.default_fields
  - jiramator/config_merge.py:merge_configs
  - jiramator/config_merge.py:_apply_team_layer_to_templates
  - jiramator/config.py:load_org_config (tuple return)
  - jiramator/config.py:load_team_config (tuple return; merge no longer internal)
affects:
  - jiramator/cli.py:plan (wires merge_configs between loaders and run_plan)
  - jiramator/cli.py:import_command (unpacks the new tuple; does NOT merge)
  - jiramator/importer.py (carries Phase-2-scope documentation comment)
  - tests/test_config.py (loader callsites unpack tuple; I1-I6 rewired through merge_configs)
  - tests/test_cli.py / tests/test_integration.py / tests/test_run_report.py / tests/test_import_integration.py / tests/test_ticket_builder_strip_lines.py / scripts/dry_run.py (callsites updated)
tech-stack:
  added: []   # stdlib + already-vendored rich
  patterns:
    - layered-merge orchestrator (org → team-defaults → templates)
    - tuple-returning loaders carrying tagged_raw for late line resolution
    - extracted helper (_apply_team_layer_to_templates) reused by orchestrator + tests
    - source-comment scope guard (importer Phase-2 boundary)
key-files:
  created:
    - tests/test_config_inheritance_integration.py
  modified:
    - jiramator/config.py
    - jiramator/config_merge.py
    - jiramator/cli.py
    - jiramator/importer.py
    - tests/test_config.py
    - tests/test_config_merge.py
    - tests/test_cli.py
    - tests/test_integration.py
    - tests/test_run_report.py
    - tests/test_import_integration.py
    - tests/test_ticket_builder_strip_lines.py
    - scripts/dry_run.py
decisions:
  - merge_configs is the SINGLE composition point for all template-inheritance layers; load_team_config no longer applies the team-defaults merge internally (avoids double-emission and confusion when both org and team layers warn).
  - Loaders return tuple[Model, tagged_raw] (RESEARCH §R4 option a) — Pydantic models do not retain tagged_raw, so the orchestrator needs both trees passed alongside.
  - merge_team_defaults_into_templates was deleted; layer 2 was extracted into _apply_team_layer_to_templates so existing Plan-02-01 unit tests can keep asserting on warning *objects* directly while merge_configs handles emission.
  - Layer-2 conflict attribution is "team defaults" even when the locking key originated from org default_fields. The merged team_model.defaults.fields reflects the org overrides for users who want to introspect (II4).
  - Importer scope: Phase 2 deliberately does NOT apply org default_fields on the import path (PATTERNS.md §11 Path B). A documentation comment in importer.py codifies the boundary; a future phase can wire merge_configs through build_row_payload if needed.
metrics:
  duration_minutes: 11
  completed: 2026-04-30
  tests_added: 25
  tests_total_after: 485
  tests_baseline_before: 460
  regressions: 0
---

# Phase 2 Plan 02: Org `default_fields` + merge_configs Orchestrator — Summary

**One-liner:** Org-level `default_fields:` block locks fields across every team's templates via the new `merge_configs(org, team, ...)` orchestrator wired into `cli.py:plan`, with two-layer conflict attribution (org → team defaults → template fields) and zero behavior change for existing org/team configs that omit the keys.

## What Shipped

A three-layer load-time merge driven by a single public orchestrator in `jiramator/config_merge.py`:

```
load_org_config(p)  ─┐
                     ├──>  merge_configs(...)  ──>  merged TeamConfig
load_team_config(p) ─┘                              (defaults.fields + every template's fields
                                                     reflect the org → team-defaults → template
                                                     earlier-wins composition)
```

`OrgConfig.default_fields: dict[str, Any] = {}` is the new top-level org-side lock surface. Loaders changed signature to `tuple[Model, tagged_raw]` so the orchestrator can resolve line numbers when emitting `ConfigConflictWarning` lines for org-vs-team conflicts. `cli.py:plan` invokes `merge_configs` between the loaders and `run_plan`. The `import` command still unpacks the new tuple but, per PATTERNS.md §11 Path B, deliberately does NOT call `merge_configs`; a documentation comment in `importer.py` codifies that boundary.

Conflict attribution is two-layer:

- **Layer 1** (org `default_fields` vs team `defaults.fields`): `earlier_layer="org config"`. Warning carries the org file/line as `earlier_*` and the team file/line as `later_*`.
- **Layer 2** (effective team-level locks vs per-template `fields:`): `earlier_layer="team defaults"`. Both files are the team file. The merged `team_model.defaults.fields` reflects org overrides, so users can grep their team config or introspect to see which keys are org-locked.

Smoke-verified end-to-end: an org with `default_fields: {priority: Medium}` plus a team config without `priority:` on a per-release ticket → merged template carries `priority: Medium`; zero warnings.

## How It Was Built (TDD)

Two tasks, each RED → GREEN:

1. **Task 1 — `OrgConfig.default_fields` + tuple-returning loaders.**
   - **RED** (`5431435`): `TestOrgDefaultFields` (O1-O6: empty default, empty dict, single key, multi-key with list shape, non-dict raises ConfigValidationError, real acme.yaml backward compat) + `TestLoaderTupleSignature` (L1, L2, L4: tuple shape, no internal team-defaults merge).
   - **GREEN** (`196f5ba`): added `default_fields: dict[str, Any] = {}` to `OrgConfig`; both loaders now return `(Model, tagged_raw)`; removed the team-defaults merge from `load_team_config`. Updated **all** callsites — `cli.py`, six test modules, and one script — to unpack the tuple. Marked Plan-02-01's `TestTeamDefaultsMergeIntegration` (I1-I6) as `@pytest.mark.skip` pending Task 2 rewire.
2. **Task 2 — `merge_configs` orchestrator + CLI wiring + I1-I6 rewire.**
   - **RED** (`8b2ba47`): `TestMergeConfigs` (MC1-MC8: no-op, propagation, layer-1 conflict, layer-2 conflict, three-layer composition, list concat across layers, no-mutation guarantee, console=None routing). New `tests/test_config_inheritance_integration.py` (II1-II6: end-to-end through public loaders, two-layer warnings, real calcs.yaml fixture, backward compat, importer scope-doc check, CLI integration via Click). `TestPlanCommandMergeWiring` (CL1-CL2: cli.py unpacks tuples and calls merge_configs).
   - **GREEN** (`8cf197c`): implemented `merge_configs` in `config_merge.py`; extracted layer 2 into `_apply_team_layer_to_templates` so existing Plan-02-01 layer-2 unit tests keep asserting on warning objects directly (the helper IS what `merge_configs` calls). Wired the orchestrator into `cli.py:plan` (module-top import). Documented the import-path Phase-2 boundary in `importer.py`. Un-skipped and rewired I1-I6 in `test_config.py` to drive the team-defaults layer through `merge_configs(stub_org, ..., team)` — same semantics, new composition point.

## Commits

| Commit    | Phase | Type | Subject                                                              |
| --------- | ----- | ---- | -------------------------------------------------------------------- |
| `5431435` | RED   | test | add failing tests for OrgConfig.default_fields + tuple loaders       |
| `196f5ba` | GREEN | feat | add OrgConfig.default_fields + tuple-returning loaders               |
| `8b2ba47` | RED   | test | add failing tests for merge_configs orchestrator + CLI wiring        |
| `8cf197c` | GREEN | feat | implement merge_configs orchestrator + CLI wiring                    |

## Verification Results

- `pytest tests/test_config_merge.py tests/test_config_inheritance_integration.py tests/test_config.py tests/test_cli.py -v` → all selected tests pass.
- `pytest -q` (full suite) → **485 passed** in ~1.2s.
- Baseline before plan: 460. New tests: 25. Regressions: **0**.
- `grep -n "default_fields" jiramator/importer.py` → 4 hits in the documentation comment (II6 verification).
- `grep -n "merge_configs" jiramator/cli.py` → import + call inside `plan` (key-link verification).
- Manual smoke: org with `default_fields: {priority: Medium}` + team without `priority:` → merged template carries `priority: Medium`, zero warnings on stderr.

## Acceptance / Done Criteria

| Criterion                                                                                                                  | Status |
| -------------------------------------------------------------------------------------------------------------------------- | ------ |
| `OrgConfig.default_fields` exists, defaults to `{}`, backward compatible with acme.yaml (DC-4)                      | ✅     |
| `merge_configs` is the single composition point; called from `cli.py:plan` between `load_*_config` and `run_plan`          | ✅     |
| Layer-1 conflicts (org vs team-defaults) emit warnings with `earlier_layer="org config"` (G-5)                             | ✅     |
| Layer-2 conflicts (effective locks vs per-template) emit warnings with `earlier_layer="team defaults"`                     | ✅     |
| Loaders return `tuple[Model, tagged_raw]`; all callsites updated                                                           | ✅     |
| Importer is explicitly out of Phase 2 scope, documented in-source                                                          | ✅     |
| TMPL-01 fully covered (org + team inheritance both directions)                                                             | ✅     |
| TMPL-02 covered (per-template `fields:` fills gaps; conflicts warned; user gets transparency via stderr)                   | ✅     |
| 460 existing tests pass without regression; 25 new tests added                                                             | ✅     |

## Deviations from Plan

### Rule 3 — auto-fixed blocking issue (test framework)

**1. [Rule 3 — Test isolation] CL2 monkeypatch wrong target.**
- **Found during:** Task 2 GREEN — initial test run.
- **Issue:** The CL2 test patched `config_merge.merge_configs`, but `cli.py` does `from jiramator.config_merge import merge_configs` at module top, binding the function to `cli.merge_configs`. Patching the source module had no effect.
- **Fix:** Patched `cli_mod.merge_configs` instead (correct binding target). Comment added explaining the binding semantics.
- **Files modified:** `tests/test_cli.py`
- **Commit:** `8cf197c` (rolled into GREEN since the test was the new test being made green).

### Plan-checker note II4 resolved

The plan flagged a possible warning-attribution mismatch in MC4 ("conflict skipping team defaults"). At execute time, the actual implementation labels layer-2 conflicts as `"team defaults"` regardless of which layer originally locked the key — matching the simplification documented in the plan's "Step 1 — Implement merge_configs" comment. Tests assert on this contract; the merged `team_model.defaults.fields` is the introspection surface for users wanting to see which keys are org-locked.

### Scope adherence

- Importer integration deferred (PATTERNS.md §11 Path B): documented in `importer.py` only.
- `merge_team_defaults_into_templates` deleted (per the plan's option (a)); `_apply_team_layer_to_templates` replaces it as the layer-2 helper. Plan-02-01 tests aliased the import — no behavior or assertion changes.

## Out-of-Scope Items (Logged for Future Phases)

- Sprint-mode resolution (`sprints_exist` + `--sprints-exist/--no-sprints-exist`). (Plan 02-03.)
- Importer-side application of org `default_fields` for `bulk_create` rows. (Future phase per PATTERNS.md §11 Path B.)
- Per-key lock provenance in layer-2 warnings (currently labeled "team defaults" uniformly; users introspect `team.defaults.fields` to see org overrides). (Optional future polish; not on the plan's must-have list.)

## Threat Surface Status

All `mitigate` items in the plan's `<threat_model>` are covered:

| ID      | Disposition | Status                                                                                                                                  |
| ------- | ----------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| T-02-07 | mitigate    | ✅ `deep_merge_dicts` skips `LINE_KEY` on both sides; layer-1 and layer-2 both run through it; verified by Plan-02-01 D7 + new tests.    |
| T-02-08 | accept      | ✅ Documented; CLI is single-user.                                                                                                       |
| T-02-09 | mitigate    | ✅ MC7 asserts `org.default_fields` snapshot equals post-merge state; `deep_merge_dicts` builds fresh dicts; only template fields and `team.defaults.fields` are reassigned (intended). |
| T-02-10 | accept      | ✅ Layer-1 warnings cite "org config"; layer-2 cite "team defaults"; introspection surface is `team_model.defaults.fields`.              |
| T-02-11 | accept      | ✅ Real configs are bounded; no adversarial input.                                                                                       |

No new threat surface introduced beyond the register.

## Self-Check: PASSED

**Files claimed → verified on disk:**

- `jiramator/config.py` — FOUND (`OrgConfig.default_fields` added; loaders return tuples).
- `jiramator/config_merge.py` — FOUND (`merge_configs` + `_apply_team_layer_to_templates`; old `merge_team_defaults_into_templates` removed).
- `jiramator/cli.py` — FOUND (imports + calls `merge_configs` in `plan`).
- `jiramator/importer.py` — FOUND (Phase-2 scope-doc comment present).
- `tests/test_config_inheritance_integration.py` — FOUND (new, 5 tests + 1 CLI integration).
- `tests/test_config.py` — FOUND (extended; I1-I6 rewired).
- `tests/test_config_merge.py` — FOUND (extended with `TestMergeConfigs`; layer-2 helper aliased).
- `tests/test_cli.py` — FOUND (CL1-CL2 added; loader callsites unpacked).

**Commits claimed → verified in git log:**

- `5431435` — FOUND (`test(02-02): add failing tests for OrgConfig.default_fields + tuple loaders`).
- `196f5ba` — FOUND (`feat(02-02): add OrgConfig.default_fields + tuple-returning loaders`).
- `8b2ba47` — FOUND (`test(02-02): add failing tests for merge_configs orchestrator + CLI wiring`).
- `8cf197c` — FOUND (`feat(02-02): implement merge_configs orchestrator + CLI wiring`).
