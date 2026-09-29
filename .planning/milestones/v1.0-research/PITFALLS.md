# Pitfalls Research

**Domain:** Jira automation CLI — spreadsheet import, MCP integration, config inheritance
**Researched:** 2026-04-27
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: Spreadsheet encoding and data type silent corruption

**What goes wrong:**
CSV files from Excel on Windows use `cp1252` encoding, not UTF-8. Cells containing em-dashes, smart quotes, or accented names (common in team member names) silently corrupt or raise `UnicodeDecodeError`. Excel `.xlsx` numeric cells auto-coerce dates and numbers — a version string `"26.1"` becomes float `26.1`, losing the trailing `.0` context. The current `spreadsheet.py:22` hardcodes `encoding="utf-8"`.

**Why it happens:**
Developers test with their own clean CSVs. Real POs export from Excel, Google Sheets, or copy-paste from Confluence tables — all producing encoding/type variations.

**How to avoid:**
- Use `chardet` or `charset-normalizer` to detect encoding before reading CSVs
- For `.xlsx`, read cells as strings (`data_only=True` already set, but add explicit string coercion for version-like fields)
- Add an encoding parameter to `read_spreadsheet()` with auto-detect default
- Test with a corpus of real-world messy spreadsheets (BOM markers, mixed encodings, numeric version strings)

**Warning signs:**
- Users report "weird characters" in Jira issue summaries
- Version fields like `26.1` appearing instead of `26.1.0`
- `UnicodeDecodeError` in production but not in tests

**Phase to address:** Spreadsheet import hardening (early — before broader rollout)

---

### Pitfall 2: MCP-first with REST fallback creates a testing and state nightmare

**What goes wrong:**
Building MCP as the primary API path with REST as fallback means every operation has two code paths. When MCP behavior diverges from REST (field formats, error shapes, pagination), bugs appear only in fallback mode — which is the mode you test least but users hit most (MCP server down, version mismatch, network issues).

**Why it happens:**
MCP is new and appealing. Developers build the happy path on MCP, treat REST as "legacy," and don't maintain parity. The current `jira_client.py` has well-tested REST patterns (retry strategy, error classification, pagination) that MCP won't inherit automatically.

**How to avoid:**
- Define an abstract `JiraBackend` protocol with methods matching current `JiraClient` public API (`create_issue`, `create_issues_bulk`, `get_fields`, etc.)
- Implement `RestBackend` (wrapping existing `JiraClient`) and `McpBackend` separately
- Run the same integration test suite against both backends
- Fallback logic lives in a `FallbackBackend` compositor, not scattered through business logic
- Keep REST as the proven default; MCP becomes opt-in until stable

**Warning signs:**
- `if use_mcp:` / `else:` blocks appearing in `importer.py` or `cli.py`
- MCP-specific error handling that doesn't map to existing `JiraApiError` structure
- Tests that mock MCP but not REST, or vice versa

**Phase to address:** MCP integration phase — design the abstraction layer before writing any MCP code

---

### Pitfall 3: Config inheritance merge semantics that surprise users

**What goes wrong:**
Template inheritance (org -> team -> issue type) with YAML dict merging leads to ambiguous behavior: does a team config's `fields: {priority: High}` **replace** the org default fields entirely, or **merge** with them? Users expect merge. Naive `dict.update()` does shallow replacement. Deep merge clobbers lists. Current `TeamConfig` and `OrgConfig` are flat Pydantic models with no inheritance mechanism.

**Why it happens:**
YAML has `<<: *anchor` merge keys, but they're YAML-level (not semantic). Pydantic doesn't natively support layered config merging. Every config inheritance system eventually needs explicit merge vs. replace semantics, and developers defer this decision until users complain.

**How to avoid:**
- Define explicit merge rules per field type: dicts deep-merge, lists append (or replace with explicit `!replace` tag), scalars override
- Document the merge behavior with examples in config docs
- Add a `jiramator config resolve --team calcs` command that shows the final merged config — makes inheritance debuggable
- Use Pydantic's `model_copy(update=...)` for clean layered overrides
- Test: org sets `defaults.priority=Medium`, team sets `defaults.priority=High` — verify High wins. Org sets `labels=[pi28]`, team sets `labels=[team-calcs]` — verify both appear

**Warning signs:**
- Users asking "why is my team config being ignored?"
- Bug reports where org defaults override team-specific values
- Config files duplicating org-level values "just to be safe"

**Phase to address:** Template inheritance phase — define merge semantics before implementing

---

### Pitfall 4: Bulk create partial failure leaves orphaned issues with no rollback

