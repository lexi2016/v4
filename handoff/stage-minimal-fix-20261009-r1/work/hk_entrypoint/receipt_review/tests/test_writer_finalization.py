"""Independent original-store/deadline/partial-publication checks."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from conftest import DATE, STAGE


def test_real_deadline_rewrite_binds_final_receipt_and_keeps_prior_archive(runtime):
    path = Path(__file__).resolve().parents[3] / "receipt_binding/references/stage_center/end_to_end_deadline.py"
    spec = importlib.util.spec_from_file_location("independent_deadline_reference", path)
    deadline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(deadline)
    clock = [100]
    trace = deadline.Trace(entry_ns=1, entry_wall_ns=1_790_000_000_000_000_000,
        policy="enforce", mono=lambda: clock[0], wall=lambda: 1_790_000_000_000_000_000 + clock[0])
    deadline.set_current(trace)
    runtime.scope["_deadline"] = deadline
    try:
        first = runtime.write(runtime.base_payload())
        first_path = runtime.root / first["receipt_history"]["relative_path"]
        first_bytes = first_path.read_bytes()
        clock[0] = deadline.BUDGET_NS + 100
        pointer = runtime.owner._receipt_path(DATE, STAGE)
        completed = deadline.complete_receipt(pointer, first, rewrite=runtime.write)
        persisted = json.loads(pointer.read_bytes())
        assert completed["deadline_status"] == "EXCEEDED"
        assert persisted["status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
        assert persisted["receipt_history"] != first["receipt_history"]
        assert first_path.read_bytes() == first_bytes
        assert persisted["markets"]["A_SHARE"]["selected_rows"] == 10
        output = runtime.read(selection_store=runtime.store)
        assert output["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
        assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
        assert output["declared_status"] == "PARTIAL_COMMIT_RETRY_REQUIRED"
        assert output["execution_verified"] is output["natural_verified"] is False
    finally:
        deadline.set_current(None)
        trace.close()


def test_archive_without_failed_current_pointer_write_does_not_replace_verified_current(runtime):
    first = runtime.write(runtime.base_payload())
    pointer = runtime.owner._receipt_path(DATE, STAGE)
    first_bytes = pointer.read_bytes()
    original_files = {str(path) for path in runtime.root.rglob("RECEIPT.json")}
    next_payload = deepcopy(first)
    next_payload["node_attempt_count"] = 99
    def fail_pointer(*args):
        raise OSError("synthetic final pointer replace failure")
    runtime.scope["_atomic_json"] = fail_pointer
    with pytest.raises(OSError, match="final pointer replace"):
        runtime.write(next_payload)
    assert pointer.read_bytes() == first_bytes
    assert len({str(path) for path in runtime.root.rglob("RECEIPT.json")} - original_files) == 1
    output = runtime.read(selection_store=runtime.store)
    assert output["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert output["node_attempt_count"] is None
    assert output["execution_verified"] is output["natural_verified"] is False


@pytest.mark.parametrize("runtime", ["actual_stage"], indirect=True)
def test_active_hk_recovery_keeps_original_a_lane_and_bound_trio(runtime):
    prior_payload = runtime.base_payload()
    prior_payload["input_bindings"] = {"A_SHARE": {"source": "old-original-A"}, "HK_CONNECT": {"source": "old-HK"}}
    prior = runtime.write(prior_payload)
    first_archive = runtime.root / prior["receipt_history"]["relative_path"]
    first_raw = first_archive.read_bytes()
    scope = runtime.receipts._ExecutionScope(("HK_CONNECT",), prior, 2, "RECOVERY")
    runtime.owner._execution_scope = scope
    retried = {"trade_date": DATE, "stage_id": STAGE, "status": "CANNOT_CONFIRM",
        "markets": {"A_SHARE": {"selected_rows": 999}, "HK_CONNECT": {"status": "CANNOT_CONFIRM", "selected_rows": 0}},
        "input_bindings": {"A_SHARE": {"source": "new-incorrect-A"}}, "write_performed": False}
    written = runtime.write(retried)
    assert written["markets"]["A_SHARE"] == prior["markets"]["A_SHARE"]
    assert written["input_bindings"]["A_SHARE"] == prior["input_bindings"]["A_SHARE"]
    assert written["selection_artifacts"]["A_SHARE"] == prior["selection_artifacts"]["A_SHARE"]
    assert "HK_CONNECT" not in written["input_bindings"]
    assert "HK_CONNECT" not in written["selection_artifacts"]
    assert written["node_attempt_count"] == 2
    assert first_archive.read_bytes() == first_raw
    output = runtime.read(selection_store=runtime.store)
    assert output["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert output["execution_verified"] is output["natural_verified"] is False


def test_failed_trio_recheck_preserves_existing_selection_without_a_binding(runtime):
    first = runtime.write(runtime.base_payload())
    relative = first["selection_artifacts"]["A_SHARE"]["receipt_relative"]
    (runtime.store.root / relative).unlink()
    written = runtime.run_noop()
    assert written["status"] == "NOOP_ALREADY_VERIFIED"
    assert written["markets"]["A_SHARE"]["selected_rows"] == 10
    assert written["selection_artifacts"] == {}
    assert "trio incomplete" in written["selection_binding_errors"]["A_SHARE"]
    output = runtime.read(selection_store=runtime.store)
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "SELECTION_TRIO_NOT_RECORDED"
    assert output["execution_verified"] is output["natural_verified"] is False
