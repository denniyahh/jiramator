# Phase 1: Reliability & Robustness — Research

**Researched:** 2026-04-28
**Domain:** Python config-driven CLI hardening — Pydantic 2 / pyyaml / encoding detection / structured run reports / resume semantics
**Confidence:** HIGH on Q1 + Q2 (verified empirically on this machine and against authoritative docs); MEDIUM on Q3 + Q4 (driven by ecosystem convention, no single canonical answer); HIGH on Don't-Hand-Roll items (cited stdlib + maintained-lib docs).

## Summary

Phase 1 is a "smooth out the rough edges" phase, not a greenfield architecture phase. The CONTEXT.md is unusually well-developed and most strategic decisions are already locked. Research therefore focuses on the four explicit Open Questions and on validating the [decided] claims that ripple into implementation.

The headline findings are: **(1)** ruamel.yaml's `lc` line/column attribute requires the round-trip loader (`typ='rt'`, the default), NOT `typ='safe'` — empirically verified on this system. This contradicts a plausible reading of the CONTEXT.md hypothesis ("`YAML(typ='safe')` … does this work with `typ='rt'`?"). The cleanest path is therefore a custom `yaml.SafeLoader` subclass — it is roughly 5–15 LoC, requires zero new dependencies, and has been the StackOverflow-canonical answer since 2018. **(2)** `charset-normalizer` is already installed transitively via `requests>=2.32` (verified: `requests 2.33.1` declares `charset_normalizer<4,>=2`). Adding it as a direct dependency therefore costs nothing in install footprint, while its MIT license (vs chardet's recently-disputed re-license) makes it the unambiguously safer choice. **(3)** Resume should key on team-config absolute path (resolved via `Path.resolve()`), with hash-of-resolved-config as a strict-drift guard, matching how Terraform and dbt key state. **(4)** `difflib.get_close_matches(cutoff=0.7, n=3)` is the de-facto standard across the Python tooling ecosystem (pip, pylint, attrs); single-suggestion phrasing `(did you mean 'X'?)` matches Python's own `NameError` enhancement (PEP 657 / Python 3.11+).

**Primary recommendation:** Use **pyyaml + custom `SafeLineLoader`** (no new dep), **charset-normalizer pinned directly** (already transitive, MIT-licensed), keyed-by-team-config-resolved-path for `--resume` auto-discovery, and `difflib.get_close_matches(n=3, cutoff=0.7)` for did-you-mean. Persist run reports atomically via `os.replace()` after writing to a sibling `.tmp` file. Schema envelope: `{"schema_version": 1, "run": {...}}`.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**FOUND-01 (validation errors):**
- Target shape: plain text `<relative-file>:<line>: <field-path> — <reason>`. Not Rich-decorated. Pipeable. [decided:reasoned]
- Did-you-mean suggestions for known-set fields only: `KNOWN_TEMPLATE_VARS`, `org.custom_fields` aliases, `team.get_epic_keys()`. Use `difflib.get_close_matches`. [decided:reasoned]
- Fail-fast on first error (no aggregation). Matches existing `sys.exit(1)` flow. [decided:reasoned]
- Cross-walk requires Pydantic `loc` tuple + line-aware loader (pyyaml SafeLoader discards lines). [evidenced:cited]

**FOUND-02 (run report):**
- Always written, never opt-in. Substrate for FOUND-03 + Phase 3. [decided:reasoned]
- Default location: `.jiramator/runs/<UTC-timestamp>-<team-slug>.json`, gitignored. `--report <path>` overrides. Slug = team config filename stem. [decided:reasoned]
- Versioned envelope: `{"schema_version": 1, "run": {...}}`. JSON. [decided:reasoned]
- Contents: run metadata (PI label, version strings, team, org config path, command invocation, start/end timestamps), per-issue results (template-key → `{status, jira_key | error}`), aggregate counts, overall status enum (`success | partial | failed`), resolved-config hash. **Never** credentials or full Jira payloads. [decided:reasoned]
- Human stderr Rich summary continues; disk artifact is for tooling. [decided:reasoned]

**FOUND-03 (resume):**
- CLI: `--resume` (no value) auto-finds most-recent `partial`/`failed` run for same team config; `--resume <path>` is explicit. No interactive prompt. [decided:reasoned]
- Resume covers epics + tickets uniformly via per-issue template-key → Jira-key map. [decided:reasoned]
- Strict drift check: resolved-config hash. On hash mismatch, abort with `--resume --force` override. [decided:reasoned]
- Run report is the only state. Persist-on-error mandatory. [decided:reasoned]

**IMPT-01 (CSV encoding):**
- Read pipeline: BOM detection first (UTF-8-SIG, UTF-16-LE, UTF-16-BE) → try UTF-8 → on `UnicodeDecodeError`, run encoding-detection lib and use top match. [decided:reasoned]
- One-line stderr announcement when non-UTF-8 used: `Read <relative-path> as <encoding>`. [decided:reasoned]
- `--encoding <name>` flag overrides detection. [decided:reasoned]
- xlsx errors surface via FOUND-01 format unchanged. [decided:reasoned]

### Claude's Discretion

- Exact wording of error messages and the encoding announcement banner.
- Module placement: likely `jiramator/run_report.py` for report dataclass + IO; `jiramator/encoding.py` or extension of `jiramator/spreadsheet.py` for read pipeline.
- How aggressively to refactor `run_plan()`'s double-`build_all()` while landing the report.
- Whether the existing inline Rich results table consumes the report dataclass or stays parallel.
- Test fixture organization for new YAML-error-path tests; whether to populate `tests/fixtures/`.

### Deferred Ideas (OUT OF SCOPE)

