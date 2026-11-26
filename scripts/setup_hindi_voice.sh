#!/usr/bin/env bash
# Install pinned, free Hindi neural Piper voices for local SINTU narration.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOICE_DIR="${SINTU_VOICE_DIR:-$ROOT/models/voices}"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/hi/hi_IN"
PIPER_BIN_NAME="${PIPER_EXECUTABLE:-piper}"

command -v curl >/dev/null 2>&1 || { echo "curl is required." >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is required." >&2; exit 1; }

if ! command -v "$PIPER_BIN_NAME" >/dev/null 2>&1; then
  python -m pip install "piper-tts==1.3.0"
fi
PIPER_BIN="$(command -v "$PIPER_BIN_NAME" || true)"
if [[ -z "$PIPER_BIN" ]]; then
  echo "Piper CLI was not found after installation. Add its bin directory to PATH." >&2
  exit 1
fi

mkdir -p "$VOICE_DIR"
download_voice() {
  local speaker="$1" name="$2" expected_sha="$3"
  local model="$VOICE_DIR/hi_IN-$name-medium.onnx"
  local config="$model.json"
  local url="$BASE/$speaker/medium"
  if [[ ! -s "$model" ]]; then
    curl --fail --location --retry 3 "$url/hi_IN-$name-medium.onnx" -o "$model.part"
    mv "$model.part" "$model"
  fi
  if [[ ! -s "$config" ]]; then
    curl --fail --location --retry 3 "$url/hi_IN-$name-medium.onnx.json" -o "$config.part"
    mv "$config.part" "$config"
  fi
  echo "$expected_sha  $model" | sha256sum --check
  python - "$config" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if data.get("language", {}).get("code") != "hi_IN":
    raise SystemExit("Piper model config is not a Hindi (hi_IN) voice.")
if data.get("audio", {}).get("quality") != "medium":
    raise SystemExit("Unexpected Piper model quality metadata.")
PY
}

# Official rhasspy/piper-voices v1.0.0 model hashes (SHA-256).
download_voice "pratham" "pratham" "169964b0871667f6793416d4b35e97357a68ba1ad01df8580c28048989ee7693"
download_voice "priyamvada" "priyamvada" "aa63bcf2cd493b55a450f280e23cf77f03afc9af7015e6e5acd43b652f166c88"
"$PIPER_BIN" --help >/dev/null

# Persist only the two voice settings; preserve every unrelated .env entry.
python - "$ROOT/.env" "$PIPER_BIN" "$VOICE_DIR/hi_IN-pratham-medium.onnx" "$VOICE_DIR/hi_IN-priyamvada-medium.onnx" <<'PY'
from pathlib import Path
import os
import sys

env_path = Path(sys.argv[1])
values = {
    "PIPER_EXECUTABLE": sys.argv[2],
    "PIPER_MODEL_PATH": sys.argv[3],
    "PIPER_FEMALE_MODEL_PATH": sys.argv[4],
}
lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
for key, value in values.items():
    prefix = key + "="
    lines = [line for line in lines if not line.startswith(prefix)]
    lines.append(prefix + value)
env_path.parent.mkdir(parents=True, exist_ok=True)
env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
try:
    os.chmod(env_path, 0o600)
except OSError:
    pass
PY

echo "Hindi Piper male and female neural voices ready and configured in .env."
echo "Male: $VOICE_DIR/hi_IN-pratham-medium.onnx"
echo "Female: $VOICE_DIR/hi_IN-priyamvada-medium.onnx"
echo "Restart SINTU to activate both Hindi voices."
