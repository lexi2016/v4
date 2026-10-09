"""Original A selector/store/owner/consumer input-reference readback.

The candidate and quote rows here are synthetic. No current candidate files
are re-read by the API and none of these tests attests PIT or natural timing.
"""
from copy import deepcopy
import importlib
import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from conftest import DATE, HERE, ROOT, canonical


@pytest.fixture
def a_runtime(runtime):
    stage = "STAGE_0930_0935"
    candidate = SimpleNamespace(trade_date=DATE, run_id="synthetic-complete-input-216",
        current_relative=f"{DATE}/current.json", current_sha256="c" * 64,
        artifact_sha256="a" * 64, manifest_sha256="b" * 64, receipt_sha256="d" * 64,
        codes=tuple(f"SZ.{index + 1:06d}" for index in range(216)), source_evidence=())
    evidence = ["selection_contract=V3_TOP10_RECOMMENDATION",
        f"candidate_current_sha256={candidate.current_sha256}", f"candidate_run_id={candidate.run_id}"]
    quotes = [dict(code=code, trade_date=DATE, stage_id=stage,
        qmt=dict(open=10, lastPrice=10.1, lastClose=10, high=10.2, low=9.9,
                 amount=5000000, bidVol=[100], askVol=[80]), candidate={"score": 80})
        for code in candidate.codes[:205]]
    envelope = runtime.selection.select_a_live_stage(quotes, DATE, stage, "e" * 64,
        source_status="PARTIAL_WITH_ROWS", requested_rows=216, source_evidence=evidence,
        missing_symbols=candidate.codes[205:])
    stored = runtime.store.publish(envelope, market="A_SHARE")
    writer = importlib.import_module("stage_center._runner_parts.runner_receipts")
    io = importlib.import_module("infrastructure.owned_io")
    owner = SimpleNamespace(config=SimpleNamespace(receipt_root=runtime.receipt_root,
        selection_root=runtime.store.root, backfill_run_id=None, hk_current_day_research_root=None),
        _receipt_path=lambda date, selected_stage: runtime.receipt_root / date / selected_stage / "receipt.json")
    scope = {"_deadline": SimpleNamespace(before_receipt=deepcopy, receipt_written=lambda *args: None),
        "_atomic_json": lambda path, value: io.SafeRoot(path.parent).write_bytes(path.name, canonical(value) + b"\n"),
        "SAFETY_FLAGS": runtime.selection.SAFETY_FLAGS, "SelectionStore": runtime.selection.SelectionStore}
    payload = dict(trade_date=DATE, stage_id=stage, status="PARTIAL_WITH_ROWS",
        execution_mode="RECOVERY", dispatch_mode="RECOVERY", RESEARCH_ONLY=True,
        candidate_run_id=candidate.run_id, candidate_current_sha256=candidate.current_sha256,
        markets={"A_SHARE": {**stored, "status": stored["selection_status"]}},
        input_bindings=writer._candidate_input_bindings(candidate, None, ("A_SHARE",), a_candidate_missing=False))
    def write(value=None):
        return writer._StageCenterRunner__write_receipt_body(scope, owner, deepcopy(value or payload), DATE, stage)
    return SimpleNamespace(**vars(runtime), stage=stage, candidate=candidate, a_stored=stored,
        a_payload=payload, a_write=write)


def test_a_original_input_reference_binds_216_input_to_205_quotes_and_10_results(a_runtime):
    a_runtime.a_write()
    response = a_runtime.client.get(DATE, a_runtime.stage)
    evidence = response["execution_evidence"]
    binding = evidence["input_binding_status"]["A_SHARE"]
    assert binding["status"] == "OWNER_DECLARED_INPUT_BOUND_TO_SELECTION"
    assert binding["current_bytes_sha256"] == a_runtime.candidate.current_sha256
    assert binding["run_id"] == a_runtime.candidate.run_id
    assert binding["row_count"] == 216
    assert binding["input_reread_performed"] is binding["candidate_pit_verified"] is False
    assert evidence["candidate_binding"] == binding["status"]
    assert evidence["candidate_run_id"] == binding["run_id"]
    assert evidence["candidate_current_sha256"] == binding["current_bytes_sha256"]
    assert response["markets"]["A_SHARE"]["selected_rows"] == 10
    assert evidence["selection_results"]["A_SHARE"]["source_rows"] == 205
    assert evidence["selection_results"]["A_SHARE"]["requested_rows"] == 216
    assert evidence["runtime_source_binding"]["status"] == "RUNTIME_SOURCE_IDENTITY_NOT_RECORDED"
    assert evidence["selection_source_bindings"]["A_SHARE"]["status"] == "SELECTION_SOURCE_IDENTITY_NOT_RECORDED"
    assert evidence["natural_verified"] is evidence["execution_verified"] is False


