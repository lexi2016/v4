#!/usr/bin/env python3
"""Create a bounded, auditable A-share sample frame from the current logical panel."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import importlib.util
import json
import math
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

MAGIC = b"V4_LOGICAL_PANEL_V1\n"
SEED = "p515-stage4-frame-v1-20261113"
SAMPLE_TARGET = 2_000
WINDOW_DAYS = 7

COLUMNS = [
    "trade_date", "ts_code", "market_type", "exchange", "close", "high", "low",
    "amount", "pct_chg", "amplitude_pct", "ma20", "ma60", "high_20",
    "high_20_prev", "market_cap_yi", "float_market_cap_yi", "finance_source_date",
    "turnover_rate_pct", "vol_ratio_60", "upper_shadow_pct", "B1", "B2", "B3",
    "breakout", "double_breakout", "break_prev_high", "brick_pullback_shrink",
    "brick_pullback_white_b", "brick_pullback_yellow_b", "primary_buy_signal",
    "secondary_buy_signal",
]
FLAG_COLUMNS = (
    "breakout", "double_breakout", "break_prev_high", "brick_pullback_shrink",
    "brick_pullback_white_b", "brick_pullback_yellow_b", "primary_buy_signal",
    "secondary_buy_signal",
)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(rows: list[dict[str, Any]], columns: list[str]) -> str:
    h = hashlib.sha256()
    for row in sorted(rows, key=lambda r: (str(r["trade_date"]), str(r["ts_code"]))):
        payload = {column: row.get(column) for column in columns}
        h.update(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode())
        h.update(b"\n")
    return h.hexdigest()


def finite_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def one(value: Any) -> bool:
    number = finite_number(value)
    return number == 1.0


def flag_status(row: dict[str, Any], names: tuple[str, ...]) -> str:
    values = [finite_number(row.get(name)) for name in names]
    if any(value == 1.0 for value in values):
        return "TRUE"
    if values and all(value == 0.0 for value in values):
        return "FALSE"
    return "UNKNOWN"


def code_exchange(row: dict[str, Any]) -> tuple[str, str]:
    code = str(row.get("ts_code") or "")
    match = re.fullmatch(r"(\d{6})\.(SH|SZ|BJ)", code.upper())
    if match is None:
        return "UNKNOWN", "STABLE_SECURITY_ID_FORMAT_INVALID"
    suffix = match.group(2)
    raw = str(row.get("exchange") or "").strip().upper()
    aliases = {"SH": "SH", "SSE": "SH", "SHSE": "SH", "SZ": "SZ", "SZSE": "SZ",
               "BJ": "BJ", "BSE": "BJ", "BSEBJ": "BJ"}
    normalized = aliases.get(raw)
    if suffix not in {"SH", "SZ", "BJ"}:
        return "UNKNOWN", "UNSUPPORTED_SECURITY_SUFFIX"
    if normalized is None:
        return suffix, "EXCHANGE_FROM_SECURITY_SUFFIX"
    if normalized != suffix:
        return "UNKNOWN", "EXCHANGE_SUFFIX_CONFLICT"
    return suffix, "PANEL_EXCHANGE_MATCHES_SECURITY_SUFFIX"


def is_a_share_record(row: dict[str, Any]) -> bool:
    exchange, _ = code_exchange(row)
    market_type = str(row.get("market_type") or "").strip().upper()
    if exchange in {"SH", "SZ"}:
        return market_type == "A_SHARE"
    if exchange == "BJ":
        return market_type == "BJ"
    return False


def date_anchors() -> list[tuple[str, date]]:
    anchors = []
    for year in range(2021, 2027):
        for month in (3, 6, 9, 12):
            if year == 2021 and month < 6:
                continue
            if year == 2026 and month == 12:
                continue
            if month == 12:
                anchor = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                anchor = date(year, month + 1, 1) - timedelta(days=1)
            anchors.append((f"{year}-Q{(month - 1) // 3 + 1}", anchor))
    return anchors


def build_date_windows() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    date_to_cohort: dict[str, str] = {}
    specs: dict[str, dict[str, str]] = {}
    for cohort, anchor in date_anchors():
        start = anchor - timedelta(days=WINDOW_DAYS)
        specs[cohort] = {"anchor": anchor.strftime("%Y%m%d"), "window_start": start.strftime("%Y%m%d")}
        cursor = start
        while cursor <= anchor:
            date_text = cursor.strftime("%Y%m%d")
            date_to_cohort[date_text] = cohort
            cursor += timedelta(days=1)
    date_to_cohort["20261113"] = "CURRENT_20261113"
    specs["CURRENT_20261113"] = {"anchor": "20261113", "window_start": "20261113"}
    return date_to_cohort, specs


def bind_source(pointer: Path, reader_path: Path) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    pointer_bytes = pointer.read_bytes()
    panel_text = pointer_bytes.decode("utf-8-sig", errors="strict").strip().strip('"')
    panel_path = Path(panel_text)
    if not panel_path.is_absolute() or not panel_path.is_file():
        raise RuntimeError(f"CURRENT_SELECTOR_POINTER_INVALID: {panel_path}")
    anchor_bytes = panel_path.read_bytes()
    if not anchor_bytes.startswith(MAGIC):
        raise RuntimeError("CURRENT_SELECTOR_IS_NOT_THE_DECLARED_LOGICAL_PANEL")
    descriptor = json.loads(anchor_bytes[len(MAGIC):])
    if descriptor.get("schema_version") != "v4.original_panel.arrow_blocks.v1":
        raise RuntimeError("LOGICAL_PANEL_SCHEMA_UNKNOWN")
    schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(descriptor["arrow_schema"])))
    metadata = schema.metadata or {}
    if b"a_share_qfq_contract_v1" not in metadata:
        raise RuntimeError("GENERATION_CONTRACT_MISSING")
    contract = json.loads(metadata[b"a_share_qfq_contract_v1"])
    manifest_path = Path(contract["generation_manifest_path"])
    manifest_bytes = manifest_path.read_bytes()
    generation = json.loads(manifest_bytes)
    if contract.get("generation_id") != generation.get("generation_id"):
        raise RuntimeError("GENERATION_ID_CONFLICT")
    if Path(generation["candidates"]["selector"]).resolve() != panel_path.resolve():
        raise RuntimeError("GENERATION_SELECTOR_PATH_CONFLICT")
    if int(generation.get("asof_date", 0)) != 20261113:
        raise RuntimeError("UNEXPECTED_GENERATION_ASOF")
    if generation.get("logical_reader_sha256") != sha256_file(reader_path):
        raise RuntimeError("LOGICAL_READER_SHA_CONFLICT")
    if generation.get("pit_certified") is not False:
        raise RuntimeError("PIT_STATUS_NOT_EXPLICITLY_UNCERTIFIED")
    if contract.get("price_basis") != "MIXED_BY_MARKET" or contract.get("amount_basis") != "MIXED_BY_MARKET":
        raise RuntimeError("UNEXPECTED_TOP_LEVEL_DATA_BASIS")
    if contract.get("market_basis", {}).get("A", {}).get("amount_basis") != "RAW_TURNOVER":
        raise RuntimeError("A_SHARE_AMOUNT_BASIS_UNKNOWN")
    if generation.get("field_basis", {}).get("market_cap_yi", {}).get("basis") != "LEGACY_STATIC_CONTEXT":
        raise RuntimeError("MARKET_CAP_FIELD_BASIS_NOT_STATIC_CONTEXT")
    data_root = pointer.parent.parent
    journal_path = data_root / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal.get("status") != "COMMITTED":
        raise RuntimeError("QFQ_PUBLICATION_NOT_COMMITTED")
    journal_selector = Path(journal.get("after", {}).get("selector", "").strip())
    if journal_selector.resolve() != panel_path.resolve():
        raise RuntimeError("QFQ_JOURNAL_SELECTOR_POINTER_CONFLICT")
    backtest_pointer = data_root / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"
    backtest_path = Path(backtest_pointer.read_text(encoding="utf-8-sig").strip())
    if Path(journal.get("after", {}).get("backtest", "").strip()).resolve() != backtest_path.resolve():
        raise RuntimeError("QFQ_JOURNAL_BACKTEST_POINTER_CONFLICT")
    backtest_bytes = backtest_path.read_bytes()
    if not backtest_bytes.startswith(MAGIC):
        raise RuntimeError("BACKTEST_LOGICAL_PANEL_INVALID")
    backtest_descriptor = json.loads(backtest_bytes[len(MAGIC):])
    backtest_schema = pa.ipc.read_schema(pa.BufferReader(base64.b64decode(backtest_descriptor["arrow_schema"])))
    backtest_contract = json.loads(backtest_schema.metadata[b"a_share_qfq_contract_v1"])
    if backtest_contract.get("generation_id") != contract.get("generation_id"):
        raise RuntimeError("SELECTOR_BACKTEST_GENERATION_CONFLICT")
    missing = [column for column in COLUMNS if column not in schema.names]
    if missing:
        raise RuntimeError(f"REQUIRED_COLUMNS_MISSING: {missing}")
    reader_module_name = "_p515_bound_research_panel_logical"
    spec = importlib.util.spec_from_file_location(reader_module_name, reader_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("LOGICAL_READER_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[reader_module_name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "LogicalFile"):
        raise RuntimeError("LOGICAL_READER_API_MISSING")
    return panel_path, descriptor, contract, generation, {
        "pointer_bytes": pointer_bytes,
        "anchor_bytes": anchor_bytes,
        "schema": schema,
        "manifest_path": manifest_path,
        "manifest_bytes": manifest_bytes,
        "journal_path": journal_path,
        "journal": journal,
        "backtest_path": backtest_path,
        "reader_module": module,
        "backtest_contract": backtest_contract,
    }


def tercile(rows: list[dict[str, Any]], indices: list[int], field: str, output_name: str) -> None:
    ordered = [(finite_number(rows[index].get(field)), str(rows[index].get("ts_code")), index)
               for index in indices]
    known = [(value, code, index) for value, code, index in ordered if value is not None]
    known.sort(key=lambda item: (item[0], item[1]))
    n = len(known)
    for rank, (_, _, index) in enumerate(known):
        bucket = min(2, (rank * 3) // n) if n else 3
        rows[index][output_name] = ("LOW", "MID", "HIGH")[bucket]
    for _, _, index in ordered:
        if finite_number(rows[index].get(field)) is None:
            rows[index][output_name] = "UNKNOWN"


def derive_archetype(row: dict[str, Any]) -> tuple[str, str]:
    buy_status = row["original_buy_signal"]
    breakout_status = row["native_breakout_marker"]
    pullback_status = row["native_pullback_marker"]
    if buy_status == "TRUE":
        return "NATIVE_BUY_SIGNAL_CONTEXT", "primary_buy_signal_or_secondary_buy_signal"
    if buy_status == "UNKNOWN":
        return "UNKNOWN_NATIVE_BUY_STATUS", "primary_or_secondary_buy_flag_missing_or_invalid"
    close = finite_number(row.get("close"))
    high = finite_number(row.get("high"))
    prior_high = finite_number(row.get("high_20_prev"))
    ma20 = finite_number(row.get("ma20"))
    ma60 = finite_number(row.get("ma60"))
    pct = finite_number(row.get("pct_chg"))
    near_high = finite_number(row.get("high_20"))
    has_breakout = breakout_status == "TRUE"
    if high is not None and close is not None and prior_high is not None and high >= prior_high and close < prior_high:
        return "FAILED_BREAKOUT_RISK_PROXY", "D_day_high_at_or_above_high_20_prev_and_close_below_high_20_prev"
    if pct is not None and pct < 0 and close is not None and ma20 is not None and ma60 is not None and close < ma20 < ma60:
        return "DOWNTREND_CONTINUATION_PROXY", "pct_chg_negative_close_below_ma20_below_ma60"
    if close is not None and near_high is not None and near_high > 0 and close / near_high >= 0.90 and row.get("upper_shadow_tercile") == "HIGH":
        return "HIGH_DISTRIBUTION_RISK_CANDIDATE", "close_within_10pct_of_high_20_and_upper_shadow_top_tercile"
    if pct is not None and pct > 0 and close is not None and ma20 is not None and close < ma20 and breakout_status == "FALSE":
        return "ORDINARY_REBOUND_PROXY", "pct_chg_positive_close_below_ma20_without_breakout_flag"
    if close is not None and ma20 is not None and ma20 > 0 and abs(close / ma20 - 1.0) <= 0.03 and row.get("volatility_tercile_within_exchange_day") == "LOW" and breakout_status == "FALSE":
        return "TREND_CONSOLIDATION_PROXY", "close_within_3pct_of_ma20_low_volatility_tercile"
    if breakout_status == "FALSE" and pullback_status == "FALSE":
        return "NO_OBVIOUS_STRUCTURE_PROXY", "no_native_breakout_or_pullback_marker"
    if breakout_status == "UNKNOWN" or pullback_status == "UNKNOWN":
        return "UNKNOWN_NATIVE_STRUCTURE_STATUS", "native_breakout_or_pullback_flag_missing_or_invalid"
    return "OTHER_NON_SIGNAL_STRUCTURE_PROXY", "native_structure_flags_outside_defined_proxy_categories"


def allocate_quotas(groups: dict[str, list[int]], target: int) -> dict[str, int]:
    if not groups:
        return {}
    population = sum(len(indices) for indices in groups.values())
    target = min(population, max(len(groups), target))
    quotas = {key: 1 for key in groups}
    remaining = target - len(groups)
    capacities = {key: len(indices) - 1 for key, indices in groups.items()}
    capacity_total = sum(capacities.values())
    if remaining <= 0 or capacity_total <= 0:
        return quotas
    exact = {key: remaining * capacity / capacity_total for key, capacity in capacities.items()}
    for key, value in exact.items():
        quotas[key] += min(capacities[key], int(math.floor(value)))
    assigned = sum(quotas.values()) - len(groups)
    left = remaining - assigned
    order = sorted(groups, key=lambda key: (-(exact[key] - math.floor(exact[key])), key))
    for key in order:
        if left <= 0:
            break
        if quotas[key] < len(groups[key]):
            quotas[key] += 1
            left -= 1
    return quotas


def build_report(manifest: dict[str, Any], sample_rows: list[dict[str, Any]], coverage: dict[str, Any]) -> str:
    sample_by_exchange = Counter(row["exchange_stratum"] for row in sample_rows)
    sample_by_case = Counter(row["archetype_candidate_category"] for row in sample_rows)
    sample_by_pit = Counter(row["PIT_status"] for row in sample_rows)
    lines = [
        "# P5.15 全A股样本框覆盖报告",
        "",
        "本产物是从当前逻辑面板按固定季度截面建立的候选观察样本框。行级标签、事件根锚和历史PIT没有由本任务创建或认证。",
        "",
        "## 来源与读取边界",
        "",
        f"- 逻辑锚路径为 `{manifest['source']['selector_path']}`，SHA-256 为 `{manifest['source']['selector_anchor_sha256']}`。",
        f"- generation 为 `{manifest['source']['generation_id']}`，candidate receipt SHA-256 为 `{manifest['source']['candidate_receipt_sha256']}`。selector 与 backtest 指针及generation一致，发布journal状态为 `{manifest['source']['publication_status']}`。",
        f"- 读者路径为 `{manifest['source']['logical_reader_path']}`，SHA-256为 `{manifest['source']['logical_reader_sha256']}`，与candidate receipt声明一致。单次流式投影读取逻辑行数 `{coverage['logical_rows_seen']:,}`，保留的A股观察母体 `{manifest['population']['rows']:,}` 行。",
        f"- 实际观察日期从 `{manifest['population']['date_min']}` 到 `{manifest['population']['date_max']}`，共 `{len(manifest['population']['observation_dates'])}` 个截面。每个季度从季度末前7个日历日内选择已观察到的最新交易日，并另含当前日期 `{manifest['population']['current_date']}`。",
        "- A股面板金额口径按generation合同为RAW_TURNOVER。市值字段是LEGACY_STATIC_CONTEXT，样本中的市值分层仅表示存储值分层，不代表各历史D日市值，也不得作为训练特征。",
        "- generation明确 `pit_certified=false`。该样本框逐行记为 `CANNOT_CONFIRM_HISTORICAL_PIT`。面板行数和截面母体只代表当前面板所含记录，不能解释为交易所完整证券名录。",
        "",
        "## 观察母体与概率抽样",
        "",
        f"- 观察单位为 `stable_security_id × observation_date`，固定日期截面的A股记录共 `{manifest['population']['rows']:,}` 行，唯一证券数 `{manifest['population']['unique_securities']:,}`。同股跨日期重复观察保留，不能直接当作独立事件。",
        f"- 所有候选行依交易所、市值存储值三分位及D日结构候选类别组成主抽样层，共 `{manifest['sampling']['stratum_count']:,}` 个非空层。目标样本 `{manifest['sampling']['target_n']:,}` 行，最终抽取 `{len(sample_rows):,}` 行。每层使用SHA-256排序确定性无放回抽样，行级包含概率为 `n_h / N_h`，CSV记录该概率与层内分母。",
        f"- 母体键SHA-256为 `{manifest['population']['population_key_sha256']}`，母体特征投影SHA-256为 `{manifest['population']['population_projection_sha256']}`。抽样种子为 `{manifest['sampling']['seed']}`。",
        "- 抽样概率只对应此文件所列固定截面和主抽样层。其他维度是覆盖属性。除非按此概率合同重新加权，否则样本不代表连续全市场股票日分布。",
        "",
        "## 覆盖结果",
        "",
        "| 维度 | 母体覆盖 | 抽样覆盖 | 状态 |",
        "|---|---:|---:|---|",
    ]
    for name, item in coverage["dimensions"].items():
        lines.append(f"| {name} | {item['population_categories']} 类 | {item['sample_categories']} 类 | {item['status']} |")
    lines.extend(["", "### 抽样交易所数量", ""])
    for key in ("SH", "SZ", "BJ", "UNKNOWN"):
        lines.append(f"- {key} 为 `{sample_by_exchange.get(key, 0):,}` 行。")
    lines.extend(["", "### 样本候选结构类别", ""])
    for key, value in sorted(sample_by_case.items()):
        lines.append(f"- `{key}` 为 `{value:,}` 行。类别由当日字段启发式定义，状态为候选代理。")
    lines.extend([
        "",
        "## 排除与缺口",
        "",
        f"- 选定截面窗口的非A股记录 `{coverage['non_a_share_candidate_window_rows']:,}` 行未入母体。日期窗口内的其他A股日期 `{coverage['non_selected_window_a_share_rows']:,}` 行未进入季度截面。",
        f"- 当前generation descriptor列出 `{manifest['source']['descriptor_excluded_symbols_count']}` 个排除证券标识。这是本版本逻辑面板的排除清单，不等同官方全市场总体的排除数量。",
        f"- 无法确认的市值PIT年龄记录 `{coverage['cap_source_date_missing_or_future']:,}` 个母体观察；样本全体PIT状态为 `{sample_by_pit.get('CANNOT_CONFIRM_HISTORICAL_PIT', 0):,}` 行。",
        "- 未生成阶段标签、回调标签、事件ID或根锚。它们在CSV中保持UNKNOWN。所有类别计数只用于样本抽取覆盖，不表示课程正例或反例。",
        "- 未取行情源之外的市值、行业或分类数据。官方上市证券名录对面板外证券的覆盖未核验。",
        "",
        "## 运行回执",
        "",
        f"- 流式读取耗时 `{coverage['elapsed_seconds']:.1f}` 秒，峰值RSS采样 `{coverage['peak_rss_bytes']:,}` 字节。",
        f"- CSV SHA-256 为 `{manifest['output']['sample_csv_sha256']}`。manifest和报告的最终SHA在交付目录 `SHA256SUMS.txt` 中登记。",
        "- 本任务仅创建研究样本框。正式训练fit、标签验证和预测计数均为0。",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pointer", type=Path, required=True)
    parser.add_argument("--reader", type=Path, required=True)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument("--output-manifest", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    args = parser.parse_args()

    started = time.monotonic()
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_report.parent.mkdir(parents=True, exist_ok=True)
    reader_sha = sha256_file(args.reader)
    panel_path, descriptor, contract, generation, bound = bind_source(args.pointer, args.reader)
    logical = bound["reader_module"].LogicalFile(panel_path)
    schema_names = logical.schema_arrow.names
    col_indices = {name: schema_names.index(name) for name in COLUMNS}
    date_to_cohort, cohort_specs = build_date_windows()
    target_date_values = pa.array(sorted(date_to_cohort), type=pa.string())
    candidate_tables: dict[str, list[pa.Table]] = defaultdict(list)
    rows_seen = 0
    a_share_bj_tagged_rows_seen = 0
    candidate_window_rows = 0
    candidate_window_a_rows = 0
    candidate_window_tagged_a_rows = 0
    non_a_share_candidate_window_rows = 0
    candidate_identity_mismatch_rows = 0
    unique_a_share_ids: set[str] = set()
    min_date: str | None = None
    max_date: str | None = None
    peak_rss = 0

    psutil_module = None
    try:
        import psutil as psutil_module
    except ImportError:
        pass
    process = psutil_module.Process() if psutil_module else None

    for batch in logical.iter_batches(batch_size=131072, columns=COLUMNS):
        table = pa.Table.from_batches([batch])
        rows_seen += table.num_rows
        dates = table["trade_date"]
        bounds = pc.min_max(dates)
        batch_min = bounds["min"].as_py()
        batch_max = bounds["max"].as_py()
        if batch_min is not None:
            min_date = batch_min if min_date is None else min(min_date, batch_min)
            max_date = batch_max if max_date is None else max(max_date, batch_max)
        market_mask = pc.is_in(table["market_type"], value_set=pa.array(["A_SHARE", "BJ"], type=pa.string()))
        a_share = table.filter(market_mask)
        a_share_bj_tagged_rows_seen += a_share.num_rows
        if a_share.num_rows:
            unique_a_share_ids.update(str(value) for value in pc.unique(a_share["ts_code"]).to_pylist())
        date_mask = pc.is_in(dates, value_set=target_date_values)
        candidate = table.filter(date_mask)
        candidate_window_rows += candidate.num_rows
        if candidate.num_rows:
            candidate_a = candidate.filter(
                pc.is_in(candidate["market_type"], value_set=pa.array(["A_SHARE", "BJ"], type=pa.string()))
            )
            candidate_window_tagged_a_rows += candidate_a.num_rows
            non_a_share_candidate_window_rows += candidate.num_rows - candidate_a.num_rows
            for identity_row in candidate_a.select(["ts_code", "market_type", "exchange"]).to_pylist():
                if is_a_share_record(identity_row):
                    candidate_window_a_rows += 1
                else:
                    candidate_identity_mismatch_rows += 1
            for date_value in pc.unique(candidate_a["trade_date"]).to_pylist():
                date_text = str(date_value)
                rows = candidate_a.filter(pc.equal(candidate_a["trade_date"], pa.scalar(date_value)))
                candidate_tables[date_text].append(rows.select(COLUMNS))
        if process is not None:
            peak_rss = max(peak_rss, process.memory_info().rss)

    date_tables: dict[str, pa.Table] = {}
    for date_text, tables in candidate_tables.items():
        date_tables[date_text] = pa.concat_tables(tables) if len(tables) > 1 else tables[0]

    selected_dates: dict[str, str] = {}
    for cohort, spec in cohort_specs.items():
        start, anchor = spec["window_start"], spec["anchor"]
        available = [value for value in date_tables if start <= value <= anchor and date_to_cohort.get(value) == cohort]
        if available:
            selected_dates[cohort] = max(available)

    selected_population: list[dict[str, Any]] = []
    all_window_candidate_keys = set()
    selected_date_keys = set(selected_dates.values())
    selected_dates_missing = sorted(set(selected_dates.values()) - set(date_tables))
    for date_text in sorted(selected_date_keys):
        table = date_tables[date_text]
        records = table.to_pylist()
        for row in records:
            if not is_a_share_record(row):
                continue
            row["trade_date"] = str(row["trade_date"])
            row["ts_code"] = str(row["ts_code"])
            row["sample_unit_id"] = f"{row['ts_code']}|{row['trade_date']}"
            row["phase_label"] = "UNKNOWN_NOT_CREATED"
            row["pullback_label"] = "UNKNOWN_NOT_CREATED"
            row["event_id"] = "UNKNOWN"
            row["root_anchor_id"] = "UNKNOWN"
            row["label_source"] = "NONE_SAMPLE_FRAME_ONLY"
            row["label_maturity_date"] = "UNKNOWN"
            row["PIT_status"] = "CANNOT_CONFIRM_HISTORICAL_PIT"
            row["UNKNOWN_reason"] = "GENERATION_PIT_CERTIFIED_FALSE_AND_NO_EVENT_LABELS_CREATED"
            row["finance_source_age_days"] = None
            finance_date = row.get("finance_source_date")
            try:
                finance_text = str(int(finance_date))
                observed = datetime.strptime(row["trade_date"], "%Y%m%d").date()
                sourced = datetime.strptime(finance_text, "%Y%m%d").date()
                row["finance_source_age_days"] = (observed - sourced).days
            except (TypeError, ValueError, OverflowError):
                pass
            exchange, exchange_status = code_exchange(row)
            row["exchange_stratum"] = exchange
            row["exchange_identity_status"] = exchange_status
            row["original_buy_signal"] = flag_status(row, ("primary_buy_signal", "secondary_buy_signal"))
            row["native_breakout_marker"] = flag_status(row, ("breakout", "double_breakout", "break_prev_high"))
            row["native_pullback_marker"] = flag_status(row, ("brick_pullback_shrink", "brick_pullback_white_b", "brick_pullback_yellow_b"))
            row["cap_tier_as_stored_nonpit"] = "UNKNOWN"
            row["liquidity_tercile_within_exchange_day"] = "UNKNOWN"
            row["volatility_tercile_within_exchange_day"] = "UNKNOWN"
            row["upper_shadow_tercile"] = "UNKNOWN"
            row["price_position_proxy"] = "UNKNOWN"
            row["archetype_candidate_category"] = "UNCLASSIFIED"
            row["archetype_proxy_reason"] = "MISSING_OR_UNSUPPORTED_FEATURES"
            row["market_regime_proxy"] = "UNKNOWN"
            selected_population.append(row)

    population_keys = [(row["trade_date"], row["ts_code"]) for row in selected_population]
    if len(population_keys) != len(set(population_keys)):
        raise RuntimeError("DUPLICATE_SECURITY_DATE_KEYS_IN_SELECTED_POPULATION")

    by_date: dict[str, list[int]] = defaultdict(list)
    by_date_exchange: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(selected_population):
        by_date[row["trade_date"]].append(index)
        by_date_exchange[(row["trade_date"], row["exchange_stratum"])].append(index)

    for date_text, indices in by_date.items():
        # The stored market-cap values are explicitly a non-PIT sampling stratum.
        tercile(selected_population, indices, "market_cap_yi", "cap_tier_as_stored_nonpit")
        returns = [finite_number(selected_population[index].get("pct_chg")) for index in indices]
        valid_returns = [value for value in returns if value is not None]
        advances = sum(value > 0 for value in valid_returns)
        declines = sum(value < 0 for value in valid_returns)
        advance_share = advances / len(valid_returns) if valid_returns else None
        decline_share = declines / len(valid_returns) if valid_returns else None
        if advance_share is None:
            regime = "UNKNOWN"
        elif advance_share >= 0.60:
            regime = "RISING_BREADTH_PROXY"
        elif decline_share is not None and decline_share >= 0.60:
            regime = "FALLING_BREADTH_PROXY"
        else:
            regime = "MIXED_OR_SIDEWAYS_BREADTH_PROXY"
        for index in indices:
            selected_population[index]["market_regime_proxy"] = regime
            selected_population[index]["market_advance_share"] = advance_share
            selected_population[index]["market_decline_share"] = decline_share
            close = finite_number(selected_population[index].get("close"))
            ma60 = finite_number(selected_population[index].get("ma60"))
            high20 = finite_number(selected_population[index].get("high_20"))
            if close is None or ma60 is None or ma60 <= 0:
                position = "UNKNOWN"
            elif close < ma60:
                position = "LOWER_THAN_MA60_PROXY"
            elif high20 is not None and high20 > 0 and close / high20 >= 0.90:
                position = "NEAR_20D_HIGH_PROXY"
            else:
                position = "MIDDLE_POSITION_PROXY"
            selected_population[index]["price_position_proxy"] = position
        for (_, _), group_indices in [((date_text, exchange), group) for (group_date, exchange), group in by_date_exchange.items() if group_date == date_text]:
            tercile(selected_population, group_indices, "amount", "liquidity_tercile_within_exchange_day")
            tercile(selected_population, group_indices, "amplitude_pct", "volatility_tercile_within_exchange_day")
            tercile(selected_population, group_indices, "upper_shadow_pct", "upper_shadow_tercile")

    for row in selected_population:
        category, reason = derive_archetype(row)
        row["archetype_candidate_category"] = category
        row["archetype_proxy_reason"] = reason
        row["selection_date_cohort"] = next((name for name, selected in selected_dates.items() if selected == row["trade_date"]), "UNKNOWN")
        row["primary_sampling_stratum"] = "|".join([
            row["selection_date_cohort"], row["exchange_stratum"], row["cap_tier_as_stored_nonpit"], category
        ])
        row["selection_rule_version"] = "p515_stage4_stratified_frame_v1"

    strata: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(selected_population):
        strata[row["primary_sampling_stratum"]].append(index)
    quota = allocate_quotas(strata, SAMPLE_TARGET)
    chosen_indices = []
    for stratum_id, indices in strata.items():
        ordered = sorted(indices, key=lambda index: hashlib.sha256(
            f"{SEED}|{stratum_id}|{selected_population[index]['trade_date']}|{selected_population[index]['ts_code']}".encode()
        ).hexdigest())
        chosen = ordered[:quota[stratum_id]]
        chosen_indices.extend(chosen)
        inclusion_probability = quota[stratum_id] / len(indices)
        for rank, index in enumerate(chosen, start=1):
            row = selected_population[index]
            row["population_stratum_n"] = len(indices)
            row["sample_stratum_n"] = quota[stratum_id]
            row["sampling_probability"] = inclusion_probability
            row["selection_rank_within_stratum"] = rank
            row["sampling_method"] = "DETERMINISTIC_SHA256_RANK_SRSWOR"
            row["sampling_seed"] = SEED

    sample_rows = [selected_population[index] for index in chosen_indices]
    sample_rows.sort(key=lambda row: (row["trade_date"], row["ts_code"]))
    counts_by_security = Counter(row["ts_code"] for row in sample_rows)
    for row in sample_rows:
        row["same_security_repeated_across_dates"] = int(counts_by_security[row["ts_code"]] > 1)

    output_columns = [
        "sample_unit_id", "stable_security_id", "ts_code", "trade_date", "selection_date_cohort",
        "market_type", "exchange", "exchange_stratum", "exchange_identity_status",
        "primary_sampling_stratum", "population_stratum_n", "sample_stratum_n", "sampling_probability",
        "selection_rank_within_stratum", "sampling_method", "sampling_seed", "same_security_repeated_across_dates",
        "close", "high", "low", "amount", "pct_chg", "amplitude_pct", "ma20", "ma60", "high_20", "high_20_prev",
        "market_cap_yi", "float_market_cap_yi", "finance_source_date", "finance_source_age_days", "turnover_rate_pct", "vol_ratio_60",
        "cap_tier_as_stored_nonpit", "liquidity_tercile_within_exchange_day", "volatility_tercile_within_exchange_day",
        "price_position_proxy", "market_regime_proxy", "market_advance_share", "market_decline_share",
        "native_breakout_marker", "native_pullback_marker", "original_buy_signal", "archetype_candidate_category",
        "archetype_proxy_reason", *FLAG_COLUMNS, "B1", "B2", "B3", "PIT_status", "phase_label", "pullback_label",
        "event_id", "root_anchor_id", "label_source", "label_maturity_date", "UNKNOWN_reason", "selection_rule_version",
    ]
    for row in sample_rows:
        row["stable_security_id"] = row["ts_code"]
    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_csv.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=output_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(sample_rows)
    output_csv_sha = sha256_file(args.output_csv)

    source_population_cols = ["trade_date", "ts_code", *COLUMNS[4:]]
    population_key_sha = canonical_sha(selected_population, ["trade_date", "ts_code"])
    population_projection_sha = canonical_sha(selected_population, source_population_cols)
    sample_key_sha = canonical_sha(sample_rows, ["trade_date", "ts_code"])
    date_counts = Counter(row["trade_date"] for row in selected_population)
    exchange_pop = Counter(row["exchange_stratum"] for row in selected_population)
    exchange_sample = Counter(row["exchange_stratum"] for row in sample_rows)
    case_pop = Counter(row["archetype_candidate_category"] for row in selected_population)
    case_sample = Counter(row["archetype_candidate_category"] for row in sample_rows)
    cap_pop = Counter(row["cap_tier_as_stored_nonpit"] for row in selected_population)
    cap_sample = Counter(row["cap_tier_as_stored_nonpit"] for row in sample_rows)
    liquidity_pop = Counter(row["liquidity_tercile_within_exchange_day"] for row in selected_population)
    liquidity_sample = Counter(row["liquidity_tercile_within_exchange_day"] for row in sample_rows)
    volatility_pop = Counter(row["volatility_tercile_within_exchange_day"] for row in selected_population)
    volatility_sample = Counter(row["volatility_tercile_within_exchange_day"] for row in sample_rows)
    regime_pop = Counter(row["market_regime_proxy"] for row in selected_population)
    regime_sample = Counter(row["market_regime_proxy"] for row in sample_rows)
    price_pop = Counter(row["price_position_proxy"] for row in selected_population)
    price_sample = Counter(row["price_position_proxy"] for row in sample_rows)
    breakout_pop = Counter(row["native_breakout_marker"] for row in selected_population)
    breakout_sample = Counter(row["native_breakout_marker"] for row in sample_rows)
    pullback_pop = Counter(row["native_pullback_marker"] for row in selected_population)
    pullback_sample = Counter(row["native_pullback_marker"] for row in sample_rows)
    buy_pop = Counter(row["original_buy_signal"] for row in selected_population)
    buy_sample = Counter(row["original_buy_signal"] for row in sample_rows)
    missing_future_finance_date = sum(
        row.get("finance_source_age_days") is None or row["finance_source_age_days"] < 0
        for row in selected_population
    )

    dimensions = {
        "沪市/深市/北交所": {"population_categories": len([k for k in exchange_pop if k != "UNKNOWN"]), "sample_categories": len([k for k in exchange_sample if k != "UNKNOWN"]), "status": "COVERED" if all(exchange_pop.get(k, 0) > 0 and exchange_sample.get(k, 0) > 0 for k in ("SH", "SZ", "BJ")) else "PARTIAL"},
        "市值大中小存储值分层": {"population_categories": len([k for k in cap_pop if k in {"LOW", "MID", "HIGH"}]), "sample_categories": len([k for k in cap_sample if k in {"LOW", "MID", "HIGH"}]), "status": "COVERED_NONPIT_ONLY" if all(cap_pop.get(k, 0) > 0 and cap_sample.get(k, 0) > 0 for k in ("LOW", "MID", "HIGH")) else "PARTIAL"},
        "交易额流动性分层": {"population_categories": len([k for k in liquidity_pop if k in {"LOW", "MID", "HIGH"}]), "sample_categories": len([k for k in liquidity_sample if k in {"LOW", "MID", "HIGH"}]), "status": "COVERED_WITHIN_EXCHANGE_DAY" if all(liquidity_pop.get(k, 0) > 0 and liquidity_sample.get(k, 0) > 0 for k in ("LOW", "MID", "HIGH")) else "PARTIAL"},
        "波动率分层": {"population_categories": len([k for k in volatility_pop if k in {"LOW", "MID", "HIGH"}]), "sample_categories": len([k for k in volatility_sample if k in {"LOW", "MID", "HIGH"}]), "status": "COVERED_WITHIN_EXCHANGE_DAY" if all(volatility_pop.get(k, 0) > 0 and volatility_sample.get(k, 0) > 0 for k in ("LOW", "MID", "HIGH")) else "PARTIAL"},
        "市场涨跌广度环境代理": {"population_categories": len([k for k in regime_pop if k != "UNKNOWN"]), "sample_categories": len([k for k in regime_sample if k != "UNKNOWN"]), "status": "COVERED_PROXY" if all(regime_pop.get(k, 0) > 0 and regime_sample.get(k, 0) > 0 for k in ("RISING_BREADTH_PROXY", "FALLING_BREADTH_PROXY", "MIXED_OR_SIDEWAYS_BREADTH_PROXY")) else "PARTIAL"},
        "低位/中位/高位价格位置代理": {"population_categories": len([k for k in price_pop if k != "UNKNOWN"]), "sample_categories": len([k for k in price_sample if k != "UNKNOWN"]), "status": "COVERED_PROXY" if all(price_pop.get(k, 0) > 0 and price_sample.get(k, 0) > 0 for k in ("LOWER_THAN_MA60_PROXY", "MIDDLE_POSITION_PROXY", "NEAR_20D_HIGH_PROXY")) else "PARTIAL"},
        "突破有无": {"population_categories": len([k for k in breakout_pop if k != "UNKNOWN"]), "sample_categories": len([k for k in breakout_sample if k != "UNKNOWN"]), "status": "COVERED" if all(breakout_pop.get(k, 0) and breakout_sample.get(k, 0) for k in ("FALSE", "TRUE")) else "PARTIAL"},
        "回调结构标记有无": {"population_categories": len([k for k in pullback_pop if k != "UNKNOWN"]), "sample_categories": len([k for k in pullback_sample if k != "UNKNOWN"]), "status": "COVERED" if all(pullback_pop.get(k, 0) and pullback_sample.get(k, 0) for k in ("FALSE", "TRUE")) else "PARTIAL"},
        "原主副买点有无": {"population_categories": len([k for k in buy_pop if k != "UNKNOWN"]), "sample_categories": len([k for k in buy_sample if k != "UNKNOWN"]), "status": "COVERED" if all(buy_pop.get(k, 0) and buy_sample.get(k, 0) for k in ("FALSE", "TRUE")) else "PARTIAL"},
        "六类非信号候选代理": {"population_categories": sum(case_pop.get(k, 0) > 0 for k in ("ORDINARY_REBOUND_PROXY", "FAILED_BREAKOUT_RISK_PROXY", "DOWNTREND_CONTINUATION_PROXY", "HIGH_DISTRIBUTION_RISK_CANDIDATE", "TREND_CONSOLIDATION_PROXY", "NO_OBVIOUS_STRUCTURE_PROXY")), "sample_categories": sum(case_sample.get(k, 0) > 0 for k in ("ORDINARY_REBOUND_PROXY", "FAILED_BREAKOUT_RISK_PROXY", "DOWNTREND_CONTINUATION_PROXY", "HIGH_DISTRIBUTION_RISK_CANDIDATE", "TREND_CONSOLIDATION_PROXY", "NO_OBVIOUS_STRUCTURE_PROXY")), "status": "COVERED_PROXY" if all(case_pop.get(k, 0) > 0 and case_sample.get(k, 0) > 0 for k in ("ORDINARY_REBOUND_PROXY", "FAILED_BREAKOUT_RISK_PROXY", "DOWNTREND_CONTINUATION_PROXY", "HIGH_DISTRIBUTION_RISK_CANDIDATE", "TREND_CONSOLIDATION_PROXY", "NO_OBVIOUS_STRUCTURE_PROXY")) else "PARTIAL"},
    }
    coverage = {
        "logical_rows_seen": rows_seen,
        "a_share_bj_tagged_rows_seen": a_share_bj_tagged_rows_seen,
        "candidate_window_rows": candidate_window_rows,
        "candidate_window_a_share_rows": candidate_window_a_rows,
        "candidate_window_a_share_tagged_rows": candidate_window_tagged_a_rows,
        "candidate_window_identity_mismatch_rows": candidate_identity_mismatch_rows,
        "non_a_share_candidate_window_rows": non_a_share_candidate_window_rows,
        "non_selected_window_a_share_rows": candidate_window_a_rows - len(selected_population),
        "peak_rss_bytes": peak_rss,
        "elapsed_seconds": time.monotonic() - started,
        "cap_source_date_missing_or_future": missing_future_finance_date,
        "dimensions": dimensions,
        "population_by_date": dict(sorted(date_counts.items())),
        "population_by_exchange": dict(sorted(exchange_pop.items())),
        "sample_by_exchange": dict(sorted(exchange_sample.items())),
        "population_by_case": dict(sorted(case_pop.items())),
        "sample_by_case": dict(sorted(case_sample.items())),
        "population_by_cap_tier_as_stored": dict(sorted(cap_pop.items())),
        "sample_by_cap_tier_as_stored": dict(sorted(cap_sample.items())),
        "population_by_liquidity_tercile": dict(sorted(liquidity_pop.items())),
        "sample_by_liquidity_tercile": dict(sorted(liquidity_sample.items())),
        "population_by_volatility_tercile": dict(sorted(volatility_pop.items())),
        "sample_by_volatility_tercile": dict(sorted(volatility_sample.items())),
        "population_by_regime_proxy": dict(sorted(regime_pop.items())),
        "sample_by_regime_proxy": dict(sorted(regime_sample.items())),
        "population_by_price_position_proxy": dict(sorted(price_pop.items())),
        "sample_by_price_position_proxy": dict(sorted(price_sample.items())),
        "sample_by_signal_flags": {
            "breakout": dict(sorted(breakout_sample.items())),
            "pullback": dict(sorted(pullback_sample.items())),
            "original_buy": dict(sorted(buy_sample.items())),
        },
    }

    manifest = {
        "schema": "p515.full_universe_sample_frame.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "formal_fit_count": 0,
        "new_model_predict_count": 0,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "source": {
            "selector_pointer_path": str(args.pointer),
            "selector_pointer_sha256": hashlib.sha256(bound["pointer_bytes"]).hexdigest(),
            "selector_path": str(panel_path),
            "selector_anchor_sha256": hashlib.sha256(bound["anchor_bytes"]).hexdigest(),
            "generation_id": contract["generation_id"],
            "candidate_receipt_path": str(bound["manifest_path"]),
            "candidate_receipt_sha256": hashlib.sha256(bound["manifest_bytes"]).hexdigest(),
            "logical_reader_path": str(args.reader),
            "logical_reader_sha256": reader_sha,
            "reader_sha_matches_receipt": True,
            "publication_journal_path": str(bound["journal_path"]),
            "publication_status": bound["journal"].get("status"),
            "selector_backtest_generation_match": True,
            "declared_historical_pit_certified": generation.get("pit_certified"),
            "price_basis": contract.get("price_basis"),
            "amount_basis": contract.get("amount_basis"),
            "a_share_amount_basis": contract.get("market_basis", {}).get("A", {}).get("amount_basis"),
            "market_cap_field_basis": generation.get("field_basis", {}).get("market_cap_yi"),
            "block_count": len(descriptor.get("blocks", [])),
            "descriptor_rows": descriptor.get("rows"),
            "descriptor_excluded_symbols_count": len(descriptor.get("excluded_symbols", [])),
            "descriptor_excluded_symbols": descriptor.get("excluded_symbols", []),
        },
        "population": {
            "unit": "stable_security_id_by_observation_date",
            "market_scope": "A_SHARE_ROWS_PRESENT_IN_CURRENT_LOGICAL_PANEL",
            "rows": len(selected_population),
            "unique_securities": len({row["ts_code"] for row in selected_population}),
            "date_min": min((row["trade_date"] for row in selected_population), default=None),
            "date_max": max((row["trade_date"] for row in selected_population), default=None),
            "current_date": "20261113",
            "observation_dates": sorted(selected_date_keys),
            "missing_quarter_end_cohorts": sorted(set(cohort_specs) - set(selected_dates)),
            "selected_date_by_cohort": dict(sorted(selected_dates.items())),
            "row_count_by_date": dict(sorted(date_counts.items())),
            "unique_a_share_securities_in_full_panel": len(unique_a_share_ids),
            "full_panel_date_min": min_date,
            "full_panel_date_max": max_date,
            "logical_rows_seen": rows_seen,
            "a_share_bj_tagged_rows_seen": a_share_bj_tagged_rows_seen,
            "non_a_share_candidate_window_rows": non_a_share_candidate_window_rows,
            "candidate_window_identity_mismatch_rows": candidate_identity_mismatch_rows,
            "non_selected_window_a_share_rows": candidate_window_a_rows - len(selected_population),
            "population_key_sha256": population_key_sha,
            "population_projection_sha256": population_projection_sha,
            "selected_sample_key_sha256": sample_key_sha,
        },
        "sampling": {
            "seed": SEED,
            "method": "DETERMINISTIC_SHA256_RANK_SRSWOR_WITHIN_PRIMARY_STRATUM",
            "target_n": max(SAMPLE_TARGET, len(strata)),
            "actual_n": len(sample_rows),
            "stratum_count": len(strata),
            "stratum_key": ["selection_date_cohort", "exchange_stratum", "cap_tier_as_stored_nonpit", "archetype_candidate_category"],
            "probability_field": "sampling_probability=n_h/N_h",
            "all_probability_rows_positive": all(0 < row["sampling_probability"] <= 1 for row in sample_rows),
            "cohort_window_days_before_quarter_end": WINDOW_DAYS,
            "quarter_end_date_anchor_rule": "latest observed A-share date within 7 calendar days ending on each calendar quarter end",
            "cap_stratum_warning": "AS_STORED_NONPIT_ONLY",
            "archetype_warning": "HEURISTIC_CANDIDATE_PROXY_NOT_LABEL",
        "stratum_denominators": {
            key: {
                "population_n": len(indices),
                "sample_n": quota[key],
                "inclusion_probability": quota[key] / len(indices),
            }
            for key, indices in sorted(strata.items())
        },
        },
        "coverage": coverage,
        "exclusions": {
            "outside_selected_date_windows": rows_seen - candidate_window_rows,
            "non_a_share_in_candidate_date_windows": non_a_share_candidate_window_rows,
            "candidate_window_a_share_not_selected_as_quarter_cut": candidate_window_a_rows - len(selected_population),
            "missing_quarter_end_cohorts": sorted(set(cohort_specs) - set(selected_dates)),
            "missing_or_future_finance_source_dates_in_population": missing_future_finance_date,
            "source_descriptor_excluded_symbols": descriptor.get("excluded_symbols", []),
            "unknown_event_identity_rows": len(selected_population),
            "unknown_phase_or_pullback_label_rows": len(selected_population),
        },
        "output": {
            "sample_csv_path": str(args.output_csv),
            "sample_csv_sha256": output_csv_sha,
            "manifest_path": str(args.output_manifest),
            "report_path": str(args.output_report),
            "script_path": str(Path(__file__).resolve()),
            "script_sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    report = build_report(manifest, sample_rows, coverage)
    args.output_report.write_text(report, encoding="utf-8")
    args.output_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest_sha = sha256_file(args.output_manifest)
    report = build_report(manifest, sample_rows, coverage)
    args.output_report.write_text(report, encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "logical_rows_seen": rows_seen,
        "a_share_bj_tagged_rows_seen": a_share_bj_tagged_rows_seen,
        "population_rows": len(selected_population),
        "sample_rows": len(sample_rows),
        "sample_size_bytes": args.output_csv.stat().st_size,
        "selected_dates": selected_dates,
        "exchange_population": dict(exchange_pop),
        "exchange_sample": dict(exchange_sample),
        "archetype_population": dict(case_pop),
        "archetype_sample": dict(case_sample),
        "dimensions": dimensions,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "peak_rss_bytes": peak_rss,
        "sample_csv_sha256": output_csv_sha,
        "manifest_sha256": manifest_sha,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
