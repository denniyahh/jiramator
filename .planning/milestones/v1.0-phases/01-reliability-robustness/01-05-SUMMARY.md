---
phase: 01-reliability-robustness
plan: 05
subsystem: cli
tags: [click, cli, flags, run-report, resume, encoding, validation]

# Dependency graph
requires:
  - phase: 01-reliability-robustness/01-01
    provides: ConfigValidationError pre-formatted messages
  - phase: 01-reliability-robustness/01-02
    provides: read_spreadsheet(encoding_override=...) escape hatch
  - phase: 01-reliability-robustness/01-03
    provides: RunReport, default_report_path, find_resumable, ConfigDriftError, write_report_atomic
  - phase: 01-reliability-robustness/01-04
    provides: run_plan/run_import accept report_path/prior_report/force kwargs
provides:
  - "--report flag (Path) on plan and import commands"
  - "--resume flag (tri-state: absent | auto | explicit-path) on plan and import"
  - "--force flag to bypass resolved-config-hash drift on resume"
  - "--encoding flag on import command (IMPT-01 escape hatch)"
  - "ConfigValidationError catch-clause that bypasses Rich markup for pipeable plain-text stderr"
  - "ConfigDriftError catch-clause around run_plan with verbatim stderr"
  - "_load_prior_report helper resolving --resume into a RunReport"
  - "_load_report_file helper with friendly errors for missing/corrupt/incompatible reports"
  - "import command owns its run-report lifecycle (cli builds + finalizes RunReport; run_import only persists)"
affects: [02-02-batched-throughput, 02-03-batched-validation, future plans that surface user errors]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "click.option(is_flag=False, flag_value='auto') for tri-state flags (--resume bare vs --resume <path>)"
    - "click.echo(message, err=True) + sys.exit(1) for plain-text error reporting (DC-1)"
    - "Catch ConfigValidationError BEFORE legacy ValueError clause"

key-files:
  created:
    - tests/test_cli.py
    - tests/test_cli_e2e.py
  modified:
    - jiramator/cli.py

key-decisions:
  - "Hoist `from jiramator.planner import run_plan` to module level (was deferred inside plan()); enables monkeypatch-based unit tests of CLI wiring without invoking the real planner."
  - "Use `click.echo(err=True)` for ConfigValidationError messages (NOT `console.print`) so Rich's bracket-tag interpreter can't mangle field paths like `per_release[0].fields.priority` (DC-1: pipeable, plain-text)."
  - "import_command owns its RunReport lifecycle (build at start, status-flip + write_report_atomic at end). run_plan owns its lifecycle internally; the asymmetry is by design — planner has the build/preview/confirm flow that needs the report inside, importer has a flat per-row loop where cli is the natural lifecycle owner."
  - "Drift check for import: compute_resolved_hash(org, team, None, []) — pi_label=None and versions=[] mean import-side hashes never collide with plan-side hashes. Cross-resume between commands is impossible by construction. Correct."
  - "--resume value-binding: with `is_flag=False, flag_value='auto'`, Click greedily parses the next token after `--resume` as its value when one exists. For `import` (which has a positional spreadsheet arg), tests put `--resume` AFTER the positional. Plan command has no trailing positional so the issue doesn't arise. Documented inline in the test."
  - "_FakeResult in stub_run_import has empty row_results — combined with stubbing render_preview_report/render_import_execution_report to lambda returning '', this avoids needing to construct full PreviewReport / ImportRunResult objects for unit tests."
  - "FakeJiraClient duplicated inline in test_cli_e2e.py rather than extracted to tests/_fakes.py; the version here adds importer-surface methods (find_issue_keys_by_summaries, get_fields) absent from the planner-only fake. A future refactor could merge them, but the duplication is small and keeps tests independently readable."
  - "Patch JiraClient at BOTH `jiramator.cli.JiraClient` AND `jiramator.planner.JiraClient` (planner instantiates its own client at line 571). Single-site patch was insufficient — caught during E1 RED phase."

