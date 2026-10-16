from datetime import date

import httpx
import pytest

from kb_meeting_agent.agent.meeting import AgentSettings, MeetingAgent
from kb_meeting_agent.agent.transcript import Transcript
from kb_meeting_agent.llm.base import LLMConfigError, LLMError, LLMUnavailable
from kb_meeting_agent.llm.fake import FAKE_DEFAULTS, FakeProvider
from kb_meeting_agent.models import Segment
from kb_meeting_agent.ports import PublishError
from kb_meeting_agent.publish.local import FakePublisher

DECISION = {"statement": "Cooldown is 30 seconds", "quote": "ok on passe à 30"}
DRAFT = {
    "title": "Cooldown at 30 s",
    "slug": "cooldown-30-s",
    "scope": "backend",
    "context": "c",
    "decision": "d",
    "consequences": "q",
    "related_pages": [
        {"path": "reference/configuration.md", "section": "Neutralization", "reason": "value"},
        {"path": "nope.md", "section": "X", "reason": "invented"},
    ],
}
VERDICT = {
    "verdict": "contradicts",
    "kb_quote": "| `COOLDOWN_SECONDS` | `45` |",
    "path": "reference/configuration.md",
    "reason": "Default is 45 s.",
    "confidence": 0.95,
}


class Sink:
    def __init__(self):
        self.messages = []

    async def send(self, message):
        self.messages.append(message)
        return str(len(self.messages))

    def texts(self):
        return [m.text for m in self.messages]


def extraction(claims=(), decisions=(), topics=()):
    return {"claims": list(claims), "decisions": list(decisions), "topics": list(topics)}


def seg(start, text, name="Alice"):
    return Segment(name.lower(), name, start, start + 31, text)


@pytest.fixture
def make_agent(kb, tmp_path):
    def factory(fast=None, strong=None, open_paths=(), **settings):
        fast = fast or FakeProvider(defaults=FAKE_DEFAULTS)
        strong = strong or FakeProvider(defaults=FAKE_DEFAULTS)
        fast.defaults = FAKE_DEFAULTS | fast.defaults
        strong.defaults = FAKE_DEFAULTS | strong.defaults
        publisher, sink = FakePublisher(list(open_paths)), Sink()
        agent = MeetingAgent(
            kb=kb,
            fast=fast,
            strong=strong,
            publisher=publisher,
            sink=sink,
            transcript=Transcript(tmp_path / "meeting" / "transcript.jsonl"),
            settings=AgentSettings(
                agent_names=["scribe"], meeting_date=date(2026, 10, 15), **settings
            ),
        )
        return agent, fast, strong, publisher, sink

    return factory


async def test_decision_is_proposed_then_published_on_button(make_agent):
    fast = FakeProvider({"Extraction": [extraction(decisions=[DECISION])]})
    strong = FakeProvider({"DecisionDraft": [DRAFT]})
    agent, _, _, publisher, sink = make_agent(fast, strong, open_paths=["decisions/0003-other.md"])
    await agent.on_segment(seg(0, "ok on passe à 30"))
    proposal = sink.messages[-1]
    assert "Cooldown is 30 seconds" in proposal.text
    assert [b.id for b in proposal.buttons] == [
        "decision:d1:validate",
        "decision:d1:edit",
        "decision:d1:ignore",
    ]
    await agent.on_button("decision:d1:validate", "Bob")
    branch, files, title, body = publisher.prs[0]
    assert "decisions/0004-cooldown-30-s.md" in files
    assert files["decisions/0004-cooldown-30-s.md"].startswith("# 0004 — Cooldown at 30 s")
    assert (
        "| [0004](0004-cooldown-30-s.md) | Cooldown at 30 s | accepted |"
        in files["decisions/README.md"]
    )
    assert "reference/configuration.md" in body and "nope.md" not in body
    assert agent.decisions["d1"].state == "validated"
    assert sink.texts()[-1].endswith("https://example.test/pull/1")


async def test_duplicate_decision_is_proposed_once(make_agent):
    fast = FakeProvider(
        {"Extraction": [extraction(decisions=[DECISION]), extraction(decisions=[DECISION])]}
    )
    agent, *_, sink = make_agent(fast)
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_segment(seg(40, "oui 30"))
    assert sum("Cooldown is 30 seconds" in text for text in sink.texts()) == 1


