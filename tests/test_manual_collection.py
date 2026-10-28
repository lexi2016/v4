"""Frozen manual-button acceptance. Dependency root may be a read-only runtime.

The old Git baseline lacks the deployed Stage8 package. Set
V4_MANUAL_COLLECTION_DEPENDENCY_ROOT to the inspected source/runtime root;
only these two new modules are loaded from the candidate worktree.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading
import time
import subprocess
from datetime import datetime
from functools import partial
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = os.environ.get("V4_MANUAL_COLLECTION_DEPENDENCY_ROOT")
if DEPENDENCIES:
    sys.path.insert(0, DEPENDENCIES)


def _candidate(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


manual = _candidate("infrastructure.manual_collection", "infrastructure/manual_collection.py")
router_module = _candidate("manual_collection_router_candidate", "apps/api/v35_api/manual_collection_router.py")
from fastapi import FastAPI
from fastapi.testclient import TestClient
from infrastructure.hkconnect_close_store import CloseSnapshotStore
from infrastructure.review_store import ReviewStore
from ops import collect_hkconnect_close_snapshot as close_module

TZ = ZoneInfo("Asia/Shanghai")
DATE = "20261020"


def _service(tmp_path, **kwargs):
    return manual.ManualCollectionService(tmp_path / "data", state_root=tmp_path / "jobs",
        clock=kwargs.pop("clock", lambda: datetime(2026, 10, 20, 20, 40, tzinfo=TZ)), **kwargs)


def _client(service):
    app = FastAPI()
    app.include_router(router_module.create_manual_collection_router(service.data_root, service=service))
    return TestClient(app)


def _finish(service, job):
    for _ in range(200):
        receipt = service.read(job["job_id"])
        if receipt["status"] in manual.TERMINAL:
            return receipt
        time.sleep(0.01)
    pytest.fail("bounded canary did not finish")


class Frame:
    def __init__(self, rows):
        self.rows = rows

    def to_dict(self, orient):
        return self.rows


class Quotes:
    def __init__(self):
        self.calls = 0
        self.closed = False

    def get_plate_stock(self, _plate):
        return 0, Frame([{"code": f"HK.{n:05}", "stock_name": f"S{n}"} for n in range(1, 601)])

    def get_market_snapshot(self, codes):
        self.calls += 1
        return 0, Frame([{"code": code, "last_price": 11, "prev_close_price": 10,
                          "turnover": 30_000_000, "update_time": "2026-10-20 16:11:00"} for code in codes])

    def close(self):
        self.closed = True


def test_button_api_reaches_real_close_collector_and_builder_keeps_partial(tmp_path, monkeypatch):
    quotes = Quotes()
    monkeypatch.setattr(close_module, "_default_quote_context_factory", lambda: quotes)
    from ops import build_close_review as builder
    pool = {"pool_id": "hkconnect_d1_top100", "trade_date": DATE, "status": "STRICT_0_2_READY",
            "source_role": "SHARED_VERIFIED_HK_0_2", "source_manifest_sha256": "a" * 64,
            "source_receipt_sha256": "b" * 64,
            "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            "rows": [{"code": f"HK.{n:05}", "market": "HK", "trade_date": DATE}
                     for n in range(1, 101)]}
    monkeypatch.setattr(builder.PreselectionPoolStore, "read_pool", lambda *_args: pool)
    service = _service(tmp_path)
    natural = tmp_path / "natural-receipt.json"
    natural.write_text('{"status":"CANNOT_CONFIRM","origin":"NATURAL"}')
    original = hashlib.sha256(natural.read_bytes()).hexdigest()
    with _client(service) as client:
        response = client.post("/api/v3/manual-collection", json={"date": DATE, "target": "HK_CLOSE"})
        assert response.status_code == 200
        job = _finish(service, response.json())
        assert job["status"] == "PARTIAL"
        assert job["result"]["same_date_row_count"] == 600
        assert job["result"]["review_status"] == "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE"
        assert job["result"]["missing_stages"]
        assert CloseSnapshotStore(service.data_root).read_snapshot(DATE)[0]["status"] == "READY"
        assert ReviewStore(service.data_root).read_reference(DATE)["status"] == "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE"
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in service.data_root.rglob("*.json")}
        again = client.post("/api/v3/manual-collection", json={"date": DATE, "target": "HK_CLOSE"}).json()
        assert again["job_id"] == job["job_id"]
        assert client.get(f"/api/v3/manual-collection/{job['job_id']}").json()["status"] == "PARTIAL"
        # New server instance / fresh job ledger still reuses both real stores.
        fresh = manual.ManualCollectionService(service.data_root, state_root=tmp_path / "fresh_jobs", clock=service.clock)
        cached = _finish(fresh, fresh.start(DATE, "HK_CLOSE"))
        assert cached["result"]["snapshot_publication"] == "IDEMPOTENT_REUSE"
        assert cached["result"]["review_publication"] == "IDEMPOTENT_REUSE"
        assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in service.data_root.rglob("*.json")} == before
    assert quotes.calls == 3 and quotes.closed
    assert hashlib.sha256(natural.read_bytes()).hexdigest() == original
    assert all(job[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent", "natural_verified"))


def test_inflight_duplicate_and_other_target_do_not_queue(tmp_path, monkeypatch):
    gate, entered = threading.Event(), threading.Event()
    service = _service(tmp_path)
    calls = []
    def blocked(job):
        calls.append(True); entered.set(); gate.wait(2)
        job.update(status="READY", message="fixture")
    monkeypatch.setattr(service, "_close", blocked)
    first = service.start(DATE, "HK_CLOSE")
    assert entered.wait(1)
    try:
        assert service.start(DATE, "HK_CLOSE")["job_id"] == first["job_id"]
        with pytest.raises(manual.CollectionRefused, match="已有补采"):
            service.start(DATE, "HK_STAGE", manual.STAGE8)
    finally:
        gate.set()
    assert _finish(service, first)["status"] == "READY"
    assert calls == [True]


@pytest.mark.parametrize("body,code", [
    ({"date": "20261021", "target": "HK_CLOSE"}, "FUTURE_DATE"),
    ({"date": "20261019", "target": "HK_CLOSE"}, "HK_CALENDAR_UNAVAILABLE"),
    ({"date": DATE, "target": "HK_STAGE"}, "TARGET_UNSUPPORTED"),
    ({"date": DATE, "target": "HK_CLOSE", "stage_id": manual.STAGE8}, "TARGET_UNSUPPORTED"),
])
def test_invalid_scope_fails_before_io(tmp_path, body, code):
    service = _service(tmp_path)
    with _client(service) as client:
        response = client.post("/api/v3/manual-collection", json=body)
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    assert not service.state_root.exists()


@pytest.mark.parametrize("extra", [{"force": True}, {"path": "/tmp/else"}, {"now": "15:50"}, {"date": "20260230"}])
def test_api_forbids_extra_and_invalid_date(tmp_path, extra):
    with _client(_service(tmp_path)) as client:
        response = client.post("/api/v3/manual-collection", json={"date": DATE, "target": "HK_CLOSE", **extra})
    assert response.status_code == 422


def test_cross_site_refused_and_job_path_not_accepted(tmp_path):
    service = _service(tmp_path)
    with _client(service) as client:
        for headers in ({"Origin": "https://other.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Origin": "null"}):
            assert client.post("/api/v3/manual-collection", json={"date": DATE, "target": "HK_CLOSE"}, headers=headers).status_code == 403
        assert client.get("/api/v3/manual-collection/not-a-job").status_code == 404
    assert not service.state_root.exists()


def test_stage8_after_window_missing_replay_is_zero_network(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.stage_config = {}  # A bound owner without a configured replay source.
    monkeypatch.setattr(service, "_new_runner", lambda: pytest.fail("missing replay must not construct collector"))
    monkeypatch.setattr(close_module, "_default_quote_context_factory", lambda: pytest.fail("network forbidden"))
    job = _finish(service, service.start(DATE, "HK_STAGE", manual.STAGE8))
    assert job["status"] == "CANNOT_CONFIRM"
    assert job["cannot_confirm"] == ["HK_STAGE8_EXACT_RTDATA_REPLAY_UNAVAILABLE"]
    assert "晚间行情" in job["message"]
    assert not service.data_root.exists()


def test_historical_close_without_cache_no_network(tmp_path, monkeypatch):
    service = _service(tmp_path)
    monkeypatch.setattr(close_module, "_default_quote_context_factory", lambda: pytest.fail("historical Futu request forbidden"))
    job = _finish(service, service.start("20261016", "HK_CLOSE"))
    assert job["status"] == "CANNOT_CONFIRM"
    assert job["cannot_confirm"] == ["HISTORICAL_CLOSE_SNAPSHOT_UNAVAILABLE"]


def test_real_stage8_precapture_path_with_fake_transport(tmp_path, monkeypatch):
    pytest.importorskip("stage_center.hk_stage8")
    from stage_center import runner as runner_module
    from stage_center.hk_stage8 import snapshot as snapshots
    import stage_center.hk_stage8 as stage8
    now = datetime(2026, 10, 20, 15, 51, tzinfo=TZ)
    service = _service(tmp_path, clock=lambda: now, stage_selection_root=tmp_path / "selection")
    roots = {key: str(tmp_path / key) for key in ("candidate_acquisition_root", "raw_root", "receipt_root",
                                                "hk_d1_root", "shared_data_root", "python_path")}
    roots["selection_root"] = str(tmp_path / "selection")
    binding = tmp_path / "binding.json"; binding.write_text(json.dumps(roots))
    service = _service(tmp_path, clock=lambda: now, stage_selection_root=tmp_path / "selection", stage_config_path=binding)
    codes = tuple(f"HK.{n:05}" for n in range(1, 101))
    monkeypatch.setattr(runner_module, "_build_hk_stage_binding", lambda *_args, **_kwargs:
                        SimpleNamespace(codes=codes, sha256="a" * 64, evidence=()))
    calls = []
    def transport(*_args, **_kwargs):
        calls.append(True)
        return SimpleNamespace(returncode=0)
    def fetch(codes, *, process_runner, **_kwargs):
        process_runner(["offline-transport"])
        return ([{"code": code, "prev_close_price": 10, "last_price": 11,
                   "turnover": 30_000_000, "volume_ratio": 2,
                   "update_time": "2026-10-20 15:51:00"} for code in codes], ())
    monkeypatch.setattr(snapshots, "_load_shared_module", lambda *_args: SimpleNamespace(fetch_futu_snapshot=fetch))
    monkeypatch.setattr(stage8, "prepare_hk_active_snapshot",
                        partial(snapshots.prepare_hk_active_snapshot, process_runner=transport, clock=lambda: now))
    with _client(service) as client:
        response = client.post("/api/v3/manual-collection", json={"date": DATE, "target": "HK_STAGE", "stage_id": manual.STAGE8})
        job = _finish(service, response.json())
    assert job["status"] == "SNAPSHOT_CAPTURED", job
    assert "尚未生成" in job["message"] and calls == [True]
    assert len(list(Path(roots["raw_root"]).rglob("*.json"))) == 1
    assert not Path(roots["receipt_root"]).exists()


def test_existing_invalid_review_preserved(tmp_path, monkeypatch):
    quotes = Quotes()
    monkeypatch.setattr(close_module, "_default_quote_context_factory", lambda: quotes)
    service = _service(tmp_path)
    reference = service.data_root / "close_reviews" / f"{DATE}.json"
    reference.parent.mkdir(parents=True)
    reference.write_text('{"invalid":"old-reference"}')
    before = reference.read_bytes()
    job = _finish(service, service.start(DATE, "HK_CLOSE"))
    assert job["status"] == "CANNOT_CONFIRM"
    assert reference.read_bytes() == before


def test_stage_binding_different_reader_root_is_rejected(tmp_path):
    binding = tmp_path / "binding.json"
    binding.write_text(json.dumps({key: str(tmp_path / key) for key in
        ("candidate_acquisition_root", "raw_root", "receipt_root", "selection_root", "hk_d1_root", "shared_data_root", "python_path")}))
    service = _service(tmp_path, stage_config_path=binding, stage_selection_root=tmp_path / "other")
    assert service.stage_config is None and service.config_error


def test_stage_cutoff_five_second_gap_does_not_start_replay(tmp_path):
    service = _service(tmp_path, clock=lambda: datetime(2026, 10, 20, 15, 55, 2, tzinfo=TZ))
    with pytest.raises(manual.CollectionRefused) as error:
        service.start(DATE, "HK_STAGE", manual.STAGE8)
    assert error.value.code == "STAGE_CUTOFF_NOT_REACHED"


@pytest.mark.parametrize("input_changes", [False, True])
def test_replay_is_isolated_and_partial_never_becomes_completed(tmp_path, monkeypatch, input_changes):
    service = _service(tmp_path)
    replay_root = tmp_path / "replay"
    folder = replay_root / DATE / manual.STAGE8; folder.mkdir(parents=True)
    csv = folder / f"hkconnect_rtdata_stage_replay_{DATE}_{manual.STAGE8}.csv"
    csv.write_text("code,update_time\nHK.00001,2026-10-20 15:54:00\n")
    service.stage_config = {"hk_stage_replay_root": str(replay_root)}
    original = tmp_path / "natural" / DATE / f"{manual.STAGE8}.json"
    original.parent.mkdir(parents=True); original.write_text("natural failure unchanged")
    before = original.read_bytes()
    calls = []
    class Runner:
        def tick(self, date, now, **kwargs):
            calls.append((date, kwargs))
            if input_changes:
                csv.write_text("different replay input")
            return {"status": "PARTIAL_WITH_ROWS", "backfill_run_id": "fixture-isolated-run",
                    "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                    "markets": {"HK_CONNECT": {"status": "PARTIAL_WITH_ROWS", "selected_rows": 1,
                                                "cannot_confirm": ["INCOMPLETE_COVERAGE"]}}}
    monkeypatch.setattr(service, "_new_runner", Runner)
    job = _finish(service, service.start(DATE, "HK_STAGE", manual.STAGE8))
    if input_changes:
        assert job["status"] == "CANNOT_CONFIRM" and job["cannot_confirm"] == ["REPLAY_INPUT_CHANGED"]
        assert original.read_bytes() == before
        return
    assert job["status"] == "PARTIAL"
    assert job["result"]["backfill_run_id"] == "fixture-isolated-run"
    assert job["result"]["input_replay_sha256"] == hashlib.sha256(csv.read_bytes()).hexdigest()
    assert calls == [(DATE, {"stage_id": manual.STAGE8, "historical_backfill": True,
                            "historical_markets": ("HK_CONNECT",)})]
    assert original.read_bytes() == before


def test_server_bound_real_owner_process_with_offline_transport(tmp_path, monkeypatch):
    owner = os.environ.get("V4_MANUAL_COLLECTION_STAGE_OWNER_ROOT")
    python = os.environ.get("V4_MANUAL_COLLECTION_STAGE_OWNER_PYTHON")
    if not owner or not python:
        pytest.skip("explicit read-only stage owner and interpreter required for subprocess canary")
    now = datetime(2026, 10, 20, 15, 51, tzinfo=TZ)
    config = {key: str(tmp_path / key) for key in ("candidate_acquisition_root", "raw_root", "receipt_root",
                                                "selection_root", "hk_d1_root", "shared_data_root", "python_path")}
    config.update(stage_owner_root=owner, stage_owner_python=python)
    binding = tmp_path / "binding.json"; binding.write_text(json.dumps(config))
    service = _service(tmp_path, clock=lambda: now, stage_config_path=binding,
                       stage_selection_root=Path(config["selection_root"]))
    # This test-only transport injection executes the unchanged fixed program
    # against the real owner's modules. No runtime injection hook is added.
    prefix = '''
import datetime, types
from zoneinfo import ZoneInfo
fixed = datetime.datetime(2026, 10, 20, 15, 51, tzinfo=ZoneInfo("Asia/Shanghai"))
import stage_center.runner as runner
import stage_center.hk_stage8 as stage8
import stage_center.hk_stage8.snapshot as snapshots
codes = tuple("HK.%05d" % n for n in range(1, 101))
runner._build_hk_stage_binding = lambda *a, **k: types.SimpleNamespace(codes=codes, sha256="a"*64, evidence=())
def fetch(codes, *, process_runner, **kwargs):
    process_runner(["offline-transport"])
    return ([dict(code=c, prev_close_price=10, last_price=11, turnover=30000000, volume_ratio=2, update_time="2026-10-20 15:51:00") for c in codes], ())
snapshots._load_shared_module = lambda *a: types.SimpleNamespace(fetch_futu_snapshot=fetch)
original_prepare = snapshots.prepare_hk_active_snapshot
def prepare(*args, **kwargs):
    return original_prepare(*args, **kwargs, clock=lambda: fixed, process_runner=lambda *a, **k: types.SimpleNamespace(returncode=0))
stage8.prepare_hk_active_snapshot = prepare
class FixedDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)
datetime.datetime = FixedDatetime
'''
    real_popen = subprocess.Popen
    observed = {}
    monkeypatch.setenv("V35_APP_ROOT", "/wrong/api/release")
    monkeypatch.setenv("V35_REVIEW_CORE_PACKAGE_ROOT", "/wrong/review/owner")
    def offline_popen(argv, **kwargs):
        assert argv == [python, "-c", manual._OWNER_PROGRAM]
        assert kwargs["cwd"] == owner and kwargs["shell"] is False
        assert kwargs["env"]["V35_APP_ROOT"] == owner
        assert kwargs["env"]["V35_REVIEW_CORE_PACKAGE_ROOT"] == str(Path(owner) / "upstreams")
        assert kwargs["env"]["REVIEW_CORE_PACKAGE_ROOT"] == str(Path(owner) / "upstreams")
        assert kwargs["env"]["PYTHONPATH"] == os.pathsep.join((str(Path(owner) / "upstreams"), owner))
        process = real_popen([python, "-c", prefix + manual._OWNER_PROGRAM], **kwargs)
        communicate = process.communicate
        def capture(*args, **kw):
            stdout, stderr = communicate(*args, **kw)
            observed["stderr"] = stderr.decode(errors="replace")
            return stdout, stderr
        process.communicate = capture
        return process
    monkeypatch.setattr(manual.subprocess, "Popen", offline_popen)
    with _client(service) as client:
        response = client.post("/api/v3/manual-collection", json={"date": DATE, "target": "HK_STAGE", "stage_id": manual.STAGE8})
        job = _finish(service, response.json())
    assert job["status"] == "SNAPSHOT_CAPTURED", (job, observed)
    assert job["stage_owner_identity"]["release_id"] == "hk-stage8-network-20261020-r1"
    assert job["child_pid"] > 0 and not (service.state_root / "owner_active.json").exists()
    assert len(list(Path(config["raw_root"]).rglob("*.json"))) == 1
    assert not Path(config["receipt_root"]).exists()


def test_interrupted_owner_requires_reconciliation_and_never_restarts(tmp_path):
    service = _service(tmp_path)
    job_id = "b" * 32
    service._write(f"jobs/{job_id}.json", {"job_id": job_id, "status": "RUNNING", "owner_pid": 0, "child_pid": 0})
    recovered = service.read(job_id)
    assert recovered["status"] == "CANNOT_CONFIRM" and recovered["recovery_required"]
    assert recovered["cannot_confirm"] == ["INTERRUPTED_COLLECTION_REQUIRES_RECONCILIATION"]
    assert json.loads((service.state_root / "jobs" / f"{job_id}.json").read_text())["status"] == "RUNNING"
