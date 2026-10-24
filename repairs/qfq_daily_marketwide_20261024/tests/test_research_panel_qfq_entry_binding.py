"""Original active five-module entry binding; no collector or producer runs."""
from pathlib import Path
import pytest

from ops import macos_research_panel_daily as daily
from ops import macos_research_panel_daily_receipts as receipts
from ops import research_panel_qfq as qfq


def test_existing_authority_calls_qfq_even_when_target_date_was_ready(tmp_path, monkeypatch):
    pointers, targets = {}, {}
    for role in ("selector", "backtest"):
        target = tmp_path / (role + ".parquet")
        target.write_bytes((role + " test artifact").encode())
        pointer = tmp_path / (role + ".txt")
        pointer.write_text(str(target))
        pointers[role], targets[role] = pointer, target
    calls = []
    def rebuild(**kwargs):
        calls.append(kwargs)
        return dict(status="READY", selector=str(targets["selector"]), backtest=str(targets["backtest"]),
                    counts={"selector": {"target_date_symbols": 5496}}, authority={"final_status": "PASS_QFQ_FULL_HISTORY"})
    monkeypatch.setattr(qfq, "run_daily_rebuild", rebuild)
    monkeypatch.setattr(daily, "_load_authority_module", lambda *_: (_ for _ in ()).throw(AssertionError("legacy main forbidden")))
    monkeypatch.setattr(daily, "_parquet_max_date", lambda *_: 20261023)
    original_root = tmp_path / "original_tdx"
    result = daily.run_windows_a_formula_authority(tmp_path / "legacy_driver.py", tdx_root=tmp_path / "accepted_view",
        qfq_original_tdx_root=original_root, data_root=tmp_path / "data", selector_pointer=pointers["selector"],
        backtest_pointer=pointers["backtest"], selector_seed=None, backtest_seed=None,
        contract_csv=tmp_path / "contract.csv", canonical_formula_path=tmp_path / "canonical.py",
        return_root=tmp_path / "runs", target_date="20261023", formula_max_workers=2)
    assert len(calls) == 1
    assert calls[0]["tdx_root"] == original_root
    assert calls[0]["publish"] is True and calls[0]["refresh_inputs"] is True
    assert calls[0]["driver_path"] == Path(daily.__file__).parent / "vendor/data_layer_daily_formula_increment_update_v1.py"
    assert calls[0]["workers"] == 2
    assert result["selector_sha256"] == qfq.sha(targets["selector"])
    assert result["backtest_sha256"] == qfq.sha(targets["backtest"])
    assert result["authority"]["selector_increment_rows"] == 5496


def test_original_ready_gate_uses_factor_revision_not_only_max_date(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(qfq, "pointer_ready", lambda *args: seen.append(args) or False)
    pointer = tmp_path / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt"
    assert daily.selector_pointer_is_ready(pointer, "20261023") is False
    assert seen == [(pointer, 20261023, qfq.input_path(tmp_path))]


def test_original_cli_keeps_accepted_view_and_passes_original_history_root(tmp_path, monkeypatch):
    captured = []
    original_root, accepted_view = tmp_path / "tdx", tmp_path / "accepted"
    monkeypatch.setattr(daily, "_a_day_files", lambda *_: [tmp_path / "one.day"])
    monkeypatch.setattr(daily, "run_windows_a_sync_authority", lambda *_args, **_kwargs: dict(status="READY", formula_tdx_root=str(accepted_view)))
    monkeypatch.setattr(daily, "run_windows_a_formula_authority", lambda *_args, **kwargs: captured.append(kwargs) or dict(status="READY"))
    monkeypatch.setattr(receipts, "build_a_lane_outcome", lambda *_args: dict(status="READY", row_count=5496, coverage_rate=5496/5800))
    def scheduled(**kwargs):
        return dict(overall_status="READY", target_date="20261023", requested_lane="A", lanes={"A": kwargs["a_runner"]("20261023")})
    monkeypatch.setattr(daily, "run_scheduled_lanes", scheduled)
    flags = ["--date", "20261023", "--lane", "A", "--a-tdx-root", str(original_root)]
    for flag in ("receipt-root", "hk-tdx-root", "a-sync-script", "a-formula-script", "a-seed-panel", "a-data-root",
                 "a-selector-pointer", "a-backtest-pointer", "a-selector-seed", "a-backtest-seed", "a-contract-csv",
                 "a-canonical-formula", "a-return-root", "hk-updater-script", "hk-asset-root"):
        flags.extend(["--" + flag, str(tmp_path / flag)])
    import sys
    monkeypatch.setattr(sys, "argv", ["macos_research_panel_daily.py", *flags])
    assert daily.main() == 0
    assert captured[0]["tdx_root"] == str(accepted_view)
    assert captured[0]["qfq_original_tdx_root"] == original_root
    monkeypatch.setattr(daily, "_a_day_files", lambda *_: [])
    with pytest.raises(daily.SnapshotGateError, match="ORIGINAL_TDX_DAY_AUTHORITY_MISSING"):
        daily.main()
