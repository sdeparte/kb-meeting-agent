from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from kb_meeting_agent.conventions import KbConventions
from kb_meeting_agent.models import Chunk


@dataclass(frozen=True)
class Modal:
    title: str
    label: str
    value: str


@dataclass(frozen=True)
class Button:
    id: str
    label: str
    modal: Modal | None = None


@dataclass(frozen=True)
class OutMessage:
    text: str
    buttons: tuple[Button, ...] = ()
    reply_to: str | None = None  # the id a sink returned for an earlier message


@dataclass(frozen=True)
class PrRef:
    number: int
    url: str
    branch: str
    head: str = ""  # commit the agent put on the branch; empty when unknown


class PublishError(Exception):
    """Raised when a pull request cannot be opened.

    The message is for the log and may hold URLs or response bodies; `public` is the short
    summary that can be shown to meeting participants.
    """

    def __init__(self, message: str, public: str = "publication error") -> None:
        super().__init__(message)
        self.public = public


class BranchChangedError(PublishError):
    """The branch no longer points at the agent's commit: someone else pushed to it."""

    def __init__(self, message: str) -> None:
        super().__init__(message, public="the branch was changed by someone else")


class OutputSink(Protocol):
    async def send(self, message: OutMessage) -> str: ...


class Publisher(Protocol):
    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef: ...

    async def open_pr_paths(self, prefix: str) -> list[str]: ...

    async def is_open(self, pr: PrRef) -> bool: ...

    async def update_branch(
        self, branch: str, files: dict[str, str], message: str, expected_head: str
    ) -> str:
        """Replace the branch with one commit on the current base; return the new head.

        Leaves the branch alone when expected_head is already one commit on the current
        base. Raises BranchChangedError when the branch head is not expected_head.
        """
        ...


class KnowledgeBase(Protocol):
    @property
    def conventions(self) -> KbConventions: ...

    async def search(
        self,
        query: str,
        k: int = 8,
        prefer_tags: tuple[str, ...] = (),
        only_tags: tuple[str, ...] = (),
    ) -> list[Chunk]:
        """Chunks of every repository; `prefer_tags` ranks some repositories higher,
        `only_tags` keeps the repositories carrying one of these tags."""
        ...

    @property
    def free_tags(self) -> list[str]:
        """Tags of the project's repositories other than KnowledgeBase and CodeBase."""
        ...

    def link(self, chunk: Chunk) -> str | None:
        """A web link to a code chunk's lines; None for knowledge base chunks."""
        ...

    def code_exists(self, repo: str, path: str) -> bool: ...

    def section(self, chunk: Chunk) -> list[Chunk]:
        """Every chunk of the chunk's section, in page order, the chunk itself included."""
        ...

    def read(self, path: str) -> str: ...

    def exists(self, path: str) -> bool: ...

    def list_files(self, directory: str) -> list[str]: ...

    def glossary(self, max_chars: int | None = ...) -> str:
        """The glossary page, cut at `max_chars` (None: whole)."""
        ...

    def instructions(self) -> str: ...

    def template(self, kind: Literal["decision", "minutes"]) -> str: ...


class SyncableKnowledgeBase(KnowledgeBase, Protocol):
    async def sync(self) -> None: ...
