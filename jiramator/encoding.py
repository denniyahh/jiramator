"""Encoding detection for CSV imports (IMPT-01).

A small, deterministic detection chain that resolves the encoding of a
CSV file in three priority steps:

1. **Override** — caller-supplied encoding wins, no I/O performed. This
   is the contract for the eventual ``--encoding`` CLI flag (Plan 01-05).
2. **BOM signature** — the first 4 bytes are inspected for one of three
   well-known byte order marks. ``UTF-8-SIG`` (3 bytes) is checked
   before ``UTF-16`` (2 bytes) so a UTF-8-SIG file isn't misclassified.
3. **Strict UTF-8 decode** — the most common case for plain ASCII /
   UTF-8 files. Succeeds without invoking charset-normalizer at all,
   keeping the happy path zero-cost beyond ``read_bytes``.
4. **charset-normalizer fallback** — only invoked when the above steps
   fail. Returns a best-guess encoding; if even charset-normalizer
   gives up (rare — see Pitfall 2), raises ``ValueError`` with an
   actionable hint naming specific encodings the user can pass via
   ``--encoding``.

Imports are kept minimal at module scope; ``charset_normalizer`` is
imported lazily inside the function so that the happy path (UTF-8)
doesn't pay the import cost.
"""

from __future__ import annotations

import codecs
from pathlib import Path

# Order matters: longer BOMs MUST come first so a UTF-8-SIG file
# (EF BB BF, 3 bytes) is not misclassified as UTF-16-LE (FF FE / 2 bytes)
# — though those particular bytes don't collide, the principle protects
# against future BOM additions and is the convention used by the stdlib.
_BOM_TABLE: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def detect_encoding(path: Path, *, override: str | None = None) -> str:
    """Return the encoding to use when reading ``path``.

    Args:
        path: Filesystem path to the file. Not opened if ``override`` set.
        override: If provided, returned verbatim — the entire detection
            chain is short-circuited and no I/O is performed. This is
            the escape hatch for users whose file mis-detects (Pitfall 5)
            or whose ops policy requires a known fixed encoding.

    Returns:
        A codec name suitable for ``open(path, encoding=...)``. One of:
        the ``override`` value verbatim; ``"utf-8-sig"`` / ``"utf-16"``
        for BOM-flagged files; ``"utf-8"`` for plain UTF-8; or
        whatever charset-normalizer's ``best().encoding`` reports for
        non-UTF-8 files without a BOM.

    Raises:
        ValueError: When charset-normalizer cannot identify the encoding.
            The message names ``cp1252`` and ``utf-16-le`` as the most
            common explicit overrides to try.
        OSError: Propagated from ``path.open`` / ``path.read_bytes`` when
            the file is unreadable. Not raised when ``override`` is set.
    """
    if override:
        return override

    with path.open("rb") as f:
        head = f.read(4)
    for sig, enc in _BOM_TABLE:
        if head.startswith(sig):
            return enc

    # No BOM — try strict UTF-8 first (the dominant case on Linux/macOS
    # CSV exports). A successful strict decode is conclusive evidence
    # the bytes are UTF-8, and we avoid the heavier charset-normalizer
    # round-trip entirely.
    raw = path.read_bytes()
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    # Lazy import: charset-normalizer is only loaded when we actually
    # need it. Keeps the happy-path import cost off the hot path.
    from charset_normalizer import from_bytes

    best = from_bytes(raw).best()
    if best is None:
        raise ValueError(
            f"Could not detect encoding for {path}. "
            f"Re-save as UTF-8 or pass --encoding <name> "
            f"(try --encoding cp1252 or --encoding utf-16-le)."
        )
    return best.encoding
