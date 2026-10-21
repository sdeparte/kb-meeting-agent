from datetime import date

from conftest import minutes_content

from kb_meeting_agent.agent.factcheck import Flag
from kb_meeting_agent.agent.minutes import (
    DecisionRecord,
    MinutesDraft,
    build_minutes_change,
    write_minutes,
)
from kb_meeting_agent.conventions import IndexConfig, MinutesConventions
from kb_meeting_agent.llm.fake import FakeProvider
from kb_meeting_agent.models import Segment


def seg(start, name, text):
    return Segment(name.lower(), name, start, start + 5, text)


async def test_write_minutes_summarizes_slices_then_synthesizes():
    strong = FakeProvider(
        {
            "SliceSummary": [{"summary": "Part one."}, {"summary": "Part two."}],
            "MinutesContent": [minutes_content("Weekly", "weekly")],
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
    _, system, user = strong.calls_for("MinutesContent")[0]
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


def test_build_minutes_change_adds_an_index_row():
    conventions = MinutesConventions(
        dir="reunions",
        index=IndexConfig(
            file="reunions/README.md",
            row="| {date} | [{title}]({filename}) | {participants} | `{path}` | {body} |",
        ),
    )
    change = build_minutes_change(
        conventions=conventions,
        template="# {title}",
        draft=MinutesDraft(title="Weekly sync", slug="weekly-sync", body="text"),
        meeting_date=date(2026, 10, 15),
        participants=["Alice", "Bob"],
        language="fr",
        index_content="# Réunions\n\n| Date | CR |\n|---|---|\n| 2026-10-08 | [A](a.md) |\n",
    )
    assert change.files["reunions/README.md"].endswith(
        "| 2026-10-08 | [A](a.md) |\n"
        "| 2026-10-15 | [Weekly sync](2026-10-15-weekly-sync.md) | Alice, Bob "
        "| `reunions/2026-10-15-weekly-sync.md` | {body} |\n"
    )
    without_file = build_minutes_change(
        conventions=conventions,
        template="# {title}",
        draft=MinutesDraft(title="Weekly sync", slug="weekly-sync", body="text"),
        meeting_date=date(2026, 10, 15),
        participants=["Alice"],
        language="fr",
        index_content=None,
    )
    assert list(without_file.files) == ["reunions/2026-10-15-weekly-sync.md"]


async def test_write_minutes_mentions_gaps():
    strong = FakeProvider(
        {
            "SliceSummary": [{"summary": "s"}],
            "MinutesContent": [minutes_content("W", "w")],
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
    user = strong.calls_for("MinutesContent")[0][2]
    assert "TRANSCRIPTION GAPS:\n- 00:05:00 to 00:06:10" in user


async def test_write_minutes_integrates_the_agent_interactions():
    strong = FakeProvider(
        {
            "SliceSummary": [{"summary": "s"}],
            "MinutesContent": [minutes_content("W", "w")],
        }
    )
    await write_minutes(
        strong,
        segments=[seg(0, "Alice", "hello")],
        decisions=[],
        flags=[],
        instructions="",
        language="fr",
        agent_label="Breach (IA)",
        interactions=[(65.0, "Alice asked Breach (IA): “Why?”; answer: “Because.”")],
    )
    _, system, user = strong.calls_for("MinutesContent")[0]
    assert "Breach (IA)" in system and "in the topic they belong to" in system
    assert "INTERACTIONS WITH Breach (IA):\n- [00:01:05] Alice asked Breach (IA)" in user


async def test_the_minutes_are_rendered_in_the_kb_language_without_empty_sections():
    content = minutes_content(
        "Point hebdo",
        "point-hebdo",
        agenda=["Cooldown"],
        topics=[
            {"title": "## Cooldown", "points": ["- Alice propose 30 s.", "Otis (IA) cite 45 s."]},
            {"title": "Vide", "points": []},
            {"title": "BLE", "points": ["* **Bob** veut le garder."]},
        ],
    )
    strong = FakeProvider({"SliceSummary": [{"summary": "s"}], "MinutesContent": [content]})
    draft = await write_minutes(
        strong,
        segments=[seg(0, "Alice", "on passe à 30")],
        decisions=[
            DecisionRecord("Cooldown à 30 s", "validated", "https://example.test/pull/1"),
            DecisionRecord("Garder le BLE", "kept", None),
            DecisionRecord("Abandonner le BLE", "ignored", None),
            DecisionRecord("Passer au QR code", "pending", None),
        ],
        flags=[Flag("cooldown", "Cooldown à 30 s", "contradicts", "`45`", "c.md#N", "", None)],
        instructions="",
        language="fr",
        gaps=[(300.0, 370.0)],
    )
    assert draft.title == "Point hebdo"
    assert draft.body == (
        "## Participants\n\n- Alice\n\n"
        "## Ordre du jour\n\n- Cooldown\n\n"
        "## Discussion\n\n### Cooldown\n\n- Alice propose 30 s.\n- Otis (IA) cite 45 s.\n\n"
        "### BLE\n\n- **Bob** veut le garder.\n\n"
        "## Décisions\n\n- Cooldown à 30 s (https://example.test/pull/1)\n"
        "- Garder le BLE (validée, pull request pas encore publiée)\n\n"
        "## Décisions en attente de validation\n\n- Passer au QR code\n\n"
        "## Décisions proposées non retenues\n\n- Abandonner le BLE\n\n"
        "## Contradictions avec la KB\n\n- Cooldown à 30 s — la KB dit “`45`” (`c.md#N`)\n\n"
        "## Trous de transcription\n\n- 00:05:00 → 00:06:10"
    )


async def test_the_summaries_name_the_assistant_and_leave_out_nicknames():
    strong = FakeProvider(
        {"SliceSummary": [{"summary": "s"}], "MinutesContent": [minutes_content("W", "w")]}
    )
    await write_minutes(
        strong,
        segments=[seg(0, "Alice", "hello")],
        decisions=[],
        flags=[],
        instructions="",
        language="fr",
        agent_label="Otis (IA)",
    )
    for system in (
        strong.calls_for("SliceSummary")[0][1],
        strong.calls_for("MinutesContent")[0][1],
    ):
        assert "the AI assistant Otis (IA)" in system and "nickname" in system
