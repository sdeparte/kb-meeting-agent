import subprocess

from conftest import commit_file

from kb_meeting_agent.config import RepoConfig
from kb_meeting_agent.kb.code import GitCodeRepository, chunk_code, select_code_files
from kb_meeting_agent.llm.fake import FakeProvider


def git_repo(root, files):
    for path, content in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    return root


def test_select_code_files_skips_binaries_large_and_generated(tmp_path):
    root = git_repo(
        tmp_path,
        {
            "src/a.php": "<?php\n",
            "lib/b.dart": "void main() {}\n",
            "lib/b.g.dart": "// generated\n",
            "assets/logo.png": b"\x89PNG\x00\x00",
            "big.txt": "x" * 200_001,
            "composer.lock": "{}",
            "app/node_modules/x/index.js": "x",
            "web/app.min.js": "x",
        },
    )
    (root / "untracked.py").write_text("x")
    assert select_code_files(root, [], []) == ["lib/b.dart", "src/a.php"]


def test_secrets_are_never_selected(tmp_path):
    root = git_repo(
        tmp_path,
        {
            ".env": "A=1",
            "config/.env.local": "A=1",
            "certs/server.pem": "x",
            "keys/id.key": "x",
            "src/client_secret.json": "{}",
            "src/credentials.py": "x",
            "src/ok.py": "x",
        },
    )
    assert select_code_files(root, [], []) == ["src/ok.py"]


def test_include_and_exclude(tmp_path):
    root = git_repo(tmp_path, {"src/a.py": "x", "src/b.py": "x", "tools/c.py": "x"})
    assert select_code_files(root, ["src/**"], ["src/b.py"]) == ["src/a.py"]


def test_chunk_code_windows_snap_to_blank_lines_and_overlap():
    lines = [f"line {i}" for i in range(1, 131)]
    lines[54] = ""  # line 55 is blank: the first window ends there
    chunks = chunk_code("back", ("CodeBase", "BackEnd"), "src/x.php", "\n".join(lines))
    assert [(c.start_line, c.end_line) for c in chunks] == [(1, 55), (46, 105), (96, 130)]
    first = chunks[0]
    assert first.repo == "back" and first.tags == ("CodeBase", "BackEnd")
    assert first.anchor == "back:src/x.php:1-55"
    assert first.citation == "[BackEnd] back:src/x.php:1-55"
    assert first.text.splitlines()[0] == "line 1"


def test_blank_files_give_no_chunk():
    assert chunk_code("back", ("CodeBase",), "a.py", "\n\n") == []


def test_secrets_are_matched_whatever_their_case(tmp_path):
    root = git_repo(
        tmp_path, {".ENV": "A=1", "src/Client_Secret.json": "{}", "certs/a.PEM": "x", "ok.py": "x"}
    )
    assert select_code_files(root, [], []) == ["ok.py"]


def test_symbolic_links_are_never_followed(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "link.txt").symlink_to(outside)
    git_repo(repo, {"ok.py": "x"})
    assert select_code_files(repo, [], []) == ["ok.py"]


def code_repo(tmp_path, origin):
    config = RepoConfig(repo="acme/back", clone_url=str(origin), tags=["CodeBase", "BackEnd"])
    return GitCodeRepository("back", config, tmp_path / "back", FakeProvider().embed, "fake")


async def test_sync_indexes_code_and_search_labels_it(tmp_path, code_origin):
    repo = code_repo(tmp_path, code_origin)
    assert not repo.indexed
    await repo.sync()
    assert repo.indexed
    [hit, *_] = await repo.search("COOLDOWN_SECONDS", k=3)
    assert hit.anchor == "back:src/Game/Relay/RelayConfigProvider.php:1-6"
    assert hit.citation.startswith("[BackEnd] back:")
    assert repo.exists("lib/game/cooldown.dart") and not repo.exists(".env")
    assert all(".env" not in c.path for c in await repo.search("SECRET", k=10))
    repo.close()


async def test_resync_is_incremental(tmp_path, code_origin):
    repo = code_repo(tmp_path, code_origin)
    await repo.sync()
    commit_file(code_origin, "lib/game/zeppelin.dart", "const kZeppelin = 1;\n")
    await repo.sync()
    assert (await repo.search("kZeppelin", k=1))[0].path == "lib/game/zeppelin.dart"
    repo.close()


SECRET_FILES = [
    ".envrc",
    ".env-local",
    "config/.env_prod",
    "docker/prod.env",
    "id_rsa",
    ".ssh/id_ed25519",
    "android/key.properties",
    "android/app/upload.keystore",
    "ios/cert.p12",
    "release.jks",
    "android/app/google-services.json",
    "ios/Runner/GoogleService-Info.plist",
    ".npmrc",
    ".netrc",
    ".pypirc",
    "infra/prod.tfvars",
    "infra/terraform.tfstate",
    "infra/terraform.tfstate.backup",
]