**What goes wrong:**
The current `create_issues_bulk` in `jira_client.py:297-298` explicitly documents "Already-created issues from previous batches are NOT rolled back." When importing 200 rows and batch 3 of 4 fails, you have ~100 orphaned issues in Jira. Re-running the import creates duplicates because the duplicate-detection (`find_issue_keys_by_summaries`) uses summary text matching, which is fragile (whitespace, case).

**Why it happens:**
Jira has no transaction support. The current code acknowledges this but doesn't provide recovery tooling. As imports get larger (spreadsheet import enables this), partial failures become more common and more painful.

**How to avoid:**
- Implement an import manifest: write each created issue key to a local JSON/YAML file as it's created
- On failure, print the manifest path and a `jiramator import --resume <manifest>` command
- Improve duplicate detection: normalize summaries (strip whitespace, lowercase) before comparison
- Add `--batch-size` flag so users can control blast radius
- Consider single-issue creation mode (`create_issue` loop) as safer default for spreadsheet imports, with bulk as opt-in for speed

**Warning signs:**
- Users reporting "I ran it twice and got duplicate issues"
- Support requests about cleaning up partial imports manually
- Import runs with >50 rows (exceeding single batch size)

**Phase to address:** Spreadsheet import phase — before enabling large imports

---

### Pitfall 5: Field resolution ambiguity at scale

**What goes wrong:**
The current `field_resolver.py` resolves spreadsheet headers through a multi-step cascade: alias -> custom field -> standard field -> normalized alias -> Jira metadata lookup. With spreadsheet import, users will have headers like "Story Points", "Story points", "story_points", "SP" — all potentially mapping to different things depending on org config. The normalized matching (`normalize_field_name`) collapses whitespace and lowercases but doesn't handle underscores, hyphens, or abbreviations.

**Why it happens:**
Field resolution was designed for controlled YAML configs written by the tool author. Spreadsheet headers come from arbitrary users and are wildly inconsistent.

**How to avoid:**
- Add a header mapping preview step (already partially exists in `build_preview_report`) but make it **interactive** — show the user the mapping and ask for confirmation before creating issues
- Expand normalization: strip underscores/hyphens, handle common abbreviations in aliases
- Warn loudly when a header resolves via `jira_normalized` (fuzzy match) vs `alias` (explicit)
- Add a `--column-map "SP=story_points,Desc=description"` CLI override for one-off corrections

**Warning signs:**
- `auto_mapped_columns` in preview report containing unexpected mappings
- Users confused about which columns were skipped vs. mapped
- Same spreadsheet producing different results across org configs

**Phase to address:** Spreadsheet import phase — enhance preview/confirmation UX

---

### Pitfall 6: Jira API rate limiting under bulk spreadsheet imports

**What goes wrong:**
Current retry strategy handles 429s with backoff (`jira_client.py:57-63`), but spreadsheet imports introduce new API-heavy patterns: `find_issue_keys_by_summaries` does a JQL search per import run, `find_user_account_id` does a user search per row with a reporter field. A 500-row spreadsheet with reporter columns triggers 500+ API calls for user lookups alone, likely hitting rate limits.

**Why it happens:**
The PI planning flow creates ~20-50 issues per team. Spreadsheet import enables 500+ row imports. The per-row user lookup pattern doesn't scale.

**How to avoid:**
- Cache user lookups: build a `{display_name: account_id}` cache during import, hit API only for cache misses
- Batch user resolution before the import loop, not during
- Add rate-limit awareness: track remaining quota from response headers, proactively throttle
- Consider a `--throttle` flag for conservative environments

**Warning signs:**
- Imports slowing dramatically mid-run
- Intermittent 429 errors in logs
- User lookup taking longer than issue creation