patterns-established:
  - "tri-state flag pattern: `is_flag=False, flag_value='auto', default=None, type=click.STRING`. Resolved by helper that returns None | discover-via-find_resumable | load-explicit-path."
  - "Plain-text stderr error reporting: `_fail(message)` helper that calls `click.echo(message, err=True); sys.exit(1)`. Used uniformly for ConfigValidationError, ConfigDriftError, missing-resume-report, parse-error, schema-mismatch."
  - "Persist-on-error in cli.import_command: try/except wraps run_import; on JiraApiError, ended_at + write_report_atomic happen before _fail (so the partial run is saved)."

requirements-completed: [FOUND-01, FOUND-02, FOUND-03, IMPT-01]

# Metrics
duration: ~30min
completed: 2026-04-30
---

# Plan 01-05: CLI Integration — All Phase 1 Requirements Surfaced

**Wires FOUND-01/02/03 + IMPT-01 into the user-facing CLI: `--report`, `--resume`, `--force`, `--encoding` flags plus pipeable plain-text error reporting for ConfigValidationError and ConfigDriftError.**

## Performance

- **Duration:** ~30 min
- **Tasks:** 2 completed (one cli.py rewrite + two test files)
- **Files modified:** 1 (jiramator/cli.py)
- **Files created:** 2 (tests/test_cli.py, tests/test_cli_e2e.py)
- **Commits:** 2 atomic commits

## Accomplishments

- All four Phase 1 requirements (FOUND-01, FOUND-02, FOUND-03, IMPT-01) reachable from `jiramator plan` and `jiramator import`.
- `jiramator plan --help` lists `--report PATH`, `--resume TEXT`, `--force`. `jiramator import --help` adds `--encoding TEXT` and the same trio.
- ConfigValidationError messages from FOUND-01 reach stderr in plain text — pipeable to `grep` / `cut` / `awk` without Rich markup tags polluting the stream.
- Full plan→report-on-disk→`--resume`→skip-already-created cycle works end to end (E1 test).
- Drift detection round-trips: mutate team config, `--resume` exits 1 with both hash prefixes; `--resume --force` overrides (E2 test).
- IMPT-01 escape hatch: `--encoding cp1252` round-trips smart-quote / em-dash / £ characters from disk to FakeJiraClient.create_issue payload (E3 test).

## Task Commits

1. **Task 1: plan command flags + ConfigValidationError + ConfigDriftError handlers** — `a9a8818` (feat)
2. **Task 2: import command flags + e2e tests** — `39c703b` (test)

_Note: cli.py mutations for both plan and import landed in Task 1's commit (single-pass rewrite); Task 2's commit adds the test coverage._

## Files Created/Modified

- `jiramator/cli.py` — rewritten: hoisted `run_plan` import; new helpers `_fail`, `_load_report_file`, `_load_prior_report`; `plan` command gains `--report`/`--resume`/`--force`; `import_command` gains `--encoding`/`--report`/`--resume`/`--force`; ConfigValidationError caught BEFORE ValueError; ConfigDriftError caught around run_plan; import_command owns its RunReport lifecycle (build → run → finalize → write_report_atomic).
- `tests/test_cli.py` — 20 unit tests via `CliRunner` + monkeypatch:
  - C1-C7: plan flag parsing (default report, `--report`, `--resume` auto/explicit, `--force` with/without `--resume`, no-resumable-found exit-1).
  - C8-C11: error handling (ConfigValidationError org/team, ConfigDriftError, legacy ValueError still works).
  - C12-C14: resume report loading errors (missing path, corrupt JSON, incompatible schema_version).
  - CI1-CI6: import command — `--encoding` threaded, `--report` written, `--resume` auto/explicit, ConfigValidationError handler.
- `tests/test_cli_e2e.py` — 3 end-to-end tests with FakeJiraClient + patched Rich prompts:
  - E1: full plan → report-on-disk → `--resume` → zero new create calls.
  - E2: drift detection (mutate team_name → `--resume` fails → `--force` overrides).
  - E3: import `--encoding cp1252` round-trip with `\u2014` em-dash + `\u00a3` £.

## Test Count Progression

