# Phase 2: Template Inheritance & Sprint Assignment — Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Mode:** Exploratory — interactive (one question per turn). User reframed the phase scope substantially during discussion; this CONTEXT supersedes the original ROADMAP/REQUIREMENTS framing where noted.

<domain>
## Phase Boundary

Two orthogonal concerns:

1. **Template inheritance (TMPL-01).** Eliminate repetitive field declarations across ticket templates. Two layers, both using the same merge rules:
   - **Org layer (locked, cross-team):** Optional `default_fields:` block on org config. Locked org-wide; teams cannot override.
   - **Team layer (per-team baseline):** Optional `defaults:` block on team config. Templates within that team config inherit from it. Each team owns its own; no cross-team coupling.

2. **Sprint assignment (ISSUE-01).** Make the sprints-exist/sprints-don't-exist decision non-interactive and config/flag-driven, so created tickets land in (or skip) sprints predictably without a TTY-bound prompt.

**In scope:**
- New `default_fields:` top-level key on `OrgConfig`.
- New `defaults:` top-level key on `TeamConfig`.
- Layered merge engine: org → team-defaults → per-template `fields`.
- Plain-text stderr conflict warnings (Phase 1 format) when a later layer writes a key an earlier layer locked.
- New `sprints_exist: true|false` field on `TeamConfig`.
- New `--sprints-exist` / `--no-sprints-exist` CLI flags on `plan` (and `import` if relevant).
- Non-TTY behavior: error if neither config nor flag is set and stdin is not a TTY.

**Explicitly out of scope (route to other phases or deferred):**
- **TMPL-02 SC3 (resolved-config CLI command) — DESCOPED.** Original ROADMAP success criterion 3 ("User can run a CLI command to see the fully resolved config after inheritance merging") is removed from Phase 2. User repeatedly indicated they don't see the value: with team-internal defaults, the team config is one file the user reads top-to-bottom; org→team locks are made visible by Q1.5 conflict warnings at load time. **Requires REQUIREMENTS.md / ROADMAP.md edit before phase verification — see Open Questions.**
- **TMPL-02 reinterpretation.** Original wording: "User can selectively override any inherited field in team config." Reinterpreted as **"team chooses which gaps to fill via its own `defaults:` block and per-template `fields`."** Selectivity is about which gaps team fills, not about overriding org. Same REQUIREMENTS.md/ROADMAP.md edit as TMPL-02 SC3.
- Recurring-epics sprint assignment — by design, epics live outside sprints.
- Literal `sprint:` override on individual templates — user accepts the existing `sprint_group` + `release_sprint_map` indirection.
- Per-PI sprint name template variation — single global pattern per team is fine.
- Promoting "unresolved sprint" warnings to errors — current warning behavior is acceptable.
- Any escape hatch / unset sentinel for inherited values — locked is locked at every layer.
- MCP integration of any of this (Phase 3).
- Resolved-config command in any form — fully descoped.

</domain>

<working_model>
## Working Model & Assumptions

### Mental model — "locked layers, gap-filling tail"

The user explicitly rejected the "inheritance with overrides" framing. The actual model is:

> Org config locks org-wide policy. Team config locks per-team baseline. Templates fill in the rest. Earlier layers always win against later layers writing the same key — later writes are warned and dropped. Disjoint keys flow through. Lists across layers concat with deduplication.

This means there is **no precedence resolver to design**. Earlier layer = locked owner; later layer's same-key writes are inert (and warned). Q2's merge rules apply to disjoint cases only.

### Layer 1 — Org `default_fields:` (locked org-wide)

**Current state:** Org config has `bulk_create.{field_aliases,field_types,defaults}` only. There is no general-purpose "every ticket gets these fields" mechanism today. Team configs repeat fields like `priority: Medium`, `customfield_10273: [{value: "No"}]`, `customfield_10026: 0.5`, `customfield_10014: "$epic:misc"` across every per_release_template (~6 templates × ~4 fields = ~25 lines of duplication in calcs.yaml alone).

