"""Stands in for connector-discord: starts a meeting, then logs what the core sends it."""

import asyncio
import json
import os
import struct
import sys
import time

from websockets.asyncio.client import connect


async def main() -> None:
    log = open(sys.argv[1], "a", encoding="utf-8")
    async with connect(os.environ["KBMA_CORE_URL"]) as ws:
        await ws.send(
            json.dumps({"type": "hello", "secret": os.environ["KBMA_SECRET"], "protocol": 1})
        )
        await ws.send(
            json.dumps(
                {
                    "type": "command",
                    "interaction_id": "i1",
                    "name": "meeting_start",
                    "options": {"project": "test"},
                    "user": {"id": "u1", "name": "Alice"},
                    "text_channel_id": "t1",
                    "voice_channel_id": "v1",
                }
            )
        )
        async for raw in ws:
            message = json.loads(raw)
            log.write(message["type"] + "\n")
            log.flush()
            if message["type"] == "reply":
                now = int(time.time() * 1000)
                await ws.send(
                    json.dumps(
                        {
                            "type": "utterance_start",
                            "user_id": "42",
                            "speaker_name": "Alice",
                            "t": now,
                        }
                    )
                )
                await ws.send(struct.pack(">BQQ", 1, 42, now) + bytes(32 * 1000))
                await ws.send(
                    json.dumps({"type": "utterance_end", "user_id": "42", "t": now + 1000})
                )
                await ws.send(json.dumps({"type": "stats", "decrypt_errors": 0, "users": []}))


asyncio.run(main())
