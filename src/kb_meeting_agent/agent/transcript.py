from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from kb_meeting_agent.models import Segment


def load_segments(path: Path) -> list[Segment]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Segment(**json.loads(line)) for line in lines if line.strip()]


class Transcript:
    """Meeting transcript, appended to a JSONL file as it grows so a crash loses nothing."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._segments = load_segments(path) if path.exists() else []

    def append(self, segment: Segment) -> None:
        self._segments.append(segment)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(segment), ensure_ascii=False) + "\n")

    def all(self) -> list[Segment]:
        return list(self._segments)

    def window(self, seconds: float) -> list[Segment]:
        if not self._segments:
            return []
        last = self._segments[-1].end
        return [s for s in self._segments if s.end >= last - seconds]
