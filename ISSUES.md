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
