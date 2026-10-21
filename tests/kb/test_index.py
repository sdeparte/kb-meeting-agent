import pytest

from kb_meeting_agent.kb.index import SearchIndex
from kb_meeting_agent.llm.fake import FakeProvider
from kb_meeting_agent.models import Chunk


def chunk(path, text, heading="H"):
    return Chunk(path=path, headings=(heading,), text=text, status=None, verified_date="2026-10-01")


@pytest.fixture
def index(tmp_path):
    idx = SearchIndex(tmp_path / "index.sqlite", FakeProvider().embed)
    yield idx
    idx.close()


async def test_exact_identifier_ranks_first(index):
    await index.upsert_file("a.md", "h1", [chunk("a.md", "| `RSSI_PROXIMITY_TOLERANCE` | `5` |")])
    await index.upsert_file("b.md", "h2", [chunk("b.md", "The proximity of players matters.")])
    results = await index.search("RSSI_PROXIMITY_TOLERANCE", k=2)
    assert results[0].path == "a.md"
    assert results[0].verified_date == "2026-10-01"
    assert results[0].headings == ("H",)


async def test_query_with_special_characters(index):
    await index.upsert_file("a.md", "h", [chunk("a.md", "BIO-SCAN uses a -70 dBm threshold")])
    results = await index.search('BIO-SCAN "quoted" -70 (x) AND OR NOT *', k=1)
    assert results[0].path == "a.md"


async def test_upsert_replaces_and_remove_deletes(index):
    await index.upsert_file("a.md", "h1", [chunk("a.md", "old text")])
    await index.upsert_file("a.md", "h2", [chunk("a.md", "new text")])
    assert index.file_hashes() == {"a.md": "h2"}
    assert [c.text for c in await index.search("text", k=5)] == ["new text"]
    index.remove_file("a.md")
    assert index.file_hashes() == {}
    assert await index.search("text", k=5) == []


async def test_boost_paths_win_ties(index):
    await index.upsert_file("a.md", "h", [chunk("a.md", "cooldown is 45 seconds")])
    await index.upsert_file("b.md", "h", [chunk("b.md", "cooldown is 45 seconds")])
    results = await index.search("cooldown", k=2, boost_paths=("b.md",))
    assert results[0].path == "b.md"


async def test_meta_and_clear(index):
    index.set_meta("key", "v1")
    assert index.get_meta("key") == "v1"
    await index.upsert_file("a.md", "h", [chunk("a.md", "x")])
    index.clear()
    assert index.file_hashes() == {}
    assert index.get_meta("key") == "v1"


async def test_section_returns_every_chunk_of_a_section_in_page_order(index):
    await index.upsert_file(
        "a.md",
        "h",
        [chunk("a.md", "rows 1-7"), chunk("a.md", "rows 8-11"), chunk("a.md", "other", "I")],
    )
    assert [c.text for c in index.section("a.md", ("H",), "rows 8-11")] == [
        "rows 1-7",
        "rows 8-11",
    ]
    assert index.section("a.md", ("Missing",), "rows 1-7") == []


async def test_section_leaves_out_another_section_with_the_same_headings(index):
    notes = [chunk("a.md", "notes 1", "Notes"), chunk("a.md", "notes 2", "Notes")]
    await index.upsert_file(
        "a.md", "h", [*notes, chunk("a.md", "rows", "Table"), chunk("a.md", "notes 3", "Notes")]
    )
    assert [c.text for c in index.section("a.md", ("Notes",), "notes 2")] == [
        "notes 1",
        "notes 2",
    ]
    assert [c.text for c in index.section("a.md", ("Notes",), "notes 3")] == ["notes 3"]
