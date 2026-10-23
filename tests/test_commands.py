import pytest

from kb_meeting_agent.agent.messages import _MESSAGES as MESSAGES
from kb_meeting_agent.commands import (
    CATALOG,
    Parsed,
    button_commands,
    catalog_payload,
    help_text,
    parse,
    typed,
)


def test_lines_without_a_bang_are_not_commands():
    assert parse("bonjour") is None
    assert parse("on dit !fin ?") is None


@pytest.mark.parametrize("text", ["!fin", "!END", "  !end  "])
def test_words_match_in_both_languages_and_any_case(text):
    assert parse(text) == Parsed("meeting_end", {})


def test_a_rest_option_takes_the_line_with_spacing_collapsed():
    assert parse("!ask  quel   cooldown ?") == Parsed("ask", {"question": "quel cooldown ?"})


def test_edit_takes_the_decision_and_the_statement():
    assert parse("!modifier d1 On passe à 45 s") == Parsed(
        "decision_edit", {"decision": "d1", "statement": "On passe à 45 s"}
    )


@pytest.mark.parametrize("text", ["!modifier d1", "!niveau bavard", "!valider", "!"])
def test_invalid_commands_get_the_help(text):
    assert parse(text) == Parsed("help", {})


def test_an_unknown_word_is_flagged_as_such():
    assert parse("!play lofi") == Parsed("help", {}, known=False)


def test_options():
    assert parse("!level context") == Parsed("meeting_level", {"level": "context"})
    assert parse("!start") == Parsed("meeting_start", {})
    assert parse("!start cyberhack") == Parsed("meeting_start", {"project": "cyberhack"})
    assert parse("!projet cyberhack") == Parsed("meeting_project", {"project": "cyberhack"})
    assert parse("!valider d2") == Parsed("decision_validate", {"decision": "d2"})


def test_button_commands():
    assert button_commands("decision:d1:validate", "fr") == "!valider d1"
    assert button_commands("decision:d1:ignore", "en") == "!ignore d1"
    assert button_commands("decision:d1:edit", "en") == "!edit d1 <statement>"
    assert button_commands("decision:d1:edit", "fr") == "!modifier d1 <énoncé>"
    assert button_commands("other", "en") is None


def test_the_catalog_payload_lists_the_slash_commands():
    payload = catalog_payload()
    assert {c["id"] for c in payload} == {
        "meeting_start",
        "meeting_project",
        "meeting_end",
        "ask",
        "meeting_level",
        "meeting_optout",
        "meeting_resume",
        "meeting_retry_publish",
    }
    start = next(c for c in payload if c["id"] == "meeting_start")
    assert start["slash"] == ["meeting", "start"]
    end = next(c for c in payload if c["id"] == "meeting_end")
    assert parse("!" + end["words"][-1]) == Parsed("meeting_end", {})
    assert start["options"][0] == {
        "name": "project",
        "description": start["options"][0]["description"],
        "required": False,
        "choices": [],
    }


def test_help_follows_the_language():
    assert "!fin" in help_text("fr") and "!end" not in help_text("fr")
    assert "!end" in help_text("en")
    assert "`!ask <question>`" in help_text("en") and "!question" not in help_text("en")
    assert "`!question <question>`" in help_text("fr")


def test_the_help_names_no_platform():
    assert "Discord" not in help_text("en") and "Discord" not in help_text("fr")


def test_typed_gives_the_word_of_the_language():
    assert typed("meeting_resume", "fr") == "!reprendre"
    assert typed("meeting_resume", "en") == "!resume"


def test_every_command_has_a_description_in_both_languages():
    for command in CATALOG:
        for lang in ("en", "fr"):
            assert f"command_{command.id}" in MESSAGES[lang]
