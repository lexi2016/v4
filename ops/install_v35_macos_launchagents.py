"""Deterministic launchd plist builders for the V3.5 Mac runtime.

The scheduler wakes on the authoritative HH:MM calendar entries and uses a
bounded five-minute heartbeat only for missed-slot recovery.  The runtime
graph collector has its own observability-only plist so graph collection can
never be mistaken for a business producer.
"""
from __future__ import annotations

import argparse
import plistlib
import re
from pathlib import Path
from typing import Any

from ops.run_scheduled_slot import ALL_SLOTS


SCHEDULER_LABEL = "com.lexi.v35.scheduler"
RUNTIME_GRAPH_LABEL = "com.lexi.v35.runtime-graph"
HEARTBEAT_SECONDS = 300
HEARTBEAT_MINUTES = tuple(range(3, 60, 5))
RUNTIME_GRAPH_INTERVAL_SECONDS = 60


def _absolute_path(name: str, value: str) -> str:
    """Validate a path before it is embedded in an owned plist payload."""

    text = str(value or "")
    if not text or not text.startswith("/") or "\\" in text:
        raise ValueError(f"{name} must be an absolute POSIX path")
    if text.startswith("/Users/lexi/Desktop/学习"):
        raise ValueError(f"{name} may not use the read-only Desktop/学习 root")
    return text


def _identity(name: str, value: str) -> str:
    """Validate a release/lineage identity before launchd receives it."""

    text = str(value or "")
    if not text or "/" in text or "\\" in text:
        raise ValueError(f"{name} must be a non-empty path-free identity")
    return text


def _calendar_entries(slots: tuple[str, ...] = ALL_SLOTS) -> list[dict[str, int]]:
    exact_entries = [
        {"Hour": int(slot[:2]), "Minute": int(slot[2:])}
        for slot in sorted(set(slots))
    ]
    # A scheduler plist must not combine StartInterval/ThrottleInterval with
    # exact calendar entries: launchd may throttle the exact stage wake.  A
    # minute-only StartCalendarInterval entry provides the same five-minute
    # recovery heartbeat while leaving every exact Hour/Minute owner intact.
    heartbeat_entries = [{"Minute": minute} for minute in HEARTBEAT_MINUTES]
    return exact_entries + heartbeat_entries


