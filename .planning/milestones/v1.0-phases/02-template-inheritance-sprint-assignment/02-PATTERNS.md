# Phase 2: Template Inheritance & Sprint Assignment — Patterns

**Mapped:** 2026-04-30
**Purpose:** Map each new file/module Phase 2 will create or extend to its closest existing analog in the codebase. Downstream agents use this to mimic established patterns without re-deriving them.

---

## File-by-File Pattern Map

### 1. `jiramator/config_merge.py` — NEW MODULE

**Role:** Pure function module. Takes a validated `OrgConfig` + `TeamConfig` (with their line-tagged raw trees) and returns a new `TeamConfig` with merged template `fields` plus emits stderr conflict warnings via `Console(stderr=True)`.

**Closest analog:** `jiramator/error_format.py` (111 lines, frozen dataclass + pure helper functions, stdlib-only, no Pydantic models).

**Why this analog:**
- Both are pure-function utility modules with a clean public surface.
- Both produce strings consumed by `Console(stderr=True)` elsewhere.
- Both are imported by `config.py` / CLI without side effects on import.

**Patterns to replicate from `error_format.py`:**

```python
# Header pattern (error_format.py:1-15)
"""<one-line purpose>.

<2-3 line context paragraph explaining the role>

Public surface:
    merge_configs       — main entrypoint
    deep_merge_dicts    — internal helper, exposed for tests
    canonical_form      — JSON-canonical form for list dedup
"""

from __future__ import annotations

# (stdlib-only imports — json, pathlib, typing)
# (jiramator imports — yaml_loader.resolve_line, etc.)
```

Function-level docstrings follow the format in `error_format.py:61-82` (`format_loc` shows the example pattern):

```python
def deep_merge_dicts(earlier: dict, later: dict, ...) -> tuple[dict, list[ConflictWarning]]:
    """Merge ``later`` into ``earlier`` with earlier-wins semantics.

    Examples::

        deep_merge_dicts({"a": 1}, {"b": 2}) == ({"a": 1, "b": 2}, [])
        deep_merge_dicts({"a": 1}, {"a": 2}) == ({"a": 1}, [<ConflictWarning>])
    """
```

**Concrete code excerpts to reuse:**

`json.dumps(item, sort_keys=True, separators=(',',':'))` — for list dedup canonical form. Stdlib, deterministic, used throughout the Python ecosystem.

`Console(stderr=True)` — instantiation pattern from `cli.py:38`. The merge function should accept a `console: Console` parameter rather than create its own — keeps testability.

---

### 2. `jiramator/config.py` — EXTEND (TeamConfig + OrgConfig + loader signatures)

**Role:** Add `default_fields:` to `OrgConfig`, `defaults:` and `sprints_exist:` to `TeamConfig`, and extend the loaders to return tagged raw trees.

**Closest analog:** the existing `OrgConfig.bulk_create` field (`config.py:104-107`) and `TeamConfig.release_sprint_map` field (`config.py:391-395`).

**Patterns to replicate:**

**Pydantic field with default_factory dict (config.py:391-395, 397-400, 100-103):**

```python
default_fields: dict[str, Any] = Field(
    default_factory=dict,
    description="Locked fields applied to every issue created from any team config in this org. "
                "Keys mirror the Jira `fields:` shape on templates. "
                "Same-name keys in team `defaults:` or template `fields:` are warned and dropped at load time.",
)
```

**Pydantic field with sub-model (config.py:104-107):**

```python
class TeamDefaults(BaseModel):
    """Per-team baseline `fields` block, merged into every template under this team."""
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Locked fields applied to every template (epic, per_release, per_sprint) in this team config. "
                    "Same-name keys in template `fields:` are warned and dropped at load time.",
    )

class TeamConfig(BaseModel):
    # ... existing fields ...
    defaults: TeamDefaults = Field(
        default_factory=TeamDefaults,
        description="Team-internal default fields merged into all templates in this team config.",
    )
```

**Pydantic optional bool field (config.py:383-386 — `board_id: int | None`):**

```python
sprints_exist: bool | None = Field(
    default=None,
    description="Whether sprints for this PI already exist in Jira. "
                "None (default) → ask interactively if TTY, else error. "
                "True → resolve sprint IDs at runtime. "
                "False → skip sprint resolution entirely (no Jira board API call).",
)
```

