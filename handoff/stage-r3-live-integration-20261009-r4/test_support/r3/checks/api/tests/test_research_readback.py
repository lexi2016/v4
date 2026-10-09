from copy import deepcopy
import hashlib
import json
import pytest
from conftest import DATE, STAGE, canonical, source_contract, source_marker


def assert_safe(result):
    assert result["RESEARCH_ONLY"] is True
    assert all(result[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_api_constructor_binds_only_exact_same_backfill_namespace(runtime):
    root = runtime.root / "isolated/selection/backfill/research-20261009"
    consumer = runtime.consumer.StageSelectionConsumer(root)
    assert consumer.execution_receipt_root == runtime.root / "isolated/receipts/backfill/research-20261009"


@pytest.mark.parametrize("relative", ["isolated/selection", "isolated/other/backfill/run1",
                                     "isolated/selection/backfill/bad id", "isolated/selection/run1"])
def test_api_constructor_does_not_guess_receipt_for_other_layouts(runtime, relative):
    assert runtime.consumer.StageSelectionConsumer(runtime.root / relative).execution_receipt_root is None


def test_api_explicit_receipt_root_still_overrides_backfill_layout(runtime):
    explicit = runtime.root / "explicit_receipts"
    consumer = runtime.consumer.StageSelectionConsumer(
        runtime.root / "isolated/selection/backfill/run1", execution_receipt_root=explicit)
    assert consumer.execution_receipt_root == explicit


def test_real_store_cannot_confirm_with_ten_rows_remains_available_without_receipt(runtime):
    saved = runtime.publish()
    out = runtime.get()
    lane = out["markets"]["HK_CONNECT"]
    summary = out["execution_evidence"]["selection_results"]["HK_CONNECT"]
    assert lane["rows"] and len(lane["rows"]) == 10
    assert lane["status"] == "CANNOT_CONFIRM"
    assert summary["status"] == "RESULT_AVAILABLE"
    assert summary["selected_rows"] == 10
    assert summary["run_id"] == saved["run_id"]
    assert summary["selection_status"] == "CANNOT_CONFIRM"
    assert out["execution_evidence"]["status"] == "EXECUTION_RECEIPT_MISSING"
    assert out["execution_evidence"]["natural_verified"] is False
    assert out["execution_evidence"]["execution_verified"] is False
    assert_safe(out)
    assert_safe(out["execution_evidence"])


def test_research_source_is_projected_from_exact_immutable_envelope(runtime):
    saved = runtime.publish()
    out = runtime.get()
    lane = out["markets"]["HK_CONNECT"]
    summary = out["execution_evidence"]["selection_results"]["HK_CONNECT"]
    assert lane["research_source"] == source_contract()
    assert summary["research_source"] == lane["research_source"]
    assert summary["source_evidence"] == saved["source_evidence"]
    assert summary["research_source_status"] == "RECORDED_IN_VERIFIED_SELECTION"
    assert (lane["trade_date"], lane["stage_id"], lane["market"]) == (DATE, STAGE, "HK_CONNECT")
    assert summary["requested_rows"] == 216 and summary["source_rows"] == 206
    assert summary["missing_quote_rows"] == 10


@pytest.mark.parametrize("stage", ["STAGE_0925", "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_0945_1030"])
@pytest.mark.parametrize("quoted", [205, 206])
def test_a_full_216_input_is_not_clamped_to_200_in_reader(runtime, stage, quoted):
    runtime.publish("A_SHARE", status="PARTIAL_WITH_ROWS", stage=stage, source_rows=quoted)
    out = runtime.get(stage=stage, markets=("A_SHARE",))
    result = out["execution_evidence"]["selection_results"]["A_SHARE"]
    assert (result["status"], result["selected_rows"], result["requested_rows"], result["source_rows"]) == ("RESULT_AVAILABLE", 10, 216, quoted)
    assert result["missing_quote_rows"] == 216 - quoted
    assert len(out["markets"]["A_SHARE"]["rows"]) == 10


def test_same_run_original_writer_receipt_and_trio_bind_without_certifying_natural(runtime):
    saved = runtime.publish()
    receipt = runtime.write({"HK_CONNECT": saved})
    before = {str(p):p.read_bytes() for p in runtime.root.rglob("*") if p.is_file()}
    out = runtime.get()
    evidence = out["execution_evidence"]
    assert evidence["selection_results"]["HK_CONNECT"]["selected_rows"] == 10
    assert evidence["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert evidence["selection_artifact_bindings"]["HK_CONNECT"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert evidence["selection_artifact_bindings"]["HK_CONNECT"]["run_id"] == saved["run_id"]
    assert evidence["markets"]["HK_CONNECT"]["selection_binding"] == "BOUND_TO_VERIFIED_SELECTION"
    assert evidence["natural_verified"] is evidence["execution_verified"] is False
    assert receipt["receipt_history"]["sha256"]
    assert {str(p):p.read_bytes() for p in runtime.root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("field,value", [
    ("trade_date", "20261008"), ("stage_id", "STAGE_0925"), ("market", "A_SHARE"),
    ("run_id", "selection-other-run"), ("algorithm_sha256", "0"*64),
    ("raw_artifact_sha256", "b"*64), ("selected_rows", 9),
    ("source_rows", 200), ("source_evidence", [source_marker(source_sha256="d"*64)]),
])
def test_reader_cannot_promote_an_external_lane_from_another_identity(runtime, field, value):
    saved = runtime.publish(status="PARTIAL_WITH_ROWS")
    lane = deepcopy(saved)
    lane.update(status=saved["selection_status"], selection_manifest_receipt_verified=True)
    lane[field] = value
    out = runtime.reader.read_stage_execution(None, DATE, STAGE, {"HK_CONNECT":lane}, selection_store=runtime.store)
    assert out["selection_results"]["HK_CONNECT"]["status"] == "NO_VERIFIED_RESULT"
    assert out["selection_results"]["HK_CONNECT"]["selected_rows"] is None


def test_uncertain_rows_cannot_be_promoted_by_external_boolean_without_a_store(runtime):
    saved = runtime.publish()
    lane = {**saved, "status":"CANNOT_CONFIRM", "selection_manifest_receipt_verified":True}
    out = runtime.reader.read_stage_execution(None, DATE, STAGE, {"HK_CONNECT":lane})
    assert out["selection_results"]["HK_CONNECT"]["status"] == "NO_VERIFIED_RESULT"


@pytest.mark.parametrize("date,stage,market", [("20261008", STAGE, "HK_CONNECT"), (DATE, "STAGE_0925", "HK_CONNECT"), (DATE, STAGE, "A_SHARE")])
def test_consumer_does_not_fall_back_to_other_date_stage_market(runtime, date, stage, market):
    runtime.publish()
    out = runtime.get(date=date, stage=stage, markets=(market,))
    assert out["markets"][market]["rows"] == []
    assert out["execution_evidence"]["selection_results"][market]["status"] == "NO_VERIFIED_RESULT"


@pytest.mark.parametrize("field,value", [("run_id","wrong-run"), ("algorithm_sha256","d"*64), ("raw_artifact_sha256","e"*64)])
def test_receipt_identity_conflict_keeps_the_verified_result_visible(runtime, field, value):
    saved = runtime.publish()
    wrong = deepcopy(saved);wrong[field] = value
    runtime.write({"HK_CONNECT":wrong})
    out = runtime.get()["execution_evidence"]
    assert out["selection_results"]["HK_CONNECT"]["selected_rows"] == 10
    assert out["markets"]["HK_CONNECT"]["selection_binding"] == "SELECTION_IDENTITY_CONFLICT"
    assert out["selection_artifact_bindings"]["HK_CONNECT"]["status"] != "BOUND_TO_VERIFIED_SELECTION_TRIO"


@pytest.mark.parametrize("field,value", [("trade_date","20261008"), ("stage_id","STAGE_0925"), ("market","A_SHARE")])
def test_original_receipt_lane_scope_conflict_is_not_bound_to_current_result(runtime, field, value):
    saved=runtime.publish()
    wrong=deepcopy(saved);wrong[field]=value
    runtime.write({"HK_CONNECT":wrong})
    out=runtime.get()["execution_evidence"]
    assert out["selection_results"]["HK_CONNECT"]["selected_rows"] == 10
    assert out["markets"]["HK_CONNECT"]["selection_binding"] == "SELECTION_IDENTITY_CONFLICT"
    assert out["selection_artifact_bindings"]["HK_CONNECT"]["status"] == "SELECTION_TRIO_CONFLICT"


def test_changed_owner_history_never_hides_rows_or_binds_execution(runtime):
    saved=runtime.publish();receipt=runtime.write({"HK_CONNECT":saved})
    history=runtime.receipts/receipt["receipt_history"]["relative_path"]
    history.write_bytes(history.read_bytes()+b" ")
    out=runtime.get()["execution_evidence"]
    assert out["receipt_history_binding"] == "OWNER_HISTORY_CONFLICT"
    assert out["selection_results"]["HK_CONNECT"]["selected_rows"] == 10
    assert out["selection_artifact_bindings"]["HK_CONNECT"]["status"] != "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert out["natural_verified"] is out["execution_verified"] is False


@pytest.mark.parametrize("changes", [dict(market="A_SHARE"), dict(trade_date="20261008"), dict(source_sha256="not-a-sha"), dict(formal_d1_eligible=True), dict(hk_connect_membership_status="VERIFIED")])
def test_conflicting_research_declaration_cannot_be_upgraded_but_result_survives(runtime, changes):
    runtime.publish(source_evidence=[source_marker(**changes)])
    out=runtime.get()["execution_evidence"]["selection_results"]["HK_CONNECT"]
    assert out["status"] == "RESULT_AVAILABLE" and out["selected_rows"] == 10
    assert out["research_source"] is None
    assert out["research_source_status"] == "CANNOT_CONFIRM"


def test_two_research_declarations_are_not_arbitrarily_chosen(runtime):
    runtime.publish(source_evidence=[source_marker(), source_marker(source_sha256="e"*64)])
    out=runtime.get()["execution_evidence"]["selection_results"]["HK_CONNECT"]
    assert out["research_source"] is None
    assert out["research_source_status"] == "CANNOT_CONFIRM"


def test_missing_trio_is_honest_unknown_not_zero_or_not_run(runtime):
    out=runtime.get()
    summary=out["execution_evidence"]["selection_results"]["HK_CONNECT"]
    assert out["markets"]["HK_CONNECT"]["rows"] == []
    assert summary["status"] == "NO_VERIFIED_RESULT"
    assert summary["selected_rows"] is None


@pytest.mark.parametrize("field,value", [("execution_origin","MANUAL_REPLAY"), ("due_status","HISTORICAL_BACKFILL"), ("due_status","LATE_CATCHUP_REPLAY"), ("same_day_late_observation_recovery",True)])
def test_explicit_manual_or_replay_evidence_never_reports_natural_mode(runtime, field, value):
    saved=runtime.publish()
    runtime.write({"HK_CONNECT":saved}, dispatch_mode="NATURAL", due_status="DUE", **{field:value}) if field != "due_status" else runtime.write({"HK_CONNECT":saved}, dispatch_mode="NATURAL", due_status=value)
    out=runtime.get()["execution_evidence"]
    assert out["attempt_mode"] != "NATURAL"
    assert out["declared_attempt_mode"] == "NATURAL"
    assert out["attempt_mode_status"] == "NATURAL_DECLARATION_CONFLICT"
    assert out["natural_verified"] is False


def test_loaded_source_observations_are_read_back_without_memory_or_execution_attestation(runtime):
    saved=runtime.publish()
    observed={"scope":"LOADED_MODULE_PATHS_AND_OBSERVED_FILE_BYTES", "source_set_sha256":"f"*64,
              "files":{"stage_center/runner.py":{"module":"stage_center.runner", "loaded_path":"/isolated/app/stage_center/runner.py", "sha256":"e"*64}},
              "memory_execution_attested":False}
    runtime.write({"HK_CONNECT":saved},runtime_source_identity=observed)
    out=runtime.get()["execution_evidence"]
    assert out["runtime_source_identity"] == observed
    assert out["runtime_source_identity_scope"] == "OWNER_RECEIPT_DECLARED_FILE_OBSERVATIONS"
    assert out["runtime_source_identity"]["memory_execution_attested"] is False
    assert out["execution_verified"] is out["natural_verified"] is False


def test_existing_backfill_namespace_keeps_its_independently_verified_result(runtime):
    store=runtime.selection.SelectionStore(runtime.store.root/'backfill'/'manual-fixture')
    saved=runtime.publish(target_store=store,source_evidence=[source_marker(),'HISTORICAL_BACKFILL'])
    out=runtime.get(allow_backfill=True)
    result=out['execution_evidence']['selection_results']['HK_CONNECT']
    assert len(out['markets']['HK_CONNECT']['rows'])==10
    assert result['status']=='RESULT_AVAILABLE'
    assert result['selected_rows']==10 and result['run_id']==saved['run_id']
    assert result['selection_mode']=='BACKFILL'
    assert result['research_source']==source_contract()
    assert all(not key.startswith('_verified_selection') for key in out['markets']['HK_CONNECT'])


def test_backfill_result_cannot_borrow_a_natural_namespace_receipt(runtime):
    store=runtime.selection.SelectionStore(runtime.store.root/'backfill'/'manual-fixture')
    saved=runtime.publish(target_store=store,source_evidence=[source_marker(),'HISTORICAL_BACKFILL'])
    runtime.write({'HK_CONNECT':saved},dispatch_mode='NATURAL',due_status='DUE')
    evidence=runtime.get(allow_backfill=True)['execution_evidence']
    assert evidence['selection_results']['HK_CONNECT']['selected_rows']==10
    assert evidence['selection_artifact_bindings']['HK_CONNECT']['status']=='EXECUTION_RECEIPT_NAMESPACE_NOT_BOUND'
    assert evidence['markets']['HK_CONNECT']['selection_binding']=='EXECUTION_RECEIPT_NAMESPACE_NOT_BOUND'
    assert evidence['attempt_mode']=='BACKFILL'
    assert evidence['declared_attempt_mode']=='NATURAL'
    assert evidence['natural_verified'] is evidence['execution_verified'] is False


def test_ambiguous_backfill_wrappers_keep_only_the_identical_selection_result(runtime):
    for wrapper in ('manual-one','manual-two'):
        store=runtime.selection.SelectionStore(runtime.store.root/'backfill'/wrapper)
        runtime.publish(target_store=store,source_evidence=[source_marker(),'HISTORICAL_BACKFILL'])
    out=runtime.get(allow_backfill=True)
    assert out['markets']['HK_CONNECT']['backfill_run_id'] is None
    assert out['markets']['HK_CONNECT']['runner_receipt_verified'] is False
    assert out['execution_evidence']['selection_results']['HK_CONNECT']['selected_rows']==10
