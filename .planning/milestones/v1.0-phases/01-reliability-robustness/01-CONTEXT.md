# Phase 1: Reliability & Robustness — Context

**Gathered:** 2026-04-28
**Status:** Ready for planning
**Mode:** Exploratory — interactive (one question at a time); typed claims preserve uncertainty for downstream researcher/planner

<domain>
## Phase Boundary

Make Jiramator's bulk operations trustworthy:

1. **FOUND-01** — Validation errors point at the file, line, and field with actionable text (and did-you-mean suggestions for known-set typos).
2. **FOUND-02** — Every plan/import run produces a structured execution report on disk.
3. **FOUND-03** — A failed bulk run can be resumed from the report without recreating already-created issues.
4. **IMPT-01** — CSV imports from Windows Excel (cp1252, UTF-8-BOM, UTF-16) work without manual encoding conversion.

**In scope:** error message format, YAML line-position capture, run-report artifact + schema, resume CLI surface, encoding fallback for CSV.

**Explicitly out of scope (route to other phases):**
- Duplicate detection / pre-flight Jira queries (deferred per README; not the same as resume)
- Rollback / bulk-delete (FOUND-04, v2)
- `--yes` non-interactive `plan` (FOUND-05 v2; INTG-02 in Phase 3 covers MCP non-interactive)
- Template inheritance error messaging (Phase 2 territory)
- MCP-shaped JSON return envelope (Phase 3 builds on the report schema landed here)

</domain>

<working_model>
## Working Model & Assumptions

### Validation error format (FOUND-01)

**Current state:** `jiramator/config.py` raises bare `ValueError` and Pydantic `ValidationError`; `cli.py:107`/`cli.py:189` catches both and prints `[red bold]Error type:[/] {exc}` then `sys.exit(1)`. Field name is sometimes present in the message; line number never is. Same code path serves both `plan` and `import`.

- [decided:reasoned] Target shape is plain text: `<relative-file>:<line>: <field-path> — <reason>`. Plain text (not Rich panel) keeps the format pipeable, easy to grep, and matches the project's `Console(stderr=True)` convention of stdout-clean output.
- [decided:reasoned] Did-you-mean suggestions are emitted for fields drawn from known sets — template variables (`KNOWN_TEMPLATE_VARS`), org `custom_fields` aliases, and epic refs (`get_epic_keys()`) — using `difflib.get_close_matches` from stdlib (no new dependency).
- [decided:reasoned] Validation fails fast on the first error rather than aggregating. Matches the existing single-`sys.exit(1)` flow, keeps the Pydantic-error-to-line-number mapping logic simpler, and mirrors how compilers most users know (Python, mypy) report on a single failure when piped from a config loader.
- [evidenced:cited] Cross-walking Pydantic 2 errors back to YAML positions requires `loc` tuples (already part of `ValidationError`) plus a YAML loader that retains line/column on every node — pyyaml's default `SafeLoader` discards them. See `jiramator/config.py:159` (`yaml.safe_load`) and `jiramator/config.py:380`.

### Execution report (FOUND-02)

**Current state:** `run_plan()` and the importer print results inline via Rich; nothing is persisted. Running the tool twice creates duplicates and there is no record of which keys were created when (CONCERNS.md §"No Rollback on Partial Bulk Creation Failure").

