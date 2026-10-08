from __future__ import annotations

import hashlib
import json
import plistlib
from pathlib import Path
import sys

import pytest

C1_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = C1_ROOT / "release/api_app"
SCHEDULER_ROOT = C1_ROOT / "release/scheduler_app"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from infrastructure.scheduling.manager_announcement_supervisor import validate_binding
from ops.prepare_api_only_cutover import extract_environment
from ops.prepare_manager_daily_chain_release import _file_inventory


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_staged_split_root_plists_share_disabled_binding_and_blocked_final():
    stage = C1_ROOT / "staged_config"
    receipt = json.loads((stage / "manager_daily_chain_c1_release_receipt.final2.json").read_text())
    assert receipt["status"] == "CANDIDATE_STAGED_NOT_ACTIVATED"
    assert receipt["activation_status"] == "NOT_ACTIVATED"
    assert receipt["launchctl_called"] is False

    api_plist_path = stage / "com.lexi.v35.api-only.c1-final2.plist"
    scheduler_plist_path = stage / "com.lexi.v35.scheduler.c1-final2.plist"
    api_plist = plistlib.loads(api_plist_path.read_bytes())
    scheduler_plist = plistlib.loads(scheduler_plist_path.read_bytes())
    api_env = extract_environment(api_plist)
    scheduler_env = extract_environment(scheduler_plist)
    binding_path = stage / "manager-plan-binding-c1.disabled.final2.json"
    state_root = C1_ROOT / "state/manager_auto_research"
    assert api_env["V35_APP_ROOT"] == str(API_ROOT)
    assert scheduler_env["V35_APP_ROOT"] == str(SCHEDULER_ROOT)
    assert api_env["V35_APP_ROOT"] != scheduler_env["V35_APP_ROOT"]
    assert api_env["V4_MANAGER_PLAN_OWNER_BINDING_PATH"] == str(binding_path)
    assert scheduler_env["V4_MANAGER_PLAN_OWNER_BINDING_PATH"] == str(binding_path)
    assert scheduler_env["V4_MANAGER_ANNOUNCEMENT_BINDING"] == str(binding_path)
    assert api_env["V4_MANAGER_RESEARCH_STATE_ROOT"] == str(state_root)
    assert scheduler_env["V4_MANAGER_RESEARCH_STATE_ROOT"] == str(state_root)
    assert api_env["V35_RELEASE_MANIFEST_PATH"] == receipt["candidate_api"]["manifest_path"]
    assert scheduler_env["V35_RELEASE_MANIFEST_PATH"] == receipt["candidate_scheduler"]["manifest_path"]
    assert api_env["V35_RELEASE_MANIFEST_SHA256"] == receipt["candidate_api"]["manifest_sha256"]
    assert scheduler_env["V35_RELEASE_MANIFEST_SHA256"] == receipt["candidate_scheduler"]["manifest_sha256"]
    for env in (api_env, scheduler_env):
        assert env["production_allowed"] == "false"
        assert env["buy_gate_updated"] == "false"
        assert env["orders_sent"] == "false"
    assert _sha(api_plist_path.read_bytes()) == receipt["candidate_api"]["plist_sha256"]
    assert _sha(scheduler_plist_path.read_bytes()) == receipt["candidate_scheduler"]["plist_sha256"]

    disabled = json.loads(binding_path.read_text())
    assert disabled["enabled"] is False
    assert disabled["announcement_collection_enabled"] is False
    assert disabled["announcement_execution_owner"] == {
        "execution_owner": "HEARTBEAT",
        "ownership_status": "HEARTBEAT_OWNED",
        "automation_ref": "automation-3",
        "scheduler_hook_enabled": False,
        "latest_execution_status": "NOT_RUN",
        "latest_success_status": "CANNOT_CONFIRM",
        "latest_gap_status": "CANNOT_CONFIRM",
        "latest_receipt_status": "NOT_OBSERVED",
    }
    validate_binding(disabled, API_ROOT)

    proposed_path = stage / "manager-plan-binding-c1.proposed-enabled.blocked.final2.json"
    proposed = json.loads(proposed_path.read_text())
    assert proposed["enabled"] is True
    assert proposed["activation_status"] == "BLOCKED_OWNER_CANARY_REQUIRED"
    assert proposed.get("activation_receipt") is None
    assert proposed["production_allowed"] is False
    assert proposed["buy_gate_updated"] is False
    assert proposed["orders_sent"] is False
    assert receipt["proposed_enabled_config"]["status"] == "BLOCKED_NOT_RENDERABLE_WITHOUT_OWNER_CANARY"
    assert receipt["proposed_enabled_config"]["path"] == str(proposed_path)
    with pytest.raises(ValueError, match="ANNOUNCEMENT_BINDING_ACTIVATION_RECEIPT_REQUIRED"):
        validate_binding(proposed, API_ROOT)


def test_split_root_manifests_bind_all_source_files_except_their_own_bytes():
    stage = C1_ROOT / "staged_config/manager_daily_chain_c1_release_receipt.final2.json"
    receipt = json.loads(stage.read_text())
    for key, root in (("candidate_api", API_ROOT), ("candidate_scheduler", SCHEDULER_ROOT)):
        manifest_path = Path(receipt[key]["manifest_path"])
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
        assert _sha(raw) == receipt[key]["manifest_sha256"]
        assert manifest["app_root"] == str(root)
        assert manifest["status"] == "CANDIDATE_NOT_ACTIVATED"
        digest = manifest.pop("sha256")
        canonical = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        assert digest == _sha(canonical)
        manifest["sha256"] = digest
        current = _file_inventory(root)
        current.pop(manifest_path.relative_to(root).as_posix())
        assert current == manifest["app_file_sha256"]
        assert all(manifest[name] is False for name in
                   ("production_allowed", "buy_gate_updated", "orders_sent"))
        assert set(manifest["stage_dependency_sha256"]) == {
            name for name in manifest["app_file_sha256"]
            if name.startswith("stage_center/") and name.endswith((".py", ".json"))
        }


def test_release_receipt_records_source_plist_preimages_without_mutation():
    receipt = json.loads((C1_ROOT / "staged_config/manager_daily_chain_c1_release_receipt.final2.json").read_text())
    for key in ("source_api", "source_scheduler"):
        source = Path(receipt[key]["path"])
        assert _sha(source.read_bytes()) == receipt[key]["sha256"]
    assert receipt["rollback"]["status"] == "IDENTITY_ONLY_NO_ACTIVATION"
    assert receipt["rollback"]["api_original_path"] == receipt["source_api"]["path"]
    assert receipt["rollback"]["scheduler_original_path"] == receipt["source_scheduler"]["path"]
    assert receipt["proposed_enabled_config"]["activation_receipt"] == "CANNOT_CONFIRM"
