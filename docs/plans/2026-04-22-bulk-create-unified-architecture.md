# Unified Bulk Issue Creation Architecture Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: Replace the current divergent ad hoc issue-creation ideas with one shared bulk-issue creation engine that supports multiple input adapters: YAML issue specs and spreadsheet imports.

Architecture: Keep `plan` as a separate workflow because it is a template-driven PI planner with runtime prompts and sprint/version orchestration. Build a new bulk-create subsystem for row/item-oriented issue creation. The subsystem will parse source inputs into a normalized intermediate model, resolve fields using org config plus Jira metadata, coerce values into Jira API payloads, and execute dry-run or live creation consistently regardless of source format.

Tech Stack: Python 3.11+, Click, Pydantic, requests, Rich, csv stdlib, openpyxl (new dependency), pytest.

---

## Executive summary

You were right to question whether YAML alone is sufficient for risk Jiras. But the deeper design issue is this: `create-issues` and spreadsheet import are not two unrelated features. They are two front doors into the same problem:

- ingest structured issue definitions
- map user-facing fields to Jira fields
- coerce values into Jira REST payload shape
- preview results safely
- create issues with reporting

If we implement them as separate stacks, we will duplicate:
- mapping logic
- payload coercion logic
- preview rendering
- execution/reporting logic
- tests for edge cases

That would be a bad architecture decision.

So the correct design is:
- keep `plan` separate
- build one `bulk-create` engine
- add source adapters:
  - YAML issue-spec adapter
  - CSV/XLSX spreadsheet adapter

---

## What exists today

Implemented:
- `plan` command
- org/team config loading
- planner orchestration (`planner.py`)
- Jira client for create issue, bulk create, fix versions, sprint lookup
- template-based payload builder (`ticket_builder.py`)

Not implemented despite docs/specs:
- `create-issues` CLI command
- issue-spec parsing/building modules
- spreadsheet import command

Problematic drift:
- README documents `create-issues` as if shipped
- `configs/teams/issue-spec.template.yaml` exists, but no CLI supports it
- `docs/create-issues-spec.md` is partly outdated and should not be treated as current truth

---

## Architecture decision

### Keep `plan` separate

Do not try to force `plan` into the new bulk-create engine.

Why:
- `plan` is template expansion + runtime prompting + fix version management + sprint assignment
- it has a two-phase epic-first build flow
- it is driven by org/team template configs, not an issue list input file

That workflow is fundamentally different enough to keep separate.

### Unify ad hoc issue creation

Unify these under one subsystem:
- YAML issue-spec creation
- spreadsheet import creation

Shared concerns:
- field mapping
- field type coercion
- preview tables
- dry-run/live execution
- success/failure reporting
- optional Jira field metadata lookup

---

## Proposed subsystem design

### New command surface

Recommended CLI shape:

```bash
jiramator bulk-create --from yaml --file configs/teams/pi28-issues.yaml --org-config configs/org/marketaxess.yaml --dry-run
jiramator bulk-create --from xlsx --file ~/Jira.xlsx --team-config configs/teams/calcs.yaml --sheet Risks --dry-run
jiramator bulk-create --from csv  --file ~/Jira.csv  --team-config configs/teams/calcs.yaml
```

Alternative UX if you care about friendliness over purity:
- `jiramator create-issues ...` as an alias for YAML adapter
- `jiramator import ...` as an alias for spreadsheet adapter
- both delegate internally to the same engine

My recommendation:
Ship the user-friendly commands, but make them thin wrappers around one engine.

Why:
- users think in verbs, not adapter abstractions
- CLI discoverability stays high
- internals remain clean

So externally:
- `jiramator create-issues ...`
- `jiramator import ...`

Internally:
- both call bulk-create engine

---

## Core abstraction boundary

### Normalized issue model

Both adapters should emit the same normalized intermediate representation.

Example:

```python
@dataclass
class NormalizedIssueInput:
    source_row_number: int | None
    source_group: str | None           # e.g. epic label or sheet name
    source_identifier: str | None      # e.g. epic key, row id
    fields: dict[str, Any]             # user-facing logical fields before Jira coercion
```

This model is intentionally pre-Jira. It should not contain wrapped payloads yet.

YAML adapter output example:
- fields: `{"summary": "Implement thing", "type": "Story", "story_points": 3, ...}`

Spreadsheet adapter output example:
- fields: `{"summary": "Counterparty risk ...", "priority": "High", "api_impact": "No", ...}`

The engine then handles normalization to Jira API payloads.

---

## Proposed modules

### New files

- `jiramator/bulk_create.py`
  - shared orchestration for ad hoc issue creation
  - dry-run/live execution
  - success/failure reporting

