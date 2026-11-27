"""Owner formula binding preserves date, lineage, and quarantine semantics."""
from hashlib import sha256
import json

import pytest
from fastapi.testclient import TestClient

from v4_core.api.app import create_app
from v4_core.api.workbench_formula_groups import APPROVED_FORMULA_SHA256, SAFETY_FLAGS
from v4_core.config import V4Config


BASE = "/api/v4/research/workbench"
SOURCE = "2026-11-24"
OBSERVATION = "2026-11-25"
GENERATION = "1" * 64
INPUT = "2" * 64
SELECTOR = "3" * 64
ORIGINAL_DAY = "4" * 64


def _bind_formula_owner(folder, defect=None):
    folder.mkdir(parents=True)
    references = {}

    def write(name, payload):
        raw = json.dumps(payload, sort_keys=True).encode()
        (folder / name).write_bytes(raw)
        references[name] = sha256(raw).hexdigest()
        return {"path": "/owner/never-follow-this-path/" + name, "sha256": references[name]}

    numeric = write("numeric_manifest.json", {
        **SAFETY_FLAGS, "schema_version": "v4.a_share.daily_product_manifest.v1", "data_date": "20261124",
        "source_generation": GENERATION, "input_sha256": INPUT, "processed_count": 15, "sample_only": False,
    })
    artifact = write("owner_artifact.json", {
        **SAFETY_FLAGS, "schema": "V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1", "source_date": SOURCE,
        "observation_date": OBSERVATION, "numeric_manifest": numeric, "formula_sha256": APPROVED_FORMULA_SHA256,
        "generation": GENERATION, "input_sha256": INPUT, "selector_sha256": SELECTOR,
        "group_counts": {"b23_entry": 2, "pb2_confirm": 1},
        "rows": [
            {"symbol": "000001.SZ", "display_name": "甲", "groups": ["b23_entry"]},
            {"symbol": "000002.SZ", "display_name": "乙", "groups": ["pb2_confirm"]},
            {"symbol": "000003.SZ", "display_name": "丙", "groups": ["b23_entry"]},
        ],
    })
    receipt = write("owner_receipt.json", {
        **SAFETY_FLAGS, "status": "COMMITTED", "source_date": SOURCE, "generation": GENERATION,
        "numeric_manifest": numeric, "artifact": artifact,
    })
    write("owner_pointer.json", {
        **SAFETY_FLAGS, "schema": "V4_WORKBENCH_MODULE_COMMIT_V1", "module": "formula_groups",
        "date": SOURCE, "artifact": artifact, "receipt": receipt,
    })
    rows = [
        {"symbol": "000001.SZ", "display_name": "甲", "eligible_candidate": True, "source_groups": "b23_entry",
         "group_states": {"b23_entry": "TRUE", "pb2_confirm": "FALSE"}},
        {"symbol": "000002.SZ", "display_name": "乙", "eligible_candidate": True, "source_groups": "pb2_confirm",
         "group_states": {"b23_entry": "FALSE", "pb2_confirm": "TRUE"}},
        {"symbol": "000003.SZ", "display_name": "丙", "eligible_candidate": False, "source_groups": None,
         "group_states": {"b23_entry": "UNKNOWN", "pb2_confirm": "UNKNOWN"}},
    ]
    if defect == "rebound_duplicate":
        rows[2] = rows[1]
    if defect == "rebound_formula_membership":
        rows[0]["group_states"] = {"b23_entry": "FALSE", "pb2_confirm": "TRUE"}
    write("visible_scope.json", {
        "source_date": SOURCE, "observation_date": OBSERVATION, "generation": GENERATION,
        "input_sha256": INPUT, "source_selector_sha256": SELECTOR, "original_day_sha256": ORIGINAL_DAY,
        "group_counts": {"b23_entry": 1, "pb2_confirm": 1}, "quarantined_identity_count": 1, "rows": rows,
    })
    write("binding.json", {
        "schema": "V4_R20_ISOLATED_FORMULA_BINDING_V1", "source_date": SOURCE,
        "observation_date": OBSERVATION, "approved_formula_sha256": APPROVED_FORMULA_SHA256,
        "original_day_sha256": ORIGINAL_DAY, "files": dict(references),
    })
    if defect == "corrupt_checksum":
        with (folder / "owner_artifact.json").open("ab") as target:
            target.write(b" ")


