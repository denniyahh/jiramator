"""Shared test fixtures for Jiramator."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIGS_DIR = Path(__file__).parent.parent / "configs"


@pytest.fixture
def org_config_path():
    """Path to the example org config."""
    return CONFIGS_DIR / "org.example" / "example.yaml"


@pytest.fixture
def team_config_path():
    """Path to the Calcs team config fixture.

    Lives under tests/fixtures/ (tracked) rather than configs/teams/
    (gitignored, personal/team-specific) so the test suite is reproducible
    on a fresh clone regardless of local config state.
    """
    return FIXTURES_DIR / "teams" / "calcs.yaml"


@pytest.fixture(autouse=True)
def _isolate_runs_dir(tmp_path, monkeypatch):
    """Keep default-path run reports out of the repo's real ``.jiramator/runs``.

    Commands invoked without ``--report`` write to ``RUNS_DIR``; point it at a
    per-test temp dir (same ``.jiramator/runs`` suffix, so path-shape
    assertions still hold). Tests that set ``RUNS_DIR`` themselves override this.
    """
    monkeypatch.setattr(
        "jiramator.run_report.RUNS_DIR", tmp_path / ".jiramator" / "runs"
    )
