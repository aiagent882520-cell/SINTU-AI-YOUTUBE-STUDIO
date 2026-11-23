#!/data/data/com.termux/files/usr/bin/bash
# Safely enable isolated-main tests in an existing dirty SINTU checkout.
# Only patches the clean GitHub issue relay file and adds one new helper script.
set -Eeuo pipefail

APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
RELAY="scripts/github_termux_relay.py"
HELPER="scripts/termux_main_worktree_tests.py"

cd "$APP_DIR"
[ -d .git ] || { echo "SINTU Git repository not found: $APP_DIR" >&2; exit 2; }
[ ! -L "$RELAY" ] || { echo "Relay file is a symlink; refusing to modify it." >&2; exit 2; }
git ls-files --error-unmatch "$RELAY" >/dev/null
git diff --quiet HEAD -- "$RELAY" || {
  echo "Relay file has local modifications; refusing to overwrite it." >&2
  exit 3
}

git fetch origin main:refs/remotes/origin/main
git cat-file -e "origin/main:$HELPER"

helper_tmp="$(mktemp "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/sintu-main-worktree.XXXXXX")"
trap 'rm -f "$helper_tmp"' EXIT
git show "origin/main:$HELPER" > "$helper_tmp"
if [ -e "$HELPER" ] || [ -L "$HELPER" ]; then
  [ ! -L "$HELPER" ] || { echo "Helper path is a symlink; refusing." >&2; exit 3; }
  cmp -s "$helper_tmp" "$HELPER" || {
    echo "A different untracked helper already exists; refusing to overwrite it." >&2
    exit 3
  }
else
  install -m 600 "$helper_tmp" "$HELPER"
fi

backup_dir="$(mktemp -d "$HOME/.sintu/relay-backup.XXXXXX")"
cp -p "$RELAY" "$backup_dir/github_termux_relay.py"

python - "$RELAY" <<'PY'
from pathlib import Path
import os
import stat
import sys
import tempfile

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
action_anchor = '"git_status", "git_pull_ff_only", "run_tests", "compile_check",'
command_anchor = '    if action == "run_tests":\n'
if '"main_worktree_tests"' not in source:
    if source.count(action_anchor) != 1 or source.count(command_anchor) != 1:
        raise SystemExit("Relay source layout did not match the expected safe patch anchors; no changes made.")
    source = source.replace(
        action_anchor,
        '"git_status", "git_pull_ff_only", "run_tests", "main_worktree_tests", "compile_check",',
        1,
    )
    source = source.replace(
        command_anchor,
        '    if action == "main_worktree_tests":\n'
        '        return [PYTHON, "scripts/termux_main_worktree_tests.py"]\n'
        + command_anchor,
        1,
    )
    if '"main_worktree_tests"' not in source or 'scripts/termux_main_worktree_tests.py' not in source:
        raise SystemExit("Relay patch verification failed; no changes made.")
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temporary = tempfile.mkstemp(prefix=".github_termux_relay.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(source)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
print("SINTU isolated-main relay action installed.")
PY

echo "Backup: $backup_dir/github_termux_relay.py"
echo "Existing dirty project files were not changed."
echo "Next: bash scripts/start_services.sh"