- Concurrency / lockfile for run reports.
- Report retention / rotation policy.
- Aggregate validation errors in a single pass.
- Rich panel error rendering with code excerpt.
- Defensive xlsx encoding fallback.
- Duplicate detection / pre-flight Jira queries.
- Hash-strict resume (any config change blocks).
- `--yes` for `plan` (FOUND-05 v2; INTG-02 in Phase 3).
- MCP-shaped JSON envelope (Phase 3 builds on `schema_version: 1`).

</user_constraints>

---

## Standard Stack

### Core (already present, no version bump needed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pyyaml` | `>=6.0` (already in `pyproject.toml`) | YAML parsing with custom `SafeLoader` subclass for line numbers | Stable, ubiquitous, supports loader subclassing — `node.start_mark.line` is part of public PyYAML behaviour. |
| `pydantic` | `>=2.0` (already present) | Validation; `ValidationError.errors()[i]['loc']` is the cross-walk key | Already adopted; v2 `loc` API is stable. |
| `click` | `>=8.1` | `--report`, `--resume`, `--encoding`, `--force` flags | Already adopted; `path_type=Path` follows existing conventions. |
| `rich` | `>=13.0` | `Console(stderr=True)` for end-of-run summary (NOT for the FOUND-01 error format) | Already adopted; preserved for the existing UX. |
| `difflib` | stdlib | `get_close_matches` for did-you-mean | Stdlib, zero dep, sufficient for known-set typos. (G-5) |
| `hashlib` | stdlib | SHA-256 of canonical-JSON-serialized resolved config for drift check | Stdlib; deterministic when fed `json.dumps(..., sort_keys=True)`. |
| `json` | stdlib | Run report serialization | Stdlib; matches `schema_version` envelope. |
| `os.replace` | stdlib | Atomic write (write `.tmp` → `os.replace` to final) | POSIX `rename(2)` semantics; atomic on same filesystem. The Pythonic answer for "don't leave a half-written file." |
| `codecs` | stdlib | `BOM_UTF8`, `BOM_UTF16_LE`, `BOM_UTF16_BE` constants for BOM-first sniff | Stdlib; deterministic, zero-dep first-line of defense. |

### Supporting (one new explicit dep)

| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| `charset-normalizer` | `>=3,<4` | Encoding fallback for IMPT-01 (cp1252 / cp1254 / mac_roman / etc.) | **Already a transitive dep via `requests` (verified: `requests 2.33.1` declares `charset_normalizer<4,>=2`). Promoting it to a direct dep adds zero install footprint** while declaring the intent explicitly (DC-6 satisfied). MIT-licensed. Active maintenance (last release March 2026 per upstream README). |

### Alternatives Considered & Rejected

| Instead of | Could Use | Tradeoff | Verdict |
|------------|-----------|----------|---------|
| Custom pyyaml `SafeLineLoader` | `ruamel.yaml` `YAML(typ='rt')` | Adds ~1MB dep, requires *round-trip* loader (heavier, comment-preserving), but gives richer `lc` API including per-key positions (`obj.lc.key('story_points')`). | **Rejected for Phase 1.** Custom subclass is 5–15 LoC, no dep, sufficient for `<file>:<line>: <field-path>` granularity. Revisit if/when we need column-level pointers. |
| `charset-normalizer` | `chardet` | chardet 7.0+ relicensed LGPL→MIT but **the relicensing is publicly disputed by the original author** (see charset-normalizer README footnote, March 2026). Earlier chardet versions are LGPL-2.1, restrictive. | **Rejected.** charset-normalizer is MIT, already transitive, and the project's MIT license (per `pyproject.toml`) makes the LGPL/disputed-license risk avoidable. |
| `rapidfuzz` for did-you-mean | stdlib `difflib` | rapidfuzz is faster and has more algorithms but is a C-extension dep for a feature that runs at most a few dozen times during a single validation pass. | **Rejected (G-5).** stdlib `difflib.get_close_matches` is fine. |
| `tomli`/`json` schemas | Pydantic-only | Already using Pydantic; no benefit. | **Rejected.** Stay Pydantic. |
| Lockfile / fcntl for concurrent-run protection | (current: nothing) | Single-PO tool; deferred per CONTEXT.md. | **Out of scope.** |

### Installation diff

```toml
# pyproject.toml — add to dependencies
"charset-normalizer>=3,<4",  # Already transitive via requests; pinned directly for IMPT-01
```

No other dependency changes. ruamel.yaml is **not** added.

---

## Architecture Patterns

### Module layout (extension of existing layout)

```
jiramator/
├── config.py             # Pydantic models (existing) — minor changes only
├── yaml_loader.py        # NEW: SafeLineLoader subclass + pydantic-loc → line resolver
├── error_format.py       # NEW: ConfigValidationError + format_error() + did-you-mean helpers
├── run_report.py         # NEW: RunReport dataclass + atomic JSON IO + resume discovery
├── encoding.py           # NEW: BOM-first → UTF-8 → charset-normalizer fallback chain
├── spreadsheet.py        # MODIFIED: _read_csv calls encoding.detect_and_open()
├── planner.py            # MODIFIED: emits report incrementally; consumes resume state
├── importer.py           # MODIFIED: emits report; consumes resume state
└── cli.py                # MODIFIED: --resume, --report, --encoding, --force flags

tests/
├── fixtures/             # NEW (currently empty per CONCERNS.md): YAML-error fixtures + CSV samples
└── test_*.py             # NEW: test_yaml_loader, test_error_format, test_run_report, test_encoding
```

### Pattern 1: Line-aware YAML loading (Q1 resolution)

