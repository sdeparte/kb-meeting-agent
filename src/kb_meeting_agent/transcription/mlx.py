from __future__ import annotations

import threading
from typing import Any

import numpy as np

from kb_meeting_agent.config import TranscriberRole
from kb_meeting_agent.transcription.base import TranscriptionResult


class MlxWhisperTranscriber:
    """Whisper on the Apple Silicon GPU (macOS only; install the `mlx` extra).

    mlx_whisper keeps its model in a process-wide holder and MLX does not guarantee
    thread-safe concurrent evaluation, so calls are serialised across all instances.
    """

    _lock = threading.Lock()

    def __init__(self, role: TranscriberRole, module: Any | None = None) -> None:
        if module is None:
            import mlx_whisper as module
        self._mlx = module
        self._model = role.model

    def transcribe(
        self, audio: np.ndarray, *, language: str | None, prompt: str
    ) -> TranscriptionResult:
        with self._lock:
            result = self._mlx.transcribe(
                audio,
                path_or_hf_repo=self._model,
                language=language,
                initial_prompt=prompt or None,
                condition_on_previous_text=False,
            )
        segments = result.get("segments", [])
        probabilities = [s["no_speech_prob"] for s in segments if "no_speech_prob" in s]
        logprobs = [s["avg_logprob"] for s in segments if "avg_logprob" in s]
        return TranscriptionResult(
            result.get("text", "").strip(),
            min(probabilities) if probabilities else None,
            sum(logprobs) / len(logprobs) if logprobs else None,
        )
