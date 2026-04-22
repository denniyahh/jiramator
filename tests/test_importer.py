"""Tests for spreadsheet row -> Jira payload import builder."""

from __future__ import annotations

from jiramator.config import BulkCreateConfig, OrgConfig, TeamConfig


def _org_config() -> OrgConfig:
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={
            "api_impact": "customfield_10273",
            "product_horizontals": "customfield_12747",
            "product_verticals": "customfield_12749",
            "platform": "customfield_14823",
        },
        bulk_create=BulkCreateConfig(
            field_aliases={
                "Summary": "summary",
                "Description": "description",
                "Issue Type": "issuetype",
                "Priority": "priority",
                "API Impact": "api_impact",
                "Product Horizontals": "product_horizontals",
                "Product Verticals": "product_verticals",
                "Platform": "platform",
                "Fix Versions": "fixVersions",
                "Labels": "labels",
            },
            field_types={
                "issuetype": "name_object",
                "priority": "name_object",
                "fixVersions": "name_object_array",
                "labels": "labels",
                "api_impact": "multi_select",
                "product_horizontals": "single_select",
                "product_verticals": "multi_select",
                "platform": "multi_select",
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


class TestBuildRowPayload:
    def test_builds_payload_from_row_and_defaults(self):
        from jiramator.importer import build_row_payload

        row = {
            "Summary": "Risk - calc discrepancy",
            "Description": "Reconcile VaR mismatch",
            "Priority": "High",
            "Product Horizontals": "Calcs",
            "Product Verticals": "US High Grade, Data",
            "Platform": "Calcs, Risk",
            "Fix Versions": "26.3.0",
            "Labels": "PI28, Risk",
        }

        result = build_row_payload(
            row,
            row_number=2,
            org_config=_org_config(),
            team_config=_team_config(),
        )

        assert result.success is True
        assert result.warnings == []
        assert result.payload == {
            "fields": {
                "project": {"key": "CA"},
                "summary": "Risk - calc discrepancy",
                "description": "Reconcile VaR mismatch",
                "priority": {"name": "High"},
                "issuetype": {"name": "Risk"},
                "customfield_10273": [{"value": "No"}],
                "customfield_12747": {"value": "Calcs"},
                "customfield_12749": [{"value": "US High Grade"}, {"value": "Data"}],
                "customfield_14823": [{"value": "Calcs"}, {"value": "Risk"}],
                "fixVersions": [{"name": "26.3.0"}],
                "labels": ["PI28", "Risk"],
            }
        }
        assert result.summary == "Risk - calc discrepancy"
        assert result.resolved_columns["Summary"].jira_field == "summary"
        assert result.resolved_columns["Product Horizontals"].jira_field == "customfield_12747"

    def test_unresolved_columns_are_skipped_with_warning(self):
        from jiramator.importer import build_row_payload

        row = {
            "Summary": "Risk - skipped field example",
            "Mystery Column": "???",
        }

        result = build_row_payload(
            row,
            row_number=7,
            org_config=_org_config(),
            team_config=_team_config(),
        )

        assert result.success is True
        assert result.payload == {
            "fields": {
                "project": {"key": "CA"},
                "summary": "Risk - skipped field example",
                "issuetype": {"name": "Risk"},
                "customfield_10273": [{"value": "No"}],
            }
        }
        assert result.warnings == ["Row 7: skipped unresolved column 'Mystery Column'"]

    def test_jira_metadata_can_auto_resolve_unknown_header(self):
        from jiramator.importer import build_row_payload

        row = {
            "Summary": "Risk - auto mapped",
            "Component/s": "API, UI",
        }
        jira_fields = [
            {"id": "components", "name": "Component/s"},
        ]

        result = build_row_payload(
            row,
            row_number=3,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=jira_fields,
        )

        assert result.success is True
        assert result.payload["fields"]["components"] == [{"name": "API"}, {"name": "UI"}]
        assert result.resolved_columns["Component/s"].resolution_source == "jira_exact"

    def test_jira_metadata_can_auto_resolve_custom_field_using_logical_type(self):
        from jiramator.importer import build_row_payload

        row = {
            "Summary": "Risk - auto mapped custom field",
            "Product Horizontals(Finance)": "Calcs",
        }
        jira_fields = [
            {"id": "customfield_12747", "name": "Product Horizontals(Finance)"},
        ]

        result = build_row_payload(
            row,
            row_number=4,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=jira_fields,
        )

        assert result.success is True
        assert result.payload["fields"]["customfield_12747"] == {"value": "Calcs"}
        assert result.resolved_columns["Product Horizontals(Finance)"].resolution_source == "jira_exact"

    def test_missing_summary_is_a_row_error(self):
        from jiramator.importer import build_row_payload

        row = {
            "Description": "No summary here",
        }

        result = build_row_payload(
            row,
            row_number=5,
            org_config=_org_config(),
            team_config=_team_config(),
        )

        assert result.success is False
        assert result.payload is None
        assert result.summary == "<missing summary>"
        assert result.error == "Row 5: required field 'summary' is missing or empty"

    def test_empty_values_are_omitted_without_warning(self):
        from jiramator.importer import build_row_payload

        row = {
            "Summary": "Risk - sparse row",
            "Description": "",
            "Labels": "",
            "Platform": None,
        }

        result = build_row_payload(
            row,
            row_number=8,
            org_config=_org_config(),
            team_config=_team_config(),
        )

        assert result.success is True
        assert result.payload == {
            "fields": {
                "project": {"key": "CA"},
                "summary": "Risk - sparse row",
                "issuetype": {"name": "Risk"},
                "customfield_10273": [{"value": "No"}],
            }
        }
        assert result.warnings == []

    def test_auto_lookup_can_be_disabled_even_when_jira_fields_are_available(self):
        from jiramator.importer import build_row_payload

        org_config = _org_config()
        org_config.bulk_create.auto_lookup_unknown_fields = False
        row = {
            "Summary": "Risk - no auto lookup",
            "Component/s": "API, UI",
        }
        jira_fields = [
            {"id": "components", "name": "Component/s"},
        ]

        result = build_row_payload(
            row,
            row_number=9,
            org_config=org_config,
            team_config=_team_config(),
            jira_fields=jira_fields,
        )

        assert result.success is True
        assert result.payload == {
            "fields": {
                "project": {"key": "CA"},
                "summary": "Risk - no auto lookup",
                "issuetype": {"name": "Risk"},
                "customfield_10273": [{"value": "No"}],
            }
        }
        assert result.warnings == ["Row 9: skipped unresolved column 'Component/s'"]

    def test_assignee_scalar_is_skipped_with_warning(self):
        from jiramator.importer import build_row_payload

        row = {
            "Summary": "Risk - unsupported assignee",
            "Assignee": "dennis@example.com",
        }
        jira_fields = [
            {"id": "assignee", "name": "Assignee"},
        ]

        result = build_row_payload(
            row,
            row_number=10,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=jira_fields,
        )

        assert result.success is True
        assert result.payload == {
            "fields": {
                "project": {"key": "CA"},
                "summary": "Risk - unsupported assignee",
                "issuetype": {"name": "Risk"},
                "customfield_10273": [{"value": "No"}],
            }
        }
        assert result.warnings == [
            "Row 10: skipped unsupported assignee value for column 'Assignee'; expected a Jira user object"
        ]


class TestBuildPreviewReport:
    def test_summarizes_mapped_automapped_and_skipped_columns(self):
        from jiramator.importer import build_preview_report

        rows = [
            {"Summary": "Risk 1", "Mystery Column": "x", "Component/s": "API"},
            {"Summary": "Risk 2", "Component/s": "UI"},
        ]
        jira_fields = [{"id": "components", "name": "Component/s"}]

        report = build_preview_report(
            rows,
            org_config=_org_config(),
            team_config=_team_config(),
            jira_fields=jira_fields,
        )

        assert report.total_rows == 2
        assert report.successful_rows == 2
        assert report.failed_rows == 0
        assert report.mapped_columns == {"Summary": "summary"}
        assert report.auto_mapped_columns == {"Component/s": "components"}
        assert report.skipped_columns == ["Mystery Column"]
        assert report.row_results[0].warnings == ["Row 1: skipped unresolved column 'Mystery Column'"]
