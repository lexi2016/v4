#!/usr/bin/env python3
"""Run the external reviewer Vitest probe via a temporary test-only copy."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


REVIEWER = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("MANAGER_TEST_SOURCE_ROOT", "")).resolve() if os.environ.get(
    "MANAGER_TEST_SOURCE_ROOT") else REVIEWER.parents[3] / "worktrees" / "manager_automation"
if not (ROOT / "apps/web/vite.config.ts").is_file():
    raise SystemExit(f"cannot find manager_automation source root: {ROOT}; set MANAGER_TEST_SOURCE_ROOT")

WEB = ROOT / "apps/web"
NODE_MODULES = Path(os.environ.get("V4_TEST_NODE_MODULES", "")).resolve() if os.environ.get(
    "V4_TEST_NODE_MODULES") else ROOT.parent.parent / "candidate/apps/web/node_modules"
if not (NODE_MODULES / ".bin/vitest").is_file():
    raise SystemExit(f"cannot find Vitest dependencies: {NODE_MODULES}; set V4_TEST_NODE_MODULES")

node_link = WEB / "node_modules"
created_link = not node_link.exists()
test_copies = {
    WEB / "src/manager-selection/__reviewer_actual_route_readback.spec.ts":
        REVIEWER / "ui_actual_route_readback_independent.spec.ts",
    WEB / "src/manager-selection/__reviewer_readback_contract.spec.ts":
        REVIEWER / "ui_readback_contract_probe.spec.ts",
}
existing = [path for path in test_copies if path.exists()]
if existing:
    raise SystemExit(f"refusing to overwrite existing test path(s): {existing}")

if created_link:
    node_link.symlink_to(NODE_MODULES, target_is_directory=True)
for destination, source in test_copies.items():
    shutil.copyfile(source, destination)
env = os.environ.copy()
env["MANAGER_TEST_SOURCE_ROOT"] = str(ROOT)
env["V4_TEST_SOURCE_ROOT"] = str(ROOT)
env.setdefault("V4_TEST_PYTHON", "/workspace/scratch/a154a3323e32/test_env/bin/python")
try:
    result = subprocess.run(
        [str(NODE_MODULES / ".bin/vitest"), "run",
         "src/manager-selection/__reviewer_actual_route_readback.spec.ts",
         "src/manager-selection/__reviewer_readback_contract.spec.ts"],
        cwd=WEB, env=env, check=False,
    )
finally:
    for path in test_copies:
        path.unlink(missing_ok=True)
    if created_link:
        node_link.unlink(missing_ok=True)
raise SystemExit(result.returncode)
