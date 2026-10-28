"""Build V3-equivalent D-1 review sources from immutable shared evidence.

The parser, role assignment, board roles, prior-plan and handoff rules are a
direct port of the frozen V3 close-review producer.  The inputs are path-free:
an immutable public bundle, the exact-date selector close rows and V3.5's
native Stage7 input.  No legacy runtime is imported or read.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping

V3_D1_SOURCE_ORACLE_SHA256 = "7a6f13b661ea277b1637e41704d72db04c5c91e866f6eac1e276d1071c96917e"
# Include producer semantics in every materialization identity.  A fixed
# producer must not reuse a receipt emitted by an older parser.
D1_SOURCE_PRODUCER_VERSION = "v3_5.d1_review_source_producer.v3.canonical_a_code_name_resolution"
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.out.append(text)


def _strip_html(html: object) -> str:
    if html is None:
        return ""
    parser = _Stripper()
    try:
        parser.feed(str(html))
        return " ".join(parser.out).replace("\xa0", " ").strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", str(html)).strip()


def _parse_yi(text: object) -> float | None:
    value = str(text or "").replace(",", "").replace(" ", "")
    if not value:
        return None
    sign = -1 if value.startswith("-") else 1
    value = value.lstrip("+-")
    try:
        if "亿" in value:
            return sign * float(value.replace("亿", ""))
        if "万" in value:
            return sign * float(value.replace("万", "")) / 10000.0
        return sign * float(re.sub(r"[^0-9.]", "", value) or "0")
    except Exception:
        return None


def _parse_int(text: object) -> int:
    match = re.search(r"(\d+)", str(text or ""))
    return int(match.group(1)) if match else 0


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value or "").strip())
    except ValueError:
        return default


_CANONICAL_A_CODE = re.compile(
    r"^(?:(?:A|SH|SZ|BJ)\.(\d{6})|(\d{6})\.(?:SH|SZ|BJ)|(\d{6}))$",
    re.IGNORECASE,
)


def _canonical_a_code(value: object) -> str | None:
    """Normalize the accepted exchange-qualified A-share code forms."""

    text = str(value or "").strip().upper()
    match = _CANONICAL_A_CODE.fullmatch(text)
    if not match:
        return None
    return next(group for group in match.groups() if group is not None)


def _parse_dxx_board(html: str, trade_date: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    board_rows: list[dict[str, object]] = []
    stock_rows: list[dict[str, object]] = []
    parts = html.split("<div class='list-group-item ztitem'")[1:]
    for board_rank, part in enumerate(parts, start=1):
        heading = re.search(r"<b[^>]*>(.*?)</b>(.*?)</span>", part, re.S)
        board_name = _strip_html(heading.group(1)) if heading else f"板块{board_rank}"
        catalyst = _strip_html(heading.group(2)) if heading else ""
        catalyst = catalyst.lstrip("：:").strip()
        count_match = re.search(r"<div[^>]*font-weight:bold[^>]*>(\d+)</div>", part, re.S)
        zt_count = int(count_match.group(1)) if count_match else 0
        rows: list[dict[str, object]] = []
        for order, row_html in enumerate(re.findall(r"<tr style='[^']*'>(.*?)</tr>", part, re.S), start=1):
            cells = [_strip_html(value) for value in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]
            if not cells:
                continue
            code_match = re.search(r"code='(\d+)'", row_html)
            row: dict[str, object] = {
                "target_trade_date": trade_date,
                "source": "短线侠 /api/getFupanByYidong type=plate",
                "board_rank": board_rank,
                "board_name": board_name,
                "board_catalyst": catalyst,
                "board_zt_count": zt_count,
                "stock_order_in_board": order,
                "code": code_match.group(1) if code_match else (cells[1] if len(cells) > 1 else ""),
                "name": cells[0] if len(cells) > 0 else "",
                "price": cells[2] if len(cells) > 2 else "",
                "pct_chg": cells[3] if len(cells) > 3 else "",
                "limit_type": cells[4] if len(cells) > 4 else "",
                "board_count_text": cells[5] if len(cells) > 5 else "",
                "lianban_num": cells[6] if len(cells) > 6 else "",
                "first_limit_time": cells[7] if len(cells) > 7 else "",
                "last_limit_time": cells[8] if len(cells) > 8 else "",
                "open_board_times": cells[9] if len(cells) > 9 else "",
                "seal_amount": cells[10] if len(cells) > 10 else "",
                "turnover_amount": cells[11] if len(cells) > 11 else "",
                "turnover_rate": cells[12] if len(cells) > 12 else "",
                "reason": cells[16] if len(cells) > 16 else "",
            }
            row["turnover_amount_yi"] = _parse_yi(row["turnover_amount"])
            row["seal_amount_yi"] = _parse_yi(row["seal_amount"])
            row["lianban_num_int"] = _parse_int(row["lianban_num"])
            row["board_count_int"] = _parse_int(row["board_count_text"])
            rows.append(row)
            stock_rows.append(row)
        max_lb = max([int(row["lianban_num_int"]) for row in rows] or [0])
        leaders = [str(row["name"]) for row in rows if int(row["lianban_num_int"]) == max_lb and max_lb > 0][:4]
        capacity = [str(row["name"]) for row in sorted(rows, key=lambda item: float(item["turnover_amount_yi"] or -1), reverse=True)[:4]]
        risk = [str(row["name"]) for row in rows if str(row["limit_type"]) in ("分歧板", "回封板") or str(row["open_board_times"]) not in ("", "0")][:5]
        board_rows.append({
            "target_trade_date": trade_date,
            "source": "短线侠 /api/getFupanByYidong type=plate",
            "board_rank": board_rank,
            "board_name": board_name,
            "board_catalyst": catalyst,
            "zt_count": zt_count,
            "stock_rows": len(rows),
            "top_stocks": "、".join(str(row["name"]) for row in rows[:8]),
            "leader_candidates": "、".join(leaders),
            "capacity_anchor_candidates": "、".join(capacity),
            "risk_anchor_candidates": "、".join(risk),
            "evidence_state": "DXX_PUBLIC_THEME_LIMIT_POOL_CONFIRMED",
            "cannot_confirm": "短线侠可作题材/涨停池来源，但不证明逐笔主动买卖、十档队列、撤单、真实盘口资金属性；含传闻的催化必须保留质量边界。",
        })
    return board_rows, stock_rows


def _selector_by_code(rows: list[Mapping[str, Any]], trade_date: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("trade_date") or "").replace("-", "") != trade_date:
            continue
        ts_code = str(row.get("ts_code") or "")
        code = _canonical_a_code(ts_code)
        if code is None:
            continue
        result[code] = {
            "code": code,
            "ts_code": ts_code,
            "name": str(row.get("name") or code),
            "pct_chg": round(_as_float(row.get("pct_chg")), 4),
            "amount_yi": round(_as_float(row.get("amount")) / 1e8, 4),
            "split_detected": False,
        }
    return result


def _stock_text(row: Mapping[str, Any]) -> str:
    return f"{row.get('name')}({row.get('code')}) {row.get('pct_chg')}%，{row.get('amount_yi')}亿"


def _enrich_board_rows(board_rows: list[dict[str, object]], stock_rows: list[dict[str, object]], daily_by_code: dict[str, dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[int, list[dict[str, object]]] = defaultdict(list)
    for row in stock_rows:
        grouped[int(row.get("board_rank") or 0)].append(row)
    enriched: list[dict[str, object]] = []
    for board in board_rows:
        rank = int(board.get("board_rank") or 0)
        members = grouped.get(rank, [])
        matched = [daily_by_code.get(str(row.get("code"))) for row in members if daily_by_code.get(str(row.get("code")))]
        matched_clean = [row for row in matched if row]
        amount_sum = round(sum(float(row.get("amount_yi") or 0) for row in matched_clean), 2)
        pct_values = [float(row.get("pct_chg")) for row in matched_clean if row.get("pct_chg") != "" and not row.get("split_detected")]
        pct_avg = round(statistics.mean(pct_values), 2) if pct_values else ""
        strong_amount = sorted(matched_clean, key=lambda row: float(row.get("amount_yi") or 0), reverse=True)[:4]
        local_capacity = "、".join(_stock_text(row) for row in strong_amount)
        if rank == 1:
            role = "MAINLINE 主线候选"
        elif rank <= 3:
            role = "STRONG_BRANCH 强分支"
        elif int(board.get("zt_count") or 0) >= 5:
            role = "ROTATION_BRANCH 轮动分支"
        else:
            role = "WATCH_ONLY 观察分支"
        enriched.append({
            "section": board.get("board_name"),
            "evidence_level": "DXX_THEME_CONFIRMED + TDX_DAILY_CROSSCHECK",
            "today_role": role,
            "local_evidence": f"短线侠涨停 {board.get('zt_count')} 家；催化：{board.get('board_catalyst')}；TDX 日线匹配 {len(matched_clean)}/{len(members)} 只，匹配成交额合计 {amount_sum} 亿，平均涨幅 {pct_avg}%。",
            "anchors": f"高度：{board.get('leader_candidates') or '无'}；容量：{board.get('capacity_anchor_candidates') or local_capacity or '无'}；分歧：{board.get('risk_anchor_candidates') or '未见明显分歧锚'}",
            "next_trigger": "次日看容量锚是否继续承接、前排是否不瀑布、后排是否不大面积掉队；若只剩小票冲高，降级为轮动。",
            "cannot_confirm": board.get("cannot_confirm"),
        })
    return enriched


def _build_anchor_roles(stock_rows: list[dict[str, object]], daily_by_code: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in stock_rows:
        grouped[str(row.get("board_name") or "")].append(row)
    for theme, members in grouped.items():
        members = sorted(members, key=lambda row: (int(row.get("stock_order_in_board") or 999), -_as_float(row.get("turnover_amount_yi"))))
        for index, row in enumerate(members[:8], start=1):
            code = str(row.get("code") or "")
            daily = daily_by_code.get(code, {})
            role_type = "rear_row"
            if index == 1 or _as_float(row.get("lianban_num_int")) >= 2:
                role_type = "leader"
            elif _as_float(row.get("turnover_amount_yi")) >= 10 or _as_float(daily.get("amount_yi")) >= 10:
                role_type = "capacity_anchor"
            if str(row.get("limit_type")) in {"分歧板", "回封板"} or str(row.get("open_board_times")) not in {"", "0"}:
                role_type = "risk_anchor" if role_type == "rear_row" else role_type
            rows.append({
                "theme": theme,
                "stock": str(row.get("name") or code),
                "role_type": role_type,
                "why_this_role": f"短线侠板块第{row.get('board_rank')}行内第{index}；涨停形态={row.get('limit_type')}; TDX日线涨幅={daily.get('pct_chg', '')}%，成交额={daily.get('amount_yi', '')}亿。",
                "confirmed_by": "短线侠涨停池 + 本地TDX日线 + 开盘阶段1分钟K代理",
                "not_confirmed_by": "未确认逐笔主动买卖、十档队列、撤单、未匹配量、视频同日逐字稿。",
                "tomorrow_if_strong": "次日看前排/容量锚是否继续承接，不能只看后排冲高。",
                "tomorrow_if_weak": "若容量锚或前排负反馈，降级为轮动/风险观察。",
                "cannot_confirm": "角色用于复盘学习和次日验证树，不是买入建议。",
            })
    return rows


def _stage_counts(stage_inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Counter]:
    mapping = {"stage4": "STAGE_0940_0945", "stage5": "STAGE_0945_1030", "stage6": "STAGE_1300_1315", "stage7": "STAGE_1445_1500"}
    result: dict[str, Counter] = {}
    for short, stage_id in mapping.items():
        payload = stage_inputs.get(stage_id) or {}
        rows = (payload.get("rows") or {}).get("A") if isinstance(payload.get("rows"), Mapping) else []
        labels = [str(row.get(f"{short}_label") or row.get("stage_label") or "") for row in rows or [] if isinstance(row, Mapping)]
        result[short] = Counter(label for label in labels if label)
    return result


def _build_prior_plan(board_rows: list[dict[str, object]], counts: dict[str, Counter]) -> list[dict[str, str]]:
    return [{
        "planned_anchor": str(board.get("section") or ""),
        "prior_expectation": "承接 D-1 复盘观察池/Stage7 明日观察池，先看开盘四阶段。",
        "mapped_theme": str(board.get("section") or ""),
        "open_realization": f"Stage4 强承接 {counts['stage4'].get('阶段强承接观察', 0)}，一般 {counts['stage4'].get('阶段承接一般观察', 0)}。",
        "intraday_validation": "Stage6/Stage7 已接入，均为 1分钟K代理；不能确认L2盘口。",
        "close_result": str(board.get("today_role") or ""),
        "tomorrow_scenario": str(board.get("next_trigger") or ""),
        "cannot_confirm": "该行是复盘验证树，不是买卖计划。",
    } for board in board_rows[:8]]


def _build_handoff(board_rows: list[dict[str, object]], stage7_counts: Counter) -> list[dict[str, str]]:
    return [{
        "theme": str(board.get("section") or ""),
        "morning_anchor": str(board.get("anchors") or "").split("；")[0],
        "morning_status": "开盘四阶段已接入，证据等级 DATA_PARTIAL_PYTDX_1MIN_BAR。",
        "afternoon_handoff": f"Stage7 标签分布：{dict(stage7_counts)}",
        "failed_anchor": "未接入结构化L2，失败锚只能按日线/1分钟K代理识别。",
        "stage_l0_evidence": str(board.get("local_evidence") or ""),
        "close_role": str(board.get("today_role") or ""),
        "cannot_confirm": "不能用尾盘强弱倒推开盘买点。",
    } for board in board_rows[:10]]


def _market_suffix(code: str) -> str:
    text = str(code or "").zfill(6)
    if text.startswith(("5", "6", "9")):
        return ".SH"
    if text.startswith(("4", "8")):
        return ".BJ"
    return ".SZ"


def _build_stage7_tail(
    stage_inputs: Mapping[str, Mapping[str, Any]],
    trade_date: str,
    *,
    daily_by_code: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    payload = stage_inputs.get("STAGE_1445_1500") or {}
    rows = (payload.get("rows") or {}).get("A") if isinstance(payload.get("rows"), Mapping) else []
    result: list[dict[str, Any]] = []
    for index, row in enumerate(rows or [], start=1):
        if not isinstance(row, Mapping):
            continue
        code = _canonical_a_code(row.get("code") or row.get("symbol") or row.get("ts_code"))
        if code is None:
            continue
        rank = int(_as_float(row.get("pool_rank"), index))
        label = "14:45-15:00 收盘前总结观察候选（富途 OpenD按阶段截止截断的一分钟线命中）"
        prev_close = _as_float(row.get("prev_close_price"))
        open_price = _as_float(row.get("open_price"))
        if prev_close > 0 and open_price > 0:
            change = (open_price / prev_close - 1) * 100
            label += f"；竞价{'涨' if change >= 0 else '跌'}幅 {abs(change):.2f}%"
        daily = (daily_by_code or {}).get(code) or {}
        name = str(
            row.get("stock_name")
            or row.get("name")
            or row.get("display_name")
            or daily.get("name")
            or code
        )
        result.append({
            "pool_rank": rank,
            "ts_code": f"{code}{_market_suffix(code)}",
            "name": name,
            "display_name": name,
            "candidate_source": "real_d1_stage7_tail_replay",
            "candidate_source_path": "stage_inputs/STAGE_1445_1500",
            "pool_score": row.get("pool_score", ""),
            "primary_buy_signal": "0",
            "secondary_buy_signal": "0",
            "stage": "stage7",
            "window": "14:45:00-15:00:00",
            "bar_window": f"{trade_date} 14:45:00-15:00:00",
            "first_open": row.get("open_price", ""),
            "last_close": row.get("last_price", ""),
            "high_price": row.get("high_price", ""),
            "low_price": row.get("low_price", ""),
            "window_change_pct": row.get("window_change_pct", ""),
            "amount_in_window": row.get("amount_in_window", ""),
            "stage_score": row.get("stage_score", row.get("pool_score", "")),
            "stage7_label": label,
            "stage_note": str(row.get("why") or f"pool rank {rank} / score {row.get('pool_score', '')}"),
            "stage7_rank": rank,
            "source_path": "stage_inputs/STAGE_1445_1500",
            "cannot_confirm": "共享分钟线不包含逐笔委托、撤单轨迹、经纪席位或十档队列。",
        })
    result.sort(key=lambda row: int(row["stage7_rank"]))
    return result


def _dedupe_texts(values: object) -> list[str]:
    """Keep machine-readable evidence in its producer order without repeats."""

    if not isinstance(values, (list, tuple)):
        return []
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _stage7_source_evidence(stage_inputs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Project the native Stage7 partial evidence into D-1 source artifacts.

    The Stage7 payload is the authority for coverage and market availability.
    Keep the evidence explicitly scoped to this Stage7 input so an unavailable
    HK quote set cannot be read as a claim about the formal HK pool.
    """

    payload = stage_inputs.get("STAGE_1445_1500") or {}
    source_summary = payload.get("source_summary") if isinstance(payload, Mapping) else {}
    source_summary = dict(source_summary) if isinstance(source_summary, Mapping) else {}
    market_status = payload.get("market_status") if isinstance(payload, Mapping) else {}
    market_status = {
        str(key): str(value)
        for key, value in market_status.items()
    } if isinstance(market_status, Mapping) else {}
    quote_coverage = source_summary.get("quote_coverage")
    quote_coverage = {
        str(key): dict(value)
        for key, value in quote_coverage.items()
        if isinstance(value, Mapping)
    } if isinstance(quote_coverage, Mapping) else {}
    source_summary_cannot_confirm = _dedupe_texts(source_summary.get("cannot_confirm"))
    payload_cannot_confirm = _dedupe_texts(payload.get("cannot_confirm"))
    market_status_reason = ""
    if market_status:
        market_status_reason = "STAGE7_MARKET_STATUS:" + ";".join(
            f"{market}={market_status[market]}"
            for market in sorted(market_status)
        )
    upstream_cannot_confirm = _dedupe_texts(
        [*source_summary_cannot_confirm, *payload_cannot_confirm, market_status_reason]
    )
    return {
        "source_summary": source_summary,
        "source_summary_cannot_confirm": source_summary_cannot_confirm,
        "quote_coverage": quote_coverage,
        "market_status": market_status,
        "cannot_confirm": upstream_cannot_confirm,
    }


