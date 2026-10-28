"""ops.run_v35_close_review_node: stock_dictionary (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __fupan_stockdict_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    if _v4_global(_v4_scope, '_should_use_shared_video_route')(data_root):
        return _v4_global(_v4_scope, '_shared_video_result')(
            data_root=data_root,
            date=date,
            node="FUPAN_STOCKDICT",
        )
    if selector_data_root is None:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "SELECTOR_DATA_ROOT_MISSING",
            "selector-data-root not provided",
            {},
        )
    capture_manifest = _v4_global(_v4_scope, 'resolve_owned_path')(
        data_root, f"close_review_sources/{date}/bilibili/capture_manifest.json"
    )
    pointer_path = _v4_global(_v4_scope, '_stockdict_pointer_path')(data_root, date)
    selector_pointer = _v4_global(_v4_scope, '_selector_pointer_path')(data_root, date)
    if not capture_manifest.is_file():
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "CAPTURE_MANIFEST_MISSING",
            "capture_manifest.json not found",
            {},
        )
    try:
        selector_panel = _v4_global(_v4_scope, 'resolve_selector_panel')(selector_data_root, date)
    except _v4_global(_v4_scope, 'Exception') as error:
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "SELECTOR_PANEL_UNAVAILABLE",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            {},
        )
    selector_pointer.parent.mkdir(parents=True, exist_ok=True)
    _v4_global(_v4_scope, '_atomic_write_str')(selector_pointer, _v4_global(_v4_scope, 'str')(selector_panel))
    try:
        pointer = _v4_global(_v4_scope, 'build_stockdict')(
            data_root,
            date,
            capture_manifest_path=capture_manifest,
            panel_pointer=selector_pointer,
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            {},
        )
    artifacts = {
        "capture_manifest": _v4_global(_v4_scope, 'str')(capture_manifest),
        "selector_pointer": _v4_global(_v4_scope, 'str')(selector_pointer),
        "current_asr_pointer": _v4_global(_v4_scope, 'str')(pointer_path),
        "stock_mentions": _v4_global(_v4_scope, 'str')(_v4_global(_v4_scope, '_stockdict_mentions_path')(data_root, date)),
    }
    if (
        pointer.get("status") == "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY"
        and pointer_path.is_file()
    ):
        return (
            "SUCCESS",
            "CURRENT_ASR_STOCKDICT_READY_EXACT_ONLY",
            "current ASR stockdict pointer materialized",
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        _v4_global(_v4_scope, 'str')(pointer.get("status") or "NOT_MATERIALIZED"),
        _v4_global(_v4_scope, 'str')(pointer.get("reason") or ""),
        artifacts,
    )
