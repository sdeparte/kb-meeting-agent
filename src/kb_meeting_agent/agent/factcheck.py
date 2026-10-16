from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from kb_meeting_agent.agent.detection import Claim
from kb_meeting_agent.agent.prompting import format_chunks
from kb_meeting_agent.kb.quote import find_quote_line
from kb_meeting_agent.llm.base import LLMProvider, Schema, complete
from kb_meeting_agent.ports import KnowledgeBase


class Verdict(Schema):
    verdict: Literal["confirms", "contradicts", "not_covered", "already_rejected"]
    kb_quote: str
    path: str
    reason: str
    confidence: float


@dataclass(frozen=True)
class Flag:
    subject: str
    statement: str
    verdict: str
    quote: str
    anchor: str
    reason: str
    stale_since: str | None


FACTCHECK_SYSTEM = """You compare a statement made during a meeting with knowledge base (KB) excerpts.
verdict:
- confirms: the KB states the same thing.
- contradicts: the KB states something incompatible.
- already_rejected: the statement proposes or assumes something the KB marks as rejected.
- not_covered: the excerpts say nothing about it.
A value attached to a planned or in-progress item is not the production value.
kb_quote: copy verbatim, character for character, the shortest KB sentence or table row supporting the verdict (empty when not_covered).
path: the `source` attribute of that excerpt.
reason: one sentence in language "{language}".
confidence: from 0 to 1."""

FLAGGED_VERDICTS = ("contradicts", "already_rejected")


async def check_claim(
    strong: LLMProvider,
    kb: KnowledgeBase,
    claim: Claim,
    *,
    threshold: float,
    stale_days: int,
    today: date,
    language: str,
) -> Flag | None:
    chunks = await kb.search(f"{claim.subject} {claim.statement}", k=8)
    if not chunks:
        return None
    verdict = await complete(
        strong,
        FACTCHECK_SYSTEM.format(language=language),
        f"SUBJECT: {claim.subject}\nSTATEMENT: {claim.statement}\n\n"
        f"KB EXCERPTS:\n{format_chunks(chunks)}",
        Verdict,
    )
    if verdict.verdict not in FLAGGED_VERDICTS or verdict.confidence < threshold:
        return None
    path = verdict.path.split("#", 1)[0].strip()
    line = find_quote_line(verdict.kb_quote, kb.read(path)) if kb.exists(path) else None
    if line is None:
        return None
    same_page = [chunk for chunk in chunks if chunk.path == path]
    source = next((c for c in same_page if find_quote_line(line, c.text)), None)
    source = source or (same_page[0] if same_page else None)
    stale_since = None
    if source and source.verified_date:
        verified = date.fromisoformat(source.verified_date)
        if verified < today - timedelta(days=stale_days):
            stale_since = source.verified_date
    return Flag(
        subject=claim.subject,
        statement=claim.statement,
        verdict=verdict.verdict,
        quote=line,
        anchor=source.anchor if source else path,
        reason=verdict.reason,
        stale_since=stale_since,
    )
