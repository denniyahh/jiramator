"""Actionable config validation error format (FOUND-01).

Renders errors as ``<file>:<line>: <field-path> — <reason>[ suggestion]``
so a user staring at a 200-line YAML config can jump straight to the
offending field.

Public surface:
    ConfigValidationError — frozen dataclass + Exception subclass raised by
        ``jiramator.config.load_org_config`` and ``load_team_config``.
    format_loc            — Pydantic ``loc`` tuple → ``a.b[0].c.d`` string.
    did_you_mean          — difflib-backed PEP-657-style spelling suggestion.

Note: ``frozen=True`` on a dataclass that subclasses ``Exception`` requires
Python 3.11+. Project pyproject pins ``>=3.11`` so this is supported.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

# Exception-internal dunder attributes that the interpreter, contextlib, and
# frameworks like Click assign directly on a *caught* exception instance
# (e.g. contextlib's @contextmanager re-raises reassign __traceback__ when
# normalizing tracebacks across a `yield`). A plain frozen dataclass rejects
# ALL attribute assignment, including these, which crashes any code path
# where a ConfigValidationError propagates out of a context manager or
# generator-based decorator (this is exactly what Click's
# `augment_usage_errors` does around every command callback). Allow these
# specific attributes through while keeping the declared dataclass fields
# genuinely immutable.
_EXC_INTERNAL_ATTRS = frozenset(
    {"__traceback__", "__cause__", "__context__", "__suppress_context__", "__notes__"}
)


@dataclass(frozen=True)
class ConfigValidationError(Exception):
    """Raised by config loaders when YAML/Pydantic validation fails.

    Attributes:
        file: Source file path (rendered relative to CWD when possible).
        line: 1-indexed line of the offending mapping, or ``None`` when no
            line is available (e.g. file-not-found, FileNotFoundError-like).
        field_path: Dotted/bracketed path to the offending field
            (e.g. ``per_release_tickets[0].fields.story_points``). Use
            ``"<root>"`` when the error is at the document root,
            ``"<file>"`` for I/O errors, ``"<yaml>"`` for parse errors.
        reason: Human-readable failure reason (typically the Pydantic msg).
        suggestion: Optional ``did_you_mean``-style hint, in parentheses,
            ready to append (e.g. ``"(did you mean 'story_points'?)"``).
    """

    file: Path
    line: int | None
    field_path: str
    reason: str
    suggestion: str | None = None

    def __str__(self) -> str:
        rel = self._relative_to_cwd()
        line_part = f":{self.line}" if self.line is not None else ""
        suffix = f" {self.suggestion}" if self.suggestion else ""
        return f"{rel}{line_part}: {self.field_path} — {self.reason}{suffix}"

    def _relative_to_cwd(self) -> str:
        """Render ``file`` relative to CWD if possible, else absolute.

        Relative paths use forward slashes (``as_posix``) so error output is
        identical on Windows, macOS, and Linux. Absolute fallbacks keep the
        OS-native separator.
        """
        try:
            return self.file.resolve().relative_to(Path.cwd()).as_posix()
        except ValueError:
            return str(self.file)


# dataclass(frozen=True) refuses to decorate a class that already defines
# __setattr__ in its own body (it must generate that method itself), so the
# dunder-attribute carve-out is patched on immediately after class creation
# instead. This still fully preserves immutability for the declared fields
# above — only the whitelisted exception-internal attributes bypass it.
_frozen_setattr = ConfigValidationError.__setattr__


def _setattr_allowing_exception_internals(
    self: ConfigValidationError, name: str, value: object
) -> None:
    if name in _EXC_INTERNAL_ATTRS:
        object.__setattr__(self, name, value)
        return
    _frozen_setattr(self, name, value)


ConfigValidationError.__setattr__ = _setattr_allowing_exception_internals  # type: ignore[method-assign]


def format_loc(loc: tuple[int | str, ...]) -> str:
    """Render a Pydantic ``loc`` tuple as a dotted/bracketed field path.

    Examples::

        format_loc(())                                            == ""
        format_loc(("a",))                                        == "a"
        format_loc(("a", 0, 1))                                   == "a[0][1]"
        format_loc((0, "a"))                                      == "[0].a"
        format_loc(("teams", 0, "tickets", 3, "fields", "x"))     == "teams[0].tickets[3].fields.x"
    """
    parts: list[str] = []
    for step in loc:
        if isinstance(step, int):
            parts.append(f"[{step}]")
        else:
            # String step — separator depends on whether anything precedes it.
            if not parts:
                parts.append(str(step))
            else:
                parts.append(f".{step}")
    return "".join(parts)


def did_you_mean(
    value: str,
    candidates: list[str],
    *,
    n: int = 3,
    cutoff: float = 0.7,
) -> str | None:
    """Return a PEP-657-style suggestion string, or ``None`` on no match.

    Args:
        value: The user-supplied (likely misspelled) name.
        candidates: Known-good names to match against.
        n: Max number of close matches to consider.
        cutoff: ``difflib.get_close_matches`` similarity floor (0.0-1.0).

    Returns:
        - ``None`` when no candidate scores above ``cutoff``.
        - ``"(did you mean 'X'?)"`` when exactly one candidate matches —
          mirrors Python 3.11+ NameError phrasing.
        - ``"(closest matches: X, Y, Z)"`` when ≥2 candidates match.
    """
    matches = difflib.get_close_matches(value, candidates, n=n, cutoff=cutoff)
    if not matches:
        return None
    if len(matches) == 1:
        return f"(did you mean '{matches[0]}'?)"
    return f"(closest matches: {', '.join(matches)})"


# ---------------------------------------------------------------------------
# Phase 02-01 — layered-config merge conflict warning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigConflictWarning:
    """A merge-time conflict surfaced when a later layer tries to write a key
    locked by an earlier layer.

    Emitted to stderr by ``jiramator.config.load_team_config`` (and, in a
    later plan, by the org-vs-team ``merge_configs``); NOT raised — the
    config still loads with the earlier-layer winner.

    Format:
        ``<later-file>[:<later-line>]: <field-path> — locked by
        <earlier-layer> (<earlier-file>[:<earlier-line>]); later value
        ignored.``

    Attributes:
        later_file:    File of the layer whose write was dropped.
        later_line:    1-indexed line of the dropped write (``None`` if unknown).
        earlier_file:  File of the layer that locked the key.
        earlier_line:  1-indexed line of the locking declaration (``None`` if unknown).
        field_path:    Dotted/bracketed path (mirrors ``format_loc`` shape).
        earlier_layer: Human label — ``"team defaults"`` (this plan) or
                       ``"org config"`` (Plan 02-02).

    NOT an ``Exception`` subclass — warnings are printed, not raised.
    """

    later_file: Path
    later_line: int | None
    earlier_file: Path
    earlier_line: int | None
    field_path: str
    earlier_layer: str

    def __str__(self) -> str:
        later = self._rel(self.later_file)
        ll = f":{self.later_line}" if self.later_line is not None else ""
        earlier = self._rel(self.earlier_file)
        el = f":{self.earlier_line}" if self.earlier_line is not None else ""
        return (
            f"{later}{ll}: {self.field_path} — locked by {self.earlier_layer} "
            f"({earlier}{el}); later value ignored."
        )

    @staticmethod
    def _rel(p: Path) -> str:
        """Render ``p`` relative to CWD if possible, else absolute.

        Mirrors ``ConfigValidationError._relative_to_cwd`` so both
        formatters render paths identically — relative paths use forward
        slashes for cross-platform-consistent output.
        """
        try:
            return p.resolve().relative_to(Path.cwd()).as_posix()
        except ValueError:
            return str(p)