- [decided:reasoned] The run report is **always written**, never opt-in. It's the substrate for FOUND-03 (resume reads it) and Phase 3 (MCP returns structured results); making it opt-in would force a parallel state mechanism for resume.
- [decided:reasoned] Default location is `.jiramator/runs/<UTC-timestamp>-<team-slug>.json`, gitignored. `--report <path>` overrides. Keeps repo root clean while still being discoverable next to the project. Slug = the team config filename stem.
- [decided:reasoned] Format is JSON with a versioned envelope: `{"schema_version": 1, "run": {...}}`. JSON because Phase 3 MCP needs structured machine-readable output and we want one canonical artifact. Versioning protects future schema evolution.
- [decided:reasoned] Report contents: run metadata (PI label, version strings, team, org config path, command invocation, start/end timestamps), per-issue results (template-key → `{status, jira_key | error}`), aggregate counts (created/skipped/errored), overall status enum (`success | partial | failed`), and the resolved-config hash (per resume strict-drift check, see below). Excludes credentials and full Jira payloads.
- [decided:reasoned] Human-readable summary continues to render on stderr at end-of-run (Rich table). Disk artifact is for tooling and resume; humans get the same UX they have today.

### Resume mechanism (FOUND-03)

**Current state:** No state file. A mid-batch failure leaves orphan epics and an unknown number of created tickets; user must manually reconcile in Jira (CONCERNS.md).

- [decided:reasoned] CLI surface: `--resume` (no value) auto-finds the most recent `partial`/`failed` run for the same team config in `.jiramator/runs/` and continues it. `--resume <path>` is the explicit override. No interactive "do you want to resume?" prompt — we want this to work with the (Phase 3) non-interactive MCP path too.
- [decided:reasoned] Resume covers epics + tickets uniformly. Per-issue results in the report carry the template-key → Jira-key map for both. Resume = "skip every template-key already in `created`, retry everything else." Unifies the model and lets us recover from epic-phase failures without forcing the user to hand-edit YAML to populate `existing_epics`.
- [decided:reasoned] Strict config-drift check: the resolved (post-merge, post-template-resolution) config is hashed and stored in the report. On resume, if the current hash differs, abort with a clear error pointing at what changed; require `--resume --force` to override. Prevents silent partial-state corruption from edits between runs.
- [decided:reasoned] The run report is the **only** state — no separate lockfile. Concurrent-run protection is deferred (single-user PO tool today; concurrency belongs in a later concurrency-hardening phase if it ever matters). Persist-on-error (write the report immediately whenever an exception bubbles up) is mandatory so the report always reflects reality.

### CSV encoding (IMPT-01)

**Current state:** `jiramator/spreadsheet.py:_read_csv` is hardcoded to `encoding="utf-8"`. Any non-ASCII byte from Windows Excel (smart quotes, em-dash, `£`, `°`, `™`, curly apostrophes in names like `O'Brien`) raises `UnicodeDecodeError` with no actionable message. xlsx path is binary via openpyxl and unaffected.

**Audience reality:** This is not a non-English-language issue. Windows Excel autocorrect produces non-ASCII bytes inside ordinary English content the moment a user types `"`, `'`, `--`, or any currency/degree symbol. PowerShell exports default to UTF-16-LE (older) or UTF-8-with-BOM (newer). The "broader audience uses Windows/Excel" motivation in REQUIREMENTS.md targets exactly these cases.

- [decided:reasoned] Read pipeline: BOM detection first (handles UTF-8-SIG, UTF-16-LE, UTF-16-BE) → try UTF-8 → on `UnicodeDecodeError`, run an encoding-detection library and use the top match.
- [decided:reasoned] When a non-UTF-8 encoding is used, emit a one-line stderr announcement: `Read <relative-path> as <encoding>`. Silent autodetect would hide a non-trivial assumption from the user; FOUND-01's spirit ("actionable") argues for visibility.
- [decided:reasoned] `--encoding <name>` flag overrides detection entirely. Power-user escape hatch for files where detection is wrong.
- [decided:reasoned] xlsx errors surface as-is via the FOUND-01 error format. Don't second-guess openpyxl.

### Claude's Discretion