def build_scheduler_plist(
    *,
    launch_script: str,
    app_root: str,
    runtime_root: str,
    data_root: str,
    ledger_root: str,
    stage_selection_root: str,
    preselection_input_root: str,
    shared_data_root: str,
    hk_universe_root: str,
    shared_package_root: str,
    selector_data_root: str,
    hk_0_2_python: str,
    research_panel_receipt_root: str,
    selector_pointer: str,
    backtest_pointer: str,
    review_core_package_root: str,
    review_core_shared_package_root: str,
    review_core_shared_store_root: str,
    review_core_runtime_root: str,
    review_core_calendar_path: str,
    review_core_hk_root: str,
    review_core_close_root: str,
    review_core_fupan_store_root: str,
    review_core_stage7_store_root: str,
    review_core_bundle_root: str,
    research_panel_a_tdx_root: str,
    research_panel_hk_tdx_root: str,
    research_panel_a_sync_script: str,
    research_panel_a_formula_script: str,
    research_panel_a_seed_panel: str,
    research_panel_a_data_root: str,
    research_panel_a_selector_pointer: str,
    research_panel_a_backtest_pointer: str,
    research_panel_a_selector_seed: str,
    research_panel_a_backtest_seed: str,
    research_panel_a_contract_csv: str,
    research_panel_a_canonical_formula: str,
    research_panel_a_return_root: str,
    research_panel_hk_updater_script: str,
    research_panel_hk_python_executable: str,
    research_panel_hk_asset_root: str,
    release_id: str,
    upstream_fingerprint: str,
    release_manifest_path: str,
    release_manifest_sha256: str,
    intraday_config_path: str | None = None,
    intraday_config_sha256: str | None = None,
    intraday_source_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    """Return a complete scheduler plist payload without writing it.

    The launcher shell has four mandatory roots and the registered workload
    adapters have additional optional roots.  They are all required here so a
    generated plist cannot silently fall back to a different release or to a
    path derived from the shell's location.  This function only renders data;
    the caller owns any subsequent candidate-only write.
    """

    if not re.fullmatch(r"[0-9a-f]{64}", str(release_manifest_sha256)):
        raise ValueError("release_manifest_sha256 must be a lowercase SHA-256")
    launch_script = _absolute_path("launch_script", launch_script)
    roots = {
        "V35_APP_ROOT": _absolute_path("app_root", app_root),
        "V35_RUNTIME_ROOT": _absolute_path("runtime_root", runtime_root),
        "V35_DATA_ROOT": _absolute_path("data_root", data_root),
        "V35_DISPATCH_LEDGER_ROOT": _absolute_path("ledger_root", ledger_root),
        "V35_STAGE_CENTER_SELECTION_ROOT": _absolute_path(
            "stage_selection_root", stage_selection_root
        ),
        "V35_PRESELECTION_INPUT_ROOT": _absolute_path(
            "preselection_input_root", preselection_input_root
        ),
        "V35_SHARED_DATA_ROOT": _absolute_path("shared_data_root", shared_data_root),
        "V35_HK_UNIVERSE_ROOT": _absolute_path("hk_universe_root", hk_universe_root),
        "V35_SHARED_PACKAGE_ROOT": _absolute_path(
            "shared_package_root", shared_package_root
        ),
        "V35_SELECTOR_DATA_ROOT": _absolute_path("selector_data_root", selector_data_root),
        "V35_HK_0_2_PYTHON": _absolute_path("hk_0_2_python", hk_0_2_python),
        # These are explicit adapter roots.  Date-specific research close
        # paths intentionally remain unset: the registry derives
        # ``{business_date}.json`` from the dispatch request instead of
        # freezing one day's file into a persistent LaunchAgent.
        "V35_RESEARCH_PANEL_RECEIPT_ROOT": _absolute_path(
            "research_panel_receipt_root", research_panel_receipt_root
        ),
        "V35_SELECTOR_POINTER": _absolute_path("selector_pointer", selector_pointer),
        "V35_BACKTEST_POINTER": _absolute_path("backtest_pointer", backtest_pointer),
        "V35_REVIEW_CORE_PACKAGE_ROOT": _absolute_path(
            "review_core_package_root", review_core_package_root
        ),
        "V35_REVIEW_CORE_SHARED_PACKAGE_ROOT": _absolute_path(
            "review_core_shared_package_root", review_core_shared_package_root
        ),
        "V35_REVIEW_CORE_SHARED_STORE_ROOT": _absolute_path(
            "review_core_shared_store_root", review_core_shared_store_root
        ),
        "V35_REVIEW_CORE_RUNTIME_ROOT": _absolute_path(
            "review_core_runtime_root", review_core_runtime_root
        ),
        "V35_REVIEW_CORE_CALENDAR_PATH": _absolute_path(
            "review_core_calendar_path", review_core_calendar_path
        ),
        "V35_REVIEW_CORE_HK_ROOT": _absolute_path("review_core_hk_root", review_core_hk_root),
        "V35_REVIEW_CORE_CLOSE_ROOT": _absolute_path(
            "review_core_close_root", review_core_close_root
        ),
        "V35_REVIEW_CORE_FUPAN_STORE_ROOT": _absolute_path(
            "review_core_fupan_store_root", review_core_fupan_store_root
        ),
        "V35_REVIEW_CORE_STAGE7_STORE_ROOT": _absolute_path(
            "review_core_stage7_store_root", review_core_stage7_store_root
        ),
        "V35_REVIEW_CORE_BUNDLE_ROOT": _absolute_path(
            "review_core_bundle_root", review_core_bundle_root
        ),
        "V35_RESEARCH_PANEL_A_TDX_ROOT": _absolute_path(
            "research_panel_a_tdx_root", research_panel_a_tdx_root
        ),
        "V35_RESEARCH_PANEL_HK_TDX_ROOT": _absolute_path(
            "research_panel_hk_tdx_root", research_panel_hk_tdx_root
        ),
        "V35_RESEARCH_PANEL_A_SYNC_SCRIPT": _absolute_path(
            "research_panel_a_sync_script", research_panel_a_sync_script
        ),
        "V35_RESEARCH_PANEL_A_FORMULA_SCRIPT": _absolute_path(
            "research_panel_a_formula_script", research_panel_a_formula_script
        ),
        "V35_RESEARCH_PANEL_A_SEED_PANEL": _absolute_path(
            "research_panel_a_seed_panel", research_panel_a_seed_panel
        ),
        "V35_RESEARCH_PANEL_A_DATA_ROOT": _absolute_path(
            "research_panel_a_data_root", research_panel_a_data_root
        ),
        "V35_RESEARCH_PANEL_A_SELECTOR_POINTER": _absolute_path(
            "research_panel_a_selector_pointer", research_panel_a_selector_pointer
        ),
        "V35_RESEARCH_PANEL_A_BACKTEST_POINTER": _absolute_path(
            "research_panel_a_backtest_pointer", research_panel_a_backtest_pointer
        ),
        "V35_RESEARCH_PANEL_A_SELECTOR_SEED": _absolute_path(
            "research_panel_a_selector_seed", research_panel_a_selector_seed
        ),
        "V35_RESEARCH_PANEL_A_BACKTEST_SEED": _absolute_path(
            "research_panel_a_backtest_seed", research_panel_a_backtest_seed
        ),
        "V35_RESEARCH_PANEL_A_CONTRACT_CSV": _absolute_path(
            "research_panel_a_contract_csv", research_panel_a_contract_csv
        ),
        "V35_RESEARCH_PANEL_A_CANONICAL_FORMULA": _absolute_path(
            "research_panel_a_canonical_formula", research_panel_a_canonical_formula
        ),
        "V35_RESEARCH_PANEL_A_RETURN_ROOT": _absolute_path(
            "research_panel_a_return_root", research_panel_a_return_root
        ),
        "V35_RESEARCH_PANEL_HK_UPDATER_SCRIPT": _absolute_path(
            "research_panel_hk_updater_script", research_panel_hk_updater_script
        ),
        "V35_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE": _absolute_path(
            "research_panel_hk_python_executable", research_panel_hk_python_executable
        ),
        "V35_RESEARCH_PANEL_HK_ASSET_ROOT": _absolute_path(
            "research_panel_hk_asset_root", research_panel_hk_asset_root
        ),
        # Keep the consumer-side alias tied to the canonical, date-scoped
        # preselection input root.  It is not an exact-URL producer.
        "V35_WECHAT_INPUT_ROOT": _absolute_path(
            "wechat_input_root", preselection_input_root
        ),
    }
    # A candidate may remain unbound/inactive. Partial bindings never silently
    # choose a different state or source; registry rejects the absent binding.
    intraday = (intraday_config_path, intraday_config_sha256, intraday_source_manifest_sha256)
    if any(value is not None for value in intraday):
        if (not all(intraday) or ".." in Path(str(intraday_config_path)).parts
                or any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in intraday[1:])):
            raise ValueError("intraday config path and both approved SHA values are required")
        roots.update({"V4_INTRADAY_CONFIG_PATH": _absolute_path("intraday_config_path", intraday_config_path),
                      "V4_INTRADAY_CONFIG_SHA256": intraday_config_sha256,
                      "V4_INTRADAY_SOURCE_MANIFEST_SHA256": intraday_source_manifest_sha256})
    identities = {
        "V35_RELEASE_ID": _identity("release_id", release_id),
        "V35_RELEASE_MANIFEST_PATH": _absolute_path("release_manifest_path", release_manifest_path),
        "V35_RELEASE_MANIFEST_SHA256": release_manifest_sha256,
        "V35_UPSTREAM_FINGERPRINT": _identity(
            "upstream_fingerprint", upstream_fingerprint
        ),
    }
    return {
        "Label": SCHEDULER_LABEL,
        "ProgramArguments": ["/bin/bash", launch_script],
        "WorkingDirectory": roots["V35_APP_ROOT"],
        "RunAtLoad": True,
        "StartCalendarInterval": _calendar_entries(),
        "ProcessType": "Background",
        "EnvironmentVariables": {
            **roots,
            **identities,
            "V35_SCHEDULER_HEARTBEAT_SECONDS": str(HEARTBEAT_SECONDS),
            "V35_SCHEDULER_CALENDAR_OWNER": "v3_legacy_exact_slots",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
            "production_allowed": "false",
            "buy_gate_updated": "false",
            "orders_sent": "false",
        },
    }