**What:** Subclass `yaml.SafeLoader`, override `construct_mapping`/`construct_sequence` to inject `__line__` markers using `node.start_mark.line + 1`.

**When to use:** At both `config.py:159` (`load_org_config`) and `config.py:380` (`load_team_config`) — the only YAML entry points.

**Why this works:** PyYAML's `Node` instances carry `start_mark` and `end_mark` attributes (line/column tuples) regardless of loader type — these are populated during the *parse* phase, not the *construct* phase. The SafeLoader-subclass pattern is the canonical StackOverflow answer (~30 upvotes, since 2018) for "PyYAML + line numbers."

**Example (verified executing on this system):**

```python
# jiramator/yaml_loader.py
from __future__ import annotations
import yaml

LINE_KEY = "__line__"  # special key injected into every mapping

class SafeLineLoader(yaml.SafeLoader):
    """PyYAML SafeLoader that records 1-indexed source line on every mapping."""

    def construct_mapping(self, node, deep=False):
        mapping = super().construct_mapping(node, deep=deep)
        mapping[LINE_KEY] = node.start_mark.line + 1  # 1-indexed
        return mapping

def safe_load_with_lines(stream) -> object:
    return yaml.load(stream, Loader=SafeLineLoader)
```

**Pydantic-loc → line resolver:**

```python
# jiramator/yaml_loader.py (continued)
def resolve_line(raw: object, loc: tuple[int | str, ...]) -> int | None:
    """Walk the raw (loaded) tree following Pydantic's `loc` tuple, returning
    the line number of the deepest mapping reached. Returns None on failure.

    `loc` example: ('teams', 0, 'tickets', 3, 'fields', 'story_points')
    """
    node = raw
    last_line: int | None = None
    for step in loc:
        if isinstance(node, dict):
            if LINE_KEY in node:
                last_line = node[LINE_KEY]
            if step in node:
                node = node[step]
            else:
                # field doesn't exist on parent (e.g., extra-not-allowed) —
                # report parent's line, which we already captured.
                break
        elif isinstance(node, list) and isinstance(step, int) and 0 <= step < len(node):
            node = node[step]
        else:
            break
    # If we ended on a mapping, prefer its line over its parent's.
    if isinstance(node, dict) and LINE_KEY in node:
        last_line = node[LINE_KEY]
    return last_line
```

**Strip the marker before Pydantic sees it:**

Two clean options — pick one in the planner:
1. Add `model_config = ConfigDict(extra="ignore")` to all Pydantic models so `__line__` is silently dropped. Simplest.
2. Recursively strip `__line__` from the raw dict before `OrgConfig(**raw)` / `TeamConfig(**raw)`. More explicit.

**Recommendation:** Option 1 (ConfigDict extra=ignore on the *root* models only) — Pydantic 2 already accepts `extra="ignore"` and this is the lowest-friction change. The internal `dict[str, Any]` fields (e.g. `EpicTemplate.fields`, `BulkCreateConfig.defaults`) will still contain `__line__` keys, which **must** be stripped during ticket-payload generation in `ticket_builder.py`. **This is the single biggest implementation risk for Q1** — the planner should make stripping `__line__` from all `Any`-typed leaf dicts an explicit task with test coverage.

### Pattern 2: Error format

```python
# jiramator/error_format.py
from __future__ import annotations
import difflib
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class ConfigValidationError(Exception):
    """Raised by load_*_config; rendered by cli.py."""
    file: Path
    line: int | None
    field_path: str        # e.g. "teams[0].tickets[3].fields.story_points"
    reason: str
    suggestion: str | None = None  # "(did you mean 'sprint_num'?)"

    def __str__(self) -> str:
        rel = self._relative_to_cwd()
        line_part = f":{self.line}" if self.line is not None else ""
        suffix = f" {self.suggestion}" if self.suggestion else ""
        return f"{rel}{line_part}: {self.field_path} — {self.reason}{suffix}"

    def _relative_to_cwd(self) -> str:
        try:
            return str(self.file.resolve().relative_to(Path.cwd()))
        except ValueError:
            return str(self.file)


def format_loc(loc: tuple[int | str, ...]) -> str:
    """('teams', 0, 'tickets', 3, 'fields', 'story_points')
       -> 'teams[0].tickets[3].fields.story_points'"""
    parts: list[str] = []
    for step in loc:
        if isinstance(step, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{step}]"
            else:
                parts.append(f"[{step}]")
        else:
            parts.append(str(step))
    return ".".join(parts)


def did_you_mean(value: str, candidates: list[str], *, n: int = 3, cutoff: float = 0.7) -> str | None:
    """Return ' (did you mean X?)' or ' (closest matches: X, Y)' or None."""
    matches = difflib.get_close_matches(value, candidates, n=n, cutoff=cutoff)
    if not matches:
        return None
    if len(matches) == 1:
        return f"(did you mean '{matches[0]}'?)"
    return f"(closest matches: {', '.join(matches)})"
```

### Pattern 3: Run report dataclass + atomic write

