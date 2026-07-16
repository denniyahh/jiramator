"""Tests for sprint resolution logic in planner."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from jiramator.planner import _resolve_sprint_ids, _DEFAULT_SPRINT_FIELD


def _make_org_config(sprint_field=None):
    oc = MagicMock()
    custom_fields = {}
    if sprint_field:
        custom_fields["sprint_field"] = sprint_field
    oc.custom_fields = custom_fields
    return oc


def _make_team_config(board_id=362, template="PI-{pi_num}.{sprint_num}-Calc -TI83"):
    tc = MagicMock()
    tc.board_id = board_id
    tc.sprint_name_template = template
    return tc


def _make_client(sprints):
    client = MagicMock()
    client.get_board_sprints.return_value = sprints
    return client


def _make_console():
    return MagicMock()


class TestResolveSprintIds:
    """Tests for _resolve_sprint_ids."""

    def test_injects_sprint_field_and_strips_metadata(self):
        sprints = [
            {"id": 100, "name": "PI-28.2-Calc -TI83", "state": "future"},
            {"id": 101, "name": "PI-28.3-Calc -TI83", "state": "future"},
        ]
        client = _make_client(sprints)
        oc = _make_org_config()
        tc = _make_team_config()
        payloads = [
            {"fields": {"summary": "ticket A"}, "_sprint_num": "2"},
            {"fields": {"summary": "ticket B"}, "_sprint_num": "3"},
            {"fields": {"summary": "ticket C"}},  # no sprint
        ]

        _resolve_sprint_ids(client, oc, tc, "28", payloads, _make_console())

        assert payloads[0]["fields"][_DEFAULT_SPRINT_FIELD] == 100
        assert payloads[1]["fields"][_DEFAULT_SPRINT_FIELD] == 101
        assert _DEFAULT_SPRINT_FIELD not in payloads[2]["fields"]
        # _sprint_num should be stripped
        assert "_sprint_num" not in payloads[0]
        assert "_sprint_num" not in payloads[1]

    def test_unresolved_sprint_leaves_no_field(self):
        sprints = [{"id": 100, "name": "PI-28.2-Calc -TI83", "state": "future"}]
        client = _make_client(sprints)
        oc = _make_org_config()
        tc = _make_team_config()
        payloads = [
            {"fields": {"summary": "ticket A"}, "_sprint_num": "9"},  # no match
        ]

        _resolve_sprint_ids(client, oc, tc, "28", payloads, _make_console())

        assert _DEFAULT_SPRINT_FIELD not in payloads[0]["fields"]
        assert "_sprint_num" not in payloads[0]

    def test_skips_when_no_board_id(self):
        tc = _make_team_config(board_id=None)
        payloads = [{"fields": {"summary": "x"}, "_sprint_num": "1"}]

        _resolve_sprint_ids(MagicMock(), _make_org_config(), tc, "28", payloads, _make_console())

        # Should not touch anything
        assert "_sprint_num" in payloads[0]

    def test_skips_when_no_template(self):
        tc = _make_team_config(template="")
        payloads = [{"fields": {"summary": "x"}, "_sprint_num": "1"}]

        _resolve_sprint_ids(MagicMock(), _make_org_config(), tc, "28", payloads, _make_console())

        assert "_sprint_num" in payloads[0]

    def test_long_sprint_suffixes(self):
        """Sprint 6a/6b should resolve correctly."""
        sprints = [
            {"id": 200, "name": "PI-28.6a-Calc -TI83", "state": "future"},
            {"id": 201, "name": "PI-28.6b-Calc -TI83", "state": "future"},
        ]
        client = _make_client(sprints)
        oc = _make_org_config()
        tc = _make_team_config()
        payloads = [
            {"fields": {"summary": "Prod Support 6a"}, "_sprint_num": "6a"},
            {"fields": {"summary": "Prod Support 6b"}, "_sprint_num": "6b"},
        ]

        _resolve_sprint_ids(client, oc, tc, "28", payloads, _make_console())

        assert payloads[0]["fields"][_DEFAULT_SPRINT_FIELD] == 200
        assert payloads[1]["fields"][_DEFAULT_SPRINT_FIELD] == 201

    def test_custom_sprint_field_from_org_config(self):
        """When org_config defines sprint_field, that ID is used instead of the default."""
        sprints = [{"id": 100, "name": "PI-28.2-Calc -TI83", "state": "future"}]
        client = _make_client(sprints)
        oc = _make_org_config(sprint_field="customfield_99999")
        tc = _make_team_config()
        payloads = [{"fields": {"summary": "ticket A"}, "_sprint_num": "2"}]

        _resolve_sprint_ids(client, oc, tc, "28", payloads, _make_console())

        assert payloads[0]["fields"]["customfield_99999"] == 100
        assert _DEFAULT_SPRINT_FIELD not in payloads[0]["fields"]


# ---------------------------------------------------------------------------
# Plan 02-03: _resolve_sprints_exist_mode (4-branch resolver) + integration
# ---------------------------------------------------------------------------


def _make_team_with_sprints_exist(value, board_id=362):
    """Build a TeamConfig-like mock with a configurable sprints_exist."""
    tc = MagicMock()
    tc.board_id = board_id
    tc.sprint_name_template = "PI-{pi_num}.{sprint_num}-Calc -TI83"
    tc.sprints_exist = value
    return tc


class TestSprintsExistResolution:
    """Tests for ``_resolve_sprints_exist_mode`` (Plan 02-03 Task 2)."""

    def test_s1_cli_flag_overrides_config_true_wins(self, monkeypatch):
        """S1: CLI override=True beats config=False; prompt not called."""
        from jiramator import planner

        prompt_mock = MagicMock()
        monkeypatch.setattr(planner, "_prompt_sprints_exist", prompt_mock)
        tc = _make_team_with_sprints_exist(False)

        result = planner._resolve_sprints_exist_mode(tc, True, _make_console())

        assert result is True
        prompt_mock.assert_not_called()

    def test_s2_cli_flag_overrides_config_false_wins(self, monkeypatch):
        """S2: CLI override=False beats config=True; prompt not called."""
        from jiramator import planner

        prompt_mock = MagicMock()
        monkeypatch.setattr(planner, "_prompt_sprints_exist", prompt_mock)
        tc = _make_team_with_sprints_exist(True)

        result = planner._resolve_sprints_exist_mode(tc, False, _make_console())

        assert result is False
        prompt_mock.assert_not_called()

    def test_s3_config_true_when_no_flag(self, monkeypatch):
        """S3: config=True, cli=None → True; prompt not called."""
        from jiramator import planner

        prompt_mock = MagicMock()
        monkeypatch.setattr(planner, "_prompt_sprints_exist", prompt_mock)
        tc = _make_team_with_sprints_exist(True)

        result = planner._resolve_sprints_exist_mode(tc, None, _make_console())

        assert result is True
        prompt_mock.assert_not_called()

    def test_s4_config_false_honored_no_prompt(self, monkeypatch):
        """S4 (DC-8 critical): config=False, cli=None → False; prompt not called."""
        from jiramator import planner

        prompt_mock = MagicMock()
        monkeypatch.setattr(planner, "_prompt_sprints_exist", prompt_mock)
        tc = _make_team_with_sprints_exist(False)

        result = planner._resolve_sprints_exist_mode(tc, None, _make_console())

        assert result is False
        prompt_mock.assert_not_called()

    def test_s5_tty_prompt_branch(self, monkeypatch):
        """S5: config=None, cli=None, TTY → prompt called and result returned."""
        from jiramator import planner

        prompt_mock = MagicMock(return_value=True)
        monkeypatch.setattr(planner, "_prompt_sprints_exist", prompt_mock)
        monkeypatch.setattr(planner.sys.stdin, "isatty", lambda: True, raising=False)
        tc = _make_team_with_sprints_exist(None)

        result = planner._resolve_sprints_exist_mode(tc, None, _make_console())

        assert result is True
        prompt_mock.assert_called_once()

    def test_s6_non_tty_raises_config_validation_error(self, monkeypatch):
        """S6: config=None, cli=None, non-TTY → ConfigValidationError with verbatim message."""
        from jiramator import planner
        from jiramator.error_format import ConfigValidationError

        prompt_mock = MagicMock()
        monkeypatch.setattr(planner, "_prompt_sprints_exist", prompt_mock)
        monkeypatch.setattr(planner.sys.stdin, "isatty", lambda: False, raising=False)
        tc = _make_team_with_sprints_exist(None)

        with pytest.raises(ConfigValidationError) as exc_info:
            planner._resolve_sprints_exist_mode(tc, None, _make_console())

        exc = exc_info.value
        assert exc.field_path == "sprints_exist"
        assert exc.reason == (
            "Cannot determine whether sprints exist: stdin is not a TTY "
            "and neither --sprints-exist/--no-sprints-exist nor "
            "'sprints_exist:' in team config is set."
        )
        # str(exc) starts with <runtime>: sprints_exist — (Phase 1 formatter)
        s = str(exc)
        assert "<runtime>" in s
        assert "sprints_exist" in s
        prompt_mock.assert_not_called()


class TestSprintsExistIntegration:
    """End-to-end wiring through ``run_plan`` / ``_run_plan_inner`` (DC-8, II1-II4)."""

    def test_ii3_run_plan_forwards_sprints_exist_override(self, monkeypatch):
        """II3: run_plan(..., sprints_exist_override=True) forwards to _run_plan_inner."""
        from jiramator import planner

        captured = {}

        def _recorder(*args, **kwargs):
            captured.update(kwargs)

        monkeypatch.setattr(planner, "_run_plan_inner", _recorder)
        # Bypass the run-report / persist plumbing — call run_plan with minimal stubs.
        # Use MagicMock for configs since _run_plan_inner is stubbed out.
        org = MagicMock()
        org.pi_label_template = "PI-{pi_num}"
        team = MagicMock()
        team.board_id = None
        # run_plan does pre-prompts (pi_num, fix_versions). Stub them.
        monkeypatch.setattr(planner, "_prompt_pi_number", lambda c: ("28", "PI-28"))
        monkeypatch.setattr(planner, "_prompt_fix_versions", lambda c: ["1.0"])
        monkeypatch.setattr(
            planner, "compute_resolved_hash", lambda *a, **kw: "a" * 64
        )

        try:
            planner.run_plan(
                org,
                team,
                dry_run=True,
                console=_make_console(),
                sprints_exist_override=True,
            )
        except Exception:
            pass  # We only care that _run_plan_inner was invoked with the kwarg.

        assert captured.get("sprints_exist_override") is True

    def test_ii1_no_board_api_call_when_false(self, monkeypatch):
        """II1 (DC-8): when sprints_exist resolves to False, get_board_sprints not invoked.

        Real integration test: drives _run_plan_inner with a wired mock JiraClient.
        Asserts client.get_board_sprints() is NEVER called even when board_id is set.
        """
        from jiramator import planner

        # Mock JiraClient at module level so _run_plan_inner uses the mock
        client_mock = MagicMock()
        # If get_board_sprints is ever called, fail loudly:
        client_mock.get_board_sprints.side_effect = AssertionError(
            "DC-8 violation: get_board_sprints() called when sprints_exist=False"
        )
        # create_issue returns a fake key for any payload:
        client_mock.create_issue.side_effect = lambda payload: "FAKE-1"
        # check_versions_exist returns all existing (no-op):
        client_mock.check_versions_exist.return_value = {}

        monkeypatch.setattr(planner, "JiraClient", lambda *a, **kw: client_mock)
        # Skip the duplicate-warning Confirm.ask
        monkeypatch.setattr(planner, "Confirm", MagicMock())
        planner.Confirm.ask = MagicMock(return_value=True)

        # Build minimal real configs via dicts → Pydantic
        from jiramator.config import OrgConfig, TeamConfig, SprintConfig
        from jiramator.run_report import RunReport

        org = OrgConfig(
            jira_url="https://jira.example.com",
            custom_fields={},
            sprints=SprintConfig(count=4, standard_length_weeks=2, long_length_weeks=3),
        )
        team = TeamConfig(
            project_key="PROJ",
            team_name="Test Team",
            board_id=362,  # board_id IS set — but sprints_exist=False must still skip
            sprints_exist=False,
            sprint_name_template="PI-{pi_num}.{sprint_num}",
            release_sprint_schedule={},
            recurring_epics=[],
            per_release_tickets=[],
            per_sprint_tickets=[],
        )

        # Force credential resolution to succeed without env vars
        monkeypatch.setenv("JIRA_EMAIL", "x@x.com")
        monkeypatch.setenv("JIRA_TOKEN", "tok")

        report = RunReport(
            command=["plan"],
            started_at="2026-01-01T00:00:00Z",
            team_config_path="team.yaml",
            org_config_path="org.yaml",
            team_name="Test Team",
            pi_label="PI-28",
            versions=["1.0"],
            resolved_config_hash="a" * 64,
        )

        # Call _run_plan_inner directly (bypass run_plan's pre-prompts)
        planner._run_plan_inner(
            org_config=org,
            team_config=team,
            pi_label="PI-28",
            pi_num="28",
            versions=["1.0"],
            dry_run=False,  # MUST be live to exercise the API path
            console=_make_console(),
            report=report,
            prior_created_keys={},
            persist=lambda: None,
            sprints_exist_override=None,  # use config (sprints_exist=False)
        )

        # The whole point: get_board_sprints must never have been called
        assert client_mock.get_board_sprints.call_count == 0, (
            "DC-8 violation: get_board_sprints() was called even though "
            "sprints_exist=False"
        )

    def test_ii4_backward_compat_tty_prompt_default_false(self, monkeypatch):
        """II4: existing TTY users (config=None, cli=None) still hit _prompt_sprints_exist."""
        from jiramator import planner

        prompt_mock = MagicMock(return_value=False)
        monkeypatch.setattr(planner, "_prompt_sprints_exist", prompt_mock)
        monkeypatch.setattr(planner.sys.stdin, "isatty", lambda: True, raising=False)
        tc = _make_team_with_sprints_exist(None)

        result = planner._resolve_sprints_exist_mode(tc, None, _make_console())

        assert result is False
        prompt_mock.assert_called_once()
