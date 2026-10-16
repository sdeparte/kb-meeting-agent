from __future__ import annotations

import logging
import re
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from kb_meeting_agent.agent.answering import answer_question
from kb_meeting_agent.agent.decisions import (
    Change,
    build_decision_change,
    draft_decision,
    next_number,
)
from kb_meeting_agent.agent.detection import (
    Claim,
    DecisionCandidate,
    classify_addressed,
    extract_items,
    is_addressed,
    update_summary,
)
from kb_meeting_agent.agent.factcheck import Flag, check_claim
from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.minutes import DecisionRecord, build_minutes_change, write_minutes
from kb_meeting_agent.agent.prompting import format_segments
from kb_meeting_agent.agent.transcript import Transcript
from kb_meeting_agent.config import InterventionLevel
from kb_meeting_agent.kb.quote import quote_exists
from kb_meeting_agent.llm.base import LLMConfigError, LLMError, LLMProvider, LLMUnavailable
from kb_meeting_agent.models import Segment
from kb_meeting_agent.ports import (
    Button,
    KnowledgeBase,
    OutMessage,
    OutputSink,
    PrRef,
    Publisher,
    PublishError,
)
from kb_meeting_agent.publish.local import DryRunPublisher

log = logging.getLogger(__name__)

LEVELS: tuple[InterventionLevel, ...] = ("silent", "contradictions", "context")


@dataclass
class AgentSettings:
    agent_names: list[str]
    level: InterventionLevel = "contradictions"
    contradiction_min_confidence: float = 0.8
    context_min_interval_s: float = 300
    stale_page_days: int = 60
    extraction_interval_s: float = 30
    window_s: float = 150
    summary_interval_s: float = 300
    meeting_date: date = field(default_factory=date.today)


@dataclass
class PendingDecision:
    id: str
    statement: str
    excerpt: tuple[Segment, ...]
    anchored: bool
    state: Literal["pending", "validated", "ignored", "kept"] = "pending"
    pr: PrRef | None = None


