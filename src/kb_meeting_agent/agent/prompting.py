from __future__ import annotations

from kb_meeting_agent.models import Chunk, Segment


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def format_segments(segments: list[Segment]) -> str:
    return "\n".join(f"[{format_timestamp(s.start)}] {s.speaker_name}: {s.text}" for s in segments)


def format_chunks(chunks: list[Chunk]) -> str:
    parts = []
    for chunk in chunks:
        attributes = f'source="{chunk.anchor}"'
        if chunk.start_line is not None:
            attributes += f' tags="{",".join(chunk.tags)}"'
        if chunk.status:
            attributes += f' status="{chunk.status}"'
        if chunk.verified_date:
            attributes += f' verified="{chunk.verified_date}"'
        parts.append(f"<excerpt {attributes}>\n{chunk.text}\n</excerpt>")
    return "\n\n".join(parts)
