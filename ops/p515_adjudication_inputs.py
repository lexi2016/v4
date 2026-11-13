"""Trace and project the frozen P5.15 R1.2 H1 and supplemental RAW inputs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


BAR_COLUMNS = ("ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount")
PRICE_FIELDS = ("open", "high", "low", "close")
RAW_PRICE_BASIS = "RAW_UNADJUSTED"
SECURITY_RE = re.compile(r"[0-9]{6}\.(SH|SZ|BJ)\Z")
DAY_RECORD = struct.Struct("<IIIIIfII")
NOTICES = {
    ("SH", 2026): "https://big5.sse.com.cn/site/cht/www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml",
    ("SZ", 2026): "https://www.szse.cn/English/services/trading/calendar/",
    ("BJ", 2026): "https://www.bse.cn/important_news/200027428.html",
    ("SZ", 2025): "https://www.szse.cn/disclosure/notice/general/t20241223_611283.html",
}
# Nominal exchanges' 2026 holidays were compared with the four notices above.
CLOSED_PERIODS = {
    2025: (("20250101", "20250101"), ("20250128", "20250204"), ("20250404", "20250406"),
           ("20250501", "20250505"), ("20250531", "20250602"), ("20251001", "20251008")),
    2026: (("20260101", "20260103"), ("20260215", "20260223"), ("20260404", "20260406"),
           ("20260501", "20260505"), ("20260619", "20260621"), ("20260925", "20260927"),
           ("20261001", "20261007")),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return sha256(raw).hexdigest()


def csv_rows(raw):
    reader = csv.DictReader(StringIO(raw.decode("utf-8-sig"), newline=""))
    fields = tuple(reader.fieldnames or ())
    data = list(reader)
    require(fields and len(fields) == len(set(fields)), "Missing or non-unique CSV headers")
    require(all(None not in row and None not in row.values() for row in data), "Malformed CSV row width")
    return fields, data


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def checksums(raw):
    index = {}
    for line in raw.decode("utf-8-sig").splitlines():
        checksum, name = line.split("  ", 1)
        require(name not in index and re.fullmatch(r"[0-9a-f]{64}", checksum), f"Invalid checksum entry: {name}")
        index[name] = checksum
    return index


def checked_member(archive, prefix, index, name, expected=None):
    raw = archive.read(prefix + name)
    require(index[name] == digest(raw) and (expected is None or index[name] == expected),
            f"Archived member digest conflict: {name}")
    return raw


def trade_day(value):
    text = str(value)
    require(re.fullmatch(r"[0-9]{8}", text), f"Bad trade date: {text}")
    return datetime.strptime(text, "%Y%m%d").date()


def phase_bars(rows, security, observed, expected_rows, first_day):
    require(SECURITY_RE.fullmatch(security), f"Unknown security code: {security}")
    require(len(rows) == expected_rows, f"Row count conflict: {security} {observed}")
    dates = [trade_day(row["trade_date"]) for row in rows]
    require(dates == sorted(set(dates)) and dates[-1] == trade_day(observed) and dates[0] == trade_day(first_day),
            f"Bad time axis or D cutoff: {security} {observed}")
    for row in rows:
        require(row["ts_code"] == security, f"Conflicting bar identity: {security} {observed}")
        opening, high, low, close, volume, amount = [Decimal(str(row[field])) for field in BAR_COLUMNS[2:]]
        require(all(x.is_finite() for x in (opening, high, low, close, volume, amount))
                and 0 < low <= min(opening, close) <= max(opening, close) <= high
                and volume >= 0 and volume == volume.to_integral_value() and amount >= 0,
                f"OHLCV/turnover constraint failure: {security} {row['trade_date']}")
    return dates


def calendar_status(dates, exchange):
    checked = [d for d in dates if (exchange, d.year) in NOTICES]
    require(all(d.weekday() < 5 for d in dates), "Source contains a weekend trade bar")
    require(all(not any(trade_day(start) <= d <= trade_day(end) for start, end in CLOSED_PERIODS[d.year])
                for d in checked), "Source contains an official closure date")
    if len(checked) != len(dates):
        return "PARTIAL_UNKNOWN_SOURCE_DATES_ONLY", ""
    expected = set()
    day = dates[0]
    while day <= dates[-1]:
        if day.weekday() < 5 and not any(trade_day(s) <= day <= trade_day(e) for s, e in CLOSED_PERIODS[day.year]):
            expected.add(day)
        day += timedelta(days=1)
    return "VERIFIED_EXCHANGE_SCHEDULE", len(expected - set(dates))


def numeric_bar(row):
    return (int(row["trade_date"]), *(Decimal(str(row[field])) for field in BAR_COLUMNS[2:]))


class NativeDaySources:
    """Bind exact RAW record indices to SHA-checked archived TDX files once."""

    def __init__(self, source_rows):
        self.files = defaultdict(list)
        for row in source_rows:
            self.files[row["sha256"], row["source_role"], row["ts_code"]].append(Path(row["path"]))
        self.loaded = {}

    def verify(self, row, security):
        source_sha = row["raw_source_ref_sha256"]
        key = source_sha, row["raw_source_role"], security
        if key not in self.loaded:
            candidates = [path for path in set(self.files[key]) if path.is_file()]
            require(candidates, f"Raw source not available: {key}")
            original = sorted(candidates)[0].read_bytes()
            require(len(original) % DAY_RECORD.size == 0 and digest(original) == source_sha,
                    f"Raw source identity conflict: {key}")
            self.loaded[key] = original
        idx = Decimal(str(row["raw_source_record_index"]))
        require(idx.is_finite() and idx == idx.to_integral_value() and idx >= 0,
                f"Invalid native record index: {security} {row['trade_date']}")
        value = self.loaded[key]
        offset = int(idx) * DAY_RECORD.size
        require(offset + DAY_RECORD.size <= len(value), "Native record index exceeds source size")
        day, op, hi, lo, close, amount, volume, _ = DAY_RECORD.unpack_from(value, offset)
        expected = (day, *(Decimal(x) / 100 for x in (op, hi, lo, close)), Decimal(volume), Decimal(str(amount)))
        require(numeric_bar(row) == expected, f"Native record/value conflict: {security} {day}")
        return source_sha


def make_archive(folder, destination):
    names = sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file())
    with ZipFile(destination, "w") as archive:
        for name in names:
            info = ZipInfo(name, date_time=(2026, 11, 13, 0, 0, 0))
            archive.writestr(info, (folder / name).read_bytes(), compress_type=ZIP_DEFLATED)
    with ZipFile(destination) as archive:
        require(archive.testzip() is None and archive.namelist() == names, "Judge ZIP integrity failure")
        require(all(archive.read(name) == (folder / name).read_bytes() for name in names),
                "Judge ZIP member mismatch")


def render_charts(manifest_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PatchCollection
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import StrMethodFormatter

    directory = manifest_path.parent
    _, manifest = csv_rows(manifest_path.read_bytes())
    for entry in manifest:
        _, rows = csv_rows((directory / entry["input_prefix_file"]).read_bytes())
        values = [numeric_bar(row) for row in rows]
        fig, (px, vx) = plt.subplots(2, 1, sharex=True, figsize=(12, 7),
                                      gridspec_kw={"height_ratios": [3, 1]}, layout="constrained")
        bodies, wicks, colors = [], [], []
        for idx, (_, opening, high, low, close, _, _) in enumerate(values):
            colors.append("#be4640" if close >= opening else "#258777")
            wicks.append([(idx, float(low)), (idx, float(high))])
            bodies.append(Rectangle((idx - 0.33, float(min(opening, close))),
                                    0.66, max(0.002, float(abs(close - opening)))))
        px.add_collection(LineCollection(wicks, colors=colors, linewidths=0.8))
        px.add_collection(PatchCollection(bodies, facecolors=colors, linewidths=0))
        px.autoscale_view()
        vx.bar(range(len(values)), [float(row[5]) for row in values], color=colors, width=0.66)
        vx.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        ticks = sorted({0, *(len(rows) * q // 4 for q in (1, 2, 3)), len(rows) - 1})
        vx.set_xticks(ticks, [trade_day(values[i][0]).isoformat() for i in ticks])
        vx.set_xlim(-2, len(values) + 1)
        for axis in (px, vx):
            axis.grid(axis="y", alpha=0.18)
            axis.set_axisbelow(True)
        px.set_ylabel("RAW price (CNY/share)")
        vx.set_ylabel("Volume (source units)")
        px.set_title(f"{entry['sample_id']}  |  Through D close: {trade_day(entry['observation_date']).isoformat()}", loc="left")
        fig.savefig(directory / entry["chart_file"], dpi=120, metadata={"Software": "P5.15 H1 D-only"})
        plt.close(fig)


def load_parquet(raw, selected_ids):
    import pyarrow.parquet as pq

    table = pq.read_table(BytesIO(raw), filters=[("query_id", "in", sorted(selected_ids))])
    groups = defaultdict(list)
    for row in table.to_pylist():
        groups[row["query_id"]].append(row)
    return groups


def raw_prefix(rows, security, observed, expected_rows, first_day, native):
    days = phase_bars(rows, security, observed, expected_rows, first_day)
    require(all(row["stable_security_id"] == security and row["exchange"] == security[-2:]
                and row["D"] == int(observed) and row["price_basis"] == "TDX_RAW_UNADJUSTED"
                and row["source_sha256"] == row["raw_source_ref_sha256"]
                for row in rows), f"RAW parquet evidence conflict: {security} {observed}")
    return days, sorted({native.verify(row, security) for row in rows})


def export_sup_raw(out, registers, parquet, coverage, inputs, native):
    target = out / "SUP_RAW_14_EXPORTS"
    target.mkdir()
    recovered = []
    excluded = []
    for row in registers:
        security, observed = row["security_id"], row["D"]
        key = f"{security}_{observed}"
        values, section = parquet[key], coverage[key]
        require((section["ts_code"], section["D"]) == (security, observed), f"Coverage key conflict: {key}")
        require(row["input_source_sha256"] == inputs["raw_parquet_sha256"], f"Casebook digest conflict: {key}")
        require(int(section["exported_rows"]) == len(values), f"Coverage row count conflict: {key}")
        if row["available_case_input"] != "DEV_INPUT_AVAILABLE":
            require(int(row["prefix_rows"]) == 0 and all(value["open"] is None and value["close"] is None for value in values)
                    and section["raw_status"].startswith("UNKNOWN"), "Unaccounted missing-RAW row")
            excluded.append((key, len(values), section["raw_status"]))
            continue
        require(section["raw_status"] == "BOUND" and row["price_basis"] == RAW_PRICE_BASIS
                and (section["first_date"], section["last_date"]) == (row["prefix_start"], row["prefix_max_date"]),
                f"Original coverage contract conflict: {key}")
        days, source_hashes = raw_prefix(values, security, observed, int(row["prefix_rows"]),
                                         row["prefix_start"], native)
        output = target / f"{key}.csv"
        write_csv(output, BAR_COLUMNS, [{field: value[field] for field in BAR_COLUMNS} for value in values])
        raw = output.read_bytes()
        _, saved = csv_rows(raw)
        require([numeric_bar(item) for item in saved] == [numeric_bar(item) for item in values], f"Export changed a bar: {key}")
        recovered.append({
            "stable_security_id": security, "observation_date": observed, "original_query_id": key,
            "price_basis": RAW_PRICE_BASIS, "source_price_basis": "TDX_RAW_UNADJUSTED", "prefix_rows": len(values),
            "first_date": days[0].strftime("%Y%m%d"), "last_date": days[-1].strftime("%Y%m%d"),
            "duplicate_dates": 0, "post_D_rows": 0, "source_archive_sha256": inputs["supplement_sha256"],
            "source_parquet_file": "DAILY_BARS_455.parquet", "source_parquet_sha256": inputs["raw_parquet_sha256"],
            "source_original_export_manifest_sha256": inputs["supplement_manifest_sha256"],
            "source_coverage_csv_sha256": inputs["supplement_coverage_sha256"],
            "source_mac_casebook_registry_sha256": inputs["casebook_sha256"], "native_day_sha256": "|".join(source_hashes),
            "export_file": output.relative_to(out).as_posix(), "export_sha256": digest(raw), "bytes": len(raw),
            "exposure_status": "EXPOSED_DEV", "status": "RAW_PREFIX_RESTORED_SOURCE_AND_EXPORT_VERIFIED",
        })
    require(len(recovered) == 14 and len(excluded) == 1, "Frozen supplemental scope changed")
    write_csv(out / "SUP_RAW_14_EXPORT_MANIFEST.csv", tuple(recovered[0]), recovered)
    return recovered, excluded


def judge_projection(source_rows, h1_rows, security, day):
    require(len(source_rows) == len(h1_rows), f"Projection row count conflict: {security} {day}")
    require(all(a["ts_code"] == security and numeric_bar(a) == numeric_bar(b)
                for a, b in zip(source_rows, h1_rows)), f"R1.2 H1 projection changed RAW values: {security} {day}")


def export_h1(args, h1, r12, r12_shas, sup, prefix, sup_shas, parquet, corp, native, inputs):
    out = args.output
    target = out / "H1_R1_3_ADJUDICATION"
    target.mkdir()
    (target / "inputs").mkdir()
    (target / "charts").mkdir()
    id_file = args.id_registry
    if id_file.exists():
        random_ids = json.loads(id_file.read_bytes())
    else:
        random_ids = {row["sample_id"]: "H1-" + uuid4().hex for row in h1}
        with id_file.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(random_ids, sort_keys=True, indent=2) + "\n")
    require(set(random_ids) == {row["sample_id"] for row in h1} and len(set(random_ids.values())) == len(h1)
            and all(re.fullmatch(r"H1-[0-9a-f]{32}", key) for key in random_ids.values()), "Invalid frozen judge ID map")

    audit = []
    manifest = []
    for row in h1:
        sid = random_ids[row["sample_id"]]
        security, observed = row["stable_security_id"], row["D"]
        market = security[-2:]
        key = f"{security}_{observed}"
        require(row["exchange"] == market and row["price_basis"] == RAW_PRICE_BASIS
                and row["exposure_status"] == "EXPOSED_DEV" and row["post_D_rows_in_input"] == "0"
                and row["prefix_max_date"] == observed and row["prefix_rows"] == "120"
                and row["source_archive_sha256"] == inputs["supplement_sha256"],
                f"R1.2 scope/identity conflict: {key}")
        raw = checked_member(r12, "", r12_shas, row["input_prefix_file"], row["input_prefix_SHA"])
        r12_png_key = row["input_prefix_file"].replace(".csv", ".png")
        checked_member(r12, "", r12_shas, r12_png_key, row["chart_SHA"])
        header, values = csv_rows(raw)
        require(header == BAR_COLUMNS, f"R1.2 judge CSV has extra or reordered fields: {key}")
        days = phase_bars(values, security, observed, 120, row["prefix_start"])
        source = checked_member(sup, prefix, sup_shas, row["source_member"], row["source_SHA"])
        _, source_values = csv_rows(source)
        judge_projection(source_values, values, security, observed)
        if key in parquet:
            reference = parquet[key][-120:]
            _, hashes = raw_prefix(reference, security, observed, 120, row["prefix_start"], native)
            judge_projection(reference, values, security, observed)
            raw_suspension = reference[-1]["suspension_status"]
            provenance = "EXACT_R12_ORIGINAL_MEMBER_AND_RAW_PARQUET"
        else:
            hashes = sorted({native.verify(record, security) for record in source_values})
            raw_suspension = "UNKNOWN"
            provenance = "EXACT_R12_COLUMNS_MATCH_HISTORICAL_PAIR_NATIVE"
        official, date_gaps = calendar_status(days, market)
        corporate_records = corp.get(key, [])
        in_window_actions = sorted({entry["ex_date"] for entry in corporate_records
                                    if row["prefix_start"] <= entry["ex_date"] <= observed})
        data_path = f"inputs/{sid}.csv"
        png_path = f"charts/{sid}.png"
        (target / data_path).write_bytes(raw)
        manifest.append({
            "sample_id": sid, "stable_security_id": security, "observation_date": observed,
            "market": market, "exposure_status": "EXPOSED_DEV", "prefix_rows": len(values),
            "prefix_start": row["prefix_start"], "prefix_end": observed,
            "input_prefix_file": data_path, "input_prefix_sha256": digest(raw),
            "source_raw_sha256": digest(source), "chart_file": png_path, "chart_sha256": "",
            "price_basis": RAW_PRICE_BASIS, "volume_unit": "TDX_DAY_RAW_UNIT",
            "amount_unit": "RAW_TURNOVER_UNIT_NOT_INDEPENDENTLY_CERTIFIED",
            "security_identity_status": "SOURCE_KEY_BOUND_HISTORICAL_MASTER_UNKNOWN",
            "raw_bar_integrity_status": "EXACT_RAW_SOURCE_VERIFIED",
            "exchange_calendar_status": official, "suspension_status": "UNKNOWN",
            "corporate_action_pit_status": "UNKNOWN", "sector_pit_status": "UNKNOWN",
        })
        audit.append({
            **manifest[-1], **inputs, "r12_sample_id": row["sample_id"],
            "r12_prefix_path": row["input_prefix_file"], "r12_chart_sha256": row["chart_SHA"],
            "original_source_member": row["source_member"], "provenance": provenance,
            "source_to_judge_csv_byte_equal": raw == source, "native_raw_row_verify_count": len(values),
            "native_day_sha256": "|".join(hashes), "ohlcv_status": "FINITE_ORDERED_SOURCE_MATCH",
            "amount_numeric_status": "EXACT_TDX_RAW_TURNOVER_FIELD", "duplicate_trade_dates": 0, "post_D_rows": 0,
            "D_bar_present": True, "normal_exchange_sessions_missing_in_prefix": date_gaps,
            "exchange_calendar_official_sources": "|".join(sorted({NOTICES[market, day.year] for day in days
                                                                  if (market, day.year) in NOTICES})),
            "D_suspension_source_hint": raw_suspension or "UNKNOWN",
            "D_suspension_source_hint_meaning": "Source report only; no independent intraday/timed suspension proof",
            "asof_D_corporate_action_records": len(corporate_records), "corporate_action_ex_dates_inside_prefix": "|".join(in_window_actions),
            "corporate_action_evidence_scope": ("DATED_EVENT_ROWS_PUBLICATION_UNKNOWN" if corporate_records
                                                 else "NO_QUERY_BOUND_EVENT_ROWS_STATE_UNKNOWN"),
            "independent_judgment_status": "PENDING", "fit_eligible": False,
        })
    require(len(manifest) == len({(r["stable_security_id"], r["observation_date"]) for r in manifest}) == 64,
            "Frozen H1 scope or observation identity changed")
    manifest.sort(key=lambda x: x["sample_id"])
    audit.sort(key=lambda x: x["sample_id"])
    output = target / "INPUT_MANIFEST.csv"
    write_csv(output, tuple(manifest[0]), manifest)
    subprocess.run([str(args.chart_python), str(Path(__file__).resolve()), "--render", str(output)], check=True)
    by_id = {a["sample_id"]: a for a in audit}
    for sample in manifest:
        png = (target / sample["chart_file"]).read_bytes()
        require(png.startswith(b"\x89PNG\r\n\x1a\n") and len(png) > 10_000, f"Bad chart: {sample['sample_id']}")
        chart_sha = digest(png)
        sample["chart_sha256"] = chart_sha
        by_id[sample["sample_id"]]["chart_sha256"] = chart_sha
    write_csv(output, tuple(manifest[0]), manifest)
    write_csv(out / "H1_R1_3_INPUT_AUDIT.csv", tuple(audit[0]), audit)
    fields = ("sample_id", "judge_id", "label", "label_confidence", "evidence_tier",
              "evidence_observations", "counterevidence", "unknown_reason", "label_maturity_date", "judgment_timestamp")
    for letter in ("A", "B"):
        write_csv(target / f"INDEPENDENT_JUDGMENT_{letter}.csv", fields, [{"sample_id": r["sample_id"]} for r in manifest])
    (target / "README.md").write_text(JUDGE_README, encoding="utf-8")
    return audit


JUDGE_README = """# P5.15 H1 D-only 独立判卷材料

