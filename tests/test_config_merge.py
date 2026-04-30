"""Tests for the layered config merge engine (Phase 02-01).

Covers:
  - canonical_form (JSON-canonical, deterministic, stdlib-only)
  - concat_dedup_lists (earlier-first list union with structural dedup)
  - deep_merge_dicts (earlier-wins recursive dict merge with conflict warnings)
  - merge_team_defaults_into_templates (the public top-level entrypoint that
    propagates team `defaults.fields` into every template's `fields`)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jiramator.config import (
    EpicTemplate,
    TeamConfig,
    TeamDefaults,
    TicketTemplate,
)
from jiramator.config_merge import (
    _apply_team_layer_to_templates as merge_team_defaults_into_templates,
    canonical_form,
    concat_dedup_lists,
    deep_merge_dicts,
)
from jiramator.error_format import ConfigConflictWarning
from jiramator.yaml_loader import safe_load_with_lines


# ---------------------------------------------------------------------------
# canonical_form
# ---------------------------------------------------------------------------


class TestCanonicalForm:
    def test_c1_primitive_string(self) -> None:
        assert canonical_form("audit") == '"audit"'

    def test_c2_dict_no_spaces(self) -> None:
        assert canonical_form({"value": "No"}) == '{"value":"No"}'

    def test_c3_dict_keys_sorted(self) -> None:
        assert canonical_form({"b": 1, "a": 2}) == '{"a":2,"b":1}'

    def test_c4_list_stable(self) -> None:
        items = [{"value": "No"}, {"value": "Yes"}]
        a = canonical_form(items)
        b = canonical_form(items)
        assert a == b
        assert "No" in a and "Yes" in a

    def test_c5_non_json_native_via_default_str(self) -> None:
        # default=str should accept arbitrary objects without raising.
        class Foo:
            def __str__(self) -> str:
                return "FOO"

        out = canonical_form(Foo())
        assert "FOO" in out


# ---------------------------------------------------------------------------
# concat_dedup_lists
# ---------------------------------------------------------------------------


class TestConcatDedupLists:
    def test_l1_disjoint_primitives(self) -> None:
        assert concat_dedup_lists(["a", "b"], ["c"]) == ["a", "b", "c"]

    def test_l2_dedup_primitive_first_wins(self) -> None:
        assert concat_dedup_lists(["a", "b"], ["b", "c"]) == ["a", "b", "c"]

    def test_l3_disjoint_dicts(self) -> None:
        assert concat_dedup_lists(
            [{"value": "No"}], [{"value": "Yes"}]
        ) == [{"value": "No"}, {"value": "Yes"}]

    def test_l4_structural_dedup(self) -> None:
        assert concat_dedup_lists(
            [{"value": "No"}], [{"value": "No"}]
        ) == [{"value": "No"}]

    def test_l5_empty_inputs(self) -> None:
        assert concat_dedup_lists([], ["a"]) == ["a"]
        assert concat_dedup_lists(["a"], []) == ["a"]
        assert concat_dedup_lists([], []) == []

    def test_l6_order_preserved_earlier_first(self) -> None:
        assert concat_dedup_lists(["b", "a"], ["a", "c"]) == ["b", "a", "c"]


# ---------------------------------------------------------------------------
# deep_merge_dicts
# ---------------------------------------------------------------------------


def _merge(earlier: dict, later: dict, **overrides):
    """Convenience wrapper supplying boring required kwargs."""
    kwargs = dict(
        path_prefix="",
        earlier_file=Path("team.yaml"),
        later_file=Path("team.yaml"),
        earlier_loc=("defaults", "fields"),
        later_loc=("per_release_tickets", 0, "fields"),
        earlier_tagged_root={},
        later_tagged_root={},
        earlier_layer="team defaults",
    )
    kwargs.update(overrides)
    return deep_merge_dicts(earlier, later, **kwargs)


class TestDeepMergeDicts:
    def test_d1_disjoint_keys(self) -> None:
        merged, warnings = _merge({"a": 1}, {"b": 2})
        assert merged == {"a": 1, "b": 2}
        assert warnings == []

    def test_d2_scalar_conflict_earlier_wins_one_warning(self) -> None:
        merged, warnings = _merge({"priority": "High"}, {"priority": "Medium"})
        assert merged == {"priority": "High"}
        assert len(warnings) == 1
        assert warnings[0].field_path == "priority"
        assert warnings[0].earlier_layer == "team defaults"

    def test_d3_list_concat_no_warning(self) -> None:
        merged, warnings = _merge(
            {"k": [{"value": "No"}]},
            {"k": [{"value": "Yes"}]},
        )
        assert merged == {"k": [{"value": "No"}, {"value": "Yes"}]}
        assert warnings == []

    def test_d4_nested_dict_recursive_merge(self) -> None:
        merged, warnings = _merge({"a": {"b": 1}}, {"a": {"c": 2}})
        assert merged == {"a": {"b": 1, "c": 2}}
        assert warnings == []

    def test_d4_nested_dict_conflict_dotted_path(self) -> None:
        merged, warnings = _merge({"a": {"b": 1}}, {"a": {"b": 2}})
        assert merged == {"a": {"b": 1}}
        assert len(warnings) == 1
        assert warnings[0].field_path == "a.b"

    def test_d5_shape_mismatch_scalar_vs_list(self) -> None:
        merged, warnings = _merge({"k": "x"}, {"k": [1]})
        assert merged == {"k": "x"}
        assert len(warnings) == 1
        assert warnings[0].field_path == "k"

    def test_d6_deeply_nested_compound_path(self) -> None:
        merged, warnings = _merge(
            {"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 2}}}
        )
        assert merged == {"a": {"b": {"c": 1}}}
        assert len(warnings) == 1
        assert warnings[0].field_path == "a.b.c"

    def test_d7_line_key_never_propagates(self) -> None:
        merged, warnings = _merge(
            {"__line__": 5, "a": 1},
            {"__line__": 12, "b": 2},
        )
        assert "__line__" not in merged
        assert merged == {"a": 1, "b": 2}
        assert warnings == []

    def test_d_path_prefix_propagates(self) -> None:
        merged, warnings = _merge(
            {"priority": "High"}, {"priority": "Medium"},
            path_prefix="per_release_tickets[0].fields",
        )
        assert len(warnings) == 1
        assert warnings[0].field_path == "per_release_tickets[0].fields.priority"


# ---------------------------------------------------------------------------
# merge_team_defaults_into_templates
# ---------------------------------------------------------------------------


def _make_team(
    *,
    defaults_fields: dict | None = None,
    recurring_epics: list[dict] | None = None,
    per_release_tickets: list[dict] | None = None,
    per_sprint_tickets: list[dict] | None = None,
) -> TeamConfig:
    """Build a minimal TeamConfig programmatically."""
    return TeamConfig(
        project_key="CA",
        team_name="Calcs",
        defaults=TeamDefaults(fields=defaults_fields or {}),
        recurring_epics=[
            EpicTemplate(**e) for e in (recurring_epics or [])
        ],
        per_release_tickets=[
            TicketTemplate(**t) for t in (per_release_tickets or [])
        ],
        per_sprint_tickets=[
            TicketTemplate(**t) for t in (per_sprint_tickets or [])
        ],
    )


class TestMergeConfigsTeamLayer:
    """Layer-2 (team defaults → templates) coverage; uses the internal helper
    ``_apply_team_layer_to_templates`` aliased here as
    ``merge_team_defaults_into_templates`` for continuity with Plan 02-01.
    The helper IS what ``merge_configs`` calls for layer 2.
    """
    def test_m1_no_defaults_is_noop(self) -> None:
        team = _make_team(
            per_release_tickets=[
                {"summary": "S", "fields": {"a": 1}},
            ],
        )
        warnings = merge_team_defaults_into_templates(
            team_model=team,
            team_tagged_raw={},
            team_file=Path("team.yaml"),
        )
        assert warnings == []
        assert team.per_release_tickets[0].fields == {"a": 1}

    def test_m2_defaults_propagates_to_all_three_lists(self) -> None:
        team = _make_team(
            defaults_fields={"priority": "Medium"},
            recurring_epics=[
                {"key": "bau", "summary": "BAU", "fields": {"summary_only_thing": "x"}},
            ],
            per_release_tickets=[
                {"summary": "S1", "fields": {"summary_only_thing": "x"}},
            ],
            per_sprint_tickets=[
                {"summary": "S2", "fields": {"summary_only_thing": "x"}},
            ],
        )
        warnings = merge_team_defaults_into_templates(
            team_model=team,
            team_tagged_raw={},
            team_file=Path("team.yaml"),
        )
        assert warnings == []
        assert team.recurring_epics[0].fields == {"summary_only_thing": "x", "priority": "Medium"}
        assert team.per_release_tickets[0].fields == {"summary_only_thing": "x", "priority": "Medium"}
        assert team.per_sprint_tickets[0].fields == {"summary_only_thing": "x", "priority": "Medium"}

    def test_m3_conflict_earlier_wins_with_warning(self) -> None:
        # Build tagged raw via the line-aware loader so resolve_line works.
        yaml_text = (
            "project_key: CA\n"
            "team_name: Calcs\n"
            "defaults:\n"
            "  fields:\n"
            "    priority: High\n"
            "per_release_tickets:\n"
            "  - summary: S1\n"
            "    fields:\n"
            "      priority: Medium\n"
            "      x: 1\n"
        )
        tagged = safe_load_with_lines(yaml_text)
        team = _make_team(
            defaults_fields={"priority": "High"},
            per_release_tickets=[
                {"summary": "S1", "fields": {"priority": "Medium", "x": 1}},
            ],
        )
        warnings = merge_team_defaults_into_templates(
            team_model=team,
            team_tagged_raw=tagged,
            team_file=Path("team.yaml"),
        )
        assert team.per_release_tickets[0].fields == {"priority": "High", "x": 1}
        assert len(warnings) == 1
        w = warnings[0]
        assert w.field_path == "per_release_tickets[0].fields.priority"
        assert w.earlier_layer == "team defaults"
        # Defaults block declared at line 3; defaults.fields entries start line 5.
        # Template `fields:` starts around line 8; `priority: Medium` is line 9.
        assert w.earlier_line is not None and w.earlier_line >= 3
        assert w.later_line is not None and w.later_line >= 7

    def test_m4_list_typed_defaults_concat_no_warnings(self) -> None:
        team = _make_team(
            defaults_fields={"customfield_10273": [{"value": "No"}]},
            per_release_tickets=[
                {"summary": "S1", "fields": {"customfield_10273": [{"value": "Yes"}]}},
            ],
        )
        warnings = merge_team_defaults_into_templates(
            team_model=team,
            team_tagged_raw={},
            team_file=Path("team.yaml"),
        )
        assert warnings == []
        assert team.per_release_tickets[0].fields["customfield_10273"] == [
            {"value": "No"},
            {"value": "Yes"},
        ]

    def test_m5_source_defaults_dict_not_mutated(self) -> None:
        defaults_fields = {"priority": "Medium"}
        team = _make_team(
            defaults_fields=defaults_fields,
            per_release_tickets=[
                {"summary": "S1", "fields": {"x": 1}},
            ],
        )
        # Snapshot before merge.
        before = dict(team.defaults.fields)
        merge_team_defaults_into_templates(
            team_model=team,
            team_tagged_raw={},
            team_file=Path("team.yaml"),
        )
        assert team.defaults.fields == before

    def test_m6_line_resolution_via_tagged_raw(self) -> None:
        yaml_text = (
            "project_key: CA\n"          # line 1
            "team_name: Calcs\n"           # line 2
            "defaults:\n"                  # line 3
            "  fields:\n"                  # line 4
            "    priority: High\n"         # line 5
            "per_release_tickets:\n"       # line 6
            "  - summary: S1\n"            # line 7
            "    fields:\n"                # line 8
            "      priority: Medium\n"     # line 9
        )
        tagged = safe_load_with_lines(yaml_text)
        team = _make_team(
            defaults_fields={"priority": "High"},
            per_release_tickets=[
                {"summary": "S1", "fields": {"priority": "Medium"}},
            ],
        )
        warnings = merge_team_defaults_into_templates(
            team_model=team,
            team_tagged_raw=tagged,
            team_file=Path("team.yaml"),
        )
        assert len(warnings) == 1
        w = warnings[0]
        # PyYAML's start_mark for a nested mapping points at its first child
        # key. The `defaults.fields` mapping's first child is `priority: High`
        # at line 5 — so earlier_line resolves to 5.
        assert w.earlier_line == 5
        # `priority: Medium` lives in the per_release_tickets[0].fields
        # mapping. That mapping's first child key is `priority: Medium` at
        # line 9.
        assert w.later_line == 9


# ===========================================================================
# Phase 02-02 — merge_configs orchestrator (org → team-defaults → templates)
# ===========================================================================


import copy
import io

from rich.console import Console

from jiramator.config import OrgConfig, SprintConfig


def _make_org(default_fields: dict | None = None) -> OrgConfig:
    """Build a minimal OrgConfig programmatically (Phase 02-02 helper)."""
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        sprints=SprintConfig(
            count=4, standard_length_weeks=2, long_length_weeks=3
        ),
        default_fields=default_fields or {},
    )


def _stderr_console() -> tuple[Console, io.StringIO]:
    """Build a Console writing to an in-memory buffer (test harness)."""
    buf = io.StringIO()
    return Console(file=buf, force_terminal=False, width=200), buf


class TestMergeConfigs:
    """Tests for the org → team-defaults → template orchestrator."""

    ORG_FILE = Path("org.yaml")
    TEAM_FILE = Path("team.yaml")

    def test_mc1_noop_when_no_org_defaults_and_no_team_defaults(self) -> None:
        """MC1: empty org default_fields + empty team defaults = no-op."""
        from jiramator.config_merge import merge_configs

        org = _make_org()
        team = _make_team(
            per_release_tickets=[{"summary": "S", "fields": {"a": 1}}],
        )
        console, buf = _stderr_console()
        result = merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=console,
        )
        assert result is team  # mutates and returns
        assert team.per_release_tickets[0].fields == {"a": 1}
        assert buf.getvalue() == ""

    def test_mc2_org_default_field_propagates_to_template(self) -> None:
        """MC2: org default_fields.priority flows into a template lacking it."""
        from jiramator.config_merge import merge_configs

        org = _make_org({"priority": "Medium"})
        team = _make_team(
            per_release_tickets=[{"summary": "S", "fields": {"a": 1}}],
        )
        console, buf = _stderr_console()
        merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=console,
        )
        assert team.per_release_tickets[0].fields == {
            "a": 1, "priority": "Medium",
        }
        assert buf.getvalue() == ""

    def test_mc3_org_vs_team_defaults_conflict_org_wins(self) -> None:
        """MC3: org.priority=High locks; team defaults priority=Medium dropped."""
        from jiramator.config_merge import merge_configs

        org = _make_org({"priority": "High"})
        team = _make_team(
            defaults_fields={"priority": "Medium"},
            per_release_tickets=[{"summary": "S", "fields": {}}],
        )
        console, buf = _stderr_console()
        merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=console,
        )
        # Layer-1 effective lock = High (org wins).
        assert team.defaults.fields == {"priority": "High"}
        # Template inherits High.
        assert team.per_release_tickets[0].fields == {"priority": "High"}
        # Exactly one warning, attributed to the org config.
        text = buf.getvalue()
        assert "locked by org config" in text
        assert "defaults.fields.priority" in text
        # Single warning line — count occurrences of "locked by".
        assert text.count("locked by") == 1

    def test_mc4_org_vs_template_conflict_skipping_team_defaults(self) -> None:
        """MC4: org.priority=High vs template.priority=Low (team defaults empty)."""
        from jiramator.config_merge import merge_configs

        org = _make_org({"priority": "High"})
        team = _make_team(
            per_release_tickets=[
                {"summary": "S", "fields": {"priority": "Low"}}
            ],
        )
        console, buf = _stderr_console()
        merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=console,
        )
        # Layer 2: effective team-level lock includes priority=High;
        # template's Low is dropped.
        assert team.per_release_tickets[0].fields == {"priority": "High"}
        text = buf.getvalue()
        # The template-level conflict is attributed to "team defaults"
        # (per the plan's simplification — the merged team-level layer is
        # the locker visible at layer 2). The user can inspect
        # team.defaults.fields to see the org-locked value.
        assert "locked by team defaults" in text
        assert "per_release_tickets[0].fields.priority" in text

    def test_mc5_three_layer_composition(self) -> None:
        """MC5: org > team-defaults > template, with two warnings."""
        from jiramator.config_merge import merge_configs

        org = _make_org({"priority": "High"})
        team = _make_team(
            defaults_fields={"priority": "Medium", "story_points": 0.5},
            per_release_tickets=[
                {
                    "summary": "S",
                    "fields": {
                        "priority": "Low",
                        "story_points": 1,
                        "summary_only": "x",
                    },
                },
            ],
        )
        console, buf = _stderr_console()
        merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=console,
        )
        merged = team.per_release_tickets[0].fields
        assert merged["priority"] == "High"           # org wins
        assert merged["story_points"] == 0.5          # team-defaults wins over template
        assert merged["summary_only"] == "x"          # untouched
        # Effective team-level lock layer reflects org override.
        assert team.defaults.fields == {
            "priority": "High", "story_points": 0.5,
        }
        text = buf.getvalue()
        # One warning at layer 1 (org vs team defaults: priority).
        assert "locked by org config" in text
        # At least one warning at layer 2 (team defaults vs template:
        # story_points; priority on this template is also a conflict but
        # attribution is "team defaults" per the simplification).
        assert "locked by team defaults" in text
        assert "story_points" in text

    def test_mc6_lists_concat_across_three_layers(self) -> None:
        """MC6: list values concat earlier-first across all three layers."""
        from jiramator.config_merge import merge_configs

        org = _make_org({"customfield_10273": [{"value": "No"}]})
        team = _make_team(
            defaults_fields={"customfield_10273": [{"value": "Yes"}]},
            per_release_tickets=[
                {
                    "summary": "S",
                    "fields": {"customfield_10273": [{"value": "Maybe"}]},
                },
            ],
        )
        console, buf = _stderr_console()
        merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=console,
        )
        assert team.per_release_tickets[0].fields["customfield_10273"] == [
            {"value": "No"},
            {"value": "Yes"},
            {"value": "Maybe"},
        ]
        assert buf.getvalue() == ""

    def test_mc7_does_not_mutate_source_dicts(self) -> None:
        """MC7: input org.default_fields is not mutated (shape preserved)."""
        from jiramator.config_merge import merge_configs

        org_defaults = {"priority": "Medium"}
        org_defaults_snapshot = copy.deepcopy(org_defaults)
        org = _make_org(org_defaults)
        team = _make_team(
            per_release_tickets=[{"summary": "S", "fields": {"a": 1}}],
        )
        console, _ = _stderr_console()
        merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=console,
        )
        # The original dict object passed in must be unchanged.
        assert org_defaults == org_defaults_snapshot

    def test_mc8_warnings_route_to_stderr_when_console_none(
        self, capsys
    ) -> None:
        """MC8: with console=None, warnings flow via Console(stderr=True)."""
        from jiramator.config_merge import merge_configs

        org = _make_org({"priority": "High"})
        team = _make_team(
            defaults_fields={"priority": "Medium"},
            per_release_tickets=[{"summary": "S", "fields": {}}],
        )
        merge_configs(
            org_model=org,
            org_tagged_raw={},
            org_file=self.ORG_FILE,
            team_model=team,
            team_tagged_raw={},
            team_file=self.TEAM_FILE,
            console=None,
        )
        out = capsys.readouterr()
        assert out.out == ""
        assert "locked by org config" in out.err
