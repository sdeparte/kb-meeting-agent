import json

import httpx
import pytest

from kb_meeting_agent.ports import BranchChangedError, PrRef, PublishError
from kb_meeting_agent.publish.github import GitHubPublisher


def make(existing_branches=(), fail_pulls=False, refs_down=False, head_parent="old-base"):
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
        if request.method == "GET" and path == "/repos/o/r/pulls/7":
            return httpx.Response(200, json={"number": 7, "state": "open"})
        if request.method == "GET" and path == "/repos/o/r/pulls/8":
            return httpx.Response(200, json={"number": 8, "state": "closed"})
        if request.method == "GET" and path == "/repos/o/r/git/ref/heads/decision/x":
            return httpx.Response(200, json={"object": {"sha": "agent-commit"}})
        if request.method == "GET" and path == "/repos/o/r/git/commits/agent-commit":
            return httpx.Response(200, json={"parents": [{"sha": head_parent}]})
        if request.method == "PATCH" and path == "/repos/o/r/git/refs/heads/decision/x":
            return httpx.Response(200, json={})
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


async def test_is_open():
    publisher, _ = make()
    assert await publisher.is_open(PrRef(7, "u", "b"))
    assert not await publisher.is_open(PrRef(8, "u", "b"))


async def test_update_branch_force_moves_the_branch_to_a_commit_on_the_base():
    publisher, calls = make()
    head = await publisher.update_branch(
        "decision/x", {"a.md": "A2"}, "Decision: x", "agent-commit"
    )
    assert head == "commit"
    commit = next(body for method, path, body in calls if path.endswith("/git/commits"))
    assert commit["parents"] == ["base"] and commit["message"] == "Decision: x"
    patch = next(body for method, path, body in calls if method == "PATCH")
    assert patch == {"sha": "commit", "force": True}
    refs = [i for i, (m, path, _) in enumerate(calls) if path.endswith("/git/ref/heads/decision/x")]
    built = next(i for i, (_, path, _) in enumerate(calls) if path.endswith("/git/commits"))
    assert refs[-1] > built  # the head is checked again after the commit is built


async def test_update_branch_leaves_a_branch_already_on_the_current_base():
    publisher, calls = make(head_parent="base")
    head = await publisher.update_branch("decision/x", {"a.md": "A"}, "T", "agent-commit")
    assert head == "agent-commit"
    assert not any(method in ("POST", "PATCH") for method, _, _ in calls)


async def test_open_pr_records_the_head_commit():
    publisher, _ = make()
    pr = await publisher.open_pr("decision/x", {"a.md": "A"}, "T", "B")
    assert pr.head == "commit"


async def test_update_branch_refuses_a_branch_changed_by_someone_else():
    publisher, calls = make()
    with pytest.raises(BranchChangedError):
        await publisher.update_branch("decision/x", {"a.md": "A2"}, "T", "agent-old-commit")
    assert not any(method == "PATCH" for method, _, _ in calls)
