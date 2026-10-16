from __future__ import annotations

import re

MIN_QUOTE_CHARS = 12
_MARKUP = re.compile(r"[*`|_>]")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _normalize(text: str) -> str:
    return " ".join(_MARKUP.sub(" ", text).split()).casefold()


def find_quote_line(quote: str, document: str) -> str | None:
    """The full document lines containing the quote (ignoring Markdown markup and spacing).

    Callers show these lines rather than the model's string, so a quote trimmed of a negation
    or a qualifier is still displayed with its full KB context. A quote may span wrapped
    lines or a table header and its rows.
    """
    target = _normalize(quote)
    if len(target) < MIN_QUOTE_CHARS:
        return None
    lines = document.splitlines()
    text = ""
    owners: list[int] = []
    for index, line in enumerate(lines):
        normalized = "" if _TABLE_SEPARATOR.match(line) else _normalize(line)
        if not normalized:
            continue
        if text:
            text += " "
            owners.append(index)
        text += normalized
        owners.extend([index] * len(normalized))
    position = text.find(target)
    if position < 0:
        return None
    first, last = owners[position], owners[position + len(target) - 1]
    return "\n".join(line.strip() for line in lines[first : last + 1] if line.strip())


def quote_exists(quote: str, document: str) -> bool:
    return find_quote_line(quote, document) is not None
