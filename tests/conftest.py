import subprocess
from pathlib import Path

import pytest

from kb_meeting_agent.config import RepoConfig
from kb_meeting_agent.kb.repo import GitMarkdownKnowledgeBase
from kb_meeting_agent.llm.fake import FakeProvider

KB_FILES = {
    ".meeting-agent.yml": r"""
language: en
instructions: [CONTRIBUTING.md]
exclude: [mockups/**]
authoritative: [reference/configuration.md]
glossary: reference/glossary.md
page_header:
  verified_date: '^> \*\*Verified on\*\* (\d{4}-\d{2}-\d{2})'
statuses:
  - {pattern: '[PROD]', meaning: in_production}
  - {pattern: '[PLANNED]', meaning: planned}
  - {pattern: '[REJECTED]', meaning: rejected}
decisions:
  dir: decisions
  filename: '{number:04d}-{slug}.md'
  template: .meeting-agent/decision.md
  default_status: accepted
  index: {file: decisions/README.md, row: '| [{number:04d}]({filename}) | {title} | {status} |'}
  branch: 'decision/{date}-{slug}'
minutes:
  dir: meetings
  filename: '{date}-{slug}.md'
  index: {file: meetings/README.md, row: '| {date} | [{title}]({filename}) | {participants} |'}
  branch: 'meetings/{date}-{slug}'
""",
    ".meeting-agent/decision.md": (
        "# {number:04d} — {title}\n\n- **Status**: {status}\n- **Date**: {date}\n"
        "- **Scope**: {scope}\n\n## Context\n\n{context}\n\n## Decision\n\n{decision}\n\n"
        "## Consequences\n\n{consequences}\n\n## Sources\n\n{sources}\n"
    ),
    "CONTRIBUTING.md": "# Contributing\n\nWrite in English. One decision per file.\n",
    "reference/configuration.md": (
        "# Configuration\n\n"
        "> **Verified on** 2026-10-01 · **Sources**: server main @ abc123, many more sources.\n\n"
        "## Neutralization\n\n"
        "| Variable | Default | Role |\n|---|---|---|\n"
        "| `COOLDOWN_SECONDS` | `45` | Cooldown after a neutralization `[PROD]` |\n"
        "| `RSSI_THRESHOLD` | `-70` | Initiation threshold `[PROD]` |\n"
    ),
    "reference/glossary.md": "# Glossary\n\n| In-game | Code |\n|---|---|\n| BIO-SCAN | `biometric` |\n",
    "game/ideas.md": (
        "# Ideas\n\n## Raw BLE protocol [REJECTED]\n\n"
        "Rejected because iOS stops background advertising.\n"
    ),
    "decisions/README.md": (
        "# Decisions\n\n| # | Decision | Status |\n|---|---|---|\n"
        "| [0001](0001-rest.md) | REST | accepted |\n"
        "| [0002](0002-redis.md) | Redis | accepted |\n"
    ),
    "meetings/README.md": "# Meetings\n\n| Date | Minutes | Participants |\n|---|---|---|\n",
    "decisions/0001-rest.md": "# 0001 — REST\n\nUse REST.\n",
    "decisions/0002-redis.md": "# 0002 — Redis\n\nUse Redis.\n",
    "mockups/screen.md": "# Mockup\n\nCOOLDOWN_SECONDS 999\n",
}


def minutes_content(title: str, slug: str, **fields: object) -> dict[str, object]:
    """A MinutesContent answer for the fake provider: empty sections unless given."""
    empty = {"agenda": [], "topics": [], "action_items": [], "open_questions": []}
    return {"title": title, "slug": slug, **empty, **fields}


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def make_kb_repo(root: Path, files: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for relative, content in (files or KB_FILES).items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def commit_file(repo: Path, relative: str, content: str | None) -> None:
    path = repo / relative
    if content is None:
        path.unlink()
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"update {relative}")


@pytest.fixture
def kb_origin(tmp_path) -> Path:
    return make_kb_repo(tmp_path / "origin")


@pytest.fixture
async def kb(tmp_path, kb_origin):
    config = RepoConfig(repo="acme/kb", clone_url=str(kb_origin), tags=["KnowledgeBase"])
    knowledge_base = GitMarkdownKnowledgeBase(
        "test", config, tmp_path / "data", FakeProvider().embed, embedding_model="fake"
    )
    await knowledge_base.sync()
    yield knowledge_base
    knowledge_base.close()
