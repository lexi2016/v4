from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPAIR_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPAIR_ROOT / "final3_candidate" / "release" / "api_app"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

HELPER_PATH = API_ROOT / "ops" / "prepare_manager_daily_chain_release.py"
SPEC = importlib.util.spec_from_file_location("c1_final3_stage_helper", HELPER_PATH)
assert SPEC is not None and SPEC.loader is not None
HELPER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HELPER)


def test_stage_suffix_keeps_final2_default_and_builds_consistent_final3_paths(tmp_path: Path):
    default = HELPER._stage_artifact_paths(tmp_path, "final2")
    assert default["binding"] == tmp_path / "staged_config/manager-plan-binding-c1.disabled.final2.json"
    assert default["proposed"] == tmp_path / "staged_config/manager-plan-binding-c1.proposed-enabled.blocked.final2.json"
    assert default["receipt"] == tmp_path / "staged_config/manager_daily_chain_c1_release_receipt.final2.json"
    assert default["api_plist"].name == "com.lexi.v35.api-only.c1-final2.plist"
    assert default["scheduler_plist"].name == "com.lexi.v35.scheduler.c1-final2.plist"
    assert default["api_manifest"].name == "release-manifest.c1-final2.json"
    assert default["scheduler_manifest"].name == "release-manifest.c1-final2.json"
    assert default["api_release_id"] == "v4-manager-daily-chain-c1-api-final2-candidate"
    assert default["scheduler_release_id"] == "v4-manager-daily-chain-c1-scheduler-final2-candidate"

    final3 = HELPER._stage_artifact_paths(tmp_path, "final3")
    assert final3["binding"].name == "manager-plan-binding-c1.disabled.final3.json"
    assert final3["proposed"].name == "manager-plan-binding-c1.proposed-enabled.blocked.final3.json"
    assert final3["receipt"].name == "manager_daily_chain_c1_release_receipt.final3.json"
    assert final3["api_plist"].name == "com.lexi.v35.api-only.c1-final3.plist"
    assert final3["scheduler_plist"].name == "com.lexi.v35.scheduler.c1-final3.plist"
    assert final3["api_manifest"].name == "release-manifest.c1-final3.json"
    assert final3["scheduler_manifest"].name == "release-manifest.c1-final3.json"
    assert final3["api_release_id"] == "v4-manager-daily-chain-c1-api-final3-candidate"
    assert final3["scheduler_release_id"] == "v4-manager-daily-chain-c1-scheduler-final3-candidate"


@pytest.mark.parametrize("suffix", ["../final3", "/final3", "final3/other", "", "Final3", "a" * 33])
def test_stage_suffix_rejects_non_single_safe_components(suffix: str):
    with pytest.raises(ValueError, match="C1_STAGE_SUFFIX_INVALID"):
        HELPER._stage_artifact_paths(Path("/candidate"), suffix)


def test_superseded_stage_receipt_contract_requires_distinct_suffix_and_named_receipt(tmp_path: Path):
    receipt = tmp_path / "manager_daily_chain_c1_release_receipt.final2.json"
    receipt.write_text("{}", encoding="utf-8")
    assert receipt.name == "manager_daily_chain_c1_release_receipt.final2.json"

    with pytest.raises(ValueError, match="C1_SUPERSEDED_STAGE_SUFFIX_MUST_DIFFER"):
        HELPER.stage(candidate_root=tmp_path, api_plist_path=Path("/missing/api.plist"),
            scheduler_plist_path=Path("/missing/scheduler.plist"),
            security_master_root=Path("/missing/master"), python=Path("/missing/python"),
            stage_suffix="final2", supersedes_suffix="final2",
            superseded_stage_receipt=receipt)
    with pytest.raises(ValueError, match="C1_SUPERSEDED_STAGE_RECEIPT_REQUIRED"):
        HELPER.stage(candidate_root=tmp_path, api_plist_path=Path("/missing/api.plist"),
            scheduler_plist_path=Path("/missing/scheduler.plist"),
            security_master_root=Path("/missing/master"), python=Path("/missing/python"),
            stage_suffix="final3", supersedes_suffix="final2")
    wrong_receipt = tmp_path / "wrong.json"
    wrong_receipt.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="C1_SUPERSEDED_STAGE_RECEIPT_IDENTITY_MISMATCH"):
        HELPER.stage(candidate_root=tmp_path, api_plist_path=Path("/missing/api.plist"),
            scheduler_plist_path=Path("/missing/scheduler.plist"),
            security_master_root=Path("/missing/master"), python=Path("/missing/python"),
            stage_suffix="final3", supersedes_suffix="final2",
            superseded_stage_receipt=wrong_receipt)
