"""Layered config merge engine for Phase 2 template inheritance.

Pure functions; no I/O. The orchestrator (``merge_configs``) is called by
``cli.py:plan`` after both ``load_org_config`` and ``load_team_config``,
piping the returned warnings to ``Console(stderr=True)``.

Public surface:
    merge_configs                       — top-level orchestrator
                                          (org → team-defaults → templates)
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
    from rich.console import Console

    from jiramator.config import OrgConfig, TeamConfig


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


def _apply_team_layer_to_templates(
    team_model: TeamConfig,
    team_tagged_raw: object,
    team_file: Path,
    *,
    earlier_layer: str = "team defaults",
) -> list[ConfigConflictWarning]:
    """Merge ``team_model.defaults.fields`` into every template's ``fields``.

    Internal helper called by ``merge_configs`` (layer 2). Also used by the
    test suite to exercise team-layer behavior in isolation. The function
    mutates each template's ``fields``; it returns the (un-emitted)
    warnings so the caller can route them however it likes.
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
                earlier_layer=earlier_layer,
            )
            tmpl.fields = merged
            all_warnings.extend(warnings)
    return all_warnings


def merge_configs(
    *,
    org_model: OrgConfig,
    org_tagged_raw: object,
    org_file: Path,
    team_model: TeamConfig,
    team_tagged_raw: object,
    team_file: Path,
    console: Console | None = None,
) -> TeamConfig:
    """Apply the layered merge: org.default_fields → team.defaults.fields → template fields.

    The single composition point for Phase 2 template inheritance. Called
    by ``cli.py:plan`` between ``load_*_config`` and ``run_plan``.

    Mutates ``team_model``:
        - ``team_model.defaults.fields`` is replaced with the merged
          effective team-level lock layer (org default_fields composed
          earlier-wins onto team-declared defaults).
        - Every template's ``fields`` (recurring_epics, per_release_tickets,
          per_sprint_tickets) is replaced with the result of merging the
          effective team-level lock layer earlier onto the template's
          declared fields.

    The original ``org_model.default_fields`` dict is NOT mutated; the
    merge always builds fresh dicts (T-02-09).

    Layer order (CONTEXT working_model, RESEARCH §R4):
        1. ``org_model.default_fields``       — locked org-wide
        2. ``team_model.defaults.fields``     — locked team-wide (gap-fill
           against org locks, earlier-wins on collisions)
        3. per-template ``fields``            — fills remaining gaps

    Args:
        org_model:        Validated ``OrgConfig`` (carries ``default_fields``).
        org_tagged_raw:   Line-tagged YAML tree from ``load_org_config``.
        org_file:         Path of the org config file (for warning text).
        team_model:       Validated ``TeamConfig`` (carries ``defaults`` +
                          template lists). Mutated in place.
        team_tagged_raw:  Line-tagged YAML tree from ``load_team_config``.
        team_file:        Path of the team config file (for warning text).
        console:          Optional ``rich.console.Console`` to receive
                          ``ConfigConflictWarning`` lines. When ``None``,
                          a fresh ``Console(stderr=True)`` is instantiated.

    Returns:
        The mutated ``team_model`` for caller convenience.

    Conflict-warning attribution:
        - Layer-1 conflicts (org default_fields vs team defaults.fields)
          set ``earlier_layer="org config"``.
        - Layer-2 conflicts (effective team-level locks vs per-template
          ``fields:``) set ``earlier_layer="team defaults"``. The merged
          ``team_model.defaults.fields`` reflects the org overrides, so
          users can introspect to see which keys are org-locked.
    """
    warnings: list[ConfigConflictWarning] = []

    # --- Layer 1: org.default_fields  →  team.defaults.fields -------------
    org_defaults = org_model.default_fields or {}
    team_defaults_fields = team_model.defaults.fields or {}
    merged_team_defaults, w1 = deep_merge_dicts(
        earlier=org_defaults,
        later=team_defaults_fields,
        path_prefix="defaults.fields",
        earlier_file=org_file,
        later_file=team_file,
        earlier_loc=("default_fields",),
        later_loc=("defaults", "fields"),
        earlier_tagged_root=org_tagged_raw,
        later_tagged_root=team_tagged_raw,
        earlier_layer="org config",
    )
    warnings.extend(w1)
    # Persist the merged effective layer so introspection sees it.
    team_model.defaults.fields = merged_team_defaults

    # --- Layer 2: effective team-level locks  →  per-template fields ------
    w2 = _apply_team_layer_to_templates(
        team_model=team_model,
        team_tagged_raw=team_tagged_raw,
        team_file=team_file,
        earlier_layer="team defaults",
    )
    warnings.extend(w2)

    # --- Emit warnings ----------------------------------------------------
    if warnings:
        if console is None:
            from rich.console import Console as _Console
            console = _Console(stderr=True)
        for w in warnings:
            console.print(str(w), highlight=False, markup=False)

    return team_model
