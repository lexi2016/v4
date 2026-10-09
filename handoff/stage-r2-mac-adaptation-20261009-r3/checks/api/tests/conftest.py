"""Execute real SelectionStore and full consumer using pinned historical helpers.

The only unused import seam is PreselectionPoolStore: fixtures supply names and
never request a name overlay. No source service, quote collector or app runs.
"""
from copy import deepcopy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
PHASE = os.environ.get("STAGE_API_PHASE", "after")
DATE, STAGE = "20261009", "STAGE_0930_0935"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def source_contract(**changes):
    value = dict(schema_version="HK_CURRENT_DAY_RESEARCH_V1", market="HK_CONNECT",
                 mode="CURRENT_DAY_RESEARCH_ONLY", trade_date=DATE,
                 universe_as_of="20261008", captured_at="2026-10-09T15:38:41+08:00",
                 stale_universe=True, hk_connect_membership_status="CANNOT_CONFIRM",
                 formal_d1_eligible=False, source_sha256="c" * 64)
    return {**value, **changes}


def source_marker(**changes):
    return "research_source=" + canonical(source_contract(**changes)).decode()


def load(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    for name in list(sys.modules):
        if name in {"stage_center", "infrastructure"} or name.startswith(("stage_center.", "infrastructure.")):
            monkeypatch.delitem(sys.modules, name)
    for name, paths in {
        "stage_center": [ROOT / "support/stage_center"],
        "stage_center._selection_parts": [ROOT / "support/stage_center/_selection_parts"],
        "stage_center._runner_parts": [],
        "infrastructure": [ROOT / "support/infrastructure"],
    }.items():
        package = ModuleType(name)
        package.__path__ = [str(path) for path in paths]
        monkeypatch.setitem(sys.modules, name, package)
    selection = importlib.import_module("stage_center.selection")
    namespace = importlib.import_module("stage_center._selection_parts._namespace")
    monkeypatch.setitem(sys.modules, "stage_center._runner_parts._namespace", namespace)
    unused = ModuleType("infrastructure.preselection_pool_store")
    class UnusedNameStore:
        def __init__(self, *args, **kwargs):
            raise AssertionError("fixture must not exercise unprovided name authority")
    unused.PreselectionPoolStore = UnusedNameStore
    monkeypatch.setitem(sys.modules, unused.__name__, unused)
    reader = load("stage_center.execution_evidence", ROOT / PHASE / "source/actual_api/stage_center/execution_evidence.py", monkeypatch)
    consumer = load("stage_center.consumer", ROOT / PHASE / "conditional_api/stage_center/consumer.py", monkeypatch)
    writer = load("stage_center._runner_parts.runner_receipts", ROOT / "support/runner_receipts.py", monkeypatch)
    io = importlib.import_module("infrastructure.owned_io")
    store = selection.SelectionStore(tmp_path / "stage/selection")
    receipts = tmp_path / "stage/receipts"

    def publish(market="HK_CONNECT", *, status="CANNOT_CONFIRM", stage=STAGE,
                date=DATE, source_rows=206, requested_rows=216, source_evidence=None, count=10, target_store=None):
        rows = [{"code": f"{'A' if market == 'A_SHARE' else 'HK'}.{i + 1:0{6 if market == 'A_SHARE' else 5}d}",
                 "name": f"研究股票{i+1}", "rank": i + 1, "score": 95 - i,
                 "source_mode": "PYTDX_MINUTE", "trade_date": date,
                 "stage_id": stage} for i in range(count)]
        evidence = [source_marker()] if source_evidence is None and market == "HK_CONNECT" else (source_evidence or [])
        value = selection._selection_envelope(
            trade_date=date, stage_id=stage, market=market, raw_artifact_sha256="a" * 64,
            source_status="CANNOT_CONFIRM" if status == "CANNOT_CONFIRM" else "PARTIAL_WITH_ROWS",
            input_rows=source_rows, rows=rows, requested_rows=requested_rows,
            missing_symbols=(), cannot_confirm=("RESEARCH_SOURCE_LIMITATION",) if status == "CANNOT_CONFIRM" else (),
            source_evidence=evidence)
        # A verified historical envelope may be uncertain while retaining
        # calculated rows. The original real store permits this valid status.
        value["selection_status"] = status
        value["RESEARCH_ONLY"] = True
        destination=store if target_store is None else target_store
        saved = destination.publish(value, market=market)
        assert destination.read_verified(date, stage, market) == saved
        return saved

    def get(*, date=DATE, stage=STAGE, markets=("HK_CONNECT",), allow_backfill=False):
        return consumer.StageSelectionConsumer(store.root).get(date, stage, markets=markets, allow_backfill=allow_backfill)

    def write(envelopes, **changes):
        body = dict(trade_date=DATE, stage_id=STAGE, status="CANNOT_CONFIRM",
                    dispatch_mode="RECOVERY", due_status="LATE_CATCHUP_REPLAY",
                    RESEARCH_ONLY=True, markets=deepcopy(envelopes), write_performed=True)
        body.update(changes)
        config = SimpleNamespace(selection_root=store.root, receipt_root=receipts, backfill_run_id=None)
        owner = SimpleNamespace(config=config,
             _receipt_path=lambda date, stage: receipts / date / stage / "receipt.json")
        deadline = SimpleNamespace(before_receipt=lambda payload: deepcopy(payload), receipt_written=lambda *args: None)
        def atomic(path, payload):
            io.SafeRoot(path.parent).write_bytes(path.name, canonical(payload) + b"\n")
        return writer._StageCenterRunner__write_receipt_body(
            {"_deadline": deadline, "_atomic_json": atomic,
             "SAFETY_FLAGS": selection.SAFETY_FLAGS, "SelectionStore": selection.SelectionStore},
            owner, body, DATE, STAGE)

    return SimpleNamespace(root=tmp_path, selection=selection, reader=reader,
        consumer=consumer, writer=writer, store=store, receipts=receipts,
        publish=publish, get=get, write=write)
