from copy import deepcopy
import hashlib
import json
from pathlib import Path
import os
import subprocess
import importlib
import importlib.util
import shutil
import sys

import pytest

from conftest import DATE, STAGE, HERE, ROOT, SUPPORT, EXPLICIT_RUNTIME_SUPPORT, canonical


def replace_synthetic_owner_receipt(runtime, transform):
    """Craft an adverse, self-consistent declaration in this test's temp root.

    The original owner archive is preserved. This is an untrusted receipt
    fixture, not a claim that the actual writer would emit this declaration.
    """
    path = runtime.receipt_root / DATE / STAGE / "receipt.json"
    value = json.loads(path.read_bytes())
    value.pop("receipt_history")
    transform(value)
    raw = canonical(value) + b"\n"
    sha = hashlib.sha256(raw).hexdigest()
    relative = f"{DATE}/{STAGE}/attempt_evidence/recorded-{sha}/RECEIPT.json"
    archive = runtime.receipt_root / relative
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(raw)
    value["receipt_history"] = {"schema_version": "stage_center.runner.history_ref.v1",
                                "relative_path": relative, "sha256": sha}
    path.write_bytes(canonical(value) + b"\n")


def test_saved_research_result_survives_missing_execution_receipt(runtime):
    response = runtime.client.get(DATE, STAGE)
    lane = response["markets"]["HK_CONNECT"]
    summary = response["execution_evidence"]["selection_results"]["HK_CONNECT"]
    assert lane["hk_current_day_research"] == runtime.metadata
    assert lane["research_source_status"] == "VERIFIED_SELECTION_METADATA"
    assert lane["selection_mode"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert lane["RESEARCH_ONLY"] is True
    assert lane["selected_rows"] == summary["selected_rows"] == 10
    assert summary["hk_current_day_research"] == runtime.metadata
    assert summary["trade_date"] == DATE and summary["stage_id"] == STAGE
    assert summary["run_id"] == lane["run_id"] == runtime.stored["run_id"]
    assert response["execution_evidence"]["natural_verified"] is False


def test_existing_owner_trio_binds_same_research_input_and_runtime(runtime):
    runtime.write()
    response = runtime.client.get(DATE, STAGE)
    evidence = response["execution_evidence"]
    assert evidence["receipt_history_binding"] == "OWNER_HISTORY_SHA_BOUND"
    assert evidence["selection_artifact_bindings"]["HK_CONNECT"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert evidence["input_binding_status"]["HK_CONNECT"]["status"] == "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY"
    assert evidence["runtime_source_binding"]["status"] == "OWNER_HISTORY_SOURCE_IDENTITY_BOUND"
    origin = evidence["selection_source_bindings"]["HK_CONNECT"]
    assert origin["status"] == "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY"
    assert origin["invocation_matches_selection"] is True
    assert evidence["attempt_mode"] == "MANUAL_CURRENT_DAY_RESEARCH"
    assert evidence["natural_verified"] is False
    assert evidence["execution_verified"] is False
    for key in ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256"):
        assert evidence["selection_results"]["HK_CONNECT"][key] == response["markets"]["HK_CONNECT"][key]


@pytest.mark.parametrize("field,value", [("input_binding_sha256", "f" * 64), ("universe_as_of", "20261007"),
    ("captured_at", "2026-10-09T15:39:00+08:00"), ("current_connect_eligibility", "CONFIRMED")])
def test_receipt_input_disagreement_is_visible_without_hiding_saved_rows(runtime, field, value):
    payload = deepcopy(runtime.payload)
    payload["input_bindings"]["HK_CONNECT"]["research_metadata"][field] = value
    runtime.write(payload)
    response = runtime.client.get(DATE, STAGE)
    evidence = response["execution_evidence"]
    assert response["markets"]["HK_CONNECT"]["selected_rows"] == 10
    assert evidence["selection_results"]["HK_CONNECT"]["selected_rows"] == 10
    assert evidence["input_binding_status"]["HK_CONNECT"]["status"] == "RESEARCH_INPUT_BINDING_CONFLICT"
    assert evidence["natural_verified"] is False


def test_exact_run_route_reads_same_original_selection_and_preserves_research_counts(runtime, route):
    runtime.write()
    before = {str(p): p.read_bytes() for p in runtime.tmp.rglob("*") if p.is_file()}
    response = route.client.get("/api/v3/workbench/stage", params={"date": DATE, "stage": STAGE,
        "market": "HK_CONNECT", "selection_run_id": runtime.stored["run_id"], "limit": 50})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["markets"]["HK"]["display_mode"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert payload["markets"]["HK"]["selected_rows"] == payload["selected_hk_rows"] == 10
    assert payload["markets"]["HK"]["hk_current_day_research"] == runtime.metadata
    assert [row["code"] for row in payload["unified_rows"]] == [row["code"] for row in runtime.stored["rows"]]
    assert payload["execution_evidence"]["selection_results"]["HK_CONNECT"]["run_id"] == runtime.stored["run_id"]
    assert payload["RESEARCH_ONLY"] is True
    assert all(payload[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    assert {str(p): p.read_bytes() for p in runtime.tmp.rglob("*") if p.is_file()} == before


def test_exact_run_route_rejects_unknown_run_and_backfill_combination(runtime, route):
    query = {"date": DATE, "stage": STAGE, "market": "HK_CONNECT", "selection_run_id": "run-" + "f" * 24}
    result = route.client.get("/api/v3/workbench/stage", params=query)
    assert result.status_code == 404
    query["selection_run_id"] = runtime.stored["run_id"]
    query["backfill_run_id"] = "different-wrapper"
    assert route.client.get("/api/v3/workbench/stage", params=query).status_code == 422


def test_production_mode_cannot_be_inferred_from_ready_research_metadata(runtime, route):
    payload = runtime.client.get(DATE, STAGE)
    lane = payload["markets"]["HK_CONNECT"]
    lane["status"] = lane["selection_status"] = "READY"
    lane["cannot_confirm"] = []
    payload["execution_evidence"]["markets"] = {"HK_CONNECT": {"selection_binding": "BOUND_TO_VERIFIED_SELECTION"}}
    projected = route.project(payload, 50, ordinary_hk_display=True)
    assert projected["markets"]["HK"]["display_mode"] == "CURRENT_DAY_RESEARCH_ONLY"
    assert projected["selected_hk_rows"] == 10


def test_real_store_consumer_api_result_renders_same_run_in_existing_vue(runtime, route):
    runtime.write()
    response = route.client.get("/api/v3/workbench/stage", params={"date": DATE, "stage": STAGE,
        "market": "HK_CONNECT", "selection_run_id": runtime.stored["run_id"], "limit": 50})
    assert response.status_code == 200, response.text
    evidence_file = runtime.tmp / "api-evidence.json"
    evidence_file.write_text(json.dumps(response.json()["execution_evidence"], ensure_ascii=False))
    script = "import {readFileSync} from 'node:fs'; import {render,primary,text} from './tests/ssr_harness.mjs'; console.log(text(primary(await render(JSON.parse(readFileSync(process.argv[1],'utf8'))))));"
    environment = dict(os.environ)
    environment.setdefault("STAGE_UI_RUNTIME", str(ROOT / "runtime_before/actual_api/apps/web"))
    run = subprocess.run(["node", "--input-type=module", "-e", script, str(evidence_file)], cwd=HERE,
                         env=environment, capture_output=True, text=True, check=True)
    assert "已计算 10 只" in run.stdout
    assert "当日研究" in run.stdout
    assert "当前港股通资格：不能确认" in run.stdout
    assert "20261008" in run.stdout and "2026-10-09T15:38:41+08:00" in run.stdout
    assert "15:55:05" in run.stdout
    assert runtime.stored["run_id"] in run.stdout
    assert "手动当日研究" in run.stdout
    assert "自然触发（NATURAL）" not in run.stdout


def test_reader_rejects_unsafe_research_metadata_but_keeps_original_result(runtime):
    lane = runtime.client.get(DATE, STAGE)["markets"]["HK_CONNECT"]
    lane["hk_current_day_research"]["production_allowed"] = True
    evidence = runtime.reader.read_stage_execution(None, DATE, STAGE, {"HK_CONNECT": lane}, selection_store=runtime.store)
    summary = evidence["selection_results"]["HK_CONNECT"]
    assert summary["selected_rows"] == 10
    assert summary["research_source_status"] == "CANNOT_CONFIRM"
    assert summary["selection_mode"] == "CURRENT_DAY_RESEARCH_ONLY"


def test_current_invocation_source_can_differ_without_rewriting_original_selection(runtime):
    payload = deepcopy(runtime.payload)
    identity = payload["runtime_source_identity"]
    identity["files"]["stage_center/runner.py"]["sha256"] = "c" * 64
    identity["sha256"] = hashlib.sha256(canonical({k: v for k, v in identity.items() if k not in {"sha256", "status"}})).hexdigest()
    runtime.write(payload)
    evidence = runtime.client.get(DATE, STAGE)["execution_evidence"]
    assert evidence["selection_results"]["HK_CONNECT"]["runtime_source_identity"] == runtime.stored["runtime_source_identity"]
    origin = evidence["selection_source_bindings"]["HK_CONNECT"]
    assert origin["status"] == "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY"
    assert origin["invocation_matches_selection"] is False
    assert evidence["natural_verified"] is False


def test_forged_selection_origin_does_not_bind_even_when_receipt_history_is_valid(runtime):
    runtime.write()
    def forge(payload):
        payload["selection_source_identities"]["HK_CONNECT"]["files"]["stage_center/runner.py"]["sha256"] = "d" * 64
    replace_synthetic_owner_receipt(runtime, forge)
    evidence = runtime.client.get(DATE, STAGE)["execution_evidence"]
    assert evidence["selection_results"]["HK_CONNECT"]["selected_rows"] == 10
    assert evidence["selection_source_bindings"]["HK_CONNECT"]["status"] == "SELECTION_SOURCE_IDENTITY_CONFLICT"


def test_research_metadata_must_match_original_store_even_if_projected_lane_and_receipt_agree(runtime):
    payload = deepcopy(runtime.payload)
    payload["input_bindings"]["HK_CONNECT"]["research_metadata"]["input_binding_sha256"] = "f" * 64
    payload["input_bindings"]["HK_CONNECT"]["input_binding_sha256"] = "f" * 64
    runtime.write(payload)
    lane = runtime.client.get(DATE, STAGE)["markets"]["HK_CONNECT"]
    lane["hk_current_day_research"] = deepcopy(payload["input_bindings"]["HK_CONNECT"]["research_metadata"])
    lane["source_evidence"] = ["hk_current_day_research=" + canonical(lane["hk_current_day_research"]).decode()]
    result = runtime.reader.read_stage_execution(runtime.receipt_root, DATE, STAGE, {"HK_CONNECT": lane}, selection_store=runtime.store)
    assert result["selection_artifact_bindings"]["HK_CONNECT"]["status"] == "SELECTION_TRIO_CONFLICT"
    assert result["input_binding_status"]["HK_CONNECT"]["status"] != "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY"


def test_afternoon_capture_cannot_be_relabelled_to_a_morning_stage_by_changing_metadata_cutoff(runtime):
    lane = runtime.client.get(DATE, STAGE)["markets"]["HK_CONNECT"]
    lane["stage_id"] = "STAGE_0930_0935"
    metadata = lane["hk_current_day_research"]
    metadata["stage_id"] = lane["stage_id"]
    metadata["cutoff_at"] = "15:55:05"
    lane["source_evidence"] = ["hk_current_day_research=" + canonical(metadata).decode()]
    projected = runtime.reader.project_hk_current_day_research(lane)
    assert projected["research_source_status"] == "CANNOT_CONFIRM"
    assert projected["selection_mode"] == "CURRENT_DAY_RESEARCH_ONLY"


def test_strict_hk_projection_is_unchanged_when_current_day_mode_is_absent(runtime, route):
    payload = runtime.client.get(DATE, STAGE)
    lane = payload["markets"]["HK_CONNECT"]
    for key in ("hk_current_day_research", "selection_mode", "research_source_status", "research_source_restrictions"):
        lane.pop(key, None)
    lane["source_evidence"] = []
    lane["cannot_confirm"] = []
    lane["status"] = lane["selection_status"] = "READY"
    for row in lane["rows"]:
        row["formal_eligible"] = True
    payload["execution_evidence"]["markets"] = {"HK_CONNECT": {"selection_binding": "BOUND_TO_VERIFIED_SELECTION"}}
    projected = route.project(payload, 50, ordinary_hk_display=True)
    assert projected["markets"]["HK"]["display_mode"] == "FORMAL"
    assert projected["selected_hk_rows"] == 10


def test_full_candidate_runner_four_real_files_to_original_algorithm_api_and_vue(runtime, route, monkeypatch):
    """Only four input documents and the external quote provider are synthetic.

    Executes final runner/configuration, current research admission, original
    raw/selection stores, four-lane selector, final owner writer, current
    consumer, existing HTTP route source and existing Vue SFC in one chain.
    The supplied archived raw facade/helper mismatch uses the explicitly
    documented False-only test adapter; no temporal checks are disabled.
    """
    from datetime import datetime
    app_root = runtime.tmp / "complete_candidate"
    shutil.copytree(SUPPORT, app_root)
    # An explicitly supplied complete candidate is authoritative, including
    # its actual/canonical variant. Never replace it with actual Stage files.
    overlays = [] if EXPLICIT_RUNTIME_SUPPORT else [ROOT / "components/hk/after",
        ROOT / "components/collectors/after", ROOT / "components/receipt/after/actual_stage"]
    for overlay in (*overlays, HERE / "after"):
        shutil.copytree(overlay, app_root, dirs_exist_ok=True)
    if EXPLICIT_RUNTIME_SUPPORT:
        for relative in ("stage_center/runner.py", "stage_center/hk_current_day_research.py",
                         "stage_center/_runner_parts/runner_receipts.py"):
            assert (app_root / relative).read_bytes() == (SUPPORT / relative).read_bytes()
    for name in list(sys.modules):
        if name in {"stage_center", "infrastructure"} or name.startswith(("stage_center.", "infrastructure.")):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(app_root))
    research = importlib.import_module("stage_center.hk_current_day_research")
    inputs = runtime.tmp / "synthetic-input-files"
    inputs.mkdir()
    codes = [f"HK.{n:05d}" for n in range(1, 696)]
    declaration = deepcopy(research.CAPTURE_20261009)
    security_rows = [{"code": code, "name": f"Synthetic HK {n}", "outstanding_shares": 1_000_000 + n,
        "circular_market_val": 2_000_000 + n, "listing_date": "2020-01-01", "lot_size": 100,
        "stock_owner": "", "stock_child_type": "EQ", "sec_status": "NORMAL"} for n, code in enumerate(codes)]
    for key, data in {"snapshot": security_rows, "receipt": {"synthetic": True},
                      "reference_codes": codes, "final_receipt": {"synthetic": True}}.items():
        path = inputs / declaration["source_files"][key]["file"]
        path.write_bytes(canonical(data))
        declaration["source_files"][key]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(research, "CAPTURE_20261009", declaration)
    if os.environ.get("V4_RAW_SIGNATURE_SUPPORT", "strict_false") == "strict_false":
        support_file = ROOT / "components/hk/tests/raw_store_test_support.py"
        spec = importlib.util.spec_from_file_location("api_test_raw_signature_support", support_file)
        support = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(support)
        support.install_strict_false_keyword_adapter(monkeypatch)
    from stage_center.acquisition import SourceResult
    from stage_center.runner import build_production_config, StageCenterRunner
    from stage_center.consumer import StageSelectionConsumer
    calls = []
    def provider(plan, market):
        calls.append((plan.trade_date, plan.stage_id, market, len(plan.codes_for(market))))
        assert plan.universe_bindings[market].role == "CURRENT_DAY_RESEARCH_ONLY"
        observed = tuple(codes[:-11])
        rows = tuple({"batch_index": index, "code": code, "name": code,
            "update_time": "2026-10-09 15:55:00", "last_price": 10 + index / 1000,
            "open_price": 10, "high_price": 12, "low_price": 9, "prev_close_price": 9.5,
            "turnover": 150_000_000 + index, "volume": 100_000 + index,
            "bid_price": "", "ask_price": "", "bid_vol": "", "ask_vol": "",
            "window_start": "2026-10-09 15:45:00", "window_end": "2026-10-09 15:55:00",
            "bar_count": 11, "temporal_cutoff_safe": True} for index, code in enumerate(observed, 1))
        return SourceResult("pytdx_exhq", "PARTIAL_WITH_ROWS", rows=rows, requested_rows=695,
            missing_symbols=tuple(codes[-11:]), cannot_confirm=("SYNTHETIC_PROVIDER_11_SYMBOLS_MISSING",),
            source_evidence=("synthetic_provider=true", "quote_clock=EXHQ_BAR_UPDATE_TIME"))
    outputs = runtime.tmp / "full-output"
    config = build_production_config(candidate_acquisition_root=runtime.tmp / "no-a",
        raw_root=outputs / "raw", selection_root=outputs / "selection", receipt_root=outputs / "receipts",
        hk_current_day_research_root=inputs, shared_data_root=runtime.tmp / "shared", python_path=Path(sys.executable))
    owner = StageCenterRunner(config, collectors={"HK_CONNECT": provider})
    receipt = owner.tick(DATE, datetime.fromisoformat("2026-10-09T17:05:26+08:00"), stage_id=STAGE)
    assert calls == [(DATE, STAGE, "HK_CONNECT", 695)]
    assert receipt["write_performed"] is True, receipt
    selected = receipt["markets"]["HK_CONNECT"]
    assert selected["selected_rows"] == 10 and selected["source_rows"] == 684
    consumer = StageSelectionConsumer(config.selection_root, execution_receipt_root=config.receipt_root)
    route.bind_consumer(consumer)
    response = route.client.get("/api/v3/workbench/stage", params={"date": DATE, "stage": STAGE,
        "market": "HK_CONNECT", "selection_run_id": selected["run_id"], "limit": 50})
    assert response.status_code == 200, response.text
    payload = response.json()
    evidence = payload["execution_evidence"]
    assert payload["selected_hk_rows"] == 10
    assert evidence["selection_artifact_bindings"]["HK_CONNECT"]["status"] == "BOUND_TO_VERIFIED_SELECTION_TRIO"
    assert evidence["input_binding_status"]["HK_CONNECT"]["status"] == "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY"
    assert evidence["selection_source_bindings"]["HK_CONNECT"]["status"] == "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY"
    assert evidence["attempt_mode"] == "MANUAL_CURRENT_DAY_RESEARCH"
    assert evidence["natural_verified"] is False
    assert payload["markets"]["HK"]["hk_current_day_research"] == selected["hk_current_day_research"]
    assert payload["markets"]["HK"]["raw_artifact_sha256"] == selected["raw_artifact_sha256"]
    assert [row["code"] for row in payload["unified_rows"]] == [row["code"] for row in selected["rows"]]
    evidence_file = runtime.tmp / "full-api-evidence.json"
    evidence_file.write_bytes(canonical(evidence))
    script = "import {readFileSync} from 'node:fs'; import {render,primary,text} from './tests/ssr_harness.mjs'; console.log(text(primary(await render(JSON.parse(readFileSync(process.argv[1],'utf8'))))));"
    run = subprocess.run(["node", "--input-type=module", "-e", script, str(evidence_file)], cwd=HERE,
                         env=dict(os.environ), capture_output=True, text=True, check=True)
    assert "已计算 10 只" in run.stdout and "行情 684 / 695 只，缺 11 只" in run.stdout
    assert "2026-10-09 15:55:00" in run.stdout
    assert "手动当日研究" in run.stdout and selected["run_id"] in run.stdout
