"""Pydantic models for org-level and team-level Jiramator configs."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

# Known template variables that can appear in {brackets} in config strings.
# The ticket builder will provide concrete values for these at runtime.
KNOWN_TEMPLATE_VARS = frozenset({
    "pi_label",     # e.g. "PI28"
    "pi_num",       # e.g. "28"
    "version",      # e.g. "26.1.1" — only valid in per_release_tickets
    "sprint_num",   # e.g. "1", "6a" — only valid in per_sprint_tickets
    "team_name",    # e.g. "Calcs"
})

# Regex to find {var} template references in strings
_TEMPLATE_VAR_RE = re.compile(r"\{(\w+)\}")

# Regex to find $epic:key references
_EPIC_REF_RE = re.compile(r"^\$epic:(\w+)$")


# ---------------------------------------------------------------------------
# Org config — shared across all teams at a company
# ---------------------------------------------------------------------------


class SprintConfig(BaseModel):
    """Sprint cadence for a PI."""

    count: int = Field(gt=0, description="Total number of sprints in a PI")
    standard_length_weeks: int = Field(gt=0, description="Length of standard sprints in weeks")
    long_length_weeks: int = Field(gt=0, description="Length of long (extended) sprints in weeks")
    long_sprints: list[int] = Field(
        default_factory=list,
        description="Sprint numbers that use long_length_weeks (1-indexed)",
    )

    @field_validator("long_sprints")
    @classmethod
    def validate_long_sprints(cls, v: list[int], info: Any) -> list[int]:
        """Ensure long sprint numbers are within the valid range."""
        count = info.data.get("count")
        if count is not None:
            for sprint_num in v:
                if sprint_num < 1 or sprint_num > count:
                    raise ValueError(
                        f"long_sprint {sprint_num} is out of range (1-{count})"
                    )
        return v


class OrgConfig(BaseModel):
    """Organization-level configuration — Jira instance, custom fields, sprint structure."""

    jira_url: HttpUrl = Field(description="Base URL of the Jira instance")
    jira_email_env: str = Field(
        default="JIRA_EMAIL",
        description="Name of the env var containing the Jira user email",
    )
    jira_token_env: str = Field(
        default="JIRA_TOKEN",
        description="Name of the env var containing the Jira API token",
    )
    custom_fields: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of logical field names to Jira custom field IDs",
    )
    sprints: SprintConfig = Field(description="Sprint cadence configuration")

    def get_custom_field_id(self, logical_name: str) -> str:
        """Look up a custom field ID by its logical name.

        Raises KeyError if the logical name is not defined.
        """
        try:
            return self.custom_fields[logical_name]
        except KeyError:
            raise KeyError(
                f"Custom field '{logical_name}' is not defined in org config. "
                f"Available fields: {list(self.custom_fields.keys())}"
            )

    def resolve_credentials(self) -> tuple[str, str]:
        """Read Jira credentials from environment variables.

        Returns (email, token) tuple.
        Raises ValueError if either env var is missing or empty.
        """
        email = os.environ.get(self.jira_email_env, "").strip()
        token = os.environ.get(self.jira_token_env, "").strip()

        missing = []
        if not email:
            missing.append(self.jira_email_env)
        if not token:
            missing.append(self.jira_token_env)

        if missing:
            raise ValueError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                f"Set them before running jiramator."
            )

        return email, token


# ---------------------------------------------------------------------------
# Config loading utilities
# ---------------------------------------------------------------------------


def load_org_config(path: str | Path) -> OrgConfig:
    """Load and validate an org config from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Org config not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Org config must be a YAML mapping, got {type(raw).__name__}")

    return OrgConfig(**raw)


# ---------------------------------------------------------------------------
# Team config — per-team ticket templates and conventions
# ---------------------------------------------------------------------------


def _validate_template_vars(text: str, context: str) -> None:
    """Check that all {var} references in a string are known template variables.

    Raises ValueError with a clear message if unknown variables are found.
    """
    found = set(_TEMPLATE_VAR_RE.findall(text))
    unknown = found - KNOWN_TEMPLATE_VARS
    if unknown:
        raise ValueError(
            f"Unknown template variable(s) in {context}: "
            f"{', '.join(sorted(unknown))}. "
            f"Known variables: {', '.join(sorted(KNOWN_TEMPLATE_VARS))}"
        )


def _collect_epic_refs(fields: dict[str, Any]) -> set[str]:
    """Recursively find all $epic:key references in a fields dict."""
    refs: set[str] = set()
    for value in fields.values():
        if isinstance(value, str):
            m = _EPIC_REF_RE.match(value)
            if m:
                refs.add(m.group(1))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    m = _EPIC_REF_RE.match(item)
                    if m:
                        refs.add(m.group(1))
    return refs


