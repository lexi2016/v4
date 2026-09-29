"""ops.macos_research_panel_daily: a_formula_execution (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def _run_v4_a_formula_offline_body(_v4_scope, /, *, input_root, input_manifest, data_root, return_root, selector_pointer, backtest_pointer, selector_seed, backtest_seed, contract_csv, target_date, timeout_seconds, legacy_formula_source):
    """Call the V4 increment runner without importing a legacy authority."""
    project_root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, '__file__')).resolve().parents[1]
    runner = project_root / "ops" / "a_formula_increment.py"
    command = [
        _v4_global(_v4_scope, 'sys').executable,
        _v4_global(_v4_scope, 'str')(runner),
        "--target-date", _v4_global(_v4_scope, '_date')(target_date),
        "--input-root", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(input_root).resolve()),
        "--input-manifest", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(input_manifest).resolve()),
        "--data-root", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(data_root).resolve()),
        "--return-root", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(return_root).resolve()),
        "--selector-pointer", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(selector_pointer).resolve()),
        "--backtest-pointer", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(backtest_pointer).resolve()),
        "--selector-seed", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(selector_seed).resolve()),
        "--backtest-seed", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(backtest_seed).resolve()),
        "--contract-csv", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(contract_csv).resolve()),
    ]
    if legacy_formula_source is not None:
        command.extend(["--legacy-formula-source", _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(legacy_formula_source).resolve())])
    child_env = _v4_global(_v4_scope, 'dict')(_v4_global(_v4_scope, 'os').environ)
    # An offline V4 run must resolve imports from this checkout.  Do not carry
    # an active release/PYTHONPATH into the child process.
    child_env["PYTHONPATH"] = _v4_global(_v4_scope, 'str')(project_root)
    process_result = _v4_global(_v4_scope, 'run_bounded_process')(command, timeout_seconds=timeout_seconds, cwd=project_root, env=child_env)
    if process_result["timed_out"]:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "V4 offline formula timed out: "
            f"pid={process_result['pid']},group_terminated={process_result['process_group_terminated']}"
        )
    outcome = None
    for line in _v4_global(_v4_scope, 'reversed')(_v4_global(_v4_scope, 'str')(process_result.get("stdout", "")).splitlines()):
        try:
            value = _v4_global(_v4_scope, 'json').loads(line)
        except _v4_global(_v4_scope, 'json').JSONDecodeError:
            continue
        if _v4_global(_v4_scope, 'isinstance')(value, _v4_global(_v4_scope, 'Mapping')):
            outcome = _v4_global(_v4_scope, 'dict')(value)
            break
    if process_result.get("returncode") != 0 or not _v4_global(_v4_scope, 'isinstance')(outcome, _v4_global(_v4_scope, 'Mapping')) or outcome.get("status") != "READY":
        detail = "offline V4 formula runner returned no valid READY result"
        if _v4_global(_v4_scope, 'isinstance')(outcome, _v4_global(_v4_scope, 'Mapping')):
            detail = f"offline V4 formula runner failed: {outcome.get('error_type')}:{outcome.get('error')}"
        raise _v4_global(_v4_scope, 'SnapshotGateError')(detail)
    outcome["driver_command"] = command
    outcome["process"] = {
        "returncode": process_result.get("returncode"),
        "timed_out": False,
        "process_group_terminated": False,
        "pid": process_result.get("pid"),
        "stderr_tail": process_result.get("stderr", ""),
        "resource_limit_status": "CANNOT_CONFIRM_MACOS_RSS_LIMIT",
    }
    return outcome


def __strict_v4_path_root_body(_v4_scope, /, generation_pointer, *, tdx_root, data_root, return_root, selector_pointer, backtest_pointer, receipt_root):
    """Check that the strict live candidate has one V4-owned write root."""

    pointer = _v4_global(_v4_scope, 'Path')(generation_pointer).expanduser()
    pointer_path = pointer / _v4_global(_v4_scope, 'FORMULA_GENERATION_POINTER_NAME') if pointer.is_dir() else pointer
    if pointer_path.name != _v4_global(_v4_scope, 'FORMULA_GENERATION_POINTER_NAME'):
        raise _v4_global(_v4_scope, 'SnapshotGateError')("strict V4 generation pointer must be CURRENT_FORMULA_GENERATION.json")
    root = pointer_path.parent.expanduser().resolve(strict=False)
    expected_return_parent = _v4_global(_v4_scope, 'Path')(return_root).expanduser().resolve(strict=False).parent
    if expected_return_parent != root:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("strict V4 return root and generation pointer must share one output root")
    raw_values = {
        "tdx_root": _v4_global(_v4_scope, 'Path')(tdx_root).expanduser(),
        "data_root": _v4_global(_v4_scope, 'Path')(data_root).expanduser(),
        "return_root": _v4_global(_v4_scope, 'Path')(return_root).expanduser(),
        "selector_pointer": _v4_global(_v4_scope, 'Path')(selector_pointer).expanduser(),
        "backtest_pointer": _v4_global(_v4_scope, 'Path')(backtest_pointer).expanduser(),
        "receipt_root": _v4_global(_v4_scope, 'Path')(receipt_root).expanduser(),
    }
    for label, raw in raw_values.items():
        current = raw if raw.exists() or raw.is_symlink() else raw.parent
        while True:
            if current.is_symlink():
                raise _v4_global(_v4_scope, 'SnapshotGateError')(f"strict V4 {label} has symlink ancestry")
            if current.parent == current:
                break
            current = current.parent
    if "/releases/" in _v4_global(_v4_scope, 'str')(root):
        raise _v4_global(_v4_scope, 'SnapshotGateError')("strict V4 output root cannot be a formal release root")
    if "/Library/Application Support/" in _v4_global(_v4_scope, 'str')(root) and not _v4_global(_v4_scope, 'is_v4_formula_state_owner')(root):
        raise _v4_global(_v4_scope, 'SnapshotGateError')("strict V4 output root is not the designated V4 formula state owner")
    for label, raw in raw_values.items():
        resolved = raw.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except _v4_global(_v4_scope, 'ValueError') as error:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"strict V4 {label} must remain under the generation output root") from error
    root.mkdir(parents=True, exist_ok=True)
    return root, pointer_path


def _run_v4_a_live_generation_body(_v4_scope, /, *, sync_script, tdx_root, receipt_root, target_date, minimum_target_date_files, sync_authority_args, data_root, return_root, generation_pointer, selector_pointer, backtest_pointer, selector_seed, backtest_seed, contract_csv, formula_timeout_seconds):
    """Run the strict V4 live boundary without importing an old formula module."""

    output_root, generation_path = _v4_global(_v4_scope, '_strict_v4_path_root')(
        generation_pointer,
        tdx_root=tdx_root,
        data_root=data_root,
        return_root=return_root,
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        receipt_root=receipt_root,
    )
    try:
        existing = _v4_global(_v4_scope, 'read_formula_generation')(
            generation_path,
            expected_target_date=_v4_global(_v4_scope, '_date')(target_date),
            require_source=True,
        )
        return {
            "status": "READY",
            "already_current": True,
            "target_date": _v4_global(_v4_scope, '_date')(target_date),
            "sync": {"status": "SKIPPED_EXISTING_GENERATION", "runner_called": False, "network": "NOT_USED"},
            "formula": {"status": "READY", "already_current": True, "generation_pointer": {
                "path": _v4_global(_v4_scope, 'str')(existing["path"]),
                "sha256": existing["sha256"],
                "bytes": existing["bytes"],
                "generation_id": existing["generation_id"],
            }},
            "generation": {
                "path": _v4_global(_v4_scope, 'str')(existing["path"]),
                "sha256": existing["sha256"],
                "bytes": existing["bytes"],
                "generation_id": existing["generation_id"],
                "target_date": existing["target_date"],
                "selector_source": _v4_global(_v4_scope, 'str')(existing["selector_source"]),
                "selector_sidecar": _v4_global(_v4_scope, 'str')(existing["selector_sidecar"]),
            },
            "runner_called": False,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    except (_v4_global(_v4_scope, 'FormulaGenerationError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')):
        pass

    sync = _v4_global(_v4_scope, 'run_windows_a_sync_authority')(
        sync_script,
        _v4_global(_v4_scope, 'Path')(tdx_root),
        _v4_global(_v4_scope, '_date')(target_date),
        _v4_global(_v4_scope, 'Path')(receipt_root),
        minimum_target_date_files=_v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'int')(minimum_target_date_files), 1),
        authority_args=_v4_global(_v4_scope, 'dict')(sync_authority_args),
    )
    sync_receipt = _v4_global(_v4_scope, 'Path')(receipt_root).expanduser().resolve() / "a_sync_authority.json"
    if not sync_receipt.is_file():
        raise _v4_global(_v4_scope, 'SnapshotGateError')("A sync receipt was not written")
    receipt_sha = _v4_global(_v4_scope, '_sha256_file')(sync_receipt)
    input_root = _v4_global(_v4_scope, 'Path')(data_root).expanduser().resolve() / "a_formula_inputs" / f"{_v4_global(_v4_scope, '_date')(target_date)}-{receipt_sha[:16]}"
    from ops.a_formula_input_manifest import build_a_formula_input_manifest

    manifest = build_a_formula_input_manifest(
        sync_receipt=sync_receipt,
        tdx_root=tdx_root,
        output_root=input_root,
        target_date=_v4_global(_v4_scope, '_date')(target_date),
        run_id=f"a-live-{_v4_global(_v4_scope, '_date')(target_date)}-{receipt_sha[:16]}",
    )
    formula = _v4_global(_v4_scope, 'run_v4_a_formula_offline')(
        input_root=input_root,
        input_manifest=_v4_global(_v4_scope, 'Path')(manifest["path"]),
        data_root=data_root,
        return_root=return_root,
        selector_pointer=selector_pointer,
        backtest_pointer=backtest_pointer,
        selector_seed=selector_seed,
        backtest_seed=backtest_seed,
        contract_csv=contract_csv,
        target_date=_v4_global(_v4_scope, '_date')(target_date),
        timeout_seconds=formula_timeout_seconds,
        legacy_formula_source=None,
    )
    try:
        generation = _v4_global(_v4_scope, 'read_formula_generation')(
            generation_path,
            expected_target_date=_v4_global(_v4_scope, '_date')(target_date),
            require_source=True,
        )
    except (_v4_global(_v4_scope, 'FormulaGenerationError'), _v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'UnicodeError'), _v4_global(_v4_scope, 'ValueError')) as error:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"strict V4 formula generation is not verified: {error}") from error
    generation_summary = {
        "path": _v4_global(_v4_scope, 'str')(generation["path"]),
        "sha256": generation["sha256"],
        "bytes": generation["bytes"],
        "generation_id": generation["generation_id"],
        "target_date": generation["target_date"],
        "selector_source": _v4_global(_v4_scope, 'str')(generation["selector_source"]),
        "selector_source_sha256": generation["selector_source_evidence"]["sha256"],
        "selector_sidecar": _v4_global(_v4_scope, 'str')(generation["selector_sidecar"]),
        "selector_sidecar_sha256": generation["selector_sidecar_evidence"]["sha256"],
    }
    return {
        "status": "READY",
        "already_current": False,
        "target_date": _v4_global(_v4_scope, '_date')(target_date),
        "sync": sync,
        "input_manifest": manifest,
        "formula": formula,
        "generation": generation_summary,
        "runner_called": True,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }


def _run_windows_a_formula_authority_body(_v4_scope, /, script_path, *, tdx_root, data_root, selector_pointer, backtest_pointer, selector_seed, backtest_seed, contract_csv, canonical_formula_path, return_root, target_date, module_name):
    target = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_date')(target_date))
    data = _v4_global(_v4_scope, 'Path')(data_root).resolve()
    tdx = _v4_global(_v4_scope, 'Path')(tdx_root).resolve()
    selector_ptr = _v4_global(_v4_scope, 'Path')(selector_pointer).resolve()
    backtest_ptr = _v4_global(_v4_scope, 'Path')(backtest_pointer).resolve()
    generation = _v4_global(_v4_scope, '_read_formula_generation')(_v4_global(_v4_scope, 'Path')(return_root).resolve().parent)
    if generation is not None:
        selector_current = generation["selector"]
        backtest_current = generation["backtest"]
    else:
        selector_current = _v4_global(_v4_scope, '_ensure_pointer_seed')(selector_ptr, selector_seed)
        backtest_current = _v4_global(_v4_scope, '_ensure_pointer_seed')(backtest_ptr, backtest_seed)
    selector_max = _v4_global(_v4_scope, '_parquet_max_date')(selector_current)
    backtest_max = _v4_global(_v4_scope, '_parquet_max_date')(backtest_current)
    if selector_max == target and backtest_max == target:
        return {
            "status": "READY",
            "already_current": True,
            "target_date": target,
            "selector": _v4_global(_v4_scope, 'str')(selector_current),
            "backtest": _v4_global(_v4_scope, 'str')(backtest_current),
            "selector_pointer_ready": True,
            "backtest_pointer_ready": True,
            "generation_pointer": {
                "path": _v4_global(_v4_scope, 'str')(generation["path"]),
                "sha256": generation["sha256"],
                "bytes": generation["bytes"],
                "generation_id": generation["generation_id"],
            } if generation is not None else None,
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
    module = _v4_global(_v4_scope, '_load_authority_module')(script_path, module_name)
    module.TDX_ROOT = tdx
    module.DATA_ROOT = data
    module.TDX_INDUSTRY_NAMES = tdx / "T0002" / "hq_cache" / "tdxzs.cfg"
    module.TDX_STOCK_INDUSTRIES = tdx / "T0002" / "hq_cache" / "tdxhy.cfg"
    module.XDXR_CACHE_ROOT = data / "runtime" / "cache" / _v4_global(_v4_scope, 'getattr')(module, "TASK_NAME", "formula") / "tdx_xdxr"
    module.RULES_FILE = data / "DATA_LAYER_AGENTS_RULES.md"
    module.RETURN_ROOT = _v4_global(_v4_scope, 'Path')(return_root).resolve()
    module.SELECTOR_POINTER = selector_ptr
    module.BACKTEST_POINTER = backtest_ptr
    module.SCRIPT_DIR = data / "tools" / "debug_scripts" / _v4_global(_v4_scope, 'getattr')(module, "TASK_NAME", "formula")
    module.PROMOTED_SELECTOR_ROOT = data / "selector_ready_panels" / _v4_global(_v4_scope, 'getattr')(module, "TASK_NAME", "formula")
    module.PROMOTED_BACKTEST_ROOT = data / "backtest_panels" / _v4_global(_v4_scope, 'getattr')(module, "TASK_NAME", "formula")
    module.CONTRACT_CSV = _v4_global(_v4_scope, 'Path')(contract_csv).resolve()
    module.CONTRACT_DIR = module.CONTRACT_CSV.parent
    module.CANONICAL_FORMULA_PATH = _v4_global(_v4_scope, 'Path')(canonical_formula_path).resolve()
    module.RUN_TS = _v4_global(_v4_scope, '_datetime').datetime.now().strftime("%Y%m%d_%H%M%S")
    module.RUN_DIR = module.RETURN_ROOT / module.RUN_TS
    # macOS uses spawn for multiprocessing; dynamically loaded Windows modules
    # cannot be imported by spawned workers.  The authority already supports a
    # serial branch, so force that branch without changing formula functions.
    if _v4_global(_v4_scope, 'hasattr')(module, "DAILY_FORMULA_MAX_WORKERS"):
        module.DAILY_FORMULA_MAX_WORKERS = 1
    module._CANONICAL_FORMULA_MODULE = None
    module.main(False)
    summary_files = _v4_global(_v4_scope, 'sorted')(module.RUN_DIR.rglob("task_summary.json"))
    if not summary_files:
        raise _v4_global(_v4_scope, 'SnapshotGateError')("formula authority task_summary missing")
    summary = _v4_global(_v4_scope, 'json').loads(summary_files[-1].read_text(encoding="utf-8"))
    if not _v4_global(_v4_scope, 'str')(summary.get("final_status", "")).startswith("PASS"):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"formula authority final_status not PASS: {summary.get('final_status')}")
    generation = _v4_global(_v4_scope, '_read_formula_generation')(_v4_global(_v4_scope, 'Path')(return_root).resolve().parent)
    if generation is not None:
        selector_target = generation["selector"]
        backtest_target = generation["backtest"]
    else:
        selector_target = _v4_global(_v4_scope, 'Path')(selector_ptr.read_text(encoding="utf-8-sig").strip())
        backtest_target = _v4_global(_v4_scope, 'Path')(backtest_ptr.read_text(encoding="utf-8-sig").strip())
    for role, path in (("selector", selector_target), ("backtest", backtest_target)):
        if not path.is_file() or _v4_global(_v4_scope, '_parquet_max_date')(path) != target:
            raise _v4_global(_v4_scope, 'SnapshotGateError')(f"{role} pointer target-date postcondition failed: {path}")
    return {
        "status": "READY",
        "target_date": target,
        "selector": _v4_global(_v4_scope, 'str')(selector_target),
        "backtest": _v4_global(_v4_scope, 'str')(backtest_target),
        "selector_pointer_ready": True,
        "backtest_pointer_ready": True,
        "generation_pointer": {
            "path": _v4_global(_v4_scope, 'str')(generation["path"]),
            "sha256": generation["sha256"],
            "bytes": generation["bytes"],
            "generation_id": generation["generation_id"],
        } if generation is not None else None,
        "run_dir": _v4_global(_v4_scope, 'str')(module.RUN_DIR),
        "authority": summary,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
