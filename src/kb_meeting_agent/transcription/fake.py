from __future__ import annotations

import numpy as np

from kb_meeting_agent.transcription.base import TranscriptionResult


class FakeTranscriber:
    def __init__(
        self, responses: list[str | TranscriptionResult] | None = None, default: str = ""
    ) -> None:
        self.responses = list(responses or [])
        self.default = default
        self.calls: list[tuple[int, str | None, str]] = []

    def transcribe(
        self, audio: np.ndarray, *, language: str | None, prompt: str
    ) -> TranscriptionResult:
        self.calls.append((len(audio), language, prompt))
        item = self.responses.pop(0) if self.responses else self.default
        return item if isinstance(item, TranscriptionResult) else TranscriptionResult(item)
