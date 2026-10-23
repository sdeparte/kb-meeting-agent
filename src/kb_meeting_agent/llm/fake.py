from __future__ import annotations

import json
import math
import re
import zlib
from typing import Any

from kb_meeting_agent.llm.base import LLMError

_DIMENSIONS = 64


def fake_embedding(text: str) -> list[float]:
    """Deterministic bag-of-words vector, good enough for tests and dry runs."""
    vector = [0.0] * _DIMENSIONS
    for token in re.findall(r"\w+", text.casefold()):
        vector[zlib.crc32(token.encode()) % _DIMENSIONS] += 1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


FAKE_DEFAULTS: dict[str, object] = {
    "Extraction": {"claims": [], "decisions": [], "topics": []},
    "AddressedIntent": {"kind": "other", "question": "", "level": "none"},
    "Summary": {"summary": ""},
    "Queries": {"queries": [], "tags": []},
    "Answer": {"covered": False, "answer": "", "sources": []},
    "Verdict": {
        "verdict": "not_covered",
        "kb_quote": "",
        "path": "",
        "reason": "",
        "confidence": 0.0,
    },
    "DecisionDraft": {
        "title": "Decision",
        "slug": "decision",
        "scope": "",
        "context": "",
        "decision": "",
        "consequences": "",
        "related_pages": [],
    },
    "SliceSummary": {"summary": ""},
    "MinutesContent": {
        "title": "Replay",
        "slug": "replay",
        "agenda": [],
        "topics": [{"title": "Discussion", "points": ["(fake provider)"]}],
        "action_items": [],
        "open_questions": [],
    },
}


class FakeProvider:
    def __init__(
        self,
        responses: dict[str, list[Any]] | None = None,
        defaults: dict[str, object] | None = None,
    ) -> None:
        self.responses = {key: list(value) for key, value in (responses or {}).items()}
        self.defaults = dict(defaults or {})
        self.calls: list[tuple[str, str, str]] = []

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        title = schema.get("title", "")
        self.calls.append((title, system, user))
        queue = self.responses.get(title)
        if queue:
            item = queue.pop(0)
        elif title in self.defaults:
            item = self.defaults[title]
        else:
            raise LLMError(f"FakeProvider has no response for {title}")
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [fake_embedding(text) for text in texts]

    def calls_for(self, title: str) -> list[tuple[str, str, str]]:
        return [call for call in self.calls if call[0] == title]
