"""Synthetic probe: candidate installer must not execute a drifted recovery helper.

All paths and writes are under a TemporaryDirectory owned by this probe.
No service, network, product source, or business data operation is performed.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUTPUT = Path(os.environ.get("ISSUE28_REVIEW_PROBE_OUTPUT", HERE))
SOURCE = Path(os.environ.get("ISSUE28_REVIEW_INSTALLER", HERE / "initial_candidate/release/after/blocked_candidate_ops/api_candidate_install_r2.py"))
spec = importlib.util.spec_from_file_location("independent_installer_probe", SOURCE)
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

with tempfile.TemporaryDirectory(prefix="recovery-load-order-", dir=Path(__file__).parent) as temporary:
    fixture = Path(temporary)
    marker = fixture / "drifted-helper-executed"
    helper = fixture / "api_candidate_recovery.py"
    helper.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed before helper pin check')\n"
        "class RecoveryError(RuntimeError): pass\n"
        "def reviewed_guard_bytes(*args): return b''\n"
    )
    installer.RECOVERY = helper
    installer.PLAN = fixture / "plan.json"
    installer.IDENTITY = fixture / "identity.json"
    installer.PLAN.write_text(json.dumps({
        "plan_status": "READY_FOR_INDEPENDENT_REVIEW",
        "candidate": {"manifest_sha256": installer.EXPECTED["candidate_manifest_sha256"]},
        "writer_artifacts": {
            "guard_path": str(installer.GUARD),
            "guard_sha256": installer.EXPECTED["guard_sha256"],
            "install_helper_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "recovery_helper_sha256": "f" * 64,
        },
    }))
    installer.IDENTITY.write_text(json.dumps({
        "guard_path": str(installer.GUARD),
        "guard_sha256": installer.EXPECTED["guard_sha256"],
    }))
    sys.modules.pop("api_candidate_recovery", None)
    sys.path.insert(0, str(fixture))
    try:
        installer.verify_review_receipt(fixture / "unused-receipt.json", "0" * 64)
    except Exception as error:
        result = {
            "candidate_source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "helper_drift_rejected": isinstance(error, installer.InstallError),
            "error": str(error),
            "drifted_helper_executed_before_rejection": marker.exists(),
            "service_calls": 0,
            "active_paths_touched": False,
        }
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / "PROBE_RELEASE_LOAD_ORDER.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
        print(json.dumps(result, sort_keys=True, indent=2))
    else:
        raise AssertionError("Fixture unexpectedly passed")
