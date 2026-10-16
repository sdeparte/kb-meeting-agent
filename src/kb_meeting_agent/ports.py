from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from kb_meeting_agent.conventions import KbConventions
from kb_meeting_agent.models import Chunk


@dataclass(frozen=True)
class Button:
    id: str
    label: str


@dataclass(frozen=True)
class OutMessage:
    text: str
    buttons: tuple[Button, ...] = ()


@dataclass(frozen=True)
class PrRef:
    number: int
    url: str
    branch: str


class PublishError(Exception):
    """Raised when a pull request cannot be opened.

    The message is for the log and may hold URLs or response bodies; `public` is the short
    summary that can be shown to meeting participants.
    """

    def __init__(self, message: str, public: str = "publication error") -> None:
        super().__init__(message)
        self.public = public


class OutputSink(Protocol):
    async def send(self, message: OutMessage) -> str: ...


class Publisher(Protocol):
    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef: ...

    async def open_pr_paths(self, prefix: str) -> list[str]: ...


class KnowledgeBase(Protocol):
    @property
    def conventions(self) -> KbConventions: ...

    async def search(self, query: str, k: int = 8) -> list[Chunk]: ...

    def read(self, path: str) -> str: ...

    def exists(self, path: str) -> bool: ...

    def list_files(self, directory: str) -> list[str]: ...

    def glossary(self) -> str: ...

    def instructions(self) -> str: ...

    def template(self, kind: Literal["decision", "minutes"]) -> str: ...