def _collect_template_vars_in_fields(fields: dict[str, Any], context: str) -> None:
    """Validate template variables in all string values within a fields dict."""
    for key, value in fields.items():
        if isinstance(value, str) and not value.startswith("$epic:"):
            _validate_template_vars(value, f"{context}.fields.{key}")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, str) and not item.startswith("$epic:"):
                    _validate_template_vars(item, f"{context}.fields.{key}[{i}]")


class EpicTemplate(BaseModel):
    """Template for a recurring epic created each PI."""

    key: str = Field(description="Internal reference key (e.g. 'bau', 'misc')")
    summary: str = Field(description="Epic summary template (supports {variables})")

    @field_validator("summary")
    @classmethod
    def validate_summary_vars(cls, v: str) -> str:
        _validate_template_vars(v, "epic.summary")
        return v


class TicketTemplate(BaseModel):
    """Template for a recurring ticket generated per release or per sprint."""

    summary: str = Field(description="Ticket summary template (supports {variables})")
    fields: dict[str, Any] = Field(
        default_factory=dict,
        description="Jira field values — keys are field names or custom field IDs",
    )
    extra_on_long_sprint: int = Field(
        default=0,
        ge=0,
        description="Additional tickets to create on long sprints (per_sprint only)",
    )
    long_sprint_suffix: list[str] = Field(
        default_factory=list,
        description="Suffixes for sprint_num on long sprints (e.g. ['a', 'b'])",
    )

    @field_validator("summary")
    @classmethod
    def validate_summary_vars(cls, v: str) -> str:
        _validate_template_vars(v, "ticket.summary")
        return v

    @model_validator(mode="after")
    def validate_long_sprint_suffix_count(self) -> TicketTemplate:
        """If extra_on_long_sprint > 0, we need exactly 1 + extra suffixes."""
        if self.extra_on_long_sprint > 0:
            expected = 1 + self.extra_on_long_sprint
            if len(self.long_sprint_suffix) != expected:
                raise ValueError(
                    f"extra_on_long_sprint={self.extra_on_long_sprint} requires "
                    f"{expected} long_sprint_suffix entries (original + extras), "
                    f"got {len(self.long_sprint_suffix)}: {self.long_sprint_suffix}"
                )
        return self


class TeamConfig(BaseModel):
    """Team-level configuration — project key, epics, ticket templates."""

    project_key: str = Field(description="Jira project key (e.g. 'CA')")
    team_name: str = Field(description="Human-readable team name (e.g. 'Calcs')")
    board_id: int | None = Field(
        default=None,
        description="Jira board ID for sprint assignment (optional)",
    )
    sprint_name_template: str | None = Field(
        default=None,
        description="Sprint name pattern for matching (e.g. 'CA Sprint {pi_num}.{sprint_num}')",
    )

    recurring_epics: list[EpicTemplate] = Field(
        default_factory=list,
        description="Epics to create at the start of each PI",
    )
    per_release_tickets: list[TicketTemplate] = Field(
        default_factory=list,
        description="Tickets generated once per release version",
    )
    per_sprint_tickets: list[TicketTemplate] = Field(
        default_factory=list,
        description="Tickets generated once per sprint",
    )

    @field_validator("recurring_epics")
    @classmethod
    def validate_unique_epic_keys(cls, v: list[EpicTemplate]) -> list[EpicTemplate]:
        keys = [e.key for e in v]
        dupes = [k for k in keys if keys.count(k) > 1]
        if dupes:
            raise ValueError(f"Duplicate epic keys: {set(dupes)}")
        return v

    @model_validator(mode="after")
    def validate_epic_refs(self) -> TeamConfig:
        """Ensure all $epic:key references point to defined recurring_epics."""
        epic_keys = {e.key for e in self.recurring_epics}
        all_templates = self.per_release_tickets + self.per_sprint_tickets

        for i, tmpl in enumerate(all_templates):
            refs = _collect_epic_refs(tmpl.fields)
            unknown = refs - epic_keys
            if unknown:
                raise ValueError(
                    f"Ticket template '{tmpl.summary}' references undefined epic(s): "
                    f"{', '.join(sorted(unknown))}. "
                    f"Defined epics: {', '.join(sorted(epic_keys))}"
                )
        return self

    @model_validator(mode="after")
    def validate_field_template_vars(self) -> TeamConfig:
        """Validate template variables in all ticket template fields."""
        for i, tmpl in enumerate(self.per_release_tickets):
            _collect_template_vars_in_fields(
                tmpl.fields, f"per_release_tickets[{i}]"
            )
        for i, tmpl in enumerate(self.per_sprint_tickets):
            _collect_template_vars_in_fields(
                tmpl.fields, f"per_sprint_tickets[{i}]"
            )
        return self

    def get_epic_keys(self) -> list[str]:
        """Return the list of epic reference keys."""
        return [e.key for e in self.recurring_epics]


def load_team_config(path: str | Path) -> TeamConfig:
    """Load and validate a team config from a YAML file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Team config not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Team config must be a YAML mapping, got {type(raw).__name__}")

    return TeamConfig(**raw)
