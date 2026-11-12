from __future__ import annotations

import json
import sys
from pathlib import Path


def _pool(
    trade_date: str,
    pool_id: str,
    *,
    status: str,
    source_role: str,
    rows: list[dict] | None = None,
    cannot_confirm: list[str] | None = None,
) -> dict:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": pool_id,
        "display_name": pool_id,
        "market": "A" if pool_id != "hkconnect_d1_top100" else "HK",
        "status": status,
        "producer_id": "test-producer",
        "source_role": source_role,
        "source_path": "test-source",
        "source_sha256": "e" * 64 if source_role == "EXPECTED_MISSING" else "f" * 64,
        "rows": list(rows or []),
        "cannot_confirm": list(cannot_confirm or []),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_existing_formal_pair_does_not_skip_optional_lanes(tmp_path: Path, monkeypatch) -> None:
    import ops.materialize_scheduled_preselection as materializer

    trade_date = "20260827"
    signal_date = "20260826"
    input_day = tmp_path / "inputs" / trade_date
    input_day.mkdir(parents=True)
    for name in ("fupan.csv", "fupan.manifest.json", "stage7.csv", "stage7.manifest.json"):
        (input_day / name).write_text("fixture", encoding="utf-8")

    formal_a = _pool(
        trade_date,
        "a_d1_premarket_pool",
        status="V192_CANDIDATE_READY",
        source_role="SHARED_VERIFIED_V192",
        rows=[{"code": "000001"}],
    )
    formal_hk = _pool(
        trade_date,
        "hkconnect_d1_top100",
        status="HK_0_2_TOP100_READY",
        source_role="SHARED_VERIFIED_HK_0_2",
        rows=[{"code": "00001"}],
    )
    calls: list[str] = []

    def lane(pool_id: str):
        def build(*_args, **_kwargs):
            calls.append(pool_id)
            return _pool(
                trade_date,
                pool_id,
                status="READY",
                source_role="VERIFIED_D1_FUPAN_REVIEW" if "fupan" in pool_id else "VERIFIED_D1_STAGE7_REPLAY",
                rows=[{"code": "000001"}],
            )

        return build

    monkeypatch.setattr(materializer, "build_shared_v192_premarket_pool", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("A formal producer was re-entered")))
    monkeypatch.setattr(materializer, "build_shared_hk_0_2_pool", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("HK formal producer was re-entered")))
    monkeypatch.setattr(materializer, "build_fupan_watchlist_pool", lane("a_d1_fupan_watchlist_pool"))
    monkeypatch.setattr(materializer, "build_stage7_review_pool", lane("a_d1_stage7_fenshi_review_pool"))
    monkeypatch.setattr(
        materializer,
        "build_hourly_research_pool",
        lambda *_a, **_k: calls.append("a_share_research_recommendation_pool") or _pool(
            trade_date,
            "a_share_research_recommendation_pool",
            status="RESEARCH_RECOMMENDATION_POOL_READY",
            source_role="VERIFIED_HOURLY_RESEARCH",
            rows=[{"code": "000001"}],
        ),
    )

    artifacts = materializer.build_scheduled_artifacts(
        trade_date=trade_date,
        signal_date=signal_date,
        selector=None,
        input_root=tmp_path / "inputs",
        shared_data_root=tmp_path / "shared",
        shared_package_root=tmp_path / "package",
        data_root=tmp_path / "data",
        reuse_formal_pools={
            "a_d1_premarket_pool": formal_a,
            "hkconnect_d1_top100": formal_hk,
        },
    )

    by_id = {artifact["pool_id"]: artifact for artifact in artifacts}
    assert by_id["a_d1_premarket_pool"] == formal_a
    assert by_id["hkconnect_d1_top100"] == formal_hk
    assert set(calls) == {
        "a_d1_fupan_watchlist_pool",
        "a_d1_stage7_fenshi_review_pool",
        "a_share_research_recommendation_pool",
    }


