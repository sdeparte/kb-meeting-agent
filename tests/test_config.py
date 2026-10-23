from pathlib import Path

import pytest
from pydantic import ValidationError

from kb_meeting_agent.config import ConfigError, ProjectConfig, load_config

CONFIG = """
agent:
  name: Breach
  aliases: [brèche]
data_dir: {data_dir}
llm:
  fast: {{provider: openai-compatible, base_url: "http://localhost:11434/v1", model: qwen3:14b}}
  strong: {{provider: anthropic, model: claude-opus-5-5, api_key: "${{TEST_ANTHROPIC_KEY}}", effort: high}}
  embedding: {{provider: openai-compatible, base_url: "http://localhost:11434/v1", model: bge-m3}}
projects:
  demo:
    repos:
      kb:
        repo: acme/kb
        tags: [KnowledgeBase]
        token: "${{TEST_GITHUB_TOKEN}}"
      back:
        repo: acme/back
        tags: [CodeBase, BackEnd]
        exclude: ["fixtures/**"]
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_substitutes_env_and_applies_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "sk-test")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "ghp-test")
    cfg = load_config(write(tmp_path, CONFIG.format(data_dir=tmp_path / "data")))
    assert cfg.llm.strong.api_key == "sk-test"
    assert cfg.llm.strong.effort == "high"
    name, kb = cfg.projects["demo"].knowledge_base
    assert name == "kb" and kb.token == "ghp-test" and kb.base_branch == "main"
    [(code_name, code)] = cfg.projects["demo"].code_repos
    assert code_name == "back" and code.tags == ["CodeBase", "BackEnd"]
    assert code.exclude == ["fixtures/**"]
    assert cfg.defaults.intervention_level == "contradictions"
    assert cfg.defaults.contradiction_min_confidence == 0.8
    assert cfg.agent.name == "Breach"
    assert cfg.agent.names == ["Breach", "brèche"]


def test_missing_env_var_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_ANTHROPIC_KEY", raising=False)
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    with pytest.raises(ConfigError, match="TEST_ANTHROPIC_KEY"):
        load_config(write(tmp_path, CONFIG.format(data_dir=tmp_path)))


def test_unknown_key_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    text = CONFIG.format(data_dir=tmp_path) + "\nunexpected: 1\n"
    with pytest.raises(ValidationError):
        load_config(write(tmp_path, text))


def test_data_dir_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    cfg = load_config(write(tmp_path, CONFIG.format(data_dir="~/kbma")))
    assert not str(cfg.data_dir).startswith("~")


def test_anthropic_embedding_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    text = CONFIG.format(data_dir=tmp_path).replace(
        '{provider: openai-compatible, base_url: "http://localhost:11434/v1", model: bge-m3}',
        "{provider: anthropic, model: claude-opus-5-5}",
    )
    with pytest.raises(ValidationError, match="embedding"):
        load_config(write(tmp_path, text))


LIVE = """
discord:
  token: "${TEST_DISCORD_TOKEN}"
  guild_id: "123456789012345678"
transcription:
  language: fr
  live: {provider: mlx-whisper, model: mlx-community/whisper-large-v3-turbo}
  final: {provider: faster-whisper, model: large-v3, device: cpu, beam_size: 5}
  hallucination_phrases: ["Abonnez-vous"]
