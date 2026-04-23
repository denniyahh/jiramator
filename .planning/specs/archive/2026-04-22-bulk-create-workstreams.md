# Unified Bulk-Create Workstreams and Parallel Development Plan

**Status**: Archived historical execution plan
**Last reviewed**: 2026-04-23
**Why archived**:
- it captured a valid sequencing strategy at the time
- large portions are now stale because `import` shipped directly and the repo state/branching advice is no longer current
- keep this document for historical context, not as current execution guidance

> For Hermes: Use subagent-driven-development skill to execute these workstreams with isolated subagents and explicit review gates.

Goal: Break the unified bulk-create architecture into discrete, low-conflict workstreams so development can be parallelized safely where practical, without corrupting `main` or creating merge-conflict chaos.

Architecture: This plan assumes the unified architecture in `.planning/specs/2026-04-22-bulk-create-unified-architecture.md` is the source of truth. `plan` remains separate. Ad hoc creation is implemented through one shared engine with two adapters: YAML issue-spec and spreadsheet import.

Tech Stack: Python 3.11+, Click, Pydantic, requests, Rich, csv stdlib, openpyxl, pytest, git.

---

## First principle: not everything should be parallelized

Parallel development is only useful when workstreams have real seams.

Bad parallelization:
- two branches both rewriting `config.py`
- two branches both changing `cli.py`
- two branches both inventing their own field coercion logic

That just converts coding work into merge conflict work.

So the right split is:
- serial foundation where shared interfaces are defined
- parallel adapter work once those interfaces are stable
- serial integration at the end

---

## Current repo state risk

Current branch: `main`
Current state: dirty working tree

Observed local changes:
- modified: `README.md`
- modified: `configs/org/marketaxess.yaml`
- untracked: `configs/teams/issue-spec.template.yaml`
- untracked: `docs/`

This means you should NOT create multiple feature branches yet.

Why:
- branches created from a dirty tree inherit ambiguous local state
- you lose track of which branch owns which planning/doc edits
- conflict resolution becomes harder because the shared base is undefined

Required before branching:
- checkpoint the current planning/docs state into git on a dedicated branch or a clean commit

---

## Recommended branching strategy

Use a short-lived integration branch plus focused feature branches.

Recommended branch structure:

1. `feature/bulk-create-foundation`
   Owns:
   - docs honesty cleanup
   - config schema additions
   - shared field resolution layer
   - shared value coercion layer
   - shared preview/reporting helpers
   - Jira client field metadata fetch

2. `feature/bulk-create-yaml-adapter`
   Owns:
   - YAML issue-spec adapter
   - `create-issues` CLI wrapper
   - YAML adapter tests

3. `feature/bulk-create-spreadsheet-adapter`
   Owns:
   - CSV/XLSX reader
   - spreadsheet adapter
   - `import` CLI wrapper
   - spreadsheet tests

4. `feature/bulk-create-integration`
   Owns:
   - final merge integration
   - CLI reconciliation
   - end-to-end tests
   - README finalization

Important rule:
The adapter branches should branch from the foundation branch after the shared interfaces land, not directly from `main`.

Why:
- both adapters depend on the same config shape
- both adapters depend on the same field resolution and coercion APIs
- if they each guess the interface independently, they will drift and create rework

---

## Merge order

Strict merge order:

1. checkpoint/docs branch or commit
2. foundation branch
3. yaml adapter branch
4. spreadsheet adapter branch
5. integration branch
6. merge to `main`

Do not run YAML and spreadsheet work before the foundation API exists.

---

## Workstream breakdown

### Workstream 0: Checkpoint and repo honesty

Type: serial
Branch: `feature/bulk-create-foundation` or a short-lived `chore/bulk-create-planning-checkpoint`

Objective:
Create a clean, reviewable baseline before any parallel work begins.

Scope:
- add the architecture plan doc
- add this workstreams plan doc
- update README so it stops claiming `create-issues` is shipped now
- update `docs/create-issues-spec.md` status to mark it as superseded by unified architecture
- ensure existing template/spec files are clearly labeled as planned/not yet wired

Why serial:
This is repo-truth work. It should happen once, cleanly.

Expected touched files:
- `README.md`
- `docs/create-issues-spec.md`
- `docs/plans/2026-04-22-bulk-create-unified-architecture.md`
- `docs/plans/2026-04-22-bulk-create-workstreams.md`

Review gate:
- docs accurately reflect current shipping state
- no code behavior changes yet

---

