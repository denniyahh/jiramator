# External Integrations

**Analysis Date:** 2026-04-15

## APIs & External Services

**Jira Cloud REST API v3:**
- Primary and only external integration. All API communication lives in `jiramator/jira_client.py`.
- SDK/Client: `requests` library (no Jira-specific SDK). Custom `JiraClient` dataclass wraps a `requests.Session` with basic auth and retry logic.
- Auth: HTTP Basic Auth using email + API token. Credentials read from env vars at runtime via `OrgConfig.resolve_credentials()` in `jiramator/config.py`.
- Auth env vars: `JIRA_EMAIL` (default), `JIRA_TOKEN` (default). Overridable per org config with `jira_email_env` / `jira_token_env`.
- Base URL: Configured per org in `configs/org/*.yaml` (field: `jira_url`). Example: `https://marketaxess.atlassian.net`

**Jira REST API Endpoints Used:**

| Endpoint | Method | Purpose | Code Location |
|----------|--------|---------|---------------|
| `/rest/api/3/project/{key}` | GET | Validate project exists | `JiraClient.get_project()` |
| `/rest/api/3/issue` | POST | Create single issue (epics) | `JiraClient.create_issue()` |
| `/rest/api/3/issue/bulk` | POST | Bulk create issues (tickets) | `JiraClient.create_issues_bulk()` |
| `/rest/api/3/project/{key}/versions` | GET | List fix versions | `JiraClient.get_fix_versions()` |
| `/rest/api/3/version` | POST | Create fix version | `JiraClient.create_fix_version()` |
| `/rest/agile/1.0/board/{id}/sprint` | GET | List sprints for a board | `JiraClient.get_board_sprints()` |

**Retry Strategy:**
- Configured in `jiramator/jira_client.py` using `urllib3.util.retry.Retry`
- Retries on HTTP 429 (rate limit), 502, 503, 504 (transient server errors)
- 3 retries with exponential backoff: 1s, 2s, 4s (`backoff_factor=1.0`)
- Allowed methods: GET, POST, PUT
- Default timeout: 30 seconds (60 seconds for bulk operations)

**Bulk Batching:**
- Jira's bulk create limit is 50 issues per call
- `create_issues_bulk()` automatically splits payloads into batches of 50 (`_BULK_BATCH_SIZE`)
- Partial failure handling: raises `JiraApiError` with details, but already-created issues are NOT rolled back

**Error Handling:**
- Custom `JiraApiError` exception class in `jiramator/jira_client.py`
- Structured error extraction from Jira response bodies (field-level errors, error messages)
- Specific handling for HTTP 401 (auth), 403 (permissions), 404 (not found)
- 409 Conflict on fix version creation is silently handled (fetches existing version instead)

## Data Storage

**Databases:**
- None. Jiramator is stateless — no local database.

**File Storage:**
- YAML config files in `configs/` directory (read-only at runtime)
- No output files written; all results displayed in terminal via Rich

**Caching:**
- None. Every run makes fresh API calls.

## Authentication & Identity

**Auth Provider:**
- Jira Cloud API token authentication (Atlassian account)
- Implementation: HTTP Basic Auth (`requests.Session.auth = (email, token)`) in `JiraClient.__post_init__()` at `jiramator/jira_client.py`
- Credential resolution is deferred — `--dry-run` mode skips credential resolution entirely (no env vars needed for previewing)
- Resolution path: `planner.py:run_plan()` → `JiraClient(org_config)` → `OrgConfig.resolve_credentials()` → reads `os.environ`

## Monitoring & Observability

**Error Tracking:**
- None. No external error tracking service.

**Logs:**
- Python `logging` module used in `jiramator/jira_client.py` (`logger = logging.getLogger(__name__)`)
- Logs issue creation events (`logger.info("Created issue %s", key)`) and batch progress
- No log configuration in the codebase — relies on default Python logging (effectively silent unless caller configures a handler)
- User-facing output uses `rich.console.Console(stderr=True)` for colorized terminal output in `jiramator/cli.py` and `jiramator/planner.py`

## CI/CD & Deployment

**Hosting:**
- Local CLI tool — no hosted deployment

**CI Pipeline:**
- None detected. No `.github/workflows/`, `Jenkinsfile`, `.gitlab-ci.yml`, or equivalent.

## Environment Configuration

**Required env vars (for live runs):**
- `JIRA_EMAIL` — Jira account email address (default name; overridable via `jira_email_env` in org config)
- `JIRA_TOKEN` — Jira API token (default name; overridable via `jira_token_env` in org config)

**Not required for:**
- `--dry-run` mode (credential resolution is skipped)
- Running tests (Jira client is mocked)

**Secrets location:**
- Environment variables only. The `.gitignore` has no `.env` file patterns, and no `.env` files exist in the repo.
- Org config explicitly documents env var names but never stores credentials: `jira_email_env: JIRA_EMAIL`, `jira_token_env: JIRA_TOKEN` in `configs/org/marketaxess.yaml`

## Webhooks & Callbacks

**Incoming:**
- None. Jiramator is a CLI tool, not a server.

**Outgoing:**
- None. All communication is direct HTTP requests to the Jira API.

## Integration Patterns

**Request/Response Pattern:**
- All Jira API interactions are synchronous, blocking HTTP calls via `requests.Session`
- Session is reused across all calls within a single CLI invocation (connection pooling via `HTTPAdapter`)
- Headers set once on session: `Content-Type: application/json`, `Accept: application/json`

**Idempotency:**
- Fix version creation is idempotent (409 Conflict handled gracefully in `JiraClient.create_fix_version()`)
- Issue creation is NOT idempotent — duplicate detection is explicitly called out as missing (warning displayed in `planner.py` at line 389)

**Pagination:**
- Sprint listing (`get_board_sprints()`) implements cursor-based pagination with `startAt` / `maxResults` parameters and `isLast` termination check

---

*Integration audit: 2026-04-15*
