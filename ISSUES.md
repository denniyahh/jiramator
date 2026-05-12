# Open Issues

## #1 — EpicTemplate missing fields dict — Jira 400 on epic creation

**Status**: Resolved
**Type**: Bug
**Created**: 2026-04-16
**Resolved**: 2026-04-16

### Problem

`EpicTemplate` dataclass only has `key` and `summary` fields. `build_epics()` produces payloads with just project/summary/issuetype, but our Jira project requires 5 custom fields on Epics, causing a 400 error from the bulk create API.

### Required custom fields (from PI26 epics)

| Field ID | Name | BAU Value | Misc Value |
|---|---|---|---|
| `customfield_11623` | Requesting Customer | `{"value":["Internal Initiative"]}` | `{"value":["Internal Initiative"]}` |
| `customfield_10214` | Tech/Business Feature | `{"value":"Business Feature"}` | `{"value":"Technical Feature"}` |
| `customfield_11560` | T-Shirt Size | `{"value":"M"}` | `{"value":"M"}` |
| `customfield_10237` | Business Priority | `{"value":"High"}` | `{"value":"Low"}` |
| `customfield_13209` | Motivation | `{"value":"Firm Strategic"}` | `{"value":"Revenue"}` |

### Root cause

`EpicTemplate` in `config.py` only has `key` and `summary` — no `fields` dict. `TicketTemplate` already supports fields, but epics do not.

### Fix (3 parts)

1. **Add `fields` dict to `EpicTemplate`** — match `TicketTemplate` pattern
2. **Update `build_epics()` in `ticket_builder.py`** — resolve and include those fields in the payload
3. **Update YAML configs** — add per-epic required field values (values differ per epic, not team-level defaults)

### Notes

- Field values differ per epic (BAU vs Misc have different Business Priority, Tech/Business Feature, Motivation)
- API format uses `{"value": "..."}` for select fields — these are now passed through as raw dicts via epic `fields`
- `customfield_11623` (Requesting Customer) uses array value format: `{"value":["Internal Initiative"]}`

### Resolution

Implemented the fix in `jiramator/config.py`, `jiramator/ticket_builder.py`, and `configs/teams/calcs.yaml`.

- `EpicTemplate` now supports a `fields` dict, matching `TicketTemplate`
- `build_epics()` now builds epic payloads from template fields, resolves template vars, and still forces `issuetype=Epic`
- Calcs BAU and Misc epics now include the required custom fields for Jira epic creation
- Added regression coverage for model validation, builder output, and real-config integration

### Verification

- Targeted regression suite passed during development
- Full test suite now passes: `206 passed`

---

## #2 — Support pre-existing epics to skip auto-creation

**Status**: Resolved
**Type**: Enhancement
**Created**: 2026-04-20
**Resolved**: 2026-04-20

### Problem

`recurring_epics` always generates new epics via the Jira bulk create API. For teams that reuse the same epics across PIs (or create them manually), there was no way to reference pre-existing epic keys without creating new ones.

### Fix

Added `existing_epics: dict[str, str]` to `TeamConfig` — a mapping of ref_key to Jira issue key (e.g. `{bau: CA-1234, misc: CA-5678}`).

**Changes (4 files):**

1. **config.py** — Added `existing_epics` field with default `{}`. Updated `get_epic_keys()` to return keys from both sources. Added cross-validation: same key in both `recurring_epics` and `existing_epics` raises `ValidationError`. Updated `validate_epic_refs` model validator to accept refs from either source.

2. **planner.py** — `_create_epics()` is now skipped when `recurring_epics` is empty. `existing_epics` from config are seeded into `epic_keys` dict before creation, and newly created keys are merged on top.

3. **calcs.yaml** — Moved BAU/misc from `recurring_epics` to `existing_epics` with placeholder keys (`CA-XXXXX`).

4. **Tests** — Added `TestExistingEpics` class (4 tests) for config validation. Updated integration tests to reflect 0 epic payloads. All 207 tests passing.

### Design decisions

- `existing_epics` and `recurring_epics` are mixable (different keys), but overlap is rejected
- `$epic:ref` resolution works identically — ticket templates don't care whether the epic was created or pre-existing
- Placeholder keys (`CA-XXXXX`) in calcs.yaml must be replaced with real Jira keys before running

