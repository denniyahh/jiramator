---
phase: 01-reliability-robustness
plan: 03
subsystem: run-report
tags: [dataclass, atomic-io, resume, sha256, schema-versioning, gitignore]
provides:
  - jiramator/run_report.py module exporting RunReport, IssueResult, ConfigDriftError, write_report_atomic, default_report_path, find_resumable, compute_resolved_hash, SCHEMA_VERSION, RUNS_DIR
  - Atomic-write semantics (tempfile + fsync + os.replace; survives Ctrl-C; cleans up on failure)
  - Schema-versioned envelope (schema_version=1) with explicit forward/backward incompatibility errors
  - Deterministic resolved-config hash (sha256 of canonical-json over org+team+pi+versions)
  - Resume discovery that survives corrupt JSON / missing keys / symlinks
  - ConfigDriftError as a distinct Exception subclass (not ValueError)
  - .jiramator/ gitignore entry so run reports never accidentally land in commits
affects: [reliability-robustness, plan-01-04-resume-integration]
tech-stack:
  added: []
  patterns:
    - tempfile.mkstemp(dir=parent) + fsync + os.replace atomic-write idiom
    - BaseException-catching cleanup (handles KeyboardInterrupt mid-write)
    - Pessimistic-default status (RunReport.status='failed' until explicitly flipped)
    - sha256(canonical-json with sort_keys=True, separators=(',',':'), ensure_ascii=False)
    - model_dump(mode='json') for type-stable serialization of Pydantic types
    - try/except per-file in find_resumable (single corrupt file does not block discovery)
    - Symlink-aware path comparison via .resolve() on both sides
key-files:
  created:
    - jiramator/run_report.py
    - tests/test_run_report.py
  modified:
    - .gitignore
key-decisions:
  - "Used @dataclass not Pydantic for IssueResult/RunReport. Pure data, no validation needed; saves an import and aligns with stdlib-only constraint."
  - "RunReport.status defaults to 'failed' (pessimistic). An interrupted process leaves the report marked failed unless it had time to flip status to 'success' at the end of a clean run. Test 25's ConfigDriftError-as-Exception choice is symmetric: both new exception types subclass Exception directly, distinguishable by isinstance."
  - "find_resumable wraps each candidate's load in a single broad try/except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError). TypeError added for the case where 'run' is present but not a dict (e.g., a list). Discovery never aborts on a single bad file."
  - "find_resumable resolves BOTH input team_config_path AND stored team_config_path before comparison. If the stored path is unreachable (e.g., relative-and-not-anchored), .resolve() falls back gracefully via the OSError catch and uses the literal stored string."
  - "default_report_path applies stem.replace('/', '_') for defense in depth. Path.stem already strips parents (so 'a/b/c.yaml'.stem is 'c'), but the replace protects against future surprises in stem semantics or weird input."
  - "compute_resolved_hash copies versions list (list(versions)) so a caller mutating the input after the call doesn't change determinism."
  - "ConfigDriftError docstring explicitly notes the subclass-of-Exception choice with rationale (cli.py needs to distinguish it from ConfigValidationError)."
duration: 30min
completed: 2026-04-29
---

# Plan 01-03: Run Report Substrate (FOUND-02) Summary

**Shipped the data substrate for `--resume` and run-report emission: schema-versioned envelope, atomic write, resume-discovery, and deterministic config hash. Zero callers yet — Plan 04 wires this into planner.py and importer.py.**

## Performance
- **Duration:** ~30min
- **Tasks:** 1 (with 25 tests)
- **Files modified:** 3 (1 new module, 1 new test file, 1 gitignore append)

## Accomplishments
- All 7 must-have truths from the plan satisfied:
  1. ✓ All public symbols import cleanly via the top-level `from jiramator.run_report import ...` path.
  2. ✓ `write_report_atomic` produces valid JSON with `{"schema_version": 1, "run": {...}}` envelope; T-01-10 verified by Test 8 (forced `os.replace` failure leaves original intact + no `.tmp` debris).
  3. ✓ `RunReport.from_envelope` raises ValueError naming both rejected and supported versions for schema 0 / 2 / missing.
  4. ✓ `default_report_path` produces `.jiramator/runs/<UTC-stamp>-<slug>.json` matching `^\d{8}T\d{6}Z-<slug>\.json$`.
  5. ✓ `find_resumable` returns the most-recent partial/failed report; survives corrupt JSON (T-01-11) and symlinks; returns None when no candidates.
  6. ✓ `compute_resolved_hash` is deterministic across two invocations and across reloads of the same YAML.
  7. ✓ `.jiramator/` is gitignored.
- 25 new tests, all passing first-try (no GREEN iteration needed — implementation followed the plan and RESEARCH.md Pattern 3 reference verbatim).
- Zero regressions: 341 baseline → **366 passing**.
- STRIDE T-01-10 (mid-write crash) and T-01-11 (corrupt JSON in runs dir) both mitigated and regression-tested.

## Task Commits
1. **Task 1: run_report module + .gitignore + 25 unit tests** — `656b71e`

## Files Created/Modified
- `jiramator/run_report.py` (NEW, ~270 lines incl. docstrings) — All public surface listed in the plan, stdlib-only.
- `tests/test_run_report.py` (NEW, ~340 lines, 25 tests across 6 test classes) — Envelope round-trip / atomic write / default_report_path / find_resumable / compute_resolved_hash / ConfigDriftError.
- `.gitignore` — appended `.jiramator/` under `# Run reports (FOUND-02)`.

## Decisions & Deviations
- **Decision (added robustness):** `find_resumable` catches `TypeError` in addition to the plan's listed exception types. Reason: if a malformed envelope has `"run"` set to a non-dict (e.g., a list or scalar), `.get(...)` would raise TypeError. The plan's set was `(OSError, json.JSONDecodeError, KeyError, ValueError)` — adding TypeError preserves the "single corrupt file does not block discovery" invariant against more shapes of garbage.
- **Decision (added robustness):** `find_resumable` also catches `OSError` from the inner `Path(stored_path).resolve()` call (e.g., if stored path triggers a symlink loop). Falls back to comparing the literal stored string. Documented inline.
- **Decision:** `write_report_atomic` uses `tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")`. The `prefix=path.name + "."` makes the temp file visually associated with the target during a debugging session (e.g., `out.json.abc123.tmp` next to `out.json`). The cleanup glob in Test 8 covers both `*.tmp` and `tmp*` to be safe across mkstemp's naming evolution.
- **Decision:** `Path("a/b/c.yaml").stem` is `"c"` — Path.stem strips the directory. The plan's slug spec `stem.replace("/", "_")` is therefore a no-op on this input but documented as defensive insurance against future Path semantics or weird input that bypasses Path normalization.
- **Deviation (none):** All 25 tests pass first-try; implementation followed the plan exactly.

## Next Phase Readiness
- Wave 1 complete: 3/3 plans done (01-01, 01-02, 01-03). All three plans had zero file overlap, so the parallel-safe assumption held.
- Plan 01-04 (Wave 2) can now `from jiramator.run_report import *` and use the data substrate without further additions to this module.
- Phase 1 progress: 3/5 plans complete. Wave 2 (01-04) and Wave 3 (01-05) remain.
- The atomic-write idiom (`tempfile.mkstemp + fsync + os.replace`) is now established in the codebase and can be reused by future modules that need crash-safe persistence.
