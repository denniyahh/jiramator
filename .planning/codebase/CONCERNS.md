# Codebase Concerns

**Analysis Date:** 2026-04-15

## Tech Debt

**No Duplicate Detection Before Ticket Creation:**
- Issue: The `run_plan()` function in `jiramator/planner.py` (line 388–391) explicitly warns users that running the tool twice creates duplicate tickets, but does nothing to prevent it. This is acknowledged as a future enhancement in `README.md` (line 245–246).
- Files: `jiramator/planner.py`
- Impact: Running the tool accidentally or re-running after a partial failure creates duplicate Jira tickets. Users must manually clean up duplicates in Jira, which is error-prone for bulk-created tickets.
- Fix approach: Before creating tickets, query Jira for existing issues matching `summary + PI label + project_key`. Skip or warn for each match. Add a `--force` flag to override the check.

**No Rollback on Partial Bulk Creation Failure:**
- Issue: `create_issues_bulk()` in `jiramator/jira_client.py` (lines 223–225 comment) explicitly notes that already-created issues from previous batches are NOT rolled back on failure. Similarly, `run_plan()` in `jiramator/planner.py` (lines 427–431) catches bulk creation failure but only prints a warning — epics and some tickets may already exist.
- Files: `jiramator/jira_client.py`, `jiramator/planner.py`
- Impact: A network failure or Jira error mid-batch leaves the project in a half-created state with orphan epics and partial ticket sets. The user must manually identify and either complete or delete the partial run.
- Fix approach: Track all created issue keys during the run. On failure, offer to either (a) delete all created issues (rollback) or (b) output the list of already-created keys for manual cleanup. At minimum, persist the created keys to a log file.

**Double `build_all()` Call for Live Runs:**
- Issue: `run_plan()` in `jiramator/planner.py` calls `build_all()` twice — once for preview (line 356–363) with `epic_keys={}`, then again after epic creation (lines 409–416) with resolved epic keys. This duplicates all ticket-building computation.
- Files: `jiramator/planner.py`
- Impact: Minor performance overhead (not user-facing). The real risk is divergence — if the two calls receive different state, the preview won't match what gets created.
- Fix approach: Refactor to build payloads once, then do a targeted replacement of `$epic:ref` values in the already-built payloads after epic keys are known. Or accept the double-build as intentional simplicity.

