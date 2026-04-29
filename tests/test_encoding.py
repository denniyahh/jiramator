"""Tests for jiramator/encoding.py — encoding detection chain (IMPT-01).

Plan: 01-02 Task 1.

Detection order is BOM-first → strict UTF-8 → charset-normalizer fallback.
The override flag short-circuits the entire chain. The function never
guesses if it can avoid it: BOM-flagged files are identified from 4
header bytes only; plain UTF-8 succeeds via strict decode without
calling charset-normalizer at all.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jiramator.encoding import detect_encoding

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "csv_encodings"


# ---------------------------------------------------------------------------
# Override short-circuits everything
# ---------------------------------------------------------------------------


def test_override_short_circuits_without_open():
    """Test 1: override returns verbatim and does NOT touch the filesystem.

    A nonexistent path must not raise — proves the override branch runs
    before any open() call.
    """
    nonexistent = Path("/definitely/does/not/exist.csv")
    assert detect_encoding(nonexistent, override="latin-1") == "latin-1"


# ---------------------------------------------------------------------------
# BOM-first detection
# ---------------------------------------------------------------------------


def test_plain_utf8_returns_utf8():
    """Test 2: ASCII-only / plain UTF-8 → 'utf-8' (strict decode succeeds).

    Critically NOT 'utf-8-sig' — no BOM means the cheaper codec is selected.
    """
    assert detect_encoding(FIXTURE_DIR / "utf8.csv") == "utf-8"


def test_utf8_sig_returns_utf8_sig():
    """Test 3: UTF-8 with BOM → 'utf-8-sig' (BOM table hit, no decode attempted)."""
    assert detect_encoding(FIXTURE_DIR / "utf8_sig.csv") == "utf-8-sig"


def test_utf16_le_with_bom_returns_utf16():
    """Test 4: UTF-16-LE with BOM → 'utf-16' (Python's 'utf-16' handles
    either endian when BOM is present)."""
    assert detect_encoding(FIXTURE_DIR / "utf16_le_bom.csv") == "utf-16"


def test_bom_table_ordering_utf8_sig_before_utf16(tmp_path):
    """Test 7: A 4-byte buffer starting with the UTF-8-SIG BOM (3 bytes)
    must be classified as utf-8-sig, not utf-16. The longer BOM wins.

    The first 3 bytes are EF BB BF (utf-8-sig); naive 2-byte BOM matching
    would mistake the leading EF BB as a (nonexistent) BOM, but the table
    must be ordered longest-first to prevent that class of bug.
    """
    p = tmp_path / "edge.csv"
    p.write_bytes(b"\xef\xbb\xbfA")
    assert detect_encoding(p) == "utf-8-sig"


# ---------------------------------------------------------------------------
# Charset-normalizer fallback
# ---------------------------------------------------------------------------


def test_cp1252_falls_through_to_charset_normalizer():
    """Test 5: A cp1252 file (no BOM, fails strict UTF-8 decode) falls
    through to charset-normalizer. The exact returned encoding may vary
    (cp1252 vs cp1250 vs windows-1252 vs iso-8859-* — Pitfall 5: charset
    detectors commonly confuse Windows code pages). The contract is:
    a non-UTF-8 string is returned, NOT 'utf-8'.
    """
    enc = detect_encoding(FIXTURE_DIR / "cp1252.csv")
    assert enc != "utf-8"
    assert enc != "utf-8-sig"
    # Must be one of the known plausible matches for this byte pattern.
    plausible = {
        "cp1252", "cp1250", "windows-1252", "windows-1250",
        "iso-8859-1", "iso-8859-15", "latin-1", "latin_1",
    }
    # Normalize for comparison (charset-normalizer uses underscores
    # sometimes; codecs canonicalizes hyphens). Accept either shape.
    norm = enc.lower().replace("_", "-")
    plausible_norm = {p.lower().replace("_", "-") for p in plausible}
    assert norm in plausible_norm, f"unexpected encoding {enc!r}"


def test_random_binary_either_raises_or_returns_non_utf8(tmp_path):
    """Test 6: Random binary input may either raise ValueError (with the
    actionable hint) OR return a low-confidence non-UTF-8 guess from
    charset-normalizer (Pitfall 2: charset-normalizer rarely returns None).

    Both behaviors are acceptable. What's NOT acceptable is silently
    returning 'utf-8' for random bytes.
    """
    p = tmp_path / "random.bin"
    p.write_bytes(os.urandom(2048))
    try:
        enc = detect_encoding(p)
    except ValueError as exc:
        # Acceptable path: hint mentions both alternative encodings.
        msg = str(exc)
        assert "Could not detect encoding" in msg
        assert "cp1252" in msg
        assert "utf-16-le" in msg
        return
    # Acceptable path: returned a guess; must not be UTF-8.
    assert enc != "utf-8"
