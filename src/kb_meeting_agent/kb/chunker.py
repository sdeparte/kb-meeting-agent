from __future__ import annotations

import re

from kb_meeting_agent.conventions import KbConventions
from kb_meeting_agent.models import Chunk

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def chunk_markdown(
    path: str, text: str, conventions: KbConventions, max_chars: int = 1500
) -> list[Chunk]:
    header = conventions.page_header.verified_date
    header_re = re.compile(header) if header else None
    verified: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        match = header_re.search(line) if header_re else None
        if match:
            verified = verified or match.group(1)
            continue
        lines.append(line)

    chunks: list[Chunk] = []
    for headings, section_lines in _sections(lines):
        for piece in _pack(_blocks(section_lines), max_chars):
            chunks.append(
                Chunk(
                    path=path,
                    headings=headings,
                    text=piece,
                    status=_status(piece, headings, conventions),
                    verified_date=verified,
                )
            )
    return chunks


def _sections(lines: list[str]) -> list[tuple[tuple[str, ...], list[str]]]:
    stack: list[tuple[int, str]] = []
    current: list[str] = []
    sections: list[tuple[tuple[str, ...], list[str]]] = []
    in_code = False
    for line in lines:
        if _FENCE.match(line):
            in_code = not in_code
        match = None if in_code else _HEADING.match(line)
        if match:
            sections.append((tuple(title for _, title in stack), current))
            current = []
            level = len(match.group(1))
            stack = [(lvl, title) for lvl, title in stack if lvl < level]
            stack.append((level, match.group(2)))
        else:
            current.append(line)
    sections.append((tuple(title for _, title in stack), current))
    return sections


def _blocks(lines: list[str]) -> list[tuple[str, list[str]]]:
    """Group lines into ("table" | "text", lines) blocks; code fences stay whole in text blocks."""
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] = []
    kind: str | None = None
    in_code = False

    def flush() -> None:
        nonlocal current, kind
        if any(line.strip() for line in current):
            blocks.append((kind or "text", current))
        current, kind = [], None

    for line in lines:
        if in_code:
            current.append(line)
            if _FENCE.match(line):
                in_code = False
            continue
        if _FENCE.match(line):
            if kind == "table":
                flush()
            kind = "text"
            current.append(line)
            in_code = True
            continue
        if not line.strip():
            flush()
            continue
        line_kind = "table" if line.lstrip().startswith("|") else "text"
        if kind and line_kind != kind:
            flush()
        kind = line_kind
        current.append(line)
    flush()
    return blocks


def _split_table(lines: list[str], max_chars: int) -> list[list[str]]:
    if len(lines) < 3 or not _TABLE_SEPARATOR.match(lines[1]):
        return [lines]
    header, rows = lines[:2], lines[2:]
    groups: list[list[str]] = []
    current: list[str] = []
    for row in rows:
        if current and len("\n".join(header + current + [row])) > max_chars:
            groups.append(header + current)
            current = []
        current.append(row)
    if current:
        groups.append(header + current)
    return groups


def _pack(blocks: list[tuple[str, list[str]]], max_chars: int) -> list[str]:
    pieces: list[str] = []
    current: list[str] = []
    for kind, lines in blocks:
        too_long = len("\n".join(lines)) > max_chars
        parts = _split_table(lines, max_chars) if kind == "table" and too_long else [lines]
        for part in parts:
            text = "\n".join(part)
            if current and len("\n\n".join(current + [text])) > max_chars:
                pieces.append("\n\n".join(current))
                current = []
            current.append(text)
    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _status(text: str, headings: tuple[str, ...], conventions: KbConventions) -> str | None:
    for source in (text, *reversed(headings)):
        found = [
            (source.find(rule.pattern), rule.meaning)
            for rule in conventions.statuses
            if rule.pattern in source
        ]
        if found:
            return min(found)[1]
    return None
