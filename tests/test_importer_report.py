"""Plan 01-04 Task 3: run_import emits run report + consumes prior on resume."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jiramator.config import BulkCreateConfig, OrgConfig, TeamConfig
from jiramator.importer import _row_template_key, run_import
from jiramator.jira_client import JiraApiError
from jiramator.payload_validator import validate_ticket_payload
from jiramator.run_report import IssueResult, RunReport
from tests.conftest import PermissiveFieldMeta, stub_createmeta

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
# Createmeta stub contract (tests/conftest.py)
# ---------------------------------------------------------------------------


class TestStubCreatemeta:
    def test_get_unknown_field_is_permissive(self):
        meta = PermissiveFieldMeta({}).get("customfield_99999")
        assert isinstance(meta, dict)
        assert meta["required"] is False
        assert "schema" not in meta
        assert "allowedValues" not in meta

    def test_contains_any_key(self):
        assert "anything" in PermissiveFieldMeta({})

    def test_getitem_missing_does_not_raise(self):
        assert PermissiveFieldMeta({})["x"]["required"] is False

    def test_items_only_explicit(self):
        meta = PermissiveFieldMeta({"a": {"name": "A", "required": True}})
        assert list(meta.items()) == [("a", {"name": "A", "required": True})]
        assert meta.get("a") == {"name": "A", "required": True}

    def test_validator_reports_nothing(self):
        payload = {
            "summary": "Risk A",
            "issuetype": {"name": "Risk"},
            "customfield_11941": "plain text",
        }
        assert validate_ticket_payload(payload, PermissiveFieldMeta({})) == []
        assert (
            validate_ticket_payload(
                payload, PermissiveFieldMeta({}), report_off_screen_fields=True
            )
            == []
        )

    def test_stub_createmeta_wires_client(self):
        client = stub_createmeta(
            MagicMock(),
            issue_types=("Risk", "Task"),
            fields_by_type={"Task": {"summary": {"name": "Summary", "required": True}}},
        )
        types = client.get_createmeta_issue_types("CA")
        assert [t["name"] for t in types] == ["Risk", "Task"]
        assert dict(client.get_createmeta_fields("CA", types[0]["id"])) == {}
        assert list(client.get_createmeta_fields("CA", types[1]["id"])) == ["summary"]


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
        stub_createmeta(client)
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
        stub_createmeta(client)
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

        stub_createmeta(client)
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

        stub_createmeta(client)
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

        stub_createmeta(client)
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

        stub_createmeta(client)
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

    def test_i6b_row_error_redacts_token(self, tmp_path, monkeypatch):
        """WR-03: a failed row's ``error`` is redacted like ``run.error``."""
        secret = "tok-SECRET-123456"
        org = _org_config()
        monkeypatch.setenv(org.jira_email_env, "me@example.com")
        monkeypatch.setenv(org.jira_token_env, secret)

        client = MagicMock()

        stub_createmeta(client)
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = [
            JiraApiError(f"401 Authorization: Basic xyz token {secret}", status_code=401)
        ]
        report_path = tmp_path / "r.json"

        run_import(
            [{"Summary": "New", "API Impact": "No"}],
            org_config=org,
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=report_path,
        )

        run = _read_report(report_path)["run"]
        assert run["issues"][0]["status"] == "failed"
        assert run["issues"][0]["error"] == "401 Authorization: Basic *** token ***"
        assert secret not in report_path.read_text(encoding="utf-8")


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

        stub_createmeta(client)
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
        # INV-04: end time (import "Z" format) and cause recorded before re-raise
        assert run["ended_at"].endswith("Z")
        assert run["error"]["type"] == "KeyboardInterrupt"
        assert run["error"]["message"] == "simulated Ctrl-C"

    def test_i7b_failed_crash_write_does_not_mask_original(self, tmp_path):
        """WR-06: an OSError from the crash-handler write is swallowed so
        the original exception propagates unchanged (P-01-01)."""
        from jiramator.run_report import write_report_atomic as real_write

        def flaky_write(report, path):
            if report.error is not None:
                raise OSError("disk full")
            real_write(report, path)

        client = MagicMock()

        stub_createmeta(client)
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = KeyboardInterrupt("simulated Ctrl-C")

        with patch("jiramator.importer.write_report_atomic", side_effect=flaky_write):
            with pytest.raises(KeyboardInterrupt, match="simulated Ctrl-C"):
                run_import(
                    [{"Summary": "A", "API Impact": "No"}],
                    org_config=_org_config(),
                    team_config=_team_config(),
                    jira_fields=[],
                    client=client,
                    report=_new_report(),
                    report_path=tmp_path / "r.json",
                )


