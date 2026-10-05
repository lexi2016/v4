"""Six-slot public CLI -> existing authority -> exact artifacts -> existing API.
Only provider transport and clock are fixtures; no fake capture/aggregator.
"""
from __future__ import annotations
import ast
import base64
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from statistics import mean, median
from urllib.parse import urlsplit, parse_qs

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-09-14"
PREV = "2026-09-11"
SLOTS = ("09:25", "09:35", "10:00", "11:30", "14:00", "15:00")
OLD_SHA = "3c9c2bc3b6d97d545ba2eeca417b116e2456c4904606aed746324d6e2cc507c5"
SAFETY = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def encode(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class IntradayTransport:
    def __init__(self, stamp):
        self.stamp = stamp
        self.calls = Counter()
        self.quote_day = DATE
        self.missing = False
        self.live_missing = False
        self.pcts = {"000001": 2.5, "600001": -5.25, "600002": 0.0}

    def ak(self, endpoint, **params):
        self.calls[(endpoint, json.dumps(params, sort_keys=True))] += 1
        if endpoint == "stock_zh_a_hist_tx":
            return pd.DataFrame({"date": ["2026-09-10", PREV, DATE]})
        if endpoint == "stock_zt_pool_em":
            if self.live_missing:
                return pd.DataFrame()
            return pd.DataFrame([{"代码": "000001", "名称": "甲", "连板数": 2, "所属行业": "甲行业"},
                                 {"代码": "600002", "名称": "丙", "连板数": 6, "所属行业": "乙行业"}])
        if endpoint in {"stock_zt_pool_zbgc_em", "stock_zt_pool_dtgc_em"}:
            return pd.DataFrame()
        raise AssertionError("unexpected endpoint: " + endpoint)

    def http_get(self, url, **params):
        from domains.research_review_generation.owned_authority import RawResponse
        self.calls[(url, "http")] += 1
        symbols = url.split("q=", 1)[1].split(",")
        lines = []
        for symbol in symbols:
            code = symbol[-6:]
            if code != "600000" and (self.missing or code not in self.pcts):
                continue
            fields = ["0"] * 34
            fields[0] = f'v_{symbol}="1'
            fields[1] = code
            fields[30] = self.quote_day.replace("-", "") + self.stamp.strftime("%H%M%S")
            fields[32] = str(self.pcts.get(code, 1.0))
            lines.append("~".join(fields) + '";')
        return RawResponse("".join(lines).encode("gbk"))


def fixture_config(tmp_path, slot="09:25"):
    stamp = datetime.fromisoformat(DATE + "T" + slot + ":30+08:00")
    state = tmp_path / "state"; cache = state / "data"
    cache.mkdir(parents=True)
    previous = {"zt": [{"code": "000001", "name": "甲", "boards": 1, "sector": "甲行业"},
                       {"code": "600001", "name": "乙", "boards": 2, "sector": "乙行业"},
                       {"code": "600002", "name": "丙", "boards": 5, "sector": "乙行业"},
                       {"code": "600003", "name": "丁", "boards": 5, "sector": "甲行业"}],
                "zb": [], "dt": [], "raw": {"zt": [], "zb": [], "dt": []}}
    name = "cache/market_facts/" + PREV + ".json"
    raw = encode({"schema": 3, "date": PREV, "pools": previous})
    path = cache / name; path.parent.mkdir(parents=True); path.write_bytes(raw)
    inventory = state / "cache-inventory.json"
    inventory.write_bytes(encode({"schema": "v4.vibe_cache_inventory.v1", "files": {name: {"bytes": len(raw), "sha256": sha(raw)}}}))
    manifest = ROOT / "domains/research_review_generation/OWNED_SOURCE_MANIFEST.json"
    code_sha = sha(manifest.read_bytes())
    config = {"schema": "v4.intraday_bindings.v1", "state_root": str(state), "cache_root": str(cache),
              "cache_manifest_path": str(inventory), "cache_manifest_sha256": sha(inventory.read_bytes()),
              "source_id": "V4_OWNED_ORIGINAL_VIBE_DATA", "source_manifest_sha256": code_sha,
              "input_bindings": {}}
    path = tmp_path / "intraday.json"; path.write_bytes(encode(config))
    return path, sha(path.read_bytes()), code_sha, IntradayTransport(stamp), stamp, previous


def invoke(path, pin, code, transport, stamp, slot="09:25", date=DATE):
    from ops.run_intraday_research import main
    return main(["--date", date.replace("-", ""), "--slot", slot.replace(":", ""), "--config", str(path),
                 "--config-sha256", pin, "--source-manifest-sha256", code], transport=transport, clock=lambda: stamp)


def original_aggregate(previous, live, pcts, slot, stamp):
    """Execute the frozen original pure aggregation statements, not a rewritten golden formula."""
    old = ROOT.parent / "input/vibe_reference/duanxian/intraday.py"
    raw = old.read_bytes()
    assert sha(raw) == OLD_SHA
    capture = next(n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == "capture")
    def assignment(node, name):
        return isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
    start = next(i for i,n in enumerate(capture.body) if assignment(n, "live_counts"))
    end = next(i for i,n in enumerate(capture.body) if assignment(n, "snap"))
    # Original empty-data `return` is kept in a function so its AST is valid.
    function = ast.FunctionDef(name="golden", args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),
                               body=capture.body[start:end+1] + [ast.Return(value=ast.Name(id="snap", ctx=ast.Load()))], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    ns = {"pp": previous, "live": live, "batch_pct": lambda _: pcts, "mean": mean, "median": median,
          "date": DATE, "slot": slot, "now": stamp, "prev": PREV, "drift": 0, "_SNAP_SCHEMA": 3}
    exec(compile(module, str(old), "exec"), ns)
    return ns["golden"]()


@pytest.mark.parametrize("slot", SLOTS)
def test_public_cli_original_aggregate_parity_and_api(tmp_path, capsys, slot):
    path, pin, code, transport, stamp, previous = fixture_config(tmp_path, slot)
    assert invoke(path, pin, code, transport, stamp, slot) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    from domains.intraday_research import read_intraday_day
    state = tmp_path / "state"
    view = read_intraday_day("20260914", intraday_root=state / "intraday")
    assert view["status"] == "READY" and len(view["slots"]) == 1
    snap = view["slots"][0]
    live = {"zt": [{"boards": 2, "sector": "甲行业"}, {"boards": 6, "sector": "乙行业"}], "zb": [], "dt": []}
    assert {k: snap[k] for k in original_aggregate(previous, live, transport.pcts, slot, stamp)} == original_aggregate(previous, live, transport.pcts, slot, stamp)
    assert snap["coverage_rate"] == .75 and snap["expected_sample"] == 4
    assert len(view["missing_slots"]) == 5
    assert out["artifact_sha256"] == view["evidence"][0]["artifact_sha256"]
    for field in SAFETY: assert out[field] is False
    from apps.api.v35_api.review_router import create_review_router
    app = FastAPI(); app.include_router(create_review_router(tmp_path / "data", review_root=state / "reviews", intraday_root=state / "intraday"))
    before = {str(f): sha(f.read_bytes()) for f in state.rglob("*.json")}
    response = TestClient(app).get("/api/v3/review?date=20260914")
    assert response.status_code == 200 and response.json()["intraday_research"]["slots"] == view["slots"]
    assert before == {str(f): sha(f.read_bytes()) for f in state.rglob("*.json")}
    assert view["path"]["points"][0]["slot"] == slot
    assert view["auction"]["available"] is (slot == "09:25")
    assert not any("stock_zt_pool" in key[0] and PREV.replace("-", "") in key[1] for key in transport.calls)
    # quote reference, calendar, three live pools, previous cohort quotes.
    assert sum(transport.calls.values()) == 6


@pytest.mark.parametrize("case", ["cross_day", "before", "late", "holiday", "no_quotes", "wrong_sha", "wrong_code", "bad_cache"])
def test_intraday_rejects_invalid_date_source_or_missing_quotes(tmp_path, capsys, case):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    day = DATE
    if case == "cross_day": day = PREV
    if case == "before": stamp -= timedelta(minutes=1)
    if case == "late": stamp += timedelta(minutes=9)
    if case == "holiday": transport.quote_day = PREV
    if case == "no_quotes": transport.missing = True
    if case == "wrong_sha": pin = "0" * 64
    if case == "wrong_code": code = "0" * 64
    if case == "bad_cache": (tmp_path / "state/data/cache/market_facts" / (PREV + ".json")).write_text("{}")
    assert invoke(path, pin, code, transport, stamp, date=day) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "CANNOT_CONFIRM"
    assert not list((tmp_path / "state/intraday/artifacts").glob("**/*.json"))
    if case in {"cross_day", "before", "late", "wrong_sha", "wrong_code", "bad_cache"}: assert not transport.calls


def test_eight_minute_boundary_and_missing_live_counts(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    transport.live_missing = True; stamp += timedelta(minutes=8); transport.stamp = stamp
    assert invoke(path, pin, code, transport, stamp) == 0
    from domains.intraday_research import read_intraday_day
    view = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday")
    assert view["slots"][0]["drift_minutes"] == 8 and view["slots"][0]["live"] is None
    assert "LIVE_POOL_UNAVAILABLE" in view["cannot_confirm"]


def test_duplicate_concurrent_requests_share_single_committed_capture(tmp_path):
    from domains.intraday_research import capture_intraday
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    def run(): return capture_intraday("20260914", "0925", config_path=path, config_sha256=pin,
        source_manifest_sha256=code, transport=transport, clock=lambda: stamp)
    with ThreadPoolExecutor(max_workers=6) as pool: results = list(pool.map(lambda _: run(), range(6)))
    assert sum(r["status"] == "SUCCEEDED" for r in results) == 1
    assert sum(r["status"] == "ALREADY_EXISTS" for r in results) == 5
    assert sum(transport.calls.values()) == 6
    assert len({r["artifact_sha256"] for r in results}) == 1


def test_failed_attempt_not_reacquired(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path); transport.missing = True
    assert invoke(path, pin, code, transport, stamp) == 2
    before = transport.calls.copy(); transport.missing = False
    assert invoke(path, pin, code, transport, stamp) == 2 and transport.calls == before
    marker = json.loads(
        (tmp_path / "state/intraday/attempts/2026-09-14/0925.json").read_bytes()
    )
    assert marker["attempt_state"] == "REQUEST_ATTEMPTED"


def test_failed_no_request_can_retry_without_reacquiring_transport(tmp_path, capsys):
    from domains.intraday_research import _acquire, load_intraday_binding

    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    cfg = load_intraday_binding(path, pin, code)
    inputs = _acquire(cfg, DATE, "09:25", stamp, transport=transport, clock=lambda: stamp)
    raw = encode(inputs)
    binding_path = "inputs/retryable-exact.json"
    body = json.loads(path.read_bytes())
    body["input_bindings"][DATE + "/0925"] = {
        "path": binding_path,
        "bytes": len(raw),
        "sha256": sha(raw),
    }
    path.write_bytes(encode(body))
    pin = sha(path.read_bytes())
    transport.calls.clear()

    assert invoke(path, pin, code, transport, stamp) == 2
    assert not transport.calls
    marker_path = tmp_path / "state/intraday/attempts/2026-09-14/0925.json"
    assert json.loads(marker_path.read_bytes())["attempt_state"] == "FAILED_NO_REQUEST"

    destination = tmp_path / "state/intraday" / binding_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    assert invoke(path, pin, code, transport, stamp) == 0
    assert not transport.calls
    assert json.loads(marker_path.read_bytes())["attempt_state"] == "SUCCEEDED"
    states = [
        json.loads(item.read_bytes())["attempt_state"]
        for item in sorted(
            (tmp_path / "state/intraday/attempts/events").rglob("*.json")
        )
    ]
    assert states == ["PREPARED", "FAILED_NO_REQUEST", "PREPARED", "SUCCEEDED"]


def test_legacy_started_marker_is_uncertain_and_never_reacquired(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    marker = tmp_path / "state/intraday/attempts/2026-09-14/0925.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(
        encode(
            {
                "schema": "v4.intraday_attempt.v1",
                "date": "2026-09-14",
                "slot": "09:25",
                "status": "STARTED",
                "config_sha256": pin,
            }
        )
    )

    assert invoke(path, pin, code, transport, stamp) == 2
    assert not transport.calls
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["attempt_state"] == "ATTEMPT_UNKNOWN"


def test_malformed_marker_is_uncertain_and_never_reacquired(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    marker = tmp_path / "state/intraday/attempts/2026-09-14/0925.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(b"{")

    assert invoke(path, pin, code, transport, stamp) == 2
    assert not transport.calls
    output = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert output["error_code"] == "INTRADAY_ATTEMPT_UNKNOWN"
    assert output["attempt_state"] == "ATTEMPT_UNKNOWN"


def test_source_drift_reader_refuses_without_fetching(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    assert invoke(path, pin, code, transport, stamp) == 0
    from domains.intraday_research import read_intraday_day
    raw = next((tmp_path / "state/raw").glob("*.json")); raw.write_text("{}")
    before = transport.calls.copy()
    result = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday")
    assert result["status"] == "CANNOT_CONFIRM" and result["slots"] == [] and transport.calls == before


def test_symlink_output_refuses_no_outside_writes(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    outside = tmp_path / "outside"; outside.mkdir(); (tmp_path / "state/intraday").symlink_to(outside, target_is_directory=True)
    assert invoke(path, pin, code, transport, stamp) == 2
    assert not list(outside.iterdir()) and not transport.calls


def test_input_scope_different_slots_do_not_reuse_live_requests(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    assert invoke(path, pin, code, transport, stamp) == 0
    stamp += timedelta(minutes=10); transport.stamp = stamp
    assert invoke(path, pin, code, transport, stamp, "09:35") == 0
    from domains.intraday_research import read_intraday_day
    view = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday")
    assert [s["slot"] for s in view["slots"]] == ["09:25", "09:35"]
    assert sum(transport.calls.values()) == 12


def test_no_daily_generation_scheduler_and_single_replacement_workload():
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.executor_registry import ALLOWED_WORKLOAD_IDS
    catalog = load_workload_catalog()
    matches = [w for w in catalog.workloads if w.workload_id == "v4_intraday_research"]
    assert len(matches) == 1 and matches[0].slots == tuple(s.replace(":", "") for s in SLOTS)
    assert "v4_intraday_research" in ALLOWED_WORKLOAD_IDS
    assert not any("research_review_generation" in w.workload_id for w in catalog.workloads)


def test_precollected_exact_input_reused_with_zero_transport(tmp_path, capsys):
    from domains.intraday_research import load_intraday_binding, _acquire
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    cfg = load_intraday_binding(path, pin, code)
    inputs = _acquire(cfg, DATE, "09:25", stamp, transport=transport, clock=lambda: stamp)
    # Existing owner captured this exact date/slot/source before publication.
    # Bind its bytes explicitly; do not invent a successful final snapshot.
    raw = encode(inputs); dest = tmp_path / "state/intraday/inputs/shared-exact.json"
    dest.parent.mkdir(parents=True); dest.write_bytes(raw)
    body = json.loads(path.read_bytes())
    body["input_bindings"][DATE + "/0925"] = {"path": "inputs/shared-exact.json", "bytes": len(raw), "sha256": sha(raw)}
    path.write_bytes(encode(body)); pin = sha(path.read_bytes())
    transport.calls.clear()
    assert invoke(path, pin, code, transport, stamp) == 0
    assert not transport.calls


def test_precollected_wrong_slot_never_falls_back_to_live(tmp_path, capsys):
    from domains.intraday_research import load_intraday_binding, _acquire
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    cfg = load_intraday_binding(path, pin, code)
    inputs = _acquire(cfg, DATE, "09:25", stamp, transport=transport, clock=lambda: stamp)
    raw = encode(inputs); dest = tmp_path / "state/intraday/inputs/shared-exact.json"
    dest.parent.mkdir(parents=True); dest.write_bytes(raw)
    body = json.loads(path.read_bytes())
    body["input_bindings"][DATE + "/0935"] = {"path": "inputs/shared-exact.json", "bytes": len(raw), "sha256": sha(raw)}
    path.write_bytes(encode(body)); pin = sha(path.read_bytes())
    transport.calls.clear(); stamp += timedelta(minutes=10)
    assert invoke(path, pin, code, transport, stamp, "09:35") == 2
    assert not transport.calls


def test_current_daily_cache_is_not_an_intraday_quote_or_live_pool(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path, "15:00")
    cfg = json.loads(path.read_bytes()); cache = Path(cfg["cache_root"])
    name = "cache/market_facts/" + DATE + ".json"
    daily = {"schema": 3, "date": DATE, "pools": {"zt": [{"code": "600999", "name": "不得复用的日终数据", "boards": 99, "sector": "错误"}],
              "zb": [], "dt": [], "raw": {"zt": [{"代码": "600999", "名称": "错误", "连板数": 99}], "zb": [], "dt": []}}}
    raw = encode(daily); (cache / name).write_bytes(raw)
    inv = Path(cfg["cache_manifest_path"]); inventory = json.loads(inv.read_bytes())
    inventory["files"][name] = {"bytes": len(raw), "sha256": sha(raw)}; inv.write_bytes(encode(inventory))
    cfg["cache_manifest_sha256"] = sha(inv.read_bytes()); path.write_bytes(encode(cfg)); pin = sha(path.read_bytes())
    stamp += timedelta(minutes=6); transport.stamp = stamp
    assert invoke(path, pin, code, transport, stamp, "15:00") == 0
    from domains.intraday_research import read_intraday_day
    snap = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday")["slots"][0]
    assert snap["live"]["highest_board"] == 6
    assert (cache / name).read_bytes() == raw
    assert sum(transport.calls.values()) == 6


def test_reference_day_current_but_one_cohort_quote_stale_refused(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    original = transport.http_get
    def stale_one(url, **kwargs):
        reply = original(url, **kwargs)
        if url.endswith("sh600000"): return reply
        reply.content = reply.content.replace(b"20260914", b"20260911", 1)
        return reply
    transport.http_get = stale_one  # transport fixture only, not a global data/graph patch
    assert invoke(path, pin, code, transport, stamp) == 2
    assert not list((tmp_path / "state/intraday/artifacts").glob("**/*.json"))


def test_acquisition_finishes_outside_eight_minutes_no_artifact(tmp_path, capsys):
    from domains.intraday_research import capture_intraday
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    times = iter([stamp, stamp + timedelta(minutes=9)])
    with pytest.raises(ValueError, match="WINDOW"):
        capture_intraday("20260914", "0925", config_path=path, config_sha256=pin,
            source_manifest_sha256=code, transport=transport, clock=lambda: next(times))
    assert not list((tmp_path / "state/intraday/artifacts").glob("**/*.json"))


def test_weekend_refused_before_transport(tmp_path, capsys):
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    stamp = datetime.fromisoformat("2026-09-12T09:25:30+08:00")
    assert invoke(path, pin, code, transport, stamp, date="2026-09-12") == 2
    assert not transport.calls


def test_registry_executes_public_cli_and_independently_checks_receipt(tmp_path, monkeypatch):
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from ops.run_intraday_research import main
    import contextlib, io, subprocess
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    for key, val in {"V4_INTRADAY_CONFIG_PATH": str(path), "V4_INTRADAY_CONFIG_SHA256": pin,
                     "V4_INTRADAY_SOURCE_MANIFEST_SHA256": code}.items(): monkeypatch.setenv(key, val)
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        assert command[1:3] == ["-m", "ops.run_intraday_research"]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = main(command[3:], transport=transport, clock=lambda: stamp)
        return subprocess.CompletedProcess(command, rc, output.getvalue(), "")
    registry = FixedExecutorRegistry(tmp_path / "data", runner=runner)
    workload = next(w for w in load_workload_catalog().workloads if w.workload_id == "v4_intraday_research")
    request = DispatchRequest("20260914", "20260914", "20260914", "0925", DispatchMode.LIVE)
    result = registry(workload, request)
    assert result["status"] == "SUCCEEDED" and result["receipt_verified"] is True
    assert sum(transport.calls.values()) == 6 and len(calls) == 1
    result = registry(workload, request)
    assert result["capture_status"] == "ALREADY_EXISTS" and sum(transport.calls.values()) == 6
    # Same code route, but stdout hash corrupted after real publication.
    actual_runner = registry._runner
    def corrupt(command, **kwargs):
        result = actual_runner(command, **kwargs)
        obj = json.loads(result.stdout); obj["artifact_sha256"] = "0" * 64
        return subprocess.CompletedProcess(command, 0, json.dumps(obj), "")
    registry._runner = corrupt
    with pytest.raises(WorkloadExecutionError): registry(workload, request)


def test_registry_missing_binding_and_backfill_never_launch(tmp_path, monkeypatch):
    from infrastructure.scheduling.catalog import load_workload_catalog
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry, WorkloadExecutionError
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    calls = []
    registry = FixedExecutorRegistry(tmp_path / "data", runner=lambda *a, **k: calls.append(a))
    workload = next(w for w in load_workload_catalog().workloads if w.workload_id == "v4_intraday_research")
    monkeypatch.delenv("V4_INTRADAY_CONFIG_PATH", raising=False)
    with pytest.raises(WorkloadExecutionError):
        registry(workload, DispatchRequest("20260914", "20260914", "20260914", "0925", DispatchMode.LIVE))
    with pytest.raises(WorkloadExecutionError):
        registry(workload, DispatchRequest("20260914", "20260911", "20260911", "0925", DispatchMode.BACKFILL))
    assert not calls


@pytest.mark.parametrize(
    ("state", "expected_class"),
    (
        ("FAILED_NO_REQUEST", "INTRADAY_NO_REQUEST"),
        ("REQUEST_ATTEMPTED", "INTRADAY_REQUEST_ATTEMPTED"),
        ("ATTEMPT_UNKNOWN", "INTRADAY_ATTEMPT_UNKNOWN"),
    ),
)
def test_registry_preserves_intraday_attempt_outcome_for_retry_policy(
    tmp_path, state, expected_class
):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry

    registry = FixedExecutorRegistry(tmp_path / "data", runner=lambda *a, **k: None)
    result = registry._classify_intraday_failure(
        {
            "status": "FAILED",
            "exit_code": 2,
            "stdout": json.dumps({
                "status": "CANNOT_CONFIRM",
                "error_code": "INTRADAY_CAPTURE_WINDOW_REFUSED",
                "attempt_state": state,
            }),
            "stderr": "",
        }
    )
    assert result["failure_class"] == expected_class
    assert result["attempt_state"] == state


@pytest.mark.parametrize("state", ["REQUEST_ATTEMPTED", "REQUEST_IN_FLIGHT", "ATTEMPT_UNKNOWN", ""])
def test_registry_rejects_conflicting_no_request_envelope(tmp_path, state):
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from ops import run_v35_macos_scheduler as scheduler

    registry = FixedExecutorRegistry(tmp_path / "data", runner=lambda *a, **k: None)
    result = registry._classify_intraday_failure(
        {
            "status": "FAILED",
            "exit_code": 2,
            "stdout": json.dumps({
                "status": "CANNOT_CONFIRM",
                "error_code": "INTRADAY_NO_REQUEST",
                "attempt_state": state,
            }),
            "stderr": "",
        }
    )
    assert result["failure_class"] == "INTRADAY_ATTEMPT_UNKNOWN"
    assert result["attempt_state"] == (state or "ATTEMPT_UNKNOWN")
    receipt_dir = tmp_path / "ledger" / "receipts" / "live" / "20260914" / "0925"
    receipt_dir.mkdir(parents=True)
    (receipt_dir / "conflict.dispatch-receipt.json").write_text(
        json.dumps(
            {
                "status": "FAILED",
                "failure_class": result["failure_class"],
                "finished_at": "2026-09-14T01:00:00Z",
                "workload_results": [
                    {
                        "workload_id": "v4_intraday_research",
                        "status": "FAILED",
                        "failure_class": result["failure_class"],
                        "attempt_state": result["attempt_state"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert scheduler._slot_blocks_retry(
        tmp_path / "ledger",
        "20260914",
        "0925",
        moment=datetime.fromisoformat("2026-09-14T09:30:00+08:00"),
    ) is True

@pytest.mark.parametrize("field,value", [("source_manifest_sha256", "0" * 64),
                                          ("cache_root", "DIFFERENT_CACHE")])
def test_bound_input_wrong_source_refused_before_artifact(tmp_path, capsys, field, value):
    from domains.intraday_research import load_intraday_binding, _acquire
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    cfg = load_intraday_binding(path, pin, code)
    inputs = _acquire(cfg, DATE, "09:25", stamp, transport=transport, clock=lambda: stamp)
    if value == "DIFFERENT_CACHE":
        import shutil
        other = tmp_path / "state/other-data"
        shutil.copytree(Path(cfg["cache_root"]), other)
        value = str(other)
    inputs[field] = value
    raw = encode(inputs); dest = tmp_path / "state/intraday/inputs/shared-exact.json"
    dest.parent.mkdir(parents=True); dest.write_bytes(raw)
    body = json.loads(path.read_bytes())
    body["input_bindings"][DATE + "/0925"] = {"path": "inputs/shared-exact.json", "bytes": len(raw), "sha256": sha(raw)}
    path.write_bytes(encode(body)); pin = sha(path.read_bytes()); transport.calls.clear()
    assert invoke(path, pin, code, transport, stamp) == 2
    assert not list((tmp_path / "state/intraday/artifacts").glob("**/*.json"))
    assert not transport.calls


def test_exact_artifact_reference_does_not_accept_name_suffix(tmp_path):
    from domains.intraday_research import _bound
    from infrastructure.owned_io import SafeRoot
    io = SafeRoot(tmp_path)
    raw = encode({"date": DATE})
    io.write_bytes("artifacts/2026-09-14/0925.json.extra", raw)
    with pytest.raises(ValueError, match="BINDING"):
        _bound(io, {"path": "artifacts/2026-09-14/0925.json.extra", "bytes": len(raw), "sha256": sha(raw)},
               "artifacts/2026-09-14/0925.json")


def test_manifest_publication_failure_never_reads_ready_or_reacquires(tmp_path, monkeypatch, capsys):
    from infrastructure.owned_io import SafeRoot
    from domains.intraday_research import read_intraday_day
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    original = SafeRoot.write_bytes
    def injected_disk_failure(self, relative, payload, **kwargs):
        if str(relative).startswith("manifests/"):
            raise OSError("synthetic disk failure")
        return original(self, relative, payload, **kwargs)
    with monkeypatch.context() as local:
        local.setattr(SafeRoot, "write_bytes", injected_disk_failure)
        assert invoke(path, pin, code, transport, stamp) == 2
    assert not list((tmp_path / "state/intraday/receipts").glob("**/*.json"))
    view = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday")
    assert view["status"] == "CANNOT_CONFIRM"
    count = transport.calls.copy()
    assert invoke(path, pin, code, transport, stamp) == 2 and transport.calls == count


def test_partial_quote_coverage_explicitly_reported(tmp_path, capsys):
    from domains.intraday_research import read_intraday_day
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    assert invoke(path, pin, code, transport, stamp) == 0
    view = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday")
    assert "QUOTE_COVERAGE_PARTIAL:09:25" in view["cannot_confirm"]
    assert view["slots"][0]["coverage_rate"] == .75


@pytest.mark.parametrize("alter", ["live_projection", "missing_calendar"])
def test_precollected_input_must_match_raw_pool_and_calendar(tmp_path, capsys, alter):
    from domains.intraday_research import load_intraday_binding, _acquire
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    inputs = _acquire(load_intraday_binding(path, pin, code), DATE, "09:25", stamp,
                      transport=transport, clock=lambda: stamp)
    if alter == "live_projection":
        inputs["live_pool"]["zt"][0]["boards"] = 99
    else:
        inputs["raw_sources"] = [ref for ref in inputs["raw_sources"]
            if json.loads((tmp_path / "state" / ref["path"]).read_bytes())["identity"]["endpoint"] != "stock_zh_a_hist_tx"]
    raw = encode(inputs); dest = tmp_path / "state/intraday/inputs/shared-exact.json"
    dest.parent.mkdir(parents=True); dest.write_bytes(raw)
    body = json.loads(path.read_bytes())
    body["input_bindings"][DATE + "/0925"] = {"path": "inputs/shared-exact.json", "bytes": len(raw), "sha256": sha(raw)}
    path.write_bytes(encode(body)); pin = sha(path.read_bytes()); transport.calls.clear()
    assert invoke(path, pin, code, transport, stamp) == 2
    assert not list((tmp_path / "state/intraday/artifacts").glob("**/*.json"))
    assert not transport.calls


def test_auction_reads_previous_exact_review_conditions_without_generation(tmp_path, capsys):
    from domains.research_review_generation import write_exact_review
    from test_research_review_generation import _payload
    from domains.intraday_research import read_intraday_day
    path, pin, code, transport, stamp, _ = fixture_config(tmp_path)
    payload = _payload(PREV)
    payload["focus"] = {"verification_items": [{"metric": "money_effect_median", "direction": "up"},
                                               {"metric": "broken_rate", "direction": "down"}]}
    reviews = tmp_path / "state/reviews"
    write_exact_review(reviews, PREV.replace("-", ""), payload, mode="READ_ONLY_PREVIOUS_ARTIFACT_FIXTURE")
    assert invoke(path, pin, code, transport, stamp) == 0
    before = transport.calls.copy()
    view = read_intraday_day("20260914", intraday_root=tmp_path / "state/intraday", review_root=reviews)
    early = view["auction"]["verification_early"]
    assert view["auction"]["prev_date"] == PREV and view["auction"]["previous_review_status"] == "READY"
    assert early[0]["early_value"] == view["slots"][0]["median"]
    assert early[1]["early_value"] is None and early[1]["note"] == "该指标要等盘中/收盘才有读数"
    assert transport.calls == before


def test_two_processes_share_one_slot_capture(tmp_path):
    import subprocess, sys
    path, pin, code, _, stamp, _ = fixture_config(tmp_path)
    worker = '''
import contextlib,io,json,sys
from datetime import datetime
from test_v4_intraday_research import IntradayTransport
from ops.run_intraday_research import main
stamp=datetime.fromisoformat("2026-09-14T09:25:30+08:00")
transport=IntradayTransport(stamp); out=io.StringIO()
with contextlib.redirect_stdout(out):
    rc=main(sys.argv[1:],transport=transport,clock=lambda:stamp)
print(json.dumps({"rc":rc,"result":json.loads(out.getvalue()),"transport_calls":sum(transport.calls.values())}))
raise SystemExit(rc)
'''
    command = [sys.executable, "-c", worker, "--date", "20260914", "--slot", "0925",
               "--config", str(path), "--config-sha256", pin, "--source-manifest-sha256", code]
    processes = [subprocess.Popen(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
    records = []
    for process in processes:
        output, error = process.communicate(timeout=30)
        assert process.returncode == 0, error
        records.append(json.loads(output))
    assert sorted(row["result"]["status"] for row in records) == ["ALREADY_EXISTS", "SUCCEEDED"]
    assert sum(row["transport_calls"] for row in records) == 6
    assert len({row["result"]["artifact_sha256"] for row in records}) == 1