**Loader signature extension (config.py:249-261):**

The current pattern is:

```python
def load_org_config(path: str | Path) -> OrgConfig:
    path = Path(path)
    clean, tagged = _load_yaml_with_lines(path, kind="Org")
    try:
        return OrgConfig(**clean)
    except ValidationError as exc:
        raise _wrap_validation_error(exc, file=path, tagged_raw=tagged) from exc
```

R4 in RESEARCH.md recommends extending this to return `tuple[OrgConfig, object]` (the tagged tree). Two options for the planner:
- Option A: change return type `(OrgConfig, tagged_raw)` and update all callsites.
- Option B: add `load_org_config_with_lines(path) -> tuple[OrgConfig, object]` and keep `load_org_config(path)` as a thin wrapper.

**Recommend Option A** — only two callsites in `cli.py` (lines 197, 334), and the merge function genuinely needs both pieces. Mirroring the existing `_load_yaml_with_lines` return shape (line 192: `tuple[dict[str, Any], object]`).

**Backward compat constraint (DC-4):** all new fields use `default_factory=dict` / `default=None`. Existing configs without these keys load identically.

---

### 3. `jiramator/error_format.py` — EXTEND (add ConfigConflictWarning string builder)

**Role:** Add a sibling formatter to `ConfigValidationError` for Phase 2 conflict warnings. Same plain-text shape; **not** an exception class — just a string builder + dataclass for line/field metadata.

**Closest analog:** `ConfigValidationError` itself (`error_format.py:24-58`).

**Why this analog:**
- Same output shape: `<file>:<line>: <field> — <reason>`.
- Same line-resolution mechanism (`resolve_line(tagged_raw, loc)`).
- Same plain-text discipline (no Rich markup, pipeable).

**Pattern to replicate (modified for warning, not error):**

```python
@dataclass(frozen=True)
class ConfigConflictWarning:
    """A merge-time conflict surfaced when a later layer tries to write a key
    locked by an earlier layer. Emitted to stderr; not raised.
    """
    later_file: Path
    later_line: int | None
    earlier_file: Path
    earlier_line: int | None
    field_path: str
    earlier_layer: str   # "org config" or "team defaults"

    def __str__(self) -> str:
        # Mirror ConfigValidationError.__str__ shape (error_format.py:47-51)
        later = self._rel(self.later_file)
        ll = f":{self.later_line}" if self.later_line is not None else ""
        earlier = self._rel(self.earlier_file)
        el = f":{self.earlier_line}" if self.earlier_line is not None else ""
        return (
            f"{later}{ll}: {self.field_path} — locked by {self.earlier_layer} "
            f"({earlier}{el}); later value ignored."
        )

    @staticmethod
    def _rel(p: Path) -> str:
        # Same as ConfigValidationError._relative_to_cwd (error_format.py:53-58)
        try:
            return str(p.resolve().relative_to(Path.cwd()))
        except ValueError:
            return str(p)
```

**Two CONTEXT formats unified:**
- Org-vs-team: `earlier_layer = "org config"`, `earlier_file = org config path`.
- Team-defaults-vs-template (intra-file): `earlier_layer = "team defaults"`, `earlier_file = team config path` (same as `later_file`).

This keeps one warning class with two configurable layer labels rather than duplicating the formatter.

---

### 4. `jiramator/planner.py` — EXTEND (sprint-mode resolution)

**Role:** Replace unconditional `_prompt_sprints_exist` call (line 536) with a four-branch resolver: CLI flag → config → TTY prompt → error.

**Closest analog:** `_resolve_credentials` pattern in `OrgConfig.resolve_credentials()` (`config.py:123-144`).

**Why this analog:**
- Both resolve a runtime value with priority order (env var presence → fail-with-message).
- Both raise actionable errors with the full set of resolution paths in the error text.

**Pattern to replicate:**

