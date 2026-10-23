from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from kb_meeting_agent.agent.meeting import AgentSettings, MeetingAgent
from kb_meeting_agent.agent.transcript import Transcript, load_segments
from kb_meeting_agent.config import load_config
from kb_meeting_agent.kb.project import build_sources
from kb_meeting_agent.llm.factory import build_provider
from kb_meeting_agent.ports import OutMessage, Publisher
from kb_meeting_agent.publish.factory import build_publisher
from kb_meeting_agent.publish.local import DryRunPublisher, LocalKeeper


class ConsoleSink:
    def __init__(self) -> None:
        self._count = 0

    async def send(self, message: OutMessage) -> str:
        self._count += 1
        print(f"[agent] {message.text}")
        for button in message.buttons:
            print(f"        [{button.label}] {button.id}")
        return str(self._count)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb-meeting-agent")
    commands = parser.add_subparsers(dest="command", required=True)
    replay = commands.add_parser("replay", help="replay a recorded transcript (JSONL)")
    replay.add_argument("transcript", type=Path)
    replay.add_argument("--config", type=Path, default=Path("config.yml"))
    replay.add_argument("--project", required=True, help="project name from the config")
    replay.add_argument("--out", type=Path, default=Path("replay-out"))
    replay.add_argument("--level", choices=["silent", "contradictions", "context"])
    replay.add_argument("--auto-validate", action="store_true", help="validate every decision")
    replay.add_argument("--publish", action="store_true", help="open real pull requests")
    live = commands.add_parser("run", help="join live meetings through the connector")
    live.add_argument("--config", type=Path, default=Path("config.yml"))
    index = commands.add_parser("index", help="sync and index every repository of a project")
    index.add_argument("--config", type=Path, default=Path("config.yml"))
    index.add_argument("--project", required=True, help="project name from the config")
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "index":
        return asyncio.run(_index(args))
    return asyncio.run(_replay(args))


def _run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    missing = [name for name in ("connector", "transcription") if getattr(config, name) is None]
    if missing:
        print(f"run needs the {' and '.join(missing)} section(s) in {args.config}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    for noisy in ("httpx", "httpx2", "huggingface_hub"):  # one line per HTTP request otherwise
        logging.getLogger(noisy).setLevel(logging.WARNING)
    from kb_meeting_agent.live.runner import ConnectorConfigError, run

    try:
        asyncio.run(run(config))
    except ConnectorConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


async def _index(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    project = config.projects.get(args.project)
    if project is None:
        print(f"unknown project: {args.project}", file=sys.stderr)
        return 2
    embedder = build_provider(config.llm.embedding)
    sources = build_sources(
        args.project, project, config.data_dir, embedder.embed, config.llm.embedding.model
    )
    failed = False
    try:
        # One failing repository (git, or the embedding server) does not stop the others.
        for repo in (sources.knowledge_base, *sources.code_repos):
            try:
                await repo.sync()
                print(f"indexed {repo.name}: {repo.file_count} files")
            except Exception as exc:
                print(f"{repo.name}: {exc}", file=sys.stderr)
                failed = True
    finally:
        sources.close()
    return 1 if failed else 0


async def _replay(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    project = config.projects.get(args.project)
    if project is None:
        print(f"unknown project: {args.project}", file=sys.stderr)
        return 2
    kb_name, kb_config = project.knowledge_base
    if args.publish and not kb_config.token:
        print(f"--publish needs a token for the {kb_name} repository", file=sys.stderr)
        return 2
    embedder = build_provider(config.llm.embedding)
    kb = build_sources(
        args.project, project, config.data_dir, embedder.embed, config.llm.embedding.model
    )
    await kb.sync()
    for repo in kb.code_repos:
        try:
            await repo.sync()
        except Exception as exc:
            print(f"{repo.name}: {exc} (answers rely on the other sources)", file=sys.stderr)
    publisher: Publisher
    if args.publish:
        publisher = build_publisher(kb_config)
    else:
        publisher = DryRunPublisher(args.out)
    transcript_path = args.out / "transcript.jsonl"
    transcript_path.unlink(missing_ok=True)
    agent = MeetingAgent(
        kb=kb,
        fast=build_provider(config.llm.fast),
        strong=build_provider(config.llm.strong),
        publisher=publisher,
        keeper=LocalKeeper(args.out / "unpublished"),
        sink=ConsoleSink(),
        transcript=Transcript(transcript_path),
        settings=AgentSettings(
            agent_name=config.agent.name,
            agent_aliases=config.agent.aliases,
            level=args.level or config.defaults.intervention_level,
            contradiction_min_confidence=config.defaults.contradiction_min_confidence,
            context_min_interval_s=config.defaults.context_min_interval_minutes * 60,
            stale_page_days=config.defaults.stale_page_days,
        ),
    )

    async def auto_validate() -> None:
        if args.auto_validate:
            for decision in list(agent.decisions.values()):
                if decision.state == "pending":
                    await agent.validate_decision(decision.id, "replay")

    try:
        for segment in load_segments(args.transcript):
            await agent.on_segment(segment)
            await auto_validate()
        await agent.flush()
        await auto_validate()
        await agent.end()
    finally:
        kb.close()
        await publisher.aclose()
    return 0
