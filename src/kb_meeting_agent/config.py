from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConfigError(Exception):
    """Raised when the instance configuration cannot be loaded."""


InterventionLevel = Literal["silent", "contradictions", "context"]

_ENV_VAR = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


def _substitute(value: Any) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                raise ConfigError(f"environment variable {name} is not set")
            return os.environ[name]

        return _ENV_VAR.sub(replace, value)
    if isinstance(value, dict):
        return {key: _substitute(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item) for item in value]
    return value


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelRole(_Strict):
    provider: Literal["anthropic", "openai-compatible", "fake"]
    model: str
    base_url: str | None = None
    api_key: str | None = None
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    refusal_fallback: bool = False
    # openai-compatible: extra request fields passed as is, e.g. {reasoning_effort: none}
    request_options: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(_Strict):
    fast: ModelRole
    strong: ModelRole
    embedding: ModelRole

    @model_validator(mode="after")
    def _embedding_needs_an_embeddings_endpoint(self) -> LLMConfig:
        if self.embedding.provider == "anthropic":
            raise ValueError(
                "llm.embedding cannot use the anthropic provider (Anthropic has no embeddings "
                "endpoint); use an openai-compatible server"
            )
        return self


class KbConfig(_Strict):
    repo: str
    base_branch: str = "main"
    token: str | None = None
    clone_url: str | None = None
    language: str | None = None  # used when the KB's .meeting-agent.yml does not set one


class DefaultsConfig(_Strict):
    intervention_level: InterventionLevel = "contradictions"
    contradiction_min_confidence: float = Field(0.8, ge=0, le=1)
    context_min_interval_minutes: float = 5
    auto_leave_empty_minutes: float = 5
    transcription_lag_alert_seconds: float = 30
    transcript_retention_days: int = 30
    stale_page_days: int = 60


class DiscordConfig(_Strict):
    token: str
    guild_id: str
    node: str = "node"
    connector_dir: Path | None = None


class TranscriberRole(_Strict):
    provider: Literal["mlx-whisper", "faster-whisper", "openai-compatible", "fake"]
    model: str
    base_url: str | None = None
    api_key: str | None = None
    device: str = "auto"
    compute_type: str = "int8"
    beam_size: int = Field(1, ge=1)


class TranscriptionConfig(_Strict):
    language: str | None = None
    workers: int = Field(2, ge=1)
    live: TranscriberRole
    final: TranscriberRole | None = None
    hallucination_phrases: list[str] = Field(default_factory=list)
    min_utterance_seconds: float = Field(0.4, ge=0)
    max_no_speech_prob: float = Field(0.6, ge=0, le=1)
    min_voiced_seconds: float = Field(0.2, ge=0)
    min_avg_logprob: float | None = -1.0
    vocabulary_max_chars: int = Field(600, ge=0)


class AppConfig(_Strict):
    agent_names: list[str] = Field(default_factory=lambda: ["agent"])
    data_dir: Path = Path("~/.local/share/kb-meeting-agent")
    llm: LLMConfig
    knowledge_bases: dict[str, KbConfig]
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    discord: DiscordConfig | None = None
    transcription: TranscriptionConfig | None = None


def load_config(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = AppConfig.model_validate(_substitute(raw))
    config.data_dir = config.data_dir.expanduser()
    return config
