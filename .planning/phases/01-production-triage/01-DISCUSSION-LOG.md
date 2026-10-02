# Phase 1: Production Triage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-10-02
**Phase:** 01-production-triage
**Areas discussed:** Reproduction method, Bar for done, Disposition of findings, Run-report error capture

Process note: the interactive question form returned "user unavailable". The agent presented
recommendations for all four areas in its summary; the user replied **"proceed as you
suggested"**, adopting all four recommendations as below.

---

## Reproduction method

| Option | Description | Selected |
|--------|-------------|----------|
| Current code, dry-run only | Replay against work clone's real configs with `--dry-run` (reads Jira, never writes); old tags only as fallback | ✓ |
| Old release tags | Check out the SHA live at failure time and reproduce exactly | |
| User memory | Reconstruct from what the user remembers | |

**User's choice:** Current code, dry-run only (recommendation adopted)

---

## Bar for done

| Option | Description | Selected |
|--------|-------------|----------|
| History + run-pair evidence | "Fixed by commit X" acceptable when git history and a failed→succeeded run pair support it; Jul 21 must be reproduced/explained | ✓ |
| Reproduce everything | Every failure reproduced, at old SHA if needed | |

**User's choice:** History + run-pair evidence, with Jul 21 held to a concrete explanation

---

## Disposition of findings

| Option | Description | Selected |
|--------|-------------|----------|
| Tiered | Trivial → fix in Phase 1; larger → new reqs in Phases 2–4; out of milestone → GitHub issue | ✓ |
| All to later phases | Phase 1 is investigation only | |
| All fixed in Phase 1 | Phase 1 grows to absorb every fix | |

**User's choice:** Tiered

---

## Run-report error capture

| Option | Description | Selected |
|--------|-------------|----------|
| Add requirement this milestone | Reports record exception + `ended_at` on crash (backward compatible) | ✓ |
| Defer to v1.3 seed | Note it, don't build it | |

**User's choice:** Add requirement (placed in Phase 1 as INV-04)

## the agent's Discretion

- Error field shape / schema_version handling (must stay backward compatible)
- Investigation order and temp-dir layout

## Deferred Ideas

None.
