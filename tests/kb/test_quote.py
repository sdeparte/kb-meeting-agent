from kb_meeting_agent.kb.quote import find_quote_line, quote_exists

DOC = "| `COOLDOWN_SECONDS` | `45` | Cooldown after a **neutralization** `[PROD]` |"


def test_quote_matches_despite_markdown_and_spacing():
    assert quote_exists("COOLDOWN_SECONDS | 45", DOC)
    assert quote_exists("cooldown after a   neutralization", DOC)


def test_invented_or_too_short_quote_is_rejected():
    assert not quote_exists("COOLDOWN_SECONDS | 30", DOC)
    assert not quote_exists("45", DOC)


def test_find_quote_line_returns_the_whole_kb_line():
    doc = "# Biometric\n\nBIO-SCAN is not enabled by default.\n"
    assert find_quote_line("enabled by default", doc) == "BIO-SCAN is not enabled by default."
    assert find_quote_line("COOLDOWN_SECONDS | 45", DOC) == DOC


def test_find_quote_line_spans_wrapped_lines():
    doc = "# Arme\n\nLe cooldown de l'arme est de 30 secondes,\nsauf pendant un blackout.\n"
    expected = "Le cooldown de l'arme est de 30 secondes,\nsauf pendant un blackout."
    assert find_quote_line("30 secondes, sauf pendant un blackout", doc) == expected


def test_find_quote_line_spans_table_header_and_row():
    doc = "| Variable | Default |\n|---|---|\n| `COOLDOWN_SECONDS` | `45` |\n"
    found = find_quote_line("Variable | Default | COOLDOWN_SECONDS | 45", doc)
    assert found == "| Variable | Default |\n|---|---|\n| `COOLDOWN_SECONDS` | `45` |"
