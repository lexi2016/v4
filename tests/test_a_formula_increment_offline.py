"""Offline public-chain tests for the V4 A formula increment runner."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from infrastructure.formula_generation import FormulaGenerationError, read_formula_generation
from ops import a_formula_increment as increment
from ops import macos_research_panel_daily as panel


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "a_formula_field_contract_v0.csv"
SELECTOR_HISTORY_SEED_SHA = "e82c8de505db3d567057aca1afcc87343982ef03b534f4249dc1694b3184adee"


def _manifest_sha(value: dict) -> str:
    payload = dict(value)
    payload.pop("manifest_sha256", None)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path) -> dict[str, Path | dict]:
    input_root = tmp_path / "input"
    input_root.mkdir()
    output_root = tmp_path / "output"
    data_root = output_root / "data"
    return_root = output_root / "runs"
    pointer_root = output_root / "pointers"
    pointer_root.mkdir(parents=True)

    dates = [int(value.strftime("%Y%m%d")) for value in pd.bdate_range("2026-08-26", "2026-09-11")]
    rows = []
    for code, base in (("600001.SH", 10.0), ("000001.SZ", 20.0)):
        for index, day in enumerate(dates):
            close = base + index * 0.11
            rows.append(
                {
                    "ts_code": code,
                    "trade_date": day,
                    "raw_code": code[:6],
                    "exchange": code[-2:],
                    "market_type": "A",
                    "name": "offline-fixture",
                    "open": close - 0.04,
                    "high": close + 0.16,
                    "low": close - 0.16,
                    "close": close,
                    "volume": 1_000 + index * 25,
                    "amount": 100_000 + index * 1_500,
                }
            )
    bars = pd.DataFrame(rows)
    policy = increment.build_contract_policy(increment.load_authoritative_contract_rows(CONTRACT), CONTRACT)
    missing_columns = [column for column in policy["official_columns"] if column not in bars.columns]
    extra_columns = {
        column: (
            "fixture"
            if column.endswith(("source", "policy", "scope", "root", "path", "outputs"))
            else 0
        )
        for column in missing_columns
    }
    if extra_columns:
        bars = pd.concat([bars, pd.DataFrame(extra_columns, index=bars.index)], axis=1)
    source_path = input_root / "bars.parquet"
    bars.to_parquet(source_path, index=False)
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    sync_receipt = input_root / "sync-receipt.json"
    sync_receipt.write_text(
        json.dumps(
            {
                "status": "READY",
                "authority_status": "PASS",
                "target_date": "20260911",
                "files": [str(source_path.resolve())],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sync_receipt_sha = hashlib.sha256(sync_receipt.read_bytes()).hexdigest()
    manifest = {
        "schema": "v4.a_formula.input_manifest.v1",
        "market": "A",
        "target_date": "20260911",
        "run_id": "offline-fixture-r1",
        "source": {
            "name": "synthetic-offline-fixture",
            "version": "1",
            "sync_receipt_path": str(sync_receipt.resolve()),
            "sync_receipt_sha256": sync_receipt_sha,
            "network": "NOT_USED",
        },
        "source_sha256": source_sha,
        "files": [{"path": "bars.parquet", "sha256": source_sha, "rows": len(bars)}],
        "coverage": {"status": "PASS", "rows": len(bars), "symbols": 2},
        "duplicate_key_audit": {"status": "PASS", "duplicate_rows": 0},
        "future_check": {"status": "PASS", "future_rows": 0},
    }
    manifest["manifest_sha256"] = _manifest_sha(manifest)
    manifest_path = input_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    normalized = increment._normalize_input_frame(bars, 20260911)
    features = increment.compute_formula_features(increment.collect_increment_history(normalized))
    features["field_contract_version"] = policy["contract_version"]
    current = features[features["trade_date"] <= 20260909].copy()
    selector_seed = tmp_path / "selector-seed.parquet"
    backtest_seed = tmp_path / "backtest-seed.parquet"
    current.to_parquet(selector_seed, index=False)
    current.to_parquet(backtest_seed, index=False)
    selector_pointer = pointer_root / "CURRENT_SELECTOR_READY_PANEL.txt"
    backtest_pointer = pointer_root / "CURRENT_BACKTEST_BASE_PANEL.txt"
    selector_pointer.write_bytes(b"old-selector-pointer\n")
    backtest_pointer.write_bytes(b"old-backtest-pointer\n")
    return {
        "input_root": input_root,
        "manifest": manifest_path,
        "data_root": data_root,
        "return_root": return_root,
        "selector_pointer": selector_pointer,
        "backtest_pointer": backtest_pointer,
        "selector_seed": selector_seed,
        "backtest_seed": backtest_seed,
        "manifest_obj": manifest,
        "sync_receipt": sync_receipt,
        "output_root": output_root,
    }


def _public_command(fixture: dict[str, Path | dict]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "ops.macos_research_panel_daily",
        "--date",
        "20260911",
        "--lane",
        "A",
        "--receipt-root",
        str(Path(fixture["output_root"]) / "receipts"),
        "--a-offline-input-root",
        str(fixture["input_root"]),
        "--a-offline-input-manifest",
        str(fixture["manifest"]),
        "--a-data-root",
        str(fixture["data_root"]),
        "--a-return-root",
        str(fixture["return_root"]),
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
        "--a-formula-timeout-seconds",
        "30",
    ]


def test_public_offline_chain_writes_187_selector_and_12_sidecar(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    selector_before = Path(fixture["selector_pointer"]).read_bytes()
    completed = subprocess.run(
        _public_command(fixture),
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
    assert Path(fixture["selector_pointer"]).read_bytes() != selector_before
    pointer_target = Path(Path(fixture["selector_pointer"]).read_text().strip())
    assert pointer_target.is_file()
    selector = pd.read_parquet(pointer_target)
    assert len(selector.columns) == 187
    assert selector["trade_date"].max() == 20260911
    sidecars = list(Path(fixture["return_root"]).glob("a_formula_20260911_*/selector_aux_sidecar.parquet"))
    assert len(sidecars) == 1
    sidecar = pd.read_parquet(sidecars[0])
    assert list(sidecar.columns[:2]) == ["ts_code", "trade_date"]
    assert len(sidecar.columns) == 14
    assert set(sidecar["trade_date"]) == set(selector["trade_date"])
    receipt = list(Path(fixture["return_root"]).glob("a_formula_20260911_*/authority-receipt.json"))[0]
    payload = json.loads(receipt.read_text())
    assert payload["gates"]["official_projection"]["status"] == "PASS"
    assert payload["gates"]["official_projection"]["column_count"] == 187
    assert payload["gates"]["sidecar_keys"]["key_count"] == len(sidecar)
    assert payload["gates"]["sidecar_keys"]["key_sha256"] == payload["gates"]["sidecar_keys"]["source_key_sha256"]
    assert payload["sidecar_binding"]["auxiliary_columns"] == list(increment.SIDEcar_COLUMNS)
    assert payload["process"]["network"] == "NOT_USED"
    assert payload["historical_seed_health"]["status"] == "CANNOT_CONFIRM"
    assert payload["gates"]["selector_source"]["full_seed_health"] == "CANNOT_CONFIRM"
    assert payload["gates"]["selector_source"]["existing_rows_value_sha256_before"] == payload["gates"]["selector_source"]["existing_rows_value_sha256_after"]
    assert payload["gates"]["backtest_source"]["existing_rows_value_sha256_before"] == payload["gates"]["backtest_source"]["existing_rows_value_sha256_after"]
    assert payload["gates"]["selector_source"]["seed_sha256"] == hashlib.sha256(Path(fixture["selector_seed"]).read_bytes()).hexdigest()
    generation_pointer = Path(fixture["output_root"]) / "CURRENT_FORMULA_GENERATION.json"
    generation = read_formula_generation(generation_pointer, expected_target_date="20260911", require_source=True)
    owned_manifest = Path(generation["input_manifest"]["path"])
    owned_receipt = Path(generation["source"]["sync_receipt_path"])
    assert owned_manifest.parent == receipt.parent
    assert owned_receipt.parent == receipt.parent
    assert owned_manifest.read_bytes() == Path(fixture["manifest"]).read_bytes()
    assert owned_receipt.read_bytes() == Path(fixture["sync_receipt"]).read_bytes()
    assert payload["generation_owned_evidence"]["input_manifest"]["path"] == str(owned_manifest)
    assert payload["generation_owned_evidence"]["sync_receipt"]["path"] == str(owned_receipt)


@pytest.mark.parametrize("provenance", ("input_manifest", "sync_receipt"))
def test_strict_generation_rejects_owned_provenance_drift(tmp_path: Path, provenance: str) -> None:
    fixture = _fixture(tmp_path)
    completed = subprocess.run(
        _public_command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    generation_pointer = Path(fixture["output_root"]) / "CURRENT_FORMULA_GENERATION.json"
    generation = read_formula_generation(generation_pointer, expected_target_date="20260911", require_source=True)
    path = (
        Path(generation["input_manifest"]["path"])
        if provenance == "input_manifest"
        else Path(generation["source"]["sync_receipt_path"])
    )
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(FormulaGenerationError, match="(bytes|SHA) mismatch"):
        read_formula_generation(generation_pointer, expected_target_date="20260911", require_source=True)


def _retention_fixture() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    contract = json.loads((ROOT / "contracts" / "a_known_history_gaps.json").read_text(encoding="utf-8"))
    approved_keys = next(item["keys"] for item in contract["seeds"] if item["role"] == "selector")
    current_rows = [
        {
            "ts_code": "600001.SH",
            "trade_date": 20260909,
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 10.1,
            "volume": 100,
            "amount": 1000,
        }
    ]
    # Keep the fixture's anomaly set exactly equal to the frozen contract;
    # a smaller illustrative subset would correctly fail the production
    # identity gate rather than exercise retention behavior.
    current_rows.extend(
        {
            "ts_code": str(item["ts_code"]),
            "trade_date": int(item["trade_date"]),
            "open": 10.0,
            "high": 10.5,
            "low": 9.5,
            "close": 11.0,
            "volume": 100,
            "amount": 1000,
        }
        for item in approved_keys
    )
    current = pd.DataFrame(current_rows)
    increment_row = pd.DataFrame(
        [
            {
                "ts_code": "600001.SH",
                "trade_date": 20260911,
                "open": 10.1,
                "high": 10.6,
                "low": 9.9,
                "close": 10.4,
                "volume": 120,
                "amount": 1200,
            }
        ]
    )
    combined = increment._append_rows(current, increment_row, role="selector")
    return current, increment_row, combined


def test_existing_hk_history_is_retained_and_reported_as_unresolved_gap() -> None:
    current, _increment, combined = _retention_fixture()
    audit = increment._audit_existing_history(
        current,
        combined,
        role="selector_history",
        target_date=20260911,
        seed_sha256=SELECTOR_HISTORY_SEED_SHA,
    )
    assert audit["status"] == "PASS"
    assert audit["existing_rows_retained"] == len(current)
    assert audit["existing_rows_value_sha256_before"] == audit["existing_rows_value_sha256_after"]
    assert audit["historical_health"] == "CANNOT_CONFIRM"
    assert audit["full_seed_health"] == "CANNOT_CONFIRM"
    assert {(row["market"], row["rows"]) for row in audit["known_historical_gaps"]} == {("HK", 186), ("HK_FUND", 168)}
    assert all(row["status"] == "CANNOT_CONFIRM" for row in audit["known_historical_gaps"])


def test_existing_history_mutation_or_loss_fails_closed() -> None:
    current, _increment, combined = _retention_fixture()
    changed = combined.copy()
    changed.loc[changed["ts_code"].eq("600001.SH") & changed["trade_date"].eq(20260909), "close"] = 10.2
    with pytest.raises(increment.AuthorityError, match="retention failed|logical value digest changed"):
        increment._audit_existing_history(
            current,
            changed,
            role="selector_history",
            target_date=20260911,
            seed_sha256=SELECTOR_HISTORY_SEED_SHA,
        )
    dropped = combined.loc[~(combined["ts_code"].eq("600001.SH") & combined["trade_date"].eq(20260909))].copy()
    with pytest.raises(increment.AuthorityError, match="retention failed"):
        increment._audit_existing_history(
            current,
            dropped,
            role="selector_history",
            target_date=20260911,
            seed_sha256=SELECTOR_HISTORY_SEED_SHA,
        )


def test_new_a_rows_keep_strict_ohlc_gate() -> None:
    bad = pd.DataFrame(
        [
            {
                "ts_code": "600001.SH",
                "trade_date": 20260911,
                "open": 10.1,
                "high": 10.6,
                "low": 9.9,
                "close": 11.0,
                "volume": 120,
                "amount": 1200,
                "gold_brick_context": "none",
                "brick_resonance_context": 0,
                "brick_buy": 0,
                "brick_buy1_low_absorb": 0,
                "brick_buy2_attack": 0,
                "primary_buy_signal": 0,
                "secondary_buy_signal": 0,
                "brick_exist_b": 0,
                "brick_resonance1": 0,
                "brick_resonance2": 0,
                "brick_resonance": 0,
            }
        ]
    )
    with pytest.raises(increment.AuthorityError, match="candidate row gate failed"):
        increment.validate_new_selector_rows(bad, 20260911, role="selector_increment")
    with pytest.raises(increment.AuthorityError, match="candidate row gate failed"):
        increment._validate_backtest_frame(bad, 20260911)


def test_invalid_manifest_keeps_both_pointer_bytes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    selector_pointer = Path(fixture["selector_pointer"])
    backtest_pointer = Path(fixture["backtest_pointer"])
    selector_before = selector_pointer.read_bytes()
    backtest_before = backtest_pointer.read_bytes()
    manifest = json.loads(Path(fixture["manifest"]).read_text())
    manifest["future_check"]["status"] = "FAIL"
    manifest["manifest_sha256"] = _manifest_sha(manifest)
    Path(fixture["manifest"]).write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    completed = subprocess.run(
        _public_command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert selector_pointer.read_bytes() == selector_before
    assert backtest_pointer.read_bytes() == backtest_before
    failure_receipt = Path(fixture["output_root"]) / "receipts" / "a-20260911.json"
    failure_payload = json.loads(failure_receipt.read_text(encoding="utf-8"))
    assert "future_check" in failure_payload["error"]


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    (("date", "target_date mismatch"), ("duplicate", "duplicate key"), ("missingcols", "missing base columns")),
)
def test_invalid_input_gates_fail_closed_without_pointer_write(tmp_path: Path, mutation: str, expected_error: str) -> None:
    fixture = _fixture(tmp_path)
    selector_pointer = Path(fixture["selector_pointer"])
    backtest_pointer = Path(fixture["backtest_pointer"])
    selector_before = selector_pointer.read_bytes()
    backtest_before = backtest_pointer.read_bytes()
    manifest = json.loads(Path(fixture["manifest"]).read_text(encoding="utf-8"))
    source_path = Path(fixture["input_root"]) / "bars.parquet"
    if mutation == "date":
        manifest["target_date"] = "20260910"
    else:
        bars = pd.read_parquet(source_path)
        if mutation == "duplicate":
            bars = pd.concat([bars, bars.iloc[[0]]], ignore_index=True)
        else:
            bars = bars.drop(columns=["close"])
        bars.to_parquet(source_path, index=False)
        source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
        manifest["source_sha256"] = source_sha
        manifest["files"][0]["sha256"] = source_sha
        manifest["files"][0]["rows"] = len(bars)
        manifest["coverage"]["rows"] = len(bars)
    manifest["manifest_sha256"] = _manifest_sha(manifest)
    Path(fixture["manifest"]).write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    completed = subprocess.run(
        _public_command(fixture),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert selector_pointer.read_bytes() == selector_before
    assert backtest_pointer.read_bytes() == backtest_before
    failure_receipt = Path(fixture["output_root"]) / "receipts" / "a-20260911.json"
    failure_payload = json.loads(failure_receipt.read_text(encoding="utf-8"))
    assert expected_error in failure_payload["error"]


def test_timeout_terminates_process_group() -> None:
    result = panel.run_bounded_process(
        [sys.executable, "-c", "import time; time.sleep(20)"],
        timeout_seconds=0.1,
        cwd=ROOT,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    assert result["timed_out"] is True
    assert result["process_group_terminated"] is True


def test_generation_commit_stays_coherent_when_legacy_projection_process_dies(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    pointer_root = output_root / "pointers"
    pointer_root.mkdir(parents=True)
    selector_target = output_root / "selector-new.parquet"
    backtest_target = output_root / "backtest-new.parquet"
    pd.DataFrame({"trade_date": [20260911]}).to_parquet(selector_target, index=False)
    pd.DataFrame({"trade_date": [20260911]}).to_parquet(backtest_target, index=False)
    selector_pointer = pointer_root / "CURRENT_SELECTOR_READY_PANEL.txt"
    backtest_pointer = pointer_root / "CURRENT_BACKTEST_BASE_PANEL.txt"
    selector_pointer.write_bytes(b"old-selector\n")
    backtest_pointer.write_bytes(b"old-backtest\n")
    child = """
