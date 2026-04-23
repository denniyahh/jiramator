"""Integration tests for spreadsheet import using real shipped configs."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from openpyxl import Workbook

from jiramator.config import load_org_config, load_team_config
from jiramator.importer import run_import
from jiramator.spreadsheet import read_spreadsheet

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ORG_CONFIG_PATH = _REPO_ROOT / "configs" / "org" / "marketaxess.yaml"
_TEAM_CONFIG_PATH = _REPO_ROOT / "configs" / "teams" / "calcs.yaml"


def _write_ca_risk_workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Risks"
    ws.append(
        [
            "Summary",
            "API Impact",
            "Code Complexity",
            "QA Testing",
            "Risk Impact",
            "Risk Description",
            "Risk Mitigation",
            "Plan for Risk Mitigation",
            "Overall Risk Value",
            "Tech Stack",
            "Repositories",
            "Object model changes",
            "Database Impact",
            "Requires Load Test",
            "Production Sanity Test with Release?",
            "Reporter",
        ]
    )
    ws.append(
        [
            "Integration Risk A",
            "No",
            "Medium",
            "Medium",
            "Medium",
            "Important risk details",
            "Low",
            "Mitigate via rollout checklist",
            "7",
            "Python, Jira",
            "github.com/example/repo",
            "No",
            "No",
            "No",
            "Yes",
            "Dennis Kim",
        ]
    )
    wb.save(path)


class TestImportIntegration:
    def test_ca_risk_xlsx_preview_and_live_import_use_real_configs(self, tmp_path: Path) -> None:
        org_config = load_org_config(_ORG_CONFIG_PATH)
        team_config = load_team_config(_TEAM_CONFIG_PATH)

        sheet_path = tmp_path / "ca-risk.xlsx"
        _write_ca_risk_workbook(sheet_path)

        rows = read_spreadsheet(sheet_path, sheet_name="Risks")
        assert rows == [
            {
                "Summary": "Integration Risk A",
                "API Impact": "No",
                "Code Complexity": "Medium",
                "QA Testing": "Medium",
                "Risk Impact": "Medium",
                "Risk Description": "Important risk details",
                "Risk Mitigation": "Low",
                "Plan for Risk Mitigation": "Mitigate via rollout checklist",
                "Overall Risk Value": "7",
                "Tech Stack": "Python, Jira",
                "Repositories": "github.com/example/repo",
                "Object model changes": "No",
                "Database Impact": "No",
                "Requires Load Test": "No",
                "Production Sanity Test with Release?": "Yes",
                "Reporter": "Dennis Kim",
            }
        ]

        preview_result = run_import(
            rows,
            org_config=org_config,
            team_config=team_config,
            jira_fields=None,
            client=None,
            dry_run=True,
        )

        assert preview_result.created == []
        assert preview_result.skipped == []
        assert preview_result.failed == []
        assert preview_result.preview.total_rows == 1
        assert preview_result.preview.successful_rows == 1
        assert preview_result.preview.failed_rows == 0
        assert preview_result.preview.auto_mapped_columns == {}
        assert preview_result.preview.skipped_columns == []
        assert preview_result.preview.mapped_columns == {
            "API Impact": "customfield_10273",
            "Code Complexity": "customfield_11901",
            "Database Impact": "customfield_11943",
            "Object model changes": "customfield_11942",
            "Overall Risk Value": "customfield_11905",
            "Plan for Risk Mitigation": "customfield_12001",
            "Production Sanity Test with Release?": "customfield_12153",
            "QA Testing": "customfield_11902",
            "Reporter": "reporter",
            "Repositories": "customfield_11941",
            "Requires Load Test": "customfield_11944",
            "Risk Description": "customfield_11823",
            "Risk Impact": "customfield_11904",
            "Risk Mitigation": "customfield_11903",
            "Summary": "summary",
            "Tech Stack": "customfield_11940",
        }

        row_result = preview_result.preview.row_results[0]
        assert row_result.success is True
        assert row_result.warnings == []
        assert row_result.resolved_columns["Reporter"].jira_field == "reporter"
        assert row_result.payload == {
            "fields": {
                "project": {"key": team_config.project_key},
                "summary": "Integration Risk A",
                "issuetype": {"name": "Risk"},
                "customfield_10273": [{"value": "No"}],
                "customfield_11901": {"value": "Medium"},
                "customfield_11902": {"value": "Medium"},
                "customfield_11904": {"value": "Medium"},
                "customfield_11823": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Important risk details"}],
                        }
                    ],
                },
                "customfield_11903": {"value": "Low"},
                "customfield_12001": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Mitigate via rollout checklist"}],
                        }
                    ],
                },
                "customfield_11905": 7,
                "customfield_11940": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Python, Jira"}],
                        }
                    ],
                },
                "customfield_11941": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "github.com/example/repo"}],
                        }
                    ],
                },
                "customfield_11942": {"value": "No"},
                "customfield_11943": {"value": "No"},
                "customfield_11944": {"value": "No"},
                "customfield_12153": {"value": "Yes"},
            }
        }
        assert "reporter" not in row_result.payload["fields"]

        client = MagicMock()
        client.find_issue_keys_by_summaries.return_value = {}
        client.find_user_account_id.return_value = "acct-123"
        client.create_issue.return_value = "CA-9999"

        live_result = run_import(
            rows,
            org_config=org_config,
            team_config=team_config,
            jira_fields=[],
            client=client,
            dry_run=False,
        )

        assert live_result.created == [(1, "Integration Risk A", "CA-9999")]
        assert live_result.skipped == []
        assert live_result.failed == []
        client.find_issue_keys_by_summaries.assert_called_once_with(team_config.project_key, ["Integration Risk A"])
        client.find_user_account_id.assert_called_once_with("Dennis Kim")
        client.create_issue.assert_called_once()

        created_payload = client.create_issue.call_args.args[0]
        assert created_payload["fields"]["project"] == {"key": team_config.project_key}
        assert created_payload["fields"]["reporter"] == {"accountId": "acct-123"}
