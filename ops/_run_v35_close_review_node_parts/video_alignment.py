"""ops.run_v35_close_review_node: video_alignment (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __prepare_alignment_inputs_body(_v4_scope, /, data_root, date):
    """Derive machine-scoped alignment inputs from the current native ASR."""
    pointer_path = _v4_global(_v4_scope, '_stockdict_pointer_path')(data_root, date)
    pointer = _v4_global(_v4_scope, 'json').loads(pointer_path.read_bytes().decode("utf-8-sig"))
    if pointer.get("trade_date") != date:
        raise _v4_global(_v4_scope, 'ValueError')("current ASR pointer date mismatch")
    base = _v4_global(_v4_scope, 'resolve_owned_path')(data_root, f"close_review_sources/{date}/bilibili")
    transcript_dir = base / "transcript"
    inputs = base / "video_ocr_alignment" / "inputs"
    segments_path = inputs / "asr_segments.json"
    spotcheck_path = inputs / "spotcheck_rows.json"

    evidence_bv = {
        _v4_global(_v4_scope, 'str')(row.get("filename") or ""): _v4_global(_v4_scope, 'str')(row.get("bv_id") or "")
        for row in pointer.get("transcript_evidence") or []
        if _v4_global(_v4_scope, 'isinstance')(row, _v4_global(_v4_scope, 'dict'))
    }
    segments: list[dict[str, Any]] = []
    seen_segments: set[tuple[str, str, str, str, str]] = _v4_global(_v4_scope, 'set')()
    for path in _v4_global(_v4_scope, 'sorted')(transcript_dir.glob("*.funasr_segments.csv")):
        bv_id = evidence_bv.get(path.name) or path.name.split(".", 1)[0]
        with path.open("r", encoding="utf-8-sig", newline="") as source:
            for raw in _v4_global(_v4_scope, 'csv').DictReader(source):
                row = {key: _v4_global(_v4_scope, 'str')(value or "") for key, value in raw.items()}
                row["bv_id"] = bv_id
                key = (
                    bv_id,
                    row.get("segment_index", ""),
                    row.get("start", ""),
                    row.get("end", ""),
                    row.get("text", ""),
                )
                if key not in seen_segments:
                    seen_segments.add(key)
                    segments.append(row)

    spotchecks: list[dict[str, Any]] = []
    seen_mentions: set[tuple[str, str, str]] = _v4_global(_v4_scope, 'set')()
    for mention in pointer.get("stock_mentions") or []:
        if not _v4_global(_v4_scope, 'isinstance')(mention, _v4_global(_v4_scope, 'dict')):
            continue
        bv_id = _v4_global(_v4_scope, 'str')(mention.get("bv_id") or "")
        stock_code = _v4_global(_v4_scope, 'str')(mention.get("stock_code") or "")
        stock_name = _v4_global(_v4_scope, 'str')(mention.get("stock_name") or "")
        key = (bv_id, stock_code, stock_name)
        if not stock_name or key in seen_mentions:
            continue
        seen_mentions.add(key)
        segment = _v4_global(_v4_scope, 'next')(
            (
                row for row in segments
                if row.get("bv_id") == bv_id and stock_name in row.get("text", "")
            ),
            {},
        )
        spotchecks.append({
            "bv_id": bv_id,
            "frame_time": _v4_global(_v4_scope, 'str')(segment.get("start") or mention.get("timestamp") or ""),
            "frame_path": "",
            "segment_index": _v4_global(_v4_scope, 'str')(segment.get("segment_index") or ""),
            "stock_code": stock_code,
            "stock_name": stock_name,
            "asr_text": _v4_global(_v4_scope, 'str')(segment.get("text") or stock_name),
            "status": "ASR_STOCKDICT_OBSERVATION_READY",
        })
    if not spotchecks and segments:
        segment = segments[0]
        spotchecks.append({
            "bv_id": _v4_global(_v4_scope, 'str')(segment.get("bv_id") or ""),
            "frame_time": _v4_global(_v4_scope, 'str')(segment.get("start") or ""),
            "frame_path": "",
            "segment_index": _v4_global(_v4_scope, 'str')(segment.get("segment_index") or ""),
            "stock_code": "",
            "stock_name": "",
            "asr_text": _v4_global(_v4_scope, 'str')(segment.get("text") or ""),
            "status": "ASR_METHOD_OBSERVATION_READY",
        })
    if not segments_path.is_file():
        _v4_global(_v4_scope, '_capture_write')(segments_path, {"trade_date": date, "rows": segments})
    if not spotcheck_path.is_file():
        _v4_global(_v4_scope, '_capture_write')(spotcheck_path, {"trade_date": date, "rows": spotchecks})
    return {"asr_segments": segments_path, "spotcheck_rows": spotcheck_path}


def __fupan_video_table_ocr_align_body(_v4_scope, /, *, data_root, date, loopback_base_url, http_getter, funasr_script, ffmpeg, selector_data_root):
    if _v4_global(_v4_scope, '_should_use_shared_video_route')(data_root):
        return _v4_global(_v4_scope, '_shared_video_result')(
            data_root=data_root,
            date=date,
            node="FUPAN_VIDEO_TABLE_OCR_ALIGN",
        )
    current_asr_pointer = _v4_global(_v4_scope, '_stockdict_pointer_path')(data_root, date)
    alignment_pointer = _v4_global(_v4_scope, '_alignment_pointer_path')(data_root, date)
    if not current_asr_pointer.is_file():
        return (
            "ACTION_RAN_WITH_CANNOT_CONFIRM",
            "CURRENT_ASR_POINTER_MISSING",
            "current_asr_pointer.json not found",
            {},
        )
    inputs = _v4_global(_v4_scope, 'resolve_owned_path')(
        data_root, f"close_review_sources/{date}/bilibili/video_ocr_alignment/inputs"
    )
    names = (
        "spotcheck_rows",
        "asr_segments",
        "news_rows",
        "anchor_rows",
        "board_rows",
        "tdx_rows",
    )
    paths: dict[str, Path | None] = {}
    for name in names:
        candidate = inputs / f"{name}.json"
        paths[name] = candidate if candidate.is_file() else None
    if paths["spotcheck_rows"] is None or paths["asr_segments"] is None:
        try:
            generated = _v4_global(_v4_scope, '_prepare_alignment_inputs')(data_root, date)
            paths["spotcheck_rows"] = paths["spotcheck_rows"] or generated["spotcheck_rows"]
            paths["asr_segments"] = paths["asr_segments"] or generated["asr_segments"]
        except _v4_global(_v4_scope, 'Exception') as error:
            return (
                "FAIL",
                "HANDLER_ERROR",
                f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
                {},
            )
    try:
        result = _v4_global(_v4_scope, 'materialize_alignment')(
            data_root,
            date,
            current_asr_pointer_path=current_asr_pointer,
            spotcheck_path=paths["spotcheck_rows"],
            asr_segments_path=paths["asr_segments"],
            news_path=paths["news_rows"],
            anchors_path=paths["anchor_rows"],
            boards_path=paths["board_rows"],
            tdx_path=paths["tdx_rows"],
        )
    except _v4_global(_v4_scope, 'Exception') as error:
        return (
            "FAIL",
            "HANDLER_ERROR",
            f"{_v4_global(_v4_scope, 'type')(error).__name__}: {error}",
            {},
        )
    artifacts = {
        "current_asr_pointer": _v4_global(_v4_scope, 'str')(current_asr_pointer),
        "alignment_pointer": _v4_global(_v4_scope, 'str')(alignment_pointer),
    }
    if (
        result.get("status") == "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY"
        and alignment_pointer.is_file()
    ):
        return (
            "SUCCESS",
            "VIDEO_TABLE_ASR_NEWS_ALIGNMENT_READY",
            "video OCR alignment pointer materialized",
            artifacts,
        )
    return (
        "ACTION_RAN_WITH_CANNOT_CONFIRM",
        _v4_global(_v4_scope, 'str')(result.get("status") or "NOT_MATERIALIZED"),
        _v4_global(_v4_scope, 'str')(result.get("reason") or ""),
        artifacts,
    )
