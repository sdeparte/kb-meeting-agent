from __future__ import annotations

from pathlib import Path

from kb_meeting_agent.ports import PrRef, PublishError


class DryRunPublisher:
    """Writes what would be published under out_dir/<branch>/, plus a PR.md description."""

    def __init__(self, out_dir: Path) -> None:
        self._out_dir = out_dir
        self._count = 0

    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef:
        base = self._out_dir.resolve()
        root = (base / branch).resolve()
        targets = {(root / path).resolve(): content for path, content in files.items()}
        if not root.is_relative_to(base) or not all(t.is_relative_to(root) for t in targets):
            raise PublishError(
                f"refusing to write outside {base}: {branch}", public="unsafe file path"
            )
        self._count += 1
        for target, content in targets.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        root.mkdir(parents=True, exist_ok=True)
        (root / "PR.md").write_text(f"# {title}\n\n{body}", encoding="utf-8")
        return PrRef(number=self._count, url=root.resolve().as_uri(), branch=branch)

    async def open_pr_paths(self, prefix: str) -> list[str]:
        return []


class FakePublisher:
    def __init__(self, open_paths: list[str] | None = None) -> None:
        self.prs: list[tuple[str, dict[str, str], str, str]] = []
        self._open_paths = list(open_paths or [])

    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef:
        self.prs.append((branch, files, title, body))
        number = len(self.prs)
        return PrRef(number=number, url=f"https://example.test/pull/{number}", branch=branch)

    async def open_pr_paths(self, prefix: str) -> list[str]:
        return [path for path in self._open_paths if path.startswith(prefix)]
