"""Shared test fixtures for Jiramator."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

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


# ---------------------------------------------------------------------------
# Createmeta stub
# ---------------------------------------------------------------------------


class PermissiveFieldMeta(dict):
    """Createmeta field metadata that treats every field as on-screen and optional.

    Live ``run_import`` tests use bare ``MagicMock()`` clients. Once the import
    preflight runs on live imports, iterating ``MagicMock().get_createmeta_*``
    yields nothing, so every row would fail with "Issue type … is not available"
    or every sent field would be reported off-screen (D-10) — RESEARCH Pitfall 1.

    This dict answers lookups permissively while iterating only the explicitly
    supplied descriptors:

    * ``get(key)`` / ``meta[key]`` return the explicit descriptor when present,
      otherwise ``{"name": key, "required": False}`` — no ``schema`` and no
      ``allowedValues``, so no required/ADF/option problem can arise.
    * ``key in meta`` is always True (nothing is off-screen).
    * ``items()`` / ``keys()`` / iteration / ``len()`` see only explicit entries,
      so the required-field pass only checks what a test opted into.
    """

    def get(self, key: Any, default: Any = None) -> Any:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        return {"name": key, "required": False}

    def __missing__(self, key: Any) -> dict[str, Any]:
        return {"name": key, "required": False}

    def __contains__(self, key: object) -> bool:
        return True


def stub_createmeta(
    client: Any,
    issue_types: Sequence[str] = ("Risk",),
    fields_by_type: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> Any:
    """Stub a mock Jira client's createmeta endpoints for live import tests.

    Args:
        client: A ``MagicMock`` standing in for ``JiraClient``.
        issue_types: Issue type names the project offers; ids are assigned
            ``"10000"``, ``"10001"``, … in order.
        fields_by_type: Optional explicit field descriptors per issue type name.
            Fields not listed are permissively on-screen and optional (see
            ``PermissiveFieldMeta``); list descriptors to opt into real problems.

    Returns:
        The same client, for chaining.
    """
    explicit = fields_by_type or {}
    types = [
        {"id": str(10000 + i), "name": name, "subtask": False}
        for i, name in enumerate(issue_types)
    ]
    name_by_id = {t["id"]: t["name"] for t in types}

    def _fields(project_key: str, issue_type_id: str) -> PermissiveFieldMeta:
        name = name_by_id.get(str(issue_type_id), "")
        return PermissiveFieldMeta(explicit.get(name, {}))

    client.get_createmeta_issue_types.return_value = types
    client.get_createmeta_fields.side_effect = _fields
    return client
