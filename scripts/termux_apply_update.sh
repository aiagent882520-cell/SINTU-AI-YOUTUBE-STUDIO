#!/data/data/com.termux/files/usr/bin/bash
# One-time safe update/restart after the automation PR is merged.
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
cd "$APP_DIR"
[ -d .git ] || { echo "SINTU repository not found: $APP_DIR" >&2; exit 1; }

stop_known() {
  local file="$1" marker="$2" pid cmd
  [ -f "$LOG_DIR/$file.pid" ] || return 0
  pid="$(cat "$LOG_DIR/$file.pid" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmd" == *"$marker"* ]]; then
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
    else
      echo "PID $pid does not match $marker; refusing to kill it." >&2
      return 1
    fi
  fi
  rm -f "$LOG_DIR/$file.pid"
}

git pull --ff-only origin main
mkdir -p "$LOG_DIR"
stop_known server "app.main:app"
stop_known bridge-worker "scripts/termux_bridge_worker.py"
stop_known github-relay "scripts/github_termux_relay.py"
bash scripts/start_services.sh

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "SINTU update applied; API health check passed."
    echo "Automation-only mode remains enabled; video production is paused."
    exit 0
  fi
  sleep 2
done
echo "SINTU API health check failed; inspect $LOG_DIR/server.log" >&2
exit 1
