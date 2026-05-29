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
    """Path to the Calcs team config."""
    return CONFIGS_DIR / "teams" / "calcs.yaml"
