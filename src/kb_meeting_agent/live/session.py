from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from kb_meeting_agent.agent.decisions import append_table_row, existing_numbers
from kb_meeting_agent.agent.meeting import AgentSettings, MeetingAgent
from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.prompting import format_timestamp
from kb_meeting_agent.agent.transcript import Transcript
from kb_meeting_agent.commands import button_commands, catalog_payload, help_text, parse, typed
from kb_meeting_agent.config import AppConfig, ProjectConfig, RepoConfig, TranscriptionConfig
from kb_meeting_agent.kb.project import ProjectSources
from kb_meeting_agent.live.audio import Utterance, UtteranceAssembler, speaker_file_id
from kb_meeting_agent.live.pipeline import TranscriptionPipeline
from kb_meeting_agent.live.protocol import AudioFrame
from kb_meeting_agent.llm.base import LLMProvider
from kb_meeting_agent.models import Segment
from kb_meeting_agent.ports import OutMessage, PrRef, Publisher
from kb_meeting_agent.publish.local import LocalKeeper
from kb_meeting_agent.transcription.base import Transcriber, pcm16_to_float, read_wav
from kb_meeting_agent.transcription.filtering import HallucinationFilter
from kb_meeting_agent.transcription.vocabulary import vocabulary_prompt

log = logging.getLogger(__name__)

LOST_VOICE_STATES = ("disconnected", "destroyed", "lost")
# A connector that cannot rejoin on its own (a browser account must be invited into the call).
INVITE_NEEDED = "needs_invite"
MAX_SECOND_PASS_FAILURES = 3
# Commands that change the meeting itself: only from its call or its text channel.
PARTICIPANT_COMMANDS = frozenset(
    {
        "meeting_project",
        "meeting_end",
        "meeting_level",
        "decision_validate",
        "decision_ignore",
        "decision_edit",
    }
)


class ConnectorPort(Protocol):
    async def send(self, type_: str, **fields: Any) -> bool: ...


class ConnectorSink:
    """Posts the agent's messages to the meeting's text channel through the connector."""

    def __init__(
        self, link: ConnectorPort, channel_id: str, *, buttons: bool = True, lang: str = "en"
    ) -> None:
        self._link = link
        self._channel_id = channel_id
        # hello.capabilities.buttons: False on text-only platforms, where what to type
        # replaces them.
        self.buttons = buttons
        self._lang = lang
        # The connector keeps the ids of the messages it posted across meetings: a prefix of
        # this sink's own, so an answer never replies to another meeting's message.
        self._prefix = uuid.uuid4().hex[:6]
        self._count = 0
        # The connector opens a button's modal itself, from memory: kept here too, so a
        # restarted connector can be given them again (see resend_modals).
        self._modals: dict[str, dict[str, Any]] = {}

    async def send(self, message: OutMessage) -> str:
        self._count += 1
        request_id = f"{self._prefix}-m{self._count}"
        text = message.text
        if not self.buttons:
            typed = [c for b in message.buttons if (c := button_commands(b.id, self._lang))]
            if typed:
                commands = " / ".join(f"`{c}`" for c in typed)
                text += "\n" + t(self._lang, "decision_reply_hint", commands=commands)
            message = replace(message, text=text, buttons=())
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
            **({"reply_to": message.reply_to} if message.reply_to else {}),
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
    make_sources: Callable[[str, ProjectConfig], ProjectSources]
    make_publisher: Callable[[RepoConfig], Publisher]
    clock_ms: Callable[[], int] = field(default=lambda: int(time.time() * 1000))
    today: Callable[[], date] = date.today


