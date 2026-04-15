"""Tests for the ticket builder engine."""

from __future__ import annotations

import pytest

from jiramator.config import (
    EpicTemplate,
    OrgConfig,
    SprintConfig,
    TeamConfig,
    TicketTemplate,
)
from jiramator.ticket_builder import (
    WRAPPED_FIELDS,
    _build_fields_payload,
    _wrap_field,
    build_all,
    build_epics,
    build_per_release_tickets,
    build_per_sprint_tickets,
    resolve_value,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def org_config() -> OrgConfig:
    """Minimal org config for testing."""
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={"story_points": "customfield_10026", "epic_link": "customfield_10014"},
        sprints=SprintConfig(
            count=6,
            standard_length_weeks=2,
            long_length_weeks=3,
            long_sprints=[6],
        ),
    )


@pytest.fixture
def team_config() -> TeamConfig:
    """Minimal team config with one epic, one per-release, one per-sprint template."""
    return TeamConfig(
        project_key="TST",
        team_name="TestTeam",
        recurring_epics=[
            EpicTemplate(key="misc", summary="{team_name} {pi_label} - Misc"),
        ],
        per_release_tickets=[
            TicketTemplate(
                summary="Testing - {version} Pre-regression",
                fields={
                    "issuetype": "Task",
                    "priority": "Medium",
                    "labels": ["{pi_label}", "Testing"],
                    "fixVersions": ["{version}"],
                    "customfield_10026": 0.5,
                    "customfield_10014": "$epic:misc",
                },
            ),
        ],
        per_sprint_tickets=[
            TicketTemplate(
                summary="Prod Support (Sprint {sprint_num})",
                fields={
                    "issuetype": "Task",
                    "priority": "Medium",
                    "labels": ["{pi_label}", "Prod_Support"],
                    "fixVersions": ["{pi_label}"],
                    "customfield_10026": 2.0,
                    "customfield_10014": "$epic:misc",
                },
                extra_on_long_sprint=1,
                long_sprint_suffix=["a", "b"],
            ),
        ],
    )


@pytest.fixture
def base_vars() -> dict[str, str]:
    """Base runtime variables."""
    return {
        "pi_label": "PI28",
        "pi_num": "28",
        "team_name": "TestTeam",
    }


@pytest.fixture
def epic_keys() -> dict[str, str]:
    """Epic ref → Jira key mapping."""
    return {"misc": "TST-100"}


# ---------------------------------------------------------------------------
# resolve_value
# ---------------------------------------------------------------------------


class TestResolveValue:
    """Tests for template and epic ref resolution."""

    def test_plain_string_passthrough(self):
        assert resolve_value("hello", {}, {}) == "hello"

    def test_number_passthrough(self):
        assert resolve_value(0.5, {}, {}) == 0.5

    def test_none_passthrough(self):
        assert resolve_value(None, {}, {}) is None

    def test_bool_passthrough(self):
        assert resolve_value(True, {}, {}) is True

    def test_template_interpolation(self):
        result = resolve_value("{pi_label}", {"pi_label": "PI28"}, {})
        assert result == "PI28"

    def test_template_partial_interpolation(self):
        result = resolve_value(
            "Testing - {version} Pre-regression",
            {"version": "26.1.1"},
            {},
        )
        assert result == "Testing - 26.1.1 Pre-regression"

    def test_template_multiple_vars(self):
        result = resolve_value(
            "{team_name} {pi_label} - BAU",
            {"team_name": "Calcs", "pi_label": "PI28"},
            {},
        )
        assert result == "Calcs PI28 - BAU"

    def test_epic_ref_resolved(self):
        result = resolve_value("$epic:misc", {}, {"misc": "CA-5001"})
        assert result == "CA-5001"

    def test_epic_ref_unresolved_falls_back(self):
        """Unresolved epic refs pass through (useful for dry-run)."""
        result = resolve_value("$epic:misc", {}, {})
        assert result == "$epic:misc"

    def test_list_resolution(self):
        result = resolve_value(
            ["{pi_label}", "Testing"],
            {"pi_label": "PI28"},
            {},
        )
        assert result == ["PI28", "Testing"]

    def test_list_with_epic_ref(self):
        result = resolve_value(
            ["$epic:misc", "{pi_label}"],
            {"pi_label": "PI28"},
            {"misc": "TST-100"},
        )
        assert result == ["TST-100", "PI28"]

    def test_list_with_numbers(self):
        result = resolve_value([1, 2.5, "text"], {}, {})
        assert result == [1, 2.5, "text"]

    def test_unused_vars_ignored(self):
        """Extra variables in the dict don't cause problems."""
        result = resolve_value(
            "{pi_label}",
            {"pi_label": "PI28", "version": "26.1.1", "extra": "ignored"},
            {},
        )
        assert result == "PI28"