# ---------------------------------------------------------------------------
# Backward compatibility: no report kwargs → existing behavior unchanged
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_no_report_kwargs_still_works(self):
        rows = [{"Summary": "X", "API Impact": "No"}]
        client = MagicMock()
        stub_createmeta(client)
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


# ---------------------------------------------------------------------------
# Plan 02-03: live preflight abort (PRE-03, D-01, D-11)
# ---------------------------------------------------------------------------


def _api_impact_createmeta() -> dict[str, dict]:
    """Risk createmeta where API Impact only accepts Yes/No."""
    return {
        "summary": {"name": "Summary", "required": True, "schema": {"type": "string"}},
        "issuetype": {"name": "Issue Type", "required": True, "schema": {"type": "issuetype"}},
        "project": {"name": "Project", "required": True, "schema": {"type": "project"}},
        "customfield_10273": {
            "name": "API Impact",
            "required": False,
            "schema": {"type": "array", "items": "option"},
            "allowedValues": [{"id": "1", "value": "Yes"}, {"id": "2", "value": "No"}],
        },
    }


def _abort_client(createmeta: dict[str, dict] | None = None) -> MagicMock:
    return stub_createmeta(
        MagicMock(),
        fields_by_type={"Risk": createmeta if createmeta is not None else _api_impact_createmeta()},
    )


class TestRunImportPreflightAbort:
    def test_mixed_sheet_records_only_failing_rows(self, tmp_path):
        rows = [
            {"Summary": "Risk A", "API Impact": "Maybe"},
            {"Summary": "Risk B", "API Impact": "No"},
            {"Summary": "Risk C", "API Impact": "Perhaps"},
        ]
        client = _abort_client()
        report = _new_report()
        report_path = tmp_path / "r.json"

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=report,
            report_path=report_path,
        )

        client.create_issue.assert_not_called()
        client.create_issues_bulk.assert_not_called()
        client.find_issue_keys_by_summaries.assert_not_called()
        client.find_user_account_id.assert_not_called()
        assert result.preflight is not None and result.preflight.status == "problems"
        assert result.created == [] and result.skipped == []
        assert [row for row, _, _ in result.failed] == [1, 3]

        run = _read_report(report_path)["run"]
        assert run["error"]["type"] == "Aborted"
        assert run["error"]["message"] == (
            "Preflight found problems in 2 of 3 row(s). No issues were created."
        )
        assert [i["template_key"] for i in run["issues"]] == [
            _row_template_key(1, "Risk A"),
            _row_template_key(3, "Risk C"),
        ]
        assert all(i["status"] == "failed" and i["kind"] == "imported" for i in run["issues"])
        assert "'Maybe'" in run["issues"][0]["error"]
        assert run["counts"].get("failed") == 2
        assert run["counts"].get("created", 0) == 0

    def test_abort_error_redacts_token(self, tmp_path, monkeypatch):
        secret = "tok-SECRET-abcdef123"
        org = _org_config()
        monkeypatch.setenv(org.jira_email_env, "me@example.com")
        monkeypatch.setenv(org.jira_token_env, secret)
        client = _abort_client()
        report_path = tmp_path / "r.json"

        run_import(
            [{"Summary": "Risk A", "API Impact": f"leak {secret}"}],
            org_config=org,
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=report_path,
        )

        text = report_path.read_text(encoding="utf-8")
        assert secret not in text
        run = json.loads(text)["run"]
        assert run["issues"][0]["status"] == "failed"
        assert "***" in run["issues"][0]["error"]
        client.create_issue.assert_not_called()

    def test_duplicate_summary_rows_get_separate_entries(self, tmp_path):
        """OQ-3: rows that would be dedup-skipped are still validated, and
        duplicate summaries in the sheet get one entry per row."""
        rows = [
            {"Summary": "Same", "API Impact": "Bad"},
            {"Summary": "Same", "API Impact": "Bad"},
        ]
        client = _abort_client()
        client.find_issue_keys_by_summaries.return_value = {"Same": "CA-1"}
        report_path = tmp_path / "r.json"

        run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=report_path,
        )

        run = _read_report(report_path)["run"]
        assert [i["template_key"] for i in run["issues"]] == [
            _row_template_key(1, "Same"),
            _row_template_key(2, "Same"),
        ]
        client.find_issue_keys_by_summaries.assert_not_called()


