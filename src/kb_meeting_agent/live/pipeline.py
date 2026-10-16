from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from kb_meeting_agent.live.audio import Utterance
from kb_meeting_agent.models import Segment
from kb_meeting_agent.transcription.base import (
    HallucinationFilter,
    Transcriber,
    pcm16_to_float,
    read_wav,
)

log = logging.getLogger(__name__)


class TranscriptionPipeline:
    """Transcribes utterances in a bounded pool, keeping each speaker's order."""

    def __init__(
        self,
        transcriber: Transcriber,
        *,
        language: str | None,
        prompt: str,
        cleaner: HallucinationFilter,
        workers: int,
        meeting_start_ms: int,
        on_segment: Callable[[Segment], Awaitable[None]],
        clock_ms: Callable[[], int],
    ) -> None:
        self._transcriber = transcriber
        self._language = language
        self._prompt = prompt
        self._cleaner = cleaner
        self._slots = asyncio.Semaphore(workers)
        self._start_ms = meeting_start_ms
        self._on_segment = on_segment
        self._clock_ms = clock_ms
        self._tails: dict[str, asyncio.Task[None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self.lag_s = 0.0

    def submit(self, utterance: Utterance) -> None:
        previous = self._tails.get(utterance.speaker_id)
        task = asyncio.create_task(self._run(utterance, previous))
        self._tails[utterance.speaker_id] = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _run(self, utterance: Utterance, previous: asyncio.Task[None] | None) -> None:
        if previous is not None:
            await asyncio.wait([previous])
        async with self._slots:
            try:
                audio = pcm16_to_float(read_wav(utterance.path))
                result = await asyncio.to_thread(
                    self._transcriber.transcribe,
                    audio,
                    language=self._language,
                    prompt=self._prompt,
                )
            except Exception:
                log.exception("transcribing %s failed", utterance.path.name)
                result = None
        self.lag_s = (self._clock_ms() - utterance.end_ms) / 1000
        if result is None:
            return
        text = self._cleaner.clean(result, utterance.duration_s)
        if text:
            await self._on_segment(
                Segment(
                    speaker_id=utterance.speaker_id,
                    speaker_name=utterance.speaker_name,
                    start=(utterance.start_ms - self._start_ms) / 1000,
                    end=(utterance.end_ms - self._start_ms) / 1000,
                    text=text,
                )
            )
