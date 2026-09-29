---
phase: 01-reliability-robustness
plan: 02
subsystem: csv-import
tags: [encoding, csv, charset-normalizer, bom, cp1252, utf-16, import]
provides:
  - detect_encoding(path, *, override=None) — three-stage detection chain (override → BOM → strict UTF-8 → charset-normalizer fallback)
  - _read_csv accepts encoding_override; calls detect_encoding; emits one-line stderr announcement on non-UTF-8
  - read_spreadsheet exposes encoding_override keyword arg (forwarded to CSV path; ignored for xlsx)
  - charset-normalizer>=3,<4 declared as direct dependency (zero install footprint — already transitive via requests)
affects: [reliability-robustness, plan-01-05-cli-encoding-flag]
tech-stack:
  added:
    - charset-normalizer>=3,<4 (direct dep; was transitive via requests)
  patterns:
    - BOM-first detection via codecs.BOM_* constants, ordered longest-first
    - Strict-decode short-circuit on UTF-8 happy path (zero charset-normalizer cost)
    - Lazy import of charset_normalizer.from_bytes inside the function
    - Override-first contract for the eventual --encoding CLI flag
    - DC-1 channel discipline (stderr for user-facing notes, stdout clean)
key-files:
  created:
    - jiramator/encoding.py
    - tests/test_encoding.py
    - tests/fixtures/csv_encodings/utf8.csv
    - tests/fixtures/csv_encodings/utf8_sig.csv
    - tests/fixtures/csv_encodings/cp1252.csv
    - tests/fixtures/csv_encodings/utf16_le_bom.csv
  modified:
    - jiramator/spreadsheet.py
    - tests/test_spreadsheet.py
    - pyproject.toml
key-decisions:
  - "BOM table ordered longest-first (utf-8-sig 3 bytes before utf-16 2 bytes) to prevent future misclassification — even though current BOM bytes don't collide, the ordering principle protects against future BOM additions."
  - "charset_normalizer.from_bytes imported lazily inside detect_encoding, so the UTF-8 happy path never pays the import cost."
  - "Stderr announcement fires for ANY non-utf-8 encoding (including utf-8-sig and utf-16) — preserves transparency over silence; user can verify the assumption."
  - "Path display in announcement uses the Path object as-is (no .resolve()) so relative paths stay readable in CLI output."
  - "Test N6 forces ValueError deterministically by patching from_bytes to return an object whose .best() is None — random binary may produce a guess on some installs (Pitfall 2: charset-normalizer rarely returns None)."
  - "Test 5 (cp1252) accepts a plausible-set of encodings {cp1252, cp1250, windows-1252, windows-1250, iso-8859-1, iso-8859-15, latin-1} per Pitfall 5 — charset-normalizer commonly returns cp1250 for cp1252 content; the override flag is the user's escape hatch."
duration: 35min
completed: 2026-04-29
---

# Plan 01-02: Non-UTF-8 CSV Import (IMPT-01) Summary

**Replaced hardcoded `encoding="utf-8"` in CSV ingestion with a deterministic detection chain that handles Windows-Excel-exported cp1252, BOM-flagged UTF-8 / UTF-16, and a charset-normalizer fallback — with override hatch and stderr transparency.**

## Performance
- **Duration:** ~35min
- **Tasks:** 2 (both completed)
- **Files modified:** 9 (1 new source, 2 modified source incl. pyproject, 4 fixtures, 2 test files)

## Accomplishments
- All 6 must-have truths from the plan satisfied:
  1. ✓ Windows-Excel cp1252 CSV imports without manual conversion (test N2 verifies curly apos / smart quotes / em-dash / £ all preserved as proper Unicode codepoints).
  2. ✓ UTF-8-with-BOM (`utf-8-sig`) imports succeed (test N1 verifies BOM stripped from header).
  3. ✓ UTF-16-LE-with-BOM imports succeed (test N3).
  4. ✓ Stderr announcement `Read <path> as <encoding>` fires before any data row is processed for non-UTF-8 (test N5a, N5c).
  5. ✓ `encoding_override` bypasses charset-normalizer entirely (test N4 patches `from_bytes` to fail loudly; test passes only if override short-circuits).
  6. ✓ Detection-failure error names `--encoding cp1252` AND `--encoding utf-16-le` (test N6).
