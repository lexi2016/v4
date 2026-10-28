from __future__ import annotations

import contextlib
import importlib
import io
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


APP_ROOT = Path(__file__).resolve().parents[1]


def _request(business_date: str):
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from contracts.trading_calendar import load_market_calendar, next_session

    target_date = next_session(
        load_market_calendar(), business_date, market="a_share"
    )
    return DispatchRequest(
        scheduled_date=business_date,
        business_date=business_date,
        target_date=target_date,
        slot="1720",
        mode=DispatchMode.REPLAY,
    )


def _pool(
    trade_date: str,
    pool_id: str,
    *,
    status: str,
    source_role: str,
    rows: list[dict],
) -> dict:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "target_date": trade_date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": "A",
        "status": status,
        "producer_id": "test-v192-consumer",
        "source_role": source_role,
        "source_path": f"runs/{trade_date}/test/artifact.csv",
        "source_sha256": "a" * 64,
        "source_run_id": "test-v192-run",
        "source_row_count": len(rows),
        "artifact_role": "A_SHARE_V192_PREMARKET_POOL_V3",
        "artifact_version": "V3",
        "signal_date": "20260826",
        "source_merge_role": "MAIN_STAGE_INPUT",
        "stage_selection_eligible": True,
        "rows": rows,
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _a_reader(target_date: str, signal_date: str):
    from domains import preselection_materializer as materializer

    row = {field: "x" for field in materializer.SHARED_V192_ENTRY_FIELDS}
    row.update(
        ts_code="000001.SZ",
        review_rank_v19=1,
        signal_date=signal_date,
        target_date=target_date,
        rank_usage_boundary=materializer.SHARED_V192_RANK_BOUNDARY,
        formal_recommendation_allowed="false",
        formula_source=materializer.SHARED_V192_FORMULA_SOURCE,
        gold_brick_context="none",
        stock_name="平安银行",
    )
    verification = {
        "run_id": "synthetic-a-v192-run",
        "artifact_relative": f"runs/{target_date}/A_SHARE_V192_PREMARKET_POOL_V3/synthetic-a-v192-run/artifact.csv",
        "artifact_sha256": "a" * 64,
        "row_count": 1,
    }
    return SimpleNamespace(
        rows=[row],
        run=SimpleNamespace(
            verification=verification,
            receipt={
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
        ),
    )


def _hk_reader(target_date: str, signal_date: str, eligibility_date: str):
    rows = [
        {
            "code_norm": f"{rank:05d}",
            "rank": rank,
            "score_prob_active": 101 - rank,
            "signal_date": signal_date,
            "target_date": target_date,
            "d1_freshness_status": "PASS",
            "selected_strategy": "prob_active",
            "name": f"港股{rank}",
        }
        for rank in range(1, 101)
    ]
    verification = {
        "run_id": f"synthetic-hk-{target_date}",
        "artifact_relative": f"runs/{target_date}/HK_CONNECT_D1_TOP100_0_2/synthetic-hk-{target_date}/artifact.csv",
        "artifact_sha256": "b" * 64,
        "manifest_sha256": "c" * 64,
        "receipt_sha256": "d" * 64,
        "row_count": 100,
    }
    manifest = {
        "provenance": {
            "signal_date": signal_date,
            "eligibility_source_date": eligibility_date,
            "security_master_trade_date": eligibility_date,
            "security_master_run_id": f"synthetic-master-{eligibility_date}",
            "security_master_artifact_sha256": "e" * 64,
            "security_master_captured_at": f"{eligibility_date[:4]}-{eligibility_date[4:6]}-{eligibility_date[6:]}T17:00:00+08:00",
        }
    }
    return SimpleNamespace(
        rows=rows,
        run=SimpleNamespace(
            verification=verification,
            receipt={
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            manifest=manifest,
        ),
    )


def _pool_snapshot(data_root: Path, trade_date: str, pool_id: str) -> dict:
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    return PreselectionPoolStore(data_root).read_pool_snapshot(trade_date, pool_id)


def _run_scheduled_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    market_scope: str | None,
) -> tuple[int, dict, Path]:
    cli = importlib.import_module("ops.materialize_scheduled_preselection")
    target_date = "20261008"
    signal_date = "20261002"
    hk_target_date = "20261005"
    hk_signal_date = "20261002"
    eligibility_date = "20260930"
    input_root = tmp_path / "input"
    input_root.mkdir(parents=True)
    shared_root = tmp_path / "shared"
    (shared_root / "assets" / "hk_0_2").mkdir(parents=True)
    package_root = tmp_path / "package"
    (package_root / "shared_data").mkdir(parents=True)
    (package_root / "scripts").mkdir()
    data_root = tmp_path / "data"

    def missing_baimao(*_args, **_kwargs):
        return cli._missing(
            target_date,
            pool_id="a_share_baimao_research_map",
            display_name="白毛卡点研究池",
            market="A",
            reason="TEST_A_INPUT_MISSING",
        )

    def missing_a(*_args, **_kwargs):
        raise FileNotFoundError("synthetic A formal source missing")

    def hk_reader(_root, *, target_date, expected_signal_date, expected_eligibility_source_date):
        return _hk_reader(target_date, expected_signal_date, expected_eligibility_source_date)

    monkeypatch.setattr(cli, "load_baimao_preselection_pool", missing_baimao)
    args = [
        "--trade-date", target_date,
        "--signal-date", signal_date,
        "--hk-target-date", hk_target_date,
        "--hk-signal-date", hk_signal_date,
        "--hk-eligibility-source-date", eligibility_date,
        "--input-root", str(input_root),
        "--data-root", str(data_root),
        "--shared-data-root", str(shared_root),
        "--shared-package-root", str(package_root),
    ]
    if market_scope is not None:
        args.extend(["--market-scope", market_scope])
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = cli.main(args, pool_reader=missing_a, hk_pool_reader=hk_reader)
    return exit_code, json.loads(output.getvalue()), data_root


def _run_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    business_date: str,
    *,
    a_input_ready: bool,
    hk_input_ready: bool = True,
    selector_ready: bool,
    hk_producer_success: bool = True,
):
    from contracts.trading_calendar import (
        TradingDayState,
        load_market_calendar,
        next_session,
        previous_session,
        resolve_market_states,
    )
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    import infrastructure.scheduling.executor_registry as registry_module

    cli = importlib.import_module("ops.materialize_scheduled_preselection")
    calls: list[tuple[str, list[str]]] = []
    shared = tmp_path / "shared-data"
    for directory in (
        shared / "universes",
        shared / "assets" / "hk_security_master",
        shared / "assets" / "hk_0_2",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    package = tmp_path / "shared-package"
    scripts = package / "scripts"
    scripts.mkdir(parents=True)
    (package / "shared_data").mkdir()
    shared_hk_module = APP_ROOT / "upstreams" / "v3_shared_data" / "shared_data" / "hk_0_2.py"
    if shared_hk_module.is_file():
        (package / "shared_data" / "hk_0_2.py").write_bytes(shared_hk_module.read_bytes())
    for name in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "materialize_hk_0_2.py",
    ):
        (scripts / name).write_text("# isolated test stub\n", encoding="utf-8")
    selector_root = tmp_path / "selector"
    selector_root.mkdir()
    selector_path = selector_root / "selector_ready.parquet"
    selector_path.write_bytes(b"test-selector-panel")
    if selector_ready:
        monkeypatch.setattr(
            registry_module,
            "resolve_selector_panel",
            lambda *_args, **_kwargs: selector_path,
        )
        try:
            candidate_executor = importlib.import_module(
                "infrastructure.scheduling.executor_registry_preselection"
            )
        except ModuleNotFoundError:
            candidate_executor = None
        if candidate_executor is not None and hasattr(candidate_executor, "resolve_selector_panel"):
            monkeypatch.setattr(candidate_executor, "resolve_selector_panel", lambda *_a, **_k: selector_path)

    calendar = load_market_calendar()
    a_target = next_session(calendar, business_date, market="a_share")
    hk_target = next_session(calendar, business_date, market="hk_securities")
    hk_state = resolve_market_states(calendar, business_date)["hk_securities"]
    hk_signal = (
        business_date
        if hk_state in {
            TradingDayState.FULL_TRADING_DAY,
            TradingDayState.HALF_TRADING_DAY_AM,
        }
        else previous_session(calendar, business_date, market="hk_securities")
    )
    # The executor owns this date calculation; the test checks its returned value below.
    eligibility = previous_session(calendar, hk_target, market="hk_connect")

    def pool_reader(_root, *, target_date, expected_signal_date):
        if not a_input_ready:
            raise FileNotFoundError("A V192 exact input missing")
        return _a_reader(target_date, expected_signal_date)

    def hk_pool_reader(_root, *, target_date, expected_signal_date, **kwargs):
        if not hk_input_ready:
            raise FileNotFoundError("HK exact source missing")
        eligibility_date = kwargs.get("expected_eligibility_source_date", expected_signal_date)
        return _hk_reader(target_date, expected_signal_date, eligibility_date)

    def runner(command, *, cwd, timeout_seconds, env):
        module = command[2]
        arguments = list(command[3:])
        calls.append((module, arguments))
        if module == "ops.materialize_scheduled_preselection":
            if not a_input_ready:
                def missing_baimao(*_args, **_kwargs):
                    return cli._missing(
                        a_target,
                        pool_id="a_share_baimao_research_map",
                        display_name="白毛卡点研究池",
                        market="A",
                        reason="TEST_A_INPUT_MISSING",
                    )
                monkeypatch.setattr(cli, "load_baimao_preselection_pool", missing_baimao)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = cli.main(
                    arguments,
                    pool_reader=pool_reader,
                    hk_pool_reader=hk_pool_reader,
                )
            from infrastructure.scheduling.executor_registry import _STDOUT_LIMIT, _bounded

            child_stdout = output.getvalue()
            assert len(child_stdout) <= _STDOUT_LIMIT
            return subprocess.CompletedProcess(
                command, exit_code, _bounded(child_stdout, _STDOUT_LIMIT), ""
            )
        exit_code = 1 if module == "scripts.materialize_hk_0_2" and not hk_producer_success else 0
        return subprocess.CompletedProcess(command, exit_code, json.dumps({"status": "READY"}), "")

    universe = tmp_path / "hk-universe"
    (universe / "universes").mkdir(parents=True)
    (universe / "assets" / "hk_security_master").mkdir(parents=True)
    data_root = tmp_path / "data"
    registry = FixedExecutorRegistry(
        data_root=data_root,
        shared_data_root=shared,
        hk_universe_root=universe,
        shared_package_root=package,
        shared_futu_python_executable=Path("/synthetic/futu-python"),
        selector_data_root=selector_root if selector_ready else None,
        preselection_input_root=data_root / "preselection_inputs",
        repo_root=APP_ROOT,
        runner=runner,
        hk_0_2_tdx_root=tmp_path / "hk-tdx",
    )
    request = _request(business_date)
    from types import SimpleNamespace

    result = registry(SimpleNamespace(workload_id="preselection_pools"), request)
    return result, calls, data_root, request, hk_target, hk_signal, eligibility


