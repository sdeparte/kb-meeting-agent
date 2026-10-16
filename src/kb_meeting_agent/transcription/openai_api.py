from __future__ import annotations

from typing import Any

import numpy as np
import openai

from kb_meeting_agent.config import TranscriberRole
from kb_meeting_agent.transcription.base import TranscriptionResult, float_to_pcm16, wav_bytes


class OpenAICompatibleTranscriber:
    """Any server exposing /v1/audio/transcriptions."""

    def __init__(self, role: TranscriberRole, client: Any | None = None) -> None:
        self._client = client or openai.OpenAI(
            base_url=role.base_url, api_key=role.api_key or "not-needed"
        )
        self._model = role.model

    def transcribe(
        self, audio: np.ndarray, *, language: str | None, prompt: str
    ) -> TranscriptionResult:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "file": ("utterance.wav", wav_bytes(float_to_pcm16(audio)), "audio/wav"),
        }
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["prompt"] = prompt
        response = self._client.audio.transcriptions.create(**kwargs)
        return TranscriptionResult(response.text.strip())
