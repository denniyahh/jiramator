"""Tests for shared Jira value coercion used by bulk-create workflows."""

from __future__ import annotations

import pytest

from jiramator.config import BulkCreateConfig


@pytest.fixture()
def bulk_create_config() -> BulkCreateConfig:
    return BulkCreateConfig(
        field_types={
            "issuetype": "name_object",
            "priority": "name_object",
            "fixVersions": "name_object_array",
            "components": "name_object_array",
            "labels": "labels",
            "api_impact": "multi_select",
            "product_horizontals": "single_select",
            "product_verticals": "multi_select",
            "platform": "multi_select",
        },
        multi_value_delimiter=",",
    )


class TestCoerceFieldValue:
    def test_name_object(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("issuetype", "Risk", bulk_create_config) == {"name": "Risk"}

    def test_name_object_array_from_scalar(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("fixVersions", "26.3.0", bulk_create_config) == [{"name": "26.3.0"}]

    def test_name_object_array_from_list(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("components", ["API", "UI"], bulk_create_config) == [
            {"name": "API"},
            {"name": "UI"},
        ]

    def test_labels_from_comma_separated_string(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("labels", "PI28, Testing", bulk_create_config) == ["PI28", "Testing"]

    def test_single_select(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("product_horizontals", "Calcs", bulk_create_config) == {"value": "Calcs"}

    def test_multi_select_from_comma_separated_string(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("product_verticals", "US High Grade, Data", bulk_create_config) == [
            {"value": "US High Grade"},
            {"value": "Data"},
        ]

    def test_multi_select_from_list(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("platform", ["Calcs", "Risk"], bulk_create_config) == [
            {"value": "Calcs"},
            {"value": "Risk"},
        ]

    def test_adf_text(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        bulk_create_config.field_types["risk_description"] = "adf_text"

        assert coerce_field_value("risk_description", "Java touches core code", bulk_create_config) == {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Java touches core code"}],
                }
            ],
        }

    def test_number_from_string(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        bulk_create_config.field_types["overall_risk_value"] = "number"

        assert coerce_field_value("overall_risk_value", "10", bulk_create_config) == 10
        assert coerce_field_value("overall_risk_value", "10.5", bulk_create_config) == 10.5

    def test_passthrough_for_untyped_field(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import coerce_field_value

        assert coerce_field_value("customfield_10026", 3.0, bulk_create_config) == 3.0


class TestSplitMultiValue:
    def test_splits_and_trims_string(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import split_multi_value

        assert split_multi_value(" A,  B , , C ", bulk_create_config) == ["A", "B", "C"]

    def test_list_is_trimmed(self, bulk_create_config: BulkCreateConfig):
        from jiramator.value_coercion import split_multi_value

        assert split_multi_value([" A ", "B", "  ", "C "], bulk_create_config) == ["A", "B", "C"]


class TestShouldOmitValue:
    def test_omit_none(self):
        from jiramator.value_coercion import should_omit_value

        assert should_omit_value(None) is True

    def test_omit_empty_string(self):
        from jiramator.value_coercion import should_omit_value

        assert should_omit_value("") is True

    def test_omit_empty_list(self):
        from jiramator.value_coercion import should_omit_value

        assert should_omit_value([]) is True

    def test_do_not_omit_wrapped_values(self):
        from jiramator.value_coercion import should_omit_value

        assert should_omit_value({"name": "Risk"}) is False
        assert should_omit_value([{"value": "Calcs"}]) is False
