# Feature Research

**Domain:** Jira automation CLI for PI planning
**Researched:** 2026-04-27
**Confidence:** MEDIUM — based on domain knowledge of Jira tooling ecosystem; no single dominant competitor in this exact niche (config-driven CLI for PI planning)

## Existing Feature Baseline

Jiramator already ships:
- `plan` command: interactive PI planning with YAML configs, template variables, epic references, two-phase build, bulk creation
- `import` command: CSV/XLSX spreadsheet import with field resolution, coercion, duplicate detection, dry-run
- Org/team config split, Rich CLI output

## Feature Landscape

### Table Stakes (Users Expect These)

Features that users of a PI planning automation tool assume exist. Missing = friction that pushes them back to manual processes or spreadsheets.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Config validation with actionable errors** | Users write YAML by hand; cryptic errors waste time | LOW | JSON Schema validation on load, surface line numbers. Already partially exists but needs hardening |
| **Setup wizard (`setup` subcommand)** | New users can't create configs from scratch without examples | MEDIUM | Interactive prompts → generate org + team YAML. Listed in README future enhancements |
| **`--yes` flag for non-interactive runs** | CI/scripted usage, repeat runs without babysitting | LOW | Skip all confirmation prompts. Listed in README future enhancements |
| **Sub-task support** | Many teams structure work as stories → sub-tasks, not just epic → tickets | MEDIUM | `parent` field linking to created issues, not just epics. Listed in README future enhancements |
| **Better duplicate detection** | Re-running plan after partial failure shouldn't create duplicates | MEDIUM | Query existing issues by summary + PI label before creation. Listed in README future enhancements |
| **Execution report / run summary** | Users need proof of what was created for audit trail and team communication | LOW | Structured output (JSON/Markdown) of created issue keys, skipped duplicates, errors |
| **Error recovery / resume** | Partial failures during bulk creation leave users in unknown state | MEDIUM | Persist creation state, allow resuming from last failure point |

### Differentiators (Competitive Advantage)

Features that would make Jiramator notably better than "just write a Python script" or "use Jira bulk import UI."

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Template inheritance (org → team → override)** | Teams share 80% of config; inheritance eliminates copy-paste drift across team configs | MEDIUM | Org config provides base templates, team config overrides/extends. Key architectural feature — see dependency notes |
| **MCP server integration** | Let AI assistants (Copilot, Claude) create/modify PI plans conversationally; POs describe intent, tool generates configs | HIGH | Expose plan/import as MCP tools. Novel for this domain. Depends on stable CLI interface first |
| **Spreadsheet import enhancements** | POs live in spreadsheets; the closer Jiramator maps to their mental model, the lower adoption friction | MEDIUM | Column mapping profiles, row filtering, conditional field defaults, multi-sheet orchestration |
| **Config diffing between PIs** | "What changed from PI27 to PI28?" — helps POs track config evolution and catch unintended changes | LOW | Diff two team configs, highlight added/removed/modified templates |
| **Plan preview as shareable artifact** | POs need to share "here's what I'm about to create" with stakeholders before executing | LOW | Export dry-run output as Markdown/HTML table for Slack/email/Confluence |
| **Multi-team orchestration** | POs managing multiple teams want one command, not N separate runs | MEDIUM | Glob team configs, run plan for each, aggregate report. Depends on stable single-team execution |
| **Sprint assignment** | Assigning created tickets to actual Jira sprints saves a manual step | MEDIUM | Resolve sprint names via board API, assign during creation. `board_id` and `sprint_name_template` already in config but not wired |
| **Rollback / undo** | "I created 50 wrong tickets" — ability to bulk-delete a run's output | LOW | Use execution report to identify and delete created issues. Safety feature that builds trust |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Full Jira issue update/sync engine** | "I want to update existing tickets too" | Upsert semantics on Jira are complex (field merge, transition states, permissions). Turns a creation tool into a sync engine with 10x complexity | Keep create-only. If users need updates, they should use Jira bulk edit or dedicated sync tools (e.g., Jira CLI, ScriptRunner) |
| **Web UI / dashboard** | "Not everyone uses CLI" | Maintaining a web frontend doubles the surface area and changes the project's identity. CLI is the strength | Invest in MCP integration instead — meets users where they already are (AI assistants, chat) |
| **Jira workflow automation (transitions, webhooks)** | "Auto-move tickets through workflow" | This is Jira Automation's domain. Reimplementing it is a maintenance trap | Document integration with Jira Automation rules for post-creation workflows |
| **Multi-Jira-instance support** | "We have Cloud and Server" | Server API differs enough to require parallel codepaths. Cloud-only is a defensible scope decision | Stay Jira Cloud only. Document clearly |
| **Real-time Jira field validation in dry-run** | "Dry-run should catch all errors" | Jira's `validateOnly=true` was observed to create real issues (noted in README). Server-side validation is unreliable | Keep dry-run as payload preview. Add client-side schema checks where possible |
| **Plugin/extension system** | "Let users write custom coercion logic" | Plugin APIs are expensive to design and maintain for a niche tool | Use config-driven coercion rules. If a user needs custom logic, they fork |

## Feature Dependencies

