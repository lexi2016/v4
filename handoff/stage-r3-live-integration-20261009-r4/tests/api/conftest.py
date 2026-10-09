"""Offline integration fixtures: original R3 stores, receipt writer, and exact API route.

The synthetic manifest is explicitly substituted for the one approved production
manifest in tests. There is no fixture override in the delivered reader or CLI.
Only FastAPI's exception/query wrappers are represented locally; these tests do
not claim HTTP startup, a current Mac process, or real market acquisition.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

WORK = Path(__file__).resolve().parents[1]
R3 = Path(os.environ.get("R3_PACKAGE", WORK.parents[2] / "stage-r2-mac-adaptation-20261009-r3"))
AFTER = Path(os.environ.get("R4_API_AFTER_ROOT", WORK / "after"))
BEFORE = Path(os.environ.get("R4_API_BEFORE_ROOT", WORK / "before"))
TOOLS = Path(os.environ.get("R4_API_TOOL_ROOT", WORK / "tools"))
DAY, STAGE, BACKFILL = "20261009", "STAGE_0930_0935", "85e29661ecd848fe9b8344ea59279e86"
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def load(name, path, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class RouteHTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def route_source(case, *, phase="after", research_reader=None):
    """Compile the exact delivered route and unchanged projection helpers.

    Full application dependencies are unavailable in this Chat workspace; no
    networking wrappers, services, or alternative API projections are invented.
    """
    path = (BEFORE if phase == "before" else AFTER) / "apps/api/v35_api/app.py"
    module = ast.parse(path.read_text())
    app = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "create_app")
    names = {"_stage_projection_status", "_hk_display_mode", "project_shared_selection",
             "_quarantine_known_hk_auction_pool_mismatch", "_read_exact_target_hk_override",
             "_read_r8_exact_target_hk_override", "_read_r9_exact_target_hk_override", "stage_workbench"}
    top = []
    for node in module.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.For)):
            top.append(deepcopy(node))
        elif isinstance(node, ast.FunctionDef) and node.name != "create_app":
            top.append(deepcopy(node))
    for node in app.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            copied = deepcopy(node)
            copied.decorator_list = []
            top.append(copied)
    top.insert(0, ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0))
    namespace = {"__file__": str(path), "Path": Path, "datetime": datetime,
                 "hashlib": hashlib, "inspect": inspect, "Any": Any, "Mapping": Mapping,
                 "HTTPException": RouteHTTPException, "Query": lambda default=None, **kwargs: default,
                 "TRADING_SAFETY_FLAGS": {key: False for key in FLAGS if key != "RESEARCH_ONLY"},
                 "FROZEN_STAGE_IDS": tuple(stage.stage_id for stage in case.consumer.EIGHT_STAGES),
                 "STAGE_DEFINITIONS": {}, "StageSelectionConsumer": case.consumer.StageSelectionConsumer,
                 "configured_selection_root": case.history.root,
                 "shared_selection_consumer": case.consumer.StageSelectionConsumer(case.history.root),
                 "approved_research_reader": research_reader,
                 "_catalog": lambda: {"default_date": DAY, "system_date": DAY},
                 "stage_runner": None}
    if case.binding_module is not None:
        namespace["ResearchReadError"] = case.binding_module.ResearchReadError
    exec(compile(ast.fix_missing_locations(ast.Module(body=top, type_ignores=[])), str(path), "exec"), namespace)
    return namespace


@pytest.fixture
def case(monkeypatch, tmp_path):
    helper = load("_r4_original_api_fixture", R3 / "checks/api/tests/conftest.py", monkeypatch)
    runtime = helper.runtime.__wrapped__(monkeypatch, tmp_path)
    api_root = tmp_path / "api_source"
    shutil.copytree(AFTER, api_root)
    load("stage_center.execution_evidence", api_root / "stage_center/execution_evidence.py", monkeypatch)
    consumer = load("stage_center.consumer", api_root / "stage_center/consumer.py", monkeypatch)
    history = runtime.store
    # Nineteen ordinary dates have real immutable selection trios.
    ordinary = {}
    for offset in range(1, 20):
        day = (datetime(2026, 2, 1) - timedelta(days=offset)).strftime("%Y%m%d")
        ordinary[day] = {market: runtime.publish(market, date=day, status="PARTIAL_WITH_ROWS",
                                                source_evidence=[], target_store=history)
                         for market in ("A_SHARE", "HK_CONNECT")}
    output = tmp_path / "immutable_candidate/research_0935"
    selection = runtime.selection.SelectionStore(output / "selection/backfill" / BACKFILL)
    receipts = output / "receipts/backfill" / BACKFILL
    raw_root = output / "raw/backfill" / BACKFILL
    raw_root.mkdir(parents=True)
    seeds = runtime.selection.SelectionStore(tmp_path / "fixture_seed_store")
    selected = {}
    for market in ("A_SHARE", "HK_CONNECT"):
        envelope = runtime.publish(market, status="PARTIAL_WITH_ROWS", target_store=seeds,
                                   requested_rows=216 if market == "A_SHARE" else 695,
                                   source_rows=206 if market == "A_SHARE" else 695)
        # The original production runner's immutable envelopes carry the
        # three false safety flags; RESEARCH_ONLY lives on its owner receipt.
        # Match that existing contract instead of inventing an extra field.
        envelope.pop("RESEARCH_ONLY", None)
        selected[market] = selection.publish(envelope, market=market)
    body = {"trade_date": DAY, "stage_id": STAGE, "status": "PARTIAL_WITH_ROWS",
            "dispatch_mode": "RECOVERY", "due_status": "HISTORICAL_BACKFILL",
            "execution_origin": "CURRENT_DAY_RESEARCH_REPLAY", "natural_verified": False,
            "markets": selected, "write_performed": True, **FLAGS}
    owner_config = SimpleNamespace(selection_root=selection.root, receipt_root=receipts,
                                   raw_root=raw_root, backfill_run_id=BACKFILL)
    owner = SimpleNamespace(config=owner_config,
                            _receipt_path=lambda day, stage: receipts / day / stage / "receipt.json")
    deadline = SimpleNamespace(before_receipt=lambda value: deepcopy(value), receipt_written=lambda *args: None)
    receipt = runtime.writer._StageCenterRunner__write_receipt_body(
        {"_deadline": deadline, "_atomic_json": write_json,
         "SAFETY_FLAGS": runtime.selection.SAFETY_FLAGS, "SelectionStore": runtime.selection.SelectionStore},
        owner, body, DAY, STAGE)
    write_json(output / "result.json", receipt)
    source_map_path = R3 / "SOURCE_MAP.json"
    source_map = json.loads(source_map_path.read_text())
    stage_app = tmp_path / "immutable_candidate/stage_app"
    stage_sources = []
    for row in source_map["files"]:
        if row["group"] != "stage":
            continue
        target = stage_app / row["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(R3 / row["after_path"], target)
        stage_sources.append({"relative_path": row["relative_path"], "actual_path": str(target),
                              "package_after_path": str(R3 / row["after_path"]), "sha256": row["after_sha256"]})
    candidate_manifest = stage_app / "CANARY_SOURCE_MANIFEST.json"
    write_json(candidate_manifest, {"fixture_only": True, "source_map_sha256": digest(source_map_path)})
    owner_receipt = receipts / DAY / STAGE / "receipt.json"
    owner_history = receipts / receipt["receipt_history"]["relative_path"]
    manifest = {"schema_version": "V4_CURRENT_DAY_RESEARCH_CANARY_RUN_V1", "status": "RESEARCH_ROWS_WRITTEN",
                "trade_date": DAY, "stage_id": STAGE, "executed": True, "execute_requested": True,
                "input_bytes_unchanged": True, "manual_replay": True, "historical_backfill": True,
                "natural_verified": False, "execution_origin": "CURRENT_DAY_RESEARCH_REPLAY", "errors": [],
                "package": str(R3), "stage_app": str(stage_app), "source_map_sha256": digest(source_map_path),
                "candidate_source_manifest_sha256": digest(candidate_manifest), "stage_sources": stage_sources,
                "owner_receipt_sha256": digest(owner_receipt), "owner_history_sha256": digest(owner_history),
                "selection_run_id": selected["HK_CONNECT"]["run_id"],
                "selected_rows": {market: 10 for market in selected},
                "output_paths": {"run_manifest": str(output / "run_manifest.json"),
                                 "result": str(output / "result.json"), "raw_root": str(raw_root),
                                 "selection_root": str(selection.root), "receipt_root": str(receipts),
                                 "owner_receipt": str(owner_receipt), "owner_history_receipt": str(owner_history)},
                **FLAGS}
    manifest_path = output / "run_manifest.json"
    write_json(manifest_path, manifest)
    binding_module = None
    module_path = api_root / "stage_center/research_read_binding.py"
    if module_path.is_file():
        binding_module = load("stage_center.research_read_binding", module_path, monkeypatch)
        approved = deepcopy(binding_module.APPROVED_RESEARCH_RUN)
        approved.update(run_manifest_sha256=digest(manifest_path),
                        candidate_source_manifest_sha256=digest(candidate_manifest),
                        selection_run_ids={market: lane["run_id"] for market, lane in selected.items()})
        monkeypatch.setattr(binding_module, "APPROVED_RESEARCH_RUN", approved)
    result = SimpleNamespace(root=tmp_path, runtime=runtime, history=history, ordinary=ordinary,
                             selection=selection, receipts=receipts, owner=receipt, manifest=manifest,
                             manifest_path=manifest_path, consumer=consumer, selected=selected,
                             binding_module=binding_module, module_path=module_path, output=output,
                             api_root=api_root)
    return result


def prepare_case(case):
    if case.binding_module is None:
        # The RED phase executes the actual unextended API source against the
        # real ordinary store; it cannot reach the separate candidate namespace.
        return None, None
    document = case.binding_module.build_research_read_binding(
        manifest_path=case.manifest_path, history_root=case.history.root,
        api_after_root=case.api_root)
    path = case.root / "reviewed_release/stage_center/approved_research_read.json"
    write_json(path, document)
    path.with_suffix(".sha256").write_text(digest(path) + "\n", encoding="ascii")
    reader = case.binding_module.ApprovedResearchReadBinding(
        binding_path=path, history_root=case.history.root,
        api_root=case.api_root, expected_reader_sha256=digest(case.module_path),
        a_name_pool_root=None)
    return reader, path
