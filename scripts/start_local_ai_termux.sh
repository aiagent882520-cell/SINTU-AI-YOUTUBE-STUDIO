#!/data/data/com.termux/files/usr/bin/bash
# Start SINTU's local llama.cpp server on loopback only.
set -Eeuo pipefail
MODEL_FILE="${SINTU_LOCAL_MODEL_PATH:-$HOME/.sintu/models/qwen2.5-0.5b-instruct-q4_k_m.gguf}"
PORT="${SINTU_LOCAL_AI_PORT:-8080}"
THREADS="${SINTU_LOCAL_AI_THREADS:-4}"
CONTEXT="${SINTU_LOCAL_AI_CONTEXT:-1024}"

[ -x "$(command -v llama-server || true)" ] || { echo "llama-server missing. Run: bash scripts/setup_local_ai_termux.sh" >&2; exit 1; }
[ -s "$MODEL_FILE" ] || { echo "GGUF model missing: $MODEL_FILE" >&2; exit 1; }
case "$PORT:$THREADS:$CONTEXT" in *[!0-9:]*|:*|*::*|*:) echo "Invalid local AI server settings." >&2; exit 1;; esac
[ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ] || { echo "Port must be 1024–65535." >&2; exit 1; }
[ "$THREADS" -ge 1 ] && [ "$THREADS" -le 8 ] || { echo "Threads must be 1–8." >&2; exit 1; }
[ "$CONTEXT" -ge 512 ] && [ "$CONTEXT" -le 4096 ] || { echo "Context must be 512–4096 on this mobile profile." >&2; exit 1; }

magic="$(head -c 4 "$MODEL_FILE" | od -An -tx1 | tr -d ' \n')"
[ "$magic" = "47475546" ] || { echo "Invalid GGUF model file; refusing to start." >&2; exit 1; }
printf 'Starting local-only SINTU AI: http://127.0.0.1:%s/v1\n' "$PORT"
printf 'Model: %s · context: %s · threads: %s\n' "$MODEL_FILE" "$CONTEXT" "$THREADS"
exec llama-server --model "$MODEL_FILE" --ctx-size "$CONTEXT" --threads "$THREADS" --host 127.0.0.1 --port "$PORT"
