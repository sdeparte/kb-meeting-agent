from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from kb_meeting_agent.agent.meeting import AgentSettings, MeetingAgent
from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.prompting import format_timestamp
from kb_meeting_agent.agent.transcript import Transcript
from kb_meeting_agent.config import AppConfig, KbConfig, TranscriptionConfig
from kb_meeting_agent.live.audio import Utterance, UtteranceAssembler
from kb_meeting_agent.live.pipeline import TranscriptionPipeline
from kb_meeting_agent.live.protocol import AudioFrame
from kb_meeting_agent.llm.base import LLMProvider
from kb_meeting_agent.models import Segment
from kb_meeting_agent.ports import OutMessage, PrRef, Publisher, SyncableKnowledgeBase
from kb_meeting_agent.transcription.base import (
    HallucinationFilter,
    Transcriber,
    pcm16_to_float,
    read_wav,
    vocabulary_prompt,
)

log = logging.getLogger(__name__)

LOST_VOICE_STATES = ("disconnected", "destroyed", "lost")
MAX_SECOND_PASS_FAILURES = 3


class ConnectorPort(Protocol):
    async def send(self, type_: str, **fields: Any) -> bool: ...


class ConnectorSink:
    """Posts the agent's messages to the meeting's text channel through the connector."""

    def __init__(self, link: ConnectorPort, channel_id: str) -> None:
        self._link = link
        self._channel_id = channel_id
        self._count = 0
        # The connector opens a button's modal itself, from memory: kept here too, so a
        # restarted connector can be given them again (see resend_modals).
        self._modals: dict[str, dict[str, Any]] = {}

    async def send(self, message: OutMessage) -> str:
        self._count += 1
        request_id = f"m{self._count}"
        buttons = [
            {"id": b.id, "label": b.label, **({"modal": asdict(b.modal)} if b.modal else {})}
            for b in message.buttons
        ]
        self._modals |= {b["id"]: b["modal"] for b in buttons if "modal" in b}
        await self._link.send(
            "send",
            request_id=request_id,
            channel_id=self._channel_id,
            text=message.text,
            buttons=buttons,
        )
        return request_id

    def forget_modals(self, custom_id: str) -> None:
        """As the connector does: once one of a message's buttons is used, its modals go."""
        prefix = custom_id[: custom_id.rfind(":") + 1]
        self._modals = {id_: m for id_, m in self._modals.items() if not id_.startswith(prefix)}

    async def resend_modals(self) -> None:
        if self._modals:
            modals = [{"id": id_, "modal": modal} for id_, modal in self._modals.items()]
            await self._link.send("modals", modals=modals)


@dataclass
class SessionDeps:
    config: AppConfig
    link: ConnectorPort
    fast: LLMProvider
    strong: LLMProvider
    live_transcriber: Transcriber
    final_transcriber: Transcriber | None
    make_kb: Callable[[str, KbConfig], SyncableKnowledgeBase]
    make_publisher: Callable[[KbConfig], Publisher]
    clock_ms: Callable[[], int] = field(default=lambda: int(time.time() * 1000))
    today: Callable[[], date] = date.today


@dataclass
class ActiveMeeting:
    id: str
    dir: Path
    kb_name: str
    kb: SyncableKnowledgeBase
    publisher: Publisher
    voice_channel_id: str
    text_channel_id: str
    start_ms: int
    meeting_date: date
    prompt: str
    agent: MeetingAgent
    sink: ConnectorSink
    assembler: UtteranceAssembler
    pipeline: TranscriptionPipeline
    queue: asyncio.Queue[tuple[Any, ...]] = field(default_factory=asyncio.Queue)
    consumer: asyncio.Task[None] | None = None
    humans: set[str] = field(default_factory=set)
    empty_timer: asyncio.Task[None] | None = None
    gaps: list[list[float]] = field(default_factory=list)
    gap_started_ms: int | None = None
    lag_alerted: bool = False
    opted_out: set[str] = field(default_factory=set)
    closing: bool = False
    voice_ready: asyncio.Event = field(default_factory=asyncio.Event)
    joiner: asyncio.Task[None] | None = None

    @property
    def lang(self) -> str:
        return self.kb.conventions.language

    def relative_s(self, t_ms: int) -> float:
        return (t_ms - self.start_ms) / 1000


