"""Pure raw-input adapters shared by the local page and replay producers.

The adapters consume caller-supplied DXX JSON/HTML and local binary daily
records.  They never fetch, discover, or write a source artifact.  Keeping
this layer explicit makes the producer inputs auditable and makes an invalid
date impossible to silently replace with an older session.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import struct
from collections import defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.out.append(text)


def strip_html(value: Any) -> str:
    if value is None:
        return ""
    parser = _Stripper()
    try:
        parser.feed(str(value))
        return " ".join(parser.out).replace("\xa0", " ").strip()
    except Exception:
        return re.sub(r"<[^>]+>", " ", str(value)).strip()


def normalize_date(value: Any) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) != 8:
        raise ValueError("trade_date must contain YYYYMMDD")
    try:
        datetime.strptime(digits, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("trade_date must contain YYYYMMDD") from exc
    return digits


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_yi(value: Any) -> float | None:
    text = str(value or "").replace(",", "").replace(" ", "")
    if not text:
        return None
    sign = -1 if text.startswith("-") else 1
    text = text.lstrip("+-")
    try:
        if "亿" in text:
            return sign * float(text.replace("亿", ""))
        if "万" in text:
            return sign * float(text.replace("万", "")) / 10000.0
        return sign * float(re.sub(r"[^0-9.]", "", text) or "0")
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int:
    match = re.search(r"(\d+)", str(value or ""))
    return int(match.group(1)) if match else 0


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).replace("%", "").strip()
        return float(text) if text else default
    except (TypeError, ValueError):
        return default


def parse_dxx_board(html: str, trade_date: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    target = normalize_date(trade_date)
    board_rows: list[dict[str, Any]] = []
    stock_rows: list[dict[str, Any]] = []
    parts = str(html or "").split("<div class='list-group-item ztitem'")[1:]
    for board_rank, part in enumerate(parts, start=1):
        heading = re.search(r"<b[^>]*>(.*?)</b>(.*?)</span>", part, re.S)
        board_name = strip_html(heading.group(1)) if heading else f"板块{board_rank}"
        catalyst = strip_html(heading.group(2)) if heading else ""
        catalyst = catalyst.lstrip("：:").strip()
        count_match = re.search(r"<div[^>]*font-weight:bold[^>]*>(\d+)</div>", part, re.S)
        zt_count = int(count_match.group(1)) if count_match else 0
        rows: list[dict[str, Any]] = []
        for order, row_html in enumerate(re.findall(r"<tr style='[^']*'>(.*?)</tr>", part, re.S), start=1):
            cells = [strip_html(item) for item in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]
            if not cells:
                continue
            code_match = re.search(r"code='(\d+)'", row_html)
            row = {
                "target_trade_date": target,
                "source": "短线侠/api/getFupanByYidong type=plate",
                "board_rank": board_rank,
                "board_name": board_name,
                "board_catalyst": catalyst,
                "board_zt_count": zt_count,
                "stock_order_in_board": order,
                "code": code_match.group(1) if code_match else (cells[1] if len(cells) > 1 else ""),
                "name": cells[0] if cells else "",
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
            row["turnover_amount_yi"] = parse_yi(row["turnover_amount"])
            row["seal_amount_yi"] = parse_yi(row["seal_amount"])
            row["lianban_num_int"] = parse_int(row["lianban_num"])
            row["board_count_int"] = parse_int(row["board_count_text"])
            rows.append(row)
            stock_rows.append(row)
        max_lb = max([int(item["lianban_num_int"]) for item in rows] or [0])
        leaders = [str(item["name"]) for item in rows if int(item["lianban_num_int"]) == max_lb and max_lb > 0][:4]
        capacity = [str(item["name"]) for item in sorted(rows, key=lambda item: float(item["turnover_amount_yi"] or -1), reverse=True)[:4]]
        risk = [
            str(item["name"])
            for item in rows
            if str(item["limit_type"]) in {"分歧板", "回封板"} or str(item["open_board_times"]) not in {"", "0"}
        ][:5]
        top = [str(item["name"]) for item in rows[:8]]
        board_rows.append(
            {
                "target_trade_date": target,
                "source": "短线侠/api/getFupanByYidong type=plate",
                "board_rank": board_rank,
                "board_name": board_name,
                "board_catalyst": catalyst,
                "zt_count": zt_count,
                "stock_rows": len(rows),
                "top_stocks": "、".join(top),
                "leader_candidates": "、".join(leaders),
                "capacity_anchor_candidates": "、".join(capacity),
                "risk_anchor_candidates": "、".join(risk),
                "evidence_state": "DXX_PUBLIC_THEME_LIMIT_POOL_CONFIRMED",
                "cannot_confirm": "短线侠可作题材/涨停池来源，但不证明逐笔主动买卖、十档队列、撤单、真实盘口资金属性；含传闻的催化必须保留质量边界。",
            }
        )
    return board_rows, stock_rows


def parse_dxx_lianban(html: str, trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    rows: list[dict[str, Any]] = []
    parts = str(html or "").split("<div class='list-group-item ztitem'")[1:]
    for tier_rank, part in enumerate(parts, start=1):
        heading = re.search(r"<b[^>]*>(.*?)</b>", part, re.S)
        tier = strip_html(heading.group(1)) if heading else f"tier{tier_rank}"
        for order, row_html in enumerate(re.findall(r"<tr style='[^']*'>(.*?)</tr>", part, re.S), start=1):
            cells = [strip_html(item) for item in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]
            if not cells:
                continue
            code_match = re.search(r"code='(\d+)'", row_html)
            rows.append(
                {
                    "target_trade_date": target,
                    "source": "短线侠/api/getFupanByYidong type=lianban",
                    "tier": tier,
                    "row": order,
                    "code": code_match.group(1) if code_match else (cells[1] if len(cells) > 1 else ""),
                    "name": cells[0] if cells else "",
                    "pct_chg": cells[3] if len(cells) > 3 else "",
                    "limit_type": cells[4] if len(cells) > 4 else "",
                    "reason": cells[16] if len(cells) > 16 else "",
                }
            )
    return rows


def parse_dxx_qingxu(obj: Mapping[str, Any], trade_date: str) -> list[dict[str, Any]]:
    target = normalize_date(trade_date)
    display = datetime.strptime(target, "%Y%m%d").strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    dates = obj.get("dates", {}) if isinstance(obj, Mapping) else {}
    series = obj.get("series", {}) if isinstance(obj, Mapping) else {}
    if obj.get("result") != "success" or display not in dates:
        return rows
    index = int(dates[display])
    names = {
        "QX": "情绪指标",
        "ZT": "涨停家数",
        "DT": "跌停家数",
        "SZ": "上涨家数",
        "XD": "下跌家数",
        "HSLN": "成交额（亿元）",
        "LBGD": "连板高度",
        "PB": "今日封板率",
        "ZTBX": "昨日涨停表现",
        "LBBX": "昨日连板表现",
        "PBBX": "连板晋级率",
        "ZHULI": "主力净流入_亿元",
        "LB": "连板股数",
        "yizi_zt": "一字涨停",
        "yizi_dt": "一字跌停",
        "yizi_fd": "一字封单",
    }
    for key, metric_name in names.items():
        values = series.get(key)
        value = values[index] if isinstance(values, list) and len(values) > index else ""
        previous = values[index - 1] if isinstance(values, list) and index > 0 else ""
        rows.append(
            {
                "target_trade_date": target,
                "source": "短线侠/api/getChartByQingxu",
                "metric": key,
                "metric_name": metric_name,
                "value": value,
                "previous_trade_day_value": previous,
                "evidence_state": "DXX_PUBLIC_MARKET_BREADTH_CONFIRMED",
            }
        )
    return rows


def _tdx_path_to_code(path: Path) -> tuple[str, str]:
    name = path.stem.lower()
    if name.startswith("sh"):
        return name[2:], "SH"
    if name.startswith("sz"):
        return name[2:], "SZ"
    if name.startswith("bj"):
        return name[2:], "BJ"
    return name[-6:], ""


def _is_a_share_stock_code(code: str, exchange: str) -> bool:
    if exchange == "SH":
        return code.startswith(("600", "601", "603", "605", "688", "689"))
    if exchange == "SZ":
        return code.startswith(("000", "001", "002", "003", "300", "301"))
    if exchange == "BJ":
        return code.startswith(("43", "83", "87", "88", "92"))
    return False


def _detect_split_dates(records: Sequence[Mapping[str, Any]]) -> set[str]:
    split_dates: set[str] = set()
    for previous, current in zip(records, records[1:], strict=False):
        previous_close = float(previous.get("close") or 0)
        current_close = float(current.get("close") or 0)
        if previous_close <= 0 or current_close <= 0:
            continue
        ratio = current_close / previous_close
        if ratio < 0.40 or ratio > (1.0 / 0.40):
            split_dates.add(str(current.get("trade_date") or ""))
    return split_dates


def read_tdx_day_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.is_file():
        return []
    data = source.read_bytes()
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(data), 32):
        if offset + 32 > len(data):
            break
        trade_date, open_i, high_i, low_i, close_i, amount_f, vol_i, _ = struct.unpack("<IIIIIfII", data[offset : offset + 32])
        rows.append(
            {
                "trade_date": str(trade_date),
                "open": open_i / 100.0,
                "high": high_i / 100.0,
                "low": low_i / 100.0,
                "close": close_i / 100.0,
                "amount": float(amount_f),
                "vol": int(vol_i),
            }
        )
    return rows


def load_tdx_daily_panel(tdx_root: str | Path, trade_date: str, name_map: Mapping[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    target = normalize_date(trade_date)
    root = Path(tdx_root)
    rows: list[dict[str, Any]] = []
    for exchange in ("sh", "sz", "bj"):
        directory = root / "vipdoc" / exchange / "lday"
        for path in sorted(directory.glob(f"{exchange}*.day")) if directory.is_dir() else []:
            code, exchange_code = _tdx_path_to_code(path)
            if not _is_a_share_stock_code(code, exchange_code):
                continue
            records = read_tdx_day_records(path)
            split_dates = _detect_split_dates(records)
            index = next((idx for idx, item in enumerate(records) if str(item.get("trade_date")) == target), None)
            if index is None:
                continue
            current = records[index]
            previous = records[index - 1] if index > 0 else None
            pre_close = float(previous["close"]) if previous else None
            close = float(current["close"])
            pct = ((close / pre_close - 1) * 100) if pre_close else None
            split_today = str(current.get("trade_date")) in split_dates
            if split_today:
                pct = None
            high = float(current["high"])
            low = float(current["low"])
            amplitude = ((high - low) / pre_close * 100) if pre_close else None
            close_position = (close - low) / (high - low) if high > low else None
            name = str(name_map.get(code) or code)
            limit_threshold = 4.8 if "ST" in name.upper() else (19.5 if code.startswith(("300", "301", "688", "689")) else 9.7)
            rows.append(
                {
                    "trade_date": target,
                    "ts_code": f"{code}.{exchange_code}",
                    "code": code,
                    "name": name,
                    "exchange": exchange_code,
                    "open": round(float(current["open"]), 4),
                    "high": round(high, 4),
                    "low": round(low, 4),
                    "close": round(close, 4),
                    "pre_close": round(pre_close, 4) if pre_close else "",
                    "pct_chg": round(pct, 4) if pct is not None else "",
                    "amplitude_pct": round(amplitude, 4) if amplitude is not None else "",
                    "close_position": round(close_position, 4) if close_position is not None else "",
                    "amount_yi": round(float(current["amount"]) / 1e8, 4),
                    "amount": float(current["amount"]),
                    "vol": int(current["vol"]),
                    "is_limit_up_proxy": bool(pct is not None and pct >= limit_threshold),
                    "is_limit_down_proxy": bool(pct is not None and pct <= -limit_threshold),
                    "split_detected": split_today,
                    "source_path": str(path),
                }
            )
    pct_values = [float(item["pct_chg"]) for item in rows if item["pct_chg"] != "" and not item.get("split_detected")]
    stats = {
        "trade_date": target,
        "rows": len(rows),
        "split_detected_count": sum(1 for item in rows if item.get("split_detected")),
        "amount_sum_yi": round(sum(float(item["amount_yi"]) for item in rows), 2),
        "up_count": sum(1 for item in rows if item["pct_chg"] != "" and float(item["pct_chg"]) > 0),
        "down_count": sum(1 for item in rows if item["pct_chg"] != "" and float(item["pct_chg"]) < 0),
        "flat_count": sum(1 for item in rows if item["pct_chg"] != "" and float(item["pct_chg"]) == 0),
        "limit_up_proxy_count": sum(1 for item in rows if item["is_limit_up_proxy"]),
        "limit_down_proxy_count": sum(1 for item in rows if item["is_limit_down_proxy"]),
        "pct_mean": round(statistics.mean(pct_values), 4) if pct_values else "",
        "pct_median": round(statistics.median(pct_values), 4) if pct_values else "",
        "source": "explicit_tdx_root/vipdoc/{sh,sz,bj}/lday/*.day",
        "evidence_state": f"LOCAL_TDX_DAILY_PANEL_REBUILT_FOR_{target}",
    }
    return rows, stats


def by_code(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("code")): dict(row) for row in rows if row.get("code")}


def load_raw_page_inputs(
    trade_date: str,
    *,
    plate_json: str | Path,
    lianban_json: str | Path,
    qingxu_json: str | Path,
    tdx_root: str | Path,
    name_map: Mapping[str, str],
    jyg_html: str | Path | None = None,
) -> dict[str, Any]:
    target = normalize_date(trade_date)
    plate = read_json(plate_json)
    lianban = read_json(lianban_json)
    qingxu = read_json(qingxu_json)
    if not isinstance(plate, Mapping) or not isinstance(lianban, Mapping) or not isinstance(qingxu, Mapping):
        raise ValueError("raw DXX inputs must be JSON objects")
    board_rows, stock_rows = parse_dxx_board(str(plate.get("html") or ""), target)
    lianban_rows = parse_dxx_lianban(str(lianban.get("html") or ""), target)
    qingxu_rows = parse_dxx_qingxu(qingxu, target)
    # The page oracle gives public board names precedence over a later
    # selector label (for example a temporary ST prefix).  Preserve that
    # deterministic precedence before deriving limit proxies.
    effective_name_map = dict(name_map)
    for item in stock_rows:
        code = str(item.get("code") or "").strip()
        name = str(item.get("name") or "").strip()
        if code and name:
            effective_name_map[code] = name
    daily_rows, daily_stats = load_tdx_daily_panel(tdx_root, target, effective_name_map)
    jyg_count = None
    if jyg_html is not None:
        text = Path(jyg_html).read_text(encoding="utf-8-sig", errors="replace")
        match = re.search(r"allCount:(\d+)", text)
        jyg_count = int(match.group(1)) if match else (0 if "allCount:b" in text else None)
    return {
        "trade_date": target,
        "dxx_board_raw": board_rows,
        "dxx_stock_rows": stock_rows,
        "dxx_lianban_rows": lianban_rows,
        "qingxu_rows": qingxu_rows,
        "daily_rows": daily_rows,
        "daily_stats": daily_stats,
        "jyg_all_count": jyg_count,
        "source_status": [
            {"source": "DXX", "status": str(plate.get("result") or "unknown"), "usable": bool(plate.get("html"))},
            {"source": "DXX", "status": str(lianban.get("result") or "unknown"), "usable": bool(lianban.get("html"))},
            {"source": "DXX", "status": str(qingxu.get("result") or "unknown"), "usable": bool(qingxu.get("series"))},
        ],
    }


__all__ = [
    "by_code",
    "load_raw_page_inputs",
    "load_tdx_daily_panel",
    "normalize_date",
    "parse_dxx_board",
    "parse_dxx_lianban",
    "parse_dxx_qingxu",
    "read_csv_rows",
    "read_json",
]
