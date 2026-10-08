---
phase: 01-production-triage
plan: 03
subsystem: production-triage
tags: [triage, INV-01, INV-04, D-03, harness, run-reports]
status: complete

requires:
  - "01-01: INV-04 report ended_at/error recording (HEAD bd1b686)"
  - "01-02: Findings Table row 9, workclone-fingerprint.before D-03 baseline"
provides:
  - "01-TRIAGE-FINDINGS.md ## INV-01: exit-point table a–k, before/after INV-04 harness signature tables, timing argument, D-03 sandbox decision line, ### User evidence block (provenance-labelled)"
  - "/tmp/jm-triage/harness.py: offline 12-scenario reproduction harness (outside repo; deleted at phase close by 01-05)"
affects: [01-04, 01-05, phase-04-hygiene]

actuals:
  tokens: 6900
  tasks: 3
  commits: 0
plan_head_before: bd1b6864bcc7f579fa0f3fd4c38f64b41b6c0f0f
plan_head_after: bd1b6864bcc7f579fa0f3fd4c38f64b41b6c0f0f

tech-stack:
  added: []
  patterns:
    - "CliRunner + fake JiraClient + scripted Rich prompts + sys proxy for isatty to reproduce interactive live-only exits offline"
    - "Throwaway git worktree under /tmp for a pre-change ('before') view, removed after the run"

key-files:
  created:
    - /tmp/jm-triage/harness.py
  modified:
    - .planning/phases/01-production-triage/01-TRIAGE-FINDINGS.md

key-decisions:
  - "All 11 INV-01 candidate exits (a,b,c,d,e,e2,f,h,h2,j,k) reproduce offline on the copied real configs (hash fdedcb7e); before INV-04 they all leave the identical 07-21 signature, after INV-04 each records ended_at + error (a/h2 share KeyboardInterrupt with empty message: residual gap)"
  - "D-04 not triggered: exit paths unchanged since v1.2.8 (only ruff modernization 4afba64); pre-INV-04 view from 6676bdc"
  - "D-03 sandbox decision: jql-only (2026-10-02; orchestrator-selected, user unavailable — reversible)"
  - "Orchestrator-gathered read-only Jira evidence: zero CA issues created 2026-07-21 08:15–08:30 EDT; all four needed versions exist, creation time not determinable from API. Q1 (terminal last line) remains open for the user"

metrics:
  duration: "~20min (continuation ~5min)"
  completed: 2026-10-02
---

# Phase 1 Plan 3: INV-01 Offline Reproduction and Evidence Summary

**This plan reproduced, offline, all 11 candidate exits for the failed 2026-07-21 live `plan` run, using the real calcs/acme configs (config hash fdedcb7e).** Before INV-04, every exit leaves the same report signature as the failed run. After INV-04, every exit records `ended_at` and an `error`. Read-only Jira evidence was also recorded: no CA issues were created at 08:15–08:30 EDT. That evidence was gathered by the orchestrator, because the user was unavailable.

## Tasks

| # | Task | Result | Commit |
|---|------|--------|--------|
| 1 | Offline reproduction of every candidate exit (tracer) | Done by the previous agent. 11/11 exits reproduced. The before table shows the identical signature; the after table shows a distinct `error` per exit. D-04 not triggered. Fingerprint `identical` | none (no tracked changes) |
| 2 | D-03 sandbox decision (checkpoint:decision) | `jql-only`, recorded with orchestrator provenance | none |
| 3 | INV-01 evidence (checkpoint:human-verify) | `### User evidence (2026-10-02 checkpoint)` recorded with per-answer provenance labels | none |

The continuation check confirmed Task 1's output: the INV-01 section has the before/after tables, `/tmp/jm-triage/harness.py` exists, and HEAD is still `bd1b686`.

## Verification

- `grep "D-03 sandbox decision:"` matches at line 279. `grep "### User evidence"` matches at line 285.
- `workclone_fingerprint.py compare workclone-fingerprint.before` printed `INTEGRITY: identical` (exit 0) at 2026-10-02T18:15Z.
- No live Jira calls or jiramator runs with credentials were made by this executor. `git status` is clean, and there are no tracked changes.

## Deviations from Plan

**1. [Checkpoint provenance] Both checkpoints were resolved by the orchestrator, not the user**
- **Task 2:** the plan expected the user to choose. The orchestrator chose `jql-only` as the zero-risk, reversible option, and it is recorded that way.
- **Task 3:** the plan expected user answers to all three questions.
  - Q1 (last terminal line) is **UNANSWERED** and recorded as an open item for the user.
  - Q2 was gathered by the orchestrator through read-only Atlassian MCP calls (not user-run). Its JQL window covered the whole day of 07-21, which contains the 08:15–08:30 window.
  - Q3 is N/A because `jql-only` was chosen.
  - The acceptance criterion "answers to all three questions" is therefore only partly met: Q1 is explicitly open, not fabricated.
- **Impact on 01-04:** the Q2 evidence (no issue writes) bears on exit k. Q1 is still needed to tell c/d/e/f/h/j apart. Version creation timing (exit g / after-f) cannot be determined from the versions API.

**2. [Rule 1 - State] INV-01 is not marked complete in REQUIREMENTS.md**
- `requirements.mark-complete INV-01` ticked the requirement. That was reverted to `[ ]` / `Pending`, because the root cause is not identified yet: plan 01-04 (`requirements: [INV-01, INV-03]`) owns that. Closing INV-01 now would violate P-01-05/D-06.

Otherwise, the plan was executed as written.

## Known Stubs

None.

## Open Items for User Review

- Answer Q1: the last terminal line at ~08:19 EDT on 2026-07-21, or "don't remember".
- Optionally confirm the orchestrator-gathered JQL/versions evidence, or reverse the D-03 choice to `sandbox-dry-run`.

## Self-Check: PASSED

- FOUND: .planning/phases/01-production-triage/01-TRIAGE-FINDINGS.md (INV-01, D-03 decision line, User evidence block)
- FOUND: /tmp/jm-triage/harness.py
- Commits: 0 expected (gitignored docs plus a /tmp script); measured `rev-list bd1b686..HEAD` = 0