# ---------------------------------------------------------------------------
# _wrap_field
# ---------------------------------------------------------------------------


class TestWrapField:
    """Tests for Jira field-type wrapping."""

    def test_name_object_issuetype(self):
        assert _wrap_field("issuetype", "Task") == {"name": "Task"}

    def test_name_object_priority(self):
        assert _wrap_field("priority", "High") == {"name": "High"}

    def test_name_object_array_fix_versions(self):
        result = _wrap_field("fixVersions", ["26.1.1", "26.1.2"])
        assert result == [{"name": "26.1.1"}, {"name": "26.1.2"}]

    def test_name_object_array_single_value(self):
        """A single string gets wrapped into a list."""
        result = _wrap_field("fixVersions", "26.1.1")
        assert result == [{"name": "26.1.1"}]

    def test_name_object_array_components(self):
        result = _wrap_field("components", ["Frontend", "API"])
        assert result == [{"name": "Frontend"}, {"name": "API"}]

    def test_labels_not_wrapped(self):
        """Labels are already string arrays — no wrapping."""
        result = _wrap_field("labels", ["PI28", "Testing"])
        assert result == ["PI28", "Testing"]

    def test_custom_field_not_wrapped(self):
        """Custom fields pass through as-is."""
        assert _wrap_field("customfield_10026", 0.5) == 0.5

    def test_unknown_field_not_wrapped(self):
        assert _wrap_field("description", "some text") == "some text"


# ---------------------------------------------------------------------------
# _build_fields_payload
# ---------------------------------------------------------------------------


class TestBuildFieldsPayload:
    """Tests for the internal payload builder."""

    def test_injects_project_and_summary(self, base_vars, epic_keys):
        fields = _build_fields_payload(
            template_fields={},
            summary="Test ticket",
            project_key="TST",
            variables=base_vars,
            epic_keys=epic_keys,
        )
        assert fields["project"] == {"key": "TST"}
        assert fields["summary"] == "Test ticket"

    def test_resolves_and_wraps(self, epic_keys):
        fields = _build_fields_payload(
            template_fields={
                "issuetype": "Task",
                "priority": "Medium",
                "labels": ["{pi_label}"],
                "fixVersions": ["{version}"],
                "customfield_10026": 0.5,
                "customfield_10014": "$epic:misc",
            },
            summary="Testing - {version} Pre-regression",
            project_key="TST",
            variables={"pi_label": "PI28", "version": "26.1.1", "team_name": "T"},
            epic_keys=epic_keys,
        )
        assert fields["summary"] == "Testing - 26.1.1 Pre-regression"
        assert fields["issuetype"] == {"name": "Task"}
        assert fields["priority"] == {"name": "Medium"}
        assert fields["labels"] == ["PI28"]
        assert fields["fixVersions"] == [{"name": "26.1.1"}]
        assert fields["customfield_10026"] == 0.5
        assert fields["customfield_10014"] == "TST-100"


# ---------------------------------------------------------------------------
# build_epics
# ---------------------------------------------------------------------------


