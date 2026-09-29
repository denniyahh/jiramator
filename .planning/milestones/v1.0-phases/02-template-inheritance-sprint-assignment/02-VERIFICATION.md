---
phase: 02-template-inheritance-sprint-assignment
verified: 2026-04-30T00:00:00Z
status: passed
score: 18/18 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 17/18
  gaps_closed:
    - "When sprints_exist resolves to False, NO client.get_board_sprints() call happens (DC-8)"
  gaps_remaining: []
  regressions: []
  remediation_commit: 7f97fc4
human_verification:
  - test: "Live smoke: configure a team with board_id set, run `jiramator plan --no-sprints-exist` (non-dry-run, against a test Jira). Confirm via Jira request log that no GET /rest/agile/1.0/board/{id}/sprint was issued."
    expected: "Zero board-sprint API calls; tickets created without sprint custom field."
    why_human: "Validates DC-8 against real Jira; the code-level gap is now closed and mutation-tested, this is the final field confirmation."
---

# Phase 2: Template Inheritance & Sprint Assignment — Verification Report

**Phase Goal (ROADMAP §Phase 2):** Users can eliminate repetitive config by inheriting org defaults into team configs, and assign sprints declaratively (config/flag-driven, non-interactive).

**Requirements:** TMPL-01, TMPL-02, ISSUE-01

**Verified:** 2026-04-30 (re-verified after commit 7f97fc4)
**Status:** **passed** — 18/18 truths VERIFIED. Initial verification flagged DC-8 BLOCKER (T3.4); commit 7f97fc4 closed the gap and was mutation-tested by this verifier.
**Re-verification:** Yes — gap closure of T3.4 (DC-8) confirmed at code and test level; full suite green (507 passed).

## Goal Achievement

### Observable Truths

#### TMPL-01 — Org-locked + team-internal default fields flow into templates

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| T1.1 | Org config can declare top-level `default_fields: {priority: Medium, ...}` | ✓ VERIFIED | `jiramator/config.py:108` — `OrgConfig.default_fields: dict[str, Any] = Field(default_factory=dict, ...)` |
| T1.2 | Team config can declare top-level `defaults: {fields: {customfield_X: ...}}` | ✓ VERIFIED | `config.py:394` `class TeamDefaults` (with `fields: dict[str, Any]`); `config.py:458` `defaults: TeamDefaults = Field(default_factory=TeamDefaults, ...)` on `TeamConfig` |
| T1.3 | When org sets `default_fields.priority=Medium`, every team's every ticket carries `priority=Medium` in its built `fields` payload | ✓ VERIFIED | `config_merge.py:218-302` `merge_configs()` — Layer 1 merges org→team-defaults; Layer 2 (`_apply_team_layer_to_templates` at line 175-215) merges effective team-locks into every `recurring_epics`, `per_release_tickets`, `per_sprint_tickets` template's `fields`. Wired in `cli.py:224` (`merge_configs(...)` between loaders and `run_plan`). |
| T1.4 | When team sets `defaults.fields.customfield_10026=0.5`, every template in that team carries it | ✓ VERIFIED | Same `_apply_team_layer_to_templates` path; team-defaults flow into all 3 template lists. Tests `tests/test_config_inheritance_integration.py` II1 + `tests/test_config.py::TestTeamDefaultsMergeIntegration::I1-I3` exercise this. |
| T1.5 | Team config without `defaults:` works identically to pre-Phase-2 (DC-4) | ✓ VERIFIED | `TeamDefaults` defaults to empty `fields={}`; `_apply_team_layer_to_templates` early-returns when `defaults_fields` falsy (line 190). 417-test baseline preserved (now 507 passing; 90 new). `configs/teams/calcs.yaml` (no `defaults:` block) loads as before. |
| T1.6 | Org config without `default_fields:` works identically to pre-Phase-2 (DC-4) | ✓ VERIFIED | `OrgConfig.default_fields` default = `{}`; `merge_configs` Layer 1 merges with empty-on-empty → no-op. `configs/org/acme.yaml` (no `default_fields:` block) loads identically. Test `O1` confirms. |

**TMPL-01 score: 6/6 ✓**

