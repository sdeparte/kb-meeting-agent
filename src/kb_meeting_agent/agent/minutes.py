from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import groupby

from kb_meeting_agent.agent.decisions import Change, added_rows, index_files, slugify
from kb_meeting_agent.agent.factcheck import Flag
from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.prompting import format_segments, format_timestamp
from kb_meeting_agent.conventions import MinutesConventions, render_template
from kb_meeting_agent.llm.base import LLMProvider, Schema, complete
from kb_meeting_agent.models import Segment


@dataclass(frozen=True)
class DecisionRecord:
    statement: str
    state: str
    pr_url: str | None


class SliceSummary(Schema):
    summary: str


@dataclass(frozen=True)
class MinutesDraft:
    title: str
    slug: str
    body: str


class Topic(Schema):
    title: str
    points: list[str]


class MinutesContent(Schema):
    title: str
    slug: str
    agenda: list[str]
    topics: list[Topic]
    action_items: list[str]
    open_questions: list[str]


PEOPLE_RULE = """Name people only by their speaker names, and the AI assistant {agent}. Never replace "he", "she" or "it" by a nickname or a remark someone made about them. Leave out jokes, teasing and remarks about people that are not about the meeting's subjects."""

SLICE_SYSTEM = """Summarize this part of a meeting transcript in language "{language}": points discussed, who said what when it matters, open questions.
{people}
Factual, no invention, at most 250 words."""

MINUTES_SYSTEM = """You write the detailed minutes of a meeting for a knowledge base, following the KB's conventions below.
Use only the material provided: attribute each point to who said it and never add details, intents or interpretations the transcript does not state. The transcript is automatic: leave out isolated words that carry nothing (a lone "thank you", an unknown word) instead of narrating them.
{people}
Fill the fields; the decisions, the KB contradictions and the transcription gaps are listed apart from them, so do not repeat them as such:
- `agenda`: the subjects of the meeting, inferred, a few words each.
- `topics`: one per subject discussed, with a short `title` and its `points`, each one sentence saying who said or asked what.
- `action_items`: what someone will do, with the owner when stated.
- `open_questions`: questions left unanswered.
Plain sentences: no Markdown headings or bullets. Use empty lists when nothing qualifies.
The meeting has an AI assistant, {agent}. Put the interactions with it in the topic they belong to (who asked it what, what it answered or pointed out, which of its proposals were validated or dismissed), always naming it {agent}.
`title` is short; `slug` is kebab-case ASCII. Write in language "{language}".

KB CONVENTIONS:
{instructions}"""


