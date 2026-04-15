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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIGS_DIR = Path(__file__).parent.parent / "configs"
ORG_CONFIG_PATH = CONFIGS_DIR / "org" / "marketaxess.yaml"
TEAM_CONFIG_PATH = CONFIGS_DIR / "teams" / "calcs.yaml"


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
        cfg = load_org_config(tmp_org_config)
        assert cfg.sprints.count == 6

    def test_nonexistent_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="Org config not found"):
            load_org_config("/nonexistent/path.yaml")

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("- just\n- a\n- list\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_org_config(p)

    def test_load_real_marketaxess_config(self) -> None:
        """Verify the shipped MarketAxess config loads and validates."""
        if not ORG_CONFIG_PATH.exists():
            pytest.skip("MarketAxess config not present")
        cfg = load_org_config(ORG_CONFIG_PATH)
        assert str(cfg.jira_url) == "https://marketaxess.atlassian.net/"
        assert cfg.custom_fields["story_points"] == "customfield_10026"
        assert cfg.custom_fields["epic_link"] == "customfield_10014"
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

    def test_unknown_template_var_in_summary_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown template variable"):
            EpicTemplate(key="bad", summary="{team_name} {bogus_var} - Epic")

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
# Team config YAML loading
# ---------------------------------------------------------------------------


class TestLoadTeamConfig:
    """Tests for load_team_config file loading."""

    def test_load_from_file(self, tmp_team_config: Path) -> None:
        cfg = load_team_config(tmp_team_config)
        assert cfg.project_key == "CA"
        assert cfg.team_name == "Calcs"
        assert len(cfg.recurring_epics) == 2

    def test_nonexistent_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="Team config not found"):
            load_team_config("/nonexistent/team.yaml")

    def test_non_mapping_yaml_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.yaml"
        p.write_text("- a\n- b\n")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_team_config(p)

    def test_load_real_calcs_config(self) -> None:
        """Verify the shipped Calcs config loads and validates."""
        if not TEAM_CONFIG_PATH.exists():
            pytest.skip("Calcs team config not present")
        cfg = load_team_config(TEAM_CONFIG_PATH)
        assert cfg.project_key == "CA"
        assert cfg.team_name == "Calcs"
        assert len(cfg.recurring_epics) == 2
        assert cfg.get_epic_keys() == ["bau", "misc"]
        assert len(cfg.per_release_tickets) == 6
        assert len(cfg.per_sprint_tickets) == 1
        # Prod support has long sprint expansion
        prod = cfg.per_sprint_tickets[0]
        assert prod.extra_on_long_sprint == 1
        assert prod.long_sprint_suffix == ["a", "b"]
