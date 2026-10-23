import asyncio
import json

from conftest import KB_FILES, commit_file, minutes_content

from kb_meeting_agent.llm.fake import FakeProvider
from kb_meeting_agent.ports import PublishError
from kb_meeting_agent.publish.local import INDEX_ROWS_FILE, FakePublisher
from kb_meeting_agent.transcription.base import TranscriptionResult
from kb_meeting_agent.transcription.fake import FakeTranscriber
from live.helpers import command, speak

MINUTES = {"MinutesContent": [minutes_content("Weekly", "weekly")]}


class FailingPublisher(FakePublisher):
    async def open_pr(self, branch, files, title, body):
        raise PublishError("GET https://api.github.com: 403", public="GitHub answered 403")


async def start(session):
    await session.on_event("message", command("meeting_start", project="test"))


async def test_close_publishes_minutes_leaves_and_deletes_audio(make_session):
    session, link, clock, publisher = make_session(strong=FakeProvider(dict(MINUTES)))
    await start(session)
    await speak(session)
    meeting = session.meeting
    pr = await session.close()
    assert pr.url == "https://example.test/pull/1"
    assert publisher.prs[0][0].endswith("-weekly")
    assert link.of("leave") == [{}]
    assert not (meeting.dir / "audio").exists()
    state = json.loads((meeting.dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "closed"
    assert session.meeting is None
    assert publisher.closed


async def test_second_pass_feeds_the_minutes(make_session):
    strong = FakeProvider(dict(MINUTES))
    session, link, clock, publisher = make_session(
        strong=strong, final=FakeTranscriber(default="texte précis de la seconde passe")
    )
    await start(session)
    await speak(session)
    meeting = session.meeting
    await session.close()
    assert "texte précis" in strong.calls_for("SliceSummary")[0][2]
    final = (meeting.dir / "transcript.final.jsonl").read_text(encoding="utf-8")
    assert "texte précis" in final


async def test_failed_minutes_keep_the_audio(make_session):
    session, link, clock, _ = make_session(
        strong=FakeProvider(dict(MINUTES)), publisher=FailingPublisher()
    )
    await start(session)
    await speak(session)
    meeting = session.meeting
    assert await session.close() is None
    assert any((meeting.dir / "audio").iterdir())
    assert (meeting.dir / "unpublished").exists()


async def test_resume_after_a_crash(make_session):
    first, link, clock, _ = make_session()
    await start(first)
    await speak(first)
    await first.settle()
    meeting_dir = first.meeting.dir
    # The process dies here: no close(). A new session starts from the same data dir.
    second, link2, clock2, publisher2 = make_session(strong=FakeProvider(dict(MINUTES)))
    clock2.now = 120_000
    await second.on_event("message", command("meeting_resume"))
    assert second.meeting.dir == meeting_dir
    assert link2.of("join") == [{"voice_channel_id": "v1", "text_channel_id": "t1"}]
    assert link2.of("reply")[-1]["text"] == "Meeting resumed."
    assert [s.text for s in second.meeting.agent.transcript.all()] == ["bonjour à tous"]
    assert second.meeting.gaps[-1][1] == 120.0
    await speak(second, start=125_000)
    assert second.meeting.assembler.next_index == 2
    await second.close()
    assert len(publisher2.prs) == 1


async def test_nothing_to_resume(make_session):
    session, link, *_ = make_session()
    await session.on_event("message", command("meeting_resume"))
    assert link.of("reply")[-1]["text"] == "There is no unfinished meeting to resume."


async def test_retry_publish_sends_kept_pull_requests(make_session):
    failing, link, clock, _ = make_session(
        strong=FakeProvider(dict(MINUTES)), publisher=FailingPublisher()
    )
    await start(failing)
    await speak(failing)
    meeting_dir = failing.meeting.dir
    await failing.close()
    working, link2, clock2, publisher = make_session()
    await working.on_event("message", command("meeting_retry_publish"))
    assert len(publisher.prs) == 1
    branch, files, title, body = publisher.prs[0]
    assert branch.endswith("-weekly") and title == "Minutes: Weekly"
    assert any(path.endswith("-weekly.md") for path in files)
    assert "https://example.test/pull/1" in link2.of("reply")[-1]["text"]
    assert not any((meeting_dir / "unpublished").rglob("PR.md"))
    assert publisher.closed


async def test_optout_survives_a_resume_and_deletes_the_speakers_audio(make_session):
    first, link, clock, _ = make_session()
    await start(first)
    await speak(first, user="u2", name="Bob")
    await first.settle()
    meeting_dir = first.meeting.dir
    assert list((meeting_dir / "audio").glob("*-u2.wav"))
    await first.on_event("message", command("meeting_optout", interaction="i2", user=("u2", "Bob")))
    assert not list((meeting_dir / "audio").glob("*-u2.wav"))
    second, link2, clock2, _ = make_session(strong=FakeProvider(dict(MINUTES)))
    await second.on_event("message", command("meeting_resume"))
    assert link2.of("optout") == [{"user_id": "u2"}]
    await second.on_event("connected", {"type": "hello"})
    assert link2.of("optout") == [{"user_id": "u2"}, {"user_id": "u2"}]
    await speak(second, user="u2", name="Bob", start=5_000)
    await second.settle()
    assert [s.start for s in second.meeting.agent.transcript.all()] == [1.0]


async def test_second_pass_keeps_opted_out_speakers_live_lines_only(make_session):
    strong = FakeProvider(dict(MINUTES))
    final = FakeTranscriber(default="seconde passe")
    session, link, clock, _ = make_session(strong=strong, final=final)
    await start(session)
    await speak(session, user="u1", name="Alice", start=1_000)
    await speak(session, user="u2", name="Bob", start=3_000)
    await session.settle()
    await session.on_event(
        "message", command("meeting_optout", interaction="i2", user=("u2", "Bob"))
    )
    await session.close()
    assert len(final.calls) == 1
    summary_input = strong.calls_for("SliceSummary")[0][2]
    assert "Alice: seconde passe" in summary_input and "Bob: bonjour à tous" in summary_input


async def test_expired_meetings_are_deleted(make_session):
    session, link, clock, _ = make_session(
        strong=FakeProvider(dict(MINUTES)), publisher=FailingPublisher()
    )
    await start(session)
    await speak(session)
    closed_dir = session.meeting.dir
    await session.close()
    await session.on_event(
        "message", command("meeting_start", interaction="i2", project="test", voice="v2")
    )
    abandoned_dir = session.meeting.dir
    fresh, _, fresh_clock, _ = make_session()
    fresh_clock.now = 31 * 86_400_000
    await fresh.on_event("message", command("meeting_start", interaction="i3", project="test"))
    assert not closed_dir.exists() and not abandoned_dir.exists()
    assert fresh.meeting.dir.exists()


async def test_close_runs_once_and_leaves_before_writing_the_minutes(make_session):
    session, link, clock, publisher = make_session(strong=FakeProvider(dict(MINUTES)))
    await start(session)
    await speak(session)
    first, second = await asyncio.gather(session.close(), session.close())
    assert len(publisher.prs) == 1
    assert [first, second].count(None) == 1
    kinds = [kind for kind, _ in link.sent]
    minutes_message = next(
        i for i, (k, f) in enumerate(link.sent) if k == "send" and "Meeting minutes" in f["text"]
    )
    assert kinds.index("leave") < minutes_message


async def test_end_during_close_says_it_is_already_ending(make_session):
    session, link, clock, publisher = make_session(strong=FakeProvider(dict(MINUTES)))
    await start(session)
    closing = asyncio.create_task(session.close())
    await asyncio.sleep(0)
    await session.on_event("message", command("meeting_end", interaction="i2"))
    await closing
    assert {"interaction_id": "i2", "text": "The meeting is already ending."} in link.of("reply")


async def test_an_open_gap_is_counted_at_close(make_session):
    strong = FakeProvider(dict(MINUTES))
    session, link, clock, _ = make_session(strong=strong)
    await start(session)
    await speak(session)
    clock.now = 60_000
    await session.on_event("disconnected", None)
    clock.now = 90_000
    await session.close()
    assert "00:01:00 to 00:01:30" in strong.calls_for("MinutesContent")[0][2]


async def test_second_pass_falls_back_to_live_lines_when_it_fails(make_session):
    class FailsOnce:
        def __init__(self):
            self.calls = 0

        def transcribe(self, audio, *, language, prompt):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("out of memory")
            return TranscriptionResult("version précise")

    strong = FakeProvider(dict(MINUTES))
    session, link, clock, _ = make_session(strong=strong, final=FailsOnce())
    await start(session)
    await speak(session, user="u1", name="Alice", start=1_000)
    await speak(session, user="u2", name="Bob", start=3_000)
    await session.close()
    summary_input = strong.calls_for("SliceSummary")[0][2]
    assert "Alice: bonjour à tous" in summary_input
    assert "Bob: version précise" in summary_input


async def test_second_pass_stops_after_three_consecutive_failures(make_session, caplog):
    class Missing:
        def __init__(self):
            self.calls = 0

        def transcribe(self, audio, *, language, prompt):
            self.calls += 1
            raise RuntimeError("model not found")

    engine = Missing()
    strong = FakeProvider(dict(MINUTES))
    session, link, clock, _ = make_session(strong=strong, final=engine)
    await start(session)
    for i in range(5):
        await speak(session, start=1_000 + i * 2_000)
    await session.close()
    assert engine.calls == 3
    assert strong.calls_for("SliceSummary")[0][2].count("Alice: bonjour à tous") == 5
    assert sum(record.exc_info is not None for record in caplog.records) == 1


async def test_a_failed_close_frees_the_session(make_session):
    session, link, *_ = make_session()
    await start(session)
    await speak(session)
    meeting = session.meeting

    async def broken_end(**_):
        raise RuntimeError("boom")

    meeting.agent.end = broken_end
    assert await session.close() is None
    assert session.meeting is None
    assert link.texts()[-1].startswith("Ending the meeting failed")
    state = json.loads((meeting.dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"  # not offered to /meeting resume
    assert any((meeting.dir / "audio").iterdir())
    await session.on_event("message", command("meeting_start", interaction="i2", project="test"))
    assert session.meeting is not None and session.meeting.dir != meeting.dir


async def test_resume_does_not_reuse_utterances_recorded_after_the_last_save(make_session):
    first, *_ = make_session()
    await start(first)
    await speak(first)
    await first.settle()
    state_path = first.meeting.dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state_path.write_text(json.dumps(state | {"next_utterance": 0}), encoding="utf-8")
    second, *_ = make_session()
    await second.on_event("message", command("meeting_resume"))
    assert second.meeting.assembler.next_index == 1


async def test_retry_publish_rebuilds_the_index_on_the_current_base(make_session, kb_origin):
    failing, *_ = make_session(strong=FakeProvider(dict(MINUTES)), publisher=FailingPublisher())
    await start(failing)
    await speak(failing)
    await failing.close()
    merged = "| 2024-01-01 | [Kickoff](2024-01-01-kickoff.md) | Bob |"
    commit_file(kb_origin, "meetings/README.md", KB_FILES["meetings/README.md"] + merged + "\n")
    working, link, _, publisher = make_session()
    await working.on_event("message", command("meeting_retry_publish"))
    _, files, _, _ = publisher.prs[0]
    index = files["meetings/README.md"].splitlines()
    assert index[-2] == merged and "[Weekly]" in index[-1]
    assert not any(path.endswith(INDEX_ROWS_FILE) for path in files)


async def test_retry_publish_skips_a_decision_whose_number_is_now_taken(make_session, kb_origin):
    decision = {"statement": "Cooldown is 30 seconds", "quote": "bonjour à tous"}
    fast = FakeProvider({"Extraction": [{"claims": [], "decisions": [decision], "topics": []}]})
    failing, *_ = make_session(fast=fast, publisher=FailingPublisher())
    await start(failing)
    await speak(failing, start=0, ms=31_000)
    await failing.settle()
    await failing.on_event(
        "message",
        {"type": "button", "custom_id": "decision:d1:validate", "user": {"id": "u1", "name": "A"}},
    )
    await failing.settle()
    kept = failing.meeting.dir / "unpublished"
    assert any(kept.rglob("0003-*.md"))
    commit_file(kb_origin, "decisions/0003-other.md", "# 0003 — Other\n")
    working, link, _, publisher = make_session()
    await working.on_event("message", command("meeting_retry_publish"))
    assert publisher.prs == []
    assert "decision number 0003 is now used" in link.of("reply")[-1]["text"]
    assert any(kept.rglob("PR.md"))
