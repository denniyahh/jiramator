"""Tests for the setup wizard (``jiramator init``).

Pure helpers (field discovery, slugify, YAML rendering, env helpers) are tested
directly. The interactive ``run_init`` orchestration is tested end-to-end with
the Jira client and Rich prompts mocked — matching the planner test conventions
(mock only the HTTP/prompt boundary).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from jiramator.config import SprintConfig, load_org_config, load_team_config
from jiramator.wizard import (
    _ensure_gitignored,
    build_org_config_yaml,
    build_team_skeleton_yaml,
    discover_field_id,
    render_env_exports,
    render_env_file,
    run_init,
    slugify,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def console() -> Console:
    return Console(force_terminal=False, no_color=True, file=None)


@pytest.fixture()
def sprints() -> SprintConfig:
    return SprintConfig(
        count=6, standard_length_weeks=2, long_length_weeks=3, long_sprints=[6]
    )


# ---------------------------------------------------------------------------
# discover_field_id
# ---------------------------------------------------------------------------


class TestDiscoverFieldId:
    def test_matches_by_name_case_insensitive(self):
        fields = [{"id": "customfield_10026", "name": "Story Points"}]
        assert discover_field_id(fields, ["story points"]) == "customfield_10026"

    def test_honors_candidate_priority(self):
        fields = [
            {"id": "cf_parent", "name": "Parent"},
            {"id": "cf_epic", "name": "Epic Link"},
        ]
        # "Epic Link" comes first in candidates, so it wins over "Parent".
        assert discover_field_id(fields, ["Epic Link", "Parent"]) == "cf_epic"

    def test_returns_none_when_no_match(self):
        fields = [{"id": "cf_1", "name": "Something Else"}]
        assert discover_field_id(fields, ["Sprint"]) is None

    def test_first_id_wins_for_duplicate_names(self):
        fields = [
            {"id": "cf_first", "name": "Sprint"},
            {"id": "cf_second", "name": "Sprint"},
        ]
        assert discover_field_id(fields, ["Sprint"]) == "cf_first"


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_spaces_and_punctuation_become_hyphens(self):
        assert slugify("My Team!") == "my-team"

    def test_collapses_and_trims(self):
        assert slugify("  Calcs  ") == "calcs"

    def test_empty_falls_back_to_config(self):
        assert slugify("!!!") == "config"


# ---------------------------------------------------------------------------
# YAML rendering — must round-trip through the real loaders
# ---------------------------------------------------------------------------


class TestBuildOrgConfigYaml:
    def test_generated_org_config_loads(self, tmp_path, sprints):
        text = build_org_config_yaml(
            jira_url="https://acme.atlassian.net",
            jira_email_env="JIRA_EMAIL",
            jira_token_env="JIRA_TOKEN",
            custom_fields={"epic_link": "customfield_10014"},
            sprints=sprints,
        )
        path = tmp_path / "org.yaml"
        path.write_text(text, encoding="utf-8")
        org, _ = load_org_config(path)
        assert str(org.jira_url).startswith("https://acme.atlassian.net")
        assert org.custom_fields["epic_link"] == "customfield_10014"
        assert org.sprints.count == 6

    def test_empty_custom_fields_still_loads(self, tmp_path, sprints):
        text = build_org_config_yaml(
            jira_url="https://acme.atlassian.net",
            jira_email_env="JIRA_EMAIL",
            jira_token_env="JIRA_TOKEN",
            custom_fields={},
            sprints=sprints,
        )
        path = tmp_path / "org.yaml"
        path.write_text(text, encoding="utf-8")
        org, _ = load_org_config(path)
        assert org.custom_fields == {}


class TestBuildTeamSkeletonYaml:
    def test_generated_team_config_loads(self, tmp_path):
        text = build_team_skeleton_yaml(
            project_key="CA", team_name="Calcs", epic_link_field="customfield_10014"
        )
        path = tmp_path / "team.yaml"
        path.write_text(text, encoding="utf-8")
        team, _ = load_team_config(path)
        assert team.project_key == "CA"
        assert team.team_name == "Calcs"
        assert len(team.per_release_tickets) == 1
        assert len(team.per_sprint_tickets) == 1
        # The discovered epic-link field id is wired into the templates.
        assert (
            team.per_release_tickets[0].fields["customfield_10014"] == "$epic:misc"
        )


# ---------------------------------------------------------------------------
# Credential rendering
# ---------------------------------------------------------------------------


class TestCredentialRendering:
    def test_env_exports_include_both_shells(self):
        out = render_env_exports("JIRA_EMAIL", "JIRA_TOKEN", "me@x.com", "tok")
        assert "export JIRA_EMAIL='me@x.com'" in out
        assert "$env:JIRA_TOKEN='tok'" in out

    def test_env_file_contents(self):
        out = render_env_file("JIRA_EMAIL", "JIRA_TOKEN", "me@x.com", "tok")
        assert "JIRA_EMAIL=me@x.com" in out
        assert "JIRA_TOKEN=tok" in out


# ---------------------------------------------------------------------------
# _ensure_gitignored
# ---------------------------------------------------------------------------


class TestEnsureGitignored:
    def test_appends_entry_to_new_file(self, tmp_path):
        gi = tmp_path / ".gitignore"
        _ensure_gitignored(".env", gi)
        assert ".env" in gi.read_text().splitlines()

    def test_does_not_duplicate_existing_entry(self, tmp_path):
        gi = tmp_path / ".gitignore"
        gi.write_text(".env\nother\n", encoding="utf-8")
        _ensure_gitignored(".env", gi)
        assert gi.read_text().count(".env") == 1


# ---------------------------------------------------------------------------
# run_init — end-to-end (mocked Jira + prompts)
# ---------------------------------------------------------------------------


class TestRunInit:
    def _fields(self):
        return [
            {"id": "customfield_10014", "name": "Epic Link"},
            {"id": "customfield_10026", "name": "Story Points"},
            {"id": "customfield_10021", "name": "Sprint"},
        ]

    @patch("jiramator.wizard.Prompt.ask")
    @patch("jiramator.wizard.IntPrompt.ask")
    @patch("jiramator.wizard.JiraClient")
    def test_writes_both_configs_with_export_choice(
        self, mock_jira_cls, mock_int, mock_prompt, console, tmp_path, monkeypatch
    ):
        # Isolate env writes from the real process environment.
        monkeypatch.setattr("jiramator.wizard.os.environ", {})

        mock_client = MagicMock()
        mock_jira_cls.return_value = mock_client
        mock_client.get_fields.return_value = self._fields()
        mock_client.get_project.return_value = {"name": "Calcs"}

        # Prompt.ask order: url, email, token, project_key, team_name,
        # long-sprints, credential-choice
        mock_prompt.side_effect = [
            "https://acme.atlassian.net",
            "me@acme.com",
            "secret-token",
            "ca",
            "Calcs",
            "6",
            "1",  # show export commands
        ]
        # IntPrompt.ask order: count, standard, long_len
        mock_int.side_effect = [6, 2, 3]

        org_dir = tmp_path / "org"
        team_dir = tmp_path / "teams"
        run_init(console, org_dir=org_dir, team_dir=team_dir, cwd=tmp_path)

        org_path = org_dir / "calcs.yaml"
        team_path = team_dir / "calcs.yaml"
        assert org_path.exists() and team_path.exists()

        # Generated files are valid and carry discovered ids.
        org, _ = load_org_config(org_path)
        team, _ = load_team_config(team_path)
        assert org.custom_fields["epic_link"] == "customfield_10014"
        assert team.project_key == "CA"

        # Export choice must NOT write a .env file.
        assert not (tmp_path / ".env").exists()

    @patch("jiramator.wizard.Prompt.ask")
    @patch("jiramator.wizard.IntPrompt.ask")
    @patch("jiramator.wizard.JiraClient")
    def test_env_file_choice_writes_gitignored_env(
        self, mock_jira_cls, mock_int, mock_prompt, console, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("jiramator.wizard.os.environ", {})

        mock_client = MagicMock()
        mock_jira_cls.return_value = mock_client
        mock_client.get_fields.return_value = self._fields()
        mock_client.get_project.return_value = {"name": "Calcs"}

        mock_prompt.side_effect = [
            "https://acme.atlassian.net",
            "me@acme.com",
            "secret-token",
            "ca",
            "Calcs",
            "6",
            "2",  # write .env
        ]
        mock_int.side_effect = [6, 2, 3]

        run_init(
            console,
            org_dir=tmp_path / "org",
            team_dir=tmp_path / "teams",
            cwd=tmp_path,
        )

        env_path = tmp_path / ".env"
        assert env_path.exists()
        assert "JIRA_TOKEN=secret-token" in env_path.read_text()
        # .env must be gitignored.
        assert ".env" in (tmp_path / ".gitignore").read_text().splitlines()

    @patch("jiramator.wizard.Prompt.ask")
    @patch("jiramator.wizard.IntPrompt.ask")
    @patch("jiramator.wizard.JiraClient")
    def test_unmatched_field_prompts_for_manual_id(
        self, mock_jira_cls, mock_int, mock_prompt, console, tmp_path, monkeypatch
    ):
        monkeypatch.setattr("jiramator.wizard.os.environ", {})

        mock_client = MagicMock()
        mock_jira_cls.return_value = mock_client
        # Only Epic Link + Story Points auto-match; Sprint is missing.
        mock_client.get_fields.return_value = [
            {"id": "customfield_10014", "name": "Epic Link"},
            {"id": "customfield_10026", "name": "Story Points"},
        ]
        mock_client.get_project.return_value = {"name": "Calcs"}

        # Note the extra prompt (manual sprint id) inserted after team fields.
        mock_prompt.side_effect = [
            "https://acme.atlassian.net",  # url
            "me@acme.com",                 # email
            "secret-token",                # token
            "customfield_99999",           # manual sprint_field id
            "ca",                          # project key
            "Calcs",                       # team name
            "6",                           # long sprints
            "1",                           # cred choice
        ]
        mock_int.side_effect = [6, 2, 3]

        org_dir = tmp_path / "org"
        run_init(
            console, org_dir=org_dir, team_dir=tmp_path / "teams", cwd=tmp_path
        )

        org, _ = load_org_config(org_dir / "calcs.yaml")
        assert org.custom_fields["sprint_field"] == "customfield_99999"