async def test_ignore_and_edit(make_agent):
    fast = FakeProvider(
        {"Extraction": [extraction(decisions=[DECISION, {"statement": "Drop BLE", "quote": "q"}])]}
    )
    strong = FakeProvider({"DecisionDraft": [DRAFT]})
    agent, _, strong, publisher, _ = make_agent(fast, strong)
    await agent.on_segment(seg(0, "..."))
    await agent.on_button("decision:d2:ignore", "Bob")
    assert agent.decisions["d2"].state == "ignored"
    await agent.edit_decision("d1", "Cooldown is 25 seconds", "Bob")
    assert "Cooldown is 25 seconds" in strong.calls_for("DecisionDraft")[0][2]
    assert len(publisher.prs) == 1


async def test_contradiction_is_flagged_once_per_subject(make_agent):
    claim = {"subject": "cooldown", "statement": "The cooldown is 30 seconds"}
    fast = FakeProvider({"Extraction": [extraction(claims=[claim]), extraction(claims=[claim])]})
    strong = FakeProvider({"Verdict": [VERDICT, VERDICT]})
    agent, *_, sink = make_agent(fast, strong)
    await agent.on_segment(seg(0, "the cooldown is 30 seconds"))
    await agent.on_segment(seg(40, "yes 30 seconds"))
    flagged = [text for text in sink.texts() if "COOLDOWN_SECONDS" in text]
    assert len(flagged) == 1
    assert "reference/configuration.md#Neutralization" in flagged[0]
    assert len(agent.flags) == 1


async def test_invented_quote_is_not_posted(make_agent):
    claim = {"subject": "cooldown", "statement": "The cooldown is 30 seconds"}
    fast = FakeProvider({"Extraction": [extraction(claims=[claim])]})
    strong = FakeProvider({"Verdict": [VERDICT | {"kb_quote": "the cooldown is 60 seconds"}]})
    agent, *_, sink = make_agent(fast, strong)
    await agent.on_segment(seg(0, "the cooldown is 30 seconds"))
    assert sink.messages == []


async def test_silent_level_skips_claims(make_agent):
    claim = {"subject": "cooldown", "statement": "x"}
    fast = FakeProvider({"Extraction": [extraction(claims=[claim])]})
    agent, _, strong, *_ = make_agent(fast, level="silent")
    await agent.on_segment(seg(0, "x"))
    assert strong.calls_for("Verdict") == []


async def test_addressed_question_is_answered(make_agent):
    fast = FakeProvider(
        {
            "AddressedIntent": [
                {"kind": "question", "question": "What is the cooldown?", "level": "none"}
            ],
            "Queries": [{"queries": ["cooldown"]}],
        }
    )
    strong = FakeProvider(
        {
            "Answer": [
                {
                    "covered": True,
                    "answer": "45 s.",
                    "sources": ["reference/configuration.md#Neutralization"],
                }
            ]
        }
    )
    agent, *_, sink = make_agent(fast, strong, extraction_interval_s=1000)
    await agent.on_segment(seg(0, "Scribe, what is the cooldown?"))
    assert sink.texts()[0].startswith("45 s.")


async def test_voice_commands(make_agent):
    fast = FakeProvider(
        {
            "Extraction": [extraction(decisions=[DECISION])],
            "AddressedIntent": [
                {"kind": "validate", "question": "", "level": "none"},
                {"kind": "set_level", "question": "", "level": "silent"},
            ],
        }
    )
    strong = FakeProvider({"DecisionDraft": [DRAFT]})
    agent, _, _, publisher, sink = make_agent(fast, strong)
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_segment(seg(1, "scribe, valide"))
    assert len(publisher.prs) == 1
    await agent.on_segment(seg(2, "scribe, mode silencieux"))
    assert agent.level == "silent"
    assert sink.texts()[-1] == "Intervention level: silent."


async def test_unavailable_model_pauses_checks_once(make_agent):
    fast = FakeProvider({"Extraction": [LLMUnavailable("down"), LLMUnavailable("down")]})
    agent, *_, sink = make_agent(fast)
    await agent.on_segment(seg(0, "a"))
    await agent.on_segment(seg(40, "b"))
    assert sink.texts() == ["Checks paused: the model is unavailable. Transcription continues."]
    await agent.on_segment(seg(80, "c"))
    assert sink.texts()[-1] == "Checks resumed."
    assert len(agent.transcript.all()) == 3


