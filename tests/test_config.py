"""Tests for org config and team config loading and validation."""

import os
from pathlib import Path

import pytest
import yaml

from jiramator.config import (
    EpicTemplate,
    OrgConfig,
    SprintConfig,
    TeamConfig,
    TicketTemplate,
    _collect_epic_refs,
    _validate_template_vars,
    load_org_config,
    load_team_config,
)
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIGS_DIR = Path(__file__).parent.parent / "configs"
ORG_CONFIG_PATH = CONFIGS_DIR / "org.example" / "example.yaml"
# Use the tracked fixture (not the gitignored configs/teams/ dir) so this
# suite is reproducible on a fresh clone / in CI.
TEAM_CONFIG_PATH = FIXTURES_DIR / "teams" / "calcs.yaml"


@pytest.fixture
def org_config_data() -> dict:
    """Minimal valid org config data."""
    return {
        "jira_url": "https://example.atlassian.net",
        "jira_email_env": "JIRA_EMAIL",
        "jira_token_env": "JIRA_TOKEN",
        "custom_fields": {
            "story_points": "customfield_10026",
            "epic_link": "customfield_10014",
        },
        "sprints": {
            "count": 6,
            "standard_length_weeks": 2,
            "long_length_weeks": 3,
            "long_sprints": [6],
        },
    }


@pytest.fixture
def tmp_org_config(tmp_path: Path, org_config_data: dict) -> Path:
    """Write a valid org config YAML to a temp file and return the path."""
    p = tmp_path / "org.yaml"
    p.write_text(yaml.dump(org_config_data))
    return p


# ---------------------------------------------------------------------------
# OrgConfig parsing
# ---------------------------------------------------------------------------


class TestOrgConfigParsing:
    """Tests for OrgConfig model validation."""

    def test_valid_config(self, org_config_data: dict) -> None:
        cfg = OrgConfig(**org_config_data)
        assert str(cfg.jira_url) == "https://example.atlassian.net/"
        assert cfg.jira_email_env == "JIRA_EMAIL"
        assert cfg.jira_token_env == "JIRA_TOKEN"
        assert cfg.custom_fields["story_points"] == "customfield_10026"
        assert cfg.sprints.count == 6
        assert cfg.sprints.long_sprints == [6]

    def test_bulk_create_defaults_to_empty_values(self, org_config_data: dict) -> None:
        cfg = OrgConfig(**org_config_data)
        assert cfg.bulk_create.field_aliases == {}
        assert cfg.bulk_create.field_types == {}
        assert cfg.bulk_create.defaults == {}
        assert cfg.bulk_create.auto_lookup_unknown_fields is True
        assert cfg.bulk_create.multi_value_delimiter == ","

    def test_bulk_create_block_is_parsed(self, org_config_data: dict) -> None:
        org_config_data["custom_fields"] = {
            "story_points": "customfield_10026",
            "epic_link": "customfield_10014",
            "code_complexity": "customfield_11901",
            "risk_description": "customfield_11823",
        }
        org_config_data["bulk_create"] = {
            "field_aliases": {
                "Summary": "summary",
                "Issue Type": "issuetype",
                "API Impact": "api_impact",
                "Code Complexity": "code_complexity",
                "Risk Description": "risk_description",
            },
            "field_types": {
                "issuetype": "name_object",
                "api_impact": "multi_select",
                "code_complexity": "single_select",
                "risk_description": "adf_text",
                "overall_risk_value": "number",
            },
            "defaults": {
                "issuetype": "Risk",
            },
            "auto_lookup_unknown_fields": True,
            "multi_value_delimiter": ",",
        }
        cfg = OrgConfig(**org_config_data)
        assert cfg.bulk_create.field_aliases["Summary"] == "summary"
        assert cfg.bulk_create.field_aliases["API Impact"] == "api_impact"
        assert cfg.bulk_create.field_aliases["Code Complexity"] == "code_complexity"
        assert cfg.bulk_create.field_types["api_impact"] == "multi_select"
        assert cfg.bulk_create.field_types["risk_description"] == "adf_text"
        assert cfg.bulk_create.field_types["overall_risk_value"] == "number"
        assert cfg.bulk_create.defaults["issuetype"] == "Risk"

    def test_defaults_for_env_vars(self) -> None:
        """If env var names are omitted, defaults kick in."""
        cfg = OrgConfig(
            jira_url="https://example.atlassian.net",
            sprints={"count": 4, "standard_length_weeks": 2, "long_length_weeks": 3},
        )
        assert cfg.jira_email_env == "JIRA_EMAIL"
        assert cfg.jira_token_env == "JIRA_TOKEN"
        assert cfg.custom_fields == {}

    def test_missing_jira_url_raises(self) -> None:
        with pytest.raises(Exception):  # ValidationError
            OrgConfig(
                sprints={"count": 4, "standard_length_weeks": 2, "long_length_weeks": 3},
            )

    def test_missing_sprints_raises(self) -> None:
        with pytest.raises(Exception):  # ValidationError
            OrgConfig(jira_url="https://example.atlassian.net")

    def test_invalid_url_raises(self, org_config_data: dict) -> None:
        org_config_data["jira_url"] = "not-a-url"
        with pytest.raises(Exception):
            OrgConfig(**org_config_data)


# ---------------------------------------------------------------------------
# SprintConfig validation
# ---------------------------------------------------------------------------


