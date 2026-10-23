"""Stands in for connector-discord in tests: says hello, reports an error, then waits."""

import asyncio
import json
import os

from websockets.asyncio.client import connect


async def main() -> None:
    async with connect(os.environ["KBMA_CORE_URL"]) as ws:
        await ws.send(
            json.dumps({"type": "hello", "secret": os.environ["KBMA_SECRET"], "protocol": 3})
        )
        await ws.send(
            json.dumps({"type": "error", "message": f"token={os.environ.get('DISCORD_TOKEN')}"})
        )
        await asyncio.sleep(5)


asyncio.run(main())