@dataclass
class ActiveMeeting:
    id: str
    dir: Path
    project: str
    kb: ProjectSources
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
    invite_asked: bool = False  # participants asked to invite the agent again, since the last ready
    joiner: asyncio.Task[None] | None = None
    code_sync: asyncio.Task[None] | None = None

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
        self._buttons = True  # from the connector's hello: whether it can show buttons
        # A meeting interrupted in a call, offered by `start` there: (call, (folder, state)).
        self._resume_offer: tuple[str, tuple[Path, dict[str, Any]]] | None = None
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
            max_compression_ratio=tc.max_compression_ratio,
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
            await self._on_connected(payload)
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
        elif kind == "chat":
            await self._on_chat(msg)
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

    async def _on_connected(self, hello: dict[str, Any]) -> None:
        await self.deps.link.send("commands", commands=catalog_payload())
        self._buttons = bool((hello.get("capabilities") or {}).get("buttons", True))
        if self.meeting:
            self.meeting.sink.buttons = self._buttons
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
        its platform, and gives up after a failed reconnection: the core never does.
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
        if status in LOST_VOICE_STATES or status == INVITE_NEEDED:
            m.voice_ready.clear()
            self._gap_start()
            self._keep_joining(m)
            if status == INVITE_NEEDED and not m.invite_asked:
                m.invite_asked = True
                await m.sink.send(OutMessage(t(m.lang, "invite_agent_again")))
            return
        if status == "ready":
            m.voice_ready.set()
            m.invite_asked = False
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
                    await m.agent.set_level(item[1], announce=False, user=item[2])
                elif kind == "ask":
                    await self._respond(item[2], await m.agent.ask(item[1], user=item[3]))
            except Exception:
                log.exception("meeting step %s failed", item[0])
                if item[0] == "ask":  # the user is waiting on a deferred reply
                    await self._respond(item[2], t(m.lang, "command_failed"))
            finally:
                m.queue.task_done()
                self._save_state()

    async def settle(self) -> None:
        """Wait until every received utterance is transcribed and handled by the agent."""
        if self.meeting:
            await self.meeting.pipeline.drain()
            await self.meeting.queue.join()

    # -- commands ------------------------------------------------------------------------

    async def _respond(self, msg: dict[str, Any], text: str) -> None:
        """Answer a command where it came from: a slash command's deferred reply, or the
        channel a chat command was typed in."""
        if msg.get("origin") != "chat":
            await self.deps.link.send("reply", interaction_id=msg["interaction_id"], text=text)
            return
        channel = msg.get("text_channel_id") or (self.meeting and self.meeting.text_channel_id)
        await self.deps.link.send(
            "send",
            request_id=f"r-{uuid.uuid4().hex[:12]}",
            channel_id=channel,
            text=text,
            buttons=[],
        )

    async def _on_chat(self, msg: dict[str, Any]) -> None:
        """A chat line: the same commands as the slash commands, typed as `!…`."""
        parsed = parse(msg.get("text", ""))
        if parsed is None:
            return
        # An unknown word may be another bot's command: the help only in the meeting's
        # text channel, where the agent is the one expected to answer.
        if not parsed.known and not (
            self.meeting and msg.get("text_channel_id") == self.meeting.text_channel_id
        ):
            return
        await self._on_command(
            {
                "type": "command",
                "origin": "chat",
                "interaction_id": f"chat-{uuid.uuid4().hex}",
                "name": parsed.id,
                "options": parsed.options,
                "user": msg["user"],
                "text_channel_id": msg.get("text_channel_id"),
                "voice_channel_id": msg.get("voice_channel_id"),
            }
        )

    async def _on_command(self, msg: dict[str, Any]) -> None:
        handlers = {
            "meeting_start": self._start,
            "meeting_end": self._end,
            "meeting_level": self._level,
            "meeting_optout": self._optout,
            "meeting_resume": self._resume,
            "meeting_retry_publish": self._retry_publish,
            "ask": self._ask,
            "help": self._help,
            "meeting_project": self._project,
            "decision_validate": self._decide,
            "decision_ignore": self._decide,
            "decision_edit": self._decide,
        }
        handler = handlers.get(msg["name"])
        if handler is None:
            await self._respond(msg, t(self._lang(), "unknown_command"))
            return
        if msg["name"] in PARTICIPANT_COMMANDS and not self._from_meeting(msg):
            await self._respond(msg, t(self._lang(), "not_in_meeting"))
            return
        try:
            await handler(msg)
        except Exception:
            log.exception("command %s failed", msg["name"])
            await self._respond(msg, t(self._lang(), "command_failed"))

    def _from_meeting(self, msg: dict[str, Any]) -> bool:
        """Whether a command comes from the meeting's call or its text channel (or there is
        no meeting, which the handler answers)."""
        m = self.meeting
        return m is None or (
            msg.get("voice_channel_id") == m.voice_channel_id
            or msg.get("text_channel_id") == m.text_channel_id
        )

    async def _post_notice(self, m: ActiveMeeting, kb_config: RepoConfig) -> None:
        notice = t(
            m.lang,
            "recording_notice",
            repo=kb_config.repo,
            name=self.deps.config.agent.name,
            project=m.project,
        )
        await m.sink.send(OutMessage(notice))

    async def _project(self, msg: dict[str, Any]) -> None:
        if (m := await self._open_meeting(msg)) is None:
            return
        found = self.deps.config.project_named(msg["options"].get("project"))
        if found is None:
            names = ", ".join(sorted(self.deps.config.projects))
            await self._respond(msg, t(m.lang, "unknown_project", names=names))
            return
        name, project_config = found
        if name == m.project:
            await self._respond(msg, t(m.lang, "project_changed", project=name))
        elif m.agent.acted:
            await self._respond(msg, t(m.lang, "project_locked", project=m.project))
        else:
            await self._switch_project(msg, m, name, project_config)

    async def _switch_project(
        self, msg: dict[str, Any], m: ActiveMeeting, name: str, project_config: ProjectConfig
    ) -> None:
        """Reopen the meeting on another project: same id, folder, transcript and opt-outs;
        new sources, publisher, agent, vocabulary hint and transcription pipeline."""
        _, kb_config = project_config.knowledge_base
        kb = self.deps.make_sources(name, project_config)
        await self._sync_or_close(kb)
        # Utterances still open stay open: the new meeting keeps the assembler, so whoever
        # is speaking is not cut. What is already recorded is handled on the old project.
        await m.pipeline.drain()
        await m.queue.join()
        # Meanwhile the meeting may have closed (the room emptied), or what was still being
        # transcribed or queued may have made the agent speak.
        if m.closing or self.meeting is not m:
            kb.close()
            return
        if m.agent.acted:
            kb.close()
            await self._respond(msg, t(m.lang, "project_locked", project=m.project))
            return
        await m.queue.put(("stop",))
        if m.consumer:
            await m.consumer
        for task in (m.code_sync, m.joiner):
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        m.kb.close()
        try:
            await m.publisher.aclose()
        except Exception:
            log.exception("closing the publisher failed")
        new = self._open(
            meeting_id=m.id,
            project=name,
            kb=kb,
            kb_config=kb_config,
            voice_channel_id=m.voice_channel_id,
            text_channel_id=m.text_channel_id,
            start_ms=m.start_ms,
            meeting_date=m.meeting_date,
            assembler=m.assembler,
        )
        new.agent.restore(m.agent.snapshot())
        new.opted_out |= m.opted_out
        new.gaps, new.gap_started_ms = m.gaps, m.gap_started_ms
        new.humans, new.empty_timer = m.humans, m.empty_timer
        if m.voice_ready.is_set():
            new.voice_ready.set()
        else:
            self._keep_joining(new)
        await self._post_notice(new, kb_config)
        await self._respond(msg, t(new.lang, "project_changed", project=name))
        self._save_state()
        new.code_sync = asyncio.create_task(self._sync_code(new))

    async def _help(self, msg: dict[str, Any]) -> None:
        await self._respond(msg, help_text(self._lang()))

    async def _decide(self, msg: dict[str, Any]) -> None:
        """A decision validated, ignored or reworded by a typed command: what its button or
        its Edit modal would have done."""
        if (m := await self._open_meeting(msg)) is None:
            return
        decision, user = msg["options"]["decision"].casefold(), msg["user"]["name"]
        found = m.agent.decisions.get(decision)
        if found is None or found.state != "pending":
            pending = [d for d, c in m.agent.decisions.items() if c.state == "pending"]
            listed = ", ".join(pending) or t(m.lang, "no_pending_decision")
            await self._respond(
                msg, t(m.lang, "unknown_decision", decision=decision, pending=listed)
            )
            return
        action = msg["name"].removeprefix("decision_")
        custom_id = f"decision:{decision}:{action}"
        m.sink.forget_modals(custom_id)
        if action == "edit":
            await m.queue.put(("modal", custom_id, msg["options"]["statement"], user))
        else:
            await m.queue.put(("button", custom_id, user))

    def _interrupted_in(
        self, voice_channel_id: str, project: str | None
    ) -> tuple[Path, dict[str, Any]] | None:
        """Today's meeting left active by a crash in this call, on the named project if one
        is named: a channel used again another day, or for another project, starts afresh
        (`!resume` still picks the old meeting up)."""
        today = self.deps.today().isoformat()
        return next(
            (
                (d, s)
                for d, s in self._states()
                if s.get("status") == "active"
                and s.get("voice_channel_id") == voice_channel_id
                and s.get("meeting_date") == today
                and s.get("project") in self.deps.config.projects
                and project in (None, s.get("project"))
            ),
            None,
        )

    async def _start(self, msg: dict[str, Any]) -> None:
        if self.meeting:
            await self._respond(msg, t(self._lang(), "meeting_already_running"))
            return
        if not msg.get("voice_channel_id"):
            await self._respond(msg, t("en", "join_voice_first"))
            return
        named = msg["options"].get("project")
        call = msg["voice_channel_id"]
        # A meeting interrupted in this call is offered once; `start` again starts afresh.
        offered = self._resume_offer and self._resume_offer[0] == call
        self._resume_offer = None
        if not offered and (interrupted := self._interrupted_in(call, named)):
            self._resume_offer = (call, interrupted)
            offer = t(
                "en",
                "resume_offer",
                project=interrupted[1]["project"],
                resume=typed("meeting_resume", "en"),
                start=typed("meeting_start", "en"),
            )
            await self._respond(msg, offer)
            return
        found = self.deps.config.project_named(named)
        if found is None:
            names = ", ".join(sorted(self.deps.config.projects))
            await self._respond(msg, t("en", "unknown_project", names=names))
            return
        project, project_config = found
        self._purge_expired()
        _, kb_config = project_config.knowledge_base
        kb = self.deps.make_sources(project, project_config)
        await self._sync_or_close(kb)
        m = self._open(
            meeting_id=f"{self.deps.today().isoformat()}-{uuid.uuid4().hex[:6]}",
            project=project,
            kb=kb,
            kb_config=kb_config,
            voice_channel_id=msg["voice_channel_id"],
            text_channel_id=msg["text_channel_id"],
            start_ms=self.deps.clock_ms(),
            meeting_date=self.deps.today(),
        )
        if level := msg["options"].get("level"):
            await m.agent.set_level(level, announce=False, user=msg["user"]["name"])
        await self._join(m)
        await self._post_notice(m, kb_config)
        await self._respond(msg, t(m.lang, "meeting_started", project=project))
        self._save_state()
        m.code_sync = asyncio.create_task(self._sync_code(m))

    async def _end(self, msg: dict[str, Any]) -> None:
        if not self.meeting:
            await self._respond(msg, t("en", "no_meeting"))
            return
        if self.meeting.closing:
            await self._respond(msg, t(self._lang(), "meeting_already_ending"))
            return
        await self._respond(msg, t(self._lang(), "meeting_ending"))
        await self.close()

    async def _open_meeting(self, msg: dict[str, Any]) -> ActiveMeeting | None:
        """The meeting a command can act on; replies and returns None if there is none.

        During a close the consumer has stopped reading the queue: a queued item would
        never be handled, so the command is refused instead.
        """
        if not self.meeting:
            await self._respond(msg, t("en", "no_meeting"))
            return None
        if self.meeting.closing:
            await self._respond(msg, t(self._lang(), "meeting_already_ending"))
            return None
        return self.meeting

    async def _level(self, msg: dict[str, Any]) -> None:
        if (m := await self._open_meeting(msg)) is None:
            return
        level = msg["options"].get("level")
        await m.queue.put(("level", level, msg["user"]["name"]))
        await self._respond(msg, t(self._lang(), "level_changed", level=level))

    async def _optout(self, msg: dict[str, Any]) -> None:
        if not self.meeting:
            await self._respond(msg, t("en", "no_meeting"))
            return
        m = self.meeting
        user = msg["user"]
        # `speaker_ids`: the audio ids the author may be, when the platform's chat only names them
        for user_id in dict.fromkeys([user["id"], *user.get("speaker_ids", [])]):
            m.opted_out.add(user_id)
            m.assembler.opt_out(user_id)
            for path in (m.dir / "audio").glob(f"*-{speaker_file_id(user_id)}.wav"):
                path.unlink(missing_ok=True)
            await self.deps.link.send("optout", user_id=user_id)
        self._save_state()
        await self._respond(msg, t(self._lang(), "optout_done"))

    async def _ask(self, msg: dict[str, Any]) -> None:
        if (m := await self._open_meeting(msg)) is None:
            return
        await m.queue.put(("ask", msg["options"].get("question", ""), msg, msg["user"]["name"]))

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

    @staticmethod
    async def _sync_or_close(sources: ProjectSources) -> None:
        try:
            await sources.sync()
        except BaseException:
            sources.close()
            raise

    async def _resume(self, msg: dict[str, Any]) -> None:
        if self.meeting:
            await self._respond(msg, t(self._lang(), "meeting_already_running"))
            return
        found = self._resume_offer[1] if self._resume_offer else None
        self._resume_offer = None
        directory, active = found or next(
            ((d, s) for d, s in self._states() if s.get("status") == "active"), (None, None)
        )
        project_config = (
            self.deps.config.projects.get(active.get("project", "")) if active else None
        )
        if directory is None or active is None or project_config is None:
            await self._respond(msg, t("en", "nothing_to_resume"))
            return
        _, kb_config = project_config.knowledge_base
        kb = self.deps.make_sources(active["project"], project_config)
        await self._sync_or_close(kb)
        m = self._open(
            meeting_id=active["id"],
            project=active["project"],
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
        await self._post_notice(m, kb_config)  # people may have joined since
        await self._respond(msg, t(m.lang, "meeting_resumed"))
        self._save_state()
        m.code_sync = asyncio.create_task(self._sync_code(m))

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
        candidates = [(d, s) for d, s in self._states() if any(LocalKeeper.of_meeting(d).kept())]
        if not candidates:
            await self._respond(msg, t(self._lang(), "retry_publish_none"))
            return
        directory, state = candidates[0]
        project_config = self.deps.config.projects.get(state.get("project", ""))
        if project_config is None:
            await self._respond(msg, t(self._lang(), "retry_publish_none"))
            return
        _, kb_config = project_config.knowledge_base
        publisher = self.deps.make_publisher(kb_config)
        try:
            # The kept files were built on the KB of the meeting day: index rows are rebuilt
            # on today's base, and a decision number taken since is not published.
            kb = self.deps.make_sources(state["project"], project_config)
            try:
                await self._republish_kept(msg, LocalKeeper.of_meeting(directory), kb, publisher)
            finally:
                kb.close()
        finally:
            try:
                await publisher.aclose()
            except Exception:  # the result is already posted: a second reply would contradict it
                log.exception("closing the publisher failed")

    async def _republish_kept(
        self, msg: dict[str, Any], keeper: LocalKeeper, kb: ProjectSources, publisher: Publisher
    ) -> None:
        await kb.sync()  # the knowledge base only: the code is not needed to publish
        decisions_dir = kb.conventions.decisions.dir.rstrip("/") + "/"
        taken = existing_numbers(
            kb.list_files(decisions_dir) + await publisher.open_pr_paths(decisions_dir)
        )
        urls: list[str] = []
        lines: list[str] = []
        for change in keeper.kept():
            branch, files, rows = change.branch, dict(change.files), change.index_rows
            numbers = existing_numbers(
                path for path in files if path.startswith(decisions_dir) and path not in rows
            )
            if clash := sorted(numbers & taken):
                lines.append(
                    t(self._lang(), "retry_publish_number_taken", number=clash[0], branch=branch)
                )
                continue
            for index_file, row in rows.items():
                current = kb.read(index_file) if kb.exists(index_file) else None
                rebuilt = append_table_row(current, row) if current is not None else None
                if rebuilt is None:
                    log.warning("%s has no table any more: no index row added", index_file)
                    files.pop(index_file, None)
                else:
                    files[index_file] = rebuilt
            try:
                pr = await publisher.open_pr(branch, files, change.title, change.body)
            except Exception:
                log.exception("republishing %s failed", branch)
                continue
            keeper.discard(branch)
            urls.append(pr.url)
        if urls:
            lines.insert(
                0, t(self._lang(), "retry_publish_done", count=len(urls), urls=", ".join(urls))
            )
        await self._respond(msg, "\n".join(lines) or t(self._lang(), "retry_publish_none"))

    # -- meeting lifecycle ---------------------------------------------------------------

    def _open(
        self,
        *,
        meeting_id: str,
        project: str,
        kb: ProjectSources,
        kb_config: RepoConfig,
        voice_channel_id: str,
        text_channel_id: str,
        start_ms: int,
        meeting_date: date,
        next_utterance: int = 0,
        assembler: UtteranceAssembler | None = None,
    ) -> ActiveMeeting:
        directory = self._meetings_dir / meeting_id
        (directory / "audio").mkdir(parents=True, exist_ok=True)
        defaults = self.deps.config.defaults
        sink = ConnectorSink(
            self.deps.link, text_channel_id, buttons=self._buttons, lang=kb.conventions.language
        )
        agent = MeetingAgent(
            kb=kb,
            fast=self.deps.fast,
            strong=self.deps.strong,
            publisher=self.deps.make_publisher(kb_config),
            keeper=LocalKeeper.of_meeting(directory),
            sink=sink,
            transcript=Transcript(directory / "transcript.jsonl"),
            settings=AgentSettings(
                agent_name=self.deps.config.agent.name,
                agent_aliases=self.deps.config.agent.aliases,
                level=defaults.intervention_level,
                contradiction_min_confidence=defaults.contradiction_min_confidence,
                context_min_interval_s=defaults.context_min_interval_minutes * 60,
                stale_page_days=defaults.stale_page_days,
                meeting_date=meeting_date,
            ),
        )
        # The agent's name first, so that Whisper spells it right when people call it. Not
        # its aliases: they are often misspellings, which the hint would teach Whisper.
        # The whole glossary: the hint keeps its own length, and a cut page would stop it at "C".
        prompt = vocabulary_prompt(
            kb.glossary(max_chars=None),
            self._transcription.vocabulary_max_chars,
            first=[self.deps.config.agent.name, *self._transcription.vocabulary],
        )
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
            project=project,
            kb=kb,
            publisher=agent.publisher,
            voice_channel_id=voice_channel_id,
            text_channel_id=text_channel_id,
            start_ms=start_ms,
            meeting_date=meeting_date,
            prompt=prompt,
            agent=agent,
            sink=sink,
            assembler=assembler or UtteranceAssembler(directory / "audio", next_utterance),
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
            "project": m.project,
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
            if m.code_sync:
                m.code_sync.cancel()
                await asyncio.gather(m.code_sync, return_exceptions=True)
            m.kb.close()
            try:
                await m.publisher.aclose()
            except Exception:
                log.exception("closing the publisher failed")
            try:
                self._save_state(status=status)
            except Exception:
                log.exception("saving the meeting state failed")
            self.meeting = None
        if isinstance(pr, PrRef):
            shutil.rmtree(m.dir / "audio", ignore_errors=True)
        return pr

    async def _close(self, m: ActiveMeeting) -> PrRef | None:
        for task in (m.empty_timer, m.joiner, m.code_sync):
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

    async def _sync_code(self, m: ActiveMeeting) -> None:
        """Sync each code repository while the meeting runs: searches use what is indexed."""
        for repo in m.kb.code_repos:
            if not repo.indexed:
                await m.sink.send(OutMessage(t(m.lang, "code_index_building", repo=repo.name)))
            try:
                await repo.sync()
            except Exception:
                log.exception("syncing the %s repository failed", repo.name)
                await m.sink.send(OutMessage(t(m.lang, "code_repo_unavailable", repo=repo.name)))

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
                duration = (record["end_ms"] - record["start_ms"]) / 1000
                if not cleaner.audible(audio, duration):
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
