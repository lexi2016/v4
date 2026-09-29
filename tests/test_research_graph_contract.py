from __future__ import annotations

import hashlib
import json
from pathlib import Path

from contracts.research import DEDUPE_KEY_FIELDS


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "migration" / "research_desk_graph_contract_v1.json"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "research"
FIXTURE_MANIFEST = FIXTURE_ROOT / "manifest.json"
LEGACY_SOURCE = FIXTURE_ROOT / "snapshots" / "research_lane_snapshot_20260730.json"


def test_research_desk_is_anchored_to_inventory_graph_and_frozen_source() -> None:
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
    feature = next(
        row for row in inventory["features"] if row["feature_id"] == "research.desk"
    )

    assert payload["atlas_semantic_hash"] == baseline["static_atlas"]["semantic_hash"]
    assert payload["graph_baseline_semantic_hash"] == baseline["semantic_hash"]
    # The graph contract is finer-grained than the inventory feature: it also
    # tracks the legacy file node that hosts the research desk view. The
    # contract must cover every inventory node plus the extra file node, and
    # every contract node must exist in the frozen baseline registry.
    assert set(feature["graph_node_ids"]).issubset(set(payload["graph_node_ids"]))
    assert set(payload["graph_node_ids"]).issubset(baseline["graph_node_registry"]["ids"])
    assert payload["frozen_input"] == {
        "archive_date": "20260730",
        "relative_path": "研报模块/runtime_outputs/latest/20260730/research_lane_snapshot.json",
        "raw_sha256": "8ba8b92b6c85b977caac13390533fbf0aec05bfd4e52045229f0964a159be96c",
        "source_counts": {
            "stock_research_timeline": 1475,
            "stock_research_daily": 205,
            "research_pool_bridge": 205,
            "cannot_confirm": 333,
        },
        "normalized_counts": {"articles": 336, "stock_pool": 205},
    }
    assert payload["frozen_semantics"]["dedupe_key_fields"] == list(DEDUPE_KEY_FIELDS)
    assert payload["frozen_semantics"]["stock_pool_limit"] is None
    assert payload["frozen_semantics"]["latest_fallback_allowed"] is False

    inventory_sources = {row["old_source"]: row for row in inventory["sources"]}
    for source in payload["legacy_source_records"].values():
        record = inventory_sources[source["path"]]
        assert record["atlas_file_id"] == source["file_id"]
        assert record["atlas_sha256"] == source["atlas_sha256"]
        assert record["sha256"] == source["current_sha256"]
    for relative in payload["v35_replacements"].values():
        assert (ROOT / relative).is_file(), relative
    assert payload["v35_endpoints"] == {
        "exact": "GET /api/v3/research/articles?archive_date=YYYYMMDD",
        "latest": "GET /api/v3/research/articles/latest",
        "missing_status": "NOT_MATERIALIZED",
    }
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_frozen_legacy_source_reproduces_graph_counts_without_path_leakage() -> None:
    from domains.research import build_research_archive

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    frozen = contract["frozen_input"]
    fixture_manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    assert fixture_manifest["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    snapshot_fixture = fixture_manifest["snapshot"]
    assert snapshot_fixture["archive_date"] == "20260730"
    assert snapshot_fixture["relative_path"] == "snapshots/research_lane_snapshot_20260730.json"
    raw = LEGACY_SOURCE.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == frozen["raw_sha256"]
    assert digest == snapshot_fixture["sha256"]
    assert len(raw) == snapshot_fixture["bytes"]
    source = json.loads(raw.decode("utf-8-sig"))
    for field, expected in snapshot_fixture["source_counts"].items():
        assert len(source[field]) == expected
        assert len(source[field]) == frozen["source_counts"][field]

    archive = build_research_archive(source, source_input_sha256=digest)

    assert archive["article_count"] == frozen["normalized_counts"]["articles"]
    assert archive["stock_pool_count"] == frozen["normalized_counts"]["stock_pool"]
    assert archive["article_count"] == snapshot_fixture["normalized_counts"]["articles"]
    assert archive["stock_pool_count"] == snapshot_fixture["normalized_counts"]["stock_pool"]
    serialized = json.dumps(archive, ensure_ascii=False)
    assert "\\v3_system\\" not in serialized
    assert "C:\\Users\\huang" not in serialized
    assert "LEGACY_RUNTIME_PATHS_REDACTED:2" in archive["cannot_confirm"]
