from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ops.run_hkconnect_0915_0920_capture import (
    HK_AUCTION_ROLE,
    materialize_hkconnect_0915_0920,
)
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore
from stage_center.runner import _validate_hk_second_filter


TRADE_DATE = "20260821"
SIGNAL_DATE = "20260820"


def _sha_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _d1_rows() -> list[dict[str, str]]:
    return [
        {
            "code": f"HK.{index:05d}",
            "name": f"名称{index}",
            "preselect_rank": str(index),
            "preselect_lane": "D1_PRESELECT",
            "preselect_score": str(1000 - index),
        }
        for index in range(1, 101)
    ]


def _auction_rows() -> list[dict[str, object]]:
    return [
        {
            "trade_date": TRADE_DATE,
            "bar_time": "09:19:59",
            "code": f"HK.{index:05d}",
            "name": f"名称{index}",
            "target_date": TRADE_DATE,
            "signal_date": SIGNAL_DATE,
            "stage1_ref_score": 100 - index,
            "stage1_ref_label": "PREOPEN_REF_PRIORITY",
            "reference_scope": "SIGNAL_INPUT_CUTOFF_SAFE_091959",
            "auction_ref_gap_pct": 1.0,
            "first_to_last_ref_pct": 0.1,
            "visible_depth_hkd": 2_000_000,
            "bid_ask_imbalance": 0.2,
            "spread_pct": 0.5,
            "last_price": 10.0 + index / 10,
            "prev_close_price": 10.0,
            "bid_price": 10.0,
            "ask_price": 10.1,
            "bid_vol": 1000,
            "ask_vol": 900,
            "turnover": 1_000_000 + index,
            "update_time": f"{TRADE_DATE[:4]}-{TRADE_DATE[4:6]}-{TRADE_DATE[6:]} 09:19:5{index % 10}",
            "collector_wall_time": f"{TRADE_DATE[:4]}-{TRADE_DATE[4:6]}-{TRADE_DATE[6:]} 09:19:5{index % 10}",
        }
        for index in range(1, 51)
    ]


