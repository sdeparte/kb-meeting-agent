from __future__ import annotations

import re
import unicodedata
from typing import Literal

from kb_meeting_agent.config import InterventionLevel
from kb_meeting_agent.llm.base import LLMProvider, Schema, complete


def _fold(text: str) -> str:
    """Lowercase without accents, so that "Brèche" and "breche" match."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def is_addressed(text: str, names: list[str]) -> bool:
    folded = _fold(text)
    return any(re.search(rf"(?<!\w){re.escape(_fold(name))}(?!\w)", folded) for name in names)


class Claim(Schema):
    subject: str
    statement: str


class DecisionCandidate(Schema):
    statement: str
    quote: str


class Extraction(Schema):
    claims: list[Claim]
    decisions: list[DecisionCandidate]
    topics: list[str]


class AddressedIntent(Schema):
    kind: Literal["question", "set_level", "validate", "ignore", "other"]
    question: str
    level: Literal["silent", "contradictions", "context", "none"]


class Summary(Schema):
    summary: str


EXTRACTION_SYSTEM = """You monitor a live meeting transcript for a team that keeps a knowledge base (KB).
Read the CONTEXT to understand the conversation, but extract items from the NEW part only:
- claims: factual, checkable statements about the product or project (values, behaviours, rules, statuses). Not opinions, questions or proposals. `subject` is a short noun phrase naming what the claim is about.
- decisions: choices the participants explicitly agree on. Not ideas still under discussion. `statement` is a self-contained sentence; `quote` is the verbatim transcript line it comes from.
- topics: at most 3 short names of subjects discussed in the NEW part.
Return empty lists when nothing qualifies. Write `subject`, `statement` and `topics` in language "{language}"."""

# The recent transcript misled small models into classifying what was said before the
# utterance ("set_level" for a question asked after the level was discussed): the prompt says
# what to classify, defines the levels and gives examples; the previous and default levels
# resolve "as before" and "back to the default".
ADDRESSED_SYSTEM = """You are {name}, the AI assistant of this meeting{aliases}. A participant just addressed you.
Classify only the UTTERANCE ADDRESSED TO YOU. The recent transcript is there to understand what it refers to ("as before", "that page"); never classify something said earlier.
- question: asks for information that may be in the knowledge base; put a self-contained version of the question, in language "{language}", in `question`.
- set_level: the utterance itself asks you to speak up more or less often. Levels: silent (speak only when addressed), contradictions (also point out statements that contradict the knowledge base), context (also link related knowledge-base pages). Put the level asked for in `level`. A question about the subject of the meeting, even one about production, statuses, levels or contradictions, is a question, not set_level.
- validate: approves the decision you proposed last.
- ignore: rejects the decision you proposed last.
- other: anything else.
Use an empty `question` and level "none" when they do not apply.

Examples:
- "{name}, what is the default cooldown?" -> question
- "{name}, which items are in production?" -> question
- "{name}, be quiet for a while" / "stop interrupting us" -> set_level silent
- "{name}, only point out contradictions" -> set_level contradictions
- "{name}, also give us the related pages" / "speak up more often" -> set_level context
- "back to the default" -> set_level {default_level}; "as before" -> set_level {previous_level}
- "Hey {name}! {name}!" / "{name} is here" / "let {name} answer" -> other"""

SUMMARY_SYSTEM = """Update the running summary of a meeting with the new transcript excerpt.
Keep it factual and under 200 words, in language "{language}". Return the full updated summary."""


async def classify_addressed(
    llm: LLMProvider,
    *,
    names: list[str],
    context: str,
    utterance: str,
    level: InterventionLevel,
    previous_level: InterventionLevel,
    default_level: InterventionLevel,
    language: str,
) -> AddressedIntent:
    user = (
        f"YOUR LEVEL: {level} (previous: {previous_level}, default: {default_level})\n\n"
        f"RECENT TRANSCRIPT:\n{context}\n\nUTTERANCE ADDRESSED TO YOU:\n{utterance}"
    )
    aliases = f"; participants may also call you {', '.join(names[1:])}" if names[1:] else ""
    system = ADDRESSED_SYSTEM.format(
        name=names[0],
        aliases=aliases,
        language=language,
        previous_level=previous_level,
        default_level=default_level,
    )
    return await complete(llm, system, user, AddressedIntent)


async def extract_items(
    llm: LLMProvider, *, summary: str, context: str, new: str, language: str
) -> Extraction:
    user = f"MEETING SUMMARY SO FAR:\n{summary or '(none)'}\n\nCONTEXT:\n{context}\n\nNEW:\n{new}"
    return await complete(llm, EXTRACTION_SYSTEM.format(language=language), user, Extraction)


async def update_summary(llm: LLMProvider, *, summary: str, new: str, language: str) -> str:
    user = f"CURRENT SUMMARY:\n{summary or '(none)'}\n\nNEW EXCERPT:\n{new}"
    result = await complete(llm, SUMMARY_SYSTEM.format(language=language), user, Summary)
    return result.summary
