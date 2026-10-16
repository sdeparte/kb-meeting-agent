from __future__ import annotations

from kb_meeting_agent.config import ModelRole
from kb_meeting_agent.llm.base import LLMProvider
from kb_meeting_agent.llm.fake import FAKE_DEFAULTS, FakeProvider


def build_provider(role: ModelRole) -> LLMProvider:
    match role.provider:
        case "anthropic":
            from kb_meeting_agent.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider(role)
        case "openai-compatible":
            from kb_meeting_agent.llm.openai_provider import OpenAICompatibleProvider

            return OpenAICompatibleProvider(role)
        case "fake":
            return FakeProvider(defaults=FAKE_DEFAULTS)
