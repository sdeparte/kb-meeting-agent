from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from kb_meeting_agent.agent.meeting import AgentSettings, MeetingAgent
from kb_meeting_agent.agent.transcript import Transcript, load_segments
from kb_meeting_agent.config import load_config
from kb_meeting_agent.kb.repo import GitMarkdownKnowledgeBase
from kb_meeting_agent.llm.factory import build_provider
from kb_meeting_agent.ports import OutMessage, Publisher
from kb_meeting_agent.publish.github import GitHubPublisher
from kb_meeting_agent.publish.local import DryRunPublisher


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
    replay.add_argument("--kb", required=True, help="knowledge base name from the config")
    replay.add_argument("--out", type=Path, default=Path("replay-out"))
    replay.add_argument("--level", choices=["silent", "contradictions", "context"])
    replay.add_argument("--auto-validate", action="store_true", help="validate every decision")
    replay.add_argument("--publish", action="store_true", help="open real pull requests")
    args = parser.parse_args(argv)
    return asyncio.run(_replay(args))


async def _replay(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    kb_config = config.knowledge_bases.get(args.kb)
    if kb_config is None:
        print(f"unknown knowledge base: {args.kb}", file=sys.stderr)
        return 2
    if args.publish and not kb_config.token:
        print(f"--publish needs a token for knowledge base {args.kb}", file=sys.stderr)
        return 2
    embedder = build_provider(config.llm.embedding)
    kb = GitMarkdownKnowledgeBase(
        args.kb, kb_config, config.data_dir, embedder.embed, config.llm.embedding.model
    )
    await kb.sync()
    publisher: Publisher
    if args.publish:
        publisher = GitHubPublisher(kb_config.repo, kb_config.base_branch, kb_config.token)
    else:
        publisher = DryRunPublisher(args.out)
    transcript_path = args.out / "transcript.jsonl"
    transcript_path.unlink(missing_ok=True)
    agent = MeetingAgent(
        kb=kb,
        fast=build_provider(config.llm.fast),
        strong=build_provider(config.llm.strong),
        publisher=publisher,
        sink=ConsoleSink(),
        transcript=Transcript(transcript_path),
        settings=AgentSettings(
            agent_names=config.agent_names,
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
        if isinstance(publisher, GitHubPublisher):
            await publisher.aclose()
    return 0
