#!/data/data/com.termux/files/usr/bin/bash
# Start SINTU API and its allowlisted local bridge worker.
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
mkdir -p "$LOG_DIR"
cd "$APP_DIR"
[ -x .venv/bin/python ] || { echo "SINTU virtualenv missing; run scripts/termux_one_command.sh first." >&2; exit 1; }
[ -f .env ] || { echo "SINTU .env missing; run scripts/termux_one_command.sh first." >&2; exit 1; }

if [ -f "$LOG_DIR/server.pid" ] && kill -0 "$(cat "$LOG_DIR/server.pid")" 2>/dev/null; then
  :
else
  : > "$LOG_DIR/server.log"
  nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >>"$LOG_DIR/server.log" 2>&1 </dev/null &
  echo $! > "$LOG_DIR/server.pid"
fi

ready=0
for _ in $(seq 1 45); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then ready=1; break; fi
  if ! kill -0 "$(cat "$LOG_DIR/server.pid")" 2>/dev/null; then break; fi
  sleep 2
done
[ "$ready" -eq 1 ] || { tail -n 60 "$LOG_DIR/server.log" >&2 || true; exit 1; }

# Restore the optional local llama.cpp model server after Android reboot.
if command -v llama-server >/dev/null 2>&1 && [ -d "$LOG_DIR/models" ]; then
  MODEL_PATH="$(find "$LOG_DIR/models" -maxdepth 1 -type f -name '*.gguf' -size +100M -print -quit)"
  if [ -n "$MODEL_PATH" ]; then
    if [ -f "$LOG_DIR/llama-server.pid" ] && kill -0 "$(cat "$LOG_DIR/llama-server.pid")" 2>/dev/null; then
      :
    else
      nohup llama-server -m "$MODEL_PATH" --host 127.0.0.1 --port 8080 -c 4096 -t 4 \
        >>"$LOG_DIR/llama-server.log" 2>&1 </dev/null &
      echo $! > "$LOG_DIR/llama-server.pid"
    fi
  fi
fi

if [ -f "$LOG_DIR/bridge-worker.pid" ] && kill -0 "$(cat "$LOG_DIR/bridge-worker.pid")" 2>/dev/null; then
  :
else
  : > "$LOG_DIR/bridge-worker.log"
  nohup .venv/bin/python scripts/termux_bridge_worker.py >>"$LOG_DIR/bridge-worker.log" 2>&1 </dev/null &
  echo $! > "$LOG_DIR/bridge-worker.pid"
fi

echo "SINTU API and Termux bridge worker are running."
