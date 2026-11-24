"""Safety regression tests for the isolated Termux main worktree runner."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts import termux_main_worktree_tests as runner


def _configure(tmp_path, monkeypatch, *, registered=False, status="", head="main-sha",
               upstream="main-sha"):
    root = tmp_path / "checkout"
    root.mkdir()
    worktree = tmp_path / ".sintu" / "worktrees" / "main"
    monkeypatch.setattr(runner, "ROOT", root)
    monkeypatch.setattr(runner, "WORKTREE", worktree)
    monkeypatch.setattr(runner.Path, "home", classmethod(lambda cls: tmp_path))

    calls = []
    registered_output = f"worktree {worktree.resolve()}\n" if registered else ""

    def fake_git(*args, cwd=root):
        calls.append(args)
        if args == ("fetch", "origin", "main:refs/remotes/origin/main"):
            return ""
        if args == ("worktree", "list", "--porcelain"):
            return registered_output
        if args[:2] == ("worktree", "add"):
            worktree.mkdir(parents=True, exist_ok=True)
            return ""
        if args[:1] == ("-C",) and args[2:4] == ("status", "--porcelain"):
            return status
        if args[:1] == ("-C",) and args[2:] == ("checkout", "--detach", "origin/main"):
            return ""
        if args[:1] == ("-C",) and args[2:] == ("rev-parse", "HEAD"):
            return head
        if args == ("rev-parse", "origin/main"):
            return upstream
        raise AssertionError(f"Unexpected git command: {args}")

    monkeypatch.setattr(runner, "git", fake_git)
    return worktree, calls


def test_new_isolated_worktree_is_created_at_fetched_main(tmp_path, monkeypatch):
    worktree, calls = _configure(tmp_path, monkeypatch)

    assert runner.prepare_worktree() == "main-sha"
    assert worktree.is_dir()
    assert ("fetch", "origin", "main:refs/remotes/origin/main") in calls
    assert ("worktree", "add", "--detach", str(worktree), "origin/main") in calls
    assert not any(command[0] in {"reset", "clean", "stash", "pull"} for command in calls)


def test_clean_registered_worktree_is_advanced_only_after_clean_check(tmp_path, monkeypatch):
    worktree, calls = _configure(tmp_path, monkeypatch, registered=True)
    worktree.mkdir(parents=True)

    assert runner.prepare_worktree() == "main-sha"
    status_index = calls.index(("-C", str(worktree), "status", "--porcelain", "--untracked-files=all"))
    checkout_index = calls.index(("-C", str(worktree), "checkout", "--detach", "origin/main"))
    assert status_index < checkout_index


def test_dirty_registered_worktree_is_never_overwritten(tmp_path, monkeypatch):
    worktree, calls = _configure(tmp_path, monkeypatch, registered=True, status=" M owner-data.txt")
    worktree.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="contains local changes"):
        runner.prepare_worktree()

    assert not any("checkout" in command for command in calls)


def test_existing_unregistered_directory_is_refused(tmp_path, monkeypatch):
    worktree, _ = _configure(tmp_path, monkeypatch)
    worktree.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="not registered"):
        runner.prepare_worktree()


def test_symlinked_worktree_parent_is_refused_before_git_access(tmp_path, monkeypatch):
    worktree, calls = _configure(tmp_path, monkeypatch)
    worktree.parent.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    worktree.parent.symlink_to(outside, target_is_directory=True)

    with pytest.raises(RuntimeError, match="symlink"):
        runner.prepare_worktree()

    assert calls == []


def test_worktree_head_must_match_fetched_origin_main(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, head="old-sha", upstream="new-sha")

    with pytest.raises(RuntimeError, match="does not match fetched origin/main"):
        runner.prepare_worktree()


def test_runner_executes_pytest_inside_isolated_worktree(tmp_path, monkeypatch, capsys):
    worktree, _ = _configure(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "prepare_worktree", lambda: "verified-main-sha")
    monkeypatch.setattr(runner, "PYTHON", "/termux/.venv/bin/python")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="12 passed\\n")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.main() == 0
    assert captured["command"] == ["/termux/.venv/bin/python", "-m", "pytest", "-q"]
    assert captured["cwd"] == worktree
    assert captured["timeout"] == 1800
    assert captured["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
    output = capsys.readouterr().out
    assert "SINTU_MAIN_WORKTREE=verified-main-sha" in output
    assert "SINTU_MAIN_WORKTREE_TEST_EXIT=0" in output
