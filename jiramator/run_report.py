"""Run report schema, atomic IO, and resume-discovery (FOUND-02).

See .planning/phases/01-reliability-robustness/01-RESEARCH.md §Pattern 3
for design rationale and §Example 3 for the canonical hash recipe.

Public surface (Plan 04 callers depend on these names verbatim):
- ``SCHEMA_VERSION`` / ``RUNS_DIR`` — module constants.
- ``IssueStatus`` / ``RunStatus`` / ``IssueKind`` — Literal aliases.
- ``IssueResult`` / ``RunReport`` — pure dataclasses (no Pydantic).
- ``ConfigDriftError`` — raised by Plan 04 callers when --resume detects
  a hash mismatch with the prior run.
- ``write_report_atomic`` — tempfile + os.replace; survives Ctrl-C.
- ``default_report_path`` — produces ``.jiramator/runs/<stamp>-<slug>.json``.
- ``find_resumable`` — most-recent partial/failed report whose stored
  team_config_path matches the resolved input; corrupt files skipped.
- ``compute_resolved_hash`` — sha256(canonical-json) of (org, team, pi, versions).

Stdlib only — no external imports.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:  # avoid an import cycle if config ever pulls run_report
    from jiramator.config import OrgConfig, TeamConfig


# ---------------------------------------------------------------------------
# Constants and type aliases
# ---------------------------------------------------------------------------

SCHEMA_VERSION: int = 1
RUNS_DIR: Path = Path(".jiramator/runs")

IssueStatus = Literal["created", "skipped", "failed", "pending"]
RunStatus = Literal["success", "partial", "failed"]
IssueKind = Literal["epic", "per_release", "per_sprint", "imported"]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfigDriftError(Exception):
    """Raised when --resume detects the resolved-config hash differs from the
    prior run's hash.

    cli.py catches this, formats a user-facing message naming both the prior
    and current hashes (first 12 chars), and exits 1 unless --force was passed.

    Subclasses ``Exception`` (NOT ``ValueError``) so callers can catch it
    distinctly from FOUND-01's ``ConfigValidationError`` and from arbitrary
    Pydantic ValueError paths.
    """


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IssueResult:
    """Per-issue result row stored inside ``RunReport.issues``."""

    template_key: str
    kind: IssueKind
    status: IssueStatus
    jira_key: str | None = None
    error: str | None = None


@dataclass
class RunReport:
    """One run's output: identification, hash, counts, per-issue results.

    Fields:
        schema_version: Always ``SCHEMA_VERSION`` for this version of jiramator.
        command: ``sys.argv``-shaped list. Caller is responsible for not
            putting secrets on the CLI; we never store env values.
        started_at / ended_at: ISO8601 UTC strings (e.g. ``2026-04-29T10:00:00Z``).
        team_config_path / org_config_path: absolute, resolved paths.
        team_name / pi_label / versions: human-readable identification.
        resolved_config_hash: sha256 of canonical-json(org, team, pi, versions).
        status: ``success`` only when set explicitly at end of a clean run.
            Default is pessimistic (``failed``) so an interrupted process
            leaves the report marked failed unless it had time to flip it.
        counts: rolling counters; total per-issue == sum of values.
        issues: per-template/per-version IssueResult entries.
    """

    schema_version: int = SCHEMA_VERSION
    command: list[str] = field(default_factory=list)
    started_at: str = ""
    ended_at: str | None = None
    team_config_path: str = ""
    org_config_path: str = ""
    team_name: str = ""
    pi_label: str | None = None
    versions: list[str] = field(default_factory=list)
    resolved_config_hash: str = ""
    status: RunStatus = "failed"
    counts: dict[str, int] = field(
        default_factory=lambda: {"created": 0, "skipped": 0, "failed": 0}
    )
    issues: list[IssueResult] = field(default_factory=list)

    def to_envelope(self) -> dict[str, Any]:
        """Render as ``{"schema_version": N, "run": {...}}`` for JSON write.

        ``asdict`` recurses into nested IssueResult dataclasses producing
        plain dicts — that's the on-disk shape we want.
        """
        return {"schema_version": self.schema_version, "run": asdict(self)}

    @classmethod
    def from_envelope(cls, obj: dict[str, Any]) -> RunReport:
        """Parse a ``{"schema_version": N, "run": {...}}`` envelope.

        Raises:
            ValueError: When ``schema_version != SCHEMA_VERSION`` or the
                envelope shape is missing the expected keys. The message
                names both the rejected version and the supported one.
        """
        if obj.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported run report schema_version: {obj.get('schema_version')}; "
                f"this version of jiramator only reads schema_version={SCHEMA_VERSION}."
            )
        run = dict(obj["run"])  # shallow copy — don't mutate caller's dict
        run["issues"] = [IssueResult(**i) for i in run.get("issues", [])]
        return cls(**run)


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def write_report_atomic(report: RunReport, path: Path) -> None:
    """Write ``report`` to ``path`` atomically.

    Implementation:
      1. Ensure the parent directory exists (created if missing).
      2. Open a NamedTemporaryFile in the SAME directory (must be same
         filesystem so ``os.replace`` is atomic — cross-fs replace raises).
      3. Write JSON, fsync, close.
      4. ``os.replace(tmp, path)`` — POSIX-atomic rename.
      5. On ANY exception (including KeyboardInterrupt), unlink the tmp
         file so we don't leave dangling ``*.tmp`` debris.

    The original destination file (if any) is never modified until step 4
    succeeds; if step 4 raises (e.g. cross-fs ``OSError``), the original
    is intact.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(report.to_envelope(), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Clean up the temp file on any failure (regular exception or
        # KeyboardInterrupt mid-write — Ctrl-C is a likely real trigger).
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Path generation
# ---------------------------------------------------------------------------


def default_report_path(team_config_path: Path) -> Path:
    """Return ``RUNS_DIR / "<UTC-stamp>-<team-slug>.json"``.

    Stamp format: ``%Y%m%dT%H%M%SZ`` (e.g. ``20260429T103045Z``).
    Slug: ``team_config_path.stem`` with ``/`` replaced by ``_`` for
    defense in depth. (Path.stem already strips parents and the extension,
    but the replace is cheap insurance against future surprises.)
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = team_config_path.stem.replace("/", "_")
    return RUNS_DIR / f"{stamp}-{slug}.json"


# ---------------------------------------------------------------------------
# Resume discovery
# ---------------------------------------------------------------------------


def find_resumable(team_config_path: Path) -> Path | None:
    """Return the most-recent resumable report path for ``team_config_path``.

    "Resumable" means: status is ``partial`` or ``failed`` (NOT ``success``,
    which means the run completed cleanly and has nothing to resume).

    Returns ``None`` when:
      - ``RUNS_DIR`` doesn't exist.
      - ``RUNS_DIR`` exists but contains no candidates.
      - No candidate's stored ``team_config_path`` resolves to the same
        absolute path as the input.

    Robust to:
      - Corrupt JSON in the directory (silently skipped).
      - Valid JSON missing the ``run`` key or expected fields (silently
        skipped — wrap in try/except (KeyError, ValueError)).
      - Symlinks: input and stored paths are both ``.resolve()``-d before
        comparison.
    """
    if not RUNS_DIR.exists():
        return None

    target = str(team_config_path.resolve())
    candidates: list[tuple[str, Path]] = []  # (started_at, file_path)
    for entry in RUNS_DIR.iterdir():
        if not entry.is_file() or entry.suffix != ".json":
            continue
        try:
            envelope = json.loads(entry.read_text(encoding="utf-8"))
            run = envelope["run"]
            if run.get("status") == "success":
                continue
            stored_path = run.get("team_config_path", "")
            # Resolve stored path too — symlinks may have been canonicalized
            # at write time, but we can't assume it. Compare resolved forms.
            try:
                stored_resolved = str(Path(stored_path).resolve())
            except OSError:
                stored_resolved = stored_path
            if stored_resolved != target:
                continue
            candidates.append((run.get("started_at", ""), entry))
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError):
            # Silently skip — a single corrupt file must not block discovery.
            continue

    if not candidates:
        return None
    # ISO8601 strings sort lexicographically; descending = most recent first.
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Resolved-config hash
# ---------------------------------------------------------------------------


def compute_resolved_hash(
    org_config: OrgConfig,
    team_config: TeamConfig,
    pi_label: str | None,
    versions: list[str],
) -> str:
    """Return a deterministic sha256 hex of the resolved planning inputs.

    Determinism guarantees:
      - ``sort_keys=True`` makes dict ordering irrelevant.
      - ``model_dump(mode="json")`` produces JSON-compatible primitives
        (datetime/Path/etc. become strings) so ``json.dumps`` never
        encounters a non-serializable type.
      - ``versions`` is copied (``list(versions)``) so a caller mutating
        the input list after the call doesn't change the hash output.

    Order-sensitivity: ``versions`` is treated as ordered (release order
    matters semantically — sprint N gets versions[N]). Reordering produces
    a different hash. ``pi_label=None`` is hashed distinctly from any
    string value.
    """
    payload = {
        "org": org_config.model_dump(mode="json"),
        "team": team_config.model_dump(mode="json"),
        "pi_label": pi_label,
        "versions": list(versions),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
