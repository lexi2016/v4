from __future__ import annotations

from ops.install_v35_macos_launchagents import (
    build_runtime_graph_plist,
    build_scheduler_plist,
)


def test_scheduler_plist_uses_exact_calendar_slots_and_five_minute_heartbeat() -> None:
    plist = build_scheduler_plist(
        launch_script="/Applications/v35/ops/launch_v35_macos_scheduler.sh",
        app_root="/Applications/v35/app",
        runtime_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime",
        data_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data",
        ledger_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher",
        stage_selection_root="/Users/lexi/Library/Application Support/com.lexi.stage-center.local/state/selection",
        preselection_input_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_inputs",
        shared_data_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data",
        hk_universe_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/hk_universe",
        shared_package_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/upstreams/v3_shared_data",
        selector_data_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据",
        hk_0_2_python="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime/venvs/v3.5-hk02/bin/python",
        research_panel_receipt_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/receipts",
        selector_pointer="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
        backtest_pointer="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt",
        review_core_package_root="/Users/lexi/Library/Application Support/com.lexi.review-core.local/app",
        review_core_shared_package_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/upstreams/v3_shared_data",
        review_core_shared_store_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data",
        review_core_runtime_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime",
        review_core_calendar_path="/Users/lexi/Documents/Codex/release/app/contracts/market_calendar_2026.json",
        review_core_hk_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/hk_universe",
        review_core_close_root="/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/close_reviews",
        review_core_fupan_store_root="/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/fupan_store",
        review_core_stage7_store_root="/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/stage7_store",
        review_core_bundle_root="/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/review_bundle",
        research_panel_a_tdx_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/tdx",
        research_panel_hk_tdx_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/hk_tdx",
        research_panel_a_sync_script="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/tdxpy_daily_vipdoc_sync_v1.py",
        research_panel_a_formula_script="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/data_layer_daily_formula_increment_update_v1.py",
        research_panel_a_seed_panel="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/selector_ready_panels/seed.parquet",
        research_panel_a_data_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据",
        research_panel_a_selector_pointer="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
        research_panel_a_backtest_pointer="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt",
        research_panel_a_selector_seed="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/selector_ready_panels/seed.parquet",
        research_panel_a_backtest_seed="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/backtest_panels/seed.parquet",
        research_panel_a_contract_csv="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/authoritative_field_contract_v0.csv",
        research_panel_a_canonical_formula="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/build_canonical_formula_research_panel.py",
        research_panel_a_return_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/a_formula_runs",
        research_panel_hk_updater_script="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py",
        research_panel_hk_python_executable="/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime/venvs/v3.5-hk02/bin/python",
        research_panel_hk_asset_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2",
        release_id="r1",
        release_manifest_path="/Applications/v35/release-manifest.json",
        release_manifest_sha256="a" * 64,
        upstream_fingerprint="upstream-sha256",
    )
    intervals = plist["StartCalendarInterval"]
    pairs = {
        (item["Hour"], item["Minute"])
        for item in intervals
        if "Hour" in item
    }
    heartbeat_minutes = {
        item["Minute"] for item in intervals if "Hour" not in item
    }

    assert (8, 30) in pairs
    assert (8, 40) in pairs
    assert (9, 1) in pairs
    assert (9, 15) in pairs
    assert (9, 25) in pairs
    assert (9, 40) in pairs
    assert (17, 20) in pairs
    assert (17, 30) in pairs
    assert (20, 1) in pairs
    assert (21, 15) in pairs
    assert heartbeat_minutes == set(range(3, 60, 5))
    assert "StartInterval" not in plist
    assert "ThrottleInterval" not in plist
    assert all(item["Minute"] != 30 or item["Hour"] != 0 for item in intervals)


def test_runtime_graph_plist_is_observability_only_and_not_business_workload() -> None:
    plist = build_runtime_graph_plist(
        python="/Applications/v35/runtime/bin/python",
        app_root="/Applications/v35/app",
        data_root="/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data",
    )

    assert plist["Label"] == "com.lexi.v35.runtime-graph"
    assert plist["StartInterval"] == 60
    assert plist["ThrottleInterval"] == 60
    assert any("ops.collect_runtime_graph" in item for item in plist["ProgramArguments"])
    assert any("'--date'" in item for item in plist["ProgramArguments"])
    assert plist["EnvironmentVariables"]["V35_OBSERVABILITY_ONLY"] == "true"