- [decided:reasoned] Add a new top-level `default_fields:` block on `OrgConfig` (Pydantic model + YAML root key). Mirrors the disjoint top-level layout of `bulk_create:` and `sprints:` rather than nesting under `bulk_create`. Top-level placement matches the parallel `defaults:` on `TeamConfig`.
- [decided:reasoned] If the org sets `default_fields.priority: Medium`, every ticket and epic created from any team config in the org gets `priority: Medium` in its `fields` payload at build time.
- [decided:reasoned] Org-locked keys are immutable from the team side. If a team config sets a same-name key (in team `defaults:` or in a per-template `fields:`), the team value is **dropped** and a stderr warning is emitted at config-load time (see Q1.5 below).
- [decided:reasoned] Type: `dict[str, Any]` mirroring the `fields:` shape on templates. Default `{}` (empty = no org-wide defaults). Backward compatible — existing org configs without this key behave identically to today.

### Layer 2 — Team `defaults:` (per-team baseline)

**Current state:** No team-internal defaults mechanism. Each ticket template repeats values verbatim.

- [decided:reasoned] Add a new top-level `defaults:` block on `TeamConfig`. Sibling of `recurring_epics:`, `per_release_tickets:`, `per_sprint_tickets:`. Top-level keeps depth flat and discoverable.
- [decided:reasoned] Team `defaults:` values are merged into every ticket and epic template's `fields` for that team's templates only. No cross-team visibility.
- [decided:reasoned] Team-defaults-locked keys are immutable from per-template `fields:`. If a template tries to set a same-name key, the template value is dropped and a stderr warning is emitted (intra-file Q1.5 warning shape).
- [decided:reasoned] Type: `{ fields: dict[str, Any] }` (a sub-model with a `fields` member, parallel to ticket/epic template shape). Default `{}` (empty fields). Keeps room to add other future template-shared defaults (e.g. `defaults.summary_prefix` if ever needed) without restructuring.

### Merge order and rules

[decided:reasoned] **Order:** `org.default_fields` → `team.defaults.fields` → per-template `fields`. Each layer locks its keys against later writes.

[decided:reasoned] **Dicts (Q2a):** Deep-merge. Disjoint keys from later layers merge in. Same-name keys: earlier wins, later dropped, Q1.5 warning emitted. Recurses into nested dicts (e.g. structured custom fields).

[decided:reasoned] **Lists (Q2b):** Concat with dedup. Final list = `earlier_layer_list + later_layer_list`, order-preserving (earlier first), deduplicated. Dedup key is **deep equality via JSON-canonical form**: `json.dumps(item, sort_keys=True, separators=(',',':'))` per item; first occurrence wins. This handles primitives (`"audit"`), structured items (`{value: "No"}`), and nested structures uniformly.

> **Multi-select-conflict caveat (flagged for Phase 2 tests, possibly Phase 3 revisit):** When org sets `customfield_X: [{value: "No"}]` and team sets `customfield_X: [{value: "Yes"}]`, the merge result is `[{value: "No"}, {value: "Yes"}]` (concat, no dedup hit). Jira may or may not accept both values for a single-select field. Test against real Jira behavior; if this proves to be a footgun, revisit by special-casing list-typed fields known to be single-select via `org.bulk_create.field_types`. For Phase 2 we accept the concat behavior as documented.

[decided:reasoned] **Scalars:** Earlier wins. Same-key warning fires.

[decided:reasoned] **No escape hatch (Q2c).** No `~unset` sentinel, no `team_overridable: true` flag, no per-key opt-out. Org-locked means locked. If a real exception emerges, the org config gets restructured (move the field out of `default_fields`).

### Conflict warning format (Q1.5)

[decided:reasoned] When a layer attempts to write a key locked by an earlier layer, emit a plain-text stderr warning at config-load time. **Org-vs-team:**
```
<team-file>:<line>: <field> — locked by org config (<org-file>:<line>); team value ignored.
```
**Team-defaults-vs-template (intra-file):**
```
<team-file>:<template-line>: <field> — locked by team defaults (<team-file>:<defaults-line>); template value ignored.
```

- Plain text. No Rich markup. Pipeable. Matches Phase 1 error format precedent.
- Warnings, not errors. Config still loads. Team value is dropped.
- Reuses Phase 1 line-aware loader (`yaml_loader.safe_load_with_lines` + `resolve_line`). Both org and team configs already load through this — no new loader work needed.
- Channel: stderr via `Console(stderr=True)` (DC-1 from Phase 1 carries over).

