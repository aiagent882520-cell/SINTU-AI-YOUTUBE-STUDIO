#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
REPORT_DIR="$APP_DIR/reports"
mkdir -p "$REPORT_DIR" "$LOG_DIR"
cd "$APP_DIR"
PY="$APP_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT="$REPORT_DIR/termux-render-worker-recovery-$STAMP.txt"
{
  echo "SINTU TERMUX RENDER WORKER RECOVERY DIAGNOSTIC"
  echo "timestamp_utc=$STAMP"
  echo "repo=$APP_DIR"
  echo "git_head=$(git rev-parse HEAD 2>/dev/null || echo unavailable)"
  echo "python=$($PY --version 2>&1)"
  echo "platform=$($PY -c 'import platform; print(platform.platform())')"
  echo "ffmpeg=$(command -v ffmpeg || echo missing)"
  echo "ffprobe=$(command -v ffprobe || echo missing)"
  echo "env_file_present=$([ -f .env ] && echo yes || echo no)"
  echo "api_health=$(curl -fsS --max-time 4 http://127.0.0.1:8000/api/health 2>/dev/null || echo unavailable)"
  for name in server bridge-worker render-worker github-relay watchdog; do
    file="$LOG_DIR/$name.pid"
    pid="$(cat "$file" 2>/dev/null || true)"
    if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
      cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
      echo "service_$name=pid:$pid cmd:$cmd"
    else
      echo "service_$name=not_running_or_no_pid"
    fi
  done
  "$PY" - <<'PY'
import os, sqlite3
from pathlib import Path
db = Path(os.getenv("SINTU_DATA_DIR", Path.cwd())).expanduser() / "sintu_studio.db"
print(f"queue_db_exists={db.is_file()}")
if db.is_file():
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT status,COUNT(*) FROM studio_render_queue GROUP BY status").fetchall()
        print("queue_status_counts=" + repr(dict(rows)))
        columns = {row[1] for row in con.execute("PRAGMA table_info(studio_render_queue)")}
        print("cancel_requested_column=" + str("cancel_requested" in columns))
    except sqlite3.Error as exc:
        print("queue_db_error=" + type(exc).__name__)
    finally:
        con.close()
PY
} | tee "$REPORT"
echo "Running automation cancellation/recovery regression tests..."
"$PY" -m pytest -q tests/test_render_process.py tests/test_durable_render_queue.py tests/test_render_queue_worker.py tests/test_render_queue_api_leases.py
echo "Running compile validation..."
"$PY" -m compileall -q app scripts
if [[ "${SINTU_DEVICE_RESTART:-0}" == "1" ]]; then
  running="$("$PY" - <<'PY'
import os, sqlite3
from pathlib import Path
db=Path(os.getenv("SINTU_DATA_DIR", Path.cwd()))/"sintu_studio.db"
if not db.exists(): print(0)
else:
    con=sqlite3.connect(db)
    try: print(con.execute("SELECT COUNT(*) FROM studio_render_queue WHERE status='running'").fetchone()[0])
    finally: con.close()
PY
)"
  if [[ "$running" != "0" ]]; then echo "Refusing restart: $running render job(s) running." >&2; exit 3; fi
  pid_file="$LOG_DIR/render-worker.pid"
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    if [[ "$cmd" == *"scripts/render_queue_worker.py"* ]]; then
      kill -TERM "$pid"
      for _ in $(seq 1 30); do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      if kill -0 "$pid" 2>/dev/null; then echo "Worker did not stop gracefully; refusing SIGKILL." >&2; exit 4; fi
    else
      echo "Worker PID identity mismatch; refusing to signal PID $pid." >&2; exit 5
    fi
  fi
  bash scripts/start_services.sh
  sleep 2
  new_pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ "$new_pid" =~ ^[0-9]+$ ]] && kill -0 "$new_pid"
  cmd="$(tr '\0' ' ' < "/proc/$new_pid/cmdline" 2>/dev/null || true)"
  [[ "$cmd" == *"scripts/render_queue_worker.py"* ]]
  echo "controlled_worker_restart=verified pid:$new_pid"
fi
echo "PASS: local diagnostics, regression tests and compile checks completed."
echo "report=$REPORT"
