"""Integration tests — load shipped example/Calcs configs and verify end-to-end.

These tests load the actual YAML config files shipped in configs/ and run the
ticket builder against them. No mocking of config models — the real parse +
validate + build pipeline runs end-to-end. Only the Jira API layer (which
belongs to the planner, not tested here) is absent.

Test scenario: PI28, versions [26.1.1, 26.1.2, 26.2.0].
Expected output:
    0 epics  (bau + misc are reused via existing_epics, not created)
    6 per-release templates × 3 versions = 18 per-release tickets
    1 per-sprint template × (5 standard + 2 long-sprint) = 7 per-sprint tickets
    Total: 25 payloads
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jiramator.config import load_org_config, load_team_config
from jiramator.ticket_builder import build_all, build_epics

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ORG_CONFIG_PATH = _REPO_ROOT / "configs" / "org.example" / "example.yaml"
_TEAM_CONFIG_PATH = _REPO_ROOT / "configs" / "teams" / "calcs.yaml"

# ---------------------------------------------------------------------------
# Runtime parameters for test scenario
# ---------------------------------------------------------------------------
PI_LABEL = "PI28"
PI_NUM = "28"
VERSIONS = ["26.1.1", "26.1.2", "26.2.0"]

# Simulate epic keys as if Jira had created them
EPIC_KEYS = {"bau": "CA-9001", "misc": "CA-9002"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def org_config():
    """Load the example org config."""
    cfg, _ = load_org_config(_ORG_CONFIG_PATH)
    return cfg


@pytest.fixture(scope="module")
def team_config():
    """Load the real Calcs team config."""
    cfg, _ = load_team_config(_TEAM_CONFIG_PATH)
    return cfg


@pytest.fixture(scope="module")
def all_payloads(org_config, team_config):
    """Build all payloads using real configs and simulated epic keys."""
    return build_all(
        org_config,
        team_config,
        pi_label=PI_LABEL,
        pi_num=PI_NUM,
        versions=VERSIONS,
        epic_keys=EPIC_KEYS,
    )


# ---------------------------------------------------------------------------
# Config loading smoke tests
# ---------------------------------------------------------------------------


class TestConfigLoading:
    """Verify the shipped YAML files parse and validate without error."""

    def test_org_config_loads(self, org_config):
        assert str(org_config.jira_url) == "https://example.atlassian.net/"
        assert org_config.custom_fields["story_points"] == "customfield_10026"
        assert org_config.custom_fields["epic_link"] == "customfield_10014"

    def test_org_sprint_config(self, org_config):
        assert org_config.sprints.count == 6
        assert org_config.sprints.standard_length_weeks == 2
        assert org_config.sprints.long_length_weeks == 3
        assert org_config.sprints.long_sprints == [6]

    def test_team_config_loads(self, team_config):
        assert team_config.project_key == "CA"
        assert team_config.team_name == "Calcs"
        assert team_config.board_id == 362
        assert team_config.sprint_name_template == "PI-{pi_num}.{sprint_num}-Calc -TI83"

    def test_team_has_expected_epic_count(self, team_config):
        assert len(team_config.recurring_epics) == 0
        assert team_config.existing_epics == {"bau": "CA-4829", "misc": "CA-4830"}
        assert sorted(team_config.get_epic_keys()) == ["bau", "misc"]

    def test_team_has_expected_per_release_count(self, team_config):
        assert len(team_config.per_release_tickets) == 6

    def test_team_has_expected_per_sprint_count(self, team_config):
        assert len(team_config.per_sprint_tickets) == 1

    def test_per_sprint_template_has_long_sprint_config(self, team_config):
        tmpl = team_config.per_sprint_tickets[0]
        assert tmpl.extra_on_long_sprint == 1
        assert tmpl.long_sprint_suffix == ["a", "b"]


# ---------------------------------------------------------------------------
# Total count assertions
# ---------------------------------------------------------------------------


class TestTicketCounts:
    """Verify build_all produces the correct number of payloads."""

    def test_epic_count(self, all_payloads):
        # No recurring epics — using existing_epics instead
        assert len(all_payloads["epics"]) == 0

    def test_per_release_count(self, all_payloads):
        # 6 templates × 3 versions = 18
        assert len(all_payloads["per_release"]) == 18

    def test_per_sprint_count(self, all_payloads):
        # Sprints 1-5: 1 ticket each = 5
        # Sprint 6 (long): 2 tickets (6a, 6b) = 2
        # Total = 7
        assert len(all_payloads["per_sprint"]) == 7

    def test_grand_total(self, all_payloads):
        total = (
            len(all_payloads["epics"])
            + len(all_payloads["per_release"])
            + len(all_payloads["per_sprint"])
        )
        assert total == 25  # 0 epics + 18 per-release + 7 per-sprint


# ---------------------------------------------------------------------------
# Epic payload verification
# ---------------------------------------------------------------------------


class TestEpicPayloads:
    """With existing_epics, no epic payloads are generated."""

    def test_no_epic_payloads_with_existing_epics(self, all_payloads):
        assert all_payloads["epics"] == []

    def test_existing_epic_keys_available(self, team_config):
        assert team_config.existing_epics["bau"] == "CA-4829"
        assert team_config.existing_epics["misc"] == "CA-4830"


# ---------------------------------------------------------------------------
# Per-release payload verification
# ---------------------------------------------------------------------------


class TestPerReleasePayloads:
    """Verify per-release tickets are correctly templated across versions."""

    def test_all_have_project_key(self, all_payloads):
        for ticket in all_payloads["per_release"]:
            assert ticket["fields"]["project"] == {"key": "CA"}

    def test_all_have_task_issuetype(self, all_payloads):
        for ticket in all_payloads["per_release"]:
            assert ticket["fields"]["issuetype"] == {"name": "Task"}

    def test_all_have_medium_priority(self, all_payloads):
        for ticket in all_payloads["per_release"]:
            assert ticket["fields"]["priority"] == {"name": "Medium"}

    def test_all_have_story_points(self, all_payloads):
        for ticket in all_payloads["per_release"]:
            assert ticket["fields"]["customfield_10026"] == 0.5

    def test_all_have_epic_link_resolved(self, all_payloads):
        for ticket in all_payloads["per_release"]:
            assert ticket["fields"]["customfield_10014"] == "CA-9002"  # misc epic

    def test_versions_are_correct(self, all_payloads):
        """Each version should appear exactly 6 times (once per template)."""
        version_counts: dict[str, int] = {}
        for ticket in all_payloads["per_release"]:
            # fixVersions is wrapped as [{"name": "x.y.z"}]
            fv = ticket["fields"]["fixVersions"]
            assert len(fv) == 1
            version_name = fv[0]["name"]
            version_counts[version_name] = version_counts.get(version_name, 0) + 1

        assert version_counts == {
            "26.1.1": 6,
            "26.1.2": 6,
            "26.2.0": 6,
        }

    def test_summaries_contain_version(self, all_payloads):
        """Every per-release summary should contain one of the version strings."""
        for ticket in all_payloads["per_release"]:
            summary = ticket["fields"]["summary"]
            assert any(v in summary for v in VERSIONS), f"No version found in: {summary}"

    def test_first_version_summaries(self, all_payloads):
        """Verify the exact 6 summaries for version 26.1.1 (first batch)."""
        first_six = all_payloads["per_release"][:6]
        expected_summaries = [
            "Testing - 26.1.1 Pre-regression test",
            "Testing - 26.1.1 Post-regression test",
            "Testing - Update Sanity Tester for 26.1.1",
            "Testing - 26.1.1 Auto-classifier pre-regression test",
            "Testing - 26.1.1 Auto-classifier post-regression test",
            "Testing - 26.1.1 Pre-release framework & defaults review",
        ]
        actual_summaries = [t["fields"]["summary"] for t in first_six]
        assert actual_summaries == expected_summaries

    def test_labels_include_pi_label(self, all_payloads):
        """Every per-release ticket should have PI28 in its labels."""
        for ticket in all_payloads["per_release"]:
            assert PI_LABEL in ticket["fields"]["labels"]


# ---------------------------------------------------------------------------
# Per-sprint payload verification
# ---------------------------------------------------------------------------


class TestPerSprintPayloads:
    """Verify per-sprint tickets, including long sprint expansion."""

    def test_all_have_project_key(self, all_payloads):
        for ticket in all_payloads["per_sprint"]:
            assert ticket["fields"]["project"] == {"key": "CA"}

    def test_all_have_task_issuetype(self, all_payloads):
        for ticket in all_payloads["per_sprint"]:
            assert ticket["fields"]["issuetype"] == {"name": "Task"}

    def test_all_have_story_points(self, all_payloads):
        for ticket in all_payloads["per_sprint"]:
            assert ticket["fields"]["customfield_10026"] == 2.0

    def test_all_have_epic_link_resolved(self, all_payloads):
        for ticket in all_payloads["per_sprint"]:
            assert ticket["fields"]["customfield_10014"] == "CA-9002"

    def test_all_have_prod_support_label(self, all_payloads):
        for ticket in all_payloads["per_sprint"]:
            assert "Prod_Support" in ticket["fields"]["labels"]

    def test_fix_versions_are_pi_label(self, all_payloads):
        """Per-sprint tickets use PI label as fixVersion, not release version."""
        for ticket in all_payloads["per_sprint"]:
            fv = ticket["fields"]["fixVersions"]
            assert fv == [{"name": "PI28"}]

    def test_sprint_summaries_in_order(self, all_payloads):
        """Verify exact summaries: sprints 1-5 standard, sprint 6 → 6a + 6b."""
        expected_summaries = [
            "Misc - Prod Support (Sprint 1)",
            "Misc - Prod Support (Sprint 2)",
            "Misc - Prod Support (Sprint 3)",
            "Misc - Prod Support (Sprint 4)",
            "Misc - Prod Support (Sprint 5)",
            "Misc - Prod Support (Sprint 6a)",
            "Misc - Prod Support (Sprint 6b)",
        ]
        actual_summaries = [t["fields"]["summary"] for t in all_payloads["per_sprint"]]
        assert actual_summaries == expected_summaries

    def test_no_plain_sprint_6(self, all_payloads):
        """Sprint 6 should NOT appear — only 6a and 6b."""
        summaries = [t["fields"]["summary"] for t in all_payloads["per_sprint"]]
        assert not any("Sprint 6)" in s for s in summaries)


# ---------------------------------------------------------------------------
# Dry-run (empty epic_keys) verification
# ---------------------------------------------------------------------------


class TestDryRun:
    """Verify build_all works with empty epic_keys (dry-run mode)."""

    @pytest.fixture(scope="class")
    def dry_payloads(self, org_config, team_config):
        return build_all(
            org_config,
            team_config,
            pi_label=PI_LABEL,
            pi_num=PI_NUM,
            versions=VERSIONS,
            epic_keys={},
        )

    def test_counts_match_live_run(self, dry_payloads):
        assert len(dry_payloads["epics"]) == 0  # no recurring_epics in calcs config
        assert len(dry_payloads["per_release"]) == 18
        assert len(dry_payloads["per_sprint"]) == 7

    def test_epic_links_unresolved(self, dry_payloads):
        """With no epic_keys, $epic:misc stays as the raw string."""
        for ticket in dry_payloads["per_release"]:
            assert ticket["fields"]["customfield_10014"] == "$epic:misc"

    def test_summaries_still_resolved(self, dry_payloads):
        """Template vars should still resolve even without epic_keys."""
        first = dry_payloads["per_release"][0]
        assert first["fields"]["summary"] == "Testing - 26.1.1 Pre-regression test"
