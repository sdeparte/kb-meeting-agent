from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import subprocess
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

from kb_meeting_agent.config import KbConfig
from kb_meeting_agent.conventions import KbConventions, load_conventions, load_template
from kb_meeting_agent.kb.chunker import chunk_markdown
from kb_meeting_agent.kb.index import Embedder, SearchIndex
from kb_meeting_agent.models import Chunk

INSTRUCTIONS_MAX_CHARS = 12000
GLOSSARY_MAX_CHARS = 4000


class KbSyncError(Exception):
    """Raised when the KB repository cannot be cloned or updated."""


class GitMarkdownKnowledgeBase:
    def __init__(
        self,
        name: str,
        config: KbConfig,
        data_dir: Path,
        embed: Embedder,
        embedding_model: str,
    ) -> None:
        self.name = name
        self._config = config
        self.repo_dir = data_dir / "kb" / name / "repo"
        self._index = SearchIndex(data_dir / "kb" / name / "index.sqlite", embed)
        self._embedding_model = embedding_model
        self._conventions = KbConventions()

    @property
    def conventions(self) -> KbConventions:
        return self._conventions

    def close(self) -> None:
        self._index.close()

    async def sync(self) -> None:
        await asyncio.to_thread(self._git_sync)
        self._conventions = load_conventions(self.repo_dir)
        await self._reindex()

    async def search(self, query: str, k: int = 8) -> list[Chunk]:
        return await self._index.search(query, k=k, boost_paths=self._conventions.authoritative)

    def read(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def exists(self, path: str) -> bool:
        try:
            return self._resolve(path).is_file()
        except ValueError:
            return False

    def list_files(self, directory: str) -> list[str]:
        folder = self._resolve(directory)
        return [p.name for p in folder.iterdir() if p.is_file()] if folder.is_dir() else []

    def glossary(self) -> str:
        path = self._conventions.glossary
        return self.read(path)[:GLOSSARY_MAX_CHARS] if path and self.exists(path) else ""

    def instructions(self) -> str:
        parts = [
            f"--- {path} ---\n{self.read(path)}"
            for path in self._conventions.instructions
            if self.exists(path)
        ]
        return "\n\n".join(parts)[:INSTRUCTIONS_MAX_CHARS]

    def template(self, kind: Literal["decision", "minutes"]) -> str:
        section = self._conventions.decisions if kind == "decision" else self._conventions.minutes
        return load_template(self.repo_dir, section.template, f"{kind}.md")

    def _resolve(self, relative: str) -> Path:
        root = self.repo_dir.resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"path outside the KB: {relative}")
        return path

    def _clone_url(self) -> str:
        return self._config.clone_url or f"https://github.com/{self._config.repo}.git"

    def _basic_credential(self) -> str | None:
        if not self._config.token:
            return None
        return base64.b64encode(f"x-access-token:{self._config.token}".encode()).decode()

    def _git_env(self) -> dict[str, str]:
        """Auth through the environment: never written to .git/config, never in argv, and
        scoped to github.com so a custom clone_url host never receives the token."""
        env = dict(os.environ)
        credential = self._basic_credential()
        if credential:
            env |= {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credential}",
            }
        return env

    def _redact(self, message: str) -> str:
        for secret in (self._config.token, self._basic_credential()):
            if secret:
                message = message.replace(secret, "***")
        return message

    def _git(self, *args: str) -> None:
        try:
            subprocess.run(
                ["git", *args], check=True, capture_output=True, text=True, env=self._git_env()
            )
        except subprocess.CalledProcessError as exc:
            raise KbSyncError(self._redact(exc.stderr or str(exc))) from None

    def _git_sync(self) -> None:
        branch = self._config.base_branch
        if not (self.repo_dir / ".git").exists():
            self.repo_dir.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--quiet", "--branch", branch, self._clone_url(), str(self.repo_dir))
            return
        repo = str(self.repo_dir)
        self._git("-C", repo, "remote", "set-url", "origin", self._clone_url())
        self._git("-C", repo, "fetch", "--quiet", "origin", branch)
        self._git("-C", repo, "reset", "--quiet", "--hard", f"origin/{branch}")

    def _markdown_files(self) -> dict[str, Path]:
        patterns = [".git/**", *self._conventions.exclude]
        files: dict[str, Path] = {}
        for path in sorted(self.repo_dir.rglob("*.md")):
            relative = path.relative_to(self.repo_dir).as_posix()
            if not any(fnmatch(relative, pattern) for pattern in patterns):
                files[relative] = path
        return files

    async def _reindex(self) -> None:
        index_key = hashlib.sha256(
            (self._conventions.model_dump_json() + self._embedding_model).encode()
        ).hexdigest()
        if self._index.get_meta("index_key") != index_key:
            self._index.clear()
            self._index.set_meta("index_key", index_key)
        known = self._index.file_hashes()
        current = self._markdown_files()
        for relative in known.keys() - current.keys():
            self._index.remove_file(relative)
        for relative, path in current.items():
            content = path.read_text(encoding="utf-8")
            digest = hashlib.sha256(content.encode()).hexdigest()
            if known.get(relative) != digest:
                chunks = chunk_markdown(relative, content, self._conventions)
                await self._index.upsert_file(relative, digest, chunks)
