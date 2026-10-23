import pytest

from kb_meeting_agent.live.protocol import (
    HEADER_SIZE,
    PROTOCOL_VERSION,
    AudioFrame,
    ProtocolError,
    decode_audio_frame,
    decode_message,
    encode_audio_frame,
    encode_message,
)


@pytest.mark.parametrize(
    "user_id",
    [
        "18446744073709551615",  # Discord snowflake
        "U0123ABCD",  # Slack
        "spaces/abc-defg-hij/participants/9f8e7d",  # Meet
        "Zoé",
    ],
)
def test_audio_frame_round_trip_with_any_speaker_id(user_id):
    frame = AudioFrame(user_id, 1_760_000_000_123, b"\x01\x02\x03\x04")
    data = encode_audio_frame(frame)
    assert len(data) == HEADER_SIZE + len(user_id.encode()) + 4 and data[0] == 1
    assert decode_audio_frame(data) == frame


def test_protocol_version():
    assert PROTOCOL_VERSION == 3


@pytest.mark.parametrize("user_id", ["", "x" * 256])
def test_speaker_ids_are_one_to_255_bytes(user_id):
    with pytest.raises(ProtocolError):
        encode_audio_frame(AudioFrame(user_id, 0, b""))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x02" + bytes(9) + b"\x01a",  # unknown kind
        b"\x01" + bytes(5),  # short header
        b"\x01" + bytes(8) + b"\x05ab",  # id longer than the frame
        b"\x01" + bytes(8) + b"\x00",  # empty id
        b"\x01" + bytes(8) + b"\x01\xff",  # id not UTF-8
    ],
)
def test_bad_audio_frames(data):
    with pytest.raises(ProtocolError):
        decode_audio_frame(data)


def test_messages():
    text = encode_message("send", text="Décision détectée", buttons=[])
    assert decode_message(text) == {"type": "send", "text": "Décision détectée", "buttons": []}
    for bad in ("not json", "[]", '{"no": "type"}', '{"type": 3}'):
        with pytest.raises(ProtocolError):
            decode_message(bad)