def test_scheduler_reuse_runs_optional_materializer(tmp_path: Path, monkeypatch) -> None:
    import subprocess
    from contracts.runtime_tasks import DispatchMode, DispatchRequest
    from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
    from infrastructure.scheduling import executor_registry as registry_module

    shared_package = tmp_path / "shared"
    scripts = shared_package / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "capture_public_fupan.py",
        "materialize_v192_selector.py",
        "update_hk_0_2_panel.py",
        "materialize_hk_0_2.py",
    ):
        (scripts / name).write_text("# fixture\n", encoding="utf-8")
    repo_root = tmp_path / "repo"
    (repo_root / "ops").mkdir(parents=True)
    (repo_root / "ops" / "ensure_hk_security_master.py").write_text(
        "# fixture\n", encoding="utf-8"
    )
    registry = FixedExecutorRegistry(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared-data",
        hk_universe_root=tmp_path / "hk-universe",
        shared_package_root=shared_package,
        preselection_input_root=tmp_path / "preselection-input",
        repo_root=repo_root,
    )
    monkeypatch.setattr(
        registry,
        "_verified_formal_pool_reuse",
        lambda _date: {
            "status": "SUCCEEDED",
            "workload_id": "preselection_pools",
            "formal_pool_reuse": {"a_row_count": 48, "hk_row_count": 100},
        },
    )
    calls: list[tuple[str, list[str]]] = []

    def fake_run(module, arguments, **_kwargs):
        calls.append((module, list(arguments)))
        return {
            "status": "SUCCEEDED",
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(registry, "_run", fake_run)
    request = DispatchRequest(
        scheduled_date="20260826",
        business_date="20260826",
        target_date="20260827",
        slot="1800",
        mode=DispatchMode.LIVE,
    )
    result = registry._preselection_pools(request)

    modules = [module for module, _arguments in calls]
    assert "scripts.capture_public_fupan" in modules
    assert "ops.materialize_d1_review_lanes" not in modules
    assert "ops.materialize_scheduled_preselection" in modules
    assert "ops.materialize_shared_v192_preselection" not in modules
    assert "scripts.materialize_hk_0_2" not in modules
    scheduled_args = next(
        args for module, args in calls
        if module == "ops.materialize_scheduled_preselection"
    )
    assert "--reuse-formal-pools" in scheduled_args
    assert result["formal_pool_reuse"]["a_row_count"] == 48



def test_expected_missing_pool_can_be_upgraded_with_revision(tmp_path: Path) -> None:
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    store = PreselectionPoolStore(tmp_path / "data")
    missing = _pool(
        "20260827",
        "a_d1_stage7_fenshi_review_pool",
        status="CANNOT_CONFIRM",
        source_role="EXPECTED_MISSING",
        cannot_confirm=["A_D1_STAGE7_FENSHI_EVIDENCE_MISSING"],
    )
    ready = _pool(
        "20260827",
        "a_d1_stage7_fenshi_review_pool",
        status="READY",
        source_role="VERIFIED_D1_STAGE7_REPLAY",
        rows=[{"code": "000001"}],
    )
    first = store.materialize(missing)
    second = store.materialize(ready)

    assert first["sha256"] != second["sha256"]
    assert store.read_pool("20260827", "a_d1_stage7_fenshi_review_pool")["status"] == "READY"
    revision = tmp_path / "data" / "preselection_revisions" / "20260827" / f"{first['sha256']}.json"
    assert revision.is_file()


def test_non_refreshable_pool_reentry_does_not_create_revision(tmp_path: Path) -> None:
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    store = PreselectionPoolStore(tmp_path / "data")
    formal = _pool(
        "20260827",
        "a_d1_premarket_pool",
        status="V192_CANDIDATE_READY",
        source_role="SHARED_VERIFIED_V192",
        rows=[{"code": "000001"}],
    )

    first = store.materialize(formal)
    second = store.materialize(formal)

    assert second == first
    assert not (tmp_path / "data" / "preselection_revisions").exists()


def test_verified_hourly_research_can_append_a_verified_source_slot(
    tmp_path: Path,
) -> None:
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    store = PreselectionPoolStore(tmp_path / "data")
    first = _pool(
        "20260827",
        "a_share_research_recommendation_pool",
        status="RESEARCH_RECOMMENDATION_POOL_READY",
        source_role="VERIFIED_HOURLY_RESEARCH",
        rows=[{"symbol": "A.000001", "source_article_ids": ["article-1"]}],
    )
    first["source_path"] = "research/hourly/live/20260826/1200.json"
    first["source_sha256"] = "a" * 64
    second = _pool(
        "20260827",
        "a_share_research_recommendation_pool",
        status="RESEARCH_RECOMMENDATION_POOL_READY",
        source_role="VERIFIED_HOURLY_RESEARCH",
        rows=[
            {"symbol": "A.000001", "source_article_ids": ["article-1"]},
            {"symbol": "A.000002", "source_article_ids": ["article-2"]},
        ],
    )
    second["source_path"] = (
        "research/hourly/live/20260826/1200.json|"
        "research/hourly/live/20260826/1300.json"
    )
    second["source_sha256"] = "b" * 64

    first_result = store.materialize(first)
    second_result = store.materialize(second)

    assert first_result["sha256"] != second_result["sha256"]
    assert store.read_pool(
        "20260827", "a_share_research_recommendation_pool"
    )["rows"] == second["rows"]
    revision = (
        tmp_path
        / "data"
        / "preselection_revisions"
        / "20260827"
        / f"{first_result['sha256']}.json"
    )
    assert revision.is_file()


def test_verified_hourly_research_cannot_remove_an_old_source_slot(
    tmp_path: Path,
) -> None:
    import pytest
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    store = PreselectionPoolStore(tmp_path / "data")
    first = _pool(
        "20260827",
        "a_share_research_recommendation_pool",
        status="RESEARCH_RECOMMENDATION_POOL_READY",
        source_role="VERIFIED_HOURLY_RESEARCH",
        rows=[{"symbol": "A.000001"}],
    )
    first["source_path"] = "research/hourly/live/20260826/1200.json"
    first["source_sha256"] = "a" * 64
    second = dict(first)
    second["source_path"] = "research/hourly/live/20260826/1300.json"
    second["source_sha256"] = "b" * 64

    store.materialize(first)
    with pytest.raises(ValueError, match="conflicting preselection-pool"):
        store.materialize(second)


def test_formal_pool_sha_change_still_conflicts(tmp_path: Path) -> None:
    import pytest
    from infrastructure.preselection_pool_store import PreselectionPoolStore

    store = PreselectionPoolStore(tmp_path / "data")
    first = _pool(
        "20260827",
        "a_d1_premarket_pool",
        status="V192_CANDIDATE_READY",
        source_role="SHARED_VERIFIED_V192",
        rows=[{"code": "000001"}],
    )
    second = dict(first)
    second["source_sha256"] = "b" * 64
    second["rows"] = [{"code": "000002"}]

    store.materialize(first)
    with pytest.raises(ValueError, match="conflicting preselection-pool"):
        store.materialize(second)


def test_hourly_store_lists_only_verified_exact_slots(tmp_path: Path) -> None:
    from ops.run_hourly_research import run_hourly_research_file
    from test_hourly_research_runner import _source, _write_source
    from infrastructure.research_store import HourlyResearchStore

    data_root = tmp_path / "data"
    for slot in ("1200", "1300"):
        source = tmp_path / f"{slot}.json"
        payload = _source("20260826")
        payload["source_manifest"]["hourly_slot"] = slot
        _write_source(source, payload)
        run_hourly_research_file(
            data_root=data_root,
            source=source,
            business_date="20260826",
            target_date="20260826",
            slot=slot,
            mode="LIVE",
        )

    store = HourlyResearchStore(data_root)
    assert store.list_slots("20260826", mode="LIVE") == ["1200", "1300"]
    assert store.read_latest_for_date("20260826", mode="LIVE")[0] == "1300"


def _write_day_fixture(path: Path, date_value: int) -> None:
    from ops.a_share_daily_sync import pack_hq_bar

    path.parent.mkdir(parents=True, exist_ok=True)
    close = 10.0
    bar = {
        "year": date_value // 10000,
        "month": date_value // 100 % 100,
        "day": date_value % 100,
        "open": close - 0.2,
        "high": close + 0.2,
        "low": close - 0.4,
        "close": close,
        "amount": 1000.0,
        "vol": 100.0,
    }
    path.write_bytes(pack_hq_bar(bar))


def _write_rebuild_authority(path: Path, *, include_accepted: bool) -> None:
    accepted_row = "writer.writerow({'path': str(accepted), 'fetch_status': 'ok'})" if include_accepted else ""
    script = """from pathlib import Path
import csv

RUN_DIR = None

def run(args):
    run_dir = Path(RUN_DIR)
    run_dir.mkdir(parents=True, exist_ok=True)
    accepted = Path(args.tdx_root) / 'vipdoc' / 'sh' / 'lday' / 'sh600001.day'
    rejected = Path(args.tdx_root) / 'vipdoc' / 'sz' / 'lday' / 'sz000001.day'
    with (run_dir / 'file_results.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=['path', 'fetch_status'])
        writer.writeheader()
        {accepted_row}
        writer.writerow({'path': str(rejected), 'fetch_status': 'REBUILD_REQUIRED'})
    return {'status': 'REBUILD_REQUIRED', 'exit_code': 0, 'run_dir': str(run_dir)}
""".replace("{accepted_row}", accepted_row)
    path.write_text(
        script,
        encoding="utf-8",
    )


def test_rebuild_sync_materializes_accepted_only_formula_input(tmp_path: Path) -> None:
    from ops.macos_research_panel_daily import run_windows_a_sync_authority

    tdx_root = tmp_path / "tdx"
    accepted = tdx_root / "vipdoc" / "sh" / "lday" / "sh600001.day"
    rejected = tdx_root / "vipdoc" / "sz" / "lday" / "sz000001.day"
    _write_day_fixture(accepted, 20260826)
    _write_day_fixture(rejected, 20260825)
    script = tmp_path / "fake_sync.py"
    _write_rebuild_authority(script, include_accepted=True)

    result = run_windows_a_sync_authority(
        script,
        tdx_root,
        "20260826",
        tmp_path / "receipt",
        minimum_target_date_files=1,
    )

    formula_root = Path(result["formula_tdx_root"])
    assert result["status"] == "READY"
    assert result["authority_status"] == "REBUILD_REQUIRED"
    assert result["formula_input_mode"] == "ACCEPTED_ONLY"
    assert result["accepted_target_date_file_count"] == 1
    assert result["excluded_rebuild_candidate_count"] == 1
    assert (formula_root / "vipdoc" / "sh" / "lday" / "sh600001.day").read_bytes() == accepted.read_bytes()
    assert not (formula_root / "vipdoc" / "sz" / "lday" / "sz000001.day").exists()
    manifest = json.loads(Path(result["formula_input_manifest"]).read_text(encoding="utf-8"))
    assert [item["path"] for item in manifest["files"]] == [str(accepted.resolve())]


def test_rebuild_sync_without_accepted_exact_file_fails_closed(tmp_path: Path) -> None:
    import pytest
    from ops.macos_research_panel_daily import SnapshotGateError, run_windows_a_sync_authority

    tdx_root = tmp_path / "tdx"
    rejected = tdx_root / "vipdoc" / "sz" / "lday" / "sz000001.day"
    _write_day_fixture(rejected, 20260825)
    script = tmp_path / "fake_sync.py"
    _write_rebuild_authority(script, include_accepted=False)

    with pytest.raises(SnapshotGateError, match="accepted exact-date"):
        run_windows_a_sync_authority(
            script,
            tdx_root,
            "20260826",
            tmp_path / "receipt",
            minimum_target_date_files=1,
        )


def test_run_a_routes_partial_sync_to_accepted_only_formula_root(tmp_path: Path, monkeypatch) -> None:
    import ops.macos_research_panel_daily as daily

    source_root = tmp_path / "source"
    _write_day_fixture(source_root / "vipdoc" / "sh" / "lday" / "sh600001.day", 20260825)
    accepted_root = tmp_path / "accepted-only" / "20260826"
    _write_day_fixture(accepted_root / "vipdoc" / "sh" / "lday" / "sh600001.day", 20260826)
    placeholder_paths = [tmp_path / name for name in (
        "sync.py", "formula.py", "seed.parquet", "data", "selector.current",
        "backtest.current", "selector-seed.parquet", "backtest-seed.parquet",
        "contract.csv", "canonical.py", "returns", "hk-update.py", "hk-assets",
    )]
    captured: dict[str, object] = {}

    def fake_sync(*_args, **_kwargs):
        return {
            "status": "READY",
            "target_date": 20260826,
            "authority_status": "REBUILD_REQUIRED",
            "formula_tdx_root": str(accepted_root),
        }

    def fake_formula(*_args, **kwargs):
        captured["tdx_root"] = kwargs["tdx_root"]
        return {"status": "READY", "target_date": 20260826, "authority": {}}

    monkeypatch.setattr(daily, "run_windows_a_sync_authority", fake_sync)
    monkeypatch.setattr(daily, "run_windows_a_formula_authority", fake_formula)
    argv = [
        "macos_research_panel_daily.py",
        "--date", "20260826",
        "--lane", "A",
        "--receipt-root", str(tmp_path / "receipts"),
        "--a-tdx-root", str(source_root),
        "--hk-tdx-root", str(tmp_path / "hk"),
    ]
    for option, path in zip(
        (
            "--a-sync-script", "--a-formula-script", "--a-seed-panel", "--a-data-root",
            "--a-selector-pointer", "--a-backtest-pointer", "--a-selector-seed",
            "--a-backtest-seed", "--a-contract-csv", "--a-canonical-formula",
            "--a-return-root", "--hk-updater-script", "--hk-asset-root",
        ),
        placeholder_paths,
    ):
        argv.extend([option, str(path)])
    monkeypatch.setattr(sys, "argv", argv)

    assert daily.main() == 0
    assert Path(str(captured["tdx_root"])).resolve() == accepted_root.resolve()


def test_scheduled_materializer_fails_when_required_formal_pool_is_not_ready(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import ops.materialize_scheduled_preselection as materializer

    missing_a = _pool(
        "20260827",
        "a_d1_premarket_pool",
        status="CANNOT_CONFIRM",
        source_role="EXPECTED_MISSING",
        cannot_confirm=["A_V192_EXACT_INPUT_MISSING"],
    )
    ready_hk = _pool(
        "20260827",
        "hkconnect_d1_top100",
        status="HK_0_2_TOP100_READY",
        source_role="SHARED_VERIFIED_HK_0_2",
        rows=[{"code": "00001"}],
    )
    optional = _pool(
        "20260827",
        "a_d1_stage7_fenshi_review_pool",
        status="READY",
        source_role="VERIFIED_D1_STAGE7_REPLAY",
        rows=[{"code": "000001"}],
    )
    artifacts = [missing_a, ready_hk, optional]
    monkeypatch.setattr(materializer, "build_scheduled_artifacts", lambda **_kwargs: artifacts)
    materialized = [{"pool_id": item["pool_id"], "status": item["status"]} for item in artifacts]
    monkeypatch.setattr(materializer, "materialize_preselection_date", lambda *_args: materialized)

    result = materializer.main(
        [
            "--trade-date", "20260827",
            "--signal-date", "20260826",
            "--input-root", str(tmp_path / "inputs"),
            "--data-root", str(tmp_path / "data"),
            "--shared-data-root", str(tmp_path / "shared"),
            "--shared-package-root", str(tmp_path / "package"),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert result == 1
    assert output["status"] == "FAILED"
    assert output["failure_class"] == "UPSTREAM_NOT_READY"
    assert output["formal_pool_gate"]["status"] == "FAILED"
    assert "a_d1_premarket_pool" in output["formal_pool_gate"]["missing_or_invalid"]
    assert output["artifacts"] == materialized
    assert output["production_allowed"] is False
