# Spreadsheet Import for Bulk Jira Creation Implementation Plan

> For Hermes: Use subagent-driven-development skill to implement this plan task-by-task.

Goal: Add a new Jiramator CLI workflow that imports Jira issues from .xlsx or .csv spreadsheets using org-level field mappings plus best-effort automatic lookup for unknown columns.

Architecture: Keep the existing org-vs-team config model intact. Add a new import command parallel to plan, not a mutation of the planning workflow. The importer will read spreadsheet rows into normalized records, resolve spreadsheet column names to Jira fields via org config first and Jira field discovery second, transform row values into Jira REST payloads, then create issues one-by-one with continue-on-error behavior and dry-run preview support.

Tech Stack: Python 3.11+, Click, Pydantic, requests, Rich, csv stdlib, openpyxl (new dependency), pytest.

---

## Why this design

YAML remains the right abstraction for recurring templated work. Spreadsheet import is a separate ingestion path for high-variance, row-oriented work like risk Jiras. Trying to encode one-off, field-heavy imports as giant YAML blobs would be worse for both maintainability and user experience.

The import feature should therefore:
- preserve org/team config separation
- keep field mapping policy at org level
- support both explicit mappings and best-effort auto-resolution
- avoid over-generalizing into a full ETL framework
- keep failure semantics safe and observable

Non-goals:
- deduplication
- update/upsert behavior
- fully generic type inference for every possible Jira custom field
- replacing the existing plan workflow

---

## Proposed CLI UX

Primary command:

```bash
jiramator import \
  --org-config ./configs/org \
  --team-config ./configs/teams/calcs.yaml \
  --file ~/Jira.xlsx \
  --sheet Risks \
  --dry-run
```

Minimal command:

```bash
jiramator import -t ./configs/teams/calcs.yaml --file ~/Jira.xlsx
```

Recommended options:
- `--org-config/-o`: same behavior as existing command
- `--team-config/-t`: determines target project/team defaults
- `--file/-f`: required, `.xlsx` or `.csv`
- `--sheet/-s`: optional, `.xlsx` only; defaults to active sheet if omitted
- `--dry-run/-n`: preview payloads only
- `--issue-type`: optional fallback if spreadsheet does not provide `issuetype`; default `Task`
- `--max-rows`: optional safety limit for testing

Deliberate omission:
- no dedupe flag for v1
- no auto-batch mode for partial-failure semantics; create row-by-row first

---

## Org config changes

Add import-oriented field mapping configuration to `configs/org/marketaxess.yaml` and `jiramator/config.py`.

Proposed schema:

```yaml
custom_fields:
  story_points: customfield_10026
  epic_link: customfield_10014
  api_impact: customfield_10273
  product_horizontals: customfield_12747
  product_verticals: customfield_12749
  platform: customfield_14823

importer:
  field_mappings:
    Summary: summary
    Description: description
    Issue Type: issuetype
    Priority: priority
    Labels: labels
    Fix Versions: fixVersions
    API Impact: customfield_10273
    Product Horizontals: customfield_12747
    Product Verticals: customfield_12749
    Platform: customfield_14823
  required_fields:
    - Summary
  defaults:
    issuetype: Risk
  auto_lookup_unknown_fields: true
```

Key point: keep these mappings at org level because the spreadsheet headers are user-facing conventions while Jira field IDs are organization-specific.

Config model additions:
- `ImporterConfig`
- `field_mappings: dict[str, str]`
- `required_fields: list[str]`
- `defaults: dict[str, Any]`
- `auto_lookup_unknown_fields: bool = True`

Important design choice:
The mapping dictionary keys are spreadsheet headers, not logical names. That makes the importer honest about the source format instead of pretending the spreadsheet is already normalized.

---

## Automatic lookup behavior for unknown fields

Your proposed behavior is reasonable, but it needs constraints or it will become sloppy.

Recommended resolution order for each spreadsheet column:
1. Exact header match in `org_config.importer.field_mappings`
2. Exact header match against Jira field `name`
3. Case-insensitive normalized match against Jira field `name`
4. Exact match against Jira field id (e.g. `customfield_10273`)
5. If still unresolved, skip column and report warning

Normalization should only do conservative cleanup:
- strip leading/trailing whitespace
- collapse internal whitespace
- lowercase for comparison

Do not do fuzzy matching in v1. That sounds friendly but creates silent mis-mappings, which is worse than skipping.

Need a new Jira client method:
- `get_fields()` hitting `/rest/api/3/field`

