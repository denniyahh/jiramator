"""Plan 01-04 Task 2: run_plan emits run report + consumes prior_report on resume.

Uses an inline FakeJiraClient (test double, not MagicMock) so we can:
  - record create_issue/create_issues_bulk calls and assert no _template_key leaks
  - inject failures after the Nth call to test partial-state persistence
  - simulate KeyboardInterrupt mid-run to verify atomic write under signal
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from jiramator.config import (
    EpicTemplate,
    OrgConfig,
    SprintConfig,
    TeamConfig,
    TicketTemplate,
)
from jiramator.jira_client import JiraApiError
from jiramator.planner import run_plan
from jiramator.run_report import (
    ConfigDriftError,
    IssueResult,
    RunReport,
    compute_resolved_hash,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org_config() -> OrgConfig:
    return OrgConfig(
        jira_url="https://example.atlassian.net",
        custom_fields={},
        sprints=SprintConfig(
            count=2, standard_length_weeks=2, long_length_weeks=3, long_sprints=[],
        ),
    )


@pytest.fixture
def team_config() -> TeamConfig:
    return TeamConfig(
        project_key="TST",
        team_name="TestTeam",
        recurring_epics=[
            EpicTemplate(key="bau", summary="{team_name} {pi_label} BAU"),
            EpicTemplate(key="misc", summary="{team_name} {pi_label} Misc"),
        ],
        per_release_tickets=[
            TicketTemplate(
                summary="Pre-reg {version}",
                fields={"issuetype": "Task", "fixVersions": ["{version}"]},
            ),
        ],
        per_sprint_tickets=[
            TicketTemplate(
                summary="Standup S{sprint_num}",
                fields={"issuetype": "Task"},
            ),
        ],
    )


@pytest.fixture
def console() -> Console:
    return Console(stderr=True, no_color=True, force_terminal=False)


# ---------------------------------------------------------------------------
# FakeJiraClient — test double
# ---------------------------------------------------------------------------


class FakeJiraClient:
    """A deterministic Jira client double for run_plan tests.

    Records every payload it receives and asserts no `_template_key` leaks
    into the data sent to Jira (T-01-16 mitigation).
    """

    def __init__(
        self,
        *,
        fail_create_issue_after: int | None = None,
        fail_bulk: bool = False,
        interrupt_create_issue_after: int | None = None,
        bulk_observer=None,
    ) -> None:
        self.created: list[dict] = []
        self.bulk_created: list[list[dict]] = []
        self._next_id = 1
        self._fail_create_after = fail_create_issue_after
        self._fail_bulk = fail_bulk
        self._interrupt_after = interrupt_create_issue_after
        self._bulk_observer = bulk_observer

    # ---- Strip-leak guard ----
    @staticmethod
    def _assert_no_template_key(payload: dict) -> None:
        assert "_template_key" not in payload, (
            f"_template_key leaked into Jira payload (T-01-16): {payload}"
        )
        # Also check fields layer — defensive
        fields = payload.get("fields", {})
        assert "_template_key" not in fields

    # ---- API surface used by planner ----
    def get_fix_versions(self, project_key):
        # Pretend everything exists so _check_and_create_fix_versions skips
        return [{"name": "26.1.1"}, {"name": "26.1.2"}]

    def create_fix_version(self, project_key, name):  # pragma: no cover
        return {"name": name, "id": "1"}

    def create_issue(self, payload: dict) -> str:
        self._assert_no_template_key(payload)
        idx = len(self.created)
        if self._interrupt_after is not None and idx >= self._interrupt_after:
            raise KeyboardInterrupt("simulated Ctrl-C")
        if self._fail_create_after is not None and idx >= self._fail_create_after:
            raise JiraApiError("simulated epic failure", status_code=500)
        self.created.append(payload)
        key = f"FAKE-{self._next_id}"
        self._next_id += 1
        return key

    def create_issues_bulk(self, payloads: list[dict]) -> list[str]:
        for p in payloads:
            self._assert_no_template_key(p)
        if self._bulk_observer is not None:
            self._bulk_observer(payloads)
        if self._fail_bulk:
            raise JiraApiError("simulated bulk failure", status_code=500)
        self.bulk_created.append(list(payloads))
        keys = []
        for _ in payloads:
            keys.append(f"FAKE-{self._next_id}")
            self._next_id += 1
        return keys

    def get_board_sprints(self, board_id):  # pragma: no cover
        return []

    def find_user_account_id(self, name):  # pragma: no cover
        return None

    def get_createmeta_fields_by_type_name(self, project_key, issue_type_name):
        # No metadata configured — nothing to check against, so the
        # pre-flight validator finds zero problems for every payload.
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _patch_prompts(*, pi="28", n_versions=1, versions=("26.1.1",), confirm_yes=True):
    """Build a context manager stack that stubs all interactive prompts."""
    return [
        patch("jiramator.planner.Prompt.ask", side_effect=[pi, *versions]),
        patch("jiramator.planner.IntPrompt.ask", return_value=n_versions),
        # Confirm: fix-version create, duplicate-warning ack
        patch("jiramator.planner.Confirm.ask", return_value=confirm_yes),
    ]


def _run_with_patches(patches, fn):
    if not patches:
        return fn()
    with patches[0]:
        return _run_with_patches(patches[1:], fn)


def _read_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# P1: dry-run still emits a report
# ---------------------------------------------------------------------------


class TestDryRunReport:
    def test_p1_dry_run_writes_report(self, org_config, team_config, console, tmp_path):
        report_path = tmp_path / "r.json"
        patches = _patch_prompts()

        def go():
            run_plan(
                org_config, team_config,
                dry_run=True, console=console,
                report_path=report_path,
                command=["jiramator", "plan", "--dry-run"],
            )

        _run_with_patches(patches, go)

        assert report_path.exists()
        env = _read_report(report_path)
        assert env["schema_version"] == 1
        run = env["run"]
        assert run["status"] == "success"
        assert run["counts"]["created"] == 0
        assert run["pi_label"] == "PI28"
        assert run["versions"] == ["26.1.1"]


# ---------------------------------------------------------------------------
# P2: successful live run — report has all created issues + no leak
# ---------------------------------------------------------------------------


class TestSuccessfulRun:
    def test_p2_success_report(self, org_config, team_config, console, tmp_path):
        report_path = tmp_path / "r.json"
        fake = FakeJiraClient()
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                run_plan(
                    org_config, team_config,
                    dry_run=False, console=console,
                    report_path=report_path,
                )

        _run_with_patches(patches, go)

        env = _read_report(report_path)
        run = env["run"]
        # 2 epics + 1 per_release × 1 version + 1 per_sprint × 2 sprints = 5
        assert run["counts"]["created"] == 5
        assert run["counts"]["failed"] == 0
        assert run["status"] == "success"

        # Every issue's template_key resolved to a jira_key
        keys = {i["template_key"]: i for i in run["issues"]}
        assert "epic:bau" in keys
        assert "epic:misc" in keys
        assert "per_release[0]:26.1.1" in keys
        assert "per_sprint[0]:1" in keys
        assert "per_sprint[0]:2" in keys
        for i in run["issues"]:
            assert i["status"] == "created"
            assert i["jira_key"] is not None and i["jira_key"].startswith("FAKE-")


# ---------------------------------------------------------------------------
# P3: report rewritten after each epic
# ---------------------------------------------------------------------------


class TestIncrementalEmission:
    def test_p3_report_rewritten_per_epic(
        self, org_config, team_config, console, tmp_path,
    ):
        """Capture the on-disk created count BEFORE each create_issue call.

        The planner persists *after* a successful create_issue. So at the
        moment we enter call N, the file reflects N-1 created issues. This
        proves the file is being rewritten between calls (vs only at end).
        """
        report_path = tmp_path / "r.json"
        snapshots: list[int] = []
        original_create = FakeJiraClient.create_issue

        def spy_create(self, payload):
            # Snapshot BEFORE call — should grow monotonically across calls.
            if report_path.exists():
                env = _read_report(report_path)
                snapshots.append(env["run"]["counts"].get("created", 0))
            else:
                snapshots.append(-1)
            return original_create(self, payload)

        fake = FakeJiraClient()
        patches = _patch_prompts()

        def go():
            with patch.object(FakeJiraClient, "create_issue", spy_create):
                with patch("jiramator.planner.JiraClient", return_value=fake):
                    run_plan(
                        org_config, team_config,
                        dry_run=False, console=console,
                        report_path=report_path,
                    )

        _run_with_patches(patches, go)
        # Before 1st epic: count=0 (only initial state persisted).
        # Before 2nd epic: count=1 (1st was persisted between calls).
        assert snapshots[0] == 0
        assert snapshots[1] == 1


# ---------------------------------------------------------------------------
# P4: epic creation fails midway → status=partial
# ---------------------------------------------------------------------------


class TestPartialFailure:
    def test_p4_epic_failure_partial(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        fake = FakeJiraClient(fail_create_issue_after=1)  # fail on 2nd epic
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                with pytest.raises(SystemExit):
                    run_plan(
                        org_config, team_config,
                        dry_run=False, console=console,
                        report_path=report_path,
                    )

        _run_with_patches(patches, go)

        env = _read_report(report_path)
        run = env["run"]
        # 1 epic created, 1 epic failed; bulks never reached
        assert run["counts"]["created"] == 1
        assert run["counts"]["failed"] >= 1
        # Status is "partial" (some succeeded) or "failed" (none succeeded);
        # with 1 created we expect "partial".
        assert run["status"] in ("partial", "failed")
        # The failed epic recorded its error
        failed = [i for i in run["issues"] if i["status"] == "failed"]
        assert len(failed) >= 1
        assert "simulated epic failure" in failed[0]["error"]


# ---------------------------------------------------------------------------
# P5: bulk failure after epics succeed
# ---------------------------------------------------------------------------


class TestBulkFailure:
    def test_p5_bulk_failure_after_epics(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        fake = FakeJiraClient(fail_bulk=True)
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                with pytest.raises(SystemExit):
                    run_plan(
                        org_config, team_config,
                        dry_run=False, console=console,
                        report_path=report_path,
                    )

        _run_with_patches(patches, go)

        env = _read_report(report_path)
        run = env["run"]
        # All epics created
        epic_results = [i for i in run["issues"] if i["kind"] == "epic"]
        assert len(epic_results) == 2
        assert all(e["status"] == "created" for e in epic_results)
        # Bulk failed → per_release/per_sprint marked failed
        non_epic = [i for i in run["issues"] if i["kind"] != "epic"]
        assert len(non_epic) >= 1
        assert all(i["status"] == "failed" for i in non_epic)


# ---------------------------------------------------------------------------
# P6 + P7: resume — created skipped, failed retried
# ---------------------------------------------------------------------------


class TestResume:
    def test_p6_resume_skips_created_epic(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"

        # Compute the same hash run_plan would compute for these inputs
        prior_hash = compute_resolved_hash(
            org_config, team_config, "PI28", ["26.1.1"],
        )
        prior = RunReport(
            resolved_config_hash=prior_hash,
            issues=[
                IssueResult(
                    template_key="epic:bau", kind="epic",
                    status="created", jira_key="REAL-1",
                ),
            ],
        )
        fake = FakeJiraClient()
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                run_plan(
                    org_config, team_config,
                    dry_run=False, console=console,
                    report_path=report_path,
                    prior_report=prior,
                )

        _run_with_patches(patches, go)

        # Only 1 epic was actually created (misc); bau was skipped
        # create_issue called once for 'misc' epic
        assert len(fake.created) == 1
        # The bau epic key should have been pre-populated into epic_keys —
        # verify by inspecting a per_release payload sent to bulk creation.
        # (Easier: just check the report includes both as created.)
        env = _read_report(report_path)
        run = env["run"]
        bau = [i for i in run["issues"] if i["template_key"] == "epic:bau"][0]
        assert bau["status"] == "created"
        assert bau["jira_key"] == "REAL-1"

    def test_p7_failed_status_is_retried(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        prior_hash = compute_resolved_hash(
            org_config, team_config, "PI28", ["26.1.1"],
        )
        prior = RunReport(
            resolved_config_hash=prior_hash,
            issues=[
                IssueResult(
                    template_key="per_release[0]:26.1.1", kind="per_release",
                    status="failed", error="prior error",
                ),
            ],
        )
        fake = FakeJiraClient()
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                run_plan(
                    org_config, team_config,
                    dry_run=False, console=console,
                    report_path=report_path,
                    prior_report=prior,
                )

        _run_with_patches(patches, go)

        # 2 epics + 1 per_release (retried, not skipped) + 2 per_sprint
        # = 2 create_issue + 1 bulk that includes the per_release ticket
        # Verify by checking the bulk_created records contain the per_release ticket.
        all_bulk = [p for batch in fake.bulk_created for p in batch]
        per_release_summaries = [
            p["fields"]["summary"] for p in all_bulk
            if p["fields"]["summary"].startswith("Pre-reg")
        ]
        assert per_release_summaries == ["Pre-reg 26.1.1"]


# ---------------------------------------------------------------------------
# P8 + P9: drift detection
# ---------------------------------------------------------------------------


class TestDrift:
    def test_p8_drift_raises_without_force(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        prior = RunReport(resolved_config_hash="DEADBEEF" * 8)  # mismatch

        # A fake client that asserts on every method — should never be called
        class Tripwire:
            def __getattr__(self, name):
                raise AssertionError(f"client.{name} called despite drift")

        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=Tripwire()):
                with pytest.raises(ConfigDriftError):
                    run_plan(
                        org_config, team_config,
                        dry_run=False, console=console,
                        report_path=report_path,
                        prior_report=prior,
                        force=False,
                    )

        _run_with_patches(patches, go)

    def test_p9_force_overrides_drift(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        prior = RunReport(resolved_config_hash="DEADBEEF" * 8)
        fake = FakeJiraClient()
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                run_plan(
                    org_config, team_config,
                    dry_run=False, console=console,
                    report_path=report_path,
                    prior_report=prior,
                    force=True,
                )

        _run_with_patches(patches, go)

        env = _read_report(report_path)
        run = env["run"]
        # Hash overwritten with current — no longer "DEADBEEF..."
        assert run["resolved_config_hash"] != "DEADBEEF" * 8
        # And the run actually proceeded
        assert run["counts"]["created"] > 0


# ---------------------------------------------------------------------------
# P10: persist on KeyboardInterrupt
# ---------------------------------------------------------------------------


class TestPersistOnError:
    def test_p10_keyboardinterrupt_leaves_valid_report(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        fake = FakeJiraClient(interrupt_create_issue_after=1)  # interrupt 2nd call
        patches = _patch_prompts()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                with pytest.raises(KeyboardInterrupt):
                    run_plan(
                        org_config, team_config,
                        dry_run=False, console=console,
                        report_path=report_path,
                    )

        _run_with_patches(patches, go)

        # File exists, is valid JSON
        assert report_path.exists()
        env = _read_report(report_path)
        run = env["run"]
        # 1 epic completed before interrupt
        assert run["counts"]["created"] >= 1
        assert run["status"] == "failed"
        # INV-04 / D-12: the cause and end time are recorded before re-raise
        assert run["ended_at"] is not None
        assert run["error"] == {
            "type": "KeyboardInterrupt", "message": "simulated Ctrl-C",
        }


# ---------------------------------------------------------------------------
# INV-04: every plan exit path records a distinguishable run-level error
# ---------------------------------------------------------------------------


class _RequiredFieldFake(FakeJiraClient):
    """Fake whose createmeta marks a field required that no payload sets."""

    def get_createmeta_fields_by_type_name(self, project_key, issue_type_name):
        return {"customfield_99999": {"required": True, "name": "Mandatory"}}


class TestErrorCapture:
    @staticmethod
    def _run_live(org_config, team_config, console, report_path, fake, patches,
                  *, expect=SystemExit, prior_report=None):
        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                with pytest.raises(expect):
                    run_plan(
                        org_config, team_config,
                        dry_run=False, console=console,
                        report_path=report_path,
                        prior_report=prior_report,
                    )

        _run_with_patches(patches, go)
        return _read_report(report_path)["run"]

    def test_final_confirm_decline_records_aborted_reason(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        run = self._run_live(
            org_config, team_config, console, report_path,
            FakeJiraClient(), _patch_prompts(confirm_yes=False),
        )
        assert run["error"] == {
            "type": "Aborted",
            "message": "User declined ticket creation at the final confirmation.",
        }
        assert run["ended_at"] is not None
        assert run["counts"] == {"created": 0, "skipped": 0, "failed": 0}
        assert run["issues"] == []

    def test_fix_version_decline_records_aborted_reason(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        # "99.9.9" is absent from the fake's fix versions → create prompt.
        run = self._run_live(
            org_config, team_config, console, report_path,
            FakeJiraClient(),
            _patch_prompts(versions=("99.9.9",), confirm_yes=False),
        )
        reason = "Cannot proceed without fix versions (declined creating: 99.9.9)."
        assert run["error"] == {"type": "Aborted", "message": reason}
        assert run["ended_at"] is not None

    def test_fix_version_decline_console_matches_report(
        self, org_config, team_config, tmp_path,
    ):
        """WR-05: the recorded reason is exactly what the console printed."""
        console = Console(stderr=True, no_color=True, force_terminal=False, record=True)
        report_path = tmp_path / "r.json"
        run = self._run_live(
            org_config, team_config, console, report_path,
            FakeJiraClient(),
            _patch_prompts(versions=("99.9.9",), confirm_yes=False),
        )
        assert f"Aborted. {run['error']['message']}" in console.export_text()

    def test_credential_error_records_aborted_reason(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"

        def go():
            with patch(
                "jiramator.planner.JiraClient",
                side_effect=ValueError("JIRA_TOKEN not set"),
            ):
                with pytest.raises(SystemExit):
                    run_plan(
                        org_config, team_config,
                        dry_run=False, console=console,
                        report_path=report_path,
                    )

        _run_with_patches(_patch_prompts(), go)
        run = _read_report(report_path)["run"]
        assert run["error"]["type"] == "Aborted"
        assert run["error"]["message"].startswith("Credential error:")
        assert "JIRA_TOKEN not set" in run["error"]["message"]

    def test_preflight_problems_record_aborted_reason(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        run = self._run_live(
            org_config, team_config, console, report_path,
            _RequiredFieldFake(), _patch_prompts(),
        )
        assert run["error"]["type"] == "Aborted"
        msg = run["error"]["message"]
        assert msg.startswith("Found ")
        assert "field problem(s): " in msg
        # WR-05: the specific problem (which field) is kept in the report.
        assert "customfield_99999" in msg
        assert msg.endswith("No tickets were created.")
        assert run["ended_at"] is not None

    def test_bulk_api_error_records_exception(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        run = self._run_live(
            org_config, team_config, console, report_path,
            FakeJiraClient(fail_bulk=True), _patch_prompts(),
        )
        assert run["error"]["type"] == "JiraApiError"
        assert "simulated bulk failure" in run["error"]["message"]
        assert run["ended_at"] is not None

    def test_epic_api_error_records_exception(
        self, org_config, team_config, console, tmp_path,
    ):
        report_path = tmp_path / "r.json"
        run = self._run_live(
            org_config, team_config, console, report_path,
            FakeJiraClient(fail_create_issue_after=0), _patch_prompts(),
        )
        assert run["error"]["type"] == "JiraApiError"
        assert "simulated epic failure" in run["error"]["message"]

    @pytest.mark.parametrize(
        "fake_kwargs", [{"fail_create_issue_after": 0}, {"fail_bulk": True}],
        ids=["epic", "bulk"],
    )
    def test_token_absent_from_whole_report_on_api_error(
        self, org_config, team_config, console, tmp_path, monkeypatch, fake_kwargs,
    ):
        """WR-03: per-issue ``error`` strings are redacted like ``run.error``."""
        secret = "tok-SECRET-123456"
        monkeypatch.setenv(org_config.jira_email_env, "me@example.com")
        monkeypatch.setenv(org_config.jira_token_env, secret)

        class _LeakyFake(FakeJiraClient):
            def create_issue(self, payload):
                if self._fail_create_after is not None:
                    raise JiraApiError(f"401 token {secret} rejected", status_code=401)
                return super().create_issue(payload)

            def create_issues_bulk(self, payloads):
                if self._fail_bulk:
                    raise JiraApiError(f"401 token {secret} rejected", status_code=401)
                return super().create_issues_bulk(payloads)

        report_path = tmp_path / "r.json"
        run = self._run_live(
            org_config, team_config, console, report_path,
            _LeakyFake(**fake_kwargs), _patch_prompts(),
        )
        failed = [i for i in run["issues"] if i["status"] == "failed"]
        assert failed
        assert all(i["error"] == "401 token *** rejected" for i in failed)
        assert secret not in report_path.read_text(encoding="utf-8")

    def test_builder_value_error_records_exception(
        self, org_config, console, tmp_path,
    ):
        # sprint_group set, but no release_sprint_schedule entry for 1 release
        team = TeamConfig(
            project_key="TST",
            team_name="TestTeam",
            per_release_tickets=[
                TicketTemplate(
                    summary="Pre-reg {version}",
                    fields={"issuetype": "Task"},
                    sprint_group="pre",
                ),
            ],
            release_sprint_schedule={2: [{"pre": 1}, {"pre": 2}]},
        )
        report_path = tmp_path / "r.json"
        run = self._run_live(
            org_config, team, console, report_path,
            FakeJiraClient(), _patch_prompts(), expect=ValueError,
        )
        assert run["error"]["type"] == "ValueError"
        assert "release_sprint_schedule" in run["error"]["message"]
        assert run["ended_at"] is not None

    def test_resume_from_legacy_report_without_error_succeeds(
        self, org_config, team_config, console, tmp_path,
    ):
        prior_hash = compute_resolved_hash(
            org_config, team_config, "PI28", ["26.1.1"],
        )
        legacy_path = tmp_path / "legacy.json"
        legacy_path.write_text(json.dumps({
            "schema_version": 1,
            "run": {
                "schema_version": 1,
                "command": ["jiramator", "plan"],
                "started_at": "2026-04-29T10:00:00+00:00",
                "ended_at": None,
                "team_config_path": "",
                "org_config_path": "",
                "team_name": "TestTeam",
                "pi_label": "PI28",
                "versions": ["26.1.1"],
                "resolved_config_hash": prior_hash,
                "status": "failed",
                "counts": {"created": 1, "skipped": 0, "failed": 0},
                "issues": [{
                    "template_key": "epic:bau", "kind": "epic",
                    "status": "created", "jira_key": "REAL-1",
                    "error": None, "fields": [],
                }],
            },
        }))
        prior = RunReport.from_envelope(json.loads(legacy_path.read_text()))
        assert prior.error is None

        report_path = tmp_path / "r.json"
        fake = FakeJiraClient()

        def go():
            with patch("jiramator.planner.JiraClient", return_value=fake):
                run_plan(
                    org_config, team_config,
                    dry_run=False, console=console,
                    report_path=report_path,
                    prior_report=prior,
                )

        _run_with_patches(_patch_prompts(), go)
        run = _read_report(report_path)["run"]
        assert run["status"] == "success"
        assert "error" not in run
        assert len(fake.created) == 1  # bau resumed, only misc created
