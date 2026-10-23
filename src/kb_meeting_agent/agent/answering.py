from __future__ import annotations

from typing import Literal

from pydantic import create_model

from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.prompting import format_chunks
from kb_meeting_agent.llm.base import LLMProvider, Schema, complete
from kb_meeting_agent.models import Chunk
from kb_meeting_agent.ports import KnowledgeBase

MAX_QUERIES = 3
MAX_CHUNKS = 10
SECTION_MAX_CHARS = 6000
EXCERPTS_MAX_CHARS = 30000  # about 10k tokens: fits a 16k context (Ollama on the Mac mini)


class Queries(Schema):
    queries: list[str]
    tags: list[str]


def queries_model(free_tags: list[str]) -> type[Queries]:
    """Queries whose `tags` can only name the project's free tags (a JSON schema enum)."""
    if not free_tags:
        return Queries
    return create_model(
        "Queries",
        __base__=Queries,
        tags=(list[Literal[tuple(free_tags)]], ...),  # type: ignore[valid-type]
    )


class Answer(Schema):
    covered: bool
    answer: str
    sources: list[str]


QUERIES_SYSTEM = """Rewrite the question into 1 to 3 short search queries for a keyword + semantic search over a knowledge base and source code.
When the glossary maps a name to a technical identifier, include both.
{tags}
GLOSSARY:
{glossary}"""

TAGS_HINT = """Also list in "tags" the parts of the project the question is about, among: {tags}. Leave it empty when the question points at none."""
NO_TAGS_HINT = """Leave "tags" empty."""

ANSWER_SYSTEM = """You answer a question asked during a meeting, using ONLY the excerpts provided: knowledge base pages and, when present, source code (excerpts with a `tags` attribute). Never use outside knowledge.
If the excerpts do not answer the question, set `covered` to false.
When you use code, explain what the code does and say so ("the code does…"), separately from what the knowledge base says ("the KB says…"). Never copy more than two lines of code.
List in `sources` the `source` attribute of every excerpt you used, copied exactly.
When an item's status is not in production, say so.
Answer in language "{language}", in at most 4 sentences."""


async def answer_question(
    fast: LLMProvider,
    strong: LLMProvider,
    kb: KnowledgeBase,
    *,
    question: str,
    context: str,
    language: str,
) -> str:
    free_tags = kb.free_tags
    hint = TAGS_HINT.format(tags=", ".join(free_tags)) if free_tags else NO_TAGS_HINT
    planned = await complete(
        fast,
        QUERIES_SYSTEM.format(tags=hint, glossary=kb.glossary() or "(none)"),
        f"RECENT TRANSCRIPT:\n{context}\n\nQUESTION:\n{question}",
        queries_model(free_tags),
    )
    prefer = tuple(tag for tag in planned.tags if tag in free_tags)
    chunks: list[Chunk] = []
    seen: set[tuple[str, str]] = set()
    for query in (planned.queries or [question])[:MAX_QUERIES]:
        for chunk in await kb.search(query, k=5, prefer_tags=prefer):
            key = (chunk.anchor, chunk.text)
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)
    chunks = _with_sections(kb, chunks[:MAX_CHUNKS])
    if not chunks:
        return t(language, "not_covered")
    answer = await complete(
        strong,
        ANSWER_SYSTEM.format(language=language),
        f"QUESTION:\n{question}\n\nEXCERPTS:\n{format_chunks(chunks)}",
        Answer,
    )
    if not answer.covered:
        return t(language, "not_covered")
    cited = (_source_chunk(chunks, source) for source in answer.sources)
    sources = dict.fromkeys(_cite(kb, chunk) for chunk in cited if chunk)
    return t(language, "answer", answer=answer.answer, sources=", ".join(sources) or "—")


def _source_chunk(chunks: list[Chunk], source: str) -> Chunk | None:
    """The excerpt a source names. Small models often drop the end of the anchor (qwen3:8b
    cites `back:src/x.php` for `back:src/x.php:12-70`): then the first excerpt of that file."""
    for chunk in chunks:
        if chunk.anchor == source:
            return chunk
    for chunk in chunks:
        file = f"{chunk.repo}:{chunk.path}" if chunk.start_line is not None else chunk.path
        if file == source:
            return chunk
    return None


def _cite(kb: KnowledgeBase, chunk: Chunk) -> str:
    """`anchor` for a KB page; `[Tag]` and the anchor linked to its lines for code."""
    if chunk.start_line is None:
        return f"`{chunk.anchor}`"
    label = chunk.citation.removesuffix(f" {chunk.anchor}")
    link = kb.link(chunk)
    return f"`{label}` [{chunk.anchor}]({link})" if link else f"`{label}` `{chunk.anchor}`"


def _with_sections(kb: KnowledgeBase, chunks: list[Chunk]) -> list[Chunk]:
    """Each chunk with the other chunks of its section, when the section was split: a table
    cut in parts is then read whole, where a question listing its rows would see only some.
    The search results are always kept; sections are added while the excerpts fit in
    EXCERPTS_MAX_CHARS, past which a local model's context would silently drop the prompt's start."""
    result: list[Chunk] = []
    seen: set[tuple[str, str]] = set()
    total = 0
    for i, chunk in enumerate(chunks):
        pieces = kb.section(chunk)
        if chunk not in pieces or sum(len(piece.text) for piece in pieces) > SECTION_MAX_CHARS:
            pieces = [chunk]
        new = [piece for piece in pieces if (piece.anchor, piece.text) not in seen]
        later = sum(len(c.text) for c in chunks[i + 1 :])
        if len(new) > 1 and total + sum(len(p.text) for p in new) + later > EXCERPTS_MAX_CHARS:
            new = [piece for piece in new if piece == chunk]
        for piece in new:
            seen.add((piece.anchor, piece.text))
            result.append(piece)
            total += len(piece.text)
    return result
