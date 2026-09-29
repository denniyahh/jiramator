---
status: testing
phase: 02-template-inheritance-sprint-assignment
source: [02-01-SUMMARY.md, 02-02-SUMMARY.md, 02-03-SUMMARY.md]
started: 2026-05-12T18:55:02Z
updated: 2026-05-12T18:55:02Z
---

## Current Test

number: 1
name: Team Defaults Merge Into Templates
expected: |
  Add a `defaults:` block with `fields: {priority: Medium}` to a team config YAML (e.g., `configs/teams/calcs.yaml`). Remove `priority` from one template's `fields:`. Run `jiramator plan` (dry-run). The template missing `priority` should now carry `priority: Medium` from defaults. Other templates that still declare `priority` should emit a conflict warning on stderr in the format: `<file>:<line>: <field> — locked by team defaults (<file>:<line>); later value ignored.`
awaiting: user response

## Tests

### 1. Team Defaults Merge Into Templates
expected: Add a `defaults:` block with `fields: {priority: Medium}` to a team config YAML. Remove `priority` from one template's `fields:`. Run `jiramator plan` (dry-run). The template missing `priority` inherits `priority: Medium` from defaults. Templates that still declare `priority` emit a conflict warning on stderr.
result: [pending]

### 2. Org Default Fields Lock Into Team Templates
expected: Add `default_fields: {priority: Medium}` to an org config YAML. Run `jiramator plan` with a team config that has no `priority` on a template. The merged template carries `priority: Medium`. If the team config also declares `priority` in `defaults.fields`, a layer-1 conflict warning appears citing "org config" as the earlier source.
result: [pending]

### 3. Conflict Warning Format
expected: When both org and team define the same field, stderr warnings follow the canonical format: `<file>:<line>: <field> — locked by <layer> (<file>:<line>); later value ignored.` Layer attribution distinguishes "org config" (layer 1) from "team defaults" (layer 2).
result: [pending]

### 4. Backward Compatibility — No Defaults Block
expected: Existing team configs without a `defaults:` block (e.g., the real `calcs.yaml`) load and plan identically to before. No warnings, no errors, no behavior change.
result: [pending]

### 5. Sprint Mode via Config Field
expected: Set `sprints_exist: false` in a team config YAML. Run `jiramator plan` without any sprint flag. The plan runs without prompting for sprint mode and skips sprint assignment. Console shows "Sprint assignment: skipped (not yet created)" or similar.
result: [pending]

### 6. Sprint Mode via CLI Flag
expected: Run `jiramator plan --sprints-exist` or `jiramator plan --no-sprints-exist`. The CLI flag overrides whatever is in the team config. `--no-sprints-exist` skips sprint resolution; `--sprints-exist` enables it.
result: [pending]

### 7. Non-Interactive Sprint Error
expected: Remove `sprints_exist` from team config (or set to `null`). Run `jiramator plan` in a non-TTY context (e.g., piped input). Instead of hanging on a prompt, a `ConfigValidationError` is raised with a clear message about needing `sprints_exist` in config or `--sprints-exist` flag.
result: [pending]

## Summary

total: 7
passed: 0
issues: 0
pending: 7
skipped: 0
blocked: 0

## Gaps

[none yet]
