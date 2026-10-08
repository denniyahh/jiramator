---
phase: 01-production-triage
reviewed: 2026-10-05T18:26:24Z
depth: standard
iteration: 2
files_reviewed: 11
files_reviewed_list:
  - CHANGELOG.md
  - jiramator/cli.py
  - jiramator/importer.py
  - jiramator/planner.py
  - jiramator/run_report.py
  - tests/conftest.py
  - tests/test_cli.py
  - tests/test_import_cli.py
  - tests/test_importer_report.py
  - tests/test_planner_report.py
  - tests/test_run_report.py
findings:
  critical: 0
  warning: 1
  info: 6
  total: 7
status: issues_found
---

# Phase 01: Code Review Report (re-review after fixes)

**Reviewed:** 2026-10-05T18:26:24Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Scope: `git diff develop...HEAD` (10 commits). That covers plan 01-01 (85e73f4, 7df134f, bd1b686), the
review-fix commits (74a3893, 6db86ae, bfaf5c4, 64822f5, 9a304ca, 05e8786) and dda6c1e (`update`
report redaction). The suite passes (`pytest -q`: 699 passed) and `ruff check .` is clean. I checked
the claims below by running code against the current tree, not just by reading it.

**Status of the previous findings:**

| ID | Status | Evidence |
|----|--------|----------|
| WR-01 | Resolved | `sanitize_message("…Basic Constraints of CA cert not marked critical")` comes back unchanged (both cases). |
| WR-02 | Resolved | `authorization: basic dXNlcjp0b2s=` → `authorization: basic ***`. `Basic=`, `Basic:`, tab and `BEARER` are redacted. `credential_secrets()` adds `base64(email:token)` and strips the same way as `OrgConfig.resolve_credentials()`, so the literal matches what `requests` sends. |
| WR-03 | Resolved | Planner epic and bulk `IssueResult.error`, importer `_record` and the `update` report rows all go through `sanitize_message`. |
| WR-04 | Resolved | `from_envelope` raises `ValueError` for a non-dict envelope or `run`, non-list or non-dict `issues`, and non-dict `error`. A missing required `IssueResult` key still raises `TypeError`, which `_load_report_file` already catches. |
| WR-05 | Resolved | The fix-version decline uses one `reason` for both the console and the report. The preflight record includes the full problem list. |
| WR-06 | Resolved (for the cited handlers) | Both `except BaseException` handlers swallow `OSError` from `_persist()`. The abort-site `persist()` calls are still unguarded (see IN-07). |
| IN-01 | Resolved | All three copies are replaced by `run_report.credential_secrets()`. |
| IN-02, IN-03, IN-04 | Still apply | See below. |

**New issues.** The WR-01/WR-02 fix chose to over-redact: every word after any standalone
"basic"/"bearer" is replaced. Because WR-05 now records full preflight problem lists and Jira messages,
this corrupts real diagnostics (WR-07). The rest are minor: the CHANGELOG makes compatibility claims the
code doesn't meet, the regex misses some credential spellings, and the abort-site writes are unguarded.
I found no blockers.

## Narrative Findings (AI reviewer)

## Warnings

### WR-07: The credential regex over-redacts ordinary text after "basic"/"bearer", which garbles Jira diagnostics and the new preflight problem list

**File:** `jiramator/run_report.py:209-212` (applied at `:255`). Affects every caller: `planner.py:520-527` (preflight list), `planner.py:990-995,1121-1129`, `importer.py:330-332`, `cli.py:234,245`
**Issue:** `\b(basic|bearer)([\s:=]+)(?!constraints\b)[^\s'",;:=][^\s'",;]*` with `IGNORECASE` treats *any* word after a standalone "basic"/"bearer" as a credential. The only exemption is "Constraints". I verified these outputs:
- `Basic authentication with passwords is deprecated. For more information, see: …` → `Basic *** with passwords is deprecated…`. Atlassian returns this message when someone uses a password instead of an API token. It is a real production auth failure, and the redaction removes the word that explains it.
- `Bearer token has expired` → `Bearer *** has expired`.
- `basic auth failed for user bob@example.com` → `basic *** failed …`.
- `invalid value Basic for field Tier` → `invalid value Basic *** field Tier`, and `customfield_10001 Basic: value must be one of Basic, Premium` → `Basic: *** must be one of …`.