以 INPUT_MANIFEST.csv 的随机 sample_id 打开对应 inputs/ 与 charts/ 文件。CSV 是原始未复权 OHLCV 和原成交额字段，截至观察日 D 收盘。所有 64 条暴露状态为 EXPOSED_DEV。

A 和 B 各自使用本人的空白工作表，完成后分别提交。只依据 D 日及以前可见的结构，填写一个主标签、置信度、D 前证据、反证和未知原因。主标签字典沿用已交付的 H1 标注手册：BUILDUP_STRUCTURE_CANDIDATE、IGNITION、ADVANCE、TREND_CONSOLIDATION、HIGH_LEVEL_RISK、DISTRIBUTION_RISK_CANDIDATE、STRUCTURE_FAILURE、UNKNOWN。交易日历按交易所公告核对。停牌状态和公司行动时点仍未知。观察到机械跳变但无法区分原因时，在工作表登记具体不确定性。
"""


def input_report(args, audit, recovered, excluded, combined):
    number_sources = len({h for row in audit for h in row["native_day_sha256"].split("|")})
    exact = sum(row["source_to_judge_csv_byte_equal"] for row in audit)
    sessions = Counter(row["exchange_calendar_status"] for row in audit)
    markets = Counter(row["market"] for row in audit)
    observed_not_reported = sum(row["D_suspension_source_hint"] == "NO_REPORTED_SUSPENSION" for row in audit)
    action_observed = sum(bool(row["corporate_action_ex_dates_inside_prefix"]) for row in audit)
    missing_sessions = Counter(row["normal_exchange_sessions_missing_in_prefix"] for row in audit)
    chart = subprocess.check_output([str(args.chart_python), "-c", "import matplotlib; print(matplotlib.__version__)"], text=True).strip()
    report = f"""# P5.15 R1.3 H1 D-only 输入与 SUP_RAW 回执

