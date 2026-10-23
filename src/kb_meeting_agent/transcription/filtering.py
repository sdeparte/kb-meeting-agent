"""What is kept of a transcription: Whisper fills silence and noise with phrases from its
training subtitles, and loops; the checks on scores apply to engines that report them."""

from __future__ import annotations

import re
import zlib

import numpy as np

from kb_meeting_agent.transcription.base import TranscriptionResult, voiced_seconds

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


def compression_ratio(text: str) -> float:
    """Whisper's own loop detector: a text repeating itself compresses far better than speech."""
    data = text.encode("utf-8")
    return len(data) / len(zlib.compress(data)) if data else 0.0


# What Whisper writes for noise or breath; dropped only when it is the whole utterance.
LONE_HALLUCINATIONS = ("merci", "merci beaucoup", "thank you", "thank you very much")


_SENTENCE_END = "[.!?…]"


def _strip_sentence(text: str, phrase: str) -> str:
    """Remove the phrase where Whisper adds it: as a sentence of its own at the start or the
    end of the text. Inside a sentence it is real speech (« Merci d'avoir regardé la PR »)."""
    p = re.escape(phrase)
    text = re.sub(
        rf"(?:^|(?<={_SENTENCE_END}))\s*{p}\s*{_SENTENCE_END}*\s*$", " ", text, flags=re.I
    )
    return re.sub(rf"^\s*{p}\s*(?:{_SENTENCE_END}+|$)", " ", text, flags=re.I)


class HallucinationFilter:
    def __init__(
        self,
        phrases: list[str],
        min_seconds: float,
        max_no_speech_prob: float,
        *,
        min_voiced_seconds: float = 0.0,
        min_avg_logprob: float | None = None,
        max_compression_ratio: float | None = None,
    ) -> None:
        self._phrases = sorted({*DEFAULT_HALLUCINATIONS, *phrases}, key=len, reverse=True)
        self._min_seconds = min_seconds
        self._max_no_speech_prob = max_no_speech_prob
        self._min_voiced_seconds = min_voiced_seconds
        self._min_avg_logprob = min_avg_logprob
        self._max_compression_ratio = max_compression_ratio

    def audible(self, audio: np.ndarray, duration_s: float) -> bool:
        """Checked before transcribing: Whisper fills near-silence with "Merci." and the like,
        and an utterance too short to keep would only take the GPU from the others."""
        return duration_s >= self._min_seconds and voiced_seconds(audio) >= self._min_voiced_seconds

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
        if (
            self._max_compression_ratio is not None
            and compression_ratio(original) > self._max_compression_ratio
        ):
            return None  # Whisper stuck in a loop: "Eik, Disa, Eik, Disa, …"
        text = original
        for phrase in self._phrases:
            text = _strip_sentence(text, phrase)
        text = " ".join(text.split())
        if text != original:  # a phrase was removed: drop the punctuation it left behind
            text = text.strip(" .,;:!?-…")
        if text.strip(" .,;:!?-…").lower() in LONE_HALLUCINATIONS:
            return None
        return text if re.search(r"\w", text) else None
