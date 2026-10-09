"""Real SelectionStore/owner/consumer + exact existing API route and Vue fixtures.

All market/security inputs below are synthetic. The route fixture executes the
unaltered AST bodies of the existing app's route and projection helpers inside
FastAPI; it does not claim that every unrelated router or the Mac service ran.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Mapping

import pytest

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
PHASE = os.environ.get("STAGE_API_PHASE", "after")
APP = HERE / PHASE
SUPPORT = Path(os.environ.get("V4_API_TEST_RUNTIME", str(ROOT / "runtime_after/actual_stage")))
EXPLICIT_RUNTIME_SUPPORT = bool(os.environ.get("V4_API_TEST_RUNTIME"))
DATE, STAGE = "20261009", "STAGE_1545_1555"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def research_metadata():
    files = {key: {"file": name, "sha256": digit * 64} for key, name, digit in (
        ("snapshot", "snapshot_rows_projected.json", "1"),
        ("receipt", "receipt.json", "2"),
        ("reference_codes", "reference_codes_20261008.json", "3"),
        ("final_receipt", "FINAL_RECEIPT.json", "4"),
    )}
    return {
        "input_mode": "CURRENT_DAY_RESEARCH_ONLY", "trade_date": DATE, "stage_id": STAGE,
        "universe_as_of": "20261008", "captured_at": "2026-10-09T15:38:41+08:00",
        "cutoff_at": "15:55:05", "stale_universe": True,
        "current_connect_eligibility": "CANNOT_CONFIRM", "RESEARCH_ONLY": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
        "input_binding_sha256": "5" * 64, "source_files": files,
    }


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    for name in list(sys.modules):
        if name in {"stage_center", "infrastructure"} or name.startswith(("stage_center.", "infrastructure.")):
            monkeypatch.delitem(sys.modules, name)
    runner_paths = [SUPPORT / "stage_center/_runner_parts", HERE / "references/namespace"]
    if not EXPLICIT_RUNTIME_SUPPORT:
        runner_paths.insert(0, ROOT / "components/receipt/after/actual_stage/stage_center/_runner_parts")
    for name, paths in {
        "stage_center": [APP / "stage_center", SUPPORT / "stage_center"],
        "stage_center._selection_parts": [SUPPORT / "stage_center/_selection_parts", HERE / "references/namespace"],
        "stage_center._runner_parts": runner_paths,
        "infrastructure": [SUPPORT / "infrastructure"],
    }.items():
        package = ModuleType(name)
        package.__path__ = [str(path) for path in paths]
        monkeypatch.setitem(sys.modules, name, package)
    selection = importlib.import_module("stage_center.selection")
    consumer = importlib.import_module("stage_center.consumer")
    reader = importlib.import_module("stage_center.execution_evidence")
    writer = importlib.import_module("stage_center._runner_parts.runner_receipts")
    if EXPLICIT_RUNTIME_SUPPORT:
        assert Path(writer.__file__).resolve().is_relative_to(SUPPORT.resolve())
    io = importlib.import_module("infrastructure.owned_io")
    store = selection.SelectionStore(tmp_path / "stage/selection")
    receipt_root = tmp_path / "stage/receipts"
    meta = research_metadata()
    source_body = {"schema_version": "stage_center.runtime_source_identity.v1", "owner": "STAGE_RUNNER",
        "scope": "SOURCE_FILES_AT_RUNNER_ENTRY_NOT_PROCESS_ATTESTATION", "missing_files": [],
        "files": {"stage_center/runner.py": {"sha256": "b" * 64, "bytes": 123}}}
    source_identity = {**source_body, "sha256": hashlib.sha256(canonical(source_body)).hexdigest(), "status": "RECORDED"}
    quote_rows = [dict(
        code=f"HK.{index + 1:05d}", name=f"Synthetic {index + 1}",
        candidate_lanes=["LIVE_HKCONNECT_GAINER"],
        platform_circular_market_cap_hkd_yi=80.0,
        offer_float_market_cap_hkd_yi=15.0, pct_chg=4.0 + index / 10,
        volume_ratio=1.5, turnover_hkd_yi=0.2, turnover_rate=3.0,
        stage_id=STAGE, source_last_bar_time="2026-10-09T15:55:00+08:00",
    ) for index in range(12)]
    result = selection.select_hk_four_lane(
        quote_rows, DATE, STAGE, "a" * 64, source_status="PARTIAL_WITH_ROWS",
        requested_rows=695, source_evidence=(
            "selection_contract=V3_TOP10_RECOMMENDATION",
            "hk_current_day_research=" + canonical(meta).decode(),
        ), cannot_confirm=("CURRENT_CONNECT_ELIGIBILITY_CANNOT_CONFIRM",),
    )
    result["hk_current_day_research"] = deepcopy(meta)
    result["RESEARCH_ONLY"] = True
    result["runtime_source_identity"] = deepcopy(source_identity)
    stored = store.publish(result, market="HK_CONNECT")
    assert store.read_verified(DATE, STAGE, "HK_CONNECT") == stored

    def atomic(path, value):
        io.SafeRoot(path.parent).write_bytes(path.name, canonical(value) + b"\n")
    owner = SimpleNamespace(config=SimpleNamespace(
        receipt_root=receipt_root, selection_root=store.root, backfill_run_id=None,
        candidate_acquisition_root=tmp_path / "candidate", hk_d1_root=None,
        injected_test_mode=True, preselection_source_root=None,
        hk_current_day_research_root=tmp_path / "synthetic-security-input",
    ), _receipt_path=lambda date, stage: receipt_root / date / stage / "receipt.json")
    scope = {"_deadline": SimpleNamespace(before_receipt=deepcopy, receipt_written=lambda *args: None),
             "_atomic_json": atomic, "SAFETY_FLAGS": selection.SAFETY_FLAGS,
             "SelectionStore": selection.SelectionStore}
    payload = {
        "trade_date": DATE, "stage_id": STAGE, "status": "PARTIAL_WITH_ROWS",
        "dispatch_mode": "MANUAL_CURRENT_DAY_RESEARCH", "execution_mode": "MANUAL_CURRENT_DAY_RESEARCH",
        "due_status": "MANUAL_CURRENT_DAY_RESEARCH", "RESEARCH_ONLY": True,
        "markets": {"HK_CONNECT": {**deepcopy(stored), "status": stored["selection_status"]}},
        "input_bindings": {"HK_CONNECT": {"role": "CURRENT_DAY_RESEARCH_ONLY",
            "status": "CURRENT_DAY_RESEARCH_ONLY", "research_metadata": deepcopy(meta),
            "input_binding_sha256": meta["input_binding_sha256"], "source_files": meta["source_files"]}},
        "runtime_source_identity": source_identity, "write_performed": True,
        "selection_source_identities": {"HK_CONNECT": deepcopy(source_identity)},
    }
    def write(value=None):
        return writer._StageCenterRunner__write_receipt_body(scope, owner, deepcopy(value or payload), DATE, STAGE)
    client = consumer.StageSelectionConsumer(store.root, execution_receipt_root=receipt_root)
    return SimpleNamespace(selection=selection, reader=reader, consumer=consumer, client=client,
        store=store, stored=stored, metadata=meta, payload=payload, write=write,
        receipt_root=receipt_root, tmp=tmp_path)


@pytest.fixture
def route(runtime):
    from fastapi import FastAPI, HTTPException, Query
    from fastapi.testclient import TestClient
    app = FastAPI()
    tree = ast.parse((APP / "apps/api/v35_api/app.py").read_text())
    create = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    names = {"_stage_projection_status", "_hk_display_mode", "project_shared_selection", "stage_workbench"}
    bodies = [node for node in create.body if isinstance(node, ast.FunctionDef) and node.name in names]
    strict = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_strict_date")
    import datetime
    namespace = dict(app=app, Query=Query, HTTPException=HTTPException, Any=Any, Mapping=Mapping,
        datetime=datetime.datetime, shared_selection_consumer=runtime.client,
        configured_selection_root=runtime.store.root, FROZEN_STAGE_IDS=(STAGE,),
        STAGE_DEFINITIONS={STAGE: {"label": "Hong Kong close", "window": "15:45–15:55"}},
        _catalog=lambda: {"default_date": DATE, "system_date": DATE})
    code = compile(ast.fix_missing_locations(ast.Module(body=[strict, *bodies], type_ignores=[])),
                   str(APP / "apps/api/v35_api/app.py"), "exec")
    exec(code, namespace)
    def bind_consumer(client):
        namespace["shared_selection_consumer"] = client
        namespace["configured_selection_root"] = client.store.root
    return SimpleNamespace(client=TestClient(app), project=namespace["project_shared_selection"], bind_consumer=bind_consumer)