class TestBuildEpics:
    """Tests for epic payload generation."""

    def test_epic_payload_shape(self, org_config, team_config, base_vars):
        epics = build_epics(org_config, team_config, base_vars)
        assert len(epics) == 1

        epic = epics[0]
        assert epic["ref_key"] == "misc"
        assert epic["payload"]["fields"]["project"] == {"key": "TST"}
        assert epic["payload"]["fields"]["summary"] == "TestTeam PI28 - Misc"
        assert epic["payload"]["fields"]["issuetype"] == {"name": "Epic"}

    def test_multiple_epics(self, org_config, base_vars):
        tc = TeamConfig(
            project_key="X",
            team_name="TestTeam",
            recurring_epics=[
                EpicTemplate(key="bau", summary="{team_name} {pi_label} - BAU"),
                EpicTemplate(key="misc", summary="{team_name} {pi_label} - Misc"),
            ],
        )
        epics = build_epics(org_config, tc, base_vars)
        assert len(epics) == 2
        assert epics[0]["ref_key"] == "bau"
        assert epics[1]["ref_key"] == "misc"

    def test_no_epics(self, org_config, base_vars):
        tc = TeamConfig(project_key="X", team_name="TestTeam", recurring_epics=[])
        epics = build_epics(org_config, tc, base_vars)
        assert epics == []


# ---------------------------------------------------------------------------
# build_per_release_tickets
# ---------------------------------------------------------------------------


