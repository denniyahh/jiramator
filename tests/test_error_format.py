"""Tests for the ConfigValidationError dataclass and helpers (FOUND-01).

Plan: 01-01 Task 2.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jiramator.error_format import (
    ConfigConflictWarning,
    ConfigValidationError,
    did_you_mean,
    format_loc,
)


# ---------------------------------------------------------------------------
# ConfigValidationError.__str__
# ---------------------------------------------------------------------------


def test_str_format_basic_with_line(tmp_path, monkeypatch):
    """Test 1: file:line: field — reason format with em-dash and single spaces."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "configs" / "teams" / "calcs.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("placeholder")
    err = ConfigValidationError(
        file=target,
        line=42,
        field_path="per_release_tickets[0].fields.story_points",
        reason="Input should be a valid integer",
    )
    assert str(err) == (
        "configs/teams/calcs.yaml:42: per_release_tickets[0].fields.story_points "
        "— Input should be a valid integer"
    )


def test_str_appends_suggestion_with_single_space(tmp_path, monkeypatch):
    """Test 2: suggestion appends with a single-space separator."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "configs" / "teams" / "calcs.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    err = ConfigValidationError(
        file=target,
        line=42,
        field_path="per_release_tickets[0].fields.story_points",
        reason="Input should be a valid integer",
        suggestion="(did you mean 'story_points'?)",
    )
    assert str(err).endswith(
        "Input should be a valid integer (did you mean 'story_points'?)"
    )


def test_str_omits_line_when_none(tmp_path, monkeypatch):
    """Test 3: When line is None, the :line segment is omitted."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "calcs.yaml"
    target.write_text("x")
    err = ConfigValidationError(
        file=target,
        line=None,
        field_path="<file>",
        reason="Team config not found: calcs.yaml",
    )
    rendered = str(err)
    assert ":<file>:" not in rendered
    assert ": <file>" in rendered
    # No `:42:` style line segment between filename and field
    assert rendered.startswith("calcs.yaml: <file> — Team config not found:")


def test_str_path_outside_cwd_renders_absolute(tmp_path, monkeypatch):
    """Test 4: Path outside CWD renders as absolute (relative_to falls back)."""
    # Make CWD a separate directory; the config file lives elsewhere.
    cwd_dir = tmp_path / "cwd"
    cwd_dir.mkdir()
    monkeypatch.chdir(cwd_dir)
    other_dir = tmp_path / "elsewhere"
    other_dir.mkdir()
    target = other_dir / "calcs.yaml"
    target.write_text("x")
    err = ConfigValidationError(
        file=target,
        line=1,
        field_path="<root>",
        reason="bad",
    )
    rendered = str(err)
    # Falls back to absolute path
    assert str(target) in rendered or str(target.resolve()) in rendered


def test_str_path_inside_cwd_renders_relative(tmp_path, monkeypatch):
    """Test 5: Path inside CWD renders relative."""
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "configs" / "teams" / "calcs.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("x")
    err = ConfigValidationError(
        file=target, line=1, field_path="<root>", reason="bad",
    )
    rendered = str(err)
    assert rendered.startswith("configs/teams/calcs.yaml:")


def test_is_exception_subclass_and_frozen(tmp_path):
    """Test 6: ConfigValidationError is an Exception subclass and is frozen."""
    target = tmp_path / "x.yaml"
    target.write_text("x")
    err = ConfigValidationError(
        file=target, line=1, field_path="<root>", reason="bad",
    )
    assert isinstance(err, Exception)
    # Must be raisable
    with pytest.raises(ConfigValidationError):
        raise err
    # Must be immutable post-construction
    with pytest.raises(Exception):
        err.line = 99  # type: ignore[misc]


def test_propagates_through_click_command_without_crashing(tmp_path):
    """Regression: frozen dataclass exceptions used to crash when propagating
    out of a Click command callback.

    Click wraps every command invocation in ``augment_usage_errors``, a
    ``@contextlib.contextmanager``-based context manager. When an exception
    escapes the ``with`` block, ``contextlib``'s generator machinery
    explicitly reassigns ``exc.__traceback__`` while normalizing the
    traceback across the ``yield`` boundary. A plain ``frozen=True``
    dataclass rejects *all* attribute assignment — including dunder
    attributes like ``__traceback__`` — so this used to raise
    ``dataclasses.FrozenInstanceError`` instead of letting the intended
    ``ConfigValidationError`` propagate to the caller.
    """
    import click

    target = tmp_path / "x.yaml"
    target.write_text("x")

    @click.command()
    def _cmd() -> None:
        raise ConfigValidationError(
            file=target, line=1, field_path="<root>", reason="bad",
        )

    with pytest.raises(ConfigValidationError):
        _cmd.main(args=[], standalone_mode=False)

    # Declared fields must still be genuinely immutable after the fix.
    err = ConfigValidationError(file=target, line=1, field_path="<root>", reason="bad")
    with pytest.raises(Exception):
        err.reason = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# format_loc
# ---------------------------------------------------------------------------


def test_format_loc_mixed_int_and_str_steps():
    """Test 7: Pydantic-style loc with int indices renders as a.b[0].c.d[3]-shape."""
    assert format_loc(
        ("teams", 0, "tickets", 3, "fields", "story_points")
    ) == "teams[0].tickets[3].fields.story_points"


