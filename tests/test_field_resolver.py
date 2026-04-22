"""Tests for shared field resolution used by bulk-create workflows."""

from __future__ import annotations

import pytest

from jiramator.config import BulkCreateConfig, OrgConfig


@pytest.fixture()
def org_config() -> OrgConfig:
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={
            "story_points": "customfield_10026",
            "epic_link": "customfield_10014",
            "api_impact": "customfield_10273",
            "product_horizontals": "customfield_12747",
        },
        bulk_create=BulkCreateConfig(
            field_aliases={
                "type": "issuetype",
                "fix_version": "fixVersions",
                "Summary": "summary",
                "Issue Type": "issuetype",
                "API Impact": "api_impact",
                "Product Horizontals": "product_horizontals",
            }
        ),
        sprints={
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    )


class TestNormalizeFieldName:
    def test_strips_and_lowercases(self):
        from jiramator.field_resolver import normalize_field_name

        assert normalize_field_name("  API   Impact ") == "api impact"


class TestResolveFieldName:
    def test_alias_resolves_to_standard_field(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        result = resolve_field_name("Issue Type", org_config)

        assert result.source_name == "Issue Type"
        assert result.logical_name == "issuetype"
        assert result.jira_field == "issuetype"
        assert result.resolution_source == "alias"

    def test_alias_resolves_to_custom_field_via_logical_name(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        result = resolve_field_name("API Impact", org_config)

        assert result.logical_name == "api_impact"
        assert result.jira_field == "customfield_10273"
        assert result.resolution_source == "alias"

    def test_normalized_alias_match_is_supported(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        result = resolve_field_name("  product   horizontals ", org_config)

        assert result.logical_name == "product_horizontals"
        assert result.jira_field == "customfield_12747"
        assert result.resolution_source == "alias_normalized"

    def test_direct_standard_field_passthrough(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        result = resolve_field_name("summary", org_config)

        assert result.logical_name == "summary"
        assert result.jira_field == "summary"
        assert result.resolution_source == "direct"

    def test_direct_custom_field_id_passthrough(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        result = resolve_field_name("customfield_99999", org_config)

        assert result.logical_name == "customfield_99999"
        assert result.jira_field == "customfield_99999"
        assert result.resolution_source == "direct"

    def test_jira_exact_name_match_is_used_when_enabled(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        jira_fields = [
            {"id": "customfield_14823", "name": "Platform"},
        ]

        result = resolve_field_name("Platform", org_config, jira_fields=jira_fields)

        assert result.logical_name == "Platform"
        assert result.jira_field == "customfield_14823"
        assert result.resolution_source == "jira_exact"

    def test_jira_normalized_name_match_is_used_when_enabled(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        jira_fields = [
            {"id": "customfield_14823", "name": "Platform"},
        ]

        result = resolve_field_name("  platform ", org_config, jira_fields=jira_fields)

        assert result.logical_name == "platform"
        assert result.jira_field == "customfield_14823"
        assert result.resolution_source == "jira_normalized"

    def test_unknown_field_returns_unresolved(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_field_name

        result = resolve_field_name("Totally Unknown", org_config)

        assert result.source_name == "Totally Unknown"
        assert result.logical_name == "Totally Unknown"
        assert result.jira_field is None
        assert result.resolution_source == "unresolved"


class TestResolveFieldsMap:
    def test_resolves_multiple_fields_and_collects_unresolved(self, org_config: OrgConfig):
        from jiramator.field_resolver import resolve_fields_map

        resolved, unresolved = resolve_fields_map(
            ["Summary", "Issue Type", "Unknown Header"],
            org_config,
        )

        assert resolved["Summary"].jira_field == "summary"
        assert resolved["Issue Type"].jira_field == "issuetype"
        assert unresolved == ["Unknown Header"]
