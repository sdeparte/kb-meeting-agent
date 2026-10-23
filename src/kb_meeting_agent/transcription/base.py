from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

SAMPLE_RATE = 16000


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    no_speech_prob: float | None = None
    avg_logprob: float | None = None


class Transcriber(Protocol):
    """Synchronous: the pipeline calls it in a worker thread.

    `prompt` holds vocabulary hints (vocabulary.py), which an engine without a prompt
    ignores. Scores an engine does not report stay None, and their filters do not apply.
    """

    def transcribe(
        self, audio: np.ndarray, *, language: str | None, prompt: str
    ) -> TranscriptionResult: ...


def pcm16_to_float(pcm: bytes) -> np.ndarray:
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(audio: np.ndarray) -> bytes:
    return np.round(np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def wav_bytes(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)
    return buffer.getvalue()


def write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(pcm))


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav:
        return wav.readframes(wav.getnframes())


FRAME_SAMPLES = SAMPLE_RATE // 50  # 20 ms
VOICED_DBFS = -40.0


def voiced_seconds(audio: np.ndarray) -> float:
    """Time spent above -40 dBFS, in 20 ms frames: near zero for the silent tails connectors send."""
    frames = audio[: len(audio) // FRAME_SAMPLES * FRAME_SAMPLES].reshape(-1, FRAME_SAMPLES)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    threshold = 10 ** (VOICED_DBFS / 20)
    return int(np.count_nonzero(rms > threshold)) * FRAME_SAMPLES / SAMPLE_RATE
