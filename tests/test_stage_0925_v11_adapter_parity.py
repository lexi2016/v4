from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from domains.opening_second_filter import apply_a_share_v11_adapter
from domains.stage_scoring import rank_a_stage_rows


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "contracts"
    / "migration"
    / "stage_0925_v11_adapter_parity_v1.json"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_stage_0925_v11_adapter_matches_frozen_v3_projection() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    semantic_hash = contract.pop("semantic_hash")
    assert semantic_hash == _semantic_hash(contract)
    assert contract["status"] == "FROZEN_BEFORE_CHANGE"

    graph = json.loads(
        (ROOT / "contracts/migration/v3_graph_baseline_v2.json").read_text(
            encoding="utf-8"
        )
    )
    inventory = json.loads(
        (ROOT / "contracts/migration/v35_replacement_inventory_v2.json").read_text(
            encoding="utf-8"
        )
    )
    assert contract["graph_baseline_semantic_hash"] == graph["semantic_hash"]
    assert set(contract["graph_node_ids"]).issubset(
        graph["graph_node_registry"]["ids"]
    )
    authority = contract["legacy_authority"]
    source = next(
        item
        for item in inventory["sources"]
        if item["old_source"] == authority["path"]
    )
    assert authority["atlas_file_id"] == source["atlas_file_id"]
    assert authority["sha256"] == source["atlas_sha256"]

    fixture_path = ROOT / contract["frozen_input"]["path"]
    assert _sha(fixture_path) == contract["frozen_input"]["sha256"]
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    ranked = rank_a_stage_rows(
        payload["rows"]["A"],
        "STAGE_0925",
        limit=50,
    )
    rows = apply_a_share_v11_adapter(ranked)
    projection = [
        {field: row.get(field) for field in contract["projection_fields"]}
        for row in rows
    ]
    expected = contract["expected"]

    assert len(rows) == expected["row_count"]
    assert _semantic_hash(projection) == expected["projection_sha256"]
    assert _semantic_hash([row["symbol"] for row in projection]) == (
        expected["symbol_order_sha256"]
    )
    assert round(
        sum(row["opening_second_filter_score"] for row in projection),
        4,
    ) == expected["score_sum"]
    assert Counter(
        row["opening_second_filter_label"] for row in projection
    ) == expected["labels"]
    assert Counter(
        flag
        for row in projection
        for flag in row["opening_second_filter_flags"]
    ) == expected["flag_counts"]
    compact = lambda row: [
        row["symbol"],
        row["opening_second_filter_score"],
        row["opening_second_filter_label"],
    ]
    assert [compact(row) for row in projection[:5]] == expected["first_five"]
    assert [compact(row) for row in projection[-5:]] == expected["last_five"]
    for row in rows:
        assert row["model_version"] == "1.1"
        assert row["opening_second_filter_strategy"] == (
            "a_share_v1_1_price_volume_adapter"
        )
        assert row["recommendation_status"] == "WATCH_ONLY"
        assert row["production_allowed"] is False
        assert row["buy_gate_updated"] is False
        assert row["orders_sent"] is False


def test_stage_0925_v11_preserves_near_pressure_risk_reward_semantics() -> None:
    row = {
        "symbol": "A.000001",
        "market": "A",
        "stage_score": 80,
        "pool_score": 80,
        "rank": "1",
        "qmt_open": 104.0,
        "qmt_last": 105.0,
        "qmt_low": 102.0,
        "qmt_high": 105.5,
        "qmt_prev_close": 100.0,
        "qmt_stage_change_pct": 5.0,
        "qmt_amount": 50_000_000,
        "decision_level": "WATCH_TOP",
        "recommendation_status": "WATCH_ONLY",
    }

    result = apply_a_share_v11_adapter([row])[0]

    assert result["breakout_status"] == "NEAR_PRESSURE_NOT_BROKEN"
    assert "level_support_distance_healthy" in result[
        "opening_second_filter_flags"
    ]
    assert "level_near_pressure_unbroken" in result[
        "opening_second_filter_flags"
    ]
    assert "level_risk_reward_poor" in result["opening_second_filter_flags"]
    assert "点位风险收益比" in result["level_structure_reason"]
    assert result["level_structure_reason"] in result[
        "opening_second_filter_reason"
    ]