def build_runtime_graph_plist(
    *,
    python: str,
    app_root: str,
    data_root: str,
    api_base: str = "http://127.0.0.1:8873",
) -> dict[str, Any]:
    """Return a one-shot, date-resolving observability LaunchAgent payload."""

    for name, value in (("python", python), ("app_root", app_root), ("data_root", data_root)):
        if not value or not value.startswith("/"):
            raise ValueError(f"{name} must be an absolute path")
    code = (
        "from datetime import datetime; "
        "from zoneinfo import ZoneInfo; "
        "from ops.collect_runtime_graph import main; "
        f"raise SystemExit(main(['--date', datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d'), "
        f"'--data-root', {data_root!r}, '--api-base', {api_base!r}]))"
    )
    return {
        "Label": RUNTIME_GRAPH_LABEL,
        "ProgramArguments": [python, "-B", "-c", code],
        "WorkingDirectory": app_root,
        "RunAtLoad": True,
        "StartInterval": RUNTIME_GRAPH_INTERVAL_SECONDS,
        "ThrottleInterval": RUNTIME_GRAPH_INTERVAL_SECONDS,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "V35_OBSERVABILITY_ONLY": "true",
            "V35_RUNTIME_GRAPH_OWNER": "v35_observability.runtime_graph",
            "PRODUCTION_ALLOWED": "false",
            "BUY_GATE_UPDATED": "false",
            "ORDERS_SENT": "false",
            "production_allowed": "false",
            "buy_gate_updated": "false",
            "orders_sent": "false",
        },
    }


