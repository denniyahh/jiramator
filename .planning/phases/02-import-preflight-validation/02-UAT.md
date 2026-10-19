---
status: testing
phase: 02-import-preflight-validation
source: [02-VERIFICATION.md]
started: 2026-10-15T18:15:00Z
updated: 2026-10-19T15:05:00Z
---

## Current Test

number: 1
name: Live smoke — `jiramator import --dry-run` against real Jira on the 2026-09-02-shaped Risk sheet
expected: |
  Preview prints, then a validation section listing missing 'Fix versions' (fixVersions) on all 6 rows
  and 'Repositories' (customfield_11941) on rows 2-3 (8 problems), the line '6 of 6 rows have problems',
  exit code 1, nothing created in Jira.
awaiting: user response

## Tests

### 1. Live smoke — `jiramator import --dry-run` against real Jira on the 2026-09-02-shaped Risk sheet
expected: Preview prints, then a validation section listing missing 'Fix versions' on all 6 rows and 'Repositories' on rows 2-3 (8 problems), '6 of 6 rows have problems', exit 1, nothing created in Jira
result: [pending]

### 2. Same sheet with JIRA_TOKEN unset
expected: 'Schema validation skipped' printed, exit code 0
result: [pending]

### 3. Live abort — real `import` (no --dry-run) on a sheet with problem rows
expected: Aborts before creating anything, prints every failing row and 'Aborting — fix the rows above. No issues were created.', exit 1, report status 'failed' with error.type 'Aborted'
result: [pending]

### 4. Live dry-run with a required Reporter/Parent field on a real create screen
expected: Caveat 'required <Name> (<id>) depends on live <kind> lookup — not preflight-validated' under 'Not preflight-validated:', exit 0
result: [pending]

### 5. Option-value comparison matches Jira's (backstop, 02-01)
expected: Submitting a select value that differs only in case or NFC/NFD form against a real select field is rejected by Jira (so preflight's exact match is not a false positive) — or the assumption is consciously accepted
result: [pending]

### 6. Confirm prohibitions P-02-01..P-02-05 (see 02-VERIFICATION.md Prohibitions table)
expected: Each LLM-judged HELD verdict confirmed or rejected by a human
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
