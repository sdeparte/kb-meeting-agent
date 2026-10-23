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
    """A searchable piece of a KB page, or a window of lines of a code file."""

    path: str
    headings: tuple[str, ...]
    text: str
    status: str | None
    verified_date: str | None
    repo: str = ""
    tags: tuple[str, ...] = ()
    start_line: int | None = None  # code chunks only
    end_line: int | None = None

    @property
    def anchor(self) -> str:
        if self.start_line is not None:
            return f"{self.repo}:{self.path}:{self.start_line}-{self.end_line}"
        return f"{self.path}#{self.headings[-1]}" if self.headings else self.path

    @property
    def citation(self) -> str:
        """How participants see the source: code is labelled with its tag."""
        if self.start_line is None:
            return self.anchor
        label = next((tag for tag in self.tags if tag != "CodeBase"), "CodeBase")
        return f"[{label}] {self.anchor}"