def write_plist(path: Path, payload: dict[str, Any]) -> Path:
    """Write one plist atomically within the caller's explicitly owned root."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render V3.5 Mac LaunchAgent plists")
    parser.add_argument("--scheduler-script", required=True, type=Path)
    parser.add_argument("--runtime-graph-python", required=True)
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--stage-selection-root", required=True)
    parser.add_argument("--preselection-input-root", required=True)
    parser.add_argument("--shared-data-root", required=True)
    parser.add_argument("--hk-universe-root", required=True)
    parser.add_argument("--shared-package-root", required=True)
    parser.add_argument("--selector-data-root", required=True)
    parser.add_argument("--hk-0-2-python", required=True)
    parser.add_argument("--research-panel-receipt-root", required=True)
    parser.add_argument("--selector-pointer", required=True)
    parser.add_argument("--backtest-pointer", required=True)
    parser.add_argument("--review-core-package-root", required=True)
    parser.add_argument("--review-core-shared-package-root", required=True)
    parser.add_argument("--review-core-shared-store-root", required=True)
    parser.add_argument("--review-core-runtime-root", required=True)
    parser.add_argument("--review-core-calendar-path", required=True)
    parser.add_argument("--review-core-hk-root", required=True)
    parser.add_argument("--review-core-close-root", required=True)
    parser.add_argument("--review-core-fupan-store-root", required=True)
    parser.add_argument("--review-core-stage7-store-root", required=True)
    parser.add_argument("--review-core-bundle-root", required=True)
    parser.add_argument("--research-panel-a-tdx-root", required=True)
    parser.add_argument("--research-panel-hk-tdx-root", required=True)
    parser.add_argument("--research-panel-a-sync-script", required=True)
    parser.add_argument("--research-panel-a-formula-script", required=True)
    parser.add_argument("--research-panel-a-seed-panel", required=True)
    parser.add_argument("--research-panel-a-data-root", required=True)
    parser.add_argument("--research-panel-a-selector-pointer", required=True)
    parser.add_argument("--research-panel-a-backtest-pointer", required=True)
    parser.add_argument("--research-panel-a-selector-seed", required=True)
    parser.add_argument("--research-panel-a-backtest-seed", required=True)
    parser.add_argument("--research-panel-a-contract-csv", required=True)
    parser.add_argument("--research-panel-a-canonical-formula", required=True)
    parser.add_argument("--research-panel-a-return-root", required=True)
    parser.add_argument("--research-panel-hk-updater-script", required=True)
    parser.add_argument("--research-panel-hk-python-executable", required=True)
    parser.add_argument("--research-panel-hk-asset-root", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--release-manifest-path", required=True)
    parser.add_argument("--release-manifest-sha256", required=True)
    parser.add_argument("--intraday-config-path")
    parser.add_argument("--intraday-config-sha256")
    parser.add_argument("--intraday-source-manifest-sha256")
    parser.add_argument("--upstream-fingerprint", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    root = args.output_root
    write_plist(
        root / f"{SCHEDULER_LABEL}.plist",
        build_scheduler_plist(
            launch_script=str(args.scheduler_script),
            app_root=args.app_root,
            runtime_root=args.runtime_root,
            data_root=args.data_root,
            ledger_root=args.ledger_root,
            stage_selection_root=args.stage_selection_root,
            preselection_input_root=args.preselection_input_root,
            shared_data_root=args.shared_data_root,
            hk_universe_root=args.hk_universe_root,
            shared_package_root=args.shared_package_root,
            selector_data_root=args.selector_data_root,
            hk_0_2_python=args.hk_0_2_python,
            research_panel_receipt_root=args.research_panel_receipt_root,
            selector_pointer=args.selector_pointer,
            backtest_pointer=args.backtest_pointer,
            review_core_package_root=args.review_core_package_root,
            review_core_shared_package_root=args.review_core_shared_package_root,
            review_core_shared_store_root=args.review_core_shared_store_root,
            review_core_runtime_root=args.review_core_runtime_root,
            review_core_calendar_path=args.review_core_calendar_path,
            review_core_hk_root=args.review_core_hk_root,
            review_core_close_root=args.review_core_close_root,
            review_core_fupan_store_root=args.review_core_fupan_store_root,
            review_core_stage7_store_root=args.review_core_stage7_store_root,
            review_core_bundle_root=args.review_core_bundle_root,
            research_panel_a_tdx_root=args.research_panel_a_tdx_root,
            research_panel_hk_tdx_root=args.research_panel_hk_tdx_root,
            research_panel_a_sync_script=args.research_panel_a_sync_script,
            research_panel_a_formula_script=args.research_panel_a_formula_script,
            research_panel_a_seed_panel=args.research_panel_a_seed_panel,
            research_panel_a_data_root=args.research_panel_a_data_root,
            research_panel_a_selector_pointer=args.research_panel_a_selector_pointer,
            research_panel_a_backtest_pointer=args.research_panel_a_backtest_pointer,
            research_panel_a_selector_seed=args.research_panel_a_selector_seed,
            research_panel_a_backtest_seed=args.research_panel_a_backtest_seed,
            research_panel_a_contract_csv=args.research_panel_a_contract_csv,
            research_panel_a_canonical_formula=args.research_panel_a_canonical_formula,
            research_panel_a_return_root=args.research_panel_a_return_root,
            research_panel_hk_updater_script=args.research_panel_hk_updater_script,
            research_panel_hk_python_executable=args.research_panel_hk_python_executable,
            research_panel_hk_asset_root=args.research_panel_hk_asset_root,
            release_id=args.release_id,
            release_manifest_path=args.release_manifest_path,
            release_manifest_sha256=args.release_manifest_sha256,
            intraday_config_path=args.intraday_config_path,
            intraday_config_sha256=args.intraday_config_sha256,
            intraday_source_manifest_sha256=args.intraday_source_manifest_sha256,
            upstream_fingerprint=args.upstream_fingerprint,
        ),
    )
    write_plist(
        root / f"{RUNTIME_GRAPH_LABEL}.plist",
        build_runtime_graph_plist(
            python=args.runtime_graph_python,
            app_root=args.app_root,
            data_root=args.data_root,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HEARTBEAT_SECONDS",
    "RUNTIME_GRAPH_INTERVAL_SECONDS",
    "RUNTIME_GRAPH_LABEL",
    "SCHEDULER_LABEL",
    "build_runtime_graph_plist",
    "build_scheduler_plist",
    "main",
    "write_plist",
]
