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


async def test_code_chunks_keep_their_lines(index):
    code = Chunk(
        "src/x.php",
        (),
        "function cooldown()",
        None,
        None,
        repo="back",
        tags=("CodeBase",),
        start_line=12,
        end_line=70,
    )
    await index.upsert_file("src/x.php", "h", [code])
    [found] = await index.search("cooldown", k=1)
    assert (found.start_line, found.end_line) == (12, 70)


def test_old_index_files_gain_the_line_columns(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE chunks (id INTEGER PRIMARY KEY, path TEXT NOT NULL, headings TEXT NOT NULL, "
        "text TEXT NOT NULL, status TEXT, verified_date TEXT, vector BLOB NOT NULL);"
    )
    db.close()
    SearchIndex(path, FakeProvider().embed).close()
    columns = {row[1] for row in sqlite3.connect(path).execute("PRAGMA table_info(chunks)")}
    assert {"start_line", "end_line"} <= columns


async def test_vectors_are_loaded_once_until_the_index_changes(index, monkeypatch):
    from kb_meeting_agent.kb import index as index_module

    await index.upsert_file("a.md", "h", [chunk("a.md", "cooldown alpha")])
    loads = []
    stack = index_module.np.stack
    monkeypatch.setattr(index_module.np, "stack", lambda *a, **k: loads.append(1) or stack(*a, **k))
    await index.search("cooldown", k=1)
    await index.search("alpha", k=1)
    assert len(loads) == 1
    await index.upsert_file("b.md", "h", [chunk("b.md", "zeppelin")])
    assert (await index.search("zeppelin", k=1))[0].path == "b.md"
    assert len(loads) == 2
    index.remove_file("b.md")
    assert all(c.path != "b.md" for c in await index.search("zeppelin", k=5))


async def test_another_writer_on_the_same_file_refreshes_the_vectors(index, tmp_path):
    await index.upsert_file("a.md", "h", [chunk("a.md", "cooldown alpha")])
    await index.search("cooldown", k=1)  # vectors loaded
    other = SearchIndex(tmp_path / "index.sqlite", FakeProvider().embed)
    await other.upsert_file("c.md", "h", [chunk("c.md", "zeppelin")])
    await other.upsert_file("a.md", "h2", [chunk("a.md", "cooldown alpha")])
    other.remove_file("c.md")
    other.close()
    assert [c.path for c in await index.search("zeppelin cooldown", k=5)] == ["a.md"]


async def test_a_file_reindexed_during_a_search_is_left_out_not_a_crash(tmp_path):
    import asyncio

    fake = FakeProvider()
    release = asyncio.Event()

    async def slow_embed(texts):
        if texts == ["cooldown"]:
            await release.wait()
        return await fake.embed(texts)

    index = SearchIndex(tmp_path / "index.sqlite", slow_embed)
    await index.upsert_file("a.md", "h", [chunk("a.md", "cooldown alpha")])
    await index.upsert_file("b.md", "h", [chunk("b.md", "cooldown beta")])
    search = asyncio.create_task(index.search("cooldown", k=5))
    await asyncio.sleep(0)  # the lexical ids are taken, the query embedding waits
    await index.upsert_file("a.md", "h2", [chunk("a.md", "something else")])
    release.set()
    assert {c.path for c in await search} <= {"a.md", "b.md"}
    index.close()
