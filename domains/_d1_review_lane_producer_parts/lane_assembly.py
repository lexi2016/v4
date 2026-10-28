"""domains.d1_review_lane_producer: lane_assembly (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __rows_for_lane_body(_v4_scope, /, rows, *, lane):
    tag = "（复）" if lane == "fupan_lane" else "（分）"
    label = "D1_FUPAN" if lane == "fupan_lane" else "D1_STAGE7"
    stage_id = "D_MINUS_1_FUPAN" if lane == "fupan_lane" else "D_MINUS_1_STAGE7"
    out: list[dict[str, Any]] = []
    for row in rows:
        item = _v4_global(_v4_scope, 'dict')(row)
        item["stage_id"] = stage_id
        item["display_name"] = f"{item.get('stock_name') or item.get('name')}{tag}"
        item["source_tag"] = label
        item["source_tags"] = tag
        item["source_lanes"] = lane
        item["pool_type"] = (
            "D_MINUS_1_FUPAN_OBSERVATION_POOL"
            if lane == "fupan_lane"
            else "D_MINUS_1_STAGE7_NEXT_INTRADAY_POOL"
        )
        out.append(item)
    return out


def __build_real_stage7_rows_body(_v4_scope, /, *, target_date, signal_date, path, manifest_path):
    """Build the Stage7 lane from the real D-1 14:45-15:00 replay output."""

    raw_rows = _v4_global(_v4_scope, '_read_csv')(path)
    manifest = _v4_global(_v4_scope, '_read_json')(manifest_path)
    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        code = _v4_global(_v4_scope, '_clean_code')(
            raw.get("stock_code") or raw.get("code") or raw.get("ts_code", "")
        )
        name = _v4_global(_v4_scope, 'str')(raw.get("name") or raw.get("stock_name") or raw.get("display_name") or code).strip()
        if not code or not name:
            continue
        ts_code = f"{code}{_v4_global(_v4_scope, '_market_suffix')(code)}"
        score = _v4_global(_v4_scope, '_as_float')(raw.get("stage_score") or raw.get("pool_score"))
        source_path = _v4_global(_v4_scope, 'str')(raw.get("source_path") or "")
        source_trace = _v4_global(_v4_scope, 'str')(path)
        if source_path:
            source_trace = f"{source_trace} | replay_source={source_path}"
        rows.append(
            {
                "target_date": target_date,
                "trade_date": target_date,
                "signal_date": signal_date,
                "stage_id": "D_MINUS_1_REAL_STAGE7_TAIL_REPLAY",
                "ts_code": ts_code,
                "stock_code": code,
                "name": name,
                "stock_name": name,
                "display_name": f"{name}（分）",
                "pool_type": "D_MINUS_1_STAGE7_NEXT_INTRADAY_POOL",
                "source_tag": "D1_REAL_STAGE7",
                "source_tags": "（分）",
                "source_lanes": "stage7_lane",
                "stage7_group": _v4_global(_v4_scope, 'str')(raw.get("stage7_label") or raw.get("stage") or "D-1 Stage7 尾盘观察"),
                "stage7_label": _v4_global(_v4_scope, 'str')(raw.get("stage7_label") or raw.get("stage_note") or ""),
                "stage7_next_day_pool_score": f"{score:.2f}",
                "pool_score": f"{score:.2f}",
                "primary_buy_signal": _v4_global(_v4_scope, 'str')(raw.get("primary_buy_signal") or "0"),
                "secondary_buy_signal": _v4_global(_v4_scope, 'str')(raw.get("secondary_buy_signal") or "0"),
                "role": _v4_global(_v4_scope, 'str')(raw.get("stage7_label") or "D-1 Stage7尾盘"),
                "theme": "",
                "route_context": _v4_global(_v4_scope, 'str')(raw.get("stage_note") or ""),
                "position_tags": f"stage7_rank={raw.get('stage7_rank') or raw.get('pool_rank') or ''}; window={raw.get('window') or raw.get('bar_window') or ''}",
                "trigger_condition": "目标日仅看 09:25-09:45 分时承接、竞价强弱和板块反馈；不因 D-1 尾盘池直接买入。",
                "fail_condition": "目标日竞价低于预期、开盘无承接、放量下杀或板块负反馈则降级。",
                "boundary": "D-1 14:45-15:00 本地 1 分钟线尾盘回放，只作次日分时观察触发器，不是买入名单。",
                "cannot_confirm": _v4_global(_v4_scope, 'str')(
                    raw.get("cannot_confirm")
                    or "仅为本地历史 1 分钟 K 线回放，不能确认逐笔主动买卖、十档队列、撤单轨迹、竞价未匹配量。"
                ),
                "source_trace": source_trace,
                "_sort_rank": _v4_global(_v4_scope, '_as_int')(raw.get("stage7_rank") or raw.get("pool_rank")),
                "_sort_score": score,
            }
        )

    rows.sort(key=lambda row: (_v4_global(_v4_scope, 'int')(row.get("_sort_rank") or 999999), -_v4_global(_v4_scope, 'float')(row.get("_sort_score") or 0), row["stock_code"]))
    for idx, row in _v4_global(_v4_scope, 'enumerate')(rows, start=1):
        row["pool_rank"] = idx
        row.pop("_sort_rank", None)
        row.pop("_sort_score", None)

    return rows, manifest
