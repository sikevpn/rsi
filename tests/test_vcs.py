"""Snapshot/rollback primitive the quality ratchet depends on — against real git."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rsi.vcs import GitVCS, NoopVCS


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.name", "t"),
        ("config", "user.email", "t@t"),
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-qm", "seed"], cwd=root, check=True, capture_output=True
    )
    return root


def test_is_repo_true_only_at_the_repository_root(repo):
    assert GitVCS(repo).is_repo() is True
    (repo / "sub").mkdir()
    assert GitVCS(repo / "sub").is_repo() is False


def test_is_repo_false_outside_any_repository(tmp_path):
    assert GitVCS(tmp_path).is_repo() is False


def test_snapshot_commits_the_working_tree(repo):
    vcs = GitVCS(repo)
    (repo / "memories.md").write_text("- learned\n", encoding="utf-8")
    assert vcs.snapshot("self-modification") is True
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout
    assert "self-modification" in log


def test_revert_last_undoes_the_self_modification(repo):
    """The ratchet's rollback must actually restore the pre-change tree."""
    vcs = GitVCS(repo)
    (repo / "memories.md").write_text("- bad lesson\n", encoding="utf-8")
    vcs.snapshot("self-modification")
    assert (repo / "memories.md").exists()

    assert vcs.revert_last() is True
    assert not (repo / "memories.md").exists()


def test_changed_paths_lists_dirty_files(repo):
    vcs = GitVCS(repo)
    (repo / "prompts.md").write_text("x\n", encoding="utf-8")
    assert "prompts.md" in vcs.changed_paths()


def test_noop_vcs_records_intent_without_touching_git():
    vcs = NoopVCS()
    assert vcs.snapshot("a") is True
    assert vcs.snapshot("b") is True
    assert vcs.snapshots == ["a", "b"]
    assert vcs.revert_last() is True
    assert vcs.reverts == 1
    assert vcs.changed_paths() == []


def test_git_vcs_on_a_non_repo_is_inert(tmp_path):
    vcs = GitVCS(tmp_path)
    assert vcs.snapshot("x") is False
    assert vcs.revert_last() is False
    assert vcs.changed_paths() == []
