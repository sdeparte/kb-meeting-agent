from kb_meeting_agent.conventions import KbConventions, PageHeader, StatusRule
from kb_meeting_agent.kb.chunker import chunk_markdown

CONV = KbConventions(
    page_header=PageHeader(verified_date=r"^> \*\*Verified on\*\* (\d{4}-\d{2}-\d{2})"),
    statuses=[
        StatusRule(pattern="[PROD]", meaning="in_production"),
        StatusRule(pattern="[PLANNED]", meaning="planned"),
    ],
)

PAGE = """# Configuration

> **Verified on** 2026-10-01 · **Sources**: a very long list of sources.

Intro paragraph.

## Neutralization

| Variable | Default |
|---|---|
| `COOLDOWN_SECONDS` | `45` [PROD] |

## Ideas [PLANNED]

Some planned thing.
"""


def test_splits_by_section_and_drops_the_header_line():
    chunks = chunk_markdown("reference/configuration.md", PAGE, CONV)
    assert [c.headings for c in chunks] == [
        ("Configuration",),
        ("Configuration", "Neutralization"),
        ("Configuration", "Ideas [PLANNED]"),
    ]
    assert all("Sources" not in c.text for c in chunks)
    assert all(c.verified_date == "2026-10-01" for c in chunks)


def test_status_from_text_then_headings():
    chunks = chunk_markdown("p.md", PAGE, CONV)
    assert chunks[0].status is None
    assert chunks[1].status == "in_production"
    assert chunks[2].status == "planned"


def test_long_table_is_split_with_its_header_repeated():
    rows = "\n".join(f"| `VAR_{i}` | `{i}` |" for i in range(60))
    page = f"## Big\n\n| Variable | Default |\n|---|---|\n{rows}\n"
    chunks = chunk_markdown("p.md", page, CONV, max_chars=400)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text.startswith("| Variable | Default |\n|---|---|\n")
        assert len(chunk.text) <= 400
    joined = "\n".join(chunks_text for chunks_text in (c.text for c in chunks))
    assert all(f"`VAR_{i}`" in joined for i in range(60))


def test_code_fence_is_not_parsed():
    page = "## Real\n\n```bash\n# not a heading\n| not | a table |\n```\n\nAfter.\n"
    chunks = chunk_markdown("p.md", page, CONV)
    assert len(chunks) == 1
    assert chunks[0].headings == ("Real",)
    assert "# not a heading" in chunks[0].text
    assert "After." in chunks[0].text


def test_empty_sections_produce_no_chunk():
    chunks = chunk_markdown("p.md", "# Title\n\n## Empty\n\n## Full\n\nText.\n", CONV)
    assert [c.headings for c in chunks] == [("Title", "Full")]