- `jiramator/field_resolver.py`
  - resolve logical names / spreadsheet headers / Jira field names to Jira field IDs or standard field names
  - conservative auto-lookup support

- `jiramator/value_coercion.py`
  - convert normalized user values into Jira REST shapes
  - e.g. `High` -> `{"name": "High"}`
  - e.g. `US High Grade,Data` -> `[{"value": "US High Grade"}, {"value": "Data"}]`

- `jiramator/input_adapters/yaml_issue_spec.py`
  - parse issue-spec YAML
  - merge defaults and epic group context into `NormalizedIssueInput`

- `jiramator/input_adapters/spreadsheet.py`
  - read `.csv` / `.xlsx`
  - map rows to `NormalizedIssueInput`

- `jiramator/preview.py`
  - render preview/report tables for bulk-create workflows

### Existing files to modify

- `jiramator/cli.py`
  - add `create-issues` and `import` thin wrapper commands

- `jiramator/config.py`
  - add importer/bulk-create config sections to `OrgConfig`

- `jiramator/jira_client.py`
  - add `get_fields()`
  - possibly add `get_issue()` helper for epic validation if desired

- `README.md`
  - stop claiming unimplemented behavior
  - document the unified architecture once implemented

---

## Config model design

### Org config additions

The org config should be the home for organization-specific Jira knowledge, not the team config.

Add:

```yaml
custom_fields:
  story_points: customfield_10026
  epic_link: customfield_10014
  api_impact: customfield_10273
  product_horizontals: customfield_12747
  product_verticals: customfield_12749
  platform: customfield_14823

bulk_create:
  field_aliases:
    type: issuetype
    fix_version: fixVersions
    Summary: summary
    Description: description
    Issue Type: issuetype
    Priority: priority
    Labels: labels
    Fix Versions: fixVersions
    API Impact: api_impact
    Product Horizontals: product_horizontals
    Product Verticals: product_verticals
    Platform: platform
  field_types:
    issuetype: name_object
    priority: name_object
    fixVersions: name_object_array
    components: name_object_array
    labels: labels
    api_impact: multi_select
    product_horizontals: single_select
    product_verticals: multi_select
    platform: multi_select
  defaults: {}
  auto_lookup_unknown_fields: true
  multi_value_delimiter: ","
```

Important design decision:
`field_aliases` should resolve source-facing names to logical names first, not directly to `customfield_*` whenever possible.

Why this is better:
- YAML adapter and spreadsheet adapter can share the same logical vocabulary
- org config remains the single translation layer from logical name -> Jira field id
- if Jira field IDs change, the logical alias layer stays stable

Resolution pipeline should therefore be:
1. source field/header -> logical alias (`type` -> `issuetype`, `API Impact` -> `api_impact`)
2. logical name -> Jira field id if in `custom_fields`
3. otherwise treat as standard Jira field name
4. if still unresolved and auto-lookup enabled, consult Jira metadata

This is cleaner than mapping every source label straight to `customfield_...`.

---

## Shared engine responsibilities

The new bulk-create engine should do exactly this:

1. accept normalized issue inputs from an adapter
2. resolve each field to final Jira field name/id
3. coerce values into Jira API shape
4. inject required project field
5. optionally inject epic link or defaults already supplied by adapter
6. validate required fields (e.g. summary)
7. build previewable payload list
8. dry-run: render preview + warnings
9. live mode: create issues, continue or bulk depending on workflow mode
10. return/report results

Note: YAML adapter and spreadsheet adapter may choose different execution strategies:
- spreadsheet import should create row-by-row with continue-on-error
- YAML issue-spec could use bulk create safely if desired

But I recommend the engine support both modes explicitly:

```python
execution_mode = "bulk" | "continue_on_error"
```

Do not bury this in adapter-specific hacks.

---

## YAML adapter design

### Scope

Use for structured ad hoc creation where the user is comfortable editing YAML.

The existing issue-spec template remains useful, but it should flow through the shared engine.

Adapter responsibilities:
- parse `meta`, `defaults`, `epics`
- validate required issue fields
- merge defaults with per-issue overrides
- if epic key present, add logical `epic_link` field to each issue
- emit `NormalizedIssueInput` list

Open questions from old spec that should now be decided:

1. Sub-task support
- defer for v1
- reject `type: Sub-task` with a clear error

2. Multi-select field format
- resolved via org config `field_types`
- no longer an open question

3. Epic validation
- yes, validate upfront in YAML adapter live mode
- because epic keys are explicit and low-volume

---

## Spreadsheet adapter design

### Scope

Use for business-owned, row-based imports such as risk Jiras.

Adapter responsibilities:
- read `.csv` / `.xlsx`
- produce one `NormalizedIssueInput` per row
- preserve row number for reporting
- use header aliases from org config first
- use conservative Jira metadata auto-lookup second
- skip unknown columns with warnings