### Workstream 1: Shared foundation

Type: serial
Branch: `feature/bulk-create-foundation`

Objective:
Define the shared contracts that both adapters will consume.

Scope:
1. org config schema for `bulk_create`
2. real org config updates for aliases/types/defaults
3. Jira client `get_fields()`
4. shared field resolver module
5. shared value coercion module
6. shared preview/reporting module
7. normalized issue input datamodel
8. shared bulk-create orchestration skeleton

Expected touched files:
- `jiramator/config.py`
- `configs/org/marketaxess.yaml`
- `jiramator/jira_client.py`
- `jiramator/field_resolver.py`
- `jiramator/value_coercion.py`
- `jiramator/preview.py`
- `jiramator/bulk_create.py`
- tests for each shared module

Why serial:
This defines the contract. Adapters must not invent their own versions of these APIs.

Acceptance gate before parallelizing:
- shared module APIs are committed and stable enough for adapters
- test coverage exists for resolver/coercion/config/Jira field metadata
- importers/adapters can be developed against these interfaces without guessing

---

### Workstream 2: YAML issue-spec adapter

Type: parallelizable after foundation lands
Branch: `feature/bulk-create-yaml-adapter`

Objective:
Implement `create-issues` as a thin wrapper over the shared engine.

Scope:
1. parse issue-spec YAML
2. validate spec structure
3. merge defaults and per-issue fields
4. attach epic link logically
5. optionally validate explicit epic keys in live mode
6. feed normalized issues into shared bulk-create engine
7. add CLI wrapper: `jiramator create-issues`
8. add adapter/unit/integration tests

Expected touched files:
- `jiramator/input_adapters/yaml_issue_spec.py`
- `jiramator/cli.py`
- `tests/test_yaml_issue_spec_adapter.py`
- `tests/test_cli_bulk_create.py`
- maybe `configs/teams/issue-spec.template.yaml`

Files that should NOT be substantially redefined here:
- `config.py`
- `field_resolver.py`
- `value_coercion.py`

If adapter work discovers a foundation gap, patch the foundation branch/interface first instead of hacking around it locally.

---

### Workstream 3: Spreadsheet adapter

Type: parallelizable after foundation lands
Branch: `feature/bulk-create-spreadsheet-adapter`

Objective:
Implement `import` as a thin wrapper over the shared engine.

Scope:
1. CSV parser
2. XLSX parser
3. header normalization
4. alias resolution + conservative Jira metadata fallback
5. per-row normalized issue generation
6. continue-on-error execution mode hookup
7. add CLI wrapper: `jiramator import`
8. add adapter/unit/integration tests

Expected touched files:
- `pyproject.toml`
- `jiramator/input_adapters/spreadsheet.py`
- `jiramator/cli.py`
- `tests/test_spreadsheet_adapter.py`
- `tests/fixtures/*.csv`
- `tests/fixtures/*.xlsx`
- `tests/test_cli_bulk_create.py`

Files that should NOT be substantially redefined here:
- `config.py`
- `field_resolver.py`
- `value_coercion.py`

Again: if the adapter needs a foundation change, that change should be made in the shared foundation and then rebased/merged forward.

---

### Workstream 4: Final integration and hardening

Type: serial
Branch: `feature/bulk-create-integration`

Objective:
Merge the completed branches, resolve interface mismatches, and prove the full system works coherently.

Scope:
1. merge foundation + YAML adapter + spreadsheet adapter
2. reconcile `cli.py`
3. add/expand end-to-end tests
4. verify no drift in preview/report behavior
5. finalize README command docs
6. full test suite run
7. regression check that `plan` still works untouched

Expected touched files:
- `jiramator/cli.py`
- `README.md`
- `tests/test_integration.py`
- possibly `tests/test_cli_bulk_create.py`

Why serial:
This is the convergence point. Parallelizing convergence is nonsense.

---

## Practical parallelization matrix

### Can run in parallel now?
No.

Reason:
- repo is dirty
- foundation interfaces are not implemented yet

### Can run in parallel after Workstream 1?
Yes.

Parallel pair:
- YAML adapter branch
- spreadsheet adapter branch

Shared dependency:
- foundation branch merged or rebased into both first

### Can docs cleanup run in parallel with foundation?
Not really worth it.

Reason:
- tiny amount of work
- touches README and planning docs that foundation likely also touches
- better to do it together as the first checkpoint

---

## Branch creation commands (recommended sequence)

Do not run these until the current dirty state is either committed or intentionally stashed.

