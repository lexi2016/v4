"""ops.macos_research_panel_daily: cli (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __public_envelope_body(_v4_scope, /, result, receipt_root):
    """Bounded stdout protocol; full updater evidence stays in dated receipts.

    Digests bind this invocation's response to the exact bytes, not to a latest
    pointer. The registry independently reads and verifies those bytes. This
    is transport evidence, not a replacement for authority/manifest validation.
    """
    payload = {key: result[key] for key in (
        "target_date", "requested_lane", "overall_status", "status", "runner_called",
        "lane_ready", "selector_pointer_ready", "idempotent",
    ) if key in result}
    # Retain the v16 compact-envelope header; receipt digests are additional
    # transport evidence. The paired registry requires the digest extension.
    overall = result.get("overall_status", result.get("status", "CANNOT_CONFIRM"))
    payload.update(schema_version="v3.macos.research_panel_authority_envelope.v1",
                   status=result.get("status", overall), overall_status=overall,
                   lane=result.get("requested_lane"), **_v4_global(_v4_scope, 'SAFETY_FLAGS'))
    lanes = result.get("lanes")
    compact: dict[str, Any] = {}
    if _v4_global(_v4_scope, 'isinstance')(lanes, _v4_global(_v4_scope, 'Mapping')):
        for lane in ("A", "HK"):
            detail = lanes.get(lane)
            if not _v4_global(_v4_scope, 'isinstance')(detail, _v4_global(_v4_scope, 'Mapping')):
                continue
            status = _v4_global(_v4_scope, 'str')(detail.get("status", "CANNOT_CONFIRM"))
            compact[lane] = {"status": status}
            if status != "NOT_REQUESTED":
                digest = detail.get("receipt_sha256")
                size = detail.get("receipt_bytes")
                if _v4_global(_v4_scope, 'isinstance')(digest, _v4_global(_v4_scope, 'str')) and _v4_global(_v4_scope, 'isinstance')(size, _v4_global(_v4_scope, 'int')):
                    compact[lane].update(receipt_sha256=digest, receipt_bytes=size)
                elif detail.get("receipt_written") is not False:
                    name = f"{lane.lower()}-{_v4_global(_v4_scope, '_date')(result.get('target_date'))}.json"
                    raw = _v4_global(_v4_scope, 'SafeRoot')(receipt_root).read_bytes(name)
                    compact[lane].update(receipt_sha256=_v4_global(_v4_scope, 'hashlib').sha256(raw).hexdigest(), receipt_bytes=_v4_global(_v4_scope, 'len')(raw))
    payload["lanes"] = compact
    return payload


def _main_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(description="Research-only A/H daily lane receipt helper")
    parser.add_argument("--date", required=False, default=None)
    parser.add_argument("--lane", choices=_v4_global(_v4_scope, 'LANE_CHOICES'), default="ALL")
    parser.add_argument("--receipt-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--a-tdx-root", required=False, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--hk-tdx-root", required=False, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--a-universe", required=False, type=_v4_global(_v4_scope, 'Path'), help="Legacy collector input; ignored by authority chain")
    parser.add_argument("--a-minimum-rows", type=_v4_global(_v4_scope, 'int'), default=1)
    parser.add_argument("--a-limit", type=_v4_global(_v4_scope, 'int'), default=None, help="Canary-only A universe limit; never lowers HK minimum 600")
    parser.add_argument(
        "--a-sync-run-budget-seconds",
        default=None,
        help=f"Positive finite A sync wall-clock budget in seconds (default: {_v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'DEFAULT_A_SYNC_RUN_BUDGET_SECONDS'))}; env: {_v4_global(_v4_scope, 'A_SYNC_RUN_BUDGET_ENV')})",
    )
    parser.add_argument(
        "--a-host",
        default=_v4_global(_v4_scope, 'os').environ.get(_v4_global(_v4_scope, 'A_SYNC_HOST_ENV')) or None,
        help=f"Explicit pytdx HQ host override (default: env {_v4_global(_v4_scope, 'A_SYNC_HOST_ENV')}); otherwise probe official hq_hosts",
    )
    parser.add_argument("--a-port", type=_v4_global(_v4_scope, 'int'), default=None, help="Explicit pytdx HQ port (requires --a-host)")
    parser.add_argument("--a-sync-script", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-formula-script", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-seed-panel", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-data-root", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-selector-pointer", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-backtest-pointer", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-selector-seed", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-backtest-seed", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-contract-csv", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-canonical-formula", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--a-return-root", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument(
        "--a-formula-generation-pointer",
        type=_v4_global(_v4_scope, 'Path'),
        default=_v4_global(_v4_scope, 'os').environ.get(_v4_global(_v4_scope, 'A_FORMULA_GENERATION_POINTER_ENV')) or None,
        help=f"Strict V4 generation pointer (default: env {_v4_global(_v4_scope, 'A_FORMULA_GENERATION_POINTER_ENV')})",
    )
    parser.add_argument("--a-offline-input-root", type=_v4_global(_v4_scope, 'Path'), required=False, help="Explicit A parquet input root for an isolated offline run")
    parser.add_argument("--a-offline-input-manifest", type=_v4_global(_v4_scope, 'Path'), required=False, help="Manifest binding the A offline input date/source/SHA")
    parser.add_argument("--a-formula-timeout-seconds", type=_v4_global(_v4_scope, 'float'), default=900.0, help="Bounded V4 offline formula child wall-clock timeout")
    parser.add_argument("--hk-updater-script", type=_v4_global(_v4_scope, 'Path'), required=False)
    parser.add_argument("--hk-python-executable", type=_v4_global(_v4_scope, 'Path'), default=_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'sys').executable))
    parser.add_argument("--hk-asset-root", type=_v4_global(_v4_scope, 'Path'), required=False)
    args = parser.parse_args(argv)
    offline_requested = args.a_offline_input_root is not None or args.a_offline_input_manifest is not None
    offline_a = args.a_offline_input_root is not None and args.a_offline_input_manifest is not None
    if offline_requested and not offline_a:
        parser.error("--a-offline-input-root and --a-offline-input-manifest must be supplied together")
    if offline_a and args.lane != "A":
        parser.error("offline A input is only supported with --lane A")
    if offline_a and args.date is None:
        parser.error("offline A input requires an explicit --date")
    if offline_a and (not _v4_global(_v4_scope, 'math').isfinite(args.a_formula_timeout_seconds) or args.a_formula_timeout_seconds <= 0):
        parser.error("--a-formula-timeout-seconds must be a positive finite number")
    raw_a_sync_run_budget = args.a_sync_run_budget_seconds
    if raw_a_sync_run_budget is None:
        raw_a_sync_run_budget = _v4_global(_v4_scope, 'os').environ.get(_v4_global(_v4_scope, 'A_SYNC_RUN_BUDGET_ENV'))
    try:
        a_sync_run_budget = _v4_global(_v4_scope, '_resolve_a_sync_run_budget')(raw_a_sync_run_budget) if args.lane != "HK" else None
    except _v4_global(_v4_scope, 'ValueError') as error:
        parser.error(_v4_global(_v4_scope, 'str')(error))
    args.receipt_root = _v4_global(_v4_scope, '_absolute_path_argument')(parser, args.receipt_root, "--receipt-root")
    if args.lane != "HK":
        if args.a_minimum_rows < 1:
            parser.error("--a-minimum-rows must be positive")
        if args.a_limit is not None and (args.a_limit < 1 or args.a_minimum_rows > args.a_limit):
            parser.error("--a-minimum-rows cannot exceed --a-limit")
        if args.a_port is not None and args.a_host is None:
            parser.error("--a-port requires --a-host")
        if args.a_port is not None and not 1 <= _v4_global(_v4_scope, 'int')(args.a_port) <= 65535:
            parser.error("--a-port must be between 1 and 65535")
        if args.a_port is not None and ":" in _v4_global(_v4_scope, 'str')(args.a_host):
            parser.error("--a-host must omit the port when --a-port is used")
    authority_paths = {
        "--a-tdx-root": args.a_tdx_root,
        "--hk-tdx-root": args.hk_tdx_root,
        "--a-sync-script": args.a_sync_script,
        "--a-formula-script": args.a_formula_script,
        "--a-seed-panel": args.a_seed_panel,
        "--a-data-root": args.a_data_root,
        "--a-selector-pointer": args.a_selector_pointer,
        "--a-backtest-pointer": args.a_backtest_pointer,
        "--a-selector-seed": args.a_selector_seed,
        "--a-backtest-seed": args.a_backtest_seed,
        "--a-contract-csv": args.a_contract_csv,
        "--a-canonical-formula": args.a_canonical_formula,
        "--a-return-root": args.a_return_root,
        "--a-formula-generation-pointer": args.a_formula_generation_pointer,
        "--hk-updater-script": args.hk_updater_script,
        "--hk-asset-root": args.hk_asset_root,
    }
    authority_paths = {name: value for name, value in authority_paths.items()
        if args.lane == "ALL" or name.startswith("--" + args.lane.lower() + "-")}
    if offline_a:
        authority_paths.update({
            "--a-offline-input-root": args.a_offline_input_root,
            "--a-offline-input-manifest": args.a_offline_input_manifest,
        })
        required_offline = {
            "--a-offline-input-root", "--a-offline-input-manifest", "--a-data-root",
            "--a-selector-pointer", "--a-backtest-pointer", "--a-selector-seed",
            "--a-backtest-seed", "--a-contract-csv", "--a-return-root",
        }
        optional_offline = {"--a-formula-script", "--a-canonical-formula"}
        authority_paths = {
            name: value for name, value in authority_paths.items()
            if name in required_offline or (name in optional_offline and value is not None)
        }
    missing = [name for name, value in authority_paths.items() if value is None and name != "--a-formula-generation-pointer"]
    if missing:
        parser.error("authority chain requires explicit paths: " + ", ".join(missing))
    if authority_paths.get("--a-formula-generation-pointer") is None:
        authority_paths.pop("--a-formula-generation-pointer", None)
    for name, value in authority_paths.items():
        authority_paths[name] = _v4_global(_v4_scope, '_absolute_path_argument')(parser, value, name)
    python_executable = _v4_global(_v4_scope, '_absolute_path_argument')(parser, args.hk_python_executable, "--hk-python-executable") if args.lane != "A" else None

    def run_a(target: str) -> dict[str, Any]:
        if offline_a:
            formula = _v4_global(_v4_scope, 'run_v4_a_formula_offline')(
                input_root=authority_paths["--a-offline-input-root"],
                input_manifest=authority_paths["--a-offline-input-manifest"],
                data_root=authority_paths["--a-data-root"],
                return_root=authority_paths["--a-return-root"],
                selector_pointer=authority_paths["--a-selector-pointer"],
                backtest_pointer=authority_paths["--a-backtest-pointer"],
                selector_seed=authority_paths["--a-selector-seed"],
                backtest_seed=authority_paths["--a-backtest-seed"],
                contract_csv=authority_paths["--a-contract-csv"],
                target_date=target,
                timeout_seconds=args.a_formula_timeout_seconds,
                legacy_formula_source=authority_paths.get("--a-formula-script") or authority_paths.get("--a-canonical-formula"),
            )
            return {
                "status": "READY",
                "target_date": target,
                "bootstrap": None,
                "sync": {"status": "SKIPPED_OFFLINE_INPUT", "runner_called": False, "network": "NOT_USED"},
                "formula": formula,
                "sha256": formula.get("receipt_sha256", ""),
                **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
            }
        sync_authority_args: dict[str, Any] = {"run_budget_seconds": a_sync_run_budget}
        if args.a_host is not None:
            sync_host = _v4_global(_v4_scope, 'str')(args.a_host)
            if args.a_port is not None:
                sync_host = f"{sync_host}:{_v4_global(_v4_scope, 'int')(args.a_port)}"
            sync_authority_args["host"] = sync_host
        if args.a_formula_generation_pointer is not None:
            return _v4_global(_v4_scope, 'run_v4_a_live_generation')(
                sync_script=authority_paths["--a-sync-script"],
                tdx_root=authority_paths["--a-tdx-root"],
                receipt_root=args.receipt_root,
                target_date=target,
                minimum_target_date_files=_v4_global(_v4_scope, 'max')(args.a_minimum_rows, 1),
                sync_authority_args=sync_authority_args,
                data_root=authority_paths["--a-data-root"],
                return_root=authority_paths["--a-return-root"],
                generation_pointer=authority_paths["--a-formula-generation-pointer"],
                selector_pointer=authority_paths["--a-selector-pointer"],
                backtest_pointer=authority_paths["--a-backtest-pointer"],
                selector_seed=authority_paths["--a-selector-seed"],
                backtest_seed=authority_paths["--a-backtest-seed"],
                contract_csv=authority_paths["--a-contract-csv"],
                formula_timeout_seconds=args.a_formula_timeout_seconds,
            )
        day_files_before = _v4_global(_v4_scope, '_a_day_files')(args.a_tdx_root)
        bootstrap = None
        if not day_files_before:
            bootstrap = _v4_global(_v4_scope, 'bootstrap_a_vipdoc_from_panel')(authority_paths["--a-seed-panel"], args.a_tdx_root)
        sync = _v4_global(_v4_scope, 'run_windows_a_sync_authority')(
            authority_paths["--a-sync-script"],
            args.a_tdx_root,
            target,
            args.receipt_root,
            minimum_target_date_files=_v4_global(_v4_scope, 'max')(args.a_minimum_rows, 1),
            authority_args=sync_authority_args,
        )
        formula = _v4_global(_v4_scope, 'run_windows_a_formula_authority')(
            authority_paths["--a-formula-script"],
            tdx_root=args.a_tdx_root,
            data_root=authority_paths["--a-data-root"],
            selector_pointer=authority_paths["--a-selector-pointer"],
            backtest_pointer=authority_paths["--a-backtest-pointer"],
            selector_seed=authority_paths["--a-selector-seed"],
            backtest_seed=authority_paths["--a-backtest-seed"],
            contract_csv=authority_paths["--a-contract-csv"],
            canonical_formula_path=authority_paths["--a-canonical-formula"],
            return_root=authority_paths["--a-return-root"],
            target_date=target,
        )
        return {"status": "READY", "target_date": target, "bootstrap": bootstrap, "sync": sync, "formula": formula, "sha256": formula.get("authority", {}).get("source_sha256", ""), **_v4_global(_v4_scope, 'SAFETY_FLAGS')}

    def run_hk(target: str) -> dict[str, Any]:
        from .hk_capture_gate import run_hk_capture_gate

        return run_hk_capture_gate(
            _v4_scope,
            target_date=target,
            args=args,
            authority_paths=authority_paths,
            python_executable=python_executable,
        )

    # Existing authorities can print arbitrarily large diagnostics. Keep stdout
    # exclusively for the bounded machine protocol consumed by the registry.
    with _v4_global(_v4_scope, 'contextlib').redirect_stdout(_v4_global(_v4_scope, 'sys').stderr):
        if args.date is None:
            result = _v4_global(_v4_scope, 'ensure_after_1700')(
                target_date=_v4_global(_v4_scope, '_today_shanghai')(), receipt_root=args.receipt_root,
                selector_pointer=authority_paths.get("--a-selector-pointer"),
                a_runner=run_a, hk_runner=run_hk, lane=args.lane,
                formula_generation_pointer=authority_paths.get("--a-formula-generation-pointer"),
            )
            exit_code = _v4_global(_v4_scope, 'ensure_exit_code')(result)
        else:
            result = _v4_global(_v4_scope, 'run_scheduled_lanes')(
                target_date=args.date, receipt_root=args.receipt_root,
                a_runner=run_a, hk_runner=run_hk, lane=args.lane,
            )
            exit_code = 0 if result["overall_status"] in {"READY", "NON_TRADING_DAY"} else 2 if result["overall_status"] == "PARTIAL" else 1
    _v4_global(_v4_scope, 'print')(_v4_global(_v4_scope, 'json').dumps(_v4_global(_v4_scope, '_public_envelope')(result, args.receipt_root), ensure_ascii=False, sort_keys=True))
    return exit_code
