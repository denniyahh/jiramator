"""End-to-end CLI tests — Plan 01-05 Task 2 (E1, E2, E3).

These tests exercise the full wiring through ``jiramator.cli`` to the
underlying planner / importer / run_report stack with a FakeJiraClient
double. They are slower than the unit tests in ``test_cli.py`` but are
the only check that the layers compose correctly end to end.

Scope:
- E1: plan → report-on-disk → --resume → second plan skips already-created.
- E2: plan → mutate team config → --resume detects drift → --force overrides.
- E3: import --encoding cp1252 round-trip with smart-quote / em-dash / £.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from jiramator.cli import cli
from jiramator.jira_client import JiraApiError
from jiramator.run_report import RunReport


# ---------------------------------------------------------------------------
# Shared FakeJiraClient (mirrors tests/test_planner_report.py's double)
# ---------------------------------------------------------------------------


class FakeJiraClient:
    """Deterministic Jira double for E2E tests.

    Records every payload, asserts no `_template_key` leaks, returns
    ``FAKE-N`` keys monotonically.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.created: list[dict] = []
        self.bulk_created: list[list[dict]] = []
        self._next_id = 1

    @staticmethod
    def _assert_no_template_key(payload: dict) -> None:
        assert "_template_key" not in payload, payload
        assert "_template_key" not in payload.get("fields", {})

    # ---- planner surface ----
    def get_fix_versions(self, project_key: str) -> list[dict]:
        # Pretend everything exists so create_fix_version isn't called.
        return [{"name": "26.1.1"}, {"name": "26.1.2"}]

    def create_fix_version(self, project_key: str, name: str) -> dict:  # pragma: no cover
        return {"name": name, "id": "1"}

    def create_issue(self, payload: dict) -> str:
        self._assert_no_template_key(payload)
        self.created.append(payload)
        key = f"FAKE-{self._next_id}"
        self._next_id += 1
        return key

    def create_issues_bulk(self, payloads: list[dict]) -> list[str]:
        for p in payloads:
            self._assert_no_template_key(p)
        self.bulk_created.append(list(payloads))
        keys = []
        for _ in payloads:
            keys.append(f"FAKE-{self._next_id}")
            self._next_id += 1
        return keys

    # ---- importer surface ----
    def get_fields(self) -> list[dict]:
        return []

    def find_issue_keys_by_summaries(
        self, project_key: str, summaries: list[str]
    ) -> dict[str, str]:
        return {}

    # ---- unused but called ----
    def get_board_sprints(self, board_id: int) -> list[dict]:  # pragma: no cover
        return []

    def find_user_account_id(self, name: str) -> str | None:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# Helpers — minimal config writers
# ---------------------------------------------------------------------------


def _write_org_config(path: Path) -> None:
    """Minimal org config that loads cleanly."""
    path.write_text(
        """\
jira_url: https://example.atlassian.net
custom_fields: {}
sprints:
  count: 2
  standard_length_weeks: 2
  long_length_weeks: 3
  long_sprints: []
""",
        encoding="utf-8",
    )


def _write_team_config(path: Path, *, team_name: str = "TestTeam") -> None:
    """Minimal team config — one recurring epic, one per-release ticket."""
    path.write_text(
        f"""\
project_key: TST
team_name: {team_name}
board_id: 1
recurring_epics:
  - key: bau
    summary: "{{team_name}} {{pi_label}} BAU"
per_release_tickets:
  - summary: "Pre-reg {{version}}"
    fields:
      issuetype: Task
      fixVersions: ["{{version}}"]
""",
        encoding="utf-8",
    )


def _patch_prompts(
    pi: str = "28",
    n_versions: int = 1,
    versions: tuple[str, ...] = ("26.1.1",),
    confirm_yes: bool = True,
) -> list:
    """Stack of patches for all Rich prompts inside planner."""
    return [
        patch("jiramator.planner.Prompt.ask", side_effect=[pi, *versions]),
        patch("jiramator.planner.IntPrompt.ask", return_value=n_versions),
        patch("jiramator.planner.Confirm.ask", return_value=confirm_yes),
    ]


def _run_with_patches(patches: list, fn):
    if not patches:
        return fn()
    with patches[0]:
        return _run_with_patches(patches[1:], fn)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def configs(tmp_path: Path) -> dict[str, Path]:
    org = tmp_path / "org.yaml"
    team = tmp_path / "team.yaml"
    _write_org_config(org)
    _write_team_config(team)
    return {"org": org, "team": team}


# ---------------------------------------------------------------------------
# E1 — full plan → report → resume → skip cycle
# ---------------------------------------------------------------------------