def _shared_fixture(tmp_path: Path, *, source_sha: str | None = None):
    shared_root = tmp_path / "shared"
    data_root = tmp_path / "data"
    package_root = tmp_path / "shared-package"
    package_root.mkdir()
    auction_path = tmp_path / "auction.csv"
    d1_path = tmp_path / "d1.csv"

    auction_rows = _auction_rows()
    with auction_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(auction_rows[0]))
        writer.writeheader()
        writer.writerows(auction_rows)
    with auction_path.open("r", encoding="utf-8", newline="") as stream:
        auction_rows = list(csv.DictReader(stream))
    d1_rows = _d1_rows()
    with d1_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(d1_rows[0]))
        writer.writeheader()
        writer.writerows(d1_rows)

    def frozen_rows(preselect, reference):
        return [
            {
                "rank": index,
                "code": row["code"],
                "name": row["name"],
                "auction_rank": index,
                "auction_score": row["stage1_ref_score"],
                "second_filter_status": "AUCTION_SECOND_FILTER_PRIORITY",
                "auction_ref_gap_pct": row["auction_ref_gap_pct"],
                "turnover": row["turnover"],
                "reference_price_hkd": row["last_price"],
                "strict_failure_price_hkd": 0,
            }
            for index, row in enumerate(reference[:20], start=1)
        ]

    source_hash_rows = [
        {
            **row,
            "auction_ref_gap_pct": float(row["auction_ref_gap_pct"]),
            "turnover": float(row["turnover"]),
        }
        for row in auction_rows
    ]
    frozen = frozen_rows(d1_rows, source_hash_rows)
    frozen_sha = _sha_json(
        {
            "contract": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer",
            "trade_date": TRADE_DATE,
            "rows": frozen,
        }
    )
    auction_sha = hashlib.sha256(auction_path.read_bytes()).hexdigest()
    d1_sha = hashlib.sha256(d1_path.read_bytes()).hexdigest()
    run_id = "20260821-hk-auction-reference-run"
    manifest = {
        "schema_version": "v3_shared_data.manifest.v1",
        "source_id": "futu_hk_0915_0920_snapshot",
        "market": "HK_CONNECT",
        "trade_date": TRADE_DATE,
        "signal_date": SIGNAL_DATE,
        "stage_id": "STAGE_0925",
        "cutoff_at": "09:19:59",
        "row_count": 50,
        "temporal_cutoff_safe": True,
        "provenance": {
            "signal_date": SIGNAL_DATE,
            "d1_pool_sha256": d1_sha,
            "source_output_sha256": source_sha or frozen_sha,
        },
    }
    receipt = {
        "status": "READY",
        "role": HK_AUCTION_ROLE,
        "trade_date": TRADE_DATE,
        "stage_id": "STAGE_0925",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    auction_verified = SimpleNamespace(
        artifact_path=auction_path,
        manifest=manifest,
        receipt=receipt,
        verification={
            "run_id": run_id,
            "artifact_sha256": auction_sha,
            "manifest_sha256": "a" * 64,
            "receipt_sha256": "b" * 64,
        },
    )
    d1_verified = SimpleNamespace(
        artifact_path=d1_path,
        manifest={"trade_date": TRADE_DATE, "signal_date": SIGNAL_DATE, "row_count": 100},
        receipt={
            "status": "READY",
            "role": "HK_CONNECT_D1_TOP100_0_2",
            "trade_date": TRADE_DATE,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
        verification={
            "run_id": "d1-run",
            "artifact_sha256": d1_sha,
            "manifest_sha256": "d" * 64,
            "receipt_sha256": "e" * 64,
        },
    )
    calls: list[str] = []

    def read_verified_latest(root, date, role):
        calls.append(role)
        return auction_verified if role == HK_AUCTION_ROLE else d1_verified

    shared = SimpleNamespace(
        ROLE=HK_AUCTION_ROLE,
        SIGNAL_CUTOFF="09:19:59",
        PUBLICATION_TIME="09:20:00",
        run_capture=lambda *args, **kwargs: {
            "ok": True,
            "status": "READY",
            "run": {"run_id": run_id},
            "source_output_sha256": frozen_sha,
        },
        load_verified_candidates=lambda *args, **kwargs: (d1_rows, {"signal_date": SIGNAL_DATE}),
        build_second_filter_rows=frozen_rows,
        sha256_json=_sha_json,
    )
    class StoreError(Exception):
        pass

    consumer = SimpleNamespace(
        StoreError=StoreError,
        read_verified_latest=read_verified_latest,
    )
    return data_root, shared_root, package_root, shared, consumer, calls, frozen_sha


def test_materializes_verified_shared_trio_into_exact_pair(tmp_path: Path) -> None:
    data_root, shared_root, package_root, shared, consumer, calls, frozen_sha = _shared_fixture(tmp_path)

    result = materialize_hkconnect_0915_0920(
        data_root,
        shared_root,
        package_root,
        TRADE_DATE,
        Path(__file__),
        shared_module=shared,
        consumer_module=consumer,
    )

    assert result["status"] == "MATERIALIZED_FROM_SHARED_HK_0920"
    assert result["row_count"] == 20
    assert calls == [HK_AUCTION_ROLE, "HK_CONNECT_D1_TOP100_0_2"]
    pair_root = data_root / "opening_second_filter" / TRADE_DATE
    csv_path = pair_root / f"hkconnect_0920_auction_second_filter_{TRADE_DATE}.csv"
    acceptance_path = pair_root / f"hkconnect_0920_auction_second_filter_{TRADE_DATE}.acceptance.json"
    assert csv_path.is_file() and acceptance_path.is_file()
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    assert acceptance["schema_version"] == "hkconnect_0920_auction_second_filter.v3"
    assert acceptance["source_output_sha256"] == frozen_sha
    assert acceptance["reference_only"] is True
    assert acceptance["market_access"] == "NOT_TRADABLE_PREOPEN"
    assert acceptance["action_level"] == "NO_BUY"
    assert acceptance["production_allowed"] is False
    stored = OpeningSecondFilterStore(data_root).read(TRADE_DATE)
    assert stored is not None
    assert stored["exact_csv_sha256"] == acceptance["csv_sha256"] == hashlib.sha256(csv_path.read_bytes()).hexdigest()
    _validate_hk_second_filter(data_root / "opening_second_filter" / TRADE_DATE, TRADE_DATE)


def test_weekend_gate_does_not_call_capture(tmp_path: Path) -> None:
    data_root, shared_root, package_root, shared, consumer, _calls, _sha = _shared_fixture(tmp_path)
    called: list[bool] = []
    shared.run_capture = lambda *args, **kwargs: called.append(True) or pytest.fail("capture called on weekend")

    result = materialize_hkconnect_0915_0920(
        data_root,
        shared_root,
        package_root,
        "20260822",
        Path(__file__),
        shared_module=shared,
        consumer_module=consumer,
    )

    assert result["status"] == "SKIPPED_NON_TRADING_DAY"
    assert called == []


@pytest.mark.parametrize(
    "mutation",
    [
        "run_id",
        "collector_wall_time",
        "update_time",
        "source_output_sha256",
    ],
)
def test_lineage_and_temporal_mismatch_fail_closed(tmp_path: Path, mutation: str) -> None:
    data_root, shared_root, package_root, shared, consumer, _calls, frozen_sha = _shared_fixture(tmp_path)
    if mutation == "run_id":
        shared.run_capture = lambda *args, **kwargs: {
            "ok": True,
            "status": "READY",
            "run": {"run_id": "different-run"},
            "source_output_sha256": frozen_sha,
        }
    elif mutation == "source_output_sha256":
        auction = consumer.read_verified_latest(shared_root, TRADE_DATE, HK_AUCTION_ROLE)
        auction.manifest["provenance"]["source_output_sha256"] = "f" * 64
    else:
        auction = consumer.read_verified_latest(shared_root, TRADE_DATE, HK_AUCTION_ROLE)
        first = _auction_rows()[0]
        first[mutation] = "2026-08-21 09:20:00" if mutation == "update_time" else "2026-08-21 09:20:00"
        with auction.artifact_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(first))
            writer.writeheader()
            writer.writerows([first, *_auction_rows()[1:]])

    capture_runner = shared.run_capture if mutation == "run_id" else None
    with pytest.raises(ValueError):
        materialize_hkconnect_0915_0920(
            data_root,
            shared_root,
            package_root,
            TRADE_DATE,
            Path(__file__),
            shared_module=shared,
            consumer_module=consumer,
            capture_runner=capture_runner,
        )


def test_conflicting_reentry_is_rejected_before_store_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_root, shared_root, package_root, shared, consumer, _calls, _sha = _shared_fixture(tmp_path)
    materialize_hkconnect_0915_0920(
        data_root,
        shared_root,
        package_root,
        TRADE_DATE,
        Path(__file__),
        shared_module=shared,
        consumer_module=consumer,
    )
    acceptance = data_root / "opening_second_filter" / TRADE_DATE / f"hkconnect_0920_auction_second_filter_{TRADE_DATE}.acceptance.json"
    payload = json.loads(acceptance.read_text(encoding="utf-8"))
    payload["source_output_sha256"] = "0" * 64
    acceptance.write_text(json.dumps(payload), encoding="utf-8")
    publish_calls: list[bool] = []
    monkeypatch.setattr(
        "ops.run_hkconnect_0915_0920_capture.OpeningSecondFilterStore.publish",
        lambda *args, **kwargs: publish_calls.append(True),
    )

    with pytest.raises(ValueError, match="conflict"):
        materialize_hkconnect_0915_0920(
            data_root,
            shared_root,
            package_root,
            TRADE_DATE,
            Path(__file__),
            shared_module=shared,
            consumer_module=consumer,
        )
    assert publish_calls == []


def test_catalog_runner_command_is_registered() -> None:
    from ops.migration.runtime_governance import _runner_command_complete
    from infrastructure.scheduling.catalog import load_workload_catalog

    catalog = load_workload_catalog()
    row = next(item for item in catalog.source_payload["workloads"] if item["workload_id"] == "hk_auction_0920")
    assert _runner_command_complete(row["command"], Path(__file__).resolve().parents[1])


def test_executor_uses_v35_wrapper_and_fixed_roots(tmp_path: Path) -> None:
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from contracts.runtime_tasks import DispatchMode, DispatchRequest

    package = tmp_path / "package"
    (package / "ops").mkdir(parents=True)
    (tmp_path / "ops").mkdir(parents=True)
    (tmp_path / "ops" / "ensure_hk_security_master.py").write_text("# fixture\n", encoding="utf-8")
    calls = []

    def runner(command, *, cwd, timeout_seconds, env):
        calls.append((command, cwd, timeout_seconds, env))
        return __import__("subprocess").CompletedProcess(command, 0, "{}", "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared",
        hk_universe_root=tmp_path / "hk-universe",
        shared_package_root=package,
        shared_futu_python_executable=tmp_path / "futu-python",
        repo_root=tmp_path,
        runner=runner,
    )
    result = registry._hk_auction_0920(
        DispatchRequest(
            scheduled_date=TRADE_DATE,
            business_date=TRADE_DATE,
            target_date=TRADE_DATE,
            slot="0915",
            mode=DispatchMode.LIVE,
        )
    )
    assert result["status"] == "SUCCEEDED"
    assert len(calls) == 2
    security_command, security_cwd, security_timeout, security_env = calls[0]
    assert security_command[2] == "ops.ensure_hk_security_master"
    assert security_command[3:] == [
        "--store-root", str(tmp_path / "shared"),
        "--universe-root", str(tmp_path / "hk-universe"),
        "--shared-package-root", str(package),
        "--trade-date", TRADE_DATE,
        "--futu-python", str(tmp_path / "futu-python"),
    ]
    assert security_cwd == tmp_path
    assert security_timeout == 300
    assert security_env["V3_SHARED_DATA_STORE_ROOT"] == str(tmp_path / "shared")

    capture_command, capture_cwd, capture_timeout, capture_env = calls[1]
    assert capture_command[2] == "ops.run_hkconnect_0915_0920_capture"
    assert capture_command[3:] == [
        "--data-root", str(tmp_path / "data"),
        "--shared-data-root", str(tmp_path / "shared"),
        "--shared-package-root", str(package),
        "--trade-date", TRADE_DATE,
        "--futu-python", str(tmp_path / "futu-python"),
    ]
    assert capture_cwd == tmp_path
    assert capture_timeout == 420
    assert capture_env["V3_SHARED_DATA_STORE_ROOT"] == str(tmp_path / "shared")


def test_hk_0920_executor_uses_long_capture_timeout_only_for_this_workload(
    tmp_path: Path,
) -> None:
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from contracts.runtime_tasks import DispatchMode, DispatchRequest

    calls: list[int] = []
    (tmp_path / "ops").mkdir(parents=True)
    (tmp_path / "ops" / "ensure_hk_security_master.py").write_text("# fixture\n", encoding="utf-8")

    def runner(command, *, cwd, timeout_seconds, env):
        del command, cwd, env
        calls.append(timeout_seconds)
        return __import__("subprocess").CompletedProcess([], 0, "{}", "")

    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared",
        hk_universe_root=tmp_path / "hk-universe",
        shared_package_root=tmp_path / "package",
        repo_root=tmp_path,
        runner=runner,
    )
    result = registry._hk_auction_0920(
        DispatchRequest(
            scheduled_date=TRADE_DATE,
            business_date=TRADE_DATE,
            target_date=TRADE_DATE,
            slot="0915",
            mode=DispatchMode.LIVE,
        )
    )

    assert result["status"] == "SUCCEEDED"
    assert calls == [300, 420]