def test_formula_owner_lineage_and_exact_dates_in_api(tmp_path):
    cfg = V4Config.from_env(tmp_path)
    _bind_formula_owner(cfg.data_dir / "workbench_formula_groups" / SOURCE)
    with TestClient(create_app(cfg)) as client:
        history = client.get(f"{BASE}/history").json()
        assert history["days"] == [{"source_date": SOURCE, "observation_date": OBSERVATION,
                                    "observation_date_basis": "VERIFIED_OWNER_FORMULA_BINDING", "revision": GENERATION}]
        response = client.get(f"{BASE}/days/{SOURCE}", params={"revision": GENERATION})
        assert response.status_code == 200
        body = response.json()
        assert body["source_date"] == SOURCE and body["observation_date"] == OBSERVATION
        assert body["revision"] == body["generation"] == GENERATION and body["input_sha256"] == INPUT
        assert body["formula_groups"]["status"] == "READY"
        assert body["formula_groups"]["group_counts"] == {"b23_entry": 1, "pb2_confirm": 1}
        assert body["formula_groups"]["source_group_counts"] == {"b23_entry": 2, "pb2_confirm": 1}
        assert body["rows"][-1]["classification"] == {"classification": None, "identity_status": "IDENTITY_CONFLICT_NAME"}
        assert body["rows"][-1]["group_states"] == {"b23_entry": "UNKNOWN", "pb2_confirm": "UNKNOWN"}
        assert body["scope_count"] == 3 and body["original_processed_count"] == 15
        for key, expected in SAFETY_FLAGS.items():
            assert body[key] is expected
        assert client.get(f"{BASE}/days/{OBSERVATION}").status_code == 404
        assert client.get(f"{BASE}/days/{SOURCE}?revision=unbound").status_code == 404


@pytest.mark.parametrize("defect", ["corrupt_checksum", "rebound_duplicate", "rebound_formula_membership", "other_date"])
def test_formula_owner_mismatch_cannot_materialize_or_pollute_history(tmp_path, defect):
    cfg = V4Config.from_env(tmp_path)
    supplied_date = OBSERVATION if defect == "other_date" else SOURCE
    _bind_formula_owner(cfg.data_dir / "workbench_formula_groups" / supplied_date, defect)
    with TestClient(create_app(cfg)) as client:
        assert client.get(f"{BASE}/history").json()["days"] == []
        assert client.get(f"{BASE}/days/{supplied_date}").status_code == 404


@pytest.mark.parametrize("has_malformed_binding", [False, True])
def test_unbound_workbench_day_preserves_legacy_score_without_claiming_formula_groups(tmp_path, has_malformed_binding):
    cfg = V4Config.from_env(tmp_path)
    if has_malformed_binding:
        _bind_formula_owner(cfg.data_dir / "workbench_formula_groups" / SOURCE, "corrupt_checksum")
    app = create_app(cfg)
    legacy_detail = {
        "hold_score": {"score": 73, "status": "READY", "action": "WATCH_ONLY"},
        "group_states": {"b23_entry": "TRUE", "pb2_confirm": "FALSE"},
    }
    for day in (SOURCE, "2026-02-30", "20261123"):
        app.state.store.save_workbench_scores(day, [{
            "trade_date": day, "symbol": "000001.SZ", "selection_group": "192", "rule_version": "legacy",
            "score": 73, "action": "WATCH_ONLY", "status": "READY", "detail_json": json.dumps(legacy_detail),
        }])
    with TestClient(app) as client:
        assert client.get(f"{BASE}/days/{SOURCE}?revision=unbound").status_code == 404
        body = client.get(f"{BASE}/days/{SOURCE}?revision=sqlite-current").json()
        assert body["revision"] == "sqlite-current"
        row = body["rows"][0]
        assert row["selection_group"] == "192" and row["hold_score"] == legacy_detail["hold_score"]
        assert row["group_states"]["b23_entry"] == row["group_states"]["pb2_confirm"] == "UNKNOWN"
        assert row["group_states"]["192"] is True and row["group_states"]["backtest"] is False
        assert row["group_states"]["status"] == "CANNOT_CONFIRM_NOT_MATERIALIZED"
        assert "group_states" not in row["history_rates"]
        assert body["formula_review"] == "PENDING"
        history = client.get(f"{BASE}/history").json()
        assert history["dates"] == [SOURCE] and history["rows"] == [{"source_date": SOURCE}]
        assert history["count"] == 1 and history["days"][0]["revision"] == "sqlite-current"
        for bad_date in ("2026-02-30", "20261123"):
            assert client.get(f"{BASE}/days/{bad_date}").status_code == 404
