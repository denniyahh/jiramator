"""Tests for the PI planning orchestration engine (planner.py).

Strategy: mock Rich prompts and JiraClient to test the full flow without
any real Jira API calls. We use the real OrgConfig/TeamConfig/builder —
only the interactive prompts and HTTP layer are faked.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from rich.console import Console

from jiramator.config import (
    EpicTemplate,
    OrgConfig,
    SprintConfig,
    TeamConfig,
    TicketTemplate,
)
from jiramator.jira_client import JiraApiError, JiraClient
from jiramator.planner import (
    _check_and_create_fix_versions,
    _create_epics,
    _create_tickets_bulk,
    _display_preview,
    _display_results,
    _extract_field,
    _extract_summary,
    _prompt_pi_number,
    _prompt_versions,
    run_plan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def org_config() -> OrgConfig:
    """Minimal org config for planner tests."""
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        jira_email_env="JIRA_EMAIL",
        jira_token_env="JIRA_TOKEN",
        custom_fields={
            "story_points": "customfield_10026",
            "epic_link": "customfield_10014",
        },
        sprints=SprintConfig(
            count=6,
            standard_length_weeks=2,
            long_length_weeks=3,
            long_sprints=[6],
        ),
    )


@pytest.fixture()
def team_config() -> TeamConfig:
    """Minimal team config with one epic, one per-release, one per-sprint template."""
    return TeamConfig(
        project_key="TST",
        team_name="TestTeam",
        recurring_epics=[
            EpicTemplate(key="misc", summary="{team_name} {pi_label} - Misc"),
        ],
        per_release_tickets=[
            TicketTemplate(
                summary="Testing - {version} Pre-regression",
                fields={
                    "issuetype": "Task",
                    "priority": "Medium",
                    "fixVersions": ["{version}"],
                    "customfield_10014": "$epic:misc",
                },
            ),
        ],
        per_sprint_tickets=[
            TicketTemplate(
                summary="Prod Support (Sprint {sprint_num})",
                fields={
                    "issuetype": "Task",
                    "priority": "Medium",
                    "customfield_10014": "$epic:misc",
                },
                extra_on_long_sprint=1,
                long_sprint_suffix=["a", "b"],
            ),
        ],
    )


@pytest.fixture()
def console() -> Console:
    """A non-interactive console that doesn't emit escape codes."""
    return Console(force_terminal=False, no_color=True, file=None)


@pytest.fixture()
def mock_client() -> MagicMock:
    """A fully mocked JiraClient."""
    client = MagicMock(spec=JiraClient)
    return client


# ---------------------------------------------------------------------------
# _extract_summary
# ---------------------------------------------------------------------------


class TestExtractSummary:
    def test_basic(self):
        payload = {"fields": {"summary": "My Issue"}}
        assert _extract_summary(payload) == "My Issue"

    def test_missing_summary(self):
        payload = {"fields": {}}
        assert _extract_summary(payload) == "<no summary>"

    def test_missing_fields(self):
        assert _extract_summary({}) == "<no summary>"


# ---------------------------------------------------------------------------
# _extract_field
# ---------------------------------------------------------------------------


class TestExtractField:
    def test_string_value(self):
        payload = {"fields": {"summary": "test"}}
        assert _extract_field(payload, "summary") == "test"

    def test_name_object(self):
        """Unwrap Jira {\"name\": \"Task\"} structures."""
        payload = {"fields": {"issuetype": {"name": "Task"}}}
        assert _extract_field(payload, "issuetype") == "Task"

    def test_list_of_name_objects(self):
        """Unwrap [{\"name\": \"26.1.1\"}, {\"name\": \"26.1.2\"}]."""
        payload = {"fields": {"fixVersions": [{"name": "26.1.1"}, {"name": "26.1.2"}]}}
        assert _extract_field(payload, "fixVersions") == "26.1.1, 26.1.2"

    def test_list_of_strings(self):
        payload = {"fields": {"labels": ["PI28", "Testing"]}}
        assert _extract_field(payload, "labels") == "PI28, Testing"

    def test_default(self):
        payload = {"fields": {}}
        assert _extract_field(payload, "missing", "N/A") == "N/A"

    def test_numeric_value(self):
        payload = {"fields": {"customfield_10026": 3.0}}
        assert _extract_field(payload, "customfield_10026") == "3.0"

    def test_empty_string_uses_default(self):
        payload = {"fields": {"summary": ""}}
        assert _extract_field(payload, "summary", "fallback") == "fallback"


