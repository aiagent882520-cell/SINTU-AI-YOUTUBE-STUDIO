#!/data/data/com.termux/files/usr/bin/bash
# Configure SINTU to use a locally running ComfyUI SDXL image workflow.
set -Eeuo pipefail
APP_DIR="${SINTU_APP_DIR:-$HOME/SINTU-AI-YOUTUBE-STUDIO}"
cd "$APP_DIR"
WORKFLOW="$APP_DIR/config/comfyui/sdxl_image_api.json"
[ -s "$WORKFLOW" ] || { echo "Missing workflow: $WORKFLOW" >&2; exit 1; }
BASE_URL="${COMFYUI_BASE_URL:-http://127.0.0.1:8188}"
case "$BASE_URL" in http://127.0.0.1:*|http://localhost:*|http://host.docker.internal:*) ;; *) echo "Only local ComfyUI URLs are allowed." >&2; exit 1;; esac
.venv/bin/python - "$WORKFLOW" "$BASE_URL" <<'PY'
from pathlib import Path
import json, sys
workflow = Path(sys.argv[1])
data = json.loads(workflow.read_text(encoding="utf-8"))
required = {"__SINTU_PROMPT__", "__SINTU_WIDTH__", "__SINTU_HEIGHT__"}
serialized = json.dumps(data)
missing = sorted(x for x in required if x not in serialized)
if missing:
    raise SystemExit("Workflow placeholders missing: " + ", ".join(missing))
env = Path(".env")
lines = env.read_text(encoding="utf-8").splitlines() if env.exists() else []
values = {"COMFYUI_BASE_URL": sys.argv[2], "COMFYUI_IMAGE_WORKFLOW_PATH": str(workflow), "SINTU_IMAGE_GENERATION_MODE": "ai"}
for key, value in values.items():
    lines = [line for line in lines if not line.startswith(key + "=")]
    lines.append(key + "=" + value)
env.write_text("\n".join(lines) + "\n", encoding="utf-8")
env.chmod(0o600)
print("Configured local ComfyUI image workflow and AI-only mode (no procedural fallback).")
print("Required checkpoint: sd_xl_base_1.0.safetensors")
print("Start ComfyUI separately, install the checkpoint in ComfyUI/models/checkpoints, then restart SINTU.")
PY