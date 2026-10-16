from kb_meeting_agent.agent.answering import answer_question
from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.llm.fake import FakeProvider


async def test_answer_keeps_only_real_sources(kb):
    fast = FakeProvider({"Queries": [{"queries": ["COOLDOWN_SECONDS default"]}]})
    strong = FakeProvider(
        {
            "Answer": [
                {
                    "covered": True,
                    "answer": "The cooldown is 45 seconds.",
                    "sources": ["reference/configuration.md#Neutralization", "invented.md#X"],
                }
            ]
        }
    )
    text = await answer_question(
        fast, strong, kb, question="What is the cooldown?", context="", language="en"
    )
    assert "45 seconds" in text
    assert "`reference/configuration.md#Neutralization`" in text
    assert "invented.md" not in text
    assert "COOLDOWN_SECONDS" in strong.calls[0][2]
    assert "BIO-SCAN" in fast.calls[0][1]


async def test_not_covered(kb):
    fast = FakeProvider({"Queries": [{"queries": []}]})
    strong = FakeProvider({"Answer": [{"covered": False, "answer": "", "sources": []}]})
    text = await answer_question(fast, strong, kb, question="Who won?", context="", language="fr")
    assert text == t("fr", "not_covered")
    assert "Who won?" in strong.calls[0][2]
