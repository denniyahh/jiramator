"""Tests for spreadsheet row -> Jira update payload builder."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from jiramator.config import BulkCreateConfig, OrgConfig
from jiramator.updater import (
    RowUpdateResult,
    UpdateRunResult,
    build_row_update_payload,
    build_update_preview_report,
    render_update_execution_report,
    render_update_preview_report,
    run_update,
    validate_unique_issue_keys,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _org_config() -> OrgConfig:
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={
            "product_horizontals": "customfield_12747",
            "product_verticals": "customfield_12749",
            "platform": "customfield_14823",
        },
        bulk_create=BulkCreateConfig(
            field_aliases={
                "Platform": "platform",
                "Horizontal": "product_horizontals",
                "Vertical": "product_verticals",
            },
            field_types={
                "platform": "multi_select",
                "product_horizontals": "single_select",
                "product_verticals": "multi_select",
                "risk_score": "number",
            },
            defaults={"issuetype": "Risk"},  # must NOT be applied during updates
        ),
        sprints={
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    )


# ---------------------------------------------------------------------------
# build_row_update_payload
# ---------------------------------------------------------------------------


class TestBuildRowUpdatePayload:
    def test_builds_update_payload_from_row(self):
        row = {
            "Key": "CA-4646",
            "Platform": "Calcs",
            "Horizontal": "Calcs",
            "Vertical": "US High Grade, Data",
        }
        result = build_row_update_payload(
            row, row_number=2, key_column="Key", org_config=_org_config()
        )

        assert result.success is True
        assert result.issue_key == "CA-4646"
        assert result.payload is not None
        fields = result.payload["fields"]
        assert fields["customfield_14823"] == [{"value": "Calcs"}]
        assert fields["customfield_12747"] == {"value": "Calcs"}
        assert fields["customfield_12749"] == [{"value": "US High Grade"}, {"value": "Data"}]

    def test_does_not_apply_defaults(self):
        """bulk_create.defaults must not be injected into update payloads."""
        row = {"Key": "CA-1", "Platform": "Calcs"}
        result = build_row_update_payload(
            row, row_number=1, key_column="Key", org_config=_org_config()
        )

        assert result.success is True
        assert result.payload is not None
        # issuetype default must NOT appear
        assert "issuetype" not in result.payload["fields"]

    def test_missing_key_returns_failure(self):
        row = {"Key": "", "Platform": "Calcs"}
        result = build_row_update_payload(
            row, row_number=3, key_column="Key", org_config=_org_config()
        )

        assert result.success is False
        assert result.payload is None
        assert "missing or empty" in (result.error or "")

    def test_missing_key_column_returns_failure(self):
        row = {"Platform": "Calcs"}  # no Key column at all
        result = build_row_update_payload(
            row, row_number=1, key_column="Key", org_config=_org_config()
        )

        assert result.success is False

    def test_blank_cells_omitted_from_payload(self):
        """Blank = no change; empty values must not appear in the payload."""
        row = {"Key": "CA-2", "Platform": "Calcs", "Horizontal": "", "Vertical": ""}
        result = build_row_update_payload(
            row, row_number=1, key_column="Key", org_config=_org_config()
        )

        assert result.success is True
        assert result.payload is not None
        # Only Platform is set; Horizontal and Vertical are omitted
        fields = result.payload["fields"]
        assert "customfield_12747" not in fields
        assert "customfield_12749" not in fields

    def test_whitespace_cells_omitted_from_payload(self):
        """Whitespace-only cells also mean no change."""
        row = {"Key": "CA-2", "Platform": "Calcs", "Horizontal": "   "}
        result = build_row_update_payload(
            row, row_number=1, key_column="Key", org_config=_org_config()
        )

        assert result.success is True
        assert result.payload is not None
        assert "customfield_12747" not in result.payload["fields"]

    def test_no_op_row_returns_none_payload(self):
        """Row with only the key column (no update fields) returns success but no payload."""
        row = {"Key": "CA-3"}
        result = build_row_update_payload(
            row, row_number=1, key_column="Key", org_config=_org_config()
        )

        assert result.success is True
        assert result.payload is None

    def test_unresolved_column_generates_warning(self):
        row = {"Key": "CA-4", "UnknownField": "value"}
        result = build_row_update_payload(
            row, row_number=1, key_column="Key", org_config=_org_config()
        )

        assert result.success is True
        assert result.payload is None
        assert any("skipped unresolved column" in w for w in result.warnings)

    def test_key_column_not_included_in_fields(self):
        row = {"Key": "CA-5", "Platform": "Calcs"}
        result = build_row_update_payload(
            row, row_number=1, key_column="Key", org_config=_org_config()
        )

        assert result.success is True
        assert result.payload is not None
        # 'Key' must not appear as a field in the payload
        assert "Key" not in result.payload["fields"]


# ---------------------------------------------------------------------------
# build_update_preview_report
# ---------------------------------------------------------------------------


class TestBuildUpdatePreviewReport:
    def test_counts_no_op_rows(self):
        rows = [
            {"Key": "CA-1", "Platform": "Calcs"},
            {"Key": "CA-2"},  # no-op
        ]
        report = build_update_preview_report(
            rows, key_column="Key", org_config=_org_config()
        )

        assert report.total_rows == 2
        assert report.no_op_rows == 1
        assert report.failed_rows == 0

    def test_fails_when_key_column_missing(self):
        rows = [{"Platform": "Calcs"}]
        with pytest.raises(ValueError, match="Key column 'Key' not found"):
            build_update_preview_report(
                rows, key_column="Key", org_config=_org_config()
            )

    def test_duplicate_keys_raise_value_error(self):
        rows = [
            {"Key": "CA-1", "Platform": "Calcs"},
            {"Key": "CA-1", "Horizontal": "Calcs"},
        ]

        with pytest.raises(ValueError, match="Duplicate Jira keys found"):
            build_update_preview_report(
                rows, key_column="Key", org_config=_org_config()
            )

    def test_populates_mapped_columns(self):
        rows = [{"Key": "CA-1", "Platform": "Calcs"}]
        report = build_update_preview_report(
            rows, key_column="Key", org_config=_org_config()
        )

        assert "Platform" in report.mapped_columns

    def test_populates_skipped_columns(self):
        rows = [{"Key": "CA-1", "WeirdCol": "value"}]
        report = build_update_preview_report(
            rows, key_column="Key", org_config=_org_config()
        )

        assert "WeirdCol" in report.skipped_columns

    def test_row_coercion_error_does_not_abort_report(self):
        org_config = _org_config()
        org_config.custom_fields["risk_score"] = "customfield_20000"
        rows = [
            {"Key": "CA-1", "risk_score": "not-a-number"},
            {"Key": "CA-2", "Platform": "Calcs"},
        ]

        report = build_update_preview_report(
            rows, key_column="Key", org_config=org_config
        )

        assert report.failed_rows == 1
        assert report.row_results[0].success is False
        assert "could not build update payload" in (report.row_results[0].error or "")
        assert report.row_results[1].success is True


# ---------------------------------------------------------------------------
# run_update
# ---------------------------------------------------------------------------


class TestRunUpdate:
    def test_dry_run_returns_empty_updated_list(self):
        rows = [{"Key": "CA-1", "Platform": "Calcs"}]
        result = run_update(
            rows,
            key_column="Key",
            org_config=_org_config(),
            jira_fields=None,
            client=None,
            dry_run=True,
        )

        assert result.updated == []
        assert result.failed == []
        assert result.skipped == []

    def test_live_run_calls_update_issue(self):
        rows = [{"Key": "CA-1", "Platform": "Calcs"}]
        client = MagicMock()
        client.update_issue = MagicMock()

        result = run_update(
            rows,
            key_column="Key",
            org_config=_org_config(),
            jira_fields=None,
            client=client,
        )

        client.update_issue.assert_called_once()
        call_args = client.update_issue.call_args
        assert call_args[0][0] == "CA-1"
        assert "fields" in call_args[0][1]
        assert len(result.updated) == 1
        assert result.updated[0] == (1, "CA-1")

    def test_skips_no_op_rows(self):
        rows = [{"Key": "CA-1"}]  # no fields to update
        client = MagicMock()

        result = run_update(
            rows,
            key_column="Key",
            org_config=_org_config(),
            jira_fields=None,
            client=client,
        )

        client.update_issue.assert_not_called()
        assert len(result.skipped) == 1
        assert "no fields to update" in result.skipped[0][2]

    def test_records_failed_rows_on_api_error(self):
        from jiramator.jira_client import JiraApiError

        rows = [{"Key": "CA-1", "Platform": "Calcs"}]
        client = MagicMock()
        client.update_issue.side_effect = JiraApiError("not found", status_code=404)

        result = run_update(
            rows,
            key_column="Key",
            org_config=_org_config(),
            jira_fields=None,
            client=client,
        )

        assert len(result.failed) == 1
        assert result.failed[0][1] == "CA-1"

    def test_records_failed_rows_on_payload_build_error(self):
        org_config = _org_config()
        org_config.custom_fields["risk_score"] = "customfield_20000"
        rows = [
            {"Key": "CA-1", "risk_score": "not-a-number"},
            {"Key": "CA-2", "Platform": "Calcs"},
        ]
        client = MagicMock()

        result = run_update(
            rows,
            key_column="Key",
            org_config=org_config,
            jira_fields=None,
            client=client,
        )

        assert len(result.failed) == 1
        assert result.failed[0][1] == "CA-1"
        assert len(result.updated) == 1

    def test_raises_when_client_none_for_live_run(self):
        rows = [{"Key": "CA-1", "Platform": "Calcs"}]
        with pytest.raises(ValueError, match="client is required"):
            run_update(
                rows,
                key_column="Key",
                org_config=_org_config(),
                jira_fields=None,
                client=None,
            )

    def test_duplicate_keys_abort_before_live_updates(self):
        rows = [
            {"Key": "CA-1", "Platform": "Calcs"},
            {"Key": "CA-1", "Horizontal": "Calcs"},
        ]
        client = MagicMock()

        with pytest.raises(ValueError, match="CA-1 appears on rows 1, 2"):
            run_update(
                rows,
                key_column="Key",
                org_config=_org_config(),
                jira_fields=None,
                client=client,
            )

        client.update_issue.assert_not_called()


# ---------------------------------------------------------------------------
# validate_unique_issue_keys
# ---------------------------------------------------------------------------


class TestValidateUniqueIssueKeys:
    def test_allows_unique_and_blank_keys(self):
        rows = [
            {"Key": "CA-1", "Platform": "Calcs"},
            {"Key": "", "Platform": "Calcs"},
            {"Key": "CA-2", "Platform": "Calcs"},
        ]

        validate_unique_issue_keys(rows, key_column="Key")

    def test_rejects_duplicate_keys_with_all_row_numbers(self):
        rows = [
            {"Key": "CA-1", "Platform": "Calcs"},
            {"Key": "CA-2", "Platform": "Calcs"},
            {"Key": "CA-1", "Platform": "Calcs"},
            {"Key": "CA-2", "Platform": "Calcs"},
        ]

        with pytest.raises(ValueError) as exc_info:
            validate_unique_issue_keys(rows, key_column="Key")

        message = str(exc_info.value)
        assert "CA-1 appears on rows 1, 3" in message
        assert "CA-2 appears on rows 2, 4" in message

    def test_rejects_missing_key_column(self):
        rows = [{"Platform": "Calcs"}]

        with pytest.raises(ValueError, match="Key column 'Key' not found"):
            validate_unique_issue_keys(rows, key_column="Key")


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class TestRenderReports:
    def test_preview_report_includes_summary_line(self):
        rows = [{"Key": "CA-1", "Platform": "Calcs"}]
        report = build_update_preview_report(
            rows, key_column="Key", org_config=_org_config()
        )
        output = render_update_preview_report(report)

        assert "Update preview" in output
        assert "total_rows=1" in output

    def test_execution_report_includes_updated_line(self):
        result = UpdateRunResult(
            preview=MagicMock(),
            updated=[(1, "CA-1")],
            skipped=[],
            failed=[],
        )
        output = render_update_execution_report(result)

        assert "updated=1" in output
        assert "CA-1" in output

    def test_execution_report_includes_failed_line(self):
        result = UpdateRunResult(
            preview=MagicMock(),
            updated=[],
            skipped=[],
            failed=[(2, "CA-2", "not found")],
        )
        output = render_update_execution_report(result)

        assert "failed=1" in output
        assert "CA-2" in output
        assert "not found" in output
