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

# Termux packages the eSpeak NG engine under the name "espeak".
if ! command -v espeak-ng >/dev/null 2>&1 && ! command -v espeak >/dev/null 2>&1; then
  if pkg install -y espeak; then
    say "Optional local Hindi eSpeak voice engine installed"
  else
    say "eSpeak package is unavailable on this mirror; install continues without local TTS"
  fi
fi

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
  python -m venv --system-site-packages .venv
fi
# Termux ships native Pillow and cryptography builds as system packages. Expose
# those ABI-compatible builds inside the venv instead of trying to compile them
# from PyPI on Android; also repair existing isolated venvs on safe reruns.
if [ -f .venv/pyvenv.cfg ] && grep -q '^include-system-site-packages = false' .venv/pyvenv.cfg; then
  sed -i 's/^include-system-site-packages = false/include-system-site-packages = true/' .venv/pyvenv.cfg
fi
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements.txt

# Termux must use its Android-native python-cryptography package. PyPI's
# abi3/manylinux Rust extension can be incompatible with Android's Python ABI
# and fail at import time (for example: PyBaseObject_Type not found).
if [ -n "${PREFIX:-}" ]; then
  say "Verifying Android-native Python cryptography binding"
  .venv/bin/python - <<'PY'
from pathlib import Path
import importlib.util
import subprocess
import sys

venv = Path(sys.prefix).resolve()
spec = importlib.util.find_spec("cryptography")
origin = Path(spec.origin).resolve() if spec and spec.origin else None
if origin and origin.is_relative_to(venv):
    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", "cryptography"],
        check=True,
    )
import cryptography
loaded = Path(cryptography.__file__).resolve()
if loaded.is_relative_to(venv):
    raise SystemExit(
        "Incompatible venv cryptography remains installed; "
        "Termux python-cryptography system package is required."
    )
from cryptography.fernet import Fernet
Fernet.generate_key()
print(f"Using Termux-native cryptography: {loaded}")
PY
fi

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


say "Preparing optional free local llama.cpp engine"
if ! command -v llama-server >/dev/null 2>&1; then
  if pkg install -y llama-cpp; then
    say "Termux llama.cpp package installed"
  else
    say "llama-cpp package is unavailable on this Termux mirror; continuing without local LLM bootstrap"
  fi
fi

if command -v llama-server >/dev/null 2>&1; then
  RAM_KB="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
  FREE_KB="$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)"
  MODEL_DIR="$HOME/.sintu/models"
  mkdir -p "$MODEL_DIR"
  MODEL_URL=""
  MODEL_NAME=""
  MIN_MODEL_BYTES=0
  if [ "${RAM_KB:-0}" -ge 4194304 ] && [ "${FREE_KB:-0}" -ge 3145728 ]; then
    MODEL_NAME="qwen2.5-3b-instruct-q4_k_m.gguf"
    MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/$MODEL_NAME"
    MIN_MODEL_BYTES=1700000000
  elif [ "${RAM_KB:-0}" -ge 2097152 ] && [ "${FREE_KB:-0}" -ge 900000 ]; then
    MODEL_NAME="qwen2.5-0.5b-instruct-q4_k_m.gguf"
    MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/$MODEL_NAME"
    MIN_MODEL_BYTES=350000000
  fi

  if [ -n "$MODEL_URL" ]; then
    MODEL_PATH="$MODEL_DIR/$MODEL_NAME"
    if [ ! -s "$MODEL_PATH" ] && [ -s "$MODEL_PATH.part" ]; then
      PART_BYTES="$(wc -c < "$MODEL_PATH.part" | tr -d ' ')"
      if [ "${PART_BYTES:-0}" -ge "$MIN_MODEL_BYTES" ]; then
        mv "$MODEL_PATH.part" "$MODEL_PATH"
      fi
    fi
    if [ ! -s "$MODEL_PATH" ]; then
      say "Downloading free Qwen GGUF model selected from available RAM and storage"
      if curl --fail --location --retry 3 --retry-all-errors --continue-at - \
        --output "$MODEL_PATH.part" "$MODEL_URL"; then
        MODEL_BYTES="$(wc -c < "$MODEL_PATH.part" | tr -d ' ')"
        if [ "${MODEL_BYTES:-0}" -ge "$MIN_MODEL_BYTES" ]; then
          mv "$MODEL_PATH.part" "$MODEL_PATH"
        else
          say "Model download was incomplete; keeping partial file for a later resume"
        fi
      else
        say "Model download failed; the app will still install and can use an existing local model"
      fi
    fi

    if [ -s "$MODEL_PATH" ]; then
      MODEL_BYTES="$(wc -c < "$MODEL_PATH" | tr -d ' ')"
      if [ "${MODEL_BYTES:-0}" -ge "$MIN_MODEL_BYTES" ]; then
        if [ -f "$LOG_DIR/llama-server.pid" ] && kill -0 "$(cat "$LOG_DIR/llama-server.pid")" 2>/dev/null; then
          say "Existing local llama.cpp server process found"
        else
          say "Starting local llama.cpp model server on 127.0.0.1:8080"
          nohup llama-server -m "$MODEL_PATH" --host 127.0.0.1 --port 8080 -c 4096 -t 4 \
            >>"$LOG_DIR/llama-server.log" 2>&1 </dev/null &
          echo $! > "$LOG_DIR/llama-server.pid"
        fi
        AI_READY=0
        for _ in $(seq 1 60); do
          if curl -fsS http://127.0.0.1:8080/v1/models >/dev/null 2>&1; then AI_READY=1; break; fi
          if [ -f "$LOG_DIR/llama-server.pid" ] && ! kill -0 "$(cat "$LOG_DIR/llama-server.pid")" 2>/dev/null; then break; fi
          sleep 2
        done
        if [ "$AI_READY" -eq 1 ]; then
          say "Free local AI model server is ready"
        else
          say "Local AI server did not become ready in time; inspect $LOG_DIR/llama-server.log"
        fi
      fi
    fi
  else
    say "Device RAM/storage is below the safe automatic model-download threshold; no large model was downloaded"
  fi