class TestSprintConfig:
    """Tests for sprint cadence validation."""

    def test_long_sprint_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            SprintConfig(
                count=6,
                standard_length_weeks=2,
                long_length_weeks=3,
                long_sprints=[7],  # only 6 sprints exist
            )

    def test_long_sprint_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            SprintConfig(
                count=6,
                standard_length_weeks=2,
                long_length_weeks=3,
                long_sprints=[0],  # sprints are 1-indexed
            )

    def test_zero_count_raises(self) -> None:
        with pytest.raises(Exception):
            SprintConfig(
                count=0,
                standard_length_weeks=2,
                long_length_weeks=3,
            )

    def test_empty_long_sprints_ok(self) -> None:
        cfg = SprintConfig(
            count=4,
            standard_length_weeks=2,
            long_length_weeks=3,
            long_sprints=[],
        )
        assert cfg.long_sprints == []

    def test_multiple_long_sprints(self) -> None:
        """Some orgs might have 2 long sprints."""
        cfg = SprintConfig(
            count=6,
            standard_length_weeks=2,
            long_length_weeks=3,
            long_sprints=[5, 6],
        )
        assert cfg.long_sprints == [5, 6]


# ---------------------------------------------------------------------------
# Custom field lookup
# ---------------------------------------------------------------------------


class TestCustomFieldLookup:
    """Tests for get_custom_field_id."""

    def test_known_field(self, org_config_data: dict) -> None:
        cfg = OrgConfig(**org_config_data)
        assert cfg.get_custom_field_id("story_points") == "customfield_10026"
        assert cfg.get_custom_field_id("epic_link") == "customfield_10014"

    def test_unknown_field_raises(self, org_config_data: dict) -> None:
        cfg = OrgConfig(**org_config_data)
        with pytest.raises(KeyError, match="Custom field 'nonexistent'"):
            cfg.get_custom_field_id("nonexistent")


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------


