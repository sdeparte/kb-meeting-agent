from __future__ import annotations

import base64
import os
import subprocess
import threading
from pathlib import Path

from kb_meeting_agent.config import RepoConfig


class KbSyncError(Exception):
    """Raised when a repository cannot be cloned or updated."""


_CHECKOUT_LOCKS: dict[Path, threading.Lock] = {}
_CHECKOUT_LOCKS_GUARD = threading.Lock()


def _checkout_lock(repo_dir: Path) -> threading.Lock:
    """One git at a time per checkout: a sync cancelled at the end of a meeting keeps running
    in its thread, and the next meeting on the same project must not race it."""
    with _CHECKOUT_LOCKS_GUARD:
        return _CHECKOUT_LOCKS.setdefault(repo_dir.resolve(), threading.Lock())


class GitCheckout:
    """A local clone of a configured repository, kept on its base branch."""

    def __init__(self, config: RepoConfig, repo_dir: Path) -> None:
        self._config = config
        self.repo_dir = repo_dir

    def _clone_url(self) -> str:
        return self._config.clone_url or f"https://github.com/{self._config.repo}.git"

    def _basic_credential(self) -> str | None:
        if not self._config.token:
            return None
        return base64.b64encode(f"x-access-token:{self._config.token}".encode()).decode()

    def _git_env(self) -> dict[str, str]:
        """Auth through the environment: never written to .git/config, never in argv, and
        scoped to github.com so a custom clone_url host never receives the token."""
        env = dict(os.environ)
        credential = self._basic_credential()
        if credential:
            env |= {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credential}",
            }
        return env

    def _redact(self, message: str) -> str:
        for secret in (self._config.token, self._basic_credential()):
            if secret:
                message = message.replace(secret, "***")
        return message

    def _git(self, *args: str) -> None:
        try:
            subprocess.run(
                ["git", *args], check=True, capture_output=True, text=True, env=self._git_env()
            )
        except subprocess.CalledProcessError as exc:
            raise KbSyncError(self._redact(exc.stderr or str(exc))) from None

    def _git_sync(self) -> None:
        with _checkout_lock(self.repo_dir):
            self._git_sync_unlocked()

    def _git_sync_unlocked(self) -> None:
        branch = self._config.base_branch
        if not (self.repo_dir / ".git").exists():
            self.repo_dir.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--quiet", "--branch", branch, self._clone_url(), str(self.repo_dir))
            return
        repo = str(self.repo_dir)
        self._git("-C", repo, "remote", "set-url", "origin", self._clone_url())
        self._git("-C", repo, "fetch", "--quiet", "origin", branch)
        self._git("-C", repo, "reset", "--quiet", "--hard", f"origin/{branch}")