---

## Improvement Plan (from 2026-04-23 codebase review)

### Triage of identified issues

The following items were surfaced in a full codebase review. Each was verified against the source code. Items that don't warrant action are listed with rationale at the bottom.

---

### #3 — Reporter lookup bypasses field resolution in import

**Status**: Resolved
**Type**: Bug
**Severity**: Low (only triggers when spreadsheet header ≠ literal `"Reporter"`)
**File**: `jiramator/importer.py:260`
**Resolved**: 2026-04-23

#### Problem

During live import, the reporter value is retrieved by hardcoded key:

```python
reporter_value = source_row.get("Reporter")
```

This bypasses the entire field resolution system. If the spreadsheet header is `"reporter"` (lowercase), or a custom alias like `"Report Author"` mapped to `reporter` via `bulk_create.field_aliases`, the lookup silently fails and the created issue gets no reporter.

The field resolution system *does* correctly identify reporter columns — the `_DEFERRED_FIELDS` set on line 51 prevents reporter from being emitted in the payload during build, and the README documents this split as intentional. But the live-mode lookup on line 260 doesn't use the resolution results to find which source column actually mapped to reporter.

#### Fix

After `build_preview_report` runs, scan `resolved_columns` across row results to find which source header resolved to `reporter`. Use that header to look up the value in the source row, instead of hardcoding `"Reporter"`.

#### Scope

- `jiramator/importer.py` — ~10 lines changed
- `tests/test_importer.py` — add test for lowercase/aliased reporter header

---

### #4 — Hardcoded sprint custom field ID

**Status**: Resolved
**Type**: Enhancement
**Severity**: Low
**File**: `jiramator/planner.py:32`
**Resolved**: 2026-04-23

#### Problem

`_SPRINT_FIELD = "customfield_10021"` is hardcoded. Every other custom field in the system is configurable via `org_config.custom_fields`. If another Jira instance uses a different field ID for sprints, this would require a code change.

#### Fix

Add `sprint_field: customfield_10021` to `org_config.custom_fields` in the marketaxess config, and read it via `org_config.get_custom_field_id("sprint_field")` in planner. Fall back to `customfield_10021` if not configured (backward compatible).

#### Scope

- `configs/org/marketaxess.yaml` — add one line
- `jiramator/planner.py` — change constant to config lookup (~3 lines)
- `tests/test_planner_sprint.py` — update fixture

---

### Discarded items (no action needed)

| Item | Reason discarded |
|------|------------------|
| **`--yes` flag for `plan` command** | No current intention to automate `plan` — it's a human-driven, once-per-PI ritual. `import` already works non-interactively. Revisit if CI usage becomes a real need. |
| **Deferred import in `cli.py:126`** | Verified: `planner.py` doesn't import from `cli`, so no circular risk. However, the deferred import is harmless (costs nothing at runtime) and the comment documents the intent. Removing it changes nothing. Not worth a commit. |
| **Duplicate version in `__init__.py` + `pyproject.toml`** | `__version__` in `__init__.py` is only defined once and isn't referenced anywhere in the codebase (not used for CLI version — Click reads from package metadata via `version_option(package_name="jiramator")`). It's dead code but harmless. Could delete the line, but it's a 1-line cosmetic change that doesn't warrant its own task. Bundle it if touching `__init__.py` for another reason. |
| **Real Jira keys in `calcs.yaml`** | These are the team's actual config — that's the entire point of the tool. The configs dir is meant to hold real team configs. No issue here. |
| **Plan command duplicate detection** | Listed as future work in README. It's a feature request, not a bug or debt item. The current behavior is documented and the warning is explicit. Would be nice but doesn't belong in a cleanup plan. |
| **Extract deferred-field resolution hook** | Over-engineering for a single deferred field (`reporter`). Fix #3 addresses the actual bug. If more deferred fields appear later, refactor then. |

---

### Execution order

Both open items are independent. Either order works; #3 first since it's an actual bug:

1. **#3 — Reporter lookup bug** (bug fix)
2. **#4 — Sprint field config** (hardening)
