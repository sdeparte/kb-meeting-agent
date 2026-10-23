from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from pathlib import Path
from typing import Literal

from kb_meeting_agent.config import CODE_BASE, KNOWLEDGE_BASE, ProjectConfig
from kb_meeting_agent.conventions import KbConventions
from kb_meeting_agent.kb.code import GitCodeRepository
from kb_meeting_agent.kb.index import Embedder
from kb_meeting_agent.kb.repo import GLOSSARY_MAX_CHARS, GitMarkdownKnowledgeBase
from kb_meeting_agent.llm.base import LLMError
from kb_meeting_agent.models import Chunk

log = logging.getLogger(__name__)

PREFERRED_TAG_BOOST = 1.5


class ProjectSources:
    """A project's KnowledgeBase repo and code repos behind the agent's KnowledgeBase port."""

    def __init__(
        self,
        kb: GitMarkdownKnowledgeBase,
        kb_name: str,
        kb_tags: tuple[str, ...],
        code: list[GitCodeRepository],
        links: dict[str, str],
    ) -> None:
        self._kb = kb
        self._kb_name = kb_name
        self._kb_tags = kb_tags
        self.code_repos = code
        self._links = links  # repo name -> https://github.com/<repo>/blob/<branch>

    @property
    def conventions(self) -> KbConventions:
        return self._kb.conventions

    @property
    def knowledge_base(self) -> GitMarkdownKnowledgeBase:
        return self._kb

    @property
    def has_code(self) -> bool:
        return bool(self.code_repos)

    @property
    def free_tags(self) -> list[str]:
        tags = {tag for repo in self.code_repos for tag in repo.tags} | set(self._kb_tags)
        return sorted(tags - {KNOWLEDGE_BASE, CODE_BASE})

    async def sync(self) -> None:
        """The knowledge base only: code repositories are synced by their owner."""
        await self._kb.sync()

    def close(self) -> None:
        self._kb.close()
        for repo in self.code_repos:
            repo.close()

    async def search(
        self,
        query: str,
        k: int = 8,
        prefer_tags: tuple[str, ...] = (),
        only_tags: tuple[str, ...] = (),
    ) -> list[Chunk]:
        searches: list[tuple[str, tuple[str, ...], Callable[..., Awaitable[list[Chunk]]]]] = [
            (self._kb_name, self._kb_tags, self._kb_search),
            *((repo.name, repo.tags, repo.search) for repo in self.code_repos),
        ]
        # Each repository's own ranking, interleaved by rank: the scores of two indexes are not
        # comparable, their ranks are. The knowledge base and a preferred repository move up 1.5
        # times faster through the ranks (their 3rd result comes with the others' 2nd), the
        # knowledge base first on a tie: code adds to it without crowding it out, which a boost
        # on scores would do (a code file's 10th result beat the knowledge base's 1st).
        scored: list[tuple[float, int, Chunk]] = []
        for name, tags, search in searches:
            if only_tags and not set(only_tags) & set(tags):
                continue
            try:
                results = await search(query, k=k)
            except LLMError:
                raise  # one embedder for every repository: the meeting pauses its checks
            except Exception:
                if name == self._kb_name:
                    raise  # a KB that cannot be searched must not read as "the KB doesn't say"
                log.exception("searching the %s repository failed", name)
                continue
            preferred = name == self._kb_name or set(prefer_tags) & set(tags)
            boost = PREFERRED_TAG_BOOST if preferred else 1.0
            for rank, chunk in enumerate(results):
                scored.append((rank / boost - (boost - 1), len(scored), chunk))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [chunk for _, _, chunk in scored[:k]]

    async def _kb_search(self, query: str, k: int) -> list[Chunk]:
        return [self._label(chunk) for chunk in await self._kb.search(query, k=k)]

    def _label(self, chunk: Chunk) -> Chunk:
        return replace(chunk, repo=self._kb_name, tags=self._kb_tags)

    def section(self, chunk: Chunk) -> list[Chunk]:
        if chunk.start_line is not None:
            return [chunk]
        return [self._label(piece) for piece in self._kb.section(chunk)]

    def link(self, chunk: Chunk) -> str | None:
        base = self._links.get(chunk.repo)
        if chunk.start_line is None or base is None:
            return None
        return f"{base}/{chunk.path}#L{chunk.start_line}-L{chunk.end_line}"

    def link_file(self, repo: str, path: str) -> str | None:
        base = self._links.get(repo)
        return f"{base}/{path}" if base else None

    def code_exists(self, repo: str, path: str) -> bool:
        return any(r.name == repo and r.exists(path) for r in self.code_repos)

    def read(self, path: str) -> str:
        return self._kb.read(path)

    def exists(self, path: str) -> bool:
        return self._kb.exists(path)

    def list_files(self, directory: str) -> list[str]:
        return self._kb.list_files(directory)

    def glossary(self, max_chars: int | None = GLOSSARY_MAX_CHARS) -> str:
        return self._kb.glossary(max_chars)

    def instructions(self) -> str:
        return self._kb.instructions()

    def template(self, kind: Literal["decision", "minutes"]) -> str:
        return self._kb.template(kind)


def build_sources(
    name: str, project: ProjectConfig, data_dir: Path, embed: Embedder, embedding_model: str
) -> ProjectSources:
    """A project's repositories, cloned and indexed under <data_dir>/projects/<name>/<repo>."""
    root = data_dir / "projects" / name
    kb_name, kb_config = project.knowledge_base
    kb = GitMarkdownKnowledgeBase(
        kb_name, kb_config, data_dir, embed, embedding_model, root=root / kb_name
    )
    code = [
        GitCodeRepository(repo_name, repo, root / repo_name, embed, embedding_model)
        for repo_name, repo in project.code_repos
    ]
    links = {
        repo_name: f"https://github.com/{repo.repo}/blob/{repo.base_branch}"
        for repo_name, repo in project.code_repos
    }
    return ProjectSources(kb, kb_name, tuple(kb_config.tags), code, links)
