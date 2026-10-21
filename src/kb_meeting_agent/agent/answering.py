from __future__ import annotations

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


class Answer(Schema):
    covered: bool
    answer: str
    sources: list[str]


QUERIES_SYSTEM = """Rewrite the question into 1 to 3 short search queries for a keyword + semantic search over a knowledge base.
When the glossary maps a name to a technical identifier, include both.
GLOSSARY:
{glossary}"""

ANSWER_SYSTEM = """You answer a question asked during a meeting, using ONLY the knowledge base excerpts provided. Never use outside knowledge.
If the excerpts do not answer the question, set `covered` to false.
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
    planned = await complete(
        fast,
        QUERIES_SYSTEM.format(glossary=kb.glossary() or "(none)"),
        f"RECENT TRANSCRIPT:\n{context}\n\nQUESTION:\n{question}",
        Queries,
    )
    chunks: list[Chunk] = []
    seen: set[tuple[str, str]] = set()
    for query in (planned.queries or [question])[:MAX_QUERIES]:
        for chunk in await kb.search(query, k=5):
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
        f"QUESTION:\n{question}\n\nKB EXCERPTS:\n{format_chunks(chunks)}",
        Answer,
    )
    if not answer.covered:
        return t(language, "not_covered")
    anchors = {chunk.anchor for chunk in chunks}
    sources = [source for source in answer.sources if source in anchors]
    return t(
        language,
        "answer",
        answer=answer.answer,
        sources=", ".join(f"`{source}`" for source in sources) or "—",
    )


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
