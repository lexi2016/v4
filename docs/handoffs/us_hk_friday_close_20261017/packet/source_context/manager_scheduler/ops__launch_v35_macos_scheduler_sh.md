## Source excerpt: `ops/launch_v35_macos_scheduler.sh`

Original source path: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-long-pdf-scheduler-20261016-r3/app/ops/launch_v35_macos_scheduler.sh`

Original full-file SHA-256: `0c577ae83b1f182dabf3b62e642a5bd5f0f8708b48e1806d8c653b691d2ec952`

Release/worktree group: `manager_scheduler`

Loaded manager scheduler launcher source root, Python environment forwarding, and daemon entrypoint.

### Full-source lines 5-9

```bash

ops_dir="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
repo_root="$(CDPATH= cd -- "$ops_dir/.." && pwd -P)"
workspace_root="$(CDPATH= cd -- "$repo_root/.." && pwd -P)"
runtime_root="${V35_RUNTIME_ROOT:-$workspace_root/runtime}"
python_bin="$runtime_root/venvs/v3.5-mac/bin/python"

```

### Full-source lines 63-64

```bash

cd "$repo_root"
export PYTHONPATH="$repo_root:$main_site_packages:${PYTHONPATH:-}"

```

### Full-source lines 92-94

```bash

  exec "$python_bin" -S -m ops.run_v35_macos_scheduler "${args[@]}"
fi
exec "$python_bin" -S -m ops.run_v35_macos_scheduler_daemon "${args[@]}"

```