- Exact wording of error messages and the announcement banner.
- Module placement of new helpers (likely `jiramator/run_report.py` for the report dataclass + IO, `jiramator/encoding.py` or extension of `jiramator/spreadsheet.py` for the read pipeline).
- How aggressively to refactor `run_plan()`'s double-`build_all()` (CONCERNS.md) while landing the report — tactical decision for the planner.
- Whether to fold the existing inline Rich results table into a function that consumes the report dataclass, or keep them parallel for now.
- Test fixture organization for new YAML-error-path tests.
- Whether to populate `tests/fixtures/` (currently empty per CONCERNS.md) as part of FOUND-01 fixture data, or keep inline.

</working_model>

<constraints>
## Derived Constraints

- **DC-1:** [evidenced:cited] All user-facing output must go to `Console(stderr=True)`; stdout stays clean for piping. Source: `.planning/codebase/CONVENTIONS.md` §CLI Patterns; the import flow already follows this.
- **DC-2:** [evidenced:cited] Credentials never appear in any persisted artifact. The run report excludes `JIRA_EMAIL`/`JIRA_TOKEN` values and any header/auth metadata. Source: `PROJECT.md` §Constraints, `.planning/codebase/CONCERNS.md` §Security.
- **DC-3:** [evidenced:cited] Phase 3 (MCP) consumes whatever schema we land here. Schema must be machine-readable and versioned from day one. Source: ROADMAP.md §Phase 3 dependency on Phase 1.
- **DC-4:** [evidenced:cited] FOUND-03 success criterion specifies "only the uncreated issues are attempted" — resume must skip created keys, not retry them. Source: ROADMAP.md §Phase 1 Success Criterion 3.
- **DC-5:** [evidenced:reasoned] The validation-error path serves both `plan` (`cli.py:107`) and `import` (`cli.py:189`) — landing FOUND-01 in `config.py` and the YAML loader is automatically picked up by both subcommands. Source: grep of `(ValueError|FileNotFoundError|click.BadParameter)` handlers.
- **DC-6:** [decided:reasoned] No new runtime dependency may be added without justifying its weight. Encoding-detection library is the only candidate from this phase; YAML loader choice may add ruamel.yaml. Both must be evaluated by the researcher.
- **DC-7:** [evidenced:cited] Existing `recurring_epics` / `existing_epics` distinction must continue to work unchanged after resume lands. Source: `ISSUES.md` §#2 resolution; `jiramator/config.py:get_epic_keys()`.

</constraints>

<guardrails>
## Epistemic Guardrails

- **G-1:** [governing] Resume is **not** duplicate detection. Resume reads a known prior run's report. Querying Jira to see if an issue exists is a separate (deferred) feature and must not creep into Phase 1. Any planner task that says "check Jira for existing issue" without "from this run's report" is out of scope.
- **G-2:** [governing] No interactive prompts in the resume or report code paths. Phase 3 MCP will be non-interactive; we don't want to relitigate this when Phase 3 lands. Interactive prompts in `run_plan()`'s pre-build flow (PI number, version) remain unchanged for now.
- **G-3:** [governing] The report schema is **the** contract. Once shipped at `schema_version: 1`, breaking changes require `schema_version: 2` and a documented migration. No "we'll fix the field name later."
- **G-4:** [governing] Persist-on-error is mandatory. The report file must reflect the most recent reality after any exception in the create path. A run that crashed without writing a report is a bug, not "the user must rerun."
- **G-5:** [reasoned] Prefer stdlib over new deps. `difflib` over `rapidfuzz`. Custom `SafeLoader` is acceptable if it's <50 LoC; otherwise prefer ruamel.yaml. charset-normalizer or chardet for encoding (verify if already transitive via `requests`).
- **G-6:** [governing] FOUND-01 success is measured by error legibility, not error throughput. Tests must assert on the rendered string format, not just on which exception type was raised.

</guardrails>

<questions>
## Open Questions

### Q1: YAML line-position capture — ruamel.yaml vs custom pyyaml SafeLoader

