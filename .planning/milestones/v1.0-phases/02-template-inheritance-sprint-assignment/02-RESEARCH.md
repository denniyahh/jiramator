# Phase 2: Template Inheritance & Sprint Assignment — Research

**Conducted:** 2026-04-30
**Mode:** Scoped — focused on the four open questions in CONTEXT.md (`<questions>`) plus G-6 (load-time vs build-time merge) and the Click tri-state flag pattern.
**Sources:** Codebase trace (file:line evidence), git history, Click 8.3 official docs, Jira Cloud REST v3 API reference, existing test fixtures.

This RESEARCH.md does NOT relitigate decisions already made in CONTEXT.md. It either confirms them with code-level evidence or recommends specific resolutions for the open questions, citing concrete artifacts.

---

## R1 — Q1: `sprints_exist` default value (`None` vs `False`)

### Evidence

**Audit of current prompt usage:**

- Prompt callsite: `jiramator/planner.py:536` — `sprints_exist = _prompt_sprints_exist(console)`, called only when `team_config.board_id is not None` (line 535). When `board_id is None`, the prompt is already skipped today.
- Prompt definition: `jiramator/planner.py:99-109` — `Confirm.ask(..., default=False, console=console)`. **The interactive default is already `False`.** Pressing Enter at the prompt today produces `False`.
- Git history of the prompt: introduced in `dc01482` (initial commit). No subsequent change. No README mention. No CONVENTIONS.md mention beyond the naming-convention example (`.planning/codebase/CONVENTIONS.md:16` cites `_prompt_sprints_exist()` as a verb-prefixed boolean helper, not as user-facing behavior).
- Tests that exercise the prompt: `tests/test_planner_sprint.py` exists; no test currently asserts on the prompt's interactive flow (the prompt is only reachable in non-mocked paths).
- README.md mentions the `board_id` field (line 281) and the sprint resolution machinery, but does NOT document the interactive prompt — users are not told it will appear. It's an undocumented runtime behavior.

**Phase 3 readiness check:**

Phase 3 (MCP integration, per ROADMAP.md) requires non-interactive execution. With `default=None`:
- MCP path: no TTY, no flag, no config → `ConfigValidationError`-styled error from CONTEXT branch 4.
- Cure: caller must pass `--sprints-exist` / `--no-sprints-exist` or set `sprints_exist:` in config.
- The error message (CONTEXT branch 4) is good UX: it names all three resolution paths explicitly.

With `default=False`:
- MCP path: silently runs sprintless without any signal. **This is dangerous** — a user who intended sprint assignment but forgot the flag gets quiet "no sprints" behavior with no diagnostic.
- The user's framing in CONTEXT (`<specifics>` last bullet) was about an explicit declaration — "if user runs jiramator prior to sprints being available, jiramator should assume that all tickets will be created without sprint being set." That's a deliberate signal, not a silent default.

### Recommendation

**Stick with `None` as the Pydantic default** (CONTEXT working_model is correct). Three reasons, in priority order:

1. **Backward compat (DC-4):** existing `acme.yaml` + `calcs.yaml` work identically. The interactive prompt (whose interactive default is already `False`) preserves the exact "press Enter for sprintless" behavior users have today. `default=False` would silently change semantics for any user who previously answered "y" to the prompt — they'd now need to add `sprints_exist: true` everywhere.
2. **Phase 3 fail-loud:** MCP without explicit flag/config gets a clear actionable error, not silent sprintless creation. Better to fail loudly than mis-create tickets.
3. **No documented users to break:** the prompt is undocumented, so there's no behavioral contract to honor in either direction. The conservative move is "preserve runtime observable" — and the runtime observable today is "prompt with default=False."

**Implementation note for the planner:** the four-branch resolution chain (CONTEXT working_model, sprint section) is correct as written. Special case: if `board_id is None`, all four branches collapse into "skip with existing message" (`planner.py:543-546`) — none of the new resolution logic runs. This is already noted in CONTEXT.

