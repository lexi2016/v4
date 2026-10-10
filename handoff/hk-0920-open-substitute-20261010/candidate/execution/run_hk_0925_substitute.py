from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from stage_center.live_collectors import read_hk_0925_0930_substitute_inputs
from stage_center.selection import SelectionStore, select_hk_0925_0930_substitute

E3 = Path(__file__).resolve().parents[1]
TRADE_DATE = "20261009"
RAW_STORE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/"
    "mac_apply_20261009_r3_01/research_0935/raw/backfill/85e29661ecd848fe9b8344ea59279e86"
)
RAW_RUN_ID = "20261009-hk_connect_1min_stage_0930_0935-4ae83948d3a9e50d"
RAW_ARTIFACT_SHA256 = "e0923241fd5172ac547019aa013190b74c2aee6ee218ace1b0001620f2bf6eb4"
D1_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/"
    "recovery_20261009_all_stages_20261010/candidate/hk_0_2_score_01"
)
D1_RANKED_ROWS_SHA256 = "ad12cffc5ea14925d705c5519ec4d35dfe82f4bf665dfff98d3daf487103d94c"
D1_CANDIDATE_RECEIPT_SHA256 = "adcaa31e445010a02208d6006ead15e5876433d2f8bfd7598f8f358ae33e69ef"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    source = read_hk_0925_0930_substitute_inputs(
        raw_store_root=RAW_STORE_ROOT,
        source_run_id=RAW_RUN_ID,
        expected_raw_artifact_sha256=RAW_ARTIFACT_SHA256,
        d1_ranked_rows_path=D1_ROOT / "ranked_rows.json",
        expected_d1_ranked_rows_sha256=D1_RANKED_ROWS_SHA256,
        d1_candidate_receipt_path=D1_ROOT / "candidate_receipt.json",
        expected_d1_candidate_receipt_sha256=D1_CANDIDATE_RECEIPT_SHA256,
        trade_date=TRADE_DATE,
    )
    envelope = select_hk_0925_0930_substitute(
        source,
        TRADE_DATE,
        raw_artifact_sha256=RAW_ARTIFACT_SHA256,
    )
    backfill_id = uuid5(
        NAMESPACE_URL,
        f"hk-0925-substitute:{TRADE_DATE}:{RAW_ARTIFACT_SHA256}:{D1_RANKED_ROWS_SHA256}",
    ).hex
    store_root = E3 / "candidate" / "state" / "stage" / "selection" / "backfill" / backfill_id
    store = SelectionStore(store_root)
    published = store.publish(envelope, market="HK_CONNECT")
    verified = store.read_verified(TRADE_DATE, "STAGE_0925", "HK_CONNECT")
    if published != verified:
        raise RuntimeError("SelectionStore readback differs from published substitute")
    latest = json.loads(store.latest_path.read_text(encoding="utf-8"))
    entry = latest["entries"][f"{TRADE_DATE}/STAGE_0925/HK_CONNECT"]
    run_dir = store_root / "selection_runs" / TRADE_DATE / "HK_CONNECT_SELECTION_STAGE_0925" / entry["run_id"]
    output = {
        "schema_version": "v4.hk_0925_0930_substitute_build_receipt.v1",
        "candidate_only": True,
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0925",
        "display_label": "09:30–09:35开盘数据替代补算；实际数据截止09:35",
        "ranking_stage_id": "STAGE_0930_0935",
        "ranking_algorithm_sha256": verified["algorithm_sha256"],
        "source": {
            "source_id": "pytdx_exhq",
            "run_id": RAW_RUN_ID,
            "artifact_sha256": RAW_ARTIFACT_SHA256,
            "raw_store_root": str(RAW_STORE_ROOT),
            "requested_rows": 695,
            "source_rows": 695,
            "target_d1_member_requested_rows": source["requested_rows"],
            "target_d1_member_rows_available": source["source_rows"],
            "missing_target_d1_members": list(source["missing_symbols"]),
            "source_window": "09:30-09:35",
            "source_last_bar_time": "2026-10-09 09:35:00",
            "source_captured_at": source["source_capture_time"],
            "manifest_temporal_cutoff_safe": False,
            "target_stage_temporal_cutoff_safe": False,
            "membership_status": "RECONSTRUCTED_ASOF_CANDIDATE_PIT_UNVERIFIED",
            "d1_ranked_rows_sha256": D1_RANKED_ROWS_SHA256,
            "d1_candidate_receipt_sha256": D1_CANDIDATE_RECEIPT_SHA256,
        },
        "selection": {
            "run_id": verified["run_id"],
            "artifact_id": verified["artifact_id"],
            "selection_status": verified["selection_status"],
            "source_status": verified["source_status"],
            "requested_rows": verified["requested_rows"],
            "source_rows": verified["source_rows"],
            "selected_rows": len(verified["rows"]),
            "missing_symbols": verified["missing_symbols"],
            "cannot_confirm": verified["cannot_confirm"],
            "codes_scores": [{"code": row["code"], "score": row["score"]} for row in verified["rows"]],
            "latest_path": str(store.latest_path),
            "run_path": str(run_dir),
            "artifact_path": str(run_dir / "artifact.csv"),
            "artifact_sha256": sha_file(run_dir / "artifact.csv"),
            "manifest_path": str(run_dir / "manifest.json"),
            "manifest_file_sha256": sha_file(run_dir / "manifest.json"),
            "receipt_path": str(run_dir / "receipt.json"),
            "receipt_file_sha256": sha_file(run_dir / "receipt.json"),
        },
        "safety": {
            "RESEARCH_ONLY": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        "source_evidence": source["source_evidence"],
    }
    receipt_path = E3 / "receipts" / "hk0925_substitute" / "SELECTION_BUILD_RECEIPT.json"
    write_json(receipt_path, output)
    print(json.dumps({
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha_file(receipt_path),
        "backfill_id": backfill_id,
        "selection_run_id": verified["run_id"],
        "source_rows": verified["source_rows"],
        "requested_rows": verified["requested_rows"],
        "selected_rows": len(verified["rows"]),
        "selection_status": verified["selection_status"],
        "algorithm_sha256": verified["algorithm_sha256"],
        "codes_scores": output["selection"]["codes_scores"],
        "source_last_bar_time": "2026-10-09 09:35:00",
        "temporal_cutoff_safe": False,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
