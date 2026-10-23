import asyncio
import json

from kb_meeting_agent.live.audio import BYTES_PER_MS
from kb_meeting_agent.live.protocol import AudioFrame
from kb_meeting_agent.live.session import ConnectorSink
from kb_meeting_agent.llm.fake import FakeProvider
from kb_meeting_agent.ports import OutMessage
from kb_meeting_agent.transcription.fake import FakeTranscriber
from live.helpers import FakeLink, command, speak


async def start(session, **options):
    await session.on_event("message", command("meeting_start", project="test", **options))


async def test_start_joins_posts_the_notice_and_replies(make_session):
    session, link, clock, _ = make_session()
    await start(session)
    assert link.of("join") == [{"voice_channel_id": "v1", "text_channel_id": "t1"}]
    assert "acme/kb" in link.texts()[0] and "/meeting optout" in link.texts()[0]
    assert link.of("reply")[-1]["text"] == "Meeting started with the test project."
    state = json.loads((session.meeting.dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "active" and state["project"] == "test"


async def test_start_requires_a_voice_channel_and_a_known_project(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", command("meeting_start", voice=None, project="test"))
    await session.on_event("message", command("meeting_start", interaction="i2", project="nope"))
    replies = [r["text"] for r in link.of("reply")]
    assert replies == ["Join a voice channel first.", "Unknown project. Available: test."]
    assert session.meeting is None


async def test_second_start_is_refused(make_session):
    session, link, *_ = make_session()
    await start(session)
    await session.on_event("message", command("meeting_start", interaction="i2", project="test"))
    assert link.of("reply")[-1]["text"] == "A meeting is already running."


async def test_speech_reaches_the_transcript_with_meeting_times(make_session):
    session, link, clock, _ = make_session()
    await start(session)
    await speak(session, start=1_000, ms=1_000)
    await session.settle()
    [segment] = session.meeting.agent.transcript.all()
    assert (segment.speaker_name, segment.start, segment.end, segment.text) == (
        "Alice",
        1.0,
        2.0,
        "bonjour à tous",
    )
    records = (session.meeting.dir / "utterances.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(records[0])["file"] == "00000-u1.wav"


async def test_optout_stops_transcribing_that_speaker(make_session):
    session, link, *_ = make_session()
    await start(session)
    await session.on_event(
        "message", command("meeting_optout", interaction="i2", user=("u2", "Bob"))
    )
    await speak(session, user="u2", name="Bob")
    await session.settle()
    assert session.meeting.agent.transcript.all() == []
    assert link.of("optout") == [{"user_id": "u2"}]
    assert link.of("reply")[-1]["text"].startswith("Your voice is no longer transcribed")


async def test_buttons_and_modals_reach_the_agent(make_session):
    decision = {"statement": "Cooldown is 30 seconds", "quote": "bonjour à tous"}
    fast = FakeProvider({"Extraction": [{"claims": [], "decisions": [decision], "topics": []}]})
    session, link, clock, publisher = make_session(fast=fast)
    await start(session)
    await speak(session, start=0, ms=31_000)
    await session.settle()
    proposal = link.of("send")[-1]
    assert proposal["buttons"][1]["modal"]["value"] == "Cooldown is 30 seconds"
    await session.on_event(
        "message",
        {
            "type": "modal_submit",
            "custom_id": "decision:d1:edit",
            "value": "Cooldown is 25 s",
            "user": {"id": "u1", "name": "Alice"},
        },
    )
    await session.settle()
    assert len(publisher.prs) == 1


async def test_ask_and_level_commands(make_session):
    session, link, *_ = make_session()
    await start(session)
    await session.on_event(
        "message", command("ask", interaction="i2", question="What is the cooldown?")
    )
    await session.on_event("message", command("meeting_level", interaction="i3", level="silent"))
    await session.settle()
    replies = {r["interaction_id"]: r["text"] for r in link.of("reply")}
    assert replies["i2"] == "The KB does not cover this point."
    assert replies["i3"] == "Intervention level: silent."
    assert session.meeting.agent.level == "silent"


async def test_commands_need_a_meeting(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", command("meeting_end"))
    await session.on_event("message", command("bogus", interaction="i2"))
    assert [r["text"] for r in link.of("reply")] == ["No meeting is running.", "Unknown command."]


async def test_bots_do_not_keep_the_meeting_alive(make_session):
    session, link, *_ = make_session()
    await start(session)
    await session.on_event(
        "message", {"type": "members", "members": [{"id": "bot", "name": "Scribe", "bot": True}]}
    )
    await asyncio.sleep(0.2)
    assert session.meeting is None
    assert link.of("leave") == [{}]


async def test_member_returning_cancels_auto_leave(make_session):
    session, link, *_ = make_session()
    await start(session)
    await session.on_event("message", {"type": "members", "members": []})
    await session.on_event(
        "message", {"type": "members", "members": [{"id": "u1", "name": "Alice", "bot": False}]}
    )
    await asyncio.sleep(0.2)
    assert session.meeting is not None


async def test_transcription_lag_is_announced_once(make_session):
    session, link, clock, _ = make_session(transcription_lag_alert_seconds=5)
    await start(session)
    clock.now = 60_000
    await speak(session, start=1_000)
    await speak(session, start=3_000)
    await session.settle()
    assert sum("behind" in text for text in link.texts()) == 1


async def test_connector_restart_rejoins_and_records_a_gap(make_session):
    session, link, clock, _ = make_session()
    await start(session)
    clock.now = 60_000
    await session.on_event("disconnected", None)
    clock.now = 75_000
    await session.on_event("connected", {"type": "hello"})
    assert len(link.of("join")) == 2
    await session.on_event("message", {"type": "voice_state", "status": "ready"})
    assert link.texts()[-1] == "Audio was interrupted from 00:01:00 to 00:01:15."
    assert session.meeting.gaps == [[60.0, 75.0]]


async def test_stats_are_logged_to_the_meeting_folder(make_session):
    session, link, *_ = make_session()
    await start(session)
    await session.on_event("message", {"type": "stats", "decrypt_errors": 0, "users": []})
    lines = (session.meeting.dir / "stats.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["decrypt_errors"] == 0


async def test_join_is_retried_until_the_voice_is_ready(make_session):
    session, link, *_ = make_session()
    session.join_retry_s = 0.05
    await start(session)
    await asyncio.sleep(0.3)
    assert len(link.of("join")) >= 3
    await session.on_event("message", {"type": "voice_state", "status": "ready"})
    joins = len(link.of("join"))
    await asyncio.sleep(0.3)
    assert len(link.of("join")) == joins
    await session.on_event("message", {"type": "voice_state", "status": "lost"})
    await asyncio.sleep(0.3)
    assert len(link.of("join")) > joins


async def test_connector_crash_closes_open_utterances(make_session):
    session, link, clock, _ = make_session()
    await start(session)
    await session.on_event(
        "message", {"type": "utterance_start", "user_id": "u1", "speaker_name": "Alice", "t": 1_000}
    )
    await session.on_event("audio", AudioFrame("u1", 1_000, bytes(BYTES_PER_MS * 1_000)))
    clock.now = 2_000
    await session.on_event("disconnected", None)
    await session.on_event("connected", {"type": "hello"})
    await speak(session, start=10_000)
    await session.settle()
    assert [s.start for s in session.meeting.agent.transcript.all()] == [1.0, 10.0]


async def test_commands_are_refused_while_the_meeting_ends(make_session):
    session, link, *_ = make_session()
    await start(session)
    session.meeting.closing = True
    await session.on_event("message", command("ask", interaction="i2", question="Why?"))
    await session.on_event("message", command("meeting_level", interaction="i3", level="silent"))
    replies = {r["interaction_id"]: r["text"] for r in link.of("reply")}
    assert replies["i2"] == replies["i3"] == "The meeting is already ending."
    assert session.meeting.queue.empty()


async def test_a_failed_question_is_answered(make_session):
    session, link, *_ = make_session()
    await start(session)

    async def broken_ask(question):
        raise RuntimeError("boom")

    session.meeting.agent.ask = broken_ask
    await session.on_event("message", command("ask", interaction="i2", question="Why?"))
    await session.settle()
    reply = next(r for r in link.of("reply") if r["interaction_id"] == "i2")
    assert reply["text"] == "The command failed; details are in the agent's log."


async def test_a_restarted_connector_gets_the_edit_modals_back(make_session):
    decision = {"statement": "Cooldown is 30 seconds", "quote": "bonjour à tous"}
    fast = FakeProvider({"Extraction": [{"claims": [], "decisions": [decision], "topics": []}]})
    session, link, *_ = make_session(fast=fast)
    await start(session)
    await speak(session, start=0, ms=31_000)
    await session.settle()
    await session.on_event("connected", {"type": "hello"})
    [resent] = link.of("modals")
    assert resent["modals"][0]["id"] == "decision:d1:edit"
    assert resent["modals"][0]["modal"]["value"] == "Cooldown is 30 seconds"
    await session.on_event(
        "message",
        {"type": "button", "custom_id": "decision:d1:ignore", "user": {"id": "u1", "name": "A"}},
    )
    await session.on_event("connected", {"type": "hello"})
    assert len(link.of("modals")) == 1  # nothing left to give back


async def test_the_notice_and_the_whisper_hint_carry_the_agent_name(make_session):
    live = FakeTranscriber(default="bonjour")
    session, link, *_ = make_session(live=live)
    await start(session)
    assert "Scribe" in link.texts()[0]
    await speak(session)
    await session.settle()
    assert live.calls[0][2].startswith("Scribe")


async def test_the_level_chosen_at_start_is_recorded_with_who_chose_it(make_session):
    session, *_ = make_session()
    await start(session, level="silent")
    [interaction] = session.meeting.agent.interactions
    assert interaction.text == "Alice set Scribe (AI) to the `silent` level"


async def test_the_whisper_hint_leaves_out_the_aliases_and_adds_the_vocabulary(make_session):
    live = FakeTranscriber(default="bonjour")
    session, *_ = make_session(
        live=live,
        agent={"name": "Otis", "aliases": ["Otisse"]},
        transcription={"vocabulary": ["KB"]},
    )
    await start(session)
    await speak(session)
    await session.settle()
    assert live.calls[0][2].startswith("Otis, KB")
    assert "Otisse" not in live.calls[0][2]


async def test_the_answer_to_a_spoken_question_replies_to_its_announcement(make_session):
    fast = FakeProvider(
        {
            "AddressedIntent": [
                {"kind": "question", "question": "What is the cooldown?", "level": "none"}
            ],
            "Queries": [{"queries": ["cooldown"], "tags": []}],
        }
    )
    strong = FakeProvider({"Answer": [{"covered": True, "answer": "45 s.", "sources": []}]})
    live = FakeTranscriber(default="Scribe, what is the cooldown?")
    session, link, *_ = make_session(fast=fast, strong=strong, live=live)
    await start(session)
    await speak(session)
    await session.settle()
    *_, announcement, answer = link.of("send")
    assert announcement["text"].startswith("🔎")
    assert "reply_to" not in announcement
    assert answer["reply_to"] == announcement["request_id"]


async def test_each_meeting_gives_its_messages_ids_of_its_own():
    # the connector keeps the ids across meetings: a reply must not find an older meeting's
    link = FakeLink()
    first, second = ConnectorSink(link, "t1"), ConnectorSink(link, "t2")
    assert await first.send(OutMessage("a")) != await second.send(OutMessage("b"))


async def test_code_sync_runs_in_the_background(make_session, code_origin):
    session, link, *_ = make_session(code=str(code_origin))
    await start(session)
    assert link.of("join")
    await session.meeting.code_sync
    assert any("Building the index of back" in text for text in link.texts())
    assert session.meeting.kb.code_repos[0].indexed
    [hit, *_] = await session.meeting.kb.search("COOLDOWN_SECONDS", prefer_tags=("BackEnd",))
    assert hit.repo == "back"


async def test_an_unavailable_code_repo_is_reported_once(make_session, tmp_path):
    session, link, *_ = make_session(code=str(tmp_path / "nonexistent"))
    await start(session)
    await session.meeting.code_sync
    assert sum("back repository is unavailable" in text for text in link.texts()) == 1
    assert link.of("reply")[-1]["text"] == "Meeting started with the test project."


async def test_closing_stops_the_code_sync(make_session, code_origin):
    session, *_ = make_session(code=str(code_origin))
    await start(session)
    sync = session.meeting.code_sync
    await session.close()
    assert sync.done()


async def test_closing_releases_the_project_sources(make_session, code_origin):
    session, *_ = make_session(code=str(code_origin))
    await start(session)
    sources = session.meeting.kb
    closed = []
    original = sources.close
    sources.close = lambda: closed.append(1) or original()
    await session.close()
    assert closed == [1]
