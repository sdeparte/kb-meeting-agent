from __future__ import annotations

from pathlib import Path

from kb_meeting_agent.ports import BranchChangedError, PrRef, PublishError


class DryRunPublisher:
    """Writes what would be published under out_dir/<branch>/, plus a PR.md description."""

    def __init__(self, out_dir: Path, local_urls: bool = True) -> None:
        """local_urls=False labels PRs "dry run: <branch>" instead of a file:// URL, for
        messages that participants see (local paths must not reach the meeting channel)."""
        self._out_dir = out_dir
        self._local_urls = local_urls
        self._count = 0

    def _write(self, branch: str, files: dict[str, str]) -> Path:
        base = self._out_dir.resolve()
        root = (base / branch).resolve()
        targets = {(root / path).resolve(): content for path, content in files.items()}
        if not root.is_relative_to(base) or not all(t.is_relative_to(root) for t in targets):
            raise PublishError(
                f"refusing to write outside {base}: {branch}", public="unsafe file path"
            )
        for target, content in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        root.mkdir(parents=True, exist_ok=True)
        return root

    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef:
        root = self._write(branch, files)
        self._count += 1
        (root / "PR.md").write_text(f"# {title}\n\n{body}", encoding="utf-8")
        url = root.as_uri() if self._local_urls else f"dry run: {branch}"
        return PrRef(number=self._count, url=url, branch=branch)

    async def is_open(self, pr: PrRef) -> bool:
        return True

    async def update_branch(
        self, branch: str, files: dict[str, str], message: str, expected_head: str
    ) -> str:
        self._write(branch, files)
        return expected_head

    async def open_pr_paths(self, prefix: str) -> list[str]:
        return []


class FakePublisher:
    def __init__(self, open_paths: list[str] | None = None, closed: set[int] | None = None) -> None:
        self.prs: list[tuple[str, dict[str, str], str, str]] = []
        self.updates: list[tuple[str, dict[str, str], str]] = []
        self.update_heads: list[str] = []
        self.moved: set[str] = set()  # branches someone else pushed to
        self._open_paths = list(open_paths or [])
        self._closed = set(closed or ())

    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef:
        self.prs.append((branch, files, title, body))
        number = len(self.prs)
        return PrRef(
            number=number,
            url=f"https://example.test/pull/{number}",
            branch=branch,
            head=f"sha{number}",
        )

    async def open_pr_paths(self, prefix: str) -> list[str]:
        return [path for path in self._open_paths if path.startswith(prefix)]

    async def is_open(self, pr: PrRef) -> bool:
        return pr.number not in self._closed

    async def update_branch(
        self, branch: str, files: dict[str, str], message: str, expected_head: str
    ) -> str:
        if branch in self.moved:
            raise BranchChangedError(f"{branch} moved")
        self.updates.append((branch, files, message))
        self.update_heads.append(expected_head)
        return f"{expected_head}+"
