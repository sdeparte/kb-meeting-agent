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
knowledge_bases:
  test: {{repo: acme/kb, clone_url: "{kb_origin}"}}
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
        ["replay", str(transcript), "--config", str(config), "--kb", "test", "--out", str(out)]
    )
    assert code == 0
    written = [p.relative_to(out).as_posix() for p in out.rglob("*.md")]
    assert any(p.startswith("meetings/") and p.endswith("-replay.md") for p in written)
    assert any(p.endswith("PR.md") for p in written)
    assert (out / "transcript.jsonl").exists()
    assert "Meeting minutes:" in capsys.readouterr().out


def test_unknown_kb_is_an_error(tmp_path, kb_origin, capsys):
    config = tmp_path / "config.yml"
    config.write_text(
        """
llm:
  fast: {provider: fake, model: fake}
  strong: {provider: fake, model: fake}
  embedding: {provider: fake, model: fake}
knowledge_bases: {}
""",
        encoding="utf-8",
    )
    transcript = tmp_path / "in.jsonl"
    transcript.write_text("", encoding="utf-8")
    assert main(["replay", str(transcript), "--config", str(config), "--kb", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_run_needs_discord_and_transcription(tmp_path, capsys):
    config = tmp_path / "config.yml"
    config.write_text(
        """
llm:
  fast: {provider: fake, model: fake}
  strong: {provider: fake, model: fake}
  embedding: {provider: fake, model: fake}
knowledge_bases: {}
""",
        encoding="utf-8",
    )
    assert main(["run", "--config", str(config)]) == 2
    assert "discord" in capsys.readouterr().err