WR-05 now writes the full preflight problem list into `run.error.message`, so select-option names that contain "Basic"/"Bearer" followed by a space are mangled in the report. Example: payload_validator's `'Tier' (customfield_X): value 'Basic Plus' is not one of the allowed options (Basic Plus, Premium)` becomes `Basic ***' … (Basic ***, Premium)`. That is the INV-04 information WR-05 was meant to keep. The redaction is also now redundant for the main threat. `credential_secrets()` already redacts the exact Jira token and its `base64(email:token)` form, so the regex only needs to catch *other* credentials, and those are token-shaped. The fix report rejected a length threshold because it would miss `BEARER abc.def`. But neither of those strings is a credential a Jira client would ever produce.
**Fix:** Redact a word only when it looks like a token, not like a word. For example, require at least one digit or one of `+/=._-`, or a length of at least 16, and keep the "constraints" exemption as an extra guard:
```python
_AUTH_CREDENTIAL_RE = re.compile(
    r"\b(basic|bearer)([\s:=]+)(?!constraints\b)"
    r"(?=[A-Za-z0-9+/=._~-]*(?:[0-9+/=._~-]|[A-Za-z]{16}))"
    r"[A-Za-z0-9+/=._~-]{6,}",
    re.IGNORECASE,
)
```
I tested this pattern. It still redacts `basic dXNlcjp0b2s=`, `BEARER abc.def`, `Basic=…`, `Basic:…` and tab separators, and it leaves the four examples above unchanged. One caveat: a word that ends in sentence punctuation, such as `Basic support.`, still matches, so consider trimming a trailing `.` before the check. Or require header context (`authorization["']?\s*[:=]\s*["']?(basic|bearer)\s+…`). Add regression tests asserting that `"Basic authentication with passwords is deprecated"`, `"Bearer token has expired"` and `"value 'Basic Plus' is not one of the allowed options"` come through unchanged, and keep the existing `dXNlcjp0b2s=` / `abc.def` redaction tests passing.

## Info

### IN-02: The same credential failure gets a different error type in `plan` and `import`

**File:** `jiramator/planner.py:912-917` vs `jiramator/cli.py:676-692`
**Issue:** This still applies. In `plan`, a missing token records `type: "Aborted"` with message `Credential error: …`. In `import`, the same `ValueError` from `JiraClient(org_config)` reaches `except (ValueError, JiraApiError)` → `_record_import_failure` → `error_info`, which records `type: "ValueError"`.
**Fix:** Construct the client in its own `try` in `import_command` and record `abort_info(f"Credential error: {exc}", secrets=credential_secrets(org_config))`, or document the difference.

### IN-03: The new code keeps two different `ended_at` formats

**File:** `jiramator/planner.py:825,906,1055` vs `jiramator/importer.py:516`, `jiramator/cli.py:123,702`
**Issue:** This still applies. The plan handlers write `…+00:00`, while the import handlers and `_record_import_failure` write `…Z`. Anything that parses `ended_at` across report types has to handle both.
**Fix:** Add one `utc_now_iso()` helper in `run_report.py` and use it everywhere (in a later cleanup).

### IN-04: Crashed reports, the ones that need resuming, can't be resumed by 1.2.8

**File:** `jiramator/run_report.py:138-149`; `CHANGELOG.md:27-29`
**Issue:** This still applies, and it was accepted on purpose (D-13). Reports with an `error` key are exactly the `failed`/`partial` reports that `--resume` targets, so rolling back to 1.2.8 strands them. The CHANGELOG caveat is present.
**Fix:** Optionally mention it in the release notes and upgrade guide as well.

### IN-05: The CHANGELOG makes compatibility claims the code no longer meets

**File:** `CHANGELOG.md:24-26`; `jiramator/planner.py:322-327,948-951`
**Issue:** The entry says aborts are recorded "with the reason shown on screen" and that "Exit codes and console output are unchanged". Neither holds:
- The WR-05 fix changed the fix-version decline console line. It was `Aborted. Cannot proceed without fix versions.` on `develop` and is now `Aborted. Cannot proceed without fix versions (declined creating: X).`.
- The final-confirmation decline prints only `Aborted.` but records `User declined ticket creation at the final confirmation.`, a reason never shown on screen.
**Fix:** Change the wording to something like "Console output is unchanged except that the fix-version decline now names the declined versions". Then either print the final-confirmation reason (`Aborted. User declined ticket creation.`) or describe that message as a report-only label.

### IN-06: The redaction regex misses quoted and URL-encoded credentials

**File:** `jiramator/run_report.py:209-212`
**Issue:** The first character of the token excludes quotes, and the separator excludes `%20`. Verified: `Authorization: Basic "dXNlcjp0b2s="` and `Basic 'dXNlcjp0b2s='` come through unchanged, as does `Authorization=Basic%20dXNlcjp0b2s%3D`. The configured Jira credential is still caught by the literal `credential_secrets()` pass, so this only matters for other credentials, such as proxy auth. That is why it is Info and not a Warning.
**Fix:** If you keep the regex (see WR-07), allow an optional opening quote (`([\s:=]+["']?)`) and `%20` as a separator. Add test cases for both.

### IN-07: The WR-06 guard covers only the outer handlers; abort-site `persist()` calls can still replace a clean exit with an `OSError` traceback

**File:** `jiramator/planner.py:528, 996, 1131`
**Issue:** The preflight, epic-failure and bulk-failure abort paths call `persist()` unguarded, just before `sys.exit(1)`. If the write fails (disk full, permissions), an `OSError` is raised instead of `SystemExit(1)`. The outer handler then keeps the recorded `error`, swallows its own retry and re-raises the `OSError`, so the user sees a traceback instead of the abort message and exit 1. The outer `except BaseException` handler now always sets `ended_at`/`error` and persists, so these inner `persist()` calls are redundant on the abort path. This behavior predates the phase, but it is the same P-01-01 concern WR-06 fixed.
**Fix:** Remove the inner `persist()` calls on paths that end in `sys.exit` (the outer handler persists), or wrap them in `try/except OSError: pass`.

---

_Reviewed: 2026-10-05T18:26:24Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
