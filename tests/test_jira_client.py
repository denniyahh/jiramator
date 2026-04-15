"""Tests for the Jira REST API client.

All HTTP calls are mocked — no real Jira API traffic.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests

from jiramator.config import OrgConfig
from jiramator.jira_client import JiraApiError, JiraClient, _BULK_BATCH_SIZE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def org_config() -> OrgConfig:
    """A minimal org config for testing."""
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        jira_email_env="JIRA_EMAIL",
        jira_token_env="JIRA_TOKEN",
        custom_fields={"story_points": "customfield_10026"},
        sprints={
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    )


@pytest.fixture()
def client(org_config: OrgConfig, monkeypatch: pytest.MonkeyPatch) -> JiraClient:
    """A JiraClient with mocked credentials."""
    monkeypatch.setenv("JIRA_EMAIL", "test@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "fake-token-12345")
    return JiraClient(org_config=org_config)


def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    ok: bool | None = None,
) -> MagicMock:
    """Create a mock requests.Response."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = ok if ok is not None else (200 <= status_code < 300)
    resp.json.return_value = json_data or {}
    return resp


# ---------------------------------------------------------------------------
# Client initialization
# ---------------------------------------------------------------------------


class TestClientInit:
    """Test client construction and credential resolution."""

    def test_creates_session_with_auth(
        self, client: JiraClient, org_config: OrgConfig
    ) -> None:
        assert client._session.auth == ("test@example.com", "fake-token-12345")
        assert client._base_url == "https://example.atlassian.net"

    def test_strips_trailing_slash_from_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("JIRA_EMAIL", "a@b.com")
        monkeypatch.setenv("JIRA_TOKEN", "tok")
        org = OrgConfig(
            jira_url="https://example.atlassian.net/",
            sprints={"count": 1, "standard_length_weeks": 2, "long_length_weeks": 3},
        )
        c = JiraClient(org_config=org)
        assert c._base_url == "https://example.atlassian.net"

    def test_missing_credentials_raises(
        self, org_config: OrgConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)
        with pytest.raises(ValueError, match="Missing required environment variable"):
            JiraClient(org_config=org_config)


# ---------------------------------------------------------------------------
# get_project
# ---------------------------------------------------------------------------


class TestGetProject:
    def test_success(self, client: JiraClient) -> None:
        project_data = {"key": "CA", "name": "Calcs", "id": "10001"}
        client._session.get = MagicMock(
            return_value=_mock_response(200, project_data)
        )
        result = client.get_project("CA")
        assert result == project_data
        client._session.get.assert_called_once()

    def test_404_raises(self, client: JiraClient) -> None:
        client._session.get = MagicMock(
            return_value=_mock_response(404, {"errorMessages": ["Project not found"]})
        )
        with pytest.raises(JiraApiError, match="Not found.*404"):
            client.get_project("NOPE")

    def test_401_raises_with_token_hint(self, client: JiraClient) -> None:
        client._session.get = MagicMock(
            return_value=_mock_response(401, {})
        )
        with pytest.raises(JiraApiError, match="JIRA_TOKEN"):
            client.get_project("CA")


# ---------------------------------------------------------------------------
# create_issue
# ---------------------------------------------------------------------------


class TestCreateIssue:
    def test_success_returns_key(self, client: JiraClient) -> None:
        payload = {"fields": {"summary": "Test issue", "project": {"key": "CA"}}}
        client._session.post = MagicMock(
            return_value=_mock_response(201, {"key": "CA-101", "id": "50001"})
        )
        key = client.create_issue(payload)
        assert key == "CA-101"

    def test_400_surfaces_field_errors(self, client: JiraClient) -> None:
        payload = {"fields": {"summary": "", "project": {"key": "CA"}}}
        error_body = {
            "errorMessages": [],
            "errors": {"summary": "You must specify a summary of the issue."},
        }
        client._session.post = MagicMock(
            return_value=_mock_response(400, error_body)
        )
        with pytest.raises(JiraApiError, match="summary.*must specify"):
            client.create_issue(payload)

    def test_error_includes_summary_in_context(self, client: JiraClient) -> None:
        payload = {"fields": {"summary": "My task", "project": {"key": "CA"}}}
        client._session.post = MagicMock(
            return_value=_mock_response(500, {"errorMessages": ["Internal"]})
        )
        with pytest.raises(JiraApiError, match="My task"):
            client.create_issue(payload)


# ---------------------------------------------------------------------------
# create_issues_bulk
# ---------------------------------------------------------------------------


