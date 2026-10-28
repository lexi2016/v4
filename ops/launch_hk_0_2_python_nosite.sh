#!/bin/bash

set -euo pipefail

ops_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(CDPATH= cd -- "$ops_dir/.." && pwd -P)"
workspace_root="$(CDPATH= cd -- "$repo_root/.." && pwd -P)"
runtime_root="${V4_RUNTIME_ROOT:?V4_RUNTIME_ROOT is required}"
real_python="${V4_HK_0_2_REAL_PYTHON:-$runtime_root/venvs/v4-hk02/bin/python}"
hk_site_packages="$runtime_root/venvs/v4-hk02/lib/python3.13/site-packages"
shared_package_root="${V4_SHARED_PACKAGE_ROOT:?V4_SHARED_PACKAGE_ROOT is required}"

[ -x "$real_python" ] || {
  printf 'V4 HK 0.2 real Python is missing or not executable: %s\n' "$real_python" >&2
  exit 1
}
[ -d "$hk_site_packages" ] || {
  printf 'V4 HK 0.2 Python site-packages is missing: %s\n' "$hk_site_packages" >&2
  exit 1
}
[ -d "$shared_package_root" ] || {
  printf 'V4 shared package root is missing: %s\n' "$shared_package_root" >&2
  exit 1
}

export PYTHONPATH="$hk_site_packages:$shared_package_root:${PYTHONPATH:-}"
exec "$real_python" -S "$@"
