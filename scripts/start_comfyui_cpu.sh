#!/usr/bin/env bash
# Start a separately hosted ComfyUI instance in explicit CPU-fallback mode.
# This script does not install dependencies, download weights, or expose a public listener.
set -euo pipefail

COMFYUI_ROOT="${COMFYUI_ROOT:-$HOME/ComfyUI}"
COMFYUI_PYTHON="${COMFYUI_PYTHON:-python3}"
COMFYUI_DEVICE="${COMFYUI_DEVICE:-cpu}"
COMFYUI_LISTEN="${COMFYUI_LISTEN:-127.0.0.1}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"

if [[ ! -f "$COMFYUI_ROOT/main.py" ]]; then
  echo "BLOCKED: ComfyUI main.py not found at $COMFYUI_ROOT" >&2
  echo "Set COMFYUI_ROOT to an existing ComfyUI checkout; this launcher does not install it." >&2
  exit 2
fi
if ! command -v "$COMFYUI_PYTHON" >/dev/null 2>&1; then
  echo "BLOCKED: Python executable not found: $COMFYUI_PYTHON" >&2
  exit 2
fi
if [[ ! "$COMFYUI_PORT" =~ ^[0-9]+$ ]] || (( COMFYUI_PORT < 1 || COMFYUI_PORT > 65535 )); then
  echo "Invalid COMFYUI_PORT; expected 1..65535." >&2
  exit 2
fi
if [[ "$COMFYUI_DEVICE" != "cpu" && "$COMFYUI_DEVICE" != "auto" ]]; then
  echo "COMFYUI_DEVICE must be cpu or auto." >&2
  exit 2
fi

device_info="$("$COMFYUI_PYTHON" -c '
try:
 import torch
 print("torch=" + str(torch.__version__))
 print("cuda=" + str(bool(torch.cuda.is_available())))
 print("mps=" + str(bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())))
except Exception as exc:
 print("torch=unavailable:" + type(exc).__name__)
')"
echo "$device_info"

args=()
if [[ "$COMFYUI_DEVICE" == "cpu" ]]; then
  args+=(--cpu)
else
  if ! grep -Eq 'cuda=True|mps=True' <<<"$device_info"; then
    echo "CUDA/MPS accelerator unavailable; selecting ComfyUI CPU fallback."
    args+=(--cpu)
  fi
fi

if [[ "$COMFYUI_LISTEN" != "127.0.0.1" && "$COMFYUI_LISTEN" != "::1" ]]; then
  echo "WARNING: ComfyUI listener is not loopback ($COMFYUI_LISTEN). Restrict access with a host firewall." >&2
fi

cd "$COMFYUI_ROOT"
exec "$COMFYUI_PYTHON" main.py --listen "$COMFYUI_LISTEN" --port "$COMFYUI_PORT" "${args[@]}"
