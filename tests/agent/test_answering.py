import pytest
from conftest import commit_file
from pydantic import ValidationError

from kb_meeting_agent.agent import answering
from kb_meeting_agent.agent.answering import answer_question, queries_model
from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.llm.fake import FakeProvider


async def test_answer_keeps_only_real_sources(kb):
    fast = FakeProvider(
        {"Queries": [{"queries": ["COOLDOWN_SECONDS default"], "code": False, "tags": []}]}
    )
    strong = FakeProvider(
        {
            "Answer": [
                {
                    "covered": True,
                    "answer": "The cooldown is 45 seconds.",
                    "sources": ["reference/configuration.md#Neutralization", "invented.md#X"],
                }
            ]
        }
    )
    text = await answer_question(
        fast, strong, kb, question="What is the cooldown?", context="", language="en"
    )
    assert "45 seconds" in text
    assert "`reference/configuration.md#Neutralization`" in text
    assert "invented.md" not in text
    assert "COOLDOWN_SECONDS" in strong.calls[0][2]
    assert "BIO-SCAN" in fast.calls[0][1]
    assert 'Set "code" to false.' in fast.calls[0][1]  # a KB without code repositories


async def test_not_covered(kb):
    fast = FakeProvider({"Queries": [{"queries": [], "code": False, "tags": []}]})
    strong = FakeProvider({"Answer": [{"covered": False, "answer": "", "sources": []}]})
    text = await answer_question(fast, strong, kb, question="Who won?", context="", language="fr")
    assert text == t("fr", "not_covered")
    assert "Who won?" in strong.calls[0][2]


ROADMAP = "# Roadmap\n\n## Mini-games\n\n| Type | Name | Status |\n|---|---|---|\n" + "".join(
    f"| `type{i:02d}` | GAME-{i:02d} {'x' * 40} | `[PROD]` |\n" for i in range(1, 41)
)


async def excerpts_for_the_first_part_of_a_split_table(kb, kb_origin, monkeypatch):
    commit_file(kb_origin, "roadmap.md", ROADMAP)
    await kb.sync()
    [first] = [c for c in await kb.search("GAME-01", k=20) if "GAME-01" in c.text]
    assert "GAME-40" not in first.text  # the table was split
    original_search = kb.search

    async def search(query, k=8, **_):  # only the first part of the table matches
        return [first, *[c for c in await original_search(query, k) if c.path != "roadmap.md"]]

    monkeypatch.setattr(kb, "search", search)
    fast = FakeProvider({"Queries": [{"queries": ["GAME-01"], "code": False, "tags": []}]})
    strong = FakeProvider({"Answer": [{"covered": False, "answer": "", "sources": []}]})
    await answer_question(fast, strong, kb, question="Which mini-games?", context="", language="en")
    return strong.calls[0][2]


async def test_a_split_table_is_read_whole(kb, kb_origin, monkeypatch):
    excerpts = await excerpts_for_the_first_part_of_a_split_table(kb, kb_origin, monkeypatch)
    assert "GAME-01" in excerpts and "GAME-40" in excerpts
    assert excerpts.index("GAME-01") < excerpts.index("GAME-40")


async def test_a_section_is_not_added_past_the_excerpts_budget(kb, kb_origin, monkeypatch):
    monkeypatch.setattr(answering, "EXCERPTS_MAX_CHARS", 1000)
    excerpts = await excerpts_for_the_first_part_of_a_split_table(kb, kb_origin, monkeypatch)
    assert "GAME-01" in excerpts and "GAME-40" not in excerpts


async def test_an_unexpanded_section_is_read_as_found(kb, kb_origin, monkeypatch):
    commit_file(kb_origin, ".meeting-agent.yml", "unexpanded_sections: ['^Mini']\n")
    excerpts = await excerpts_for_the_first_part_of_a_split_table(kb, kb_origin, monkeypatch)
    assert "GAME-01" in excerpts and "GAME-40" not in excerpts


async def test_code_is_searched_only_when_the_question_asks_about_it(sources):
    for code in (False, True):
        fast = FakeProvider(
            {"Queries": [{"queries": ["cooldown"], "code": code, "tags": ["BackEnd"]}]}
        )
        strong = FakeProvider({"Answer": [{"covered": False, "answer": "", "sources": []}]})
        await answer_question(
            fast, strong, sources, question="How does the back set it?", context="", language="en"
        )
        assert ('tags="CodeBase,BackEnd"' in strong.calls[0][2]) is code
    assert '"code" to true only' in fast.calls[0][1]
    assert "BackEnd" in fast.calls[0][1]  # the system prompt lists the project's free tags


def test_queries_model_limits_tags():
    model = queries_model(["BackEnd", "FrontEnd"])
    assert model.model_validate({"queries": [], "code": True, "tags": ["BackEnd"]}).tags == [
        "BackEnd"
    ]
    with pytest.raises(ValidationError):
        model.model_validate({"queries": [], "code": True, "tags": ["Mobile"]})
    assert model.model_json_schema()["title"] == "Queries"


async def test_code_sources_are_labelled_and_linked(sources):
    code = [h for h in await sources.search("COOLDOWN_SECONDS", k=10) if h.repo == "back"][0]
    fast = FakeProvider({"Queries": [{"queries": ["COOLDOWN_SECONDS"], "code": True, "tags": []}]})
    strong = FakeProvider(
        {"Answer": [{"covered": True, "answer": "30 s in the back.", "sources": [code.anchor]}]}
    )
    text = await answer_question(
        fast, strong, sources, question="Cooldown?", context="", language="en"
    )
    link = f"https://github.com/acme/back/blob/main/{code.path}#L"
    assert f"`[BackEnd]` [{code.anchor}]({link}" in text
    assert "the code does" in strong.calls[0][1]


async def test_a_source_without_its_lines_or_section_is_still_cited(sources):
    code = [h for h in await sources.search("COOLDOWN_SECONDS", k=10) if h.repo == "back"][0]
    fast = FakeProvider({"Queries": [{"queries": ["COOLDOWN_SECONDS"], "code": True, "tags": []}]})
    cited = [f"back:{code.path}", f"back:{code.path}", "reference/configuration.md", "back:x.php"]
    strong = FakeProvider({"Answer": [{"covered": True, "answer": "30 s.", "sources": cited}]})
    text = await answer_question(
        fast, strong, sources, question="Cooldown?", context="", language="en"
    )
    assert text.count(f"[{code.anchor}]") == 1
    assert "`reference/configuration.md#Neutralization`" in text
    assert "x.php" not in text