- Before Plan 05: 394 passing
- After Task 1 (C1-C14): 408 (+14)
- After Task 2 (CI1-6, E1-3): **417 (+9 in this commit, +23 total for Plan 05)**
- Zero regressions throughout.

## Decisions Made

See `key-decisions` in frontmatter. Highlights:

- **Hoist `run_plan` to module level.** Was deferred inside `plan()` to avoid a stated circular-import worry; verified no actual cycle exists, hoisting unlocks monkeypatch-based unit tests of CLI wiring.
- **`click.echo` for validation errors, `console.print` for decorative output.** Rich's markup interpreter sees `[red]...[/]` in the decorative path but would mangle field paths like `per_release[0].fields.priority` if used for pre-formatted ConfigValidationError messages.
- **Asymmetric report lifecycle** (planner internal, importer cli-owned). Documented as deliberate; matches the asymmetry in their flow shapes (planner has build/preview/confirm, importer has a flat row loop).
- **Drift hash for import** uses `(org, team, None, [])` — never collides with plan-side hashes; cross-resume across commands is structurally prevented.

## Deviations from Plan

### Auto-fixed Issues

**1. Plan 05 spec for `--resume <positional>` order — Click `is_flag=False + flag_value` ambiguity**
- **Found during:** Task 2 RED phase (test_CI4)
- **Issue:** Plan invocation `import ... --resume sheet.csv` had Click consuming `sheet.csv` as the value of `--resume` rather than as the positional. Verified with isolated repro.
- **Fix:** In CI4, place `--resume` AFTER the positional spreadsheet path; documented inline. Real-user invocations follow the same convention.
- **Files modified:** tests/test_cli.py (CI4 only).
- **Verification:** Tests pass; pattern documented in test comment.

**2. CI fixtures expected `Summary` (capitalized) — field_resolver standard set is lowercase**
- **Found during:** Task 2 E3 RED phase
- **Issue:** field_resolver.py's standard_fields set contains `summary` (lowercase); E3 fixture used `Summary`.
- **Fix:** E3 fixture uses `summary` lowercase; documented inline. (A real user with a `Summary` column would need a `field_aliases` entry in their org config; this is correct existing behavior.)

**3. CliRunner `mix_stderr` removed in Click 8.2+**
- **Found during:** Task 1 first test run
- **Issue:** Click 8.3.2 removed `mix_stderr` kwarg (stdout/stderr separated by default).
- **Fix:** `CliRunner()` with no args; documented inline.

**Total deviations:** 3 auto-fixed (env/idiom/fixture). No scope creep.

## Issues Encountered

- **JiraClient single-site monkeypatch insufficient.** The first E1 RED run failed because `jiramator.planner` imports `JiraClient` directly and instantiates one at line 571 — patching only `jiramator.cli.JiraClient` left planner using the real class. Fixed by patching both sites in E1/E2.

## Phase 1 Readiness

**Plan 01-05 closes Phase 1 (Reliability & Robustness).** All five plans complete:

| Plan | Requirement(s) | Commit(s) |
|------|---------------|-----------|
| 01-01 | FOUND-01 (line-aware config errors) | (Wave 1) |
| 01-02 | IMPT-01 (encoding detection) | (Wave 1) |
| 01-03 | FOUND-02 substrate (run_report module) | (Wave 2) |
| 01-04 | FOUND-02 + FOUND-03 (planner + importer wiring) | 9af0d4f, 679388b, 9439625 |
| 01-05 | FOUND-01/02/03 + IMPT-01 (CLI surface) | a9a8818, 39c703b |

**Verification gate:** `pytest tests/` → 417 passing, 0 regressions. `jiramator plan --help` and `jiramator import --help` both list all expected flags. Ready for phase verification + (optionally) phase merge.

## Next Phase Readiness

- Phase 1 complete and stable; ready to run `gsd-sdk query roadmap.update-plan-progress 1 01-05 complete` and the phase verification gate.
- Future phases that surface user errors should follow the `_fail()` plain-text-stderr pattern established here — Rich is for decorative output only.

---
*Phase: 01-reliability-robustness*
*Completed: 2026-04-30*
