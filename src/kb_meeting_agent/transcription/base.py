from __future__ import annotations

import io
import re
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
    """Synchronous: the pipeline calls it in a worker thread."""

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
    """Time spent above -40 dBFS, in 20 ms frames: near zero for the silent tails Discord sends."""
    frames = audio[: len(audio) // FRAME_SAMPLES * FRAME_SAMPLES].reshape(-1, FRAME_SAMPLES)
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    threshold = 10 ** (VOICED_DBFS / 20)
    return int(np.count_nonzero(rms > threshold)) * FRAME_SAMPLES / SAMPLE_RATE


_CODE = re.compile(r"`([^`\n]+)`")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def vocabulary_prompt(glossary: str, max_chars: int) -> str:
    """Terms worth hinting to Whisper: first table cells and `code` spans of the glossary."""
    terms: list[str] = []
    lines = glossary.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_header = i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1])
        if stripped.startswith("|") and not _TABLE_SEPARATOR.match(stripped) and not is_header:
            first = stripped.strip("|").split("|")[0]
            terms.append(_CODE.sub(r"\1", first).strip().strip("*").strip())
        if not is_header:
            terms.extend(_CODE.findall(line))
    unique: list[str] = []
    for term in terms:
        if term and len(term) <= 60 and term not in unique:
            unique.append(term)
    prompt = ""
    for term in unique:
        candidate = f"{prompt}, {term}" if prompt else term
        if len(candidate) > max_chars:
            break
        prompt = candidate
    return prompt


DEFAULT_HALLUCINATIONS = (
    "Sous-titres réalisés par la communauté d'Amara.org",
    "Sous-titres réalisés para la communauté d'Amara.org",
    "Sous-titrage ST' 501",
    "Sous-titrage Société Radio-Canada",
    "Merci d'avoir regardé cette vidéo",
    "Merci d'avoir regardé",
    "Subtitles by the Amara.org community",
    "Thank you for watching",
    "Thanks for watching",
)

# What Whisper writes for noise or breath; dropped only when it is the whole utterance.
LONE_HALLUCINATIONS = ("merci", "merci beaucoup", "thank you", "thank you very much")


class HallucinationFilter:
    def __init__(
        self,
        phrases: list[str],
        min_seconds: float,
        max_no_speech_prob: float,
        *,
        min_voiced_seconds: float = 0.0,
        min_avg_logprob: float | None = None,
    ) -> None:
        self._phrases = sorted({*DEFAULT_HALLUCINATIONS, *phrases}, key=len, reverse=True)
        self._min_seconds = min_seconds
        self._max_no_speech_prob = max_no_speech_prob
        self._min_voiced_seconds = min_voiced_seconds
        self._min_avg_logprob = min_avg_logprob

    def audible(self, audio: np.ndarray) -> bool:
        """Checked before transcribing: Whisper fills near-silence with "Merci." and the like."""
        return voiced_seconds(audio) >= self._min_voiced_seconds

    def clean(self, result: TranscriptionResult, duration_s: float) -> str | None:
        if duration_s < self._min_seconds:
            return None
        if result.no_speech_prob is not None and result.no_speech_prob > self._max_no_speech_prob:
            return None
        if (
            self._min_avg_logprob is not None
            and result.avg_logprob is not None
            and result.avg_logprob < self._min_avg_logprob
        ):
            return None
        original = " ".join(result.text.replace("’", "'").split())
        text = original
        for phrase in self._phrases:
            text = re.sub(re.escape(phrase), " ", text, flags=re.IGNORECASE)
        text = " ".join(text.split())
        if text != original:  # a phrase was removed: drop the punctuation it left behind
            text = text.strip(" .,;:!?-…")
        if text.strip(" .,;:!?-…").lower() in LONE_HALLUCINATIONS:
            return None
        return text if re.search(r"\w", text) else None
