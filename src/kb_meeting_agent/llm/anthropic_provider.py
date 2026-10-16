from __future__ import annotations

from typing import Any

import anthropic

from kb_meeting_agent.config import ModelRole
from kb_meeting_agent.llm.base import LLMError, LLMInvalidOutput, LLMUnavailable, status_error


class AnthropicProvider:
    def __init__(self, role: ModelRole, client: Any | None = None) -> None:
        self._role = role
        self._client = client or anthropic.AsyncAnthropic(api_key=role.api_key)

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if self._role.effort:
            output_config["effort"] = self._role.effort
        kwargs: dict[str, Any] = {
            "model": self._role.model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        try:
            if self._role.refusal_fallback:
                response = await self._client.beta.messages.create(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                response = await self._client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            raise status_error(exc.status_code, exc) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable(str(exc)) from exc
        if response.stop_reason == "refusal":
            raise LLMInvalidOutput("the model declined the request")
        return next((block.text for block in response.content if block.type == "text"), "")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise LLMError(
            "Anthropic has no embeddings endpoint; configure llm.embedding "
            "with an openai-compatible provider"
        )
