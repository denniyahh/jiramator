"""Thin wrapper around the Jira REST API for issue and version management.

This module handles authentication, request formatting, error handling, and
retry logic.  It does NOT do any template interpolation or payload building —
that's the ticket_builder's job.  This module takes ready-made payloads and
ships them to Jira.

All methods raise ``JiraApiError`` on failure with structured error details
from the Jira response body.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from jiramator.config import OrgConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class JiraApiError(Exception):
    """Raised when a Jira API call fails.

    Attributes:
        status_code: HTTP status code (None for connection errors).
        errors: Jira field-level error dict (if available).
        message: Human-readable error message.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        errors: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.errors = errors or {}
        super().__init__(message)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

# Retry on 429 (rate limit), 502/503/504 (transient server errors).
_RETRY_STRATEGY = Retry(
    total=3,
    backoff_factor=1.0,  # 1s, 2s, 4s
    status_forcelist=[429, 502, 503, 504],
    allowed_methods=["GET", "POST", "PUT"],
    raise_on_status=False,  # We handle status codes ourselves
)

_DEFAULT_TIMEOUT = 30  # seconds
_BULK_BATCH_SIZE = 50


@dataclass
class JiraClient:
    """Low-level Jira REST API client.

    Constructed from an ``OrgConfig`` — credentials are resolved from env vars
    at init time so failures surface early.

    Args:
        org_config: Organization config with Jira URL and credential env var names.
    """

    org_config: OrgConfig
    _session: requests.Session = field(init=False, repr=False)
    _base_url: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        email, token = self.org_config.resolve_credentials()
        self._base_url = str(self.org_config.jira_url).rstrip("/")

        self._session = requests.Session()
        self._session.auth = (email, token)
        self._session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        # Mount retry adapter for both http and https
        adapter = HTTPAdapter(max_retries=_RETRY_STRATEGY)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # -- internal helpers --------------------------------------------------

    def _url(self, path: str) -> str:
        """Build a full URL from a REST API path."""
        return f"{self._base_url}{path}"

    def _handle_error(self, response: requests.Response, context: str) -> None:
        """Raise ``JiraApiError`` with details extracted from the response.

        Args:
            response: The failed HTTP response.
            context: Human-readable description of what we were trying to do
                     (e.g. "creating issue").
        """
        status = response.status_code

        # Try to extract Jira's structured error body
        try:
            body = response.json()
        except (ValueError, requests.exceptions.JSONDecodeError):
            body = {}

        errors = body.get("errors", {})
        error_messages = body.get("errorMessages", [])

        if status == 401:
            raise JiraApiError(
                f"Authentication failed (401) while {context}. "
                f"Check your {self.org_config.jira_token_env} env var.",
                status_code=status,
                errors=errors,
            )

        if status == 403:
            raise JiraApiError(
                f"Permission denied (403) while {context}. "
                f"Your Jira user may lack the required project permissions.",
                status_code=status,
                errors=errors,
            )

        if status == 404:
            raise JiraApiError(
                f"Not found (404) while {context}. "
                f"Check that the project/resource exists.",
                status_code=status,
                errors=errors,
            )

        # Generic error — include Jira's field-level errors if present
        parts = [f"Jira API error ({status}) while {context}."]
        if error_messages:
            parts.append(f"Messages: {'; '.join(error_messages)}")
        if errors:
            parts.append(f"Field errors: {errors}")

        raise JiraApiError(
            " ".join(parts),
            status_code=status,
            errors=errors,
        )

    # -- public API --------------------------------------------------------

    def get_project(self, project_key: str) -> dict[str, Any]:
        """Validate that a project exists and return its metadata.

        Raises:
            JiraApiError: If the project doesn't exist or auth fails.
        """
        response = self._session.get(
            self._url(f"/rest/api/3/project/{project_key}"),
            timeout=_DEFAULT_TIMEOUT,
        )
        if not response.ok:
            self._handle_error(response, f"fetching project {project_key}")
        return response.json()

    def get_fields(self) -> list[dict[str, Any]]:
        """Fetch Jira field metadata for field name/id resolution."""
        response = self._session.get(
            self._url("/rest/api/3/field"),
            timeout=_DEFAULT_TIMEOUT,
        )
        if not response.ok:
            self._handle_error(response, "fetching Jira field metadata")
        return response.json()

    def find_issue_keys_by_summaries(
        self,
        project_key: str,
        summaries: list[str],
    ) -> dict[str, str]:
        """Return an exact-summary -> issue key mapping for existing issues in a project."""
        unique_summaries = sorted({summary.strip() for summary in summaries if summary.strip()})
        if not unique_summaries:
            return {}

        clauses = []
        for summary in unique_summaries:
            escaped = summary.replace("\\", "\\\\").replace('"', '\\"')
            clauses.append(f'summary ~ "\\"{escaped}\\""')

        jql = f'project = "{project_key}" AND (' + " OR ".join(clauses) + ")"
        response = self._session.get(
            self._url("/rest/api/3/search"),
            params={
                "jql": jql,
                "fields": "summary",
                "maxResults": len(unique_summaries),
            },
            timeout=_DEFAULT_TIMEOUT,
        )
        if not response.ok:
            self._handle_error(response, "searching for existing issues by summary")

        issues = response.json().get("issues", [])
        requested = set(unique_summaries)
        matches: dict[str, str] = {}
        for issue in issues:
            summary = issue.get("fields", {}).get("summary", "")
            key = issue.get("key")
            if summary in requested and key:
                matches[summary] = key
        return matches

    def find_user_account_id(self, query: str) -> str | None:
        """Resolve a Jira Cloud user query to an accountId using exact-match preference."""
        cleaned = query.strip()
        if not cleaned:
            return None

        response = self._session.get(
            self._url("/rest/api/3/user/search"),
            params={"query": cleaned},
            timeout=_DEFAULT_TIMEOUT,
        )
        if not response.ok:
            self._handle_error(response, "resolving Jira user")

        users = response.json()
        if not users:
            return None

        lowered = cleaned.casefold()
        for user in users:
            if str(user.get("displayName", "")).casefold() == lowered:
                return user.get("accountId")

        return users[0].get("accountId")

    def create_issue(self, payload: dict[str, Any]) -> str:
        """Create a single Jira issue.

        Args:
            payload: A ``{"fields": {...}}`` dict (output of the ticket builder).

        Returns:
            The created issue key (e.g. "CA-5001").

        Raises:
            JiraApiError: On any API error.
        """
        response = self._session.post(
            self._url("/rest/api/3/issue"),
            json=payload,
            timeout=_DEFAULT_TIMEOUT,
        )
        if not response.ok:
            summary = payload.get("fields", {}).get("summary", "<unknown>")
            self._handle_error(response, f"creating issue '{summary}'")

        data = response.json()
        key = data["key"]
        logger.info("Created issue %s", key)
        return key

    def create_issues_bulk(
        self,
        payloads: list[dict[str, Any]],
        *,
        batch_size: int = _BULK_BATCH_SIZE,
    ) -> list[str]:
        """Create multiple issues in batches.

        Jira's bulk create endpoint accepts up to 50 issues per call.
        This method splits larger lists into batches automatically.

        Args:
            payloads: List of ``{"fields": {...}}`` dicts.
            batch_size: Max issues per API call (default 50, Jira's limit).

        Returns:
            List of created issue keys, in the same order as the input payloads.

        Raises:
            JiraApiError: If any batch fails.  Already-created issues from
                previous batches are NOT rolled back.
        """
        all_keys: list[str] = []

        for batch_start in range(0, len(payloads), batch_size):
            batch = payloads[batch_start : batch_start + batch_size]
            batch_num = (batch_start // batch_size) + 1
            total_batches = (len(payloads) + batch_size - 1) // batch_size

            logger.info(
                "Creating batch %d/%d (%d issues)",
                batch_num, total_batches, len(batch),
            )

            response = self._session.post(
                self._url("/rest/api/3/issue/bulk"),
                json={"issueUpdates": batch},
                timeout=_DEFAULT_TIMEOUT * 2,  # bulk takes longer
            )
            if not response.ok:
                self._handle_error(
                    response,
                    f"bulk creating issues (batch {batch_num}/{total_batches})",
                )

            data = response.json()

            # Jira bulk response has "issues" array on success and
            # may have "errors" array for partial failures
            if data.get("errors"):
                # Partial failure — some issues created, some failed
                failed = data["errors"]
                raise JiraApiError(
                    f"Bulk create partial failure in batch {batch_num}: "
                    f"{len(failed)} issue(s) failed. "
                    f"Details: {failed}",
                    status_code=response.status_code,
                    errors={"bulk_errors": failed},
                )

            batch_keys = [issue["key"] for issue in data.get("issues", [])]
            all_keys.extend(batch_keys)

        return all_keys

    def get_fix_versions(self, project_key: str) -> list[dict[str, Any]]:
        """Get all fix versions for a project.

        Returns:
            List of version dicts with at least ``id``, ``name``, ``released`` keys.
        """
        response = self._session.get(
            self._url(f"/rest/api/3/project/{project_key}/versions"),
            timeout=_DEFAULT_TIMEOUT,
        )
        if not response.ok:
            self._handle_error(
                response, f"fetching fix versions for {project_key}"
            )
        return response.json()

    def create_fix_version(self, project_key: str, name: str) -> dict[str, Any]:
        """Create a fix version in a project.

        If the version already exists (409 Conflict), this is silently
        treated as success — the existing version info is fetched and returned.

        Args:
            project_key: The Jira project key (e.g. "CA").
            name: The version name (e.g. "26.1.1").

        Returns:
            The version dict (``id``, ``name``, etc.).
        """
        payload = {
            "name": name,
            "project": project_key,
        }
        response = self._session.post(
            self._url("/rest/api/3/version"),
            json=payload,
            timeout=_DEFAULT_TIMEOUT,
        )

        if response.status_code == 409:
            # Version already exists — not an error
            logger.info(
                "Fix version '%s' already exists in %s, skipping creation",
                name, project_key,
            )
            # Fetch existing versions to find the matching one
            versions = self.get_fix_versions(project_key)
            for v in versions:
                if v["name"] == name:
                    return v
            # Shouldn't happen, but fall back to a minimal dict
            return {"name": name, "project": project_key}

        if not response.ok:
            self._handle_error(
                response, f"creating fix version '{name}' in {project_key}"
            )

        data = response.json()
        logger.info("Created fix version '%s' (id=%s)", name, data.get("id"))
        return data

    def get_board_sprints(
        self,
        board_id: int,
        state: str = "future,active",
    ) -> list[dict[str, Any]]:
        """Get sprints for an agile board.

        Uses the Jira Agile REST API (``/rest/agile/1.0/``).

        Args:
            board_id: The Jira board ID.
            state: Comma-separated sprint states to filter by
                   (e.g. "future,active", "active").

        Returns:
            List of sprint dicts with ``id``, ``name``, ``state`` keys.
        """
        sprints: list[dict[str, Any]] = []
        start_at = 0
        page_size = 50

        while True:
            response = self._session.get(
                self._url(f"/rest/agile/1.0/board/{board_id}/sprint"),
                params={
                    "state": state,
                    "startAt": start_at,
                    "maxResults": page_size,
                },
                timeout=_DEFAULT_TIMEOUT,
            )
            if not response.ok:
                self._handle_error(
                    response,
                    f"fetching sprints for board {board_id} (state={state})",
                )

            data = response.json()
            sprints.extend(data.get("values", []))

            # Pagination: stop when we've fetched everything
            if data.get("isLast", True):
                break
            start_at += page_size

        return sprints