# ---------------------------------------------------------------------------
# _display_preview
# ---------------------------------------------------------------------------


class TestDisplayPreview:
    def test_counts_all_categories(self, org_config, console):
        """Total should be sum of epics + per_release + per_sprint."""
        payloads = {
            "epics": [
                {"ref_key": "misc", "payload": {"fields": {"summary": "Epic 1"}}},
            ],
            "per_release": [
                {"fields": {"summary": "PR 1", "issuetype": {"name": "Task"}, "fixVersions": [{"name": "26.1.1"}]}},
                {"fields": {"summary": "PR 2", "issuetype": {"name": "Task"}, "fixVersions": [{"name": "26.1.2"}]}},
            ],
            "per_sprint": [
                {"fields": {"summary": "PS 1", "issuetype": {"name": "Task"}}},
            ],
        }
        total = _display_preview(payloads, ["26.1.1", "26.1.2"], org_config, console)
        assert total == 4

    def test_empty_categories(self, org_config, console):
        """Empty payloads → zero total."""
        payloads = {"epics": [], "per_release": [], "per_sprint": []}
        total = _display_preview(payloads, [], org_config, console)
        assert total == 0

    def test_only_epics(self, org_config, console):
        payloads = {
            "epics": [
                {"ref_key": "a", "payload": {"fields": {"summary": "E1"}}},
                {"ref_key": "b", "payload": {"fields": {"summary": "E2"}}},
            ],
            "per_release": [],
            "per_sprint": [],
        }
        total = _display_preview(payloads, [], org_config, console)
        assert total == 2


# ---------------------------------------------------------------------------
# _check_and_create_fix_versions
# ---------------------------------------------------------------------------


class TestCheckAndCreateFixVersions:
    def test_all_exist(self, mock_client, console):
        """When all versions exist, nothing is created."""
        mock_client.get_fix_versions.return_value = [
            {"name": "26.1.1", "id": "100"},
            {"name": "26.1.2", "id": "101"},
        ]
        _check_and_create_fix_versions(
            mock_client, "TST", ["26.1.1", "26.1.2"], console
        )
        mock_client.create_fix_version.assert_not_called()

    @patch("jiramator.planner.Confirm.ask", return_value=True)
    def test_missing_versions_created(self, mock_confirm, mock_client, console):
        """Missing versions are created after user confirmation."""
        mock_client.get_fix_versions.return_value = [{"name": "26.1.1", "id": "100"}]
        mock_client.create_fix_version.return_value = {"name": "26.1.2", "id": "102"}

        _check_and_create_fix_versions(
            mock_client, "TST", ["26.1.1", "26.1.2"], console
        )
        mock_client.create_fix_version.assert_called_once_with("TST", "26.1.2")

    @patch("jiramator.planner.Confirm.ask", return_value=False)
    def test_user_declines_creation(self, mock_confirm, mock_client, console):
        """User declining version creation causes SystemExit."""
        mock_client.get_fix_versions.return_value = []

        with pytest.raises(SystemExit):
            _check_and_create_fix_versions(
                mock_client, "TST", ["26.1.1"], console
            )
        mock_client.create_fix_version.assert_not_called()


# ---------------------------------------------------------------------------
# _create_epics
# ---------------------------------------------------------------------------


