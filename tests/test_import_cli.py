"""CLI/import integration tests for spreadsheet-driven Jira issue import."""

from __future__ import annotations

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
