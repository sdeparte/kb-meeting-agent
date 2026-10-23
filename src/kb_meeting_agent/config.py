from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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


KNOWLEDGE_BASE = "KnowledgeBase"
CODE_BASE = "CodeBase"
Tag = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]+$")]


class RepoConfig(_Strict):
    provider: Literal["github"] = "github"  # where the repo is hosted (forges.py)
    repo: str
    base_branch: str = "main"
    token: str | None = None
    clone_url: str | None = None
    language: str | None = None  # KnowledgeBase only: used when .meeting-agent.yml sets none
    tags: list[Tag]
    include: list[str] = Field(default_factory=list)  # CodeBase only
    exclude: list[str] = Field(default_factory=list)  # CodeBase only

    @model_validator(mode="after")
    def _one_role(self) -> RepoConfig:
        roles = {KNOWLEDGE_BASE, CODE_BASE} & set(self.tags)
        if roles == {KNOWLEDGE_BASE, CODE_BASE}:
            raise ValueError(f"{self.repo} cannot be both {KNOWLEDGE_BASE} and {CODE_BASE}")
        if not roles:
            raise ValueError(f"{self.repo} must be tagged {KNOWLEDGE_BASE} or {CODE_BASE}")
        if CODE_BASE not in self.tags and (self.include or self.exclude):
            raise ValueError(f"{self.repo}: include and exclude apply to {CODE_BASE} repos only")
        if KNOWLEDGE_BASE not in self.tags and self.language is not None:
            raise ValueError(f"{self.repo}: language applies to the {KNOWLEDGE_BASE} repo only")
        return self


class ProjectConfig(_Strict):
    repos: dict[str, RepoConfig]

    @model_validator(mode="after")
    def _exactly_one_knowledge_base(self) -> ProjectConfig:
        found = [name for name, repo in self.repos.items() if KNOWLEDGE_BASE in repo.tags]
        if len(found) != 1:
            raise ValueError(
                f"a project needs exactly one {KNOWLEDGE_BASE} repo, found {len(found)}"
            )
        return self

    @property
    def knowledge_base(self) -> tuple[str, RepoConfig]:
        return next((n, r) for n, r in self.repos.items() if KNOWLEDGE_BASE in r.tags)

    @property
    def code_repos(self) -> list[tuple[str, RepoConfig]]:
        return [(n, r) for n, r in self.repos.items() if CODE_BASE in r.tags]


class DefaultsConfig(_Strict):
    intervention_level: InterventionLevel = "contradictions"
    contradiction_min_confidence: float = Field(0.8, ge=0, le=1)
    context_min_interval_minutes: float = 5
    auto_leave_empty_minutes: float = 5
    transcription_lag_alert_seconds: float = 30
    transcript_retention_days: int = 30
    stale_page_days: int = 60


class ConnectorConfig(_Strict):
    """The process that joins meetings on a platform (Discord, Meet, Slack...) for the core.

    The core knows nothing of the platform: it runs `command` and gives it `env`, its
    credentials and settings, plus the local link (KBMA_CORE_URL, KBMA_SECRET).
    """

    name: Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]+$")]
    # Default: [node, <dir>/src/index.js], dir defaulting to connector-<name>/ of this checkout
    command: list[str] | None = None
    node: str = "node"
    dir: Path | None = None
    env: dict[str, str] = Field(default_factory=dict)


# The engines each engine-specific option of TranscriberRole applies to. Adding an engine
# means listing it under the options it reads; it is refused the others.
_ENGINE_OPTIONS: dict[str, tuple[str, ...]] = {
    "base_url": ("openai-compatible",),
    "api_key": ("openai-compatible",),
    "device": ("faster-whisper",),
    "compute_type": ("faster-whisper",),
    "beam_size": ("faster-whisper",),
    "temperature_fallback": ("mlx-whisper", "faster-whisper"),
}


class TranscriberRole(_Strict):
    provider: Literal["mlx-whisper", "faster-whisper", "openai-compatible", "fake"]
    model: str
    base_url: str | None = None
    api_key: str | None = None
    device: str = "auto"
    compute_type: str = "int8"
    beam_size: int = Field(1, ge=1)
    # Decode again at higher temperatures when the text loops or the model is unsure (up to 6
    # decodings of the utterance)
    temperature_fallback: bool = True

    @model_validator(mode="after")
    def _options_of_another_engine(self) -> TranscriberRole:
        for option in sorted(self.model_fields_set & _ENGINE_OPTIONS.keys()):
            engines = _ENGINE_OPTIONS[option]
            if self.provider not in engines:
                raise ValueError(
                    f"{option} has no effect with the {self.provider} provider; "
                    f"only {' and '.join(engines)} read it"
                )
        return self


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
    max_compression_ratio: float | None = Field(2.4, gt=0)
    # hinted before the glossary to the engines that take a prompt
    vocabulary: list[str] = Field(default_factory=list)
    vocabulary_max_chars: int = Field(600, ge=0)


# An empty name would match between any punctuation and a space: every segment would address it.
_AgentName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AgentIdentity(_Strict):
    name: _AgentName = "agent"  # how the agent introduces itself and appears in the minutes
    aliases: list[_AgentName] = Field(default_factory=list)  # other ways to address it

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]


class AppConfig(_Strict):
    agent: AgentIdentity = Field(default_factory=AgentIdentity)
    data_dir: Path = Path("~/.local/share/kb-meeting-agent")
    llm: LLMConfig
    projects: dict[str, ProjectConfig]
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    connector: ConnectorConfig | None = None
    transcription: TranscriptionConfig | None = None


def load_config(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # Before substituting: a validation error would echo the section, token included
    if isinstance(raw, dict) and "discord" in raw:
        raise ConfigError(
            "the discord section is now `connector: {name: discord, env: {DISCORD_TOKEN: ..., "
            "DISCORD_GUILD_ID: ...}}`; connector_dir is now dir (docs/configuration.md#connector)"
        )
    config = AppConfig.model_validate(_substitute(raw))
    config.data_dir = config.data_dir.expanduser()
    return config
