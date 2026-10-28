"""Synthetic, offline regressions; no runtime producer, service or market calls."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATE, SIGNAL = "20260820", "20260819"


def _fixtures():
    spec = importlib.util.spec_from_file_location("review_repair_existing_fixtures", ROOT / "tests/test_recurrence_repairs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(tmp_path):
    f = _fixtures()
    return dict(trade_date=DATE, signal_date=SIGNAL, selector=None,
                input_root=tmp_path / "inputs", shared_data_root=tmp_path / "shared",
                shared_package_root=tmp_path / "package", data_root=tmp_path / "data",
                pool_reader=lambda *a, **k: f._fake_a_pool(DATE, SIGNAL),
                hk_pool_reader=lambda *a, **k: f._fake_hk_pool(DATE, SIGNAL))


@pytest.mark.parametrize("files,pool_id", [
    (("fupan.csv", "fupan.manifest.json"), "a_d1_fupan_watchlist_pool"),
    (("stage7.csv", "stage7.manifest.json"), "a_d1_stage7_fenshi_review_pool"),
    (("baimao.json",), "a_share_baimao_research_map"),
    (("wechat_rows.csv", "wechat_manifest.json"), "wechat_public_account_v3_preselect"),
])
def test_bad_optional_input_does_not_discard_valid_siblings(tmp_path, files, pool_id):
    from ops.materialize_scheduled_preselection import build_scheduled_artifacts
    args = _args(tmp_path)
    day = args["input_root"] / DATE
    day.mkdir(parents=True)
    for name in files:
        (day / name).write_text("{broken" if name.endswith(".json") else "code\n000001\n")
    values = {a["pool_id"]: a for a in build_scheduled_artifacts(**args)}
    assert len(values["a_d1_premarket_pool"]["rows"]) == 1
    assert len(values["hkconnect_d1_top100"]["rows"]) == 100
    assert values[pool_id]["status"] == "CANNOT_CONFIRM"
    assert values[pool_id]["rows"] == []
    assert values[pool_id]["cannot_confirm"]


def test_optional_programming_error_is_not_suppressed(tmp_path, monkeypatch):
    import ops.materialize_scheduled_preselection as m
    def broken(*args, **kwargs):
        raise RuntimeError("programmer error")
    monkeypatch.setattr(m, "build_hourly_research_pool", broken)
    with pytest.raises(RuntimeError, match="programmer error"):
        m.build_scheduled_artifacts(**_args(tmp_path))


def test_optional_programming_valueerror_is_not_suppressed(tmp_path, monkeypatch):
    import ops.materialize_scheduled_preselection as m

    def broken(*args, **kwargs):
        raise ValueError("synthetic programmer defect")

    monkeypatch.setattr(m, "build_baimao_pool", broken)
    args = _args(tmp_path)
    day = args["input_root"] / DATE
    day.mkdir(parents=True)
    (day / "baimao.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="synthetic programmer defect"):
        m.build_scheduled_artifacts(**args)


def test_formal_missing_is_deferred_and_same_day_ready_can_publish(tmp_path):
    import ops.materialize_scheduled_preselection as m
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    args = _args(tmp_path)
    store = PreselectionPoolStore(args["data_root"])
    good = m.build_scheduled_artifacts(**args)
    missing = m._missing(DATE, pool_id=good[0]["pool_id"], display_name=good[0]["display_name"], market="A", reason="synthetic not ready")
    first = m.publish_scheduled_artifacts(store, [missing])
    assert first[0]["status"] == "DEFERRED"
    assert first[0]["artifact_written"] is False
    second = m.publish_scheduled_artifacts(store, [good[0]])
    assert second[0]["sha256"]
    assert store.read_pool_snapshot(DATE, good[0]["pool_id"])["artifact"]["source_role"] == "SHARED_VERIFIED_V192"
    assert m.publish_scheduled_artifacts(store, [good[0]]) == second


def test_ready_conflict_is_explicit_and_does_not_block_sibling(tmp_path):
    import ops.materialize_scheduled_preselection as m
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    args = _args(tmp_path)
    artifacts = m.build_scheduled_artifacts(**args)
    a, hk = artifacts[0], artifacts[5]
    store = PreselectionPoolStore(args["data_root"])
    store.materialize(a)
    changed = json.loads(json.dumps(a)); changed["display_name"] += "changed"
    with pytest.raises(ValueError, match="conflicting preselection-pool materialization") as caught:
        m.publish_scheduled_artifacts(store, [changed, hk])
    results = caught.value.results
    assert results[0]["status"] == "REJECTED"
    assert results[0]["reason_code"] == "IMMUTABLE_POOL_CONFLICT"
    assert results[1]["sha256"]
    assert store.read_pool_snapshot(DATE, a["pool_id"])["artifact"] == a


def test_legacy_formal_placeholder_is_not_overwritten(tmp_path):
    import ops.materialize_scheduled_preselection as m
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    args = _args(tmp_path); store = PreselectionPoolStore(args["data_root"])
    a = m.build_scheduled_artifacts(**args)[0]
    old = m._missing(DATE, pool_id=a["pool_id"], display_name=a["display_name"], market="A", reason="legacy missing")
    store.materialize(old)
    with pytest.raises(ValueError, match="conflicting preselection-pool materialization") as caught:
        m.publish_scheduled_artifacts(store, [a])
    results = caught.value.results
    assert results[0]["status"] == "REJECTED"
    assert store.read_pool_snapshot(DATE, a["pool_id"])["artifact"] == old


def test_non_ascii_lock_denies_without_recursion(tmp_path):
    from stage_center.runner import SlotLock
    path = tmp_path / "slot.lock"; path.write_bytes(b"\xff")
    lock = SlotLock(path)
    import sys
    old_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(140)
        assert lock.acquire() is False
    finally:
        sys.setrecursionlimit(old_limit)
    assert path.read_bytes() == b"\xff"


def test_slot_lock_uses_persistent_mutex_and_releases(tmp_path):
    from stage_center.runner import SlotLock
    path = tmp_path / "slot.lock"
    first, second = SlotLock(path), SlotLock(path)
    assert first.acquire() is True
    try:
        mutex = path.with_name(path.name + ".mutex")
        assert mutex.is_file()
        identity = mutex.stat().st_ino
        assert second.acquire() is False
    finally:
        first.release()
    assert second.acquire() is True
    try:
        assert mutex.stat().st_ino == identity
    finally:
        second.release()
    assert not path.exists()
    assert mutex.exists()


def _lock_worker(path, barrier, release, queue):
    from stage_center.runner import SlotLock
    lock = SlotLock(path)
    barrier.wait(timeout=10)
    acquired = lock.acquire()
    queue.put((os.getpid(), acquired))
    if acquired:
        release.wait(timeout=10)
        lock.release()


def test_two_process_stale_owner_has_only_one_winner(tmp_path):
    path = tmp_path / "slot.lock"; path.write_text("2147483647:dead")
    ctx = multiprocessing.get_context("spawn")
    barrier, release, queue = ctx.Barrier(3), ctx.Event(), ctx.Queue()
    processes = [ctx.Process(target=_lock_worker, args=(path, barrier, release, queue)) for _ in range(2)]
    try:
        for process in processes: process.start()
        barrier.wait(timeout=10)
        results = [queue.get(timeout=10) for _ in processes]
        assert sum(acquired for _, acquired in results) == 1
    finally:
        release.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive(): process.terminate(); process.join(timeout=5)
        queue.close()
    assert all(process.exitcode == 0 for process in processes)


def test_release_pin_contains_direct_split_execution_inputs():
    from infrastructure.scheduling.dispatcher import _RUNTIME_IDENTITY_FILES
    for relative in ("infrastructure/scheduling/_executor_registry_parts/preselection.py",
                     "infrastructure/scheduling/_executor_registry_parts/_namespace.py",
                     "stage_center/_runner_parts/slot_lock.py",
                     "domains/_preselection_materializer_parts/row_assembly.py"):
        assert relative in _RUNTIME_IDENTITY_FILES
    assert len(set(_RUNTIME_IDENTITY_FILES)) == len(_RUNTIME_IDENTITY_FILES)
    assert all((ROOT / relative).is_file() for relative in _RUNTIME_IDENTITY_FILES)


def test_missing_hk_config_is_lane_local(tmp_path, monkeypatch):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    calls = []
    registry = FixedExecutorRegistry(tmp_path / "data", shared_data_root=tmp_path / "shared",
        shared_package_root=ROOT / "upstreams/v3_shared_data", preselection_input_root=tmp_path / "inputs",
        hk_universe_root=None, repo_root=ROOT)
    def exact(**kwargs):
        return ({"status":"READY", "run_id":"synthetic", "artifact_sha256":"a"*64, "row_count":1}, "") if kwargs["module_leaf"] == "v192_selector" else (None, "synthetic unavailable")
    def run(module, args, **kwargs):
        calls.append(module)
        return {"status":"SUCCEEDED", "exit_code":0, "stdout":"", "stderr":"", "production_allowed":False, "buy_gate_updated":False, "orders_sent":False}
    monkeypatch.setattr(registry, "_verified_preselection_source", exact)
    monkeypatch.setattr(registry, "_run", run)
    result = registry._preselection_pools(SimpleNamespace(business_date=SIGNAL, target_date=DATE))
    assert "ops.materialize_scheduled_preselection" in calls
    assert result["a_selector_status"] == "READY"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert "scripts.update_hk_0_2_panel" not in calls
    assert "scripts.materialize_hk_0_2" not in calls
    assert "ops.ensure_hk_security_master" not in calls


def test_hk_securities_policy_uses_hk_securities_not_connect(monkeypatch):
    import domains.task_status as m
    from contracts.trading_calendar import RunPolicy, TradingDayState
    states = {"a_share":TradingDayState.NON_TRADING_DAY, "hk_connect":TradingDayState.NON_TRADING_DAY,
              "hk_securities":TradingDayState.HALF_TRADING_DAY_AM}
    monkeypatch.setattr(m, "resolve_market_states", lambda *args: states)
    assert m._schedule_date_is_eligible(SimpleNamespace(run_policy=RunPolicy.HK_SECURITIES_TRADE_DAY), DATE) is True
    assert m._schedule_date_is_eligible(SimpleNamespace(run_policy=RunPolicy.HK_CONNECT_TRADE_DAY), DATE) is False


def test_unknown_missing_calendar_state_is_not_trade_day(monkeypatch):
    import domains.task_status as m
    from contracts.trading_calendar import RunPolicy
    monkeypatch.setattr(m, "resolve_market_states", lambda *args: {})
    assert m._schedule_date_is_eligible(SimpleNamespace(run_policy=RunPolicy.A_SHARE_TRADE_DAY), DATE) is False


def test_next_due_loads_calendar_once(monkeypatch):
    import domains.task_status as m
    from datetime import datetime
    from contracts.trading_calendar import RunPolicy
    calls=[]; real=m.load_market_calendar
    def load(): calls.append(1); return real()
    monkeypatch.setattr(m, "load_market_calendar", load)
    workload=SimpleNamespace(enabled=True, slots=("0900",), run_policy=RunPolicy.A_SHARE_TRADE_DAY)
    assert m._next_due(workload,"20261231",datetime.fromisoformat("2026-12-31T10:00:00+08:00")) is None
    assert len(calls) == 1


@pytest.mark.parametrize("atomic", [False, True])
def test_same_path_changed_bytes_have_new_source_digest(tmp_path, atomic):
    import domains.preselection_materializer as m
    pool, manifest = tmp_path / "fupan.csv", tmp_path / "fupan.manifest.json"
    manifest.write_text(json.dumps({"status":"FUPAN_WATCHLIST_POOL_READY", "fupan_pool_rule":"AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW", "target_date":DATE, "signal_date":SIGNAL, "source_paths":["synthetic"], "row_count":1}))
    pool.write_text(f"code,stock_name,signal_date\n000001,synthetic,{SIGNAL}\n")
    first = m.build_fupan_watchlist_pool(pool, manifest, trade_date=DATE, signal_date=SIGNAL)
    content=f"code,stock_name,signal_date\n000002,synthetic,{SIGNAL}\n"
    if atomic:
        temp=tmp_path/"new.csv"; temp.write_text(content); temp.replace(pool)
    else: pool.write_text(content)
    second = m.build_fupan_watchlist_pool(pool, manifest, trade_date=DATE, signal_date=SIGNAL)
    digest=hashlib.sha256("".join(hashlib.sha256(p.read_bytes()).hexdigest() for p in (manifest,pool)).encode("ascii")).hexdigest()
    assert second["rows"][0]["symbol"] == "A.000002"
    assert first["source_sha256"] != second["source_sha256"]
    assert second["source_sha256"] == digest


def test_legacy_video_facade_binds_sys_statically():
    tree=ast.parse((ROOT / "ops/run_v35_close_review_node.py").read_bytes())
    assert any(isinstance(n,ast.Import) and any(a.name == "sys" and a.asname in (None,"sys") for a in n.names) for n in tree.body)


def test_manifest_digest_matches_parsed_bytes_even_if_path_changes(tmp_path, monkeypatch):
    import domains.preselection_materializer as m
    pool, manifest = tmp_path / "fupan.csv", tmp_path / "fupan.manifest.json"
    payload={"status":"FUPAN_WATCHLIST_POOL_READY", "fupan_pool_rule":"AUTO_FUPAN_THEN_VIDEO_SECOND_REVIEW", "target_date":DATE, "signal_date":SIGNAL, "source_paths":["synthetic"], "row_count":1}
    manifest.write_text(json.dumps(payload))
    pool.write_text(f"code,stock_name,signal_date\n000001,synthetic,{SIGNAL}\n")
    expected = hashlib.sha256("".join(hashlib.sha256(p.read_bytes()).hexdigest() for p in (manifest,pool)).encode("ascii")).hexdigest()
    original=m._manifest
    def read_then_change(path, **kwargs):
        value=original(path, **kwargs)
        manifest.write_text(json.dumps({**payload, "cannot_confirm":["modified-after-parse"]}))
        return value
    monkeypatch.setattr(m,"_manifest",read_then_change)
    artifact=m.build_fupan_watchlist_pool(pool,manifest,trade_date=DATE,signal_date=SIGNAL)
    assert artifact["source_sha256"] == expected
    assert "modified-after-parse" not in artifact["cannot_confirm"]


def test_helper_byte_drift_is_rejected_by_real_release_guard(tmp_path, monkeypatch):
    import infrastructure.scheduling.dispatcher as m
    source=tmp_path/"app"; entries=[]
    helper="infrastructure/scheduling/_executor_registry_parts/preselection.py"
    for relative in dict.fromkeys((*m._RUNTIME_IDENTITY_FILES,helper)):
        raw=(ROOT/relative).read_bytes(); dest=source/relative; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(raw)
        entries.append({"path":relative,"kind":"file","size":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
    manifest={"schema_version":"v4.release_candidate.v1","candidate":{"app_root":str(source),"release_id":"synthetic-offline"},
              "application_inventory":{"entries":entries,"entry_count":len(entries),"aggregate_sha256":hashlib.sha256(json.dumps(entries,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()}}
    path=tmp_path/"manifest.json"; path.write_text(json.dumps(manifest))
    env={"V35_APP_ROOT":str(source),"V35_RELEASE_ID":"synthetic-offline","V35_RELEASE_MANIFEST_PATH":str(path),"V35_RELEASE_MANIFEST_SHA256":hashlib.sha256(path.read_bytes()).hexdigest()}
    for name,value in env.items():monkeypatch.setenv(name,value)
    monkeypatch.setattr(m,"__file__",str(source/"infrastructure/scheduling/dispatcher.py"))
    assert m.validate_release_identity()["release_id"] == "synthetic-offline"
    with (source/helper).open("ab") as stream: stream.write(b"\n# synthetic mutation\n")
    with pytest.raises(ValueError,match="RELEASE_RUNTIME_BYTES_MISMATCH"):
        m.validate_release_identity()


def test_cli_missing_formal_reports_deferred_but_publishes_valid_hk(tmp_path, capsys):
    import ops.materialize_scheduled_preselection as m
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    args=_args(tmp_path)
    def missing(*a,**k):raise FileNotFoundError("synthetic unavailable")
    code=m.main(["--trade-date",DATE,"--signal-date",SIGNAL,"--input-root",str(args["input_root"]),
                 "--data-root",str(args["data_root"]),"--shared-data-root",str(args["shared_data_root"]),
                 "--shared-package-root",str(args["shared_package_root"])],pool_reader=missing,hk_pool_reader=args["hk_pool_reader"])
    payload=json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["status"] == "PARTIAL"
    assert payload["artifacts"][0]["artifact_written"] is False
    assert payload["artifacts"][0]["status"] == "DEFERRED"
    assert len(PreselectionPoolStore(args["data_root"]).read_pool_snapshot(DATE,"hkconnect_d1_top100")["artifact"]["rows"]) == 100
