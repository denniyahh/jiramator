# Jiramator — Future Enhancements

## Pure Template Engine Refactor

**Priority:** Next major version
**Scope:** ticket_builder.py, config.py, calcs.yaml, all tests

### Problem

The ticket builder currently has implicit behavior baked into its build
functions. While ticket *fields* are already config-driven via `TicketTemplate.fields`,
the builder should have zero hardcoded field assignment logic — it should be a
pure template engine that only does variable interpolation, epic ref resolution,
and Jira field-type wrapping.

### Requirements

1. **Builder becomes a pure template engine** — `build_per_release_tickets()` and
   `build_per_sprint_tickets()` must not inject or assume any field values that
   aren't explicitly declared in the team config's `TicketTemplate.fields` dict.
   All field assignments (labels, fixVersions, story points, epic links, etc.)
   must come from config, never from code.

2. **Update calcs.yaml** — Add `labels` and `fixVersions` entries to every
   ticket template's `fields` dict so the config is fully self-describing.
   Currently some templates already have these; verify completeness across all
   per_release_tickets and per_sprint_tickets entries.

3. **Update tests** — Integration tests (test_integration.py) and unit tests
   (test_ticket_builder.py) assert on specific payload shapes. These must be
   updated to reflect the new pure-template behavior where every field in the
   output originates from config, not builder logic.

### Design Notes

- The `WRAPPED_FIELDS` dict and `_wrap_field()` function stay — they handle Jira
  API serialization concerns (e.g. `issuetype: Task` → `{"name": "Task"}`), which
  is a legitimate builder responsibility.
- Template variable resolution (`resolve_value()`) stays unchanged.
- Epic ref resolution (`$epic:key`) stays unchanged.
- The builder should remain pure/stateless — no I/O, no API calls.
