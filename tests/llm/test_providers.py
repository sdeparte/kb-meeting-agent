from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest

from kb_meeting_agent.config import ModelRole
from kb_meeting_agent.llm.anthropic_provider import AnthropicProvider
from kb_meeting_agent.llm.base import LLMConfigError, LLMError, LLMInvalidOutput, LLMUnavailable
from kb_meeting_agent.llm.factory import build_provider
from kb_meeting_agent.llm.fake import FakeProvider
from kb_meeting_agent.llm.openai_provider import OpenAICompatibleProvider

SCHEMA = {"title": "T", "type": "object", "properties": {}, "additionalProperties": False}


class Recorder:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def anthropic_response(text="{}", stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)]
    )


def anthropic_client(response):
    return SimpleNamespace(
        messages=Recorder(response), beta=SimpleNamespace(messages=Recorder(response))
    )


async def test_anthropic_sends_schema_and_effort():
    client = anthropic_client(anthropic_response('{"a": 1}'))
    role = ModelRole(provider="anthropic", model="claude-opus-5-5", effort="low")
    out = await AnthropicProvider(role, client=client).complete_json("sys", "hello", SCHEMA)
    assert out == '{"a": 1}'
    kwargs = client.messages.kwargs
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["system"] == "sys"
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert kwargs["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "low",
    }


async def test_anthropic_refusal_fallback_uses_beta_endpoint():
    client = anthropic_client(anthropic_response())
    role = ModelRole(provider="anthropic", model="claude-opus-5-5", refusal_fallback=True)
    await AnthropicProvider(role, client=client).complete_json("s", "u", SCHEMA)
    assert client.messages.kwargs is None
    assert client.beta.messages.kwargs["betas"] == ["server-side-fallback-2026-07-01"]
    assert client.beta.messages.kwargs["fallbacks"] == "default"


async def test_anthropic_refusal_is_invalid_output():
    client = anthropic_client(anthropic_response(stop_reason="refusal"))
    role = ModelRole(provider="anthropic", model="claude-opus-5-5")
    with pytest.raises(LLMInvalidOutput):
        await AnthropicProvider(role, client=client).complete_json("s", "u", SCHEMA)


async def test_anthropic_has_no_embeddings():
    role = ModelRole(provider="anthropic", model="claude-opus-5-5")
    with pytest.raises(LLMError, match="openai-compatible"):
        await AnthropicProvider(role, client=anthropic_client(anthropic_response())).embed(["x"])


async def test_openai_compatible_sends_json_schema_and_embeds():
    completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"b": 2}'))]
    )
    embeddings = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=Recorder(completion)), embeddings=Recorder(embeddings)
    )
    role = ModelRole(provider="openai-compatible", model="qwen3:14b", base_url="http://x/v1")
    provider = OpenAICompatibleProvider(role, client=client)
    assert await provider.complete_json("sys", "u", SCHEMA) == '{"b": 2}'
    kwargs = client.chat.completions.kwargs
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["response_format"]["json_schema"]["schema"] == SCHEMA
    assert kwargs["response_format"]["json_schema"]["name"] == "T"
    assert await provider.embed(["x"]) == [[0.1, 0.2]]
    assert client.embeddings.kwargs == {"model": "qwen3:14b", "input": ["x"]}


def test_factory_builds_fake_provider():
    assert isinstance(build_provider(ModelRole(provider="fake", model="x")), FakeProvider)


class Raiser:
    def __init__(self, exc):
        self.exc = exc

    async def create(self, **kwargs):
        raise self.exc


def http_response(status):
    return httpx.Response(status, request=httpx.Request("POST", "http://x"))


async def test_openai_rejected_request_is_a_configuration_error():
    exc = openai.BadRequestError(
        "json_schema not supported", response=http_response(400), body=None
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=Raiser(exc)))
    role = ModelRole(provider="openai-compatible", model="m")
    with pytest.raises(LLMConfigError, match="400"):
        await OpenAICompatibleProvider(role, client=client).complete_json("s", "u", SCHEMA)


async def test_anthropic_auth_error_is_a_configuration_error():
    exc = anthropic.AuthenticationError("bad key", response=http_response(401), body=None)
    client = SimpleNamespace(messages=Raiser(exc), beta=SimpleNamespace(messages=Raiser(exc)))
    role = ModelRole(provider="anthropic", model="claude-opus-5-5")
    with pytest.raises(LLMConfigError, match="401"):
        await AnthropicProvider(role, client=client).complete_json("s", "u", SCHEMA)


async def test_openai_rate_limit_is_unavailable():
    exc = openai.RateLimitError("slow down", response=http_response(429), body=None)
    client = SimpleNamespace(chat=SimpleNamespace(completions=Raiser(exc)))
    role = ModelRole(provider="openai-compatible", model="m")
    with pytest.raises(LLMUnavailable, match="429"):
        await OpenAICompatibleProvider(role, client=client).complete_json("s", "u", SCHEMA)


async def test_openai_compatible_passes_request_options_through():
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=Recorder(completion)))
    role = ModelRole(
        provider="openai-compatible",
        model="qwen3:8b",
        request_options={"reasoning_effort": "none"},
    )
    await OpenAICompatibleProvider(role, client=client).complete_json("sys", "u", SCHEMA)
    assert client.chat.completions.kwargs["extra_body"] == {"reasoning_effort": "none"}
    assert client.chat.completions.kwargs["messages"][0]["content"] == "sys"


async def test_openai_compatible_sends_no_extra_body_by_default():
    completion = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=Recorder(completion)))
    role = ModelRole(provider="openai-compatible", model="m")
    await OpenAICompatibleProvider(role, client=client).complete_json("sys", "u", SCHEMA)
    assert "extra_body" not in client.chat.completions.kwargs