```python
# jiramator/run_report.py
from __future__ import annotations
import json
import os
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Any

SCHEMA_VERSION = 1
RUNS_DIR = Path(".jiramator/runs")

IssueStatus = Literal["created", "skipped", "failed", "pending"]
RunStatus = Literal["success", "partial", "failed"]

@dataclass
class IssueResult:
    template_key: str         # e.g. "epic:bau" or "per_release[2]:v26.1.1"
    kind: Literal["epic", "per_release", "per_sprint", "imported"]
    status: IssueStatus
    jira_key: str | None = None
    error: str | None = None  # human-readable; never a stack trace

@dataclass
class RunReport:
    schema_version: int = SCHEMA_VERSION
    command: list[str] = field(default_factory=list)  # sys.argv-style; NEVER env values
    started_at: str = ""                               # ISO8601 UTC
    ended_at: str | None = None
    team_config_path: str = ""                         # absolute, resolved
    org_config_path: str = ""
    team_name: str = ""
    pi_label: str | None = None
    versions: list[str] = field(default_factory=list)
    resolved_config_hash: str = ""                     # sha256 hex
    status: RunStatus = "failed"
    counts: dict[str, int] = field(default_factory=lambda: {"created": 0, "skipped": 0, "failed": 0})
    issues: list[IssueResult] = field(default_factory=list)
    # NOTE: no credentials, no full payloads, no env values.

    def to_envelope(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "run": asdict(self)}

    @classmethod
    def from_envelope(cls, obj: dict[str, Any]) -> "RunReport":
        if obj.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported run report schema_version: {obj.get('schema_version')}; "
                f"this version of jiramator only reads schema_version={SCHEMA_VERSION}."
            )
        run = obj["run"]
        run["issues"] = [IssueResult(**i) for i in run.get("issues", [])]
        return cls(**run)


def write_report_atomic(report: RunReport, path: Path) -> None:
    """Write JSON via tmp file + os.replace — atomic on POSIX/Windows.

    Called after every state change in the create path so the file always
    reflects reality if the process crashes (G-4).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report.to_envelope(), f, indent=2, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic rename
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def default_report_path(team_config_path: Path) -> Path:
    """`.jiramator/runs/<UTC-timestamp>-<team-slug>.json`."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = team_config_path.stem.replace("/", "_")
    return RUNS_DIR / f"{ts}-{slug}.json"


def find_resumable(team_config_path: Path) -> Path | None:
    """Most-recent partial/failed report whose team_config_path matches.

    Match rule: resolved-absolute team_config_path equality (Q3 resolution).
    """
    if not RUNS_DIR.exists():
        return None
    target = str(team_config_path.resolve())
    candidates: list[tuple[str, Path]] = []
    for p in RUNS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            run = data.get("run", {})
            if run.get("status") in ("partial", "failed") and run.get("team_config_path") == target:
                candidates.append((run.get("started_at", ""), p))
        except (OSError, json.JSONDecodeError, KeyError):
            continue  # skip malformed; never abort discovery
    if not candidates:
        return None
    candidates.sort(reverse=True)  # most recent first by ISO8601 lexicographic
    return candidates[0][1]
```

### Pattern 4: Resume diff-the-report logic

```python
# Sketch — for ticket_builder/planner integration
def filter_already_created(payloads: list[dict], prior_report: RunReport) -> list[dict]:
    """Return the subset of payloads whose template_key is NOT in prior.issues
    with status='created'. Skipped/failed/pending are RETRIED."""
    done = {i.template_key for i in prior_report.issues if i.status == "created"}
    return [p for p in payloads if p["_template_key"] not in done]
```

The `_template_key` annotation must be added to every payload in `ticket_builder.build_all()` and stripped before sending to Jira (same pattern as the existing `_sprint_num` metadata at `planner.py:298`).

### Pattern 5: Encoding fallback chain

```python
# jiramator/encoding.py
from __future__ import annotations
import codecs
from pathlib import Path
from typing import TextIO

# BOM signatures, ordered longest-first (UTF-8-SIG=3 bytes, UTF-16=2 bytes)
_BOM_TABLE = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),     # Python's "utf-16" handles either-endian when BOM present
    (codecs.BOM_UTF16_BE, "utf-16"),
)

def detect_encoding(path: Path, *, override: str | None = None) -> str:
    """Return the encoding name to use for `open(path, encoding=...)`.

    Pipeline:
      1. If `override` is set (--encoding flag), trust it.
      2. Read first 4 bytes; if a known BOM signature, return that encoding.
      3. Try strict UTF-8 decode of the whole file; if it succeeds, return 'utf-8'.
      4. Fall back to charset-normalizer's best match.
    """
    if override:
        return override
    with path.open("rb") as f:
        head = f.read(4)
    for sig, enc in _BOM_TABLE:
        if head.startswith(sig):
            return enc
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    from charset_normalizer import from_bytes
    best = from_bytes(raw).best()
    if best is None:
        raise ValueError(
            f"Could not detect encoding for {path}. "
            f"Re-save as UTF-8 or pass --encoding <name> (e.g. cp1252)."
        )
    return best.encoding
```

Then `_read_csv` becomes:

```python
def _read_csv(path: Path, *, max_rows: int | None = None, encoding_override: str | None = None) -> list[dict[str, str]]:
    enc = detect_encoding(path, override=encoding_override)
    if enc != "utf-8":
        # DC-1: stderr-only announcement
        from rich.console import Console
        Console(stderr=True).print(f"Read {path} as {enc}")
    with path.open(newline="", encoding=enc) as handle:
        reader = csv.DictReader(handle)
        ...  # existing logic unchanged
```

### Anti-patterns to Avoid