**Phase to address:** Spreadsheet import phase — before enabling large imports

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Summary-based duplicate detection | Simple, no state to manage | False positives on similar summaries; misses renamed issues | MVP only — add manifest-based tracking for v2 |
| Hardcoded UTF-8 in CSV reading | Works for developer's own files | Breaks for Windows Excel exports | Never once targeting broader audience |
| Single `OrgConfig` + `TeamConfig` without inheritance | Flat, easy to understand | Config duplication across teams; no org-wide defaults cascade | Acceptable until 3+ teams onboarded |
| Per-row user lookup during import | Correct results | O(n) API calls, rate limit risk | Only for <50 row imports |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Jira REST API v3 | Sending plain text for `description` field | Must use Atlassian Document Format (ADF) — `value_coercion.py` handles this but spreadsheet import must route descriptions through `adf_text` coercion |
| Jira bulk create endpoint | Assuming atomic behavior | It's not transactional — partial failures return mixed success/error arrays. Must handle per-issue in the response |
| MCP server | Assuming same field format as REST | MCP may abstract or rename fields. Build a translation layer, don't pass REST payloads directly |
| openpyxl `.xlsx` reading | Using `read_only=True` without closing workbook | Leaves file handles open. Current code doesn't call `workbook.close()` in `spreadsheet.py:45` |
| Jira user search API | Assuming `query` parameter does exact match | It's fuzzy. Multiple results common. Current code handles this well with exact-match preference but MCP path must replicate |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Per-row user lookup | Import takes 10x longer than expected | Cache user lookups; batch resolve before import loop | >50 rows with reporter/assignee columns |
| JQL search for duplicate detection | Timeout on large projects | Limit JQL scope with date range or sprint filter | Projects with >10k issues and common summary patterns |
| Loading all Jira field metadata per import | 2-5 second overhead on every run | Cache field metadata locally with TTL (fields rarely change) | Noticeable on repeated imports; annoying in interactive use |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Logging spreadsheet contents at DEBUG level | PII exposure (names, emails in reporter/assignee columns) | Redact user-identifying fields in debug logs; log row numbers not content |
| Storing Jira tokens in config YAML | Credential leak if configs are committed | Current approach (env var names in config, values in env) is correct — don't regress |
| MCP server connection without TLS verification | MITM on Jira credentials | Enforce TLS; don't add `verify=False` shortcuts for development convenience |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Silent column skipping | User thinks all data was imported; missing fields discovered days later | Show skipped columns prominently in preview; require `--ignore-unmapped` to proceed |
| No dry-run default for spreadsheet import | User accidentally creates 500 issues in production | Make `--dry-run` the default; require `--execute` or `--confirm` for live runs |
| Config inheritance without visibility | User can't debug why a field has an unexpected value | Add `jiramator config show --resolved` to display final merged config with source annotations |
| Error messages referencing Jira field IDs | "Error in customfield_10015" means nothing to a PO | Map custom field IDs back to logical names in all user-facing error messages |

## "Looks Done But Isn't" Checklist

- [ ] **Spreadsheet import:** Often missing encoding detection — verify with a Windows-exported CSV containing special characters
- [ ] **Spreadsheet import:** Often missing workbook close — verify no file handle leaks with `read_only=True` openpyxl mode
- [ ] **MCP integration:** Often missing error parity with REST — verify `JiraApiError` raised with same structure from both backends
- [ ] **MCP integration:** Often missing retry/backoff — verify MCP path has equivalent resilience to REST's `_RETRY_STRATEGY`
- [ ] **Config inheritance:** Often missing list merge semantics — verify `labels` from org and team configs are combined, not replaced
- [ ] **Config inheritance:** Often missing "show resolved config" tooling — verify users can debug inheritance
- [ ] **Bulk import:** Often missing resume capability — verify a failed import at row 150 can be resumed without duplicates
- [ ] **Field resolution:** Often missing interactive confirmation — verify user sees and approves column mapping before creation

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Partial bulk import failure | MEDIUM | Use import manifest to identify created issues; delete orphans via `jiramator cleanup --manifest <file>` or manually |
| Wrong column mapping created issues | HIGH | No undo in Jira bulk; must manually edit or delete. Prevention (dry-run default) is critical |
| Config inheritance producing wrong values | LOW | Re-run with corrected config; existing issues unaffected (creation is idempotent by summary match) |
| Encoding corruption in summaries | MEDIUM | Bulk-edit summaries in Jira or re-import with correct encoding after deleting corrupted issues |
| MCP/REST behavior divergence | LOW | Switch to REST-only mode via config flag; debug MCP path separately |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Spreadsheet encoding corruption | Spreadsheet import | Test with Windows-exported CSV containing em-dashes and accented names |
| MCP/REST dual code path divergence | MCP integration | Same test suite passes against both backends |
| Config inheritance merge ambiguity | Template inheritance | `config show --resolved` command works; merge tests for dicts, lists, scalars |
| Bulk import partial failure | Spreadsheet import | Import manifest written on failure; `--resume` flag works |
| Field resolution ambiguity | Spreadsheet import | Interactive preview shows mapping; `--column-map` override works |
| API rate limiting under load | Spreadsheet import | User lookup cache implemented; 500-row import completes without 429s |

## Sources

- Jiramator codebase analysis (current `jira_client.py`, `importer.py`, `spreadsheet.py`, `field_resolver.py`, `config.py`)
- Jira REST API v3 documentation — bulk create endpoint limitations, rate limiting behavior
- openpyxl documentation — `read_only` mode file handle behavior
- Python `csv` module — encoding handling limitations
- MCP specification — transport and error handling patterns

---
*Pitfalls research for: Jira automation CLI — spreadsheet import, MCP integration, config inheritance*
*Researched: 2026-04-27*
