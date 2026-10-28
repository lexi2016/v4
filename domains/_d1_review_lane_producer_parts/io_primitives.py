"""domains.d1_review_lane_producer: io_primitives (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __write_csv_body(_v4_scope, /, path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(handle, "w", encoding=_v4_global(_v4_scope, 'ENCODING'), newline="") as output:
            writer = _v4_global(_v4_scope, 'csv').DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
            writer.writeheader()
            writer.writerows([{field: row.get(field, "") for field in fields} for row in rows])
            output.flush()
            _v4_global(_v4_scope, 'os').fsync(output.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __write_json_body(_v4_scope, /, path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (_v4_global(_v4_scope, 'json').dumps(payload, ensure_ascii=False, indent=2, default=_v4_global(_v4_scope, 'str')) + "\n").encode(_v4_global(_v4_scope, 'ENCODING'))
    handle, temporary = _v4_global(_v4_scope, 'tempfile').mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with _v4_global(_v4_scope, 'os').fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            _v4_global(_v4_scope, 'os').fsync(output.fileno())
        _v4_global(_v4_scope, 'os').replace(temporary, path)
    finally:
        if _v4_global(_v4_scope, 'os').path.exists(temporary):
            _v4_global(_v4_scope, 'os').unlink(temporary)


def __paths_body(_v4_scope, /, target_date, signal_date, *, source_dir, output_dir, video_dir):
    fupan_dir = _v4_global(_v4_scope, 'Path')(source_dir)
    preopen_dir = _v4_global(_v4_scope, 'Path')(output_dir)
    stage_data_dir = preopen_dir / "_stage7_evidence"
    video_watch_dir = _v4_global(_v4_scope, 'Path')(video_dir) if video_dir is not None else fupan_dir / "video"
    return {
        "fupan_dir": fupan_dir,
        "anchor_role": fupan_dir / "anchor_role.csv",
        "theme_stocks": fupan_dir / "theme_stocks.csv",
        "prior_plan": fupan_dir / "prior_plan.csv",
        "intraday_handoff": fupan_dir / "intraday_handoff.csv",
        "video_watch_status": video_watch_dir / "status.json",
        "video_acceptance": video_watch_dir / f"acceptance_{signal_date}.json",
        "video_capture_manifest": video_watch_dir / f"capture_manifest_{signal_date}.json",
        "video_gap_matrix": video_watch_dir / f"video_gap_matrix_{signal_date}.csv",
        "video_delta": video_watch_dir / f"new_video_delta_{signal_date}.csv",
        "fupan_pool": preopen_dir / "fupan.csv",
        "fupan_manifest": preopen_dir / "fupan.manifest.json",
        "stage7_preopen_pool": preopen_dir / "stage7.csv",
        "stage7_next_pool": stage_data_dir / f"{signal_date}_stage7_next_intraday_pool.csv",
        "stage7_intraday_pool": stage_data_dir / f"{target_date}_intraday_selection_pool_from_{signal_date}_stage7.csv",
        "stage7_summary": stage_data_dir / f"{signal_date}_stage7_1500_summary.csv",
        "stage7_manifest": preopen_dir / "stage7.manifest.json",
        "real_stage7_pool": fupan_dir / "stage7_tail_replay.csv",
        "real_stage7_manifest": fupan_dir / "stage7_tail_replay.manifest.json",
    }


def __load_video_fupan_context_body(_v4_scope, /, paths, signal_date):
    status_payload = _v4_global(_v4_scope, '_read_json')(paths["video_watch_status"])
    if _v4_global(_v4_scope, 'str')(status_payload.get("trade_date") or "") != signal_date:
        status_payload = {}
    acceptance_payload = _v4_global(_v4_scope, '_read_json')(paths["video_acceptance"])
    manifest_payload = _v4_global(_v4_scope, '_read_json')(paths["video_capture_manifest"])
    gap_rows = _v4_global(_v4_scope, '_read_csv')(paths["video_gap_matrix"])
    source_paths = [_v4_global(_v4_scope, 'str')(path) for path in _v4_global(_v4_scope, '_video_source_paths')(paths) if path.exists()]

    status = (
        _v4_global(_v4_scope, 'str')(status_payload.get("status") or "")
        or _v4_global(_v4_scope, 'str')(acceptance_payload.get("status") or "")
        or _v4_global(_v4_scope, 'str')(manifest_payload.get("status") or "")
        or "VIDEO_FUPAN_POOL_NOT_READY"
    )
    videos = status_payload.get("videos") if _v4_global(_v4_scope, 'isinstance')(status_payload.get("videos"), _v4_global(_v4_scope, 'list')) else []
    if not videos and _v4_global(_v4_scope, 'isinstance')(acceptance_payload.get("videos"), _v4_global(_v4_scope, 'list')):
        videos = acceptance_payload.get("videos") or []
    def is_same_day_video(video: dict[str, Any]) -> bool:
        scope = _v4_global(_v4_scope, 'str')(video.get("date_scope") or "")
        upload_digits = "".join(ch for ch in _v4_global(_v4_scope, 'str')(video.get("upload_date") or "") if ch.isdigit())
        upload_date = upload_digits[:8] if _v4_global(_v4_scope, 'len')(upload_digits) >= 8 else ""
        return scope == "SAME_DAY_FUPAN" or upload_date == signal_date or (not scope and not upload_date)

    same_day_videos = [video for video in videos if _v4_global(_v4_scope, 'isinstance')(video, _v4_global(_v4_scope, 'dict')) and is_same_day_video(video)]

    cannot_confirm: list[str] = []
    for payload in (status_payload, acceptance_payload, manifest_payload):
        items = payload.get("cannot_confirm")
        if _v4_global(_v4_scope, 'isinstance')(items, _v4_global(_v4_scope, 'list')):
            cannot_confirm.extend(_v4_global(_v4_scope, 'str')(item) for item in items if _v4_global(_v4_scope, 'str')(item or "").strip())
    cannot_confirm = _v4_global(_v4_scope, 'list')(_v4_global(_v4_scope, 'dict').fromkeys(cannot_confirm))
    if videos and not same_day_videos:
        if gap_rows:
            cannot_confirm.append(
                "Bilibili watch captured a latest fupan video, but it is not SAME_DAY_FUPAN for this signal date; "
                "video gap rows are kept for learning/audit and are not merged into the preopen fupan lane."
            )
        gap_rows = []

    if gap_rows and same_day_videos:
        video_pool_status = "VIDEO_FUPAN_GAP_MATRIX_READY"
    elif gap_rows:
        video_pool_status = "VIDEO_FUPAN_GAP_MATRIX_READY_VIDEO_META_PARTIAL"
    elif videos and not same_day_videos:
        video_pool_status = "VIDEO_FUPAN_CAPTURED_NOT_SIGNAL_DATE"
    elif status == "NO_NEW_VIDEO":
        video_pool_status = "VIDEO_FUPAN_NO_NEW_VIDEO"
    elif status == "BLOCKED_NEED_USER_COOKIE_OR_BV":
        video_pool_status = "VIDEO_FUPAN_BLOCKED_NEED_USER_COOKIE_OR_BV"
    else:
        video_pool_status = "VIDEO_FUPAN_POOL_NOT_READY"

    if not cannot_confirm and not gap_rows:
        cannot_confirm.append("D-1 video second-review did not produce a stock-level gap matrix for the preopen fupan pool.")

    return {
        "status": video_pool_status,
        "raw_status": status,
        "gap_rows": gap_rows,
        "videos_count": _v4_global(_v4_scope, 'len')(videos),
        "same_day_videos_count": _v4_global(_v4_scope, 'len')(same_day_videos),
        "source_paths": source_paths,
        "cannot_confirm": cannot_confirm,
    }


def __build_code_maps_body(_v4_scope, /, theme_rows):
    mapping: dict[str, dict[str, str]] = {}
    for row in theme_rows:
        name = _v4_global(_v4_scope, 'str')(row.get("name") or "").strip()
        code = _v4_global(_v4_scope, 'str')(row.get("code") or "").strip().zfill(6)
        if not name or not code:
            continue
        mapping[name] = {
            "stock_code": code,
            "ts_code": f"{code}{_v4_global(_v4_scope, '_market_suffix')(code)}",
        }
    return mapping


def __build_video_fupan_rows_body(_v4_scope, /, *, target_date, signal_date, video_context, code_map):
    rows: list[dict[str, Any]] = []
    seen: set[str] = _v4_global(_v4_scope, 'set')()
    source_trace = " | ".join(video_context.get("source_paths") or [])
    blocked_decisions = {"REJECT", "NO_ACTION", "BLOCKED"}

    for raw in video_context.get("gap_rows") or []:
        if not _v4_global(_v4_scope, 'isinstance')(raw, _v4_global(_v4_scope, 'dict')):
            continue
        decision = _v4_global(_v4_scope, '_first_text')(raw, "decision", "status").upper()
        if decision in blocked_decisions:
            continue

        ts_code = _v4_global(_v4_scope, '_first_text')(raw, "ts_code")
        code = _v4_global(_v4_scope, '_clean_code')(ts_code or _v4_global(_v4_scope, '_first_text')(raw, "stock_code", "code", "symbol"))
        name = _v4_global(_v4_scope, '_first_text')(raw, "stock_name", "name", "stock")
        if not code and name in code_map:
            info = code_map[name]
            code = info["stock_code"]
            ts_code = info["ts_code"]
        if not code:
            continue
        if not ts_code:
            ts_code = f"{code}{_v4_global(_v4_scope, '_market_suffix')(code)}"
        if not name:
            name = code
        if code in seen:
            continue
        seen.add(code)

        route_context = "；".join(
            part
            for part in [
                _v4_global(_v4_scope, '_first_text')(raw, "video_question_or_framework", "video_framework", "title_or_segment", "item"),
                _v4_global(_v4_scope, '_first_text')(raw, "local_review_answer", "impact", "reason"),
            ]
            if part
        )
        rows.append(
            {
                "target_date": target_date,
                "trade_date": target_date,
                "signal_date": signal_date,
                "stage_id": "D_MINUS_1_FUPAN_VIDEO_REVIEW",
                "ts_code": ts_code,
                "stock_code": code,
                "name": name,
                "stock_name": name,
                "display_name": f"{name}（复/视）",
                "pool_type": "D_MINUS_1_FUPAN_VIDEO_SECOND_REVIEW_POOL",
                "source_tag": "D1_FUPAN_VIDEO",
                "source_tags": "（复/视）",
                "source_lanes": "fupan_lane",
                "stage7_group": "视频二次复盘观察",
                "stage7_label": "D-1自动复盘后经视频二次复盘补充，目标日仍需竞价和开盘承接确认。",
                "stage7_next_day_pool_score": 58,
                "pool_score": 58,
                "primary_buy_signal": "0",
                "secondary_buy_signal": "0",
                "role": _v4_global(_v4_scope, '_first_text')(raw, "role", "gap_type") or "video_second_review",
                "theme": _v4_global(_v4_scope, '_first_text')(raw, "theme", "board", "item", "gap_type"),
                "route_context": route_context,
                "position_tags": f"video_second_review; decision={decision or 'UNKNOWN'}",
                "trigger_condition": _v4_global(_v4_scope, '_first_text')(raw, "trigger_condition")
                or "目标日只看09:25-09:45承接、板块反馈和风险锚变化，不因视频复盘直接买入。",
                "fail_condition": _v4_global(_v4_scope, '_first_text')(raw, "fail_condition")
                or "视频涉及股票无法被本地价量/开盘承接验证时降级为观察或剔除。",
                "boundary": "视频二次复盘只用于补充复盘观察池和风险校正，不是BUY gate。",
                "cannot_confirm": _v4_global(_v4_scope, '_first_text')(raw, "cannot_confirm")
                or "视频股票名/观点仍需本地价量、ASR抽查和开盘承接确认。",
                "source_trace": source_trace,
            }
        )
    return rows


def __merge_fupan_and_video_rows_body(_v4_scope, /, fupan_rows, video_rows):
    merged: list[dict[str, Any]] = []
    by_code: dict[str, dict[str, Any]] = {}
    for row in fupan_rows:
        item = _v4_global(_v4_scope, 'dict')(row)
        code = _v4_global(_v4_scope, 'str')(item.get("stock_code") or _v4_global(_v4_scope, '_clean_code')(item.get("ts_code", "")))
        if code:
            by_code[code] = item
        merged.append(item)

    for row in video_rows:
        code = _v4_global(_v4_scope, 'str')(row.get("stock_code") or _v4_global(_v4_scope, '_clean_code')(row.get("ts_code", "")))
        existing = by_code.get(code)
        if existing is None:
            item = _v4_global(_v4_scope, 'dict')(row)
            by_code[code] = item
            merged.append(item)
            continue
        existing["source_tag"] = "D1_FUPAN+VIDEO"
        existing["source_tags"] = "（复/视）"
        existing["position_tags"] = f"{existing.get('position_tags', '')}; video_second_review"
        existing["route_context"] = f"{existing.get('route_context', '')} | video_second_review: {row.get('route_context', '')}"
        existing["source_trace"] = f"{existing.get('source_trace', '')} | {row.get('source_trace', '')}"
        existing["cannot_confirm"] = (
            f"{existing.get('cannot_confirm', '')}；视频二次复盘只作框架/风险校正，仍需目标日盘口确认。"
        )
        existing["pool_score"] = _v4_global(_v4_scope, '_as_float')(existing.get("pool_score")) + 8
        existing["stage7_next_day_pool_score"] = existing["pool_score"]

    merged.sort(key=lambda item: (-_v4_global(_v4_scope, '_as_float')(item.get("pool_score")), _v4_global(_v4_scope, 'str')(item.get("theme") or ""), _v4_global(_v4_scope, 'str')(item.get("stock_name") or "")))
    for idx, row in _v4_global(_v4_scope, 'enumerate')(merged, start=1):
        row["pool_rank"] = idx
    return merged


def __build_rows_body(_v4_scope, /, *, target_date, signal_date, paths, anchor_rows, theme_rows, plan_rows, handoff_rows):
    code_map = _v4_global(_v4_scope, '_build_code_maps')(theme_rows)
    plan_by_theme = {row.get("mapped_theme") or row.get("planned_anchor") or "": row for row in plan_rows}
    handoff_by_theme = {row.get("theme") or "": row for row in handoff_rows}
    source_trace = "；".join(_v4_global(_v4_scope, 'str')(path) for path in _v4_global(_v4_scope, '_source_paths')(paths))
    rows: list[dict[str, Any]] = []
    seen: set[str] = _v4_global(_v4_scope, 'set')()

    for raw in anchor_rows:
        stock = _v4_global(_v4_scope, 'str')(raw.get("stock") or "").strip()
        theme = _v4_global(_v4_scope, 'str')(raw.get("theme") or "").strip()
        if not stock or stock in seen:
            continue
        info = code_map.get(stock)
        if not info:
            continue
        seen.add(stock)
        role_type = _v4_global(_v4_scope, 'str')(raw.get("role_type") or "")
        group, label, group_score = _v4_global(_v4_scope, '_stage7_group')(role_type, theme)
        plan = plan_by_theme.get(theme, {})
        handoff = handoff_by_theme.get(theme, {})
        score = 50 + _v4_global(_v4_scope, '_role_score')(role_type) + group_score
        rows.append(
            {
                "target_date": target_date,
                "trade_date": target_date,
                "signal_date": signal_date,
                "stage_id": "D_MINUS_1_FUPAN_STAGE7",
                "ts_code": info["ts_code"],
                "stock_code": info["stock_code"],
                "name": stock,
                "stock_name": stock,
                "display_name": f"{stock}（复/分）",
                "pool_type": "D_MINUS_1_FUPAN_AND_STAGE7_OBSERVATION_POOL",
                "source_tag": "D1_FUPAN_STAGE7",
                "source_tags": "D1_FUPAN_STAGE7",
                "source_lanes": "fupan_lane / stage7_lane",
                "stage7_group": group,
                "stage7_label": label,
                "stage7_next_day_pool_score": score,
                "pool_score": score,
                "primary_buy_signal": "0",
                "secondary_buy_signal": "1" if role_type in {"leader", "capacity_anchor"} else "0",
                "role": role_type,
                "theme": theme,
                "route_context": _v4_global(_v4_scope, 'str')(raw.get("why_this_role") or ""),
                "position_tags": f"{role_type}; {group}; {handoff.get('close_role', '')}",
                "trigger_condition": _v4_global(_v4_scope, 'str')(
                    raw.get("tomorrow_if_strong")
                    or plan.get("tomorrow_scenario")
                    or "次日看09:25-09:45承接。"
                ),
                "fail_condition": _v4_global(_v4_scope, 'str')(raw.get("tomorrow_if_weak") or "容量锚或前排负反馈则降级。"),
                "boundary": "D-1复盘/Stage7观察池，不是买入名单；目标日必须再看竞价和开盘四阶段。",
                "cannot_confirm": _v4_global(_v4_scope, 'str')(raw.get("cannot_confirm") or "未确认L2/十档/逐笔/撤单/未匹配量。"),
                "source_trace": source_trace,
            }
        )

    rows.sort(key=lambda row: (-_v4_global(_v4_scope, 'float')(row["pool_score"]), row["theme"], row["stock_name"]))
    for idx, row in _v4_global(_v4_scope, 'enumerate')(rows, start=1):
        row["pool_rank"] = idx
    return rows


def __build_summary_body(_v4_scope, /, rows, target_date, signal_date):
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = _v4_global(_v4_scope, 'defaultdict')(_v4_global(_v4_scope, 'list'))
    for row in rows:
        grouped[(_v4_global(_v4_scope, 'str')(row["theme"]), _v4_global(_v4_scope, 'str')(row["stage7_group"]))].append(row)

    summary: list[dict[str, Any]] = []
    for (theme, group), items in _v4_global(_v4_scope, 'sorted')(grouped.items()):
        summary.append(
            {
                "signal_date": signal_date,
                "target_date": target_date,
                "theme": theme,
                "stage7_group": group,
                "stock_count": _v4_global(_v4_scope, 'len')(items),
                "top_names": "、".join(_v4_global(_v4_scope, 'str')(item["stock_name"]) for item in items[:8]),
                "basis": f"由{signal_date}复盘角色表、情景树和盘中交接表蒸馏生成。",
                "boundary": f"只作为{target_date}分时观察触发器，不是买入名单。",
                "cannot_confirm": "未确认结构化L2/十档/逐笔/撤单/未匹配量。",
            }
        )
    return summary
