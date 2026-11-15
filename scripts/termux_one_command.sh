#!/data/data/com.termux/files/usr/bin/bash
# SINTU AI YOUTUBE STUDIO - one-command Termux bootstrap
# Free/local-first. Safe to rerun. Does not overwrite existing secrets or user data.
set -Eeuo pipefail

REPO="https://github.com/aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO.git"
BRANCH="${SINTU_INSTALL_BRANCH:-main}"
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
PID_FILE="$LOG_DIR/server.pid"
LOG_FILE="$LOG_DIR/server.log"

say(){ printf '\n[SINTU] %s\n' "$*"; }
fail(){ printf '\n[SINTU ERROR] %s\n' "$*" >&2; exit 1; }
trap 'fail "Setup failed at line $LINENO. Log: $LOG_FILE (if created). Fix the reported error and rerun this script."' ERR

[ -n "${PREFIX:-}" ] || fail "Termux required. Open Termux app and run this command there."
mkdir -p "$LOG_DIR"

say "Updating Termux packages"
pkg update -y
pkg upgrade -y
# Speech engines are deliberately optional: package names differ across Termux
# repository snapshots. Their absence must never block the studio installation.
pkg install -y git python python-pip python-pillow python-cryptography ffmpeg openssl curl libjpeg-turbo libpng freetype clang make pkg-config

say "Checking shared storage permission (optional)"
if [ ! -d "$HOME/storage/shared" ]; then
  termux-setup-storage || true
fi

if [ -d "$APP_DIR/.git" ]; then
  say "Updating existing repository"
  git -C "$APP_DIR" fetch origin "$BRANCH"
  git -C "$APP_DIR" checkout "$BRANCH"
  git -C "$APP_DIR" pull --ff-only origin "$BRANCH"
elif [ -e "$APP_DIR" ]; then
  fail "$APP_DIR exists but is not a Git repository. Move it or set SINTU_APP_DIR."
else
  say "Downloading SINTU repository"
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$APP_DIR"
fi

cd "$APP_DIR"
[ -f requirements.txt ] || fail "requirements.txt missing; repository checkout is incomplete."
[ -f app/main.py ] || fail "app/main.py missing; repository checkout is incomplete."

say "Creating isolated Python environment"
if [ ! -x .venv/bin/python ]; then
  python -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt

say "Creating local-first environment file"
if [ ! -f .env ]; then
  .venv/bin/python - <<'PY'
from pathlib import Path
import secrets
import shutil
source = Path(".env.example")
text = source.read_text(encoding="utf-8") if source.exists() else ""
admin_password = secrets.token_urlsafe(24)
text = text.replace("SINTU_ADMIN_PASSWORD=CHANGE-THIS-TO-A-LONG-UNIQUE-PASSWORD",
                    "SINTU_ADMIN_PASSWORD=" + admin_password)
text = text.replace("SINTU_SESSION_SECRET=CHANGE-THIS-TO-A-RANDOM-64-CHARACTER-SECRET",
                    "SINTU_SESSION_SECRET=" + secrets.token_hex(32))
text = text.replace("SINTU_BIND_ADDRESS=127.0.0.1", "SINTU_BIND_ADDRESS=127.0.0.1")
text = text.replace("AI_PROVIDER=local", "AI_PROVIDER=local")
speech = shutil.which("espeak-ng") or shutil.which("espeak")
if speech:
    text = text.replace("ESPEAK_EXECUTABLE=espeak", "ESPEAK_EXECUTABLE=" + speech)
Path(".env").write_text(text, encoding="utf-8")
Path(".env").chmod(0o600)
print("Created .env. Save these first-login credentials securely:")
print("Username: admin")
print("Password: " + admin_password)
if not speech:
    print("No eSpeak binary found; install will continue without this optional TTS fallback.")
PY
else
  say "Existing .env preserved; secrets were not overwritten"
fi

say "Checking local media tools"
command -v ffmpeg >/dev/null || fail "FFmpeg is required but unavailable."
command -v ffprobe >/dev/null || fail "FFprobe is required but unavailable."
if command -v espeak-ng >/dev/null; then
  say "Optional eSpeak NG voice engine available"
elif command -v espeak >/dev/null; then
  say "Optional eSpeak voice engine available"
else
  say "No eSpeak binary found; studio setup continues. Configure Piper or another TTS engine later."
fi

say "Running Python compile check"
.venv/bin/python -m compileall -q app scripts

say "Starting SINTU locally"
mkdir -p generated_videos generated_images generated_audio generated_music
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  say "Existing SINTU server is already running (PID $(cat "$PID_FILE"))."
else
  nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 \
    >>"$LOG_FILE" 2>&1 </dev/null &
  echo $! > "$PID_FILE"
fi

READY=0
for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then READY=1; break; fi
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then break; fi
  sleep 2
done

if [ "$READY" -ne 1 ]; then
  say "Server did not answer /health yet. Recent log:"
  tail -n 60 "$LOG_FILE" || true
  fail "App startup health check failed. Server was not marked ready."
fi

cat <<EOF

====================================================
 SINTU AI YOUTUBE STUDIO - READY
====================================================
App:       http://127.0.0.1:8000
Project:   $APP_DIR
Logs:      $LOG_FILE
PID file:  $PID_FILE

Useful commands:
  cd "$APP_DIR"
  bash scripts/termux_one_command.sh   # rerun safe setup/update
  tail -f "$LOG_FILE"                  # live server log
  kill \$(cat "$PID_FILE")               # stop server

Security:
  .env is private (mode 600); do not share it.
  Server binds to localhost only; it is not exposed to the internet.
====================================================
EOF
