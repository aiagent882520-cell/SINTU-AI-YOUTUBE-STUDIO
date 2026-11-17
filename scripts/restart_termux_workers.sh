#!/data/data/com.termux/files/usr/bin/bash
# Delayed, identity-checked service reload after the current relay/worker job
# has had time to post its completion result.
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
mkdir -p "$LOG_DIR"
cd "$APP_DIR"

# The caller must have already returned success to its queue before this runs.
sleep 15

stop_expected() {
  local pid_file="$1"
  local marker="$2"
  [ -f "$pid_file" ] || return 0
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || { rm -f "$pid_file"; return 0; }
  kill -0 "$pid" 2>/dev/null || { rm -f "$pid_file"; return 0; }
  local cmdline
  cmdline="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  if [[ "$cmdline" == *"$marker"* ]]; then
    kill -TERM "$pid" 2>/dev/null || true
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
  fi
}

# Only these fixed SINTU services are eligible; PID identity is checked before
# signalling. Never kill a PID based only on a stale PID file.
stop_expected "$LOG_DIR/server.pid" "uvicorn app.main:app"
stop_expected "$LOG_DIR/bridge-worker.pid" "scripts/termux_bridge_worker.py"
stop_expected "$LOG_DIR/github-relay.pid" "scripts/github_termux_relay.py"

sleep 2
SINTU_SKIP_DELAYED_RESTART=1 bash scripts/start_services.sh
echo "SINTU API, bridge worker and GitHub relay reloaded with current repository code."
