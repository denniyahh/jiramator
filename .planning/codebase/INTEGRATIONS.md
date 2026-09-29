---
last_mapped_commit: 8c96e59b775dcea4aaa6a50e976c76a64e447907
last_mapped_at: 2026-09-28
---
# External Integrations

**Analysis Date:** 2026-09-28

## APIs & External Services

**Jira Cloud REST API (primary and only external service):**

- Service: Atlassian Jira Cloud, REST API v3 + Agile API v1.0
- Client: `requests.Session`, wrapped in `JiraClient` (`jiramator/jira_client.py`)
- Base URL: configurable per org via `jira_url` (`OrgConfig` in `jiramator/config.py`), read from org YAML config (e.g. `configs/org.example/example.yaml`)
- Auth: HTTP Basic Auth (`email`, `API token`) tuple set on `session.auth`, resolved from env vars named by `jira_email_env`/`jira_token_env` (defaults `JIRA_EMAIL`/`JIRA_TOKEN`)
- Endpoints used (all in `jiramator/jira_client.py`):
  - `GET /rest/api/3/project/{project_key}` - `get_project()` — validates project exists
  - `GET /rest/api/3/field` - `get_fields()` — field metadata for name/id resolution
  - `POST /rest/api/3/search/jql` - `find_issue_keys_by_summaries()` — exact-summary issue lookup (replaces deprecated `GET /rest/api/3/search`, which Jira Cloud returns 410 Gone for)
  - `GET /rest/api/3/user/search` - `find_user_account_id()` — resolves user query to `accountId`
  - `PUT /rest/api/3/issue/{issue_key}` - `update_issue()`
  - `POST /rest/api/3/issue` - `create_issue()`
  - `POST /rest/api/3/issue/bulk` - `create_issues_bulk()` — batched, `_BULK_BATCH_SIZE = 50`
  - `GET /rest/api/3/project/{project_key}/versions` - `get_fix_versions()`
  - `POST /rest/api/3/version` - `create_fix_version()`
  - `GET /rest/api/3/issue/createmeta/{project_key}/issuetypes` - `get_createmeta_issue_types()`
  - `GET /rest/api/3/issue/createmeta/{project_key}/issuetypes/{id}` - `get_createmeta_fields()` / `get_createmeta_fields_by_type_name()`
  - `GET /rest/agile/1.0/board/{board_id}/sprint` - `get_board_sprints()` (Jira Software Agile API)
- Retry policy: `urllib3.util.retry.Retry(total=3, backoff_factor=1.0, status_forcelist=[429, 502, 503, 504])`, mounted via `HTTPAdapter` on both `http://` and `https://` in `JiraClient.__post_init__` (`jiramator/jira_client.py`)
- Timeout: `_DEFAULT_TIMEOUT = 30` seconds on every call
- Error handling: `_handle_error()` translates 401/403/404/other into structured `JiraApiError` exceptions surfacing Jira's `errors`/`errorMessages` body

## Data Storage

**Databases:**

- None. Jiramator has no database dependency of any kind.

**File Storage:**

- Local filesystem only:
  - YAML config files: org configs (`configs/org/`, example at `configs/org.example/`), team configs (`configs/teams/`, example at `configs/teams.example/`), loaded via `jiramator/yaml_loader.py` and `jiramator/config.py`
  - XLSX/CSV spreadsheets: input for `import`/`update` CLI commands, read via `openpyxl`/`csv` in `jiramator/spreadsheet.py`
  - Run reports: JSON files written atomically to `.jiramator/runs/<stamp>-<slug>.json` via `jiramator/run_report.py` (`write_report_atomic`, tempfile + `os.replace`), used for crash-safe resume (`--resume` flag) and audit trail. Directory is gitignored.

**Caching:**

- None. No caching layer, in-memory or external.

## Authentication & Identity

**Auth Provider:**

