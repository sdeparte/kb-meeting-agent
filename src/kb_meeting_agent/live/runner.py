from __future__ import annotations

import asyncio
import logging
import os
import secrets
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from kb_meeting_agent.config import AppConfig, ProjectConfig, RepoConfig
from kb_meeting_agent.kb.project import ProjectSources, build_sources
from kb_meeting_agent.live.link import ConnectorLink
from kb_meeting_agent.live.protocol import CONFIG_ERROR_EXIT
from kb_meeting_agent.live.session import MeetingSession, SessionDeps
from kb_meeting_agent.llm.factory import build_provider
from kb_meeting_agent.ports import Publisher
from kb_meeting_agent.publish.factory import build_publisher
from kb_meeting_agent.publish.local import DryRunPublisher
from kb_meeting_agent.transcription.factory import build_transcriber

log = logging.getLogger(__name__)

CHECKOUT_DIR = Path(__file__).resolve().parents[3]  # bundled connectors: connector-<name>/
_PASSED_THROUGH = ("PATH", "HOME", "LANG", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP")


class ConnectorConfigError(Exception):
    """The connector cannot run with this configuration: restarting it would not help."""


class ConnectorProcess:
    """Runs the connector and restarts it with exponential backoff until stopped."""

    def __init__(
        self,
        command: list[str],
        env: dict[str, str],
        backoff_initial: float = 1.0,
        backoff_max: float = 60.0,
        stable_after: float = 60.0,
    ) -> None:
        self._command = command
        self._env = env
        self._initial = backoff_initial
        self._max = backoff_max
        self._stable_after = stable_after
        self.runs = 0
        self.refused = False

    async def run(self, stop: asyncio.Event) -> None:
        delay = self._initial
        while not stop.is_set():
            self.runs += 1
            started = time.monotonic()
            # Own process group: a Ctrl+C in the terminal reaches the core only, which closes
            # the meeting through the connector before stopping it.
            try:
                process = await asyncio.create_subprocess_exec(
                    *self._command, env=self._env, start_new_session=True
                )
            except OSError as exc:  # missing node or connector: retried, never silent
                outcome = f"could not be started ({exc})"
            else:
                waiter = asyncio.create_task(process.wait())
                stopper = asyncio.create_task(stop.wait())
                await asyncio.wait({waiter, stopper}, return_when=asyncio.FIRST_COMPLETED)
                stopper.cancel()
                if stop.is_set():
                    if process.returncode is None:
                        process.terminate()
                        try:
                            await asyncio.wait_for(process.wait(), 10)
                        except TimeoutError:
                            process.kill()
                    return
                if process.returncode == CONFIG_ERROR_EXIT:
                    log.error("connector refused its configuration; see its log above")
                    self.refused = True
                    return
                outcome = f"exited with {process.returncode}"
            if time.monotonic() - started > self._stable_after:
                delay = self._initial
            log.warning("connector %s; restarting in %.1f s", outcome, delay)
            try:
                await asyncio.wait_for(stop.wait(), delay)
            except TimeoutError:
                pass
            delay = min(delay * 2, self._max)


def connector_command(config: AppConfig) -> list[str]:
    connector = config.connector
    assert connector is not None
    if connector.command:
        return list(connector.command)
    directory = connector.dir or CHECKOUT_DIR / f"connector-{connector.name}"
    return [connector.node, str(directory / "src" / "index.js")]


def connector_env(url: str, secret: str, config: AppConfig) -> dict[str, str]:
    """Only what the connector needs: no model key or repository token."""
    assert config.connector is not None
    env = {name: os.environ[name] for name in _PASSED_THROUGH if name in os.environ}
    return env | config.connector.env | {"KBMA_CORE_URL": url, "KBMA_SECRET": secret}


def _deps(config: AppConfig, link: ConnectorLink) -> SessionDeps:
    assert config.transcription is not None
    embedder = build_provider(config.llm.embedding)

    def make_sources(name: str, project: ProjectConfig) -> ProjectSources:
        return build_sources(
            name, project, config.data_dir, embedder.embed, config.llm.embedding.model
        )

    def make_publisher(kb_config: RepoConfig) -> Publisher:
        if kb_config.token:
            return build_publisher(kb_config)
        return DryRunPublisher(config.data_dir / "dry-run", local_urls=False)

    final = config.transcription.final
    return SessionDeps(
        config=config,
        link=link,
        fast=build_provider(config.llm.fast),
        strong=build_provider(config.llm.strong),
        live_transcriber=build_transcriber(config.transcription.live),
        final_transcriber=build_transcriber(final) if final else None,
        make_sources=make_sources,
        make_publisher=make_publisher,
    )


async def run(
    config: AppConfig,
    *,
    connector: list[str] | None = None,
    stop: asyncio.Event | None = None,
    observe: Callable[[str, Any], None] | None = None,
) -> None:
    stop = stop or asyncio.Event()
    command = connector or connector_command(config)
    assert config.connector is not None
    if connector is None and not config.connector.command and not Path(command[1]).is_file():
        raise ConnectorConfigError(f"no connector at {command[1]}: check connector.name or dir")
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows, or not the main thread (tests)
    secret = secrets.token_urlsafe(32)
    link = ConnectorLink(secret)
    url = await link.start()
    session = MeetingSession(_deps(config, link))
    process = ConnectorProcess(command, connector_env(url, secret, config))
    # Stopping is two-step: the meeting is closed while the connector still runs (so the
    # channel gets the minutes link and the bot leaves), then the connector is stopped.
    stop_connector = asyncio.Event()
    supervisor = asyncio.create_task(process.run(stop_connector))
    supervisor.add_done_callback(lambda _: stop.set())  # a refused connector stops the run
    stopper = asyncio.create_task(stop.wait())
    try:
        while not stop.is_set():
            getter = asyncio.create_task(link.events.get())
            await asyncio.wait({getter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if not getter.done():
                getter.cancel()
                break
            kind, payload = getter.result()
            if observe:
                observe(kind, payload)
            try:
                await session.on_event(kind, payload)
            except Exception:
                log.exception("handling a connector event failed")
    finally:
        stopper.cancel()
        if session.meeting:
            await session.close()
        stop_connector.set()
        await supervisor
        await link.close()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.remove_signal_handler(signum)
            except (NotImplementedError, RuntimeError):
                pass
    if process.refused:
        raise ConnectorConfigError("the connector refused its configuration (connector.env)")
