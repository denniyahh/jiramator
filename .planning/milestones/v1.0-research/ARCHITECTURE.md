# Architecture Research

**Domain:** CLI tool for Jira ticket automation (Python)
**Researched:** 2026-04-27
**Confidence:** HIGH

## Current Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI Layer (Click)                       │
│  cli.py — arg parsing, config loading, error display         │
├──────────────┬──────────────────────────────────┬───────────┤
│  plan cmd    │  import cmd                      │  (future) │
├──────────────┴──────────────────────────────────┴───────────┤
│                   Orchestration Layer                         │
│  planner.py (interactive prompts, Rich output)               │
│  importer.py (spreadsheet→payload transform + execution)     │
├─────────────────────────────────────────────────────────────┤
│                   Data Transform Layer                        │
│  ticket_builder.py — template interpolation, payload build   │
│  field_resolver.py — field name resolution                   │
│  value_coercion.py — type coercion for Jira payloads         │
├─────────────────────────────────────────────────────────────┤
│                    I/O Layer                                  │
│  spreadsheet.py — CSV/XLSX reading                           │
│  jira_client.py — REST API (auth, retry, bulk create)        │
├─────────────────────────────────────────────────────────────┤
│                   Config Layer (Pydantic)                     │
│  config.py — OrgConfig, TeamConfig, template validation      │
│  YAML files: configs/org/*.yaml, configs/teams/*.yaml        │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Communicates With |
|-----------|----------------|-------------------|
| `cli.py` | Click entrypoints, arg parsing, config loading, error display | config.py, planner.py, importer.py, spreadsheet.py, jira_client.py |
| `config.py` | Pydantic models (OrgConfig, TeamConfig), YAML loading, template var validation | YAML files on disk |
| `planner.py` | Interactive PI planning orchestration: prompts, preview, epic-first creation | ticket_builder.py, jira_client.py, config models |
| `importer.py` | Spreadsheet row → Jira payload transform, duplicate-safe row-by-row import | field_resolver.py, value_coercion.py, jira_client.py |
| `ticket_builder.py` | Pure data transform: template interpolation, `$epic:ref` resolution, field wrapping | config models (read-only) |
| `field_resolver.py` | Resolves source field names → Jira field IDs via aliases, custom fields, Jira metadata | config models, Jira field metadata |
| `value_coercion.py` | Coerces raw values into Jira REST shapes (name objects, ADF, selects) | BulkCreateConfig |
| `spreadsheet.py` | Reads CSV/XLSX into `list[dict[str, str]]` | filesystem only |
| `jira_client.py` | HTTP client: auth, retry, single/bulk create, version/sprint management | Jira REST API |

### Key Architectural Properties

1. **Two command paths** that share config and Jira client but diverge at orchestration:
   - `plan`: interactive prompts → ticket_builder → jira_client (two-phase: epics then tickets)
   - `import`: spreadsheet.py → importer.py (field_resolver + value_coercion) → jira_client

2. **Pure data transform core**: ticket_builder.py has zero I/O. importer.py's `build_row_payload` is also pure — I/O only happens in `run_import`.

3. **Config is hierarchical but flat**: org-level + team-level YAML loaded independently, no inheritance between team configs.

## How New Features Integrate

### Feature 1: Template Config Inheritance

**What:** Allow team configs to inherit from a base template, overriding only what differs.

**Integration point:** `config.py` — specifically `load_team_config()`.

**Architecture decision:** Implement as a pre-processing step in config loading, not in the Pydantic models. The loaded `TeamConfig` should be identical regardless of whether it came from a flat file or an inherited one.

```
configs/
├── org/
│   └── acme.yaml
└── teams/
    ├── _base.yaml              # shared defaults
    ├── calcs.yaml              # inherits: _base.yaml + overrides
    └── platform.yaml           # inherits: _base.yaml + overrides
```

**Data flow:**
```
load_team_config(path)
    → read YAML
    → check for `inherits:` key
    → if present: load base YAML, deep-merge overrides on top
    → pass merged dict to TeamConfig(**merged)
    → return validated TeamConfig (identical shape as today)
```

**Component boundary:** This is entirely inside config.py. No other module changes. ticket_builder.py, planner.py, importer.py all receive the same `TeamConfig` object they do today.

**Merge semantics (opinionated):** Use deep-merge with list-replace (not list-append). Lists like `recurring_epics` and `per_release_tickets` should be fully replaced by the child, not concatenated. Rationale: appending creates invisible ordering dependencies; explicit is better.

### Feature 2: Spreadsheet Import Enhancements

**What:** The spreadsheet import path already exists (`import` command). Enhancements would include richer field mapping, validation previews, or additional source formats.

**Integration point:** Already well-factored. The pipeline is:

```
spreadsheet.py (read) → importer.py (transform) → jira_client.py (create)
```

**No architectural changes needed.** The existing layering handles this cleanly:
- New source formats → add reader in `spreadsheet.py`
- New field types → add coercion in `value_coercion.py`
- New mapping rules → extend `field_resolver.py`
- New CLI options → extend `import_command` in `cli.py`

### Feature 3: MCP (Model Context Protocol) API Support

**What:** Expose Jiramator's capabilities as MCP tools so AI assistants can invoke plan/import operations programmatically.

**Integration point:** New module `mcp_server.py` that sits alongside `cli.py` as an alternative entry point.

**Architecture decision:** MCP is a new **entry point**, not a new layer. It reuses the same orchestration and data transform layers.

```
┌───────────────────────────────────────────┐
│          Entry Points                      │
│  cli.py (Click)    mcp_server.py (MCP)    │
├───────────────────────────────────────────┤
│          Orchestration Layer               │
│  planner.py    importer.py                │
│  (refactored: separate prompt from logic) │
├───────────────────────────────────────────┤
│          Data Transform + I/O             │
│  (unchanged)                              │
└───────────────────────────────────────────┘
```

**Critical refactoring required:** `planner.py` currently mixes orchestration logic with interactive prompts (Rich `Prompt.ask`, `Confirm.ask`). MCP callers pass parameters directly — no interactive prompts. The planner must be split:

1. **`planner.py` core logic** — accepts all parameters as function args, returns results as data (no sys.exit, no console prompts)
2. **Interactive wrapper** — called by CLI, handles prompts then delegates to core
3. **MCP handler** — called by MCP server, passes params directly to core

**Data flow (MCP):**
```
MCP tool call (JSON params: pi_num, versions, team_config_path, dry_run)
    → mcp_server.py validates params, loads configs
    → calls planner core function (same as CLI path, minus prompts)
    → returns structured result (JSON, not Rich tables)
```

**MCP tools to expose:**
| Tool | Maps To | Parameters |
|------|---------|------------|
| `plan_pi` | `run_plan()` core | pi_num, versions, team_config, org_config, dry_run |
| `import_spreadsheet` | `run_import()` | spreadsheet_path, team_config, org_config, dry_run |
| `preview_plan` | `build_all()` | pi_num, versions, team_config, org_config |
| `list_teams` | config directory scan | org_config_path |

## Recommended Project Structure

```
jiramator/
├── cli.py              # Click entrypoint (unchanged)
├── mcp_server.py       # NEW: MCP server entrypoint
├── config.py           # Extended: add inheritance loading
├── planner.py          # Refactored: extract core from interactive
├── importer.py         # Unchanged
├── ticket_builder.py   # Unchanged
├── field_resolver.py   # Unchanged
├── value_coercion.py   # Unchanged
├── spreadsheet.py      # Unchanged
└── jira_client.py      # Unchanged
```

## Data Flow

### Plan Command (current)

```
User (interactive prompts)
    ↓
cli.py → load configs
    ↓
planner.py → prompt PI num, versions
    ↓
ticket_builder.build_all(epic_keys={}) → preview payloads
    ↓
planner._display_preview() → Rich table
    ↓ (if not dry_run)
JiraClient.create_issue() → epics (get real keys)
    ↓
ticket_builder.build_all(epic_keys=real) → final payloads
    ↓
JiraClient.create_issues_bulk() → tickets
    ↓
planner._display_results()
```

### Import Command (current)

```
User provides spreadsheet path
    ↓
cli.py → load configs + spreadsheet.read_spreadsheet()
    ↓
importer.build_preview_report()
    → field_resolver.resolve_field_name() per column
    → value_coercion.coerce_field_value() per cell
    → build_row_payload() per row
    ↓
importer.run_import()
    → client.find_issue_keys_by_summaries() (dedup)
    → client.create_issue() per row
```

### Plan via MCP (proposed)

```
AI assistant sends MCP tool call (pi_num=28, versions=[...], ...)
    ↓
mcp_server.py → validate params, load configs
    ↓
planner.run_plan_core(params) → same logic, no prompts
    ↓
return JSON result to MCP caller
```

## Architectural Patterns

### Pattern 1: Config Loading as the Single Validation Gate

**What:** All validation happens at config load time via Pydantic. Downstream code assumes valid data.
**When to use:** Always — this is the existing pattern and it works well.
**Trade-offs:** Strict upfront validation catches errors early. Downside: config.py is the largest, most complex module.

**Implication for inheritance:** The merge must happen *before* Pydantic validation. Load base YAML as raw dict, merge child dict on top, then pass to `TeamConfig(**merged)`. This ensures all cross-field validators (epic ref checks, template var checks) run on the final merged result.

### Pattern 2: Two-Phase Build for Epic Dependencies

**What:** Epics created first → real Jira keys collected → tickets built with resolved `$epic:ref`.
**When to use:** Any workflow that creates epics + linked tickets.
**Trade-offs:** Requires two passes through ticket_builder. Simple and correct.

**Implication for MCP:** The MCP handler must preserve this two-phase flow. It cannot be parallelized.

### Pattern 3: Pure Transform + Thin I/O Boundary

**What:** ticket_builder.py and importer.py's build functions are pure data transforms. I/O is isolated in jira_client.py and spreadsheet.py.
**When to use:** Always — this is the pattern that makes testing easy.
**Trade-offs:** Slightly more wiring code in orchestrators.

## Anti-Patterns

### Anti-Pattern 1: Mixing MCP Concerns into Existing Modules

**What people do:** Add MCP decorators or protocol handling directly into planner.py or cli.py.
**Why it's wrong:** Couples entry-point concerns. CLI and MCP have different I/O models (interactive vs. programmatic).
**Do this instead:** MCP server is a separate entrypoint module that imports and calls the same core functions.

### Anti-Pattern 2: Config Inheritance via Pydantic Model Inheritance

**What people do:** Create `BaseTeamConfig` and `DerivedTeamConfig` Python classes.
**Why it's wrong:** The inheritance is in YAML data, not in the Python type system. Team configs all have the same shape — they differ in values, not structure.
**Do this instead:** Implement inheritance as YAML dict merging in the loader, produce the same `TeamConfig` type.

### Anti-Pattern 3: Adding State to the Jira Client

**What people do:** Cache sprint lookups or field metadata in the client.
**Why it's wrong:** The client is currently stateless (aside from session). Adding caches creates hidden coupling.
**Do this instead:** If caching is needed, do it in the orchestration layer (planner/importer), not the client.

## Build Order (Dependencies Between Components)

### Phase 1: Template Config Inheritance
**Dependencies:** None — config.py only, no other module changes.
**Deliverable:** `load_team_config()` supports `inherits:` key, deep-merge, same `TeamConfig` output.
**Risk:** Low. Isolated change.

### Phase 2: Planner Refactoring (Core Extraction)
**Dependencies:** None, but required before MCP.
**Deliverable:** `run_plan()` split into `run_plan_core(params) → result` + interactive wrapper. No behavior change for CLI users.
**Risk:** Medium. Must preserve the two-phase epic flow and sprint resolution. Test coverage on planner is critical.

### Phase 3: MCP Server
**Dependencies:** Phase 2 (needs non-interactive planner core).
**Deliverable:** `mcp_server.py` exposing plan/import as MCP tools.
**Risk:** Medium. MCP protocol handling, error serialization, structured results.

### Phase 4: Spreadsheet Import Enhancements
**Dependencies:** None — can be done in parallel with any phase.
**Deliverable:** Whatever specific enhancements are needed (new formats, validation, etc.)
**Risk:** Low. Well-factored existing pipeline.

```
Phase 1 (config inheritance) ──────────────────────────→ done
Phase 2 (planner refactor)   ──────────────────────────→ done
                                                            ↓
Phase 3 (MCP server)         ──── requires Phase 2 ───→ done
Phase 4 (spreadsheet)        ──── independent ─────────→ done (anytime)
```

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Jira REST API | HTTP client with retry (jira_client.py) | Already well-isolated. No changes needed for new features. |
| MCP Protocol | stdio-based JSON-RPC (mcp_server.py) | New. Use `mcp` Python SDK. Entry point only — reuses all existing logic. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| CLI ↔ Orchestration | Function calls with typed args | cli.py calls planner/importer directly |
| MCP ↔ Orchestration | Same function calls | mcp_server.py calls same functions as CLI |
| Orchestration ↔ Transform | Pure function calls, dict in/dict out | ticket_builder returns dicts, importer returns dataclasses |
| Orchestration ↔ I/O | JiraClient method calls | Client takes ready payloads, returns keys/data |
| Config loading ↔ YAML | File I/O in load_*_config() | Inheritance merge happens here, transparent to callers |

## Sources

- Direct codebase analysis of jiramator/ (all 9 modules)
- Existing config structure in configs/org/ and configs/teams/
- MCP specification for tool exposure patterns

---
*Architecture research for: Jiramator CLI tool — feature integration*
*Researched: 2026-04-27*
