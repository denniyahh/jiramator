#!/usr/bin/env python3
"""Dry-run preview of PI28 ticket plan with sprint assignments."""
from jiramator.config import load_org_config, load_team_config
from jiramator.ticket_builder import build_all

org, _ = load_org_config("configs/org.example/example.yaml")
team, _ = load_team_config("tests/fixtures/teams/calcs.yaml")

result = build_all(
    org, team,
    pi_label="PI28", pi_num="28",
    versions=["26.2.1", "26.2.2", "26.3.0"],
    epic_keys={"bau": "CA-4829", "misc": "CA-4830"},
)

fmt = "{:>3}  {:<58} {:<8} {:<7} {}"

print("=== PER-RELEASE TICKETS ===")
print(fmt.format("#", "Summary", "FixVer", "Sprint", "Epic"))
print("-" * 100)
for i, tk in enumerate(result["per_release"], 1):
    f = tk["fields"]
    fv = ", ".join(v["name"] for v in f.get("fixVersions", []))
    sp = tk.get("_sprint_num", "-")
    ep = f.get("customfield_10014", "-")
    print(fmt.format(i, f["summary"], fv, sp, ep))

print()
print("=== PER-SPRINT TICKETS ===")
print(fmt.format("#", "Summary", "FixVer", "Sprint", "Epic"))
print("-" * 100)
for i, tk in enumerate(result["per_sprint"], 1):
    f = tk["fields"]
    fv = ", ".join(v["name"] for v in f.get("fixVersions", []))
    sp = tk.get("_sprint_num", "-")
    ep = f.get("customfield_10014", "-")
    print(fmt.format(i, f["summary"], fv, sp, ep))

total = len(result["per_release"]) + len(result["per_sprint"])
print()
print("Total: {} tickets (0 epics, {} per-release, {} per-sprint)".format(
    total, len(result["per_release"]), len(result["per_sprint"])))