class TestCredentialResolution:
    """Tests for resolve_credentials."""

    def test_credentials_from_env(self, org_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_TOKEN", "secret-token-123")

        cfg = OrgConfig(**org_config_data)
        email, token = cfg.resolve_credentials()
        assert email == "user@example.com"
        assert token == "secret-token-123"

    def test_missing_email_raises(self, org_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.setenv("JIRA_TOKEN", "token")

        cfg = OrgConfig(**org_config_data)
        with pytest.raises(ValueError, match="JIRA_EMAIL"):
            cfg.resolve_credentials()

    def test_missing_token_raises(self, org_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        cfg = OrgConfig(**org_config_data)
        with pytest.raises(ValueError, match="JIRA_TOKEN"):
            cfg.resolve_credentials()

    def test_both_missing_lists_both(self, org_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_TOKEN", raising=False)

        cfg = OrgConfig(**org_config_data)
        with pytest.raises(ValueError, match="JIRA_EMAIL.*JIRA_TOKEN"):
            cfg.resolve_credentials()

    def test_empty_string_env_var_raises(self, org_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("JIRA_EMAIL", "  ")
        monkeypatch.setenv("JIRA_TOKEN", "token")

        cfg = OrgConfig(**org_config_data)
        with pytest.raises(ValueError, match="JIRA_EMAIL"):
            cfg.resolve_credentials()

    def test_custom_env_var_names(self, org_config_data: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        org_config_data["jira_email_env"] = "MY_JIRA_USER"
        org_config_data["jira_token_env"] = "MY_JIRA_PAT"
        monkeypatch.setenv("MY_JIRA_USER", "admin@corp.com")
        monkeypatch.setenv("MY_JIRA_PAT", "pat-12345")

        cfg = OrgConfig(**org_config_data)
        email, token = cfg.resolve_credentials()
        assert email == "admin@corp.com"
        assert token == "pat-12345"


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class TestLoadOrgConfig:
    """Tests for load_org_config file loading."""

    def test_load_from_file(self, tmp_org_config: Path) -> None:
        cfg, _ = load_org_config(tmp_org_config)
        assert cfg.sprints.count == 6

    def test_nonexistent_file_raises(self) -> None:
        from jiramator.error_format import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="Org config not found"):
            load_org_config("/nonexistent/path.yaml")

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        from jiramator.error_format import ConfigValidationError
        p = tmp_path / "bad.yaml"
        p.write_text("- just\n- a\n- list\n")
        with pytest.raises(ConfigValidationError, match="YAML mapping"):
            load_org_config(p)

    def test_load_example_org_config(self) -> None:
        """Verify the shipped example org config loads and validates."""
        if not ORG_CONFIG_PATH.exists():
            pytest.skip("Example org config not present")
        cfg, _ = load_org_config(ORG_CONFIG_PATH)
        assert str(cfg.jira_url) == "https://example.atlassian.net/"
        assert cfg.custom_fields["story_points"] == "customfield_10026"
        assert cfg.custom_fields["epic_link"] == "customfield_10014"
        assert cfg.custom_fields["api_impact"] == "customfield_10273"
        assert cfg.custom_fields["product_horizontals"] == "customfield_12747"
        assert cfg.custom_fields["product_verticals"] == "customfield_12749"
        assert cfg.custom_fields["platform"] == "customfield_14823"
        assert cfg.bulk_create.field_aliases["Summary"] == "summary"
        assert cfg.bulk_create.field_aliases["API Impact"] == "api_impact"
        assert cfg.bulk_create.field_aliases["Reporter"] == "reporter"
        assert cfg.bulk_create.field_types["issuetype"] == "name_object"
        assert cfg.bulk_create.field_types["api_impact"] == "multi_select"
        assert cfg.bulk_create.defaults["issuetype"] == "Risk"
        assert cfg.bulk_create.auto_lookup_unknown_fields is True
        assert cfg.bulk_create.multi_value_delimiter == ","
        assert cfg.sprints.count == 6
        assert 6 in cfg.sprints.long_sprints


# ===========================================================================
# TEAM CONFIG TESTS
# ===========================================================================


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def team_config_data() -> dict:
    """Minimal valid team config data with epics and templates."""
    return {
        "project_key": "CA",
        "team_name": "Calcs",
        "recurring_epics": [
            {"key": "bau", "summary": "{team_name} {pi_label} - BAU Work"},
            {"key": "misc", "summary": "{team_name} {pi_label} - Miscellaneous Work"},
        ],
        "per_release_tickets": [
            {
                "summary": "Testing - {version} Pre-regression test",
                "fields": {
                    "issuetype": "Task",
                    "labels": ["{pi_label}", "Testing"],
                    "fixVersions": ["{version}"],
                    "customfield_10014": "$epic:misc",
                },
            },
        ],
        "per_sprint_tickets": [
            {
                "summary": "Misc - Prod Support (Sprint {sprint_num})",
                "fields": {
                    "issuetype": "Task",
                    "labels": ["{pi_label}", "Prod_Support"],
                    "customfield_10014": "$epic:misc",
                },
                "extra_on_long_sprint": 1,
                "long_sprint_suffix": ["a", "b"],
            },
        ],
    }


@pytest.fixture
def tmp_team_config(tmp_path: Path, team_config_data: dict) -> Path:
    """Write a valid team config YAML to a temp file and return the path."""
    p = tmp_path / "team.yaml"
    p.write_text(yaml.dump(team_config_data))
    return p


# ---------------------------------------------------------------------------
# EpicTemplate
# ---------------------------------------------------------------------------


class TestEpicTemplate:
    """Tests for EpicTemplate model validation."""

    def test_valid_epic(self) -> None:
        epic = EpicTemplate(key="bau", summary="{team_name} {pi_label} - BAU Work")
        assert epic.key == "bau"
        assert "{team_name}" in epic.summary

    def test_valid_epic_with_fields(self) -> None:
        epic = EpicTemplate(
            key="misc",
            summary="{team_name} {pi_label} - Misc Work",
            fields={
                "labels": ["{pi_label}", "Epic"],
                "customfield_10237": {"value": "Low"},
            },
        )
        assert epic.fields["labels"] == ["{pi_label}", "Epic"]
        assert epic.fields["customfield_10237"] == {"value": "Low"}

    def test_unknown_template_var_in_summary_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template variable"):
            EpicTemplate(key="bad", summary="{team_name} {bogus_var} - Epic")

    def test_unknown_template_var_in_fields_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template variable"):
            EpicTemplate(
                key="bad",
                summary="Static Epic",
                fields={"labels": ["{bogus_var}"]},
            )

    def test_no_template_vars_ok(self) -> None:
        """Static summary with no variables is fine."""
        epic = EpicTemplate(key="static", summary="Always This Name")
        assert epic.summary == "Always This Name"


# ---------------------------------------------------------------------------
# TicketTemplate
# ---------------------------------------------------------------------------


class TestTicketTemplate:
    """Tests for TicketTemplate model validation."""

    def test_valid_ticket_no_extras(self) -> None:
        tmpl = TicketTemplate(
            summary="Testing - {version} Pre-regression",
            fields={"issuetype": "Task"},
        )
        assert tmpl.extra_on_long_sprint == 0
        assert tmpl.long_sprint_suffix == []

    def test_valid_ticket_with_long_sprint(self) -> None:
        tmpl = TicketTemplate(
            summary="Misc - Prod Support (Sprint {sprint_num})",
            fields={"issuetype": "Task"},
            extra_on_long_sprint=1,
            long_sprint_suffix=["a", "b"],
        )
        assert tmpl.extra_on_long_sprint == 1
        assert tmpl.long_sprint_suffix == ["a", "b"]

    def test_unknown_template_var_in_summary_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template variable"):
            TicketTemplate(summary="Bad - {nonexistent}")

    def test_long_sprint_suffix_count_mismatch_raises(self) -> None:
        """extra=1 needs 2 suffixes (original + 1 extra)."""
        with pytest.raises(ValueError, match="long_sprint_suffix entries"):
            TicketTemplate(
                summary="Prod Support (Sprint {sprint_num})",
                extra_on_long_sprint=1,
                long_sprint_suffix=["a"],  # needs 2
            )

    def test_long_sprint_suffix_count_too_many_raises(self) -> None:
        with pytest.raises(ValueError, match="long_sprint_suffix entries"):
            TicketTemplate(
                summary="Prod Support (Sprint {sprint_num})",
                extra_on_long_sprint=1,
                long_sprint_suffix=["a", "b", "c"],  # needs 2
            )

    def test_extra_zero_ignores_suffixes(self) -> None:
        """When extra_on_long_sprint=0, suffixes are ignored (no validation)."""
        tmpl = TicketTemplate(
            summary="Normal ticket {version}",
            extra_on_long_sprint=0,
            long_sprint_suffix=["x", "y"],  # won't trigger validation
        )
        assert tmpl.extra_on_long_sprint == 0

    def test_extra_2_needs_3_suffixes(self) -> None:
        tmpl = TicketTemplate(
            summary="Triple (Sprint {sprint_num})",
            extra_on_long_sprint=2,
            long_sprint_suffix=["a", "b", "c"],
        )
        assert len(tmpl.long_sprint_suffix) == 3

    def test_negative_extra_raises(self) -> None:
        with pytest.raises(Exception):  # ge=0 validation
            TicketTemplate(
                summary="Bad {sprint_num}",
                extra_on_long_sprint=-1,
            )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for _validate_template_vars and _collect_epic_refs."""

    def test_validate_template_vars_known(self) -> None:
        """Known vars pass without error."""
        _validate_template_vars("{pi_label} {version}", "test")

    def test_validate_template_vars_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template variable.*bogus"):
            _validate_template_vars("{pi_label} {bogus}", "test")

    def test_validate_template_vars_no_vars(self) -> None:
        """Plain text with no {vars} is fine."""
        _validate_template_vars("just a string", "test")

    def test_collect_epic_refs_finds_refs(self) -> None:
        fields = {
            "customfield_10014": "$epic:misc",
            "labels": ["{pi_label}", "$epic:bau"],
        }
        refs = _collect_epic_refs(fields)
        assert refs == {"misc", "bau"}

    def test_collect_epic_refs_no_refs(self) -> None:
        fields = {"issuetype": "Task", "labels": ["Testing"]}
        refs = _collect_epic_refs(fields)
        assert refs == set()

    def test_collect_epic_refs_ignores_non_epic_dollar(self) -> None:
        """Only $epic:key pattern is matched, not arbitrary $strings."""
        fields = {"summary": "$not_an_epic_ref", "other": "$epic_without_colon"}
        refs = _collect_epic_refs(fields)
        assert refs == set()


# ---------------------------------------------------------------------------
# TeamConfig
# ---------------------------------------------------------------------------


class TestTeamConfig:
    """Tests for TeamConfig model validation."""

    def test_valid_config(self, team_config_data: dict) -> None:
        cfg = TeamConfig(**team_config_data)
        assert cfg.project_key == "CA"
        assert cfg.team_name == "Calcs"
        assert cfg.board_id is None
        assert cfg.sprint_name_template is None
        assert len(cfg.recurring_epics) == 2
        assert len(cfg.per_release_tickets) == 1
        assert len(cfg.per_sprint_tickets) == 1

    def test_minimal_config(self) -> None:
        """Just project_key and team_name — everything else defaults empty."""
        cfg = TeamConfig(project_key="TEST", team_name="Test Team")
        assert cfg.recurring_epics == []
        assert cfg.per_release_tickets == []
        assert cfg.per_sprint_tickets == []

    def test_missing_project_key_raises(self) -> None:
        with pytest.raises(Exception):
            TeamConfig(team_name="NoProject")

    def test_missing_team_name_raises(self) -> None:
        with pytest.raises(Exception):
            TeamConfig(project_key="X")

    def test_duplicate_epic_keys_raises(self) -> None:
        with pytest.raises(ValueError, match="Duplicate epic keys"):
            TeamConfig(
                project_key="X",
                team_name="Test",
                recurring_epics=[
                    {"key": "dup", "summary": "{team_name} A"},
                    {"key": "dup", "summary": "{team_name} B"},
                ],
            )

    def test_undefined_epic_ref_raises(self, team_config_data: dict) -> None:
        """$epic:nonexistent should fail validation."""
        team_config_data["per_release_tickets"][0]["fields"]["customfield_10014"] = "$epic:nonexistent"
        with pytest.raises(ValueError, match="undefined epic"):
            TeamConfig(**team_config_data)

    def test_epic_ref_in_list_field_validated(self) -> None:
        """$epic:ref inside a list value should also be validated."""
        with pytest.raises(ValueError, match="undefined epic"):
            TeamConfig(
                project_key="X",
                team_name="Test",
                recurring_epics=[{"key": "a", "summary": "{team_name}"}],
                per_release_tickets=[
                    {
                        "summary": "Ticket {version}",
                        "fields": {"links": ["$epic:a", "$epic:missing"]},
                    }
                ],
            )

    def test_unknown_template_var_in_fields_raises(self) -> None:
        """A {bad_var} in a ticket field string should fail."""
        with pytest.raises(ValueError, match="Unknown template variable"):
            TeamConfig(
                project_key="X",
                team_name="Test",
                recurring_epics=[{"key": "a", "summary": "{team_name}"}],
                per_release_tickets=[
                    {
                        "summary": "Ok {version}",
                        "fields": {"labels": ["{pi_label}", "{bad_var}"]},
                    }
                ],
            )

    def test_get_epic_keys(self, team_config_data: dict) -> None:
        cfg = TeamConfig(**team_config_data)
        assert cfg.get_epic_keys() == ["bau", "misc"]

    def test_board_id_and_sprint_template(self) -> None:
        cfg = TeamConfig(
            project_key="CA",
            team_name="Calcs",
            board_id=42,
            sprint_name_template="CA Sprint {pi_num}.{sprint_num}",
        )
        assert cfg.board_id == 42
        assert cfg.sprint_name_template == "CA Sprint {pi_num}.{sprint_num}"

    def test_numeric_field_values_not_validated_as_templates(self) -> None:
        """Numeric values in fields should pass without template validation."""
        cfg = TeamConfig(
            project_key="X",
            team_name="Test",
            recurring_epics=[{"key": "a", "summary": "{team_name}"}],
            per_release_tickets=[
                {
                    "summary": "Ticket {version}",
                    "fields": {
                        "customfield_10026": 0.5,
                        "customfield_10014": "$epic:a",
                    },
                }
            ],
        )
        assert cfg.per_release_tickets[0].fields["customfield_10026"] == 0.5


# ---------------------------------------------------------------------------
# release_sprint_schedule config tests
# ---------------------------------------------------------------------------


class TestReleaseSprintSchedule:
    """Tests for TeamConfig.release_sprint_schedule validation."""

    def test_valid_schedule(self) -> None:
        cfg = TeamConfig(
            project_key="X",
            team_name="Test",
            release_sprint_schedule={
                2: [{"pre": 4, "post": 5}, {"pre": 5, "post": 6}],
                3: [{"pre": 2, "post": 3}, {"pre": 4, "post": 5}, {"pre": 5, "post": 6}],
            },
        )
        assert cfg.release_sprint_schedule[2] == [
            {"pre": 4, "post": 5}, {"pre": 5, "post": 6},
        ]

    def test_default_empty(self) -> None:
        cfg = TeamConfig(project_key="X", team_name="Test")
        assert cfg.release_sprint_schedule == {}

    def test_entry_count_mismatch_raises(self) -> None:
        """A `3` key must have exactly 3 position entries."""
        with pytest.raises(ValueError, match="expected 3"):
            TeamConfig(
                project_key="X",
                team_name="Test",
                release_sprint_schedule={
                    3: [{"pre": 2, "post": 3}, {"pre": 4, "post": 5}],
                },
            )

    def test_zero_release_count_key_raises(self) -> None:
        with pytest.raises(ValueError, match="positive integer"):
            TeamConfig(
                project_key="X",
                team_name="Test",
                release_sprint_schedule={0: []},
            )

    def test_empty_position_entry_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            TeamConfig(
                project_key="X",
                team_name="Test",
                release_sprint_schedule={1: [{}]},
            )


# ---------------------------------------------------------------------------
# existing_epics config tests
# ---------------------------------------------------------------------------


class TestExistingEpics:
    """Tests for existing_epics field on TeamConfig."""

    MINIMAL = {
        "project_key": "CA",
        "team_name": "Calcs",
    }

    def test_existing_epics_default_empty(self) -> None:
        cfg = TeamConfig(**self.MINIMAL)
        assert cfg.existing_epics == {}

    def test_existing_epics_accepted(self) -> None:
        cfg = TeamConfig(**self.MINIMAL, existing_epics={"bau": "CA-123", "misc": "CA-456"})
        assert cfg.existing_epics == {"bau": "CA-123", "misc": "CA-456"}

    def test_get_epic_keys_combines_both(self) -> None:
        cfg = TeamConfig(
            **self.MINIMAL,
            existing_epics={"bau": "CA-123"},
            recurring_epics=[EpicTemplate(key="misc", summary="Misc")],
        )
        assert sorted(cfg.get_epic_keys()) == ["bau", "misc"]

    def test_epic_ref_resolves_against_existing(self) -> None:
        """$epic:ref should validate against existing_epics too."""
        cfg = TeamConfig(
            **self.MINIMAL,
            existing_epics={"bau": "CA-123"},
            per_release_tickets=[
                TicketTemplate(
                    summary="Task",
                    fields={"issuetype": "Story", "customfield_10014": "$epic:bau"},
                ),
            ],
        )
        assert cfg.per_release_tickets[0].fields["customfield_10014"] == "$epic:bau"

    def test_overlap_between_existing_and_recurring_rejected(self) -> None:
        with pytest.raises(ValidationError, match="existing_epics and recurring_epics"):
            TeamConfig(
                **self.MINIMAL,
                existing_epics={"bau": "CA-123"},
                recurring_epics=[EpicTemplate(key="bau", summary="BAU")],
            )

    def test_epic_ref_missing_from_both_rejected(self) -> None:
        with pytest.raises(ValidationError, match="undefined epic.*unknown"):
            TeamConfig(
                **self.MINIMAL,
                per_release_tickets=[
                    TicketTemplate(
                        summary="Task",
                        fields={"issuetype": "Story", "customfield_10014": "$epic:unknown"},
                    ),
                ],
            )


# ---------------------------------------------------------------------------
# Team config YAML loading
# ---------------------------------------------------------------------------


class TestLoadTeamConfig:
    """Tests for load_team_config file loading."""

    def test_load_from_file(self, tmp_team_config: Path) -> None:
        cfg, _ = load_team_config(tmp_team_config)
        assert cfg.project_key == "CA"
        assert cfg.team_name == "Calcs"
        assert len(cfg.recurring_epics) == 2

    def test_nonexistent_file_raises(self) -> None:
        from jiramator.error_format import ConfigValidationError
        with pytest.raises(ConfigValidationError, match="Team config not found"):
            load_team_config("/nonexistent/team.yaml")

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        from jiramator.error_format import ConfigValidationError
        p = tmp_path / "bad.yaml"
        p.write_text("- a\n- b\n")
        with pytest.raises(ConfigValidationError, match="YAML mapping"):
            load_team_config(p)

    def test_load_real_calcs_config(self) -> None:
        """Verify the shipped Calcs team config loads and validates."""
        if not TEAM_CONFIG_PATH.exists():
            pytest.skip("Calcs team config not present")
        cfg, _ = load_team_config(TEAM_CONFIG_PATH)
        assert cfg.project_key == "CA"
        assert cfg.team_name == "Calcs"
        assert len(cfg.recurring_epics) == 0
        assert cfg.existing_epics == {"bau": "CA-4829", "misc": "CA-4830"}
        assert sorted(cfg.get_epic_keys()) == ["bau", "misc"]
        assert len(cfg.per_release_tickets) == 6
        assert len(cfg.per_sprint_tickets) == 1
        # Prod support has long sprint expansion
        prod = cfg.per_sprint_tickets[0]
        assert prod.extra_on_long_sprint == 1
        assert prod.long_sprint_suffix == ["a", "b"]


# ===========================================================================
# PHASE 02-01 — TEAM DEFAULTS (TEMPLATE INHERITANCE)
# ===========================================================================


import io

from rich.console import Console

from jiramator.config import TeamDefaults
from jiramator.error_format import ConfigConflictWarning


class TestTeamDefaultsPydantic:
    """Pydantic-shape tests for the new TeamConfig.defaults field."""

    def test_p1_defaults_absent_yields_empty(self, team_config_data: dict) -> None:
        """P1: existing team config without `defaults:` defaults to empty."""
        cfg = TeamConfig(**team_config_data)
        assert isinstance(cfg.defaults, TeamDefaults)
        assert cfg.defaults.fields == {}

    def test_p2_defaults_empty_dict_accepted(self, team_config_data: dict) -> None:
        """P2: `defaults: {}` validates to empty TeamDefaults."""
        team_config_data["defaults"] = {}
        cfg = TeamConfig(**team_config_data)
        assert cfg.defaults.fields == {}

    def test_p3_defaults_fields_priority(self, team_config_data: dict) -> None:
        """P3: defaults.fields.priority loads verbatim."""
        team_config_data["defaults"] = {"fields": {"priority": "Medium"}}
        cfg = TeamConfig(**team_config_data)
        # Pydantic constructor does NOT run the merge; only load_team_config does.
        assert cfg.defaults.fields == {"priority": "Medium"}

    def test_p4_defaults_fields_multiple_keys(self, team_config_data: dict) -> None:
        """P4: defaults.fields carries arbitrary key shapes verbatim."""
        team_config_data["defaults"] = {
            "fields": {
                "priority": "Medium",
                "customfield_10273": [{"value": "No"}],
            },
        }
        cfg = TeamConfig(**team_config_data)
        assert cfg.defaults.fields["priority"] == "Medium"
        assert cfg.defaults.fields["customfield_10273"] == [{"value": "No"}]

    def test_p5_defaults_non_dict_raises(
        self, team_config_data: dict, tmp_path: Path
    ) -> None:
        """P5: `defaults: 42` raises ConfigValidationError citing `defaults`."""
        team_config_data["defaults"] = 42
        p = tmp_path / "team.yaml"
        p.write_text(yaml.dump(team_config_data))
        from jiramator.error_format import ConfigValidationError
        with pytest.raises(ConfigValidationError) as exc:
            load_team_config(p)
        assert "defaults" in exc.value.field_path

    def test_p6_existing_calcs_yaml_loads_unchanged(self) -> None:
        """P6: real-world calcs.yaml (no defaults: block) loads identically."""
        # No assertion on defaults beyond "it's empty and the load succeeds."
        cfg, _ = load_team_config(TEAM_CONFIG_PATH)
        assert cfg.defaults.fields == {}
        # Sanity-check at least one template list is non-empty (real config).
        all_templates = (
            cfg.recurring_epics + cfg.per_release_tickets + cfg.per_sprint_tickets
        )
        assert len(all_templates) >= 1
        # No template should have gained a `__line__` key from merge.
        for tmpl in all_templates:
            assert "__line__" not in tmpl.fields


@pytest.fixture
def _stub_org() -> OrgConfig:
    """Minimal OrgConfig with empty default_fields — used to drive merge_configs
    in the Plan-02-01 team-defaults integration tests (Phase 02-02 rewire)."""
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        sprints=SprintConfig(
            count=4, standard_length_weeks=2, long_length_weeks=3
        ),
    )


def _load_and_merge(
    team_path: Path, stub_org: OrgConfig
) -> TeamConfig:
    """Helper: load team config and apply merge_configs with a stub org.

    Used by the Plan-02-01 I1-I6 integration tests, rewired in Plan 02-02
    Task 2 to drive the team-defaults layer through the new orchestrator
    (the single composition point).
    """
    from jiramator.config_merge import merge_configs

    team, team_tagged = load_team_config(team_path)
    return merge_configs(
        org_model=stub_org,
        org_tagged_raw={},
        org_file=Path("stub-org.yaml"),
        team_model=team,
        team_tagged_raw=team_tagged,
        team_file=team_path,
    )


class TestTeamDefaultsMergeIntegration:
    """End-to-end integration tests for the team-defaults layer.

    Rewired in Plan 02-02 Task 2: routes through ``merge_configs`` with a
    stub OrgConfig (default_fields={}) so the layer-2 (team-defaults vs
    template) behavior is exercised exactly as in Plan 02-01, but via the
    new single composition point.
    """

    def _write_team(self, tmp_path: Path, data: dict) -> Path:
        p = tmp_path / "team.yaml"
        p.write_text(yaml.dump(data))
        return p

    def test_i1_disjoint_priority_merges_with_no_warning(
        self,
        tmp_path: Path,
        team_config_data: dict,
        capsys,
        _stub_org: OrgConfig,
    ) -> None:
        """I1: defaults.priority + ticket without priority → ticket gets it."""
        team_config_data["defaults"] = {"fields": {"priority": "Medium"}}
        team_config_data["per_release_tickets"] = [
            {"summary": "Hello {pi_label}", "fields": {"summary_only": "x"}},
        ]
        p = self._write_team(tmp_path, team_config_data)
        cfg = _load_and_merge(p, _stub_org)
        captured = capsys.readouterr()
        assert captured.err == ""
        merged = cfg.per_release_tickets[0].fields
        assert merged == {"summary_only": "x", "priority": "Medium"}

    def test_i2_conflict_emits_stderr_warning_and_defaults_win(
        self,
        tmp_path: Path,
        team_config_data: dict,
        capsys,
        _stub_org: OrgConfig,
    ) -> None:
        """I2: defaults.priority=Medium + ticket priority=High → defaults win, warn."""
        team_config_data["defaults"] = {"fields": {"priority": "Medium"}}
        team_config_data["per_release_tickets"] = [
            {"summary": "Hello {pi_label}", "fields": {"priority": "High"}},
        ]
        p = self._write_team(tmp_path, team_config_data)
        cfg = _load_and_merge(p, _stub_org)
        captured = capsys.readouterr()
        assert "locked by team defaults" in captured.err
        assert "per_release_tickets[0].fields.priority" in captured.err
        assert "later value ignored." in captured.err
        assert cfg.per_release_tickets[0].fields["priority"] == "Medium"

    def test_i3_defaults_propagate_across_all_three_lists(
        self,
        tmp_path: Path,
        team_config_data: dict,
        capsys,
        _stub_org: OrgConfig,
    ) -> None:
        """I3: defaults flow into recurring_epics + per_release + per_sprint alike."""
        team_config_data["defaults"] = {"fields": {"priority": "Medium"}}
        team_config_data["recurring_epics"] = [
            {"key": "bau", "summary": "{team_name} BAU", "fields": {}},
        ]
        team_config_data["per_release_tickets"] = [
            {"summary": "Hello {pi_label}", "fields": {}},
        ]
        team_config_data["per_sprint_tickets"] = [
            {"summary": "Sprint {sprint_num}", "fields": {}},
        ]
        p = self._write_team(tmp_path, team_config_data)
        cfg = _load_and_merge(p, _stub_org)
        assert capsys.readouterr().err == ""
        assert cfg.recurring_epics[0].fields == {"priority": "Medium"}
        assert cfg.per_release_tickets[0].fields == {"priority": "Medium"}
        assert cfg.per_sprint_tickets[0].fields == {"priority": "Medium"}

    def test_i4_list_typed_defaults_concat_no_warning(
        self,
        tmp_path: Path,
        team_config_data: dict,
        capsys,
        _stub_org: OrgConfig,
    ) -> None:
        """I4: multi-select list value concats earlier-first, no warning."""
        team_config_data["defaults"] = {
            "fields": {"customfield_10273": [{"value": "No"}]},
        }
        team_config_data["per_release_tickets"] = [
            {
                "summary": "S {pi_label}",
                "fields": {"customfield_10273": [{"value": "Yes"}]},
            },
        ]
        p = self._write_team(tmp_path, team_config_data)
        cfg = _load_and_merge(p, _stub_org)
        assert capsys.readouterr().err == ""
        merged = cfg.per_release_tickets[0].fields["customfield_10273"]
        assert merged == [{"value": "No"}, {"value": "Yes"}]

    def test_i5_calcs_style_realistic_fixture(
        self,
        tmp_path: Path,
        team_config_data: dict,
        capsys,
        _stub_org: OrgConfig,
    ) -> None:
        """I5: hoist 4 calcs.yaml-style repeated fields into defaults; templates inherit."""
        common_defaults = {
            "priority": "Medium",
            "customfield_10273": [{"value": "No"}],
            "customfield_10026": 0.5,
            "customfield_10014": "$epic:misc",
        }
        team_config_data["defaults"] = {"fields": common_defaults}
        team_config_data["recurring_epics"] = [
            {"key": "misc", "summary": "{team_name} Misc"},
        ]
        team_config_data["per_release_tickets"] = [
            {
                "summary": "Pre-regression {version}",
                "fields": {
                    "issuetype": "Task",
                    "labels": ["{pi_label}", "Testing"],
                    "fixVersions": ["{version}"],
                },
            },
        ]
        # Drop the default base fixture's per_sprint_tickets (it sets
        # customfield_10014, which collides with the hoisted defaults).
        team_config_data["per_sprint_tickets"] = []
        p = self._write_team(tmp_path, team_config_data)
        cfg = _load_and_merge(p, _stub_org)
        assert capsys.readouterr().err == ""
        tmpl = cfg.per_release_tickets[0].fields
        # All four hoisted fields present:
        for k, v in common_defaults.items():
            assert tmpl[k] == v
        # Plus the template-specific fields:
        assert tmpl["issuetype"] == "Task"
        assert tmpl["fixVersions"] == ["{version}"]

    def test_i6_warnings_routed_via_default_console_to_stderr(
        self,
        tmp_path: Path,
        team_config_data: dict,
        capsys,
        _stub_org: OrgConfig,
    ) -> None:
        """I6: with no `console` arg merge_configs instantiates Console(stderr=True).

        The warning text appears on captured stderr (capsys.err), proving the
        default-console path is wired.
        """
        team_config_data["defaults"] = {"fields": {"priority": "Medium"}}
        team_config_data["per_release_tickets"] = [
            {"summary": "S {pi_label}", "fields": {"priority": "High"}},
        ]
        p = self._write_team(tmp_path, team_config_data)
        _load_and_merge(p, _stub_org)
        out = capsys.readouterr()
        assert out.out == ""
        assert "locked by team defaults" in out.err


# ===========================================================================
# PHASE 02-02 — ORG default_fields + tuple-returning loaders
# ===========================================================================


class TestOrgDefaultFields:
    """Pydantic-shape tests for the new OrgConfig.default_fields field."""

    def test_o1_default_fields_absent_yields_empty(
        self, org_config_data: dict
    ) -> None:
        """O1: existing org config without `default_fields:` defaults to empty."""
        cfg = OrgConfig(**org_config_data)
        assert cfg.default_fields == {}

    def test_o2_default_fields_empty_dict_accepted(
        self, org_config_data: dict
    ) -> None:
        """O2: `default_fields: {}` validates to empty dict."""
        org_config_data["default_fields"] = {}
        cfg = OrgConfig(**org_config_data)
        assert cfg.default_fields == {}

    def test_o3_default_fields_priority(self, org_config_data: dict) -> None:
        """O3: `default_fields: { priority: Medium }` loads verbatim."""
        org_config_data["default_fields"] = {"priority": "Medium"}
        cfg = OrgConfig(**org_config_data)
        assert cfg.default_fields == {"priority": "Medium"}

    def test_o4_default_fields_multiple_keys_with_list(
        self, org_config_data: dict
    ) -> None:
        """O4: arbitrary key shapes preserved verbatim, list shape intact."""
        org_config_data["default_fields"] = {
            "priority": "Medium",
            "customfield_10273": [{"value": "No"}],
        }
        cfg = OrgConfig(**org_config_data)
        assert cfg.default_fields["priority"] == "Medium"
        assert cfg.default_fields["customfield_10273"] == [{"value": "No"}]

    def test_o5_default_fields_non_dict_raises(
        self, org_config_data: dict, tmp_path: Path
    ) -> None:
        """O5: `default_fields: 42` raises ConfigValidationError citing
        `default_fields`."""
        org_config_data["default_fields"] = 42
        p = tmp_path / "org.yaml"
        p.write_text(yaml.dump(org_config_data))
        from jiramator.error_format import ConfigValidationError
        with pytest.raises(ConfigValidationError) as exc:
            load_org_config(p)
        assert "default_fields" in exc.value.field_path

    def test_o6_existing_example_yaml_unchanged(self) -> None:
        """O6: shipped example org config (no default_fields) loads with empty."""
        if not ORG_CONFIG_PATH.exists():
            pytest.skip("Example org config not present")
        cfg, _ = load_org_config(ORG_CONFIG_PATH)
        assert cfg.default_fields == {}


class TestLoaderTupleSignature:
    """Loader signature change: load_*_config now returns (model, tagged_raw)."""

    def test_l1_load_org_config_returns_tuple(
        self, tmp_org_config: Path
    ) -> None:
        """L1: load_org_config returns a 2-tuple of (OrgConfig, tagged_raw)."""
        result = load_org_config(tmp_org_config)
        assert isinstance(result, tuple)
        assert len(result) == 2
        cfg, tagged = result
        assert isinstance(cfg, OrgConfig)
        # tagged_raw is a dict with line markers injected by the YAML loader.
        from jiramator.yaml_loader import LINE_KEY
        assert isinstance(tagged, dict)
        assert LINE_KEY in tagged

    def test_l2_load_team_config_returns_tuple(
        self, tmp_team_config: Path
    ) -> None:
        """L2: load_team_config returns a 2-tuple of (TeamConfig, tagged_raw)."""
        result = load_team_config(tmp_team_config)
        assert isinstance(result, tuple)
        assert len(result) == 2
        cfg, tagged = result
        assert isinstance(cfg, TeamConfig)
        from jiramator.yaml_loader import LINE_KEY
        assert isinstance(tagged, dict)
        assert LINE_KEY in tagged

    def test_l4_load_team_config_does_not_apply_defaults(
        self, tmp_path: Path, team_config_data: dict
    ) -> None:
        """L4: load_team_config no longer applies team defaults internally.

        Template `fields` after load reflect the raw YAML; merge_configs
        is now the single composition point.
        """
        team_config_data["defaults"] = {"fields": {"priority": "Medium"}}
        team_config_data["per_release_tickets"] = [
            {"summary": "Hello {pi_label}", "fields": {"summary_only": "x"}},
        ]
        p = tmp_path / "team.yaml"
        p.write_text(yaml.dump(team_config_data))
        cfg, _ = load_team_config(p)
        # Defaults NOT applied — template's fields untouched.
        assert cfg.per_release_tickets[0].fields == {"summary_only": "x"}
        # But defaults model still carries the declared value:
        assert cfg.defaults.fields == {"priority": "Medium"}


# ---------------------------------------------------------------------------
# Plan 02-03: TeamConfig.sprints_exist tri-state field
# ---------------------------------------------------------------------------


class TestTeamConfigSprintsExist:
    """Tests for the new ``TeamConfig.sprints_exist: bool | None`` field (Plan 02-03)."""

    def test_se1_absent_field_defaults_to_none(self, team_config_data: dict) -> None:
        """SE1: backward compat — absent ``sprints_exist:`` yields ``None``."""
        cfg = TeamConfig(**team_config_data)
        assert cfg.sprints_exist is None

    def test_se2_explicit_true(self, team_config_data: dict) -> None:
        """SE2: ``sprints_exist: true`` yields ``True``."""
        team_config_data["sprints_exist"] = True
        cfg = TeamConfig(**team_config_data)
        assert cfg.sprints_exist is True

    def test_se3_explicit_false(self, team_config_data: dict) -> None:
        """SE3: ``sprints_exist: false`` yields ``False``."""
        team_config_data["sprints_exist"] = False
        cfg = TeamConfig(**team_config_data)
        assert cfg.sprints_exist is False

    def test_se4_explicit_null(self, team_config_data: dict, tmp_path: Path) -> None:
        """SE4: explicit YAML ``null`` round-trips to ``None``."""
        team_config_data["sprints_exist"] = None
        p = tmp_path / "team.yaml"
        p.write_text(yaml.dump(team_config_data))
        cfg, _ = load_team_config(p)
        assert cfg.sprints_exist is None

    def test_se5_string_value_rejected(
        self, team_config_data: dict, tmp_path: Path
    ) -> None:
        """SE5: non-bool/non-null values rejected with ConfigValidationError mentioning sprints_exist."""
        team_config_data["sprints_exist"] = "yes"
        p = tmp_path / "team.yaml"
        p.write_text(yaml.dump(team_config_data))
        from jiramator.error_format import ConfigValidationError

        with pytest.raises(ConfigValidationError) as exc_info:
            load_team_config(p)
        assert "sprints_exist" in exc_info.value.field_path

    def test_se6_independent_of_board_id(self, team_config_data: dict) -> None:
        """SE6: ``sprints_exist=True`` validates even when ``board_id`` is unset (runtime concern, not validation)."""
        team_config_data["sprints_exist"] = True
        # No board_id set — should still validate at the model level.
        cfg = TeamConfig(**team_config_data)
        assert cfg.sprints_exist is True
        assert cfg.board_id is None

    def test_se7_round_trip_via_load_team_config(
        self, team_config_data: dict, tmp_path: Path
    ) -> None:
        """sprints_exist survives YAML round-trip via load_team_config."""
        team_config_data["sprints_exist"] = False
        p = tmp_path / "team.yaml"
        p.write_text(yaml.dump(team_config_data))
        cfg, _ = load_team_config(p)
        assert cfg.sprints_exist is False
