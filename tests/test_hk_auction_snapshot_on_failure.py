"""Auction-only native failure retention; original shared gates, fake provider."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops import run_hkconnect_0915_0920_capture as auction

DATE = "20261023"
CODES = [f"HK.{index:05d}" for index in range(1, 101)]


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    package = Path(os.environ["AUCTION_SHARED_PACKAGE_ROOT"])
    module, _ = auction._load_shared(package)
    members = [{"code": code, "name": code, "preselect_rank": index} for index, code in enumerate(CODES, 1)]
    monkeypatch.setattr(module, "load_verified_candidates", lambda *_: (members, {
        "signal_date": "20261022", "d1_pool_sha256": "a" * 64, "d1_run_id": "same-target-verified"}))
    consumer = SimpleNamespace(StoreError=module.StoreError,
        read_verified_latest=lambda *_: (_ for _ in ()).throw(module.StoreError("not published")))
    monkeypatch.setattr(auction, "_calendar_gate", lambda _: {"status": "ELIGIBLE"})
    monkeypatch.setattr(auction.time, "sleep", lambda _: None)
    monkeypatch.setattr(module, "_test_frozen_run_capture", module.run_capture, raising=False)
    return module, consumer


def invoke(tmp_path, monkeypatch, bridge, mode):
    module, consumer = bridge
    original_run = module._test_frozen_run_capture
    # Each invocation gets an independent clock; no quote process is launched.
    values = (["09:19:10", "09:19:10", "09:20:00"] if mode == "late" else
              ["09:19:10", "09:19:10", "09:19:10", "09:20:00"] if mode in {"coverage", "parse", "exception", "timeout"} else
              ["09:19:10", "09:19:10", "09:19:10", "09:19:40", "09:19:40", "09:20:00"])
    ticks = iter(datetime.fromisoformat(f"2026-10-23 {clock}") for clock in values)
    def run(store, date, python, **kwargs):
        return original_run(store, date, python, now=lambda: next(ticks), **kwargs)
    monkeypatch.setattr(module, "run_capture", run)
    monkeypatch.setattr(module, "publish_reference_rows", lambda *_args, **_kwargs: {"status": "READY", "run_id": "frozen-top50"})
    originals = []
    def provider(command, **kwargs):
        assert json.loads(kwargs["input"])["codes"] == CODES
        if mode == "exception":
            raise ConnectionError("provider had no bytes")
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 1, output=b'{"partial":', stderr=b"timeout")
        row_codes = CODES[:2] if mode == "partial" else CODES
        rows = [{"code": code, "update_time": "2026-10-23 09:19:09", "last_price": 10,
                 "prev_close_price": 9, "bid_price": 9.9, "ask_price": 10, "bid_vol": 100,
                 "ask_vol": 100, "turnover": 100000, "native_extra": "原生字段"} for code in row_codes]
        stdout = "malformed-native" if mode == "parse" else module.MARKER + json.dumps({"rows": rows, "errors": []}, ensure_ascii=False)
        originals.append(stdout.encode())
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
    monkeypatch.setattr(auction.subprocess, "run", provider)
    with pytest.raises(Exception) as raised:
        auction.materialize_hkconnect_0915_0920(tmp_path / "data", tmp_path / "shared", Path("/unused/package"), DATE,
            Path(sys.executable), shared_module=module, consumer_module=consumer)
    return raised.value, originals


def events(error):
    refs = error.auction_native_evidence
    result = []
    for ref in refs:
        raw = Path(ref["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == ref["sha256"]
        result.append((ref, json.loads(raw)))
    return result


def test_canary_native_retained_before_real_bridge_parse_failure(tmp_path, monkeypatch, bridge):
    error, originals = invoke(tmp_path, monkeypatch, bridge, "parse")
    stored = events(error)
    native = next(data for ref, data in stored if ref["event"] == "native")
    assert base64.b64decode(native["stdout_base64"]) == originals[0]
    assert native["stdout_sha256"] == hashlib.sha256(originals[0]).hexdigest()
    assert stored[0][0]["event"] == "query"
    assert stored[-1][0]["event"] == "capture-error"
    assert native["membership"]["d1_pool_sha256"] == "a" * 64
    assert native["codes"] == CODES
    assert native["market"] == "HK_CONNECT" and native["stage_id"] == "STAGE_0925"
    assert native["trade_date"] == DATE
    assert native["provider_started_at"] <= native["provider_finished_at"]
    # Historical market time stays inside the original native payload; capture
    # timestamps come from the actual wall clock, never this fake source clock.
    assert native["provider_started_at"] != "2026-10-23T09:19:10+08:00"
    assert native["authorizes_selection"] is False


@pytest.mark.parametrize("mode,reason", [
    ("coverage", "CONTINUOUS_COVERAGE"),
    ("partial", "reference shortfall"),
    ("late", "CONTINUOUS_COVERAGE"),
    ("projection", "not published"),
])
def test_real_coverage_top50_and_later_projection_failures_keep_native(tmp_path, monkeypatch, bridge, mode, reason):
    error, originals = invoke(tmp_path, monkeypatch, bridge, mode)
    assert reason in str(error)
    stored = events(error)
    native = [data for ref, data in stored if ref["event"] == "native"]
    assert [base64.b64decode(data["stdout_base64"]) for data in native] == originals
    assert all(data["authorizes_selection"] is False for _, data in stored)
    assert not (tmp_path / "data" / "opening_second_filter").exists()


@pytest.mark.parametrize("mode", ["exception", "timeout"])
def test_provider_failure_records_query_error_and_only_actual_partial_bytes(tmp_path, monkeypatch, bridge, mode):
    error, originals = invoke(tmp_path, monkeypatch, bridge, mode)
    stored = events(error)
    assert originals == []
    assert [ref["event"] for ref, _ in stored] == ["query", "provider-error", "capture-error"]
    failure = stored[1][1]
    assert "stdout_base64" not in failure if mode == "exception" else base64.b64decode(failure["output_base64"]) == b'{"partial":'
    assert all(data[flag] is False for _, data in stored for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_late_retry_never_overwrites_earlier_native_attempt(tmp_path, monkeypatch, bridge):
    error, _ = invoke(tmp_path, monkeypatch, bridge, "coverage")
    previous = {ref["path"]: Path(ref["path"]).read_bytes() for ref in error.auction_native_evidence}
    late, _ = invoke(tmp_path, monkeypatch, bridge, "late")
    assert all(Path(path).read_bytes() == raw for path, raw in previous.items())
    assert set(previous).isdisjoint(ref["path"] for ref in late.auction_native_evidence)


def test_wrong_date_cannot_escape_owned_root(tmp_path):
    with pytest.raises(ValueError):
        auction._AuctionNativeEvidence(tmp_path / "shared", "../../20261023")
    assert not (tmp_path / "shared").exists()


def test_main_failure_output_links_durable_native_attempts(tmp_path, monkeypatch, bridge, capsys):
    error, _ = invoke(tmp_path, monkeypatch, bridge, "coverage")
    monkeypatch.setattr(auction, "materialize_hkconnect_0915_0920", lambda *_: (_ for _ in ()).throw(error))
    code = auction.main(["--data-root", str(tmp_path / "data"), "--shared-data-root", str(tmp_path / "shared"),
        "--shared-package-root", "/unused/package", "--trade-date", DATE, "--futu-python", sys.executable])
    output = json.loads(capsys.readouterr().out)
    assert code == 1 and output["status"] == "CANNOT_CONFIRM"
    assert output["auction_native_evidence"] == error.auction_native_evidence
