"""Independent integration fixture using the actual SelectionStore facade.

The fixed handoff lacks a complete current app. SelectionStore's original
publication/verification helpers, IO, calendar, and namespace come from the
separately pinned historical support manifest. Only candidate acquisition and
the existing-slot lookup are synthetic seams; no quote source or service runs.
"""
from __future__ import annotations

import builtins
from copy import deepcopy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


WORK = Path(__file__).resolve().parents[3]
QUOTE = WORK / "quote_fields"
WRITER = WORK / "receipt_binding"
API = WORK / "api_ui"
DATE, STAGE = "20261009", "STAGE_0925"


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def load(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=["actual_stage", "canonical"])
def runtime(request, monkeypatch, tmp_path):
    for item in json.loads((QUOTE / "SUPPORT_MANIFEST.json").read_text())["files"]:
        assert hashlib.sha256((QUOTE / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    for name in list(sys.modules):
        if name in {"stage_center", "infrastructure"} or name.startswith(("stage_center.", "infrastructure.")):
            monkeypatch.delitem(sys.modules, name)
    for name, paths in {
        "stage_center": [QUOTE / "support/stage_center"],
        "stage_center._selection_parts": [QUOTE / "before/stage_center/_selection_parts", QUOTE / "support/stage_center/_selection_parts"],
        "stage_center._runner_parts": [WRITER / "after/source" / request.param / "stage_center/_runner_parts"],
        "infrastructure": [QUOTE / "support/infrastructure"],
    }.items():
        package = ModuleType(name)
        package.__path__ = [str(path) for path in paths]
        monkeypatch.setitem(sys.modules, name, package)
    namespace = ModuleType("stage_center._runner_parts._namespace")
    namespace.read_global = lambda scope, name: scope.get(name, getattr(builtins, name, None))
    monkeypatch.setitem(sys.modules, namespace.__name__, namespace)
    selection = importlib.import_module("stage_center.selection")
    receipts = importlib.import_module("stage_center._runner_parts.runner_receipts")
    slot = importlib.import_module("stage_center._runner_parts.slot_execution")
    reader = load("stage_center.execution_evidence", API / "after/source/actual_api/stage_center/execution_evidence.py", monkeypatch)
    io_module = importlib.import_module("infrastructure.owned_io")

    store = selection.SelectionStore(tmp_path / "selection")
    rows = [{"code": f"A.{index + 1:06d}", "trade_date": DATE,
             "time": "2026-10-09 09:25:00", "price": 105 + index,
             "open_price": 105 + index, "last_price": 105 + index,
             "prev_close_price": 100, "high_price": 110 + index,
             "low_price": 100, "amount": 2_500_000}
            for index in range(12)]
    result = selection.select_a_0925_auction(
        rows, DATE, "a" * 64, source_status="READY", requested_rows=216,
        missing_symbols=(), cannot_confirm=(),
        source_evidence=("selection_contract=V3_TOP10_RECOMMENDATION",),
    )
    stored = store.publish(result, market="A_SHARE")
    # The original store itself reads and verifies latest and the full trio.
    assert store.read_verified(DATE, STAGE, "A_SHARE") == stored
    lanes = {"A_SHARE": {**deepcopy(stored), "status": stored["selection_status"]},
             "HK_CONNECT": {"status": "CANNOT_CONFIRM", "selected_rows": 0}}

    receipt_root = tmp_path / "runner_receipts"
    config = SimpleNamespace(receipt_root=receipt_root, selection_root=store.root,
                             backfill_run_id=None, candidate_acquisition_root=tmp_path / "candidate",
                             hk_d1_root=None, injected_test_mode=True, preselection_source_root=None)
    deadline_calls = []
    deadline = SimpleNamespace(before_receipt=lambda value: deepcopy(value),
                               receipt_written=lambda path, value: deadline_calls.append((path, deepcopy(value))))
    def atomic(path, value):
        io_module.SafeRoot(path.parent).write_bytes(path.name, json_bytes(value) + b"\n")
    scope = {"_deadline": deadline, "_atomic_json": atomic,
             "SAFETY_FLAGS": selection.SAFETY_FLAGS, "SelectionStore": selection.SelectionStore}
    owner = SimpleNamespace(config=config,
        _receipt_path=lambda date, stage: receipt_root / date / stage / "receipt.json")
    def write(payload, date=DATE, stage=STAGE):
        return receipts._StageCenterRunner__write_receipt_body(scope, owner, payload, date, stage)
    owner._write_receipt = write
    candidate = SimpleNamespace(trade_date=DATE, run_id="synthetic-validated-candidate",
        current_relative=f"current/{DATE}/A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3/current.json",
        current_sha256="0" * 64, artifact_sha256="1" * 64, manifest_sha256="2" * 64,
        receipt_sha256="3" * 64, artifact_bytes_sha256="4" * 64,
        manifest_bytes_sha256="5" * 64, receipt_bytes_sha256="6" * 64,
        codes=tuple(f"A.{index + 1:06d}" for index in range(216)), source_evidence=("synthetic_validated_input",))
    owner._validate_hk_auction_root_binding = lambda stage: None
    owner._existing_slot = lambda *args: ("VERIFIED", {
        "raw": {"receipt": {"bundle_id": "synthetic-existing-bundle"}},
        "selections": {"A_SHARE": deepcopy(stored)},
    })
    class InputError(ValueError):
        pass
    run_scope = {"_stage_markets_for_date": lambda *args: ("A_SHARE",),
        "_resolve_stage_market_scope": lambda *args, **kwargs: ("A_SHARE",),
        "read_candidate_input": lambda *args, **kwargs: candidate,
        "CandidateInputError": InputError, "RunnerError": InputError,
        "RawStoreError": InputError, "SelectionError": selection.SelectionError,
        "StageUniverseBinding": SimpleNamespace(ready=lambda **kwargs: SimpleNamespace(**kwargs))}
    decision = SimpleNamespace(trade_date=DATE, stage_id=STAGE, status="DUE")
    def run_noop():
        kwargs = {"historical_backfill": False, "backfill_run_id": None}
        if request.param == "canonical":
            kwargs["historical_markets"] = None
        return slot._StageCenterRunner__run_one_body(run_scope, owner, decision, **kwargs)
    def read(**kwargs):
        return reader.read_stage_execution(receipt_root, DATE, STAGE, lanes, **kwargs)
    def base_payload():
        return {"trade_date": DATE, "stage_id": STAGE, "status": "PARTIAL_WITH_ROWS",
            "dispatch_mode": "NATURAL", "due_status": "DUE", "markets": {
                "A_SHARE": deepcopy(stored), "HK_CONNECT": {"status": "CANNOT_CONFIRM", "selected_rows": 0,
                    "cannot_confirm": ["HK D1 status must be STRICT_0_2_READY"], "write_performed": False}},
            "write_performed": True}
    return SimpleNamespace(variant=request.param, selection=selection, receipts=receipts,
        reader=reader, store=store, lanes=lanes, owner=owner, scope=scope,
        root=receipt_root, write=write, read=read, base_payload=base_payload,
        run_noop=run_noop, run_scope=run_scope, candidate=candidate,
        deadline=deadline, deadline_calls=deadline_calls, tmp=tmp_path,
        io_module=io_module, input_error=InputError)
