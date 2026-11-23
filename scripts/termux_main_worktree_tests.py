#!/usr/bin/env python3
"""Run the GitHub main test suite in an isolated Termux git worktree.

The user's existing checkout is never reset, stashed, cleaned, or overwritten.
The shared virtualenv is reused; only a clean dedicated worktree is checked out.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKTREE = Path.home() / ".sintu" / "worktrees" / "main"
PYTHON = ROOT / ".venv" / "bin" / "python"
if not PYTHON.is_file():
    PYTHON = Path(sys.executable)


def git(*args: str, cwd: Path = ROOT) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False, timeout=180,
    )
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed (exit {result.returncode}):\n{result.stdout[-5000:]}")
    return result.stdout.strip()


def registered_worktrees() -> set[Path]:
    output = git("worktree", "list", "--porcelain")
    paths = set()
    for line in output.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line[9:]).resolve())
    return paths


def prepare_worktree() -> str:
    if WORKTREE.is_symlink():
        raise RuntimeError("Dedicated main worktree path is a symlink; refusing to use it.")
    WORKTREE.parent.mkdir(parents=True, exist_ok=True)
    git("fetch", "origin", "main:refs/remotes/origin/main")
    registered = registered_worktrees()
    target = WORKTREE.resolve()
    if WORKTREE.exists():
        if target not in registered:
            raise RuntimeError("Dedicated worktree path already exists but is not registered with this repository; refusing to modify it.")
        dirty = git("-C", str(WORKTREE), "status", "--porcelain", "--untracked-files=all")
        if dirty:
            raise RuntimeError("Dedicated main worktree contains local changes; refusing to overwrite them.")
        git("-C", str(WORKTREE), "checkout", "--detach", "origin/main")
    else:
        if target in registered:
            raise RuntimeError("Git reports the dedicated worktree as registered but its directory is missing.")
        git("worktree", "add", "--detach", str(WORKTREE), "origin/main")
    head = git("-C", str(WORKTREE), "rev-parse", "HEAD")
    upstream = git("rev-parse", "origin/main")
    if head != upstream:
        raise RuntimeError("Isolated worktree HEAD does not match fetched origin/main.")
    return head


def main() -> int:
    try:
        head = prepare_worktree()
        print(f"SINTU_MAIN_WORKTREE={head}", flush=True)
        print(f"SINTU_MAIN_WORKTREE_PATH={WORKTREE}", flush=True)
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        result = subprocess.run(
            [str(PYTHON), "-m", "pytest", "-q"], cwd=WORKTREE,
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=1800, check=False, env=env,
        )
        output = result.stdout or "(pytest produced no output)"
        print(output[-16000:], end="" if output.endswith("\n") else "\n")
        print(f"SINTU_MAIN_WORKTREE_TEST_EXIT={result.returncode}")
        return result.returncode
    except subprocess.TimeoutExpired:
        print("Isolated main test suite exceeded the 30-minute timeout.", file=sys.stderr)
        return 124
    except Exception as exc:
        print(f"Isolated main test suite could not start: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
