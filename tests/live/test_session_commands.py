import json

from conftest import minutes_content

from kb_meeting_agent.llm.fake import FakeProvider
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
