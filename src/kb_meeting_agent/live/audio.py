from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kb_meeting_agent.live.protocol import AudioFrame
from kb_meeting_agent.transcription.base import SAMPLE_RATE, write_wav

MAX_UTTERANCE_MS = 30_000  # Whisper's window; the connector splits too
BYTES_PER_MS = SAMPLE_RATE * 2 // 1000
_FILE_SAFE_ID = re.compile(r"[A-Za-z0-9_]{1,64}")


def speaker_file_id(speaker_id: str) -> str:
    """The speaker id as it appears in file names: ids come from the connector's platform
    (a Meet participant is "spaces/…/participants/…"), so others are replaced by a hash."""
    if _FILE_SAFE_ID.fullmatch(speaker_id):
        return speaker_id
    return "h" + hashlib.sha256(speaker_id.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Utterance:
    index: int
    speaker_id: str
    speaker_name: str
    start_ms: int
    end_ms: int
    path: Path

    @property
    def duration_s(self) -> float:
        return (self.end_ms - self.start_ms) / 1000

    def record(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "file": self.path.name,
        }


@dataclass
class _Open:
    speaker_name: str
    start_ms: int
    pcm: bytearray = field(default_factory=bytearray)


class UtteranceAssembler:
    """Turns utterance events and audio frames into WAV files, one per utterance."""

    def __init__(self, audio_dir: Path, next_index: int = 0) -> None:
        self._dir = audio_dir
        self._open: dict[str, _Open] = {}
        self._opted_out: set[str] = set()
        self.next_index = next_index

    def start(self, speaker_id: str, speaker_name: str, t_ms: int) -> None:
        if speaker_id not in self._opted_out and speaker_id not in self._open:
            self._open[speaker_id] = _Open(speaker_name, t_ms)

    def add(self, frame: AudioFrame) -> Utterance | None:
        current = self._open.get(frame.user_id)
        if current is None:
            return None
        current.pcm.extend(frame.pcm)
        if len(current.pcm) >= MAX_UTTERANCE_MS * BYTES_PER_MS:
            end_ms = current.start_ms + len(current.pcm) // BYTES_PER_MS
            utterance = self._finish(frame.user_id, end_ms)
            self._open[frame.user_id] = _Open(current.speaker_name, end_ms)
            return utterance
        return None

    def end(self, speaker_id: str, t_ms: int) -> Utterance | None:
        if speaker_id not in self._open:
            return None
        return self._finish(speaker_id, t_ms)

    def close_all(self, t_ms: int) -> list[Utterance]:
        return [u for speaker in list(self._open) if (u := self._finish(speaker, t_ms))]

    def opt_out(self, speaker_id: str) -> None:
        self._opted_out.add(speaker_id)
        self._open.pop(speaker_id, None)

    def _finish(self, speaker_id: str, t_ms: int) -> Utterance | None:
        current = self._open.pop(speaker_id)
        if not current.pcm:
            return None
        end_ms = max(t_ms, current.start_ms + len(current.pcm) // BYTES_PER_MS)
        end_ms = min(
            end_ms, current.start_ms + max(MAX_UTTERANCE_MS, len(current.pcm) // BYTES_PER_MS)
        )
        path = self._dir / f"{self.next_index:05d}-{speaker_file_id(speaker_id)}.wav"
        write_wav(path, bytes(current.pcm))
        utterance = Utterance(
            self.next_index, speaker_id, current.speaker_name, current.start_ms, end_ms, path
        )
        self.next_index += 1
        return utterance