#### TMPL-02 (reframed) — Transparency via stderr conflict warnings + visible defaults block

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| T2.1 | Team key trying to override org-locked key emits `<team-file>:<line>: <field> — locked by org config (<org-file>:<line>); team value ignored.` (or "later value ignored." per Plan 02-01 standardization) | ✓ VERIFIED | `error_format.py:158-159` formats as `"{later}{ll}: {self.field_path} — locked by {self.earlier_layer} ({earlier}{el}); later value ignored."`. `config_merge.py:289` sets `earlier_layer="org config"` for Layer-1. NOTE: the wording standardized on **"later value ignored."** instead of CONTEXT's original "team value ignored." — covered by Plan 02-01 PATTERNS.md §3 to keep one phrasing across both layers. |
| T2.2 | Template key trying to override team-defaults-locked key emits `<team-file>:<template-line>: <field> — locked by team defaults (<team-file>:<defaults-line>); later value ignored.` | ✓ VERIFIED | `_apply_team_layer_to_templates` (config_merge.py:175) passes `earlier_layer="team defaults"`. Tests `TestMergeConfigs::MC5`, `TestTeamDefaultsMergeIntegration::I2` assert on this format. |
| T2.3 | Warnings go to stderr, plain text, no Rich markup (DC-1) | ✓ VERIFIED | `config_merge.py:308` — `Console(stderr=True)`; line 310 uses `console.print(str(w), highlight=False, markup=False)`. |
| T2.4 | Warnings are warnings, not errors — config still loads, earlier-layer wins (DC-7) | ✓ VERIFIED | `ConfigConflictWarning` is a frozen dataclass, NOT an Exception subclass (`error_format.py:120` — `class ConfigConflictWarning:` no base). Tests `W5` and `MC1-MC8` confirm config returns successfully alongside warnings. |
| T2.5 | NO `jiramator config show` / `--show-resolved` CLI command (DESCOPED, G-2) | ✓ VERIFIED | `grep -E "show-resolved\|config show" jiramator/cli.py` → no hits. Plan 02-02 PATTERNS.md §11 explicitly defers. |

**TMPL-02 score: 5/5 ✓**

#### ISSUE-01 — Config/flag-driven sprint assignment

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| T3.1 | `TeamConfig.sprints_exist: bool \| None` field exists | ✓ VERIFIED | `config.py:430-454` — `sprints_exist: bool \| None = Field(default=None, ...)` plus `@field_validator("sprints_exist", mode="before")` strict-bool guard. |
| T3.2 | `plan` command exposes `--sprints-exist/--no-sprints-exist` flag pair | ✓ VERIFIED | `cli.py:169-176` — `@click.option("--sprints-exist/--no-sprints-exist", "sprints_exist_override", default=None, ...)`. |
| T3.3 | 4-branch priority chain: CLI flag → config → TTY prompt → error (DC-6) | ✓ VERIFIED | `planner.py:113-148` `_resolve_sprints_exist_mode` implements exactly: (1) `cli_override is not None` → return; (2) `team_config.sprints_exist is not None` → return; (3) `sys.stdin.isatty()` → `_prompt_sprints_exist`; (4) raise `ConfigValidationError`. Tests `S1-S6` cover all four. |
| T3.4 | When `sprints_exist=False`, NO `client.get_board_sprints()` call happens (DC-8) | ✓ VERIFIED | **Closed by commit 7f97fc4 (re-verified).** `planner.py:577` now hoists `sprints_exist: bool = False` to function scope; `planner.py:706` gate now reads `if team_config.board_id is not None and sprints_exist:`; the `else` branch at lines 718-723 explicitly skips `_resolve_sprint_ids` and strips `_sprint_num` annotations (with DC-8 comment). Real integration test at `tests/test_planner_sprint.py:277-356` (`TestSprintsExistIntegration::test_ii1_no_board_api_call_when_false`) drives `_run_plan_inner` end-to-end with a wired mock `JiraClient` (`board_id=362`, `sprints_exist=False`, `dry_run=False`) and asserts `client_mock.get_board_sprints.call_count == 0`. **Mutation-tested by verifier:** reverting line 706 to `if team_config.board_id is not None:` causes the test to fail with `AssertionError: DC-8 violation: get_board_sprints() called when sprints_exist=False`; restoring the fix passes. Full suite: 507 passed. |
| T3.5 | When `sprints_exist=True`, existing `_resolve_sprint_ids()` behavior unchanged | ✓ VERIFIED | `planner.py:704-716` Step 11b unchanged from pre-Phase-2 except for Step 4 hint output. `_resolve_sprint_ids` body (`planner.py:286-...`) untouched in this phase. |
| T3.6 | TTY users (no flag, no config) see unchanged interactive prompt (DC-4) | ✓ VERIFIED | Branch 3 of `_resolve_sprints_exist_mode` calls `_prompt_sprints_exist(console)` (planner.py:138) which is preserved verbatim at planner.py:100-110 with original `default=False` and original wording. Test `S5` and `II4` confirm. |
| T3.7 | `run_plan` and `_run_plan_inner` accept `sprints_exist_override: bool \| None = None`; CLI forwards Click flag value | ✓ VERIFIED | `planner.py:449` (`run_plan`), `planner.py:573` (`_run_plan_inner`); `cli.py:202` plan() signature, `cli.py:260` forwarding to `run_plan`. |

