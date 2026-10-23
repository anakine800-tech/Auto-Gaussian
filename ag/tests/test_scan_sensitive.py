"""Exercise archive renames through real Git diffs and the scanner CLI."""

from pathlib import Path
import subprocess
import sys

import pytest


SCANNER = Path(__file__).parents[1] / "tools" / "scan_sensitive.py"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def prepare_rename(repo, content):
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Scanner Test")
    git(repo, "config", "user.email", "scanner@example.invalid")  # scan-public: allow synthetic reserved-domain email fixture
    (repo / "legacy.txt").write_text(content)
    git(repo, "add", "legacy.txt")
    git(repo, "commit", "-qm", "baseline")
    (repo / "archive").mkdir()
    git(repo, "mv", "legacy.txt", "archive/legacy.txt")


def scan(repo, mode):
    if mode == "staged":
        args = ["--staged"]
    else:
        git(repo, "commit", "-qm", "archive")
        args = ["--base", "HEAD^", "--head", "HEAD"]
    return subprocess.run(
        [sys.executable, str(SCANNER), *args], cwd=repo,
        capture_output=True, text=True,
    )


@pytest.mark.parametrize("mode", ["staged", "committed"])
def test_identical_rename_preserves_legacy_path_without_rescanning(tmp_path, mode):
    private_path = "/".join(("", "home", "researcher", "study"))
    prepare_rename(tmp_path, private_path + "\n")
    result = scan(tmp_path, mode)
    assert result.returncode == 0, result.stderr
    assert "Sensitive information scan passed." in result.stdout


@pytest.mark.parametrize("mode", ["staged", "committed"])
def test_modified_rename_with_private_path_fails(tmp_path, mode):
    original = "Historical reference text.\n" * 100
    prepare_rename(tmp_path, original)
    private_path = "/".join(("", "Users", "researcher", "study"))
    (tmp_path / "archive/legacy.txt").write_text(original + private_path + "\n")
    git(tmp_path, "add", "archive/legacy.txt")
    result = scan(tmp_path, mode)
    assert result.returncode == 1, result.stderr
    assert "Sensitive information (user directory): archive/legacy.txt" in result.stdout
    assert private_path not in result.stdout + result.stderr