Important constraint:
Do not try to infer too much. No fuzzy matching in v1.

Recommended resolution order for unknown spreadsheet headers:
1. `bulk_create.field_aliases` exact match
2. normalized alias match
3. exact Jira field name match
4. normalized Jira field name match
5. exact Jira field ID match
6. skip with warning

---

## Preview/reporting design

Both adapters should share preview/reporting code.

Common preview columns:
- # / row number
- summary
- issue type
- priority
- project
- epic (if applicable)
- fix versions
- source info (row number or epic label)

Common reporting sections:
- resolved aliases
- auto-mapped fields
- skipped fields
- total issues prepared
- created count
- failed count
- per-item errors

This is a good example of code that should absolutely be shared.

---

## Execution strategy

### Live execution modes

The engine should support two modes:

1. `bulk`
- use Jira bulk API in batches of 50
- fail batch on error
- good for YAML issue-spec after strong validation

2. `continue_on_error`
- create one issue at a time
- capture errors per item
- continue processing
- required for spreadsheet import

This gives you one engine and explicit behavior rather than separate orchestration stacks.

---

## Revised backlog and priority

### Priority 0: repo honesty

1. Fix README so it does not claim `create-issues` is already shipped.
2. Update `docs/create-issues-spec.md` header/status to make clear it is superseded by unified architecture.

This is not glamorous, but it matters. Right now docs are misleading.

### Priority 1: shared foundation

3. Add `bulk_create` config schema to `OrgConfig`
4. Add Jira field metadata fetch to `JiraClient`
5. Build shared field resolver
6. Build shared value coercion layer
7. Build shared preview/reporting helpers

### Priority 2: first adapter

8. Implement YAML issue-spec adapter and `create-issues` command using the shared engine

Why YAML first?
- fewer parsing edge cases than spreadsheets
- cleaner place to prove the engine
- already partially specced
- lower risk than openpyxl + header resolution + row continuation all at once

### Priority 3: second adapter

9. Implement spreadsheet adapter and `import` command using the shared engine

### Priority 4: operational polish

10. Add `--yes`
11. Add duplicate detection if still wanted

### Deferred

12. setup wizard
13. sub-task support

---

## Why YAML-first is the right order

I want to be explicit here, because it’s easy to chase the immediate pain point and skip architecture validation.

You might be tempted to build spreadsheet import first because that’s the thing you just needed. I think that would be the wrong engineering order.

Why YAML-first is better:
- simpler parser
- deterministic structure
- easier to test the normalized engine
- already has a template/spec in repo
- lets us validate aliasing/coercion without spreadsheet file-format noise

Then spreadsheet import becomes “just another adapter,” which is exactly what we want.

If you build spreadsheet import first, there’s a real risk the engine becomes row/header-centric in a way that makes YAML fit awkwardly later.

---

## Recommended file layout

```text
jiramator/
  cli.py
  config.py
  jira_client.py
  planner.py
  ticket_builder.py
  bulk_create.py
  field_resolver.py
  value_coercion.py
  preview.py
  input_adapters/
    __init__.py
    yaml_issue_spec.py
    spreadsheet.py
tests/
  test_bulk_create.py
  test_field_resolver.py
  test_value_coercion.py
  test_preview.py
  test_yaml_issue_spec_adapter.py
  test_spreadsheet_adapter.py
  test_jira_client.py
  test_cli_bulk_create.py
```

Avoid dumping everything into one god-module like `create_issues.py`. That would be the path of least resistance and the wrong long-term choice.

---

## Acceptance criteria

This architecture work is complete when:
- repo docs no longer claim unimplemented commands are shipped
- shared bulk-create engine exists
- field resolution and value coercion are centralized
- YAML issue-spec uses the shared engine
- spreadsheet import uses the shared engine
- both commands have dry-run support
- YAML path supports safe bulk creation
- spreadsheet path supports continue-on-error creation
- tests cover shared engine + both adapters

---

## First implementation slice

The best first slice is:
1. docs honesty cleanup
2. config schema for `bulk_create`
3. shared field resolver
4. shared coercion layer
5. YAML adapter
6. `create-issues` command

Only after that:
7. spreadsheet adapter
8. `import` command

That is the correct sequence if you care about code quality over just getting the next demo working.

---

## Immediate recommendation

Before implementation, make one product decision explicit:

Do you want the public CLI to expose:
A. `bulk-create --from ...`
or
B. separate user-facing commands (`create-issues`, `import`) that share the same internal engine?

My recommendation is B.

It gives users obvious verbs while keeping the internal architecture clean.

---

Plan complete and saved. Ready to execute using subagent-driven-development — I'll dispatch a fresh subagent per task with two-stage review if you want. Shall I proceed?
