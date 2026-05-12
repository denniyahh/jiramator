# Jiramator Planning and Spec Index

This directory is the canonical home for project planning/specification artifacts.

Status taxonomy:
- active: current design or planning document that still informs implementation
- completed: implementation plan whose work has substantially landed; keep for historical traceability
- superseded: historical document retained for context, but no longer authoritative
- template: design-only artifact that is not currently wired to shipped runtime behavior

## Active
- `2026-04-22-bulk-create-unified-architecture.md`
  - Status: active
  - Canonical architecture/design document for the broader bulk-create direction
  - Important caveat: parts of it are intentionally aspirational because the YAML `create-issues` path has not shipped yet

## Completed
- `completed/2026-04-22-spreadsheet-import.md`
  - Status: completed
  - Historical implementation plan for spreadsheet import
  - The shipped `import` command materially landed; use README for current operator docs

## Superseded / Archive
- `archive/2026-04-20-create-issues-spec-legacy.md`
  - Status: superseded
  - Legacy standalone `create-issues` design from before the unified architecture direction
- `archive/2026-04-22-bulk-create-workstreams.md`
  - Status: archived historical execution plan
  - Useful for understanding sequencing decisions made at the time, but not current execution guidance

## Templates
- `templates/issue-spec.template.yaml`
  - Status: template / not wired to shipped CLI behavior
  - Design artifact for a future YAML-based ad-hoc bulk-create path

## Non-planning docs that intentionally stay outside this directory
- `README.md` — user/operator documentation for shipped behavior
- `.planning/codebase/*` — codebase analysis/reference notes, not feature specs
- `configs/*.yaml` — runtime configuration, not planning artifacts
