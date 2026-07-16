# Changelog

All notable changes to Jiramator are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [1.2.4] — 2026-07-17

### Fixed
- **`plan`: custom fields declared `adf_text` in the org config's
  `field_types` now send valid Atlassian Document Format (ADF), not just the
  built-in `description` field.** v1.2.3 fixed `description`, but `plan`'s
  ticket builder still special-cased only that one field — any other
  rich-text custom field (e.g. "Acceptance Criteria", `customfield_10042`)
  templated into `plan`'s epics/tickets was sent as a plain string and
  rejected by Jira Cloud with `"The field value is not valid Atlassian
  Document Format (ADF) content."`. The builder now reuses the same
  `field_types: adf_text` declarations already used by `import`/`update`
  (reverse-mapped from logical name to Jira field ID via `custom_fields`),
  so declaring a field `adf_text` once covers `plan`, `import`, and `update`
  consistently.

## [1.2.3] — 2026-07-16

### Fixed
- **`plan`: `description` field now sends valid Atlassian Document Format
  (ADF).** Jira Cloud's REST API v3 rejects a plain string for `description`
  with `"The field value is not valid Atlassian Document Format (ADF)
  content."`. `import`/`update` already handled this (v1.1.1); `plan`'s
  ticket builder now wraps `description` the same way, so PI-planning
  templates can include a `description` field on epics/tickets.

## [1.2.2] — 2026-07-15

### Fixed
- **`import`/`update`: whole-number values from XLSX cells no longer break
  `value_aliases` (or any other exact-string field match).** Excel/openpyxl
  frequently stores whole numbers as floats internally (e.g. a cell showing
  `1` is read back as `1.0`), even when the user never typed a decimal.
  Spreadsheet ingestion now renders whole-number floats without the trailing
  `.0`, so a `value_aliases` entry keyed `"1"` correctly matches a `1.0` cell
  instead of silently passing through unmapped as `"1.0"` and getting
  rejected by Jira with `Select a valid option ... and try again`.

## [1.2.1] — 2026-07-14

### Added
- **`JIRAMATOR_CA_BUNDLE` and `JIRAMATOR_RELAX_TLS_STRICT` environment
  variables** to work around SSL certificate errors on corporate networks
  where a VPN client or TLS-inspecting proxy (e.g. Netskope, Zscaler)
  re-signs HTTPS traffic with its own certificate. `JIRAMATOR_CA_BUNDLE`
  points jiramator at an alternate trusted-certificate bundle (e.g. the
  system store). `JIRAMATOR_RELAX_TLS_STRICT` narrowly relaxes a single
  RFC 5280 conformance check (non-critical "Basic Constraints") that
  Python 3.13+ enforces by default but some corporate proxy certificates
  don't satisfy — certificate trust, hostname matching, and expiry checks
  remain fully enforced either way. Both are opt-in and off by default, so
  default behavior is unchanged. See the new README Troubleshooting entry
  for guidance on when and how to use them.

## [1.2.0] — 2026-07-13

### Added
- **`bulk_create.value_aliases` in org config** — maps shorthand spreadsheet
  values to the exact Jira dropdown option label for `single_select`/
  `multi_select` fields, in both `import` and `update` (they share the same
  field-coercion path, so this works for both without extra config). Jira
  rejects any value that isn't an exact match to a field's configured
  option list; for **Risk** Jira tickets, fields like Code Complexity, QA
  Testing, Risk Impact, and Risk Mitigation are commonly scored with a
  bare number (e.g. `1`, `2`, `3`) in source data, while Jira's actual
  option strings include a descriptive label (e.g. `1. Low`, `3. High`).
  `value_aliases` lets you map the shorthand once in org config instead of
  editing every spreadsheet. Values with no alias entry pass through
  unchanged — fully additive, no impact on existing configs.

## [1.1.1] — 2026-07-13

### Fixed
- **`import`/`update`: `description` field now sends valid Atlassian Document
  Format (ADF).** Jira Cloud's REST API v3 rejects a plain string for
  `description` with `"The field value is not valid Atlassian Document Format
  (ADF) content."`. The bulk-create/update field coercion now converts
  `description` the same way it already did for other rich-text custom
  fields, so spreadsheet imports and updates with a Description column work
  correctly.
- **`plan`: fix versions referenced only via a ticket template (e.g.
  `fixVersions: ["{pi_label}"]` on a recurring ticket) are now detected and
  offered for creation.** Previously, only the release versions typed in at
  the `--versions` prompt were checked against Jira and auto-created;
  a fix version referenced solely inside a ticket template's fields (such as
  a PI-umbrella version distinct from per-release versions) would cause a
  confusing 400 error at ticket-creation time instead of the normal
  create-with-confirmation flow.

### Docs
- README: added a **Glossary** and **Troubleshooting** section, worked
  examples for `plan`, `import`, and `update` (using a shared `PI26.4`
  scenario), and a clearer firm-level (org config) vs. team-level (team
  config) comparison.

## [1.1.0] — 2026-07-10

### Added
- **`jiramator init` setup wizard** — an interactive, guided first-time setup.
  It connects to Jira, **auto-discovers your custom field IDs by name** (Epic
  Link, Story Points, Sprint), validates your project key, sets up credentials
  (paste-able export commands or a gitignored `.env`), and writes a ready-to-use
  org config plus a commented team-config skeleton. This removes the hardest
  onboarding barrier for non-technical users: hand-editing YAML with raw
  `customfield_*` IDs.

### Changed
- README Quick Start now leads with `jiramator init` and `pipx install`;
  hand-editing configs is demoted to a "Manual setup" section.

### Docs
- New wiki page: **Setup Wizard Walkthrough** (prompt-by-prompt guide).
- `docs/mcp-server-proposal.md` marked **reviewed / declined**; the MCP path was
  not adopted because it does not remove the real on-ramp barriers.

## [1.0.1] — 2026-07-10

### Added
- **Non-interactive `plan`** via `--pi-number`, `--versions`, and `--yes/-y`
  flags. When all inputs are supplied, `plan` runs without prompts; `--yes`
  skips the fix-version-creation and final-create confirmations. The interactive
  flow is unchanged when flags are omitted.
- `PlanInputs` dataclass and pure normalization helpers (`normalize_pi_number`,
  `normalize_versions`, `make_plan_inputs`) in `planner.py`, giving the planner
  a promptless core.
- Experimental `.github/workflows/jiramator-plan.yml` (`workflow_dispatch`
  planning form). Note: unusable where GitHub Actions is disabled by
  enterprise/org policy.

### Fixed
- Corrected the `update --dry-run` credentials note and harmonized CLI help text.

## [1.0.0]

Initial release.

### Added
- `plan`, `import`, and `update` commands.
- Run reports + `--resume` with config-drift protection (`plan`, `import`).
- Template inheritance (org `default_fields` → team `defaults` → template `fields`).
- Sprint assignment for `plan` (via `board_id` + `sprint_name_template`).
- Pre-existing epic reuse (`existing_epics`) and release→sprint mapping.
- CSV encoding auto-detection with `--encoding` override.
- Preview-first safety model: `--dry-run` on every command.

[1.2.4]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.2.4
[1.2.3]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.2.3
[1.2.2]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.2.2
[1.2.1]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.2.1
[1.2.0]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.2.0
[1.1.1]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.1.1
[1.1.0]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.1.0
[1.0.1]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.0.1
[1.0.0]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.0.0
