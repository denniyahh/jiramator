---
last_mapped_commit: 8c96e59b775dcea4aaa6a50e976c76a64e447907
last_mapped_at: 2026-09-28
---
# Codebase Concerns

**Analysis Date:** 2026-09-28

## Summary

Jiramator is a small, well-tested CLI (653 passing tests, 0 failures at time of
analysis). Most historical issues tracked in `ISSUES.md` are already resolved
(EpicTemplate fields, existing-epic support, reporter field resolution,
hardcoded sprint field). The codebase shows evidence of iterative hardening
against real Jira Cloud API quirks (see `CHANGELOG.md` 1.2.6–1.2.8), which is
a good sign but also flags the Jira API surface as the most fragile part of
the system. Remaining concerns below are lower-severity and mostly
opportunities for hardening rather than active bugs.

## Tech Debt

**Placeholder custom field ID left in wizard-generated config:**

- Issue: `jiramator/wizard.py:156` hardcodes `epic = epic_link_field or "customfield_XXXXX"` as a fallback when the interactive setup wizard can't detect the org's actual Epic Link field ID.
- Files: `jiramator/wizard.py:156`
- Impact: If a new user runs the wizard and the org doesn't have a discoverable Epic Link field, the generated `org.yaml` silently contains an invalid placeholder (`customfield_XXXXX`), which will only surface as a Jira 400 error much later during `plan`.
- Fix approach: Emit a visible warning in the wizard output when falling back to the placeholder, and/or validate `custom_fields` values against `customfield_\d+` pattern in `OrgConfig` at load time.

**Dead code — unused `__version__`:**

- Issue: `__version__` in `jiramator/__init__.py` is defined but not referenced anywhere; Click reads the version from package metadata instead.
- Files: `jiramator/__init__.py`
- Impact: None functionally; purely cosmetic duplication with `pyproject.toml` version. Already noted as low-priority in `ISSUES.md` "Discarded items".
- Fix approach: Remove when next touching `__init__.py` for another reason.

**No automated cleanup for accumulated run reports:**

- Issue: Every `plan`/`import`/`update` invocation writes a JSON report to `.jiramator/runs/` (`jiramator/run_report.py:41` `RUNS_DIR`), but nothing prunes old reports.
- Files: `jiramator/run_report.py`, `jiramator/cli.py` (report_path wiring)
- Impact: Long-lived repos/teams accumulate an unbounded number of small JSON files under `.jiramator/runs/`. Low impact today (files are small, git-ignored via `.jiramator/`), but could become noisy for teams running `import`/`update` frequently in CI.
- Fix approach: Add an optional `--prune-reports-older-than` flag or a lightweight `jiramator reports prune` command; not urgent.

## Known Bugs

