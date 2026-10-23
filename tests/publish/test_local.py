import json

import pytest

from kb_meeting_agent.ports import PublishError
from kb_meeting_agent.publish.local import (
    INDEX_ROWS_FILE,
    DryRunPublisher,
    FakePublisher,
    LocalKeeper,
)


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


async def test_dry_run_update_branch_rewrites_files(tmp_path):
    publisher = DryRunPublisher(tmp_path)
    pr = await publisher.open_pr("decision/x", {"a.md": "v1"}, "T", "B")
    assert await publisher.is_open(pr)
    assert await publisher.update_branch("decision/x", {"a.md": "v2"}, "T", "h") == "h"
    assert (tmp_path / "decision/x/a.md").read_text(encoding="utf-8") == "v2"


async def test_dry_run_can_hide_local_paths(tmp_path):
    publisher = DryRunPublisher(tmp_path, local_urls=False)
    pr = await publisher.open_pr("decision/x", {"a.md": "v1"}, "T", "B")
    assert pr.url == "dry run: decision/x"
    assert str(tmp_path) not in pr.url


async def test_local_keeper_writes_the_change_and_its_index_rows(tmp_path):
    keeper = LocalKeeper(tmp_path / "unpublished")
    await keeper.keep(
        "decision/x",
        {"decisions/0003-x.md": "content"},
        "T",
        "Body",
        {"decisions/README.md": "| 3 |"},
    )
    root = tmp_path / "unpublished" / "decision/x"
    assert (root / "decisions/0003-x.md").read_text(encoding="utf-8") == "content"
    assert (root / "PR.md").read_text(encoding="utf-8") == "# T\n\nBody"
    assert json.loads((root / INDEX_ROWS_FILE).read_text(encoding="utf-8")) == {
        "decisions/README.md": "| 3 |"
    }


async def test_local_keeper_writes_no_index_rows_file_when_there_are_none(tmp_path):
    keeper = LocalKeeper(tmp_path)
    await keeper.keep("b", {"a.md": "x"}, "T", "B", {})
    assert not (tmp_path / "b" / INDEX_ROWS_FILE).exists()
