#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v pkg >/dev/null 2>&1; then
  echo "यह launcher Android Termux के लिए है। Termux में इसे चलाएँ।"
  exit 1
fi

echo "SINTU AI YOUTUBE STUDIO — Termux setup"
echo "पहली बार setup में internet और कुछ समय लगेगा।"
pkg update -y
pkg install -y python ffmpeg git clang make rust pkg-config libjpeg-turbo freetype libpng libffi openssl zlib

if ! python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)'; then
  echo "Python 3.11 या नया version आवश्यक है।"
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  python -m venv .venv
fi

PY="$ROOT/.venv/bin/python"
"$PY" -m pip install --upgrade pip setuptools wheel
# Termux is Android/bionic, not glibc Linux. The prebuilt cryptography wheel can
# load with unresolved CPython symbols on Android, so compile it against Termux.
if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/include/openssl" ]; then
  export OPENSSL_DIR="$PREFIX"
  export OPENSSL_INCLUDE_DIR="$PREFIX/include"
  export OPENSSL_LIB_DIR="$PREFIX/lib"
  export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
  echo "Building cryptography from source for Android/Termux..."
  "$PY" -m pip install --no-binary=cryptography --force-reinstall "cryptography>=50.0.0,<51"
else
  "$PY" -m pip install "cryptography>=50.0.0,<51"
fi
"$PY" -m pip install -r requirements.txt

# Fail here with a focused diagnostic instead of a long Uvicorn import traceback.
"$PY" -c 'from cryptography.fernet import Fernet; print("Cryptography native module: OK")'

if [ ! -f ".env" ]; then
  "$PY" scripts/bootstrap_local.py
fi

echo
echo "Local engine readiness (missing engines are reported, not silently replaced):"
"$PY" scripts/live_e2e.py

echo
echo "Dashboard: http://127.0.0.1:8000"
echo "Server band karne ke liye CTRL+C dabayein."
echo "Android par browser mein upar wala address kholein."
echo "Note: Termux dashboard/API host hai; Ollama, ComfyUI video models aur Piper voice ko"
echo "compatible PC/server par alag se configure karna pad sakta hai."
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
