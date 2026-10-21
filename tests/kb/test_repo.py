from conftest import KB_FILES, commit_file, make_kb_repo

from kb_meeting_agent.config import KbConfig
from kb_meeting_agent.kb import repo
from kb_meeting_agent.kb.repo import GitMarkdownKnowledgeBase
from kb_meeting_agent.llm.fake import FakeProvider


async def test_sync_clones_and_indexes(kb):
    assert kb.conventions.language == "en"
    results = await kb.search("COOLDOWN_SECONDS", k=3)
    assert results[0].path == "reference/configuration.md"
    assert results[0].status == "in_production"
    assert all(chunk.path != "mockups/screen.md" for chunk in await kb.search("999", k=20))


async def test_read_exists_list_and_templates(kb):
    assert kb.exists("decisions/0001-rest.md")
    assert not kb.exists("../outside.md")
    assert sorted(kb.list_files("decisions")) == ["0001-rest.md", "0002-redis.md", "README.md"]
    assert "Use REST." in kb.read("decisions/0001-rest.md")
    assert "BIO-SCAN" in kb.glossary()
    assert "Write in English" in kb.instructions()
    assert kb.template("decision").startswith("# {number:04d}")
    assert "{body}" in kb.template("minutes")


async def test_resync_is_incremental(kb, kb_origin):
    before = kb._index.file_hashes()
    commit_file(kb_origin, "game/ideas.md", "# Ideas\n\nNew content about teleportation.\n")
    commit_file(kb_origin, "decisions/0002-redis.md", None)
    await kb.sync()
    after = kb._index.file_hashes()
    assert "decisions/0002-redis.md" not in after
    assert after["game/ideas.md"] != before["game/ideas.md"]
    assert after["reference/configuration.md"] == before["reference/configuration.md"]
    assert (await kb.search("teleportation", k=1))[0].path == "game/ideas.md"


async def test_changing_embedding_model_rebuilds_the_index(tmp_path, kb_origin):
    config = KbConfig(repo="acme/kb", clone_url=str(kb_origin))
    first = GitMarkdownKnowledgeBase("t", config, tmp_path / "d", FakeProvider().embed, "m1")
    await first.sync()
    first._index.set_meta("probe", "x")
    first._index._db.execute("UPDATE files SET hash = 'stale'")
    first._index._db.commit()
    first.close()
    second = GitMarkdownKnowledgeBase("t", config, tmp_path / "d", FakeProvider().embed, "m2")
    await second.sync()
    assert "stale" not in second._index.file_hashes().values()
    second.close()


async def test_language_falls_back_to_the_instance_setting(tmp_path, kb_origin):
    commit_file(kb_origin, ".meeting-agent.yml", None)
    config = KbConfig(repo="acme/kb", clone_url=str(kb_origin), language="fr")
    knowledge_base = GitMarkdownKnowledgeBase(
        "t", config, tmp_path / "d", FakeProvider().embed, "m"
    )
    assert knowledge_base.conventions.language == "fr"
    await knowledge_base.sync()
    assert knowledge_base.conventions.language == "fr"
    commit_file(kb_origin, ".meeting-agent.yml", "language: de\n")
    await knowledge_base.sync()
    assert knowledge_base.conventions.language == "de"
    knowledge_base.close()


def test_token_is_scoped_to_github_and_kept_out_of_argv(tmp_path):
    config = KbConfig(repo="acme/kb", token="s3cret")
    knowledge_base = GitMarkdownKnowledgeBase(
        "t", config, tmp_path / "d", FakeProvider().embed, "m"
    )
    env = knowledge_base._git_env()
    assert knowledge_base._clone_url() == "https://github.com/acme/kb.git"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ")
    secret = env["GIT_CONFIG_VALUE_0"].removeprefix("Authorization: Basic ")
    redacted = knowledge_base._redact(f"git-remote-curl -c failed s3cret {secret}")
    assert redacted == "git-remote-curl -c failed *** ***"
    knowledge_base.close()


async def test_sync_follows_a_changed_clone_url(tmp_path, kb_origin):
    other = make_kb_repo(tmp_path / "other", KB_FILES | {"game/ideas.md": "# Ideas\n\nZeppelin.\n"})
    embed = FakeProvider().embed
    first = GitMarkdownKnowledgeBase(
        "t", KbConfig(repo="a/b", clone_url=str(kb_origin)), tmp_path / "d", embed, "m"
    )
    await first.sync()
    first.close()
    second = GitMarkdownKnowledgeBase(
        "t", KbConfig(repo="a/b", clone_url=str(other)), tmp_path / "d", embed, "m"
    )
    await second.sync()
    assert (await second.search("Zeppelin", k=1))[0].path == "game/ideas.md"
    second.close()


async def test_truncated_or_missing_instructions_are_logged(kb, kb_origin, monkeypatch, caplog):
    monkeypatch.setattr(repo, "INSTRUCTIONS_MAX_CHARS", 20)
    assert len(kb.instructions()) == 20
    assert "cut at 20" in caplog.text
    yml = KB_FILES[".meeting-agent.yml"].replace("[CONTRIBUTING.md]", "[CONTRIBUTING.md, gone.md]")
    commit_file(kb_origin, ".meeting-agent.yml", yml)
    await kb.sync()
    kb.instructions()
    assert "instruction files not found: gone.md" in caplog.text


async def test_the_glossary_is_cut_unless_asked_whole(kb, kb_origin):
    rows = "".join(f"| TERM-{i:03d} | `t{i}` |\n" for i in range(300))
    commit_file(kb_origin, "reference/glossary.md", "| In-game | Code |\n|---|---|\n" + rows)
    await kb.sync()
    assert len(kb.glossary()) == repo.GLOSSARY_MAX_CHARS
    assert "TERM-299" in kb.glossary(max_chars=None)
