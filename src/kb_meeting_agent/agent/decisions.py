from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import PurePosixPath

from pydantic import ConfigDict, Field, field_validator

from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.prompting import format_chunks
from kb_meeting_agent.conventions import (
    DecisionConventions,
    IndexConfig,
    fold,
    render_template,
    scope_key,
)
from kb_meeting_agent.llm.base import LLMProvider, Schema, complete
from kb_meeting_agent.models import Chunk

log = logging.getLogger(__name__)


def slugify(text: str, max_len: int = 60) -> str:
    ascii_text = fold(text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "decision"


_LEADING_NUMBER = re.compile(r"^(\d+)")


def existing_numbers(paths: Iterable[str]) -> set[int]:
    return {
        int(match.group(1))
        for path in paths
        if (match := _LEADING_NUMBER.match(PurePosixPath(path).name))
    }


def next_number(paths: Iterable[str], reserved: Iterable[int] = ()) -> int:
    return max(existing_numbers(paths) | set(reserved), default=0) + 1


_FENCE = re.compile(r"^\s*(```|~~~)")


def append_table_row(content: str, row: str) -> str | None:
    """Insert the row after the last table row of the file, ignoring code fences; None if the
    file has no table (a row on its own would not render as one)."""
    lines = content.splitlines()
    in_code = False
    last_row: int | None = None
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_code = not in_code
        elif not in_code and line.lstrip().startswith("|"):
            last_row = i
    if last_row is None:
        return None
    lines.insert(last_row + 1, row)
    return "\n".join(lines) + "\n"


def _table_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    return " ".join(value.split()).replace("|", "\\|")


def index_row(index: IndexConfig, values: Mapping[str, object]) -> str:
    return render_template(index.row, {key: _table_cell(value) for key, value in values.items()})


def index_files(
    index: IndexConfig | None, content: str | None, values: Mapping[str, object]
) -> dict[str, str]:
    """The index file with a row for `values`; nothing without an index, its file or a table."""
    if index is None or content is None:
        return {}
    updated = append_table_row(content, index_row(index, values))
    if updated is None:
        log.warning("%s has no table: no index row added", index.file)
        return {}
    return {index.file: updated}


def added_rows(
    index: IndexConfig | None, files: Mapping[str, str], values: Mapping[str, object]
) -> dict[str, str]:
    """The row added to the index, by index file, if `files` carries the index."""
    if index is None or index.file not in files:
        return {}
    return {index.file: index_row(index, values)}


class RelatedPage(Schema):
    path: str
    section: str
    reason: str


class DecisionDraft(Schema):
    title: str
    slug: str
    scope: str
    context: str
    decision: str
    consequences: str
    related_pages: list[RelatedPage]


@cache
def _draft_model(scopes: tuple[str, ...]) -> type[DecisionDraft]:
    """DecisionDraft whose scope must be one of `scopes`; case, accent and spacing variants
    are mapped to the listed spelling, anything else fails validation (and is re-asked once)."""
    if not scopes:
        return DecisionDraft
    listed = {scope_key(scope): scope for scope in scopes}

    class ScopedDecisionDraft(DecisionDraft):
        model_config = ConfigDict(title="DecisionDraft")
        # enum rather than Literal, which gives `const` for a single scope
        scope: str = Field(json_schema_extra={"enum": list(scopes)})

        @field_validator("scope")
        @classmethod
        def _listed_spelling(cls, value: str) -> str:
            if (scope := listed.get(scope_key(value))) is None:
                raise ValueError(f"scope must be one of {list(scopes)}")
            return scope

    return ScopedDecisionDraft


FREE_SCOPE = "scope (what it applies to, in the KB's vocabulary)"
LISTED_SCOPE = "scope (what it applies to: exactly one of {scopes})"

DRAFT_SYSTEM = """You write a decision record for a knowledge base, following the KB's own conventions below.
Use only the decision statement, the transcript quote and the KB excerpts. Do not invent facts.
Fields: title (short), slug (kebab-case, ASCII), {scope_field}, context, decision, consequences (Markdown allowed), related_pages (KB pages this decision probably makes outdated: the path part of an excerpt's source, the section heading, one-sentence reason).
Write in language "{language}".

KB CONVENTIONS:
{instructions}"""


async def draft_decision(
    strong: LLMProvider,
    *,
    statement: str,
    quote: str,
    chunks: list[Chunk],
    instructions: str,
    language: str,
    scopes: Sequence[str] = (),
) -> DecisionDraft:
    """Raises LLMInvalidOutput when the model keeps answering a scope outside `scopes`."""
    user = (
        f"DECISION: {statement}\n\nTRANSCRIPT QUOTE: {quote}\n\n"
        f"KB EXCERPTS:\n{format_chunks(chunks)}"
    )
    scope_field = (
        LISTED_SCOPE.format(scopes=", ".join(json.dumps(s, ensure_ascii=False) for s in scopes))
        if scopes
        else FREE_SCOPE
    )
    system = DRAFT_SYSTEM.format(
        scope_field=scope_field, language=language, instructions=instructions or "(none)"
    )
    draft = await complete(strong, system, user, _draft_model(tuple(scopes)))
    return DecisionDraft.model_validate(draft.model_dump())


INDEX_ROWS_FILE = "INDEX_ROWS.json"  # next to PR.md in a change kept locally


@dataclass(frozen=True)
class Change:
    branch: str
    files: dict[str, str]
    title: str
    body: str
    # Row added to each index file in `files`: a change kept locally is rebuilt from it on
    # the base of the day it is published, instead of resending a stale copy of the index.
    index_rows: dict[str, str] = field(default_factory=dict)


def _blockquote(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines() or [""])


def build_decision_change(
    *,
    conventions: DecisionConventions,
    template: str,
    draft: DecisionDraft,
    number: int | None,
    meeting_date: date,
    quote: str,
    validated_by: str,
    index_content: str | None,
    language: str,
    excerpt_note: str = "",
) -> Change:
    values: dict[str, object] = {
        "title": draft.title,
        "slug": slugify(draft.slug or draft.title),
        "status": conventions.default_status,
        "date": meeting_date.isoformat(),
        "scope": draft.scope,
        "context": draft.context,
        "decision": draft.decision,
        "consequences": draft.consequences,
        "sources": t(
            language, "decision_sources", date=meeting_date.isoformat(), user=validated_by
        ),
    }
    if number is not None:
        values["number"] = number
    filename = render_template(conventions.filename, values)
    path = f"{conventions.dir.rstrip('/')}/{filename}"
    files = {path: render_template(template, values).rstrip() + "\n"}
    row_values = values | {"filename": filename, "path": path}
    files |= index_files(conventions.index, index_content, row_values)
    related = "\n".join(
        f"- `{page.path}` § {page.section} — {page.reason}" for page in draft.related_pages
    ) or t(language, "no_related_pages")
    body = t(
        language,
        "decision_pr_body",
        user=validated_by,
        date=meeting_date.isoformat(),
        quote=(f"{excerpt_note}\n\n" if excerpt_note else "") + _blockquote(quote),
        related=related,
    )
    return Change(
        branch=render_template(conventions.branch, values),
        files=files,
        title=t(language, "decision_pr_title", title=draft.title),
        body=body,
        index_rows=added_rows(conventions.index, files, row_values),
    )
