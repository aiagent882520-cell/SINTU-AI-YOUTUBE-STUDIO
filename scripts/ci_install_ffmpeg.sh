#!/usr/bin/env bash
set -euo pipefail

has_ffmpeg() {
  command -v ffmpeg >/dev/null 2>&1 &&
    command -v ffprobe >/dev/null 2>&1 &&
    ffmpeg -hide_banner -filters 2>/dev/null | grep -q subtitles
}

if ! has_ffmpeg; then
  echo "Installing distro FFmpeg with a strict total time bound."

  # Try the runner's existing apt package indexes first. GitHub-hosted
  # Ubuntu images commonly have fresh indexes, so avoid a slow apt update
  # when the package can be installed immediately.
  if ! timeout 120 sudo apt-get \
      -o Acquire::Retries=1 \
      -o Acquire::http::Timeout=20 \
      -o Acquire::https::Timeout=20 \
      install -y --no-install-recommends ffmpeg; then
    echo "Cached package indexes unavailable; refreshing once."
    timeout 180 sudo apt-get \
      -o Acquire::Retries=1 \
      -o Acquire::http::Timeout=20 \
      -o Acquire::https::Timeout=20 \
      update -qq
    timeout 300 sudo apt-get \
      -o Acquire::Retries=1 \
      -o Acquire::http::Timeout=20 \
      -o Acquire::https::Timeout=20 \
      install -y --no-install-recommends ffmpeg
  fi
fi

ffmpeg -version
ffprobe -version
ffmpeg -hide_banner -filters | grep -q subtitles
