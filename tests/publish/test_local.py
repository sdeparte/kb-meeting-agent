import pytest

from kb_meeting_agent.ports import PublishError
from kb_meeting_agent.publish.local import DryRunPublisher, FakePublisher


async def test_dry_run_writes_files_and_description(tmp_path):
    publisher = DryRunPublisher(tmp_path)
    pr = await publisher.open_pr("decision/x", {"decisions/0003-x.md": "content"}, "T", "Body")
    assert (tmp_path / "decision/x/decisions/0003-x.md").read_text(encoding="utf-8") == "content"
    assert "Body" in (tmp_path / "decision/x/PR.md").read_text(encoding="utf-8")
    assert pr.number == 1 and pr.url.startswith("file://")
    assert await publisher.open_pr_paths("decisions/") == []


async def test_fake_publisher_records_prs():
    publisher = FakePublisher(open_paths=["decisions/0005-z.md"])
    pr = await publisher.open_pr("b", {"f": "c"}, "T", "B")
    assert pr.url == "https://example.test/pull/1"
    assert publisher.prs == [("b", {"f": "c"}, "T", "B")]
    assert await publisher.open_pr_paths("decisions/") == ["decisions/0005-z.md"]


async def test_dry_run_refuses_paths_outside_its_directory(tmp_path):
    publisher = DryRunPublisher(tmp_path / "out")
    with pytest.raises(PublishError):
        await publisher.open_pr("decision/x", {"../../escape.md": "x"}, "T", "B")
    with pytest.raises(PublishError):
        await publisher.open_pr("../../escape", {"a.md": "x"}, "T", "B")
    assert not (tmp_path / "escape.md").exists()
    assert not list(tmp_path.glob("escape*"))