class TestE1PlanRoundTrip:
    def test_e2e_plan_creates_report_and_resume_skips_already_created(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        configs: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        report_path = tmp_path / "r.json"
        fake = FakeJiraClient()

        # Wire JiraClient to our fake at BOTH cli and planner import sites.
        # Planner builds its own JiraClient at line ~571; cli builds one for
        # the import command; both must yield the fake.
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda *a, **kw: fake)
        monkeypatch.setattr("jiramator.planner.JiraClient", lambda *a, **kw: fake)

        # First run — fresh, should call create_issue + create_issues_bulk.
        with _patch_prompts()[0], _patch_prompts()[1], _patch_prompts()[2]:
            result = runner.invoke(
                cli,
                [
                    "plan",
                    "--org-config",
                    str(configs["org"]),
                    "--team-config",
                    str(configs["team"]),
                    "--report",
                    str(report_path),
                ],
            )

        assert result.exit_code == 0, result.stderr
        assert report_path.exists()

        envelope = json.loads(report_path.read_text(encoding="utf-8"))
        run = envelope["run"]
        assert run["status"] == "success"
        # 1 epic + 1 per-release ticket = 2 issues created.
        first_run_calls = len(fake.created) + sum(len(b) for b in fake.bulk_created)
        assert first_run_calls >= 2
        assert run["counts"]["created"] >= 2

        # Second run — --resume should skip already-created.
        fake_count_before_resume = (
            len(fake.created) + sum(len(b) for b in fake.bulk_created)
        )
        with _patch_prompts()[0], _patch_prompts()[1], _patch_prompts()[2]:
            result2 = runner.invoke(
                cli,
                [
                    "plan",
                    "--org-config",
                    str(configs["org"]),
                    "--team-config",
                    str(configs["team"]),
                    "--report",
                    str(report_path),
                    "--resume",
                    str(report_path),
                ],
            )

        assert result2.exit_code == 0, result2.stderr
        # No new issues should have been created on resume.
        fake_count_after_resume = (
            len(fake.created) + sum(len(b) for b in fake.bulk_created)
        )
        assert fake_count_after_resume == fake_count_before_resume, (
            f"Resume created new issues unexpectedly: "
            f"before={fake_count_before_resume}, after={fake_count_after_resume}"
        )


# ---------------------------------------------------------------------------
# E2 — drift detection
# ---------------------------------------------------------------------------


class TestE2DriftDetection:
    def test_e2e_resume_after_team_config_mutation_detects_drift(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        configs: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        report_path = tmp_path / "r.json"
        fake = FakeJiraClient()
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda *a, **kw: fake)
        monkeypatch.setattr("jiramator.planner.JiraClient", lambda *a, **kw: fake)

        # First run.
        with _patch_prompts()[0], _patch_prompts()[1], _patch_prompts()[2]:
            result = runner.invoke(
                cli,
                [
                    "plan",
                    "--org-config",
                    str(configs["org"]),
                    "--team-config",
                    str(configs["team"]),
                    "--report",
                    str(report_path),
                ],
            )
        assert result.exit_code == 0, result.stderr

        # Mutate team config — change team_name.
        _write_team_config(configs["team"], team_name="MutatedTeam")

        # Resume without --force → drift error.
        with _patch_prompts()[0], _patch_prompts()[1], _patch_prompts()[2]:
            result2 = runner.invoke(
                cli,
                [
                    "plan",
                    "--org-config",
                    str(configs["org"]),
                    "--team-config",
                    str(configs["team"]),
                    "--report",
                    str(report_path),
                    "--resume",
                    str(report_path),
                ],
            )
        assert result2.exit_code == 1
        assert "drifted" in result2.stderr.lower()
        assert "prior hash:" in result2.stderr
        assert "current hash:" in result2.stderr

        # Resume with --force → proceeds.
        with _patch_prompts()[0], _patch_prompts()[1], _patch_prompts()[2]:
            result3 = runner.invoke(
                cli,
                [
                    "plan",
                    "--org-config",
                    str(configs["org"]),
                    "--team-config",
                    str(configs["team"]),
                    "--report",
                    str(report_path),
                    "--resume",
                    str(report_path),
                    "--force",
                ],
            )
        assert result3.exit_code == 0, result3.stderr


# ---------------------------------------------------------------------------
# E3 — encoding round-trip
# ---------------------------------------------------------------------------


class TestE3EncodingRoundTrip:
    def test_e2e_import_with_explicit_encoding_passes_unicode_through(
        self,
        runner: CliRunner,
        monkeypatch: pytest.MonkeyPatch,
        configs: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        # Write a CP-1252 CSV containing smart-quote, em-dash, and £.
        # CP-1252 codepoints: 0x91=‘ 0x92=’ 0x93=“ 0x94=” 0x97=— 0xA3=£
        sheet = tmp_path / "cp1252_sample.csv"
        # Use lowercase "summary" so it matches the standard-field set in
        # field_resolver.py (which is case-sensitive — "Summary" does not match).
        text = "summary\n\u201cFix\u201d \u2014 \u00a3100 charge\n"
        sheet.write_bytes(text.encode("cp1252"))

        # Verify the file is NOT valid UTF-8 (sanity check).
        with pytest.raises(UnicodeDecodeError):
            sheet.read_text(encoding="utf-8")

        fake = FakeJiraClient()
        monkeypatch.setattr("jiramator.cli.JiraClient", lambda *a, **kw: fake)

        result = runner.invoke(
            cli,
            [
                "import",
                "--org-config",
                str(configs["org"]),
                "--team-config",
                str(configs["team"]),
                str(sheet),
                "--encoding",
                "cp1252",
            ],
        )

        assert result.exit_code == 0, result.stderr
        # FakeJiraClient.find_issue_keys_by_summaries returned {}, so import
        # tries to create the issue. Verify the unicode chars survived.
        all_payloads = fake.created + [p for batch in fake.bulk_created for p in batch]
        assert len(all_payloads) >= 1, "Expected at least one create_issue call"
        summaries_seen = [p.get("fields", {}).get("summary", "") for p in all_payloads]
        # Em-dash (\u2014) is the cleanest marker — survives only with cp1252.
        assert any("\u2014" in s for s in summaries_seen), summaries_seen
        assert any("\u00a3" in s for s in summaries_seen), summaries_seen
