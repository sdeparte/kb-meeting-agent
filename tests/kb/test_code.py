import subprocess

from kb_meeting_agent.kb.code import chunk_code, select_code_files


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
