from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import subprocess
from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from kb_meeting_agent.config import RepoConfig
from kb_meeting_agent.kb.git import GitCheckout
from kb_meeting_agent.kb.index import Embedder, SearchIndex
from kb_meeting_agent.models import Chunk

log = logging.getLogger(__name__)

MAX_CODE_FILE_BYTES = 200_000
_BINARY_PROBE_BYTES = 8192

# Matched against the whole path and the file name, ignoring case (`*` also matches `/`).
DEFAULT_CODE_EXCLUDE = (
    # lockfiles
    "*.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    # dependencies, builds, generated code
    "vendor/*",
    "*/vendor/*",
    "node_modules/*",
    "*/node_modules/*",
    "build/*",
    "*/build/*",
    "dist/*",
    "*/dist/*",
    ".dart_tool/*",
    "*/.dart_tool/*",
    "*.g.dart",
    "*.freezed.dart",
    "*.min.js",
    "*.map",
    # secrets: an excerpt can be quoted in the meeting channel
    ".env*",
    "*.env",
    "*.pem",
    "*.key",
    "*secret*",
    "*credential*",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    "key.properties",
    "*.keystore",
    "*.jks",
    "*.p12",
    "*.pfx",
    ".npmrc",
    ".netrc",
    ".pypirc",
    "*.tfvars",
    "*.tfstate*",
    "google-services.json",
    "googleservice-info.plist",
)

# A file holding one of these is not indexed whatever its name: private keys, GitHub, AWS,
# OpenAI-style and Slack tokens.
SECRET_CONTENT = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\bxox[abposr]-[A-Za-z0-9-]{10,}"
)


def _matches(path: str, pattern: str) -> bool:
    path, pattern = path.lower(), pattern.lower()  # `.ENV` is as secret as `.env`
    return fnmatchcase(path, pattern) or fnmatchcase(PurePosixPath(path).name, pattern)


def _tracked(root: Path) -> dict[str, str]:
    """Tracked files and their blob ids: a changed file is found without reading any file."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-s", "-z"], check=True, capture_output=True
    ).stdout.decode()
    tracked = {}
    for entry in filter(None, listed.split("\0")):
        meta, _, path = entry.partition("\t")  # "<mode> <blob> <stage>\t<path>"
        tracked[path] = meta.split()[1]
    return tracked


def select_code_files(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    """Tracked text files worth indexing, as POSIX paths relative to root."""
    selected = []
    for path in _tracked(root):
        if include and not any(_matches(path, pattern) for pattern in include):
            continue
        if any(_matches(path, pattern) for pattern in (*DEFAULT_CODE_EXCLUDE, *exclude)):
            continue
        file = root / path
        # A tracked link can point anywhere on this machine, e.g. at an SSH key.
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_CODE_FILE_BYTES:
            continue
        with file.open("rb") as handle:
            if b"\0" in handle.read(_BINARY_PROBE_BYTES):
                continue
        selected.append(path)
    return sorted(selected)


def chunk_code(
    repo: str,
    tags: tuple[str, ...],
    path: str,
    text: str,
    window: int = 60,
    overlap: int = 10,
    snap: int = 15,
) -> list[Chunk]:
    """Windows of about `window` lines, ending on a blank line when one is near the end."""
    lines = text.splitlines()
    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        end = min(start + window, len(lines))
        if end < len(lines):
            for i in range(end - 1, max(start, end - snap) - 1, -1):
                if not lines[i].strip():
                    end = i + 1
                    break
        body = "\n".join(lines[start:end])
        if body.strip():
            chunks.append(
                Chunk(
                    path,
                    (),
                    body,
                    None,
                    None,
                    repo=repo,
                    tags=tags,
                    start_line=start + 1,
                    end_line=end,
                )
            )
        if end >= len(lines):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


class GitCodeRepository(GitCheckout):
    """A read-only code repository, indexed in windows of lines."""

    def __init__(
        self, name: str, config: RepoConfig, root: Path, embed: Embedder, embedding_model: str
    ) -> None:
        super().__init__(config, root / "repo")
        self.name = name
        self.tags = tuple(config.tags)
        self._index = SearchIndex(root / "index.sqlite", embed)
        self._embedding_model = embedding_model

    @property
    def indexed(self) -> bool:
        return bool(self._index.file_hashes())

    @property
    def file_count(self) -> int:
        return len(self._index.file_hashes())

    def close(self) -> None:
        self._index.close()

    async def sync(self) -> None:
        await asyncio.to_thread(self._git_sync)
        await self._reindex()

    async def search(self, query: str, k: int = 8) -> list[Chunk]:
        return [
            replace(chunk, repo=self.name, tags=self.tags)
            for chunk in await self._index.search(query, k=k)
        ]

    def exists(self, path: str) -> bool:
        """Only an indexed file can be cited: secrets and generated files never are."""
        return path in self._index.file_hashes()

    def _changes(self, known: dict[str, str]) -> tuple[set[str], list[tuple[str, str, str]]]:
        """The files to index, and the (path, blob id, text) of those that changed. Run in a
        thread: a repository of thousands of files must not stall the meeting."""
        blobs = _tracked(self.repo_dir)
        current = select_code_files(self.repo_dir, self._config.include, self._config.exclude)
        changed = [
            (path, blobs[path], _read_source(self.repo_dir / path))
            for path in current
            if known.get(path) != blobs[path]
        ]
        return set(current), changed

    async def _reindex(self) -> None:
        # Every selection rule is in the key: a stricter rule must drop files already indexed.
        rules = repr(
            (
                DEFAULT_CODE_EXCLUDE,
                SECRET_CONTENT.pattern,
                MAX_CODE_FILE_BYTES,
                self._config.include,
                self._config.exclude,
            )
        )
        key = hashlib.sha256((rules + self._embedding_model).encode()).hexdigest()
        if self._index.get_meta("index_key") != key:
            self._index.clear()
            self._index.set_meta("index_key", key)
        known = self._index.file_hashes()
        current, changed = await asyncio.to_thread(self._changes, known)
        for path in known.keys() - current:
            self._index.remove_file(path)
        for path, blob, text in changed:
            if SECRET_CONTENT.search(text):
                log.warning("%s: %s looks like it holds a secret: not indexed", self.name, path)
                self._index.remove_file(path)
                continue
            await self._index.upsert_file(path, blob, chunk_code(self.name, self.tags, path, text))
