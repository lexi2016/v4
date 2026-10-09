"""Fresh R2 source/receipt tests; fixture bytes are explicitly synthetic."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
from copy import deepcopy
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = Path(os.environ.get("V4_RECEIPT_TEST_RUNTIME", ROOT / "runtime_after/actual_stage"))
sys.path.insert(0, str(RUNTIME))


def _module():
    return importlib.import_module("stage_center.runtime_source_identity")


def _source_tree(tmp_path):
    mod = _module()
    for relative in mod.SOURCE_RELATIVES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# synthetic source fixture: " + relative + "\n")
    return mod


def test_source_identity_binds_bytes_and_has_explicit_scope(tmp_path):
    mod = _source_tree(tmp_path)
    identity = mod.capture_runtime_source_identity(root=tmp_path)
    assert identity["status"] == "RECORDED"
    assert identity["scope"] == "SOURCE_FILES_AT_RUNNER_ENTRY_NOT_PROCESS_ATTESTATION"
    body = {k: v for k, v in identity.items() if k not in {"sha256", "status"}}
    expected = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert identity["sha256"] == expected
    for relative, evidence in identity["files"].items():
        content = (tmp_path / relative).read_bytes()
        assert evidence == {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
    assert mod.source_stability(identity, root=tmp_path)["status"] == "SOURCE_FILES_UNCHANGED_SINCE_ENTRY"


def test_missing_source_does_not_claim_complete_identity(tmp_path):
    mod = _source_tree(tmp_path)
    (tmp_path / mod.SOURCE_RELATIVES[0]).unlink()
    identity = mod.capture_runtime_source_identity(root=tmp_path)
    assert identity["status"] == "CANNOT_CONFIRM"
    assert identity["missing_files"] == [mod.SOURCE_RELATIVES[0]]
    assert mod.source_stability(identity, root=tmp_path)["status"] == "SOURCE_IDENTITY_INCOMPLETE"


def test_disk_mutation_and_identity_forgery_are_distinguished(tmp_path):
    mod = _source_tree(tmp_path)
    identity = mod.capture_runtime_source_identity(root=tmp_path)
    (tmp_path / mod.SOURCE_RELATIVES[0]).write_text("# changed after entry\n")
    stability = mod.source_stability(identity, root=tmp_path)
    assert stability["status"] == "SOURCE_FILES_CHANGED_DURING_RUN"
    assert stability["changed_files"] == [mod.SOURCE_RELATIVES[0]]
    assert stability["entry_sha256"] == identity["sha256"]
    assert stability["observed_sha256"] != identity["sha256"]
    identity["files"][mod.SOURCE_RELATIVES[1]]["sha256"] = "0" * 64
    assert mod.source_stability(identity, root=tmp_path)["status"] == "SOURCE_IDENTITY_INVALID"


def test_capture_refuses_source_symlink(tmp_path):
    mod = _source_tree(tmp_path)
    source = tmp_path / mod.SOURCE_RELATIVES[0]
    source.unlink()
    source.symlink_to(tmp_path / mod.SOURCE_RELATIVES[1])
    identity = mod.capture_runtime_source_identity(root=tmp_path)
    assert identity["status"] == "CANNOT_CONFIRM"
    assert mod.SOURCE_RELATIVES[0] in identity["missing_files"]


@pytest.mark.parametrize("outer_mode", ["NATURAL", "RECOVERY", "MANUAL"])
def test_final_owner_writer_keeps_manual_research_mode_and_immutable_bytes(tmp_path, outer_mode):
    writer = importlib.import_module("stage_center._runner_parts.runner_receipts")
    from infrastructure.owned_io import SafeRoot
    date, stage = "20261009", "STAGE_1545_1555"
    owner = SimpleNamespace(config=SimpleNamespace(
        receipt_root=tmp_path / "stage/receipts", selection_root=tmp_path / "stage/selection",
        backfill_run_id=None, hk_current_day_research_root=tmp_path / "security_metadata",
    ))
    owner._receipt_path = lambda day, slot: owner.config.receipt_root / day / slot / "receipt.json"
    def atomic(path, payload):
        SafeRoot(path.parent).write_bytes(path.name, json.dumps(payload, ensure_ascii=False, sort_keys=True).encode())
    globals_scope = {"_deadline": SimpleNamespace(before_receipt=deepcopy, receipt_written=lambda *args: None),
        "SAFETY_FLAGS": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        "_atomic_json": atomic}
    record = writer._StageCenterRunner__write_receipt_body(globals_scope, owner, {
        "trade_date": date, "stage_id": stage, "markets": {}, "execution_mode": outer_mode,
        "natural_execution_verified": True, "status": "CANNOT_CONFIRM", "write_performed": False,
    }, date, stage)
    assert record["execution_mode"] == "MANUAL_CURRENT_DAY_RESEARCH"
    assert record["natural_execution_verified"] is False
    assert record["RESEARCH_ONLY"] is True
    assert all(record[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    archived = (owner.config.receipt_root / record["receipt_history"]["relative_path"]).read_bytes()
    assert hashlib.sha256(archived).hexdigest() == record["receipt_history"]["sha256"]
    assert json.loads(archived) == {key: value for key, value in record.items() if key != "receipt_history"}
    assert record["record_time_source"] == "OWNER_WRITE_CLOCK_UTC"


def test_current_research_never_enters_original_direct_precapture(tmp_path):
    writer = importlib.import_module("stage_center._runner_parts.runner_receipts")
    owner = SimpleNamespace(config=SimpleNamespace(hk_current_day_research_root=tmp_path, hk_d1_root=None))
    # An empty scope would fail if the strict producer or its calendar runs.
    assert writer._StageCenterRunner__prepare_hk_active_snapshots_body({}, owner, "20261009", None,
        stage_id="STAGE_1545_1555", historical_backfill=False) == []
