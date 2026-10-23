from __future__ import annotations

from typing import assert_never

from kb_meeting_agent.config import RepoConfig
from kb_meeting_agent.ports import Publisher


def build_publisher(config: RepoConfig) -> Publisher:
    """The publisher of the repository's forge; publishing needs the repository's token."""
    if not config.token:
        raise ValueError(f"publishing to {config.repo} needs a token")
    match config.provider:
        case "github":
            from kb_meeting_agent.publish.github import GitHubPublisher

            return GitHubPublisher(config.repo, config.base_branch, config.token)
        case _:
            assert_never(config.provider)