def _source_inputs_sha256(
    *,
    trade_date: str,
    public_manifest_sha256: str,
    selector_sha256: str,
    stage_inputs: Mapping[str, Mapping[str, Any]],
) -> str:
    """Hash source data together with the producer's semantic identity."""

    identity = {
        "producer_semantic_version": D1_SOURCE_PRODUCER_VERSION,
        "source_oracle_sha256": V3_D1_SOURCE_ORACLE_SHA256,
        "trade_date": trade_date,
        "public_manifest_sha256": public_manifest_sha256,
        "selector_sha256": selector_sha256,
        "stage_input_sha256s": {
            key: hashlib.sha256(
                json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            for key, value in sorted(stage_inputs.items())
        },
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(str(key))
    if not fields:
        raise ValueError(f"D-1 source would be empty: {path.name}")
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _atomic_bytes(path, buffer.getvalue().encode("utf-8-sig"))


def materialize_d1_review_sources(
    *,
    trade_date: str,
    public_files: Mapping[str, bytes],
    public_manifest_sha256: str,
    selector_rows: list[Mapping[str, Any]],
    selector_sha256: str,
    stage_inputs: Mapping[str, Mapping[str, Any]],
    output_dir: Path,
) -> dict[str, Any]:
    plate_bytes = public_files.get("plate.json")
    if not isinstance(plate_bytes, bytes):
        raise ValueError("shared public plate source missing")
    plate = json.loads(plate_bytes.decode("utf-8-sig", "replace"))
    if not isinstance(plate, dict) or plate.get("result") != "success" or not plate.get("html"):
        raise ValueError("shared public plate source not ready")
    daily_by_code = _selector_by_code(selector_rows, trade_date)
    if not daily_by_code:
        raise ValueError("selector close rows missing for D-1 source producer")
    board_raw, theme_stocks = _parse_dxx_board(str(plate["html"]), trade_date)
    if not board_raw or not theme_stocks:
        raise ValueError("public plate source parsed to zero rows")
    enriched = _enrich_board_rows(board_raw, theme_stocks, daily_by_code)
    stage7 = _build_stage7_tail(
        stage_inputs,
        trade_date,
        daily_by_code=daily_by_code,
    )
    stage7_source_evidence = _stage7_source_evidence(stage_inputs)
    counts = _stage_counts(stage_inputs)
    counts["stage7"] = Counter(str(row.get("stage7_label") or "") for row in stage7)
    anchors = _build_anchor_roles(theme_stocks, daily_by_code)
    prior = _build_prior_plan(enriched, counts)
    handoff = _build_handoff(enriched, counts["stage7"])
    if not anchors or not prior or not handoff or not stage7:
        raise ValueError("D-1 source producer evidence incomplete")

    output_dir = Path(output_dir)
    inputs_sha = _source_inputs_sha256(
        trade_date=trade_date,
        public_manifest_sha256=public_manifest_sha256,
        selector_sha256=selector_sha256,
        stage_inputs=stage_inputs,
    )
    receipt_path = output_dir / "receipt.json"
    if receipt_path.is_file():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing.get("inputs_sha256") == inputs_sha and existing.get("status") == "READY":
            return {**existing, "already_exists": True}
        raise ValueError("D-1 derived source slot already contains different inputs")

    paths = {
        "anchor_role": output_dir / "anchor_role.csv",
        "theme_stocks": output_dir / "theme_stocks.csv",
        "prior_plan": output_dir / "prior_plan.csv",
        "intraday_handoff": output_dir / "intraday_handoff.csv",
        "stage7_tail_replay": output_dir / "stage7_tail_replay.csv",
    }
    for path, rows in (
        (paths["anchor_role"], anchors),
        (paths["theme_stocks"], theme_stocks),
        (paths["prior_plan"], prior),
        (paths["intraday_handoff"], handoff),
        (paths["stage7_tail_replay"], stage7),
    ):
        _write_csv(path, rows)
    stage_manifest = {
        "schema_version": "v3_5.d1_stage7_source.v2",
        "status": "DATA_PARTIAL_OBSERVE_ONLY",
        "trade_date": trade_date,
        "stage_id": "STAGE_1445_1500",
        "row_count": len(stage7),
        "source_role": "real_d1_stage7_tail_replay",
        "producer_semantic_version": D1_SOURCE_PRODUCER_VERSION,
        "source_oracle_sha256": V3_D1_SOURCE_ORACLE_SHA256,
        "source_summary": stage7_source_evidence["source_summary"],
        "source_summary_cannot_confirm": stage7_source_evidence["source_summary_cannot_confirm"],
        "quote_coverage": stage7_source_evidence["quote_coverage"],
        "market_status": stage7_source_evidence["market_status"],
        "cannot_confirm": _dedupe_texts([
            "No L2 order queue, cancellation or unmatched auction evidence.",
            *stage7_source_evidence["cannot_confirm"],
        ]),
        **SAFETY,
    }
    _atomic_bytes(output_dir / "stage7_tail_replay.manifest.json", (json.dumps(stage_manifest, ensure_ascii=False, indent=2) + "\n").encode())
    outputs = {key: {"path": str(path), "sha256": _sha256_bytes(path.read_bytes())} for key, path in paths.items()}
    receipt = {
        "schema_version": "v3_5.d1_review_sources.v2",
        "status": "READY",
        "trade_date": trade_date,
        "inputs_sha256": inputs_sha,
        "producer_semantic_version": D1_SOURCE_PRODUCER_VERSION,
        "source_oracle_sha256": V3_D1_SOURCE_ORACLE_SHA256,
        "public_manifest_sha256": public_manifest_sha256,
        "selector_sha256": selector_sha256,
        "stage7_source_summary": stage7_source_evidence["source_summary"],
        "stage7_source_summary_cannot_confirm": stage7_source_evidence["source_summary_cannot_confirm"],
        "stage7_quote_coverage": stage7_source_evidence["quote_coverage"],
        "stage7_market_status": stage7_source_evidence["market_status"],
        "stage7_cannot_confirm": stage7_source_evidence["cannot_confirm"],
        "cannot_confirm": _dedupe_texts([
            "No L2 order queue, cancellation or unmatched auction evidence.",
            *stage7_source_evidence["cannot_confirm"],
        ]),
        "outputs": outputs,
        "counts": {"anchor_role": len(anchors), "theme_stocks": len(theme_stocks), "prior_plan": len(prior), "intraday_handoff": len(handoff), "stage7_tail_replay": len(stage7)},
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "already_exists": False,
        **SAFETY,
    }
    _atomic_bytes(receipt_path, (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode())
    return receipt


__all__ = ["materialize_d1_review_sources"]