Need a small resolver component:
- cache Jira field metadata once per run
- resolve unknown headers deterministically
- emit warnings for skipped columns
- expose a report at the end: mapped, auto-mapped, skipped

---

## Value transformation rules

This is where most spreadsheet imports become garbage if you are not explicit.

Start with a narrow, predictable transformation layer:

Field handling rules for v1:
- `summary`: raw string, required
- `description`: raw string
- `issuetype`: wrap as `{"name": value}`
- `priority`: wrap as `{"name": value}`
- `fixVersions`: split comma-separated strings into `[{"name": ...}]`
- `labels`: split comma-separated strings into `[...]`
- `components`: split comma-separated strings into `[{"name": ...}]`
- direct `customfield_*`: pass through raw value unless explicit coercion rule applies

Needed explicit coercion support because CA has known field quirks:
- single-select custom fields must become `{"value": "X"}`
- multi-select custom fields must become `[{"value": "A"}, {"value": "B"}]`

You already know these stable CA conventions from prior work:
- `customfield_12747` = single-select
- `customfield_12749` and `customfield_14823` = multi-select

So the importer should support org-level field coercion metadata too.

Extend org config:

```yaml
importer:
  field_mappings:
    Product Horizontals: customfield_12747
    Product Verticals: customfield_12749
    Platform: customfield_14823
  field_types:
    customfield_12747: single_select
    customfield_12749: multi_select
    customfield_14823: multi_select
    customfield_10273: multi_select
  multi_value_delimiter: ","
```

Why this matters:
Jira field names alone are not enough. The REST API shape depends on field type, and getting that wrong produces confusing 400s.

Recommended supported field types for v1:
- `string`
- `labels`
- `name_object`
- `name_object_array`
- `single_select`
- `multi_select`
- `passthrough`

Default behavior if no explicit type is known:
- built-in standard fields use hardcoded rules
- `customfield_*` defaults to passthrough

---

## Import execution flow

End-to-end flow:
1. Load org config
2. Load team config
3. Read spreadsheet rows
4. Normalize headers
5. Resolve spreadsheet columns to Jira field IDs/names
6. Merge org-level importer defaults
7. Inject required project field from team config
8. Build per-row payloads
9. In dry-run: show preview and warnings, then exit
10. In live mode: create issues row-by-row, continue on failures
11. Print summary with created keys and failed rows

Important pushback:
Do not reuse `ticket_builder.py` directly for this feature. It is a template interpolation engine for the planning workflow. Spreadsheet import is a different abstraction: row-to-payload transformation. Forcing both through one builder will make the code worse.

Instead, add a new module, something like:
- `jiramator/importer.py`
- maybe `jiramator/spreadsheet.py` if you want cleaner separation between file parsing and Jira payload construction

Suggested module responsibilities:
- `spreadsheet.py`: parse `.csv` / `.xlsx` into `list[dict[str, str]]`
- `importer.py`: header resolution, value coercion, payload building, result reporting
- `jira_client.py`: field metadata fetch and existing create_issue reuse
- `cli.py`: new `import` command

---

## Data model sketch

Add to `jiramator/config.py`:

```python
class ImporterConfig(BaseModel):
    field_mappings: dict[str, str] = Field(default_factory=dict)
    field_types: dict[str, str] = Field(default_factory=dict)
    required_fields: list[str] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    auto_lookup_unknown_fields: bool = True
    multi_value_delimiter: str = ","

class OrgConfig(BaseModel):
    ...
    importer: ImporterConfig = Field(default_factory=ImporterConfig)
```

Add new importer-facing dataclasses in `jiramator/importer.py`:

```python
@dataclass
class ResolvedColumn:
    source_header: str
    jira_field: str
    resolution_source: str  # config | jira_exact | jira_normalized

@dataclass
class RowImportResult:
    row_number: int
    summary: str
    issue_key: str | None
    success: bool
    error: str | None = None
```

This is intentionally simple. Do not introduce ten layers of abstraction for a CSV/XLSX importer.

---

## Task-by-task implementation plan

### Task 1: Add failing config tests for importer schema

Objective: Define and lock the org-config contract before writing importer code.

Files:
- Modify: `tests/test_config.py`
- Modify: `jiramator/config.py`

Step 1: Add tests asserting that org config can parse an `importer` block with:
- `field_mappings`
- `field_types`
- `required_fields`
- `defaults`
- `auto_lookup_unknown_fields`
- `multi_value_delimiter`

