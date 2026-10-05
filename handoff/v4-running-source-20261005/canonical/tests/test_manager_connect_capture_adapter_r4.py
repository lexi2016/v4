import hashlib
import json
from pathlib import Path

import pytest

from upstreams.v3_shared_data.shared_data.hashing import sha256_json
from upstreams.v3_shared_data.shared_data.hk_security_master import publish_hk_security_master
from v4.manager_research.connect_capture_adapter import read_d1_scope
from v4.manager_research.connect_selection import filter_cards, read_scope

DATE = "20260930"
TARGET = "20261002"
FINISHED = "2026-09-30T17:20:08.269649+08:00"
FALSE_FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _canonical_sha(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path):
    codes = ["HK.00001", "HK.00002", "HK.00003"]
    master_root = tmp_path / "shared-data"
    master_rows = [
        {"code": code, "name": f"issuer-{index}", "outstanding_shares": 1000,
         "circular_market_val": 100000, "listing_date": "2010-01-01", "lot_size": 100,
         "stock_owner": "", "stock_child_type": "", "sec_status": "NORMAL"}
        for index, code in enumerate(codes)
    ]
    published = publish_hk_security_master(
        master_root, trade_date=DATE, rows=master_rows,
        universe_codes_sha256=sha256_json(codes), captured_at="2026-09-30T17:00:00+08:00",
    )
    asset_root = master_root / "assets" / "hk_security_master"
    latest = json.loads((asset_root / "latest.json").read_text())
    entry = latest["entries"][DATE]
    manifest_path = asset_root / entry["manifest_relative"]
    receipt_path = asset_root / entry["receipt_relative"]
    manifest = json.loads(manifest_path.read_text())
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    artifact_sha = hashlib.sha256((asset_root / manifest["artifact_relative"]).read_bytes()).hexdigest()
    codes_sha = sha256_json(codes)

    capture_root = tmp_path / "capture-receipts"
    capture_dir = capture_root / "hk_capture" / DATE
    capture_dir.mkdir(parents=True)
    run_id = "20260930-capture-fixture"
    rows = [{"code": code, "trade_date": DATE, "close": 10 + i} for i, code in enumerate(codes)]
    source_payload = {"rows": rows, "plates": ["HK.GangGuTong", "HK.LIST1922"]}
    capture = {
        "schema_version": "v3.macos.research_panel_hk_capture.v1",
        "target_date": DATE,
        "codes": codes,
        "plates": ["HK.GangGuTong", "HK.LIST1922"],
        "rows": rows,
        "source_payload": source_payload,
        "source_sha256": _canonical_sha(source_payload),
        **FALSE_FLAGS,
    }
    capture["capture_sha256"] = _canonical_sha(capture)
    raw_path = capture_dir / f"{run_id}.capture.json"
    raw_bytes = json.dumps(capture, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    raw_path.write_bytes(raw_bytes)
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    capture_manifest = {
        "schema_version": "v3.macos.research_panel_hk_capture_manifest.v1",
        "status": "READY", "target_date": DATE, "capture_run_id": run_id,
        "capture_raw_sha256": raw_sha, "capture_sha256": capture["capture_sha256"],
        "capture_relative_path": raw_path.name, "capture_path": raw_path.name,
        "codes": codes, "capture": capture, **FALSE_FLAGS,
    }
    capture_manifest_path = capture_dir / f"{run_id}.json"
    capture_manifest_path.write_text(json.dumps(capture_manifest, ensure_ascii=False, sort_keys=True))

    summary_sha = "4" * 64
    panel_authority_sha = "5" * 64
    panel = {
        "schema_version": "v3.macos.research_panel_receipt.v1",
        "target_date": DATE, "lane": "HK", "status": "READY",
        "capture_run_id": run_id, "capture_raw_path": str(raw_path),
        "capture_manifest_path": str(capture_manifest_path),
        "capture_raw_sha256": raw_sha, "source_sha256": capture["source_sha256"],
        "row_count": len(rows), "universe_count": len(codes), "sha256": summary_sha,
        "authority": {"status": "READY", "target_date": DATE, "through_date": DATE,
                      "panel_sha256": panel_authority_sha, **FALSE_FLAGS},
        "security_master": {
            "status": "READY", "trade_date": DATE, "row_count": len(codes),
            "run_id": published["run_id"], "security_master_run_id": published["run_id"],
            "security_master_manifest_sha256": manifest_sha,
            "security_master_artifact_sha256": artifact_sha,
            "universe_codes_sha256": codes_sha,
            "capture_sha256": capture["capture_sha256"],
            "source_sha256": capture["source_sha256"],
            "panel_sha256": panel_authority_sha, **FALSE_FLAGS,
        },
        **FALSE_FLAGS,
    }
    panel_path = capture_root / f"HK-{DATE}.json"
    panel_path.write_text(json.dumps(panel, ensure_ascii=False, sort_keys=True))

    summary = {
        "schema_version": "v3.macos.research_panel_authority_envelope.v1",
        "lane": "HK", "status": "READY", "overall_status": "READY", "target_date": DATE,
        "lanes": {"HK": {"status": "READY", "target_date": DATE,
                           "row_count": len(rows), "sha256": summary_sha, **FALSE_FLAGS}},
        **FALSE_FLAGS,
    }
    workload = {
        "workload_id": "research_panel_daily_hk", "status": "SUCCEEDED", "lane": "HK",
        "lane_status": "READY", "exit_code": 0, "target_date": DATE,
        "source_result": summary, "_authoritative_payload": summary, **FALSE_FLAGS,
    }
    dispatch = {
        "schema_version": "v3_5.dispatch.v1", "status": "SUCCEEDED", "target_date": DATE,
        "business_date": DATE, "scheduled_date": DATE, "slot": "1720",
        "run_id": "fixture-dispatch-run", "started_workload_ids": ["research_panel_daily_hk"],
        "selected_workload_ids": ["research_panel_daily_hk"], "finished_at": FINISHED,
        "workload_results": [workload], **FALSE_FLAGS,
    }
    dispatch_root = tmp_path / "dispatch-receipts"
    dispatch_dir = dispatch_root / "live" / DATE / "1720"
    dispatch_dir.mkdir(parents=True)
    (dispatch_dir / "fixture-dispatch-run.dispatch-receipt.json").write_text(
        json.dumps(dispatch, ensure_ascii=False, sort_keys=True)
    )
    context = {"plan_trade_date": TARGET, "market_session": DATE,
               "research_cutoff": "2026-10-01T08:46:37+08:00"}
    return context, master_root, capture_root, dispatch_root, codes


def test_exact_previous_session_capture_scope_validates_full_link_chain_and_keeps_source_date(tmp_path):
    context, master_root, capture_root, dispatch_root, codes = _fixture(tmp_path)
    scope = read_d1_scope(
        context, security_master_root=master_root,
        capture_receipt_root=capture_root, dispatch_receipt_root=dispatch_root,
    )
    assert scope["status"] == "OWNER_VERIFIED", scope["gaps"]
    assert scope["target_trade_date"] == TARGET
    assert scope["source_date"] == DATE
    assert scope["codes"] == codes
    assert scope["source"]["source_date"] == DATE
    assert scope["source"]["dispatch_finished_at"] == FINISHED
    assert scope["effective_available_at"] == FINISHED
    assert scope["source"]["availability_semantics"].startswith("SUCCESSFUL_HK_DISPATCH_FINISH")
    assert "available_at" not in scope["source"]

    accepted, rejected = filter_cards(
        [{"symbol": codes[0], "name": "display name is not membership evidence"},
         {"symbol": "HK.00999", "name": "outside"}],
        scope, target_date=TARGET,
    )
    assert [row["symbol"] for row in accepted] == [codes[0]]
    assert accepted[0]["connect_eligibility"] == "VERIFIED_PREVIOUS_FULL_SESSION_CONNECT_MEMBERSHIP"
    assert accepted[0]["membership_semantics"] == "EXACT_PREVIOUS_FULL_SESSION_CAPTURED_CONNECT_CODES"
    assert rejected[0]["reason"] == "NOT_IN_TARGET_HK_CONNECT_UNIVERSE"


def test_dispatch_finish_after_cutoff_and_capture_lane_mismatch_fail_closed(tmp_path):
    context, master_root, capture_root, dispatch_root, _codes = _fixture(tmp_path)
    too_early_cutoff = {**context, "research_cutoff": "2026-09-30T16:59:00+08:00"}
    out = read_d1_scope(too_early_cutoff, security_master_root=master_root,
                        capture_receipt_root=capture_root, dispatch_receipt_root=dispatch_root)
    assert out["status"] == "CANNOT_CONFIRM"
    assert "HK_CONNECT_D1_MASTER_AFTER_CUTOFF_OR_UNKNOWN" in out["gaps"][0]

    after_master_before_dispatch = {**context, "research_cutoff": "2026-09-30T17:10:00+08:00"}
    out = read_d1_scope(after_master_before_dispatch, security_master_root=master_root,
                        capture_receipt_root=capture_root, dispatch_receipt_root=dispatch_root)
    assert out["status"] == "CANNOT_CONFIRM"

    panel_path = capture_root / f"HK-{DATE}.json"
    panel = json.loads(panel_path.read_text())
    panel["lane"] = "A"
    panel_path.write_text(json.dumps(panel, ensure_ascii=False, sort_keys=True))
    out = read_d1_scope(context, security_master_root=master_root,
                        capture_receipt_root=capture_root, dispatch_receipt_root=dispatch_root)
    assert out["status"] == "CANNOT_CONFIRM"
    assert "HK_CONNECT_D1_PANEL_RECEIPT_INVALID" in out["gaps"][0]


def test_read_scope_keeps_target_v2_first_then_uses_explicit_d1_roots(tmp_path, monkeypatch):
    import domains.manager_research_evidence as target_evidence
    import upstreams.v3_shared_data.shared_data.hk_security_master as master_owner

    context, master_root, capture_root, dispatch_root, codes = _fixture(tmp_path)
    owner_root = Path(__file__).resolve().parents[1]
    owner_path = owner_root / "stage_center" / "hk_universe_preflight.py"
    owner_sha = hashlib.sha256(owner_path.read_bytes()).hexdigest()
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_ROOT", str(master_root))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_ROOT", str(owner_root))
    monkeypatch.setenv("V4_MANAGER_UNIVERSE_OWNER_SHA256", owner_sha)
    monkeypatch.setenv("V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT", str(capture_root))
    # Production config binds the exact live receipts directory. The reader
    # also keeps compatibility with direct callers using its parent root.
    monkeypatch.setenv("V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT", str(dispatch_root / "live"))

    def no_target_authority(*_args, **_kwargs):
        raise ValueError("HK_CONNECT_EXACT_UNIVERSE_MISSING")

    monkeypatch.setattr(target_evidence, "read_universe_evidence", no_target_authority)
    scope = read_scope(context)
    assert scope["status"] == "OWNER_VERIFIED"
    assert scope["codes"] == codes
    assert scope["source_date"] == DATE
    assert scope["target_trade_date"] == TARGET
    assert scope["target_date_authority_diagnostic"].endswith("HK_CONNECT_EXACT_UNIVERSE_MISSING")


@pytest.mark.parametrize("change", ["raw_hash", "dispatch_status"])
def test_d1_link_tampering_is_not_accepted(tmp_path, change):
    context, master_root, capture_root, dispatch_root, _codes = _fixture(tmp_path)
    if change == "raw_hash":
        raw = next((capture_root / "hk_capture" / DATE).glob("*.capture.json"))
        raw.write_bytes(raw.read_bytes() + b" ")
    else:
        receipt = next((dispatch_root / "live" / DATE / "1720").glob("*.dispatch-receipt.json"))
        value = json.loads(receipt.read_text())
        value["status"] = "FAILED"
        receipt.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
    out = read_d1_scope(context, security_master_root=master_root,
                        capture_receipt_root=capture_root, dispatch_receipt_root=dispatch_root)
    assert out["status"] == "CANNOT_CONFIRM"
    assert out["codes"] == []