async def test_end_publishes_minutes_with_decision_links(make_agent):
    fast = FakeProvider({"Extraction": [extraction(decisions=[DECISION])]})
    strong = FakeProvider(
        {
            "DecisionDraft": [DRAFT],
            "MinutesDraft": [{"title": "Weekly", "slug": "weekly", "body": "## Decisions"}],
        }
    )
    agent, _, strong, publisher, sink = make_agent(fast, strong)
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_button("decision:d1:validate", "Bob")
    pr = await agent.end()
    branch, files, *_ = publisher.prs[-1]
    assert branch == "meetings/2026-10-15-weekly"
    assert "meetings/2026-10-15-weekly.md" in files
    assert "https://example.test/pull/1" in strong.calls_for("MinutesDraft")[0][2]
    assert pr.url == "https://example.test/pull/2"
    assert sink.texts()[-1] == "Meeting minutes: https://example.test/pull/2"


async def test_end_without_transcript_publishes_nothing(make_agent):
    agent, *_, publisher, _ = make_agent()
    assert await agent.end() is None
    assert publisher.prs == []


class FailingPublisher(FakePublisher):
    async def open_pr(self, branch, files, title, body):
        raise PublishError("403 forbidden")


async def test_paraphrased_decision_is_proposed_once(make_agent):
    paraphrase = {"statement": "The team sets the cooldown to 30 s", "quote": "ok on passe à 30"}
    fast = FakeProvider(
        {"Extraction": [extraction(decisions=[DECISION]), extraction(decisions=[paraphrase])]}
    )
    agent, *_, sink = make_agent(fast)
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_segment(seg(40, "oui"))
    assert len([m for m in sink.messages if m.buttons]) == 1


async def test_pr_body_quotes_the_real_transcript(make_agent):
    invented = {"statement": "Cooldown is 30 seconds", "quote": "we solemnly decided thirty"}
    fast = FakeProvider({"Extraction": [extraction(decisions=[invented])]})
    strong = FakeProvider({"DecisionDraft": [DRAFT]})
    agent, _, _, publisher, _ = make_agent(fast, strong)
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_button("decision:d1:validate", "Bob")
    body = publisher.prs[0][3]
    assert "> [00:00:00] Alice: ok on passe à 30" in body
    assert "solemnly" not in body


async def test_same_kb_line_is_flagged_once(make_agent):
    fast = FakeProvider(
        {
            "Extraction": [
                extraction(claims=[{"subject": "cooldown", "statement": "30 s"}]),
                extraction(claims=[{"subject": "neutralization delay", "statement": "30 s"}]),
            ]
        }
    )
    strong = FakeProvider({"Verdict": [VERDICT, VERDICT]})
    agent, *_, sink = make_agent(fast, strong)
    await agent.on_segment(seg(0, "a"))
    await agent.on_segment(seg(40, "b"))
    assert len(agent.flags) == 1
    assert len(sink.messages) == 1


async def test_any_model_error_does_not_stop_the_meeting(make_agent):
    fast = FakeProvider({"Extraction": [LLMError("weird")]})
    agent, *_, sink = make_agent(fast)
    await agent.on_segment(seg(0, "a"))
    assert sink.messages == []


async def test_end_reports_minutes_failure(make_agent):
    strong = FakeProvider({"SliceSummary": [LLMUnavailable("down")]})
    agent, *_, publisher, sink = make_agent(strong=strong, extraction_interval_s=1000)
    await agent.on_segment(seg(0, "a"))
    assert await agent.end() is None
    assert publisher.prs == []
    assert "transcript.jsonl" in sink.texts()[-1]


async def test_failed_publication_is_kept_locally(make_agent, tmp_path):
    fast = FakeProvider({"Extraction": [extraction(decisions=[DECISION])]})
    strong = FakeProvider(
        {
            "DecisionDraft": [DRAFT],
            "MinutesDraft": [{"title": "Weekly", "slug": "weekly", "body": "x"}],
        }
    )
    agent, *_, sink = make_agent(fast, strong)
    agent.publisher = FailingPublisher()
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_button("decision:d1:validate", "Bob")
    await agent.end()
    kept = tmp_path / "meeting" / "unpublished"
    assert (kept / "decision/2026-10-15-cooldown-30-s/decisions/0003-cooldown-30-s.md").exists()
    assert (kept / "meetings/2026-10-15-weekly/meetings/2026-10-15-weekly.md").exists()
    assert "unpublished" in sink.texts()[-1]
    assert str(tmp_path) not in "".join(sink.texts())