class TestCreateEpics:
    def test_creates_and_returns_keys(self, mock_client, console):
        mock_client.create_issue.side_effect = ["TST-100", "TST-101"]
        epic_payloads = [
            {"ref_key": "bau", "payload": {"fields": {"summary": "BAU Epic"}}},
            {"ref_key": "misc", "payload": {"fields": {"summary": "Misc Epic"}}},
        ]
        result = _create_epics(mock_client, epic_payloads, console)
        assert result == {"bau": "TST-100", "misc": "TST-101"}
        assert mock_client.create_issue.call_count == 2

    def test_empty_list(self, mock_client, console):
        result = _create_epics(mock_client, [], console)
        assert result == {}
        mock_client.create_issue.assert_not_called()


# ---------------------------------------------------------------------------
# _create_tickets_bulk
# ---------------------------------------------------------------------------


class TestCreateTicketsBulk:
    def test_creates_and_returns_keys(self, mock_client, console):
        mock_client.create_issues_bulk.return_value = ["TST-200", "TST-201"]
        payloads = [
            {"fields": {"summary": "T1"}},
            {"fields": {"summary": "T2"}},
        ]
        result = _create_tickets_bulk(mock_client, payloads, "per-release", console)
        assert result == ["TST-200", "TST-201"]
        mock_client.create_issues_bulk.assert_called_once_with(payloads)

    def test_empty_list_skips(self, mock_client, console):
        result = _create_tickets_bulk(mock_client, [], "per-release", console)
        assert result == []
        mock_client.create_issues_bulk.assert_not_called()


# ---------------------------------------------------------------------------
# _display_results
# ---------------------------------------------------------------------------


class TestDisplayResults:
    def test_displays_all_categories(self, console):
        """Smoke test — just ensure it doesn't crash."""
        _display_results(
            {"misc": "TST-100", "bau": "TST-101"},
            ["TST-200", "TST-201"],
            ["TST-300"],
            console,
        )

    def test_empty_results(self, console):
        _display_results({}, [], [], console)


# ---------------------------------------------------------------------------
# run_plan — dry-run mode
# ---------------------------------------------------------------------------


class TestRunPlanDryRun:
    """Dry-run should prompt, preview, and exit without creating anything."""

    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    def test_dry_run_no_client(
        self,
        mock_int_prompt,
        mock_prompt,
        org_config,
        team_config,
        console,
    ):
        """In dry-run mode, JiraClient is never constructed."""
        # Prompt sequence: PI number, then release count, then version string
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1

        with patch("jiramator.planner.JiraClient") as mock_jira_cls:
            run_plan(org_config, team_config, dry_run=True, console=console)
            mock_jira_cls.assert_not_called()

    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    def test_dry_run_builds_payloads(
        self,
        mock_int_prompt,
        mock_prompt,
        org_config,
        team_config,
        console,
    ):
        """Dry-run calls build_all with empty epic_keys."""
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1

        with patch("jiramator.planner.build_all", wraps=None) as mock_build:
            # Set up a realistic return value
            mock_build.return_value = {
                "epics": [{"ref_key": "misc", "payload": {"fields": {"summary": "E"}}}],
                "per_release": [{"fields": {"summary": "T1"}}],
                "per_sprint": [{"fields": {"summary": "T2"}}],
            }
            run_plan(org_config, team_config, dry_run=True, console=console)
            mock_build.assert_called_once()
            # Verify epic_keys={} in dry-run
            _, kwargs = mock_build.call_args
            # build_all is called positionally, check the last positional arg
            args = mock_build.call_args[0]
            # args: org_config, team_config; kwargs: pi_label, pi_num, versions, epic_keys
            assert kwargs.get("epic_keys") == {} or (len(args) > 5 and args[5] == {})


# ---------------------------------------------------------------------------
# run_plan — full creation flow
# ---------------------------------------------------------------------------


