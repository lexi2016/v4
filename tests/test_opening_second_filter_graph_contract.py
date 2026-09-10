from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "migration" / "opening_second_filter_v11_graph_contract.json"


def test_v11_implementation_is_anchored_to_the_full_legacy_graph_chain() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    semantic_hash = payload.pop("semantic_hash")
    assert hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest() == semantic_hash

    baseline = json.loads(
        (ROOT / "contracts/migration/v3_graph_baseline_v2.json").read_text(
            encoding="utf-8"
        )
    )
    inventory = json.loads(
        (ROOT / "contracts/migration/v35_replacement_inventory_v2.json").read_text(
            encoding="utf-8"
        )
    )

    assert payload["feature_id"] == "stage.workbench"
    assert payload["atlas_semantic_hash"] == baseline["static_atlas"]["semantic_hash"]
    assert payload["graph_baseline_semantic_hash"] == baseline["semantic_hash"]
    assert payload["graph_node_ids"] == [
        "timeline_node:hkconnect_d1_top100_prob_active",
        "timeline_node:v3_hkconnect_opening_second_filter_v1_1_morning_check",
        "timeline_node:v3_opening_intraday_stage_select_0925_1500",
    ]
    assert set(payload["graph_node_ids"]).issubset(
        baseline["graph_node_registry"]["ids"]
    )
    feature = next(
        row
        for row in inventory["features"]
        if row["feature_id"] == payload["feature_id"]
    )
    assert set(payload["graph_node_ids"]) & set(feature["graph_node_ids"])
    assert set(payload["legacy_source_records"]) == {
        "d1_stage_preselect",
        "auction_reference_capture",
        "v11_champion_rerank",
        "dual_market_overlay",
        "stage_workbench_consumer",
        "daily_orchestrator",
    }
    inventory_sources = {row["old_source"]: row for row in inventory["sources"]}
    for source in payload["legacy_source_records"].values():
        record = inventory_sources[source["path"]]
        assert record["atlas_file_id"] == source["file_id"]
        assert record["atlas_sha256"] == source["atlas_sha256"]
        assert record["sha256"] == source["current_sha256"]
    assert payload["frozen_model_contract"] == {
        "model_id": "hkconnect_opening_second_filter_v1_1",
        "version": "1.1",
        "champion_contract": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer",
        "d1_membership_model": "0.2",
        "same_day_rerank_model": "1.1",
        "signal_cutoff": "09:19:59",
        "publication_time": "09:20:00",
        "top_n": 20,
        "shadow_may_replace_champion": False,
    }
    for relative in payload["v35_replacements"].values():
        assert (ROOT / relative).is_file(), relative
    assert "V35_DAILY_0915_TO_0920_CAPTURE_ORCHESTRATOR" in payload["pending_scope"]
    assert payload["production_allowed"] is False
    assert payload["orders_sent"] is False