def test_scheduler_plist_binds_launch_shell_roots_and_release_identity() -> None:
    launch_script = "/Users/lexi/Documents/Codex/release/app/ops/launch_v35_macos_scheduler.sh"
    roots = {
        "app_root": "/Users/lexi/Documents/Codex/release/app",
        "runtime_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime",
        "data_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data",
        "ledger_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher",
        "stage_selection_root": "/Users/lexi/Library/Application Support/com.lexi.stage-center.local/state/selection",
        "preselection_input_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_inputs",
        "shared_data_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data",
        "hk_universe_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/hk_universe",
        "shared_package_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/upstreams/v3_shared_data",
        "selector_data_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据",
        "hk_0_2_python": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime/venvs/v3.5-hk02/bin/python",
        "research_panel_receipt_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/receipts",
        "selector_pointer": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
        "backtest_pointer": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt",
        "review_core_package_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/app",
        "review_core_shared_package_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/upstreams/v3_shared_data",
        "review_core_shared_store_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data",
        "review_core_runtime_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime",
        "review_core_calendar_path": "/Users/lexi/Documents/Codex/release/app/contracts/market_calendar_2026.json",
        "review_core_hk_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/hk_universe",
        "review_core_close_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/close_reviews",
        "review_core_fupan_store_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/fupan_store",
        "review_core_stage7_store_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/stage7_store",
        "review_core_bundle_root": "/Users/lexi/Library/Application Support/com.lexi.review-core.local/state/data/review_bundle",
        "research_panel_a_tdx_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/tdx",
        "research_panel_hk_tdx_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/hk_tdx",
        "research_panel_a_sync_script": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/tdxpy_daily_vipdoc_sync_v1.py",
        "research_panel_a_formula_script": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/data_layer_daily_formula_increment_update_v1.py",
        "research_panel_a_seed_panel": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/selector_ready_panels/seed.parquet",
        "research_panel_a_data_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据",
        "research_panel_a_selector_pointer": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt",
        "research_panel_a_backtest_pointer": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt",
        "research_panel_a_selector_seed": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/selector_ready_panels/seed.parquet",
        "research_panel_a_backtest_seed": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/backtest_panels/seed.parquet",
        "research_panel_a_contract_csv": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/authoritative_field_contract_v0.csv",
        "research_panel_a_canonical_formula": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/runtime/v1/build_canonical_formula_research_panel.py",
        "research_panel_a_return_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/a_formula_runs",
        "research_panel_hk_updater_script": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/app/upstreams/v3_shared_data/scripts/update_hk_0_2_panel.py",
        "research_panel_hk_python_executable": "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r1/runtime/venvs/v3.5-hk02/bin/python",
        "research_panel_hk_asset_root": "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2",
    }
    plist = build_scheduler_plist(
        launch_script=launch_script,
        **roots,
        release_id="r1",
        release_manifest_path="/Applications/v35/release-manifest.json",
        release_manifest_sha256="a" * 64,
        upstream_fingerprint="upstream-sha256",
    )

    env = plist["EnvironmentVariables"]
    assert plist["ProgramArguments"] == ["/bin/bash", launch_script]
    for name, value in {
        "V35_APP_ROOT": roots["app_root"],
        "V35_RUNTIME_ROOT": roots["runtime_root"],
        "V35_DATA_ROOT": roots["data_root"],
        "V35_DISPATCH_LEDGER_ROOT": roots["ledger_root"],
        "V35_STAGE_CENTER_SELECTION_ROOT": roots["stage_selection_root"],
        "V35_PRESELECTION_INPUT_ROOT": roots["preselection_input_root"],
        "V35_SHARED_DATA_ROOT": roots["shared_data_root"],
        "V35_HK_UNIVERSE_ROOT": roots["hk_universe_root"],
        "V35_SHARED_PACKAGE_ROOT": roots["shared_package_root"],
        "V35_SELECTOR_DATA_ROOT": roots["selector_data_root"],
        "V35_HK_0_2_PYTHON": roots["hk_0_2_python"],
        "V35_RESEARCH_PANEL_RECEIPT_ROOT": roots["research_panel_receipt_root"],
        "V35_SELECTOR_POINTER": roots["selector_pointer"],
        "V35_BACKTEST_POINTER": roots["backtest_pointer"],
        "V35_REVIEW_CORE_PACKAGE_ROOT": roots["review_core_package_root"],
        "V35_REVIEW_CORE_SHARED_PACKAGE_ROOT": roots["review_core_shared_package_root"],
        "V35_REVIEW_CORE_SHARED_STORE_ROOT": roots["review_core_shared_store_root"],
        "V35_REVIEW_CORE_RUNTIME_ROOT": roots["review_core_runtime_root"],
        "V35_REVIEW_CORE_CALENDAR_PATH": roots["review_core_calendar_path"],
        "V35_REVIEW_CORE_HK_ROOT": roots["review_core_hk_root"],
        "V35_REVIEW_CORE_CLOSE_ROOT": roots["review_core_close_root"],
        "V35_REVIEW_CORE_FUPAN_STORE_ROOT": roots["review_core_fupan_store_root"],
        "V35_REVIEW_CORE_STAGE7_STORE_ROOT": roots["review_core_stage7_store_root"],
        "V35_REVIEW_CORE_BUNDLE_ROOT": roots["review_core_bundle_root"],
        "V35_RESEARCH_PANEL_A_TDX_ROOT": roots["research_panel_a_tdx_root"],
        "V35_RESEARCH_PANEL_HK_TDX_ROOT": roots["research_panel_hk_tdx_root"],
        "V35_RESEARCH_PANEL_A_SYNC_SCRIPT": roots["research_panel_a_sync_script"],
        "V35_RESEARCH_PANEL_A_FORMULA_SCRIPT": roots["research_panel_a_formula_script"],
        "V35_RESEARCH_PANEL_A_SEED_PANEL": roots["research_panel_a_seed_panel"],
        "V35_RESEARCH_PANEL_A_DATA_ROOT": roots["research_panel_a_data_root"],
        "V35_RESEARCH_PANEL_A_SELECTOR_POINTER": roots["research_panel_a_selector_pointer"],
        "V35_RESEARCH_PANEL_A_BACKTEST_POINTER": roots["research_panel_a_backtest_pointer"],
        "V35_RESEARCH_PANEL_A_SELECTOR_SEED": roots["research_panel_a_selector_seed"],
        "V35_RESEARCH_PANEL_A_BACKTEST_SEED": roots["research_panel_a_backtest_seed"],
        "V35_RESEARCH_PANEL_A_CONTRACT_CSV": roots["research_panel_a_contract_csv"],
        "V35_RESEARCH_PANEL_A_CANONICAL_FORMULA": roots["research_panel_a_canonical_formula"],
        "V35_RESEARCH_PANEL_A_RETURN_ROOT": roots["research_panel_a_return_root"],
        "V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT": roots["research_panel_hk_updater_script"],
        "V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE": roots["research_panel_hk_python_executable"],
        "V35_RESEARCH_PANEL_HK_ASSET_ROOT": roots["research_panel_hk_asset_root"],
        "V35_WECHAT_INPUT_ROOT": roots["preselection_input_root"],
        "V35_RELEASE_ID": "r1",
        "V35_UPSTREAM_FINGERPRINT": "upstream-sha256",
    }.items():
        assert env[name] == value
    assert env["production_allowed"] == "false"
    assert env["buy_gate_updated"] == "false"
    assert env["orders_sent"] == "false"
    assert env["PRODUCTION_ALLOWED"] == "false"
    assert env["BUY_GATE_UPDATED"] == "false"
    assert env["ORDERS_SENT"] == "false"