"""


def test_live_sections(tmp_path, monkeypatch):
    for name in ("TEST_ANTHROPIC_KEY", "TEST_GITHUB_TOKEN", "TEST_DISCORD_TOKEN"):
        monkeypatch.setenv(name, "x")
    cfg = load_config(write(tmp_path, CONFIG.format(data_dir=tmp_path) + LIVE))
    assert cfg.discord.guild_id == "123456789012345678"
    assert cfg.discord.node == "node"
    assert cfg.transcription.live.provider == "mlx-whisper"
    assert cfg.transcription.final.beam_size == 5
    assert cfg.transcription.workers == 2
    assert cfg.transcription.hallucination_phrases == ["Abonnez-vous"]


def test_live_sections_are_optional(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    cfg = load_config(write(tmp_path, CONFIG.format(data_dir=tmp_path)))
    assert cfg.discord is None and cfg.transcription is None


def test_unknown_transcriber_is_rejected(tmp_path, monkeypatch):
    for name in ("TEST_ANTHROPIC_KEY", "TEST_GITHUB_TOKEN", "TEST_DISCORD_TOKEN"):
        monkeypatch.setenv(name, "x")
    text = CONFIG.format(data_dir=tmp_path) + LIVE.replace(
        "provider: mlx-whisper", "provider: vosk"
    )
    with pytest.raises(ValidationError):
        load_config(write(tmp_path, text))


def test_temperature_fallback_is_rejected_where_it_has_no_effect(tmp_path, monkeypatch):
    for name in ("TEST_ANTHROPIC_KEY", "TEST_GITHUB_TOKEN", "TEST_DISCORD_TOKEN"):
        monkeypatch.setenv(name, "x")
    text = CONFIG.format(data_dir=tmp_path) + LIVE.replace(
        "{provider: mlx-whisper, model: mlx-community/whisper-large-v3-turbo}",
        '{provider: openai-compatible, base_url: "http://localhost:8000/v1", model: whisper, '
        "temperature_fallback: false}",
    )
    with pytest.raises(ValidationError, match="temperature_fallback"):
        load_config(write(tmp_path, text))


def test_agent_names_is_no_longer_accepted(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    text = CONFIG.format(data_dir=tmp_path).replace(
        "agent:\n  name: Breach\n  aliases: [brèche]\n", "agent_names: [scribe]\n"
    )
    with pytest.raises(ValidationError, match="agent_names"):
        load_config(write(tmp_path, text))


def test_agent_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    text = CONFIG.format(data_dir=tmp_path).replace(
        "agent:\n  name: Breach\n  aliases: [brèche]\n", ""
    )
    assert load_config(write(tmp_path, text)).agent.names == ["agent"]


@pytest.mark.parametrize(
    "agent", ["agent:\n  name: ''\n", "agent:\n  name: Otis\n  aliases: ['  ']\n"]
)
def test_an_empty_agent_name_is_rejected(tmp_path, monkeypatch, agent):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    text = CONFIG.format(data_dir=tmp_path).replace(
        "agent:\n  name: Breach\n  aliases: [brèche]\n", agent
    )
    with pytest.raises(ValidationError):
        load_config(write(tmp_path, text))


@pytest.mark.parametrize(
    ("repos", "message"),
    [
        ({"a": {"repo": "x/a", "tags": ["CodeBase"]}}, "exactly one KnowledgeBase"),
        (
            {
                "a": {"repo": "x/a", "tags": ["KnowledgeBase"]},
                "b": {"repo": "x/b", "tags": ["KnowledgeBase"]},
            },
            "exactly one KnowledgeBase",
        ),
        ({"a": {"repo": "x/a", "tags": ["KnowledgeBase", "CodeBase"]}}, "both"),
        (
            {
                "a": {"repo": "x/a", "tags": ["KnowledgeBase"]},
                "b": {"repo": "x/b", "tags": ["BackEnd"]},
            },
            "KnowledgeBase or CodeBase",
        ),
        ({"a": {"repo": "x/a", "tags": ["KnowledgeBase"], "include": ["src/**"]}}, "include"),
        ({"a": {"repo": "x/a", "tags": ["KnowledgeBase", "bad tag"]}}, "pattern"),
        (
            {
                "a": {"repo": "x/a", "tags": ["KnowledgeBase"]},
                "b": {"repo": "x/b", "tags": ["CodeBase"], "language": "fr"},
            },
            "language",
        ),
    ],
)
def test_project_rules(repos, message):
    with pytest.raises(ValidationError, match=message):
        ProjectConfig.model_validate({"repos": repos})


def test_knowledge_bases_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_ANTHROPIC_KEY", "x")
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "x")
    text = CONFIG.format(data_dir=tmp_path) + "\nknowledge_bases: {}\n"
    with pytest.raises(ValidationError, match="knowledge_bases"):
        load_config(write(tmp_path, text))