@pytest.mark.parametrize("business_date", ["20261002", "20261005"])
def test_hk_open_a_closed_runs_only_hk_formal_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, business_date: str
) -> None:
    result, calls, data_root, request, hk_target, hk_signal, eligibility = _run_registry(
        tmp_path,
        monkeypatch,
        business_date,
        a_input_ready=False,
        selector_ready=False,
    )

    modules = [module for module, _arguments in calls]
    assert "scripts.capture_public_fupan" not in modules
    assert "ops.materialize_shared_v192_preselection" not in modules
    cli_call = next(arguments for module, arguments in calls if module == "ops.materialize_scheduled_preselection")
    assert cli_call[cli_call.index("--market-scope") + 1] == "HK_CONNECT"
    assert result["status"] == "SUCCEEDED"
    assert result["a_lane_status"] == "NOT_APPLICABLE"
    assert result["hk_lane_status"] in {"READY", "SUCCEEDED"}
    snapshot = _pool_snapshot(data_root, hk_target, "hkconnect_d1_top100")
    artifact = snapshot["artifact"]
    assert len(artifact["rows"]) == 100
    assert len({row["symbol"] for row in artifact["rows"]}) == 100
    assert {row["target_date"] for row in artifact["rows"]} == {hk_target}
    assert {row["signal_date"] for row in artifact["rows"]} == {hk_signal}
    assert artifact["historical_provenance"]["eligibility_source_date"] == eligibility
    assert artifact["source_sha256"] == "b" * 64
    assert all(artifact[key] is False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
    day_dir = data_root / "preselection_pools" / hk_target
    assert {path.name for path in day_dir.glob("*.json")} == {
        "hkconnect_d1_top100.json",
        "manifest.json",
    }


def test_a_gap_does_not_block_ready_hk_and_remains_in_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    business_date = "20260827"
    result, calls, data_root, _request_value, hk_target, hk_signal, eligibility = _run_registry(
        tmp_path,
        monkeypatch,
        business_date,
        a_input_ready=False,
        selector_ready=False,
    )

    modules = [module for module, _arguments in calls]
    assert "ops.materialize_shared_v192_preselection" not in modules
    assert "scripts.capture_public_fupan" in modules
    assert result["status"] == "SUCCEEDED"
    assert result["a_selector_status"] == "CANNOT_CONFIRM"
    assert result["hk_lane_status"] in {"READY", "SUCCEEDED"}
    gate = result["formal_pool_gate"]
    assert gate["status"] == "PARTIAL"
    assert gate["required"]["a_d1_premarket_pool"]["ready"] is False
    assert gate["required"]["hkconnect_d1_top100"]["ready"] is True
    artifact = _pool_snapshot(data_root, hk_target, "hkconnect_d1_top100")["artifact"]
    assert len(artifact["rows"]) == 100
    assert artifact["target_date"] == hk_target
    assert artifact["signal_date"] == hk_signal
    assert artifact["source_run_id"] == f"synthetic-hk-{hk_target}"
    assert artifact["source_sha256"] == "b" * 64
    if eligibility != hk_signal:
        assert artifact["historical_provenance"]["eligibility_source_date"] == eligibility
    else:
        assert eligibility == hk_signal


def test_a_only_date_keeps_a_lane_and_does_not_materialize_hk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    business_date = "20260407"
    result, calls, data_root, request, hk_target, _hk_signal, _eligibility = _run_registry(
        tmp_path,
        monkeypatch,
        business_date,
        a_input_ready=True,
        selector_ready=True,
    )

    modules = [module for module, _arguments in calls]
    assert "scripts.capture_public_fupan" in modules
    assert "ops.materialize_shared_v192_preselection" in modules
    assert "scripts.update_hk_0_2_panel" not in modules
    assert "ops.ensure_hk_security_master" not in modules
    assert "scripts.materialize_hk_0_2" not in modules
    cli_call = next(arguments for module, arguments in calls if module == "ops.materialize_scheduled_preselection")
    assert cli_call[cli_call.index("--market-scope") + 1] == "A_SHARE"
    assert result["status"] == "SUCCEEDED"
    assert result["hk_lane_status"] == "NOT_APPLICABLE"
    _pool_snapshot(data_root, request.target_date, "a_d1_premarket_pool")
    assert not (data_root / "preselection_pools" / hk_target / "hkconnect_d1_top100.json").exists()


def test_hk_strict_source_failure_is_not_reported_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from infrastructure.scheduling.executor_registry import WorkloadExecutionError

    with pytest.raises(WorkloadExecutionError) as raised:
        _run_registry(
            tmp_path,
            monkeypatch,
            "20261002",
            a_input_ready=False,
            hk_input_ready=False,
            selector_ready=False,
            hk_producer_success=False,
        )
    result = raised.value.result
    assert result["status"] == "FAILED"
    assert result["hk_lane_status"] == "CANNOT_CONFIRM"
    assert result["formal_pool_gate"]["required"]["hkconnect_d1_top100"]["ready"] is False


def test_normal_a_and_hk_lanes_keep_independent_ready_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    business_date = "20260827"
    result, calls, data_root, request, hk_target, _hk_signal, _eligibility = _run_registry(
        tmp_path,
        monkeypatch,
        business_date,
        a_input_ready=True,
        selector_ready=True,
    )

    modules = [module for module, _arguments in calls]
    assert "ops.materialize_shared_v192_preselection" in modules
    assert "scripts.materialize_hk_0_2" in modules
    gate = result["formal_pool_gate"]
    assert gate["status"] == "READY"
    assert gate["required"]["a_d1_premarket_pool"]["ready"] is True
    assert gate["required"]["hkconnect_d1_top100"]["ready"] is True
    child_payload = json.loads(result["stdout"])
    lineage_by_path = {item["artifact_path"]: item for item in child_payload["artifacts"]}
    expected_paths = {
        f"preselection_pools/{request.target_date}/a_d1_premarket_pool.json",
        f"preselection_pools/{hk_target}/hkconnect_d1_top100.json",
    }
    assert set(lineage_by_path) == expected_paths
    assert all(
        set(item) == {"artifact_path", "receipt_path", "sha256"}
        for item in lineage_by_path.values()
    )
    _pool_snapshot(data_root, request.target_date, "a_d1_premarket_pool")
    _pool_snapshot(data_root, hk_target, "hkconnect_d1_top100")


def test_no_scope_cli_preserves_canonical_and_r9_legacy_contracts_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_scope_dir = tmp_path / "no_scope"
    no_scope_dir.mkdir()
    exit_code, body, _data_root = _run_scheduled_cli(
        no_scope_dir, monkeypatch, market_scope=None
    )
    if APP_ROOT.name == "app":
        # Immutable R9's no-scope CLI required both formal pools.
        assert exit_code == 1
        assert body["status"] == "FAILED"
        assert body["formal_pool_gate"]["status"] == "FAILED"
        assert body["formal_pool_gate"]["required"]["hkconnect_d1_top100"]["ready"] is True
        assert body["formal_pool_gate"]["missing_or_invalid"] == [
            "a_d1_premarket_pool"
        ]
    else:
        # Preserve the canonical V4 no-scope behavior that predates revision 2.
        assert exit_code == 0
        assert body["status"] == "PARTIAL"
        assert body["formal_pool_gate"]["status"] == "PARTIAL"

    explicit_dir = tmp_path / "explicit_cross_market"
    explicit_dir.mkdir()
    explicit_exit, explicit_body, _ = _run_scheduled_cli(
        explicit_dir, monkeypatch, market_scope="CROSS_MARKET"
    )
    assert explicit_exit == 0
    assert explicit_body["status"] == "PARTIAL"
    assert explicit_body["formal_pool_gate"]["required"]["a_d1_premarket_pool"]["ready"] is False
    assert explicit_body["formal_pool_gate"]["required"]["hkconnect_d1_top100"]["ready"] is True


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("target_date", "19000101"),
        ("target_date", None),
        ("signal_date", "19000101"),
        ("signal_date", None),
    ],
)
def test_hk_formal_gate_rejects_missing_or_wrong_row_dates(
    field: str, bad_value: str | None
) -> None:
    cli = importlib.import_module("ops.materialize_scheduled_preselection")
    target_date = "20261005"
    signal_date = "20261002"
    rows = [
        {
            "symbol": f"HK.{rank:05d}",
            "target_date": target_date,
            "signal_date": signal_date,
        }
        for rank in range(1, 101)
    ]
    if bad_value is None:
        rows[0].pop(field)
    else:
        rows[0][field] = bad_value
    artifact = {
        "pool_id": "hkconnect_d1_top100",
        "status": "STRICT_0_2_READY",
        "trade_date": target_date,
        "target_date": target_date,
        "signal_date": signal_date,
        "rows": rows,
    }

    gate = cli._formal_pool_gate(
        [artifact],
        market_scope="HK_CONNECT",
        hk_target_date=target_date,
        hk_signal_date=signal_date,
    )
    assert gate["required"]["hkconnect_d1_top100"]["ready"] is False