import os
import sys
from pathlib import Path
from ops import a_formula_increment as increment

selector_pointer = Path(sys.argv[1]).resolve()
original_write_bytes = increment.SafeRoot.write_bytes

def crash_after_selector(self, relative, raw, *args, **kwargs):
    original_write_bytes(self, relative, raw, *args, **kwargs)
    if Path(self.root) == selector_pointer.parent and str(relative) == selector_pointer.name:
        os._exit(77)

increment.SafeRoot.write_bytes = crash_after_selector
increment._write_pointer_pair(
    selector_pointer,
    Path(sys.argv[2]).resolve(),
    Path(sys.argv[3]).resolve(),
    Path(sys.argv[4]).resolve(),
    Path(sys.argv[5]).resolve(),
)
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            child,
            str(selector_pointer),
            str(backtest_pointer),
            str(selector_target),
            str(backtest_target),
            str(output_root),
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONNOUSERSITE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 77, completed.stderr
    generation = panel._read_formula_generation(output_root)
    assert generation is not None
    assert generation["selector"] == selector_target.resolve()
    assert generation["backtest"] == backtest_target.resolve()
    assert Path(selector_pointer.read_text().strip()) == selector_target.resolve()
    assert backtest_pointer.read_bytes() == b"old-backtest\n"
    old_backtest = output_root / "backtest-old.parquet"
    pd.DataFrame({"trade_date": [20260910]}).to_parquet(old_backtest, index=False)
    backtest_pointer.write_text(str(old_backtest) + "\n", encoding="utf-8")
    consumed = panel.run_windows_a_formula_authority(
        output_root / "unused-authority.py",
        tdx_root=output_root / "tdx",
        data_root=output_root / "data",
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        selector_seed=None,
        backtest_seed=None,
        contract_csv=output_root / "contract.csv",
        canonical_formula_path=output_root / "formula.py",
        return_root=output_root / "runs",
        target_date="20260911",
    )
    assert consumed["selector"] == str(selector_target.resolve())
    assert consumed["backtest"] == str(backtest_target.resolve())
    assert consumed["generation_pointer"]["generation_id"] == generation["generation_id"]