def test_scheduler_renderer_refuses_missing_or_invalid_manifest_identity():
    import inspect
    import pytest
    kwargs = {name: "/isolated/" + name for name, item in inspect.signature(build_scheduler_plist).parameters.items()
              if item.default is inspect.Parameter.empty}
    kwargs.update(release_id="reviewed", upstream_fingerprint="upstream", release_manifest_sha256="x", release_manifest_path="/isolated/manifest.json")
    with pytest.raises(ValueError, match="sha256"):
        build_scheduler_plist(**kwargs)
    kwargs["release_manifest_sha256"] = "b" * 64
    kwargs["release_manifest_path"] = "relative.json"
    with pytest.raises(ValueError, match="absolute"):
        build_scheduler_plist(**kwargs)


def test_scheduler_renderer_intraday_binding_is_explicit_and_all_or_none(tmp_path):
    import inspect
    import pytest
    signature = inspect.signature(build_scheduler_plist)
    kwargs = {name: str(tmp_path / name) for name, p in signature.parameters.items()
              if p.default is inspect.Parameter.empty}
    kwargs.update(release_id="fixture-release", upstream_fingerprint="fixture-upstream",
                  release_manifest_sha256="a" * 64)
    binding = {"intraday_config_path": str(tmp_path / "intraday.json"),
               "intraday_config_sha256": "b" * 64, "intraday_source_manifest_sha256": "c" * 64}
    payload = build_scheduler_plist(**kwargs, **binding)
    env = payload["EnvironmentVariables"]
    assert env["V4_INTRADAY_CONFIG_PATH"] == binding["intraday_config_path"]
    assert env["V4_INTRADAY_CONFIG_SHA256"] == "b" * 64
    assert env["V4_INTRADAY_SOURCE_MANIFEST_SHA256"] == "c" * 64
    for key in binding:
        partial = {k: v for k, v in binding.items() if k != key}
        with pytest.raises(ValueError, match="intraday"):
            build_scheduler_plist(**kwargs, **partial)
    assert not list(tmp_path.iterdir())  # Renderer never writes/activates anything.
