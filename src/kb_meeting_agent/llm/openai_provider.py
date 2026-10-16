from __future__ import annotations

from typing import Any

import openai

from kb_meeting_agent.config import ModelRole
from kb_meeting_agent.llm.base import LLMUnavailable, status_error


class OpenAICompatibleProvider:
    """Any server speaking the OpenAI API: Ollama, LM Studio, llama.cpp server, mlx-lm, vLLM..."""

    def __init__(self, role: ModelRole, client: Any | None = None) -> None:
        self._role = role
        self._client = client or openai.AsyncOpenAI(
            base_url=role.base_url, api_key=role.api_key or "not-needed"
        )

    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._role.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema.get("title", "response"),
                        "schema": schema,
                        "strict": True,
                    },
                },
            )
        except openai.APIStatusError as exc:
            raise status_error(exc.status_code, exc) from exc
        except openai.APIConnectionError as exc:
            raise LLMUnavailable(str(exc)) from exc
        return response.choices[0].message.content or ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(model=self._role.model, input=texts)
        except openai.APIStatusError as exc:
            raise status_error(exc.status_code, exc) from exc
        except openai.APIConnectionError as exc:
            raise LLMUnavailable(str(exc)) from exc
        return [item.embedding for item in response.data]