```python
def _resolve_sprints_exist_mode(
    team_config: TeamConfig,
    cli_override: bool | None,
    console: Console,
) -> bool:
    """Resolve whether sprints exist for the current run.

    Priority order:
      1. CLI flag (--sprints-exist / --no-sprints-exist)
      2. team_config.sprints_exist (config field)
      3. Interactive prompt (if stdin is a TTY)
      4. Error (non-TTY with no flag and no config)

    Returns True if sprints should be resolved, False to skip resolution.
    Raises ConfigValidationError-styled error in branch 4.
    """
    if cli_override is not None:
        return cli_override
    if team_config.sprints_exist is not None:
        return team_config.sprints_exist
    if sys.stdin.isatty():
        return _prompt_sprints_exist(console)
    raise ConfigValidationError(
        file=Path("<runtime>"),
        line=None,
        field_path="sprints_exist",
        reason=(
            "Cannot determine whether sprints exist: stdin is not a TTY and "
            "neither --sprints-exist/--no-sprints-exist flag nor 'sprints_exist:' "
            "in team config is set."
        ),
    )
```

**Concrete code excerpt to reuse from `planner.py:535-546`:**

```python
# Replace this block:
if team_config.board_id is not None:
    sprints_exist = _prompt_sprints_exist(console)
    ...

# With:
if team_config.board_id is not None:
    sprints_exist = _resolve_sprints_exist_mode(team_config, sprints_exist_override, console)
    ...
```

The downstream skip path (`_resolve_sprint_ids` invocation in `planner.py:661-675`) is **unchanged** — when `sprints_exist == False`, the existing `else` branch already skips it. This is one of the cleanest refactor targets in the codebase: a single guard becomes a function call.

---

### 5. `jiramator/cli.py` — EXTEND (Click flag + parameter passthrough)

**Role:** Add `--sprints-exist/--no-sprints-exist` Click flag pair to the `plan` command and pass through to `run_plan`.

**Closest analog (for boolean tri-state flag):** Click's documented `--shout/--no-shout` pattern with `default=None`. NO existing analog in this codebase for boolean tri-state — this is a new pattern.

**Closest analog (for option ordering and help text):** existing flags on the `plan` command, e.g. `--dry-run` (`cli.py:153-159`) and `--report` (`cli.py:160-166`).

**Patterns to replicate:**

**Flag declaration ordering:** insert after `--report` and before `--resume` (between non-state-affecting and state-affecting flags). Mirrors the visual grouping of `--dry-run`, `--report`, `--sprints-exist`, `--resume`, `--force`.

**Help text style (cli.py:158, 165):**

```python
@click.option(
    "--sprints-exist/--no-sprints-exist",
    "sprints_exist_override",
    default=None,
    help="Whether sprints for this PI already exist in Jira. "
         "If unset, falls back to 'sprints_exist:' in team config, "
         "then to interactive prompt (or error if non-TTY).",
)
```

**Parameter passthrough (cli.py:188-220):** add `sprints_exist_override: bool | None` to the function signature alongside existing `resume_arg: str | None` and `force: bool`. Forward to `run_plan` as a keyword argument.

**`run_plan` signature change (planner.py — find current signature):** add `sprints_exist_override: bool | None = None` parameter, forwarded into `_run_plan_inner`.

---

### 6. `tests/test_config_merge.py` — NEW TEST FILE

**Role:** Unit tests for the merge engine (deep dict merge, list concat-dedup, conflict-warning emission).

**Closest analog:** `tests/test_error_format.py` (small, focused, pure-function tests of `error_format.py`).

**Patterns to replicate:**

- One test class per public function (`TestDeepMergeDicts`, `TestConcatDedupList`, `TestMergeConfigs`).
- Parametrized test cases for shape variations (dict vs list vs scalar, conflict vs disjoint, nested vs flat).
- Pytest `caplog` or `capsys` for asserting on stderr warning text.

```python
class TestDeepMergeDicts:
    def test_disjoint_keys_merge(self) -> None:
        result, warnings = deep_merge_dicts({"a": 1}, {"b": 2}, ...)
        assert result == {"a": 1, "b": 2}
        assert warnings == []

    def test_same_key_earlier_wins_warning_emitted(self) -> None:
        result, warnings = deep_merge_dicts({"a": 1}, {"a": 2}, ...)
        assert result == {"a": 1}
        assert len(warnings) == 1
        assert "locked by" in str(warnings[0])
```