class TestStubCreatemetaThroughPreflight:
    """Plan 02 stub contract proven through the real preflight."""

    def test_stub_createmeta_passes_live_shaped_rows(self):
        from jiramator.import_preflight import run_preflight
        from jiramator.importer import (
            _DEFERRED_FIELDS,
            _DEFERRED_LOGICAL_FIELDS,
            build_preview_report,
        )

        org = _org_config()
        org.custom_fields["repositories"] = "customfield_11941"
        org.bulk_create.field_aliases.update(
            {"Repositories": "repositories", "Description": "description", "Reporter": "reporter"}
        )
        rows = [
            {
                "Summary": "Risk A",
                "API Impact": "No",
                "Repositories": "repo-alpha",
                "Description": "plain text description",
                "Reporter": "Synthetic Person",
            }
        ]
        preview = build_preview_report(
            rows, org_config=org, team_config=_team_config(), jira_fields=[]
        )
        assert preview.failed_rows == 0
        fields = preview.row_results[0].payload["fields"]
        assert "customfield_11941" in fields and "customfield_10273" in fields
        assert "reporter" not in fields  # deferred

        result = run_preflight(
            stub_createmeta(MagicMock()),
            project_key="CA",
            row_results=preview.row_results,
            source_rows=rows,
            org_config=org,
            template_key_fn=_row_template_key,
            deferred_fields=frozenset(_DEFERRED_FIELDS),
            deferred_logical_fields=frozenset(_DEFERRED_LOGICAL_FIELDS),
        )

        assert result.status == "passed"
        assert result.problem_rows == []
        assert all(not row.caveats for row in result.rows)

    def test_e2e_fake_client_passes(self, tmp_path):
        from jiramator.config import load_org_config
        from jiramator.import_preflight import run_preflight
        from jiramator.importer import build_preview_report
        from tests.test_cli_e2e import FakeJiraClient, _write_import_org_config

        org_path = tmp_path / "org.yaml"
        _write_import_org_config(org_path)
        org, _ = load_org_config(org_path)
        # Lower-case header: the e2e import sheets use the standard field name.
        rows = [{"summary": "Imported A"}, {"summary": "Imported B"}]
        team = TeamConfig(project_key="TST", team_name="TestTeam")
        preview = build_preview_report(rows, org_config=org, team_config=team, jira_fields=[])

        result = run_preflight(
            FakeJiraClient(),
            project_key="TST",
            row_results=preview.row_results,
            source_rows=rows,
            org_config=org,
            template_key_fn=_row_template_key,
        )

        assert result.status == "passed"
        assert result.checked_rows == 2
        assert result.problem_rows == []
        assert all(not row.caveats for row in result.rows)


