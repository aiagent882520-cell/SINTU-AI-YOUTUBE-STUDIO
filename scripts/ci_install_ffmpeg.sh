#!/usr/bin/env bash
set -euo pipefail

has_ffmpeg() {
  command -v ffmpeg >/dev/null 2>&1 &&
    command -v ffprobe >/dev/null 2>&1 &&
    ffmpeg -hide_banner -filters 2>/dev/null | grep -q subtitles
}

if ! has_ffmpeg; then
  installed=0
  for attempt in 1 2 3; do
    echo "Installing distro FFmpeg (attempt ${attempt}/3)"
    if timeout 300 sudo apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update -qq &&
       timeout 600 sudo apt-get install -y --no-install-recommends ffmpeg; then
      installed=1
      break
    fi
    if [[ "${attempt}" -lt 3 ]]; then sleep "$((attempt * 5))"; fi
  done
  if [[ "${installed}" -ne 1 ]]; then
    echo "FFmpeg installation failed after three bounded attempts." >&2
    exit 1
  fi
fi

ffmpeg -version
ffprobe -version
ffmpeg -hide_banner -filters | grep -q subtitles
