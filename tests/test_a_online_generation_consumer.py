"""Focused fixture tests for the V4 A live-to-generation consumer boundary."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import warnings

import pandas as pd

from infrastructure.formula_generation import read_formula_generation
from ops import a_formula_increment as increment
from ops import a_formula_input_manifest as input_manifest
from ops import daily_materialize
from ops import macos_research_panel_daily as panel
from ops.a_share_daily_sync import DAY_STRUCT


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "a_formula_field_contract_v0.csv"


def _fixture(tmp_path: Path) -> dict[str, Path]:
    root = tmp_path / "v4-a-live"
    tdx = root / "tdx"
    (tdx / "vipdoc" / "sh" / "lday").mkdir(parents=True)
    (tdx / "vipdoc" / "sz" / "lday").mkdir(parents=True)
    (root / "pointers").mkdir()
    (root / "seeds").mkdir()
    (root / "receipts").mkdir()
    dates = [int(value.strftime("%Y%m%d")) for value in pd.bdate_range("2026-08-26", "2026-09-11")]
    rows: list[dict[str, object]] = []
    for market, code, base in (("sh", "600001", 10.0), ("sz", "000001", 20.0)):
        encoded: list[bytes] = []
        for index, day in enumerate(dates):
            close = base + index * 0.11
            encoded.append(
                DAY_STRUCT.pack(
                    day,
                    int(round((close - 0.04) * 100)),
                    int(round((close + 0.16) * 100)),
                    int(round((close - 0.16) * 100)),
                    int(round(close * 100)),
                    100_000.0 + index * 1_500,
                    int(round((1_000 + index * 25) * 100)),
                    0,
                )
            )
            rows.append(
                {
                    "ts_code": f"{code}.{market.upper()}",
                    "trade_date": day,
                    "raw_code": code,
                    "exchange": market.upper(),
                    "market_type": "A",
                    "name": "fixture",
                    "open": close - 0.04,
                    "high": close + 0.16,
                    "low": close - 0.16,
                    "close": close,
                    "volume": 1_000 + index * 25,
                    "amount": 100_000 + index * 1_500,
                }
            )
        (tdx / "vipdoc" / market / "lday" / f"{market}{code}.day").write_bytes(b"".join(encoded))
    bars = pd.DataFrame(rows)
    normalized = increment._normalize_input_frame(bars, 20260911)
    policy = increment.build_contract_policy(
        increment.load_authoritative_contract_rows(CONTRACT), CONTRACT
    )
    features = increment.compute_formula_features(increment.collect_increment_history(normalized))
    features["field_contract_version"] = policy["contract_version"]
    for column in policy["official_columns"]:
        if column not in features.columns:
            features[column] = "fixture" if column.endswith(("source", "policy", "scope", "root", "path", "outputs")) else 0
    seed = features[features["trade_date"] <= 20260909].copy()
    selector_seed = root / "seeds" / "selector.parquet"
    backtest_seed = root / "seeds" / "backtest.parquet"
    seed.to_parquet(selector_seed, index=False)
    seed.to_parquet(backtest_seed, index=False)

    fake_sync = root / "fake_sync.py"
    fake_sync.write_text(
        "from pathlib import Path\n"
        "def run(args):\n"
        "    assert args.host == '127.0.0.1:7709'\n"
        "    assert Path(args.tdx_root).is_dir()\n"
        "    return {'status': 'PASS', 'exit_code': 0, 'target_date': str(args.target_date)}\n",
        encoding="utf-8",
    )
    placeholder = root / "placeholder.py"
    placeholder.write_text("# strict fixture placeholder\n", encoding="utf-8")
    return {
        "root": root,
        "tdx": tdx,
        "selector_seed": selector_seed,
        "backtest_seed": backtest_seed,
        "fake_sync": fake_sync,
        "placeholder": placeholder,
        "receipt_root": root / "receipts",
        "data_root": root / "data",
        "return_root": root / "runs",
        "selector_pointer": root / "pointers" / "CURRENT_SELECTOR_READY_PANEL.txt",
        "backtest_pointer": root / "pointers" / "CURRENT_BACKTEST_BASE_PANEL.txt",
        "generation_pointer": root / "CURRENT_FORMULA_GENERATION.json",
    }


def _command(fixture: dict[str, Path]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "ops.macos_research_panel_daily",
        "--date",
        "20260911",
        "--lane",
        "A",
        "--receipt-root",
        str(fixture["receipt_root"]),
        "--a-tdx-root",
        str(fixture["tdx"]),
        "--a-sync-script",
        str(fixture["fake_sync"]),
        "--a-formula-script",
        str(fixture["placeholder"]),
        "--a-seed-panel",
        str(fixture["placeholder"]),
        "--a-data-root",
        str(fixture["data_root"]),
        "--a-selector-pointer",
        str(fixture["selector_pointer"]),
        "--a-backtest-pointer",
        str(fixture["backtest_pointer"]),
        "--a-selector-seed",
        str(fixture["selector_seed"]),
        "--a-backtest-seed",
        str(fixture["backtest_seed"]),
        "--a-contract-csv",
        str(CONTRACT),
        "--a-canonical-formula",
        str(fixture["placeholder"]),
        "--a-return-root",
        str(fixture["return_root"]),
        "--a-formula-generation-pointer",
        str(fixture["generation_pointer"]),
        "--a-host",
        "127.0.0.1",
        "--a-port",
        "7709",
        "--a-minimum-rows",
        "1",
        "--a-formula-timeout-seconds",
        "30",
    ]


def _publisher_fixture(tmp_path: Path, monkeypatch) -> tuple[dict[str, Path], object, dict[str, object], dict[str, object], Path]:
    fixture = _fixture(tmp_path)
    completed = subprocess.run(
        _command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    from ops import publish_research_panel_runtime_receipt as publisher

    # The publisher's path policy intentionally excludes pytest's temporary
    # root; this test-only seam keeps the evidence chain under the fixture.
    monkeypatch.setattr(
        publisher,
        "_allowed_input_path",
        lambda value: Path(value).expanduser().absolute(),
    )
    generation = read_formula_generation(
        fixture["generation_pointer"], expected_target_date="20260911", require_source=True
    )
    receipt_path = fixture["receipt_root"] / "a-20260911.json"
    receipt = json.loads(receipt_path.read_text())
    result = publisher._publish_a(
        "20260911",
        fixture["receipt_root"],
        fixture["selector_pointer"],
        fixture["backtest_pointer"],
        fixture["generation_pointer"],
    )
    return fixture, publisher, generation, receipt, receipt_path


def test_public_live_fixture_binds_one_generation_and_source(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    completed = subprocess.run(
        _command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    envelope = json.loads(completed.stdout.strip().splitlines()[-1])
    assert envelope["overall_status"] == "READY"
    assert envelope["lanes"]["A"]["status"] == "READY"
    generation = read_formula_generation(
        fixture["generation_pointer"], expected_target_date="20260911", require_source=True
    )
    assert generation["selector"].is_file()
    assert generation["backtest"].is_file()
    assert generation["selector_source"].is_file()
    assert generation["selector_sidecar"].is_file()
    assert fixture["selector_pointer"].read_text().strip() == str(generation["selector"])
    assert fixture["backtest_pointer"].read_text().strip() == str(generation["backtest"])
    receipt = json.loads((fixture["receipt_root"] / "a-20260911.json").read_text())
    assert receipt["generation"]["generation_id"] == generation["generation_id"]
    assert receipt["sync"]["authority"]["status"] == "PASS"
    assert receipt["formula"]["source"]["network"] == "NOT_USED"
    assert receipt["formula"]["process"]["timed_out"] is False


def test_publisher_rejects_stale_or_missing_producer_generation(tmp_path: Path, monkeypatch) -> None:
    fixture, publisher, _generation, receipt, receipt_path = _publisher_fixture(tmp_path, monkeypatch)
    stale = json.loads(json.dumps(receipt))
    stale["generation"]["generation_id"] = "0" * 64
    receipt_path.write_text(json.dumps(stale), encoding="utf-8")
    rejected = publisher._publish_a(
        "20260911",
        fixture["receipt_root"],
        fixture["selector_pointer"],
        fixture["backtest_pointer"],
        fixture["generation_pointer"],
    )
    assert rejected["status"] == "CANNOT_CONFIRM"
    assert "A_PRODUCER_GENERATION_MISMATCH" in rejected["reason"]

    missing = json.loads(json.dumps(receipt))
    missing.pop("generation")
    receipt_path.write_text(json.dumps(missing), encoding="utf-8")
    rejected_missing = publisher._publish_a(
        "20260911",
        fixture["receipt_root"],
        fixture["selector_pointer"],
        fixture["backtest_pointer"],
        fixture["generation_pointer"],
    )
    assert rejected_missing["status"] == "CANNOT_CONFIRM"
    assert "A_PRODUCER_GENERATION_MISSING" in rejected_missing["reason"]


def test_publisher_accepts_matching_generation_from_top_or_nested_claim(tmp_path: Path, monkeypatch) -> None:
    fixture, publisher, generation, receipt, receipt_path = _publisher_fixture(tmp_path, monkeypatch)
    assert publisher._publish_a(
        "20260911",
        fixture["receipt_root"],
        fixture["selector_pointer"],
        fixture["backtest_pointer"],
        fixture["generation_pointer"],
    )["status"] == "READY"

    nested = json.loads(json.dumps(receipt))
    claim = nested.pop("generation")
    nested.setdefault("formula", {})["generation_pointer"] = claim
    receipt_path.write_text(json.dumps(nested), encoding="utf-8")
    accepted = publisher._publish_a(
        "20260911",
        fixture["receipt_root"],
        fixture["selector_pointer"],
        fixture["backtest_pointer"],
        fixture["generation_pointer"],
    )
    assert accepted["status"] == "READY"
    assert accepted["formula_generation"]["generation_id"] == generation["generation_id"]


def test_publisher_rejects_conflicting_generation_claims_and_metadata(tmp_path: Path, monkeypatch) -> None:
    fixture, publisher, generation, receipt, receipt_path = _publisher_fixture(tmp_path, monkeypatch)
    conflicting = json.loads(json.dumps(receipt))
    conflicting.setdefault("formula", {})["generation_pointer"] = {
        **conflicting["generation"],
        "generation_id": "0" * 64,
    }
    receipt_path.write_text(json.dumps(conflicting), encoding="utf-8")
    conflict_result = publisher._publish_a(
        "20260911",
        fixture["receipt_root"],
        fixture["selector_pointer"],
        fixture["backtest_pointer"],
        fixture["generation_pointer"],
    )
    assert conflict_result["status"] == "CANNOT_CONFIRM"
    assert "A_PRODUCER_GENERATION_FIELDS_CONFLICT:generation_id" in conflict_result["reason"]

    for field, value in (("path", "/wrong/generation.json"), ("bytes", generation["bytes"] + 1)):
        mismatched = json.loads(json.dumps(receipt))
        mismatched["generation"][field] = value
        receipt_path.write_text(json.dumps(mismatched), encoding="utf-8")
        result = publisher._publish_a(
            "20260911",
            fixture["receipt_root"],
            fixture["selector_pointer"],
            fixture["backtest_pointer"],
            fixture["generation_pointer"],
        )
        assert result["status"] == "CANNOT_CONFIRM"
        assert f"A_PRODUCER_GENERATION_{field.upper()}_MISMATCH" in result["reason"]


def test_generation_fast_path_is_strict_and_idempotent(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    first = subprocess.run(
        _command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr[-4000:]
    before_receipt = (fixture["receipt_root"] / "a-20260911.json").read_bytes()
    result = panel.ensure_after_1700(
        target_date="20260911",
        receipt_root=fixture["receipt_root"],
        selector_pointer=fixture["selector_pointer"],
        formula_generation_pointer=fixture["generation_pointer"],
        a_runner=lambda _date: (_ for _ in ()).throw(AssertionError("runner must not be called")),
        hk_runner=lambda _date: {"status": "READY"},
        lane="A",
        now=panel._datetime.datetime(2026, 9, 11, 18, 0, tzinfo=panel.ZoneInfo("Asia/Shanghai")),
    )
    assert result["status"] == "ALREADY_READY"
    assert result["lane_ready"] is True
    assert (fixture["receipt_root"] / "a-20260911.json").read_bytes() == before_receipt

    pointer_payload = json.loads(fixture["generation_pointer"].read_text())
    pointer_payload["status"] = "CANNOT_CONFIRM"
    fixture["generation_pointer"].write_text(json.dumps(pointer_payload), encoding="utf-8")
    assert panel.selector_pointer_is_ready(
        fixture["selector_pointer"], "20260911", fixture["generation_pointer"]
    ) is False


def test_input_manifest_rejects_future_day_without_writing_ready(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    source = fixture["tdx"] / "vipdoc" / "sh" / "lday" / "sh600001.day"
    source.write_bytes(
        source.read_bytes()
        + DAY_STRUCT.pack(20260912, 1000, 1020, 990, 1010, 100000.0, 100000, 0)
    )
    sync_receipt = fixture["root"] / "future-receipt.json"
    sync_receipt.write_text(
        json.dumps(
            {
                "status": "READY",
                "target_date": "20260911",
                "files": [str(source)],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ),
        encoding="utf-8",
    )
    output = fixture["root"] / "future-input"
    try:
        input_manifest.build_a_formula_input_manifest(
            sync_receipt=sync_receipt,
            tdx_root=fixture["tdx"],
            output_root=output,
            target_date="20260911",
        )
    except input_manifest.InputManifestError as error:
        assert "future" in str(error)
    else:
        raise AssertionError("future .day row was admitted")
    assert not (output / "manifest.json").exists()


def test_daily_selector_resolver_uses_generation_without_latest_fallback(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    completed = subprocess.run(
        _command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    resolved = daily_materialize.resolve_selector_panel(
        None, "20260911", formula_generation_pointer=fixture["generation_pointer"]
    )
    generation = read_formula_generation(fixture["generation_pointer"], require_source=True)
    assert resolved == generation["selector"]


def test_v192_wrapper_uses_generation_source_role(tmp_path: Path, monkeypatch, capsys) -> None:
    """The V192 consumer receives selector_source, never backtest_candidate."""
    fixture = _fixture(tmp_path)
    completed = subprocess.run(
        _command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    generation = read_formula_generation(fixture["generation_pointer"], require_source=True)

    from ops import materialize_shared_v192_preselection as wrapper

    class StoreError(Exception):
        pass

    seen: dict[str, object] = {}

    def fake_loader(*_args, **_kwargs):
        def missing(*_args, **_kwargs):
            raise StoreError("fixture has no prior V192 pool")

        def materialize(store_root, *, panel_path, signal_date, target_date):
            seen.update(
                store_root=str(store_root),
                panel_path=Path(panel_path),
                signal_date=signal_date,
                target_date=target_date,
            )
            return {"status": "READY", "run_id": "v192-fixture"}

        return type(
            "V192FixtureModule",
            (),
            {
                "StoreError": StoreError,
                "read_verified_v192_pool": missing,
                "materialize_frozen_v192_selector": materialize,
            },
        )

    monkeypatch.setattr(wrapper, "load_isolated_package_module", fake_loader)
    monkeypatch.setenv("V35_SHARED_PACKAGE_ROOT", str(fixture["root"] / "shared-package"))
    monkeypatch.setenv("V3_SHARED_DATA_STORE_ROOT", str(fixture["root"] / "shared-store"))
    monkeypatch.setenv("V3_SHARED_SELECTOR_READY_PANEL", str(generation["selector"]))
    exit_code = wrapper.main(
        [
            "--signal-date",
            "20260911",
            "--target-date",
            "20260914",
            "--generation-pointer",
            str(fixture["generation_pointer"]),
        ]
    )
    assert exit_code == 0
    output = json.loads(capsys.readouterr().out.strip())
    assert output["status"] == "READY"
    assert seen["panel_path"] == generation["selector_source"]
    assert seen["panel_path"] != generation["backtest"]
    assert seen["signal_date"] == "20260911"
    assert seen["target_date"] == "20260914"
    assert output["source_panel"]["role"] == "selector_source"
    assert output["formula_generation"]["generation_id"] == generation["generation_id"]


def test_v192_public_entry_reads_real_int64_trade_date_panel(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Run the public wrapper against an isolated package and real parquet reader."""
    bundle_path = (
        ROOT
        / "upstreams"
        / "v3_shared_data"
        / "shared_data"
        / "v192_oracle_bundle.py"
    )
    spec = importlib.util.spec_from_file_location("test_v192_date_bundle", bundle_path)
    assert spec is not None and spec.loader is not None
    bundle = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bundle)

    dates = pd.bdate_range("2026-01-05", periods=140).strftime("%Y%m%d").tolist()
    rows: list[dict[str, object]] = []
    for symbol_index, code in enumerate(("000001.SZ", "600000.SH")):
        for index, trade_date in enumerate(dates):
            close = 10.0 + symbol_index * 3.0 + index * 0.025
            row: dict[str, object] = {
                column: False if column in bundle.BOOL_COLUMNS else 0.0
                for column in bundle.REQUIRED_BASE_COLUMNS
            }
            row.update(
                {
                    "trade_date": trade_date,
                    "ts_code": code,
                    "name": f"fixture-{symbol_index}",
                    "open": close - 0.05,
                    "high": close + 0.12,
                    "low": close - 0.14,
                    "close": close,
                    "volume": 1_000_000.0 + index * 1_000.0,
                    "amount": 10_000_000.0 + index * 10_000.0,
                    "pre_close": close - 0.025,
                    "pct_chg": 0.25,
                    "amplitude_pct": 2.6,
                    "bar_close_pos": 0.7,
                    "upper_shadow_pct": 1.1,
                    "lower_shadow_pct": 1.3,
                    "amount_ratio_20": 1.0,
                    "high_20_prev": close,
                    "BBI": close - 0.03,
                    "zge_white_line": close - 0.04,
                    "zge_yellow_line": close - 0.08,
                    "J": 40.0,
                    "zge_rsi3": 40.0,
                    "ma20": close - 0.02,
                    "gold_brick_context": "none",
                }
            )
            rows.append(row)

    panel = tmp_path / "selector_int64.parquet"
    frame = pd.DataFrame(rows)
    frame["trade_date"] = pd.to_numeric(frame["trade_date"]).astype("int64")
    frame = frame.assign(
        brick_resonance1=0,
        brick_resonance2=0,
        brick_resonance=0,
        ref_hold_score=4,
        route_context="B2",
        brick_context="1",
        formula_source="computed_main_chart_formula_20260515",
        field_contract_version="formula_signal_v2_reference_score",
    )
    target = frame["trade_date"].eq(int(dates[-1]))
    for field in (
        "B2",
        "primary_buy_signal",
        "brick_buy2_attack",
        "ref_score_close_up",
        "ref_score_above_bbi",
        "ref_score_no_giant_true_yin",
        "ref_score_trend_up",
        "ref_score_j_no_dead_cross",
    ):
        frame.loc[target, field] = True
    frame.to_parquet(panel, index=False)

    package_root = tmp_path / "shared-package"
    shutil.copytree(
        ROOT / "upstreams" / "v3_shared_data" / "shared_data",
        package_root / "shared_data",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    store_root = tmp_path / "v192-store"
    monkeypatch.setenv("V35_SHARED_PACKAGE_ROOT", str(package_root))
    monkeypatch.setenv("V3_SHARED_DATA_STORE_ROOT", str(store_root))
    monkeypatch.setenv("V3_SHARED_SELECTOR_READY_PANEL", str(panel))
    from ops import materialize_shared_v192_preselection as wrapper

    source_before = panel.read_bytes()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
        exit_code = wrapper.main(
            ["--signal-date", dates[-1], "--target-date", "20260914"]
        )
    output = json.loads(capsys.readouterr().out.strip())
    assert exit_code == 0, output
    assert output["ok"] is True
    assert output["status"] == "READY"
    assert output["row_count"] == 2
    assert output["production_allowed"] is False
    assert output["buy_gate_updated"] is False
    assert output["orders_sent"] is False
    assert panel.read_bytes() == source_before
    assert any(path.name == "artifact.csv" for path in store_root.rglob("artifact.csv"))


def test_v192_wrapper_rejects_generation_source_date_mismatch(tmp_path: Path, monkeypatch, capsys) -> None:
    fixture = _fixture(tmp_path)
    completed = subprocess.run(
        _command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]

    from ops import materialize_shared_v192_preselection as wrapper
    monkeypatch.setenv("V35_SHARED_PACKAGE_ROOT", str(fixture["root"] / "shared-package"))
    monkeypatch.setenv("V3_SHARED_DATA_STORE_ROOT", str(fixture["root"] / "shared-store"))
    monkeypatch.setenv("V3_SHARED_SELECTOR_READY_PANEL", str(fixture["root"] / "unused-panel.parquet"))

    exit_code = wrapper.main(
        [
            "--signal-date",
            "20260910",
            "--target-date",
            "20260914",
            "--generation-pointer",
            str(fixture["generation_pointer"]),
        ]
    )
    assert exit_code == 1
    output = json.loads(capsys.readouterr().out.strip())
    assert output["status"] == "FAILED"
    assert "target_date mismatch" in output["error"]
