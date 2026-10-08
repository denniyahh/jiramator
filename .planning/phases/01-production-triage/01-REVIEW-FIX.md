---
phase: 01-production-triage
fixed_at: 2026-10-05T15:17:00Z
review_path: .planning/phases/01-production-triage/01-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-10-05T15:17:00Z
**Source review:** .planning/phases/01-production-triage/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (WR-01..WR-06; Info findings IN-* were out of scope)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### WR-01: The credential regex changes the "Basic Constraints" TLS error, the error this project most often needs to diagnose

**Files modified:** `jiramator/run_report.py`, `tests/test_run_report.py`
**Commit:** 74a3893
**Applied fix:** The regex now has a negative lookahead `(?!constraints\b)` after the scheme separator, which exempts the OpenSSL phrase "Basic Constraints of CA cert not marked critical". I chose this narrow exemption instead of the reviewer's ≥16-character token rule. That rule would have let `BEARER abc.def` (7 characters) and `basic dXNlcjp0b2s=` (12 characters) through, which would weaken WR-02. Every other word that follows a scheme is still redacted (over-redaction is the safe side). Test `test_32d` asserts that both the original-case and lower-case phrases come through unchanged.

### WR-02: The credential regex is case-sensitive and misses common header spellings

**Files modified:** `jiramator/run_report.py`, `jiramator/planner.py`, `jiramator/importer.py`, `jiramator/cli.py`, `tests/test_run_report.py`
**Commit:** 6db86ae
**Applied fix:** `_AUTH_CREDENTIAL_RE` is now `\b(basic|bearer)([\s:=]+)(?!constraints\b)[^\s'",;:=][^\s'",;]*` with `re.IGNORECASE`. The scheme and separator are kept and the token becomes `***`. The token's first character excludes the separator set, so backtracking can't shift the token start past the exemption. The fix adds a public `credential_secrets(org_config)` helper that returns the token plus `base64(email:token)`, the Basic credential `requests` sends. It replaces the three copied token lookups in planner, importer and cli, and their unused `os` imports were removed. Empirically, `authorization: basic dXNlcjp0b2s=` → `authorization: basic ***`, `BEARER abc.def` → `BEARER ***`, `Basic=dXNlcjp0b2s=` → `Basic=***`. Parametrized tests `test_32e` cover these plus `Basic:` and tab separators; `test_32f` covers the helper and the base64 literal. **This closes threat T-01-01**; `/gsd-secure-phase 01` should re-verify it.
**Note:** The WR-02 fix text prescribes the shared helper, so this commit also resolves IN-01 (copied token lookup) as a side effect. No other IN-* finding was touched.

### WR-03: The redaction promise covers only `run.error`; the same exception text is saved unredacted in `issues[].error`

**Files modified:** `jiramator/run_report.py`, `jiramator/planner.py`, `jiramator/importer.py`, `tests/test_planner_report.py`, `tests/test_importer_report.py`, `CHANGELOG.md`
**Commit:** bfaf5c4
**Applied fix:** `_sanitize_message` is now the public `sanitize_message(message, *, secrets=())`. The planner's epic and bulk `IssueResult(error=...)` sites use it. The importer's `_record` sanitizes every recorded `error`, which covers the API-failure row site and the build-failure rows. The tests check the plan epic and bulk paths and the import row path, asserting that the token appears nowhere in the written JSON. The CHANGELOG Unreleased INV-04 entry now says redaction covers the run-level message and the per-issue `error` strings in `plan`/`import` reports, lists the token, its base64 `email:token` form, and any-case `Basic`/`Bearer` credentials with whitespace, `:` or `=` separators, notes that the "Basic Constraints" diagnostic is preserved, and says each recorded message is capped.
**Residual (outside this finding's cited sites):** the `update` command's report (`cli._update_report_from_result`) still stores per-row `error` strings unsanitized. `update` is not part of INV-04, and that helper has no `org_config`. The CHANGELOG wording is scoped to `plan`/`import` accordingly.

### WR-04: The tolerant `from_envelope` changed a malformed-report failure from `TypeError` to `AttributeError`, so `_load_report_file` now crashes with a traceback

**Files modified:** `jiramator/run_report.py`, `tests/test_run_report.py`, `tests/test_cli.py`
**Commit:** 64822f5
**Applied fix:** `from_envelope` now raises `ValueError` when the envelope or `run` is not an object, when `run.issues` is not a list of objects, or when `run.error` is neither an object nor null. `_load_report_file` already catches `ValueError`. `test_28b` (7 malformed shapes) and the CLI test `test_C14b` check that `--resume` on `{"issues": ["bad"]}` exits 1 with "Resume report incompatible" and no traceback. C14b fails on the pre-fix code.

### WR-05: Abort messages don't match the console reason, and the preflight abort loses the problem list

**Files modified:** `jiramator/planner.py`, `tests/test_planner_report.py`
**Commit:** 9a304ca
**Applied fix:** For the fix-version decline, the code builds one `reason` string (`Cannot proceed without fix versions (declined creating: X).`). It prints it after `Aborted.` (Rich-escaped) and records the same string. The preflight abort now records `Found N field problem(s): p1; p2. No tickets were created.`, and the 2,000-character cap bounds it. Both functions gained a `secrets` kwarg, and the callers pass `credential_secrets`. Before this, these two `abort_info` calls passed no secrets, contrary to what 01-SECURITY.md T-01-01 claimed. The tests assert exact equality, compare against recorded console output, and check that the problem field ID appears in the report.

### WR-06: A failed report write in the crash handlers replaces the original exception, which breaks P-01-01

**Files modified:** `jiramator/planner.py`, `jiramator/importer.py`, `tests/test_planner_report.py`, `tests/test_importer_report.py`
**Commit:** 05e8786
**Applied fix:** In both `except BaseException` handlers, `_persist()` is wrapped in `try/except OSError: pass` before the bare `raise`. The tests `test_p10b` and `test_i7b` make the crash-handler write raise `OSError` and assert that the original `KeyboardInterrupt` still propagates. Both fail on the pre-fix code.

## Verification

- Where it ran: the **main checkout** (branch `gsd/phase-01-production-triage`). Per the orchestrator's instruction, I committed in place and created no isolated worktree, so the results reproduce from this tree.
- Per fix: re-read the changed code, ran `ruff check` and the targeted pytest files. For WR-04 and WR-06, confirmed the new tests fail with the fix stashed.
- Final: `.venv/bin/python -m pytest -q` → **698 passed** (baseline was 676; 22 new tests). `.venv/bin/ruff check .` → **All checks passed**. `ruff format` was not run.
- All commits carry the `Co-authored-by: Copilot` trailer. Nothing was pushed, and the work clone at ~/dev/work_projects/jiramator was not touched.
- WR-01/WR-02 involve regex logic. They are covered by explicit tests, but a human should still review the exemption choice (fixed: requires human verification).

---

_Fixed: 2026-10-05T15:17:00Z_
_Fixer: the agent (gsd-code-fixer)_
_Iteration: 1_