**ISSUE-01 score: 7/7 ✓ (T3.4 closed by commit 7f97fc4)**

### Required Artifacts (All Levels)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `jiramator/config_merge.py` | Merge engine (deep_merge_dicts, concat_dedup_lists, canonical_form, merge_configs, _apply_team_layer_to_templates) | ✓ VERIFIED | All five public symbols present; 312 lines; pure stdlib. |
| `jiramator/error_format.py` | `ConfigConflictWarning` frozen dataclass (not Exception) | ✓ VERIFIED | Line 120; `__str__` matches canonical format. |
| `jiramator/config.py` — OrgConfig.default_fields | `dict[str, Any] = Field(default_factory=dict)` | ✓ VERIFIED | Line 108. |
| `jiramator/config.py` — TeamDefaults | Pydantic sub-model with `fields: dict[str, Any]` | ✓ VERIFIED | Line 394. |
| `jiramator/config.py` — TeamConfig.defaults + TeamConfig.sprints_exist | `defaults: TeamDefaults`; `sprints_exist: bool \| None` | ✓ VERIFIED | Lines 430 (sprints_exist + validator at 443), 458 (defaults). |
| `jiramator/config.py` — loaders return tuples | `load_org_config / load_team_config -> tuple[Model, tagged_raw]` | ✓ VERIFIED | Lines 261, 540. |
| `jiramator/cli.py` — `--sprints-exist/--no-sprints-exist`; `merge_configs` call | Click flag + merge call between loaders and run_plan | ✓ VERIFIED | cli.py:169 (flag), cli.py:224 (merge_configs invocation). |
| `jiramator/planner.py` — `_resolve_sprints_exist_mode` | 4-branch resolver | ✓ VERIFIED | Lines 113-148. Function correct in isolation AND result now threaded through to Step 11b gate (planner.py:577 hoist + planner.py:706 gate, fixed in 7f97fc4). |
| `jiramator/importer.py` — Phase 2 scope comment | Documentation-only TODO comment | ✓ VERIFIED | Lines 18-30 carry `default_fields` Phase-2-scope note. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `cli.py:plan` | `merge_configs` | function call after both loaders | ✓ WIRED | cli.py:19 import, cli.py:224 call. |
| `cli.py:plan` | `run_plan` | `sprints_exist_override` kwarg | ✓ WIRED | cli.py:260. |
| `_run_plan_inner` | `_resolve_sprints_exist_mode` | call at planner.py:579 | ✓ WIRED | Result now stored in function-scope `sprints_exist` (planner.py:577) and consumed by Step 11b gate. |
| `_resolve_sprints_exist_mode` (False path) | Step 11b API gate at `planner.py:706` | short-circuit `_resolve_sprint_ids` | ✓ WIRED | Gate reads `if team_config.board_id is not None and sprints_exist:` (fix in 7f97fc4); else-branch strips `_sprint_num` and bypasses `_resolve_sprint_ids` entirely. |
| `merge_configs` | `ConfigConflictWarning` + `resolve_line` | both layers attribute correctly | ✓ WIRED | config_merge.py:34-35 imports; layer-1 uses "org config", layer-2 uses "team defaults". |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full test suite passes | `pytest -q` | `507 passed in 1.24s` | ✓ PASS |
| No new runtime deps | inspection of `pyproject.toml [project].dependencies` | unchanged set: charset-normalizer, click, openpyxl, pydantic, pyyaml, requests, rich | ✓ PASS (DC-3) |
| Importer doesn't apply default_fields | `grep "default_fields" jiramator/importer.py` | only documentation comment lines (no runtime code applies default_fields) | ✓ PASS (matches PATTERNS.md §11 Path B scope) |
| `_prompt_sprints_exist` invoked from one place | `grep -n "_prompt_sprints_exist" jiramator/planner.py` | 2 hits: definition + reuse from `_resolve_sprints_exist_mode` branch 3 | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| TMPL-01 | 02-01, 02-02 | Org-locked + team-internal default fields flow into templates | ✓ SATISFIED | 6/6 truths; merge engine + cli wiring complete. |
| TMPL-02 | 02-01, 02-02 | Stderr conflict warnings + visible team `defaults:` block | ✓ SATISFIED | 5/5 truths. |
| ISSUE-01 | 02-03 | Config/flag-driven sprint assignment, non-interactive | ✓ SATISFIED | 7/7 truths; T3.4 (DC-8) closed by commit 7f97fc4 — `--no-sprints-exist` now actually short-circuits the API call. Mutation-tested. |