def test_hk_0920_calendar_gate_ignores_a_share_closure(monkeypatch: pytest.MonkeyPatch) -> None:
    from contracts.trading_calendar import TradingDayState
    from ops import run_hkconnect_0915_0920_capture as capture

    monkeypatch.setattr(capture, "load_market_calendar", lambda: object())
    monkeypatch.setattr(
        capture,
        "resolve_market_states",
        lambda _calendar, _date: {
            "a_share": TradingDayState.NON_TRADING_DAY,
            "hk_securities": TradingDayState.FULL_TRADING_DAY,
            "hk_connect": TradingDayState.FULL_TRADING_DAY,
        },
    )

    result = capture._calendar_gate(TRADE_DATE)

    assert result["status"] == "ELIGIBLE"


def test_hk_open_connect_closed_day_reaches_existing_capture_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contracts.trading_calendar import TradingDayState
    from ops import run_hkconnect_0915_0920_capture as capture

    trade_date = "20260925"
    monkeypatch.setitem(globals(), "TRADE_DATE", trade_date)
    monkeypatch.setitem(globals(), "SIGNAL_DATE", "20260924")
    gate = capture._calendar_gate(trade_date)
    assert gate["status"] == "ELIGIBLE"
    assert gate["calendar"]["hk_securities"] == TradingDayState.FULL_TRADING_DAY.value
    assert gate["calendar"]["hk_connect"] == TradingDayState.NON_TRADING_DAY.value

    data_root, shared_root, package_root, shared, consumer, _calls, _sha = _shared_fixture(tmp_path)
    invoked: list[str] = []
    run_capture = shared.run_capture

    def capture_fixture(root, date, futu_python, **kwargs):
        invoked.append(date)
        return run_capture(root, date, futu_python, **kwargs)

    result = materialize_hkconnect_0915_0920(
        data_root,
        shared_root,
        package_root,
        trade_date,
        Path(__file__),
        shared_module=shared,
        consumer_module=consumer,
        capture_runner=capture_fixture,
    )
    assert result["status"] == "MATERIALIZED_FROM_SHARED_HK_0920"
    assert invoked == [trade_date]
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False