### Sprint assignment (ISSUE-01)

**Current state:** `_resolve_sprint_ids()` (`planner.py:247`) runs unconditionally on live runs, gated only by `team_config.board_id is not None`. Before that, `_prompt_sprints_exist()` (`planner.py:99`) blocks on a Rich `Confirm.ask("Are the sprints for this PI already created in Jira?")`. If the user answers "no", the planner skips sprint resolution but still ran the prompt.

**Phase 2 change:**

- [decided:reasoned] Add `sprints_exist: bool | None` to `TeamConfig` with default `None` (preserves the current "ask interactively" behavior for existing configs).
- [decided:reasoned] Add `--sprints-exist` / `--no-sprints-exist` Click flags to the `plan` command (and `import` if it touches sprint resolution — verify in research). CLI flag overrides config.
- [decided:reasoned] Resolution at runtime, in priority order:
  1. CLI flag if set → use flag value.
  2. Else `team_config.sprints_exist` if not `None` → use config value.
  3. Else if stdin is a TTY → existing interactive prompt (`_prompt_sprints_exist`).
  4. Else (non-TTY, no flag, no config) → error with `ConfigValidationError`-styled message: `Cannot determine whether sprints exist: stdin is not a TTY and neither --sprints-exist/--no-sprints-exist nor 'sprints_exist:' in team config is set.`
- [decided:reasoned] When the resolved value is `False`: skip `_resolve_sprint_ids()` entirely. No `client.get_board_sprints()` API call. All tickets created without the sprint custom field. No "unresolved sprint" warnings (since no resolution was attempted). The existing post-resolution `pop("_sprint_num", None)` cleanup still runs so the annotation doesn't leak into Jira payloads.
- [decided:reasoned] When the resolved value is `True`: existing `_resolve_sprint_ids()` behavior unchanged. Yellow warnings for unresolved sprint names remain.
- [decided:reasoned] `team_config.board_id` interaction: if `board_id is None`, `sprints_exist` is irrelevant (no board to query); the existing skip-with-message path handles this. If `board_id is not None` and `sprints_exist == False`, we still skip — having a board configured doesn't override the user's "sprints aren't ready" declaration.

### Claude's Discretion

