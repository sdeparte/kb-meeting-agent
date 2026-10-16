from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError


class Schema(BaseModel):
    """Base for every structured model output. Every field must be required (no defaults)."""

    model_config = ConfigDict(extra="forbid")


class LLMError(Exception):
    """Base error for model calls."""


class LLMUnavailable(LLMError):
    """The model could not be reached (network, rate limit, server error)."""


class LLMInvalidOutput(LLMError):
    """The model answered, but not with usable output."""


class LLMConfigError(LLMError):
    """The provider rejected the request itself (bad key, unknown model, unsupported option).

    The message is for the log; `status` (the HTTP status, when known) can be shown publicly.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def status_error(status: int, exc: Exception) -> LLMError:
    """Map an HTTP status from a provider: transient failures pause, the rest is configuration."""
    message = f"{status}: {exc}"
    if status in (408, 429) or status >= 500:
        return LLMUnavailable(message)
    return LLMConfigError(message, status=status)


class LLMProvider(Protocol):
    async def complete_json(self, system: str, user: str, schema: dict[str, Any]) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def json_schema_for(model: type[Schema]) -> dict[str, Any]:
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(dict(defs[node["$ref"].rsplit("/", 1)[-1]]))
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(value) for value in node]
        return node

    return resolve(schema)


_FENCED = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def extract_json(raw: str) -> str:
    text = raw.strip()
    fenced = _FENCED.match(text)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


async def complete[T: Schema](
    provider: LLMProvider, system: str, user: str, model: type[T], retries: int = 1
) -> T:
    schema = json_schema_for(model)
    prompt = user
    error: ValidationError | None = None
    for _ in range(retries + 1):
        raw = await provider.complete_json(system, prompt, schema)
        try:
            return model.model_validate_json(extract_json(raw))
        except ValidationError as exc:
            error = exc
            prompt = (
                f"{user}\n\nYour previous answer was not valid ({exc.errors()[0]['msg']}). "
                f"Reply with JSON only, matching exactly this schema:\n{json.dumps(schema)}"
            )
    raise LLMInvalidOutput(str(error))
