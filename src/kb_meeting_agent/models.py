from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """One transcribed utterance. Times are seconds since the meeting started."""

    speaker_id: str
    speaker_name: str
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Chunk:
    """A searchable piece of a KB page."""

    path: str
    headings: tuple[str, ...]
    text: str
    status: str | None
    verified_date: str | None

    @property
    def anchor(self) -> str:
        return f"{self.path}#{self.headings[-1]}" if self.headings else self.path
