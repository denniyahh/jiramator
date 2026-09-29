# Research Summary

**Project:** Jiramator — Feature Extensions (Template Inheritance, MCP Server, Spreadsheet Hardening)
**Synthesized:** 2026-04-27

## Executive Summary

Jiramator is an existing, well-structured Python CLI for PI planning automation with Jira. The codebase has clean architectural layers (CLI → orchestration → pure transforms → I/O) and a mature config system built on Pydantic + PyYAML. The three planned features — template config inheritance, MCP server integration, and spreadsheet import hardening — fit naturally into the existing architecture without requiring structural overhauls.

The recommended approach is to build foundation-first: config inheritance and CLI hardening (`--yes` flag, execution reports) before MCP integration. MCP requires a planner refactor to separate interactive prompts from core logic — this is the riskiest change because it touches the most critical code path. Spreadsheet hardening is independent and can proceed in parallel with everything else.

The key risks are: (1) config merge semantics that confuse users (deep-merge vs. replace ambiguity), (2) MCP integration creating a second untested code path that diverges from the CLI, and (3) spreadsheet imports at scale hitting Jira API rate limits. All three are preventable with explicit design decisions upfront — merge rules documented before implementation, same test suite for both entry points, and user-lookup caching before enabling large imports.

## Key Findings

### From STACK.md

- **Only one new dependency:** `mcp>=1.27` (official MCP Python SDK). Everything else uses existing stack.
- Template inheritance = custom `extends` + deep dict merge in config loader. No new libraries — 15 lines of stdlib code.
- Spreadsheet hardening = code-level work in existing modules. No new libraries needed (avoid pandas/polars — overkill).
- MCP SDK brings async infrastructure (httpx, anyio, uvicorn) — MCP server is async but core logic stays sync.

### From FEATURES.md

**Must-have (P1):**
- Config validation with actionable errors
- `--yes` flag for non-interactive/scripted runs
- Execution report (JSON/Markdown of created issues)
- Template inheritance (org → team → override)

**Should-have (P2):**
- MCP server integration (depends on `--yes` + stable CLI)
- Setup wizard, sprint assignment, sub-task support
- Multi-team orchestration (depends on template inheritance)
- Better duplicate detection, error recovery/resume

**Defer to v2+:**
- Rollback/undo, plan preview export, config diffing, spreadsheet import enhancements