None currently open. All bugs tracked in `ISSUES.md` (#1 EpicTemplate missing fields, #3 reporter lookup bypass) are marked Resolved with verification notes and regression tests.

## Security Considerations

**Fallback to first fuzzy-matched user on ambiguous account lookup:**

- Risk: `find_user_account_id()` in `jiramator/jira_client.py:291-315` resolves a reporter/assignee name from a spreadsheet cell via Jira's `/rest/api/3/user/search`. If no user's `displayName` exactly matches (case-insensitively), it silently falls back to `users[0].get("accountId")` — the *first* result returned by Jira's fuzzy search, not necessarily the intended person.
- Files: `jiramator/jira_client.py:311-315`, called from `jiramator/importer.py:428-437`
- Current mitigation: None — no warning is emitted when falling back to a fuzzy (non-exact) match, unlike the "could not resolve" warning path used when zero users match.
- Recommendation: Treat a non-exact match as ambiguous by default — either skip assignment and emit a warning (matching the existing "could not resolve" UX), or only auto-assign when exactly one candidate is returned and warn when multiple candidates exist. This avoids silently assigning tickets to the wrong person when names are ambiguous (e.g. two "John Smith"s in the org).

**TLS strictness can be relaxed via environment variables:**

- Risk: `_build_https_adapter()` in `jiramator/jira_client.py:97-124` supports `JIRAMATOR_RELAX_TLS_STRICT` (disables `ssl.VERIFY_X509_STRICT`) and `JIRAMATOR_CA_BUNDLE` (custom CA trust) to work around corporate TLS-inspecting proxies.
- Files: `jiramator/jira_client.py:76-124`
- Current mitigation: Certificate trust, hostname verification, and expiry checks remain enforced even with these flags — only one RFC-conformance nitpick (non-critical Basic Constraints) is relaxed. Well-documented in the code's docstring.
- Recommendation: No code change needed; this is intentionally scoped and documented. Worth calling out in onboarding docs so operators understand the blast radius before setting these env vars in shared CI environments.

**Credentials are process-lifetime, not rotated:**

- Risk: `OrgConfig.resolve_credentials()` (`jiramator/config.py:153-174`) reads the Jira email/token once from env vars at `JiraClient.__post_init__` and reuses the same `requests.Session` auth for the whole run. This is standard practice for a CLI tool but means a long-running `plan`/`import` invocation (e.g. very large bulk imports) will fail hard if the token is rotated/revoked mid-run rather than picking up a refreshed credential.
- Files: `jiramator/jira_client.py:147-152`, `jiramator/config.py:153-174`
- Current mitigation: Failures surface immediately as a `JiraApiError` with a clear "check your env var" message.
- Recommendation: No action needed for current scale (PI planning / spreadsheet import batches); revisit only if usage grows into long-running daemon-style workflows.

## Performance Bottlenecks

**Sequential single-issue creation path when not using bulk create:**

- Problem: `create_issue()` (`jiramator/jira_client.py:335-359`) issues one HTTP POST per issue and is used for epic creation and some update flows, in contrast to `create_issues_bulk()` which batches up to 50 issues per call.
- Files: `jiramator/jira_client.py:335-359` vs `:361-424`
- Cause: Epic creation (`_create_epics()` in `jiramator/planner.py:580`) and single-row updates go through the non-batched path since epics are typically few per team/PI.
- Improvement path: Not a real bottleneck at current scale (a handful of epics per PI); would only matter if epic counts grew into the hundreds. No action needed now.

**`find_issue_keys_by_summaries` builds one large JQL OR-clause:**

- Problem: `jiramator/jira_client.py:251-287` builds a single JQL query with one `summary ~ "..."` clause OR'd together per unique summary, sized by `len(unique_summaries)` for `maxResults`.
- Files: `jiramator/jira_client.py:251-287`
- Cause: For very large imports (hundreds+ of rows), the generated JQL string could approach Jira's query length limits, and a single `maxResults` this large may get capped server-side without the code noticing (no pagination handling here, unlike the createmeta endpoints).
- Improvement path: Add pagination (nextPageToken handling, since this uses the newer `/rest/api/3/search/jql` endpoint) and/or chunk `unique_summaries` into batches of ~100 for very large imports. Not urgent at current typical usage (spreadsheet imports of tens to low hundreds of rows).

## Fragile Areas

**Jira Cloud API response shape assumptions (createmeta endpoints):**

- Files: `jiramator/jira_client.py:488-576` (`get_createmeta_issue_types`, `get_createmeta_fields`)
- Why fragile: `CHANGELOG.md` 1.2.6 documents that these endpoints previously broke silently — wrong JSON key (`values` vs `fields`) and missing `isLast` pagination markers caused validation to be a silent no-op and pagination to stop after 50 results. The code now hardcodes pagination via `total`/`startAt` with inline comments explaining the undocumented behavior ("confirmed against live Jira Cloud"), which means any future Jira API change to these fields will again fail silently unless caught by tests against a live instance.
- Safe modification: Any change here should be validated against a live Jira Cloud instance, not just unit tests with mocked responses, since the whole class of past bugs came from incorrect assumptions about response shape that mocks didn't catch.
- Test coverage: `tests/test_jira_client.py` covers pagination logic against mocked responses reproducing the documented shape, but cannot catch a future real-world API drift the way the 1.2.6 bug wasn't caught until live use.

**Sprint field / sprint ID resolution:**

- Files: `jiramator/planner.py` (`_resolve_sprint_ids`, `_SPRINT_FIELD` config lookup), `jiramator/jira_client.py:605+` (`get_board_sprints`)
- Why fragile: CHANGELOG 1.2.7 notes that Jira's Sprint custom field requires a bare numeric sprint ID, not a name string — a mismatch between what spreadsheets naturally contain (sprint names) and what the API needs. This class of "friendly name vs. internal ID" mismatch is a recurring theme across the codebase (see also Epic Link field, issue type names vs ids) and is easy to reintroduce when adding new field types.
- Safe modification: When adding support for a new Jira field type that has both a human name and internal ID, follow the existing pattern of resolving name→ID before building the payload (see `get_createmeta_fields_by_type_name` for the established convention) rather than passing the display value straight through.
- Test coverage: `tests/test_planner_sprint.py` (370 lines) exercises this fairly thoroughly.

**Deferred-field resolution split (reporter/assignee/parent):**

- Files: `jiramator/importer.py:94-120` (`_DEFERRED_FIELDS`), `jiramator/importer.py:400-450` (live resolution)
- Why fragile: Reporter, assignee, and parent fields are deliberately excluded from the payload during `build_row_payload()` and resolved separately during the live run using `deferred_headers` derived from column resolution. This two-phase design is intentional (per `ISSUES.md` #3 resolution notes) but means any new field requiring live-lookup-based resolution (e.g. a future "component owner" field) must be wired into both the deferred-field set and the live-resolution loop, or it will silently fail the same way reporter did before the #3 fix.
- Safe modification: If adding a new deferred field, mirror the existing reporter/assignee/parent pattern exactly — add to `_DEFERRED_FIELDS`, and add a resolution branch in the loop around `jiramator/importer.py:426-450`.
- Test coverage: `tests/test_importer.py` (674 lines) and `tests/test_importer_report.py` (407 lines) cover the existing three deferred fields well.

## Scaling Limits

**Bulk create batch size:**

- Current capacity: `create_issues_bulk()` batches at 50 issues per call (Jira's documented limit), looping over larger lists automatically (`jiramator/jira_client.py:361-424`).
- Limit: A batch failure mid-run does **not** roll back already-created issues in prior batches (explicitly documented in the docstring) — a large import that fails on batch 3 of 5 leaves batches 1–2 created in Jira with no automatic cleanup.
- Scaling path: The `import`/`plan` run-report + resume mechanism (`jiramator/run_report.py`, `_bulk_create_with_resume` in `jiramator/planner.py:1022`) is the existing mitigation — reruns skip already-created rows. This is adequate for the tool's current use case (human-supervised PI planning / spreadsheet imports) but would need explicit partial-failure UX if usage grew toward fully unattended CI bulk imports.

**JQL-based summary lookup (`find_issue_keys_by_summaries`):**

- Current capacity: Works well for the typical tens-to-hundreds-of-rows spreadsheet import.
- Limit: No chunking/pagination (see Performance Bottlenecks above) — very large imports (many hundreds+ rows) risk hitting JQL length or `maxResults` limits without a clear error message.
- Scaling path: Add batching by summary count and switch to token-based pagination on `/rest/api/3/search/jql` if usage grows beyond current typical scale.

## Dependencies at Risk

None identified. Dependencies are mainstream and actively maintained (`requests`, `urllib3`, Pydantic-style config validation, Click-based CLI, Rich for console rendering — confirm exact list in `pyproject.toml`). No dependency pinned to an end-of-life version was found during this pass.

## Missing Critical Features

**Plan command duplicate detection:**

- Problem: Documented in the README as future work — `plan` does not currently detect when a ticket with the same summary/epic already exists before creating a duplicate.
- Blocks: Safe re-running of `plan` without risk of duplicate epics/tickets in edge cases outside the existing resume-by-run-report mechanism.
- Note: This is a known, intentionally-deferred feature request (see `ISSUES.md` "Discarded items" — not treated as a bug), not an oversight.

## Test Coverage Gaps

**Live Jira API shape drift:**

- What's not tested: Real-world Jira Cloud response shape changes to createmeta, search/jql, and bulk-create endpoints — all current tests mock HTTP responses based on documented/observed shapes.
- Files: `tests/test_jira_client.py`
- Risk: A future Jira API change (undocumented field rename, pagination behavior change) could reintroduce silent failures of the same class fixed in CHANGELOG 1.2.6, and unit tests alone won't catch it.
- Priority: Medium — mitigate by periodically smoke-testing against a real Jira Cloud sandbox rather than adding more mocked tests.

**Ambiguous user-lookup fallback path:**

- What's not tested: The `find_user_account_id()` fallback-to-first-fuzzy-match behavior (`jiramator/jira_client.py:311-315`) does not appear to have a test asserting the current (arguably risky) fallback behavior, which would need updating if the security recommendation above is implemented.
- Files: `jiramator/jira_client.py:291-315`, `tests/test_jira_client.py`
- Risk: A future refactor could change this behavior unintentionally in either direction without a failing test to catch it.
- Priority: Medium — add a test locking in whichever behavior is chosen (current fallback, or the safer "warn on ambiguity" approach recommended above).

---

*Concerns audit: 2026-09-28*