- 17 new tests across 2 files (7 unit tests of `detect_encoding`, 10 wiring tests via `read_spreadsheet`).
- Zero regressions: 277 baseline → 324 after 01-01 → **341 after 01-02**.
- STRIDE T-01-06 (encoding misdetection silently corrupts ticket text) mitigated by stderr announcement; T-01-09 (BOM-prefixed header) mitigated by `utf-8-sig` codec contract — both have regression assertions.

## Task Commits
1. **Task 1: Encoding detection module + dependency + fixtures** — `f074305`
2. **Task 2: Wire detect_encoding into _read_csv + thread encoding_override** — `e1530e1`

## Files Created/Modified
- `jiramator/encoding.py` (NEW) — `detect_encoding(path, *, override=None)`; `_BOM_TABLE` constant ordered longest-first; lazy import of `charset_normalizer.from_bytes`; raises ValueError with actionable hint on detection failure.
- `jiramator/spreadsheet.py` — `_read_csv` and `read_spreadsheet` both gain `encoding_override` keyword; `_read_csv` calls `detect_encoding`, emits rich.Console stderr announcement when encoding != "utf-8".
- `pyproject.toml` — `charset-normalizer>=3,<4` pinned as direct dependency.
- `tests/test_encoding.py` (NEW) — 7 tests covering override short-circuit, plain UTF-8, UTF-8-SIG, UTF-16-LE-with-BOM, BOM ordering edge case, cp1252 fallback (Pitfall 5 plausible-set), random-binary either-raises-or-returns-non-utf-8 (Pitfall 2).
- `tests/test_spreadsheet.py` — `TestEncodingDetection` class with 10 tests (R1, R2, N1, N2, N3, N4, N5a, N5b, N5c, N6).
- `tests/fixtures/csv_encodings/{utf8,utf8_sig,cp1252,utf16_le_bom}.csv` (NEW) — hand-authored byte-exact fixtures (BOMs verified via xxd).

## Decisions & Deviations
- **Decision:** Test N5c flagged a design choice — utf-8-sig also gets the announcement (not just true non-UTF-8 encodings). Rationale documented inline: transparency > silence; the user wants to know whenever detection diverged from plain UTF-8.
- **Decision:** Test N6 deterministically forces the `best() is None` branch by patching `charset_normalizer.from_bytes` (rather than relying on random binary). Rationale: charset-normalizer is "the kind of detector that always finds something" (Pitfall 2 from RESEARCH.md), so non-deterministic test inputs flake on different installs.
- **Decision:** Test 5 (cp1252) asserts membership in a plausible-set rather than equality with `"cp1252"`. Rationale: charset-normalizer 3.4.7 returns `cp1250` for the test bytes on this machine (Pitfall 5: confusable code pages). The plausible-set explicitly includes cp1250/iso-8859-* — the contract is "non-UTF-8 string", not exact match. The override flag is the user's escape hatch when detection is wrong.
- **Deviation (none):** Plan executed exactly as specified, including the Test 5 plausible-set acceptance language and Test N6 deterministic-patch approach (both anticipated in the plan).

## Next Phase Readiness
- Plan 01-05 (CLI `--encoding` flag) has its contract: pass user-supplied `--encoding` value as `encoding_override` to `read_spreadsheet`.
- Wave 1 progress: 2/3 plans complete (01-01, 01-02). Plan 01-03 remains — no file overlap with the two completed plans, can proceed.
- charset-normalizer is now a directly-pinned dependency; future encoding-related changes can rely on its API stability via the `>=3,<4` major-version pin.