class ExplodingPublisher(FakePublisher):
    async def open_pr(self, branch, files, title, body):
        raise httpx.ConnectError("api.internal.example:8443 refused")


async def test_two_decisions_from_one_utterance_are_both_proposed(make_agent):
    line = "ok on passe à Postgres et on abandonne Redis"
    decisions = [
        {"statement": "We move to Postgres", "quote": line},
        {"statement": "We drop Redis", "quote": line},
    ]
    fast = FakeProvider({"Extraction": [extraction(decisions=decisions)]})
    agent, *_, sink = make_agent(fast)
    await agent.on_segment(seg(0, line))
    assert len([m for m in sink.messages if m.buttons]) == 2


async def test_unanchored_excerpt_is_labelled_in_the_pr(make_agent):
    invented = {"statement": "Cooldown is 30 seconds", "quote": "we solemnly decided thirty"}
    fast = FakeProvider({"Extraction": [extraction(decisions=[invented])]})
    strong = FakeProvider({"DecisionDraft": [DRAFT]})
    agent, _, _, publisher, _ = make_agent(fast, strong)
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_button("decision:d1:validate", "Bob")
    assert "could not be matched" in publisher.prs[0][3]


async def test_unexpected_publish_error_keeps_the_work(make_agent, tmp_path):
    fast = FakeProvider({"Extraction": [extraction(decisions=[DECISION])]})
    strong = FakeProvider(
        {
            "DecisionDraft": [DRAFT],
            "MinutesDraft": [{"title": "Weekly", "slug": "weekly", "body": "x"}],
        }
    )
    agent, *_, sink = make_agent(fast, strong)
    agent.publisher = ExplodingPublisher()
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_button("decision:d1:validate", "Bob")
    assert agent.decisions["d1"].state == "kept"
    assert await agent.end() is None
    kept = tmp_path / "meeting" / "unpublished"
    assert (kept / "meetings/2026-10-15-weekly/meetings/2026-10-15-weekly.md").exists()


async def test_rejected_model_request_is_reported_once(make_agent):
    error = LLMConfigError("400: json_schema not supported by http://10.0.0.5:11434", status=400)
    fast = FakeProvider({"Extraction": [error, error]})
    agent, *_, sink = make_agent(fast)
    await agent.on_segment(seg(0, "a"))
    await agent.on_segment(seg(40, "b"))
    assert len(sink.messages) == 1
    assert "HTTP 400" in sink.texts()[0]
    assert "10.0.0.5" not in sink.texts()[0]


async def test_unexpected_publish_error_details_stay_out_of_the_channel(make_agent, tmp_path):
    fast = FakeProvider({"Extraction": [extraction(decisions=[DECISION])]})
    strong = FakeProvider({"DecisionDraft": [DRAFT]})
    agent, *_, sink = make_agent(fast, strong)
    agent.publisher = ExplodingPublisher()
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_button("decision:d1:validate", "Bob")
    posted = "".join(sink.texts())
    assert "ConnectError" in posted
    assert "api.internal.example" not in posted
    assert str(tmp_path) not in posted


class LeakyPublisher(FakePublisher):
    async def open_pr_paths(self, prefix):
        raise PublishError("GET https://ghe.internal/api/v3/pulls: 500 <html>", public="GitHub 500")


async def test_publish_error_shows_only_its_public_summary(make_agent):
    fast = FakeProvider({"Extraction": [extraction(decisions=[DECISION])]})
    strong = FakeProvider({"DecisionDraft": [DRAFT]})
    agent, *_, sink = make_agent(fast, strong)
    agent.publisher = LeakyPublisher()
    await agent.on_segment(seg(0, "ok on passe à 30"))
    await agent.on_button("decision:d1:validate", "Bob")
    assert "GitHub 500" in sink.texts()[-1]
    assert "ghe.internal" not in "".join(sink.texts())