### What this defers to the planner

- Exact wording of the non-TTY error (CONTEXT proposes `Cannot determine whether sprints exist: stdin is not a TTY...`). The planner picks specific phrasing, but the message MUST cite all three resolution paths explicitly.
- Whether `_resolve_sprints_exist_mode()` lives in `planner.py` (alongside `_prompt_sprints_exist`) or moves to `config.py` (config-level concern). **Recommend keeping it in `planner.py`** — it depends on `console` and `sys.stdin.isatty()`, which are CLI/runtime concerns, and the existing `_prompt_sprints_exist` is already there.

---

## R2 — Q3: `default_fields:` placement (top-level on org)

### Evidence

**Where is `org.bulk_create.defaults` actually applied today?**

```
jiramator/importer.py:78   def _apply_defaults(fields, org_config) -> None:
jiramator/importer.py:82       for logical_name, raw_value in org_config.bulk_create.defaults.items():
jiramator/importer.py:140      _apply_defaults(fields, org_config)   # called once per row in build_row_payload
```

That's the **only** callsite. Confirmed via:
```
grep -rn "bulk_create.defaults" jiramator/ → 2 hits, both in importer.py (lines 82, 140 above + comment).
grep -rn "_apply_defaults" jiramator/ → only importer.py.
```

`planner.py` and `ticket_builder.py` do **not** apply `org_config.bulk_create.defaults`. The `plan` command (`cli.py:plan`, `planner.run_plan`) never touches it. So today: `bulk_create.defaults` is an **import-only** mechanism for filling in values absent from spreadsheet rows.

**Is the existing `defaults` semantically what we want for `default_fields`?**

No. Important differences:
- `bulk_create.defaults` only fills gaps (`importer.py:85`: `if jira_field is None or jira_field in fields: continue`). It does NOT lock — if the row has the field, the row wins.
- Phase 2 `default_fields` is **lock-then-warn**, not gap-fill. Earlier wins, later is dropped + warned.
- `bulk_create.defaults` uses `logical_name` keys (e.g., `issuetype: Risk`). Phase 2 `default_fields` uses Jira field IDs / direct keys (mirroring template `fields:` shape).

These are different mechanisms with different semantics, applied to different code paths.

**Backward compat against `acme.yaml`:**

```
configs/org/acme.yaml:92:  defaults:
                                 :93:    issuetype: Risk
```

