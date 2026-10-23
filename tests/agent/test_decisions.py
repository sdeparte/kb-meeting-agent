from datetime import date

import pytest

from kb_meeting_agent.agent.decisions import (
    DecisionDraft,
    RelatedCode,
    RelatedPage,
    _draft_model,
    append_table_row,
    build_decision_change,
    draft_decision,
    index_files,
    next_number,
    slugify,
)
from kb_meeting_agent.conventions import DecisionConventions, IndexConfig
from kb_meeting_agent.llm.base import LLMInvalidOutput, json_schema_for
from kb_meeting_agent.llm.fake import FakeProvider

DRAFT = DecisionDraft(
    title="Cooldown at 30 s",
    slug="Cooldown at 30 s!",
    scope="backend",
    context="Players found 45 s too long.",
    decision="Set COOLDOWN_SECONDS to 30.",
    consequences="Faster rounds.",
    related_pages=[
        RelatedPage(
            path="reference/configuration.md", section="Neutralization", reason="Default changes"
        )
    ],
    related_code=[],
)


def test_slugify():
    assert slugify("Délai de récupération à 30 s") == "delai-de-recuperation-a-30-s"
    assert slugify("!!!") == "decision"
    assert len(slugify("x" * 200)) == 60


def test_next_number_considers_paths_and_reservations():
    paths = ["decisions/0001-a.md", "0002-b.md", "README.md", "decisions/0007-open-pr.md"]
    assert next_number(paths) == 8
    assert next_number(paths, reserved={8, 9}) == 10
    assert next_number([]) == 1


def test_append_table_row_after_last_row():
    content = "# T\n\n| a |\n|---|\n| 1 |\n\nFooter text.\n"
    assert (
        append_table_row(content, "| 2 |") == "# T\n\n| a |\n|---|\n| 1 |\n| 2 |\n\nFooter text.\n"
    )
    assert append_table_row("No table\n", "| 2 |") is None


def test_build_numbered_change_with_index():
    conventions = DecisionConventions(
        index=IndexConfig(
            file="decisions/README.md", row="| [{number:04d}]({filename}) | {title} |"
        )
    )
    change = build_decision_change(
        conventions=conventions,
        template="# {number:04d} — {title}\n\n{decision}\n\n{sources}",
        draft=DRAFT,
        number=3,
        meeting_date=date(2026, 10, 15),
        quote="ok on passe à 30",
        validated_by="Bob",
        index_content="| # | D |\n|---|---|\n| [0002](0002-b.md) | B |\n",
        language="en",
    )
    path = "decisions/0003-cooldown-at-30-s.md"
    assert change.branch == "decision/2026-10-15-cooldown-at-30-s"
    assert change.files[path].startswith("# 0003 — Cooldown at 30 s\n")
    assert "validated by Bob" in change.files[path]
    assert change.files["decisions/README.md"].endswith(
        "| [0003](0003-cooldown-at-30-s.md) | Cooldown at 30 s |\n"
    )
    assert change.title == "Decision: Cooldown at 30 s"
    assert "> ok on passe à 30" in change.body
    assert "`reference/configuration.md` § Neutralization — Default changes" in change.body


def test_build_unnumbered_change_without_index():
    conventions = DecisionConventions(filename="{date}-{slug}.md")
    change = build_decision_change(
        conventions=conventions,
        template="# {title}",
        draft=DRAFT.model_copy(update={"related_pages": []}),
        number=None,
        meeting_date=date(2026, 10, 15),
        quote="q",
        validated_by="Bob",
        index_content=None,
        language="fr",
    )
    assert list(change.files) == ["decisions/2026-10-15-cooldown-at-30-s.md"]
    assert "Aucune identifiée." in change.body


async def test_draft_decision_passes_instructions_and_excerpts(kb):
    strong = FakeProvider({"DecisionDraft": [DRAFT.model_dump()]})
    chunks = await kb.search("cooldown", k=2)
    draft = await draft_decision(
        strong,
        statement="Cooldown is 30 s",
        quote="ok on passe à 30",
        chunks=chunks,
        instructions="Write in English.",
        language="en",
    )
    assert draft.title == "Cooldown at 30 s"
    system, user = strong.calls[0][1], strong.calls[0][2]
    assert "Write in English." in system
    assert "ok on passe à 30" in user and "<excerpt" in user
    assert "in the KB's vocabulary" in system
    assert "never copy code" in system