class TestCreateIssuesBulk:
    def test_single_batch(self, client: JiraClient) -> None:
        payloads = [
            {"fields": {"summary": f"Issue {i}"}} for i in range(5)
        ]
        bulk_response = {
            "issues": [{"key": f"CA-{100 + i}", "id": str(5000 + i)} for i in range(5)],
            "errors": [],
        }
        client._session.post = MagicMock(
            return_value=_mock_response(201, bulk_response)
        )
        keys = client.create_issues_bulk(payloads)
        assert keys == [f"CA-{100 + i}" for i in range(5)]
        # Should be a single API call
        assert client._session.post.call_count == 1

    def test_multiple_batches(self, client: JiraClient) -> None:
        """More than batch_size issues get split into multiple API calls."""
        n = 7
        payloads = [{"fields": {"summary": f"Issue {i}"}} for i in range(n)]

        # batch_size=3 → 3 batches: 3 + 3 + 1
        batch1_resp = _mock_response(201, {
            "issues": [{"key": f"CA-{i}", "id": str(i)} for i in range(3)],
            "errors": [],
        })
        batch2_resp = _mock_response(201, {
            "issues": [{"key": f"CA-{3 + i}", "id": str(3 + i)} for i in range(3)],
            "errors": [],
        })
        batch3_resp = _mock_response(201, {
            "issues": [{"key": "CA-6", "id": "6"}],
            "errors": [],
        })
        client._session.post = MagicMock(
            side_effect=[batch1_resp, batch2_resp, batch3_resp]
        )

        keys = client.create_issues_bulk(payloads, batch_size=3)
        assert len(keys) == 7
        assert client._session.post.call_count == 3

        # Verify batch sizes in the request bodies
        calls = client._session.post.call_args_list
        body = lambda i: calls[i].kwargs.get("json") or calls[i][1].get("json")
        assert len(body(0)["issueUpdates"]) == 3
        assert len(body(1)["issueUpdates"]) == 3
        assert len(body(2)["issueUpdates"]) == 1

    def test_partial_failure_raises(self, client: JiraClient) -> None:
        payloads = [{"fields": {"summary": "OK"}}, {"fields": {"summary": ""}}]
        client._session.post = MagicMock(
            return_value=_mock_response(201, {
                "issues": [{"key": "CA-1", "id": "1"}],
                "errors": [{"status": 400, "elementErrors": {"summary": "required"}}],
            })
        )
        with pytest.raises(JiraApiError, match="partial failure"):
            client.create_issues_bulk(payloads)

    def test_empty_list_returns_empty(self, client: JiraClient) -> None:
        keys = client.create_issues_bulk([])
        assert keys == []

    def test_http_error_raises(self, client: JiraClient) -> None:
        payloads = [{"fields": {"summary": "Fail"}}]
        client._session.post = MagicMock(
            return_value=_mock_response(500, {"errorMessages": ["boom"]})
        )
        with pytest.raises(JiraApiError, match="500"):
            client.create_issues_bulk(payloads)


# ---------------------------------------------------------------------------
# get_fix_versions
# ---------------------------------------------------------------------------


class TestGetFixVersions:
    def test_success(self, client: JiraClient) -> None:
        versions = [
            {"id": "1", "name": "26.1.0", "released": True},
            {"id": "2", "name": "26.1.1", "released": False},
        ]
        client._session.get = MagicMock(
            return_value=_mock_response(200, versions)
        )
        result = client.get_fix_versions("CA")
        assert len(result) == 2
        assert result[0]["name"] == "26.1.0"

    def test_error_raises(self, client: JiraClient) -> None:
        client._session.get = MagicMock(
            return_value=_mock_response(403, {})
        )
        with pytest.raises(JiraApiError, match="Permission denied"):
            client.get_fix_versions("CA")


# ---------------------------------------------------------------------------
# create_fix_version
# ---------------------------------------------------------------------------


