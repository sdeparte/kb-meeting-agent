"""Connector <-> core protocol, version 3. Mirrored by every connector-*/src/protocol.js.

Platform-neutral: ids (users, channels, interactions) are opaque strings chosen by the
connector, such as a Discord snowflake, a Slack user id or a Meet participant resource name.
A user has one id: the `user_id` of audio frames and `speaking` is the `user.id` of their
commands, buttons and modals, which opt-out relies on.

Version 3: the connector's `hello` may carry `capabilities` (`buttons: false` when it cannot
show buttons); the core sends the command catalog in a `commands` message once connected
(each command's slash path and chat `words`), and the connector forwards chat lines starting
with `!` as `chat` messages. A connector that cannot rejoin a call on its own reports the
`voice_state` `needs_invite`: the core asks the participants to invite the agent again.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 3
# Exit code of a connector refusing its env (a missing credential): it is not restarted
CONFIG_ERROR_EXIT = 78
AUDIO_FRAME = 0x01
# kind, timestamp, length of the user id; then the id (UTF-8), then the PCM
_HEADER = struct.Struct(">BQB")
HEADER_SIZE = _HEADER.size
MAX_ID_BYTES = 255


class ProtocolError(Exception):
    """A frame or message that does not follow the protocol."""


@dataclass(frozen=True)
class AudioFrame:
    """16 kHz mono 16-bit little-endian PCM from one speaker, stamped by the connector."""

    user_id: str
    timestamp_ms: int
    pcm: bytes


def encode_audio_frame(frame: AudioFrame) -> bytes:
    user_id = frame.user_id.encode("utf-8")
    if not 0 < len(user_id) <= MAX_ID_BYTES:
        raise ProtocolError(f"user ids are 1 to {MAX_ID_BYTES} bytes")
    return _HEADER.pack(AUDIO_FRAME, frame.timestamp_ms, len(user_id)) + user_id + frame.pcm


def decode_audio_frame(data: bytes) -> AudioFrame:
    if len(data) < HEADER_SIZE:
        raise ProtocolError("audio frame too short")
    kind, timestamp_ms, id_length = _HEADER.unpack_from(data)
    if kind != AUDIO_FRAME:
        raise ProtocolError(f"unknown binary frame kind {kind}")
    end = HEADER_SIZE + id_length
    if id_length == 0 or len(data) < end:
        raise ProtocolError("audio frame without a whole user id")
    try:
        user_id = bytes(data[HEADER_SIZE:end]).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("user id is not UTF-8") from exc
    return AudioFrame(user_id, timestamp_ms, bytes(data[end:]))


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
