#!/data/data/com.termux/files/usr/bin/bash
# SINTU Android/Termux Local AI bootstrap.
# Installs the official Termux llama.cpp package and a small Apache-2.0 Qwen GGUF.
set -Eeuo pipefail

MODEL_DIR="${SINTU_LOCAL_MODEL_DIR:-$HOME/.sintu/models}"
MODEL_FILE="$MODEL_DIR/qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
MIN_DISK_KB=1250000
MIN_RAM_KB=900000

fail() { printf 'SINTU Local AI setup: ERROR: %s\n' "$*" >&2; exit 1; }
command -v pkg >/dev/null 2>&1 || fail "Yeh script Termux ke andar chalayein."
[ "$(uname -m)" = "aarch64" ] || fail "Is setup ke liye Android arm64/aarch64 chahiye; detected: $(uname -m)."

available_ram_kb="$(awk '/MemAvailable:/ {print $2; exit}' /proc/meminfo)"
[ -n "$available_ram_kb" ] || fail "Available RAM read nahi ho saki."
[ "$available_ram_kb" -ge "$MIN_RAM_KB" ] || fail "Available RAM kam hai ($(awk -v n="$available_ram_kb" 'BEGIN{printf "%.0f",n/1024}') MB). Apps band karke dobara chalayein; model setup se pehle kam se kam 900 MB free RAM chahiye."

mkdir -p "$MODEL_DIR"
available_disk_kb="$(df -Pk "$MODEL_DIR" | awk 'NR==2 {print $4}')"
[ -n "$available_disk_kb" ] && [ "$available_disk_kb" -ge "$MIN_DISK_KB" ] || fail "Model download ke liye kam se kam 1.25 GB free storage chahiye."

if ! command -v llama-server >/dev/null 2>&1; then
  printf '\n[1/3] Termux package index update aur llama.cpp install...\n'
  pkg update -y
  pkg install -y llama-cpp
fi
if ! command -v curl >/dev/null 2>&1; then
  pkg install -y curl
fi
command -v curl >/dev/null 2>&1 || fail "Model download ke liye curl install nahi ho saka."
command -v llama-server >/dev/null 2>&1 || fail "llama-cpp install hua, lekin llama-server command nahi mila. Package output check karein; source build automatically nahi kiya gaya."

if [ -s "$MODEL_FILE" ]; then
  magic="$(head -c 4 "$MODEL_FILE" | od -An -tx1 | tr -d ' \n')"
  [ "$magic" = "47475546" ] || fail "Existing model file GGUF format mein nahi hai: $MODEL_FILE. Original file ko delete nahi kiya."
  printf '\n[2/3] Existing valid GGUF model reuse kiya.\n'
else
  printf '\n[2/3] Official Qwen model download (~491 MB)...\n'
  temp_file="$MODEL_FILE.part"
  rm -f "$temp_file"
  curl --fail --location --retry 3 --connect-timeout 20 --output "$temp_file" "$MODEL_URL"
  magic="$(head -c 4 "$temp_file" | od -An -tx1 | tr -d ' \n')"
  [ "$magic" = "47475546" ] || { rm -f "$temp_file"; fail "Downloaded file GGUF nahi hai; partial download hata diya." ; }
  mv "$temp_file" "$MODEL_FILE"
fi

printf '\n[3/3] Setup verification...\n'
llama-server --version 2>&1 | head -n 1 || true
printf 'Model: %s\n' "$MODEL_FILE"
printf 'Model size: '
du -h "$MODEL_FILE" | awk '{print $1}'
printf '\nSetup complete. Start the local engine with:\n'
printf '  bash scripts/start_local_ai_termux.sh\n'
printf '\nSINTU auto-detects the loopback OpenAI-compatible endpoint at http://127.0.0.1:8080/v1.\n'
printf 'No .env secrets or paid-provider settings were changed.\n'
