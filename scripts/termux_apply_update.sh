#!/data/data/com.termux/files/usr/bin/bash
# One-time safe update/restart after the automation PR is merged.
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
LOG_DIR="$HOME/.sintu"
cd "$APP_DIR"
[ -d .git ] || { echo "SINTU repository not found: $APP_DIR" >&2; exit 1; }

# Fast-forward only: preserve local modifications and fail rather than reset them.
git pull --ff-only origin main
mkdir -p "$LOG_DIR"

# Use the shared identity-checked, graceful restart path. It waits for active
# render work and never SIGKILLs a worker or signals an unrelated PID.
bash scripts/restart_termux_workers.sh

for _ in $(seq 1 30); do
  if curl -fsS --max-time 4 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "SINTU update applied; API health check passed."
    echo "Automation-only mode remains enabled; video production is paused."
    if ! grep -Eq '^SINTU_OWNER_TOTP_SECRET=.{16,}' .env 2>/dev/null; then
      echo "Owner mobile OTP is not enrolled. Before Owner login, run: .venv/bin/python scripts/setup_owner_otp.py"
    fi
    exit 0
  fi
  sleep 2
done
echo "SINTU API health check failed; inspect $LOG_DIR/server.log" >&2
exit 1