class MeetingAgent:
    def __init__(
        self,
        *,
        kb: KnowledgeBase,
        fast: LLMProvider,
        strong: LLMProvider,
        publisher: Publisher,
        sink: OutputSink,
        transcript: Transcript,
        settings: AgentSettings,
    ) -> None:
        self.kb = kb
        self.fast = fast
        self.strong = strong
        self.publisher = publisher
        self.sink = sink
        self.transcript = transcript
        self.settings = settings
        self.level: InterventionLevel = settings.level
        self.decisions: dict[str, PendingDecision] = {}
        self.flags: list[Flag] = []
        self._flagged_subjects: set[str] = set()
        self._flagged_lines: set[tuple[str, str]] = set()
        self._reserved_numbers: set[int] = set()
        self._summary = ""
        self._last_extraction_end = 0.0
        self._last_summary_end = 0.0
        self._last_context_at: float | None = None
        self._paused = False
        self._reported_errors: set[str] = set()

    @property
    def _lang(self) -> str:
        return self.kb.conventions.language

    async def _say(self, text: str, buttons: tuple[Button, ...] = ()) -> None:
        await self.sink.send(OutMessage(text=text, buttons=buttons))

    async def _guard(self, step: Awaitable[None]) -> None:
        """Run a model-backed step; never let a model failure stop the meeting."""
        try:
            await step
        except LLMUnavailable as exc:
            log.warning("model unavailable: %s", exc)
            if not self._paused:
                self._paused = True
                await self._say(t(self._lang, "checks_paused"))
            return
        except LLMConfigError as exc:
            log.error("model rejected the request: %s", exc)
            shown = f"HTTP {exc.status}" if exc.status else type(exc).__name__
            if shown not in self._reported_errors:
                self._reported_errors.add(shown)
                await self._say(t(self._lang, "model_rejected", error=shown))
            return
        except LLMError as exc:
            log.warning("dropping a cycle after a model error: %s", exc)
        if self._paused:
            self._paused = False
            await self._say(t(self._lang, "checks_resumed"))

    async def on_segment(self, segment: Segment) -> None:
        self.transcript.append(segment)
        if is_addressed(segment.text, self.settings.agent_names):
            await self._guard(self._handle_addressed(segment))
        if segment.end - self._last_extraction_end >= self.settings.extraction_interval_s:
            await self._extract(until=segment.end)

    async def flush(self) -> None:
        segments = self.transcript.all()
        if segments and segments[-1].end > self._last_extraction_end:
            await self._extract(until=segments[-1].end)

    async def _extract(self, until: float) -> None:
        new = [s for s in self.transcript.all() if self._last_extraction_end < s.end <= until]
        self._last_extraction_end = until
        if new:
            await self._guard(self._process(new))

    async def _process(self, new: list[Segment]) -> None:
        if new[-1].end - self._last_summary_end >= self.settings.summary_interval_s:
            since = [s for s in self.transcript.all() if s.end > self._last_summary_end]
            self._summary = await update_summary(
                self.fast, summary=self._summary, new=format_segments(since), language=self._lang
            )
            self._last_summary_end = new[-1].end
        extraction = await extract_items(
            self.fast,
            summary=self._summary,
            context=format_segments(self.transcript.window(self.settings.window_s)),
            new=format_segments(new),
            language=self._lang,
        )
        for candidate in extraction.decisions:
            await self._propose(candidate, new)
        if self.level != "silent":
            for claim in extraction.claims:
                await self._check(claim)
        if self.level == "context":
            for topic in extraction.topics:
                await self._offer_context(topic, now=new[-1].end)

    async def _propose(self, candidate: DecisionCandidate, new: list[Segment]) -> None:
        # Tie the decision to real transcript lines: the PR quotes those, never the model's
        # string, and two extractions of the same lines yield a single proposal.
        matched = tuple(
            s
            for s in self.transcript.window(self.settings.window_s)
            if quote_exists(s.text, candidate.quote) or quote_exists(candidate.quote, s.text)
        )
        key = candidate.statement.casefold().strip()
        for existing in self.decisions.values():
            if existing.statement.casefold().strip() == key:
                return
            if (
                matched
                and existing.anchored
                and set(matched) & set(existing.excerpt)
                and _similar(existing.statement, candidate.statement)
            ):
                return
        decision_id = f"d{len(self.decisions) + 1}"
        self.decisions[decision_id] = PendingDecision(
            decision_id, candidate.statement, matched or tuple(new), anchored=bool(matched)
        )
        buttons = tuple(
            Button(f"decision:{decision_id}:{action}", t(self._lang, f"button_{action}"))
            for action in ("validate", "edit", "ignore")
        )
        await self._say(t(self._lang, "decision_detected", statement=candidate.statement), buttons)

    async def _check(self, claim: Claim) -> None:
        subject = claim.subject.casefold().strip()
        if subject in self._flagged_subjects:
            return
        flag = await check_claim(
            self.strong,
            self.kb,
            claim,
            threshold=self.settings.contradiction_min_confidence,
            stale_days=self.settings.stale_page_days,
            today=self.settings.meeting_date,
            language=self._lang,
        )
        if flag is None:
            return
        self._flagged_subjects.add(subject)
        if (flag.anchor, flag.quote) in self._flagged_lines:
            return
        self._flagged_lines.add((flag.anchor, flag.quote))
        self.flags.append(flag)
        key = "already_rejected" if flag.verdict == "already_rejected" else "contradiction"
        text = t(self._lang, key, quote=flag.quote, anchor=flag.anchor, reason=flag.reason)
        if flag.stale_since:
            text += t(self._lang, "stale", date=flag.stale_since)
        await self._say(text)

    async def _offer_context(self, topic: str, now: float) -> None:
        last = self._last_context_at
        if last is not None and now - last < self.settings.context_min_interval_s:
            return
        results = await self.kb.search(topic, k=1)
        if results:
            self._last_context_at = now
            await self._say(t(self._lang, "context", anchor=results[0].anchor))

    async def _handle_addressed(self, segment: Segment) -> None:
        context = format_segments(self.transcript.window(self.settings.window_s))
        intent = await classify_addressed(
            self.fast, names=self.settings.agent_names, context=context, utterance=segment.text
        )
        if intent.kind == "question":
            text = await answer_question(
                self.fast,
                self.strong,
                self.kb,
                question=intent.question or segment.text,
                context=context,
                language=self._lang,
            )
            await self._say(text)
        elif intent.kind == "set_level" and intent.level in LEVELS:
            self.level = intent.level
            await self._say(t(self._lang, "level_changed", level=intent.level))
        elif intent.kind in ("validate", "ignore"):
            pending = [d for d in self.decisions.values() if d.state == "pending"]
            if pending and intent.kind == "validate":
                await self._validate(pending[-1], segment.speaker_name)
            elif pending:
                await self.ignore_decision(pending[-1].id, segment.speaker_name)

    async def on_button(self, button_id: str, user: str) -> None:
        prefix, decision_id, action = button_id.split(":", 2)
        if prefix != "decision" or decision_id not in self.decisions:
            return
        if action == "validate":
            await self.validate_decision(decision_id, user)
        elif action == "ignore":
            await self.ignore_decision(decision_id, user)

    async def edit_decision(self, decision_id: str, statement: str, user: str) -> None:
        decision = self.decisions.get(decision_id)
        if decision and decision.state == "pending":
            decision.statement = statement
            await self.validate_decision(decision_id, user)

    async def validate_decision(self, decision_id: str, user: str) -> None:
        decision = self.decisions.get(decision_id)
        if decision and decision.state == "pending":
            await self._guard(self._validate(decision, user))

    async def ignore_decision(self, decision_id: str, user: str) -> None:
        decision = self.decisions.get(decision_id)
        if decision and decision.state == "pending":
            decision.state = "ignored"
            await self._say(t(self._lang, "decision_ignored", user=user))

    async def _validate(self, decision: PendingDecision, user: str) -> None:
        conventions = self.kb.conventions.decisions
        chunks = await self.kb.search(decision.statement, k=6)
        excerpt = format_segments(list(decision.excerpt))
        draft = await draft_decision(
            self.strong,
            statement=decision.statement,
            quote=excerpt,
            chunks=chunks,
            instructions=self.kb.instructions(),
            language=self._lang,
        )
        draft = draft.model_copy(
            update={"related_pages": [p for p in draft.related_pages if self.kb.exists(p.path)]}
        )
        number = None
        if "{number" in conventions.filename:
            try:
                open_paths = await self.publisher.open_pr_paths(conventions.dir.rstrip("/") + "/")
            except PublishError as exc:
                log.error("listing open pull requests failed: %s", exc)
                await self._say(t(self._lang, "publish_failed", error=exc.public))
                return
            number = next_number(
                self.kb.list_files(conventions.dir) + open_paths, self._reserved_numbers
            )
        index_file = conventions.index.file if conventions.index else None
        change = build_decision_change(
            conventions=conventions,
            template=self.kb.template("decision"),
            draft=draft,
            number=number,
            meeting_date=self.settings.meeting_date,
            quote=excerpt,
            validated_by=user,
            index_content=self.kb.read(index_file)
            if index_file and self.kb.exists(index_file)
            else None,
            language=self._lang,
            excerpt_note="" if decision.anchored else t(self._lang, "excerpt_unanchored"),
        )
        pr = await self._open_pr(change)
        if isinstance(pr, Path):
            decision.state = "kept"
            return
        if pr is None:
            return
        if number is not None:
            self._reserved_numbers.add(number)
        decision.state, decision.pr = "validated", pr
        await self._say(t(self._lang, "decision_published", user=user, url=pr.url))

    async def _open_pr(self, change: Change) -> PrRef | Path | None:
        """Open the PR; on any failure keep the files locally so the work is not lost.

        Returns the PR, the local folder the files were kept in, or None if both failed.
        """
        try:
            return await self.publisher.open_pr(
                change.branch, change.files, change.title, change.body
            )
        except Exception as exc:  # noqa: BLE001 - a publication must never lose the work
            log.exception("publishing %s failed", change.branch)
            # Participants only see a short summary; hosts, URLs, paths and response bodies
            # stay in the log.
            shown = exc.public if isinstance(exc, PublishError) else type(exc).__name__
            kept = self.transcript.path.parent / "unpublished"
            try:
                await DryRunPublisher(kept).open_pr(
                    change.branch, change.files, change.title, change.body
                )
            except (PublishError, OSError):
                log.exception("keeping %s (%s) locally failed", change.branch, change.title)
                await self._say(t(self._lang, "publish_failed", error=shown))
                return None
            log.warning("kept %s locally in %s", change.branch, kept)
            await self._say(t(self._lang, "kept_locally", error=shown))
            return kept

    async def end(self) -> PrRef | None:
        await self.flush()
        segments = self.transcript.all()
        if not segments:
            return None
        try:
            draft = await write_minutes(
                self.strong,
                segments=segments,
                decisions=[
                    DecisionRecord(d.statement, d.state, d.pr.url if d.pr else None)
                    for d in self.decisions.values()
                ],
                flags=self.flags,
                instructions=self.kb.instructions(),
                language=self._lang,
            )
        except LLMError as exc:
            log.exception("writing the minutes failed; transcript at %s", self.transcript.path)
            await self._say(t(self._lang, "minutes_failed", error=type(exc).__name__))
            return None
        participants = sorted({s.speaker_name for s in segments})
        change = build_minutes_change(
            conventions=self.kb.conventions.minutes,
            template=self.kb.template("minutes"),
            draft=draft,
            meeting_date=self.settings.meeting_date,
            participants=participants,
            language=self._lang,
        )
        pr = await self._open_pr(change)
        if not isinstance(pr, PrRef):
            return None
        await self._say(t(self._lang, "minutes_published", url=pr.url))
        return pr


_STOPWORDS = frozenset(
    "the and are for from that this with will our you les des une est sont pour avec dans "
    "que qui sur par pas plus".split()
)


def _content_words(text: str) -> set[str]:
    words = re.findall(r"\w+", text.casefold())
    return {w for w in words if (len(w) >= 3 or w.isdigit()) and w not in _STOPWORDS}


def _similar(a: str, b: str) -> bool:
    """Two statements about the same thing share most of the shorter one's content words."""
    left, right = _content_words(a), _content_words(b)
    if not left or not right:
        return False
    return len(left & right) / min(len(left), len(right)) >= 0.5
