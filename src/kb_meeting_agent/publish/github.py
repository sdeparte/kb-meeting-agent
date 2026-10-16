from __future__ import annotations

from typing import Any

import httpx

from kb_meeting_agent.ports import PrRef, PublishError

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

    async def open_pr(self, branch: str, files: dict[str, str], title: str, body: str) -> PrRef:
        repo = f"/repos/{self._repo}"
        base = await self._request("GET", f"{repo}/git/ref/heads/{self._base}")
        base_sha = base["object"]["sha"]
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
            json={"message": title, "tree": tree["sha"], "parents": [base_sha]},
        )
        head = await self._create_branch(branch, commit["sha"])
        pull = await self._request(
            "POST",
            f"{repo}/pulls",
            json={"title": title, "head": head, "base": self._base, "body": body},
        )
        return PrRef(number=pull["number"], url=pull["html_url"], branch=head)

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
