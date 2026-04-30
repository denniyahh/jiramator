"""CLI flag-parsing and error-handling unit tests.

Plan 01-05 Task 1 (C1-C14) and Task 2 (CI1-CI6).

These tests use ``CliRunner(mix_stderr=False)`` and stub out ``run_plan``,
``run_import``, ``find_resumable``, and ``read_spreadsheet`` at the
``jiramator.cli`` import site so we exercise wiring only — not planner
or importer internals, which are covered exhaustively in their own files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from jiramator.cli import cli
from jiramator.error_format import ConfigValidationError
from jiramator.run_report import (
    SCHEMA_VERSION,
    ConfigDriftError,
    IssueResult,
    RunReport,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    # Click 8.2+ separates stderr/stdout by default; mix_stderr was removed
    return CliRunner()


@pytest.fixture
def stub_run_plan(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``jiramator.cli.run_plan`` with a recorder that captures kwargs."""
    captured: dict[str, Any] = {}

    def _recorder(*args: Any, **kwargs: Any) -> None:
        captured["args"] = args
        captured["kwargs"] = kwargs

    monkeypatch.setattr("jiramator.cli.run_plan", _recorder)
    return captured


def _write_envelope(path: Path, *, team_config_path: str = "", status: str = "failed") -> None:
    """Write a minimal valid run-report envelope to *path*."""
    report = RunReport(
        schema_version=SCHEMA_VERSION,
        command=["jiramator", "plan"],
        started_at="2026-04-29T10:00:00+00:00",
        team_config_path=team_config_path,
        org_config_path="",
        team_name="test-team",
        pi_label="PI-28",
        versions=["v1"],
        resolved_config_hash="a" * 64,
        status=status,  # type: ignore[arg-type]
        counts={"created": 0, "skipped": 0, "failed": 0},
        issues=[],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_envelope()), encoding="utf-8")


def _plan_args(
    org_config_path: Path,
    team_config_path: Path,
    *extra: str,
) -> list[str]:
    return [
        "plan",
        "--org-config",
        str(org_config_path),
        "--team-config",
        str(team_config_path),
        *extra,
    ]


# ---------------------------------------------------------------------------
# Task 1 — plan command flag wiring (C1-C7)
# ---------------------------------------------------------------------------


