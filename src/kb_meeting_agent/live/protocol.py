"""Connector <-> core protocol, version 1. Mirrored by connector-discord/src/protocol.js."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
AUDIO_FRAME = 0x01
_HEADER = struct.Struct(">BQQ")
HEADER_SIZE = _HEADER.size


class ProtocolError(Exception):
    """A frame or message that does not follow the protocol."""


@dataclass(frozen=True)
class AudioFrame:
    """16 kHz mono 16-bit little-endian PCM from one speaker, stamped by the connector."""

    user_id: str
    timestamp_ms: int
    pcm: bytes


def encode_audio_frame(frame: AudioFrame) -> bytes:
    return _HEADER.pack(AUDIO_FRAME, int(frame.user_id), frame.timestamp_ms) + frame.pcm


def decode_audio_frame(data: bytes) -> AudioFrame:
    if len(data) < HEADER_SIZE:
        raise ProtocolError("audio frame too short")
    kind, user_id, timestamp_ms = _HEADER.unpack_from(data)
    if kind != AUDIO_FRAME:
        raise ProtocolError(f"unknown binary frame kind {kind}")
    return AudioFrame(str(user_id), timestamp_ms, bytes(data[HEADER_SIZE:]))


def encode_message(type_: str, **fields: Any) -> str:
    return json.dumps({"type": type_, **fields}, ensure_ascii=False)


def decode_message(text: str) -> dict[str, Any]:
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError("message is not JSON") from exc
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("message has no type")
    return message