**Research program:**
1. Prototype both approaches against the existing `org.yaml`/`team.yaml` shapes:
   - Approach A: drop-in `ruamel.yaml.YAML(typ='safe')` replacing `yaml.safe_load` in `config.py:159` and `:380`. Measure: how do Pydantic `loc` tuples translate to ruamel position info? Does it round-trip the existing test corpus byte-identically?
   - Approach B: subclass `yaml.SafeLoader`, override `construct_mapping` / `construct_sequence` to attach `__line__`/`__column__` to dict/list nodes. Measure: LoC, type-stability across pydantic validation, performance on the 200+ existing test cases.
2. For each, write a Pydantic-loc → line-number resolver. Test against representative errors: missing required key, type mismatch, list element invalid, nested dict invalid.
3. Compare: install size delta, maintenance footprint, error-quality difference for fields buried deep in lists (e.g., `tickets[3].fields.story_points`).

**Downstream decisions affected:** Whether the planner adds a dependency (`ruamel.yaml`, ~1MB) or owns ~30-50 LoC of loader code; how the FOUND-01 implementation tasks split.

**Reversibility:** MEDIUM. The error-format CONTRACT (DC-6, G-6) is stable either way — internal swap is feasible later but not free, since tests assert on format and the loader choice ripples into how the resolver is structured.

### Q2: Encoding-detection library — charset-normalizer vs chardet

**Research program:**
1. Check whether `charset-normalizer` or `chardet` is already a transitive dep via `requests>=2.31` (likely `charset-normalizer`). If yes, no install cost.
2. Build a small test corpus: actual Excel-on-Windows CSV exports with curly quotes, em-dash, `£`, `°`; PowerShell `Out-File` UTF-16-LE outputs; LibreOffice cp1252 exports; an intentionally-malformed file. Run both libraries; compare top-match accuracy and confidence scores.
3. Verify license compatibility (project has no declared license stance — confirm this is OK to add).

**Downstream decisions affected:** Single dep added (or zero, if transitive). Detection-quality tradeoff might not matter in practice for the Western-Excel corpus this phase targets.

**Reversibility:** HIGH. Library is encapsulated behind `_read_csv`. Swap is a few lines.

### Q3: Resume scoping — what counts as "the same team config" for `--resume` auto-discovery?

**Research program:**
1. Survey: when the user runs `jiramator plan --org-config X --team-config Y --resume`, do we match against the team config path (Y), the team-config filename stem, the team `name` field inside the YAML, or the resolved-config hash?
2. Edge cases: same team across two PIs (PI label changes but team config is the same file); team config moved between directories; team renamed in YAML.
3. Recommend the heuristic that minimizes "I expected to resume X and got Y" surprises.

**Downstream decisions affected:** Auto-discovery rule in the resume CLI; what error users see when no candidate found.

**Reversibility:** MEDIUM. The matching rule shapes user mental model; changing it later is a UX regression.

### Q4: Where to draw the "did-you-mean" suggestion budget

**Research program:**
1. Identify every known-set field at validation time: `KNOWN_TEMPLATE_VARS` (`config.py`), `org_config.custom_fields` keys, epic ref keys (`get_epic_keys()`), maybe team `bulk_create.field_aliases` keys.
2. For each, decide the `difflib.get_close_matches(cutoff=...)` threshold and `n=` cap that produces useful suggestions without noise. Calibrate against typos seen in tests + plausible user errors.
3. Decide error-message phrasing: `(did you mean 'X'?)` vs `(closest matches: X, Y)`.

**Downstream decisions affected:** FOUND-01 message-format polish; test assertions on suggestion strings.

**Reversibility:** HIGH. Pure presentation tweak.

</questions>

<dependencies>
## Claim Dependencies

