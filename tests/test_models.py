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