class TestRunPlanFullFlow:
    """Full flow: prompts → preview → fix versions → create → results."""

    @patch("jiramator.planner.Confirm.ask")
    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    @patch("jiramator.planner.JiraClient")
    def test_full_creation(
        self,
        mock_jira_cls,
        mock_int_prompt,
        mock_prompt,
        mock_confirm,
        org_config,
        team_config,
        console,
    ):
        """End-to-end: creates epics, rebuilds payloads, bulk creates."""
        # --- Prompt stubs ---
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1
        # Confirm calls: fix version creation (True), duplicate warning (True)
        mock_confirm.side_effect = [True, True]

        # --- JiraClient stubs ---
        mock_client = MagicMock()
        mock_jira_cls.return_value = mock_client

        # get_fix_versions → empty list (all missing)
        mock_client.get_fix_versions.return_value = []
        # create_fix_version → success
        mock_client.create_fix_version.return_value = {"name": "26.1.1", "id": "100"}
        # create_issue for epics → return keys
        mock_client.create_issue.return_value = "TST-500"
        # create_issues_bulk → return keys
        mock_client.create_issues_bulk.return_value = ["TST-501", "TST-502"]

        run_plan(org_config, team_config, dry_run=False, console=console)

        # Verify epic was created
        mock_client.create_issue.assert_called_once()
        # Verify fix version was created
        mock_client.create_fix_version.assert_called_once_with("TST", "26.1.1")
        # Verify bulk creation was called (at least once)
        assert mock_client.create_issues_bulk.call_count >= 1

    @patch("jiramator.planner.Confirm.ask")
    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    @patch("jiramator.planner.JiraClient")
    def test_user_aborts_at_confirmation(
        self,
        mock_jira_cls,
        mock_int_prompt,
        mock_prompt,
        mock_confirm,
        org_config,
        team_config,
        console,
    ):
        """User says no at the duplicate warning → SystemExit, nothing created."""
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1
        # First Confirm: fix versions (all exist, so this won't fire)
        # Only Confirm: duplicate warning → False
        mock_confirm.return_value = False

        mock_client = MagicMock()
        mock_jira_cls.return_value = mock_client
        mock_client.get_fix_versions.return_value = [{"name": "26.1.1", "id": "100"}]

        with pytest.raises(SystemExit):
            run_plan(org_config, team_config, dry_run=False, console=console)

        mock_client.create_issue.assert_not_called()
        mock_client.create_issues_bulk.assert_not_called()

    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    @patch("jiramator.planner.JiraClient")
    def test_credential_error(
        self,
        mock_jira_cls,
        mock_int_prompt,
        mock_prompt,
        org_config,
        team_config,
        console,
    ):
        """ValueError from JiraClient constructor → SystemExit."""
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1
        mock_jira_cls.side_effect = ValueError("JIRA_TOKEN env var not set")

        with pytest.raises(SystemExit):
            run_plan(org_config, team_config, dry_run=False, console=console)

    @patch("jiramator.planner.Confirm.ask")
    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    @patch("jiramator.planner.JiraClient")
    def test_epic_creation_failure(
        self,
        mock_jira_cls,
        mock_int_prompt,
        mock_prompt,
        mock_confirm,
        org_config,
        team_config,
        console,
    ):
        """JiraApiError during epic creation → SystemExit."""
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1
        mock_confirm.side_effect = [True, True]  # fix versions, duplicate warning

        mock_client = MagicMock()
        mock_jira_cls.return_value = mock_client
        mock_client.get_fix_versions.return_value = []
        mock_client.create_fix_version.return_value = {"name": "26.1.1", "id": "100"}
        mock_client.create_issue.side_effect = JiraApiError("Forbidden", status_code=403)

        with pytest.raises(SystemExit):
            run_plan(org_config, team_config, dry_run=False, console=console)

    @patch("jiramator.planner.Confirm.ask")
    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    @patch("jiramator.planner.JiraClient")
    def test_bulk_creation_failure(
        self,
        mock_jira_cls,
        mock_int_prompt,
        mock_prompt,
        mock_confirm,
        org_config,
        team_config,
        console,
    ):
        """JiraApiError during bulk creation → SystemExit."""
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1
        mock_confirm.side_effect = [True, True]

        mock_client = MagicMock()
        mock_jira_cls.return_value = mock_client
        mock_client.get_fix_versions.return_value = []
        mock_client.create_fix_version.return_value = {"name": "26.1.1", "id": "100"}
        mock_client.create_issue.return_value = "TST-500"
        mock_client.create_issues_bulk.side_effect = JiraApiError(
            "Server Error", status_code=500
        )

        with pytest.raises(SystemExit):
            run_plan(org_config, team_config, dry_run=False, console=console)