| Claim | Depends On | Vulnerability |
|-------|------------|---------------|
| Strict config-drift check (resume) | A stable, deterministic resolved-config hash | MEDIUM — if the hash includes ordering-sensitive fields (dict ordering, regex group order), benign re-saves invalidate resume. Researcher must validate hash inputs. |
| Resume covers epics uniformly | Report's per-issue results includes epic template-keys with their Jira-key mappings, persisted before tickets phase begins | LOW — already a deliberate decision; planner just needs to ensure epic-creation step writes to the report incrementally, not at end-of-run. |
| FOUND-01 line numbers | Q1 outcome (loader choice) | MEDIUM — the format contract is stable, but loader choice constrains implementation cost. |
| Encoding announcement on stderr | DC-1 (stderr-only output) holds across the import flow | LOW — the import path already uses `Console(stderr=True)`. |
| `.jiramator/runs/` default | User has write access to the working directory | LOW — tool already writes to CWD via dry-run flow; if `.jiramator/` cannot be created, fall back to a clear FOUND-01-style error ("could not create .jiramator/runs: <reason>"). |

</dependencies>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/ROADMAP.md` §Phase 1 — phase goal, dependencies, success criteria
- `.planning/REQUIREMENTS.md` §Foundation — FOUND-01, FOUND-02, FOUND-03 specifications and motivation
- `.planning/REQUIREMENTS.md` §Spreadsheet Import — IMPT-01 specification

### Codebase context
- `.planning/codebase/STRUCTURE.md` — module layout, where new code goes
- `.planning/codebase/CONVENTIONS.md` — naming, error-handling, Pydantic, CLI, logging patterns (especially §"Error Handling" and §"CLI Patterns" — directly govern FOUND-01 implementation)
- `.planning/codebase/CONCERNS.md` §"No Rollback on Partial Bulk Creation Failure" — the failure mode FOUND-03 addresses
- `.planning/codebase/CONCERNS.md` §"Planner Interactive Flow with `sys.exit(1)` Calls" — established error-exit pattern; FOUND-01 must respect it
- `.planning/codebase/CONCERNS.md` §"Empty `tests/fixtures/`" — opportunity to populate with FOUND-01 fixtures

### Existing source for FOUND-01
- `jiramator/config.py:159` — `load_org_config` YAML entry point
- `jiramator/config.py:380` — `load_team_config` YAML entry point
- `jiramator/config.py` — all `raise ValueError` and Pydantic validators (22 sites surveyed during discussion)
- `jiramator/cli.py:107`, `:113`, `:189`, `:195`, `:205`, `:231` — all CLI error-catch sites that render to user

### Existing source for FOUND-02 / FOUND-03
- `jiramator/planner.py:run_plan()` — orchestration, end-of-run results display, the natural seam for report persistence
- `jiramator/planner.py:_create_epics()` — epic-phase creation; needs to write report incrementally before tickets phase
- `jiramator/jira_client.py:create_issues_bulk()` — partial-batch failure semantics (CONCERNS.md describes the un-rolled-back state)
- `jiramator/importer.py` — second consumer of FOUND-02 (import runs need the same report shape)

### Existing source for IMPT-01
- `jiramator/spreadsheet.py:_read_csv` (line 21) — hardcoded `encoding="utf-8"`; the single change site
- `jiramator/spreadsheet.py:87-88` — existing encoding-related `ValueError`s for unsupported file types; FOUND-01 format applies here too

### Project context
- `PROJECT.md` §Constraints — credentials/env-var rule (DC-2)
- `PROJECT.md` §Out of Scope — duplicate detection; reinforces G-1
- `ISSUES.md` §#2 — `existing_epics` design; resume must coexist (DC-7)
- `README.md` §Future enhancements — duplicate detection deferral (G-1 source)

### Conventions
- `pyproject.toml` — current dependency set; new deps must be justified against DC-6
- All source files use `from __future__ import annotations`; FOUND-01 helpers continue this

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`Console(stderr=True)` pattern** (`planner.py`, `importer.py`, `cli.py`) — the only legal channel for user-facing output from FOUND-01 errors and FOUND-02 summaries. New code uses it directly.
- **`JiraApiError`** (`jiramator/jira_client.py`) — established domain-exception pattern. FOUND-01 may want a sibling `ConfigValidationError` that wraps Pydantic + position info, keeping `cli.py` catch lists tidy.
- **Pydantic `loc` tuples** — already produced for every validation failure; the cross-walk to YAML lines is the only missing piece.
- **`difflib.get_close_matches`** — stdlib; covers all did-you-mean cases without a new dep.
- **`urllib3 Retry` strategy** (`jira_client.py`) — already handles transient failures; the report's `failed` status reflects post-retry reality, not transient blips.

### Established Patterns
- **Pydantic-first validation** — all rule changes go through `@field_validator` / `@model_validator`; FOUND-01 line-mapping happens at the YAML-loader boundary, not inside validators.
- **Snake_case modules, mirrored test files** — new modules (`run_report.py`, possibly `encoding.py`) follow `tests/test_run_report.py`, `tests/test_encoding.py`.
- **Click `--option` with `path_type=Path`** — `--report` and `--resume` follow this convention.
- **Stderr Rich + sys.exit(1)** — FOUND-01 errors render via Rich on stderr then exit 1; matches `cli.py:107` and `:189`.

### Integration Points
- **YAML loader replacement** sits at `config.py:159` and `:380`; one change site each subcommand.
- **Report writes** happen at three places in `run_plan()`: after epic creation succeeds, after each bulk batch, and at the end-of-run summary. Importer has parallel sites.
- **`--resume` parsing** happens in `cli.py` `plan` and `import` commands (both need it). Resolution to a report path lives in `run_report.py`.
- **Encoding detection** sits inside `spreadsheet.py:_read_csv`; signature unchanged; new `--encoding` Click option in `cli.py` for the `import` subcommand.

</code_context>

<specifics>
## Specific Ideas

- The user explicitly wanted clarification on whether IMPT-01 was a non-English-charset feature. It is not — it's a Windows-vs-elsewhere issue affecting English Excel users via smart-quote autocorrect, em-dash autocorrect, `£`/`°`/`™`, curly apostrophes (`O'Brien`), bullet points pasted from PowerPoint, and PowerShell `Out-File` UTF-16-LE exports. The implementation must read like it solves *that* problem, not like an i18n feature.
- The error format `<file>:<line>: <field> — <reason>` mirrors compiler conventions (Python tracebacks, mypy, gcc) and is intentionally pipeable; do not Rich-decorate it.
- "Resume covers epics" matters because today's failure mode is mid-batch; without epic resume, users have to manually copy `CA-XXXXX` keys into `existing_epics` to retry, which defeats the FOUND-03 user value.

