import json

import pytest
from conftest import KB_FILES, make_kb_repo, minutes_content

from kb_meeting_agent.live.audio import BYTES_PER_MS
from kb_meeting_agent.live.protocol import AudioFrame
from kb_meeting_agent.llm.fake import FakeProvider
from kb_meeting_agent.ports import OutMessage
from live.helpers import chat, command, speak

DECISION = {"statement": "Cooldown is 30 seconds", "quote": "bonjour à tous"}
MINUTES = {"MinutesContent": [minutes_content("Weekly", "weekly")]}


def deciding():
    return FakeProvider({"Extraction": [{"claims": [], "decisions": [DECISION], "topics": []}]})


async def propose(session):
    await session.on_event("message", chat("!start"))
    await speak(session, start=0, ms=31_000)
    await session.settle()


async def test_chat_start_uses_the_only_project(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!start"))
    assert session.meeting.project == "test"
    assert link.of("reply") == []  # a chat command is answered in the channel
    assert link.texts()[-1] == "Meeting started with the test project."


async def test_start_without_project_uses_the_only_project(make_session):
    session, *_ = make_session()
    await session.on_event("message", command("meeting_start"))
    assert session.meeting.project == "test"


async def test_chat_end_closes_the_meeting_like_the_slash_command(make_session):
    session, link, *_ = make_session(strong=FakeProvider(dict(MINUTES)))
    await session.on_event("message", chat("!start"))
    await speak(session)
    await session.on_event("message", chat("!fin"))
    assert session.meeting is None
    assert link.of("leave") == [{}]


async def test_chat_ask_is_answered_in_the_channel(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!start"))
    await session.on_event("message", chat("!ask What is the cooldown?"))
    await session.settle()
    assert link.of("reply") == []
    assert len(link.of("send")) >= 3  # notice, started, answer
    assert session.meeting.agent.acted


async def test_chat_lines_without_bang_are_ignored(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("start"))
    assert session.meeting is None and link.sent == []


async def test_unknown_chat_command_in_the_meeting_channel_gets_the_help(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!start"))
    await session.on_event("message", chat("!nope"))
    assert "!end" in link.texts()[-1]


async def test_unknown_chat_command_elsewhere_is_left_to_other_bots(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!play lofi", text_channel="t9"))
    assert link.sent == []
    await session.on_event("message", chat("!start"))
    sent = len(link.sent)
    await session.on_event("message", chat("!play lofi", voice="v9", text_channel="t9"))
    assert len(link.sent) == sent


async def test_help_is_answered_anywhere(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!help", text_channel="t9"))
    assert "!end" in link.texts()[-1]


async def test_chat_validate_publishes_like_the_button(make_session):
    session, link, clock, publisher = make_session(fast=deciding())
    await propose(session)
    await session.on_event("message", chat("!validate d1"))
    await session.settle()
    assert len(publisher.prs) == 1


async def test_chat_edit_rewords_then_publishes(make_session):
    session, link, clock, publisher = make_session(fast=deciding())
    await propose(session)
    await session.on_event("message", chat("!edit d1 Cooldown is 25 s"))
    await session.settle()
    assert len(publisher.prs) == 1
    assert session.meeting.agent.decisions["d1"].statement == "Cooldown is 25 s"


async def test_validate_of_an_unknown_decision_is_answered(make_session):
    session, link, clock, publisher = make_session(fast=deciding())
    await propose(session)
    await session.on_event("message", chat("!validate d9"))
    await session.settle()
    assert publisher.prs == []
    assert link.texts()[-1] == "No pending decision d9. Pending: d1."


async def test_a_decision_already_handled_is_no_longer_pending(make_session):
    session, link, clock, publisher = make_session(fast=deciding())
    await propose(session)
    await session.on_event("message", chat("!ignore d1"))
    await session.settle()
    await session.on_event("message", chat("!validate d1"))
    assert link.texts()[-1] == "No pending decision d1. Pending: none."


async def test_decision_ids_are_typed_in_any_case(make_session):
    session, link, clock, publisher = make_session(fast=deciding())
    await propose(session)
    await session.on_event("message", chat("!validate D1"))
    await session.settle()
    assert len(publisher.prs) == 1


async def test_a_proposed_decision_shows_its_id(make_session):
    session, link, *_ = make_session(fast=deciding())
    await propose(session)
    assert "Decision d1 detected: *Cooldown is 30 seconds*" in link.texts()


async def interrupted_meeting(make_session, **kwargs):
    """A meeting started in call v1, then the process dies: no close()."""
    first, *_ = make_session(**kwargs)
    await first.on_event("message", chat("!start"))
    await speak(first)
    await first.settle()
    return first.meeting


async def test_start_in_the_same_call_offers_to_resume_the_interrupted_meeting(make_session):
    await interrupted_meeting(make_session)
    second, link2, *_ = make_session()
    await second.on_event("message", chat("!start"))
    assert second.meeting is None
    assert link2.texts()[-1] == (
        "A meeting on the test project was interrupted in this call: type `!resume` to "
        "resume it, or `!start` again to start a new meeting."
    )


async def test_resume_after_the_offer_picks_up_the_interrupted_meeting(make_session):
    old = await interrupted_meeting(make_session)
    second, link2, *_ = make_session()
    await second.on_event("message", chat("!start"))
    await second.on_event("message", chat("!resume"))
    assert second.meeting.id == old.id
    assert link2.texts()[-1] == "Meeting resumed."
    assert link2.texts()[-2].startswith("This meeting is transcribed by Scribe")


async def test_start_again_after_the_offer_starts_afresh(make_session):
    old = await interrupted_meeting(make_session)
    second, *_ = make_session()
    await second.on_event("message", chat("!start"))
    await second.on_event("message", chat("!start", user=("u2", "Bob")))
    assert second.meeting.id != old.id


async def test_start_in_another_call_does_not_resume(make_session):
    first, *_ = make_session()
    await first.on_event("message", chat("!start"))
    old = first.meeting
    second, *_ = make_session()
    await second.on_event("message", chat("!start", voice="v2"))
    assert second.meeting.id != old.id
    state = json.loads((old.dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "active"


async def test_text_only_connector_gets_decisions_as_commands(make_session):
    session, link, *_ = make_session(fast=deciding())
    await session.on_event("connected", {"type": "hello", "capabilities": {"buttons": False}})
    await propose(session)
    proposal = link.of("send")[-1]
    assert proposal["buttons"] == []
    assert "!validate d1" in proposal["text"] and "!edit d1 <statement>" in proposal["text"]


async def test_chat_command_during_close_is_refused(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!start"))
    session.meeting.closing = True
    await session.on_event("message", chat("!ask anything"))
    assert link.texts()[-1] == "The meeting is already ending."


@pytest.fixture
def french_kb(tmp_path):
    settings = KB_FILES[".meeting-agent.yml"].replace("language: en", "language: fr")
    return str(make_kb_repo(tmp_path / "kb-fr", {**KB_FILES, ".meeting-agent.yml": settings}))


async def test_project_switch_before_anything_rebuilds_the_sources(make_session, french_kb):
    session, link, clock, publisher = make_session(second_kb=french_kb)
    await session.on_event("message", chat("!start"))
    await speak(session)
    await session.settle()
    meeting = session.meeting
    await session.on_event("message", chat("!project other"))
    assert session.meeting.project == "other" and session.meeting.id == meeting.id
    assert [s.text for s in session.meeting.agent.transcript.all()] == ["bonjour à tous"]
    assert publisher.closed
    state = json.loads((meeting.dir / "state.json").read_text(encoding="utf-8"))
    assert state["project"] == "other"


async def test_switch_to_a_kb_in_another_language(make_session, french_kb):
    session, link, *_ = make_session(second_kb=french_kb)
    await session.on_event("message", chat("!start"))
    await session.on_event("message", chat("!projet other"))
    assert "Cette réunion est transcrite" in link.texts()[-2]
    assert link.texts()[-1] == "Projet changé : other."


async def test_project_switch_after_a_decision_is_refused(make_session, french_kb):
    session, link, *_ = make_session(fast=deciding(), second_kb=french_kb)
    await propose(session)
    await session.on_event("message", chat("!project other"))
    assert session.meeting.project == "test"
    assert link.texts()[-1] == (
        "The project can no longer change: the agent has already spoken. Project: test."
    )


async def test_system_messages_do_not_lock_the_project(make_session, french_kb):
    session, link, *_ = make_session(second_kb=french_kb)
    await session.on_event("message", chat("!start"))
    await session.meeting.sink.send(OutMessage("Building the index of back…"))
    await session.on_event("message", chat("!project other"))
    assert session.meeting.project == "other"


async def test_switch_to_an_unknown_project(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!start"))
    await session.on_event("message", chat("!project nope"))
    assert link.texts()[-1] == "Unknown project. Available: test."


async def test_resume_after_a_switch_uses_the_new_project(make_session, french_kb):
    first, *_ = make_session(second_kb=french_kb)
    await first.on_event("message", chat("!start"))
    await first.on_event("message", chat("!project other"))
    second, *_ = make_session(second_kb=french_kb)
    await second.on_event("message", chat("!resume"))
    assert second.meeting.project == "other"


async def test_start_does_not_resume_a_meeting_from_another_day(make_session):
    first, *_ = make_session()
    await first.on_event("message", chat("!start"))
    old = first.meeting
    state_path = old.dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["meeting_date"] = "2020-01-01"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    second, *_ = make_session()
    await second.on_event("message", chat("!start"))
    assert second.meeting.id != old.id


async def test_speech_in_progress_survives_a_project_switch(make_session, french_kb):
    session, link, *_ = make_session(second_kb=french_kb)
    await session.on_event("message", chat("!start"))
    await session.on_event(
        "message", {"type": "utterance_start", "user_id": "u1", "speaker_name": "Alice", "t": 1_000}
    )
    await session.on_event("audio", AudioFrame("u1", 1_000, bytes(BYTES_PER_MS * 500)))
    await session.on_event("message", chat("!project other"))
    await session.on_event("audio", AudioFrame("u1", 1_500, bytes(BYTES_PER_MS * 500)))
    await session.on_event("message", {"type": "utterance_end", "user_id": "u1", "t": 2_000})
    await session.settle()
    records = (session.meeting.dir / "utterances.jsonl").read_text(encoding="utf-8")
    spans = [json.loads(line) for line in records.splitlines()]
    assert sum(r["end_ms"] - r["start_ms"] for r in spans) == 1_000


async def test_a_publisher_failing_to_close_does_not_stop_the_switch(make_session, french_kb):
    session, link, clock, publisher = make_session(second_kb=french_kb)
    await session.on_event("message", chat("!start"))

    async def broken():
        raise RuntimeError("network down")

    publisher.aclose = broken
    await session.on_event("message", chat("!project other"))
    assert session.meeting.project == "other"
    assert link.texts()[-1] == "Projet changé : other."


async def test_a_meeting_closed_during_the_switch_stays_closed(make_session, french_kb):
    session, link, *_ = make_session(strong=FakeProvider(dict(MINUTES)), second_kb=french_kb)
    await session.on_event("message", chat("!start"))
    sync = session._sync_or_close

    async def closed_meanwhile(sources):
        await sync(sources)
        await session.close()  # the auto-leave timer firing during the sync

    session._sync_or_close = closed_meanwhile
    await session.on_event("message", chat("!project other"))
    assert session.meeting is None


@pytest.mark.parametrize(
    "line", ["!project other", "!fin", "!level silent", "!validate d1", "!edit d1 Autre"]
)
async def test_meeting_commands_from_outside_the_meeting_are_refused(make_session, french_kb, line):
    session, link, clock, publisher = make_session(fast=deciding(), second_kb=french_kb)
    await propose(session)
    await session.on_event("message", chat(line, voice="v9", text_channel="t9"))
    await session.settle()
    assert link.texts()[-1] == (
        "Only the meeting's participants can do that: join its call or use its text channel."
    )
    assert session.meeting.project == "test" and publisher.prs == []


async def test_meeting_commands_from_its_text_channel_are_accepted(make_session):
    session, link, clock, publisher = make_session(fast=deciding())
    await propose(session)
    await session.on_event("message", chat("!validate d1", voice=None))
    await session.settle()
    assert len(publisher.prs) == 1


async def test_slash_commands_from_outside_the_meeting_are_refused_too(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", chat("!start"))
    msg = command("meeting_end", voice="v9")
    msg["text_channel_id"] = "t9"
    await session.on_event("message", msg)
    assert session.meeting is not None
    assert link.of("reply")[-1]["text"].startswith("Only the meeting's participants")


async def test_a_decision_proposed_while_switching_cancels_the_switch(make_session, french_kb):
    session, link, *_ = make_session(fast=deciding(), second_kb=french_kb)
    await session.on_event("message", chat("!start"))
    await speak(session, start=0, ms=31_000)  # still being transcribed: no settle
    await session.on_event("message", chat("!project other"))
    assert session.meeting.project == "test"
    assert link.texts()[-1].startswith("The project can no longer change")
    await session.settle()


async def test_start_naming_another_project_does_not_resume(make_session, french_kb):
    first, *_ = make_session(second_kb=french_kb)
    await first.on_event("message", chat("!start"))
    old = first.meeting
    second, *_ = make_session(second_kb=french_kb)
    await second.on_event("message", chat("!start other"))
    assert second.meeting.id != old.id and second.meeting.project == "other"
