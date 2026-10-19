import pytest

from kb_meeting_agent.llm.base import (
    LLMError,
    LLMInvalidOutput,
    Schema,
    complete,
    extract_json,
    json_schema_for,
)
from kb_meeting_agent.llm.fake import FakeProvider, fake_embedding


class Item(Schema):
    name: str


class Bag(Schema):
    items: list[Item]
    count: int


def test_json_schema_inlines_refs_and_forbids_extra():
    schema = json_schema_for(Bag)
    assert "$defs" not in schema
    assert schema["title"] == "Bag"
    item = schema["properties"]["items"]["items"]
    assert item["properties"]["name"]["type"] == "string"
    assert item["additionalProperties"] is False
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"items", "count"}


@pytest.mark.parametrize(
    "raw",
    [
        '{"items": [], "count": 1}',
        '```json\n{"items": [], "count": 1}\n```',
        'Sure! Here it is: {"items": [], "count": 1} Hope it helps.',
    ],
)
def test_extract_json(raw):
    assert extract_json(raw) == '{"items": [], "count": 1}'


async def test_complete_accepts_fenced_json():
    provider = FakeProvider({"Bag": ['```json\n{"items": [{"name": "a"}], "count": 1}\n```']})
    bag = await complete(provider, "sys", "user", Bag)
    assert bag.items[0].name == "a"


async def test_complete_retries_once_with_the_schema():
    provider = FakeProvider({"Bag": ['{"count": "x"}', {"items": [], "count": 2}]})
    bag = await complete(provider, "sys", "user", Bag)
    assert bag.count == 2
    assert len(provider.calls) == 2
    assert '"title": "Bag"' in provider.calls[1][2]


async def test_complete_gives_up_after_retries():
    provider = FakeProvider({"Bag": ["nope", "still nope"]})
    with pytest.raises(LLMInvalidOutput):
        await complete(provider, "sys", "user", Bag)


async def test_fake_provider_raises_queued_exceptions_and_uses_defaults():
    provider = FakeProvider(
        {"Bag": [LLMError("down")]}, defaults={"Bag": {"items": [], "count": 0}}
    )
    with pytest.raises(LLMError):
        await complete(provider, "s", "u", Bag)
    assert (await complete(provider, "s", "u", Bag)).count == 0


def test_fake_embedding_is_deterministic_and_normalized():
    a, b = fake_embedding("cooldown seconds"), fake_embedding("cooldown seconds")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-6


@pytest.mark.parametrize(
    "raw",
    [
        '<think>The user wants {x} and maybe {y}.</think>\n{"items": [], "count": 1}',
        '<think>\n</think>\n\n```json\n{"items": [], "count": 1}\n```',
        'Thinking about {braces}... the answer: {"items": [], "count": 1}',
    ],
)
async def test_complete_ignores_reasoning_before_the_json(raw):
    provider = FakeProvider({"Bag": [raw]})
    assert (await complete(provider, "sys", "user", Bag)).count == 1
