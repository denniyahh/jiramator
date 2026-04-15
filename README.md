# Jiramator

Generic, config-driven Jira ticket automation for PI planning.

Jiramator reads a pair of YAML config files — one for your organization, one for
your team — and generates the full set of recurring Jira tickets you need at the
start of every Program Increment: epics, per-release tickets, and per-sprint
tickets.  Zero team-specific logic is hardcoded; everything is declarative
config.

## Quick Start

### 1. Install

```bash
# Clone the repo
git clone <repo-url> && cd jiramator

# Install (editable) with dev deps
pip install -e ".[dev]"
```

### 2. Set credentials

Jiramator reads Jira credentials from environment variables (never from config
files).  The default variable names are `JIRA_EMAIL` and `JIRA_TOKEN` — these
can be overridden per-org in the org config.

```bash
export JIRA_EMAIL="you@company.com"
export JIRA_TOKEN="your-jira-api-token"
```

### 3. Create config files

Copy the example configs and edit them for your organization and team:

```bash
cp configs/org/marketaxess.yaml  configs/org/mycompany.yaml
cp configs/teams/calcs.yaml      configs/teams/myteam.yaml
```

See [Config Reference](#config-reference) below for the full schema.

### 4. Run

```bash
# Dry run — preview what would be created, no API calls
jiramator plan --org-config configs/org/mycompany.yaml \
               --team-config configs/teams/myteam.yaml \
               --dry-run

# Live run — creates tickets in Jira
jiramator plan --org-config configs/org/mycompany.yaml \
               --team-config configs/teams/myteam.yaml
```

The `plan` command walks you through an interactive flow:

1. Prompts for the PI number (e.g. `28`)
2. Prompts for release versions (e.g. `26.1.1, 26.1.2, 26.2.0`)
3. Builds the full ticket set and shows a preview with counts
4. Checks for missing fix versions in Jira and offers to create them
5. Asks for confirmation before creating anything
6. Creates epics first, then bulk-creates remaining tickets

## Config Reference

Jiramator uses a two-tier configuration model:

- **Org config** — shared across all teams at a company (Jira URL, custom field
  IDs, sprint cadence)
- **Team config** — specific to one team (project key, epic definitions, ticket
  templates)

### Org Config

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `jira_url` | string | **yes** | Base URL of your Jira instance |
| `jira_email_env` | string | no | Env var name for email (default: `JIRA_EMAIL`) |
| `jira_token_env` | string | no | Env var name for API token (default: `JIRA_TOKEN`) |
| `custom_fields` | map | **yes** | Mapping of logical names → Jira custom field IDs |
| `sprints.count` | int | **yes** | Number of sprints per PI |
| `sprints.standard_length_weeks` | int | **yes** | Length of standard sprints in weeks |
| `sprints.long_length_weeks` | int | **yes** | Length of extended sprints in weeks |
| `sprints.long_sprints` | list[int] | no | Which sprint numbers are long (1-indexed) |

**Example** (`configs/org/marketaxess.yaml`):

```yaml
jira_url: https://marketaxess.atlassian.net

jira_email_env: JIRA_EMAIL
jira_token_env: JIRA_TOKEN

custom_fields:
  story_points: customfield_10026
  epic_link: customfield_10014

sprints:
  count: 6
  standard_length_weeks: 2
  long_length_weeks: 3
  long_sprints: [6]
```

### Team Config

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `project_key` | string | **yes** | Jira project key (e.g. `CA`) |
| `team_name` | string | **yes** | Team display name, available as `{team_name}` |
| `board_id` | int/null | no | Jira board ID for sprint assignment (null to skip) |
| `sprint_name_template` | string/null | no | Pattern to match sprints (e.g. `"CA Sprint {pi_num}.{sprint_num}"`) |
| `recurring_epics` | list | no | Epics created at the start of each PI |
| `per_release_tickets` | list | no | Tickets generated once per release version |
| `per_sprint_tickets` | list | no | Tickets generated once per sprint |

#### Epic Template

```yaml
recurring_epics:
  - key: bau                                    # internal ref key
    summary: "{team_name} {pi_label} - BAU Work" # template string
```

The `key` is used in ticket templates to link tickets to this epic via
`$epic:<key>` syntax (see [Epic References](#epic-references)).

#### Ticket Template

```yaml
per_release_tickets:
  - summary: "Testing - {version} Pre-regression test"
    fields:
      issuetype: Task
      priority: Medium
      labels: ["{pi_label}", "Testing"]
      fixVersions: ["{version}"]
      customfield_10026: 0.5          # story points
      customfield_10014: "$epic:misc"  # epic link
```

#### Per-Sprint Ticket with Long Sprint Handling

```yaml
per_sprint_tickets:
  - summary: "Misc - Prod Support (Sprint {sprint_num})"
    fields:
      issuetype: Task
      priority: Medium
      labels: ["{pi_label}", "Prod_Support"]
      fixVersions: ["{pi_label}"]
      customfield_10026: 2.0
      customfield_10014: "$epic:misc"
    extra_on_long_sprint: 1             # create 1 extra ticket on long sprints
    long_sprint_suffix: ["a", "b"]      # suffixes for {sprint_num}: "6a", "6b"
```

For a 6-sprint PI where sprint 6 is long, this produces:
- Sprints 1–5: one ticket each (`Sprint 1`, `Sprint 2`, ... `Sprint 5`)
- Sprint 6: two tickets (`Sprint 6a`, `Sprint 6b`)

## Template Variable Reference

| Variable | Available In | Example Value | Description |
|----------|-------------|---------------|-------------|
| `{pi_label}` | epics, all tickets | `PI28` | `"PI" + pi_num` |
| `{pi_num}` | epics, all tickets | `28` | The PI number entered at runtime |
| `{version}` | per_release only | `26.1.1` | The release version string |
| `{sprint_num}` | per_sprint only | `1`, `6a` | Sprint number (with suffix for long sprints) |
| `{team_name}` | epics, all tickets | `Calcs` | From team config `team_name` field |

Variables can appear in `summary` and in any string value within `fields`.
Numeric field values (e.g. `customfield_10026: 0.5`) are passed through as-is.

## Epic References

Use `$epic:<key>` in any field value to reference an epic defined in
`recurring_epics`.  The ticket builder resolves these to actual Jira issue keys
after the epics are created.

```yaml
customfield_10014: "$epic:misc"   # → resolved to e.g. "CA-1234"
```

In dry-run mode, epic references are left as the literal string `$epic:misc`.

## Field Type Mapping

Jiramator automatically wraps field values into the JSON structures Jira expects.
You write simple values in your config; the builder handles the rest.

| Config Value | Jira API Payload | Fields |
|-------------|-----------------|--------|
| `"Task"` | `{"name": "Task"}` | `issuetype`, `priority` |
| `["26.1.1"]` | `[{"name": "26.1.1"}]` | `fixVersions`, `components` |
| `["PI28", "Testing"]` | `["PI28", "Testing"]` | `labels` (no wrapping) |
| `0.5` | `0.5` | `customfield_*` (pass-through) |
| `"$epic:misc"` | `"CA-1234"` | `customfield_*` (resolved) |

## Creating Custom Team Configs

1. **Start from an example:** Copy `configs/teams/calcs.yaml` as a starting
   point.

2. **Set your project key and team name:** These are the only required fields.

3. **Define your epics:** List the recurring epics your team creates each PI.
   Give each a unique `key` for cross-referencing.

4. **Define per-release tickets:** Templates that get stamped out once for each
   release version.  Use `{version}` in summaries and fix versions.

5. **Define per-sprint tickets:** Templates stamped out once per sprint.  Use
   `{sprint_num}`.  For long sprints, add `extra_on_long_sprint` and
   `long_sprint_suffix` to generate split tickets.

6. **Look up custom field IDs:** Use the Jira REST API to find your instance's
   custom field IDs:
   ```
   GET /rest/api/3/field
   ```
   Map the logical names in your org config, then reference the field IDs
   directly in team ticket templates.

7. **Validate:** Run with `--dry-run` to see the full ticket set before touching
   Jira.

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest -v
```

198 tests covering config parsing, ticket building, Jira client, orchestration,
and end-to-end integration with real config files.

## Future Enhancements

- **`setup` subcommand** — Interactive wizard to generate org and team config
  files step by step.
- **Duplicate detection** — Query Jira for existing tickets matching summary +
  PI label before creating, skip duplicates automatically.
- **`--yes` flag** — Skip all confirmation prompts for CI/scripted usage.

## License

MIT