### Anti-Patterns Found

_All blockers identified in initial verification have been resolved by commit 7f97fc4. See Remediation section below._

| File | Line | Pattern | Severity | Status |
|------|------|---------|----------|--------|
| `jiramator/planner.py` | (was 578-590) | Resolved `sprints_exist` discarded after print; not propagated to Step 11b gate | 🛑 Blocker | ✓ RESOLVED in 7f97fc4 — value hoisted to function scope (line 577) and consumed at gate (line 706) |
| `tests/test_planner_sprint.py` | (was 277-295) | II1 test asserted on disconnected MagicMock — false confidence | 🛑 Blocker (test-validity) | ✓ RESOLVED in 7f97fc4 — replaced with real integration test driving `_run_plan_inner` end-to-end with wired mock client (lines 277-356) |

### Human Verification Required

See frontmatter `human_verification`. The code-level DC-8 gap is closed and mutation-tested; the remaining check is a real-Jira smoke test confirming `GET /rest/agile/1.0/board/{id}/sprint` is not issued under `--no-sprints-exist` against a live test instance.

### Gaps Summary

Phase 2 ships a fully-working template-inheritance merge engine (TMPL-01, TMPL-02 — 11/11 truths verified, 90 new tests, zero regressions in the 417-test baseline, no new runtime deps). The merge engine is well-factored, correctly attributes warnings to org-vs-team-defaults vs. team-defaults-vs-template layers, and is wired into the `plan` command exactly as RESEARCH.md §R4 prescribed.

ISSUE-01 originally shipped the surface but not the substance of DC-8: the `TeamConfig.sprints_exist` field, `--sprints-exist/--no-sprints-exist` flag, and `_resolve_sprints_exist_mode` resolver were correct in isolation, but the planner consumed the boolean only for a console message. **Commit 7f97fc4 closed this gap.** ISSUE-01 is now 7/7.

## Remediation

**Commit:** `7f97fc4 fix(02-03): thread sprints_exist into Step 11b API gate (DC-8)`

**Code changes (`jiramator/planner.py`):**
- Line 577: `sprints_exist: bool = False` hoisted to function scope of `_run_plan_inner` (previously block-scoped to the `if team_config.board_id is not None:` arm at the old line 578).
- Line 706: Step 11b gate changed from `if team_config.board_id is not None:` to `if team_config.board_id is not None and sprints_exist:`.
- Lines 718-723: explicit `else` branch documents DC-8 intent and strips `_sprint_num` annotations from payloads so they cannot leak into Jira create calls when sprint resolution is skipped.

**Test changes (`tests/test_planner_sprint.py`):**
- Old `test_ii1_no_board_api_call_when_false` (a sham asserting on a disconnected MagicMock) was replaced with a real integration test inside the new `TestSprintsExistIntegration` class.
- New test (lines 277-356): drives `_run_plan_inner` end-to-end with `monkeypatch.setattr(planner, "JiraClient", lambda *a, **kw: client_mock)` so the production `client = JiraClient(org_config)` construction at planner.py:616 returns the mock. Configures `board_id=362`, `sprints_exist=False`, `dry_run=False`, and asserts `client_mock.get_board_sprints.call_count == 0`. The mock's `get_board_sprints.side_effect` raises `AssertionError("DC-8 violation: ...")` to fail loudly if invoked.

**Mutation test (verifier-run):**
- Reverted line 706 back to `if team_config.board_id is not None:` → `test_ii1_no_board_api_call_when_false` FAILS with `AssertionError: DC-8 violation: get_board_sprints() called when sprints_exist=False`.
- Restored the fix → test passes; full suite green: `507 passed in 1.19s`.
- Confirms the test is genuinely coupled to the gate (no false-positive coverage).

**Result:** T3.4 status flips from FAILED → VERIFIED. Phase 2 verdict: **passed (18/18)**. Ready to proceed to STATE/ROADMAP final updates and Phase 3 planning. The pre-existing `error_format.py` `FrozenInstanceError`-under-Python-3.14 fragility logged in 02-03-SUMMARY (deferred-items) remains tracked separately and is independent of this remediation.

---

_Verified: 2026-04-30 (initial)_
_Re-verified: 2026-04-30 (after commit 7f97fc4)_
_Verifier: gsd-verifier_
