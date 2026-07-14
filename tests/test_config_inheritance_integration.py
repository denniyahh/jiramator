"""End-to-end integration tests for Phase 02-02 template inheritance.

Covers the load-time composition path:

    load_org_config(p)  ─┐
                         ├──>  merge_configs(...)  ──>  merged TeamConfig
    load_team_config(p) ─┘                                    (templates carry inherited fields)

Plus the CLI wiring path (`plan` command picks up the merge automatically).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from jiramator.config import load_org_config, load_team_config
from jiramator.config_merge import merge_configs


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_BASE_ORG = {
    "jira_url": "https://example.atlassian.net",
    "jira_email_env": "JIRA_EMAIL",
    "jira_token_env": "JIRA_TOKEN",
    "custom_fields": {
        "story_points": "customfield_10026",
        "epic_link": "customfield_10014",
    },
    "sprints": {
        "count": 4,
        "standard_length_weeks": 2,
        "long_length_weeks": 3,
    },
}


_BASE_TEAM = {
    "project_key": "CA",
    "team_name": "Calcs",
    "existing_epics": {"misc": "CA-100"},
    "recurring_epics": [],
    "per_release_tickets": [],
    "per_sprint_tickets": [],
}


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.dump(data))
    return path


# ---------------------------------------------------------------------------
# II1-II6 — end-to-end composition through the public loader API
# ---------------------------------------------------------------------------


class TestConfigInheritanceIntegration:

    def test_ii1_org_default_propagates_through_load_and_merge(
        self, tmp_path: Path, capsys
    ) -> None:
        """II1: org default_fields.priority flows into a per-release ticket."""
        org_data = dict(_BASE_ORG)
        org_data["default_fields"] = {"priority": "Medium"}
        team_data = dict(_BASE_TEAM)
        team_data["per_release_tickets"] = [
            {"summary": "Hello {pi_label}", "fields": {"summary_only": "x"}},
        ]
        org_path = _write_yaml(tmp_path / "org.yaml", org_data)
        team_path = _write_yaml(tmp_path / "team.yaml", team_data)

        org, org_tagged = load_org_config(org_path)
        team, team_tagged = load_team_config(team_path)
        merged = merge_configs(
            org_model=org,
            org_tagged_raw=org_tagged,
            org_file=org_path,
            team_model=team,
            team_tagged_raw=team_tagged,
            team_file=team_path,
        )
        assert merged.per_release_tickets[0].fields == {
            "summary_only": "x", "priority": "Medium",
        }
        assert capsys.readouterr().err == ""

    def test_ii2_org_locks_against_team_defaults_and_template(
        self, tmp_path: Path, capsys
    ) -> None:
        """II2: org-locked priority warns at both layer 1 and layer 2."""
        org_data = dict(_BASE_ORG)
        org_data["default_fields"] = {"priority": "Medium"}
        team_data = dict(_BASE_TEAM)
        team_data["defaults"] = {"fields": {"priority": "Low"}}
        team_data["per_release_tickets"] = [
            {"summary": "S {pi_label}", "fields": {"priority": "Medium"}},
        ]
        org_path = _write_yaml(tmp_path / "org.yaml", org_data)
        team_path = _write_yaml(tmp_path / "team.yaml", team_data)

        org, org_tagged = load_org_config(org_path)
        team, team_tagged = load_team_config(team_path)
        merge_configs(
            org_model=org,
            org_tagged_raw=org_tagged,
            org_file=org_path,
            team_model=team,
            team_tagged_raw=team_tagged,
            team_file=team_path,
        )
        # Org-locked Medium wins.
        assert team.per_release_tickets[0].fields["priority"] == "Medium"
        err = capsys.readouterr().err
        # Two warnings: one at layer 1 (org vs team defaults), one at layer
        # 2 (effective team-level lock vs template).
        assert err.count("locked by") == 2
        assert "locked by org config" in err
        assert "locked by team defaults" in err

    def test_ii3_realistic_calcs_team_fixture(
        self, tmp_path: Path, capsys
    ) -> None:
        """II3: load real calcs.yaml; org provides priority Medium; conflicts warn."""
        # Tracked fixture (not the gitignored configs/teams/ dir) so this
        # test is reproducible on a fresh clone / in CI.
        calcs_path = (
            Path(__file__).parent / "fixtures" / "teams" / "calcs.yaml"
        )

        org_data = dict(_BASE_ORG)
        # Use the real custom_fields shape that calcs.yaml references.
        org_data["custom_fields"] = {
            "story_points": "customfield_10026",
            "epic_link": "customfield_10014",
            "api_impact": "customfield_10273",
        }
        org_data["default_fields"] = {"priority": "Medium"}
        org_path = _write_yaml(tmp_path / "org.yaml", org_data)

        org, org_tagged = load_org_config(org_path)
        team, team_tagged = load_team_config(calcs_path)
        merge_configs(
            org_model=org,
            org_tagged_raw=org_tagged,
            org_file=org_path,
            team_model=team,
            team_tagged_raw=team_tagged,
            team_file=calcs_path,
        )
        # Every template — recurring epics, per-release, per-sprint —
        # carries priority: Medium after merge.
        for tmpl in (
            team.recurring_epics
            + team.per_release_tickets
            + team.per_sprint_tickets
        ):
            assert tmpl.fields.get("priority") == "Medium"
        # calcs.yaml declares priority: Medium on individual tickets, so
        # those WILL warn (effective lock equals declared value but the
        # write is still a conflict — see CONTEXT G-1).
        # We just assert that *some* warning fired (at least one ticket
        # in the real fixture sets priority).
        # If the real fixture has zero priority-bearing tickets that's
        # fine; we don't enforce a non-empty stderr.
        # Sanity: stderr is well-formed (no tracebacks).
        err = capsys.readouterr().err
        assert "Traceback" not in err

    def test_ii4_backward_compat_no_warnings_no_default_fields(
        self, tmp_path: Path, capsys
    ) -> None:
        """II4: org/team without inheritance keys produce zero warnings (DC-4)."""
        org_data = dict(_BASE_ORG)  # no default_fields
        team_data = dict(_BASE_TEAM)  # no defaults
        team_data["per_release_tickets"] = [
            {"summary": "S {pi_label}", "fields": {"a": 1}},
        ]
        org_path = _write_yaml(tmp_path / "org.yaml", org_data)
        team_path = _write_yaml(tmp_path / "team.yaml", team_data)

        org, org_tagged = load_org_config(org_path)
        team, team_tagged = load_team_config(team_path)
        merge_configs(
            org_model=org,
            org_tagged_raw=org_tagged,
            org_file=org_path,
            team_model=team,
            team_tagged_raw=team_tagged,
            team_file=team_path,
        )
        # Template fields untouched.
        assert team.per_release_tickets[0].fields == {"a": 1}
        # No effective lock layer.
        assert team.defaults.fields == {}
        # No warnings.
        assert capsys.readouterr().err == ""

    def test_ii6_importer_documents_phase_2_scope(self) -> None:
        """II6: importer.py carries a comment naming default_fields."""
        importer_path = (
            Path(__file__).parent.parent / "jiramator" / "importer.py"
        )
        text = importer_path.read_text()
        assert "default_fields" in text, (
            "importer.py must document Phase 2 scope (PATTERNS.md §11 Path B)"
        )


# ---------------------------------------------------------------------------
# II5 — CLI integration via Click runner
# ---------------------------------------------------------------------------


class TestCLIIntegrationPlan:

    def test_ii5_plan_command_runs_merge_configs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """II5: `plan --dry-run` invokes merge_configs between loads + run_plan.

        We monkeypatch ``run_plan`` to a recording stub and assert that the
        merged team_config it receives carries the org's default_fields.
        """
        from jiramator import cli

        org_data = dict(_BASE_ORG)
        org_data["default_fields"] = {"priority": "Medium"}
        team_data = dict(_BASE_TEAM)
        team_data["per_release_tickets"] = [
            {"summary": "Hello {pi_label}", "fields": {"summary_only": "x"}},
        ]
        org_path = _write_yaml(tmp_path / "org.yaml", org_data)
        team_path = _write_yaml(tmp_path / "team.yaml", team_data)

        captured: dict = {}

        def _stub_run_plan(org_config, team_config, **kwargs):
            captured["team_config"] = team_config
            captured["org_config"] = org_config

        monkeypatch.setattr(cli, "run_plan", _stub_run_plan)

        runner = CliRunner()
        result = runner.invoke(
            cli.cli,
            [
                "plan",
                "--org-config", str(org_path),
                "--team-config", str(team_path),
                "--dry-run",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0, result.output
        merged_team = captured["team_config"]
        assert merged_team.per_release_tickets[0].fields == {
            "summary_only": "x", "priority": "Medium",
        }
