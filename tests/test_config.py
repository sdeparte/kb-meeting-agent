from pathlib import Path

import pytest
from pydantic import ValidationError

from kb_meeting_agent.config import ConfigError, load_config

CONFIG = """
agent_names: [scribe]
data_dir: {data_dir}
llm:
  fast: {{provider: openai-compatible, base_url: "http://localhost:11434/v1", model: qwen3:14b}}
  strong: {{provider: anthropic, model: claude-opus-5-5, api_key: "${{TEST_ANTHROPIC_KEY}}", effort: high}}
  embedding: {{provider: openai-compatible, base_url: "http://localhost:11434/v1", model: bge-m3}}
knowledge_bases:
  demo:
    repo: acme/kb
    token: "${{TEST_GITHUB_TOKEN}}"
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
    assert cfg.knowledge_bases["demo"].token == "ghp-test"
    assert cfg.knowledge_bases["demo"].base_branch == "main"
    assert cfg.defaults.intervention_level == "contradictions"
    assert cfg.defaults.contradiction_min_confidence == 0.8
    assert cfg.agent_names == ["scribe"]


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
