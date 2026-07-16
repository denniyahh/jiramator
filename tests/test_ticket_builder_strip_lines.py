"""Tests for the __line__ marker defuser in ticket_builder (FOUND-01).

Plan: 01-01 Task 3, Pitfall 1.

The line-aware YAML loader injects ``__line__: <int>`` on every parsed
mapping. Pydantic models pass these through (``dict[str, Any]`` accepts
unknown keys), so they would leak into Jira REST API payloads unless
stripped. ``_strip_line_markers`` walks the structure recursively and
removes the marker from every dict, returning a clean copy.

Two layers of coverage:
- Unit tests of ``_strip_line_markers`` directly (top-level / nested /
  list / scalar / mixed / no-mutation).
- S1–S4 integration tests that exercise ``_build_fields_payload`` and a
  full ``build_all(...)`` run on the real shipped Calcs config to prove
  no payload leaks ``__line__`` end-to-end.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jiramator.ticket_builder import _build_fields_payload, _strip_line_markers, build_all
from jiramator.yaml_loader import LINE_KEY


def test_strip_top_level_marker():
    """Test 1: __line__ at top level is removed."""
    out = _strip_line_markers({"a": 1, LINE_KEY: 5})
    assert out == {"a": 1}
    assert LINE_KEY not in out


def test_strip_nested_dict_marker():
    """Test 2: __line__ in a nested dict is removed."""
    out = _strip_line_markers({"outer": {"inner": 1, LINE_KEY: 7}, LINE_KEY: 3})
    assert out == {"outer": {"inner": 1}}


def test_strip_list_of_dicts_marker():
    """Test 3: __line__ inside list-of-dicts is removed from each element."""
    out = _strip_line_markers(
        {
            "items": [
                {"a": 1, LINE_KEY: 2},
                {"b": 2, LINE_KEY: 3},
            ],
            LINE_KEY: 1,
        }
    )
    assert out == {"items": [{"a": 1}, {"b": 2}]}


def test_no_marker_returns_equivalent_dict():
    """Test 4: Input without markers passes through unchanged in value."""
    src = {"a": 1, "b": [1, 2, 3], "c": {"d": "x"}}
    out = _strip_line_markers(src)
    assert out == src


def test_does_not_mutate_input():
    """Test 5: Input dict is not mutated (returns a copy)."""
    src = {"a": 1, LINE_KEY: 5, "nested": {"x": 1, LINE_KEY: 6}}
    snapshot = {"a": 1, LINE_KEY: 5, "nested": {"x": 1, LINE_KEY: 6}}
    _ = _strip_line_markers(src)
    assert src == snapshot


def test_handles_scalar_values():
    """Test 6: Scalar leaves (str/int/None/bool) pass through."""
    out = _strip_line_markers(
        {"s": "x", "i": 1, "n": None, "b": True, LINE_KEY: 9}
    )
    assert out == {"s": "x", "i": 1, "n": None, "b": True}


def test_handles_list_of_scalars():
    """Test 7: List of scalars passes through untouched."""
    out = _strip_line_markers({"tags": ["a", "b", "c"], LINE_KEY: 1})
    assert out == {"tags": ["a", "b", "c"]}


def test_deeply_nested_mixed_structure():
    """Test 8: Deep mix of dicts/lists with markers everywhere is fully cleaned."""
    src = {
        LINE_KEY: 1,
        "components": [
            {"name": "api", LINE_KEY: 3, "tags": ["x", "y"]},
            {
                "name": "ui",
                LINE_KEY: 5,
                "meta": {"owner": "team", LINE_KEY: 6},
            },
        ],
        "config": {LINE_KEY: 8, "k": "v"},
    }
    out = _strip_line_markers(src)
    assert out == {
        "components": [
            {"name": "api", "tags": ["x", "y"]},
            {"name": "ui", "meta": {"owner": "team"}},
        ],
        "config": {"k": "v"},
    }
    # Verify marker is gone everywhere
    def _no_marker(obj: object) -> bool:
        if isinstance(obj, dict):
            return LINE_KEY not in obj and all(_no_marker(v) for v in obj.values())
        if isinstance(obj, list):
            return all(_no_marker(v) for v in obj)
        return True

    assert _no_marker(out)


# ---------------------------------------------------------------------------
# S1–S4: Pitfall 1 wiring tests through _build_fields_payload + build_all
# ---------------------------------------------------------------------------


def _no_line_marker(obj: object) -> bool:
    """Recursive predicate: returns True iff obj contains no LINE_KEY anywhere."""
    if isinstance(obj, dict):
        return LINE_KEY not in obj and all(_no_line_marker(v) for v in obj.values())
    if isinstance(obj, list):
        return all(_no_line_marker(v) for v in obj)
    return True


def test_S1_build_fields_payload_strips_top_level_marker():
    """S1: _build_fields_payload removes a top-level __line__ from template_fields."""
    payload = _build_fields_payload(
        template_fields={"description": "x", LINE_KEY: 12},
        summary="hello",
        project_key="CA",
        variables={},
        epic_keys={},
    )
    assert LINE_KEY not in payload
    assert _no_line_marker(payload)


def test_S2_build_fields_payload_strips_nested_marker():
    """S2: _build_fields_payload strips __line__ at any nesting depth."""
    payload = _build_fields_payload(
        template_fields={"a": {"b": "x", LINE_KEY: 7}, LINE_KEY: 5},
        summary="hello",
        project_key="CA",
        variables={},
        epic_keys={},
    )
    assert _no_line_marker(payload)


def test_S3_build_fields_payload_strips_marker_inside_list_of_dicts():
    """S3: _build_fields_payload strips __line__ from list-of-dict elements."""
    payload = _build_fields_payload(
        template_fields={"items": [{"x": 1, LINE_KEY: 9}], LINE_KEY: 8},
        summary="hello",
        project_key="CA",
        variables={},
        epic_keys={},
    )
    assert _no_line_marker(payload)


def test_S4_build_all_on_real_calcs_config_emits_no_marker():
    """S4: full build_all on the shipped Calcs config produces no payload
    that contains __line__ anywhere (integration-level Pitfall 1 safety net)."""
    from jiramator.config import load_org_config, load_team_config

    repo_root = Path(__file__).resolve().parent.parent
    org_path = repo_root / "configs" / "org.example" / "example.yaml"
    # Tracked fixture (not the gitignored configs/teams/ dir) so this test
    # is reproducible on a fresh clone / in CI.
    team_path = repo_root / "tests" / "fixtures" / "teams" / "calcs.yaml"
    if not org_path.exists():
        pytest.skip("Shipped configs not present in this checkout")

    org_cfg, _ = load_org_config(org_path)
    team_cfg, _ = load_team_config(team_path)
    bundle = build_all(
        org_config=org_cfg,
        team_config=team_cfg,
        pi_label="PI28",
        pi_num="28",
        versions=["28.1", "28.2", "28.3"],
        epic_keys={},
    )
    # Walk every payload across all three buckets — must be marker-free.
    assert _no_line_marker(bundle)
