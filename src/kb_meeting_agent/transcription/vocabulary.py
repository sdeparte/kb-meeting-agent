"""The vocabulary hinted to transcription engines that take a prompt (Whisper's
initial_prompt): names and glossary terms people are likely to say."""

from __future__ import annotations

import re

_CODE = re.compile(r"`([^`\n]+)`")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


_STATUS_TAG = re.compile(r"^\[[^\]]*\]$")
_COMMIT_HASH = re.compile(r"^(?=.*\d)[0-9a-f]{7,40}$")
_IDENTIFIER = re.compile(r"[/.:(){}=_]|[a-z][A-Z]")  # paths, calls, snake_case, camelCase


def _named(term: str) -> bool:
    """Whether the term names something: not a status tag or a commit hash."""
    return not (_STATUS_TAG.match(term) or _COMMIT_HASH.match(term))


def _spoken(span: str) -> bool:
    """Whether people may say a `code` span: not a code identifier either. Only spans are
    checked for identifiers: a glossary term such as "iOS" or "Node.js" looks like one."""
    return _named(span) and (" " in span or not _IDENTIFIER.search(span))


def vocabulary_prompt(glossary: str, max_chars: int, first: list[str] | None = None) -> str:
    """Terms worth hinting to Whisper: `first`, then the first cells of the glossary tables,
    then the `code` spans of their rows. Prose is skipped: it holds sources, not terms."""
    terms: list[str] = []
    spans: list[str] = []
    lines = glossary.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_header = i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1])
        if stripped.startswith("|") and not _TABLE_SEPARATOR.match(stripped) and not is_header:
            first_cell = stripped.strip("|").split("|")[0]
            terms.append(_CODE.sub(r"\1", first_cell).strip().strip("*").strip())
            spans.extend(_CODE.findall(line))
    unique: list[str] = list(dict.fromkeys(t for t in first or [] if t))
    candidates = [t for t in terms if _named(t)] + [s for s in spans if _spoken(s)]
    for term in candidates:
        if term and len(term) <= 60 and term not in unique:
            unique.append(term)
    prompt = ""
    for term in unique:
        candidate = f"{prompt}, {term}" if prompt else term
        if len(candidate) > max_chars:
            break
        prompt = candidate
    return prompt