class TestRunImportPreflightResume:
    def _prior(self, *issues: IssueResult) -> RunReport:
        return RunReport(issues=list(issues))

    def test_prior_created_row_is_not_validated(self, tmp_path):
        """D-08: a row created by the prior run is not validated, so its
        (now invalid) value cannot abort the resume."""
        rows = [
            {"Summary": "Risk A", "API Impact": "Maybe"},
            {"Summary": "Risk B", "API Impact": "No"},
        ]
        tk_a = _row_template_key(1, "Risk A")
        prior = self._prior(
            IssueResult(template_key=tk_a, kind="imported", status="created", jira_key="CA-1")
        )
        client = _abort_client()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-2"]
        report_path = tmp_path / "r.json"

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=report_path,
            prior_report=prior,
        )

        assert result.preflight is not None and result.preflight.status == "passed"
        assert result.preflight.considered_rows == 1
        assert client.create_issue.call_count == 1
        run = _read_report(report_path)["run"]
        failed_keys = [i["template_key"] for i in run["issues"] if i["status"] == "failed"]
        assert tk_a not in failed_keys
        assert run.get("error") is None

    def test_resume_after_abort_revalidates_and_creates_every_row(self, tmp_path):
        """D-11: an aborted report created nothing → resume attempts every row."""
        rows = [
            {"Summary": "Risk A", "API Impact": "No"},
            {"Summary": "Risk B", "API Impact": "Yes"},
        ]
        prior = self._prior(
            IssueResult(
                template_key=_row_template_key(1, "Risk A"), kind="imported",
                status="failed", error="old problem",
            ),
            IssueResult(
                template_key=_row_template_key(2, "Risk B"), kind="imported",
                status="failed", error="old problem",
            ),
        )
        client = _abort_client()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-1", "CA-2"]
        report_path = tmp_path / "r.json"

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=report_path,
            prior_report=prior,
        )

        assert result.preflight is not None
        assert result.preflight.checked_rows == 2
        assert result.preflight.status == "passed"
        assert client.create_issue.call_count == 2
        run = _read_report(report_path)["run"]
        assert [i["status"] for i in run["issues"]] == ["created", "created"]

    def test_resumed_abort_keeps_carried_forward_created(self, tmp_path):
        rows = [
            {"Summary": "Risk A", "API Impact": "No"},
            {"Summary": "Risk B", "API Impact": "Maybe"},
        ]
        tk_a = _row_template_key(1, "Risk A")
        prior = self._prior(
            IssueResult(template_key=tk_a, kind="imported", status="created", jira_key="CA-1")
        )
        client = _abort_client()
        report_path = tmp_path / "r.json"

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=report_path,
            prior_report=prior,
        )

        client.create_issue.assert_not_called()
        assert result.preflight is not None and result.preflight.status == "problems"
        run = _read_report(report_path)["run"]
        assert run["issues"][0] == {
            **run["issues"][0],
            "template_key": tk_a,
            "status": "created",
            "jira_key": "CA-1",
        }
        assert run["issues"][1]["template_key"] == _row_template_key(2, "Risk B")
        assert run["issues"][1]["status"] == "failed"
        assert run["counts"]["created"] == 1
        assert run["counts"]["failed"] == 1
        assert run["error"]["message"] == (
            "Preflight found problems in 1 of 1 row(s). No issues were created."
        )

    def test_build_failed_row_aborts_with_build_error(self, tmp_path):
        """D-08: an empty-Summary row is part of the abort list with its
        build error; nothing is created."""
        rows = [
            {"Summary": "Risk A", "API Impact": "No"},
            {"Summary": "", "API Impact": "No"},
            {"Summary": "Risk C", "API Impact": "No"},
        ]
        client = _abort_client()
        report_path = tmp_path / "r.json"

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=report_path,
        )

        client.create_issue.assert_not_called()
        assert [row for row, _, _ in result.failed] == [2]
        run = _read_report(report_path)["run"]
        assert len(run["issues"]) == 1
        assert run["issues"][0]["error"] == "Row 2: required field 'summary' is missing or empty"
        assert run["issues"][0]["template_key"] == _row_template_key(2, "<missing summary>")

    def test_all_rows_pass_creates_as_today(self, tmp_path):
        rows = [
            {"Summary": "Risk A", "API Impact": "No"},
            {"Summary": "Risk B", "API Impact": "Yes"},
        ]
        client = _abort_client()
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-1", "CA-2"]

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=tmp_path / "r.json",
        )

        assert result.preflight is not None and result.preflight.status == "passed"
        assert [key for _, _, key in result.created] == ["CA-1", "CA-2"]
        assert result.failed == []

    def test_zero_data_rows_makes_no_createmeta_call(self, tmp_path):
        client = _abort_client()
        client.find_issue_keys_by_summaries.return_value = {}

        result = run_import(
            [],
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=tmp_path / "r.json",
        )

        client.get_createmeta_issue_types.assert_not_called()
        client.get_createmeta_fields.assert_not_called()
        client.create_issue.assert_not_called()
        assert result.failed == []

    def test_unavailable_proceeds_and_records_build_failures_as_today(self, tmp_path):
        """D-02 + build-failed rows when validation is unavailable."""
        import requests

        rows = [
            {"Summary": "Risk A", "API Impact": "No"},
            {"Summary": "", "API Impact": "No"},
        ]
        client = _abort_client()
        client.get_createmeta_issue_types.side_effect = requests.exceptions.ConnectionError("x")
        client.find_issue_keys_by_summaries.return_value = {}
        client.create_issue.side_effect = ["CA-1"]

        result = run_import(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=[],
            client=client,
            report=_new_report(),
            report_path=tmp_path / "r.json",
        )

        assert result.preflight is not None and result.preflight.status == "unavailable"
        assert [key for _, _, key in result.created] == ["CA-1"]
        assert [row for row, _, _ in result.failed] == [2]
