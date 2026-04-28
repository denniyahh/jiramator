"""Tests for the line-aware YAML loader and Pydantic-loc → line resolver.

Plan: 01-01 Task 1 (FOUND-01).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jiramator.yaml_loader import (
    LINE_KEY,
    SafeLineLoader,
    resolve_line,
    safe_load_with_lines,
)

FIXTURES = Path(__file__).parent / "fixtures" / "yaml_errors"


# ---------------------------------------------------------------------------
# SafeLineLoader behavior
# ---------------------------------------------------------------------------


def test_top_level_mapping_records_line_1():
    """Test 1: A flat mapping records __line__: 1 (1-indexed)."""
    raw = safe_load_with_lines("a: 1\nb: 2\n")
    assert isinstance(raw, dict)
    assert raw[LINE_KEY] == 1
    assert raw["a"] == 1
    assert raw["b"] == 2


def test_nested_mapping_records_lines_for_each_dict():
    """Test 2: Nested mappings each carry their own __line__."""
    raw = safe_load_with_lines("team:\n  name: foo\n")
    assert raw[LINE_KEY] == 1
    assert raw["team"][LINE_KEY] == 2
    assert raw["team"]["name"] == "foo"


def test_list_of_mappings_each_item_has_line_marker():
    """Test 3: Each dict inside a list of mappings records __line__."""
    raw = safe_load_with_lines("items:\n  - a: 1\n  - b: 2\n")
    assert raw[LINE_KEY] == 1
    assert raw["items"][0][LINE_KEY] == 2
    assert raw["items"][1][LINE_KEY] == 3


def test_lines_are_1_indexed_with_leading_blanks_and_comments(tmp_path):
    """Test 4: First mapping starts on line 5 → __line__ == 5 (1-indexed)."""
    src = "# comment line 1\n# comment line 2\n\n\nfirst_key: value\n"
    raw = safe_load_with_lines(src)
    # The first key/mapping starts on line 5
    assert raw[LINE_KEY] == 5


def test_safe_load_with_lines_is_deterministic_wrapper():
    """Test 5: safe_load_with_lines is a thin wrapper around yaml.load(..., SafeLineLoader)."""
    src = "a: 1\nb:\n  c: 2\n"
    out1 = safe_load_with_lines(src)
    out2 = yaml.load(src, Loader=SafeLineLoader)
    assert out1 == out2


# ---------------------------------------------------------------------------
# resolve_line behavior
# ---------------------------------------------------------------------------


def test_resolve_line_scalar_value_returns_parent_line():
    """Test 6: For a scalar leaf, resolve_line returns the parent mapping's line."""
    raw = safe_load_with_lines("a: 1\nb: 2\n")
    # 'a' is a scalar leaf; the parent (raw itself) is on line 1
    assert resolve_line(raw, ("a",)) == 1


def test_resolve_line_into_list_dict_returns_dict_line():
    """Test 7: resolve_line(raw, ('items', 1, 'b')) returns the line of items[1]."""
    raw = safe_load_with_lines("items:\n  - a: 1\n  - b: 2\n")
    # items[1] is on line 3
    assert resolve_line(raw, ("items", 1, "b")) == 3


def test_resolve_line_out_of_bounds_list_index_returns_deepest_valid():
    """Test 8: Out-of-range list index returns the deepest valid __line__ reached."""
    raw = safe_load_with_lines("items:\n  - a: 1\n  - b: 2\n")
    # items[99] does not exist; deepest valid is the 'items' container.
    # The list itself has no __line__ (lists are not dicts), so resolve_line
    # falls back to the parent of 'items' (the root mapping), line 1.
    result = resolve_line(raw, ("items", 99, "b"))
    assert result == 1
    assert result is not None


def test_resolve_line_missing_dict_key_returns_parent_line():
    """Test 9: Missing key returns the parent's __line__ (Pydantic 'missing' case)."""
    raw = safe_load_with_lines("a: 1\nb: 2\n")
    assert resolve_line(raw, ("nonexistent",)) == 1


def test_resolve_line_walks_into_nested_mapping_at_existing_key():
    """Test 10: resolve_line into an existing key whose value is a mapping returns that mapping's line."""
    raw = safe_load_with_lines("outer:\n  inner: 1\n")
    # 'outer' value is a dict on line 2; the loc just names it.
    assert resolve_line(raw, ("outer",)) == 2


def test_resolve_line_empty_raw_returns_none():
    """Test 11: Empty/non-dict raw returns None."""
    assert resolve_line({}, ("a",)) is None
    assert resolve_line(None, ("a",)) is None


# ---------------------------------------------------------------------------
# Fixture sanity — fixtures load (or fail) as expected
# ---------------------------------------------------------------------------


def test_yaml_parse_error_fixture_raises_with_problem_mark():
    """The yaml_parse_error.yaml fixture must trigger YAMLError with a problem_mark on line 3."""
    text = (FIXTURES / "yaml_parse_error.yaml").read_text()
    with pytest.raises(yaml.YAMLError) as exc_info:
        safe_load_with_lines(text)
    mark = getattr(exc_info.value, "problem_mark", None)
    assert mark is not None
    # mark.line is 0-indexed; the unclosed quote starts on line 3 (1-indexed).
    # YAML may report the error on a later line as it scans for the closing
    # quote. Accept the actual reported line as long as it is >= 3.
    assert mark.line + 1 >= 3
