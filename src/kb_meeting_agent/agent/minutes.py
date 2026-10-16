from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import groupby

from kb_meeting_agent.agent.decisions import Change, slugify
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


class MinutesDraft(Schema):
    title: str
    slug: str
    body: str


SLICE_SYSTEM = """Summarize this part of a meeting transcript in language "{language}": points discussed, who said what when it matters, open questions.
Factual, no invention, at most 250 words."""

MINUTES_SYSTEM = """You write the detailed minutes of a meeting for a knowledge base, following the KB's conventions below.
Use only the material provided. `body` is Markdown with level-2 headings for: participants, agenda (inferred), discussion (one sub-section per topic), decisions (link each validated decision to its pull request URL), decisions proposed but not retained, contradictions with the KB that were raised, action items (with owner when stated), open questions. Omit a section only when it has no content.
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
) -> MinutesDraft:
    summaries: list[str] = []
    for slice_index, part in groupby(segments, key=lambda s: int(s.start // slice_seconds)):
        result = await complete(
            strong,
            SLICE_SYSTEM.format(language=language),
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
    user = (
        f"PARTICIPANTS: {', '.join(participants)}\n\n"
        f"PART SUMMARIES:\n" + "\n\n".join(summaries) + "\n\n"
        "DECISIONS:\n" + ("\n".join(decision_lines) or "(none)") + "\n\n"
        "KB CONTRADICTIONS RAISED:\n" + ("\n".join(flag_lines) or "(none)")
    )
    system = MINUTES_SYSTEM.format(language=language, instructions=instructions or "(none)")
    return await complete(strong, system, user, MinutesDraft)


def build_minutes_change(
    *,
    conventions: MinutesConventions,
    template: str,
    draft: MinutesDraft,
    meeting_date: date,
    participants: list[str],
    language: str,
) -> Change:
    values: dict[str, object] = {
        "title": draft.title,
        "slug": slugify(draft.slug or draft.title),
        "date": meeting_date.isoformat(),
        "participants": ", ".join(participants),
        "body": draft.body,
    }
    path = f"{conventions.dir.rstrip('/')}/{render_template(conventions.filename, values)}"
    return Change(
        branch=render_template(conventions.branch, values),
        files={path: render_template(template, values).rstrip() + "\n"},
        title=t(language, "minutes_pr_title", title=draft.title),
        body=t(
            language,
            "minutes_pr_body",
            date=meeting_date.isoformat(),
            participants=", ".join(participants),
        ),
    )
