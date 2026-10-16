from kb_meeting_agent.agent.messages import t
from kb_meeting_agent.agent.prompting import format_chunks, format_segments, format_timestamp
from kb_meeting_agent.agent.transcript import Transcript, load_segments
from kb_meeting_agent.models import Chunk, Segment


def seg(start, end, text, name="Alice"):
    return Segment(speaker_id=name.lower(), speaker_name=name, start=start, end=end, text=text)


def test_append_persists_and_reloads(tmp_path):
    path = tmp_path / "meeting" / "transcript.jsonl"
    transcript = Transcript(path)
    transcript.append(seg(0, 2, "Bonjour à tous"))
    transcript.append(seg(2, 4, "Salut"))
    assert [s.text for s in Transcript(path).all()] == ["Bonjour à tous", "Salut"]
    assert "Bonjour à tous" in path.read_text(encoding="utf-8")


def test_window_keeps_recent_segments(tmp_path):
    transcript = Transcript(tmp_path / "t.jsonl")
    for i in range(10):
        transcript.append(seg(i * 30, i * 30 + 5, f"s{i}"))
    assert [s.text for s in transcript.window(60)] == ["s7", "s8", "s9"]


def test_load_segments_ignores_blank_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    Transcript(path).append(seg(0, 1, "x"))
    path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
    assert len(load_segments(path)) == 1


def test_formatting():
    assert format_timestamp(3725.4) == "01:02:05"
    assert format_segments([seg(65, 70, "Hello")]) == "[00:01:05] Alice: Hello"
    chunk = Chunk("a.md", ("H",), "Body", "planned", "2026-10-01")
    text = format_chunks([chunk])
    assert 'source="a.md#H"' in text and 'status="planned"' in text and "Body" in text


def test_messages_fall_back_to_english():
    assert t("fr", "not_covered") != t("en", "not_covered")
    assert t("de", "not_covered") == t("en", "not_covered")
    assert "Bob" in t("fr", "decision_ignored", user="Bob")