class TestBuildPerReleaseTickets:
    """Tests for per-release ticket generation."""

    def test_count_templates_times_versions(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        versions = ["26.1.1", "26.1.2", "26.2.0"]
        tickets = build_per_release_tickets(
            org_config, team_config, base_vars, versions, epic_keys,
        )
        # 1 template × 3 versions
        assert len(tickets) == 3

    def test_version_interpolated_in_summary(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_release_tickets(
            org_config, team_config, base_vars, ["26.1.1"], epic_keys,
        )
        assert tickets[0]["fields"]["summary"] == "Testing - 26.1.1 Pre-regression"

    def test_version_in_fix_versions(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_release_tickets(
            org_config, team_config, base_vars, ["26.1.1"], epic_keys,
        )
        assert tickets[0]["fields"]["fixVersions"] == [{"name": "26.1.1"}]

    def test_epic_link_resolved(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_release_tickets(
            org_config, team_config, base_vars, ["26.1.1"], epic_keys,
        )
        assert tickets[0]["fields"]["customfield_10014"] == "TST-100"

    def test_no_versions_no_tickets(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_release_tickets(
            org_config, team_config, base_vars, [], epic_keys,
        )
        assert tickets == []

    def test_no_templates_no_tickets(
        self, org_config, base_vars, epic_keys,
    ):
        tc = TeamConfig(project_key="X", team_name="T", per_release_tickets=[])
        tickets = build_per_release_tickets(
            org_config, tc, base_vars, ["26.1.1"], epic_keys,
        )
        assert tickets == []


# ---------------------------------------------------------------------------
# build_per_sprint_tickets
# ---------------------------------------------------------------------------


class TestBuildPerSprintTickets:
    """Tests for per-sprint ticket generation including long sprint handling."""

    def test_standard_sprint_count(self, org_config, team_config, base_vars, epic_keys):
        """6 sprints total: 5 standard (1 ticket each) + sprint 6 long (2 tickets) = 7."""
        tickets = build_per_sprint_tickets(
            org_config, team_config, base_vars, epic_keys,
        )
        assert len(tickets) == 7

    def test_standard_sprint_summaries(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_sprint_tickets(
            org_config, team_config, base_vars, epic_keys,
        )
        summaries = [t["fields"]["summary"] for t in tickets]
        assert summaries[0] == "Prod Support (Sprint 1)"
        assert summaries[1] == "Prod Support (Sprint 2)"
        assert summaries[4] == "Prod Support (Sprint 5)"

    def test_long_sprint_suffixed(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_sprint_tickets(
            org_config, team_config, base_vars, epic_keys,
        )
        summaries = [t["fields"]["summary"] for t in tickets]
        # Sprint 6 is long → "6a" and "6b"
        assert summaries[5] == "Prod Support (Sprint 6a)"
        assert summaries[6] == "Prod Support (Sprint 6b)"

    def test_no_long_sprints_all_standard(self, team_config, base_vars, epic_keys):
        """With no long sprints, every sprint gets one ticket."""
        oc = OrgConfig(
            jira_url="https://example.atlassian.net",
            custom_fields={},
            sprints=SprintConfig(
                count=4,
                standard_length_weeks=2,
                long_length_weeks=3,
                long_sprints=[],
            ),
        )
        tickets = build_per_sprint_tickets(oc, team_config, base_vars, epic_keys)
        # 4 sprints × 1 template (no expansion) = 4 tickets
        assert len(tickets) == 4
        summaries = [t["fields"]["summary"] for t in tickets]
        assert summaries == [
            "Prod Support (Sprint 1)",
            "Prod Support (Sprint 2)",
            "Prod Support (Sprint 3)",
            "Prod Support (Sprint 4)",
        ]

    def test_template_without_extras_on_long_sprint(
        self, org_config, base_vars, epic_keys,
    ):
        """A template with extra_on_long_sprint=0 generates one ticket per sprint, always."""
        tc = TeamConfig(
            project_key="X",
            team_name="T",
            per_sprint_tickets=[
                TicketTemplate(
                    summary="Standup (Sprint {sprint_num})",
                    fields={"issuetype": "Task"},
                ),
            ],
        )
        tickets = build_per_sprint_tickets(org_config, tc, base_vars, epic_keys)
        # 6 sprints, no expansion
        assert len(tickets) == 6
        assert tickets[5]["fields"]["summary"] == "Standup (Sprint 6)"

    def test_labels_include_pi_label(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_sprint_tickets(
            org_config, team_config, base_vars, epic_keys,
        )
        assert "PI28" in tickets[0]["fields"]["labels"]

    def test_fix_versions_is_pi_label(
        self, org_config, team_config, base_vars, epic_keys,
    ):
        tickets = build_per_sprint_tickets(
            org_config, team_config, base_vars, epic_keys,
        )
        assert tickets[0]["fields"]["fixVersions"] == [{"name": "PI28"}]

    def test_multiple_sprint_templates(self, org_config, base_vars, epic_keys):
        """Multiple per-sprint templates each generate tickets for every sprint."""
        tc = TeamConfig(
            project_key="X",
            team_name="T",
            per_sprint_tickets=[
                TicketTemplate(
                    summary="Template A (Sprint {sprint_num})",
                    fields={"issuetype": "Task"},
                ),
                TicketTemplate(
                    summary="Template B (Sprint {sprint_num})",
                    fields={"issuetype": "Task"},
                ),
            ],
        )
        tickets = build_per_sprint_tickets(org_config, tc, base_vars, epic_keys)
        # 6 sprints × 2 templates = 12
        assert len(tickets) == 12


# ---------------------------------------------------------------------------
# build_all
# ---------------------------------------------------------------------------


class TestBuildAll:
    """Tests for the main build_all entry point."""

    def test_returns_all_categories(
        self, org_config, team_config, epic_keys,
    ):
        result = build_all(
            org_config, team_config,
            pi_label="PI28", pi_num="28",
            versions=["26.1.1"], epic_keys=epic_keys,
        )
        assert "epics" in result
        assert "per_release" in result
        assert "per_sprint" in result

    def test_total_count_with_fixture(
        self, org_config, team_config, epic_keys,
    ):
        """1 epic, 1 per-release × 3 versions, 7 per-sprint = 11 total."""
        result = build_all(
            org_config, team_config,
            pi_label="PI28", pi_num="28",
            versions=["26.1.1", "26.1.2", "26.2.0"],
            epic_keys=epic_keys,
        )
        assert len(result["epics"]) == 1
        assert len(result["per_release"]) == 3
        assert len(result["per_sprint"]) == 7

    def test_dry_run_with_empty_epic_keys(
        self, org_config, team_config,
    ):
        """With empty epic_keys, $epic:refs pass through unresolved."""
        result = build_all(
            org_config, team_config,
            pi_label="PI28", pi_num="28",
            versions=["26.1.1"], epic_keys={},
        )
        ticket = result["per_release"][0]
        assert ticket["fields"]["customfield_10014"] == "$epic:misc"

    def test_pi_num_in_variables(self, org_config, epic_keys):
        """pi_num is passed through to templates."""
        tc = TeamConfig(
            project_key="X",
            team_name="T",
            recurring_epics=[
                EpicTemplate(key="bau", summary="PI{pi_num} BAU"),
            ],
        )
        result = build_all(
            org_config, tc,
            pi_label="PI28", pi_num="28",
            versions=[], epic_keys=epic_keys,
        )
        assert result["epics"][0]["payload"]["fields"]["summary"] == "PI28 BAU"
