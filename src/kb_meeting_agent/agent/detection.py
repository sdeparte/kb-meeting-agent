from __future__ import annotations

import re
from typing import Literal

from kb_meeting_agent.llm.base import LLMProvider, Schema, complete


def is_addressed(text: str, names: list[str]) -> bool:
    folded = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(name.casefold())}(?!\w)", folded) for name in names)


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

ADDRESSED_SYSTEM = """You are a meeting assistant called {names}. A participant just addressed you.
Classify the request:
- question: asks for information that may be in the knowledge base; put a self-contained version of the question in `question`.
- set_level: asks you to change how often you intervene; put silent, contradictions or context in `level`.
- validate: approves the decision you proposed last.
- ignore: rejects the decision you proposed last.
- other: anything else.
Use an empty `question` and level "none" when they do not apply."""

SUMMARY_SYSTEM = """Update the running summary of a meeting with the new transcript excerpt.
Keep it factual and under 200 words, in language "{language}". Return the full updated summary."""


async def classify_addressed(
    llm: LLMProvider, *, names: list[str], context: str, utterance: str
) -> AddressedIntent:
    user = f"RECENT TRANSCRIPT:\n{context}\n\nUTTERANCE ADDRESSED TO YOU:\n{utterance}"
    return await complete(
        llm, ADDRESSED_SYSTEM.format(names=", ".join(names)), user, AddressedIntent
    )


async def extract_items(
    llm: LLMProvider, *, summary: str, context: str, new: str, language: str
) -> Extraction:
    user = f"MEETING SUMMARY SO FAR:\n{summary or '(none)'}\n\nCONTEXT:\n{context}\n\nNEW:\n{new}"
    return await complete(llm, EXTRACTION_SYSTEM.format(language=language), user, Extraction)


async def update_summary(llm: LLMProvider, *, summary: str, new: str, language: str) -> str:
    user = f"CURRENT SUMMARY:\n{summary or '(none)'}\n\nNEW EXCERPT:\n{new}"
    result = await complete(llm, SUMMARY_SYSTEM.format(language=language), user, Summary)
    return result.summary
