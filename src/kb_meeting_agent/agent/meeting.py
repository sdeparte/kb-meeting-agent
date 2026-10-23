from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Sequence
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any, Literal

from kb_meeting_agent.agent.answering import answer_question
from kb_meeting_agent.agent.decisions import (
    INDEX_ROWS_FILE,
    Change,
    DecisionDraft,
    build_decision_change,
    draft_decision,
    existing_numbers,
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
from kb_meeting_agent.config import KNOWLEDGE_BASE, InterventionLevel
from kb_meeting_agent.conventions import IndexConfig
from kb_meeting_agent.kb.quote import quote_exists
from kb_meeting_agent.llm.base import (
    LLMConfigError,
    LLMError,
    LLMInvalidOutput,
    LLMProvider,
    LLMUnavailable,
)
from kb_meeting_agent.models import Segment
from kb_meeting_agent.ports import (
    BranchChangedError,
    Button,
    KnowledgeBase,
    Modal,
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
    agent_name: str = "agent"
    agent_aliases: list[str] = field(default_factory=list)
    level: InterventionLevel = "contradictions"
    contradiction_min_confidence: float = 0.8
    context_min_interval_s: float = 300
    stale_page_days: int = 60
    extraction_interval_s: float = 30
    window_s: float = 150
    summary_interval_s: float = 300
    meeting_date: date = field(default_factory=date.today)

    @property
    def agent_names(self) -> list[str]:
        return [self.agent_name, *self.agent_aliases]


@dataclass(frozen=True)
class Interaction:
    """One exchange with the agent, for the minutes: who asked it what, what it did."""

    at: float  # seconds since the meeting started
    text: str


@dataclass
class PendingDecision:
    id: str
    statement: str
    excerpt: tuple[Segment, ...]
    anchored: bool
    state: Literal["pending", "validated", "ignored", "kept"] = "pending"
    pr: PrRef | None = None
    publication: dict[str, Any] | None = None


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
        self.previous_level: InterventionLevel = settings.level  # what "as before" goes back to
        self.decisions: dict[str, PendingDecision] = {}
        self.flags: list[Flag] = []
        self._flagged_subjects: set[str] = set()
        self._flagged_lines: set[tuple[str, str]] = set()
        self._reserved_numbers: set[int] = set()
        self._summary = ""
        self._last_extraction_end = 0.0
        self._latest_end = 0.0
        self._extracted = 0  # transcript segments already given to the extraction
        self._last_summary_end = 0.0
        self._last_context_at: float | None = None
        self._paused = False
        self._reported_errors: set[str] = set()
        self._thread: str | None = None  # the announcement the agent's messages answer
        self.interactions: list[Interaction] = []

    @property
    def _lang(self) -> str:
        return self.kb.conventions.language

    @property
    def _label(self) -> str:
        """The agent's name as participants and the minutes see it, e.g. "Breach (AI)"."""
        return t(self._lang, "agent_label", name=self.settings.agent_name)

    def _record(self, key: str, **values: object) -> None:
        """Keep an exchange for the minutes, in the KB's language: the minutes model copies it."""
        text = t(self._lang, f"record_{key}", agent=self._label, **values)
        self.interactions.append(Interaction(self._latest_end, text))

    async def _say(self, text: str, buttons: tuple[Button, ...] = ()) -> str:
        return await self.sink.send(OutMessage(text=text, buttons=buttons, reply_to=self._thread))

    @asynccontextmanager
    async def _announce(self, key: str, **values: object) -> AsyncIterator[None]:
        """Say what the agent is about to do, at once: answering takes a while, and silence
        reads as not heard. What it says until it is done answers that message."""
        ref = await self._say(t(self._lang, key, **values))
        previous, self._thread = self._thread, ref
        try:
            yield
        except Exception as exc:
            # never leave it unanswered
            key = "announce_failed" if isinstance(exc, LLMError) else "announce_error"
            await self._say(t(self._lang, key))
            raise  # _guard still pauses the checks if the model is down
        finally:
            self._thread = previous

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
        self._latest_end = max(self._latest_end, segment.end)
        if is_addressed(segment.text, self.settings.agent_names):
            await self._guard(self._handle_addressed(segment))
        if self._latest_end - self._last_extraction_end >= self.settings.extraction_interval_s:
            await self._extract()

    async def flush(self) -> None:
        if self._extracted < len(self.transcript.all()):
            await self._extract()

    async def _extract(self) -> None:
        # Live transcription finishes out of order across speakers: extract every segment
        # not seen yet, whatever its time, rather than a time range.
        segments = self.transcript.all()
        new = segments[self._extracted :]
        self._extracted = len(segments)
        self._last_extraction_end = self._latest_end
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
        self._record("proposed", statement=candidate.statement)
        edit = Modal(
            title=t(self._lang, "edit_title"),
            label=t(self._lang, "edit_label"),
            value=candidate.statement,
        )
        buttons = (
            Button(f"decision:{decision_id}:validate", t(self._lang, "button_validate")),
            Button(f"decision:{decision_id}:edit", t(self._lang, "button_edit"), modal=edit),
            Button(f"decision:{decision_id}:ignore", t(self._lang, "button_ignore")),
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
        self._record(
            "already_rejected" if flag.verdict == "already_rejected" else "contradiction",
            statement=flag.statement,
            quote=_one_line(flag.quote),
            anchor=flag.anchor,
        )
        key = "already_rejected" if flag.verdict == "already_rejected" else "contradiction"
        text = t(self._lang, key, quote=flag.quote, anchor=flag.anchor, reason=flag.reason)
        if flag.stale_since:
            text += t(self._lang, "stale", date=flag.stale_since)
        await self._say(text)

    async def _offer_context(self, topic: str, now: float) -> None:
        last = self._last_context_at
        if last is not None and now - last < self.settings.context_min_interval_s:
            return
        results = await self.kb.search(topic, k=1, only_tags=(KNOWLEDGE_BASE,))
        if results:
            self._last_context_at = now
            self._record("context", anchor=results[0].anchor)
            await self._say(t(self._lang, "context", anchor=results[0].anchor))

    async def _handle_addressed(self, segment: Segment) -> None:
        context = format_segments(self.transcript.window(self.settings.window_s))
        intent = await classify_addressed(
            self.fast,
            names=self.settings.agent_names,
            context=context,
            utterance=segment.text,
            level=self.level,
            previous_level=self.previous_level,
            default_level=self.settings.level,
            language=self._lang,
        )
        if intent.kind == "question":
            question = intent.question or segment.text
            async with self._announce("announce_searching", question=question):
                text = await answer_question(
                    self.fast,
                    self.strong,
                    self.kb,
                    question=question,
                    context=context,
                    language=self._lang,
                )
                self._record_answer(segment.speaker_name, question, text)
                await self._say(text)
        elif intent.kind == "set_level" and intent.level in LEVELS:
            await self.set_level(intent.level, user=segment.speaker_name)
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

    async def on_modal(self, custom_id: str, value: str, user: str) -> None:
        parts = custom_id.split(":")
        if len(parts) == 3 and parts[0] == "decision" and parts[2] == "edit" and value.strip():
            await self.edit_decision(parts[1], value.strip(), user)

    async def set_level(
        self, level: InterventionLevel, announce: bool = True, user: str | None = None
    ) -> None:
        if level not in LEVELS:
            return
        if level != self.level:
            self.previous_level = self.level
        self.level = level
        self._record("level", user=user or t(self._lang, "someone"), level=level)
        if announce:
            await self._say(t(self._lang, "level_changed", level=level))

    async def ask(self, question: str, user: str | None = None) -> str:
        context = format_segments(self.transcript.window(self.settings.window_s))
        try:
            text = await answer_question(
                self.fast,
                self.strong,
                self.kb,
                question=question,
                context=context,
                language=self._lang,
            )
        except LLMError as exc:
            log.warning("answering failed: %s", exc)
            return t(self._lang, "checks_paused")
        self._record_answer(user or t(self._lang, "someone"), question, text)
        return text

    def _record_answer(self, user: str, question: str, answer: str) -> None:
        self._record("answer", user=user, question=_one_line(question), answer=_one_line(answer))

    async def edit_decision(self, decision_id: str, statement: str, user: str) -> None:
        decision = self.decisions.get(decision_id)
        if decision and decision.state == "pending":
            self._record("reworded", user=user, before=decision.statement, after=statement)
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
            self._record("dismissed", user=user, statement=decision.statement)
            await self._say(t(self._lang, "decision_ignored", user=user))

    async def _validate(self, decision: PendingDecision, user: str) -> None:
        async with self._announce("announce_validating", user=user, statement=decision.statement):
            await self._draft_and_publish(decision, user)

    async def _draft_and_publish(self, decision: PendingDecision, user: str) -> None:
        conventions = self.kb.conventions.decisions
        chunks = await self.kb.search(decision.statement, k=6)
        excerpt = format_segments(list(decision.excerpt))
        try:
            draft = await draft_decision(
                self.strong,
                statement=decision.statement,
                quote=excerpt,
                chunks=chunks,
                instructions=self.kb.instructions(),
                language=self._lang,
                scopes=conventions.scopes,
            )
        except LLMInvalidOutput as exc:
            log.warning("drafting the decision record failed: %s", exc)
            await self._say(t(self._lang, "decision_draft_failed"))
            return  # still pending: it can be validated again
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
        note = "" if decision.anchored else t(self._lang, "excerpt_unanchored")
        change = self._decision_change(draft, number, excerpt, user, note)
        pr = await self._open_pr(change)
        if isinstance(pr, Path):
            decision.state = "kept"
            self._record("validated_kept", user=user, statement=decision.statement)
            return
        if pr is None:
            return
        if number is not None:
            self._reserved_numbers.add(number)
        decision.state, decision.pr = "validated", pr
        self._record("validated", user=user, statement=decision.statement, url=pr.url)
        decision.publication = {
            "draft": draft.model_dump(),
            "number": number,
            "quote": excerpt,
            "validated_by": user,
            "excerpt_note": note,
        }
        await self._say(t(self._lang, "decision_published", user=user, url=pr.url))

    def _index_content(self, index: IndexConfig | None) -> str | None:
        return self.kb.read(index.file) if index and self.kb.exists(index.file) else None

    def _decision_change(
        self, draft: DecisionDraft, number: int | None, quote: str, user: str, note: str
    ) -> Change:
        conventions = self.kb.conventions.decisions
        return build_decision_change(
            conventions=conventions,
            template=self.kb.template("decision"),
            draft=draft,
            number=number,
            meeting_date=self.settings.meeting_date,
            quote=quote,
            validated_by=user,
            index_content=self._index_content(conventions.index),
            language=self._lang,
            excerpt_note=note,
        )

    async def refresh_decision_prs(self) -> None:
        """Rebuild each open decision PR on the current base (call after syncing the KB).

        Equivalent to a rebase without merge commits: the agent's branch is replaced by a
        single commit on the new base. A number taken on the base meanwhile is reported.
        """
        taken = existing_numbers(self.kb.list_files(self.kb.conventions.decisions.dir))
        for decision in self.decisions.values():
            pub = decision.publication
            if decision.state != "validated" or decision.pr is None or pub is None:
                continue
            try:
                if not await self.publisher.is_open(decision.pr):
                    continue
                if pub["number"] is not None and pub["number"] in taken:
                    await self._say(
                        t(
                            self._lang,
                            "decision_number_taken",
                            number=pub["number"],
                            url=decision.pr.url,
                        )
                    )
                    continue
                change = self._decision_change(
                    DecisionDraft.model_validate(pub["draft"]),
                    pub["number"],
                    pub["quote"],
                    pub["validated_by"],
                    pub["excerpt_note"],
                )
                head = await self.publisher.update_branch(
                    decision.pr.branch, change.files, change.title, decision.pr.head
                )
                decision.pr = replace(decision.pr, head=head)
            except BranchChangedError:
                await self._say(t(self._lang, "decision_branch_changed", url=decision.pr.url))
            except PublishError as exc:
                log.error("refreshing %s failed: %s", decision.pr.url, exc)
                await self._say(t(self._lang, "publish_failed", error=exc.public))

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
                if change.index_rows:
                    (kept / change.branch / INDEX_ROWS_FILE).write_text(
                        json.dumps(change.index_rows, ensure_ascii=False), encoding="utf-8"
                    )
            except (PublishError, OSError):
                log.exception("keeping %s (%s) locally failed", change.branch, change.title)
                await self._say(t(self._lang, "publish_failed", error=shown))
                return None
            log.warning("kept %s locally in %s", change.branch, kept)
            await self._say(t(self._lang, "kept_locally", error=shown))
            return kept

    async def end(
        self,
        segments: list[Segment] | None = None,
        gaps: Sequence[tuple[float, float]] = (),
    ) -> PrRef | None:
        await self.flush()
        segments = sorted(
            segments if segments is not None else self.transcript.all(), key=lambda s: s.start
        )
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
                gaps=list(gaps),
                agent_label=self._label,
                interactions=[(i.at, i.text) for i in self.interactions],
            )
        except LLMError as exc:
            log.exception("writing the minutes failed; transcript at %s", self.transcript.path)
            await self._say(t(self._lang, "minutes_failed", error=type(exc).__name__))
            return None
        participants = sorted({s.speaker_name for s in segments})
        conventions = self.kb.conventions.minutes
        change = build_minutes_change(
            conventions=conventions,
            template=self.kb.template("minutes"),
            draft=draft,
            meeting_date=self.settings.meeting_date,
            participants=participants,
            language=self._lang,
            index_content=self._index_content(conventions.index),
        )
        pr = await self._open_pr(change)
        if not isinstance(pr, PrRef):
            return None
        await self._say(t(self._lang, "minutes_published", url=pr.url))
        return pr

    def snapshot(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "previous_level": self.previous_level,
            "summary": self._summary,
            "extracted": self._extracted,
            "latest_end": self._latest_end,
            "last_extraction_end": self._last_extraction_end,
            "last_summary_end": self._last_summary_end,
            "last_context_at": self._last_context_at,
            "reserved_numbers": sorted(self._reserved_numbers),
            "flagged_subjects": sorted(self._flagged_subjects),
            "flagged_lines": [list(line) for line in sorted(self._flagged_lines)],
            "flags": [asdict(flag) for flag in self.flags],
            "interactions": [asdict(i) for i in self.interactions],
            "decisions": [
                {
                    "id": d.id,
                    "statement": d.statement,
                    "excerpt": [asdict(s) for s in d.excerpt],
                    "anchored": d.anchored,
                    "state": d.state,
                    "pr": asdict(d.pr) if d.pr else None,
                    "publication": d.publication,
                }
                for d in self.decisions.values()
            ],
        }

    def restore(self, state: dict[str, Any]) -> None:
        self.level = state["level"]
        self.previous_level = state.get("previous_level", self.level)
        self._summary = state["summary"]
        self._extracted = state["extracted"]
        self._latest_end = state["latest_end"]
        self._last_extraction_end = state["last_extraction_end"]
        self._last_summary_end = state["last_summary_end"]
        self._last_context_at = state["last_context_at"]
        self._reserved_numbers = set(state["reserved_numbers"])
        self._flagged_subjects = set(state["flagged_subjects"])
        self._flagged_lines = {tuple(line) for line in state["flagged_lines"]}
        self.flags = [Flag(**flag) for flag in state["flags"]]
        self.interactions = [Interaction(**i) for i in state.get("interactions", [])]
        self.decisions = {
            d["id"]: PendingDecision(
                id=d["id"],
                statement=d["statement"],
                excerpt=tuple(Segment(**s) for s in d["excerpt"]),
                anchored=d["anchored"],
                state=d["state"],
                pr=PrRef(**d["pr"]) if d["pr"] else None,
                publication=d["publication"],
            )
            for d in state["decisions"]
        }


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


def _one_line(text: str, limit: int = 300) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
