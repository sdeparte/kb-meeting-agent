"""Where a repository is hosted: its clone URL, git authentication and web links.

Opening pull requests on a host is a Publisher (publish/); the rest is here, so that adding
a host is one Forge, one Publisher and one `provider` value in RepoConfig.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from kb_meeting_agent.config import RepoConfig


class Forge(Protocol):
    @property
    def origin(self) -> str:
        """Scheme and host, e.g. https://github.com: the only host a token is sent to."""
        ...

    @property
    def token_username(self) -> str:
        """The user name that goes with a token in git's HTTP Basic authentication."""
        ...

    def clone_url(self, repo: str) -> str: ...

    def file_url(
        self, repo: str, branch: str, path: str, lines: tuple[int, int] | None = None
    ) -> str: ...


@dataclass(frozen=True)
class GitHub:
    origin: str = "https://github.com"
    token_username: str = "x-access-token"

    def clone_url(self, repo: str) -> str:
        return f"{self.origin}/{repo}.git"

    def file_url(
        self, repo: str, branch: str, path: str, lines: tuple[int, int] | None = None
    ) -> str:
        url = f"{self.origin}/{repo}/blob/{branch}/{path}"
        return f"{url}#L{lines[0]}-L{lines[1]}" if lines else url


GITHUB = GitHub()


def forge_for(config: RepoConfig) -> Forge:
    match config.provider:
        case "github":
            return GITHUB
