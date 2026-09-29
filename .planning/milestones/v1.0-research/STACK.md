# Technology Stack

**Project:** Jiramator — New Feature Extensions
**Researched:** 2026-04-27
**Scope:** Spreadsheet import hardening, MCP server integration, template inheritance only. Existing stack (Click, Pydantic, requests, Rich, PyYAML, openpyxl) is not re-evaluated.

## Existing Stack (Confirmed Present)

Already in `pyproject.toml` — no changes needed:

| Technology | Version | Status |
|------------|---------|--------|
| Python | >=3.11 | Locked |
| Click | >=8.1 | Locked |
| Pydantic | >=2.0 | Locked (latest: 2.13.3) |
| openpyxl | >=3.1 | Locked (latest: 3.1.5) — already handles XLSX |
| requests | >=2.31 | Locked |
| Rich | >=13.0 | Locked |
| PyYAML | >=6.0 | Locked |

## New Dependencies

### MCP Server SDK

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `mcp` | >=1.27 | Expose jiramator as an MCP tool server | Official MCP Python SDK (by Anthropic/ModelContextProtocol). Provides `FastMCP` class for declarative tool registration with type hints. Built on Pydantic for schema generation — aligns with existing config models. Supports stdio and SSE transports. | HIGH |

**Rationale:** The `mcp` package is the canonical Python SDK for the Model Context Protocol. It uses Pydantic v2 models natively for tool input/output schemas, which means jiramator's existing Pydantic config models can be reused directly as MCP tool parameters. The `FastMCP` API lets you decorate functions as tools with minimal boilerplate.

**What NOT to use:**
- Don't hand-roll JSON-RPC — the SDK handles protocol framing, capability negotiation, and transport
- Don't use `mcp` <1.0 — pre-1.0 was unstable with breaking API changes
- Don't use `httpx` or `websockets` directly for MCP transport — the SDK abstracts this

**Key dependency note:** `mcp` pulls in `httpx`, `anyio`, `starlette`, and `uvicorn`. This adds async infrastructure. For the MCP server entrypoint, you'll need an async wrapper, but the existing sync Click CLI remains untouched.

### Spreadsheet Import (Hardening)

No new libraries needed. The existing `spreadsheet.py` already handles CSV (stdlib `csv`) and XLSX (`openpyxl`). Hardening is code-level work:

| Concern | Approach | Library |
|---------|----------|---------|
| CSV encoding detection | Use `chardet` only if users report encoding issues; UTF-8 default is correct for 95%+ of cases | None for now |
| Large file streaming | openpyxl `read_only=True` already used — correct | openpyxl (existing) |
| Data validation | Pydantic models for row validation | Pydantic (existing) |
| Header fuzzy matching | stdlib `difflib.get_close_matches` | None (stdlib) |

**What NOT to use:**
- `pandas` — massive dependency for what's essentially dict-of-strings reading. openpyxl + csv module is sufficient and already implemented. Pandas would add ~50MB to the install for no benefit.
- `xlrd` — only reads legacy `.xls` format; jiramator correctly rejects `.xls` and requires `.xlsx`
- `polars` — same rationale as pandas; overkill for row-by-row dict extraction

### Template Inheritance

No new libraries needed. This is a pattern built on existing Pydantic models and PyYAML.

| Pattern | Implementation | Library |
|---------|---------------|---------|
| Config merging (base → team override) | Deep dict merge before Pydantic validation | None (stdlib) |
| YAML `!include` or `extends` field | Custom YAML loading with `extends: base.yaml` key | PyYAML (existing) |
| Template variable resolution | Already implemented (`_TEMPLATE_VAR_RE` in config.py) | None (existing) |
| Schema validation of merged config | Pydantic `model_validate()` on merged dict | Pydantic (existing) |

**Recommended pattern:** Add an `extends` field to TeamConfig YAML files. At load time, recursively load and deep-merge base configs before Pydantic validation. This is simpler and more debuggable than YAML tags or Jinja templating.

**What NOT to use:**
- Jinja2 for template inheritance — wrong abstraction. Jinja is for string templating; this is config/data inheritance. Mixing Jinja into YAML creates parsing nightmares and makes validation impossible until post-render.
- YAML anchors/aliases (`&`/`*`) — these are document-scoped, not cross-file. Useless for base-config inheritance.
- `jsonmerge` or `deepmerge` packages — a 15-line recursive dict merge function is sufficient; no need for a dependency.
- OmegaConf / Hydra — powerful but extremely heavyweight for this use case. Designed for ML experiment configs, not CLI tool configuration.

## Supporting Libraries (Optional, Low Priority)

| Library | Version | Purpose | When to Add | Confidence |
|---------|---------|---------|-------------|------------|
| `chardet` | >=5.2 | CSV encoding detection | Only if users report non-UTF-8 CSVs | LOW — probably never needed |
| `pytest-asyncio` | >=0.25 | Async test support for MCP server tests | When writing MCP server tests | HIGH |

## Installation

```bash
# New dependency for MCP feature
pip install "mcp>=1.27"

# Dev dependency for MCP tests
pip install "pytest-asyncio>=0.25"
```

Add to `pyproject.toml`:
```toml
dependencies = [
    # ... existing ...
    "mcp>=1.27",
]

[project.optional-dependencies]
dev = [
    # ... existing ...
    "pytest-asyncio>=0.25",
]
```

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| MCP SDK | `mcp` (official) | Hand-rolled JSON-RPC | Protocol is complex (capabilities, transports, streaming); official SDK is well-maintained |
| Spreadsheet | openpyxl + csv (existing) | pandas | 50MB dependency for dict extraction that's already implemented in 88 lines |
| Config inheritance | Custom `extends` + deep merge | Hydra/OmegaConf | ML-focused, massive learning curve, fights with Pydantic validation |
| Config inheritance | Custom `extends` + deep merge | Jinja2 YAML templates | Breaks YAML validation, debugging nightmare, wrong abstraction level |
| Config inheritance | Custom `extends` + deep merge | `jsonmerge` | 15 lines of stdlib code vs. a dependency with its own schema language |

## Architecture Impact

- **MCP server** is a new entrypoint alongside the Click CLI. It should be a separate module (`jiramator/mcp_server.py`) that imports the same core functions (planner, importer, jira_client). The MCP server runs async; core logic stays sync and is called via `anyio.to_thread.run_sync()` if needed.
- **Template inheritance** modifies `config.py` load path only. Add deep merge before `TeamConfig(**raw)`. No structural changes to the models themselves.
- **Spreadsheet hardening** is contained within `spreadsheet.py` and `importer.py`. No new modules needed.

## Sources

- MCP Python SDK: `pip index versions mcp` — latest 1.27.0 (verified 2026-04-27)
- openpyxl: `pip index versions openpyxl` — latest 3.1.5 (verified 2026-04-27)
- Pydantic: `pip index versions pydantic` — latest 2.13.3 (verified 2026-04-27)
- Existing codebase: `pyproject.toml`, `jiramator/spreadsheet.py`, `jiramator/config.py`
