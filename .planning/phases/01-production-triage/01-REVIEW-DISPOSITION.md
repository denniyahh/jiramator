---
phase: 01
review: 01-REVIEW.md
titles: json
findings:
  - id: WR-07
    severity: warning
    disposition: skipped
    title: "The credential regex over-redacts ordinary text after \"basic\"/\"bearer\", which garbles Jira diagnostics and the new preflight problem list"
  - id: IN-02
    severity: info
    disposition: open
    title: "The same credential failure gets a different error type in `plan` and `import`"
  - id: IN-03
    severity: info
    disposition: open
    title: "The new code keeps two different `ended_at` formats"
  - id: IN-04
    severity: info
    disposition: open
    title: "Crashed reports, the ones that need resuming, can't be resumed by 1.2.8"
  - id: IN-05
    severity: info
    disposition: fixed
    title: "The CHANGELOG makes compatibility claims the code no longer meets"
  - id: IN-06
    severity: info
    disposition: open
    title: "The redaction regex misses quoted and URL-encoded credentials"
  - id: IN-07
    severity: info
    disposition: open
    title: "The WR-06 guard covers only the outer handlers; abort-site `persist()` calls can still replace a clean exit with an `OSError` traceback"
  - id: WR-01
    severity: warning
    disposition: fixed
    title: "The credential regex changes the \"Basic Constraints\" TLS error, the error this project most often needs to diagnose"
  - id: WR-02
    severity: warning
    disposition: fixed
    title: "The credential regex is case-sensitive and misses common header spellings"
  - id: WR-03
    severity: warning
    disposition: fixed
    title: "The redaction promise covers only `run.error`; the same exception text is saved unredacted in `issues[].error`"
  - id: WR-04
    severity: warning
    disposition: fixed
    title: "The tolerant `from_envelope` changed a malformed-report failure from `TypeError` to `AttributeError`, so `_load_report_file` now crashes with a traceback"
  - id: WR-05
    severity: warning
    disposition: fixed
    title: "Abort messages don't match the console reason, and the preflight abort loses the problem list"
  - id: WR-06
    severity: warning
    disposition: fixed
    title: "A failed report write in the crash handlers replaces the original exception, which breaks P-01-01"
  - id: IN-01
    severity: info
    disposition: fixed
    title: "Token-secret lookup is copied three times"
open: 5
total: 14
recorded: 2026-10-05T18:27:35.871Z
---

# Phase 01: Code Review Disposition

| Finding | Severity | Disposition | Source |
|---------|----------|-------------|--------|
| WR-07 | warning | skipped | accepted as-is by user in UAT test 3 (2026-10-05): over-redaction is the safe side |
| IN-02 | info | open | - |
| IN-03 | info | open | - |
| IN-04 | info | open | - |
| IN-05 | info | fixed | CHANGELOG wording corrected; deviations accepted by user in UAT test 4 (2026-10-08) |
| IN-06 | info | open | - |
| IN-07 | info | open | - |
| WR-01 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-02 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-03 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-04 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-05 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| WR-06 | warning | fixed | 01-REVIEW-FIX.md (not in the current review) |
| IN-01 | info | fixed | resolved by credential_secrets() in 6db86ae; confirmed in re-review (not in the current review) |

Dispositions: `open` (recorded, not yet triaged), `fixed`, `skipped`, `deferred`.
Set `deferred` by hand and put the reason in the Source cell; both are preserved. A `|` in the reason is kept as prose and escaped on the next run.
Re-running the gate keeps every row it can. A row the current review no longer reports is kept and its Source cell flagged, so a finding does not leave this record silently. ONE exception: when a finding id is REUSED by a different finding, the earlier decision cannot keep a row — the id is taken — and it is dropped. A RECORDED decision (anything but `open`) is named on the console when that happens; a row still at `open` is replaced silently, because `open` records no decision to lose.