## H1 对照审计

- R1.2 输入 {len(audit)} 条，{len({a['stable_security_id'] for a in audit})} 只证券，{len({a['observation_date'] for a in audit})} 个 D 日，沪 {markets['SH']}、深 {markets['SZ']}、北 {markets['BJ']}。每条 120 根 RAW 日线，合计 {sum(x['prefix_rows'] for x in audit):,} 行。证券键和观察日与原登记一致，证券主数据历史版本缺证。
- 全部 R1.2 交付 CSV 的实际字节 SHA 与其清单及 ZIP 成员哈希相符。{exact} 个 CSV 与 P5.14.8 原始成员逐字节相同。其余 {len(audit)-exact} 个历史对照以投影方式保留同样的日期、证券与全部 OHLCV/成交额数值。所有 {len(audit)} 个源成员按原 P5.14.8 清单重算 SHA，并逐行回对 {number_sources} 份冻结 TDX .day 原始字节和原记录索引。
- 价格为 TDX A/BJ 原记录价格整数除 100，人民币每股、未复权。证券、日期、OHLCV 与成交额按精确值检查，OHLC 合法、量额非负、日期严格递增，重复或 D 后数据均为 0。成交额与原 .day 浮点字段逐行相同，源语义为 RAW_TURNOVER，独立货币或金额比例单位认证保留 UNKNOWN。成交量保留 TDX 原字段单位。
- 交易所名义日历核对 {sessions['VERIFIED_EXCHANGE_SCHEDULE']}/{len(audit)} 个前缀，逐条日期均通过周末和公告休市检查。名义交易会话缺口及其样本数分布为 {dict(sorted(missing_sessions.items(), key=lambda item: str(item[0])))}，保留原始窗口。历史临时停牌或源缺行未独立证实。{observed_not_reported} 个 D 行原回溯源状态为 NO_REPORTED_SUSPENSION，全天或整个前缀的时点认证缺证。最终 suspension_status=UNKNOWN 为 {len(audit)} 条。
- 已存公司行动表以查询键和 ex_date 截止 D 核对。{action_observed} 个前缀窗口可见已存除权日历记录。历史发布时点、无事件时段完备性和因子版本缺证，64 条 corporate_action_pit_status=UNKNOWN。行业 PIT 为 UNKNOWN。D-only 裁剪与来源字节一致性审计均为回顾性证据。
- 重绘 64 同规格 PNG，严格使用已核 D-only CSV 和新随机 ID，以隔离旧图上印有的原版本标识。两个工作表均为空白，64 条为 EXPOSED_DEV，正式判卷、训练准入及拟合均为 0。审计 CSV 单独保留来源匹配，判卷目录仅含判卷所需文件。
- [上交所 2026 休市公告]({NOTICES['SH', 2026]}) · [深交所 2026 休市日历]({NOTICES['SZ', 2026]}) · [北交所 2026 休市公告]({NOTICES['BJ', 2026]}) · [深交所 2025 休市公告]({NOTICES['SZ', 2025]})

