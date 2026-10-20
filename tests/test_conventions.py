import pytest

from kb_meeting_agent.conventions import (
    CONVENTIONS_FILE,
    load_conventions,
    load_template,
    render_template,
)


def test_defaults_when_file_is_missing(tmp_path):
    conv = load_conventions(tmp_path)
    assert conv.language == "en"
    assert conv.decisions.dir == "decisions"
    assert conv.decisions.filename == "{number:04d}-{slug}.md"
    assert conv.minutes.dir == "meetings"
    assert conv.statuses == []
    assert conv.decisions.scopes == []


def test_load_file(tmp_path):
    (tmp_path / CONVENTIONS_FILE).write_text(
        """
language: fr
exclude: [maquettes/**]
statuses:
  - {pattern: '[PROD]', meaning: in_production}
decisions:
  default_status: acceptée
  scopes: [client, serveur, les deux]
  index: {file: decisions/README.md, row: '| {number} |'}
minutes:
  dir: reunions
""",
        encoding="utf-8",
    )
    conv = load_conventions(tmp_path)
    assert conv.language == "fr"
    assert conv.statuses[0].meaning == "in_production"
    assert conv.decisions.default_status == "acceptée"
    assert conv.decisions.scopes == ["client", "serveur", "les deux"]
    assert conv.decisions.index.file == "decisions/README.md"
    assert conv.minutes.dir == "reunions"


def test_render_template_formats_known_keys_and_keeps_the_rest():
    out = render_template(
        "# {number:04d} — {title} {unknown} `{a: b}`", {"number": 7, "title": "X"}
    )
    assert out == "# 0007 — X {unknown} `{a: b}`"


def test_load_template_prefers_the_repo_file(tmp_path):
    (tmp_path / "tpl.md").write_text("custom {title}", encoding="utf-8")
    assert load_template(tmp_path, "tpl.md", "decision.md") == "custom {title}"
    assert "{title}" in load_template(tmp_path, None, "decision.md")
    assert "{body}" in load_template(tmp_path, None, "minutes.md")


def test_load_template_refuses_paths_outside_the_kb(tmp_path):
    (tmp_path / "secret.txt").write_text("x", encoding="utf-8")
    repo = tmp_path / "kb"
    repo.mkdir()
    with pytest.raises(ValueError):
        load_template(repo, "../secret.txt", "decision.md")
