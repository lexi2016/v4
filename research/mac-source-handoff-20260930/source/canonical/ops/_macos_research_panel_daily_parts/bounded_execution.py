"""ops.macos_research_panel_daily: bounded_execution (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __load_authority_module_body(_v4_scope, /, script_path, module_name):
    path = _v4_global(_v4_scope, 'Path')(script_path).resolve()
    if not path.is_file():
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"authority script missing: {path}")
    spec = _v4_global(_v4_scope, 'importlib').util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"authority module cannot load: {path}")
    module = _v4_global(_v4_scope, 'importlib').util.module_from_spec(spec)
    # Dataclasses with postponed annotations resolve their defining module
    # during import. Match the v16 loader; restore prior identity on failure.
    missing = _v4_global(_v4_scope, 'object')()
    previous = _v4_global(_v4_scope, 'sys').modules.get(module_name, missing)
    _v4_global(_v4_scope, 'sys').modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except _v4_global(_v4_scope, 'BaseException'):
        if previous is missing:
            _v4_global(_v4_scope, 'sys').modules.pop(module_name, None)
        else:
            _v4_global(_v4_scope, 'sys').modules[module_name] = previous
        raise
    return module


def _run_windows_a_sync_authority_body(_v4_scope, /, script_path, tdx_root, target_date, receipt_root, *, minimum_target_date_files, module_name, authority_args):
    target = _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, '_date')(target_date))
    root = _v4_global(_v4_scope, 'Path')(tdx_root).resolve()
    module = _v4_global(_v4_scope, '_load_authority_module')(script_path, module_name)
    module.TDX_ROOT = root
    module.DATA_ROOT = _v4_global(_v4_scope, 'Path')(receipt_root).resolve()
    module.RUN_DIR = _v4_global(_v4_scope, 'Path')(receipt_root).resolve() / "a_sync_authority"
    module.DIR_BY_MARKET = {
        "a": [("sh", root / "vipdoc" / "sh" / "lday"), ("sz", root / "vipdoc" / "sz" / "lday")],
        "bj": [("bj", root / "vipdoc" / "bj" / "lday")],
    }
    args_values = {
        "tdx_root": root,
        "target_date": target,
        "markets": "a,bj",
        "limit": 0,
        "host": None,
        "timeout": 1.5,
        "count": 20,
        "sleep": 0.0,
        "progress_every": 10_000,
        "dry_run": False,
    }
    # Merge overrides before constructing Namespace so an explicit host (or
    # another authority option) replaces the default instead of becoming a
    # duplicate keyword argument.
    args_values.update(_v4_global(_v4_scope, 'dict')(authority_args or {}))
    args = _v4_global(_v4_scope, 'argparse').Namespace(**args_values)
    reported = _v4_global(_v4_scope, 'dict')(module.run(args))
    if reported.get("status") != "PASS" or _v4_global(_v4_scope, 'int')(reported.get("exit_code", 0) or 0) != 0:
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "A sync authority did not prove exact-date success: "
            f"status={reported.get('status')},exit_code={reported.get('exit_code')}"
        )
    files = _v4_global(_v4_scope, '_a_day_files')(root)
    target_files = [path for path in files if _v4_global(_v4_scope, '_day_file_last_date')(path, _v4_global(_v4_scope, 'A_DAY_STRUCT')) == target]
    if _v4_global(_v4_scope, 'len')(target_files) < _v4_global(_v4_scope, 'int')(minimum_target_date_files):
        raise _v4_global(_v4_scope, 'SnapshotGateError')(f"A sync target-date postcondition failed: {_v4_global(_v4_scope, 'len')(target_files)} < {minimum_target_date_files}")
    receipt = _v4_global(_v4_scope, 'Path')(receipt_root) / "a_sync_authority.json"
    payload = {"status": "READY", "authority_status": reported.get("status"), "target_date": target, "target_date_file_count": _v4_global(_v4_scope, 'len')(target_files), "files": [_v4_global(_v4_scope, 'str')(path) for path in target_files], "authority": reported, **_v4_global(_v4_scope, 'SAFETY_FLAGS')}
    _v4_global(_v4_scope, '_atomic_write')(receipt, (_v4_global(_v4_scope, 'json').dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return payload


def _run_bounded_process_body(_v4_scope, /, command, *, timeout_seconds, cwd, env):
    """Run one authority child in its own POSIX process group.

    This is a wall-clock boundary only.  macOS RSS/address-space enforcement is
    not claimed here; the child reports that limitation in its receipt.
    """
    timeout = _v4_global(_v4_scope, '_resolve_a_sync_run_budget')(timeout_seconds)
    process = _v4_global(_v4_scope, 'subprocess').Popen(
        [_v4_global(_v4_scope, 'str')(item) for item in command],
        cwd=_v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'Path')(cwd).resolve()),
        env=_v4_global(_v4_scope, 'dict')(env) if env is not None else None,
        stdin=_v4_global(_v4_scope, 'subprocess').DEVNULL,
        stdout=_v4_global(_v4_scope, 'subprocess').PIPE,
        stderr=_v4_global(_v4_scope, 'subprocess').PIPE,
        text=True,
        shell=False,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return {
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr[-4000:],
            "timed_out": False,
            "process_group_terminated": False,
            "pid": process.pid,
        }
    except _v4_global(_v4_scope, 'subprocess').TimeoutExpired:
        import signal
        group_terminated = False
        try:
            _v4_global(_v4_scope, 'os').killpg(process.pid, signal.SIGTERM)
            group_terminated = True
        except _v4_global(_v4_scope, 'ProcessLookupError'):
            pass
        try:
            stdout, stderr = process.communicate(timeout=_v4_global(_v4_scope, 'min')(2.0, _v4_global(_v4_scope, 'max')(0.1, timeout)))
        except _v4_global(_v4_scope, 'subprocess').TimeoutExpired:
            try:
                _v4_global(_v4_scope, 'os').killpg(process.pid, signal.SIGKILL)
                group_terminated = True
            except _v4_global(_v4_scope, 'ProcessLookupError'):
                pass
            stdout, stderr = process.communicate()
        return {
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr[-4000:],
            "timed_out": True,
            "process_group_terminated": group_terminated,
            "pid": process.pid,
        }
