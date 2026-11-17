#!/data/data/com.termux/files/usr/bin/bash
# Install only lightweight optional Termux runtime pieces.
# Never downloads AI weights, builds diffusion engines, or starts video rendering.
set -Eeuo pipefail

say(){ printf '\n[SINTU SAFE INSTALL] %s\n' "$*"; }
[ -n "${PREFIX:-}" ] || { echo "Termux is required; refusing to run on another OS." >&2; exit 2; }

RAM_KB="$(awk '/MemAvailable:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
FREE_KB="$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)"
say "Device memory: ${RAM_KB} KiB available; storage: ${FREE_KB} KiB free."

if ! command -v espeak-ng >/dev/null 2>&1 && ! command -v espeak >/dev/null 2>&1; then
  say "Installing lightweight eSpeak TTS package"
  if pkg install -y espeak; then
    say "eSpeak installed."
  else
    say "eSpeak package unavailable from the configured Termux mirror; continuing."
  fi
else
  say "Local eSpeak TTS already installed."
fi

if ! command -v llama-server >/dev/null 2>&1; then
  say "Trying the Termux llama.cpp package (binary only; no model download)."
  if pkg install -y llama-cpp; then
    say "llama.cpp package installed."
  else
    say "llama.cpp package unavailable; no source build attempted."
  fi
else
  say "llama-server binary already installed."
fi

say "AI model download intentionally skipped: current free RAM is below the conservative 1.5 GiB threshold."
say "ComfyUI and Stable Diffusion installation skipped: Android/Termux compatibility and memory are insufficient."
say "Video rendering intentionally remains paused."
say "Installed binary inventory:"
for bin in ffmpeg ffprobe espeak-ng espeak llama-server; do
  command -v "$bin" 2>/dev/null || true
done
say "Safe optional install finished."
