#!/usr/bin/env python3
"""Run the pinned runtime's existing release identity checker on the candidate."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys


HANDOFF = Path(__file__).resolve().parent
CANDIDATE_RELEASE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "us-receipt-compat-api-20261017-r1"
)
CANDIDATE_APP = CANDIDATE_RELEASE / "app"
CANDIDATE_MANIFEST = CANDIDATE_RELEASE / "release-manifest.json"
CANDIDATE_MANIFEST_SHA256 = "3b1a3edef0919fcda17b401f443bf71433ac98aff1c2c374814c0128c2e6d05c"
STAGED_PLIST = HANDOFF / "com.lexi.v35.api-only.candidate.plist"
SOURCE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
SOURCE_PLIST_SHA256 = "03095bd9b06e38da5c3fe4ebe9031851252fc78e95ac4020bfacc4bdd6f545f3"
PYTHON = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/"
    "v3.5-mac/bin/python"
)

IDENTITY_FILES = (
    "infrastructure/scheduling/dispatcher.py",
    "ops/run_scheduled_slot.py",
    "infrastructure/scheduling/executor_registry.py",
    "contracts/runtime_workloads.json",
    "domains/intraday_research.py",
    "ops/run_intraday_research.py",
    "infrastructure/research_peripheral_store.py",
    "apps/api/v35_api/research_lane_router.py",
)

RUNTIME_CODE = r'''
import hashlib, importlib, importlib.util, json, os, sys
from pathlib import Path

app = Path(os.environ["V35_APP_ROOT"]).resolve()
manifest_path = Path(os.environ["V35_RELEASE_MANIFEST_PATH"]).resolve()
if Path.cwd().resolve() != app:
    raise RuntimeError("RUNTIME_CWD_NOT_CANDIDATE_APP")
if not sys.path or Path(sys.path[0] or ".").resolve() != app:
    raise RuntimeError("RUNTIME_SYS_PATH_NOT_CANDIDATE_FIRST")
raw = manifest_path.read_bytes()
manifest_sha = hashlib.sha256(raw).hexdigest()
if manifest_sha != os.environ["V35_RELEASE_MANIFEST_SHA256"]:
    raise RuntimeError("RUNTIME_MANIFEST_SHA_MISMATCH")
manifest = json.loads(raw)
if manifest["candidate"]["release_id"] != os.environ["V35_RELEASE_ID"]:
    raise RuntimeError("RUNTIME_RELEASE_ID_MISMATCH")
entries = {row["path"]: row for row in manifest["application_inventory"]["entries"]}
for relative in EXPECTED_FILES:
    path = app / relative
    if hashlib.sha256(path.read_bytes()).hexdigest() != entries[relative]["sha256"]:
        raise RuntimeError("RUNTIME_FILE_SHA_MISMATCH:" + relative)
for relative, module_name in MODULES.items():
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        raise RuntimeError("RUNTIME_MODULE_SPEC_MISSING:" + relative)
    resolved = Path(spec.origin).resolve()
    expected_path = app / relative
    if resolved != expected_path:
        raise RuntimeError("RUNTIME_MODULE_SHADOWED:" + relative + ":" + str(resolved))
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    if digest != entries[relative]["sha256"]:
        raise RuntimeError("RUNTIME_MODULE_SHA_MISMATCH:" + relative)

from infrastructure.scheduling import dispatcher
if Path(dispatcher.__file__).resolve() != app / "infrastructure/scheduling/dispatcher.py":
    raise RuntimeError("IDENTITY_CHECKER_IMPORT_SHADOWED")
identity = dispatcher.validate_release_identity()
if identity["release_id"] != os.environ["V35_RELEASE_ID"]:
    raise RuntimeError("IDENTITY_CHECKER_RELEASE_ID_MISMATCH")
store_module = importlib.import_module("infrastructure.research_peripheral_store")
route_module = importlib.import_module("apps.api.v35_api.research_lane_router")
for module, relative in ((store_module, "infrastructure/research_peripheral_store.py"),
                         (route_module, "apps/api/v35_api/research_lane_router.py")):
    path = Path(module.__file__).resolve()
    if path != app / relative or hashlib.sha256(path.read_bytes()).hexdigest() != entries[relative]["sha256"]:
        raise RuntimeError("CANDIDATE_MODULE_POST_IMPORT_IDENTITY_MISMATCH:" + relative)
print("identity=" + json.dumps(identity, ensure_ascii=False, sort_keys=True))
print("store_module=" + str(Path(store_module.__file__).resolve()))
print("store_module_sha256=" + hashlib.sha256(Path(store_module.__file__).read_bytes()).hexdigest())
print("route_module=" + str(Path(route_module.__file__).resolve()))
print("route_module_sha256=" + hashlib.sha256(Path(route_module.__file__).read_bytes()).hexdigest())
'''


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    if not CANDIDATE_APP.is_dir() or not CANDIDATE_MANIFEST.is_file():
        raise FileNotFoundError("CANDIDATE_APP_OR_MANIFEST_MISSING")
    if CANDIDATE_MANIFEST.parent.resolve() != CANDIDATE_RELEASE.resolve():
        raise ValueError("CANDIDATE_ROOT_IDENTITY_INVALID")
    if sha256(CANDIDATE_MANIFEST.read_bytes()) != CANDIDATE_MANIFEST_SHA256:
        raise ValueError("CANDIDATE_MANIFEST_SHA_CHANGED_STOP")
    source_raw = SOURCE_PLIST.read_bytes()
    if sha256(source_raw) != SOURCE_PLIST_SHA256:
        raise ValueError("SOURCE_API_PLIST_CHANGED_STOP")
    source = plistlib.loads(source_raw)
    staged_raw = STAGED_PLIST.read_bytes()
    staged = plistlib.loads(staged_raw)
    if staged.get("Label") != source.get("Label") or staged.get("ProgramArguments") is None:
        raise ValueError("CANDIDATE_API_PLIST_IDENTITY_INVALID")
    if staged.get("RunAtLoad") != source.get("RunAtLoad") or staged.get("KeepAlive") != source.get("KeepAlive"):
        raise ValueError("CANDIDATE_API_PLIST_LIFECYCLE_CHANGED")
    if staged.get("EnvironmentVariables") != source.get("EnvironmentVariables"):
        raise ValueError("CANDIDATE_API_PLIST_ENVIRONMENT_CHANGED")
    if staged.get("StartCalendarInterval") != source.get("StartCalendarInterval"):
        raise ValueError("CANDIDATE_API_PLIST_TRIGGERS_CHANGED")
    if staged.get("WorkingDirectory") != str(CANDIDATE_APP):
        raise ValueError("CANDIDATE_API_PLIST_CWD_MISMATCH")
    expected_identity = {
        "V35_APP_ROOT": str(CANDIDATE_APP),
        "V35_RELEASE_ID": CANDIDATE_RELEASE.name,
        "V35_RELEASE_MANIFEST_PATH": str(CANDIDATE_MANIFEST),
        "V35_RELEASE_MANIFEST_SHA256": CANDIDATE_MANIFEST_SHA256,
        "PYTHONPATH": f"{CANDIDATE_APP}/upstreams:{CANDIDATE_APP}",
    }
    source_args = source["ProgramArguments"]
    staged_args = staged["ProgramArguments"]
    for name, expected in expected_identity.items():
        matches = [value for value in staged_args if isinstance(value, str) and value.startswith(name + "=")]
        if matches != [f"{name}={expected}"]:
            raise ValueError("CANDIDATE_API_PLIST_VALUE_MISMATCH:" + name)
    if len(source_args) != len(staged_args):
        raise ValueError("CANDIDATE_API_PLIST_ARGUMENT_COUNT_CHANGED")
    allowed_names = set(expected_identity)
    for before, after in zip(source_args, staged_args):
        if before == after:
            continue
        name = before.split("=", 1)[0] if isinstance(before, str) else ""
        if name not in allowed_names or not isinstance(after, str) or not after.startswith(name + "="):
            raise ValueError("CANDIDATE_API_PLIST_ARGUMENT_CHANGED")

    env = os.environ.copy()
    for value in staged_args:
        if isinstance(value, str) and "=" in value:
            name, item = value.split("=", 1)
            if name in expected_identity or name in {
                "PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "RESEARCH_ONLY",
                "production_allowed", "PRODUCTION_ALLOWED", "buy_gate_updated",
                "BUY_GATE_UPDATED", "orders_sent", "ORDERS_SENT",
            }:
                env[name] = item
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    code = (
        "EXPECTED_FILES = " + repr(IDENTITY_FILES) + "\n"
        "MODULES = " + repr({
            "infrastructure/scheduling/dispatcher.py": "infrastructure.scheduling.dispatcher",
            "ops/run_scheduled_slot.py": "ops.run_scheduled_slot",
            "infrastructure/scheduling/executor_registry.py": "infrastructure.scheduling.executor_registry",
            "domains/intraday_research.py": "domains.intraday_research",
            "ops/run_intraday_research.py": "ops.run_intraday_research",
            "infrastructure/research_peripheral_store.py": "infrastructure.research_peripheral_store",
            "apps/api/v35_api/research_lane_router.py": "apps.api.v35_api.research_lane_router",
        }) + "\n" + RUNTIME_CODE
    )
    result = subprocess.run(
        [str(PYTHON), "-B", "-c", code],
        cwd=CANDIDATE_APP,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    print(f"python={PYTHON}")
    print(f"cwd={CANDIDATE_APP}")
    print(f"candidate_manifest_sha256={CANDIDATE_MANIFEST_SHA256}")
    print(f"staged_api_plist_sha256={sha256(staged_raw)}")
    print(result.stdout, end="")
    return 0 if result.returncode == 0 and "identity={" in result.stdout else 1


if __name__ == "__main__":
    sys.exit(main())