---

### 7. `tests/test_config.py` — EXTEND (Pydantic model tests)

**Role:** Add tests asserting the new fields validate correctly and default to empty.

**Closest analog:** existing `tmp_org_config` and `tmp_team_config` fixtures (`tests/test_config.py:33-62, 341-380`).

**Patterns to replicate:**

```python
def test_org_config_default_fields_defaults_to_empty(org_config_data: dict, tmp_path: Path):
    p = tmp_path / "org.yaml"
    yaml.safe_dump(org_config_data, p.open("w"))  # no default_fields key
    org = load_org_config(p)
    assert org.default_fields == {}

def test_team_config_sprints_exist_accepts_bool_or_none(team_config_data: dict, tmp_path: Path):
    # parametrize across [None, True, False]
    ...
```

Add new programmatic dict cases to the existing `org_config_data` / `team_config_data` factory fixtures.

---

### 8. `tests/test_planner_sprint.py` — EXTEND (four-branch resolution)

**Role:** Test the `_resolve_sprints_exist_mode` function and integration through `run_plan`.

**Closest analog:** existing test patterns in `tests/test_planner_sprint.py` (mocks `JiraClient.get_board_sprints`, asserts resolution behavior).

**Patterns to replicate:**

- Use `monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)` for non-TTY branch.
- Use `monkeypatch.setattr('jiramator.planner._prompt_sprints_exist', ...)` to assert the prompt is/isn't called.
- For DC-8 ("no API call when False"), use a `MagicMock` JiraClient and assert `client.get_board_sprints.assert_not_called()`.

```python
class TestSprintsExistResolution:
    def test_cli_flag_overrides_config(self, ...):
        # team_config.sprints_exist = False, cli_override = True → True
        ...
    def test_config_used_when_no_flag(self, ...):
        # cli_override = None, team_config.sprints_exist = True → True (no prompt)
        ...
    def test_error_when_non_tty_no_flag_no_config(self, monkeypatch, ...):
        monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
        # cli_override = None, team_config.sprints_exist = None → ConfigValidationError
        ...
    def test_no_api_call_when_false(self, mock_client, ...):
        # sprints_exist resolves to False → mock_client.get_board_sprints not called
        ...
```

---

### 9. `tests/test_cli.py` — EXTEND (Click flag wiring)

**Role:** Verify the `--sprints-exist/--no-sprints-exist` flag pair correctly passes through to `run_plan`.

