"""IR-02 closure only: real CLI/store preserve every A lane around bad HK reuse.

The primary A adapter and WeChat builder are real candidate functions. Their
inputs are synthetic; unrelated missing A lanes use the original missing-lane
contract. No service, scheduler, network or business-data operation occurs.
"""
from __future__ import annotations

import contextlib
import copy
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HK = ROOT / "delivery/hk"
OWNER = HK / "after/active_producer_reference"
os.environ.update(
    HK_OWNER_ROOT=str(OWNER),
    HK_BEFORE_OWNER_ROOT=str(HK / "before/active_producer_reference"),
    HK_SUPPORT_ROOT=str(HK / "support/canonical"),
    HK_FROZEN_ROOT=str(HK / "support/frozen"),
)
spec = importlib.util.spec_from_file_location("ir02_closure_support", HK / "tests/test_hk_split_date_binding.py")
common = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = common
spec.loader.exec_module(common)
DATE = "20261008"
ALL_A = {
    "a_d1_premarket_pool", "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool", "a_share_research_recommendation_pool",
    "a_share_baimao_research_map", "wechat_public_account_v3_preselect",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def read_if_present(path):
    return path.read_bytes() if path.exists() else None


def hk_entry(manifest_path):
    if not manifest_path.exists():
        return None
    return json.loads(manifest_path.read_text()).get("hkconnect_d1_top100")


def input_hashes(root):
    return {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}


def wechat_input(day):
    day.mkdir(parents=True)
    rows = [
        {"ts_code": "000021.SZ", "stock_name": "SYNTHETIC WeChat A one", "signal_date": "20260930", "candidate_score": "0.7", "wechat_v3_preselect_rank": "1"},
        {"ts_code": "000022.SZ", "stock_name": "SYNTHETIC WeChat A two", "signal_date": "20260930", "candidate_score": "0.6", "wechat_v3_preselect_rank": "2"},
    ]
    with (day / "wechat_rows.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (day / "wechat_manifest.json").write_text(json.dumps({
        "status": "WECHAT_V3_PRESELECT_READY", "effective_trade_date": DATE,
        "target_validation": {"status": "TARGET_DATE_CHECK_PASS"},
        "boundary": {"formal_pool_write": False, "buy_gate_write": False},
        "score_scope": "wechat_pool_ts_codes_only", "counts": {"v3_matched_codes": 2},
        "signal_date": "20260930", "article_publish_date": "20260930",
    }))


reports = []
for failure in (
    "mismatched_cache", "missing_artifact", "corrupt_artifact",
    "corrupt_receipt", "corrupt_manifest_entry", "absent_cache",
):
    with tempfile.TemporaryDirectory(prefix=f"ir02-{failure}-", dir=HERE) as temporary:
        root = Path(temporary)
        patch = pytest.MonkeyPatch()
        try:
            common.isolated_a_lanes.__wrapped__(patch)
            common._synthetic_source(root / "source")
            existing = copy.deepcopy(common._build(root / "source"))
            if failure == "mismatched_cache":
                existing.pop("historical_provenance")
            store = common.PreselectionPoolStore(root / "out")
            artifact_relative, receipt_relative = store._relative(DATE, "hkconnect_d1_top100")
            artifact_path, receipt_path = root / "out" / artifact_relative, root / "out" / receipt_relative
            manifest_path = artifact_path.parent / "manifest.json"
            if failure != "absent_cache":
                store.materialize(existing)
            if failure == "missing_artifact":
                artifact_path.unlink()
            elif failure == "corrupt_artifact":
                artifact_path.write_bytes(b'{"synthetic_broken_hk":')
            elif failure == "corrupt_receipt":
                receipt = json.loads(receipt_path.read_text())
                receipt["artifact_sha256"] = "0" * 64
                receipt_path.write_text(json.dumps(receipt))
            elif failure == "corrupt_manifest_entry":
                manifest = json.loads(manifest_path.read_text())
                manifest["hkconnect_d1_top100"] = "0" * 64
                manifest_path.write_text(json.dumps(manifest))
            before = (read_if_present(artifact_path), read_if_present(receipt_path), hk_entry(manifest_path))
            wechat_input(root / "inputs" / DATE)
            source_before, inputs_before = input_hashes(root / "source"), input_hashes(root / "inputs")
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = common.scheduled.main([
                    "--trade-date", DATE, "--signal-date", "20260930",
                    "--hk-target-date", DATE, "--hk-signal-date", "20261007",
                    "--hk-eligibility-source-date", "20260930", "--reuse-formal-pools",
                    "--input-root", str(root / "inputs"), "--shared-data-root", str(root / "source"),
                    "--shared-package-root", str(common.SHARED_PACKAGE_ROOT), "--data-root", str(root / "out"),
                ])
            report = json.loads(stdout.getvalue())
            assert result == 1 and report["status"] == "FAILED"
            assert report["hk_reuse_rejection"]["status"] == "CANNOT_CONFIRM"
            assert report["hk_reuse_rejection"]["publication_status"] == "NOT_PUBLISHED_EXISTING_SLOT_PRESERVED"
            published = {Path(item["artifact_path"]).stem for item in report["artifacts"]}
            assert published == ALL_A, (failure, published)
            pools = {pool_id: store.read_pool(DATE, pool_id) for pool_id in ALL_A}
            assert len(pools["a_d1_premarket_pool"]["rows"]) == 1
            assert pools["a_d1_premarket_pool"]["stage_selection_eligible"] is True
            wechat = pools["wechat_public_account_v3_preselect"]
            assert wechat["status"] == "WECHAT_V3_PRESELECT_READY"
            assert [row["symbol"] for row in wechat["rows"]] == ["A.000021", "A.000022"]
            after = (read_if_present(artifact_path), read_if_present(receipt_path), hk_entry(manifest_path))
            assert after == before, failure
            assert input_hashes(root / "source") == source_before
            assert input_hashes(root / "inputs") == inputs_before
            reports.append({
                "case": failure, "result": "PASS", "cli_exit_code": result,
                "hk_status": "CANNOT_CONFIRM_NOT_PUBLISHED", "all_six_a_artifacts_persisted": True,
                "a_row_counts": {pool_id: len(pool["rows"]) for pool_id, pool in sorted(pools.items())},
                "nonempty_wechat_after_hk_persisted": True,
                "old_hk_artifact_sha256": sha(before[0]), "old_hk_receipt_sha256": sha(before[1]),
                "old_hk_manifest_entry": before[2], "old_hk_bytes_and_manifest_entry_preserved": True,
                "original_shared_source_and_wechat_inputs_unchanged": True,
            })
        finally:
            patch.undo()

summary = {
    "scope": "IR02_HK_REUSE_ISOLATION_CLI_REAL_STORE_ONLY",
    "candidate_ops_sha256": sha((OWNER / "ops/materialize_scheduled_preselection.py").read_bytes()),
    "cases": reports, "service_calls": 0, "all_inputs_synthetic": True,
}
(HERE / "HK_ALL_A_PUBLICATION.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