**Private API Imports Across Module Boundary:**
- Issue: `jiramator/ticket_builder.py` (line 18) imports private symbols `_EPIC_REF_RE` and `_TEMPLATE_VAR_RE` from `jiramator/config.py`. Similarly, `tests/test_config.py` (lines 16–18) imports `_collect_epic_refs` and `_validate_template_vars`. The underscore-prefix convention signals these are internal.
- Files: `jiramator/ticket_builder.py`, `tests/test_config.py`
- Impact: Refactoring `config.py` internals could silently break `ticket_builder.py`. The coupling between modules is tighter than the API suggests.
- Fix approach: Either make these public by removing the underscore prefix (since they are part of the module's inter-package contract), or move the shared regex patterns to a dedicated `jiramator/templates.py` module that both `config.py` and `ticket_builder.py` import from.

**Deferred Import to Avoid Circular Dependency:**
- Issue: `jiramator/cli.py` (line 118) uses a deferred import (`from jiramator.planner import run_plan`) inside the `plan()` function body with a `# noqa: E402` comment, explicitly noting it avoids a circular import.
- Files: `jiramator/cli.py`
- Impact: Currently functional but signals an architectural coupling smell. If more subcommands are added, each might need similar deferred imports.
- Fix approach: This is low-severity. The current pattern works. Could be resolved by restructuring imports so `cli.py` only depends on config, and `planner.py` is imported lazily. But it's not urgent.

**Empty `tests/fixtures/` Directory:**
- Issue: The `tests/fixtures/` directory exists but contains zero files. `tests/conftest.py` (line 7) defines `FIXTURES_DIR` pointing to it, but no test uses fixture files from this directory.
- Files: `tests/fixtures/`, `tests/conftest.py`
- Impact: Dead code. Tests that need YAML fixture data create temp files inline instead.
- Fix approach: Either populate with shared test fixture YAML files to reduce inline fixture data in tests, or delete the directory and the `FIXTURES_DIR` constant.

## Known Bugs

**Sprint Assignment is Advertised But Not Implemented:**
- Symptoms: The `plan` command prompts about sprint existence (lines 341–352 in `jiramator/planner.py`) and prints status messages about sprint assignment, but never actually assigns tickets to sprints. The `get_board_sprints()` method exists in `jiramator/jira_client.py` (lines 331–375) but is never called by `planner.py`.
- Files: `jiramator/planner.py`, `jiramator/jira_client.py`
- Trigger: Set `board_id` in team config and confirm sprints exist during the interactive flow — tickets are created without sprint assignment.
- Workaround: Manually assign tickets to sprints in Jira after creation.

## Security Considerations

**Credentials Handled Via Environment Variables Only:**
- Risk: Low — the design is sound. Credentials are never stored in config files. `jiramator/config.py` (lines 91–112) reads from env vars at runtime.
- Files: `jiramator/config.py`, `jiramator/jira_client.py`
- Current mitigation: `.gitignore` does not include `.env` file entries, but no `.env` files exist. The `README.md` instructs users to use `export` rather than dotfiles.
- Recommendations: Add `.env` and `.env.*` to `.gitignore` as a safety net in case users create them. Consider documenting that users should avoid storing tokens in shell history.

**API Token Passed as Basic Auth Over HTTPS:**
- Risk: Low. `jiramator/jira_client.py` (line 89) uses `session.auth = (email, token)` which is HTTP Basic Auth. This is the standard Jira Cloud API authentication mechanism.
- Files: `jiramator/jira_client.py`
- Current mitigation: Jira Cloud enforces HTTPS. The retry adapter is mounted on both `http://` and `https://` (lines 97–98), meaning a misconfigured `jira_url` with `http://` would send credentials in the clear.
- Recommendations: Add a validation check in `OrgConfig` or `JiraClient.__post_init__()` that rejects non-HTTPS `jira_url` values to prevent accidental plaintext credential transmission.

**No Rate Limiting Beyond Retry:**
- Risk: Medium. The `_RETRY_STRATEGY` in `jiramator/jira_client.py` (lines 57–63) retries on 429 (rate limit) responses, but there's no proactive rate limiting or backoff between individual API calls in `create_issues_bulk()` or `_create_epics()`.
- Files: `jiramator/jira_client.py`, `jiramator/planner.py`
- Current mitigation: urllib3's `Retry` with `backoff_factor=1.0` handles server-signaled rate limits.
- Recommendations: For larger ticket sets or teams with stricter Jira rate limits, add an optional delay between bulk batches or individual epic creations.

## Performance Bottlenecks

**Epic Creation is Sequential:**
- Problem: `_create_epics()` in `jiramator/planner.py` (lines 226–246) creates each epic one at a time via individual `create_issue()` calls.
- Files: `jiramator/planner.py`, `jiramator/jira_client.py`
- Cause: Epics must be created individually because their Jira keys are needed to resolve `$epic:ref` references in downstream tickets. This is a fundamental dependency.
- Improvement path: For teams with many epics, this could become slow. If epic count grows significantly, consider creating all epics in a batch, then fetching their keys via a search query. For typical use (2–5 epics), this is not a real issue.

## Fragile Areas

**Planner Interactive Flow with `sys.exit(1)` Calls:**
- Files: `jiramator/planner.py` (lines 47, 64, 75, 129, 377, 396, 405, 431), `jiramator/cli.py` (lines 101, 107)
- Why fragile: The `run_plan()` function and its helpers use `sys.exit(1)` for error handling throughout (10 occurrences across planner + cli). This makes the function non-composable — it cannot be called from other Python code (e.g., a web API or scheduled job) without catching `SystemExit`.
- Safe modification: When adding new error paths, follow the existing pattern (catch exception → print → `sys.exit(1)`). Be aware that `sys.exit()` raises `SystemExit` which tests catch with `pytest.raises(SystemExit)`.
- Test coverage: Good — tests in `tests/test_planner.py` cover the major error paths including credential errors, epic creation failure, bulk failure, and user aborts.

**Jira Field Wrapping is Hardcoded:**
- Files: `jiramator/ticket_builder.py` (lines 31–39)
- Why fragile: The `WRAPPED_FIELDS` dict hardcodes which Jira fields need name-object or name-object-array wrapping. Adding support for new Jira fields (e.g., `assignee`, `reporter`, `components`) requires updating this dict.
- Safe modification: Add the new field name to `WRAPPED_FIELDS` with the appropriate wrap type. Existing tests in `tests/test_ticket_builder.py::TestWrapField` cover the wrapping logic.
- Test coverage: Adequate — each wrap type is tested. The `# pragma: no cover` on line 63 marks a genuinely unreachable fallback branch.

## Scaling Limits

**Jira Bulk Create Batch Size:**
- Current capacity: 50 issues per bulk API call (constant `_BULK_BATCH_SIZE` in `jiramator/jira_client.py`, line 66).
- Limit: Jira Cloud imposes a 50-issue limit per bulk request. For a typical PI (2 epics + 18 per-release + 7 per-sprint = 27 tickets), this fits in a single batch.
- Scaling path: The batching logic in `create_issues_bulk()` already handles splitting into multiple batches. For very large teams (100+ tickets per PI), the sequential batch approach works but could be slow. Consider parallelizing batches if needed.

**Single-Team Execution Model:**
- Current capacity: One team config per run.
- Limit: Planning for multiple teams requires running the command multiple times with different `--team-config` flags.
- Scaling path: Add a `--team-config-dir` option that processes all YAML files in a directory, or a multi-team mode that chains configs.

## Dependencies at Risk

**No Lockfile:**
- Risk: No `requirements.txt`, `pip.lock`, `poetry.lock`, or `uv.lock` file exists. Dependencies are specified only via version ranges in `pyproject.toml` (lines 12–18): `click>=8.1`, `pydantic>=2.0`, `pyyaml>=6.0`, `requests>=2.31`, `rich>=13.0`.
- Impact: Builds are not reproducible. A new `pydantic` 3.x release (or any major dependency bump) could silently break the project.
- Migration plan: Generate and commit a lockfile using `pip freeze`, `pip-compile` (from pip-tools), or migrate to `uv` for deterministic installs.

**Pydantic v2 API Dependency:**
- Risk: The project uses Pydantic v2 API features (`model_validator`, `field_validator` with `mode="after"`) throughout `jiramator/config.py`. Pydantic v2 was a major breaking change from v1.
- Impact: Low near-term — `pydantic>=2.0` pins to v2+. But a future Pydantic v3 could break validators.
- Migration plan: None needed now. When Pydantic v3 is released, pin to `pydantic>=2.0,<3.0`.

## Missing Critical Features

**Sprint Assignment Not Implemented:**
- Problem: The infrastructure exists (`get_board_sprints()` in `jiramator/jira_client.py`, `sprint_name_template` field in `TeamConfig`, sprint prompts in `planner.py`) but no code ever assigns created tickets to sprints.
- Blocks: Teams that want automated sprint placement must do it manually in Jira after ticket creation, defeating part of the automation goal.

**No `--yes` / Non-Interactive Mode:**
- Problem: Every run requires interactive user input (PI number, version strings, confirmations). There is no way to run the tool in CI, cron jobs, or scripts.
- Blocks: Automation pipelines, scheduled PI planning, integration into CI/CD workflows.

**No `setup` Wizard for New Config Files:**
- Problem: New users must copy and edit example YAML files manually. There is no interactive config generator.
- Blocks: Onboarding for non-technical users or teams unfamiliar with Jira custom field IDs.

## Test Coverage Gaps

**CLI Module (`jiramator/cli.py`) Has No Direct Tests:**
- What's not tested: The `cli()` group, the `plan` command's Click option parsing, and `_resolve_org_config_path()` are not tested via any `test_cli.py` file.
- Files: `jiramator/cli.py`
- Risk: Changes to CLI argument defaults, `click.Path` validators, or the org-config directory resolution logic could break without test detection. The `_resolve_org_config_path()` function has multiple branches (file vs. directory, ambiguous configs, missing configs) that are exercised only transitively through integration tests.
- Priority: Medium — the planner tests cover `run_plan()` thoroughly, but CLI-layer bugs (wrong defaults, path resolution) would slip through.

**No Coverage Enforcement or Configuration:**
- What's not tested: There is no `.coveragerc`, no coverage configuration in `pyproject.toml`, and no coverage minimum threshold.
- Files: `pyproject.toml`
- Risk: Coverage could silently decrease as new code is added. No visibility into which lines/branches are untested.
- Priority: Low — the 198 existing tests provide strong coverage, but the absence of measurement means regressions aren't caught.

**`JiraClient` Tests Mock at Session Level, Not Network Level:**
- What's not tested: The retry adapter behavior (`_RETRY_STRATEGY`) is never exercised in tests because `client._session.get/post` is mocked as a `MagicMock`, bypassing the `HTTPAdapter` and `Retry` logic entirely.
- Files: `tests/test_jira_client.py`
- Risk: The retry configuration (backoff, status codes) could be misconfigured without test detection. Rate-limit handling (429) is part of the retry strategy but never tested.
- Priority: Low — the retry config uses well-tested urllib3 primitives. But if retry parameters are changed, there's no validation.

**Conftest Fixtures Partially Duplicated:**
- What's not tested: N/A, but the shared `conftest.py` fixtures (`org_config_path`, `team_config_path`) are never actually imported by any test file. Each test file defines its own fixtures independently.
- Files: `tests/conftest.py`, `tests/test_config.py`, `tests/test_jira_client.py`, `tests/test_planner.py`, `tests/test_ticket_builder.py`
- Risk: Not a coverage gap per se, but the unused shared fixtures add confusion. Each test file duplicates fixture definitions (e.g., `org_config` is defined 4 times across test files).
- Priority: Low — code hygiene issue, not a test gap.

---

*Concerns audit: 2026-04-15*
