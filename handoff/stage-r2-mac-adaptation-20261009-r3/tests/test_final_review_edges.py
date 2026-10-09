"""Independent review probes; synthetic seams, unchanged candidate sources."""
from pathlib import Path
import importlib.util
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from stage_center import runner as runtime
from stage_center.candidate_input import CandidateInputError
import test_slot_market_isolation as support


def test_changed_a_pointer_is_lane_local_and_hk_still_publishes(tmp_path, monkeypatch):
    owner, decision = support.setup_runner(
        tmp_path, monkeypatch,
        {"A_SHARE": support.a_builder, "HK_CONNECT": support.hk_builder},
    )
    original = runtime.read_candidate_input

    def changed_at_revalidation(*args, **kwargs):
        if kwargs.get("expected_current_sha256"):
            raise CandidateInputError("CURRENT_POINTER_CHANGED_AFTER_COLLECTION")
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "read_candidate_input", changed_at_revalidation)
    result = owner._run_one(decision)
    assert result["markets"]["HK_CONNECT"].get("selected_rows") == 10, result


@pytest.mark.parametrize("origin", ["HISTORICAL_BACKFILL", "LATE_CATCHUP_REPLAY"])
def test_reader_does_not_classify_explicit_replay_origin_as_natural(tmp_path, origin):
    path = Path(__file__).resolve().parents[1] / "after/api/stage_center/execution_evidence.py"
    spec = importlib.util.spec_from_file_location("stage_center._final_review_execution_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    slot = tmp_path / support.DATE / support.STAGE
    slot.mkdir(parents=True)
    receipt = {
        "schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center",
        "trade_date": support.DATE, "stage_id": support.STAGE,
        "dispatch_mode": "NATURAL", "execution_origin": origin,
        "due_status": "DUE", "markets": {},
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    (slot / "receipt.json").write_text(json.dumps(receipt))
    out = module.read_stage_execution(tmp_path, support.DATE, support.STAGE, {})
    assert out["attempt_mode"] != "NATURAL", out


def test_real_not_due_owner_receipt_remains_readable_by_candidate_reader(tmp_path):
    path = Path(__file__).resolve().parents[1] / "after/api/stage_center/execution_evidence.py"
    spec = importlib.util.spec_from_file_location("stage_center._final_review_execution_evidence", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = runtime.build_production_config(
        candidate_acquisition_root=tmp_path / "candidate", raw_root=tmp_path / "raw",
        selection_root=tmp_path / "selection", receipt_root=tmp_path / "receipt",
    )
    owner = runtime.StageCenterRunner(config)
    owner._execution_origin = "MANUAL_REPLAY"
    result = owner.tick(
        support.DATE, datetime(2026, 10, 9, 9, 20, tzinfo=ZoneInfo("Asia/Shanghai")),
        stage_id=support.STAGE, _skip_precapture=True,
    )
    assert result["status"] == "NOT_DUE"
    out = module.read_stage_execution(config.receipt_root, support.DATE, support.STAGE, {})
    assert out.get("execution_origin") == "MANUAL_REPLAY", out
    assert out["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND", out


def test_real_research_runner_to_final_full_consumer_keeps_same_run(tmp_path, monkeypatch):
    from test_research_runner_chain import prepared

    owner, decision, source_root, calls = prepared(tmp_path, monkeypatch, count=695)
    receipt = owner._run_one(decision)
    base = Path(__file__).resolve().parents[1] / "after/api/stage_center"
    for name, filename in [("stage_center.execution_evidence", "execution_evidence.py"),
                           ("stage_center._final_review_consumer", "consumer.py")]:
        spec = importlib.util.spec_from_file_location(name, base / filename)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
    consumer = module.StageSelectionConsumer(
        owner.config.selection_root, execution_receipt_root=owner.config.receipt_root,
    )
    out = consumer.get(support.DATE, support.STAGE)
    lane = out["markets"]["HK_CONNECT"]
    evidence = out["execution_evidence"]
    summary = evidence["selection_results"]["HK_CONNECT"]
    assert len(lane["rows"]) == 10
    assert summary["status"] == "RESULT_AVAILABLE"
    assert summary["requested_rows"] == summary["source_rows"] == 695
    for key in ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256"):
        assert summary[key] == lane[key] == receipt["markets"]["HK_CONNECT"][key]
    assert summary["research_source"]["input_sha256"]
    assert summary["research_source"]["formal_pit"] is False
    assert evidence["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert evidence["selection_artifact_bindings"]["HK_CONNECT"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert evidence["execution_origin"] == "CURRENT_DAY_RESEARCH_REPLAY"
    assert evidence["attempt_mode"] == "RECOVERY"
    assert evidence["natural_verified"] is evidence["execution_verified"] is False
