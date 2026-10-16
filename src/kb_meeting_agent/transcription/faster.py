from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from kb_meeting_agent.config import TranscriberRole
from kb_meeting_agent.transcription.base import TranscriptionResult


class FasterWhisperTranscriber:
    """Whisper through CTranslate2, on CPU or CUDA (install the `faster` extra).

    Audio is passed as an array, so no file decoding (PyAV) is involved.
    """

    def __init__(
        self, role: TranscriberRole, model_factory: Callable[..., Any] | None = None
    ) -> None:
        if model_factory is None:
            from faster_whisper import WhisperModel as model_factory
        self._model = model_factory(role.model, device=role.device, compute_type=role.compute_type)
        self._beam_size = role.beam_size

    def transcribe(
        self, audio: np.ndarray, *, language: str | None, prompt: str
    ) -> TranscriptionResult:
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            initial_prompt=prompt or None,
            beam_size=self._beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        segments = list(segments)
        text = " ".join(s.text.strip() for s in segments).strip()
        probabilities = [s.no_speech_prob for s in segments]
        logprobs = [s.avg_logprob for s in segments]
        return TranscriptionResult(
            text,
            min(probabilities) if probabilities else None,
            sum(logprobs) / len(logprobs) if logprobs else None,
        )