@pytest.mark.parametrize("field,value", [("current_bytes_sha256", "f" * 64),
    ("run_id", "another-input-run"), ("trade_date", "20261008"), ("row_count", 200)])
def test_a_wrong_input_declaration_cannot_bind_or_hide_existing_result(a_runtime, field, value):
    payload = deepcopy(a_runtime.a_payload)
    payload["input_bindings"]["A_SHARE"][field] = value
    a_runtime.a_write(payload)
    evidence = a_runtime.client.get(DATE, a_runtime.stage)["execution_evidence"]
    assert evidence["input_binding_status"]["A_SHARE"]["status"] == "A_INPUT_BINDING_CONFLICT"
    assert evidence["candidate_binding"] == "A_INPUT_BINDING_CONFLICT"
    assert evidence["selection_results"]["A_SHARE"]["selected_rows"] == 10
    assert evidence["natural_verified"] is False


def test_a_input_reference_without_owner_history_is_unbound_and_rows_remain(a_runtime):
    a_runtime.a_write()
    path = a_runtime.receipt_root / DATE / a_runtime.stage / "receipt.json"
    receipt = json.loads(path.read_bytes())
    receipt.pop("receipt_history")
    path.write_bytes(canonical(receipt) + b"\n")
    evidence = a_runtime.client.get(DATE, a_runtime.stage)["execution_evidence"]
    assert evidence["input_binding_status"]["A_SHARE"]["status"] == "A_INPUT_DECLARED_OWNER_OR_SELECTION_UNBOUND"
    assert evidence["candidate_binding"] == "A_INPUT_DECLARED_OWNER_OR_SELECTION_UNBOUND"
    assert evidence["selection_results"]["A_SHARE"]["selected_rows"] == 10


def test_a_forged_projected_source_markers_do_not_replace_original_selection_input(a_runtime):
    payload = deepcopy(a_runtime.a_payload)
    payload["input_bindings"]["A_SHARE"]["current_bytes_sha256"] = "f" * 64
    a_runtime.a_write(payload)
    lane = a_runtime.client.get(DATE, a_runtime.stage)["markets"]["A_SHARE"]
    lane["source_evidence"] = [entry.replace("c" * 64, "f" * 64) for entry in lane["source_evidence"]]
    evidence = a_runtime.reader.read_stage_execution(a_runtime.receipt_root, DATE, a_runtime.stage,
        {"A_SHARE": lane}, selection_store=a_runtime.store)
    assert evidence["input_binding_status"]["A_SHARE"]["status"] == "A_INPUT_BINDING_CONFLICT"
    assert evidence["selection_results"]["A_SHARE"]["selected_rows"] == 10


def test_existing_vue_shows_a_input_binding_and_separate_missing_natural_evidence(a_runtime):
    a_runtime.a_write()
    evidence = a_runtime.client.get(DATE, a_runtime.stage)["execution_evidence"]
    path = a_runtime.tmp / "a-evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False))
    script = "import {readFileSync} from 'node:fs'; import {render,primary,text} from './tests/ssr_harness.mjs'; console.log(text(primary(await render(JSON.parse(readFileSync(process.argv[1],'utf8'))))));"
    environment = dict(os.environ)
    environment.setdefault("STAGE_UI_RUNTIME", str(ROOT / "runtime_before/actual_api/apps/web"))
    result = subprocess.run(["node", "--input-type=module", "-e", script, str(path)], cwd=HERE,
        env=environment, capture_output=True, text=True, check=True)
    assert "已计算 10 只" in result.stdout
    assert "行情 205 / 216 只，缺 11 只" in result.stdout
    assert "预选输入声明与本结果、原执行记录已绑定" in result.stdout
    assert "未重新读取当前预选池，未验证历史资格" in result.stdout
    assert "自然时段验收" in result.stdout and "尚未验证" in result.stdout