class TestPlanCommandFlags:
    def test_C1_default_report_path_used_when_no_flag(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        result = runner.invoke(cli, _plan_args(org_config_path, team_config_path))

        assert result.exit_code == 0, result.stderr
        kwargs = stub_run_plan["kwargs"]
        # Default path should be a Path under .jiramator/runs/
        assert kwargs["report_path"] is not None
        rp = kwargs["report_path"]
        assert isinstance(rp, Path)
        assert ".jiramator" in str(rp) and "runs" in str(rp)
        assert kwargs["prior_report"] is None
        assert kwargs["force"] is False

    def test_C2_explicit_report_path(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        custom = tmp_path / "custom" / "r.json"
        result = runner.invoke(
            cli, _plan_args(org_config_path, team_config_path, "--report", str(custom))
        )

        assert result.exit_code == 0, result.stderr
        assert stub_run_plan["kwargs"]["report_path"] == custom

    def test_C3_resume_auto_uses_find_resumable(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        prior = tmp_path / "prior.json"
        _write_envelope(prior, team_config_path=str(team_config_path.resolve()))
        monkeypatch.setattr("jiramator.cli.find_resumable", lambda p: prior)

        result = runner.invoke(
            cli, _plan_args(org_config_path, team_config_path, "--resume")
        )

        assert result.exit_code == 0, result.stderr
        prior_report = stub_run_plan["kwargs"]["prior_report"]
        assert isinstance(prior_report, RunReport)
        assert prior_report.team_name == "test-team"

    def test_C4_resume_explicit_path_skips_find_resumable(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        prior = tmp_path / "explicit.json"
        _write_envelope(prior)
        called: list[Path] = []

        def _should_not_be_called(p: Path) -> Path | None:
            called.append(p)
            return None

        monkeypatch.setattr("jiramator.cli.find_resumable", _should_not_be_called)

        result = runner.invoke(
            cli,
            _plan_args(org_config_path, team_config_path, "--resume", str(prior)),
        )

        assert result.exit_code == 0, result.stderr
        assert called == []
        assert isinstance(stub_run_plan["kwargs"]["prior_report"], RunReport)

    def test_C5_force_threaded_through(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        prior = tmp_path / "prior.json"
        _write_envelope(prior)
        monkeypatch.setattr("jiramator.cli.find_resumable", lambda p: prior)

        result = runner.invoke(
            cli,
            _plan_args(org_config_path, team_config_path, "--resume", "--force"),
        )

        assert result.exit_code == 0, result.stderr
        assert stub_run_plan["kwargs"]["force"] is True

    def test_C6_resume_auto_with_no_resumable_run_exits_1(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        monkeypatch.setattr("jiramator.cli.find_resumable", lambda p: None)

        result = runner.invoke(
            cli, _plan_args(org_config_path, team_config_path, "--resume")
        )

        assert result.exit_code == 1
        assert "No resumable run found" in result.stderr
        assert "--resume <path>" in result.stderr
        assert "kwargs" not in stub_run_plan  # run_plan was not called

    def test_C7_force_without_resume_is_accepted(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        result = runner.invoke(
            cli, _plan_args(org_config_path, team_config_path, "--force")
        )

        assert result.exit_code == 0, result.stderr
        assert stub_run_plan["kwargs"]["force"] is True
        assert stub_run_plan["kwargs"]["prior_report"] is None


# ---------------------------------------------------------------------------
# Task 1 — error handling (C8-C14)
# ---------------------------------------------------------------------------


class TestPlanCommandErrors:
    def test_C8_config_validation_error_from_org_load(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        err = ConfigValidationError(
            file=Path("configs/org/acme.yaml"),
            line=5,
            field_path="org.custom_fields.epic_link",
            reason="unknown alias 'eipc'",
            suggestion="(did you mean 'epic'?)",
        )
        expected = str(err)

        def _raise(_path: Path):
            raise err

        monkeypatch.setattr("jiramator.cli.load_org_config", _raise)

        result = runner.invoke(cli, _plan_args(org_config_path, team_config_path))

        assert result.exit_code == 1
        # Plain-text on stderr — no Rich [red bold] markup tags
        assert expected in result.stderr
        assert "[red" not in result.stderr
        assert "[/" not in result.stderr

    def test_C9_config_validation_error_from_team_load(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        err = ConfigValidationError(
            file=Path("configs/teams/calcs.yaml"),
            line=12,
            field_path="team.project_key",
            reason="must not be empty",
        )
        expected = str(err)

        def _raise(_path: Path):
            raise err

        monkeypatch.setattr("jiramator.cli.load_team_config", _raise)

        result = runner.invoke(cli, _plan_args(org_config_path, team_config_path))

        assert result.exit_code == 1
        assert expected in result.stderr
        assert "[red" not in result.stderr

    def test_C10_config_drift_error_from_run_plan(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        drift_msg = (
            "Config has drifted since the prior run; resume is unsafe.\n"
            "  prior hash:   abc123def456\n"
            "  current hash: 999888777666"
        )
        call_count = {"n": 0}

        def _raise(*args: Any, **kwargs: Any) -> None:
            call_count["n"] += 1
            raise ConfigDriftError(drift_msg)

        monkeypatch.setattr("jiramator.cli.run_plan", _raise)

        result = runner.invoke(cli, _plan_args(org_config_path, team_config_path))

        assert result.exit_code == 1
        assert "Config has drifted" in result.stderr
        assert "prior hash:" in result.stderr
        assert "current hash:" in result.stderr
        assert call_count["n"] == 1

    def test_C11_value_error_still_handled(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        # Non-validation ValueError should still be caught by the legacy clause
        def _raise(_path: Path):
            raise ValueError("malformed YAML somehow")

        monkeypatch.setattr("jiramator.cli.load_org_config", _raise)

        result = runner.invoke(cli, _plan_args(org_config_path, team_config_path))

        assert result.exit_code == 1
        # The decorative path uses Rich; check stderr contains the message
        assert "malformed YAML" in result.stderr

    def test_C12_resume_explicit_path_missing_exits_1(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / "does_not_exist.json"

        result = runner.invoke(
            cli,
            _plan_args(org_config_path, team_config_path, "--resume", str(missing)),
        )

        assert result.exit_code == 1
        assert "Resume report not found" in result.stderr
        assert str(missing) in result.stderr
        assert "kwargs" not in stub_run_plan

    def test_C13_resume_corrupt_json_exits_1(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{not valid json at all", encoding="utf-8")

        result = runner.invoke(
            cli,
            _plan_args(org_config_path, team_config_path, "--resume", str(corrupt)),
        )

        assert result.exit_code == 1
        assert "Could not parse resume report" in result.stderr
        assert "kwargs" not in stub_run_plan

    def test_C14_resume_incompatible_schema_version_exits_1(
        self,
        runner: CliRunner,
        stub_run_plan: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        bad = tmp_path / "future.json"
        bad.write_text(
            json.dumps({"schema_version": 9999, "run": {}}), encoding="utf-8"
        )

        result = runner.invoke(
            cli,
            _plan_args(org_config_path, team_config_path, "--resume", str(bad)),
        )

        assert result.exit_code == 1
        assert "Resume report incompatible" in result.stderr
        assert "kwargs" not in stub_run_plan


# ---------------------------------------------------------------------------
# Task 2 — import command flag wiring (CI1-CI6)
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_run_import(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``jiramator.cli.run_import`` with a recorder.

    Also stubs the renderers so the cli's tail (which calls ``render_preview_report``
    and ``render_import_execution_report``) doesn't trip over the fake result.
    """
    captured: dict[str, Any] = {}

    class _FakePreview:
        row_results: list = []

    class _FakeResult:
        preview = _FakePreview()
        created: list = []
        skipped: list = []
        failed: list = []

    def _recorder(*args: Any, **kwargs: Any) -> Any:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeResult()

    monkeypatch.setattr("jiramator.cli.run_import", _recorder)
    monkeypatch.setattr("jiramator.cli.render_preview_report", lambda *a, **kw: "")
    monkeypatch.setattr(
        "jiramator.cli.render_import_execution_report", lambda *a, **kw: ""
    )
    return captured


@pytest.fixture
def stub_read_spreadsheet(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace ``jiramator.cli.read_spreadsheet`` with a recorder."""
    captured: dict[str, Any] = {}

    def _recorder(path: Path, **kwargs: Any) -> list[dict[str, str]]:
        captured["path"] = path
        captured["kwargs"] = kwargs
        return [{"Summary": "Row A"}]

    monkeypatch.setattr("jiramator.cli.read_spreadsheet", _recorder)
    return captured


@pytest.fixture
def stub_jira_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``jiramator.cli.JiraClient`` with a no-op double."""

    class _FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def get_fields(self) -> list[dict[str, Any]]:
            return []

    monkeypatch.setattr("jiramator.cli.JiraClient", _FakeClient)


def _import_args(
    org_config_path: Path,
    team_config_path: Path,
    spreadsheet: Path,
    *extra: str,
) -> list[str]:
    return [
        "import",
        "--org-config",
        str(org_config_path),
        "--team-config",
        str(team_config_path),
        *extra,
        str(spreadsheet),
    ]


class TestImportCommandFlags:
    def test_CI1_explicit_encoding_threaded_through(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        stub_read_spreadsheet: dict[str, Any],
        stub_jira_client: None,
        stub_run_import: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        sheet = tmp_path / "input.csv"
        sheet.write_text("Summary\nRow A\n", encoding="utf-8")

        result = runner.invoke(
            cli,
            _import_args(
                org_config_path, team_config_path, sheet, "--encoding", "cp1252"
            ),
        )

        assert result.exit_code == 0, result.stderr
        assert stub_read_spreadsheet["kwargs"]["encoding_override"] == "cp1252"

    def test_CI2_no_encoding_flag_passes_none(
        self,
        runner: CliRunner,
        stub_read_spreadsheet: dict[str, Any],
        stub_jira_client: None,
        stub_run_import: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        sheet = tmp_path / "input.csv"
        sheet.write_text("Summary\nRow A\n", encoding="utf-8")

        result = runner.invoke(
            cli, _import_args(org_config_path, team_config_path, sheet)
        )

        assert result.exit_code == 0, result.stderr
        assert stub_read_spreadsheet["kwargs"]["encoding_override"] is None

    def test_CI3_explicit_report_path_threaded_through(
        self,
        runner: CliRunner,
        stub_read_spreadsheet: dict[str, Any],
        stub_jira_client: None,
        stub_run_import: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        sheet = tmp_path / "input.csv"
        sheet.write_text("Summary\nRow A\n", encoding="utf-8")
        custom = tmp_path / "custom" / "i.json"

        result = runner.invoke(
            cli,
            _import_args(
                org_config_path, team_config_path, sheet, "--report", str(custom)
            ),
        )

        assert result.exit_code == 0, result.stderr
        assert stub_run_import["kwargs"]["report_path"] == custom
        # Report should have been written by cli at the end of the run.
        assert custom.exists()

    def test_CI4_resume_auto_uses_find_resumable(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        stub_read_spreadsheet: dict[str, Any],
        stub_jira_client: None,
        stub_run_import: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        # Build an envelope whose hash matches what cli.import_command will
        # compute (so the drift check passes). compute_resolved_hash for
        # import uses (org, team, None, []).
        from jiramator.config import load_org_config, load_team_config
        from jiramator.run_report import compute_resolved_hash

        org_config, _ = load_org_config(org_config_path)
        team_config, _ = load_team_config(team_config_path)
        current_hash = compute_resolved_hash(org_config, team_config, None, [])

        prior = tmp_path / "prior.json"
        report = RunReport(
            command=["jiramator", "import"],
            started_at="2026-04-29T10:00:00+00:00",
            team_config_path=str(team_config_path.resolve()),
            org_config_path=str(org_config_path.resolve()),
            team_name=team_config.team_name,
            pi_label=None,
            versions=[],
            resolved_config_hash=current_hash,
            status="failed",
        )
        prior.write_text(json.dumps(report.to_envelope()), encoding="utf-8")

        monkeypatch.setattr("jiramator.cli.find_resumable", lambda p: prior)

        sheet = tmp_path / "input.csv"
        sheet.write_text("Summary\nRow A\n", encoding="utf-8")

        # Click consumes the positional aggressively when --resume (no value)
        # appears immediately before it; place --resume AFTER the positional
        # to use flag_value="auto" cleanly.
        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(org_config_path),
                "--team-config",
                str(team_config_path),
                str(sheet),
                "--resume",
            ],
        )

        assert result.exit_code == 0, result.stderr
        prior_report = stub_run_import["kwargs"]["prior_report"]
        assert isinstance(prior_report, RunReport)
        assert prior_report.team_name == team_config.team_name

    def test_CI5_resume_explicit_path_skips_find_resumable(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        stub_read_spreadsheet: dict[str, Any],
        stub_jira_client: None,
        stub_run_import: dict[str, Any],
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        from jiramator.config import load_org_config, load_team_config
        from jiramator.run_report import compute_resolved_hash

        org_config, _ = load_org_config(org_config_path)
        team_config, _ = load_team_config(team_config_path)
        current_hash = compute_resolved_hash(org_config, team_config, None, [])

        prior = tmp_path / "explicit.json"
        report = RunReport(
            command=["jiramator", "import"],
            started_at="2026-04-29T10:00:00+00:00",
            team_config_path=str(team_config_path.resolve()),
            org_config_path="",
            team_name=team_config.team_name,
            resolved_config_hash=current_hash,
            status="partial",
        )
        prior.write_text(json.dumps(report.to_envelope()), encoding="utf-8")

        called: list[Path] = []
        monkeypatch.setattr(
            "jiramator.cli.find_resumable", lambda p: called.append(p) or None
        )

        sheet = tmp_path / "input.csv"
        sheet.write_text("Summary\nRow A\n", encoding="utf-8")

        result = runner.invoke(
            cli,
            _import_args(
                org_config_path,
                team_config_path,
                sheet,
                "--resume",
                str(prior),
            ),
        )

        assert result.exit_code == 0, result.stderr
        assert called == []
        assert isinstance(stub_run_import["kwargs"]["prior_report"], RunReport)

    def test_CI6_config_validation_error_in_import(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
        tmp_path: Path,
    ) -> None:
        err = ConfigValidationError(
            file=Path("configs/teams/calcs.yaml"),
            line=12,
            field_path="team.project_key",
            reason="must not be empty",
        )
        expected = str(err)

        def _raise(_path: Path):
            raise err

        monkeypatch.setattr("jiramator.cli.load_team_config", _raise)

        sheet = tmp_path / "input.csv"
        sheet.write_text("Summary\nRow A\n", encoding="utf-8")

        result = runner.invoke(
            cli, _import_args(org_config_path, team_config_path, sheet)
        )

        assert result.exit_code == 1
        assert expected in result.stderr
        assert "[red" not in result.stderr


# ===========================================================================
# Phase 02-02 — CLI plan command wires merge_configs between loads + run_plan
# ===========================================================================


class TestPlanCommandMergeWiring:
    """Verify the `plan` command unpacks loader tuples and calls merge_configs."""

    def test_cl1_plan_unpacks_loader_tuples(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        """CL1: plan command runs cleanly with the new tuple-returning loaders."""
        from jiramator import cli as cli_mod

        def _stub_run_plan(*_args, **_kwargs):
            return None

        monkeypatch.setattr(cli_mod, "run_plan", _stub_run_plan)
        result = runner.invoke(
            cli, _plan_args(org_config_path, team_config_path, "--dry-run")
        )
        assert result.exit_code == 0, result.output

    def test_cl2_plan_calls_merge_configs(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        org_config_path: Path,
        team_config_path: Path,
    ) -> None:
        """CL2: plan command invokes merge_configs between loads and run_plan."""
        from jiramator import cli as cli_mod
        from jiramator import config_merge as cm_mod

        calls: list[dict] = []
        original = cm_mod.merge_configs

        def _recording(**kwargs):
            calls.append({k: v for k, v in kwargs.items() if k in (
                "org_file", "team_file"
            )})
            return original(**kwargs)

        # cli.py binds `merge_configs` at import time, so patch it on the
        # cli module (not on config_merge) to intercept the call.
        monkeypatch.setattr(cli_mod, "merge_configs", _recording)
        monkeypatch.setattr(cli_mod, "run_plan", lambda *a, **k: None)

        result = runner.invoke(
            cli, _plan_args(org_config_path, team_config_path, "--dry-run")
        )
        assert result.exit_code == 0, result.output
        assert len(calls) == 1
        assert calls[0]["team_file"] == team_config_path