class MeetingSession:
    """One meeting at a time: lifecycle, live pipeline and a single consumer for the agent."""

    join_retry_s = 15.0  # first delay before asking the connector to join again

    def __init__(self, deps: SessionDeps) -> None:
        self.deps = deps
        self.meeting: ActiveMeeting | None = None
        self._meetings_dir = deps.config.data_dir / "meetings"
        self._purge_expired()

    @property
    def _transcription(self) -> TranscriptionConfig:
        assert self.deps.config.transcription is not None
        return self.deps.config.transcription

    def _cleaner(self) -> HallucinationFilter:
        tc = self._transcription
        return HallucinationFilter(
            tc.hallucination_phrases,
            tc.min_utterance_seconds,
            tc.max_no_speech_prob,
            min_voiced_seconds=tc.min_voiced_seconds,
            min_avg_logprob=tc.min_avg_logprob,
        )

    def _lang(self) -> str:
        return self.meeting.lang if self.meeting else "en"

    def _active(self) -> ActiveMeeting | None:
        """The meeting, unless it is closing: events arriving during a close are ignored."""
        m = self.meeting
        return m if m and not m.closing else None

    # -- events -------------------------------------------------------------------------

    async def on_event(self, kind: str, payload: Any) -> None:
        if kind == "audio":
            self._on_audio(payload)
        elif kind == "message":
            await self._on_message(payload)
        elif kind == "connected":
            await self._on_connected()
        elif kind == "disconnected":
            self._on_disconnected()

    def _on_disconnected(self) -> None:
        m = self._active()
        if m is None:
            return
        self._gap_start()
        # The dead connector will never end its open utterances: close them now, so the
        # restarted connector's utterances start fresh at the right time.
        for utterance in m.assembler.close_all(self.deps.clock_ms()):
            self._submit(utterance)

    def _on_audio(self, frame: AudioFrame) -> None:
        m = self._active()
        if m and (utterance := m.assembler.add(frame)):
            self._submit(utterance)

    async def _on_message(self, msg: dict[str, Any]) -> None:
        kind = msg["type"]
        m = self._active()
        if kind == "command":
            await self._on_command(msg)
        elif kind == "button" and m:
            m.sink.forget_modals(msg["custom_id"])
            await m.queue.put(("button", msg["custom_id"], msg["user"]["name"]))
        elif kind == "modal_submit" and m:
            m.sink.forget_modals(msg["custom_id"])
            await m.queue.put(("modal", msg["custom_id"], msg["value"], msg["user"]["name"]))
        elif kind == "members" and m:
            self._on_members(msg["members"])
        elif kind == "utterance_start" and m:
            m.assembler.start(msg["user_id"], msg.get("speaker_name") or msg["user_id"], msg["t"])
        elif kind == "utterance_end" and m:
            if utterance := m.assembler.end(msg["user_id"], msg["t"]):
                self._submit(utterance)
        elif kind == "voice_state" and m:
            await self._on_voice_state(msg["status"])
        elif kind == "stats" and m:
            log.info("connector stats: %s", msg)
            with (m.dir / "stats.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"t": self.deps.clock_ms(), **msg}) + "\n")
        elif kind == "error":
            log.warning("connector error: %s", msg.get("message"))

    async def _on_connected(self) -> None:
        m = self._active()
        if m:
            self._gap_start()
            await self._join(m)
            await self._send_optouts(m)  # a restarted connector has forgotten them
            await m.sink.resend_modals()  # and the Edit modals of messages already posted

    async def _join(self, m: ActiveMeeting) -> None:
        m.voice_ready.clear()
        await self.deps.link.send(
            "join", voice_channel_id=m.voice_channel_id, text_channel_id=m.text_channel_id
        )
        self._keep_joining(m)

    def _keep_joining(self, m: ActiveMeeting) -> None:
        if m.joiner is None or m.joiner.done():
            m.joiner = asyncio.create_task(self._join_until_ready(m))

    async def _join_until_ready(self, m: ActiveMeeting) -> None:
        """Ask again, with a growing delay, until the connector reports the voice as ready.

        A connector that has just (re)started may get the join before it is logged in to
        Discord, and gives up after a failed reconnection: the core never does.
        """
        delay = self.join_retry_s
        while not m.closing and self.meeting is m:
            try:
                await asyncio.wait_for(m.voice_ready.wait(), delay)
                return
            except TimeoutError:
                pass
            if m.closing or self.meeting is not m:
                return
            log.warning("voice not ready after %.0f s; asking the connector to join again", delay)
            await self.deps.link.send(
                "join", voice_channel_id=m.voice_channel_id, text_channel_id=m.text_channel_id
            )
            delay = min(delay * 2, 60.0)

    async def _send_optouts(self, m: ActiveMeeting) -> None:
        for user_id in sorted(m.opted_out):
            await self.deps.link.send("optout", user_id=user_id)

    def _gap_start(self) -> None:
        m = self.meeting
        if m and m.gap_started_ms is None:
            m.gap_started_ms = self.deps.clock_ms()

    async def _on_voice_state(self, status: str) -> None:
        m = self.meeting
        assert m is not None
        if status in LOST_VOICE_STATES:
            m.voice_ready.clear()
            self._gap_start()
            self._keep_joining(m)
            return
        if status == "ready":
            m.voice_ready.set()
        if status == "ready" and m.gap_started_ms is not None:
            start, end = m.relative_s(m.gap_started_ms), m.relative_s(self.deps.clock_ms())
            m.gap_started_ms = None
            m.gaps.append([start, end])
            await m.sink.send(
                OutMessage(
                    t(
                        m.lang,
                        "audio_interrupted",
                        start=format_timestamp(start),
                        end=format_timestamp(end),
                    )
                )
            )
            self._save_state()

    def _on_members(self, members: list[dict[str, Any]]) -> None:
        m = self.meeting
        assert m is not None
        m.humans = {member["id"] for member in members if not member.get("bot")}
        if m.humans and m.empty_timer:
            m.empty_timer.cancel()
            m.empty_timer = None
        elif not m.humans and m.empty_timer is None:
            m.empty_timer = asyncio.create_task(self._leave_when_empty())

    async def _leave_when_empty(self) -> None:
        await asyncio.sleep(self.deps.config.defaults.auto_leave_empty_minutes * 60)
        if self.meeting and not self.meeting.humans:
            await self.close()

    # -- live pipeline -------------------------------------------------------------------

    def _submit(self, utterance: Utterance) -> None:
        m = self.meeting
        assert m is not None
        with (m.dir / "utterances.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(utterance.record(), ensure_ascii=False) + "\n")
        m.pipeline.submit(utterance)

    async def _on_segment(self, segment: Segment) -> None:
        m = self.meeting
        if m is None:
            return
        await m.queue.put(("segment", segment))
        threshold = self.deps.config.defaults.transcription_lag_alert_seconds
        if m.pipeline.lag_s > threshold and not m.lag_alerted:
            m.lag_alerted = True
            await m.sink.send(
                OutMessage(t(m.lang, "transcription_lag", seconds=int(m.pipeline.lag_s)))
            )
        elif m.pipeline.lag_s < threshold / 2:
            m.lag_alerted = False

    async def _consume(self, m: ActiveMeeting) -> None:
        while True:
            item = await m.queue.get()
            try:
                kind = item[0]
                if kind == "stop":
                    return
                if kind == "segment":
                    await m.agent.on_segment(item[1])
                elif kind == "button":
                    await m.agent.on_button(item[1], item[2])
                elif kind == "modal":
                    await m.agent.on_modal(item[1], item[2], item[3])
                elif kind == "level":
                    await m.agent.set_level(item[1], announce=False)
                elif kind == "ask":
                    await self.deps.link.send(
                        "reply", interaction_id=item[2], text=await m.agent.ask(item[1])
                    )
            except Exception:
                log.exception("meeting step %s failed", item[0])
                if item[0] == "ask":  # the user is waiting on a deferred reply
                    await self.deps.link.send(
                        "reply", interaction_id=item[2], text=t(m.lang, "command_failed")
                    )
            finally:
                m.queue.task_done()
                self._save_state()

    async def settle(self) -> None:
        """Wait until every received utterance is transcribed and handled by the agent."""
        if self.meeting:
            await self.meeting.pipeline.drain()
            await self.meeting.queue.join()

    # -- commands ------------------------------------------------------------------------

    async def _reply(self, msg: dict[str, Any], text: str) -> None:
        await self.deps.link.send("reply", interaction_id=msg["interaction_id"], text=text)

    async def _on_command(self, msg: dict[str, Any]) -> None:
        handlers = {
            "meeting_start": self._start,
            "meeting_end": self._end,
            "meeting_level": self._level,
            "meeting_optout": self._optout,
            "meeting_resume": self._resume,
            "meeting_retry_publish": self._retry_publish,
            "ask": self._ask,
        }
        handler = handlers.get(msg["name"])
        if handler is None:
            await self._reply(msg, t(self._lang(), "unknown_command"))
            return
        try:
            await handler(msg)
        except Exception:
            log.exception("command %s failed", msg["name"])
            await self._reply(msg, t(self._lang(), "command_failed"))

    async def _start(self, msg: dict[str, Any]) -> None:
        if self.meeting:
            await self._reply(msg, t(self._lang(), "meeting_already_running"))
            return
        if not msg.get("voice_channel_id"):
            await self._reply(msg, t("en", "join_voice_first"))
            return
        kb_name = msg["options"].get("kb")
        kb_config = self.deps.config.knowledge_bases.get(kb_name or "")
        if kb_config is None:
            names = ", ".join(sorted(self.deps.config.knowledge_bases))
            await self._reply(msg, t("en", "unknown_kb", names=names))
            return
        self._purge_expired()
        kb = self.deps.make_kb(kb_name, kb_config)
        await kb.sync()
        m = self._open(
            meeting_id=f"{self.deps.today().isoformat()}-{uuid.uuid4().hex[:6]}",
            kb_name=kb_name,
            kb=kb,
            kb_config=kb_config,
            voice_channel_id=msg["voice_channel_id"],
            text_channel_id=msg["text_channel_id"],
            start_ms=self.deps.clock_ms(),
            meeting_date=self.deps.today(),
        )
        if level := msg["options"].get("level"):
            await m.agent.set_level(level, announce=False)
        await self._join(m)
        await m.sink.send(OutMessage(t(m.lang, "recording_notice", repo=kb_config.repo)))
        await self._reply(msg, t(m.lang, "meeting_started", kb=kb_name))
        self._save_state()

    async def _end(self, msg: dict[str, Any]) -> None:
        if not self.meeting:
            await self._reply(msg, t("en", "no_meeting"))
            return
        if self.meeting.closing:
            await self._reply(msg, t(self._lang(), "meeting_already_ending"))
            return
        await self._reply(msg, t(self._lang(), "meeting_ending"))
        await self.close()

    async def _open_meeting(self, msg: dict[str, Any]) -> ActiveMeeting | None:
        """The meeting a command can act on; replies and returns None if there is none.

        During a close the consumer has stopped reading the queue: a queued item would
        never be handled, so the command is refused instead.
        """
        if not self.meeting:
            await self._reply(msg, t("en", "no_meeting"))
            return None
        if self.meeting.closing:
            await self._reply(msg, t(self._lang(), "meeting_already_ending"))
            return None
        return self.meeting

    async def _level(self, msg: dict[str, Any]) -> None:
        if (m := await self._open_meeting(msg)) is None:
            return
        level = msg["options"].get("level")
        await m.queue.put(("level", level))
        await self._reply(msg, t(self._lang(), "level_changed", level=level))

    async def _optout(self, msg: dict[str, Any]) -> None:
        if not self.meeting:
            await self._reply(msg, t("en", "no_meeting"))
            return
        m = self.meeting
        user_id = msg["user"]["id"]
        m.opted_out.add(user_id)
        m.assembler.opt_out(user_id)
        for path in (m.dir / "audio").glob(f"*-{user_id}.wav"):
            path.unlink(missing_ok=True)
        await self.deps.link.send("optout", user_id=user_id)
        self._save_state()
        await self._reply(msg, t(self._lang(), "optout_done"))

    async def _ask(self, msg: dict[str, Any]) -> None:
        if (m := await self._open_meeting(msg)) is None:
            return
        await m.queue.put(("ask", msg["options"].get("question", ""), msg["interaction_id"]))

    def _purge_expired(self) -> None:
        """Delete meeting folders (audio, transcripts, state, kept files) past retention.

        Closed meetings and meetings abandoned after a crash are both purged once they have
        not been updated for transcript_retention_days.
        """
        retention_ms = self.deps.config.defaults.transcript_retention_days * 86_400_000
        horizon = self.deps.clock_ms() - retention_ms
        for directory, state in self._states():
            if self.meeting and directory == self.meeting.dir:
                continue
            if state.get("updated_ms", 0) < horizon:
                log.info("deleting expired meeting folder %s", directory.name)
                shutil.rmtree(directory, ignore_errors=True)

    def _states(self) -> list[tuple[Path, dict[str, Any]]]:
        found = []
        for path in self._meetings_dir.glob("*/state.json"):
            try:
                found.append((path.parent, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError):
                log.warning("unreadable meeting state %s", path)
        return sorted(found, key=lambda item: item[1].get("updated_ms", 0), reverse=True)

    async def _resume(self, msg: dict[str, Any]) -> None:
        if self.meeting:
            await self._reply(msg, t(self._lang(), "meeting_already_running"))
            return
        directory, active = next(
            ((d, s) for d, s in self._states() if s.get("status") == "active"), (None, None)
        )
        kb_config = self.deps.config.knowledge_bases.get(active["kb"]) if active else None
        if directory is None or active is None or kb_config is None:
            await self._reply(msg, t("en", "nothing_to_resume"))
            return
        kb = self.deps.make_kb(active["kb"], kb_config)
        await kb.sync()
        m = self._open(
            meeting_id=active["id"],
            kb_name=active["kb"],
            kb=kb,
            kb_config=kb_config,
            voice_channel_id=active["voice_channel_id"],
            text_channel_id=active["text_channel_id"],
            start_ms=active["start_ms"],
            meeting_date=date.fromisoformat(active["meeting_date"]),
            next_utterance=max(active["next_utterance"], self._next_free_utterance(directory)),
        )
        m.agent.restore(active["agent"])
        for user_id in active.get("opted_out", []):
            m.opted_out.add(user_id)
            m.assembler.opt_out(user_id)
        m.gaps = [
            *active["gaps"],
            [m.relative_s(active["updated_ms"]), m.relative_s(self.deps.clock_ms())],
        ]
        await self._join(m)
        await self._send_optouts(m)
        await self._reply(msg, t(m.lang, "meeting_resumed"))
        self._save_state()

    @staticmethod
    def _next_free_utterance(directory: Path) -> int:
        """One past the highest utterance index on disk: the state is saved after each
        handled step, so utterances recorded just before a crash can be ahead of it."""
        indexes = [
            int(path.name.split("-", 1)[0])
            for path in (directory / "audio").glob("*.wav")
            if path.name.split("-", 1)[0].isdigit()
        ]
        records = directory / "utterances.jsonl"
        if records.exists():
            for line in records.read_text(encoding="utf-8").splitlines():
                try:
                    indexes.append(int(json.loads(line)["index"]))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    continue
        return max(indexes, default=-1) + 1

    async def _retry_publish(self, msg: dict[str, Any]) -> None:
        candidates = [(d, s) for d, s in self._states() if any((d / "unpublished").rglob("PR.md"))]
        if not candidates:
            await self._reply(msg, t(self._lang(), "retry_publish_none"))
            return
        directory, state = candidates[0]
        kb_config = self.deps.config.knowledge_bases.get(state.get("kb", ""))
        if kb_config is None:
            await self._reply(msg, t(self._lang(), "retry_publish_none"))
            return
        publisher = self.deps.make_publisher(kb_config)
        kept = directory / "unpublished"
        urls: list[str] = []
        for description in sorted(kept.rglob("PR.md")):
            root = description.parent
            heading, _, body = description.read_text(encoding="utf-8").partition("\n\n")
            files = {
                path.relative_to(root).as_posix(): path.read_text(encoding="utf-8")
                for path in root.rglob("*")
                if path.is_file() and path != description
            }
            try:
                pr = await publisher.open_pr(
                    root.relative_to(kept).as_posix(), files, heading.removeprefix("# "), body
                )
            except Exception:
                log.exception("republishing %s failed", root)
                continue
            shutil.rmtree(root)
            urls.append(pr.url)
        if urls:
            text = t(self._lang(), "retry_publish_done", count=len(urls), urls=", ".join(urls))
        else:
            text = t(self._lang(), "retry_publish_none")
        await self._reply(msg, text)

    # -- meeting lifecycle ---------------------------------------------------------------

    def _open(
        self,
        *,
        meeting_id: str,
        kb_name: str,
        kb: SyncableKnowledgeBase,
        kb_config: KbConfig,
        voice_channel_id: str,
        text_channel_id: str,
        start_ms: int,
        meeting_date: date,
        next_utterance: int = 0,
    ) -> ActiveMeeting:
        directory = self._meetings_dir / meeting_id
        (directory / "audio").mkdir(parents=True, exist_ok=True)
        defaults = self.deps.config.defaults
        sink = ConnectorSink(self.deps.link, text_channel_id)
        agent = MeetingAgent(
            kb=kb,
            fast=self.deps.fast,
            strong=self.deps.strong,
            publisher=self.deps.make_publisher(kb_config),
            sink=sink,
            transcript=Transcript(directory / "transcript.jsonl"),
            settings=AgentSettings(
                agent_names=self.deps.config.agent_names,
                level=defaults.intervention_level,
                contradiction_min_confidence=defaults.contradiction_min_confidence,
                context_min_interval_s=defaults.context_min_interval_minutes * 60,
                stale_page_days=defaults.stale_page_days,
                meeting_date=meeting_date,
            ),
        )
        prompt = vocabulary_prompt(kb.glossary(), self._transcription.vocabulary_max_chars)
        pipeline = TranscriptionPipeline(
            self.deps.live_transcriber,
            language=self._transcription.language,
            prompt=prompt,
            cleaner=self._cleaner(),
            workers=self._transcription.workers,
            meeting_start_ms=start_ms,
            on_segment=self._on_segment,
            clock_ms=self.deps.clock_ms,
        )
        m = ActiveMeeting(
            id=meeting_id,
            dir=directory,
            kb_name=kb_name,
            kb=kb,
            publisher=agent.publisher,
            voice_channel_id=voice_channel_id,
            text_channel_id=text_channel_id,
            start_ms=start_ms,
            meeting_date=meeting_date,
            prompt=prompt,
            agent=agent,
            sink=sink,
            assembler=UtteranceAssembler(directory / "audio", next_utterance),
            pipeline=pipeline,
        )
        m.consumer = asyncio.create_task(self._consume(m))
        self.meeting = m
        return m

    def _save_state(self, status: str = "active") -> None:
        m = self.meeting
        if m is None:
            return
        state = {
            "status": status,
            "id": m.id,
            "kb": m.kb_name,
            "voice_channel_id": m.voice_channel_id,
            "text_channel_id": m.text_channel_id,
            "start_ms": m.start_ms,
            "meeting_date": m.meeting_date.isoformat(),
            "gaps": m.gaps,
            "opted_out": sorted(m.opted_out),
            "next_utterance": m.assembler.next_index,
            "updated_ms": self.deps.clock_ms(),
            "agent": m.agent.snapshot(),
        }
        temporary = m.dir / "state.json.tmp"
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(m.dir / "state.json")

    async def close(self) -> PrRef | None:
        """Flush, second pass, minutes, refresh decision PRs, leave.

        Never raises: a failed close is logged, told to the channel and saved as "failed"
        (not resumed, its folder kept until retention), and the session is free again.
        """
        m = self.meeting
        if m is None or m.closing:
            return None
        m.closing = True
        status, pr = "failed", None
        try:
            pr = await self._close(m)
            status = "closed"
        except Exception:
            log.exception("closing the meeting failed; its files are kept in %s", m.dir)
            try:
                await m.sink.send(OutMessage(t(m.lang, "close_failed")))
            except Exception:
                log.exception("telling the channel the close failed failed")
        finally:
            if m.consumer and not m.consumer.done():
                m.consumer.cancel()
            try:
                self._save_state(status=status)
            except Exception:
                log.exception("saving the meeting state failed")
            self.meeting = None
        if isinstance(pr, PrRef):
            shutil.rmtree(m.dir / "audio", ignore_errors=True)
        return pr

    async def _close(self, m: ActiveMeeting) -> PrRef | None:
        for task in (m.empty_timer, m.joiner):
            if task and task is not asyncio.current_task():
                task.cancel()
        now = self.deps.clock_ms()
        for utterance in m.assembler.close_all(now):
            self._submit(utterance)
        # Leave first: the bot must not look like it is still recording while it writes.
        await self.deps.link.send("leave")
        if m.gap_started_ms is not None:
            m.gaps.append([m.relative_s(m.gap_started_ms), m.relative_s(now)])
            m.gap_started_ms = None
        await m.pipeline.drain()
        await m.queue.put(("stop",))
        if m.consumer:
            await m.consumer
        final_segments = await self._second_pass(m)
        pr = await m.agent.end(segments=final_segments, gaps=[(g[0], g[1]) for g in m.gaps])
        try:
            await m.kb.sync()
            await m.agent.refresh_decision_prs()
        except Exception:
            log.exception("refreshing the decision pull requests failed")
        return pr

    async def _second_pass(self, m: ActiveMeeting) -> list[Segment] | None:
        final = self.deps.final_transcriber
        records_path = m.dir / "utterances.jsonl"
        if final is None or not records_path.exists():
            return None
        cleaner = self._cleaner()
        live = {(s.speaker_id, s.start, s.end): s for s in m.agent.transcript.all()}
        segments: list[Segment] = []
        failures = 0  # consecutive; the engine is given up after MAX_SECOND_PASS_FAILURES
        for line in records_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                log.warning("skipping a truncated utterance record (crash while writing it)")
                continue
            if record["speaker_id"] in m.opted_out:
                continue  # their audio was deleted; their live lines are kept below
            path = m.dir / "audio" / record["file"]
            key = (
                record["speaker_id"],
                m.relative_s(record["start_ms"]),
                m.relative_s(record["end_ms"]),
            )
            fallback = live.get(key)
            if not path.exists() or failures >= MAX_SECOND_PASS_FAILURES:
                segments += [fallback] if fallback else []
                continue
            try:
                audio = pcm16_to_float(read_wav(path))
                if not cleaner.audible(audio):
                    continue
                result = await asyncio.to_thread(
                    final.transcribe,
                    audio,
                    language=self._transcription.language,
                    prompt=m.prompt,
                )
            except Exception:
                failures += 1
                if failures == 1:
                    log.exception("second pass failed on %s; keeping the live line", record["file"])
                if failures == MAX_SECOND_PASS_FAILURES:
                    log.warning(
                        "second pass given up after %d consecutive failures; "
                        "the live transcription is used for the rest",
                        failures,
                    )
                segments += [fallback] if fallback else []
                continue
            failures = 0
            duration = (record["end_ms"] - record["start_ms"]) / 1000
            if text := cleaner.clean(result, duration):
                segments.append(
                    Segment(
                        record["speaker_id"],
                        record["speaker_name"],
                        m.relative_s(record["start_ms"]),
                        m.relative_s(record["end_ms"]),
                        text,
                    )
                )
        segments += [s for s in m.agent.transcript.all() if s.speaker_id in m.opted_out]
        segments.sort(key=lambda s: s.start)
        final_path = m.dir / "transcript.final.jsonl"
        final_path.unlink(missing_ok=True)
        final_transcript = Transcript(final_path)
        for segment in segments:
            final_transcript.append(segment)
        return segments or None
