---
status: complete
phase: 02-template-inheritance-sprint-assignment
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md]
started: 2026-05-12T18:55:02Z
updated: 2026-05-12T18:55:02Z
---

## Current Test

(complete — all 7 verified 2026-09-29 by automated offline dry-run; see results)

<!-- previous: -->

number: 1
name: Team Defaults Merge Into Templates
expected: |
  Add a `defaults:` block with `fields: {priority: Medium}` to a team config YAML (e.g., `configs/teams/calcs.yaml`). Remove `priority` from one template's `fields:`. Run `jiramator plan` (dry-run). The template missing `priority` should now carry `priority: Medium` from defaults. Other templates that still declare `priority` should emit a conflict warning on stderr in the format: `<file>:<line>: <field> — locked by team defaults (<file>:<line>); later value ignored.`
awaiting: user response

## Tests

### 1. Team Defaults Merge Into Templates
expected: Add a `defaults:` block with `fields: {priority: Medium}` to a team config YAML. Remove `priority` from one template's `fields:`. Run `jiramator plan` (dry-run). The template missing `priority` inherits `priority: Medium` from defaults. Templates that still declare `priority` emit a conflict warning on stderr.
result: pass — 2026-09-29 automated dry-run (offline). Template missing `priority` inherited `Medium`; 6 conflict warnings emitted citing team defaults.

### 2. Org Default Fields Lock Into Team Templates
expected: Add `default_fields: {priority: Medium}` to an org config YAML. Run `jiramator plan` with a team config that has no `priority` on a template. The merged template carries `priority: Medium`. If the team config also declares `priority` in `defaults.fields`, a layer-1 conflict warning appears citing "org config" as the earlier source.
result: pass — 2026-09-29 automated dry-run. Org `default_fields.priority` locked into templates; layer-1 warning cites "org config".

### 3. Conflict Warning Format
expected: When both org and team define the same field, stderr warnings follow the canonical format: `<file>:<line>: <field> — locked by <layer> (<file>:<line>); later value ignored.` Layer attribution distinguishes "org config" (layer 1) from "team defaults" (layer 2).
result: pass — 2026-09-29. All 13 warnings match `<file>:<line>: <field> — locked by <layer> (<file>:<line>); later value ignored.`; both layers attributed.

### 4. Backward Compatibility — No Defaults Block
expected: Existing team configs without a `defaults:` block (e.g., the real `calcs.yaml`) load and plan identically to before. No warnings, no errors, no behavior change.
result: pass — 2026-09-29. Unmodified calcs fixture: exit 0, no warnings, no traceback.

### 5. Sprint Mode via Config Field
expected: Set `sprints_exist: false` in a team config YAML. Run `jiramator plan` without any sprint flag. The plan runs without prompting for sprint mode and skips sprint assignment. Console shows "Sprint assignment: skipped (not yet created)" or similar.
result: pass — 2026-09-29. `sprints_exist: false`, no flag, stdin not a TTY: no prompt, "Sprint assignment: skipped (not yet created)".

### 6. Sprint Mode via CLI Flag
expected: Run `jiramator plan --sprints-exist` or `jiramator plan --no-sprints-exist`. The CLI flag overrides whatever is in the team config. `--no-sprints-exist` skips sprint resolution; `--sprints-exist` enables it.
result: pass — 2026-09-29. `--no-sprints-exist` overrides `sprints_exist: true` (skipped); `--sprints-exist` overrides `false` ("will be attempted after ticket creation").

### 7. Non-Interactive Sprint Error
expected: Remove `sprints_exist` from team config (or set to `null`). Run `jiramator plan` in a non-TTY context (e.g., piped input). Instead of hanging on a prompt, a `ConfigValidationError` is raised with a clear message about needing `sprints_exist` in config or `--sprints-exist` flag.
result: pass — 2026-09-29. No `sprints_exist`, no flag, non-TTY: exit 1 with a clean `sprints_exist` error, no hang, no traceback.

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

None in Phase 2 scope. Incidental finding during setup: a builder `ValueError` (e.g. missing
`release_sprint_schedule` entry for the given release count) escapes `plan` as a raw traceback
instead of a clean CLI error — tracked as v1.2.9 HYG-04.
