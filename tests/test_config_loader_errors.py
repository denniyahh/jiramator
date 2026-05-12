"""Tests for the integration of ConfigValidationError into config loaders (FOUND-01).

Plan: 01-01 Task 3.

Verifies that ``load_org_config`` and ``load_team_config`` raise the new
``ConfigValidationError`` (with line numbers, field path, em-dash format,
and did-you-mean suggestions) for the four representative error fixtures
in ``tests/fixtures/yaml_errors/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jiramator.config import load_org_config, load_team_config
from jiramator.error_format import ConfigValidationError

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "yaml_errors"


# ---------------------------------------------------------------------------
# load_team_config error paths
# ---------------------------------------------------------------------------


class TestTeamLoaderErrors:
    """ConfigValidationError emission from load_team_config."""

    def test_missing_required_field_raises_with_line(self):
        """Test 1: Missing required `project_key` → ConfigValidationError with line."""
        fixture = FIXTURE_DIR / "missing_required.yaml"
        with pytest.raises(ConfigValidationError) as exc_info:
            load_team_config(fixture)
        err = exc_info.value
        assert err.file == fixture
        # Line should point at root mapping (line 1) or the missing field's
        # nearest valid line. Either way, line is non-None.
        assert err.line is not None and err.line >= 1
        assert "project_key" in err.field_path
        assert "required" in err.reason.lower() or "missing" in err.reason.lower()

    def test_nested_template_typo_raises_with_field_path_and_suggestion(self):
        """Test 2: `{sprint_n}` typo → field path identifies the offending entry,
        suggestion proposes `sprint_num`."""
        fixture = FIXTURE_DIR / "nested_typo.yaml"
        with pytest.raises(ConfigValidationError) as exc_info:
            load_team_config(fixture)
        err = exc_info.value
        # Field path should reach into per_release_tickets[N].summary
        assert "per_release_tickets" in err.field_path
        assert "summary" in err.field_path
        # Suggestion should propose `sprint_num`
        assert err.suggestion is not None
        assert "sprint_num" in err.suggestion

    def test_yaml_parse_error_raises_with_line(self):
        """Test 3: Invalid YAML → ConfigValidationError pointing to parse line."""
        fixture = FIXTURE_DIR / "yaml_parse_error.yaml"
        with pytest.raises(ConfigValidationError) as exc_info:
            load_team_config(fixture)
        err = exc_info.value
        assert err.file == fixture
        assert err.field_path == "<yaml>"
        # YAML parser reports a line; we should propagate it.
        assert err.line is not None and err.line >= 1

    def test_nonexistent_file_raises_config_validation_error(self):
        """Test 4: Missing file → ConfigValidationError (not FileNotFoundError)."""
        with pytest.raises(ConfigValidationError) as exc_info:
            load_team_config("/nonexistent/team.yaml")
        err = exc_info.value
        assert err.line is None
        assert err.field_path == "<file>"
        assert "not found" in err.reason.lower()

    def test_non_mapping_yaml_raises_config_validation_error(self, tmp_path):
        """Test 5: List-shaped YAML → ConfigValidationError at <root>."""
        p = tmp_path / "bad.yaml"
        p.write_text("- a\n- b\n")
        with pytest.raises(ConfigValidationError) as exc_info:
            load_team_config(p)
        err = exc_info.value
        assert err.field_path == "<root>"
        assert "mapping" in err.reason.lower()


# ---------------------------------------------------------------------------
# load_org_config error paths
# ---------------------------------------------------------------------------


class TestOrgLoaderErrors:
    """ConfigValidationError emission from load_org_config."""

    def test_nonexistent_file_raises_config_validation_error(self):
        """Test 6: Missing org file → ConfigValidationError."""
        with pytest.raises(ConfigValidationError) as exc_info:
            load_org_config("/nonexistent/org.yaml")
        err = exc_info.value
        assert err.line is None
        assert err.field_path == "<file>"
        assert "not found" in err.reason.lower()

    def test_non_mapping_yaml_raises_config_validation_error(self, tmp_path):
        """Test 7: List-shaped org YAML → ConfigValidationError at <root>."""
        p = tmp_path / "bad.yaml"
        p.write_text("- just\n- a\n- list\n")
        with pytest.raises(ConfigValidationError) as exc_info:
            load_org_config(p)
        err = exc_info.value
        assert err.field_path == "<root>"
        assert "mapping" in err.reason.lower()


# ---------------------------------------------------------------------------
# Rendered string format spot-check (one full end-to-end render)
# ---------------------------------------------------------------------------


class TestRenderedFormat:
    """End-to-end format checks on the str() of raised errors."""

    def test_nested_typo_str_includes_filename_line_and_suggestion(self, monkeypatch):
        """Test 8: str(err) for the nested-typo fixture is a single-line
        actionable message with file:line, field path, em-dash, reason, suggestion."""
        # Run with CWD = repo root so the fixture path renders relative.
        repo_root = Path(__file__).resolve().parent.parent
        monkeypatch.chdir(repo_root)
        fixture = FIXTURE_DIR / "nested_typo.yaml"
        with pytest.raises(ConfigValidationError) as exc_info:
            load_team_config(fixture)
        rendered = str(exc_info.value)
        # Single line
        assert "\n" not in rendered
        # Em-dash separator
        assert " — " in rendered
        # Field path appears before em-dash
        assert "per_release_tickets" in rendered.split(" — ")[0]
        # Suggestion appears after em-dash
        assert "sprint_num" in rendered.split(" — ")[1]
        # Relative path (not absolute)
        assert "/yaml_errors/" in rendered or "yaml_errors\\" in rendered
        assert not rendered.startswith("/")
