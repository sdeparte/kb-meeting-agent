import time

from kb_meeting_agent.live.audio import BYTES_PER_MS, Utterance
from kb_meeting_agent.live.pipeline import TranscriptionPipeline
from kb_meeting_agent.transcription.base import TranscriptionResult, write_wav
from kb_meeting_agent.transcription.filtering import HallucinationFilter


class SlowFirst:
    """Answers with the utterance's length in ms; the first call is slow."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, *, language, prompt):
        self.calls += 1
        if self.calls == 1:
            time.sleep(0.2)
        return TranscriptionResult(f"{len(audio) // 16} ms")


def utterance(tmp_path, index, speaker, start_ms, ms):
    path = tmp_path / f"{index}.wav"
    write_wav(path, bytes(BYTES_PER_MS * ms))
    return Utterance(index, speaker, speaker.upper(), start_ms, start_ms + ms, path)


def make(tmp_path, transcriber, clock=lambda: 10_000):
    received = []

    async def on_segment(segment):
        received.append(segment)

    pipeline = TranscriptionPipeline(
        transcriber,
        language="fr",
        prompt="BIO-SCAN",
        cleaner=HallucinationFilter([], min_seconds=0.4, max_no_speech_prob=0.6),
        workers=2,
        meeting_start_ms=1_000,
        on_segment=on_segment,
        clock_ms=clock,
    )
    return pipeline, received


async def test_order_is_kept_per_speaker(tmp_path):
    pipeline, received = make(tmp_path, SlowFirst())
    pipeline.submit(utterance(tmp_path, 0, "a", 2_000, 1000))  # slow
    pipeline.submit(utterance(tmp_path, 1, "a", 3_000, 500))
    pipeline.submit(utterance(tmp_path, 2, "b", 2_500, 700))
    await pipeline.drain()
    a_texts = [s.text for s in received if s.speaker_id == "a"]
    assert a_texts == ["1000 ms", "500 ms"]
    first = next(s for s in received if s.text == "1000 ms")
    assert (first.start, first.end, first.speaker_name) == (1.0, 2.0, "A")


async def test_filtered_utterances_produce_no_segment(tmp_path):
    class Silent:
        def transcribe(self, audio, *, language, prompt):
            return TranscriptionResult("Merci d'avoir regardé !")

    pipeline, received = make(tmp_path, Silent())
    pipeline.submit(utterance(tmp_path, 0, "a", 2_000, 1000))
    pipeline.submit(utterance(tmp_path, 1, "a", 4_000, 100))  # too short
    await pipeline.drain()
    assert received == []


async def test_silent_utterances_are_not_transcribed(tmp_path):
    transcriber = SlowFirst()
    received = []

    async def on_segment(segment):
        received.append(segment)

    pipeline = TranscriptionPipeline(
        transcriber,
        language="fr",
        prompt="",
        cleaner=HallucinationFilter([], 0.4, 0.6, min_voiced_seconds=0.2),
        workers=1,
        meeting_start_ms=1_000,
        on_segment=on_segment,
        clock_ms=lambda: 10_000,
    )
    pipeline.submit(utterance(tmp_path, 0, "a", 2_000, 1000))  # all zeros
    await pipeline.drain()
    assert transcriber.calls == 0 and received == []
    assert pipeline.lag_s == 7.0


async def test_short_utterances_are_not_transcribed(tmp_path):
    transcriber = SlowFirst()
    pipeline, received = make(tmp_path, transcriber)
    pipeline.submit(utterance(tmp_path, 0, "a", 2_000, 300))  # under min_seconds
    await pipeline.drain()
    assert transcriber.calls == 0 and received == []


async def test_lag_and_engine_errors(tmp_path):
    class Broken:
        def transcribe(self, audio, *, language, prompt):
            raise RuntimeError("model crashed")

    pipeline, received = make(tmp_path, Broken(), clock=lambda: 50_000)
    pipeline.submit(utterance(tmp_path, 0, "a", 2_000, 1000))
    await pipeline.drain()
    assert received == []
    assert pipeline.lag_s == 47.0
