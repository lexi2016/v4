from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from ops import macos_research_panel_daily as panel
from ops._macos_research_panel_daily_parts import hk_capture_gate
from upstreams.v3_shared_data.shared_data import hk_daily_supplement as supplement


TARGET = "20261006"


def _day_file(root: Path, code: str, day: str) -> Path:
    path = root / "vipdoc" / "ds" / "lday" / f"71#{code}.day"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(panel.HK_DAY_STRUCT.pack(
        int(day), 10.0, 11.0, 9.0, 10.5, 1000.0, 100, 0,
    ))
    return path


def _source_row(day: str, *, trade=0, amount=0):
    return {
        "datetime": f"{day[:4]}-{day[4:6]}-{day[6:]} 15:00",
        "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5,
        "trade": trade, "amount": amount,
    }


def _response(code: str, rows: list[dict]) -> dict:
    return {
        "code": code,
        "status": "RESPONSE_CAPTURED",
        "request": {
            "category": 4, "market": 71, "code": code[3:],
            "start": 0, "count": 6, "target_date": TARGET,
        },
        "request_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "request_started_at": "2026-10-07T08:00:00+00:00",
        "response_acquired_at": "2026-10-07T08:00:01+00:00",
        "request_finished_at": "2026-10-07T08:00:02+00:00",
        "returned_count": len(rows),
        "source_rows": rows,
        "response_sha256": hashlib.sha256(repr(rows).encode()).hexdigest(),
    }


def test_low_level_fetch_is_category4_market71_and_keeps_raw_request_receipts():
    class Api:
        disconnected = False
        calls = []

        def get_instrument_bars(self, category, market, code, start, count):
            self.calls.append((category, market, code, start, count))
            return [_source_row(TARGET)]

        def disconnect(self):
            self.disconnected = True

    api = Api()
    result = supplement.fetch_hk_daily_bars(
        ["HK.00001", "00002"],
        connector=lambda: (api, "tdx.example:7721"),
    )

    assert api.calls == [(4, 71, "00001", 0, 6), (4, 71, "00002", 0, 6)]
    assert api.disconnected is True
    assert result["provider"] == "PYTDX_EXHQ"
    assert result["category"] == 4 and result["market"] == 71
    assert [row["code"] for row in result["records"]] == ["HK.00001", "HK.00002"]
    assert all(row["response_sha256"] for row in result["records"])
    assert all(row["request_started_at"] and row["request_finished_at"] for row in result["records"])


def test_daily_adapter_reuses_exact_rows_and_fetches_only_gaps_without_losing_zero_activity(tmp_path):
    root = tmp_path / "tdx"
    _day_file(root, "00001", TARGET)
    _day_file(root, "00002", "20261005")
    _day_file(root, "00003", "20261005")
    calls = []

    def fetcher(codes, *, count, request_context):
        calls.append((codes, count, request_context))
        return {
            "provider": "PYTDX_EXHQ", "host": "119.97.142.130:7721",
            "category": 4, "market": 71, "method": "get_instrument_bars",
            "start": 0, "count": count,
            "records": [
                _response("HK.00002", [
                    _source_row(TARGET, trade=0, amount=0),
                    _source_row("20261007", trade=0, amount=0),
                ]),
                _response("HK.00003", [_source_row("20261005", trade=2, amount=200)]),
            ],
        }

    result = panel.collect_hk_tdx_daily_rows(
        root, TARGET, package_root=tmp_path, fetcher=fetcher,
    )

    assert calls == [(["HK.00002", "HK.00003"], 6,
                      {"target_date": TARGET, "requested_target_date": TARGET})]
    assert result["status"] == "PARTIAL"
    assert result["target_codes"] == ["00001", "00002"]
    assert result["reused_target_code_count"] == 1
    assert result["requested_from_provider_code_count"] == 2
    assert result["rows"][0]["volume"] == 0
    assert result["rows"][0]["turnover"] == 0
    assert result["rows"][0]["volume_conversion_status"] == "INFERRED_NOT_VENDOR_DOCUMENTED"
    by_code = {row["code"]: row for row in result["capture"]["code_records"]}
    assert by_code["HK.00001"]["status"] == "REUSED_EXISTING_TARGET_BAR"
    assert by_code["HK.00001"]["raw_provider_capture_time_status"].startswith("CANNOT_CONFIRM")
    assert by_code["HK.00002"]["status"] == "READY"
    assert by_code["HK.00002"]["future_dates_excluded"] == ["20261007"]
    assert by_code["HK.00003"]["status"] == "NO_TARGET_BAR"
    assert "suspension" not in by_code["HK.00003"].get("reason_code", "").lower()
    assert result["capture"]["source"]["market_id"] == 71


