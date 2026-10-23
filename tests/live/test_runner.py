import asyncio
import os
import sys
from pathlib import Path

from kb_meeting_agent.config import AppConfig
from kb_meeting_agent.live.runner import ConnectorProcess, connector_command, connector_env, run

FAKE = Path(__file__).with_name("fake_connector.py")


def config(tmp_path, kb_origin=None):
    return AppConfig.model_validate(
        {
            "data_dir": str(tmp_path / "data"),
            "llm": {
                role: {"provider": "fake", "model": "fake"}
                for role in ("fast", "strong", "embedding")
            },
            "projects": {
                "test": {
                    "repos": {
                        "kb": {
                            "repo": "acme/kb",
                            "clone_url": str(kb_origin or tmp_path),
                            "tags": ["KnowledgeBase"],
                        }
                    }
                }
            },
            "discord": {"token": "discord-token", "guild_id": "1"},
            "transcription": {
                "live": {"provider": "fake", "model": "fake"},
                "min_voiced_seconds": 0,
            },
        }
    )


async def test_connector_is_restarted_with_backoff(tmp_path):
    marker = tmp_path / "runs"
    code = f"open({str(marker)!r}, 'a').write('x')"
    process = ConnectorProcess([sys.executable, "-c", code], dict(os.environ), backoff_initial=0.01)
    stop = asyncio.Event()
    task = asyncio.create_task(process.run(stop))
    await asyncio.sleep(0.8)
    stop.set()
    await task
    assert len(marker.read_text()) >= 2


async def test_a_connector_that_cannot_start_is_retried(tmp_path, caplog):
    process = ConnectorProcess([str(tmp_path / "missing-node")], {}, backoff_initial=0.01)
    stop = asyncio.Event()
    task = asyncio.create_task(process.run(stop))
    await asyncio.sleep(0.2)
    stop.set()
    await task  # the supervisor is still alive: it did not die on the first failure
    assert process.runs >= 2
    assert "connector could not be started" in caplog.text


def test_connector_command_and_minimal_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    cfg = config(tmp_path)
    command = connector_command(cfg)
    assert command[0] == "node" and command[1].endswith("connector-discord/src/index.js")
    env = connector_env("ws://127.0.0.1:1", "s", cfg)
    assert env["KBMA_CORE_URL"] == "ws://127.0.0.1:1" and env["DISCORD_TOKEN"] == "discord-token"
    assert env["DISCORD_GUILD_ID"] == "1"
    assert "ANTHROPIC_API_KEY" not in env


async def test_run_accepts_the_connector(tmp_path):
    seen = []
    stop = asyncio.Event()

    def observe(kind, payload):
        seen.append((kind, payload))
        if kind == "message":
            stop.set()

    await asyncio.wait_for(
        run(config(tmp_path), connector=[sys.executable, str(FAKE)], stop=stop, observe=observe), 15
    )
    assert seen[0][0] == "connected"
    assert seen[1] == ("message", {"type": "error", "message": "token=discord-token"})


async def test_connector_runs_in_its_own_process_group(tmp_path):
    marker = tmp_path / "pgid"
    code = f"import os; open({str(marker)!r}, 'w').write(str(os.getpgid(0)))"
    process = ConnectorProcess([sys.executable, "-c", code], dict(os.environ), backoff_initial=5)
    stop = asyncio.Event()
    task = asyncio.create_task(process.run(stop))
    for _ in range(100):
        if marker.exists() and marker.read_text():
            break
        await asyncio.sleep(0.05)
    stop.set()
    await task
    assert int(marker.read_text()) != os.getpgid(0)


async def test_shutdown_closes_the_meeting_while_the_connector_is_still_running(
    tmp_path, kb_origin, monkeypatch
):
    log = tmp_path / "connector.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    stop = asyncio.Event()

    def observe(kind, payload):
        if kind == "message" and payload["type"] == "stats":
            stop.set()

    connector = [
        sys.executable,
        str(Path(__file__).with_name("fake_meeting_connector.py")),
        str(log),
    ]
    await asyncio.wait_for(
        run(config(tmp_path, kb_origin), connector=connector, stop=stop, observe=observe), 30
    )
    received = log.read_text(encoding="utf-8").split()
    assert "join" in received and "leave" in received
    # The minutes link is posted after leaving: the connector must still be alive by then.
    assert "send" in received[received.index("leave") :]