- Exact warning wording (subject to Phase 1 format, but specific text is the planner's call).
- Module placement of the merge engine — likely a new `jiramator/config_merge.py` or extension of `config.py`. Tactical decision for the planner.
- Whether to model the layered merge as: (a) merge-into-templates at config-load time (templates carry already-merged `fields` after load) or (b) merge-at-build-time in `ticket_builder.py` (templates stay raw, builder applies layers when constructing payloads). (a) is simpler to reason about and aligns with Pydantic-first validation; (b) keeps the original config introspectable. Planner picks based on test-suite ergonomics.
- Whether the `defaults:` Pydantic sub-model is a dedicated class or a `dict[str, Any]` with a structural validator. Class probably wins for parity with `EpicTemplate`/`TicketTemplate`.
- Exact CLI flag names (`--sprints-exist`/`--no-sprints-exist` proposed; `--sprints-ready`/`--no-sprints-ready` could read better; defer to planner).
- TTY detection mechanism (`sys.stdin.isatty()` is the obvious choice; planner verifies it works under existing test fixtures).
- Test fixture organization for layered-merge cases — likely new `tests/fixtures/inheritance/` directory.

</working_model>

<constraints>
## Derived Constraints

- **DC-1 (carried from Phase 1):** All user-facing output goes to `Console(stderr=True)`. Conflict warnings, sprint-mode error message — all stderr. Source: `.planning/codebase/CONVENTIONS.md` §CLI Patterns.
- **DC-2 (carried from Phase 1):** Credentials never appear in any persisted artifact. No new persistence in Phase 2, but if any merge-debug logging is added, exclude env-resolved credentials.
- **DC-3 (carried from Phase 1):** No new runtime dependency without justification. Phase 2 is stdlib-only by intent — `json` (stdlib) for canonical-form dedup, existing `yaml_loader.py` for line capture, no new packages.
- **DC-4 (Phase 2 specific):** Backward compatibility is non-negotiable. Existing `acme.yaml` and `calcs.yaml` (no `default_fields:`, no `defaults:`, no `sprints_exist:`) must load and run identically to today. All new fields default to "absent / preserve current behavior."
- **DC-5 (Phase 2 specific):** The Phase 1 line-aware loader (`yaml_loader.safe_load_with_lines`, `resolve_line`, `strip_line_markers`) is the substrate for conflict-warning line numbers. Both org and team load paths already use it (`config.py:_load_yaml_with_lines`). No new loader work needed.
- **DC-6 (Phase 2 specific):** TTY detection is the *only* runtime branch in the sprint-mode resolution; no other heuristics. Either flag, config, TTY-prompt, or error — no fallbacks like "guess true if board_id is set."
- **DC-7 (Phase 2 specific):** Conflict warnings are warnings, not errors. Config still loads with the earlier-layer winner. Tests must assert on rendered warning string AND on the merged result.
- **DC-8 (Phase 2 specific):** `sprints_exist: false` short-circuits before any Jira API call. Verify no `client.get_board_sprints()` invocation in this path. Critical for offline / sprintless workflows.

</constraints>

<guardrails>
## Epistemic Guardrails

- **G-1 (governing):** No override mechanism. At any layer, locked-by-an-earlier-layer means dropped + warned. If a planner task introduces "team can override org for these specific keys" or "template can override team-defaults for these specific keys," it's out of scope. Q1's reframe is hard-locked.
- **G-2 (governing):** No resolved-config CLI command in Phase 2. If a planner task proposes `jiramator config show`, `jiramator plan --show-resolved`, or any equivalent — reject and refer to this CONTEXT. TMPL-02 SC3 is descoped.
- **G-3 (governing):** Team configs that don't declare `defaults:` and org configs that don't declare `default_fields:` work identically to today. Backward compat is verified by running the existing test suite green (417 tests as of 2026-04-30) without modification — only additions.
- **G-4 (governing):** Sprint resolution is binary. No "partial sprint resolution" mode, no "try and silently skip on failure" mode. Either resolve all eligible tickets and warn on unmatched names (current `True` behavior), or skip resolution entirely for all tickets (`False` behavior). The user explicitly rejected expanding this surface.
- **G-5 (governing):** The Q1.5 warning shape is stable (`<file>:<line>: <field> — locked by …; … value ignored.`). Tests assert on this format. Future phases that add new lock layers reuse the format.
- **G-6 (reasoned):** Prefer config-load-time merging (option (a) under Claude's Discretion) over build-time merging unless research shows it breaks test ergonomics. Loading already-merged templates makes downstream code (ticket_builder, planner) untouched.
- **G-7 (reasoned):** Dedup-by-JSON-canonical-form (Q2b) is correct and stable for the inputs this project actually sees (primitives, dicts of primitives, `[{value: "X"}]` shapes). Don't over-engineer with `frozenset`-of-tuples or recursive hashing — `json.dumps(sort_keys=True)` is enough.

</guardrails>

<questions>
## Open Questions

### Q1: Default value of `sprints_exist` when team config omits it

**Two candidates:**
1. `None` (proposed in working_model) — preserves the interactive-prompt behavior for existing users; requires TTY check; errors in non-TTY contexts when no flag.
2. `False` (fail-safe) — sprintless creation by default; explicit opt-in via config or flag for sprint resolution; no TTY dependency.

**Why it matters:** Affects backward compatibility (existing interactive users) vs. Phase 3 readiness (MCP needs non-interactive defaults). `None` is more conservative; `False` is more Phase-3-friendly but is a behavior change for existing users.

**Research program:**
1. Audit existing user expectation: does anyone (other than the author) currently rely on the prompt? Probably not given audience size, but verify.
2. Check what happens if Phase 3 MCP launches with `sprints_exist: None` and no flag — error message UX must be excellent.
3. Decide: stick with `None` (and require Phase 3 to set the flag explicitly), or flip to `False` (and document the migration in Phase 2 release notes).

**Reversibility:** MEDIUM. Default change is a behavior change for users who relied on the prompt; reversible but with friction.

### Q2: REQUIREMENTS.md and ROADMAP.md need explicit edits before Phase 2 verification

**The reframe affects two documents:**
1. **REQUIREMENTS.md TMPL-02:** Current wording — "User can see the fully resolved/merged config for a team (after inheritance) via a CLI command." Phase 2 no longer ships this. Options:
   - (a) Reword TMPL-02 to drop the CLI clause: "User can see how org and team layers merge via stderr conflict warnings at load time and team-internal `defaults:` block visibility."
   - (b) Move TMPL-02 SC3 to v2 backlog (REQUIREMENTS.md §v2 Requirements).
   - (c) Delete TMPL-02 SC3; keep TMPL-02 SC1+2 (inherit-and-fill-gaps coverage).
2. **ROADMAP.md Phase 2 Success Criteria:**
   - SC2 ("User can selectively override any inherited field in team config") — REWRITE per TMPL-02 reinterpretation: "User can fill in fields not locked by org or team defaults via per-template `fields:`."
   - SC3 ("User can run a CLI command to see the fully resolved config after inheritance merging") — REMOVE.
   - SC4 ("User can specify sprint assignment in config and created tickets land in the correct sprint") — KEEP, but interpret as: sprint-mode is config/flag-driven; existing sprint-resolution machinery is unchanged.

**Recommended:** User edits both docs **before** plan-phase runs, so verification gate has correct truths to check against. Planner agent should not start without these edits in place.

**Reversibility:** HIGH. Documentation edits.

### Q3: Org `default_fields:` placement — top-level vs nested under `bulk_create:`

**Two candidates:**
1. Top-level (proposed): `org.default_fields: { ... }` — sibling of `bulk_create:` and `sprints:`.
2. Nested: `org.bulk_create.default_fields: { ... }` — extends the existing bulk-create defaults block.

**Why it matters:** `bulk_create.defaults` already exists and is applied during the import command's bulk-create flow (`importer.py`). Two `defaults`-shaped concepts under the same `bulk_create` parent could confuse users. Top-level placement separates "fields applied to every issue regardless of source (plan or import)" from "bulk-create-specific defaults."

**Research program:**
1. Check whether the existing `bulk_create.defaults` is already applied during `plan` runs or only during `import`. If `import`-only, then `default_fields` at top-level is the right home (applies to both). If shared, consider whether to consolidate.
2. Verify no naming collision between `default_fields` (org top-level) and `defaults` (team top-level) — they're disjoint at the YAML root, but may confuse documentation.

**Reversibility:** MEDIUM. Public config schema is hard to change after release.

### Q4: Multi-select field merge under concat-dedup — verify against Jira reality

**The caveat from working_model:** `org.default_fields.customfield_X: [{value: "No"}]` + `team.defaults.fields.customfield_X: [{value: "Yes"}]` → merge result `[{value: "No"}, {value: "Yes"}]`. For multi-select fields this is correct; for single-select fields this would be a Jira API rejection (or worse, silent acceptance of one value).

**Research program:**
1. Build a test config that exercises both cases (multi-select and single-select `customfield`).
2. Run against real Jira test instance. Confirm: does Jira reject `[a, b]` for a single-select? What's the error?
3. If real-world behavior surfaces a footgun, special-case using `org.bulk_create.field_types[<field>] in {"single_select", "name_object"}` to switch to "earlier wins, later dropped+warned" instead of concat-dedup. Defer this to Phase 2 task only if tests demand it.

**Reversibility:** HIGH. Pure merge-logic tweak, no schema change.

</questions>

<dependencies>
## Claim Dependencies

| Claim | Depends On | Vulnerability |
|-------|------------|---------------|
| Conflict warnings include line numbers | Phase 1 line-aware loader survives unchanged | LOW — already in production from Phase 1. |
| Backward compatibility (existing configs unchanged) | All new keys default to absent / preserve current behavior | LOW — explicit in DC-4. |
| `sprints_exist: false` short-circuits to no API call | Planner cleanly factors `_resolve_sprint_ids()` into an early-return path | LOW — single guard before the call. |
| Concat-dedup is the right list semantic | Multi-select fields tolerate `[a, b]` when the user intent was `b` only | MEDIUM — covered by Q4 research; may need field-type-aware special case. |
| Top-level `default_fields:` and `defaults:` placement | No existing `default_fields`/`defaults` keys at those positions | LOW — verified against existing configs (acme.yaml, calcs.yaml). |
| Q1.5 warning is sufficient for transparency | Users actually read stderr warnings during config-load | MEDIUM — descoped CLI command was the alternative; if warnings are ignored in practice, TMPL-02 SC3 may need to come back. |

</dependencies>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements
- `.planning/ROADMAP.md` §Phase 2 — phase goal, dependencies. **Note:** SC2/SC3 wording does NOT reflect the reframe in this CONTEXT; user must edit ROADMAP.md per Q2 before plan-phase runs.
- `.planning/REQUIREMENTS.md` §Template Config — TMPL-01, TMPL-02. **Note:** TMPL-02 wording does NOT reflect descoping; user must edit per Q2.
- `.planning/REQUIREMENTS.md` §Issue Creation — ISSUE-01 specification.

### Prior context (carries forward)
- `.planning/phases/01-reliability-robustness/01-CONTEXT.md` — Phase 1 decisions on error format, line-aware loader, stderr discipline. Phase 2 reuses all of these.
- `.planning/STATE.md` §Decisions — confirmed `ConfigValidationError` non-`ValueError` subclass pattern; same approach if a `ConfigConflictWarning` shape emerges (probably just a logger/print, no exception class needed).

### Codebase context
- `.planning/codebase/STRUCTURE.md` — module layout. New code likely in `config.py` (extend models), maybe new `config_merge.py`.
- `.planning/codebase/CONVENTIONS.md` §CLI Patterns — `Console(stderr=True)`, Click `--option`/`--no-option` flag convention. Governs the new `--sprints-exist`/`--no-sprints-exist` flag pair.
- `.planning/codebase/CONVENTIONS.md` §Error Handling — Pydantic-first; Phase 2 conflict warnings are *warnings*, not raised exceptions. Different mechanism (stderr print at load time), same plain-text format.
- `.planning/codebase/CONVENTIONS.md` §Pydantic Patterns — `@field_validator`, `@model_validator(mode="after")`, `Field(default_factory=dict)`. Apply to new `default_fields:` and `defaults:` Pydantic models.
- `.planning/codebase/ARCHITECTURE.md` §Data Flow — two-phase build (epics first, then tickets with resolved epic keys). Phase 2 merge happens *before* this — merged templates are what `build_all()` consumes.

### Existing source for TMPL-01 (template inheritance)
- `jiramator/config.py:88` — `OrgConfig` Pydantic model. Add `default_fields: dict[str, Any]` field.
- `jiramator/config.py:378` — `TeamConfig` Pydantic model. Add `defaults: TeamDefaults` (or similar) field.
- `jiramator/config.py:312` — `EpicTemplate.fields`. Recipient of merged values.
- `jiramator/config.py:335` — `TicketTemplate.fields`. Recipient of merged values.
- `jiramator/config.py:152-189` — `_wrap_validation_error` and `_load_yaml_with_lines`. Phase 2 conflict warnings reuse the line-resolution path.
- `jiramator/yaml_loader.py` — `safe_load_with_lines`, `LINE_KEY`, `resolve_line`, `strip_line_markers`. Used as-is.
- `jiramator/error_format.py` — `ConfigValidationError`, `format_loc`, `did_you_mean`. Conflict-warning text formatter likely lives here too.

### Existing source for ISSUE-01 (sprint assignment)
- `jiramator/planner.py:99` — `_prompt_sprints_exist()`. Becomes one of four branches in the new resolution function.
- `jiramator/planner.py:247` — `_resolve_sprint_ids()`. Skipped entirely when `sprints_exist == False`.
- `jiramator/planner.py:535-545` — current call site of the prompt + resolution gate. The branch logic moves here.
- `jiramator/planner.py:661-675` — current resolution invocation. Skip-path adds `pop("_sprint_num", None)` only.
- `jiramator/cli.py:135` — `plan` Click command. Add `--sprints-exist`/`--no-sprints-exist` flag pair.
- `jiramator/config.py:378` — `TeamConfig`. Add `sprints_exist: bool | None = None` field.

### Project context
- `PROJECT.md` §Constraints — env-var credentials rule (no new persistence in Phase 2; still relevant if any logging is added).
- `PROJECT.md` §Open Questions — "How should template inheritance conflicts be resolved?" — Phase 2 answers this: org wins + warning; locked is locked.

### Conventions
- `pyproject.toml` — current dep set. Phase 2 adds nothing.
- All source files use `from __future__ import annotations`. New modules continue this.

### Existing configs (for backward-compat verification)
- `configs/org/acme.yaml` — must load identically post-Phase 2.
- `configs/teams/calcs.yaml` — must load identically post-Phase 2; is the canonical "before" example for the inheritance refactor opportunity (lines 35-100 are the repetition target).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`yaml_loader.safe_load_with_lines`** (`yaml_loader.py`) — already returns line-tagged tree; both org and team load paths use it. Conflict warnings use `resolve_line(tagged_raw, loc)` to get the team-side line for the warning string.
- **`error_format.py`** — `ConfigValidationError` plain-text formatter is the closest precedent for the warning-text format. Phase 2 likely adds a sibling formatter (not an exception, just a string builder + stderr print).
- **`Console(stderr=True)`** (`cli.py:38`) — already shared via the planner. Phase 2 conflict warnings emit via the same channel.
- **Pydantic `BaseModel` + `Field(default_factory=dict)`** — pattern for the new `default_fields` / `defaults` blocks.
- **`json.dumps(item, sort_keys=True, separators=(',',':'))`** — stdlib; deterministic canonical form for list dedup. No new dep.
- **`sys.stdin.isatty()`** — stdlib; standard TTY detection for the sprint-mode error path.

### Established Patterns
- **Config-load-time validation** (`config.py:_wrap_validation_error`) — Phase 2 merge logic runs at load time, *after* per-layer Pydantic validation but *before* returning the final `TeamConfig` object. Result: the returned `TeamConfig` carries already-merged template `fields`.
- **Snake_case modules + mirrored test files** — new module (if needed) is `jiramator/config_merge.py` with `tests/test_config_merge.py`.
- **`from __future__ import annotations`** in all source — new code follows.
- **Click boolean flag pair** — `--flag/--no-flag` convention; `is_flag=True` with `default=None` to distinguish "user passed flag" from "user didn't pass either."

### Integration Points
- **Org-team merge** happens in `load_team_config()` after `_load_yaml_with_lines()` returns: load org config (already loaded by CLI before team), apply org→team merge, then per-template merge, then return the merged `TeamConfig`. Or: keep `load_team_config()` org-agnostic and add a new `merge_configs(org, team) -> TeamConfig` function called by CLI after both loads. The latter is cleaner — CLI already loads both, just chains a new call.
- **Sprint-mode resolution** lives in `planner.py` near `_prompt_sprints_exist()`. Refactor target: replace the unconditional `_prompt_sprints_exist` call with `_resolve_sprints_exist_mode(team_config, cli_flag, console)` that returns `bool` and follows the four-branch priority chain.
- **CLI flag wiring** in `cli.py:plan` — add `--sprints-exist/--no-sprints-exist` Click option with `default=None` to allow three-state (true/false/unset). Pass through to `run_plan()` as `sprints_exist_override: bool | None`.

</code_context>

<specifics>
## Specific Ideas

- The user's mental model is **"org configs and team configs are distinct"** — they were resistant to framings that implied org-level templating bleeds into team-level templating. The actual design (org locks policy, team owns templates, both can lock fields) honors that distinctness: org and team configs have *disjoint* concerns by intent, even though they share the merge mechanism for the small overlap (`default_fields` on org, `defaults.fields` on team).
- The repetition pain is real and visible in `calcs.yaml` lines 35-100 — `priority: Medium`, `customfield_10273: [{value: "No"}]`, `customfield_10026: 0.5`, `customfield_10014: "$epic:misc"` repeated across 6 templates. **Team-internal `defaults:` is the single biggest readability win in this phase**, not org-level locking. Plan accordingly: Phase 2 plans should land team-internal merge first (highest user value, lowest risk), org-level locking second (lower-frequency benefit, slightly higher conceptual load), sprint-mode third (smallest scope, fully orthogonal).
- The user repeatedly rejected "resolved-config CLI" framings as overengineering. Honor that: do not propose interim solutions like `plan --print-merged` or debug subcommands. Q1.5 warnings + the user reading their own team config top-to-bottom is the entire transparency story for Phase 2.
- ISSUE-01 was mis-scoped in the original roadmap. The user's actual ask is **non-interactive sprint-mode selection**, not new sprint-assignment surface. Existing sprint resolution (board_id, sprint_name_template, release_sprint_map, sprint_group) is fine. The phase's sprint work is one Pydantic field + one Click flag pair + one branch refactor in the planner.
- The user's framing for Q4 ("if user runs jiramator prior to sprints being available, jiramator should assume that all tickets will be created without sprint being set") implies a strong ergonomic guarantee: when `sprints_exist == False`, **no Jira board API call happens** — not even a "list sprints" probe. Explicit in DC-8.

</specifics>

<deferred>
## Deferred Ideas

- **Resolved-config CLI command** (`jiramator config show` or equivalent) — fully descoped from Phase 2. If real-world adoption shows users can't reason about merged configs from warnings + reading YAML, revisit in a future phase. Will require REQUIREMENTS.md / ROADMAP.md edit (see Q2).
- **Per-key override mechanism (`team_overridable: true` flag, `~unset` sentinel)** — explicitly rejected at every layer. Org-locked means locked.
- **Field-type-aware list merge** (special-case single-select fields to "earlier wins" instead of concat-dedup) — deferred behind Q4 research. Add only if real Jira behavior surfaces a footgun.
- **Recurring-epics sprint assignment** — out of scope; epics live outside sprints by design.
- **Literal `sprint:` override on individual templates** — out of scope; user accepts existing `sprint_group` + `release_sprint_map` indirection.
- **Per-PI sprint name template variation** — out of scope; single global pattern per team is fine.
- **Promoting "unresolved sprint" warnings to errors** — out of scope; current warning is sufficient.
- **Org-level `recurring_epics` / `per_release_tickets` declaration** (Q1 scope option B/C from original discussion) — rejected. Templates live exclusively in team configs. Org configs hold instance/policy/cadence only.
- **Resolved-config command via flag on `plan` (Q3 option b)** — descoped along with the subcommand.
- **Multi-team orchestration** (one command runs plan for many teams, applying shared org defaults across all) — Phase 2 is single-team. ISSUE-04 (v2) covers this.
- **Diff between two merged configs across PIs** — CONF-02 (v2). Builds on Phase 2's merge engine but isn't Phase 2 work.

</deferred>

---

## Pre-Plan Checklist (USER ACTION REQUIRED before `/gsd-plan-phase 2`)

The reframe in this CONTEXT diverges from the original ROADMAP.md / REQUIREMENTS.md wording. **Update these two documents before plan-phase runs**, so the verification gate later in Phase 2 has correct truths to check against:

1. **`.planning/REQUIREMENTS.md` — TMPL-02:**
   - Original: "User can see the fully resolved/merged config for a team (after inheritance) via a CLI command"
   - Recommended new wording (one of):
     - (a) Reword: "User can see how org and team layers merge via stderr conflict warnings at config-load time and via the visible team-internal `defaults:` block."
     - (b) Move TMPL-02 SC3 sub-point to v2 backlog; keep TMPL-02 as inheritance-only.
     - (c) Drop TMPL-02 SC3 entirely; rely on TMPL-01 + warnings.
   - **Recommended:** (a). Keeps TMPL-02 in v1; reframes around the actual Phase 2 deliverable.

2. **`.planning/ROADMAP.md` — Phase 2 Success Criteria:**
   - **SC1** ("User defines shared fields in org config and team config inherits them without repeating") — KEEP. Covers `org.default_fields` flowing into team templates.
   - **SC2** ("User can selectively override any inherited field in team config") — REWRITE. Suggested: "User can fill in fields not locked by org or team defaults via per-template `fields:`, and team defaults flow into all team templates without repetition."
   - **SC3** ("User can run a CLI command to see the fully resolved config after inheritance merging") — REMOVE.
   - **SC4** ("User can specify sprint assignment in config and created tickets land in the correct sprint") — KEEP. Interpret as: team config controls whether sprints are resolved (via new `sprints_exist:` field + CLI flag); existing resolution machinery unchanged.

After both edits, run `/gsd-plan-phase 2` to plan the phase against this CONTEXT.

---

*Phase: 02-template-inheritance-sprint-assignment*
*Context gathered: 2026-04-30*