# ---------------------------------------------------------------------------
# run_plan — sprint handling
# ---------------------------------------------------------------------------


class TestRunPlanSprintHandling:
    """Tests for sprint-related branching in run_plan."""

    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    def test_no_board_id_skips_sprint_prompt(
        self,
        mock_int_prompt,
        mock_prompt,
        org_config,
        console,
    ):
        """When board_id is None, the sprint prompt is never shown."""
        team_config = TeamConfig(
            project_key="TST",
            team_name="TestTeam",
            board_id=None,
            recurring_epics=[],
            per_release_tickets=[],
            per_sprint_tickets=[],
        )
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1

        # Confirm should NOT be called (no sprints prompt, and dry-run skips the rest)
        with patch("jiramator.planner.Confirm.ask") as mock_confirm:
            run_plan(org_config, team_config, dry_run=True, console=console)
            mock_confirm.assert_not_called()

    @patch("jiramator.planner.Confirm.ask", return_value=True)
    @patch("jiramator.planner.Prompt.ask")
    @patch("jiramator.planner.IntPrompt.ask")
    def test_with_board_id_asks_sprint_prompt(
        self,
        mock_int_prompt,
        mock_prompt,
        mock_confirm,
        org_config,
        console,
    ):
        """When board_id is set, the sprint prompt IS shown."""
        team_config = TeamConfig(
            project_key="TST",
            team_name="TestTeam",
            board_id=42,
            recurring_epics=[],
            per_release_tickets=[],
            per_sprint_tickets=[],
        )
        mock_prompt.side_effect = ["28", "26.1.1"]
        mock_int_prompt.return_value = 1

        run_plan(org_config, team_config, dry_run=True, console=console)
        # Confirm.ask should have been called for the sprint question
        mock_confirm.assert_called_once()


# ---------------------------------------------------------------------------
# Prompt helpers (unit tests)
# ---------------------------------------------------------------------------


class TestPromptHelpers:
    @patch("jiramator.planner.Prompt.ask", return_value="28")
    def test_prompt_pi_number(self, mock_prompt, console):
        pi_num, pi_label = _prompt_pi_number(console)
        assert pi_num == "28"
        assert pi_label == "PI28"

    @patch("jiramator.planner.Prompt.ask", return_value="  42  ")
    def test_prompt_pi_number_strips_whitespace(self, mock_prompt, console):
        pi_num, pi_label = _prompt_pi_number(console)
        assert pi_num == "42"
        assert pi_label == "PI42"

    @patch("jiramator.planner.Prompt.ask", return_value="")
    def test_prompt_pi_number_empty_exits(self, mock_prompt, console):
        with pytest.raises(SystemExit):
            _prompt_pi_number(console)

    @patch("jiramator.planner.Prompt.ask", side_effect=["26.1.1", "26.1.2"])
    @patch("jiramator.planner.IntPrompt.ask", return_value=2)
    def test_prompt_versions(self, mock_int, mock_prompt, console):
        versions = _prompt_versions(console)
        assert versions == ["26.1.1", "26.1.2"]

    @patch("jiramator.planner.IntPrompt.ask", return_value=0)
    def test_prompt_versions_zero_exits(self, mock_int, console):
        with pytest.raises(SystemExit):
            _prompt_versions(console)

    @patch("jiramator.planner.Prompt.ask", return_value="  ")
    @patch("jiramator.planner.IntPrompt.ask", return_value=1)
    def test_prompt_versions_empty_string_exits(self, mock_int, mock_prompt, console):
        with pytest.raises(SystemExit):
            _prompt_versions(console)