**Closest analog:** existing `--dry-run` and `--resume` flag tests in `tests/test_cli.py` (uses Click's `CliRunner`).

**Pattern:**

```python
def test_plan_sprints_exist_flag_true(monkeypatch, ...):
    captured = {}
    def fake_run_plan(*args, sprints_exist_override=None, **kwargs):
        captured['override'] = sprints_exist_override
    monkeypatch.setattr('jiramator.cli.run_plan', fake_run_plan)

    result = runner.invoke(cli, ['plan', '--org-config', ..., '--team-config', ..., '--sprints-exist', '--dry-run'])
    assert result.exit_code == 0
    assert captured['override'] is True

def test_plan_no_sprints_exist_flag(...):
    # ... assert captured['override'] is False
def test_plan_neither_flag(...):
    # ... assert captured['override'] is None
```

---

### 10. `tests/test_config_inheritance_integration.py` — NEW TEST FILE

**Role:** End-to-end integration of the merge engine through `merge_configs(org, team)` with realistic Pydantic models.

**Closest analog:** `tests/test_integration.py` (exists, tests cross-module flows).

**Patterns to replicate:**

- Use existing `org_config_data` / `team_config_data` fixtures from `tests/test_config.py`.
- Add a fixture `org_with_default_fields` that extends the base `org_config_data` with a `default_fields:` block.
- Test the end-to-end: load both YAMLs → merge → verify `team_config.recurring_epics[0].fields` contains merged values.
- Assert on stderr capture (`capsys`) for the conflict warning text.

---

### 11. `jiramator/importer.py` — EXTEND (R2 recommendation: `default_fields` flows into import path)

**Role:** Apply org `default_fields` (with lock semantics) before existing `_apply_defaults` (gap semantics).

**Closest analog:** `_apply_defaults` itself (`importer.py:78-89`).

**Patterns to replicate:**

```python
def _apply_default_fields(
    fields: dict[str, Any],
    org_config: OrgConfig,
) -> None:
    """Apply org.default_fields with LOCK semantics (earlier wins, later dropped+warned).

    Differs from _apply_defaults:
      - default_fields LOCKS — overrides row values on conflict (with warning).
      - bulk_create.defaults FILLS GAPS — only applies when row is silent.
    """
    for logical_name, raw_value in org_config.default_fields.items():
        resolved = resolve_field_name(logical_name, org_config)
        jira_field = resolved.jira_field
        if jira_field is None:
            continue
        coerced = coerce_field_value(logical_name, raw_value, org_config.bulk_create)
        if should_omit_value(coerced):
            continue
        # Lock: org default_fields wins. If row already set this, drop + warn.
        if jira_field in fields:
            # Emit warning to stderr (the importer has access to console via the row build context)
            ...
        fields[jira_field] = coerced

# Then in build_row_payload (importer.py:140), add a call ABOVE _apply_defaults:
_apply_default_fields(fields, org_config)
_apply_defaults(fields, org_config)  # gap-fill on what's still missing
```

**Note for planner:** the importer doesn't currently have a `console` parameter in `build_row_payload`. Either:
- (a) Pre-compute warnings during config-load-time merge (recommended — warnings are about config-vs-config conflicts, not config-vs-row conflicts).
- (b) Pass console/warnings to the importer.

**Recommendation:** the import path's `default_fields` lock semantic is "row values override `default_fields`" by `_apply_defaults` precedent? **NO** — re-read CONTEXT working_model layer 1: org `default_fields` is locked org-wide. Rows cannot override. **The simpler path:** `default_fields` for the import flow means "these fields are added to every row payload, overriding any row-supplied value, with a stderr warning if the row tried to override." This requires a console reference in `build_row_payload`.

**Tactical decision deferred to planner.** Two viable paths:
- Path A: Pass `console` into `build_row_payload` (signature change). Cleanest semantically.
- Path B: Skip importer integration for Phase 2; document that `default_fields` only takes effect on `plan` runs, not `import` runs. Reduces Phase 2 scope.

The CONTEXT working_model says "every ticket and epic created from any team config" — this is ambiguous about import. The planner should pick A (full coverage) or B (scope reduction) based on plan cost; both are defensible. **Recommend Path B** (defer importer integration to a follow-up phase if scope balloons) — Phase 2 is already 3 streams (template inheritance, sprint mode, conflict warnings), and adding importer parity adds plumbing complexity without changing the user-visible value of Phase 2's primary win (eliminating template repetition in team configs).

---

## Cross-Cutting Patterns

### Console plumbing
- `Console(stderr=True)` is instantiated once in `cli.py:38` and threaded through to `planner.run_plan` and other entry points.
- The merge function (`merge_configs`) should accept a `console: Console` parameter; let the CLI inject it.
- In tests, instantiate `Console(file=io.StringIO(), force_terminal=False)` to capture output, OR use pytest's `capsys` after configuring console with `stderr=True`.

### `from __future__ import annotations`
- Every source file in `jiramator/` uses this. New modules (`config_merge.py`) follow.

### Pydantic patterns
- `Field(default_factory=dict)` for dict defaults.
- `Field(default=None)` for optional scalars/booleans.
- Sub-model classes (like `TeamDefaults`) use `BaseModel` with their own validators.

### Test fixture patterns
- Programmatic dict → tmp_path YAML dump → load. Avoid static fixtures in `tests/fixtures/` unless YAML must be malformed-on-disk.
- Existing `org_config_data` / `team_config_data` factories in `tests/test_config.py` should be extended with optional Phase 2 keys, not duplicated.

### Plain-text output discipline (DC-1, carries from Phase 1)
- All warning strings: ASCII, no Rich markup, pipeable.
- All errors: same format.
- `Console(stderr=True)` for every user-facing output.

---

## PATTERN MAPPING COMPLETE

11 files mapped to analogs with concrete patterns, code excerpts, and reuse instructions. Planner has full mapping for downstream work.
