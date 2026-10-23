from types import SimpleNamespace


async def test_search_merges_repos_and_labels_chunks(sources):
    hits = await sources.search("cooldown", k=10)
    assert {hit.repo for hit in hits} == {"kb", "back"}
    kb_hit = next(h for h in hits if h.repo == "kb")
    assert kb_hit.tags == ("KnowledgeBase",) and kb_hit.start_line is None


async def test_the_kb_leads_and_a_preferred_tag_follows(sources):
    hits = await sources.search("cooldown", k=10, prefer_tags=("BackEnd",))
    assert [h.repo for h in hits[:2]] == ["kb", "back"]


async def test_only_tags_filters_strictly(sources):
    hits = await sources.search("cooldown", k=10, only_tags=("KnowledgeBase",))
    assert hits and {h.repo for h in hits} == {"kb"}


async def test_free_tags_links_and_code_files(sources):
    assert sources.free_tags == ["BackEnd"]
    code = [h for h in await sources.search("COOLDOWN_SECONDS", k=10) if h.repo == "back"][0]
    link = sources.link(code)
    assert link.startswith("https://github.com/acme/back/blob/main/")
    assert link.endswith(f"/{code.path}#L{code.start_line}-L{code.end_line}")
    assert sources.code_exists("back", "lib/game/cooldown.dart")
    assert not sources.code_exists("back", "invented.dart")
    assert not sources.code_exists("front", "lib/game/cooldown.dart")
    kb_chunk = (await sources.search("cooldown", k=10, only_tags=("KnowledgeBase",)))[0]
    assert sources.link(kb_chunk) is None
    pieces = sources.section(kb_chunk)
    assert kb_chunk in pieces and all(p.repo == "kb" for p in pieces)


async def test_a_failing_repository_leaves_the_others(sources):
    async def broken(query, k):
        raise RuntimeError("index locked")

    sources.code_repos[0].search = broken
    hits = await sources.search("cooldown", k=5)
    assert hits and {h.repo for h in hits} == {"kb"}


def _chunks(repo, tags, n):
    from kb_meeting_agent.models import Chunk

    return [Chunk(f"{repo}{i}.md", (), "x", None, None, repo=repo, tags=tags) for i in range(n)]


async def test_the_kb_weighs_more_than_code_and_a_preferred_tag_more_than_the_rest(
    sources, monkeypatch
):
    def results(repo, tags):
        async def search(query, k):
            return _chunks(repo, tags, 10)[:k]

        return search

    front = SimpleNamespace(
        name="front", tags=("CodeBase", "FrontEnd"), search=results("front", ("FrontEnd",))
    )
    monkeypatch.setattr(sources, "_kb_search", results("kb", ("KnowledgeBase",)))
    monkeypatch.setattr(sources.code_repos[0], "search", results("back", ("BackEnd",)))
    monkeypatch.setattr(sources, "code_repos", [sources.code_repos[0], front])
    hits = await sources.search("q", k=6)
    assert [h.repo for h in hits] == ["kb", "back", "front", "kb", "kb", "back"]
    hits = await sources.search("q", k=6, prefer_tags=("BackEnd",))
    assert [h.repo for h in hits] == ["kb", "back", "front", "kb", "back", "kb"]
