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

mkdir -p "$HOME/.sintu"
backup_dir="$(mktemp -d "$HOME/.sintu/relay-backup.XXXXXX")"
cp -p "$RELAY" "$backup_dir/github_termux_relay.py"

python - "$RELAY" <<'PY'
from pathlib import Path
import os
import re
import stat
import sys
import tempfile

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
actions = re.search(r"(?ms)^ACTIONS\\s*=\\s*\\{.*?^\\}", source)
if not actions:
    raise SystemExit("Could not locate the relay allowlist; no changes made.")
block = actions.group(0)
if "main_worktree_tests" not in block:
    if '"run_tests"' in block:
        block = block.replace('"run_tests"', '"run_tests", "main_worktree_tests"', 1)
    elif "'run_tests'" in block:
        block = block.replace("'run_tests'", "'run_tests', 'main_worktree_tests'", 1)
    else:
        raise SystemExit("Could not safely extend the relay allowlist; no changes made.")
    source = source[:actions.start()] + block + source[actions.end():]

if 'scripts/termux_main_worktree_tests.py' not in source:
    command = re.search(r'(?m)^([ \\t]*)if action == ["\\']run_tests["\\']:\\s*$', source)
    if not command:
        raise SystemExit("Could not locate the fixed run_tests command mapping; no changes made.")
    indent = command.group(1)
    insertion = (
        indent + 'if action == "main_worktree_tests":\\n'
        + indent + '    return [PYTHON, "scripts/termux_main_worktree_tests.py"]\\n'
    )
    source = source[:command.start()] + insertion + source[command.start():]

actions = re.search(r"(?ms)^ACTIONS\\s*=\\s*\\{.*?^\\}", source)
if not actions or "main_worktree_tests" not in actions.group(0) or 'scripts/termux_main_worktree_tests.py' not in source:
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
