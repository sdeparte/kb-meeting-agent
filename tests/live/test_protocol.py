import pytest

from kb_meeting_agent.live.protocol import (
    HEADER_SIZE,
    AudioFrame,
    ProtocolError,
    decode_audio_frame,
    decode_message,
    encode_audio_frame,
    encode_message,
)


def test_audio_frame_round_trip_with_a_large_snowflake():
    frame = AudioFrame("18446744073709551615", 1_760_000_000_123, b"\x01\x02\x03\x04")
    data = encode_audio_frame(frame)
    assert len(data) == HEADER_SIZE + 4 and data[0] == 1
    assert decode_audio_frame(data) == frame


@pytest.mark.parametrize("data", [b"", b"\x02" + bytes(16), b"\x01" + bytes(5)])
def test_bad_audio_frames(data):
    with pytest.raises(ProtocolError):
        decode_audio_frame(data)


def test_messages():
    text = encode_message("send", text="Décision détectée", buttons=[])
    assert decode_message(text) == {"type": "send", "text": "Décision détectée", "buttons": []}
    for bad in ("not json", "[]", '{"no": "type"}', '{"type": 3}'):
        with pytest.raises(ProtocolError):
            decode_message(bad)
