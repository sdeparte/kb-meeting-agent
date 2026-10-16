from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.prompting import format_chunks
from kb_meeting_agent.conventions import DecisionConventions, render_template
from kb_meeting_agent.llm.base import LLMProvider, Schema, complete
from kb_meeting_agent.models import Chunk


def slugify(text: str, max_len: int = 60) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "decision"


_LEADING_NUMBER = re.compile(r"^(\d+)")


def next_number(paths: Iterable[str], reserved: Iterable[int] = ()) -> int:
    numbers = {
        int(match.group(1))
        for path in paths
        if (match := _LEADING_NUMBER.match(PurePosixPath(path).name))
    }
    return max(numbers | set(reserved), default=0) + 1


_FENCE = re.compile(r"^\s*(```|~~~)")


def append_table_row(content: str, row: str) -> str:
    """Insert the row after the last table row of the file, ignoring code fences."""
    lines = content.splitlines()
    in_code = False
    last_row: int | None = None
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            in_code = not in_code
        elif not in_code and line.lstrip().startswith("|"):
            last_row = i
    if last_row is None:
        return content.rstrip("\n") + "\n" + row + "\n"
    lines.insert(last_row + 1, row)
    return "\n".join(lines) + "\n"


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


DRAFT_SYSTEM = """You write a decision record for a knowledge base, following the KB's own conventions below.
Use only the decision statement, the transcript quote and the KB excerpts. Do not invent facts.
Fields: title (short), slug (kebab-case, ASCII), scope (what it applies to, in the KB's vocabulary), context, decision, consequences (Markdown allowed), related_pages (KB pages this decision probably makes outdated: the path part of an excerpt's source, the section heading, one-sentence reason).
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
) -> DecisionDraft:
    user = (
        f"DECISION: {statement}\n\nTRANSCRIPT QUOTE: {quote}\n\n"
        f"KB EXCERPTS:\n{format_chunks(chunks)}"
    )
    system = DRAFT_SYSTEM.format(language=language, instructions=instructions or "(none)")
    return await complete(strong, system, user, DecisionDraft)


@dataclass(frozen=True)
class Change:
    branch: str
    files: dict[str, str]
    title: str
    body: str


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
    if conventions.index and index_content is not None:
        row = render_template(conventions.index.row, values | {"filename": filename, "path": path})
        files[conventions.index.file] = append_table_row(index_content, row)
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
    )