Example test cases:
```python
def test_org_config_accepts_importer_block():
    raw = {
        "jira_url": "https://example.atlassian.net",
        "custom_fields": {},
        "sprints": {
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
        "importer": {
            "field_mappings": {"Summary": "summary"},
            "field_types": {"customfield_12747": "single_select"},
            "required_fields": ["Summary"],
            "defaults": {"issuetype": "Risk"},
            "auto_lookup_unknown_fields": True,
            "multi_value_delimiter": ",",
        },
    }
    config = OrgConfig(**raw)
    assert config.importer.field_mappings["Summary"] == "summary"
```

```python
def test_org_config_importer_defaults_to_empty_values():
    raw = {
        "jira_url": "https://example.atlassian.net",
        "custom_fields": {},
        "sprints": {
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [],
        },
    }
    config = OrgConfig(**raw)
    assert config.importer.field_mappings == {}
    assert config.importer.auto_lookup_unknown_fields is True
```

Step 2: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_config.py -v
```
Expected: FAIL because importer config model does not exist yet.

Step 3: Implement `ImporterConfig` and wire it into `OrgConfig`.

Step 4: Re-run the same test command.
Expected: PASS.

Step 5: Commit.

---

### Task 2: Update org config fixture file with importer metadata

Objective: Add concrete MarketAxess importer mappings and CA-specific field type rules.

Files:
- Modify: `configs/org/marketaxess.yaml`
- Test: `tests/test_config.py`

Step 1: Add an `importer:` block to the real org config.

Recommended initial contents:
```yaml
importer:
  field_mappings:
    Summary: summary
    Description: description
    Issue Type: issuetype
    Priority: priority
    Labels: labels
    Fix Versions: fixVersions
    API Impact: customfield_10273
    Product Horizontals: customfield_12747
    Product Verticals: customfield_12749
    Platform: customfield_14823
  field_types:
    labels: labels
    fixVersions: name_object_array
    components: name_object_array
    issuetype: name_object
    priority: name_object
    customfield_10273: multi_select
    customfield_12747: single_select
    customfield_12749: multi_select
    customfield_14823: multi_select
  required_fields:
    - Summary
  defaults:
    issuetype: Risk
  auto_lookup_unknown_fields: true
  multi_value_delimiter: ","
```

Step 2: Add/update a config-loading test that loads the real org config and asserts a few important values.

Step 3: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_config.py -v
```
Expected: PASS.

Step 4: Commit.

---

### Task 3: Add spreadsheet parser tests for CSV and XLSX

Objective: Create a clean file-ingestion layer with deterministic behavior.

Files:
- Create: `jiramator/spreadsheet.py`
- Create: `tests/test_spreadsheet.py`
- Create: `tests/fixtures/import_sample.csv`
- Create: `tests/fixtures/import_sample.xlsx`
- Modify: `pyproject.toml`

Step 1: Write failing tests for CSV parsing.

Test cases:
- reads headers and rows into a list of dicts
- preserves empty cells as empty strings or None consistently
- errors on unsupported extension

Example:
```python
def test_read_csv_returns_rows(tmp_path):
    path = tmp_path / "sample.csv"
    path.write_text("Summary,Priority\nRisk A,High\nRisk B,Medium\n")
    rows = read_spreadsheet(path)
    assert rows == [
        {"Summary": "Risk A", "Priority": "High"},
        {"Summary": "Risk B", "Priority": "Medium"},
    ]
```

Step 2: Write failing tests for XLSX parsing.

Step 3: Add `openpyxl>=3.1` to dependencies in `pyproject.toml`.

Step 4: Implement `read_spreadsheet(path, sheet_name=None, max_rows=None)`.
Rules:
- `.csv`: use `csv.DictReader`
- `.xlsx`: use `openpyxl.load_workbook(..., data_only=True, read_only=True)`
- first row is header
- trim header whitespace
- coerce `None` cell values to empty string
- reject `.xls` for now; be explicit

Step 5: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_spreadsheet.py -v
```
Expected: PASS.

Step 6: Commit.

---

### Task 4: Add Jira field discovery tests and implementation

Objective: Support safe auto-mapping for unknown spreadsheet headers.

Files:
- Modify: `jiramator/jira_client.py`
- Modify: `tests/test_jira_client.py`

Step 1: Add failing tests for a new `get_fields()` method.

Cases:
- returns parsed JSON on 200
- raises `JiraApiError` on non-200

Step 2: Implement:
```python
def get_fields(self) -> list[dict[str, Any]]:
    response = self._session.get(self._url("/rest/api/3/field"), timeout=_DEFAULT_TIMEOUT)
    if not response.ok:
        self._handle_error(response, "fetching Jira field metadata")
    return response.json()
