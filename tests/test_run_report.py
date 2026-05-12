"""Tests for jiramator/run_report.py — run report schema, atomic IO, resume
discovery, hash determinism, and ConfigDriftError exception (FOUND-02).

Plan: 01-03 Task 1.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from jiramator.run_report import (
    SCHEMA_VERSION,
    ConfigDriftError,
    IssueResult,
    RunReport,
    compute_resolved_hash,
    default_report_path,
    find_resumable,
    write_report_atomic,
)


# ---------------------------------------------------------------------------
# Envelope round-trip
# ---------------------------------------------------------------------------


class TestEnvelopeRoundTrip:
    def test_1_empty_report_round_trips(self):
        """Empty RunReport → to_envelope → json → from_envelope → equal."""
        original = RunReport()
        envelope = original.to_envelope()
        roundtripped = RunReport.from_envelope(json.loads(json.dumps(envelope)))
        assert asdict(roundtripped) == asdict(original)

    def test_2_populated_report_round_trips_with_nested_issues(self):
        """Populated RunReport with 3 IssueResults round-trips; nested
        instances are reconstituted as IssueResult dataclasses."""
        original = RunReport(
            command=["jiramator", "plan", "--pi", "PI28"],
            started_at="2026-04-29T10:00:00Z",
            ended_at="2026-04-29T10:05:00Z",
            team_config_path="/abs/team.yaml",
            org_config_path="/abs/org.yaml",
            team_name="Calcs",
            pi_label="PI28",
            versions=["28.1", "28.2"],
            resolved_config_hash="a" * 64,
            status="partial",
            counts={"created": 5, "skipped": 1, "failed": 1},
            issues=[
                IssueResult("epic-foo", "epic", "created", jira_key="CA-1"),
                IssueResult("rel-bar", "per_release", "failed", error="boom"),
                IssueResult("sprint-baz", "per_sprint", "pending"),
            ],
        )
        roundtripped = RunReport.from_envelope(
            json.loads(json.dumps(original.to_envelope()))
        )
        assert asdict(roundtripped) == asdict(original)
        # Nested issues are IssueResult instances, not plain dicts
        assert all(isinstance(i, IssueResult) for i in roundtripped.issues)

    def test_3_schema_version_zero_rejected_with_both_versions_named(self):
        with pytest.raises(ValueError) as exc_info:
            RunReport.from_envelope({"schema_version": 0, "run": {}})
        msg = str(exc_info.value)
        assert "0" in msg
        assert "1" in msg

    def test_4_schema_version_two_rejected(self):
        """Forward-incompat — schema 2 is reserved for a future migration plan."""
        with pytest.raises(ValueError):
            RunReport.from_envelope({"schema_version": 2, "run": {}})

    def test_5_missing_schema_version_rejected(self):
        """No schema_version key at all → treats as None != 1 → rejects."""
        with pytest.raises(ValueError):
            RunReport.from_envelope({})


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_6_write_produces_parseable_envelope(self, tmp_path):
        report = RunReport(team_name="X")
        out = tmp_path / "out.json"
        write_report_atomic(report, out)
        assert out.exists()
        loaded = json.loads(out.read_text())
        assert loaded == report.to_envelope()

    def test_7_parent_directory_auto_created(self, tmp_path):
        out = tmp_path / "deep" / "nested" / "out.json"
        write_report_atomic(RunReport(), out)
        assert out.exists()
        assert out.parent.is_dir()

    def test_8_failed_replace_leaves_original_intact_and_no_temp_files(
        self, tmp_path, monkeypatch
    ):
        out = tmp_path / "report.json"
        canary = b'{"canary": true}'
        out.write_bytes(canary)

        def _fail(*_a, **_kw):
            raise OSError("simulated replace failure")

        monkeypatch.setattr("os.replace", _fail)
        with pytest.raises(OSError):
            write_report_atomic(RunReport(team_name="new"), out)

        # Original file unchanged
        assert out.read_bytes() == canary
        # No leftover temp files in parent dir
        leftovers = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob("tmp*"))
        assert leftovers == []

    def test_9_two_writes_last_writer_wins(self, tmp_path):
        out = tmp_path / "out.json"
        write_report_atomic(RunReport(team_name="A"), out)
        write_report_atomic(RunReport(team_name="B"), out)
        envelope = json.loads(out.read_text())
        assert envelope["run"]["team_name"] == "B"


# ---------------------------------------------------------------------------
# default_report_path
# ---------------------------------------------------------------------------


class TestDefaultReportPath:
    def test_10_filename_matches_stamp_and_slug_pattern(self):
        import re
        p = default_report_path(Path("/tmp/teams/team-a.yaml"))
        assert re.match(
            r"^\d{8}T\d{6}Z-team-a\.json$", p.name
        ), f"unexpected filename: {p.name!r}"

    def test_11_slug_excludes_yaml_suffix(self):
        p = default_report_path(Path("/tmp/team-a.yaml"))
        assert p.name.endswith("-team-a.json")
        assert ".yaml" not in p.name

    def test_12_slug_replaces_path_separator_with_underscore(self):
        # Even unusual stems remain safe as filenames.
        p = default_report_path(Path("a/b/c.yaml"))
        # Path("a/b/c.yaml").stem == "c" (Path.stem strips the directory),
        # but the helper documents `/` → `_` for defense in depth.
        assert p.name.endswith("-c.json")


# ---------------------------------------------------------------------------
# find_resumable
# ---------------------------------------------------------------------------


class TestFindResumable:
    def test_13_runs_dir_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("jiramator.run_report.RUNS_DIR", tmp_path / "missing")
        assert find_resumable(Path("/whatever/team.yaml")) is None

    def test_14_runs_dir_empty_returns_none(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.setattr("jiramator.run_report.RUNS_DIR", runs)
        assert find_resumable(Path("/whatever/team.yaml")) is None

    def test_15_returns_most_recent_non_success(
        self, tmp_path, monkeypatch
    ):
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.setattr("jiramator.run_report.RUNS_DIR", runs)

        team_path = tmp_path / "team.yaml"
        team_path.write_text("team_name: x\n")
        resolved = str(team_path.resolve())

        def _emit(name, started_at, status):
            r = RunReport(
                team_config_path=resolved,
                started_at=started_at,
                status=status,
            )
            (runs / name).write_text(json.dumps(r.to_envelope()))

        _emit("A.json", "2026-04-27T10:00:00Z", "failed")
        _emit("B.json", "2026-04-28T11:00:00Z", "partial")
        _emit("C.json", "2026-04-28T12:00:00Z", "success")

        result = find_resumable(team_path)
        assert result is not None
        assert result.name == "B.json"

    def test_16_only_matching_team_path_considered(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.setattr("jiramator.run_report.RUNS_DIR", runs)

        my_team = tmp_path / "mine.yaml"
        my_team.write_text("x")
        other_team = tmp_path / "other.yaml"
        other_team.write_text("y")

        for name, team in [("mine.json", my_team), ("other.json", other_team)]:
            r = RunReport(
                team_config_path=str(team.resolve()),
                started_at="2026-04-29T10:00:00Z",
                status="failed",
            )
            (runs / name).write_text(json.dumps(r.to_envelope()))

        result = find_resumable(my_team)
        assert result is not None
        assert result.name == "mine.json"

    def test_17_corrupt_json_silently_skipped(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.setattr("jiramator.run_report.RUNS_DIR", runs)

        team_path = tmp_path / "team.yaml"
        team_path.write_text("x")

        # Corrupt sibling
        (runs / "corrupt.json").write_bytes(b"\x00\x01not json")
        # Valid candidate
        r = RunReport(
            team_config_path=str(team_path.resolve()),
            started_at="2026-04-29T10:00:00Z",
            status="failed",
        )
        (runs / "valid.json").write_text(json.dumps(r.to_envelope()))

        result = find_resumable(team_path)
        assert result is not None
        assert result.name == "valid.json"

    def test_18_missing_run_key_silently_skipped(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.setattr("jiramator.run_report.RUNS_DIR", runs)

        team_path = tmp_path / "team.yaml"
        team_path.write_text("x")

        (runs / "garbage.json").write_text(json.dumps({"schema_version": 1}))
        r = RunReport(
            team_config_path=str(team_path.resolve()),
            started_at="2026-04-29T10:00:00Z",
            status="failed",
        )
        (runs / "valid.json").write_text(json.dumps(r.to_envelope()))

        result = find_resumable(team_path)
        assert result is not None
        assert result.name == "valid.json"

    @pytest.mark.skipif(sys.platform == "win32", reason="symlink semantics differ on Windows")
    def test_19_path_matching_uses_resolve(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.setattr("jiramator.run_report.RUNS_DIR", runs)

        real_team = tmp_path / "real_team.yaml"
        real_team.write_text("x")
        symlink_team = tmp_path / "linked_team.yaml"
        symlink_team.symlink_to(real_team)

        r = RunReport(
            team_config_path=str(real_team.resolve()),
            started_at="2026-04-29T10:00:00Z",
            status="failed",
        )
        (runs / "v.json").write_text(json.dumps(r.to_envelope()))

        # Both paths should resolve to the same target → same find_resumable result.
        via_real = find_resumable(real_team)
        via_link = find_resumable(symlink_team)
        assert via_real is not None
        assert via_link is not None
        assert via_real == via_link


# ---------------------------------------------------------------------------
# compute_resolved_hash determinism
# ---------------------------------------------------------------------------


class TestResolvedHash:
    def test_20_two_invocations_same_inputs_same_hash(
        self, org_config_path, team_config_path
    ):
        from jiramator.config import load_org_config, load_team_config
        org, _ = load_org_config(org_config_path)
        team, _ = load_team_config(team_config_path)
        h1 = compute_resolved_hash(org, team, "PI28", ["26.1.1", "26.1.2"])
        h2 = compute_resolved_hash(org, team, "PI28", ["26.1.1", "26.1.2"])
        assert h1 == h2
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)

    def test_21_versions_order_matters(self, org_config_path, team_config_path):
        from jiramator.config import load_org_config, load_team_config
        org, _ = load_org_config(org_config_path)
        team, _ = load_team_config(team_config_path)
        h_ascending = compute_resolved_hash(org, team, "PI28", ["26.1.1", "26.1.2"])
        h_descending = compute_resolved_hash(org, team, "PI28", ["26.1.2", "26.1.1"])
        assert h_ascending != h_descending

    def test_22_pi_label_change_changes_hash(
        self, org_config_path, team_config_path
    ):
        from jiramator.config import load_org_config, load_team_config
        org, _ = load_org_config(org_config_path)
        team, _ = load_team_config(team_config_path)
        h1 = compute_resolved_hash(org, team, "PI28", ["26.1.1"])
        h2 = compute_resolved_hash(org, team, "PI29", ["26.1.1"])
        assert h1 != h2

    def test_23_team_name_change_changes_hash(
        self, org_config_path, team_config_path
    ):
        from jiramator.config import load_org_config, load_team_config
        org, _ = load_org_config(org_config_path)
        team, _ = load_team_config(team_config_path)
        h1 = compute_resolved_hash(org, team, "PI28", ["26.1.1"])
        # Mutate a copy via re-construction (Pydantic models are kinda-mutable
        # but we go through model_copy for cleanliness).
        team_b = team.model_copy(update={"team_name": "DIFFERENT"})
        h2 = compute_resolved_hash(org, team_b, "PI28", ["26.1.1"])
        assert h1 != h2

    def test_24_reload_same_yaml_same_hash(
        self, org_config_path, team_config_path
    ):
        """Two independent loads of the same YAML produce the same hash."""
        from jiramator.config import load_org_config, load_team_config
        org_a, _ = load_org_config(org_config_path)
        team_a, _ = load_team_config(team_config_path)
        org_b, _ = load_org_config(org_config_path)
        team_b, _ = load_team_config(team_config_path)
        h_a = compute_resolved_hash(org_a, team_a, "PI28", ["26.1.1"])
        h_b = compute_resolved_hash(org_b, team_b, "PI28", ["26.1.1"])
        assert h_a == h_b


# ---------------------------------------------------------------------------
# ConfigDriftError
# ---------------------------------------------------------------------------


class TestConfigDriftError:
    def test_25_is_exception_not_value_error(self):
        """ConfigDriftError must subclass Exception (not ValueError) so
        cli.py can catch it specifically without swallowing other ValueError
        paths from config loading."""
        assert issubclass(ConfigDriftError, Exception)
        assert not issubclass(ConfigDriftError, ValueError)
        # Constructible
        with pytest.raises(ConfigDriftError):
            raise ConfigDriftError("test")