- **Rich-decorating the FOUND-01 error string.** Format must be plain text per DC-1 + `<specifics>`; pipeable to `grep`.
- **Aggregating Pydantic errors into a single message before exit.** Fail-fast is locked. Aggregation breaks the line-resolver's complexity budget and conflicts with the "compiler convention" goal.
- **Writing the report only at end-of-run.** Persist-on-error is mandatory (G-4). Every state change writes (atomically).
- **Storing full Jira payloads or response bodies in the report.** DC-2 + leaks risk. Store template-key → jira-key (or template-key → error string) only.
- **Trusting `node.start_mark` lines without `+ 1`.** PyYAML start marks are 0-indexed; users expect 1-indexed lines.
- **Querying Jira to detect duplicates during resume** (G-1). Resume reads the report only.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Encoding detection beyond BOM | A homemade cp1252-vs-cp1254-vs-mac_roman heuristic | `charset_normalizer.from_bytes(raw).best()` | These encodings share most code points; distinguishing them requires the kind of n-gram + language-coherence analysis charset-normalizer does. (Empirical: in our test, charset-normalizer correctly distinguished cp125x from UTF-16-LE-with-BOM, though it returned cp1250 for a cp1252 sample — close enough that the detector + override-flag combination is sound, while a naive heuristic would do worse.) |
| YAML node line tracking | Re-implement YAML's `Mark` machinery or grep the source | PyYAML's `node.start_mark.line` already exists | Node positions come from the parser, not a layer on top. They're already there; just expose them via the `SafeLoader` subclass. |
| Atomic JSON file writes | `with open(..., "w"): json.dump(...)` (truncates on entry — crash leaves empty file) | `tempfile.mkstemp` → write → `os.fsync` → `os.replace` | `os.replace` maps to POSIX `rename(2)` and Windows `MoveFileEx(MOVEFILE_REPLACE_EXISTING)` — both atomic. |
| Did-you-mean fuzzy match | Levenshtein distance loop | `difflib.get_close_matches(s, candidates, n=3, cutoff=0.7)` | Stdlib; uses Ratcliff/Obershelp `SequenceMatcher.ratio()`; what `pip install` uses for the "did you mean X?" prompt. |
| Resume-state ID generation | UUIDs / timestamps / monotonic counters | The team-config absolute path **and** SHA-256 of canonical-JSON resolved config | Path is the natural human key (matches mental model "the run for *this* team"); hash protects against silent drift. (Q3.) |
| Pydantic error pretty-printing | Custom rendering of `e.errors()` | The code in `error_format.py` above + `loc` resolver | Pydantic 2 has no built-in `<file>:<line>: <field> — <reason>` formatter; this is what every CLI tool re-implements (mypy, ruff, etc., all in their own way). |
| JSON-Schema validation of the report envelope | jsonschema dependency | Pydantic dataclass + `from_envelope(...)` constructor that raises on `schema_version != 1` | Pydantic is already in deps; adding jsonschema for one envelope check is overkill (G-5). The dataclass *is* the schema for now; export `.planning/codebase/run-report-schema.json` as docs if Phase 3 needs it. |

**Key insight:** Each item above is a place where a "small" custom solution looks tempting (50 lines max) but reproduces logic that has been wrong in the wild before — atomic writes especially are a frequent source of partial-state corruption when junior implementers think `with open("w")` is enough.

---

## Common Pitfalls

### Pitfall 1: `__line__` leaking into Pydantic-validated `dict[str, Any]` fields

**What goes wrong:** `EpicTemplate.fields: dict[str, Any]` and `BulkCreateConfig.defaults: dict[str, Any]` accept arbitrary content. The SafeLineLoader injects `__line__` into *every* mapping, including these inner dicts. Pydantic accepts it (since the type is `Any`), but downstream code in `ticket_builder.py` will then send `__line__: 23` as a Jira field value — corrupting tickets.

**Why it happens:** The marker key is invisible in the YAML source; only the loader knows it's there. Pydantic doesn't strip it because the field type is permissive.

**How to avoid:**
- Add a `_strip_line_markers(d: dict) -> dict` pure helper called recursively on every `fields` / `defaults` dict, either in the loader (post-parse, pre-Pydantic) or in `ticket_builder.build_all()` before payload assembly.
- Test: a fixture YAML with deeply-nested `fields` that round-trips through `build_all()` without `__line__` appearing in any payload.

**Warning sign:** Any test or live ticket where a field named `__line__` appears in the Jira payload preview.

**This is the #1 implementation risk and warrants a dedicated planner task with explicit test coverage.**

### Pitfall 2: BOM-less UTF-16 (treated as garbage by charset-normalizer)

**What goes wrong:** Some Excel exports produce UTF-16-LE *without* a BOM. charset-normalizer's heuristics handle it eventually but with low confidence — and Python's `"utf-16"` codec *requires* a BOM (raises on its absence). The fallback path is fragile.

**Why it happens:** PowerShell's `Out-File` historically wrote BOM by default; Excel "CSV UTF-16" sometimes does, sometimes doesn't, depending on version.

**How to avoid:** Document the `--encoding utf-16-le` (no BOM) override clearly in the encoding-error message: when detection fails, the error must say *which encoding override to try*, not just "couldn't detect."

### Pitfall 3: Pydantic loc tuple ending on a non-existent key (extra/missing fields)