## SUP_RAW 补导

原 84 行 Mac 案例登记共 15 行标记 SUP_RAW，其中 14 行有有效 RAW。逐行绑定补充包原 SHA、原 Parquet 清单、原 DAILY_BARS_COVERAGE.csv、Mac 登记 SHA 以及实际 TDX 字节。恢复 {len(recovered)} 个独立 D 窗口，每个 251 行，共 {sum(r['prefix_rows'] for r in recovered):,} 行。完整保存证券、日期、OHLCV 与原成交额，逐个 CSV 回读并核对数值与 SHA。重复和 D 后行数均为 0。

排除项 {excluded[0][0]} 原 Parquet 有 {excluded[0][1]} 条日期占位，实际有效 RAW 为 0，原状态 {excluded[0][2]}。隔离其 QFQ 参考资料并登记缺口。其余已导出 14 条均为 RAW。

## 复现绑定

- 冻结 R1.2 ZIP SHA-256 {combined['r12_zip_sha256']}
- 冻结补充 ZIP SHA-256 {combined['supplement_sha256']}
- 原 DAILY_BARS_455.parquet 字节 SHA-256 {combined['raw_parquet_sha256']}
- 随机 ID 对照仅保存在本机受控 source_local/，SHA-256 {digest(args.id_registry.read_bytes())}
- 复核/导出解释器 Python {sys.version.split()[0]}，绘图使用既有实验 Python 中的 matplotlib {chart}。正式 fit、预测和 T+2 重算为 0。
"""
    (args.output / "H1_R1_3_INPUT_REPORT.md").write_text(report, encoding="utf-8")


def build(args):
    from tempfile import TemporaryDirectory

    final = args.output
    products = ("H1_R1_3_ADJUDICATION", "H1_R1_3_ADJUDICATION.zip", "H1_R1_3_INPUT_AUDIT.csv",
                "H1_R1_3_INPUT_REPORT.md", "SUP_RAW_14_EXPORTS", "SUP_RAW_14_EXPORT_MANIFEST.csv")
    require(all(not (final / path).exists() for path in products), "Existing frozen outputs will not be overwritten")
    raw_r12 = args.r12_archive.read_bytes()
    raw_sup = args.supplement_archive.read_bytes()
    raw_mac = args.casebook_archive.read_bytes()
    with TemporaryDirectory(prefix=".p515-adjudication-", dir=final) as path, \
            ZipFile(BytesIO(raw_r12)) as r12, ZipFile(BytesIO(raw_sup)) as sup, ZipFile(BytesIO(raw_mac)) as mac:
        args.output = Path(path)
        r12_shas = checksums(r12.read("SHA256SUMS.txt"))
        manifest = checked_member(r12, "", r12_shas, "COMMON_TRAINING_MANIFEST.json",
                                  digest(args.r12_manifest.read_bytes()))
        meta = json.loads(manifest)
        require(meta["delivery_version"] == "R1.2" and digest(raw_r12) == args.r12_archive_sha256,
                "Unverified R1.2 package")
        require(digest(raw_sup) == meta["common_data_source_archive"]["sha256"]
                and len(raw_sup) == meta["common_data_source_archive"]["bytes"], "Original supplement identity mismatch")
        require(digest(raw_mac) == meta["mac_local_registry_archive"]["sha256"]
                and len(raw_mac) == meta["mac_local_registry_archive"]["bytes"], "Mac original registry archive mismatch")
        _, h1 = csv_rows(checked_member(r12, "", r12_shas, "H1_DDAY_BLINDED_SAMPLE_MANIFEST.csv"))
        require(len(h1) == 64 and {r["sample_id"] for r in h1} == set(meta["sample_ids"]), "R1.2 sample identities differ")
        expected_files = {row["file"]: row["sha256"] for row in meta["file_sha256"]}
        for row in h1:
            path_csv = row["input_prefix_file"]
            path_png = path_csv.replace(".csv", ".png")
            require(expected_files[path_csv] == row["input_prefix_SHA"]
                    and expected_files[path_png] == row["chart_SHA"], "R1.2 manifest member check failed")
        mac_shas = checksums(mac.read("SHA256SUMS.txt"))
        casebook = checked_member(mac, "", mac_shas, "CASEBOOK_LOCAL_REGISTRY.csv")
        _, registers = csv_rows(casebook)
        registers = [row for row in registers if row["input_source_id"] == "SUP_RAW"]
        sup_roots = {name.split("/")[0] for name in sup.namelist() if not name.endswith("/")}
        require(len(sup_roots) == 1, "Expected one source archive root")
        source_prefix = next(iter(sup_roots)) + "/"
        sup_shas = checksums(sup.read(source_prefix + "SHA256SUMS.txt"))
        sup_manifest = checked_member(sup, source_prefix, sup_shas, "EXPORT_MANIFEST.json")
        digest_rows = {row["path"]: row for row in json.loads(sup_manifest)["files"]}
        source_parquet = checked_member(sup, source_prefix, sup_shas, "DAILY_BARS_455.parquet")
        source_coverage = checked_member(sup, source_prefix, sup_shas, "DAILY_BARS_COVERAGE.csv")
        for name, raw in (("DAILY_BARS_455.parquet", source_parquet), ("DAILY_BARS_COVERAGE.csv", source_coverage)):
            require(len(raw) == digest_rows[name]["bytes"] and digest(raw) == digest_rows[name]["sha256"],
                    f"Supplement export manifest differs on {name}")
        _, coverage_rows = csv_rows(source_coverage)
        coverage = {row["query_id"]: row for row in coverage_rows}
        require(len(coverage) == len(coverage_rows), "Duplicate raw coverage key")
        _, native_index = csv_rows(checked_member(sup, source_prefix, sup_shas, "RAW_SOURCE_FILES.csv"))
        native = NativeDaySources(native_index)
        ids = {f"{row['security_id']}_{row['D']}" for row in registers}
        ids |= {f"{row['stable_security_id']}_{row['D']}" for row in h1}
        parquet = load_parquet(source_parquet, ids)
        actions = checked_member(sup, source_prefix, sup_shas, "CORPORATE_ACTION_EVENTS_ASOF_D.csv")
        _, corporate_rows = csv_rows(actions)
        corp = defaultdict(list)
        for row in corporate_rows:
            if row["query_id"] in ids:
                require(row["ex_date"] <= row["D"] and row["query_id"] == f"{row['ts_code']}_{row['D']}",
                        f"Corporate action identity/date conflict: {row['query_id']}")
                corp[row["query_id"]].append(row)
        sources = {
            "r12_zip_sha256": args.r12_archive_sha256, "r12_manifest_sha256": digest(manifest),
            "supplement_sha256": digest(raw_sup), "raw_parquet_sha256": digest(source_parquet),
            "supplement_manifest_sha256": digest(sup_manifest), "supplement_coverage_sha256": digest(source_coverage),
            "casebook_archive_sha256": digest(raw_mac), "casebook_sha256": digest(casebook),
            "corporate_action_source_sha256": digest(actions),
        }
        recovered, excluded = export_sup_raw(args.output, registers, parquet, coverage, sources, native)
        audit = export_h1(args, h1, r12, r12_shas, sup, source_prefix, sup_shas, parquet, corp, native, sources)
        input_report(args, audit, recovered, excluded, sources)
        make_archive(args.output / products[0], args.output / products[1])
        for filename in products:
            (args.output / filename).rename(final / filename)
    print(f"H1 audit {len(audit)}; SUP_RAW {len(recovered)}; adjudication ZIP {digest((final / products[1]).read_bytes())}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", type=Path, help="Internal chart-only entry point")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--r12-manifest", type=Path)
    parser.add_argument("--r12-archive", type=Path)
    parser.add_argument("--r12-archive-sha256")
    parser.add_argument("--supplement-archive", type=Path)
    parser.add_argument("--casebook-archive", type=Path)
    parser.add_argument("--chart-python", type=Path)
    parser.add_argument("--id-registry", type=Path)
    args = parser.parse_args()
    if args.render:
        render_charts(args.render)
    else:
        required = ("output", "r12_manifest", "r12_archive", "r12_archive_sha256", "supplement_archive",
                    "casebook_archive", "chart_python", "id_registry")
        if any(getattr(args, name) is None for name in required):
            parser.error("Supply all build options, or --render")
        build(args)


if __name__ == "__main__":
    main()
