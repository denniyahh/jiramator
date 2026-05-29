"""CLI/import integration tests for spreadsheet-driven Jira issue import."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from jiramator.cli import cli
from jiramator.jira_client import JiraApiError


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
        sheet_path = tmp_path / "import.csv"
        sheet_path.write_text("Summary,API Impact\nRisk A,No\n")

        fake_report = MagicMock()
        fake_report.total_rows = 1
        fake_report.successful_rows = 1
        fake_report.failed_rows = 0
        fake_report.row_results = []

        monkeypatch.setattr("jiramator.cli.read_spreadsheet", lambda *args, **kwargs: [{"Summary": "Risk A", "API Impact": "No"}])
        monkeypatch.setattr("jiramator.cli.build_preview_report", lambda *args, **kwargs: fake_report)
        monkeypatch.setattr("jiramator.cli.render_preview_report", lambda *args, **kwargs: "PREVIEW REPORT")

        jira_client_ctor = MagicMock()
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
        jira_client_ctor.assert_not_called()

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
        monkeypatch.setattr("jiramator.cli.build_preview_report", lambda *args, **kwargs: preview_report)
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