This is import-only (used for bulk-create when a row doesn't specify issuetype). Adding a top-level `default_fields:` does NOT collide with it — different YAML root key (`bulk_create.defaults` vs. `default_fields`).

### Recommendation

**Top-level `default_fields:` on org config**, sibling of `bulk_create:` and `sprints:`. Three reasons:

1. **Different semantics:** lock vs gap-fill. Nesting under `bulk_create` would semantically confuse two different mechanisms.
2. **Different scope:** `default_fields` applies to `plan` AND `import` (both create issues from templates / rows respectively). `bulk_create.defaults` is import-only by design (it fills missing spreadsheet columns). Top-level placement signals "applies to every issue creation path."
3. **Symmetry with team:** `default_fields:` (org top-level) + `defaults:` (team top-level) read parallel. Nesting one but not the other would be inconsistent.

**Naming distinguishability:** `default_fields:` (org) vs `defaults:` (team) are visually distinct enough to avoid confusion. Document the contrast in the field's `description=` Pydantic Field metadata.

**Should `default_fields` also flow into the import path (`build_row_payload`)?** This is a scope question for the planner. The CONTEXT scope is silent on this. **Recommendation:** YES, if `default_fields` is a "every issue gets these" lock, it should apply to imports too. The implementation point is `importer.py:140` (just before or alongside `_apply_defaults`). Keep this in scope to honor SC1 ("every ticket and epic created from any team config in the org gets …" — CONTEXT working_model layer 1).

### What this defers to the planner

- Whether to extend `_apply_defaults` (importer.py) to also apply org `default_fields` with lock semantics (vs gap semantics it has today), or whether to add a separate `_apply_default_fields()` step that runs before `_apply_defaults`. **Recommend separate step** — keeps the existing gap-fill behavior intact for unknown-row cases, while adding the new locking layer.
- Whether `default_fields` keys are **logical names** (resolved via `field_aliases`) or **direct Jira keys** (matching how templates write `customfield_10273:` directly). CONTEXT's example (`default_fields.priority: Medium`) uses logical name. **Recommend logical-name resolution** for consistency with `bulk_create.defaults` in importer.

---

## R3 — Q4: Multi-select / single-select Jira reality check

### Evidence

**Jira REST v3 payload shapes (from official Atlassian docs example, `POST /rest/api/3/issue` request body):**

- Single-select (`select`): `"customfield_80000": { "value": "red" }` — a **dict**, not a list.
- Multi-select: `"customfield_30000": [ "10000", "10002" ]` or `[{ "value": ... }]` — an **array**.
- `name_object`: `"priority": { "id": "20000" }` or `{"name": "..."}` — a dict.

**Coercion in this codebase (`jiramator/value_coercion.py`):**

```
line 69-71:  field_type == "single_select" → return {"value": cleaned}            # DICT
line 73-75:  field_type == "multi_select"  → return [{"value": item} for ...]    # LIST
line 59-60:  field_type == "name_object"    → return {"name": ...}                # DICT
line 62-64:  field_type == "name_object_array" → return [{"name": ...} for ...]  # LIST
```

`field_types` classification in `configs/org/acme.yaml:68-91`:
- 4 single_select fields (e.g., `code_complexity`, `qa_testing`, `risk_impact`, `risk_mitigation_score`, `database_impact`, ...).
- 3 multi_select fields (`api_impact`, `product_verticals`, `platform`).
- The single-select fields all coerce to **dict** shape, never list shape.

**The Q4 footgun analyzed:**

The CONTEXT example `customfield_X: [{value: "No"}]` + `[{value: "Yes"}]` only happens if both org and team write that field as a **list** in YAML. By inspection of `calcs.yaml:45`, that's exactly how multi-select fields are written (`customfield_10273: [{value: "No"}]` for `api_impact`, a multi_select per acme.yaml:74). For multi-select, concat-dedup `[{value: "No"}, {value: "Yes"}]` is the **correct** Jira shape — a multi-select field can hold both values legitimately.

For a single_select field, no one would write `[{value: "X"}]` in the template — they'd write `{value: "X"}` (dict, not list). When org and team both write a single_select dict to the same key, the merge engine sees **two dicts** at that key, not two lists, and applies the **dict-merge rule** (Q2a in CONTEXT): same-key earlier wins, warn, drop.

**Does `coerce_field_value` get applied before merge or after?**

Today, `_wrap_field` (`ticket_builder.py:54-75`) is called inside `_build_fields_payload` (`ticket_builder.py:151`), which runs at **build time**, not load time. So at config-load time (where Phase 2 merge happens — see R4 below), template values are **still raw**, exactly as written in YAML. Multi-select values are lists in YAML and will be lists at merge time. Single-select values are objects in YAML and will be dicts at merge time. **The merge correctly hits the right rule for each shape.**

### Recommendation

**Ship the concat-dedup rule as specified in CONTEXT, no special-casing needed for Phase 2.** The footgun in CONTEXT's Q4 analysis is theoretical — it only fires if a user writes a single_select field as a one-element list in YAML, which contradicts the project's coercion shape contract. The shape distinction at the YAML layer naturally routes single-select through the dict-merge rule (earlier wins) and multi-select through the list concat-dedup rule.

**No need to consult `org.bulk_create.field_types` at merge time.** The shapes are self-classifying by structural type (dict vs list).

**Test fixtures should explicitly cover:**
1. Multi-select concat (org + team both write list) → result is concat-deduped list.
2. Single-select dict (org + team both write dict) → result is org's dict, team-side warned + dropped.
3. Mixed pre-coercion shapes (`priority: Medium` raw string vs `priority: {name: Medium}` dict) → these are different keys at merge time as far as type compatibility goes; the planner should treat type-mismatch (e.g., scalar vs list) as "earlier wins" by structural rule.

### What this defers to the planner

- Behavior when org and team write the same key with **incompatible shapes** (e.g., org writes `priority: Medium` string, team writes `priority: [{name: Medium}]` list). **Recommend treating as scalar conflict** (earlier wins, team value dropped + warned). Document in test.
- Whether to add a fast-path warning when a list field accumulates suspicious duplicates (e.g., concat result has same logical value coerced two different ways). **Defer — not in scope for Phase 2.**

---

## R4 — G-6: Load-time merge vs build-time merge

### Evidence

**Build-time call graph (where templates' `fields` are consumed):**

```
cli.py:plan → planner.run_plan → planner._run_plan_inner → ticket_builder.build_all
ticket_builder.build_all (line 322-360):
   ├── build_epics       → _build_fields_payload(epic_tmpl.fields, ...)  [line 175-181]
   ├── build_per_release_tickets → _build_fields_payload(tmpl.fields, ...) [line 216-222]
   └── build_per_sprint_tickets  → _build_fields_payload(tmpl.fields, ...) [line ~280]
```

`_build_fields_payload(template_fields, ...)` (line 127-153) is **the only entry point** that touches `template.fields`. It does:
1. `_strip_line_markers(template_fields)` (line 147) — strips `__line__` from line-aware loader.
2. For each `(field_name, raw_value)`: `resolve_value` (template var interpolation) + `_wrap_field` (Jira shape coercion).

**Load-time call graph (where templates first appear):**

```
config.py:load_team_config (line 470) → _load_yaml_with_lines → TeamConfig(...) Pydantic validation
config.py:load_org_config (line 249) → _load_yaml_with_lines → OrgConfig(...) Pydantic validation
cli.py:plan (line 197): org_config = load_org_config(...)
cli.py:plan (line 204): team_config = load_team_config(...)
```

The two configs are loaded sequentially in the CLI command. Neither knows about the other at load time today.

**Test ergonomics comparison:**

- **Option (a) load-time merge:** A new `merge_configs(org, team) -> TeamConfig` (or similar) called by CLI right after both loads. Returned `TeamConfig` carries already-merged template `fields`. Tests assert on `team_config.recurring_epics[0].fields == {priority: "Medium", ...}` — direct, declarative, no plumbing.
- **Option (b) build-time merge:** `_build_fields_payload` becomes layer-aware, reading org + team-defaults + template at every call. Tests must mock `org_config` for every `build_*` test.

**Debuggability:**

- (a) After load, `team_config.recurring_epics[i].fields` shows merged values. User looking at test failures sees the merged result directly. **Loses original raw template values** from the `TeamConfig` object — but the original YAML on disk is the source of truth anyway.
- (b) Templates remain raw on the `TeamConfig` object. Build-time payloads show merged values. Lossless introspection — but more state-space at runtime.

**Resume hash interaction (Phase 1 carryover):**

Phase 1 added a "resolved-config-hash drift check" (cited in `cli.py:182` `--force` help: "ignore the resolved-config-hash drift check"). Need to verify whether this hash is computed over raw `TeamConfig` or merged `TeamConfig`. If it's hashed over the loaded Pydantic object, **option (a) makes the hash include merged values**, which is *good* — drift detection becomes drift in the **effective** config, which is what the user wants. Option (b) hashes raw values, missing merge-level drift.

```
grep -rn "resolved.*hash\|config_hash\|resolved_config" jiramator/
```

(This will be quickly verifiable by the planner; recommend including it as an `<read_first>` in the merge-engine plan.)

### Recommendation

**Option (a): Load-time merge.** Three reasons:

1. **Single touchpoint:** new `merge_configs(org, team) -> TeamConfig` function called at one place in CLI; ticket_builder, planner, importer untouched.
2. **Test ergonomics:** assertions on `team_config.recurring_epics[0].fields` are direct. No mocking org into `_build_fields_payload`.
3. **Resolved-config-hash alignment:** if the Phase 1 hash already covers `TeamConfig`, merged values land in the hash automatically — drift detection on effective config is the intended semantic.

**Where to call it:**

```python
# cli.py:plan, after both loads (currently lines 197-208):
org_config = load_org_config(resolved_org_path)
team_config = load_team_config(team_config_path)
team_config = merge_configs(org_config, team_config, console=console)  # NEW
```

The merge function is also where Q1.5 conflict warnings are emitted (it has access to both line-tagged trees via `_load_yaml_with_lines` plumbing — but that plumbing is currently consumed and discarded inside `load_org_config` / `load_team_config`).

**Plumbing change required:** the current `load_*_config` functions return only the validated Pydantic model. To preserve line numbers for warnings, **either**:
- (i) extend the loaders to also return the line-tagged tree (`tuple[OrgConfig, tagged_raw]`), OR
- (ii) re-load the line-tagged trees inside `merge_configs` (double parse — small cost), OR
- (iii) attach line info to the Pydantic models themselves (intrusive).

**Recommend (i)** — minimal change, keeps single parse, preserves Pydantic validation as the only validation layer.

### What this defers to the planner

- Whether to put the merge function in a new `jiramator/config_merge.py` (CONTEXT G-6 hint) or extend `config.py`. **Recommend new module** — `config.py` is already 482 lines; the merge engine is a separable concern with its own test file.
- Whether to expose `merge_configs(org, team)` publicly (importable from elsewhere) or keep it private to CLI. **Recommend public** — Phase 3 MCP will need the same merge.
- Whether to verify resolved-config-hash interaction with a regression test (a hash test that asserts merge changes the hash). **Recommend yes** — adds confidence to the drift detection story.

---

## R5 — Click `--sprints-exist/--no-sprints-exist` tri-state pattern

### Evidence

**Click 8.3 official docs (Boolean section, "Boolean flag pairs (--flag/--no-flag)" table):**

| `default` | Not passed | `--flag` | `--no-flag` |
|-----------|-----------|----------|-------------|
| _(unset)_ | False     | True     | False       |
| True      | True      | True     | False       |
| False     | False     | True     | False       |
| **None**  | **None**  | **True** | **False**   |

The `default=None` row is exactly the tri-state needed: `None` if the user passed neither flag, `True` if `--sprints-exist`, `False` if `--no-sprints-exist`. **This is the documented official pattern**, not a workaround.

Syntax (Click docs example):

```python
@click.option('--shout/--no-shout', default=False)  # boolean pair, default=False
```

For Phase 2:

```python
@click.option('--sprints-exist/--no-sprints-exist', 'sprints_exist_override',
              default=None,
              help="...")
```

The function parameter receives `bool | None`.

**Prior art in this codebase:**

`cli.py:167-176` uses `--resume` with `is_flag=False, flag_value="auto", default=None, type=click.STRING`. **That's a different pattern** (string optional value, not boolean tri-state) — used because `--resume` can take either no value (auto-find latest) or a path (specific report). Not applicable here.

The codebase does not currently have a boolean tri-state flag. Phase 2 introduces the pattern; document it in CONVENTIONS.md if not already noted.

### Recommendation

**Use `--sprints-exist/--no-sprints-exist` with `default=None`.** Idiomatic Click, no workaround. Pass the resolved `bool | None` into `run_plan` as a new parameter, then into `_run_plan_inner` as `sprints_exist_override`.

### What this defers to the planner

- Exact flag names — CONTEXT proposes `--sprints-exist`/`--no-sprints-exist`. The alternative `--sprints-ready`/`--no-sprints-ready` is mentioned. **Recommend `--sprints-exist`** because:
  - Mirrors the field name (`sprints_exist:`) on `TeamConfig` exactly.
  - Mirrors the existing `_prompt_sprints_exist()` helper name.
  - Matches the prompt wording ("Are the sprints for this PI already created in Jira?" → "are sprints already in existence?" → "exist").
- Whether to add `--sprints-exist` to the `import` command too. **Recommend NO** for Phase 2 — `import` doesn't currently invoke `_prompt_sprints_exist` (verified: no callsite in `importer.py`). If a future phase adds sprint resolution to imports, that's the time to add the flag there. Keeps Phase 2 surface minimal.

---

## R6 — Test fixtures: organization and patterns

### Evidence

```
tests/fixtures/
├── csv_encodings/      # for test_encoding.py
└── yaml_errors/        # extra_forbidden.yaml, missing_required.yaml,
                        # nested_typo.yaml, yaml_parse_error.yaml
                        # (consumed by test_config_loader_errors.py)
```

The dominant pattern in `tests/test_config.py`:
- `tests/test_config.py:33` — `@pytest.fixture` `org_config_data` returns a dict.
- `tests/test_config.py:53-62` — `tmp_org_config(tmp_path, org_config_data)` writes YAML to `tmp_path / "org.yaml"`.
- `tests/test_config.py:341` and `:377-380` — same pattern for `team_config_data` / `tmp_team_config`.

So existing tests build configs **programmatically** as Python dicts, dump to YAML in `tmp_path`, then call `load_*_config(tmp_path / ...)`. Static fixtures in `tests/fixtures/` are reserved for **error-case YAMLs** that have to be malformed-on-disk to trigger loader errors.

For Phase 2 (template inheritance + sprint-mode), the test cases are:
- Multiple combinations of org + team configs (matrix of `default_fields:` × `defaults:` × per-template `fields:`).
- These are best built **programmatically** via the existing `org_config_data` / `team_config_data` fixture pattern. Adding a parametrized fixture for "(org_default_fields, team_defaults, template_fields, expected_merged)" tuples is the natural extension.

For sprint-mode tests:
- The four-branch resolution (CLI flag, config, TTY, error) is testable with mocks (`monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)` etc.) and Click's `CliRunner`.
- `tests/test_planner_sprint.py` already exists — extend it.

### Recommendation

**Do NOT create a new `tests/fixtures/inheritance/` directory.** Use the existing programmatic-fixture pattern from `tests/test_config.py`. Reasons:
1. The merge engine is a function; tests should compose its inputs in-place per case rather than pull from on-disk YAML files (faster to read in code review, easier to parametrize).
2. The existing pattern is already battle-tested by 417 passing tests.

**New test files to create** (planner discretion on naming):
- `tests/test_config_merge.py` — unit tests for the merge engine itself (dict deep-merge, list concat-dedup, conflict-warning emission).
- `tests/test_config_inheritance_integration.py` — integration tests through `merge_configs(org_config, team_config)` returning a fully-merged `TeamConfig`, verifying end-to-end (load + merge) with realistic fixtures.
- Extend `tests/test_planner_sprint.py` for the four-branch resolution cases.
- Possibly extend `tests/test_cli.py` for the new Click flag.

**Static fixtures only when the YAML must be malformed-on-disk.** Phase 2 doesn't currently require any new static fixtures — the merge engine operates on validated Pydantic models, and any "bad merge input" case is a programmatic dict mutation, not a malformed YAML file.

### What this defers to the planner

- Exact organization of merge engine tests (one big parametrized test vs many specific tests). **Recommend many specific tests** — easier to triage failures.
- Whether the integration test suite should include the sprint-mode resolution end-to-end (CLI flag → planner runs without `client.get_board_sprints()`). **Recommend yes** — DC-8 ("no API call") is testable only at integration level.

---

## Summary — Decisions Made vs Deferred

### Decisions made (encoded in this RESEARCH.md)

| # | Topic | Decision |
|---|-------|----------|
| R1 | `sprints_exist` default | **`None`** — preserves backward compat, fail-loud for Phase 3 MCP, no documented users to break |
| R2 | `default_fields:` placement | **Top-level on org config** — sibling of `bulk_create:`/`sprints:`; lock semantics differ from existing `bulk_create.defaults` (gap-fill); applies to both `plan` and `import` paths |
| R3 | Multi-select footgun | **No special-case needed.** Single-select coerces to dict (hits dict-merge rule), multi-select coerces to list (hits concat-dedup). YAML shapes self-classify. |
| R4 | Merge timing | **Load-time** via new `merge_configs(org, team) -> TeamConfig` called from CLI after both `load_*_config` calls. Loaders extended to return `(model, tagged_raw)` tuple for line-aware warnings. |
| R5 | Click flag pattern | **`--sprints-exist/--no-sprints-exist` with `default=None`** — official Click 8.3 boolean-pair tri-state (documented, not workaround) |
| R6 | Test fixtures | **Programmatic dicts via existing `tests/test_config.py` pattern.** New files: `tests/test_config_merge.py` + extensions to `tests/test_planner_sprint.py` + `tests/test_cli.py`. No new `tests/fixtures/inheritance/` dir needed. |

### Open / deferred to planner

These are concrete tactical choices the planner makes during plan composition; none are strategic open questions:

- **R1:** exact wording of non-TTY error message; module placement of `_resolve_sprints_exist_mode()` (recommend `planner.py`).
- **R2:** logical-name vs Jira-key resolution for `default_fields` keys (recommend logical-name); whether to extend `_apply_defaults` or add separate `_apply_default_fields` step in importer (recommend separate).
- **R3:** behavior on shape-mismatch conflicts (e.g., scalar vs list for same key) — recommend "earlier wins, warn"; document in test.
- **R4:** module location for merge engine (`config_merge.py` vs in-`config.py`); plumbing approach for line numbers ((i) extend loaders to return tagged tree — recommended); resolved-config-hash regression test.
- **R5:** flag name confirmation (`--sprints-exist` recommended); whether to add to `import` (recommend no for Phase 2).
- **R6:** test file granularity and naming.

### Phase 2 plans should explicitly answer (planner work)

- The exact Pydantic shape of `TeamDefaults` (CONTEXT working_model says `{ fields: dict[str, Any] }`).
- The exact merge function signature(s) and module placement.
- Whether `default_fields` flows into `importer.build_row_payload` (recommend yes; needs a plan task).
- Test fixtures for the matrix: org-only, team-only, both, conflict cases × dict/list/scalar value types.

### Open questions in CONTEXT now closed by this research

| CONTEXT Q | Status |
|-----------|--------|
| Q1 (sprints_exist default) | **Closed** — recommend `None`. |
| Q2 (REQUIREMENTS.md / ROADMAP.md edits) | **Closed before research** — verified both docs already updated to reflect reframe (TMPL-02 reworded, ROADMAP SC2 reworded, SC3 removed). Pre-plan checklist satisfied. |
| Q3 (default_fields placement) | **Closed** — top-level. |
| Q4 (multi/single-select reality) | **Closed** — no special-case needed; YAML shapes self-classify. |

### Cross-references for downstream agents

- `<read_first>` for any merge-engine plan task: `jiramator/config.py:88-104` (OrgConfig), `jiramator/config.py:378-409` (TeamConfig), `jiramator/yaml_loader.py` (line-aware loader), `jiramator/error_format.py` (warning text builder pattern).
- `<read_first>` for any sprint-mode plan task: `jiramator/planner.py:99-109` (existing prompt), `jiramator/planner.py:520-546` (call site), `jiramator/cli.py:167-176` (Click resume pattern as boolean reference, NOT as identical pattern).
- `<read_first>` for any importer integration task: `jiramator/importer.py:78-90` (existing `_apply_defaults`), `jiramator/importer.py:140` (callsite).

---

## RESEARCH COMPLETE

Phase 2 research is conclusive. All four CONTEXT open questions resolved with concrete recommendations and code-level evidence. No blockers identified. Planner can proceed with full information.
