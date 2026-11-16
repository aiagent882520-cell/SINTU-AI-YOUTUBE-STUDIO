#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot entrypoint. Install via scripts/termux_one_command.sh.
set -eu
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
if command -v termux-wake-lock >/dev/null 2>&1; then
  termux-wake-lock || true
fi
if [ -x "$APP_DIR/scripts/start_services.sh" ]; then
  nohup "$APP_DIR/scripts/start_services.sh" >>"$HOME/.sintu/boot.log" 2>&1 </dev/null &
fi