async def scoped_draft(kb, *answers, scopes=("client", "serveur", "les deux")):
    strong = FakeProvider({"DecisionDraft": [DRAFT.model_dump() | {"scope": a} for a in answers]})
    draft = await draft_decision(
        strong,
        statement="Cooldown is 30 s",
        quote="ok on passe à 30",
        chunks=await kb.search("cooldown", k=2),
        instructions="",
        language="fr",
        scopes=list(scopes),
    )
    return draft, strong


async def test_draft_decision_lists_the_allowed_scopes(kb):
    draft, strong = await scoped_draft(kb, "serveur")
    assert type(draft) is DecisionDraft and draft.scope == "serveur"
    system = strong.calls[0][1]
    assert 'exactly one of "client", "serveur", "les deux"' in system
    assert "in the KB's vocabulary" not in system


async def test_draft_decision_maps_spelling_variants_to_the_listed_scope(kb):
    draft, strong = await scoped_draft(kb, "  Les  DEUX ")
    assert draft.scope == "les deux" and len(strong.calls) == 1


async def test_draft_decision_asks_again_then_fails_on_an_unlisted_scope(kb):
    draft, strong = await scoped_draft(kb, "backend", "client")
    assert draft.scope == "client"
    assert "not valid" in strong.calls[1][2] and "client" in strong.calls[1][2]
    with pytest.raises(LLMInvalidOutput):
        await scoped_draft(kb, "backend", "frontend")


async def test_draft_decision_keeps_scopes_in_other_scripts_apart(kb):
    draft, _ = await scoped_draft(kb, "клиент", scopes=["клиент", "сервер"])
    assert draft.scope == "клиент"
    with pytest.raises(LLMInvalidOutput):
        await scoped_draft(kb, "хз", "—", scopes=["клиент", "сервер"])


async def test_draft_decision_schema_lists_a_single_scope_as_an_enum(kb):
    draft, _ = await scoped_draft(kb, "kb", scopes=["KB"])
    assert draft.scope == "KB"
    scope = json_schema_for(_draft_model(("KB",)))["properties"]["scope"]
    assert scope["enum"] == ["KB"] and "const" not in scope


def test_index_files_escapes_cells_and_skips_a_file_without_table():
    index = IndexConfig(file="README.md", row="| {number:04d} | {title} |")
    values = {"number": 3, "title": "Sync | Q4\nfollow-up"}
    assert index_files(index, "| # | T |\n|---|---|\n", values) == {
        "README.md": "| # | T |\n|---|---|\n| 0003 | Sync \\| Q4 follow-up |\n"
    }
    assert index_files(index, "# Index\n\n- rules\n", values) == {}
    assert index_files(index, None, values) == {}
    assert index_files(None, "| a |\n", values) == {}


def test_append_table_row_ignores_code_fences():
    content = "| a |\n|---|\n| 1 |\n\n```\n| not table |\n```\n"
    expected = "| a |\n|---|\n| 1 |\n| 2 |\n\n```\n| not table |\n```\n"
    assert append_table_row(content, "| 2 |") == expected


def test_code_files_get_their_own_section():
    draft = DRAFT.model_copy(
        update={
            "related_code": [
                RelatedCode(repo="back", path="src/x.php", reason="value changes"),
                RelatedCode(repo="back", path="src/y.php", reason="no link"),
            ]
        }
    )
    change = build_decision_change(
        conventions=DecisionConventions(),
        template="# {title}",
        draft=draft,
        number=3,
        meeting_date=date(2026, 10, 15),
        quote="q",
        validated_by="Bob",
        index_content=None,
        language="en",
        code_links={("back", "src/x.php"): "https://github.com/acme/back/blob/main/src/x.php"},
    )
    assert "## Code files that may be affected" in change.body
    link = "[src/x.php](https://github.com/acme/back/blob/main/src/x.php)"
    assert f"- `back` {link} — value changes" in change.body
    assert "- `back` `src/y.php` — no link" in change.body


def test_no_code_section_without_code_files():
    change = build_decision_change(
        conventions=DecisionConventions(),
        template="# {title}",
        draft=DRAFT,
        number=3,
        meeting_date=date(2026, 10, 15),
        quote="q",
        validated_by="Bob",
        index_content=None,
        language="en",
    )
    assert "Code files" not in change.body
