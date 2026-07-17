"""Tests for pure ticket-payload validation against Jira createmeta schema."""

from __future__ import annotations

from jiramator.payload_validator import validate_ticket_payload


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


class TestMissingRequiredFields:
    def test_missing_required_field_flagged(self):
        fields = {"project": {"key": "CA"}, "summary": "Test"}
        meta = {
            "customfield_10273": {
                "name": "API Impact", "required": True, "hasDefaultValue": False,
            },
        }
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1
        assert "API Impact" in problems[0]
        assert "customfield_10273" in problems[0]

    def test_required_field_present_not_flagged(self):
        fields = {"project": {"key": "CA"}, "customfield_10273": [{"value": "No"}]}
        meta = {
            "customfield_10273": {
                "name": "API Impact", "required": True, "hasDefaultValue": False,
            },
        }
        assert validate_ticket_payload(fields, meta) == []

    def test_required_field_with_default_not_flagged(self):
        """Jira auto-fills fields with hasDefaultValue — not our problem to flag."""
        fields = {"project": {"key": "CA"}}
        meta = {
            "priority": {"name": "Priority", "required": True, "hasDefaultValue": True},
        }
        assert validate_ticket_payload(fields, meta) == []

    def test_project_field_never_flagged(self):
        """`project` is builder-injected and excluded from required-field checks."""
        fields = {}
        meta = {"project": {"name": "Project", "required": True, "hasDefaultValue": False}}
        assert validate_ticket_payload(fields, meta) == []

    def test_empty_value_counts_as_missing(self):
        fields = {"labels": []}
        meta = {"labels": {"name": "Labels", "required": True, "hasDefaultValue": False}}
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1


# ---------------------------------------------------------------------------
# ADF / rich-text checks
# ---------------------------------------------------------------------------


class TestAdfChecks:
    def test_plain_string_description_flagged(self):
        fields = {"description": "plain text"}
        meta = {"description": {"name": "Description", "schema": {"system": "description"}}}
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1
        assert "Atlassian Document Format" in problems[0]

    def test_adf_dict_description_not_flagged(self):
        fields = {
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}],
            },
        }
        meta = {"description": {"name": "Description", "schema": {"system": "description"}}}
        assert validate_ticket_payload(fields, meta) == []

    def test_custom_textarea_field_requires_adf(self):
        fields = {"customfield_10042": "plain text"}
        meta = {
            "customfield_10042": {
                "name": "Acceptance Criteria",
                "schema": {"custom": "com.atlassian.jira.plugin.system.customfieldtypes:textarea"},
            },
        }
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1
        assert "Acceptance Criteria" in problems[0]

    def test_non_textarea_custom_field_not_flagged_for_adf(self):
        fields = {"customfield_10026": 0.5}
        meta = {
            "customfield_10026": {
                "name": "Story Points",
                "schema": {"custom": "com.pyxis.greenhopper.jira:jsw-story-points"},
            },
        }
        assert validate_ticket_payload(fields, meta) == []


# ---------------------------------------------------------------------------
# allowedValues (select-field) checks
# ---------------------------------------------------------------------------


class TestAllowedValuesChecks:
    def test_invalid_name_object_value_flagged(self):
        fields = {"priority": {"name": "NotReal"}}
        meta = {
            "priority": {
                "name": "Priority",
                "allowedValues": [{"name": "High"}, {"name": "Medium"}, {"name": "Low"}],
            },
        }
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1
        assert "not one of the allowed options" in problems[0]

    def test_valid_name_object_value_not_flagged(self):
        fields = {"priority": {"name": "High"}}
        meta = {
            "priority": {
                "name": "Priority",
                "allowedValues": [{"name": "High"}, {"name": "Medium"}],
            },
        }
        assert validate_ticket_payload(fields, meta) == []

    def test_invalid_value_in_list_flagged(self):
        fields = {"components": [{"name": "Frontend"}, {"name": "NotReal"}]}
        meta = {
            "components": {
                "name": "Components",
                "allowedValues": [{"name": "Frontend"}, {"name": "Backend"}],
            },
        }
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1
        assert "NotReal" in problems[0]

    def test_matches_by_id_not_just_name(self):
        fields = {"priority": {"id": "3"}}
        meta = {
            "priority": {
                "name": "Priority",
                "allowedValues": [{"id": "3", "name": "Medium"}],
            },
        }
        assert validate_ticket_payload(fields, meta) == []

    def test_field_not_on_screen_skipped(self):
        """A field we send that isn't in createmeta at all — not our call."""
        fields = {"customfield_99999": "anything"}
        meta = {}
        assert validate_ticket_payload(fields, meta) == []

    def test_fix_versions_allowed_values_skipped(self):
        """fixVersions' allowedValues is a snapshot of EXISTING Jira versions —
        `plan` legitimately references/creates new ones that won't be in it
        yet (see planner._check_and_create_fix_versions). A not-yet-created
        version must not be flagged as invalid, or every plan run introducing
        a new release would falsely abort."""
        fields = {"fixVersions": [{"name": "26.4.1"}]}
        meta = {
            "fixVersions": {
                "name": "Fix versions",
                "allowedValues": [{"name": "26.1.1"}, {"name": "26.2.1"}],
            },
        }
        assert validate_ticket_payload(fields, meta) == []

    def test_fix_versions_still_checked_for_required(self):
        """Skipping allowedValues for fixVersions must not skip required-ness."""
        fields = {}
        meta = {
            "fixVersions": {
                "name": "Fix versions", "required": True, "hasDefaultValue": False,
                "allowedValues": [{"name": "26.1.1"}],
            },
        }
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 1
        assert "Fix versions" in problems[0]


# ---------------------------------------------------------------------------
# Combined / integration-shaped payloads
# ---------------------------------------------------------------------------


class TestCombinedPayload:
    def test_clean_payload_returns_no_problems(self):
        fields = {
            "project": {"key": "CA"},
            "summary": "Test",
            "issuetype": {"name": "Task"},
            "priority": {"name": "Medium"},
            "description": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "hi"}]}],
            },
            "fixVersions": [{"name": "26.4.1"}],
        }
        meta = {
            "issuetype": {"name": "Issue Type", "allowedValues": [{"name": "Task"}]},
            "priority": {"name": "Priority", "allowedValues": [{"name": "Medium"}]},
            "description": {"name": "Description", "schema": {"system": "description"}},
            "fixVersions": {
                "name": "Fix versions",
                "allowedValues": [{"name": "26.1.1"}],  # 26.4.1 not here — must not flag
            },
        }
        assert validate_ticket_payload(fields, meta) == []

    def test_multiple_problems_all_reported(self):
        fields = {
            "priority": {"name": "Bogus"},
            "description": "plain",
        }
        meta = {
            "customfield_10273": {
                "name": "API Impact", "required": True, "hasDefaultValue": False,
            },
            "priority": {"name": "Priority", "allowedValues": [{"name": "High"}]},
            "description": {"name": "Description", "schema": {"system": "description"}},
        }
        problems = validate_ticket_payload(fields, meta)
        assert len(problems) == 3