else
  say "llama-server is unavailable; local LLM setup is deferred, but the studio installation continues"
fi

# Add local backend defaults without overwriting any existing operator settings.
.venv/bin/python - <<'PY'
from pathlib import Path
import shutil
path = Path(".env")
content = path.read_text(encoding="utf-8")
defaults = {
    "LOCAL_AI_BACKEND": "auto",
    "LOCAL_OPENAI_BASE_URL": "http://127.0.0.1:8080/v1",
    "LOCAL_OPENAI_MODEL": "auto",
    "LOCAL_OPENAI_API_KEY": "",
}
lines = content.splitlines()
for key, value in defaults.items():
    if not any(line.startswith(key + "=") for line in lines):
        lines.append(key + "=" + value)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
speech = shutil.which("espeak-ng") or shutil.which("espeak")
if speech:
    current = next((line.split("=", 1)[1].strip() for line in lines
                    if line.startswith("ESPEAK_EXECUTABLE=")), "")
    if not current or not (shutil.which(current) or Path(current).is_file()):
        lines = [line for line in lines if not line.startswith("ESPEAK_EXECUTABLE=")]
        lines.append("ESPEAK_EXECUTABLE=" + speech)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
PY

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


SMOKE_VIDEO_PATH=""
if [ -f "$LOG_DIR/media-smoke-path.txt" ]; then
  SMOKE_VIDEO_PATH="$(cat "$LOG_DIR/media-smoke-path.txt")"
fi
if command -v espeak-ng >/dev/null 2>&1 || command -v espeak >/dev/null 2>&1; then
  if [ ! -f "$LOG_DIR/media-smoke-success" ] || [ "${SINTU_FORCE_MEDIA_SMOKE:-false}" = "true" ]; then
    say "Running one real offline Hindi video render and black-frame validation"
    if .venv/bin/python scripts/live_e2e.py --offline-video \
      --topic "भारत की ऐतिहासिक विरासत का सिनेमाई दृश्य" \
      >"$LOG_DIR/media-smoke.json" 2>&1; then
      if SMOKE_VIDEO_PATH="$(.venv/bin/python - "$LOG_DIR/media-smoke.json" <<'PY'
import json
import shutil
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
video = report["live_tests"]["offline_storyboard_video"]
source = Path(video["final_render_path"])
if not source.is_file() or source.stat().st_size <= 1000:
    raise SystemExit("Smoke-test MP4 is missing or too small.")
shared = Path.home() / "storage" / "shared" / "Movies" / "SINTU"
try:
    if (Path.home() / "storage" / "shared").is_dir():
        shared.mkdir(parents=True, exist_ok=True)
        target = shared / ("SINTU_INSTALL_TEST_" + source.stem + ".mp4")
        shutil.copy2(source, target)
    else:
        target = source
except OSError:
    target = source
print(target)
PY
      )"; then
        printf '%s\n' "$SMOKE_VIDEO_PATH" > "$LOG_DIR/media-smoke-path.txt"
        touch "$LOG_DIR/media-smoke-success"
        say "Verified real MP4 created with Hindi voice, music, SINTU branding and renderer checks"
      else
        say "Media smoke report could not be copied; inspect $LOG_DIR/media-smoke.json"
        SMOKE_VIDEO_PATH=""
      fi
    else
      say "Offline video smoke test did not pass; installation remains available. Report: $LOG_DIR/media-smoke.json"
      tail -n 35 "$LOG_DIR/media-smoke.json" || true
      SMOKE_VIDEO_PATH=""
    fi
  else
    say "Previous verified media smoke test found; skipping duplicate render"
  fi
else
  say "No local Hindi TTS binary is installed; offline video smoke test is deferred"
fi
if [ -n "$SMOKE_VIDEO_PATH" ]; then
  say "Verified sample video: $SMOKE_VIDEO_PATH"
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
  tail -f "$LOG_DIR/llama-server.log"    # local AI model log
  kill \$(cat "$PID_FILE")               # stop SINTU
  kill \$(cat "$LOG_DIR/llama-server.pid")  # stop local AI

Security:
  .env is private (mode 600); do not share it.
  Server binds to localhost only; it is not exposed to the internet.
====================================================
EOF