```

Step 3: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_jira_client.py -v
```
Expected: PASS.

Step 4: Commit.

---

### Task 5: Add column resolution tests

Objective: Resolve spreadsheet headers to Jira fields deterministically and visibly.

Files:
- Create: `jiramator/importer.py`
- Create: `tests/test_importer.py`

Step 1: Write failing tests for `resolve_columns(...)`.

Required cases:
- config mapping wins over Jira metadata
- exact Jira field-name match works
- normalized case-insensitive match works
- exact customfield id match works
- unresolved columns are skipped and reported

Example:
```python
def test_resolve_columns_prefers_config_mapping(org_config):
    rows = [{"Summary": "A", "Risk Level": "High"}]
    jira_fields = [{"id": "priority", "name": "Priority"}]
    resolved, skipped = resolve_columns(
        headers=["Summary", "Risk Level"],
        importer_config=org_config.importer,
        jira_fields=jira_fields,
    )
    assert resolved["Summary"].jira_field == "summary"
```

Step 2: Implement resolver helpers:
- `_normalize_header(text)`
- `resolve_columns(...)`

Step 3: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_importer.py -v
```
Expected: PASS for resolution tests.

Step 4: Commit.

---

### Task 6: Add value coercion tests

Objective: Encode the CA/Jira payload-shape rules explicitly instead of letting API errors teach them.

Files:
- Modify: `tests/test_importer.py`
- Modify: `jiramator/importer.py`

Step 1: Add failing tests for `coerce_field_value(field_name, raw_value, importer_config)`.

Cases to cover:
- empty strings become omitted values or None according to builder policy
- `labels` splits comma-separated strings into arrays
- `fixVersions` wraps into `[{"name": ...}]`
- `issuetype` -> `{"name": ...}`
- `priority` -> `{"name": ...}`
- `single_select` custom field -> `{"value": ...}`
- `multi_select` custom field -> `[{"value": ...}, ...]`
- passthrough custom field leaves numeric/string values alone

Be explicit about whitespace trimming for comma-separated values.

Step 2: Implement coercion functions and field-type lookup.

Suggested API:
```python
def coerce_field_value(field_name: str, raw_value: Any, importer_config: ImporterConfig) -> Any: ...
def build_row_fields(row: dict[str, Any], ...) -> dict[str, Any]: ...
```

Step 3: Decide omission policy and test it.
Recommended v1 policy:
- if coerced value is empty (`""`, `[]`, `None`), omit that field from payload
- exception: `summary` must remain required and validated separately

This omission policy matters because Jira often rejects empty wrappers like `{"name": ""}`.

Step 4: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_importer.py -v
```
Expected: PASS.

Step 5: Commit.

---

### Task 7: Add row-to-payload build tests

Objective: Build complete Jira REST payloads from spreadsheet rows plus team/org defaults.

Files:
- Modify: `tests/test_importer.py`
- Modify: `jiramator/importer.py`

Step 1: Write failing tests for `build_import_payloads(...)`.

Required behaviors:
- injects `project: {"key": team_config.project_key}`
- applies importer defaults before row values
- row values override defaults
- requires `summary`
- skips unresolved columns
- supports `max_rows`
- preserves source row number for reporting

Important design rule:
Defaults should be resolved/coerced through the same pipeline as spreadsheet values. Otherwise you will end up with defaults shaped differently from row values.

Step 2: Implement payload builder returning something like:
```python
@dataclass
class PreparedImportRow:
    row_number: int
    source_row: dict[str, Any]
    summary: str
    payload: dict[str, Any]
```

Step 3: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_importer.py -v
```
Expected: PASS.

Step 4: Commit.

---

### Task 8: Add CLI tests for the new import command

Objective: Integrate importer workflow into the CLI without regressing existing commands.

Files:
- Modify: `jiramator/cli.py`
- Modify: `tests/test_integration.py`
- Possibly modify: `tests/conftest.py`

Step 1: Write failing CLI tests using Click test runner.

Cases:
- `jiramator import --help` shows expected options
- dry-run exits 0 and prints preview/warnings
- live mode continues after a row failure and reports summary
- unsupported file extension exits nonzero with clear message

Step 2: Implement new `import` command in `cli.py`.

Suggested control flow:
- resolve org config path
- load org/team configs
- read spreadsheet
- instantiate `JiraClient` only after parsing succeeds
- resolve columns using org config + Jira metadata if enabled
- build prepared rows
- if dry-run: print preview table and mapping report; exit 0
- else: iterate row-by-row calling `create_issue`
- accumulate successes and failures; never stop on a per-row create error
- exit 0 if all succeeded, exit 1 if any failed

Why row-by-row first instead of bulk endpoint:
Because you explicitly want continue-on-error behavior, and Jira bulk create partial failures are harder to attribute cleanly to source rows. Do the simpler correct thing first.

Step 3: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_integration.py -v
```
Expected: PASS.

