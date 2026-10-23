from kb_meeting_agent.live.audio import (
    BYTES_PER_MS,
    MAX_UTTERANCE_MS,
    UtteranceAssembler,
    speaker_file_id,
)
from kb_meeting_agent.live.protocol import AudioFrame
from kb_meeting_agent.transcription.base import read_wav


def frame(user, t, ms=20):
    return AudioFrame(user, t, bytes(BYTES_PER_MS * ms))


def test_utterance_is_written_as_wav(tmp_path):
    assembler = UtteranceAssembler(tmp_path)
    assembler.start("1", "Alice", 1000)
    for i in range(50):
        assembler.add(frame("1", 1000 + i * 20))
    utterance = assembler.end("1", 2000)
    assert (utterance.index, utterance.speaker_name, utterance.start_ms, utterance.end_ms) == (
        0,
        "Alice",
        1000,
        2000,
    )
    assert utterance.duration_s == 1.0
    assert len(read_wav(utterance.path)) == BYTES_PER_MS * 1000
    assert utterance.path.name == "00000-1.wav"
    assert utterance.record()["file"] == "00000-1.wav"
    assert assembler.next_index == 1


def test_frames_without_start_and_empty_utterances_are_dropped(tmp_path):
    assembler = UtteranceAssembler(tmp_path)
    assert assembler.add(frame("1", 0)) is None
    assembler.start("1", "Alice", 0)
    assert assembler.end("1", 10) is None


def test_long_utterance_rolls_over(tmp_path):
    assembler = UtteranceAssembler(tmp_path)
    assembler.start("1", "Alice", 0)
    rolled = [u for i in range(1600) if (u := assembler.add(frame("1", i * 20)))]
    assert len(rolled) == 1
    assert rolled[0].end_ms - rolled[0].start_ms <= MAX_UTTERANCE_MS
    rest = assembler.end("1", 32_000)
    assert rest.start_ms == rolled[0].end_ms


def test_opt_out_drops_audio_and_close_all_flushes(tmp_path):
    assembler = UtteranceAssembler(tmp_path, next_index=7)
    assembler.start("1", "Alice", 0)
    assembler.add(frame("1", 0))
    assembler.start("2", "Bob", 0)
    assembler.add(frame("2", 0))
    assembler.opt_out("2")
    assembler.start("2", "Bob", 100)
    assert assembler.add(frame("2", 100)) is None
    flushed = assembler.close_all(500)
    assert [u.speaker_id for u in flushed] == ["1"]
    assert flushed[0].index == 7


def test_speaker_ids_that_are_not_safe_file_names_are_hashed(tmp_path):
    assembler = UtteranceAssembler(tmp_path)
    speaker = "spaces/abc/participants/../*"
    assembler.start(speaker, "Alice", 0)
    assembler.add(AudioFrame(speaker, 0, b"\x00\x01" * 100))
    utterance = assembler.end(speaker, 1000)
    assert utterance.path.parent == tmp_path
    assert utterance.path.name == f"00000-{speaker_file_id(speaker)}.wav"
    assert speaker_file_id(speaker).isalnum()
    assert speaker_file_id("U0123ABCD") == "U0123ABCD"
