from datetime import date

from kb_meeting_agent.agent.detection import Claim
from kb_meeting_agent.agent.factcheck import check_claim
from kb_meeting_agent.llm.fake import FakeProvider

CLAIM = Claim(subject="cooldown", statement="The cooldown is 30 seconds")
TODAY = date(2026, 10, 15)


def verdict(**overrides):
    base = {
        "verdict": "contradicts",
        "kb_quote": "| `COOLDOWN_SECONDS` | `45` |",
        "path": "reference/configuration.md#Neutralization",
        "reason": "The default is 45 s.",
        "confidence": 0.9,
    }
    return base | overrides


async def run(kb, response, claim=CLAIM, **kwargs):
    strong = FakeProvider({"Verdict": [response]})
    options = {"threshold": 0.8, "stale_days": 60, "today": TODAY, "language": "en"} | kwargs
    return await check_claim(strong, kb, claim, **options)


async def test_contradiction_is_flagged(kb):
    flag = await run(kb, verdict())
    assert flag.verdict == "contradicts"
    assert flag.anchor == "reference/configuration.md#Neutralization"
    assert flag.stale_since is None


async def test_invented_quote_is_dropped(kb):
    assert await run(kb, verdict(kb_quote="| `COOLDOWN_SECONDS` | `60` |")) is None


async def test_low_confidence_or_confirmation_is_dropped(kb):
    assert await run(kb, verdict(confidence=0.5)) is None
    assert await run(kb, verdict(verdict="confirms")) is None


async def test_unknown_path_is_dropped(kb):
    assert await run(kb, verdict(path="nowhere.md")) is None


async def test_stale_page_is_reported(kb):
    flag = await run(kb, verdict(), stale_days=7)
    assert flag.stale_since == "2026-10-01"


async def test_already_rejected(kb):
    flag = await run(
        kb,
        verdict(
            verdict="already_rejected",
            kb_quote="Rejected because iOS stops background advertising.",
            path="game/ideas.md",
        ),
        claim=Claim(
            subject="raw BLE protocol", statement="We should switch to the raw BLE protocol"
        ),
    )
    assert flag.verdict == "already_rejected"
    assert flag.anchor == "game/ideas.md#Raw BLE protocol [REJECTED]"


async def test_flag_shows_the_full_kb_line(kb):
    flag = await run(kb, verdict(kb_quote="COOLDOWN_SECONDS | 45"))
    assert flag.quote == "| `COOLDOWN_SECONDS` | `45` | Cooldown after a neutralization `[PROD]` |"