</specifics>

<deferred>
## Deferred Ideas

- **Concurrency / lockfile for run reports** — single-PO tool today; revisit if multi-user concurrent runs of the same team config become a real scenario.
- **Report retention policy** (rotate/delete old `.jiramator/runs/` files) — out of FOUND-02 scope; can be a v2 housekeeping task.
- **Aggregate validation errors in a single pass** — explicitly deferred (chose fail-fast); revisit if user feedback shows multi-error files are common.
- **Rich panel error rendering with code excerpt** — deferred in favor of plain-text format; revisit if user feedback wants more polish.
- **Defensive xlsx encoding fallback** — deferred; openpyxl is binary-safe in practice. If real-world reports surface issues, add then.
- **Duplicate detection / pre-flight Jira queries** — already deferred per README; resume is not a substitute for this.
- **Hash-strict resume (any config change blocks resume)** — chose strict-with-`--force` over hash-strict; revisit if drift bugs appear.
- **`--yes` for `plan` non-interactive** — FOUND-05 (v2); INTG-02 covers MCP non-interactive in Phase 3.
- **MCP-shaped JSON envelope for the report** — Phase 3 builds on `schema_version: 1` landed here.

</deferred>

---

*Phase: 01-reliability-robustness*
*Context gathered: 2026-04-28*
