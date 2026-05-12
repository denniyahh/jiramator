"""Plan 01-04 Task 3: run_import emits run report + consumes prior on resume."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from jiramator.config import BulkCreateConfig, OrgConfig, TeamConfig
from jiramator.importer import _row_template_key, run_import
from jiramator.jira_client import JiraApiError
from jiramator.run_report import IssueResult, RunReport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _org_config() -> OrgConfig:
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={"api_impact": "customfield_10273"},
        bulk_create=BulkCreateConfig(
            field_aliases={
                "Summary": "summary",
                "API Impact": "api_impact",
                "Issue Type": "issuetype",
            },
            field_types={
                "issuetype": "name_object",
                "api_impact": "multi_select",
            },
            defaults={"issuetype": "Risk", "api_impact": "No"},
        ),
        sprints={
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    )


def _team_config() -> TeamConfig:
    return TeamConfig(project_key="CA", team_name="Calcs")


def _read_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _new_report(*, hash_str: str = "h0") -> RunReport:
    return RunReport(resolved_config_hash=hash_str)


# ---------------------------------------------------------------------------
# Template-key helper
# ---------------------------------------------------------------------------


class TestRowTemplateKey:
    def test_shape_and_stability(self):
        tk = _row_template_key(42, "Risk A")
        digest = hashlib.sha256(b"Risk A").hexdigest()[:8]
        assert tk == f"imported:row42:{digest}"

    def test_same_summary_same_hash(self):
        a = _row_template_key(1, "X")
        b = _row_template_key(1, "X")
        assert a == b

    def test_different_summary_different_hash(self):
        a = _row_template_key(1, "X")
        b = _row_template_key(1, "Y")
        assert a != b


# ---------------------------------------------------------------------------
# I1: successful run records every created issue with template_key
# ---------------------------------------------------------------------------


class TestSuccessfulImport:
    def test_i1_success_records_all_created(self, tmp_path):
        rows = [
            {"Summary": "Risk A", "API Impact": "No"},
            {"Summary": "Risk B", "API Impact": "No"},
        ]
        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-1", "CA-2"]

        report = _new_report()
        report_path = tmp_path / "r.json"

        run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=report,
            report_path=report_path,
        )

        env = _read_report(report_path)
        run = env["run"]
        assert run["counts"]["created"] == 2
        keys = {i["template_key"]: i for i in run["issues"]}
        tk_a = _row_template_key(1, "Risk A")
        tk_b = _row_template_key(2, "Risk B")
        assert tk_a in keys and keys[tk_a]["jira_key"] == "CA-1"
        assert tk_b in keys and keys[tk_b]["jira_key"] == "CA-2"
        assert keys[tk_a]["status"] == "created"

        # No _template_key leaked into Jira call
        for call in client.create_issue.call_args_list:
            payload = call.args[0]
            assert "_template_key" not in payload
            assert "_template_key" not in payload.get("fields", {})


# ---------------------------------------------------------------------------
# I2: same-run dedup → skipped status with existing key
# ---------------------------------------------------------------------------


class TestDuplicateSkip:
    def test_i2_dedup_records_skipped(self, tmp_path):
        rows = [{"Summary": "Risk A", "API Impact": "No"}]
        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {"Risk A": "CA-9999"}

        report = _new_report()
        report_path = tmp_path / "r.json"

        run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=report,
            report_path=report_path,
        )

        env = _read_report(report_path)
        run = env["run"]
        assert run["counts"]["skipped"] == 1
        assert run["counts"]["created"] == 0
        skipped = [i for i in run["issues"] if i["status"] == "skipped"]
        assert len(skipped) == 1
        assert skipped[0]["jira_key"] == "CA-9999"


# ---------------------------------------------------------------------------
# I3: incremental persistence (file rewritten between rows)
# ---------------------------------------------------------------------------


class TestIncrementalPersist:
    def test_i3_persisted_per_row(self, tmp_path):
        rows = [
            {"Summary": "Row1", "API Impact": "No"},
            {"Summary": "Row2", "API Impact": "No"},
            {"Summary": "Row3", "API Impact": "No"},
        ]
        snapshots: list[int] = []
        report_path = tmp_path / "r.json"

        def create_with_snapshot(payload):
            # Capture count BEFORE this row's record/persist
            if report_path.exists():
                env = _read_report(report_path)
                snapshots.append(env["run"]["counts"].get("created", 0))
            else:
                snapshots.append(-1)
            return f"CA-{len(snapshots)}"

        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = create_with_snapshot

        report = _new_report()
        run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=report,
            report_path=report_path,
        )

        # row1 sees 0, row2 sees 1, row3 sees 2 — proves per-row persist
        assert snapshots == [0, 1, 2]


# ---------------------------------------------------------------------------
# I4 + I5 + I6: resume behavior
# ---------------------------------------------------------------------------


class TestResume:
    def test_i4_skips_already_created(self, tmp_path):
        """Rows with status=created in prior_report are not re-attempted."""
        rows = [
            {"Summary": "Row1", "API Impact": "No"},
            {"Summary": "Row2", "API Impact": "No"},
        ]
        tk1 = _row_template_key(1, "Row1")

        prior = RunReport(
            issues=[
                IssueResult(
                    template_key=tk1, kind="imported",
                    status="created", jira_key="CA-EXIST",
                ),
            ],
        )

        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-NEW"]

        report = _new_report()
        report_path = tmp_path / "r.json"

        run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=report,
            report_path=report_path,
            prior_report=prior,
        )

        # Row1 not re-created
        assert client.create_issue.call_count == 1
        env = _read_report(report_path)
        run = env["run"]
        keys = {i["template_key"]: i for i in run["issues"]}
        assert keys[tk1]["jira_key"] == "CA-EXIST"
        assert keys[tk1]["status"] == "created"
        # Row2 created fresh
        tk2 = _row_template_key(2, "Row2")
        assert keys[tk2]["jira_key"] == "CA-NEW"

    def test_i5_failed_in_prior_is_retried(self, tmp_path):
        """status=failed entries in prior_report are RE-attempted."""
        rows = [{"Summary": "Row1", "API Impact": "No"}]
        tk = _row_template_key(1, "Row1")

        prior = RunReport(
            issues=[
                IssueResult(
                    template_key=tk, kind="imported",
                    status="failed", error="prior boom",
                ),
            ],
        )

        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-RETRIED"]

        report = _new_report()
        report_path = tmp_path / "r.json"

        run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=report,
            report_path=report_path,
            prior_report=prior,
        )

        # Re-attempted (failed status doesn't gate)
        assert client.create_issue.call_count == 1
        env = _read_report(report_path)
        keys = {i["template_key"]: i for i in env["run"]["issues"]}
        assert keys[tk]["status"] == "created"
        assert keys[tk]["jira_key"] == "CA-RETRIED"

    def test_i6_row_fails_after_succeeding_last_time(self, tmp_path):
        """Resume is additive on success: prior-created rows carry over even
        when new run records other rows as failed."""
        rows = [
            {"Summary": "Old", "API Impact": "No"},
            {"Summary": "New", "API Impact": "No"},
        ]
        tk_old = _row_template_key(1, "Old")
        prior = RunReport(
            issues=[
                IssueResult(
                    template_key=tk_old, kind="imported",
                    status="created", jira_key="CA-OLD",
                ),
            ],
        )

        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = [JiraApiError("boom", status_code=500)]

        report = _new_report()
        report_path = tmp_path / "r.json"

        run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=report,
            report_path=report_path,
            prior_report=prior,
        )

        env = _read_report(report_path)
        run = env["run"]
        # Old row still recorded as created (carried forward)
        keys = {i["template_key"]: i for i in run["issues"]}
        assert keys[tk_old]["status"] == "created"
        # New row marked failed
        tk_new = _row_template_key(2, "New")
        assert keys[tk_new]["status"] == "failed"
        assert "boom" in keys[tk_new]["error"]
        # Counts include both
        assert run["counts"]["created"] == 1
        assert run["counts"]["failed"] == 1


# ---------------------------------------------------------------------------
# I7: persist on KeyboardInterrupt
# ---------------------------------------------------------------------------


class TestPersistOnInterrupt:
    def test_i7_keyboardinterrupt_persists(self, tmp_path):
        rows = [
            {"Summary": "A", "API Impact": "No"},
            {"Summary": "B", "API Impact": "No"},
        ]

        call_count = {"n": 0}

        def create_with_interrupt(payload):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return "CA-1"
            raise KeyboardInterrupt("simulated Ctrl-C")

        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = create_with_interrupt

        report = _new_report()
        report_path = tmp_path / "r.json"

        with pytest.raises(KeyboardInterrupt):
            run_import(
                rows,
                org_config=_org_config(),
                team_config=_team_config(),
                jira_fields=[],
                client=client,
                report=report,
                report_path=report_path,
            )

        # File on disk is valid JSON, reflects the 1 created row
        assert report_path.exists()
        env = _read_report(report_path)
        run = env["run"]
        assert run["counts"]["created"] >= 1


# ---------------------------------------------------------------------------
# Backward compatibility: no report kwargs → existing behavior unchanged
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_no_report_kwargs_still_works(self):
        rows = [{"Summary": "X", "API Impact": "No"}]
        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.return_value = "CA-1"

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
        )
        assert result.created == [(1, "X", "CA-1")]
