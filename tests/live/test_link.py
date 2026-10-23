import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from kb_meeting_agent.live.link import ConnectorLink
from kb_meeting_agent.live.protocol import PROTOCOL_VERSION, AudioFrame, encode_audio_frame


@pytest.fixture
async def link():
    server = ConnectorLink("s3cret")
    await server.start()
    yield server
    await server.close()


def hello(secret="s3cret", protocol=PROTOCOL_VERSION):
    return json.dumps({"type": "hello", "secret": secret, "protocol": protocol})


async def next_event(link):
    return await asyncio.wait_for(link.events.get(), 2)


async def test_wrong_secret_is_rejected(link):
    async with connect(link.url) as ws:
        await ws.send(hello(secret="nope"))
        with pytest.raises(ConnectionClosed) as closed:
            await ws.recv()
    assert closed.value.rcvd.code == 4001
    assert link.events.empty()


async def test_messages_audio_and_replies(link):
    async with connect(link.url) as ws:
        await ws.send(hello())
        kind, payload = await next_event(link)
        assert kind == "connected" and payload["protocol"] == PROTOCOL_VERSION
        await ws.send(json.dumps({"type": "members", "members": []}))
        assert await next_event(link) == ("message", {"type": "members", "members": []})
        frame = AudioFrame("42", 1000, b"\x00\x01")
        await ws.send(encode_audio_frame(frame))
        assert await next_event(link) == ("audio", frame)
        await ws.send("garbage")  # ignored, the link stays open
        assert await link.send("join", voice_channel_id="1", text_channel_id="2")
        assert json.loads(await ws.recv()) == {
            "type": "join",
            "voice_channel_id": "1",
            "text_channel_id": "2",
        }
    assert await next_event(link) == ("disconnected", None)
    assert not await link.send("leave")
