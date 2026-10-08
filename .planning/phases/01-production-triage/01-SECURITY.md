---
phase: "01"
slug: "production-triage"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-10-05"
---

# Phase 01 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| exception → run report | Exception text written to `.jiramator/runs/*.json` | Error messages that may contain credentials (high) |
| run report → resume | `RunReport.from_envelope` parses JSON from disk | Untrusted report content (medium) |
| agent → work clone | Triage read the user's real work clone (D-03) | Run reports, config files (internal) |
| agent → Jira | Triage evidence gathering (D-02) | JQL reads only; no writes |
| /tmp sandbox | Temporary copies of internal configs | Jira URLs, field IDs (internal) |
| findings → public GitHub issue | Out-of-milestone defects (D-10) | Symptom/root-cause text |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-01-01 | Information disclosure | run_report.error_info / abort_info | high | mitigate | `_AUTH_CREDENTIAL_RE` is now case-insensitive and accepts whitespace, `:` or `=` after `Basic`/`Bearer`; the OpenSSL "Basic Constraints" diagnostic is exempt (run_report.py:209-212, fix commits 6db86ae and 74a3893). `credential_secrets()` also redacts the base64 `email:token` value (run_report.py:215). Redaction runs before truncation. All report write paths pass secrets: planner.py:329,523,827,916,991,995,1126,1130; importer.py:332 (`_record`, covers every per-issue error),518; cli.py:125 and the update report at cli.py:234,245 (dda6c1e). planner.py:949 records a fixed literal. Re-verified 2026-10-05: `authorization: basic <b64>`, `BEARER x`, `Basic=<b64>` and `Bearer:x` all become `***`, and "Basic Constraints…" is kept. Tests: test_32/32b/32d/32e/32f, test_i6b_row_error_redacts_token, test_live_run_redacts_credentials_in_update_report. | closed |
| T-01-02 | Denial of service | report size | low | mitigate | `_ERROR_MESSAGE_CAP = 2000` (run_report.py:50), truncation at :196-197; test_30/30b | closed |
| T-01-03 | Tampering | RunReport.from_envelope | medium | mitigate | Schema check, `isinstance` shape checks raising ValueError (run_report.py:163-186, WR-04 fix 64822f5), name filter `fields(cls)` (:172), no eval/getattr on input; `find_resumable` (:363) unchanged | closed |
| T-01-04 | Repudiation | handlers | medium | mitigate | error_info/abort_info at every crash/abort path (planner.py:320,514,822,907,940,985,1119; importer.py:508; cli.py:125) | closed |
| T-01-05 | Denial of service (resume stranding) | schema compatibility | medium | mitigate | `SCHEMA_VERSION = 1` unchanged (run_report.py:49); test_27 legacy load, test_29 error omitted, test_resume_from_legacy_report_without_error_succeeds | closed |
| T-01-06 | Tampering | work clone (D-03) | high | mitigate | Baseline sha256 a93f5991…13780 matches findings doc:43; compare re-run 2026-10-05 → `INTEGRITY: identical` | closed |
| T-01-07 | Information disclosure | findings doc | low | accept | `.planning/` gitignored (.gitignore:46); see Accepted Risks Log | closed |
| T-01-08 | Elevation / unintended write | Jira (plan 01-02) | high | mitigate | 01-02-SUMMARY.md:126 records no Jira call. The integrity compare is identical. | closed |
| T-01-09 | Tampering | work clone (plan 01-03) | high | mitigate | D-03 decision `jql-only` (01-03-SUMMARY.md:38). The compare is identical. | closed |
| T-01-10 | Elevation / unintended write | Jira (D-02) | high | mitigate | Harness uses a fake JiraClient (01-03-SUMMARY.md:26). There was no credentialed run (:64). Live access was read-only JQL and a versions list; the user accepted this in UAT test 2 on 2026-10-05. | closed |
| T-01-11 | Information disclosure | /tmp/jm-triage copies | low | mitigate | `/tmp/jm-triage` is absent (verified 2026-10-05) | closed |
| T-01-12 | Information disclosure | `gh issue create` body | medium | mitigate | `Issue filing: none drafted` (findings doc:390); no issue filed | closed |
| T-01-13 | Tampering | work clone (plan 01-05) | high | mitigate | The compare ran against a hash-checked baseline. VIOLATION exits 1 (workclone_fingerprint.py:20,129). Result: identical (findings doc:64). | closed |
| T-01-14 | Information disclosure | /tmp/jm-triage | low | mitigate | Absent after a non-VIOLATION result | closed |
| T-01-15 | Repudiation | INV-01 closure | medium | mitigate | `INV-01 decision: accept-residual (2026-10-05)` (findings doc:389); FA-INV-01 (:421) | closed |
| T-01-16 | Repudiation | integrity baseline | medium | mitigate | Baseline is in the phase dir (persistent), and its hash is in findings doc:43 and matches | closed |
| T-01-SC | Tampering | package installs | high | mitigate | No diff to pyproject.toml/requirements vs develop | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01-01 | T-01-07 | The findings doc lives in gitignored `.planning/`. It cites filenames, timings, SHAs and error text only, which is the same data class already in `.jiramator/runs/`. | plan 01-02 threat model (planned disposition) | 2026-10-02 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-10-05 | 17 | 16 | 1 | orchestrator L1 checks. The gsd-security-auditor escalated because it had no file tools, so the orchestrator ran its read-only checklist directly. |
| 2026-10-05 | 17 | 17 | 0 | orchestrator L1 re-audit (State A) after fixes 74a3893..05e8786 and dda6c1e. T-01-01 is closed. |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-10-05

## Security Audit 2026-10-05

| Metric | Count |
|---|---|
| Threats found | 17 |
| Closed | 17 |
| Open | 0 |
