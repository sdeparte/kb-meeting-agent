from datetime import date

from kb_meeting_agent.agent.factcheck import Flag
from kb_meeting_agent.agent.minutes import (
    DecisionRecord,
    MinutesDraft,
    build_minutes_change,
    write_minutes,
)
from kb_meeting_agent.conventions import MinutesConventions
from kb_meeting_agent.llm.fake import FakeProvider
from kb_meeting_agent.models import Segment


def seg(start, name, text):
    return Segment(name.lower(), name, start, start + 5, text)


async def test_write_minutes_summarizes_slices_then_synthesizes():
    strong = FakeProvider(
        {
            "SliceSummary": [{"summary": "Part one."}, {"summary": "Part two."}],
            "MinutesDraft": [{"title": "Weekly", "slug": "weekly", "body": "## Decisions\n..."}],
        }
    )
    draft = await write_minutes(
        strong,
        segments=[seg(0, "Alice", "hello"), seg(700, "Bob", "cooldown 30")],
        decisions=[
            DecisionRecord("Cooldown is 30 s", "validated", "https://example.test/pull/1"),
            DecisionRecord("Drop BLE", "ignored", None),
        ],
        flags=[
            Flag(
                "cooldown",
                "Cooldown is 30 s",
                "contradicts",
                "`45`",
                "c.md#N",
                "Default is 45.",
                None,
            )
        ],
        instructions="Write in English.",
        language="en",
    )
    assert draft.title == "Weekly"
    assert len(strong.calls_for("SliceSummary")) == 2
    _, system, user = strong.calls_for("MinutesDraft")[0]
    assert "Write in English." in system
    assert "Alice, Bob" in user
    assert "https://example.test/pull/1" in user
    assert "Drop BLE" in user and "ignored" in user
    assert "Default is 45." in user
    assert "Part one." in user and "Part two." in user


def test_build_minutes_change():
    change = build_minutes_change(
        conventions=MinutesConventions(dir="reunions"),
        template="# {title}\n\n{participants}\n\n{body}",
        draft=MinutesDraft(title="Weekly sync", slug="weekly sync", body="## Points\n\nText"),
        meeting_date=date(2026, 10, 15),
        participants=["Alice", "Bob"],
        language="fr",
    )
    assert change.branch == "meetings/2026-10-15-weekly-sync"
    assert change.files == {
        "reunions/2026-10-15-weekly-sync.md": "# Weekly sync\n\nAlice, Bob\n\n## Points\n\nText\n"
    }
    assert change.title == "Compte rendu : Weekly sync"


async def test_write_minutes_mentions_gaps():
    strong = FakeProvider(
        {
            "SliceSummary": [{"summary": "s"}],
            "MinutesDraft": [{"title": "W", "slug": "w", "body": "x"}],
        }
    )
    await write_minutes(
        strong,
        segments=[seg(0, "Alice", "hello")],
        decisions=[],
        flags=[],
        instructions="",
        language="en",
        gaps=[(300.0, 370.0)],
    )
    user = strong.calls_for("MinutesDraft")[0][2]
    assert "TRANSCRIPTION GAPS:\n- 00:05:00 to 00:06:10" in user
