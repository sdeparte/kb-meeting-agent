from __future__ import annotations

from typing import Any

import httpx

from kb_meeting_agent.ports import BranchChangedError, PrRef, PublishError

MAX_BRANCH_ATTEMPTS = 9
_NETWORK_ERROR = "network error while contacting GitHub"


class GitHubPublisher:
    def __init__(
        self,
        repo: str,
        base_branch: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        api_url: str = "https://api.github.com",
    ) -> None:
        self._repo = repo
        self._base = base_branch
        self._client = httpx.AsyncClient(
            base_url=api_url,
            transport=transport,
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise PublishError(f"{method} {url}: {exc}", public=_NETWORK_ERROR) from exc
        if response.status_code >= 400:
            raise PublishError(
                f"{method} {url}: {response.status_code} {response.text[:200]}",
                public=f"GitHub answered {response.status_code}",
            )
        return response.json() if response.content else None

    async def _base_sha(self) -> str:
        base = await self._request("GET", f"/repos/{self._repo}/git/ref/heads/{self._base}")
        return base["object"]["sha"]

    async def _commit_on_base(
        self, files: dict[str, str], message: str, base_sha: str | None = None
    ) -> str:
        repo = f"/repos/{self._repo}"
        base_sha = base_sha or await self._base_sha()
        tree = await self._request(
            "POST",
            f"{repo}/git/trees",
            json={
                "base_tree": base_sha,
                "tree": [
                    {"path": path, "mode": "100644", "type": "blob", "content": content}
                    for path, content in files.items()
                ],
            },
        )
        commit = await self._request(
            "POST",
            f"{repo}/git/commits",
            json={"message": message, "tree": tree["sha"], "parents": [base_sha]},
        )
        return commit["sha"]

    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef:
        sha = await self._commit_on_base(files, title)
        head = await self._create_branch(branch, sha)
        pull = await self._request(
            "POST",
            f"/repos/{self._repo}/pulls",
            json={"title": title, "head": head, "base": self._base, "body": body},
        )
        return PrRef(number=pull["number"], url=pull["html_url"], branch=head, head=sha)

    async def is_open(self, pr: PrRef) -> bool:
        pull = await self._request("GET", f"/repos/{self._repo}/pulls/{pr.number}")
        return pull["state"] == "open"

    async def update_branch(
        self, branch: str, files: dict[str, str], message: str, expected_head: str
    ) -> str:
        await self._check_head(branch, expected_head)
        repo = f"/repos/{self._repo}"
        head = await self._request("GET", f"{repo}/git/commits/{expected_head}")
        base_sha = await self._base_sha()
        if [parent["sha"] for parent in head["parents"]] == [base_sha]:
            return expected_head  # already one commit on the current base
        sha = await self._commit_on_base(files, message, base_sha)
        # GitHub has no compare-and-swap for a forced ref update: checking again right
        # before it leaves one request, not the whole commit build, for a push to be lost.
        await self._check_head(branch, expected_head)
        await self._request(
            "PATCH",
            f"/repos/{self._repo}/git/refs/heads/{branch}",
            json={"sha": sha, "force": True},
        )
        return sha

    async def _check_head(self, branch: str, expected_head: str) -> None:
        ref = await self._request("GET", f"/repos/{self._repo}/git/ref/heads/{branch}")
        if ref["object"]["sha"] != expected_head:
            raise BranchChangedError(f"{branch} is at {ref['object']['sha']}, not {expected_head}")

    async def _create_branch(self, branch: str, sha: str) -> str:
        for attempt in range(1, MAX_BRANCH_ATTEMPTS + 1):
            name = branch if attempt == 1 else f"{branch}-{attempt}"
            try:
                response = await self._client.post(
                    f"/repos/{self._repo}/git/refs",
                    json={"ref": f"refs/heads/{name}", "sha": sha},
                )
            except httpx.HTTPError as exc:
                raise PublishError(f"create branch {name}: {exc}", public=_NETWORK_ERROR) from exc
            if response.status_code == 201:
                return name
            if response.status_code != 422:
                raise PublishError(
                    f"create branch {name}: {response.status_code}",
                    public=f"GitHub answered {response.status_code}",
                )
        raise PublishError(f"no free branch name for {branch}", public="no free branch name")

    async def open_pr_paths(self, prefix: str) -> list[str]:
        repo = f"/repos/{self._repo}"
        pulls = await self._request(
            "GET", f"{repo}/pulls", params={"state": "open", "per_page": 100}
        )
        paths: list[str] = []
        for pull in pulls:
            files = await self._request(
                "GET", f"{repo}/pulls/{pull['number']}/files", params={"per_page": 100}
            )
            paths += [
                f["filename"]
                for f in files
                if f["status"] == "added" and f["filename"].startswith(prefix)
            ]
        return paths
