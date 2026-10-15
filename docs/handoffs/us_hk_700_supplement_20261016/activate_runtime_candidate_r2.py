"""R2 path binding for the reviewed activation core; never activates by default."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys

import activate_runtime_candidate as activation
from ops.api_release_integration import read_active_release


HANDOFF = Path(__file__).resolve().parent
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
PLIST = activation.PLIST
ACTIVE_CONFIG = BASE / "config/oversold-nextday-recovery-20261015-r1.json"
CANDIDATE = BASE / "releases/us-hk-mapping700-20261016-r2"
NEW_CONFIG = BASE / "config/us-hk-mapping700-20261016-r2.json"
PREPARATION_RECEIPT = HANDOFF / "candidate-preparation-receipt-r2.json"
DELTA_RECEIPT = HANDOFF / "runtime-delta-receipt-r2.json"
ACTIVATION_RECEIPT = HANDOFF / "runtime-activation-receipt-r2.json"
PLAN_PATH = CANDIDATE / "config/cutover-plan.json"
STAGED_PLIST = CANDIDATE / "config/com.lexi.v35.api-only.plist"
ROLLBACK_PLIST = CANDIDATE / "config/active-api-plist.preimage"
R1_ACTIVATION_RECEIPT = HANDOFF / "runtime-activation-receipt.json"

_PLAN_BINDINGS = (
    "active_plist_path", "active_plist_sha256", "active_release_id",
    "active_manifest_sha256", "active_application_inventory_sha256",
    "active_config_path", "active_config_sha256", "new_config_path", "new_config_sha256",
    "candidate_root", "candidate_app_root", "candidate_release_id", "candidate_manifest_path",
    "candidate_manifest_sha256", "staged_plist_path", "staged_plist_sha256",
    "rollback_plist_path", "rollback_plist_sha256", "runtime_delta_receipt_path",
    "runtime_delta_receipt_sha256",
)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_r2() -> dict[str, object]:
    """Validate the prepared R2 identity, then bind the reviewed core to R2 paths."""
    if ACTIVATION_RECEIPT == R1_ACTIVATION_RECEIPT:
        raise RuntimeError("R2_ACTIVATION_RECEIPT_MUST_NOT_OVERWRITE_R1")
    if ACTIVATION_RECEIPT.exists():
        raise RuntimeError("R2_ACTIVATION_RECEIPT_EXISTS_REFUSE_OVERWRITE")
    plan = json.loads(PREPARATION_RECEIPT.read_text(encoding="utf-8"))
    if (plan.get("schema_version") != "v4.mapping700_runtime_preparation_receipt.r2"
            or plan.get("status") != "PREPARED_NOT_ACTIVATED"
            or plan.get("activation_status") != "NOT_ACTIVATED"
            or plan.get("launchctl_called") is not False):
        raise RuntimeError("R2_PREPARATION_RECEIPT_NOT_PREPARED")
    expected_paths = {
        "active_plist_path": PLIST,
        "active_config_path": ACTIVE_CONFIG,
        "new_config_path": NEW_CONFIG,
        "candidate_root": CANDIDATE,
        "candidate_app_root": CANDIDATE / "app",
        "candidate_release_id": CANDIDATE.name,
        "candidate_manifest_path": CANDIDATE / "release-manifest.json",
        "staged_plist_path": STAGED_PLIST,
        "rollback_plist_path": ROLLBACK_PLIST,
        "runtime_delta_receipt_path": DELTA_RECEIPT,
    }
    for key, expected in expected_paths.items():
        if plan.get(key) != str(expected):
            raise RuntimeError("R2_PREPARATION_PATH_BINDING_MISMATCH:" + key)
    if plan.get("candidate_verification", {}).get("status") != "PASS":
        raise RuntimeError("R2_CANDIDATE_VERIFICATION_NOT_PASS")
    if plan.get("candidate_api_test", {}).get("status") != "PASS":
        raise RuntimeError("R2_CANDIDATE_API_TEST_NOT_PASS")

    cutover = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if any(cutover.get(key) != plan.get(key) for key in _PLAN_BINDINGS):
        raise RuntimeError("R2_CUTOVER_PLAN_BINDING_MISMATCH")
    if cutover.get("status") != "PREPARED_NOT_ACTIVATED" or cutover.get("activation_status") != "NOT_ACTIVATED":
        raise RuntimeError("R2_CUTOVER_PLAN_NOT_PREPARED")

    file_bindings = {
        CANDIDATE / "release-manifest.json": plan["candidate_manifest_sha256"],
        NEW_CONFIG: plan["new_config_sha256"],
        STAGED_PLIST: plan["staged_plist_sha256"],
        ROLLBACK_PLIST: plan["rollback_plist_sha256"],
        DELTA_RECEIPT: plan["runtime_delta_receipt_sha256"],
    }
    for path, expected_sha in file_bindings.items():
        if _file_sha(path) != expected_sha:
            raise RuntimeError("R2_ARTIFACT_SHA_BINDING_MISMATCH:" + path.name)

    active_plist_raw = PLIST.read_bytes()
    active = read_active_release(PLIST, role="gateway")
    if (_file_sha(PLIST) != plan["active_plist_sha256"]
            or _file_sha(ACTIVE_CONFIG) != plan["active_config_sha256"]
            or ROLLBACK_PLIST.read_bytes() != active_plist_raw
            or active["release_id"] != plan["active_release_id"]
            or active["release_manifest_sha256"] != plan["active_manifest_sha256"]
            or active["application_inventory_sha256"] != plan["active_application_inventory_sha256"]):
        raise RuntimeError("R2_ACTIVE_BASE_CAS_STALE_REBASE_REQUIRED")

    # Keep the existing reviewed gate/cutover implementation and only bind its paths.
    activation.CANDIDATE = CANDIDATE
    activation.ACTIVE_CONFIG = ACTIVE_CONFIG
    activation.NEW_CONFIG = NEW_CONFIG
    activation.PLAN_PATH = PLAN_PATH
    activation.STAGED_PLIST = STAGED_PLIST
    activation.ROLLBACK_PLIST = ROLLBACK_PLIST
    activation.ACTIVATION_RECEIPT_PATH = ACTIVATION_RECEIPT
    return {"candidate_root": str(CANDIDATE),
            "candidate_manifest_sha256": plan["candidate_manifest_sha256"],
            "new_config_path": str(NEW_CONFIG), "new_config_sha256": plan["new_config_sha256"],
            "plan_path": str(PLAN_PATH), "staged_plist_path": str(STAGED_PLIST),
            "rollback_plist_path": str(ROLLBACK_PLIST),
            "activation_receipt_path": str(ACTIVATION_RECEIPT),
            "active_plist_sha256": plan["active_plist_sha256"],
            "active_manifest_sha256": plan["active_manifest_sha256"],
            "binding_status": "PASS"}


def main() -> None:
    prior = {name: getattr(activation, name) for name in (
        "CANDIDATE", "ACTIVE_CONFIG", "NEW_CONFIG", "PLAN_PATH", "STAGED_PLIST",
        "ROLLBACK_PLIST", "ACTIVATION_RECEIPT_PATH",
    )}
    bind_r2()
    try:
        activation.main()
    finally:
        for name, value in prior.items():
            setattr(activation, name, value)


if __name__ == "__main__":
    main()
