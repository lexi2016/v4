"""Manager 15:55 mode is reuse-only for the Futu-owned security master."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import scripts.run_scheduled_stage_bundle as stage_runner


TRADE_DATE = "20260806"
HK = ZoneInfo("Asia/Hong_Kong")


def _ready_universe(*_args):
    return {
        "ok": True,
        "status": "READY",
        "row_count": 651,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "artifact": {
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    }


def _run(root: Path, python: Path, *, bundle_runner, security_master_runner):
    return stage_runner.run_scheduled_stage_bundle(
        root,
        TRADE_DATE,
        "STAGE_1545_1555",
        now=datetime(2026, 8, 6, 15, 56, tzinfo=HK),
        python_path=python,
        bundle_runner=bundle_runner,
        security_master_runner=security_master_runner,
        universe_runner=_ready_universe,
    )


def test_manager_mode_reuses_exact_master_and_never_calls_futu_runners(tmp_path, monkeypatch):
    root = tmp_path / "store"
    python = tmp_path / "python"
    python.write_bytes(b"")
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", "PYTDX_LATE_OBSERVATION")
    monkeypatch.setattr(stage_runner, "evaluate_a_share_trade_date", lambda _date: {"eligible": True})
    futu_calls = []
    bundle_calls = []

    def exact_existing_master(_root, _date, _python, *, collector):
        assert callable(collector)
        return {"ok": True, "status": "READY", "reused": True, "row_count": 651}

    monkeypatch.setattr(stage_runner, "ensure_hk_security_master", exact_existing_master)

    def forbidden_futu(*_args, **_kwargs):
        futu_calls.append("futu")
        raise AssertionError("manager PyTDX 15:55 must not start a Futu owner")

    def bundle(*args):
        bundle_calls.append(args)
        return {"ok": True, "status": "READY", "bundle_id": "bundle-1"}

    result = _run(root, python, bundle_runner=bundle, security_master_runner=forbidden_futu)

    assert result["status"] == "READY", json.dumps(result, sort_keys=True)
    assert result["hk_security_master"]["reused"] is True
    assert result["bundle"]["bundle_id"] == "bundle-1"
    assert futu_calls == []
    assert len(bundle_calls) == 1


def test_manager_mode_reports_missing_master_without_futu_or_bundle(tmp_path, monkeypatch):
    root = tmp_path / "store"
    python = tmp_path / "python"
    python.write_bytes(b"")
    monkeypatch.setenv("V4_MANAGER_CLOSE_CAPTURE_MODE", "PYTDX_LATE_OBSERVATION")
    monkeypatch.setattr(stage_runner, "evaluate_a_share_trade_date", lambda _date: {"eligible": True})
    futu_calls = []
    bundle_calls = []

    def missing_existing_master(_root, _date, _python, *, collector):
        return collector(_python, ["HK.00001"])

    monkeypatch.setattr(stage_runner, "ensure_hk_security_master", missing_existing_master)

    def forbidden_futu(*_args, **_kwargs):
        futu_calls.append("futu")
        raise AssertionError("Futu network must remain disabled")

    def bundle(*args):
        bundle_calls.append(args)
        return {"ok": True, "status": "READY"}

    result = _run(root, python, bundle_runner=bundle, security_master_runner=forbidden_futu)

    assert result["status"] == "FAILED"
    assert result["hk_security_master"]["status"] == "MANAGER_HK_SECURITY_MASTER_NOT_READY"
    assert "MANAGER_PYTDX_LATE_OBSERVATION_REQUIRES_EXISTING_HK_SECURITY_MASTER" in result["error"]
    assert futu_calls == []
    assert bundle_calls == []
    receipt = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert receipt["status"] == "FAILED"
    assert receipt["hk_security_master"]["status"] == "MANAGER_HK_SECURITY_MASTER_NOT_READY"
