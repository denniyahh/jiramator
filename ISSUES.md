# Open Issues

## #1 — EpicTemplate missing fields dict — Jira 400 on epic creation

**Status**: Open
**Type**: Bug
**Created**: 2026-04-16

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
- API format uses `{"value": "..."}` for select fields — `_wrap_field` may need a new wrapping type or these can be passed as raw dicts
- `customfield_11623` (Requesting Customer) uses array value format: `{"value":["Internal Initiative"]}`