def test_known_secret_files_are_never_selected(tmp_path):
    root = git_repo(tmp_path, {**dict.fromkeys(SECRET_FILES, "x"), "src/ok.py": "x"})
    assert select_code_files(root, [], []) == ["src/ok.py"]


async def test_files_holding_a_secret_are_not_indexed(tmp_path):
    origin = tmp_path / "origin"
    files = {
        "src/deploy.py": "KEY = '''-----BEGIN RSA PRIVATE KEY-----\nabc\n'''\n",
        "src/ci.py": "TOKEN = 'ghp_" + "a" * 36 + "'\n",
        "src/aws.py": "ACCESS = 'AKIA" + "A" * 16 + "'\n",
        "src/pay.py": "STRIPE = 'sk_live_" + "a" * 24 + "'\n",
        "src/maps.dart": "const key = 'AIza" + "B" * 35 + "';\n",
        "ci/gitlab.sh": "export T=glpat-" + "c" * 20 + "\n",
        "src/db.py": "URL = 'postgres://app:Hunter2pw@db.internal/app'\n",
        "src/ok.py": "COOLDOWN = 30\nDOCS = 'https://example.com/a:b@c'\n",
    }
    from conftest import make_kb_repo

    make_kb_repo(origin, files)
    repo = code_repo(tmp_path, origin)
    await repo.sync()
    assert repo.exists("src/ok.py")
    secrets = ("src/deploy.py", "src/ci.py", "src/aws.py", "src/pay.py", "src/maps.dart")
    assert not any(repo.exists(path) for path in (*secrets, "ci/gitlab.sh", "src/db.py"))
    repo.close()


async def test_a_file_holding_a_secret_is_read_once_while_unchanged(
    tmp_path, code_origin, monkeypatch, caplog
):
    from kb_meeting_agent.kb import code

    commit_file(code_origin, "src/ci.py", "TOKEN = 'ghp_" + "a" * 36 + "'\n")
    repo = code_repo(tmp_path, code_origin)
    await repo.sync()
    read = []
    original = code._read_source
    monkeypatch.setattr(code, "_read_source", lambda path: read.append(path) or original(path))
    caplog.clear()
    await repo.sync()
    assert read == [] and "holds a secret" not in caplog.text
    commit_file(code_origin, "src/ci.py", "TOKEN = None\n")
    await repo.sync()
    assert repo.exists("src/ci.py")
    repo.close()


async def test_resync_reads_only_the_changed_files(tmp_path, code_origin, monkeypatch):
    from kb_meeting_agent.kb import code

    repo = code_repo(tmp_path, code_origin)
    await repo.sync()
    read = []
    original = code._read_source
    monkeypatch.setattr(code, "_read_source", lambda path: read.append(path) or original(path))
    commit_file(code_origin, "lib/game/cooldown.dart", "const kCooldown = 45;\n")
    await repo.sync()
    assert [p.name for p in read] == ["cooldown.dart"]
    assert "45" in (await repo.search("kCooldown", k=1))[0].text
    repo.close()


async def test_a_stricter_secret_check_reindexes(tmp_path, code_origin, monkeypatch):
    import re

    from kb_meeting_agent.kb import code

    repo = code_repo(tmp_path, code_origin)
    await repo.sync()
    assert repo.exists("lib/game/cooldown.dart")
    monkeypatch.setattr(code, "SECRET_CONTENT", re.compile("kCooldown"))
    await repo.sync()
    assert not repo.exists("lib/game/cooldown.dart")
    repo.close()


async def test_a_new_exclude_drops_files_without_reindexing(tmp_path, code_origin, monkeypatch):
    from kb_meeting_agent.kb import code

    repo = code_repo(tmp_path, code_origin)
    await repo.sync()
    repo.close()
    read = []
    original = code._read_source
    monkeypatch.setattr(code, "_read_source", lambda path: read.append(path) or original(path))
    config = RepoConfig(
        repo="acme/back",
        clone_url=str(code_origin),
        tags=["CodeBase", "BackEnd"],
        exclude=["lib/**"],
    )
    repo = GitCodeRepository("back", config, tmp_path / "back", FakeProvider().embed, "fake")
    await repo.sync()
    assert not repo.exists("lib/game/cooldown.dart")
    assert repo.exists("src/Game/Relay/RelayConfigProvider.php")
    assert read == []
    repo.close()


async def test_two_syncs_of_the_same_checkout_do_not_collide(tmp_path, code_origin):
    import asyncio

    first, second = code_repo(tmp_path, code_origin), code_repo(tmp_path, code_origin)
    await asyncio.gather(first.sync(), second.sync())
    assert first.exists("lib/game/cooldown.dart")
    first.close()
    second.close()
