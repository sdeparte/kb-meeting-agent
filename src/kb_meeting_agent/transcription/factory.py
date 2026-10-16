from __future__ import annotations

from kb_meeting_agent.config import TranscriberRole
from kb_meeting_agent.transcription.base import Transcriber
from kb_meeting_agent.transcription.fake import FakeTranscriber


def build_transcriber(role: TranscriberRole) -> Transcriber:
    match role.provider:
        case "mlx-whisper":
            from kb_meeting_agent.transcription.mlx import MlxWhisperTranscriber

            return MlxWhisperTranscriber(role)
        case "faster-whisper":
            from kb_meeting_agent.transcription.faster import FasterWhisperTranscriber

            return FasterWhisperTranscriber(role)
        case "openai-compatible":
            from kb_meeting_agent.transcription.openai_api import OpenAICompatibleTranscriber

            return OpenAICompatibleTranscriber(role)
        case "fake":
            return FakeTranscriber(default="(fake transcription)")
