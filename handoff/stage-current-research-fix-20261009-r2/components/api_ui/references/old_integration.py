"""Independent cross-owner and failure probes, not a Mac acceptance test."""
from copy import deepcopy
from datetime import datetime, timezone
import ast
import hashlib
import json
from pathlib import Path

import pytest

from conftest import DATE, STAGE, json_bytes


def assert_unverified(output):
    assert output["natural_verified"] is output["execution_verified"] is False


def test_real_store_writer_reader_retains_results_and_binds_only_owner_history(runtime):
    old_files = {str(p): p.read_bytes() for p in runtime.store.root.rglob("*") if p.is_file()}
    written = runtime.write(runtime.base_payload())
    before = {str(p): p.read_bytes() for p in runtime.root.rglob("*") if p.is_file()}
    read = runtime.read(selection_store=runtime.store)
    assert read["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert read["selection_results"]["HK_CONNECT"]["status"] == "NO_VERIFIED_RESULT"
    assert read["markets"]["HK_CONNECT"]["failure_layer"] == "PRESELECTION_INPUT"
    assert read["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert read["selection_artifact_bindings"]["A_SHARE"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert read["selection_artifact_bindings"]["HK_CONNECT"]["status"] == "SELECTION_TRIO_NOT_RECORDED"
    binding = written["selection_artifacts"]["A_SHARE"]
    assert binding["receipt_bytes_sha256"] != binding["receipt_canonical_sha256"]
    assert binding["manifest_bytes_sha256"] != binding["manifest_canonical_sha256"]
    assert "NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING" in read["cannot_confirm"]
    assert_unverified(read)
    assert old_files == {str(p): p.read_bytes() for p in runtime.store.root.rglob("*") if p.is_file()}
    assert before == {str(p): p.read_bytes() for p in runtime.root.rglob("*") if p.is_file()}


def test_real_slot_invocation_clock_reaches_reader(runtime):
    before = datetime.now(timezone.utc)
    written = runtime.run_noop()
    read = runtime.read(selection_store=runtime.store)
    assert before <= datetime.fromisoformat(written["runner_invoked_at"]) <= datetime.now(timezone.utc)
    assert written["runner_clock_source"] == "OWNER_RUNNER_INVOCATION_UTC"
    assert read["runner_invoked_at"] == written["runner_invoked_at"]
    assert read["invocation_time_source"] == written["runner_clock_source"]
    assert read["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert_unverified(read)


@pytest.mark.parametrize("fault", ["absent", "malformed_json", "wrong_identity", "safety_true"])
def test_valid_selection_remains_visible_when_receipt_cannot_be_used(runtime, fault):
    written = runtime.write(runtime.base_payload())
    path = runtime.owner._receipt_path(DATE, STAGE)
    if fault == "absent":
        path.unlink()
    elif fault == "malformed_json":
        path.write_bytes(b"[invalid")
    elif fault == "wrong_identity":
        written["trade_date"] = "20261008"
        path.write_bytes(json_bytes(written))
    else:
        written["orders_sent"] = True
        path.write_bytes(json_bytes(written))
    read = runtime.read(selection_store=runtime.store)
    assert read["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert read["receipt_history_binding"] != "OWNER_HISTORY_SHA_BOUND"
    assert_unverified(read)


def test_missing_configured_selection_store_never_uses_writer_declared_root(runtime):
    runtime.write(runtime.base_payload())
    result = runtime.read()
    assert result["selection_artifact_bindings"]["A_SHARE"]["status"] == "SELECTION_STORE_NOT_BOUND"
    assert result["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert_unverified(result)


def test_other_empty_configured_store_cannot_verify_real_writer_trio(runtime):
    runtime.write(runtime.base_payload())
    other = runtime.selection.SelectionStore(runtime.tmp / "other_selection_root")
    result = runtime.read(selection_store=other)
    assert result["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert result["selection_artifact_bindings"]["A_SHARE"]["status"] == "SELECTION_TRIO_CONFLICT"
    assert_unverified(result)


@pytest.mark.parametrize("mutation", ["canonical_used_as_bytes", "absolute_path", "other_slot"])
def test_owner_written_archive_does_not_authenticate_bad_selection_declaration(runtime, mutation):
    written = runtime.write(runtime.base_payload())
    binding = written["selection_artifacts"]["A_SHARE"]
    if mutation == "canonical_used_as_bytes":
        binding["receipt_bytes_sha256"] = binding["receipt_canonical_sha256"]
    elif mutation == "absolute_path":
        binding["receipt_relative"] = str(runtime.store.root / binding["receipt_relative"])
    else:
        binding["receipt_relative"] = binding["receipt_relative"].replace(DATE, "20261008")
    runtime.receipts._archive_owner_receipt(runtime.owner, written, DATE, STAGE)
    runtime.owner._receipt_path(DATE, STAGE).write_bytes(json_bytes(written) + b"\n")
    output = runtime.read(selection_store=runtime.store)
    assert output["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "SELECTION_TRIO_CONFLICT"
    assert output["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert_unverified(output)


def test_replaced_pointer_during_real_store_verification_is_not_current_binding(runtime, monkeypatch):
    written = runtime.write(runtime.base_payload())
    real_verify = runtime.store._verify_run
    def replace(*args):
        verified = real_verify(*args)
        next_payload = deepcopy(written)
        next_payload["node_attempt_count"] = 2
        runtime.write(next_payload)
        return verified
    monkeypatch.setattr(runtime.store, "_verify_run", replace)
    output = runtime.read(selection_store=runtime.store)
    assert output["receipt_history_binding"] == "OWNER_HISTORY_CONFLICT"
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "SELECTION_TRIO_MATCHES_OBSERVED_RECEIPT_CURRENT_CHANGED"
    assert "RECEIPT_CHANGED_DURING_READ" in output["cannot_confirm"]
    assert output["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert_unverified(output)


def test_reformat_after_writer_still_passes_original_store_but_fails_byte_binding(runtime):
    written = runtime.write(runtime.base_payload())
    relative = written["selection_artifacts"]["A_SHARE"]["manifest_relative"]
    path = runtime.store.root / relative
    path.write_bytes(json.dumps(json.loads(path.read_bytes()), indent=2).encode() + b"\n")
    # Original verifier binds canonical JSON; the receipt's additional raw-byte
    # contract must detect formatting mutation despite that valid canonical run.
    assert runtime.store.read_verified(DATE, STAGE, "A_SHARE")["selected_rows"] == 10
    output = runtime.read(selection_store=runtime.store)
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "SELECTION_TRIO_CONFLICT"
    assert_unverified(output)


def test_unknown_api_lane_status_cannot_authenticate_receipt_references(runtime):
    runtime.write(runtime.base_payload())
    runtime.lanes["A_SHARE"]["status"] = "UNRECOGNIZED_READY"
    output = runtime.read(selection_store=runtime.store)
    assert output["selection_results"]["A_SHARE"]["status"] == "NO_VERIFIED_RESULT"
    assert output["markets"]["A_SHARE"]["selection_binding"] != "BOUND_TO_VERIFIED_SELECTION"
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] != "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert_unverified(output)


def test_json_container_status_is_refused_without_crashing_selection_display(runtime):
    runtime.lanes["A_SHARE"]["status"] = []
    output = runtime.read(selection_store=runtime.store)
    assert output["selection_results"]["A_SHARE"]["status"] == "NO_VERIFIED_RESULT"
    assert_unverified(output)


def test_original_writer_does_not_create_hk_input_from_a_missing_candidate(runtime):
    def missing(*args, **kwargs):
        raise runtime.input_error("synthetic exact-date candidate absent")
    runtime.run_scope["read_candidate_input"] = missing
    written = runtime.run_noop()
    assert written["status"] == "CANNOT_CONFIRM"
    assert written["first_failed_layer"] == "EXACT_SELECTION_INPUT_BINDING"
    assert written["input_bindings"] == written["selection_artifacts"] == {}
    output = runtime.read(selection_store=runtime.store)
    assert output["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "SELECTION_TRIO_NOT_RECORDED"
    assert_unverified(output)


def test_conditional_consumer_forwards_existing_configured_real_store(runtime):
    """Historical call boundary only; current Mac consumer identity is unknown."""
    runtime.write(runtime.base_payload())
    work = Path(__file__).resolve().parents[3]
    before = work / "api_ui/before/conditional_api/stage_center/consumer.py"
    source = work / "api_ui/after/conditional_api/stage_center/consumer.py"
    expected = before.read_text().replace(
        'self.execution_receipt_root, trade_date, stage_id, response["markets"]\n',
        'self.execution_receipt_root, trade_date, stage_id, response["markets"], selection_store=self.store\n')
    assert source.read_text() == expected
    tree = ast.parse(source.read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
             and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
             and node.value.func.id == "read_stage_execution"]
    assert len(calls) == 1
    response = {"markets": deepcopy(runtime.lanes)}
    from types import SimpleNamespace
    scope = {"self": SimpleNamespace(store=runtime.store, execution_receipt_root=runtime.root),
             "trade_date": DATE, "stage_id": STAGE, "response": response,
             "read_stage_execution": runtime.reader.read_stage_execution}
    exec(compile(ast.fix_missing_locations(ast.Module(body=calls, type_ignores=[])), str(source), "exec"), scope)
    output = response["execution_evidence"]
    assert output["selection_artifact_bindings"]["A_SHARE"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert output["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert_unverified(output)
