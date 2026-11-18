#!/data/data/com.termux/files/usr/bin/bash
# Start SINTU API and its allowlisted local bridge worker.
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
mkdir -p "$LOG_DIR"
cd "$APP_DIR"

# Queued executors set a trusted marker. For the first rollout, also accept
# exact PPID equality with the fixed relay/worker PID files so an older
# already-running executor can bootstrap its own reload without /proc access.
PARENT_PID="$PPID"
RELAY_PID="$(cat "$LOG_DIR/github-relay.pid" 2>/dev/null || true)"
WORKER_PID="$(cat "$LOG_DIR/bridge-worker.pid" 2>/dev/null || true)"
IS_QUEUED_PARENT=0
if [[ "$PARENT_PID" =~ ^[0-9]+$ ]] &&
   { [[ "$PARENT_PID" == "$RELAY_PID" ]] || [[ "$PARENT_PID" == "$WORKER_PID" ]]; }; then
  IS_QUEUED_PARENT=1
fi
if [[ "${SINTU_SKIP_DELAYED_RESTART:-0}" != "1" ]] &&
   { [[ "${SINTU_QUEUE_EXECUTOR:-}" == "github_termux_relay" ]] ||
     [[ "${SINTU_QUEUE_EXECUTOR:-}" == "termux_bridge_worker" ]] ||
     [[ "$IS_QUEUED_PARENT" == "1" ]]; }; then
  nohup bash scripts/restart_termux_workers.sh >>"$LOG_DIR/restart.log" 2>&1 </dev/null &
  echo "SINTU service restart scheduled after the current queue result is acknowledged."
  exit 0
fi
# PID files are hints, never authority. A reused PID is unlinked without
# signalling the unrelated process; an unreadable identity fails closed.
pid_is_expected() {
  local pid_file="$1" marker="$2" pid cmd
  [ -s "$pid_file" ] || return 1
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    return 1
  fi
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  if [[ -z "$cmd" ]]; then cmd="$(ps -o args= -p "$pid" 2>/dev/null || true)"; fi
  if [[ -z "$cmd" ]]; then
    echo "[ERROR] Cannot verify process identity for PID $pid ($pid_file)." >&2
    return 2
  fi
  if [[ "$cmd" == *"$marker"* ]]; then return 0; fi
  echo "[WARN] Stale PID reference $pid in $pid_file; not signalling unrelated process; clearing reference." >&2
  rm -f "$pid_file"
  return 1
}

[ -x .venv/bin/python ] || { echo "SINTU virtualenv missing; run scripts/termux_one_command.sh first." >&2; exit 1; }
[ -f .env ] || { echo "SINTU .env missing; run scripts/termux_one_command.sh first." >&2; exit 1; }

if pid_is_expected "$LOG_DIR/server.pid" "uvicorn app.main:app"; then
  :
else
  state=$?
  [ "$state" -ne 2 ] || exit 1
  if ! curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    : > "$LOG_DIR/server.log"
    nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 >>"$LOG_DIR/server.log" 2>&1 </dev/null &
    echo $! > "$LOG_DIR/server.pid"
  else
    echo "[WARN] API health is already OK; cleared stale server PID reference without starting a duplicate."
  fi
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
    if pid_is_expected "$LOG_DIR/llama-server.pid" "llama-server -m"; then
      :
    else
      state=$?
      [ "$state" -ne 2 ] || exit 1
      nohup llama-server -m "$MODEL_PATH" --host 127.0.0.1 --port 8080 -c 4096 -t 4 \
        >>"$LOG_DIR/llama-server.log" 2>&1 </dev/null &
      echo $! > "$LOG_DIR/llama-server.pid"
    fi
  fi
fi

if pid_is_expected "$LOG_DIR/bridge-worker.pid" "scripts/termux_bridge_worker.py"; then
  :
else
  state=$?
  [ "$state" -ne 2 ] || exit 1
  : > "$LOG_DIR/bridge-worker.log"
  nohup .venv/bin/python scripts/termux_bridge_worker.py >>"$LOG_DIR/bridge-worker.log" 2>&1 </dev/null &
  echo $! > "$LOG_DIR/bridge-worker.pid"
fi

# Restore the ChatGPT/GitHub-to-Termux issue relay after Android reboot.
# Do not silently report all workers as running when GitHub authentication is
# unavailable: queued GitHub commands cannot reach this device without it.
GITHUB_RELAY_STATUS="not started"
if ! command -v gh >/dev/null 2>&1; then
  echo "[WARN] GitHub issue relay not started: GitHub CLI (gh) is not installed." >&2
  echo "[WARN] Install gh, then run 'gh auth login' in Termux." >&2
elif ! gh auth status >/dev/null 2>&1; then
  echo "[WARN] GitHub issue relay not started: GitHub CLI is not authenticated." >&2
  echo "[WARN] Run 'gh auth login' in Termux; credentials are never printed by this launcher." >&2
else
  if pid_is_expected "$LOG_DIR/github-relay.pid" "scripts/github_termux_relay.py"; then
    GITHUB_RELAY_STATUS="existing relay process identity verified"
  else
    state=$?
    if [ "$state" -eq 2 ]; then
      GITHUB_RELAY_STATUS="not started: existing PID identity cannot be verified"
      echo "[WARN] $GITHUB_RELAY_STATUS." >&2
    else
      : > "$LOG_DIR/github-relay.log"
      nohup .venv/bin/python scripts/github_termux_relay.py >>"$LOG_DIR/github-relay.log" 2>&1 </dev/null &
      echo $! > "$LOG_DIR/github-relay.pid"
      GITHUB_RELAY_STATUS="relay start requested"
    fi
  fi
fi

# Keep a lightweight watchdog alive so dead local processes are restarted.
WATCHDOG_PID_FILE="$LOG_DIR/watchdog.pid"
if pid_is_expected "$WATCHDOG_PID_FILE" "scripts/termux_watchdog.sh"; then
  :
else
  state=$?
  [ "$state" -ne 2 ] || exit 1
  nohup bash scripts/termux_watchdog.sh >>"$LOG_DIR/watchdog.log" 2>&1 </dev/null &
  echo $! > "$WATCHDOG_PID_FILE"
fi

echo "SINTU API and local bridge worker startup complete."
if [[ "$GITHUB_RELAY_STATUS" == "not started" ]]; then
  echo "[WARN] GitHub issue relay is offline; GitHub command issues will remain queued until gh is installed and authenticated." >&2
else
  echo "GitHub issue relay: $GITHUB_RELAY_STATUS."
fi
