#!/bin/bash

set -euo pipefail

ops_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(CDPATH= cd -- "$ops_dir/.." && pwd -P)"
workspace_root="$(CDPATH= cd -- "$repo_root/.." && pwd -P)"
runtime_root="${V4_RUNTIME_ROOT:?V4_RUNTIME_ROOT is required}"
python_bin="$runtime_root/venvs/v4-mac/bin/python"
main_site_packages="$runtime_root/venvs/v4-mac/lib/python3.14/site-packages"
hk_0_2_python="${V4_HK_0_2_PYTHON:-$repo_root/ops/launch_hk_0_2_python_nosite.sh}"
data_root="${V4_DATA_ROOT:?V4_DATA_ROOT is required}"
ledger_root="${V4_DISPATCH_LEDGER_ROOT:?V4_DISPATCH_LEDGER_ROOT is required}"
selection_root="${V4_STAGE_CENTER_SELECTION_ROOT:?V4_STAGE_CENTER_SELECTION_ROOT is required}"
shared_data_root="${V4_SHARED_DATA_ROOT:-}"
hk_universe_root="${V4_HK_UNIVERSE_ROOT:-}"
shared_package_root="${V4_SHARED_PACKAGE_ROOT:-}"
selector_data_root="${V4_SELECTOR_DATA_ROOT:-}"
preselection_input_root="${V4_PRESELECTION_INPUT_ROOT:?V4_PRESELECTION_INPUT_ROOT is required}"
if [[ -n "${V4_RESEARCH_PANEL_HK_TDX_ROOT:-}" ]]; then
  # The launchd-facing name is the authoritative panel input.  The shared
  # executor accepts V3_SHARED_HK_TDX_ROOT, so bridge it before Python starts.
  export V3_SHARED_HK_TDX_ROOT="$V4_RESEARCH_PANEL_HK_TDX_ROOT"
elif [[ -z "${V3_SHARED_HK_TDX_ROOT:-}" ]]; then
  printf 'V4_RESEARCH_PANEL_HK_TDX_ROOT is required for the HK 0.2 lane\n' >&2
  exit 1
fi
hk_tdx_root="$V3_SHARED_HK_TDX_ROOT"
[ -d "$hk_tdx_root" ] || {
  printf 'V35 HK 0.2 TDX root is missing or not a directory: %s\n' "$hk_tdx_root" >&2
  exit 1
}

[ -x "$python_bin" ] || {
  printf 'V4 scheduler Python is missing: %s\n' "$python_bin" >&2
  exit 1
}
[ -d "$main_site_packages" ] || {
  printf 'V4 scheduler Python site-packages is missing: %s\n' "$main_site_packages" >&2
  exit 1
}

hk_0_2_runtime_valid=true
if [ ! -x "$hk_0_2_python" ]; then
  printf 'V4 HK 0.2 Python is missing or not executable; HK lane will be CANNOT_CONFIRM: %s\n' \
    "$hk_0_2_python" >&2
  hk_0_2_runtime_valid=false
elif ! hk_0_2_version="$("$hk_0_2_python" -c 'import sys; print(".".join(str(part) for part in sys.version_info[:3]))')"; then
  printf 'V4 HK 0.2 Python cannot be executed; HK lane will be CANNOT_CONFIRM: %s\n' \
    "$hk_0_2_python" >&2
  hk_0_2_runtime_valid=false
elif [[ "$hk_0_2_version" != "3.13.12" ]]; then
  printf 'V4 HK 0.2 Python must be 3.13.12, got %s; HK lane will be CANNOT_CONFIRM: %s\n' \
    "$hk_0_2_version" "$hk_0_2_python" >&2
  hk_0_2_runtime_valid=false
fi
if [[ "$hk_0_2_runtime_valid" != true ]]; then
  # Preserve the lane-local missing-runtime guard in FixedExecutorRegistry.
  # The main scheduler must still run independent workloads.
  hk_0_2_python="${hk_0_2_python}.invalid"
fi

cd "$repo_root"
export PYTHONPATH="$repo_root:$main_site_packages:${PYTHONPATH:-}"
args=(
  --data-root "$data_root"
  --ledger-root "$ledger_root"
  --preselection-input-root "$preselection_input_root"
  --stage-selection-root "$selection_root"
  --hk-0-2-python "$hk_0_2_python"
  --a-daily-timeout-seconds 14400
)
if [[ -n "$shared_data_root" ]]; then
  args+=(--shared-data-root "$shared_data_root")
fi
if [[ -z "$hk_universe_root" && -n "$shared_data_root" ]]; then
  hk_universe_root="$(dirname "$(dirname "$shared_data_root")")"
fi
if [[ -n "$hk_universe_root" ]]; then
  args+=(--hk-universe-root "$hk_universe_root")
fi
if [[ -n "$shared_package_root" ]]; then
  args+=(--shared-package-root "$shared_package_root")
fi
if [[ -n "$selector_data_root" ]]; then
  args+=(--selector-data-root "$selector_data_root")
fi
if [[ "${V4_DAEMON_MODE:-}" != "persistent-minute" ]]; then
  # Keep the historical one-shot invocation available to older sealed
  # releases and explicit compatibility canaries.  The T060 LaunchAgent
  # sets the persistent mode explicitly below.
  exec "$python_bin" -S -m ops.run_v4_macos_scheduler "${args[@]}"
fi
exec "$python_bin" -S -m ops.run_v4_macos_scheduler_daemon "${args[@]}"
