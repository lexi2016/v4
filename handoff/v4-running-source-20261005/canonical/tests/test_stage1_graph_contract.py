from __future__ import annotations

import hashlib
import json
from pathlib import Path


CONTRACT = Path("contracts/migration/stage1_core_selection_contract.json")
BASELINE = Path("contracts/migration/v3_graph_baseline_v2.json")
INVENTORY = Path("contracts/migration/v35_replacement_inventory_v2.json")


def test_stage1_contract_freezes_the_graph_records_before_implementation() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    semantic_hash = contract.pop("semantic_hash")
    assert hashlib.sha256(
        json.dumps(
            contract,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest() == semantic_hash
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))

    assert contract["schema_version"] == "v3_5.stage1_graph_contract.v2"
    assert contract["atlas_semantic_hash"] == baseline["static_atlas"]["semantic_hash"]
    assert contract["graph_baseline_semantic_hash"] == baseline["semantic_hash"]
    assert inventory["graph_baseline_semantic_hash"] == baseline["semantic_hash"]
    assert contract["feature_ids"] == [
        "navigation.dates",
        "preselection.pools",
        "stage.workbench",
    ]
    assert set(contract["source_record_ids"]) == {
        "file_246923ea63195cd1a018741f",
        "file_1e5911dd23724fa5a115882c",
        "file_2d687e7969164b4175b293c4",
        "file_46dace0844043eb2fecfa75b",
        "file_50c8fc836c92c033d1ad3fce",
        "file_6dfdc4aaf257fcff34e27c4e",
        "file_734e4e3df4f4132d7350651d",
        "file_7eefb555b890e1cf6266d0c9",
        "file_b8879c230d81dafc78aaedde",
        "file_f5f6800a18fdc855915d5931",
        "file_b9abe278524355ae2028217c",
    }
    assert contract["entrypoint_record_ids"] == [
        "entrypoint_0e4a1c702b657f189d43f34a",
    ]
    assert set(contract["source_record_ids"]).issubset(
        {row["atlas_file_id"] for row in inventory["sources"]}
    )
    assert set(contract["entrypoint_record_ids"]).issubset(
        {row["atlas_entrypoint_id"] for row in inventory["entrypoints"]}
    )
    assert set(contract["api_contracts"]) == {
        "GET /api/v1/runs/date-list",
        "GET /api/v3/preselection-pools",
        "GET /api/v3/tasks/status",
        "GET /api/v3/workbench/stage",
        "POST /api/v3/workbench/stage/ensure",
    }
    assert len(contract["runtime_task_keys"]) == 32
    assert len(set(contract["runtime_task_keys"])) == 32
    assert contract["known_legacy_gaps"] == [
        "DATA_FUPAN_TIMELINE_BUTTON_HAS_NO_CLICK_HANDLER",
    ]
    assert contract["deletion_policy"] == "NO_FEATURE_REMOVAL_WITHOUT_EXPLICIT_APPROVAL"
