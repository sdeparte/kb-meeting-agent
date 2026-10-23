from __future__ import annotations

import subprocess
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from kb_meeting_agent.models import Chunk

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
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*secret*",
    "*credential*",
)


def _matches(path: str, pattern: str) -> bool:
    path, pattern = path.lower(), pattern.lower()  # `.ENV` is as secret as `.env`
    return fnmatchcase(path, pattern) or fnmatchcase(PurePosixPath(path).name, pattern)


def select_code_files(root: Path, include: list[str], exclude: list[str]) -> list[str]:
    """Tracked text files worth indexing, as POSIX paths relative to root."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], check=True, capture_output=True
    ).stdout.decode()
    selected = []
    for path in filter(None, listed.split("\0")):
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