def test_generation_commit_rolls_back_on_projection_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_root = tmp_path / "output"
    pointer_root = output_root / "pointers"
    pointer_root.mkdir(parents=True)
    selector_target = output_root / "selector-new.parquet"
    backtest_target = output_root / "backtest-new.parquet"
    selector_target.write_bytes(b"selector-new")
    backtest_target.write_bytes(b"backtest-new")
    selector_pointer = pointer_root / "CURRENT_SELECTOR_READY_PANEL.txt"
    backtest_pointer = pointer_root / "CURRENT_BACKTEST_BASE_PANEL.txt"
    selector_pointer.write_bytes(b"old-selector\n")
    backtest_pointer.write_bytes(b"old-backtest\n")
    original_write_bytes = increment.SafeRoot.write_bytes

    def fail_on_backtest(self: object, relative: str, raw: bytes, *args: object, **kwargs: object) -> None:
        if Path(getattr(self, "root")) == backtest_pointer.parent and str(relative) == backtest_pointer.name:
            raise OSError("injected projection failure")
        original_write_bytes(self, relative, raw, *args, **kwargs)

    monkeypatch.setattr(increment.SafeRoot, "write_bytes", fail_on_backtest)
    with pytest.raises(OSError, match="injected projection failure"):
        increment._write_pointer_pair(
            selector_pointer,
            backtest_pointer,
            selector_target,
            backtest_target,
            output_root,
        )
    assert selector_pointer.read_bytes() == b"old-selector\n"
    assert backtest_pointer.read_bytes() == b"old-backtest\n"
    assert not (output_root / increment.FORMULA_GENERATION_POINTER_NAME).exists()


def test_date_normalization_accepts_only_exact_calendar_forms() -> None:
    normalized = increment._normalize_date_series(pd.Series(["20260911", "2026-09-11"]))
    assert normalized.tolist() == [20260911, 20260911]
    for decorated in ("x20260911", "20260911x", "2026/09/11", "2026-09-11-note", "20260230"):
        with pytest.raises(increment.AuthorityError, match="trade_date contains invalid values"):
            increment._normalize_date_series(pd.Series([decorated]))