def test_hk_formal_gate_uses_requested_dates_not_artifact_envelope() -> None:
    cli = importlib.import_module("ops.materialize_scheduled_preselection")
    target_date = "20261005"
    signal_date = "20261002"
    artifact = {
        "pool_id": "hkconnect_d1_top100",
        "status": "STRICT_0_2_READY",
        "trade_date": target_date,
        "target_date": target_date,
        "signal_date": signal_date,
        "rows": [
            {
                "symbol": f"HK.{rank:05d}",
                "target_date": target_date,
                "signal_date": signal_date,
            }
            for rank in range(1, 101)
        ],
    }

    gate = cli._formal_pool_gate(
        [artifact],
        market_scope="HK_CONNECT",
        hk_target_date="20261006",
        hk_signal_date=signal_date,
    )

    assert gate["required"]["hkconnect_d1_top100"]["ready"] is False


def test_cli_output_preserves_store_artifact_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hashlib import sha256

    output_dir = tmp_path / "explicit_hk"
    output_dir.mkdir()
    exit_code, body, data_root = _run_scheduled_cli(
        output_dir, monkeypatch, market_scope="HK_CONNECT"
    )

    assert exit_code == 0
    assert body["status"] == "READY"
    assert len(body["artifacts"]) == 1
    receipt = body["artifacts"][0]
    assert receipt["artifact_path"] == "preselection_pools/20261005/hkconnect_d1_top100.json"
    assert receipt["receipt_path"] == "preselection_pools/20261005/receipts/hkconnect_d1_top100.json"
    artifact_file = data_root / receipt["artifact_path"]
    receipt_file = data_root / receipt["receipt_path"]
    assert artifact_file.is_file()
    assert receipt_file.is_file()
    assert receipt["sha256"] == sha256(artifact_file.read_bytes()).hexdigest()
