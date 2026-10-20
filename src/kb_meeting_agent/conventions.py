from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

CONVENTIONS_FILE = ".meeting-agent.yml"

StatusMeaning = Literal["in_production", "in_progress", "planned", "rejected"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageHeader(_Strict):
    verified_date: str | None = None


class StatusRule(_Strict):
    pattern: str
    meaning: StatusMeaning


class IndexConfig(_Strict):
    file: str
    row: str


class DecisionConventions(_Strict):
    dir: str = "decisions"
    filename: str = "{number:04d}-{slug}.md"
    template: str | None = None
    default_status: str = "accepted"
    scopes: list[str] = Field(default_factory=list)  # empty: any scope the model writes
    index: IndexConfig | None = None
    branch: str = "decision/{date}-{slug}"


class MinutesConventions(_Strict):
    dir: str = "meetings"
    filename: str = "{date}-{slug}.md"
    template: str | None = None
    branch: str = "meetings/{date}-{slug}"


class KbConventions(_Strict):
    language: str = "en"
    instructions: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    authoritative: list[str] = Field(default_factory=list)
    glossary: str | None = None
    page_header: PageHeader = Field(default_factory=PageHeader)
    statuses: list[StatusRule] = Field(default_factory=list)
    decisions: DecisionConventions = Field(default_factory=DecisionConventions)
    minutes: MinutesConventions = Field(default_factory=MinutesConventions)


def load_conventions(repo_dir: Path) -> KbConventions:
    path = repo_dir / CONVENTIONS_FILE
    if not path.exists():
        return KbConventions()
    return KbConventions.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def load_template(repo_dir: Path, relative: str | None, default_name: str) -> str:
    if relative:
        root = repo_dir.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"template outside the KB: {relative}")
        return path.read_text(encoding="utf-8")
    return resources.files("kb_meeting_agent.templates").joinpath(default_name).read_text("utf-8")


_PLACEHOLDER = re.compile(r"\{(\w+)(?::([^{}]*))?\}")


def render_template(template: str, values: dict[str, object]) -> str:
    """Replace {key} and {key:spec} for known keys only; leave any other brace untouched."""

    def replace(match: re.Match[str]) -> str:
        key, spec = match.group(1), match.group(2)
        if key not in values:
            return match.group(0)
        return format(values[key], spec or "")

    return _PLACEHOLDER.sub(replace, template)
