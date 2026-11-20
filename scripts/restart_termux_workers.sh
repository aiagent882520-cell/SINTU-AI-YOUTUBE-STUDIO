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
  if [[ -z "$cmdline" ]]; then
    cmdline="$(ps -o args= -p "$pid" 2>/dev/null || true)"
  fi
  if [[ -z "$cmdline" ]]; then
    echo "Cannot verify process identity for PID $pid; aborting safe restart." >&2
    return 1
  fi
  if [[ "$cmdline" != *"$marker"* ]]; then
    echo "PID file identity mismatch for $pid; not signalling unrelated process; aborting restart." >&2
    return 1
  fi
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "Expected process $pid did not stop after TERM; aborting without SIGKILL." >&2
    return 1
  fi
  rm -f "$pid_file"
}

# Only these fixed SINTU services are eligible; PID identity is checked before
# signalling. Never kill a PID based only on a stale PID file.
stop_expected "$LOG_DIR/server.pid" "uvicorn app.main:app" || exit 1
stop_expected "$LOG_DIR/bridge-worker.pid" "scripts/termux_bridge_worker.py" || exit 1
stop_expected "$LOG_DIR/render-worker.pid" "scripts/render_queue_worker.py" || exit 1
stop_expected "$LOG_DIR/github-relay.pid" "scripts/github_termux_relay.py" || exit 1

sleep 2
env -u SINTU_QUEUE_EXECUTOR -u SINTU_SKIP_DELAYED_RESTART bash scripts/start_services.sh
echo "SINTU API, bridge worker and GitHub relay reloaded with current repository code."
