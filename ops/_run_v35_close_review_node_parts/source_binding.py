"""ops.run_v35_close_review_node: source_binding (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __required_review_core_binding_body(_v4_scope, /, names, label):
    """Return one explicit binding and reject missing or conflicting aliases."""

    configured = {
        name: _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'os').environ.get(name) or "").strip()
        for name in names
        if _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, 'os').environ.get(name) or "").strip()
    }
    if not configured:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"{label} binding is missing")
    values = _v4_global(_v4_scope, 'set')(configured.values())
    if _v4_global(_v4_scope, 'len')(values) != 1:
        raise _v4_global(_v4_scope, 'RuntimeError')(f"{label} bindings disagree")
    return _v4_global(_v4_scope, 'next')(_v4_global(_v4_scope, 'iter')(values))


def __review_core_package_parent_body(_v4_scope, /):
    configured = _v4_global(_v4_scope, '_required_review_core_binding')(
        _v4_global(_v4_scope, '_REVIEW_CORE_PACKAGE_ENV_NAMES'), "Review Core package"
    )
    raw = _v4_global(_v4_scope, 'Path')(configured).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise _v4_global(_v4_scope, 'RuntimeError')("Review Core package binding must be an absolute regular path")
    package = raw if raw.name == "review_core" else raw / "review_core"
    if package.is_symlink() or not package.is_dir():
        raise _v4_global(_v4_scope, 'RuntimeError')(f"Review Core package directory is missing or linked: {package}")
    init = package / "__init__.py"
    if init.is_symlink() or not init.is_file():
        raise _v4_global(_v4_scope, 'RuntimeError')(f"Review Core package initializer is missing: {init}")
    return package.parent.resolve()


def __load_shared_video_layer_body(_v4_scope, /, trade_date):
    """Resolve one explicit Review Core projection without old-root discovery."""

    package_root = _v4_global(_v4_scope, '_review_core_package_parent')()
    data_root = _v4_global(_v4_scope, '_review_core_data_root')()
    consumer = _v4_global(_v4_scope, 'load_isolated_package_module')(
        package_root,
        package_directory="review_core",
        module_leaf="consumer",
        namespace_prefix="v35_review_core_video",
    )
    loader = _v4_global(_v4_scope, 'getattr')(consumer, "load_v35_video_layer", None)
    if not _v4_global(_v4_scope, 'callable')(loader):
        raise _v4_global(_v4_scope, 'RuntimeError')("Review Core video consumer is unavailable")
    return _v4_global(_v4_scope, 'dict')(loader(trade_date, data_root))


def __shared_video_result_body(_v4_scope, /, *, data_root, date, node):
    try:
        layer = _v4_global(_v4_scope, '_load_shared_video_layer')(date)
    except _v4_global(_v4_scope, 'Exception') as error:  # fail-closed: do not consult old V3.5 folders
        layer = {
            "status": "CANNOT_CONFIRM",
            "target_trade_date": date,
            "cannot_confirm": [f"REVIEW_CORE_INVALID: {_v4_global(_v4_scope, 'type')(error).__name__}: {error}"],
            "safety_flags": {key: False for key in _v4_global(_v4_scope, '_SAFETY_FLAGS')},
            "evidence_paths": {},
        }
    target = _v4_global(_v4_scope, 'str')(layer.get("target_trade_date") or date)
    flags = layer.get("safety_flags") if _v4_global(_v4_scope, 'isinstance')(layer.get("safety_flags"), _v4_global(_v4_scope, 'dict')) else {}
    safe = target == date and _v4_global(_v4_scope, 'all')(flags.get(key) is False for key in _v4_global(_v4_scope, '_SAFETY_FLAGS'))
    artifacts = {
        _v4_global(_v4_scope, 'str')(key): _v4_global(_v4_scope, 'str')(value)
        for key, value in (layer.get("evidence_paths") or {}).items()
        if _v4_global(_v4_scope, 'str')(value or "")
    } if _v4_global(_v4_scope, 'isinstance')(layer.get("evidence_paths"), _v4_global(_v4_scope, 'dict')) else {}
    details = _v4_global(_v4_scope, 'json').dumps(
        {
            "mode": "REVIEW_CORE_READ_ONLY",
            "node": node,
            "trade_date": date,
            "materialization_status": (
                "ALREADY_MATERIALIZED_READ_ONLY"
                if safe and _v4_global(_v4_scope, 'str')(layer.get("status") or "") not in {"CANNOT_CONFIRM", "NOT_MATERIALIZED"}
                else _v4_global(_v4_scope, 'str')(layer.get("status") or "CANNOT_CONFIRM")
            ),
            "review_core_status": _v4_global(_v4_scope, 'str')(layer.get("status") or "CANNOT_CONFIRM"),
            "layer": layer,
            "old_producer_calls": 0,
        },
        ensure_ascii=False,
        sort_keys=True,
        default=_v4_global(_v4_scope, 'str'),
    )
    if safe and _v4_global(_v4_scope, 'str')(layer.get("status") or "") not in {"CANNOT_CONFIRM", "NOT_MATERIALIZED"}:
        return "SUCCESS", "ALREADY_MATERIALIZED_READ_ONLY", details, artifacts
    reason = _v4_global(_v4_scope, 'str')(layer.get("status") or "CANNOT_CONFIRM")
    return "ACTION_RAN_WITH_CANNOT_CONFIRM", reason, details, artifacts
