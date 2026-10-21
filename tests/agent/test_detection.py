import pytest

from kb_meeting_agent.agent.detection import (
    classify_addressed,
    extract_items,
    is_addressed,
    update_summary,
)
from kb_meeting_agent.llm.fake import FakeProvider


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Scribe, what does the KB say?", True),
        ("ok scribe valide", True),
        ("Can you describe it?", False),
        ("SCRIBE!", True),
    ],
)
def test_is_addressed(text, expected):
    assert is_addressed(text, ["scribe"]) is expected


async def test_extract_items_sends_new_part_and_language():
    llm = FakeProvider(
        {
            "Extraction": [
                {
                    "claims": [{"subject": "cooldown", "statement": "Cooldown is 30 s"}],
                    "decisions": [],
                    "topics": ["cooldown"],
                }
            ]
        }
    )
    result = await extract_items(
        llm,
        summary="",
        context="[00:00:00] A: hi",
        new="[00:00:10] B: cooldown is 30",
        language="fr",
    )
    assert result.claims[0].subject == "cooldown"
    _, system, user = llm.calls[0]
    assert "fr" in system
    assert "NEW:\n[00:00:10] B: cooldown is 30" in user
    assert "(none)" in user


async def test_classify_addressed():
    llm = FakeProvider(
        {"AddressedIntent": [{"kind": "set_level", "question": "", "level": "silent"}]}
    )
    intent = await classify_addressed(
        llm, names=["scribe"], context="...", utterance="scribe, mode silencieux"
    )
    assert intent.kind == "set_level" and intent.level == "silent"
    assert "scribe" in llm.calls[0][1]


async def test_update_summary():
    llm = FakeProvider({"Summary": [{"summary": "We talked about cooldown."}]})
    assert await update_summary(llm, summary="", new="x", language="en") == (
        "We talked about cooldown."
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Brèche, qu'en dit la KB ?", True),
        ("breche, valide", True),
        ("BREACH, mode silencieux", True),
        ("on a une brèche dans le mur", True),  # the name is a word: whole-word match only
        ("embrèchement", False),
    ],
)
def test_is_addressed_ignores_accents_and_case(text, expected):
    assert is_addressed(text, ["Breach", "brèche"]) is expected


async def test_classify_addressed_names_the_agent():
    llm = FakeProvider({"AddressedIntent": [{"kind": "other", "question": "", "level": "none"}]})
    await classify_addressed(llm, names=["Breach", "brèche"], context="", utterance="Breach ?")
    assert "You are Breach" in llm.calls[0][1] and "brèche" in llm.calls[0][1]


async def test_classify_addressed_without_aliases_names_the_agent_once():
    llm = FakeProvider({"AddressedIntent": [{"kind": "other", "question": "", "level": "none"}]})
    await classify_addressed(llm, names=["Breach"], context="", utterance="Breach ?")
    assert "may also call you" not in llm.calls[0][1]
