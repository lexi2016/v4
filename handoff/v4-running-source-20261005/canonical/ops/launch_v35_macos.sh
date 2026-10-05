#!/bin/bash

set -euo pipefail

ops_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(CDPATH= cd -- "$ops_dir/.." && pwd -P)"
workspace_root="$(CDPATH= cd -- "$repo_root/.." && pwd -P)"
runtime_root="${V35_RUNTIME_ROOT:-$workspace_root/runtime}"
python_bin="$runtime_root/venvs/v3.5-mac/bin/python"
port="${V35_PORT:-8873}"
selection_root="${V35_STAGE_CENTER_SELECTION_ROOT:-}"

if [ ! -x "$python_bin" ]; then
  printf 'Runtime Python is missing at %s. Run %s first.\n' \
    "$python_bin" "$ops_dir/bootstrap_v35_macos.sh" >&2
  exit 1
fi

case "$port" in
  ''|*[!0-9]*)
    printf 'V35_PORT must be a numeric port: %s\n' "$port" >&2
    exit 1
    ;;
esac

if [ "$port" -lt 1 ] || [ "$port" -gt 65535 ]; then
  printf 'V35_PORT must be between 1 and 65535: %s\n' "$port" >&2
  exit 1
fi

export V35_DATA_ROOT="${V35_DATA_ROOT:-$runtime_root/v3.5/data}"
mkdir -p "$V35_DATA_ROOT"

cd "$repo_root"
args=(
  --host 127.0.0.1 \
  --port "$port"
)
if [ -n "$selection_root" ]; then
  args+=(--stage-selection-root "$selection_root")
fi
exec "$python_bin" -m apps.api.v35_api.run "${args[@]}"
