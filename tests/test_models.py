from kb_meeting_agent.models import Chunk


def test_anchor_uses_last_heading():
    chunk = Chunk(
        path="reference/configuration.md",
        headings=("Configuration", "Neutralization"),
        text="x",
        status=None,
        verified_date=None,
    )
    assert chunk.anchor == "reference/configuration.md#Neutralization"


def test_anchor_without_heading_is_the_path():
    chunk = Chunk(path="README.md", headings=(), text="x", status=None, verified_date=None)
    assert chunk.anchor == "README.md"


def test_kb_chunks_keep_their_anchor_as_citation():
    chunk = Chunk("a.md", ("H",), "x", None, None, repo="kb", tags=("KnowledgeBase",))
    assert chunk.anchor == "a.md#H" and chunk.citation == "a.md#H"