def test_daily_adapter_missing_target_amount_stays_invalid_not_zero(tmp_path):
    root = tmp_path / "tdx"
    _day_file(root, "00002", "20261005")

    def fetcher(codes, *, count, request_context):
        return {
            "provider": "PYTDX_EXHQ", "host": "119.97.142.130:7721",
            "category": 4, "market": 71, "method": "get_instrument_bars",
            "start": 0, "count": count,
            "records": [_response("HK.00002", [_source_row(TARGET, trade=1, amount=None)])],
        }

    result = panel.collect_hk_tdx_daily_rows(
        root, TARGET, package_root=tmp_path, fetcher=fetcher,
    )

    assert result["rows"] == []
    assert result["target_codes"] == []
    assert result["capture"]["code_records"][0]["status"] == "INVALID"
    assert result["capture"]["code_records"][0]["reason_code"] == "HK_TDX_TARGET_FIELD_MISSING"


def test_daily_owner_gate_uses_tdx_and_preflights_master_without_futu_fallback(tmp_path, monkeypatch):
    target = "20261006"
    asset_root = tmp_path / "store" / "assets" / "hk_0_2"
    receipt_root = tmp_path / "receipts"
    package_script = tmp_path / "package" / "scripts" / "update_hk_0_2_panel.py"
    package_script.parent.mkdir(parents=True)
    package_script.write_text("# fixture", encoding="utf-8")
    ensure_calls = []

    def ensure_master(**kwargs):
        ensure_calls.append(kwargs)
        return {
            "status": "READY", "trade_date": target, "run_id": "master-r1",
            "security_master_artifact_sha256": "a" * 64,
        }

    import ops.ensure_hk_security_master as ensure_module
    monkeypatch.setattr(ensure_module, "ensure_hk_security_master", ensure_master)
    capture = {
        "schema_version": "v3.macos.research_panel_hk_tdx_daily_capture.v1",
        "target_date": target,
        "source": {"provider": "PYTDX_EXHQ", "category": 4, "market_id": 71},
        "requested_code_count": 2,
        "code_records": [],
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    capture_bytes = json.dumps(
        capture, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()
    captured = {
        "status": "PARTIAL", "target_date": target, "rows": [], "target_codes": [],
        "capture": capture, "capture_sha256": hashlib.sha256(capture_bytes).hexdigest(),
        "target_bar_code_count": 0, "requested_from_provider_code_count": 2,
        "coverage_rate": 0.0, "record_status_counts": {"NO_TARGET_BAR": 2},
    }
    monkeypatch.setattr(panel, "collect_hk_tdx_daily_rows", lambda *_args, **_kwargs: captured)
    monkeypatch.setattr(panel, "run_hk_0_2_authority",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("partial TDX must not update panel")))

    outcome = hk_capture_gate.run_hk_capture_gate(
        vars(panel), target_date=target,
        args=SimpleNamespace(
            hk_asset_root=asset_root,
            hk_tdx_root=tmp_path / "tdx",
            receipt_root=receipt_root,
        ),
        authority_paths={
            "--hk-updater-script": package_script,
            "--hk-asset-root": asset_root,
        },
        python_executable=Path("/not-used"),
    )

    assert outcome["status"] == "PARTIAL"
    assert outcome["reason_code"] == "HK_TDX_TARGET_ROW_MINIMUM_NOT_MET"
    assert ensure_calls[0]["reuse_only"] is True
    assert "capture" not in ensure_calls[0]
    assert outcome["tdx_capture_sha256"] == hashlib.sha256(capture_bytes).hexdigest()
    assert Path(outcome["tdx_capture_manifest"]).is_file()
    assert not (tmp_path / "tdx" / "vipdoc" / "ds" / "lday").exists()
