import json

import httpx
import pytest

from kb_meeting_agent.ports import PublishError
from kb_meeting_agent.publish.github import GitHubPublisher


def make(existing_branches=(), fail_pulls=False, refs_down=False):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        path = request.url.path
        if request.method == "GET" and path == "/repos/o/r/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": "base"}})
        if path == "/repos/o/r/git/trees":
            return httpx.Response(201, json={"sha": "tree"})
        if path == "/repos/o/r/git/commits":
            return httpx.Response(201, json={"sha": "commit"})
        if path == "/repos/o/r/git/refs":
            if refs_down:
                raise httpx.ConnectError("network down")
            if body["ref"].removeprefix("refs/heads/") in existing_branches:
                return httpx.Response(422, json={"message": "Reference already exists"})
            return httpx.Response(201, json={})
        if request.method == "POST" and path == "/repos/o/r/pulls":
            if fail_pulls:
                return httpx.Response(403, json={"message": "forbidden"})
            return httpx.Response(
                201, json={"number": 7, "html_url": "https://github.com/o/r/pull/7"}
            )
        if request.method == "GET" and path == "/repos/o/r/pulls":
            return httpx.Response(200, json=[{"number": 7}])
        if path == "/repos/o/r/pulls/7/files":
            return httpx.Response(
                200,
                json=[
                    {"filename": "decisions/0003-x.md", "status": "added"},
                    {"filename": "decisions/README.md", "status": "modified"},
                    {"filename": "other/0009-y.md", "status": "added"},
                ],
            )
        return httpx.Response(404)

    publisher = GitHubPublisher("o/r", "main", "token", transport=httpx.MockTransport(handler))
    return publisher, calls


async def test_open_pr_creates_one_commit_and_a_pull_request():
    publisher, calls = make()
    pr = await publisher.open_pr("decision/x", {"a.md": "A", "b/c.md": "C"}, "Title", "Body")
    assert pr.number == 7 and pr.url.endswith("/pull/7") and pr.branch == "decision/x"
    tree = next(body for method, path, body in calls if path.endswith("/git/trees"))
    assert tree["base_tree"] == "base"
    assert {entry["path"] for entry in tree["tree"]} == {"a.md", "b/c.md"}
    commit = next(body for method, path, body in calls if path.endswith("/git/commits"))
    assert commit["parents"] == ["base"]
    pull = next(
        body for method, path, body in calls if method == "POST" and path.endswith("/pulls")
    )
    assert pull == {"title": "Title", "head": "decision/x", "base": "main", "body": "Body"}
    await publisher.aclose()


async def test_branch_name_collision_gets_suffix():
    publisher, _ = make(existing_branches={"decision/x"})
    pr = await publisher.open_pr("decision/x", {"a.md": "A"}, "T", "B")
    assert pr.branch == "decision/x-2"


async def test_http_error_becomes_publish_error():
    publisher, _ = make(fail_pulls=True)
    with pytest.raises(PublishError, match="403"):
        await publisher.open_pr("decision/x", {"a.md": "A"}, "T", "B")


async def test_open_pr_paths_lists_added_files_under_prefix():
    publisher, _ = make()
    assert await publisher.open_pr_paths("decisions/") == ["decisions/0003-x.md"]


async def test_network_error_on_branch_creation_is_a_publish_error():
    publisher, _ = make(refs_down=True)
    with pytest.raises(PublishError, match="network down"):
        await publisher.open_pr("decision/x", {"a.md": "A"}, "T", "B")


async def test_publish_error_public_summary_has_no_response_body():
    publisher, _ = make(fail_pulls=True)
    with pytest.raises(PublishError) as raised:
        await publisher.open_pr("decision/x", {"a.md": "A"}, "T", "B")
    assert raised.value.public == "GitHub answered 403"
    assert "forbidden" in str(raised.value)
