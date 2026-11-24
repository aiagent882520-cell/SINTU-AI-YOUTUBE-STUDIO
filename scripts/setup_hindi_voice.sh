#!/usr/bin/env bash
# Install a pinned, free Hindi neural Piper voice for local SINTU narration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOICE_DIR="${SINTU_VOICE_DIR:-$ROOT/models/voices}"
MODEL="$VOICE_DIR/hi_IN-pratham-medium.onnx"
CONFIG="$MODEL.json"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/hi/hi_IN/pratham/medium"
EXPECTED_SHA256="169964b0871667f6793416d4b35e97357a68ba1ad01df8580c28048989ee7693"

command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required." >&2; exit 1; }

if ! command -v "${PIPER_EXECUTABLE:-piper}" >/dev/null 2>&1; then
  python -m pip install "piper-tts==1.3.0"
fi
PIPER_BIN="$(command -v "${PIPER_EXECUTABLE:-piper}" || true)"
if [[ -z "$PIPER_BIN" ]]; then
  echo "Piper CLI was not found after installation. Add its bin directory to PATH." >&2
  exit 1
fi

mkdir -p "$VOICE_DIR"
if [[ ! -s "$MODEL" ]]; then
  curl --fail --location --retry 3 "$BASE/hi_IN-pratham-medium.onnx" -o "$MODEL.part"
  mv "$MODEL.part" "$MODEL"
fi
if [[ ! -s "$CONFIG" ]]; then
  curl --fail --location --retry 3 "$BASE/hi_IN-pratham-medium.onnx.json" -o "$CONFIG.part"
  mv "$CONFIG.part" "$CONFIG"
fi
echo "$EXPECTED_SHA256  $MODEL" | sha256sum --check
"$PIPER_BIN" --help >/dev/null

# Persist only the two voice settings; preserve every unrelated .env entry.
python - "$ROOT/.env" "$PIPER_BIN" "$MODEL" <<'PY'
from pathlib import Path
import os
import sys

env_path = Path(sys.argv[1])
values = {
    "PIPER_EXECUTABLE": sys.argv[2],
    "PIPER_MODEL_PATH": sys.argv[3],
}
lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
for key, value in values.items():
    prefix = key + "="
    lines = [line for line in lines if not line.startswith(prefix)]
    lines.append(prefix + value)
env_path.parent.mkdir(parents=True, exist_ok=True)
env_path.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8")
try:
    os.chmod(env_path, 0o600)
except OSError:
    pass
PY

echo "Hindi Piper voice ready and configured in .env."
echo "Model: $MODEL"
echo "Restart SINTU to activate neural Hindi narration."
