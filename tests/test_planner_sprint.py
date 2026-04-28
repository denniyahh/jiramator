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