Step 4: Commit.

---

### Task 9: Add preview/reporting output tests and implementation

Objective: Make dry-run and live execution inspectable enough that users can trust the importer.

Files:
- Modify: `jiramator/importer.py`
- Modify: `tests/test_importer.py`

Step 1: Add tests for reporting helpers.

Desired reporting sections:
- total rows read
- resolved columns from config
- resolved columns from auto-lookup
- skipped columns
- payload preview for first N rows
- live run summary: created count, failed count, per-row failure messages

Step 2: Implement small formatter helpers that return strings or Rich renderables.
Do not bury presentation logic inside CLI branching.

Step 3: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_importer.py tests/test_integration.py -v
```
Expected: PASS.

Step 4: Commit.

---

### Task 10: Add end-to-end regression test for a CA risk import sample

Objective: Prove the importer handles the exact class of workflow that motivated the feature.

Files:
- Create: `tests/fixtures/ca_risk_import.csv`
- Modify: `tests/test_integration.py`

Step 1: Create a compact risk-import fixture with realistic columns like:
- Summary
- Description
- Priority
- API Impact
- Product Horizontals
- Product Verticals
- Platform
- Labels

Step 2: Write an integration test that:
- loads the real org/team configs
- parses the fixture
- mocks Jira field discovery and issue creation
- asserts correct payload shapes for CA custom fields
- asserts row numbering and continue-on-error summary

Step 3: Run:
```bash
cd /home/denniyahh/jiramator && pytest tests/test_integration.py -v
```
Expected: PASS.

Step 4: Commit.

---

### Task 11: Update README with importer documentation

Objective: Document the new workflow well enough that users do not need to read source.

Files:
- Modify: `README.md`

Step 1: Add a new section:
- what spreadsheet import is for
- when to use YAML plan vs spreadsheet import
- required columns
- optional columns
- supported file formats
- how field mapping works
- how auto-lookup works and why unresolved columns are skipped
- dry-run example
- live-run example
- CA-specific field type note

Step 2: Run a quick sanity check by reading the rendered markdown locally.

Step 3: Commit.

---

## Testing strategy summary

Unit tests:
- `tests/test_config.py`
- `tests/test_spreadsheet.py`
- `tests/test_importer.py`
- `tests/test_jira_client.py`

Integration tests:
- `tests/test_integration.py`

Full recommended test run at the end:

```bash
cd /home/denniyahh/jiramator && pytest -v
```

If you want tighter quality gates, also add later:
- Ruff
- mypy
- coverage threshold

But do not mix that cleanup into this feature PR unless you want the scope to sprawl.

---

## Key implementation cautions

1. Do not silently fuzzy-match columns.
   Conservative skip-with-warning is safer than clever guessing.

2. Do not reuse the planner’s template builder for imports.
   Different problem, different abstraction.

3. Do not bulk-create in v1 if you need continue-on-error semantics.
   Simpler row-by-row logic is more debuggable.

4. Do not send empty wrapped values to Jira.
   Omit them before request construction.

5. Do not assume Jira field names are globally stable forever.
   That is exactly why explicit org-level mappings should remain primary.

---

## Acceptance criteria

The feature is complete when:
- `jiramator import` exists and accepts `.csv` and `.xlsx`
- org config contains importer mapping/type/default settings
- unknown spreadsheet columns are auto-resolved via Jira field metadata when possible
- unresolved columns are skipped with explicit warnings
- dry-run previews payloads without creating issues
- live mode creates row-by-row and continues on failure
- CA-specific select field payloads are shaped correctly
- tests cover parsing, mapping, coercion, CLI integration, and CA regression behavior
- README documents usage and trade-offs

---

## Recommended first implementation slice

If you want to implement this incrementally, the best vertical slice is:
1. config schema
2. CSV parsing only
3. explicit mapping only
4. dry-run only
5. no XLSX yet
6. then add auto-lookup and live creation

That said, if you want the actual user-visible feature in one pass, the task list above is the right order.

---

Plan complete and saved. Ready to execute using subagent-driven-development — I'll dispatch a fresh subagent per task with two-stage review if you want. Shall I proceed?
