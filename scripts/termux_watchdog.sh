#!/data/data/com.termux/files/usr/bin/bash
# Termux process watchdog. Restarts only SINTU processes whose command lines match.
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
mkdir -p "$LOG_DIR"
cd "$APP_DIR"

process_state() {
  local name="$1" marker="$2" file="$LOG_DIR/$1.pid" pid cmd
  if [ ! -s "$file" ]; then return 1; fi
  pid="$(cat "$file" 2>/dev/null || true)"
  if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$file"
    return 1
  fi
  proc_state="$(sed 's/.*) //' "/proc/$pid/stat" 2>/dev/null | cut -d ' ' -f 1 || true)"
  if [ "$proc_state" = "Z" ]; then
    rm -f "$file"
    return 1
  fi
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  if [[ "$cmd" == *"$marker"* ]]; then return 0; fi
  printf '[WATCHDOG] Refusing to signal unrelated PID %s for %s\n' "$pid" "$name" >&2
  return 2
}

while true; do
  restart=0
  unsafe=0

  if ! curl -fsS --max-time 4 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    if process_state server "uvicorn app.main:app"; then
      pid="$(cat "$LOG_DIR/server.pid")"
      kill "$pid" 2>/dev/null || true
      for _ in $(seq 1 10); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
      rm -f "$LOG_DIR/server.pid"
      restart=1
    else
      state=$?
      if [ "$state" -eq 2 ]; then unsafe=1; else restart=1; fi
    fi
  fi

  if process_state bridge-worker "scripts/termux_bridge_worker.py"; then :; else
    state=$?
    if [ "$state" -eq 2 ]; then unsafe=1; else restart=1; fi
  fi

  if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    if process_state github-relay "scripts/github_termux_relay.py"; then :; else
      state=$?
      if [ "$state" -eq 2 ]; then unsafe=1; else restart=1; fi
    fi
  fi

  if [ "$restart" -eq 1 ] && [ "$unsafe" -eq 0 ]; then
    printf '[WATCHDOG] Restarting missing/unhealthy SINTU services at %s\n' "$(date -Iseconds)" >>"$LOG_DIR/recovery.log"
    bash scripts/start_services.sh >>"$LOG_DIR/recovery.log" 2>&1 || true
  fi
  sleep 30
done
