"""Frozen UI/API regressions; no producers or business-data mutation."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from domains._preselection_parts.source_validation import project_a_display_names
from domains.task_status import build_task_status
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger, _ledger_digest
from stage_center.consumer import StageSelectionConsumer
from upstreams.v3_shared_data.shared_data.a_share_security_master import (
    acquire_current_display_names, load_current_display_names, publish_current_display_names,
)
from upstreams.v3_shared_data.shared_data.store import StoreError
from v4.manager_workbench.display import _summary


NAMES = {"000995.SZ": "皇台酒业", "600048.SH": "保利发展", "920575.BJ": "*ST康乐"}


class QuoteFixture:
    def get_security_count(self, market):
        return 1

    def get_security_list(self, market, offset):
        return [{"code": code[:6], "name": name} for code, name in NAMES.items()
                if code.endswith({0: ".SZ", 1: ".SH", 2: ".BJ"}[market])]


def registry(tmp_path):
    observation = acquire_current_display_names(tmp_path / "evidence", observation_date="20261027",
        requested_codes=list(NAMES), api=QuoteFixture())
    publish_current_display_names(tmp_path, observation)
    return observation


def test_display_registry_is_separate_exact_date_verified_and_immutable(tmp_path):
    selector_latest = tmp_path / "assets/a_share_security_master/latest.json"
    selector_latest.parent.mkdir(parents=True)
    selector_latest.write_text("original selector publication")
    observation = registry(tmp_path)
    mapping, manifest = load_current_display_names(tmp_path, "20261027")
    assert {row["ts_code"]: row["name"] for row in mapping.values()} == NAMES
    assert manifest["selector_certified"] is manifest["pit_certified"] is False
    assert selector_latest.read_text() == "original selector publication"
    replay = dict(observation, captured_at="2026-10-27T23:59:00+08:00")
    reused = publish_current_display_names(tmp_path, replay)
    assert reused["run_id"] == manifest["run_id"]
    with pytest.raises(StoreError):
        load_current_display_names(tmp_path, "20261026")
    forged = json.loads(json.dumps(observation))
    forged["rows"][0]["name"] = "伪造名称"
    with pytest.raises(StoreError, match="does not match captured response"):
        publish_current_display_names(tmp_path, forged)
    evidence = Path(observation["rows"][0]["evidence_path"])
    evidence.write_text("tampered")
    with pytest.raises(StoreError, match="SHA mismatch"):
        load_current_display_names(tmp_path, "20261027")


def test_successful_name_pages_are_reused_without_another_request(tmp_path):
    observation = registry(tmp_path)
    cached = acquire_current_display_names(tmp_path / "evidence", observation_date="20261027",
        requested_codes=list(NAMES), api=SimpleNamespace())
    assert cached["rows"] == observation["rows"]


def test_names_cover_all_arrays_and_preserve_selector_identity_score_and_suffix(tmp_path, monkeypatch):
    registry(tmp_path)
    monkeypatch.setenv("V4_MANAGER_SECURITY_MASTER_ROOT", str(tmp_path))
    monkeypatch.setattr(StageSelectionConsumer, "_load_a_name_authority", lambda *args: {
        "mapping": {"A.000995": "皇台酒业"}, "conflicted_codes": [], "pool_audit": {"bad": {"status": "ISOLATED"}},
    })
    rows = [{"symbol": "A." + code[:6], "ts_code": "920575.SH" if code.endswith(".BJ") else code,
             "name": code[:6], "stock_name": "A." + code[:6], "display_name": "A." + code[:6] + "（选）",
             "market": "A", "target_date": "20261027", "pool_rank": index, "pool_score": 120.0}
            for index, code in enumerate(NAMES)]
    response = {key: rows for key in ("rows", "unified_rows", "a_source_only_rows", "a_all_pool_rows")}
    response["pools"] = [{"pool_id": "a_d1_premarket_pool", "source_sha256": "a" * 64, "rows": rows}]
    before = json.dumps(response, ensure_ascii=False, sort_keys=True)
    projected = project_a_display_names(response, "20261027", tmp_path)
    assert json.dumps(response, ensure_ascii=False, sort_keys=True) == before
    for target in [projected[key] for key in ("rows", "unified_rows", "a_source_only_rows", "a_all_pool_rows")] + [projected["pools"][0]["rows"]]:
        assert [r["name"] for r in target] == list(NAMES.values())
        assert [r["display_name"] for r in target] == [name + "（选）" for name in NAMES.values()]
        assert [r["pool_rank"] for r in target] == [0, 1, 2]
        assert all(r["pool_score"] == 120.0 for r in target)
        assert target[2]["ts_code"] == "920575.SH"
        assert target[2]["display_identity"]["ts_code"] == "920575.BJ"
    assert projected["pools"][0]["source_sha256"] == "a" * 64


def test_names_reject_conflict_and_wrong_row_date(tmp_path, monkeypatch):
    registry(tmp_path)
    monkeypatch.setenv("V4_MANAGER_SECURITY_MASTER_ROOT", str(tmp_path))
    monkeypatch.setattr(StageSelectionConsumer, "_load_a_name_authority", lambda *args: {
        "mapping": {}, "conflicted_codes": ["A.000995"],
    })
    rows = [{"symbol": "A.000995", "stock_name": "000995"},
            {"symbol": "A.600048", "stock_name": "600048", "target_date": "20261026"}]
    result = project_a_display_names({"rows": rows}, "20261027", tmp_path)
    assert result["rows"] == rows
    assert result["display_name_authority"]["conflicted_codes"] == ["A.000995"]


def write_receipt(ledger, *, status, scheduled_date="20261027"):
    row = dict(business_date="20261027", scheduled_date=scheduled_date, target_date="20261027",
               mode="LIVE", slot="0415", run_id=status, selected_workload_ids=["us_market_digest"],
               status=status, finished_at="2026-10-27T04:16:00+08:00", prev_ledger_sha256=None,
               workload_results=[{"workload_id": "us_market_digest", "status": status}])
    row["ledger_sha256"] = _ledger_digest(row)
    path = ledger.root / "receipts/live/20261027/0415" / (status + ".dispatch-receipt.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row))
    return path


def us_row(result):
    return next(row for row in result["groups"]["logical"] if row["workload_id"] == "us_market_digest")


def test_us_ledger_has_independent_live_chain_and_does_not_change_main(tmp_path):
    main, us = ExecutionLedger(tmp_path / "main"), ExecutionLedger(tmp_path / "us")
    write_receipt(main, status="FAILED")
    path = write_receipt(us, status="SUCCEEDED")
    args = (load_workload_catalog(), main, "20261027")
    now = datetime(2026, 10, 27, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
    main_only = build_task_status(*args, now=now)
    independent = build_task_status(*args, now=now, us_ledger=us)
    assert us_row(main_only)["status"] == "FAILED"
    assert us_row(independent)["status"] == "SUCCEEDED"
    assert us_row(independent)["receipt_chain_verified"] is True
    assert [r for r in independent["groups"]["logical"] if r["workload_id"] != "us_market_digest"] == [r for r in main_only["groups"]["logical"] if r["workload_id"] != "us_market_digest"]
    row = json.loads(path.read_text()); row["status"] = "READY"; path.write_text(json.dumps(row))
    broken = build_task_status(*args, now=now, us_ledger=us)
    assert us_row(broken)["status"] == "CANNOT_CONFIRM"
    assert us_row(broken)["result_code"] == "US_EXECUTION_RECEIPT_CHAIN_INVALID"


def test_us_ledger_wrong_scheduled_date_remains_unknown(tmp_path):
    main, us = ExecutionLedger(tmp_path / "main"), ExecutionLedger(tmp_path / "us")
    write_receipt(us, status="SUCCEEDED", scheduled_date="20261026")
    result = build_task_status(load_workload_catalog(), main, "20261027", us_ledger=us)
    assert us_row(result)["status"] == "CANNOT_CONFIRM"


def test_compact_manager_preserves_original_generated_at():
    context = SimpleNamespace(target_date="20261027", phase=SimpleNamespace(value="PREMARKET"),
                              cutoff="cutoff", source_sessions={})
    snapshot = SimpleNamespace(context=context, run_id="same-saved-run", product_sha256="a" * 64,
                               generated_at="2026-10-27T04:17:03.311511+08:00")
    assert _summary(snapshot)["generated_at"] == snapshot.generated_at


def test_bad_pool_isolated_and_wrong_pool_date_sha_never_create_names(tmp_path):
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    pool_ids = ("a_d1_premarket_pool", "a_d1_fupan_watchlist_pool", "a_d1_stage7_fenshi_review_pool", "a_share_research_recommendation_pool")
    store = PreselectionPoolStore(tmp_path)
    for pool_id in pool_ids:
        store.materialize(dict(schema_version="v3_5.preselection_pool.v1", trade_date="20261027", target_date="20261027",
            pool_id=pool_id, display_name=pool_id, market="A", status="READY", producer_id="test", source_role="RAW_SOURCE",
            source_path="tests/source", source_sha256="a" * 64, rows=[dict(symbol="A.000995", name="皇台酒业", stock_name="皇台酒业", target_date="20261027")],
            cannot_confirm=[], production_allowed=False, buy_gate_updated=False, orders_sent=False))
    def authority():
        return StageSelectionConsumer(tmp_path / "selection", a_name_pool_root=tmp_path)._load_a_name_authority("20261027")
    assert authority()["mapping"]["A.000995"] == "皇台酒业"
    # Tampering one pool is isolated; three other verified trios remain usable.
    artifact = tmp_path / "preselection_pools/20261027" / (pool_ids[0] + ".json")
    original = artifact.read_bytes()
    tampered = json.loads(original)
    tampered["rows"][0]["stock_name"] = "篡改名称"
    artifact.write_text(json.dumps(tampered, ensure_ascii=False))
    damaged = authority()
    assert damaged["pool_audit"][pool_ids[0]]["status"] == "ISOLATED"
    assert damaged["mapping"]["A.000995"] == "皇台酒业"
    artifact.write_bytes(original)
    # An exact wrong date cannot fall back to this publication.
    other = StageSelectionConsumer(tmp_path / "selection", a_name_pool_root=tmp_path)._load_a_name_authority("20261026")
    assert other["mapping"] == {}


def test_runtime_router_binds_optional_us_reader_without_rebinding_main(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.v35_api.runtime_router import create_runtime_router
    main, us = ExecutionLedger(tmp_path / "main"), ExecutionLedger(tmp_path / "us")
    write_receipt(main, status="FAILED")
    write_receipt(us, status="SUCCEEDED")
    monkeypatch.setenv("V4_TASK_STATUS_US_LEDGER_ROOT", str(us.root))
    app = FastAPI()
    app.include_router(create_runtime_router(tmp_path / "data", ledger_root=main.root))
    response = TestClient(app).get("/api/v3/tasks/status?date=20261027")
    assert response.status_code == 200
    assert us_row(response.json())["receipt_chain_verified"] is True
    assert us_row(response.json())["status"] == "SUCCEEDED"


@pytest.mark.parametrize('failure',['missing','corrupt','wrong_date'])
def test_missing_corrupt_or_wrong_date_display_registry_never_blocks_pool_projection(tmp_path,monkeypatch,failure):
    if failure=='corrupt':
        latest=tmp_path/'assets/a_share_display_names/latest.json';latest.parent.mkdir(parents=True);latest.write_text('{bad')
    elif failure=='wrong_date':
        registry(tmp_path)
    target_date='20261026' if failure=='wrong_date' else '20261027'
    monkeypatch.setenv('V4_MANAGER_SECURITY_MASTER_ROOT',str(tmp_path))
    monkeypatch.setattr(StageSelectionConsumer,'_load_a_name_authority',lambda *args:{'mapping':{'A.000995':'皇台酒业'},'conflicted_codes':[]})
    row={'symbol':'A.000995','stock_name':'A.000995','display_name':'A.000995（选）','target_date':target_date,'pool_score':120.0}
    payload={'rows':[row],'source_sha256':'a'*64,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
    before=json.dumps(payload,ensure_ascii=False,sort_keys=True)
    result=project_a_display_names(payload,target_date,tmp_path)
    assert result['rows'][0]['stock_name']=='皇台酒业'
    assert result['display_name_authority']['current_error']
    assert result['display_name_authority']['run_id'] is None
    assert result['rows'][0]['pool_score']==120.0 and result['source_sha256']=='a'*64
    assert json.dumps(payload,ensure_ascii=False,sort_keys=True)==before


@pytest.mark.parametrize('component',['artifact','manifest','receipt','index','entries','entry','rows','evidence_page'])
@pytest.mark.parametrize('invalid',[[],None])
def test_nonobject_registry_shapes_are_store_errors_with_hash_pins_and_nonblocking_projection(tmp_path,monkeypatch,component,invalid):
    from upstreams.v3_shared_data.shared_data.hashing import canonical_bytes,sha256_json
    registry(tmp_path)
    latest=tmp_path/'assets/a_share_display_names/latest.json'
    index=json.loads(latest.read_text());run=latest.parent/index['entries']['20261027']['run_relative']
    artifact=json.loads((run/'artifact.json').read_text());manifest=json.loads((run/'manifest.json').read_text());receipt=json.loads((run/'receipt.json').read_text())
    if component in {'artifact','manifest','receipt'}:
        if component=='artifact':artifact=invalid
        if component=='manifest':manifest=invalid
        if component=='receipt':receipt=invalid
    elif component=='rows':artifact['rows']=[invalid]
    elif component=='evidence_page':
        page=Path(artifact['rows'][0]['evidence_path']);page.write_bytes(canonical_bytes(invalid))
        artifact['rows'][0]['evidence_sha256']=sha256_json(invalid)
    # Rebind both outer hashes so the failure proves a shape boundary instead
    # of accidentally relying on a stale artifact/manifest digest.
    if isinstance(manifest,dict):manifest['artifact_sha256']=sha256_json(artifact)
    if isinstance(receipt,dict):
        receipt['manifest_sha256']=sha256_json(manifest)
        if isinstance(manifest,dict):receipt['artifact_sha256']=manifest['artifact_sha256']
    for name,payload in [('artifact',artifact),('manifest',manifest),('receipt',receipt)]:
        (run/(name+'.json')).write_bytes(canonical_bytes(payload))
    if component=='index':index=invalid
    elif component=='entries':index['entries']=invalid
    elif component=='entry':index['entries']['20261027']=invalid
    latest.write_bytes(canonical_bytes(index))
    if isinstance(manifest,dict):assert sha256_json(json.loads((run/'artifact.json').read_text()))==manifest['artifact_sha256']
    if isinstance(receipt,dict):assert sha256_json(json.loads((run/'manifest.json').read_text()))==receipt['manifest_sha256']
    with pytest.raises(StoreError,match='object'):
        load_current_display_names(tmp_path,'20261027')
    monkeypatch.setenv('V4_MANAGER_SECURITY_MASTER_ROOT',str(tmp_path))
    monkeypatch.setattr(StageSelectionConsumer,'_load_a_name_authority',lambda *args:{'mapping':{'A.000995':'皇台酒业'},'conflicted_codes':[]})
    original={'rows':[{'symbol':'A.000995','stock_name':'A.000995','pool_score':120.0}],'source_sha256':'b'*64}
    result=project_a_display_names(original,'20261027',tmp_path)
    assert result['rows'][0]['stock_name']=='皇台酒业'
    assert result['display_name_authority']['current_error'] and result['display_name_authority']['run_id'] is None
    assert result['source_sha256']==original['source_sha256'] and result['rows'][0]['pool_score']==120.0
    assert original['rows'][0]['stock_name']=='A.000995'


@pytest.mark.parametrize('field,invalid',[('name',[]),('name',None),('provider',[]),('evidence_path',None)])
def test_malformed_row_text_fields_fail_before_projection(tmp_path,field,invalid):
    from upstreams.v3_shared_data.shared_data.hashing import canonical_bytes,sha256_json
    registry(tmp_path);latest=tmp_path/'assets/a_share_display_names/latest.json';index=json.loads(latest.read_text());run=latest.parent/index['entries']['20261027']['run_relative']
    artifact=json.loads((run/'artifact.json').read_text());manifest=json.loads((run/'manifest.json').read_text());receipt=json.loads((run/'receipt.json').read_text())
    artifact['rows'][0][field]=invalid
    manifest['artifact_sha256']=sha256_json(artifact);receipt['artifact_sha256']=manifest['artifact_sha256'];receipt['manifest_sha256']=sha256_json(manifest)
    for name,payload in [('artifact',artifact),('manifest',manifest),('receipt',receipt)]:
        (run/(name+'.json')).write_bytes(canonical_bytes(payload))
    with pytest.raises(StoreError,match='strings'):load_current_display_names(tmp_path,'20261027')
