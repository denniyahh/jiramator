"""Layered config merge engine for Phase 2 template inheritance.

Pure functions; no I/O. The orchestrator (``config.load_team_config`` and,
in Plan 02-02, ``merge_configs``) calls these and pipes the returned
warnings to ``Console(stderr=True)``.

Public surface:
    merge_team_defaults_into_templates  — top-level orchestrator (this plan)
    deep_merge_dicts                    — earlier-wins recursive dict merge
    concat_dedup_lists                  — earlier-first list concat with
                                          canonical-form dedup
    canonical_form                      — JSON-canonical form for dedup keys

Merge rules (CONTEXT G-1, R3, R4):
    - Disjoint keys flow through.
    - Same-key dict×dict   → recurse.
    - Same-key list×list   → ``concat_dedup_lists`` (NO warning — lists are
      union-by-design; multi-select fields legitimately accumulate values).
    - Same-key scalar×anything (or any shape mismatch) → earlier wins,
      ONE ``ConfigConflictWarning`` emitted with the dotted field path.

The engine never mutates its inputs; it builds fresh dicts. Line markers
injected by ``yaml_loader.SafeLineLoader`` (``LINE_KEY``) are skipped on
both sides as a defense-in-depth measure (T-02-01).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jiramator.error_format import ConfigConflictWarning
from jiramator.yaml_loader import LINE_KEY, resolve_line

if TYPE_CHECKING:
    from jiramator.config import TeamConfig


def canonical_form(item: object) -> str:
    """Return a deterministic JSON string suitable as a dedup key.

    Uses ``sort_keys=True`` for determinism across dict orderings and
    ``default=str`` to gracefully handle non-JSON-native values (e.g.
    ``Path`` instances, custom objects) without raising.

    Examples::

        canonical_form("audit")           == '"audit"'
        canonical_form({"value": "No"})   == '{"value":"No"}'
        canonical_form({"b": 1, "a": 2})  == '{"a":2,"b":1}'
    """
    return json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)


def concat_dedup_lists(earlier: list[Any], later: list[Any]) -> list[Any]:
    """Return ``earlier + later`` with structural dedup (first occurrence wins).

    Dedup key is ``canonical_form(item)``; this handles primitives, dicts,
    and nested structures uniformly. Order is preserved earlier-first.

    Examples::

        concat_dedup_lists(["a", "b"], ["b", "c"])               == ["a", "b", "c"]
        concat_dedup_lists([{"value": "No"}], [{"value": "No"}]) == [{"value": "No"}]
    """
    seen: set[str] = set()
    out: list[Any] = []
    for item in (*earlier, *later):
        key = canonical_form(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def deep_merge_dicts(
    earlier: dict[str, Any],
    later: dict[str, Any],
    *,
    path_prefix: str,
    earlier_file: Path,
    later_file: Path,
    earlier_loc: tuple[int | str, ...],
    later_loc: tuple[int | str, ...],
    earlier_tagged_root: object,
    later_tagged_root: object,
    earlier_layer: str,
) -> tuple[dict[str, Any], list[ConfigConflictWarning]]:
    """Earlier-wins recursive dict merge with conflict warnings.

    Args:
        earlier:               The locking layer's dict (e.g. team defaults).
        later:                 The dropped-on-conflict layer's dict.
        path_prefix:           Dotted path prefix for nested warnings; ``""``
                               at the top of the merge.
        earlier_file:          File of the locking layer (for warning text).
        later_file:            File of the would-be writer (for warning text).
        earlier_loc:           Pydantic-style ``loc`` of ``earlier`` inside
                               ``earlier_tagged_root`` (used by ``resolve_line``).
        later_loc:             Same, for ``later``.
        earlier_tagged_root:   Full line-tagged tree containing the earlier
                               layer (typically the team config tagged_raw).
        later_tagged_root:     Full line-tagged tree containing the later
                               layer (same tree as ``earlier_tagged_root``
                               for intra-file conflicts).
        earlier_layer:         Human-readable label for the locking layer
                               (``"team defaults"`` or ``"org config"``).

    Returns:
        ``(merged, warnings)``: a fresh dict (no input mutation) and a list
        of conflict warnings to emit to stderr.

    The ``LINE_KEY`` marker is never propagated into ``merged``.
    """
    warnings: list[ConfigConflictWarning] = []
    out: dict[str, Any] = {}

    # Copy earlier first (skip line markers).
    for k, v in earlier.items():
        if k == LINE_KEY:
            continue
        out[k] = v

    # Merge later into earlier.
    for k, v in later.items():
        if k == LINE_KEY:
            continue
        if k not in out:
            out[k] = v
            continue

        ev = out[k]
        field_path = f"{path_prefix}.{k}" if path_prefix else k

        if isinstance(ev, dict) and isinstance(v, dict):
            merged, sub_warnings = deep_merge_dicts(
                ev,
                v,
                path_prefix=field_path,
                earlier_file=earlier_file,
                later_file=later_file,
                earlier_loc=(*earlier_loc, k),
                later_loc=(*later_loc, k),
                earlier_tagged_root=earlier_tagged_root,
                later_tagged_root=later_tagged_root,
                earlier_layer=earlier_layer,
            )
            out[k] = merged
            warnings.extend(sub_warnings)
        elif isinstance(ev, list) and isinstance(v, list):
            # Lists are union-by-design — no conflict.
            out[k] = concat_dedup_lists(ev, v)
        else:
            # Scalar conflict OR shape mismatch — earlier wins; warn.
            warnings.append(
                ConfigConflictWarning(
                    later_file=later_file,
                    later_line=resolve_line(later_tagged_root, (*later_loc, k)),
                    earlier_file=earlier_file,
                    earlier_line=resolve_line(earlier_tagged_root, (*earlier_loc, k)),
                    field_path=field_path,
                    earlier_layer=earlier_layer,
                )
            )
            # out[k] already holds ev — earlier wins.

    return out, warnings


def merge_team_defaults_into_templates(
    team_model: TeamConfig,
    team_tagged_raw: object,
    team_file: Path,
) -> list[ConfigConflictWarning]:
    """Apply ``team_model.defaults.fields`` into every template's ``fields``.

    Mutates (in place) the ``fields`` attribute of every entry in:
        - ``team_model.recurring_epics``
        - ``team_model.per_release_tickets``
        - ``team_model.per_sprint_tickets``

    The original ``team_model.defaults.fields`` dict is NOT mutated; the
    merge always builds fresh dicts (T-02-06).

    Args:
        team_model:        The validated ``TeamConfig`` to enrich.
        team_tagged_raw:   The line-tagged YAML tree from
                           ``yaml_loader.safe_load_with_lines`` (used to
                           resolve line numbers for conflict warnings).
        team_file:         The team config file path (for warning text).

    Returns:
        A list of ``ConfigConflictWarning`` describing per-template
        same-key conflicts where the template tried to override a key
        locked by team defaults. Empty list if ``defaults.fields`` is empty.
    """
    defaults_fields = team_model.defaults.fields
    if not defaults_fields:
        return []

    all_warnings: list[ConfigConflictWarning] = []
    sources: list[tuple[str, list[Any]]] = [
        ("recurring_epics", team_model.recurring_epics),
        ("per_release_tickets", team_model.per_release_tickets),
        ("per_sprint_tickets", team_model.per_sprint_tickets),
    ]

    for list_name, templates in sources:
        for idx, tmpl in enumerate(templates):
            merged, warnings = deep_merge_dicts(
                earlier=defaults_fields,
                later=tmpl.fields,
                path_prefix=f"{list_name}[{idx}].fields",
                earlier_file=team_file,
                later_file=team_file,
                earlier_loc=("defaults", "fields"),
                later_loc=(list_name, idx, "fields"),
                earlier_tagged_root=team_tagged_raw,
                later_tagged_root=team_tagged_raw,
                earlier_layer="team defaults",
            )
            tmpl.fields = merged
            all_warnings.extend(warnings)

    return all_warnings
