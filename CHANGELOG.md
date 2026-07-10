# Changelog

All notable changes to Jiramator are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

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

[1.1.0]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.1.0
[1.0.1]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.0.1
[1.0.0]: https://github.com/dkim_mktx/jiramator/releases/tag/v1.0.0
