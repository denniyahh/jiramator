#!/usr/bin/env python3
"""Read-only fingerprint of the jiramator work clone (D-03).

Usage:
    workclone_fingerprint.py snapshot OUT
    workclone_fingerprint.py compare BASELINE

Guarantees:
- stdlib only; never imports jiramator
- never opens a work-clone file for writing; never chdirs into the work clone
- git is invoked with --no-optional-locks so it does not refresh the index

Snapshot format (one entry per line):
    S <git status --porcelain line>
    F <relpath>\t<size>\t<st_mtime_ns>     (regular files under .jiramator/ and configs/, sorted)

compare classifies every difference and ends with exactly one INTEGRITY line:
    INTEGRITY: identical                  exit 0
    INTEGRITY: production-additions-only  exit 0 (only PRODUCTION-RUN additions)
    INTEGRITY: VIOLATION                  exit 1
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.home() / "dev" / "work_projects" / "jiramator"
SCAN_DIRS = (".jiramator", "configs")
RUNS_PREFIX = ".jiramator/runs/"
PHASE_MARKER = "jm-triage"


def _git_status() -> list[str]:
    out = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(ROOT), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _files() -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for sub in SCAN_DIRS:
        base = ROOT / sub
        if not base.is_dir():
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                full = os.path.join(dirpath, name)
                st = os.stat(full, follow_symlinks=False)
                if not os.path.isfile(full) or os.path.islink(full):
                    continue
                rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
                result[rel] = (st.st_size, st.st_mtime_ns)
    return result


def build_snapshot() -> list[str]:
    lines = [f"S {line}" for line in _git_status()]
    files = _files()
    for rel in sorted(files):
        size, mtime = files[rel]
        lines.append(f"F {rel}\t{size}\t{mtime}")
    return lines


def parse(lines: list[str]) -> tuple[list[str], dict[str, tuple[int, int]]]:
    status: list[str] = []
    files: dict[str, tuple[int, int]] = {}
    for line in lines:
        if line.startswith("S "):
            status.append(line[2:])
        elif line.startswith("F "):
            rel, size, mtime = line[2:].split("\t")
            files[rel] = (int(size), int(mtime))
    return status, files


def _run_info(rel: str) -> tuple[str, str]:
    """Read (read-only) a run report's started_at and joined command."""
    try:
        with open(ROOT / rel, encoding="utf-8") as fh:
            run = json.load(fh).get("run", {})
    except (OSError, ValueError):
        return "?", "?"
    cmd = run.get("command", [])
    joined = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
    return str(run.get("started_at", "?")), joined


def compare(baseline_path: str) -> int:
    base_status, base_files = parse(Path(baseline_path).read_text().splitlines())
    cur_status, cur_files = parse(build_snapshot())

    production = 0
    violations = 0

    for rel in sorted(set(cur_files) - set(base_files)):
        if rel.startswith(RUNS_PREFIX) and rel.endswith(".json"):
            started, cmd = _run_info(rel)
            if PHASE_MARKER in cmd:
                print(f"PHASE-RUN {rel}")
                violations += 1
            else:
                print(f"PRODUCTION-RUN {rel} started_at={started} command={cmd}")
                production += 1
        else:
            print(f"ADDED-OTHER {rel}")
            violations += 1
    for rel in sorted(set(base_files) - set(cur_files)):
        print(f"DELETED {rel}")
        violations += 1
    for rel in sorted(set(base_files) & set(cur_files)):
        if base_files[rel] != cur_files[rel]:
            print(f"MODIFIED {rel} before={base_files[rel]} now={cur_files[rel]}")
            violations += 1
    if sorted(base_status) != sorted(cur_status):
        for line in sorted(set(base_status) ^ set(cur_status)):
            side = "now" if line in cur_status else "before"
            print(f"STATUS-CHANGED ({side}) {line}")
        violations += 1

    if violations:
        print("INTEGRITY: VIOLATION")
        return 1
    if production:
        print("INTEGRITY: production-additions-only")
        return 0
    print("INTEGRITY: identical")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("snapshot", "compare"):
        print(__doc__, file=sys.stderr)
        return 2
    if argv[1] == "snapshot":
        lines = build_snapshot()
        Path(argv[2]).write_text("\n".join(lines) + "\n")
        print(f"wrote {len(lines)} lines to {argv[2]}")
        return 0
    return compare(argv[2])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
