"""ops.run_v35_close_review_node: node_cli (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __bilibili_nightly_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    if _v4_global(_v4_scope, '_should_use_shared_video_route')(data_root):
        return _v4_global(_v4_scope, '_shared_video_result')(
            data_root=data_root,
            date=date,
            node="bilibili_fupan_nightly",
        )
    return _v4_global(_v4_scope, '_video_check')(
        data_root=data_root,
        date=date,
        loopback_base_url=loopback_base_url,
        http_getter=http_getter,
        funasr_script=funasr_script,
        ffmpeg=ffmpeg,
        selector_data_root=selector_data_root,
    )


def __run_within_repo_body(_v4_scope, /, command):
    """Run a fixed producer command with no shell and no user-controlled args."""
    try:
        completed = _v4_global(_v4_scope, 'subprocess').run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except _v4_global(_v4_scope, 'FileNotFoundError') as error:
        return {"returncode": 127, "stdout": "", "stderr": _v4_global(_v4_scope, 'str')(error)}
    except _v4_global(_v4_scope, 'subprocess').TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "PRODUCER_TIMEOUT"}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout or "",
        "stderr": completed.stderr or "",
    }


def _run_node_body(_v4_scope, /, *, node, date, data_root, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    """Run one close-review node and publish its receipt.

    Returns ``(exit_code, receipt)``.  ``http_getter`` is injected in tests;
    by default the loopback probes go through ``urllib.request.urlopen``.
    ``funasr_script``/``ffmpeg``/``selector_data_root`` are optional
    overrides for the video nodes; the CLI accepts them as plain Path/name
    flags, never command arrays.
    """
    resolved = _v4_global(_v4_scope, '_resolve_data_root')(data_root)
    _v4_global(_v4_scope, '_validate_date')(date)
    if node not in _v4_global(_v4_scope, '_HANDLERS'):
        raise _v4_global(_v4_scope, 'ValueError')(f"NODE_UNKNOWN: {node!r}")
    receipt_path = _v4_global(_v4_scope, '_receipt_path')(resolved, date, node)
    existing = _v4_global(_v4_scope, '_load_receipt')(receipt_path)
    if _v4_global(_v4_scope, '_is_reusable')(existing, node=node, date=date):
        return _v4_global(_v4_scope, '_exit_code')(existing["status"]), existing
    getter = http_getter or _v4_global(_v4_scope, '_http_get')
    started_at = _v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'UTC')).isoformat(timespec="seconds")
    try:
        status, reason, details, artifacts = _v4_global(_v4_scope, '_HANDLERS')[node](
            data_root=resolved,
            date=date,
            loopback_base_url=loopback_base_url,
            http_getter=getter,
            funasr_script=funasr_script,
            ffmpeg=ffmpeg,
            selector_data_root=(
                _v4_global(_v4_scope, '_resolve_data_root')(selector_data_root)
                if selector_data_root is not None
                else None
            ),
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        status = "FAIL"
        reason = "HANDLER_ERROR"
        details = f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}"[:_v4_global(_v4_scope, 'MAX_ERROR_DETAIL')]
        artifacts = {}
    completed_at = _v4_global(_v4_scope, 'datetime').now(_v4_global(_v4_scope, 'UTC')).isoformat(timespec="seconds")
    receipt: dict[str, Any] = {
        "schema_version": _v4_global(_v4_scope, 'RECEIPT_SCHEMA'),
        "node_id": node,
        "date": date,
        # ``date`` is retained for the runner's compatibility contract.  The
        # frozen runtime graph reads explicit business/trade date fields from
        # receipts, so publish both aliases with the same target trading date.
        "business_date": date,
        "trade_date": date,
        "status": status,
        "reason": reason,
        "started_at": started_at,
        "completed_at": completed_at,
        "artifacts": artifacts,
        "details": details,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    _v4_global(_v4_scope, '_atomic_write')(receipt_path, receipt)
    return _v4_global(_v4_scope, '_exit_code')(status), receipt


def _main_body(_v4_scope, /, argv):
    parser = _v4_global(_v4_scope, 'argparse').ArgumentParser(
        description="Run one V3.5 close-review node and publish its receipt"
    )
    parser.add_argument("--node", required=True, choices=_v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'NODES')))
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-root", required=True, type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--loopback-base-url", default=_v4_global(_v4_scope, 'DEFAULT_LOOPBACK_BASE'))
    parser.add_argument("--funasr-script", type=_v4_global(_v4_scope, 'Path'))
    parser.add_argument("--ffmpeg")
    parser.add_argument("--selector-data-root", type=_v4_global(_v4_scope, 'Path'))
    args = parser.parse_args(argv)
    try:
        code, receipt = _v4_global(_v4_scope, 'run_node')(
            node=args.node,
            date=args.date,
            data_root=args.data_root,
            loopback_base_url=args.loopback_base_url,
            funasr_script=args.funasr_script,
            ffmpeg=args.ffmpeg,
            selector_data_root=args.selector_data_root,
        )
    except _v4_global(_v4_scope, 'ValueError') as error:
        _v4_global(_v4_scope, '_emit')(
            {
                "schema_version": _v4_global(_v4_scope, 'RECEIPT_SCHEMA'),
                "status": "FAIL",
                "reason": f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
        return 1
    _v4_global(_v4_scope, '_emit')(receipt)
    return code