- No third-party identity provider (no OAuth/SSO integration in code)
- Custom: Jira Cloud HTTP Basic Auth using an email + API token pair, both supplied via environment variables. The env var *names* are configurable per organization (`jira_email_env` / `jira_token_env` fields in `OrgConfig`, `jiramator/config.py`), defaulting to `JIRA_EMAIL` / `JIRA_TOKEN`. Credentials are validated eagerly at `JiraClient` construction (`resolve_credentials()` in `jiramator/config.py`) so missing/misconfigured tokens fail fast with a clear error rather than partway through a bulk Jira operation.
- The Jira API token itself is generated out-of-band by the user in their Atlassian account and is never stored in the repo; secrets policy is enforced only via `.gitignore` (`.envrc`, `.env`, `configs/org/`, `configs/teams/`) — there is no in-app secret vault integration.

## Monitoring & Observability

**Error Tracking:**

- None (no Sentry/Bugsnag/etc. integration). Errors are raised as Python exceptions (`JiraApiError` in `jiramator/jira_client.py`) and formatted for CLI display via `jiramator/error_format.py`.

**Logs:**

- Standard library `logging` module (`logger = logging.getLogger(__name__)` in `jiramator/jira_client.py` and other modules)
- Rich-formatted console output (progress, tables, panels) via the `rich` package for interactive CLI feedback — see `jiramator/cli.py`, `jiramator/wizard.py`, `jiramator/planner.py`
- Structured JSON run reports (`jiramator/run_report.py`) act as a durable, machine-readable execution log per run, independent of stdout logging

## CI/CD & Deployment

**Hosting:**

- None — no hosted service/backend. Distributed as a pip-installable CLI package (`jiramator` console script defined in `pyproject.toml`).

**CI Pipeline:**

- GitHub Actions:
  - `.github/workflows/ci.yml` — runs `pytest` on push/PR/workflow_dispatch across a 3×3 matrix (ubuntu/windows/macos × Python 3.11/3.12/3.13), installs via `pip install -e ".[dev]"`
  - `.github/workflows/jiramator-plan.yml` — a **spike/prototype** `workflow_dispatch` form that runs the `jiramator plan` command directly from Actions with no local setup required, for non-technical PI planning owners. Supports `preview` (dry-run, `--dry-run`) and `create` (writes to Jira, gated behind a typed `confirm_create: CREATE` input) modes. Reads `JIRA_EMAIL`/`JIRA_TOKEN` from GitHub Actions repo secrets only in `create` mode; uploads `.jiramator/runs/` as a build artifact and writes a run summary to `$GITHUB_STEP_SUMMARY`.

## Environment Configuration

**Required env vars:**

- `JIRA_EMAIL` (name configurable via `jira_email_env`) — Jira account email for Basic Auth
- `JIRA_TOKEN` (name configurable via `jira_token_env`) — Jira API token for Basic Auth
- `JIRAMATOR_CA_BUNDLE` (optional) — alternate CA bundle path for corporate TLS-inspecting proxies
- `JIRAMATOR_RELAX_TLS_STRICT` (optional) — relaxes strict X.509 validation for non-conformant proxy CAs

**Secrets location:**

- Local development: environment variables set by the developer's shell (e.g. via `.envrc`/direnv, gitignored)
- GitHub Actions spike workflow: repository/organization Secrets (`secrets.JIRA_EMAIL`, `secrets.JIRA_TOKEN`), referenced only in `.github/workflows/jiramator-plan.yml`'s `create` mode job
- No secrets manager (Vault, AWS Secrets Manager, etc.) integration

## Webhooks & Callbacks

**Incoming:**

- None — Jiramator does not expose any HTTP server or listen for inbound webhooks; it is a synchronous CLI/batch tool only.

**Outgoing:**

- None beyond the direct, synchronous Jira REST API calls listed above (no fire-and-forget webhook dispatch).

---

*Integration audit: 2026-09-28*
