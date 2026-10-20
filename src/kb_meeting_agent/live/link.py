from __future__ import annotations

import asyncio
import hmac
import logging
from typing import Any

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from kb_meeting_agent.live.protocol import (
    PROTOCOL_VERSION,
    ProtocolError,
    decode_audio_frame,
    decode_message,
    encode_message,
)

log = logging.getLogger(__name__)

UNAUTHORIZED = 4001
HELLO_TIMEOUT_S = 5


class ConnectorLink:
    """Local WebSocket server for one connector, authenticated by a shared secret."""

    def __init__(self, secret: str, host: str = "127.0.0.1", port: int = 0) -> None:
        self._secret = secret
        self._host = host
        self._port = port
        self._server: Server | None = None
        self._ws: ServerConnection | None = None
        self.url = ""
        self.events: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

    async def start(self) -> str:
        self._server = await serve(self._handle, self._host, self._port, max_size=2**20)
        port = self._server.sockets[0].getsockname()[1]
        self.url = f"ws://{self._host}:{port}"
        return self.url

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def send(self, type_: str, **fields: Any) -> bool:
        ws = self._ws
        if ws is None:
            return False
        try:
            await ws.send(encode_message(type_, **fields))
        except ConnectionClosed:
            return False
        return True

    async def _handle(self, ws: ServerConnection) -> None:
        hello = await self._authenticate(ws)
        if hello is None:
            await ws.close(UNAUTHORIZED, "unauthorized")
            return
        if self._ws is not None:
            await self._ws.close(1000, "replaced by a new connector")
        self._ws = ws
        await self.events.put(("connected", hello))
        try:
            async for data in ws:
                try:
                    if isinstance(data, bytes):
                        await self.events.put(("audio", decode_audio_frame(data)))
                    else:
                        await self.events.put(("message", decode_message(data)))
                except ProtocolError as exc:
                    log.warning("ignoring an invalid connector frame: %s", exc)
        except ConnectionClosed:
            pass
        finally:
            if self._ws is ws:
                self._ws = None
                await self.events.put(("disconnected", None))

    async def _authenticate(self, ws: ServerConnection) -> dict[str, Any] | None:
        try:
            first = await asyncio.wait_for(ws.recv(), HELLO_TIMEOUT_S)
            hello = decode_message(first) if isinstance(first, str) else None
        except (TimeoutError, ConnectionClosed, ProtocolError):
            return None
        if (
            hello is None
            or hello["type"] != "hello"
            or hello.get("protocol") != PROTOCOL_VERSION
            or not hmac.compare_digest(str(hello.get("secret", "")), self._secret)
        ):
            return None
        return hello
