#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

if ! command -v pkg >/dev/null 2>&1; then
  echo "SINTU installer sirf Android Termux ke liye hai."
  exit 1
fi

DEST="${SINTU_INSTALL_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
REPO="https://github.com/aiagent882520-cell/SINTU-AI-YOUTUBE-STUDIO.git"

pkg update -y
pkg install -y git

if [ -d "$DEST/.git" ]; then
  echo "Existing SINTU repository found; fast-forward update only."
  git -C "$DEST" pull --ff-only origin main
elif [ -e "$DEST" ]; then
  echo "Install path exists but is not a Git repository: $DEST"
  echo "Existing files ko overwrite nahi kiya gaya. SINTU_INSTALL_DIR set karke retry karein."
  exit 1
else
  git clone --depth 1 "$REPO" "$DEST"
fi

cd "$DEST"
exec bash "$DEST/START_SINTU_TERMUX.sh"
