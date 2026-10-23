import json

from kb_meeting_agent.cli import main


def test_replay_dry_run_writes_minutes(tmp_path, kb_origin, capsys):
    config = tmp_path / "config.yml"
    config.write_text(
        f"""
agent:
  name: Scribe
data_dir: {tmp_path / "data"}
llm:
  fast: {{provider: fake, model: fake}}
  strong: {{provider: fake, model: fake}}
  embedding: {{provider: fake, model: fake}}
projects:
  test:
    repos:
      kb: {{repo: acme/kb, clone_url: "{kb_origin}", tags: [KnowledgeBase]}}
""",
        encoding="utf-8",
    )
    transcript = tmp_path / "in.jsonl"
    transcript.write_text(
        "\n".join(
            json.dumps(
                {
                    "speaker_id": "a",
                    "speaker_name": "Alice",
                    "start": s,
                    "end": s + 5,
                    "text": f"t{s}",
                }
            )
            for s in (0, 40)
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    code = main(
        ["replay", str(transcript), "--config", str(config), "--project", "test", "--out", str(out)]
    )
    assert code == 0
    written = [p.relative_to(out).as_posix() for p in out.rglob("*.md")]
    assert any(p.startswith("meetings/") and p.endswith("-replay.md") for p in written)
    assert any(p.endswith("PR.md") for p in written)
    assert (out / "transcript.jsonl").exists()
    assert "Meeting minutes:" in capsys.readouterr().out


def test_unknown_project_is_an_error(tmp_path, kb_origin, capsys):
    config = tmp_path / "config.yml"
    config.write_text(
        """
llm:
  fast: {provider: fake, model: fake}
  strong: {provider: fake, model: fake}
  embedding: {provider: fake, model: fake}
projects: {}
""",
        encoding="utf-8",
    )
    transcript = tmp_path / "in.jsonl"
    transcript.write_text("", encoding="utf-8")
    assert main(["replay", str(transcript), "--config", str(config), "--project", "nope"]) == 2
    assert "unknown project: nope" in capsys.readouterr().err


def test_run_needs_discord_and_transcription(tmp_path, capsys):
    config = tmp_path / "config.yml"
    config.write_text(
        """
llm:
  fast: {provider: fake, model: fake}
  strong: {provider: fake, model: fake}
  embedding: {provider: fake, model: fake}
projects: {}
""",
        encoding="utf-8",
    )
    assert main(["run", "--config", str(config)]) == 2
    assert "discord" in capsys.readouterr().err


def project_config(tmp_path, kb_origin, code_url):
    config = tmp_path / "config.yml"
    config.write_text(
        f"""
data_dir: {tmp_path / "data"}
llm:
  fast: {{provider: fake, model: fake}}
  strong: {{provider: fake, model: fake}}
  embedding: {{provider: fake, model: fake}}
projects:
  test:
    repos:
      kb: {{repo: acme/kb, clone_url: "{kb_origin}", tags: [KnowledgeBase]}}
      back: {{repo: acme/back, clone_url: "{code_url}", tags: [CodeBase, BackEnd]}}
""",
        encoding="utf-8",
    )
    return config


def test_index_command_indexes_every_repo(tmp_path, kb_origin, code_origin, capsys):
    config = project_config(tmp_path, kb_origin, code_origin)
    assert main(["index", "--config", str(config), "--project", "test"]) == 0
    out = capsys.readouterr().out
    assert "indexed kb:" in out and "indexed back: 2 files" in out


def test_index_command_reports_an_unavailable_repo(tmp_path, kb_origin, capsys):
    config = project_config(tmp_path, kb_origin, tmp_path / "nonexistent")
    assert main(["index", "--config", str(config), "--project", "test"]) == 1
    captured = capsys.readouterr()
    assert "indexed kb:" in captured.out and "back:" in captured.err


def test_index_command_goes_on_after_any_repository_error(
    tmp_path, kb_origin, code_origin, capsys, monkeypatch
):
    from kb_meeting_agent.kb.code import GitCodeRepository

    async def failing_sync(self):
        raise RuntimeError("embedding server unreachable")

    monkeypatch.setattr(GitCodeRepository, "sync", failing_sync)
    config = project_config(tmp_path, kb_origin, code_origin)
    assert main(["index", "--config", str(config), "--project", "test"]) == 1
    captured = capsys.readouterr()
    assert "indexed kb:" in captured.out
    assert "back: embedding server unreachable" in captured.err