async def write_minutes(
    strong: LLMProvider,
    *,
    segments: list[Segment],
    decisions: list[DecisionRecord],
    flags: list[Flag],
    instructions: str,
    language: str,
    slice_seconds: float = 600,
    gaps: Sequence[tuple[float, float]] = (),
    agent_label: str = "the assistant",
    interactions: Sequence[tuple[float, str]] = (),
) -> MinutesDraft:
    summaries: list[str] = []
    for slice_index, part in groupby(segments, key=lambda s: int(s.start // slice_seconds)):
        result = await complete(
            strong,
            SLICE_SYSTEM.format(language=language, people=PEOPLE_RULE.format(agent=agent_label)),
            format_segments(list(part)),
            SliceSummary,
        )
        summaries.append(
            f"### From {format_timestamp(slice_index * slice_seconds)}\n{result.summary}"
        )
    participants = sorted({s.speaker_name for s in segments})
    decision_lines = [
        f"- [{record.state}] {record.statement}" + (f" — {record.pr_url}" if record.pr_url else "")
        for record in decisions
    ]
    flag_lines = [
        f"- {flag.statement} → {flag.verdict}: “{flag.quote}” ({flag.anchor}). {flag.reason}"
        for flag in flags
    ]
    gap_lines = [f"- {format_timestamp(start)} to {format_timestamp(end)}" for start, end in gaps]
    user = (
        f"PARTICIPANTS: {', '.join(participants)}\n\n"
        f"PART SUMMARIES:\n" + "\n\n".join(summaries) + "\n\n"
        "DECISIONS:\n" + ("\n".join(decision_lines) or "(none)") + "\n\n"
        "KB CONTRADICTIONS RAISED:\n" + ("\n".join(flag_lines) or "(none)") + "\n\n"
        "TRANSCRIPTION GAPS:\n" + ("\n".join(gap_lines) or "(none)") + "\n\n"
        f"INTERACTIONS WITH {agent_label}:\n"
        + ("\n".join(f"- [{format_timestamp(at)}] {line}" for at, line in interactions) or "(none)")
    )
    system = MINUTES_SYSTEM.format(
        language=language,
        instructions=instructions or "(none)",
        agent=agent_label,
        people=PEOPLE_RULE.format(agent=agent_label),
    )
    content = await complete(strong, system, user, MinutesContent)
    body = render_minutes(
        content,
        participants=participants,
        decisions=decisions,
        flags=flags,
        gaps=gaps,
        language=language,
    )
    return MinutesDraft(title=content.title, slug=content.slug, body=body)


def render_minutes(
    content: MinutesContent,
    *,
    participants: list[str],
    decisions: Sequence[DecisionRecord],
    flags: Sequence[Flag],
    gaps: Sequence[tuple[float, float]],
    language: str,
) -> str:
    """The minutes' Markdown: sections and headings in the KB's language, written here rather
    than by the model, which a small one gets wrong (English headings, "(none)" sections)."""
    retained = [d for d in decisions if d.state in ("validated", "kept")]
    dropped = [d for d in decisions if d.state not in ("validated", "kept")]
    sections: list[tuple[str, list[str]]] = [
        ("minutes_participants", _bullets(participants)),
        ("minutes_agenda", _bullets(content.agenda)),
        (
            "minutes_discussion",
            [
                "\n\n".join(
                    f"### {_plain(topic.title)}\n\n" + "\n".join(_bullets(topic.points))
                    for topic in content.topics
                    if _plain(topic.title) and _bullets(topic.points)
                )
            ],
        ),
        (
            "minutes_decisions",
            [
                f"- {d.statement} ({d.pr_url})"
                if d.pr_url
                else f"- {d.statement} ({t(language, 'minutes_decision_kept')})"
                for d in retained
            ],
        ),
        ("minutes_not_retained", [f"- {d.statement}" for d in dropped]),
        (
            "minutes_contradictions",
            [
                f"- {flag.statement} — {t(language, _VERDICTS.get(flag.verdict, 'minutes_contradicts'))} "
                f"“{' '.join(flag.quote.split())}” (`{flag.anchor}`)"
                for flag in flags
            ],
        ),
        ("minutes_actions", _bullets(content.action_items)),
        ("minutes_questions", _bullets(content.open_questions)),
        (
            "minutes_gaps",
            [f"- {format_timestamp(start)} → {format_timestamp(end)}" for start, end in gaps],
        ),
    ]
    return "\n\n".join(
        f"## {t(language, key)}\n\n" + "\n".join(lines) for key, lines in sections if any(lines)
    )


_VERDICTS = {"already_rejected": "minutes_already_rejected"}


_MARKERS = re.compile(r"^(?:(?:#+|[-*•])\s+)+")  # "## ", "- ", "* ", but not "**bold**"


def _plain(text: str) -> str:
    """One line without the Markdown a model adds anyway: heading marks, bullets."""
    return _MARKERS.sub("", " ".join(text.split()))


def _bullets(items: Sequence[str]) -> list[str]:
    return [f"- {line}" for item in items if (line := _plain(item))]


def build_minutes_change(
    *,
    conventions: MinutesConventions,
    template: str,
    draft: MinutesDraft,
    meeting_date: date,
    participants: list[str],
    language: str,
    index_content: str | None = None,
) -> Change:
    values: dict[str, object] = {
        "title": draft.title,
        "slug": slugify(draft.slug or draft.title),
        "date": meeting_date.isoformat(),
        "participants": ", ".join(participants),
        "body": draft.body,
    }
    filename = render_template(conventions.filename, values)
    path = f"{conventions.dir.rstrip('/')}/{filename}"
    files = {path: render_template(template, values).rstrip() + "\n"}
    row_values = {key: value for key, value in values.items() if key != "body"}
    row_values |= {"filename": filename, "path": path}
    files |= index_files(conventions.index, index_content, row_values)
    return Change(
        branch=render_template(conventions.branch, values),
        files=files,
        title=t(language, "minutes_pr_title", title=draft.title),
        body=t(
            language,
            "minutes_pr_body",
            date=meeting_date.isoformat(),
            participants=", ".join(participants),
        ),
        index_rows=added_rows(conventions.index, files, row_values),
    )