def test_hk_securities_holiday_skips_existing_capture_owner() -> None:
    from ops import run_hkconnect_0915_0920_capture as capture

    result = capture._calendar_gate("20260217")
    assert result["status"] == "SKIPPED_NON_TRADING_DAY"


def test_scheduled_slot_cli_passes_all_shared_hk_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ops import run_scheduled_slot as scheduled_slot

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        scheduled_slot,
        "compute_dates",
        lambda **_kwargs: {
            "scheduled_date": TRADE_DATE,
            "business_date": TRADE_DATE,
            "target_date": TRADE_DATE,
        },
    )

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {
            "status": "SUCCEEDED",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(scheduled_slot, "run_scheduled_slot", fake_run)
    shared_data_root = tmp_path / "shared-data"
    hk_universe_root = tmp_path / "hk-universe"
    shared_package_root = tmp_path / "shared-package"

    assert scheduled_slot.main(
        [
            "--slot", "0915",
            "--date", TRADE_DATE,
            "--data-root", str(tmp_path / "data"),
            "--shared-data-root", str(shared_data_root),
            "--hk-universe-root", str(hk_universe_root),
            "--shared-package-root", str(shared_package_root),
        ]
    ) == 0
    capsys.readouterr()
    assert captured["shared_data_root"] == shared_data_root
    assert captured["hk_universe_root"] == hk_universe_root
    assert captured["shared_package_root"] == shared_package_root


def test_preselection_uses_same_hk_security_master_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infrastructure.scheduling import executor_registry as registry_module
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from contracts.runtime_tasks import DispatchMode, DispatchRequest

    package = tmp_path / "package"
    scripts = package / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "materialize_hk_0_2.py",
    ):
        (scripts / name).write_text("# fixture\n", encoding="utf-8")
    (tmp_path / "ops").mkdir(parents=True)
    (tmp_path / "ops" / "ensure_hk_security_master.py").write_text("# fixture\n", encoding="utf-8")
    selector = tmp_path / "selector.parquet"
    selector.write_bytes(b"fixture")
    monkeypatch.setattr(registry_module, "resolve_selector_panel", lambda *_args: selector)

    calls: list[tuple[str, list[str], dict[str, object]]] = []
    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared-data",
        hk_universe_root=tmp_path / "hk-universe",
        shared_package_root=package,
        selector_data_root=tmp_path / "selector-root",
        preselection_input_root=tmp_path / "preselection-input",
        repo_root=tmp_path,
        shared_futu_python_executable=tmp_path / "futu-python",
    )

    def fake_run(module, arguments, **kwargs):
        calls.append((module, list(arguments), dict(kwargs)))
        return {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "stdout": "{}",
            "stderr": "",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    registry._run = fake_run
    result = registry._preselection_pools(
        DispatchRequest(
            scheduled_date=TRADE_DATE,
            business_date=TRADE_DATE,
            target_date=TRADE_DATE,
            slot="1730",
            mode=DispatchMode.LIVE,
        )
    )

    assert result["status"] == "SUCCEEDED"
    modules = [module for module, _arguments, _kwargs in calls]
    assert "scripts.acquire_hk_security_master" not in modules
    assert modules.count("ops.ensure_hk_security_master") == 1
    module, arguments, kwargs = next(
        item for item in calls if item[0] == "ops.ensure_hk_security_master"
    )
    assert module == "ops.ensure_hk_security_master"
    assert arguments == [
        "--store-root", str(tmp_path / "shared-data"),
        "--universe-root", str(tmp_path / "hk-universe"),
        "--shared-package-root", str(package),
        "--trade-date", TRADE_DATE,
        "--futu-python", str(tmp_path / "futu-python"),
    ]
    assert kwargs["cwd"] == tmp_path
    assert "python_executable" not in kwargs
