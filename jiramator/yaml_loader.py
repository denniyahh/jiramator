"""Line-aware YAML loader for actionable config validation errors (FOUND-01).

Subclasses ``yaml.SafeLoader`` to inject a ``__line__`` key (1-indexed source
line number) on every constructed mapping. Exposes ``resolve_line``, which walks
a Pydantic ``loc`` tuple through the parsed-but-tagged structure and returns the
deepest available line for use in error messages.

The injected ``__line__`` markers must be stripped before any Jira-bound
payload assembly — see ``jiramator/ticket_builder.py:_strip_line_markers``
(Pitfall 1 in the phase RESEARCH.md).
"""

from __future__ import annotations

from typing import Any

import yaml

# Internal key injected on every parsed mapping to record its 1-indexed source
# line. Centralized so callers (notably the ticket builder) can strip it.
LINE_KEY = "__line__"


class SafeLineLoader(yaml.SafeLoader):
    """SafeLoader that records the 1-indexed source line of every mapping.

    Inherits SafeLoader's safety guarantees (no arbitrary tag construction,
    no Python object instantiation). The only behavior added is a write of
    ``mapping[LINE_KEY] = node.start_mark.line + 1`` after the parent
    constructor returns.

    A YAML document that itself contains a ``__line__`` key gets clobbered by
    this write — by design. Trusted boundary: the injected marker always wins.
    """

    def construct_mapping(self, node, deep=False):  # type: ignore[override]
        mapping = super().construct_mapping(node, deep=deep)
        # node.start_mark.line is 0-indexed; user-facing lines are 1-indexed.
        mapping[LINE_KEY] = node.start_mark.line + 1
        return mapping


def safe_load_with_lines(stream: Any) -> object:
    """Parse YAML from ``stream`` using ``SafeLineLoader``.

    Thin wrapper kept as a stable import target — callers should use this
    rather than instantiating the loader directly.
    """
    return yaml.load(stream, Loader=SafeLineLoader)


def resolve_line(raw: object, loc: tuple[int | str, ...]) -> int | None:
    """Walk ``raw`` along ``loc`` and return the deepest mapping's ``__line__``.

    Used to translate a Pydantic ``ValidationError.errors()[0]["loc"]`` tuple
    into a source-line number for ``ConfigValidationError``.

    Behavior:
        - Empty/non-dict ``raw`` returns ``None``.
        - For each step in ``loc``:
            * Mapping step (``str``): walk into ``current[step]`` if it exists
              and is a dict; otherwise stop (return last seen line).
            * List step (``int``): walk into ``current[step]`` if in range and
              the element is a dict; otherwise stop (return last seen line).
            * Scalar leaves: return the last seen mapping line (the parent).
        - If walking exhausts ``loc`` and lands on a dict, return that dict's
          ``__line__``; otherwise return the last seen line.

    The function never raises on malformed input — it degrades to ``None`` or
    the deepest valid line so error formatting stays robust.
    """
    if not isinstance(raw, dict):
        return None

    current: Any = raw
    last_line: int | None = current.get(LINE_KEY)

    for step in loc:
        if isinstance(current, dict):
            if isinstance(step, str) and step in current:
                next_value = current[step]
                if isinstance(next_value, dict):
                    current = next_value
                    last_line = current.get(LINE_KEY, last_line)
                    continue
                if isinstance(next_value, list):
                    # Walk into the list — it has no __line__ itself, but its
                    # dict elements do. Keep last_line as the parent's.
                    current = next_value
                    continue
                # Step exists but is a scalar — return parent's line.
                return last_line
            # Step is an int into a dict, or a missing key → stop here.
            return last_line

        if isinstance(current, list):
            if isinstance(step, int) and 0 <= step < len(current):
                next_value = current[step]
                if isinstance(next_value, dict):
                    current = next_value
                    last_line = current.get(LINE_KEY, last_line)
                    continue
                return last_line
            # Out-of-range index or non-int step into a list → stop here.
            return last_line

        # Reached a scalar — nothing more to walk.
        return last_line

    # Loc exhausted; current may be a dict (return its line) or other type.
    if isinstance(current, dict):
        return current.get(LINE_KEY, last_line)
    return last_line


def strip_line_markers(obj: Any) -> Any:
    """Return a deep copy of ``obj`` with every ``LINE_KEY`` entry removed.

    The line-aware loader injects ``__line__`` on every parsed mapping. Pydantic
    models with ``dict[str, Any]`` fields (e.g. ``TicketTemplate.fields``) pass
    these through, which would leak the marker into Jira REST API payloads.
    Call this on raw config dicts before model construction, and on the
    ``fields`` dict before assembling Jira-bound payloads.

    The input is not mutated. Non-dict / non-list leaves are returned as-is
    (so the same scalar object is shared between input and output — fine,
    scalars are immutable).
    """
    if isinstance(obj, dict):
        return {k: strip_line_markers(v) for k, v in obj.items() if k != LINE_KEY}
    if isinstance(obj, list):
        return [strip_line_markers(v) for v in obj]
    return obj
