# `create-issues` CLI Command — Legacy Design Spec

**Status**: Superseded by the unified bulk-create architecture plan
**Created**: 2026-04-20
**Superseded by**:
- `docs/plans/2026-04-22-bulk-create-unified-architecture.md`
- `docs/plans/2026-04-22-bulk-create-workstreams.md`

## Important note

This document reflects the earlier idea of implementing `create-issues` as a
standalone feature. That is no longer the recommended architecture.

Current direction:
- keep `plan` separate
- implement one shared bulk-create engine
- expose `create-issues` (YAML) and `import` (CSV/XLSX) as thin adapters over that engine

Use this file as historical context only. Where it conflicts with the unified
architecture plan, the newer plan wins.

---

## Legacy overview

A new `jiramator create-issues` subcommand that reads an explicit issue-spec YAML file and creates Jira issues via the REST API. Unlike the existing `plan` command (which generates recurring boilerplate tickets from templates × versions/sprints), this command creates individually-specified issues grouped under existing epics.

## Data Flow

```
issue-spec.yaml → IssueSpec model (Pydantic-validated)
                → spec_builder (resolves field names, merges defaults, wraps fields)
                → list of Jira API payloads
                → JiraClient.create_issue / create_issues_bulk
```

## New Files

| File | Purpose |
|---|---|
| `jiramator/issue_spec.py` | Pydantic models + YAML loader for issue-spec format |
| `jiramator/spec_builder.py` | Transforms validated IssueSpec → Jira API payloads |
| `tests/test_issue_spec.py` | Model validation tests |
| `tests/test_spec_builder.py` | Payload building tests |

## Modified Files

| File | Change |
|---|---|
| `jiramator/cli.py` | Add `create-issues` subcommand to Click group |

## Issue-Spec YAML Format

Reference: `configs/teams/issue-spec.template.yaml`

```yaml
meta:
  pi: PI28
  project: CA

defaults:
  labels: [PI28]
  api_impact: "No"
  product_horizontals: "Calcs"
  product_verticals: [AxessIQ, Data, ...]
  platform: [Calcs]

epics:
  - key: CA-1234          # existing Jira epic key
    label: "My Feature"   # human-readable, not sent to Jira
    issues:
      - summary: "Implement the thing"
        type: Story
        story_points: 3
        fix_version: "26.3.0"
      - summary: "Validate the thing"
        type: Task
        story_points: 2
        fix_version: "26.3.0"
        priority: High
```

## Key Design Decisions

### 1. Logical Field Name Resolution

The spec uses friendly names that resolve to Jira field IDs at build time via the org config's `custom_fields` mapping. This keeps the YAML portable across teams.

**Spec-friendly name → Jira API field:**

| Spec Name | Jira Field | Resolution |
|---|---|---|
| `summary` | `summary` | Direct (standard field) |
| `type` | `issuetype` | Renamed + wrapped as `{"name": "Task"}` |
| `priority` | `priority` | Wrapped as `{"name": "High"}` |
| `fix_version` | `fixVersions` | Renamed + wrapped as `[{"name": "26.3.0"}]` |
| `labels` | `labels` | Direct (already string array) |
| `assignee` | `assignee` | Wrapped as `{"id": "..."}` (needs account ID lookup) |
| `description` | `description` | Converted to ADF (Atlassian Document Format) |
| `story_points` | `customfield_10026` | Via org config `custom_fields` |
| `api_impact` | `customfield_10273` | Via org config; value wrapped as `[{"value": "No"}]` |
| `product_horizontals` | `customfield_12747` | Via org config |
| `product_verticals` | `customfield_12749` | Via org config |
| `platform` | `customfield_14823` | Via org config |

### 2. Defaults Merging

`spec.defaults` apply to every issue. Per-issue fields override defaults. Scalars and lists replace entirely (no deep merge of lists).

### 3. Field Wrapping

Reuses `_wrap_field()` from `ticket_builder.py` for Jira API formatting. May need to extend `WRAPPED_FIELDS` dict for additional field types.

### 4. Epic Linking

Each issue group has a `key` (existing Jira epic key). The builder injects `customfield_10014` (epic_link, resolved from org config) into every issue payload.

### 5. Dry-Run

Same pattern as `plan` command: `--dry-run` renders a Rich Table preview of all issues without creating anything. No credential resolution needed in dry-run mode.

## CLI Interface

```
jiramator create-issues \
  --spec configs/teams/pi28-issues.yaml \
  --org-config configs/org/marketaxess.yaml \
  [--dry-run]
```

- `--spec` (required): Path to the issue-spec YAML file.
- `--org-config` (required): Path to the org config (for field ID resolution and Jira credentials).
- `--dry-run` (optional): Preview only, no Jira API calls.

## Execution Steps

1. Load and validate org config
2. Load and validate issue-spec YAML → `IssueSpec` model
3. Build Jira API payloads (resolve field names, merge defaults, wrap fields)
4. Display Rich Table preview (issue count, summaries, types, epics, fix versions)
5. If `--dry-run`: exit
6. Resolve Jira credentials, build `JiraClient`
7. Warn about duplicates, prompt for confirmation
8. Create issues (bulk API, batched by 50)
9. Display results summary

## Open Questions

### Q1: Sub-task support?

The template shows `type: Story` and `type: Task`. Should we also support `Sub-task` (which requires a `parent` field linking to a parent issue, not just an epic link)?

### Q2: Multi-select custom field format

For `product_verticals` and `platform` — these are multi-select fields in Jira. The spec template shows them as plain lists of strings. What Jira API format do they need?

Options:
- `[{"value": "US High Grade"}, ...]` (like `api_impact`)
- `[{"name": "US High Grade"}, ...]`
- `[{"id": "12345"}, ...]` (option IDs)

Need to check the actual Jira field configuration to determine the correct format.

### Q3: Epic key validation

Should the command validate that epic keys (e.g. `CA-1234`) actually exist in Jira before creating issues? Or trust the spec and let Jira error if the epic key is wrong?

**Recommendation**: Validate upfront — a single GET per epic is cheap and gives a better error message than a cryptic Jira 400 buried in a bulk create response.