class TestCreateFixVersion:
    def test_success(self, client: JiraClient) -> None:
        created = {"id": "10", "name": "26.2.0", "project": "CA"}
        client._session.post = MagicMock(
            return_value=_mock_response(201, created)
        )
        result = client.create_fix_version("CA", "26.2.0")
        assert result["name"] == "26.2.0"
        assert result["id"] == "10"

    def test_409_conflict_fetches_existing(self, client: JiraClient) -> None:
        """409 = version already exists, should silently succeed."""
        # POST returns 409
        conflict_resp = _mock_response(409, {})
        client._session.post = MagicMock(return_value=conflict_resp)

        # GET for fetching existing versions
        existing = [
            {"id": "5", "name": "26.1.0"},
            {"id": "6", "name": "26.2.0"},
        ]
        client._session.get = MagicMock(
            return_value=_mock_response(200, existing)
        )

        result = client.create_fix_version("CA", "26.2.0")
        assert result["name"] == "26.2.0"
        assert result["id"] == "6"

    def test_409_version_not_found_in_list(self, client: JiraClient) -> None:
        """409 but the version isn't in the list (edge case) — returns minimal dict."""
        client._session.post = MagicMock(return_value=_mock_response(409, {}))
        client._session.get = MagicMock(
            return_value=_mock_response(200, [{"id": "1", "name": "other"}])
        )
        result = client.create_fix_version("CA", "ghost")
        assert result["name"] == "ghost"

    def test_400_raises(self, client: JiraClient) -> None:
        client._session.post = MagicMock(
            return_value=_mock_response(400, {"errorMessages": ["Invalid name"]})
        )
        with pytest.raises(JiraApiError, match="Invalid name"):
            client.create_fix_version("CA", "")


# ---------------------------------------------------------------------------
# get_board_sprints
# ---------------------------------------------------------------------------


class TestGetBoardSprints:
    def test_single_page(self, client: JiraClient) -> None:
        sprints_data = {
            "values": [
                {"id": 1, "name": "Sprint 1", "state": "active"},
                {"id": 2, "name": "Sprint 2", "state": "future"},
            ],
            "isLast": True,
        }
        client._session.get = MagicMock(
            return_value=_mock_response(200, sprints_data)
        )
        result = client.get_board_sprints(100)
        assert len(result) == 2
        assert result[0]["name"] == "Sprint 1"

    def test_pagination(self, client: JiraClient) -> None:
        """Multiple pages of sprints are fetched and concatenated."""
        page1 = _mock_response(200, {
            "values": [{"id": i, "name": f"Sprint {i}"} for i in range(50)],
            "isLast": False,
        })
        page2 = _mock_response(200, {
            "values": [{"id": 50 + i, "name": f"Sprint {50 + i}"} for i in range(10)],
            "isLast": True,
        })
        client._session.get = MagicMock(side_effect=[page1, page2])

        result = client.get_board_sprints(100, state="future,active")
        assert len(result) == 60
        assert client._session.get.call_count == 2

    def test_error_raises(self, client: JiraClient) -> None:
        client._session.get = MagicMock(
            return_value=_mock_response(404, {"errorMessages": ["Board not found"]})
        )
        with pytest.raises(JiraApiError, match="Not found"):
            client.get_board_sprints(99999)

    def test_state_param_forwarded(self, client: JiraClient) -> None:
        """Verify the state parameter is sent to the API."""
        client._session.get = MagicMock(
            return_value=_mock_response(200, {"values": [], "isLast": True})
        )
        client.get_board_sprints(100, state="active")
        call_kwargs = client._session.get.call_args
        assert call_kwargs.kwargs.get("params", {}).get("state") == "active" or \
            call_kwargs[1].get("params", {}).get("state") == "active"


# ---------------------------------------------------------------------------
# Error handling edge cases
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_non_json_response_body(self, client: JiraClient) -> None:
        """Server returns non-JSON (e.g. HTML error page) — should still raise cleanly."""
        resp = MagicMock(spec=requests.Response)
        resp.status_code = 502
        resp.ok = False
        resp.json.side_effect = ValueError("No JSON")
        client._session.get = MagicMock(return_value=resp)

        with pytest.raises(JiraApiError, match="502"):
            client.get_project("CA")

    def test_403_includes_permission_message(self, client: JiraClient) -> None:
        client._session.post = MagicMock(
            return_value=_mock_response(403, {})
        )
        with pytest.raises(JiraApiError, match="Permission denied"):
            client.create_issue({"fields": {"summary": "test"}})

    def test_error_preserves_status_code_and_errors(self, client: JiraClient) -> None:
        error_body = {
            "errorMessages": ["Something went wrong"],
            "errors": {"customfield_10026": "invalid value"},
        }
        client._session.post = MagicMock(
            return_value=_mock_response(400, error_body)
        )
        with pytest.raises(JiraApiError) as exc_info:
            client.create_issue({"fields": {"summary": "test"}})

        err = exc_info.value
        assert err.status_code == 400
        assert "customfield_10026" in err.errors
