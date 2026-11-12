#!/bin/bash

set -euo pipefail

ops_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(CDPATH= cd -- "$ops_dir/.." && pwd -P)"
workspace_root="$(CDPATH= cd -- "$repo_root/.." && pwd -P)"
runtime_root="${V4_RUNTIME_ROOT:?V4_RUNTIME_ROOT is required}"
python_bin="$runtime_root/venvs/v4-mac/bin/python"
port="${V4_PORT:-8873}"
selection_root="${V4_STAGE_CENTER_SELECTION_ROOT:-}"

if [ ! -x "$python_bin" ]; then
  printf 'Runtime Python is missing at %s. Run %s first.\n' \
    "$python_bin" "$ops_dir/install_v4_runtime_closure.py" >&2
  exit 1
fi

case "$port" in
  ''|*[!0-9]*)
    printf 'V4_PORT must be a numeric port: %s\n' "$port" >&2
    exit 1
    ;;
esac

if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
  printf 'V4_PORT must be between 1 and 65535: %s\n' "$port" >&2
  exit 1
fi

export V4_DATA_ROOT="${V4_DATA_ROOT:?V4_DATA_ROOT is required}"
mkdir -p "$V4_DATA_ROOT"

cd "$repo_root"
args=(
  --host 127.0.0.1 \
  --port "$port"
)
if [ -n "$selection_root" ]; then
  args+=(--stage-selection-root "$selection_root")
fi
exec "$python_bin" -m apps.api.v4_api.run "${args[@]}"
