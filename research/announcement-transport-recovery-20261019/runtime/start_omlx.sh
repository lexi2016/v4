#!/bin/bash
set -euo pipefail

ROOT="/Users/lexi/Desktop/学习/助手/local_llm/qwen3_8_flash_next"
RUNTIME="$ROOT/runtime"
OMLX="$RUNTIME/venv/bin/omlx"
MODEL_DIR="$RUNTIME/models"
STATE="$RUNTIME/omlx-state"
LOG_DIR="$RUNTIME/logs"
PID_FILE="$RUNTIME/server.pid"
PORT=8802

if [[ ! -x "$OMLX" ]]; then
  echo "oMLX runtime is not installed: $OMLX" >&2
  exit 2
fi
if [[ ! -d "$MODEL_DIR/qwen3_8_flash_next" || ! -d "$MODEL_DIR/qwen3_8_27b" ]]; then
  echo "Both model discovery references must exist under $MODEL_DIR" >&2
  exit 2
fi
if [[ -f "$PID_FILE" ]]; then
  prior_pid="$(cat "$PID_FILE")"
  if [[ ! "$prior_pid" =~ ^[0-9]+$ ]]; then
    echo "Invalid PID file; inspect $PID_FILE before changing it." >&2
    exit 3
  fi
  if kill -0 "$prior_pid" 2>/dev/null; then
    echo "PID file refers to a live process (pid=$prior_pid); refusing to start another server." >&2
    exit 3
  fi
  rm "$PID_FILE"
fi
if /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Port $PORT is already occupied; refusing to signal that process." >&2
  exit 4
fi

mkdir -p "$STATE" "$STATE/paged-ssd-cache" "$STATE/huggingface/hub" "$LOG_DIR"
export OMLX_BASE_PATH="$STATE"
export OMLX_LOG_DIR="$LOG_DIR"
export HF_HOME="$STATE/huggingface"
export HF_HUB_CACHE="$STATE/huggingface/hub"
export OMLX_HOST="127.0.0.1"
export OMLX_PORT="$PORT"

printf '%s\n' "$$" > "$PID_FILE"
echo "Starting foreground oMLX on http://127.0.0.1:$PORT (pid=$$)"
echo "model discovery: $MODEL_DIR"
echo "isolated state: $STATE"
echo "Press Ctrl-C in this terminal to stop."
exec "$OMLX" serve \
  --model-dir "$MODEL_DIR" \
  --no-hf-cache \
  --host 127.0.0.1 \
  --port "$PORT" \
  --memory-guard-gb 96 \
  --max-concurrent-requests 4 \
  --paged-ssd-cache-dir "$STATE/paged-ssd-cache" \
  --paged-ssd-cache-max-size 4GB