### Step 1: checkpoint current planning/docs state

Option A: commit on a dedicated branch

```bash
git checkout -b chore/bulk-create-planning-checkpoint
git add README.md configs/org/marketaxess.yaml configs/teams/issue-spec.template.yaml docs/
git commit -m "docs: checkpoint bulk-create architecture and planning"
```

Then create foundation from there:

```bash
git checkout -b feature/bulk-create-foundation
```

Option B: if you do not want the checkpoint branch long-term, create foundation directly after the commit:

```bash
git checkout -b feature/bulk-create-foundation
git add README.md configs/org/marketaxess.yaml configs/teams/issue-spec.template.yaml docs/
git commit -m "docs: establish bulk-create architecture baseline"
```

### Step 2: after foundation shared APIs land

```bash
git checkout feature/bulk-create-foundation
git checkout -b feature/bulk-create-yaml-adapter
git checkout feature/bulk-create-foundation
git checkout -b feature/bulk-create-spreadsheet-adapter
```

### Step 3: integration branch

```bash
git checkout feature/bulk-create-foundation
git checkout -b feature/bulk-create-integration
```

Then merge adapters one at a time into integration.

---

## Suggested ownership model for subagent-driven development

Using the subagent-driven-development skill, assign ownership like this:

### Foundation owner
Single subagent or sequential subagents, because the files are tightly coupled.

Tasks:
- config schema
- Jira client field metadata
- resolver
- coercion
- preview
- shared bulk-create shell

### YAML adapter owner
Separate subagent after foundation completes.

Tasks:
- issue-spec parser
- normalized issue emission
- create-issues CLI wrapper
- adapter tests

### Spreadsheet adapter owner
Separate subagent after foundation completes.

Tasks:
- csv/xlsx parsing
- row normalization
- import CLI wrapper
- adapter tests

### Integration reviewer
Separate subagent for final convergence.

Tasks:
- merge sanity
- test suite
- CLI consistency
- doc consistency

---

## Review gates per workstream

### Foundation gate
Must pass before parallel adapter work starts:
- config tests pass
- Jira client tests pass
- resolver tests pass
- coercion tests pass
- preview tests pass
- shared interfaces are documented in code comments/docstrings

### YAML adapter gate
Must pass before integration:
- issue-spec parsing tests pass
- create-issues dry-run works
- create-issues live-mode orchestration is tested/mocked
- sub-task rejection is explicit and tested

### Spreadsheet adapter gate
Must pass before integration:
- csv tests pass
- xlsx tests pass
- unknown header skip warnings are tested
- continue-on-error behavior is tested
- import dry-run works

### Final integration gate
Must pass before merge to main:
- full pytest suite passes
- `jiramator --help` lists expected commands
- `jiramator plan` regression check passes
- README matches actual CLI behavior

---

## Merge conflict hotspots to expect

Be honest about where conflicts will happen even with good branch hygiene:

1. `jiramator/cli.py`
- both adapters add commands
- solve this in integration branch deliberately

2. `README.md`
- both adapter branches may want docs updates
- better to centralize final user docs in integration branch

3. shared test helpers / fixtures
- if both adapters add common fixtures, naming may collide

Mitigation:
- minimize README edits on adapter branches
- minimize `cli.py` edits by using obvious insertion points
- keep adapter tests isolated by filename and fixture names

---

## Recommendation: should we create branches right now?

Not yet.

Why:
- current tree is dirty
- planning/docs checkpoint is not committed
- foundation API is not defined in code
- creating adapter branches now would be premature and messy

What should happen right now instead:
1. commit/checkpoint the planning/docs state
2. start foundation branch
3. implement and review shared foundation
4. only then fork YAML and spreadsheet branches in parallel

That is the robust process.

---

## Immediate next actions

1. Checkpoint current state into git
2. Create `feature/bulk-create-foundation`
3. Implement Workstream 0 + Workstream 1 serially
4. After foundation passes review, fork:
   - `feature/bulk-create-yaml-adapter`
   - `feature/bulk-create-spreadsheet-adapter`
5. Merge both into `feature/bulk-create-integration`
6. Run full review + test suite
7. Merge to `main`

---

## Bottom line

Parallelization is practical here, but only after the shared foundation exists.

Safe parallel split:
- foundation first
- YAML adapter and spreadsheet adapter second, in parallel
- integration last

Unsafe parallel split:
- branching immediately from the current dirty `main`
- letting both adapters invent shared APIs independently

That would be fake speed.
