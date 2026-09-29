"""CLI for the V3.5 dispatcher with fixed live executor registry."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.dispatcher import dispatch_due
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry


ZERO_EXIT_STATUSES = {
    "NON_TRADING_DAY",
    "NON_TRADING_DAY_CADENCE",
    "NO_DUE_WORKLOADS",
    "NO_ELIGIBLE_WORKLOADS",
    "CONCURRENCY_SKIPPED",
    "DRY_RUN_SELECTED",
    "SUCCEEDED",
    "DUPLICATE_WORKLOAD_SKIPPED",
}

REPO_ROOT = Path(__file__).resolve().parents[1]


def _env_path(name: str) -> Path | None:
    value = str(os.environ.get(name) or "").strip()
    return Path(value) if value else None


def _executor(args: argparse.Namespace) -> FixedExecutorRegistry:
    return FixedExecutorRegistry(
        data_root=args.data_root,
        shared_data_root=args.shared_data_root,
        hk_universe_root=args.hk_universe_root,
        shared_package_root=args.shared_package_root,
        shared_futu_python_executable=args.shared_futu_python,
        hk_0_2_python_executable=args.hk_0_2_python,
        hk_0_2_tdx_root=args.hk_0_2_tdx_root,
        selector_data_root=args.selector_data_root,
        preselection_input_root=args.preselection_input_root,
        stage_selection_root=getattr(args, "stage_selection_root", None),
        timeout_seconds=args.timeout_seconds,
        repo_root=REPO_ROOT,
    )


def _ledger(args: argparse.Namespace) -> ExecutionLedger:
    # Dry-run must not occupy the live dispatch claim: a dry run reports the
    # selection it *would* make without reserving the run-scoped mutex, so a
    # later live request with the same identity is never blocked by it.
    ledger_root = (
        args.ledger_root
        if args.ledger_root is not None
        else Path(args.data_root) / "dispatcher"
    )
    root = ledger_root / "dry-run" if args.dry_run else ledger_root
    return ExecutionLedger(root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the V3.5 workload dispatcher")
    parser.add_argument(
        "--mode",
        required=True,
        type=str.upper,
        choices=tuple(mode.value for mode in DispatchMode),
    )
    parser.add_argument("--scheduled-date", required=True)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path(".runtime") / "data",
    )
    parser.add_argument(
        "--ledger-root",
        type=Path,
        default=None,
    )
    parser.add_argument("--shared-data-root", type=Path)
    parser.add_argument(
        "--hk-universe-root",
        type=Path,
        default=_env_path("V35_HK_UNIVERSE_ROOT"),
    )
    parser.add_argument(
        "--shared-package-root",
        type=Path,
        default=_env_path("V35_SHARED_PACKAGE_ROOT"),
    )
    parser.add_argument(
        "--shared-futu-python",
        type=Path,
        default=_env_path("V3_SHARED_FUTU_PYTHON"),
    )
    parser.add_argument(
        "--hk-0-2-python",
        type=Path,
        default=_env_path("V35_HK_0_2_PYTHON"),
    )
    parser.add_argument(
        "--hk-0-2-tdx-root",
        type=Path,
        default=_env_path("V3_SHARED_HK_TDX_ROOT"),
    )
    parser.add_argument("--selector-data-root", type=Path)
    parser.add_argument("--preselection-input-root", type=Path)
    parser.add_argument("--stage-selection-root", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    request = DispatchRequest(
        scheduled_date=args.scheduled_date,
        business_date=args.business_date,
        target_date=args.target_date,
        slot=args.slot,
        mode=DispatchMode(args.mode),
    )
    receipt = dispatch_due(
        request,
        load_workload_catalog(),
        _executor(args) if not args.dry_run else _noop_executor,
        ledger=_ledger(args),
        dry_run=args.dry_run,
    )
    print(json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True))
    if receipt.status in ZERO_EXIT_STATUSES:
        return 0
    return 1


def _noop_executor(*_args, **_kwargs):
    raise RuntimeError("dry-run CLI does not execute business workloads")


if __name__ == "__main__":
    raise SystemExit(main())