```
[Config validation] 
    └──required-by──> [Setup wizard] (wizard needs to validate generated configs)

[Template inheritance]
    └──required-by──> [Multi-team orchestration] (shared templates reduce per-team config)

[Execution report]
    └──required-by──> [Rollback/undo] (need to know what was created)
    └──required-by──> [Error recovery/resume] (need to know where it stopped)

[Stable CLI interface]
    └──required-by──> [MCP server integration] (MCP tools wrap CLI commands)
    └──required-by──> [--yes flag] (non-interactive mode is prerequisite for MCP)

[Sprint assignment]
    └──requires──> [board_id + sprint_name_template in config] (already present)

[Spreadsheet import enhancements]
    └──builds-on──> [Existing import command]
    └──independent-of──> [Template inheritance] (different config paths)
```

### Dependency Notes

- **Template inheritance requires config validation first:** Inheritance adds merge complexity; without validation, debugging bad merged configs is painful.
- **MCP integration requires `--yes` flag:** MCP tools can't answer interactive prompts. Non-interactive mode is a hard prerequisite.
- **Rollback requires execution report:** Can't undo what you can't identify. Execution report is the foundation.
- **Multi-team orchestration requires template inheritance:** Without inheritance, multi-team means maintaining N independent configs. With it, teams share a base and override.

## MVP Definition

### Launch With (next milestone v1.x)

- [x] Spreadsheet import — already shipped
- [ ] **Config validation with actionable errors** — foundational quality-of-life
- [ ] **`--yes` flag** — unblocks MCP and scripted usage
- [ ] **Execution report** — unblocks rollback and resume
- [ ] **Template inheritance** — highest-value differentiator for multi-team POs

### Add After Validation (v1.x+)

- [ ] **MCP server integration** — once `--yes` flag and stable CLI are proven
- [ ] **Setup wizard** — once config schema is stable
- [ ] **Sprint assignment** — wiring already exists in config, needs implementation
- [ ] **Multi-team orchestration** — once template inheritance is working

### Future Consideration (v2+)

- [ ] **Rollback/undo** — nice safety net, not blocking adoption
- [ ] **Plan preview as shareable artifact** — useful but workaround exists (copy dry-run output)
- [ ] **Config diffing** — low complexity, add when users request it
- [ ] **Spreadsheet import enhancements** — incremental, add based on user feedback

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Config validation | HIGH | LOW | P1 |
| `--yes` flag | HIGH | LOW | P1 |
| Execution report | HIGH | LOW | P1 |
| Template inheritance | HIGH | MEDIUM | P1 |
| MCP server integration | HIGH | HIGH | P2 |
| Setup wizard | MEDIUM | MEDIUM | P2 |
| Sprint assignment | MEDIUM | MEDIUM | P2 |
| Sub-task support | MEDIUM | MEDIUM | P2 |
| Multi-team orchestration | MEDIUM | MEDIUM | P2 |
| Better duplicate detection | MEDIUM | MEDIUM | P2 |
| Error recovery/resume | MEDIUM | MEDIUM | P2 |
| Rollback/undo | LOW | LOW | P3 |
| Plan preview export | LOW | LOW | P3 |
| Config diffing | LOW | LOW | P3 |
| Spreadsheet import enhancements | MEDIUM | MEDIUM | P3 |

**Priority key:**
- P1: Must have for next milestone
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Jira Bulk Import (built-in) | jira-cli (go-jira) | Custom Python scripts | **Jiramator** |
|---------|----------------------------|--------------------|-----------------------|---------------|
| CSV import | Yes (basic) | No | Manual | Yes (with coercion) |
| Template-driven creation | No | No | Per-script | Yes (YAML configs) |
| PI-aware (sprints, releases) | No | No | Per-script | Yes (native) |
| Epic reference system | No | No | Per-script | Yes (`$epic:key`) |
| Dry-run preview | No | No | Per-script | Yes |
| Config inheritance | N/A | N/A | No | **Planned** |
| AI/MCP integration | No | No | No | **Planned** |
| Multi-team | N/A | N/A | Per-script | **Planned** |

Jiramator's niche is clear: **PI-planning-aware, config-driven bulk creation**. No existing tool combines YAML templates + PI semantics (sprints, releases, epics) + spreadsheet import. The differentiators (template inheritance, MCP) widen this gap.

## Internal Tensions

| Feature | Tension Introduced | Constraint Mechanism | Residual Risk |
|---------|--------------------|---------------------|---------------|
| Template inheritance | Config merge semantics become implicit — users can't easily see "what's the final config?" | Provide a `jiramator resolve-config` command that dumps the merged result | Deep inheritance chains may still confuse users |
| MCP server integration | Tool becomes dual-interface (CLI + MCP) with different interaction models | MCP tools are thin wrappers around CLI with `--yes`; no separate logic paths | MCP-specific error reporting may diverge from CLI UX |
| Spreadsheet import enhancements | Import becomes a second "product" inside Jiramator, competing for maintenance attention | Keep import as a secondary workflow; plan is the primary. Don't add features that only serve import | Users who primarily want import may push the tool away from its PI planning identity |

## Sources

- Jiramator README.md and existing codebase analysis
- Jira REST API v3 documentation (field types, bulk create, sprint APIs)
- Domain knowledge: Atlassian ecosystem tooling (Jira CLI, ScriptRunner, Jira Automation, Jira bulk import UI)
- MCP specification (Model Context Protocol for AI tool integration)
- PI planning practices from SAFe framework

---
*Feature research for: Jira automation CLI for PI planning*
*Researched: 2026-04-27*