**Anti-features (don't build):**
- Full Jira update/sync engine, web UI, workflow automation, multi-instance support, plugin system

### From ARCHITECTURE.md

- Architecture is **4 layers**: CLI entry → orchestration (planner/importer) → pure transforms (ticket_builder, field_resolver, value_coercion) → I/O (jira_client, spreadsheet)
- MCP is a **new entry point**, not a new layer. It calls the same orchestration functions.
- **Critical refactor required:** planner.py mixes interactive prompts with core logic. Must split into `run_plan_core()` + interactive wrapper before MCP can work.
- Template inheritance is isolated to `config.py` load path — no other modules change.
- Two-phase epic build (create epics → get keys → build tickets) must be preserved in MCP path.

### From PITFALLS.md

**Top 5 pitfalls:**

| # | Pitfall | Severity | Prevention |
|---|---------|----------|------------|
| 1 | CSV encoding corruption (Windows cp1252) | CRITICAL | Auto-detect encoding; test with real-world messy files |
| 2 | MCP/REST dual code path divergence | CRITICAL | Same test suite against both backends; REST stays default |
| 3 | Config merge semantics ambiguity | CRITICAL | Define explicit rules per field type; add `config show --resolved` |
| 4 | Bulk import partial failure with no recovery | CRITICAL | Import manifest + `--resume` flag |
| 5 | API rate limiting on large imports (user lookups) | HIGH | Cache user lookups; batch resolve before import loop |

**UX pitfalls to prevent early:**
- Silent column skipping → require `--ignore-unmapped`
- No dry-run default for import → make `--dry-run` default, require `--execute`
- Error messages with Jira field IDs → map back to logical names

## Implications for Roadmap

### Suggested Phase Structure

**Phase 1: Foundation Hardening**
- Config validation with actionable errors
- `--yes` flag for non-interactive mode
- Execution report (created issues manifest)
- Fix spreadsheet encoding (auto-detect) + workbook close bug
- *Rationale:* All downstream features depend on these. `--yes` unblocks MCP. Execution report unblocks recovery/rollback. Config validation unblocks inheritance.
- *Pitfalls to avoid:* Encoding corruption (#1), partial failure recovery (#4)
- *Features delivered:* 4 P1 table stakes

**Phase 2: Template Config Inheritance**
- `inherits:` key in team YAML with deep-merge
- Explicit merge semantics (dicts deep-merge, lists replace)
- `config show --resolved` debugging command
- *Rationale:* Highest-value differentiator. Isolated to config.py — low risk. Unblocks multi-team orchestration later.
- *Pitfalls to avoid:* Merge semantics ambiguity (#3)
- *Features delivered:* Template inheritance (P1 differentiator)

**Phase 3: Planner Refactor**
- Split planner.py into core logic + interactive wrapper
- Preserve two-phase epic flow
- Add comprehensive test coverage before touching anything
- *Rationale:* Required before MCP. Riskiest change — touches core creation flow. Needs its own phase for safety.
- *Pitfalls to avoid:* Breaking existing CLI behavior during refactor

**Phase 4: MCP Server Integration**
- `mcp_server.py` entry point with `FastMCP`
- Tools: `plan_pi`, `import_spreadsheet`, `preview_plan`, `list_teams`
- Structured JSON results (not Rich tables)
- Same test suite as CLI path
- *Rationale:* Novel differentiator. Depends on Phase 3 refactor and Phase 1 `--yes` flag.
- *Pitfalls to avoid:* MCP/REST divergence (#2), missing retry/backoff parity

**Phase 5: Import Scaling & Polish**
- User lookup caching, batch resolution
- Rate limit awareness, `--batch-size` flag
- Interactive column mapping confirmation
- `--column-map` CLI override
- *Rationale:* Enables large-scale spreadsheet imports safely. Independent of MCP but benefits from execution report (Phase 1).
- *Pitfalls to avoid:* Rate limiting (#5), field resolution ambiguity (#5 from pitfalls)

### Research Flags

| Phase | Needs `/gsdr:research-phase`? | Notes |
|-------|-------------------------------|-------|
| Phase 1: Foundation | No | Standard patterns, well-documented |
| Phase 2: Config Inheritance | No | Architecture research already defines the approach clearly |
| Phase 3: Planner Refactor | **Yes** | Need to map current planner.py interactive touchpoints before refactoring |
| Phase 4: MCP Server | **Yes** | MCP SDK API surface, transport configuration, error serialization patterns |
| Phase 5: Import Scaling | No | Standard caching/batching patterns |

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Only 1 new dependency. Existing stack is locked and proven. MCP SDK version verified. |
| Features | MEDIUM | Feature priorities clear, but user validation needed. Anti-features list is opinionated (correctly). |
| Architecture | HIGH | Based on direct codebase analysis. Integration points are well-defined. |
| Pitfalls | HIGH | Specific to existing code (line numbers cited). Prevention strategies are concrete. |

**Overall: HIGH** — This is a well-understood codebase with well-scoped features. The research is grounded in actual code analysis, not hypothetical patterns.

### Gaps to Address During Planning

1. **Planner.py interactive touchpoints:** Need exact inventory of all `Prompt.ask`/`Confirm.ask` calls before refactoring
2. **MCP SDK `FastMCP` API specifics:** Tool registration, error handling, transport config need hands-on exploration
3. **Config merge edge cases:** What happens with nested lists inside dicts? Need to define full merge spec
4. **Sprint assignment wiring:** Config fields exist (`board_id`, `sprint_name_template`) but implementation scope is unclear

## Sources

- Jiramator codebase (all 9 modules in `jiramator/`)
- `pyproject.toml` dependency versions
- MCP Python SDK (`mcp>=1.27`)
- Jira REST API v3 documentation
- openpyxl, Pydantic documentation

---
*Research synthesis for: Jiramator — Feature Extensions*
*Synthesized: 2026-04-27*
