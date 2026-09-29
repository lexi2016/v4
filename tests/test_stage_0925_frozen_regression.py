from __future__ import annotations

import hashlib
import json
from pathlib import Path

from domains.stages import StageRunner
from infrastructure.stage_store import StageStore


FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "stage_0925_20260730_tdxpy_input.json"
)
FIXTURE_SHA256 = "d447078fee592a9dd741dddc16bd637ed02d2043b91c6648fab15aca3c6b284c"
ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_0925_frozen_regression_contract_is_graph_bound_and_self_hashed() -> None:
    contract_path = (
        ROOT
        / "contracts"
        / "migration"
        / "stage_0925_tdxpy_frozen_regression_v1.json"
    )
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    semantic_hash = contract.pop("semantic_hash")
    assert hashlib.sha256(
        json.dumps(
            contract,
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
    assert contract["graph_baseline_semantic_hash"] == baseline["semantic_hash"]
    assert set(contract["graph_node_ids"]).issubset(
        baseline["graph_node_registry"]["ids"]
    )
    feature = next(
        row
        for row in inventory["features"]
        if row["feature_id"] == contract["feature_id"]
    )
    assert set(contract["graph_node_ids"]) & set(feature["graph_node_ids"])

    sources = {row["old_source"]: row for row in inventory["sources"]}
    for item in contract["legacy_authority"].values():
        if not isinstance(item, dict) or "path" not in item:
            continue
        source = sources[item["path"]]
        assert source["atlas_file_id"] == item["atlas_file_id"]
        assert source["atlas_sha256"] == item["sha256"]

    for name in ("provider", "adapter", "provider_test", "frozen_input"):
        item = contract["replacement"][name]
        assert _sha256(ROOT / item["path"]) == item["sha256"]


def test_20260730_tdxpy_0925_frozen_input_keeps_147_146_50_50_contract(
    tmp_path: Path,
) -> None:
    raw = FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FIXTURE_SHA256
    payload = json.loads(raw)

    assert payload["source_summary"]["quote_source"] == (
        "V3_5_TDXPY_0925_COMPOSITE"
    )
    assert payload["source_summary"]["requested_A"] == 147
    assert len(payload["rows"]["A"]) == 146
    assert {
        row["source_method"] for row in payload["rows"]["A"]
    } == {"pytdx.hq.get_history_transaction_data"}
    assert "PYTDX_0925_AUCTION_ROWS_MISSING: A.300333" in (
        payload["source_summary"]["cannot_confirm"]
    )
    assert "A.300333" not in {
        row["symbol"] for row in payload["rows"]["A"]
    }

    store = StageStore(tmp_path / "data")
    imported = store.import_input(payload)
    assert imported["sha256"] == FIXTURE_SHA256
    result = StageRunner(store).ensure("20260730", "STAGE_0925")
    assert result["ensure_status"] == "STAGE_RUN_COMPLETE"

    workbench = StageRunner(store).read_workbench(
        "20260730",
        "STAGE_0925",
        limit=50,
    )
    assert workbench["markets"]["A"] == {
        "label": "A股",
        "candidate_count": 50,
        "source_rows": 146,
        "requested_rows": 147,
        "source_status": "CANNOT_CONFIRM",
        "data_level": "WATCH_ONLY",
    }
    assert workbench["selected_a_rows"] == 50
    assert len(workbench["stage_groups"][0]["rows"]) == 50
    assert workbench["production_allowed"] is False
    assert workbench["buy_gate_updated"] is False
    assert workbench["orders_sent"] is False
