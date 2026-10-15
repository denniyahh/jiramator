"""Unit tests for import preflight validation against Jira createmeta."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import requests
from rich.console import Console

from jiramator.config import (
    BulkCreateConfig,
    OrgConfig,
    TeamConfig,
    load_org_config,
    load_team_config,
)
from jiramator.import_preflight import (
    PreflightResult,
    PreflightRow,
    render_preflight_report,
    run_preflight,
)
from jiramator.importer import _row_template_key, build_preview_report, build_row_payload
from jiramator.jira_client import JiraApiError

_CONFIGS_DIR = Path(__file__).parent.parent / "configs"
_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_TEXTAREA = "com.atlassian.jira.plugin.system.customfieldtypes:textarea"

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _example_configs() -> tuple[OrgConfig, TeamConfig]:
    org_config, _ = load_org_config(_CONFIGS_DIR / "org.example" / "example.yaml")
    team_config, _ = load_team_config(_FIXTURES_DIR / "teams" / "calcs.yaml")
    return org_config, team_config


def _sc1_rows() -> list[dict[str, Any]]:
    """Synthetic SC1 sheet: Fix Version empty everywhere, Repositories empty on rows 2-3."""
    repos = ["repo-alpha", "", "", "repo-delta", "repo-echo", "repo-foxtrot"]
    return [
        {"Summary": f"Synthetic risk {i}", "Repositories": repo, "Fix Version": ""}
        for i, repo in enumerate(repos, start=1)
    ]


def _sc1_createmeta() -> dict[str, dict[str, Any]]:
    """Synthetic Risk createmeta mirroring the SC1 incident schema."""
    return {
        "summary": {"name": "Summary", "required": True, "hasDefaultValue": False, "schema": {"type": "string"}},
        "issuetype": {
            "name": "Issue Type",
            "required": True,
            "hasDefaultValue": False,
            "schema": {"type": "issuetype"},
            "allowedValues": [{"id": "10100", "name": "Risk"}],
        },
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
            "schema": {"type": "string", "custom": _TEXTAREA},
        },
    }


def _problem_org_config() -> OrgConfig:
    """Small synthetic org config exercising select/ADF/off-screen paths."""
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={
            "notes": "customfield_20000",
            "risk_impact": "customfield_11904",
            "repositories": "customfield_11941",
            "extra": "customfield_99999",
        },
        bulk_create=BulkCreateConfig(
            field_aliases={
                "Summary": "summary",
                "Issue Type": "issuetype",
                "Fix Version": "fixVersions",
                "Notes": "notes",
                "Risk Impact": "risk_impact",
                "Repositories": "repositories",
                "Extra": "extra",
            },
            field_types={
                "issuetype": "name_object",
                "risk_impact": "single_select",
                "repositories": "adf_text",
            },
            defaults={"issuetype": "Risk"},
        ),
        sprints={
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    )


def _problem_createmeta() -> dict[str, dict[str, Any]]:
    return {
        "summary": {"name": "Summary", "required": True, "schema": {"type": "string"}},
        "issuetype": {"name": "Issue Type", "required": True, "schema": {"type": "issuetype"}},
        "fixVersions": {
            "name": "Fix versions",
            "required": False,
            "schema": {"type": "array", "items": "version"},
            "allowedValues": [{"id": "1", "name": "26.1.1"}],
        },
        "customfield_11904": {
            "name": "Risk Impact",
            "required": False,
            "schema": {"type": "option"},
            "allowedValues": [{"id": "11", "value": "Low"}, {"id": "12", "value": "High"}],
        },
        "customfield_20000": {
            "name": "Notes",
            "required": False,
            "schema": {"type": "string", "custom": _TEXTAREA},
        },
        "customfield_11941": {
            "name": "Repositories",
            "required": True,
            "schema": {"type": "string", "custom": _TEXTAREA},
        },
    }


def _client(
    issue_types: list[dict[str, Any]] | None = None,
    fields: dict[str, dict[str, Any]] | None = None,
) -> MagicMock:
    client = MagicMock()
    client.get_createmeta_issue_types.return_value = (
        issue_types if issue_types is not None else [{"id": "10100", "name": "Risk"}]
    )
    client.get_createmeta_fields.return_value = fields if fields is not None else {}
    return client


def _preflight(
    client: MagicMock,
    rows: list[dict[str, Any]],
    org_config: OrgConfig,
    team_config: TeamConfig | None = None,
    **kwargs: Any,
) -> PreflightResult:
    team_config = team_config or TeamConfig(project_key="CA", team_name="Calcs")
    preview = build_preview_report(rows, org_config=org_config, team_config=team_config)
    return run_preflight(
        client,
        project_key=team_config.project_key,
        row_results=preview.row_results,
        source_rows=rows,
        org_config=org_config,
        **kwargs,
    )


def _export(markup: str) -> str:
    console = Console(record=True, width=200)
    console.print(markup)
    return console.export_text()


# ---------------------------------------------------------------------------
# Issue types
# ---------------------------------------------------------------------------


class TestPreflightIssueTypes:
    def test_unknown_issue_type_is_row_problem_with_available_list(self):
        rows = [{"Summary": "Synthetic A", "Issue Type": "Bogus"}]
        client = _client(issue_types=[{"id": "1", "name": "Risk"}, {"id": "2", "name": "Bug"}])

        result = _preflight(client, rows, _problem_org_config())

        assert result.status == "problems"
        assert result.rows[0].problems == [
            "Issue type 'Bogus' is not available for creation in project CA (available: Bug, Risk)"
        ]
        client.get_createmeta_fields.assert_not_called()

    def test_issue_types_differing_by_case_share_one_schema_fetch(self):
        rows = [
            {"Summary": "Synthetic A", "Issue Type": "Risk", "Repositories": "r"},
            {"Summary": "Synthetic B", "Issue Type": "risk", "Repositories": "r"},
        ]
        client = _client(fields=_problem_createmeta())

        result = _preflight(client, rows, _problem_org_config())

        assert result.status == "passed"
        assert result.checked_rows == 2
        client.get_createmeta_issue_types.assert_called_once_with("CA")
        client.get_createmeta_fields.assert_called_once_with("CA", "10100")

    def test_issuetype_case_mismatch_with_allowed_values_not_reported(self):
        meta = _problem_createmeta()
        meta["issuetype"]["allowedValues"] = [{"id": "10100", "name": "Risk"}]
        rows = [{"Summary": "Synthetic A", "Issue Type": "risk", "Repositories": "r"}]

        result = _preflight(_client(fields=meta), rows, _problem_org_config())

        assert result.status == "passed"

    def test_missing_issue_type_is_row_problem(self):
        org_config = _problem_org_config()
        org_config.bulk_create.defaults.clear()
        rows = [{"Summary": "Synthetic A"}]

        result = _preflight(_client(), rows, org_config)

        assert result.status == "problems"
        assert result.rows[0].issue_type is None
        assert "no issue type" in result.rows[0].problems[0]


# ---------------------------------------------------------------------------
# Problems (PRE-01 / PRE-02 / D-07 / D-10)
# ---------------------------------------------------------------------------


class TestPreflightProblems:
    def test_sc1_rows_report_eight_problems_with_column_attribution(self):
        org_config, team_config = _example_configs()
        client = _client(fields=_sc1_createmeta())

        result = _preflight(client, _sc1_rows(), org_config, team_config)

        assert result.status == "problems"
        assert [row.row_number for row in result.problem_rows] == [1, 2, 3, 4, 5, 6]
        assert sum(len(row.problems) for row in result.rows) == 8
        assert result.considered_rows == 6
        assert "— no value in column(s)" in result.rows[0].problems[0]
        assert "'Fix Version'" in result.rows[0].problems[0]
        assert any("(customfield_11941)" in p for p in result.rows[1].problems)
        assert not any("(customfield_11941)" in p for p in result.rows[0].problems)

    def test_required_field_without_column_says_no_column_mapped(self):
        meta = _problem_createmeta()
        meta["customfield_55555"] = {"name": "Unmapped", "required": True}
        rows = [{"Summary": "Synthetic A", "Repositories": "r"}]

        result = _preflight(_client(fields=meta), rows, _problem_org_config())

        assert result.rows[0].problems == [
            "missing required field 'Unmapped' (customfield_55555) — no spreadsheet column mapped to this field"
        ]

    def test_select_adf_and_fix_version_problems_reported_together(self):
        rows = [
            {
                "Summary": "Synthetic A",
                "Repositories": "r",
                "Risk Impact": "Medium",
                "Notes": "plain text",
                "Fix Version": "26.4.1",
            }
        ]

        result = _preflight(_client(fields=_problem_createmeta()), rows, _problem_org_config())

        problems = result.rows[0].problems
        assert result.status == "problems"
        assert len(problems) == 3
        assert any(
            "'Risk Impact' (customfield_11904)" in p and "not one of the allowed options" in p
            and p.endswith(" — from column 'Risk Impact'")
            for p in problems
        )
        assert any(
            "'Notes' (customfield_20000) requires Atlassian Document Format" in p
            and p.endswith(" — from column 'Notes'")
            for p in problems
        )
        assert any(
            "(fixVersions)" in p and "26.4.1" in p and p.endswith(" — from column 'Fix Version'")
            for p in problems
        )

    def test_off_screen_field_reported_with_column_and_issue_type(self):
        rows = [{"Summary": "Synthetic A", "Repositories": "r", "Extra": "x"}]

        result = _preflight(_client(fields=_problem_createmeta()), rows, _problem_org_config())

        assert result.rows[0].problems == [
            "customfield_99999 is mapped from column 'Extra' but is not on the create screen for Risk"
        ]

    def test_whitespace_only_required_textarea_counts_as_missing(self):
        rows = [{"Summary": "Synthetic A", "Repositories": "   "}]

        result = _preflight(_client(fields=_problem_createmeta()), rows, _problem_org_config())

        assert len(result.rows[0].problems) == 1
        assert "missing required field 'Repositories' (customfield_11941)" in result.rows[0].problems[0]

    def test_empty_select_cell_is_only_subject_to_required_check(self):
        rows = [{"Summary": "Synthetic A", "Repositories": "r", "Risk Impact": ""}]

        result = _preflight(_client(fields=_problem_createmeta()), rows, _problem_org_config())

        assert result.status == "passed"

    def test_identical_rows_reported_separately_in_row_order(self):
        rows = [
            {"Summary": "Synthetic dup", "Risk Impact": "Medium", "Repositories": "r"},
            {"Summary": "Synthetic dup", "Risk Impact": "Medium", "Repositories": "r"},
        ]

        result = _preflight(_client(fields=_problem_createmeta()), rows, _problem_org_config())

        assert [row.row_number for row in result.problem_rows] == [1, 2]
        assert result.rows[0].problems == result.rows[1].problems

    def test_resume_skipped_rows_not_validated_or_counted(self):
        rows = [
            {"Summary": "Synthetic A", "Risk Impact": "Medium", "Repositories": "r"},
            {"Summary": "Synthetic B", "Repositories": "r"},
        ]

        result = _preflight(
            _client(fields=_problem_createmeta()),
            rows,
            _problem_org_config(),
            skip_template_keys=frozenset({_row_template_key(1, "Synthetic A")}),
            template_key_fn=_row_template_key,
        )

        assert result.status == "passed"
        assert result.considered_rows == 1
        assert result.checked_rows == 1


# ---------------------------------------------------------------------------
# Availability (D-02 / OQ-5)
# ---------------------------------------------------------------------------


class TestPreflightAvailability:
    def test_issue_type_list_request_exception_is_unavailable(self):
        client = _client()
        client.get_createmeta_issue_types.side_effect = requests.exceptions.ConnectionError("boom")
        rows = [{"Summary": "Synthetic A"}]

        result = _preflight(client, rows, _problem_org_config())

        assert result.status == "unavailable"
        assert "boom" in (result.reason or "")
        assert result.rows == []

    def test_second_type_field_fetch_failure_is_unavailable(self):
        client = _client(issue_types=[{"id": "1", "name": "Risk"}, {"id": "2", "name": "Bug"}])
        client.get_createmeta_fields.side_effect = [
            _problem_createmeta(),
            JiraApiError("Forbidden", status_code=403),
        ]
        rows = [
            {"Summary": "Synthetic A", "Issue Type": "Risk", "Repositories": "r"},
            {"Summary": "Synthetic B", "Issue Type": "Bug"},
        ]

        result = _preflight(client, rows, _problem_org_config())

        assert result.status == "unavailable"
        assert result.rows == []

    def test_no_rows_to_check_makes_no_client_calls(self):
        client = _client()
        rows = [{"Summary": ""}, {"Notes": "no summary"}]

        result = _preflight(client, rows, _problem_org_config())

        # Build failures are still reported (D-08), without any Jira call.
        assert result.status == "problems"
        assert result.checked_rows == 0
        assert client.mock_calls == []


# ---------------------------------------------------------------------------
# Rendering (D-09)
# ---------------------------------------------------------------------------


def _problem_result(summary: str, issue_type: str | None = "Risk") -> PreflightResult:
    return PreflightResult(
        status="problems",
        reason=None,
        rows=[PreflightRow(row_number=1, summary=summary, issue_type=issue_type, problems=["bad [x] thing"])],
        checked_rows=1,
        considered_rows=2,
    )


class TestPreflightRender:
    def test_lower_case_issue_type_printed_literally(self):
        text = _export(render_preflight_report(_problem_result("Synthetic A", "risk")))

        assert "Row 1 'Synthetic A' [risk]:" in text
        assert "bad [x] thing" in text
        assert "1 of 2 rows have problems" in text

    def test_markup_in_summary_printed_literally(self):
        text = _export(render_preflight_report(_problem_result("Synthetic [bold]risk[/] 1")))

        assert "Synthetic [bold]risk[/] 1" in text

    def test_non_ascii_summary_printed_verbatim(self):
        text = _export(render_preflight_report(_problem_result("Risque — évalué £")))

        assert "Risque — évalué £" in text

    def test_unavailable_says_skipped_without_check_mark(self):
        result = PreflightResult(
            status="unavailable", reason="HTTP 503 [oops]", rows=[], checked_rows=0, considered_rows=3
        )

        text = _export(render_preflight_report(result))

        assert "Schema validation skipped" in text
        assert "HTTP 503 [oops]" in text
        assert "✓" not in text

    def test_passed_shows_checked_row_count(self):
        result = PreflightResult(status="passed", reason=None, rows=[], checked_rows=4, considered_rows=4)

        text = _export(render_preflight_report(result))

        assert "✓ Schema validation passed: 4 row(s) checked" in text


    def test_row_without_issue_type_omits_bracket(self):
        text = _export(render_preflight_report(_problem_result("Synthetic A", None)))

        assert "Row 1 'Synthetic A':" in text


# ---------------------------------------------------------------------------
# Deferred required fields (D-06) and deferred off-screen columns (D-10)
# ---------------------------------------------------------------------------


def _deferred_org_config() -> OrgConfig:
    """Synthetic org config mapping the import-deferred fields to columns."""
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={"sprint_field": "customfield_10021"},
        bulk_create=BulkCreateConfig(
            field_aliases={
                "Summary": "summary",
                "Issue Type": "issuetype",
                "Reporter": "reporter",
                "Assignee": "assignee",
                "Parent": "parent",
                "Sprint": "sprint_field",
            },
            field_types={"issuetype": "name_object"},
            defaults={"issuetype": "Risk"},
        ),
        sprints={
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    )


def _deferred_createmeta(**required: dict[str, Any]) -> dict[str, dict[str, Any]]:
    meta: dict[str, dict[str, Any]] = {
        "summary": {"name": "Summary", "required": True, "schema": {"type": "string"}},
        "issuetype": {"name": "Issue Type", "required": True, "schema": {"type": "issuetype"}},
        "project": {"name": "Project", "required": True, "schema": {"type": "project"}},
    }
    meta.update(required)
    return meta


_REQUIRED_REPORTER = {"name": "Reporter", "required": True, "schema": {"type": "user"}}
_REQUIRED_PARENT = {"name": "Parent", "required": True, "schema": {"type": "issuelink"}}
_REQUIRED_SPRINT = {"name": "Sprint", "required": True, "schema": {"type": "array"}}


def _deferred_preflight(client: MagicMock, rows: list[dict[str, Any]]) -> PreflightResult:
    return _preflight(
        client,
        rows,
        _deferred_org_config(),
        deferred_fields=frozenset({"reporter", "assignee", "parent"}),
        deferred_logical_fields=frozenset({"sprint_field"}),
    )


class TestPreflightDeferred:
    def test_required_reporter_with_value_is_caveat_not_problem(self):
        client = _client(fields=_deferred_createmeta(reporter=_REQUIRED_REPORTER))
        rows = [{"Summary": "Synthetic A", "Reporter": "Synthetic User"}]

        result = _deferred_preflight(client, rows)

        assert result.status == "passed"
        assert result.problem_rows == []
        assert result.rows[0].caveats == [
            "required Reporter (reporter) depends on live user lookup — not preflight-validated"
        ]
        client.find_user_account_id.assert_not_called()
        client.find_issue_keys_by_summaries.assert_not_called()
        client.get_board_sprints.assert_not_called()

    def test_whitespace_only_reporter_is_missing_required(self):
        client = _client(fields=_deferred_createmeta(reporter=_REQUIRED_REPORTER))
        rows = [{"Summary": "Synthetic A", "Reporter": "   "}]

        result = _deferred_preflight(client, rows)

        assert result.status == "problems"
        assert result.rows[0].caveats == []
        assert any(
            "missing required field 'Reporter' (reporter)" in p for p in result.rows[0].problems
        )

    def test_subtask_parent_column_present_is_caveat_only(self):
        client = _client(
            issue_types=[{"id": "5", "name": "Sub-task"}],
            fields=_deferred_createmeta(parent=_REQUIRED_PARENT),
        )
        rows = [{"Summary": "Synthetic A", "Issue Type": "Sub-task", "Parent": "CA-1"}]

        result = _deferred_preflight(client, rows)

        assert result.status == "passed"
        assert result.rows[0].problems == []
        assert result.rows[0].caveats == [
            "required Parent (parent) depends on live parent lookup — not preflight-validated"
        ]
        client.find_issue_keys_by_summaries.assert_not_called()

    def test_subtask_parent_column_absent_is_missing_required(self):
        client = _client(
            issue_types=[{"id": "5", "name": "Sub-task"}],
            fields=_deferred_createmeta(parent=_REQUIRED_PARENT),
        )
        rows = [{"Summary": "Synthetic A", "Issue Type": "Sub-task"}]

        result = _deferred_preflight(client, rows)

        assert result.status == "problems"
        assert any(
            "missing required field 'Parent' (parent)" in p for p in result.rows[0].problems
        )

    def test_required_sprint_with_value_says_sprint_lookup(self):
        client = _client(fields=_deferred_createmeta(customfield_10021=_REQUIRED_SPRINT))
        rows = [{"Summary": "Synthetic A", "Sprint": "PI-1 Sprint 1"}]

        result = _deferred_preflight(client, rows)

        assert result.status == "passed"
        assert result.rows[0].caveats == [
            "required Sprint (customfield_10021) depends on live sprint lookup — "
            "not preflight-validated"
        ]

    def test_non_string_deferred_cell_is_missing_required(self):
        # run_import only resolves str cells, so a non-str cell is never "present".
        client = _client(fields=_deferred_createmeta(customfield_10021=_REQUIRED_SPRINT))
        rows = [{"Summary": "Synthetic A", "Sprint": 5}]

        result = _deferred_preflight(client, rows)

        assert result.status == "problems"
        assert result.rows[0].caveats == []
        assert any(
            "missing required field 'Sprint' (customfield_10021)" in p
            for p in result.rows[0].problems
        )

    def test_reporter_column_not_on_create_screen_is_off_screen_problem(self):
        client = _client(fields=_deferred_createmeta())
        rows = [{"Summary": "Synthetic A", "Reporter": "Synthetic User"}]

        result = _deferred_preflight(client, rows)

        assert result.status == "problems"
        assert result.rows[0].problems == [
            "reporter is mapped from column 'Reporter' but is not on the create screen for Risk"
        ]
        assert result.rows[0].caveats == []

    def test_caveat_only_rows_never_counted_as_problems(self):
        client = _client(fields=_deferred_createmeta(reporter=_REQUIRED_REPORTER))
        rows = [
            {"Summary": "Synthetic A", "Reporter": "Synthetic User"},
            {"Summary": "Synthetic B", "Reporter": ""},
        ]

        result = _deferred_preflight(client, rows)
        text = _export(render_preflight_report(result))

        assert result.status == "problems"
        assert [row.row_number for row in result.problem_rows] == [2]
        assert "1 of 2 rows have problems" in text
        assert "Not preflight-validated:" in text
        caveat_section = text.split("Not preflight-validated:", 1)[1]
        assert "Row 1 'Synthetic A' [Risk]:" in caveat_section
        assert "not preflight-validated" in caveat_section

    def test_passed_render_lists_caveats_after_check_mark(self):
        client = _client(fields=_deferred_createmeta(reporter=_REQUIRED_REPORTER))
        rows = [{"Summary": "Synthetic [bold]A[/]", "Reporter": "Synthetic User"}]

        text = _export(render_preflight_report(_deferred_preflight(client, rows)))

        assert "✓ Schema validation passed" in text
        assert "Not preflight-validated:" in text
        assert "Row 1 'Synthetic [bold]A[/]' [Risk]:" in text
        assert "rows have problems" not in text


# ---------------------------------------------------------------------------
# Coercion failures (OQ-4) and build-failed rows in the report (D-08)
# ---------------------------------------------------------------------------


class TestRowBuildCoercionErrors:
    def test_non_numeric_number_cell_is_row_build_error(self):
        org_config, team_config = _example_configs()

        result = build_row_payload(
            {"Summary": "Synthetic A", "Overall Risk Value": "abc"},
            row_number=2,
            org_config=org_config,
            team_config=team_config,
        )

        assert result.success is False
        assert result.payload is None
        assert result.summary == "Synthetic A"
        assert "Row 2: column 'Overall Risk Value': could not convert value 'abc'" in (
            result.error or ""
        )

    def test_other_rows_still_build_and_preview_does_not_raise(self):
        org_config, team_config = _example_configs()
        rows = [
            {"Summary": "Synthetic A", "Overall Risk Value": "3"},
            {"Summary": "Synthetic B", "Overall Risk Value": "lots"},
            {"Summary": "Synthetic C"},
        ]

        preview = build_preview_report(rows, org_config=org_config, team_config=team_config)

        assert [r.success for r in preview.row_results] == [True, False, True]
        assert preview.failed_rows == 1
        assert preview.row_results[0].payload["fields"]["customfield_11905"] == 3

    def test_coercion_error_without_summary_uses_placeholder(self):
        org_config, team_config = _example_configs()

        result = build_row_payload(
            {"Overall Risk Value": "n/a"},
            row_number=1,
            org_config=org_config,
            team_config=team_config,
        )

        assert result.success is False
        assert result.summary == "<missing summary>"
        assert "could not convert value 'n/a'" in (result.error or "")


class TestPreflightBuildFailures:
    def test_build_failed_row_is_listed_with_its_error(self):
        client = _client(fields=_problem_createmeta())
        rows = [
            {"Summary": "Synthetic A", "Repositories": "r"},
            {"Summary": ""},
        ]

        result = _preflight(client, rows, _problem_org_config())

        assert result.status == "problems"
        assert result.considered_rows == 2
        assert result.checked_rows == 1
        assert [row.row_number for row in result.rows] == [1, 2]
        failed = result.rows[1]
        assert failed.issue_type is None
        assert failed.problems == ["Row 2: required field 'summary' is missing or empty"]

    def test_build_failed_rows_merged_in_row_order(self):
        client = _client(fields=_problem_createmeta())
        rows = [
            {"Summary": ""},
            {"Summary": "Synthetic B", "Repositories": "r"},
            {"Summary": ""},
        ]

        result = _preflight(client, rows, _problem_org_config())

        assert [row.row_number for row in result.rows] == [1, 2, 3]
        assert [row.row_number for row in result.problem_rows] == [1, 3]

    def test_resume_skipped_build_failed_row_not_listed(self):
        client = _client(fields=_problem_createmeta())
        rows = [
            {"Summary": ""},
            {"Summary": "Synthetic B", "Repositories": "r"},
        ]

        result = _preflight(
            client,
            rows,
            _problem_org_config(),
            skip_template_keys=frozenset({_row_template_key(1, "<missing summary>")}),
            template_key_fn=_row_template_key,
        )

        assert result.status == "passed"
        assert result.considered_rows == 1
        assert [row.row_number for row in result.rows] == [2]

    def test_unavailable_drops_build_failed_rows(self):
        client = _client()
        client.get_createmeta_issue_types.side_effect = requests.exceptions.ConnectionError("down")
        rows = [{"Summary": "Synthetic A"}, {"Summary": ""}]

        result = _preflight(client, rows, _problem_org_config())

        assert result.status == "unavailable"
        assert result.rows == []

    def test_only_build_failed_rows_make_no_client_calls(self):
        client = _client()
        rows = [{"Summary": ""}]

        result = _preflight(client, rows, _problem_org_config())

        assert result.status == "problems"
        assert [row.row_number for row in result.problem_rows] == [1]
        assert client.mock_calls == []

    def test_build_failed_row_header_has_no_bracket(self):
        client = _client()
        rows = [{"Summary": ""}]

        text = _export(render_preflight_report(_preflight(client, rows, _problem_org_config())))

        assert "Row 1 '<missing summary>':" in text
        assert "required field 'summary' is missing or empty" in text
        assert "1 of 1 rows have problems" in text