def test_format_loc_single_string():
    """Test 8: Single string loc renders without prefix."""
    assert format_loc(("a",)) == "a"


def test_format_loc_empty_tuple():
    """Test 9: Empty loc renders as empty string."""
    assert format_loc(()) == ""


def test_format_loc_starts_with_int():
    """Test 10: Loc starting with int renders as [N].rest."""
    assert format_loc((0, "a")) == "[0].a"


def test_format_loc_consecutive_ints():
    """Test 11: Consecutive ints render as a[0][1]."""
    assert format_loc(("a", 0, 1)) == "a[0][1]"


# ---------------------------------------------------------------------------
# did_you_mean
# ---------------------------------------------------------------------------


def test_did_you_mean_single_match_phrasing():
    """Test 12: Single close match returns single-quoted PEP-657-style phrasing."""
    result = did_you_mean(
        "sprint_n",
        ["pi_label", "pi_num", "sprint_num", "version", "team_name"],
    )
    assert result == "(did you mean 'sprint_num'?)"


def test_did_you_mean_no_match_returns_none():
    """Test 13: No close match → None."""
    result = did_you_mean("xyz", ["pi_label", "pi_num", "sprint_num"])
    assert result is None


def test_did_you_mean_multi_match_phrasing():
    """Test 14: Multiple close matches use comma-list phrasing."""
    result = did_you_mean(
        "storypoints",
        ["story_points", "story_point", "story", "sprint_num"],
    )
    assert result is not None
    assert result.startswith("(closest matches:")
    # At least two of the candidates should appear when multi-match fires
    assert "story_points" in result
    assert "story_point" in result


# ---------------------------------------------------------------------------
# ConfigConflictWarning (Phase 02-01)
# ---------------------------------------------------------------------------


class TestConfigConflictWarning:
    def test_w1_intra_file_team_defaults_format(self, tmp_path, monkeypatch):
        """W1: full string format for the team-defaults-vs-template case."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "t.yaml"
        target.write_text("x")
        w = ConfigConflictWarning(
            later_file=target,
            later_line=12,
            earlier_file=target,
            earlier_line=3,
            field_path="priority",
            earlier_layer="team defaults",
        )
        assert str(w) == (
            "t.yaml:12: priority — locked by team defaults "
            "(t.yaml:3); later value ignored."
        )

    def test_w2_omits_line_when_none(self, tmp_path, monkeypatch):
        """W2: when later_line / earlier_line is None, the :line segment is omitted."""
        monkeypatch.chdir(tmp_path)
        target = tmp_path / "t.yaml"
        target.write_text("x")
        w = ConfigConflictWarning(
            later_file=target,
            later_line=None,
            earlier_file=target,
            earlier_line=None,
            field_path="priority",
            earlier_layer="team defaults",
        )
        rendered = str(w)
        # No `:NN:` line segment after either filename
        assert "t.yaml: priority" in rendered
        assert "(t.yaml);" in rendered

    def test_w3_relative_to_cwd_when_possible(self, tmp_path, monkeypatch):
        """W3: paths render relative to CWD when possible."""
        monkeypatch.chdir(tmp_path)
        nested = tmp_path / "configs" / "teams" / "calcs.yaml"
        nested.parent.mkdir(parents=True)
        nested.write_text("x")
        w = ConfigConflictWarning(
            later_file=nested,
            later_line=10,
            earlier_file=nested,
            earlier_line=2,
            field_path="priority",
            earlier_layer="team defaults",
        )
        rendered = str(w)
        assert rendered.startswith("configs/teams/calcs.yaml:10:")

    def test_w4_frozen(self, tmp_path):
        """W4: ConfigConflictWarning is frozen — mutating fields raises."""
        target = tmp_path / "t.yaml"
        target.write_text("x")
        w = ConfigConflictWarning(
            later_file=target,
            later_line=1,
            earlier_file=target,
            earlier_line=2,
            field_path="x",
            earlier_layer="team defaults",
        )
        with pytest.raises(Exception):
            w.field_path = "y"  # type: ignore[misc]

    def test_w5_not_an_exception_subclass(self, tmp_path):
        """W5: ConfigConflictWarning is NOT an Exception subclass."""
        target = tmp_path / "t.yaml"
        target.write_text("x")
        w = ConfigConflictWarning(
            later_file=target,
            later_line=1,
            earlier_file=target,
            earlier_line=2,
            field_path="x",
            earlier_layer="team defaults",
        )
        assert not isinstance(w, Exception)


# ---------------------------------------------------------------------------
# did_you_mean — result shape
# ---------------------------------------------------------------------------


def test_did_you_mean_result_shape_brackets():
    """Test 15: Result always starts with '(' and ends with ')'."""
    single = did_you_mean(
        "sprint_n",
        ["pi_label", "pi_num", "sprint_num"],
    )
    assert single is not None
    assert single.startswith("(") and single.endswith(")")
    # Single-match phrasing ends with `?)`
    assert single.endswith("?)")
    multi = did_you_mean(
        "storypoints",
        ["story_points", "story_point", "story", "sprint_num"],
    )
    assert multi is not None
    assert multi.startswith("(") and multi.endswith(")")
