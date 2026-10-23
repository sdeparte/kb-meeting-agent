import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_protocol_js_copies_are_identical():
    copies = sorted(ROOT.glob("connector-*/src/protocol.js"))
    assert copies
    contents = {path.read_bytes() for path in copies}
    assert len(contents) == 1, [str(p) for p in copies]
    text = copies[0].read_text(encoding="utf-8")
    assert not re.search(r"\b(discord|slack|meet)\b", text, re.IGNORECASE)
