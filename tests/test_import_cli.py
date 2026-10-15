"""CLI/import integration tests for spreadsheet-driven Jira issue import."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from click.testing import CliRunner

from jiramator.cli import cli
from jiramator.config import load_org_config, load_team_config
from jiramator.importer import _row_template_key
from jiramator.jira_client import JiraApiError
from jiramator.run_report import (
    IssueResult,
    RunReport,
    compute_resolved_hash,
    write_report_atomic,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestImportCommand:
    def test_help_shows_expected_options(self, runner: CliRunner):
        result = runner.invoke(cli, ["import", "--help"])

        assert result.exit_code == 0
        assert "--org-config" in result.output
        assert "--team-config" in result.output
        assert "--sheet-name" in result.output
        assert "--dry-run" in result.output
        assert "--max-rows" in result.output
        assert "--preview-rows" in result.output

    def test_dry_run_prints_preview_without_creating_issues(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        """Dry-run opportunistically fetches live field metadata for a more
        accurate preview (see cli.py's import_command), but never creates
        issues — create_issue/create_issues_bulk must never be called.
        """
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary,API Impact\nRisk A,No\n")

        fake_report = MagicMock()
        fake_report.total_rows = 1
        fake_report.successful_rows = 1
        fake_report.failed_rows = 0
        fake_report.row_results = []

        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: [{"Summary": "Risk A", "API Impact": "No"}])
        monkeypatch.setattr("jiramator.importer.build_preview_report", lambda *args, **kwargs: fake_report)
        monkeypatch.setattr("jiramator.cli.render_preview_report", lambda *args, **kwargs: "PREVIEW REPORT")

        mock_client = MagicMock()
        mock_client.get_fields.return_value = []
        jira_client_ctor = MagicMock(return_value=mock_client)
        monkeypatch.setattr("jiramator.cli.JiraClient", jira_client_ctor)

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                "--dry-run",
                str(sheet_path),
            ],
        )

        assert result.exit_code == 0
        assert "PREVIEW REPORT" in result.output
        mock_client.create_issue.assert_not_called()
        mock_client.create_issues_bulk.assert_not_called()

    def test_dry_run_degrades_gracefully_without_credentials(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        """No Jira credentials available → dry-run warns and still completes."""
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary,API Impact\nRisk A,No\n")

        fake_report = MagicMock()
        fake_report.total_rows = 1
        fake_report.successful_rows = 1
        fake_report.failed_rows = 0
        fake_report.row_results = []

        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: [{"Summary": "Risk A", "API Impact": "No"}])
        monkeypatch.setattr("jiramator.importer.build_preview_report", lambda *args, **kwargs: fake_report)
        monkeypatch.setattr("jiramator.cli.render_preview_report", lambda *args, **kwargs: "PREVIEW REPORT")
        monkeypatch.setattr(
            "jiramator.cli.JiraClient",
            MagicMock(side_effect=ValueError("JIRA_TOKEN env var not set")),
        )

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                "--dry-run",
                str(sheet_path),
            ],
        )

        assert result.exit_code == 0
        assert "PREVIEW REPORT" in result.output
        assert "Schema validation skipped" in result.output

    def test_dry_run_degrades_gracefully_when_jira_unreachable(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        """Jira reachable at auth but get_fields() fails → dry-run still completes."""
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary,API Impact\nRisk A,No\n")

        fake_report = MagicMock()
        fake_report.total_rows = 1
        fake_report.successful_rows = 1
        fake_report.failed_rows = 0
        fake_report.row_results = []

        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: [{"Summary": "Risk A", "API Impact": "No"}])
        monkeypatch.setattr("jiramator.importer.build_preview_report", lambda *args, **kwargs: fake_report)
        monkeypatch.setattr("jiramator.cli.render_preview_report", lambda *args, **kwargs: "PREVIEW REPORT")

        mock_client = MagicMock()
        mock_client.get_fields.side_effect = JiraApiError("Server Error", status_code=500)
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=mock_client))

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                "--dry-run",
                str(sheet_path),
            ],
        )

        assert result.exit_code == 0
        assert "PREVIEW REPORT" in result.output
        assert "Preview based on field_aliases only (could not reach Jira)" in " ".join(
            result.output.split()
        )

    def test_unsupported_extension_exits_nonzero_with_clear_message(
        self,
        runner: CliRunner,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        sheet_path = tmp_path / "import.txt"
        sheet_path.write_text("hello")

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                str(sheet_path),
            ],
        )

        assert result.exit_code == 1
        assert "Unsupported spreadsheet file type" in result.output

    def test_live_mode_continues_after_row_failure_and_reports_summary(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary,API Impact\nRisk A,No\nRisk B,No\n")

        rows = [
            {"Summary": "Risk A", "API Impact": "No"},
            {"Summary": "Risk B", "API Impact": "No"},
        ]
        row_results = [
            MagicMock(success=True, row_number=1, summary="Risk A", payload={"fields": {"summary": "Risk A"}}, warnings=[], error=None),
            MagicMock(success=True, row_number=2, summary="Risk B", payload={"fields": {"summary": "Risk B"}}, warnings=[], error=None),
        ]
        preview_report = MagicMock(total_rows=2, successful_rows=2, failed_rows=0, row_results=row_results)

        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: rows)
        monkeypatch.setattr("jiramator.importer.build_preview_report", lambda *args, **kwargs: preview_report)
        monkeypatch.setattr("jiramator.cli.render_preview_report", lambda *args, **kwargs: "PREVIEW REPORT")

        client = MagicMock()
        client.get_fields.return_value = []
        client.find_issue_keys_by_summaries.return_value = {"Risk A": "CA-4999"}
        client.create_issue.side_effect = [JiraApiError("boom")]
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda org_config: client)

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                str(sheet_path),
            ],
        )

        assert result.exit_code == 1
        assert "created=0" in result.output
        assert "skipped=1" in result.output
        assert "failed=1" in result.output
        assert "Row 1" in result.output
        assert "duplicate summary already exists as CA-4999" in result.output
        assert "Row 2" in result.output
        assert "boom" in result.output

    def test_live_import_connection_error_writes_report_with_error(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary\nRisk A\n")
        monkeypatch.setattr(
            "jiramator.cli.read_spreadsheet",
            lambda *args, **kwargs: [{"Summary": "Risk A"}],
        )
        client = MagicMock()
        client.get_fields.side_effect = requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda org_config: client)
        report_path = tmp_path / "r.json"

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config", str(org_config_path),
                "--team-config", str(team_config_path),
                "--report", str(report_path),
                str(sheet_path),
            ],
        )

        assert result.exit_code != 0
        assert isinstance(result.exception, requests.exceptions.ConnectionError)
        assert report_path.exists()
        run = json.loads(report_path.read_text(encoding="utf-8"))["run"]
        assert run["error"] == {"type": "ConnectionError", "message": "boom"}
        assert run["ended_at"].endswith("Z")
        assert run["status"] == "failed"

    def test_live_import_credential_error_records_value_error(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary\nRisk A\n")
        monkeypatch.setattr(
            "jiramator.cli.read_spreadsheet",
            lambda *args, **kwargs: [{"Summary": "Risk A"}],
        )

        def _raise(org_config):
            raise ValueError("missing token")

        monkeypatch.setattr("jiramator.cli.JiraClient", _raise)
        report_path = tmp_path / "r.json"

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config", str(org_config_path),
                "--team-config", str(team_config_path),
                "--report", str(report_path),
                str(sheet_path),
            ],
        )

        assert result.exit_code == 1
        assert "Import error: missing token" in result.output
        run = json.loads(report_path.read_text(encoding="utf-8"))["run"]
        assert run["error"] == {"type": "ValueError", "message": "missing token"}
        assert run["ended_at"] is not None

    def test_live_import_inner_error_not_overwritten_by_cli(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary\nRisk A\n")
        monkeypatch.setattr(
            "jiramator.cli.read_spreadsheet",
            lambda *args, **kwargs: [{"Summary": "Risk A"}],
        )
        client = MagicMock()
        client.get_fields.return_value = []
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda org_config: client)

        def _inner(*args, report=None, report_path=None, **kwargs):
            report.error = {"type": "InnerError", "message": "from run_import"}
            raise ValueError("outer")

        monkeypatch.setattr("jiramator.cli.run_import", _inner)
        report_path = tmp_path / "r.json"

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config", str(org_config_path),
                "--team-config", str(team_config_path),
                "--report", str(report_path),
                str(sheet_path),
            ],
        )

        assert result.exit_code == 1
        run = json.loads(report_path.read_text(encoding="utf-8"))["run"]
        assert run["error"] == {"type": "InnerError", "message": "from run_import"}


class TestUpdateCommand:
    def test_help_shows_expected_options(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["update", "--help"])

        assert result.exit_code == 0
        assert "--org-config" in result.output
        assert "--key-column" in result.output
        assert "--dry-run" in result.output
        assert "--report" in result.output

    def test_dry_run_uses_jira_field_metadata(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        tmp_path: Path,
    ) -> None:
        sheet_path = tmp_path / "update.csv"
        sheet_path.write_text("Key,Unknown Jira Field\nCA-1,value\n")
        rows = [{"Key": "CA-1", "Unknown Jira Field": "value"}]

        client = MagicMock()
        jira_fields = [{"id": "customfield_12345", "name": "Unknown Jira Field"}]
        client.get_fields.return_value = jira_fields
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda org_config: client)
        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: rows)

        captured: dict[str, object] = {}

        def fake_run_update(*args, **kwargs):
            captured["jira_fields"] = kwargs["jira_fields"]
            return MagicMock(preview=MagicMock(), updated=[], skipped=[], failed=[])

        monkeypatch.setattr("jiramator.cli.run_update", fake_run_update)
        monkeypatch.setattr("jiramator.cli.render_update_preview_report", lambda *args, **kwargs: "UPDATE PREVIEW")

        result = runner.invoke(
            cli,
            [
                "update",
                "--org-config",
                str(org_config_path),
                "--dry-run",
                str(sheet_path),
            ],
        )

        assert result.exit_code == 0
        assert "UPDATE PREVIEW" in result.output
        assert captured["jira_fields"] == jira_fields

    def test_live_run_writes_update_report(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        tmp_path: Path,
    ) -> None:
        sheet_path = tmp_path / "update.csv"
        sheet_path.write_text("Key,Platform\nCA-1,Calcs\n")
        report_path = tmp_path / "update-report.json"
        rows = [{"Key": "CA-1", "Platform": "Calcs"}]

        client = MagicMock()
        client.get_fields.return_value = []
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda org_config: client)
        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: rows)

        preview = MagicMock(
            row_results=[
                MagicMock(
                    row_number=1,
                    payload={"fields": {"customfield_14823": [{"value": "Calcs"}]}},
                )
            ],
        )
        result_obj = MagicMock(
            preview=preview,
            updated=[(1, "CA-1")],
            skipped=[],
            failed=[],
        )
        monkeypatch.setattr("jiramator.cli.run_update", lambda *args, **kwargs: result_obj)
        monkeypatch.setattr("jiramator.cli.render_update_preview_report", lambda *args, **kwargs: "UPDATE PREVIEW")
        monkeypatch.setattr("jiramator.cli.render_update_execution_report", lambda *args, **kwargs: "UPDATE EXECUTION")

        result = runner.invoke(
            cli,
            [
                "update",
                "--org-config",
                str(org_config_path),
                "--report",
                str(report_path),
                str(sheet_path),
            ],
        )

        assert result.exit_code == 0
        envelope = json.loads(report_path.read_text(encoding="utf-8"))
        run = envelope["run"]
        assert run["status"] == "success"
        assert run["counts"] == {"updated": 1, "skipped": 0, "failed": 0}
        assert run["issues"][0]["status"] == "updated"
        assert run["issues"][0]["jira_key"] == "CA-1"
        assert run["issues"][0]["fields"] == ["customfield_14823"]

    def test_live_run_redacts_credentials_in_update_report(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        tmp_path: Path,
    ) -> None:
        token = "update-secret-token-1234"
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", token)
        sheet_path = tmp_path / "update.csv"
        sheet_path.write_text("Key,Platform\nCA-1,Calcs\nCA-2,Calcs\n")
        report_path = tmp_path / "update-report.json"
        rows = [{"Key": "CA-1", "Platform": "Calcs"}, {"Key": "CA-2", "Platform": "Calcs"}]

        client = MagicMock()
        client.get_fields.return_value = []
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda org_config: client)
        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: rows)

        result_obj = MagicMock(
            preview=MagicMock(row_results=[]),
            updated=[],
            skipped=[(2, "CA-2", f"skipped with {token}")],
            failed=[(1, "CA-1", f"Jira said: authorization: basic dXNlcjp0b2s= and {token}")],
        )
        monkeypatch.setattr("jiramator.cli.run_update", lambda *args, **kwargs: result_obj)
        monkeypatch.setattr("jiramator.cli.render_update_preview_report", lambda *args, **kwargs: "UPDATE PREVIEW")
        monkeypatch.setattr("jiramator.cli.render_update_execution_report", lambda *args, **kwargs: "UPDATE EXECUTION")

        result = runner.invoke(
            cli,
            ["update", "--org-config", str(org_config_path), "--report", str(report_path), str(sheet_path)],
        )

        assert result.exit_code == 1
        raw = report_path.read_text(encoding="utf-8")
        assert token not in raw
        assert "dXNlcjp0b2s=" not in raw
        errors = {i["jira_key"]: i["error"] for i in json.loads(raw)["run"]["issues"]}
        assert errors["CA-1"] == "Jira said: authorization: basic *** and ***"
        assert errors["CA-2"] == "skipped with ***"

    def test_duplicate_keys_exit_before_jira_client(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        tmp_path: Path,
    ) -> None:
        sheet_path = tmp_path / "update.csv"
        sheet_path.write_text("Key,Platform\nCA-1,Calcs\nCA-1,Other\n")
        rows = [
            {"Key": "CA-1", "Platform": "Calcs"},
            {"Key": "CA-1", "Platform": "Other"},
        ]

        jira_client_ctor = MagicMock()
        monkeypatch.setattr("jiramator.cli.JiraClient", jira_client_ctor)
        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: rows)

        result = runner.invoke(
            cli,
            [
                "update",
                "--org-config",
                str(org_config_path),
                str(sheet_path),
            ],
        )

        assert result.exit_code == 1
        assert "Duplicate Jira keys found" in result.output
        assert "CA-1 appears on rows 1, 2" in result.output
        jira_client_ctor.assert_not_called()


# ---------------------------------------------------------------------------
# Import preflight (dry-run)
# ---------------------------------------------------------------------------


def _sc1_createmeta() -> dict[str, dict]:
    """Synthetic Risk createmeta mirroring the SC1 incident schema."""
    return {
        "summary": {"name": "Summary", "required": True, "hasDefaultValue": False, "schema": {"type": "string"}},
        "issuetype": {"name": "Issue Type", "required": True, "hasDefaultValue": False, "schema": {"type": "issuetype"}},
        "project": {"name": "Project", "required": True, "hasDefaultValue": False, "schema": {"type": "project"}},
        "fixVersions": {
            "name": "Fix versions",
            "required": True,
            "hasDefaultValue": False,
            "schema": {"type": "array", "items": "version"},
            "allowedValues": [{"id": "1", "name": "26.1.1"}],
        },
        "customfield_11941": {
            "name": "Repositories",
            "required": True,
            "hasDefaultValue": False,
            "schema": {"type": "string", "custom": "com.atlassian.jira.plugin.system.customfieldtypes:textarea"},
        },
    }


_SC1_REPOS = ["repo-alpha", "", "", "repo-delta", "repo-echo", "repo-foxtrot"]


def _write_sc1_sheet(tmp_path: Path, summaries: list[str] | None = None) -> Path:
    """Write the synthetic SC1 Risk sheet (optionally with custom summaries)."""
    summaries = summaries or [f"Synthetic risk {i}" for i in range(1, 7)]
    sheet_path = tmp_path / "risks.csv"
    lines = ["Summary,Repositories,Fix Version"]
    lines += [f"{summary},{repo}," for summary, repo in zip(summaries, _SC1_REPOS, strict=True)]
    sheet_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sheet_path


def _preflight_client(createmeta: dict[str, dict] | None = None) -> MagicMock:
    client = MagicMock()
    client.get_fields.return_value = []
    client.get_createmeta_issue_types.return_value = [{"id": "10100", "name": "Risk"}]
    client.get_createmeta_fields.return_value = (
        createmeta if createmeta is not None else _sc1_createmeta()
    )
    return client


def _invoke_dry_run(
    runner: CliRunner,
    org_config_path: Path,
    team_config_path: Path,
    sheet_path: Path,
    *extra: str,
):
    return runner.invoke(
        cli,
        [
            "import",
            "--org-config",
            str(org_config_path),
            "--team-config",
            str(team_config_path),
            "--dry-run",
            *extra,
            str(sheet_path),
        ],
    )


def _flat(output: str) -> str:
    """Collapse whitespace so Rich's 80-column wrapping can't split a phrase."""
    return " ".join(output.split())


class TestImportPreflightDryRun:
    def test_sc1_risk_sheet_reports_all_problems_exit_1(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        """SC1 replay: 6 rows, Fix Version empty everywhere, Repositories empty
        on rows 2-3 → all 8 problems listed in one run, exit 1, no writes."""
        sheet_path = tmp_path / "risks.csv"
        repos = ["repo-alpha", "", "", "repo-delta", "repo-echo", "repo-foxtrot"]
        lines = ["Summary,Repositories,Fix Version"]
        lines += [f"Synthetic risk {i},{repo}," for i, repo in enumerate(repos, start=1)]
        sheet_path.write_text("\n".join(lines) + "\n")

        mock_client = MagicMock()
        mock_client.get_fields.return_value = []
        mock_client.get_createmeta_issue_types.return_value = [{"id": "10100", "name": "Risk"}]
        mock_client.get_createmeta_fields.return_value = _sc1_createmeta()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=mock_client))

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                "--dry-run",
                str(sheet_path),
            ],
        )

        output = result.output
        assert result.exit_code == 1, output
        assert "6 of 6 rows have problems" in output
        assert "[Risk]" in output
        assert output.count("missing required field 'Fix versions' (fixVersions)") == 6
        assert output.count("(customfield_11941)") == 2
        assert output.count("missing required field") == 8

        # Rows 2 and 3 (and only they) carry the Repositories problem.
        blocks: dict[int, str] = {}
        for n in range(1, 7):
            start = output.index(f"Row {n} 'Synthetic risk {n}'")
            end = output.find("Row ", start + 1)
            blocks[n] = output[start:end if end != -1 else len(output)]
        for n in (2, 3):
            assert "(customfield_11941)" in blocks[n]
        for n in (1, 4, 5, 6):
            assert "(customfield_11941)" not in blocks[n]

        mock_client.create_issue.assert_not_called()
        mock_client.create_issues_bulk.assert_not_called()
        mock_client.find_issue_keys_by_summaries.assert_not_called()
        mock_client.find_user_account_id.assert_not_called()
        mock_client.get_createmeta_issue_types.assert_called_once()
        mock_client.get_createmeta_fields.assert_called_once()

    def test_required_reporter_prints_caveat_exit_0(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ):
        """D-06: a required reporter satisfied by a non-blank Reporter cell is a
        caveat, not a problem — dry-run passes and makes no user lookups."""
        sheet_path = tmp_path / "risks.csv"
        sheet_path.write_text("Summary,Reporter\nSynthetic risk 1,Synthetic Person\n")

        mock_client = MagicMock()
        mock_client.get_fields.return_value = []
        mock_client.get_createmeta_issue_types.return_value = [{"id": "10100", "name": "Risk"}]
        mock_client.get_createmeta_fields.return_value = {
            "summary": {"name": "Summary", "required": True, "schema": {"type": "string"}},
            "issuetype": {"name": "Issue Type", "required": True, "schema": {"type": "issuetype"}},
            "project": {"name": "Project", "required": True, "schema": {"type": "project"}},
            "reporter": {"name": "Reporter", "required": True, "schema": {"type": "user"}},
        }
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=mock_client))

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                "--dry-run",
                str(sheet_path),
            ],
        )

        output = " ".join(result.output.split())  # undo Rich's 80-column wrapping
        assert result.exit_code == 0, output
        assert "Schema validation passed" in output
        assert "not preflight-validated" in output
        assert "required Reporter (reporter) depends on live user lookup" in output
        mock_client.find_user_account_id.assert_not_called()

    def test_get_fields_failure_still_validates_and_exits_1(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        """PRE-04: get_fields fails but createmeta works → aliases-only warning
        AND the validation section; problems still exit 1."""
        client = _preflight_client()
        client.get_fields.side_effect = JiraApiError("Server Error", status_code=500)
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(runner, org_config_path, team_config_path, _write_sc1_sheet(tmp_path))

        output = _flat(result.output)
        assert result.exit_code == 1, output
        assert "Preview based on field_aliases only (could not reach Jira)" in output
        assert "Schema validation found problems" in output
        assert "6 of 6 rows have problems" in output

    def test_createmeta_connection_error_is_skipped_exit_0(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        client = _preflight_client()
        client.get_createmeta_issue_types.side_effect = requests.exceptions.ConnectionError("boom")
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(runner, org_config_path, team_config_path, _write_sc1_sheet(tmp_path))

        output = _flat(result.output)
        assert result.exit_code == 0, output
        assert "Schema validation skipped: could not fetch Jira create metadata" in output
        assert "✓" not in output
        assert output.count("Schema validation skipped") == 1

    def test_all_rows_pass_prints_passed_exit_0(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        createmeta = {k: v for k, v in _sc1_createmeta().items() if k != "fixVersions"}
        createmeta["customfield_11941"] = {**createmeta["customfield_11941"], "required": False}
        client = _preflight_client(createmeta)
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(runner, org_config_path, team_config_path, _write_sc1_sheet(tmp_path))

        output = _flat(result.output)
        assert result.exit_code == 0, output
        assert "✓ Schema validation passed: 6 row(s) checked" in output
        assert "rows have problems" not in output

    def test_preview_rows_does_not_cap_failing_rows(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        """D-11: every failing row is printed regardless of --preview-rows."""
        client = _preflight_client()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(
            runner, org_config_path, team_config_path, _write_sc1_sheet(tmp_path), "--preview-rows", "1"
        )

        assert result.exit_code == 1, result.output
        for n in range(1, 7):
            assert f"Row {n} 'Synthetic risk {n}' [Risk]:" in result.output

    def test_max_rows_limits_validated_rows(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        client = _preflight_client()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(
            runner, org_config_path, team_config_path, _write_sc1_sheet(tmp_path), "--max-rows", "2"
        )

        output = result.output
        assert result.exit_code == 1, output
        assert "2 of 2 rows have problems" in output
        assert "Row 1 'Synthetic risk 1'" in output
        assert "Row 2 'Synthetic risk 2'" in output
        assert "Row 3" not in output

    def test_resume_dry_run_skips_rows_already_created(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        """OQ-2: dry-run --resume validates exactly the rows a live resume would."""
        org_config, _ = load_org_config(org_config_path)
        team_config, _ = load_team_config(team_config_path)
        prior = RunReport(
            command=["jiramator", "import"],
            started_at="2026-01-01T00:00:00Z",
            ended_at="2026-01-01T00:01:00Z",
            team_config_path=str(team_config_path.resolve()),
            org_config_path=str(org_config_path.resolve()),
            team_name=team_config.team_name,
            resolved_config_hash=compute_resolved_hash(org_config, team_config, None, []),
            status="partial",
            counts={"created": 1, "skipped": 0, "failed": 0},
            issues=[
                IssueResult(
                    template_key=_row_template_key(1, "Synthetic risk 1"),
                    kind="imported",
                    status="created",
                    jira_key="CA-1",
                )
            ],
        )
        prior_path = tmp_path / "prior.json"
        write_report_atomic(prior, prior_path)

        client = _preflight_client()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(
            runner,
            org_config_path,
            team_config_path,
            _write_sc1_sheet(tmp_path),
            "--resume",
            str(prior_path),
        )

        output = result.output
        assert result.exit_code == 1, output
        assert "5 of 5 rows have problems" in output
        validation = output.split("Schema validation found problems", 1)[1]
        assert "Row 1 '" not in validation
        assert "Row 2 'Synthetic risk 2'" in validation

    def test_markup_in_summary_printed_literally(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        """T-02-08: Rich markup in cell text is printed literally, never parsed."""
        summaries = [f"Synthetic risk {i}" for i in range(1, 7)]
        summaries[0] = "Synthetic [bold]risk[/] 1"
        summaries[1] = "Synthetic risk [/] 2"  # an orphan close tag would raise MarkupError
        client = _preflight_client()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(
            runner, org_config_path, team_config_path, _write_sc1_sheet(tmp_path, summaries)
        )

        assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
        assert result.exit_code == 1, result.output
        assert "Row 1 'Synthetic [bold]risk[/] 1' [Risk]:" in result.output
        assert "Row 2 'Synthetic risk [/] 2' [Risk]:" in result.output
        assert "6 of 6 rows have problems" in result.output

    def test_non_ascii_summary_printed_verbatim(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        summaries = [f"Synthetic risk {i}" for i in range(1, 7)]
        summaries[0] = "Risque — évalué £"
        client = _preflight_client()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(
            runner, org_config_path, team_config_path, _write_sc1_sheet(tmp_path, summaries)
        )

        assert result.exit_code == 1, result.output
        assert "Row 1 'Risque — évalué £' [Risk]:" in result.output

    def test_zero_data_rows_exit_0_without_createmeta(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        sheet_path = tmp_path / "empty.csv"
        sheet_path.write_text("Summary,Repositories,Fix Version\n")
        client = _preflight_client()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(runner, org_config_path, team_config_path, sheet_path)

        assert result.exit_code == 0, result.output
        client.get_createmeta_issue_types.assert_not_called()
        client.get_createmeta_fields.assert_not_called()

    def test_build_failed_row_listed_alongside_schema_problems(
        self, runner, monkeypatch, org_config_path, team_config_path, tmp_path
    ):
        """D-08: a row that fails to build is part of the failing-rows report."""
        sheet_path = _write_sc1_sheet(tmp_path)
        with sheet_path.open("a", encoding="utf-8") as handle:
            handle.write(",repo-golf,\n")
        client = _preflight_client()
        monkeypatch.setattr("jiramator.cli.JiraClient", MagicMock(return_value=client))

        result = _invoke_dry_run(runner, org_config_path, team_config_path, sheet_path)

        output = _flat(result.output)
        assert result.exit_code == 1, output
        assert "Row 7 '<missing summary>':" in output
        assert "Row 7: required field 'summary' is missing or empty" in output
        assert "7 of 7 rows have problems" in output
