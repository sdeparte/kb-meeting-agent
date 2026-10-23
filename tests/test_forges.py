from kb_meeting_agent.config import RepoConfig
from kb_meeting_agent.forges import GITHUB, forge_for


def test_github_urls():
    assert GITHUB.clone_url("acme/kb") == "https://github.com/acme/kb.git"
    assert GITHUB.file_url("acme/back", "main", "src/x.php") == (
        "https://github.com/acme/back/blob/main/src/x.php"
    )
    assert GITHUB.file_url("acme/back", "main", "src/x.php", (12, 70)) == (
        "https://github.com/acme/back/blob/main/src/x.php#L12-L70"
    )


def test_a_repository_is_on_github_by_default():
    assert forge_for(RepoConfig(repo="acme/kb", tags=["KnowledgeBase"])) is GITHUB