**What goes wrong:** For `extra="forbid"` errors, Pydantic's `loc` ends with the disallowed key name, but that key doesn't exist in the parsed YAML mapping (we'd be reporting `__line__` of the *parent*, not the offender). For `missing` errors, similarly, the key doesn't exist in source at all.

**Why it happens:** Line numbers can only point at things that exist. The deepest extant mapping line *is* the right answer (it's what users would search for), but the resolver must handle this case without crashing.

**How to avoid:** The `resolve_line()` resolver above breaks early when a step doesn't exist and returns the parent's line. Test fixtures must exercise both `extra-not-allowed` and `missing-required` cases.

### Pitfall 4: Resume not idempotent on epic ref-key drift

**What goes wrong:** A user's first run creates `epic:bau` → `CA-5001`, then crashes. Before resuming, they edit the team YAML to rename the ref key from `bau` to `business_as_usual`. The hash check catches this (good), but if the user passes `--force`, the resume now treats `business_as_usual` as a fresh ref (not in the prior report's `created` set) and creates a duplicate epic. Meanwhile `CA-5001` is orphaned.

**Why it happens:** Template-key is the resume identifier, and renames invalidate it. The strict-drift check exists for exactly this reason — the planner must make the user-facing error message clear that `--force` skips this safety, and the docs should explicitly recommend "if you renamed a ref, just put the existing key into `existing_epics` and rerun without `--resume`."

**How to avoid:** The hash-mismatch error message names the renamed/changed fields where possible (diff the prior `resolved_config_hash` against current — if expensive, at minimum say "config has changed; this run cannot be resumed safely. Inspect `<report-path>` to recover created keys, or use `--resume --force` if you understand the risk").

### Pitfall 5: charset-normalizer's `cp1252` → `cp1250` confusion

**What goes wrong:** Empirically (on this machine), a sample with smart quotes, em-dash, `£`, `°`, curly apostrophes — all cp1252-encoded — was detected as `cp1250` by charset-normalizer 3.4.7. cp1250 differs in a handful of bytes (notably `0xA3` → Ł vs £), so the decoded text is *almost* right but corrupts a few characters.

**Why it happens:** The two encodings share most byte→char mappings; charset-normalizer's heuristic guess based on letter-frequency coherence can swing either way for short files.

**How to avoid:**
- The `--encoding cp1252` override is the primary mitigation. The error path / announcement banner should be visible enough that a user sees `Read foo.csv as cp1250` and can re-run with `--encoding cp1252` if they get scrambled output.
- For Phase 1 acceptance, a corpus test should exercise actual Windows-Excel exports and accept *either* `cp1252` or `cp1250` as "passes IMPT-01" provided the round-tripped content is the user's data (with the warning visible). Going further (BOM-injection, language hints) belongs in v2 if needed.

### Pitfall 6: `os.replace` across filesystems

**What goes wrong:** If `.jiramator/runs/` is on a different filesystem from `tempfile.mkstemp`'s default location (which by default uses `$TMPDIR`), `os.replace` raises `OSError: [Errno 18] Invalid cross-device link`.

**How to avoid:** Pass `dir=path.parent` to `tempfile.mkstemp` so the tmp file lives on the same filesystem as the destination. Already shown in the example above. Test this with a fixture pinned to a tmpdir different from the report dir.

### Pitfall 7: Resume's "auto-discover most recent" false-positive

**What goes wrong:** User runs `plan` against `team-a.yaml`, it crashes with status=`failed`. They then do an unrelated `plan` against `team-b.yaml`, succeed, and a few weeks later run `plan -t team-a.yaml --resume`. If `find_resumable()` keys on filename stem, a stale `team-a` report from another directory could match.

**How to avoid:** Key on `Path.resolve()` (absolute, symlinks resolved). Documented above in `find_resumable`.

---

## Code Examples

### Example 1: Catching Pydantic ValidationError → ConfigValidationError

```python
# In jiramator/config.py, replacing the existing load_team_config
def load_team_config(path: str | Path) -> TeamConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigValidationError(
            file=path, line=None, field_path="<file>",
            reason=f"Team config not found: {path}",
        )
    with open(path) as f:
        try:
            raw = safe_load_with_lines(f)
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark else None
            raise ConfigValidationError(
                file=path, line=line, field_path="<yaml>",
                reason=f"YAML parse error: {exc.problem if hasattr(exc, 'problem') else exc}",
            )

    if not isinstance(raw, dict):
        raise ConfigValidationError(
            file=path, line=1, field_path="<root>",
            reason=f"Team config must be a YAML mapping, got {type(raw).__name__}",
        )

    try:
        return TeamConfig(**raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = first["loc"]
        line = resolve_line(raw, loc)
        field_path = format_loc(loc)
        suggestion = _suggest_for_loc(raw, loc)  # consults known sets per field
        raise ConfigValidationError(
            file=path, line=line, field_path=field_path,
            reason=first["msg"], suggestion=suggestion,
        )
```

### Example 2: Resume command flow in cli.py

```python
# cli.py — sketched additions to plan command
@click.option("--resume", "resume_arg", flag_value="auto", default=None,
              is_flag=False, flag_value="auto",
              help="Resume the most-recent partial/failed run for this team. Pass a path to override.")
@click.option("--report", "report_path", type=click.Path(path_type=Path), default=None,
              help="Override default report path (.jiramator/runs/<ts>-<slug>.json).")
@click.option("--force", "force", is_flag=True, default=False,
              help="With --resume: ignore config-drift hash mismatch.")
def plan(...):
    ...
    prior_report: RunReport | None = None
    if resume_arg:
        if resume_arg == "auto":
            found = find_resumable(team_config_path)
            if found is None:
                console.print(f"[red bold]Error:[/] No resumable run found for {team_config_path} in {RUNS_DIR}/")
                sys.exit(1)
            prior_report = RunReport.from_envelope(json.loads(found.read_text()))
        else:
            prior_report = RunReport.from_envelope(json.loads(Path(resume_arg).read_text()))

    # later, after building resolved config:
    current_hash = compute_resolved_hash(org_config, team_config, pi_label, versions)
    if prior_report and prior_report.resolved_config_hash != current_hash and not force:
        console.print(
            f"[red bold]Resume aborted:[/] config has changed since the prior run.\n"
            f"  prior hash: {prior_report.resolved_config_hash[:12]}\n"
            f"  current hash: {current_hash[:12]}\n"
            f"  Pass --resume --force to override (use with care; may create duplicates)."
        )
        sys.exit(1)
```

### Example 3: Resolved-config hash

```python
# jiramator/run_report.py
import hashlib
import json

def compute_resolved_hash(org_config, team_config, pi_label, versions) -> str:
    """SHA-256 of canonical-JSON of the resolved-merged config view.

    Includes: pi_label, versions, team_name, project_key, all template summaries
    & fields, epic-ref keys, sprint config, custom_fields mapping. Excludes:
    credentials, env var values, file paths, timestamps.
    """
    payload = {
        "pi_label": pi_label,
        "versions": versions,
        "team_name": team_config.team_name,
        "project_key": team_config.project_key,
        "existing_epics": team_config.existing_epics,
        "recurring_epics": [
            {"key": e.key, "summary": e.summary, "fields": _strip_line_markers(e.fields)}
            for e in team_config.recurring_epics
        ],
        "per_release_tickets": [t.model_dump() for t in team_config.per_release_tickets],
        "per_sprint_tickets": [t.model_dump() for t in team_config.per_sprint_tickets],
        "custom_fields": org_config.custom_fields,
        "sprints": org_config.sprints.model_dump(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `chardet` for encoding detection | `charset-normalizer` | requests 2.32+ (May 2024) made it the default; charset-normalizer 3.x is the actively maintained option as of March 2026 | MIT license (vs LGPL/disputed), better cp125x accuracy, smaller wheel. |
| Hand-formatted Pydantic errors | Tool-specific formatters per CLI (mypy/ruff/etc. each roll their own) | n/a — Pydantic 2 has no canonical formatter | Implementing the loc → line resolver is genuinely on us; there's no library to delegate to. |
| `pyyaml` `Loader=yaml.Loader` (unsafe) | `pyyaml` `SafeLoader` subclass / ruamel.yaml `typ='safe'` | PyYAML 5.1 (2019) deprecated unsafe default | Already on `yaml.safe_load`; subclass extends safety. |
| `os.rename` for atomic-replace | `os.replace` | Python 3.3+ (2012) | `os.replace` works on Windows where `os.rename` raised on existing dest. |
| `fcntl.lockf` lockfiles for concurrent runs | (deferred) | n/a | Out of scope; revisit if multi-PO concurrency materializes. |

**Deprecated / outdated:**
- `chardet < 7.0`: LGPL-2.1, slower, smaller encoding coverage. **Don't use.**
- `ruamel.yaml typ='safe'` if you want `lc`: as of 0.18.x **does not** populate `lc`. Use `typ='rt'` or stick with pyyaml subclass. (Empirically verified.)
- Older PyPI packages calling themselves `pyyaml-include`, `yaml-include` etc.: not relevant here.

---

## Open Questions

### Resolved (research provided answers)

- **Q1 — YAML line-position capture**: **pyyaml `SafeLoader` subclass.** Not ruamel.yaml. Reasoning: ruamel.yaml's `lc` is only available via `typ='rt'` (round-trip), not `typ='safe'` — empirically verified. The `typ='rt'` loader is a much heavier dependency (~1MB; comment-preserving subclasses of dict/list) for what amounts to one extra attribute (`lc.key('foo')`) we don't strictly need. The SafeLoader subclass is 5–15 LoC, zero new deps, and gives us per-mapping line numbers — sufficient for `<file>:<line>: <field-path> — <reason>`. Confidence: **HIGH** (verified by execution + documented behavior). Carries Pitfall 1 risk (the `__line__` leak) which the planner must mitigate.

- **Q2 — Encoding detection library**: **charset-normalizer**, pinned directly in `pyproject.toml`. It's already transitive via `requests` (verified: `requests 2.33.1` → `charset_normalizer<4,>=2`), so install footprint is zero. MIT licensed (vs chardet's disputed re-license). Empirically distinguishes BOM-flagged UTF-16 + UTF-8-SIG perfectly; on bare cp1252 it can return cp1250 (close-but-not-identical sister encoding) — this is acceptable given the `--encoding` override and the loud stderr announcement (`Read foo.csv as cp1250`) makes the assumption visible. Confidence: **HIGH**.

- **Q3 — Resume scoping**: **Match by `Path.resolve()` of `--team-config`** for auto-discovery, with the SHA-256 resolved-config hash as the strict-drift gate. Reasoning: this matches the user's mental model ("the run for *this* file"), survives renames within the YAML (team `name` field can change without breaking resume), and pressure-tested against G-2 (no interactive prompts — auto-discovery either finds exactly one candidate or errors out). Prior art: dbt keys on project name + target; Terraform keys on backend-configured workspace; both treat the path/identifier as primary and use a state hash for safety, which is what we're doing. When no candidate is found: `Error: no resumable run found for <resolved-path> in .jiramator/runs/. Use --resume <path> to specify explicitly, or run without --resume to start fresh.` Confidence: **MEDIUM** — no single canonical answer in the ecosystem, but path+hash is the pattern with the fewest sharp edges.

- **Q4 — Did-you-mean budget**: **`difflib.get_close_matches(word, candidates, n=3, cutoff=0.7)`**. Phrasing: `(did you mean 'X'?)` for a single match, `(closest matches: X, Y[, Z])` for 2–3. Reasoning: cutoff 0.6 is the stdlib default but produces noise (matches "kay" → "key" etc.); 0.7 is what `pip` uses for its package-name suggestion and what `attrs` uses internally. n=3 keeps the message short. The single-match phrasing matches Python's own NameError suggestion (PEP 657, 3.11+: `Did you mean: 'foo'?`). Confidence: **HIGH** — this is a presentation tweak; if telemetry later shows users want different cutoff, it's a one-line change.

### Genuine Gaps

| Question | Criticality | Recommendation |
|----------|-------------|----------------|
| Will `os.fsync` cost matter on slow disks across many incremental report writes? | Low | Accept-risk. A PI plan creates O(50–200) tickets; fsync cost is negligible against Jira API latency. If Phase 3 stress reveals contention, batch writes per-phase rather than per-issue. |
| What if the resolved-config hash is unstable due to dict ordering or float repr? | Medium | Spike (small): write a 5-line test that loads the same YAML twice and asserts hash equality. The `json.dumps(..., sort_keys=True)` approach above guards this; the test is cheap insurance and belongs in the planner's verification step. |
| Should the `--resume` schema accept `schema_version: 1` only, or also load `schema_version: 0` if we ever produce one? | Low | Accept G-3 strictly: schema_version 1 is the contract; other versions error. A migration step belongs to a future schema_version 2 plan. |

### Still Open

- The exact wording of the encoding banner (`Read X as Y` vs `Detected encoding: Y for X` vs other). Punted to Claude's Discretion per CONTEXT.md — recommend the shortest form (`Read X as Y`) for terseness.
- Whether the encoding-detection error (when even charset-normalizer fails) should suggest specific encodings to try. Recommend yes — `(try --encoding cp1252 or --encoding utf-16-le)`.

---

## Sources

### Primary (HIGH confidence)

- **Empirical verification on this machine** (`python3 -c "import requests; print(requests.__version__)"` → `2.33.1`; `importlib.metadata.requires('requests')` → `charset_normalizer<4,>=2`): confirms charset-normalizer transitivity for Q2.
- **Empirical execution** of `yaml.SafeLoader` subclass and `ruamel.yaml.YAML(typ='safe')` with identical input: confirms (a) SafeLoader subclass approach yields per-mapping line numbers; (b) ruamel.yaml `typ='safe'` returns plain dicts without `lc`; (c) ruamel.yaml `typ='rt'` (default) yields `CommentedMap` with `lc.key('foo')` API.
- **PyYAML official documentation / source** — `node.start_mark` / `start_mark.line` are exposed on every Node. (https://pyyaml.org/wiki/PyYAMLDocumentation)
- **Pydantic 2 official docs** — `ValidationError.errors()` returns list of dicts with `loc`, `msg`, `type`, `input`, `url`. (https://docs.pydantic.dev/latest/errors/errors/)
- **Python stdlib docs** — `os.replace` is atomic where filesystem supports rename(2); `codecs.BOM_*` are the canonical BOM byte sequences; `difflib.get_close_matches` signature/defaults. (https://docs.python.org/3/library/os.html, https://docs.python.org/3/library/difflib.html, https://docs.python.org/3/library/codecs.html)
- **charset-normalizer official README + docs** (https://charset-normalizer.readthedocs.io, https://github.com/jawah/charset_normalizer/blob/master/README.md) — confirms MIT license, March 2026 active maintenance, 99-encoding coverage, CLI + `from_bytes`/`from_path` API. README footnote documents the chardet 7.0+ relicensing dispute (corroborated 2025–2026).
- **ruamel.yaml official docs** (https://yaml.dev/doc/ruamel.yaml/detail/) — "collection objects (when read in via RoundTripParser) have an `lc` property" — explicitly states `lc` requires the round-trip parser. Matches our empirical finding.

### Secondary (MEDIUM confidence)

- **StackOverflow #13319067** — canonical `SafeLineLoader` pattern, ~30 upvotes, accepted answer cross-referenced by ruamel.yaml's author. Approach reused in pre-commit, copier, and several other Python config tools.
- **PEP 657** (Python 3.11 fine-grained error locations) — establishes the `Did you mean: 'X'?` phrasing for the stdlib; we mirror it.
- **pip source** — uses `difflib.get_close_matches` with cutoff=0.7 for package-name suggestions.

### Tertiary (LOW confidence — flagged for validation)

- Comparative claims about dbt and Terraform "keying state on path + hash" are generalizations from documentation reading rather than source-code spelunking. Confidence sufficient for the recommendation; if a future planner wants the exact analog, dbt's `target/` directory and Terraform's workspace state files would be the places to look.
- The "rapidfuzz is overkill for ~50 candidates" claim is a sizing intuition, not a benchmark. For Phase 1's known-set sizes this is fine.

---

## Knowledge Applied

Checked knowledge base (`.planning/knowledge/` and `~/.gsd/knowledge/`); both directories exist as scaffolding but contain **no `index.md`** and no entries (lessons, spikes, reflections all empty). No prior project knowledge to surface for this phase.

| Entry | Type | Summary | Applied To |
|-------|------|---------|------------|
| _(none)_ | _(none)_ | _(no entries in KB)_ | _(N/A — first phase, no accumulated wisdom)_ |

This phase will likely *generate* lessons (e.g. "the `__line__` leak pattern" once we hit it in implementation) which a future GSD reflect step should capture.

---

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — every dep is either already in `pyproject.toml` or empirically verified as transitively present + license-clear.
- Architecture (line resolver, atomic write, fallback chain): **HIGH** — patterns are stdlib-canonical or empirically tested on this system.
- Pitfalls: **HIGH** for #1 (`__line__` leak — verified the loader does inject), **HIGH** for #5 (cp1250/cp1252 confusion — empirically reproduced), **MEDIUM** for #4 and #6 (reasoned, not exhaustively tested).
- Q3 (resume scoping): **MEDIUM** — defensible, but the ecosystem has no single canonical answer; revisit if user feedback shows surprises.
- Q4 (did-you-mean): **HIGH** — small surface, easy to tune later.

**Research date:** 2026-04-28
**Valid until:** 2026-07-28 (90 days; deps are stable, recommended approach has been the standard since 2019)

---
*Phase 1 — Reliability & Robustness*
*Researcher: gsdr-phase-researcher*
