import pytest

from kb_meeting_agent.config import RepoConfig
from kb_meeting_agent.publish.factory import build_publisher
from kb_meeting_agent.publish.github import GitHubPublisher


async def test_a_github_repository_gets_a_github_publisher():
    config = RepoConfig(repo="acme/kb", token="t", tags=["KnowledgeBase"])
    publisher = build_publisher(config)
    assert isinstance(publisher, GitHubPublisher)
    await publisher.aclose()


def test_publishing_needs_a_token():
    with pytest.raises(ValueError, match="token"):
        build_publisher(RepoConfig(repo="acme/kb", tags=["KnowledgeBase"]))
