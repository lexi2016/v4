"""Freeze ACT039A D-only RET and indexed PRODUCT pools against ACT038A."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path
import resource
from time import perf_counter

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ops import pft_act031_frozen_forward as a31
from ops import pft_act033a_groups as groups
from ops import pft_act033a_replay as a33
from ops import pft_act034a_replay as a34
from ops import pft_act034a_rules as r34
from ops import pft_act035a_features as f35
from ops import pft_act035a_replay as a35
from ops import pft_act036a_inputs as a36
from ops import pft_act038a_export as a38

ROOT = a35.ROOT
OUT = ROOT / "pft_act039a_top200_20261125"
OLD = ROOT / "pft_act038a_oos_export_20261124"
SEAL = "TOP200_SELECTION_SEAL.json"
JOINED = "TOP200_JOINED_INPUT.parquet"
SCHEMA = "pft.act039a.d_rank_and_projection.v1"
FIRST, LAST, OBS_CUTOFF = "20260901", "20261120", "20261123"
TOP_N = 200
RET, PRODUCT = "TOP200_RET", "TOP200_PRODUCT"
EXPECTED_PRODUCT_DAYS = (
    "20261030", "20261104", "20261105", "20261106", "20261109", "20261110", "20261111",
    "20261112", "20261113", "20261116", "20261117", "20261118", "20261119", "20261120",
)
MASTER = {"path": str(OLD / "SV3_FROZEN_OOS_EXPORT_MANIFEST.json"),
          "sha256": "e5d04b33bfd7e87318fd3a6c858bab134994c7e6ca11599d6cedb0f600316c58"}
OLD_LOCKS = (
    ("SV3_FROZEN_OOS_EXPORT_202609.parquet", "b7f4fb3e06718291313b80a4d87a023a96c19bb2f273bd698a037e7df979ae99", 121583, 6364466),
    ("SV3_FROZEN_OOS_EXPORT_202610.parquet", "4307bee895f057e695c8af9ed58cfcb78807da33afac614f69809bad20987973", 98683, 4852731),
    ("SV3_FROZEN_OOS_EXPORT_202611.parquet", "2fa3f5c56bf13e3dbe3c618ab412cdce6751359e37039694a8f215e749206830", 86543, 4220636),
)
OLD_PREDICTION_SEAL_SHA = "c482bbe36f1d7ce39146f1084c7137fb56b357fb443286400849ab8a54f60ace"
CHART_COLS = ("open", "high", "low", "close", "pre_close", "vol", "amount", "tradeable_basic")
RET_SOURCE = "V4_D_QFQ_CLOSE_OVER_PRE_CLOSE"
PRODUCT_SOURCE = "V4_OWNER_INDEXED_IMMUTABLE_TOP200_PRODUCT"
BOARDS = ("MAIN_60_00", "CHINEXT", "STAR", "BJ")
CHINEXT_PREFIXES = ("300", "301", "302")
CHINEXT_302_SOURCE = "https://disc.static.szse.cn/download/disc/disk03/finalpage/2025-02-15/cedb693a-f5ee-4463-9682-ea33d406b569.PDF"
JOIN_FIELDS = (
    pa.field("pool", pa.string(), nullable=False),
    pa.field("D_rank", pa.int16(), nullable=False),
    pa.field("D_return", pa.float64(), nullable=False),
    pa.field("D_return_source", pa.string(), nullable=False),
    pa.field("board", pa.string(), nullable=False),
    pa.field("D_close", pa.float64()),
    pa.field("D_pre_close", pa.float64()),
    pa.field("D_close_official_alignment", pa.bool_()),
    pa.field("D_pre_close_official_alignment", pa.bool_()),
    pa.field("D_is_st", pa.bool_()),
    pa.field("D_st_source", pa.string(), nullable=False),
    pa.field("D_upper_band_fraction", pa.float64()),
    pa.field("D_upper_cap_yuan", pa.float64()),
    pa.field("D_close_at_upper_cap", pa.bool_()),
    pa.field("D_cap_status", pa.string(), nullable=False),
    pa.field("prediction_join_status", pa.string(), nullable=False),
)
POLICY = {
    RET: "Exact D V4 backtest bars, price plus pre-close returned to D QFQ basis by backward removal of events strictly after D. Valid raw-tradeability field, finite positive coherent OHLC/previous close, positive volume and raw amount. All valid A-share keys incl ST. Rank by unrounded binary64 close/pre_close - 1 descending, then exchange-qualified code ascending. Freeze 200 per date.",
    PRODUCT: "Only existing authoritative V4 daily_products/a_share/index.json top200[date] entries, checked against frozen rank ref, immutable physical inventory, dated official package and numeric manifest. Keep published rank and return. Alternative immutable variants remain inventoried; no fallback to RET or newer file.",
    "join": "Each pool is LEFT by exact (trade_date yyyyMMdd, ts_code) to unaltered ACT038A 40-column predictions. Keep unmatched pool rows with null forecast fields, distinct from any matched forecast state.",
    "board": "MAIN_60_00 (60.SH and 00.SZ), CHINEXT (300/301/302.SZ), STAR (688/689.SH) and BJ.",
    "D_st": "Exact dated official name when available; otherwise null. No reconstruction from another date.",
    "D_cap": "D closing proxy under frozen standard board rule, half-up to one cent. Main-board known ST uses the same 10% within the frozen post-July-6 interval. Known off-main ST has unconfirmed band. D raw official market inputs preferred; absent official data, diagnostic D-rebased QFQ inputs and nominal band only. At-cap share reports a known denominator.",
    "outcome": "No D+1/D+h outcome access in this stage. Authorized observation cutoff for downstream evaluation 20261123.",
}


def require(ok, reason):
    if not ok:
        raise a31.ContractError(f"ACT039A_INPUT_{reason}")


@dataclass
class Frozen:
    manifest: dict
    files: list
    dates: list
    forecast: pa.Table
    sources: dict
    source_ref: dict
    reader: a36.Reader
    product_root: Path
    index: dict
    index_ref: dict


def load_frozen():
    master = a31.read_ref(MASTER)
    require(master["schema"] == "pft.sv3.oos_53d_export_manifest.v1"
            and master["model_version"] == "S_V3.0_FROZEN" and master["model_commit"] == "fc528d9da0d6"
            and master["train_cutoff_date"] == "20260831" and master["market"] == "A_SHARE"
            and master["primary_key"] == ["trade_date", "ts_code"] and master["signal_days"] == 53
            and master["min_D"] == FIRST and master["max_D"] == LAST and master["observation_cutoff"] == OBS_CUTOFF
            and master["prediction_seal_sha256"] == OLD_PREDICTION_SEAL_SHA
            and all(master[name] == value for name, value in a31.FLAGS.items()), "FORECAST_SCOPE_OR_MODEL_DRIFT")
    dates = master["oot_early"] + master["dev_21d"]
    calendar = f35.exchange_days(a31.act028.ExchangeSessions().schedule)
    require(dates == calendar[calendar.index(FIRST):calendar.index(LAST) + 1]
            and len(master["oot_early"]) == 32 and len(master["dev_21d"]) == 21, "FORECAST_DATE_CALENDAR_DRIFT")
    refs, frames = [], []
    fields = [(item["name"], item["arrow_type"], item["nullable"]) for item in master["field_dictionary"]]
    declared_shards = [row for row in master["files"] if row["name"].endswith(".parquet")]
    require(len(declared_shards) == len(OLD_LOCKS) == 3 and len(fields) == 40, "FORECAST_MANIFEST_FILE_SCHEMA_DRIFT")
    for row, lock in zip(declared_shards, OLD_LOCKS, strict=True):
        name, sha, size, nbytes = lock
        require((row["name"], row["sha256"], row["rows"], row["bytes"]) == (name, sha, size, nbytes),
                f"FORECAST_SHARD_LITERAL_DRIFT:{name}")
        ref = {"path": str(OLD / name), "sha256": sha, "rows": size, "bytes": nbytes, "dates": row["dates"]}
        path = a33.checked(ref)
        require(path.stat().st_size == nbytes, f"FORECAST_SHARD_BYTES_DRIFT:{name}")
        table = pq.read_table(path)
        require([(field.name, str(field.type), field.nullable) for field in table.schema] == fields
                and table.num_rows == size and sorted(set(table["trade_date"].to_pylist())) == row["dates"],
                f"FORECAST_SHARD_CONTENT_DRIFT:{name}")
        a38.require_table(table, row["dates"])
        refs.append(ref)
        frames.append(table)
    require([day for item in refs for day in item["dates"]] == dates, "FORECAST_DATE_PARTITION_DRIFT")
    forecast = pa.concat_tables(frames)
    keys = list(zip(forecast["trade_date"].to_pylist(), forecast["ts_code"].to_pylist(), strict=True))
    require(len(keys) == len(set(keys)) == 306809, "FORECAST_UNIVERSE_KEY_OR_SIZE_DRIFT")
    for name, expected in (("model_version", master["model_version"]), ("model_commit", master["model_commit"]),
                           ("train_cutoff_date", master["train_cutoff_date"]), ("is_strict_oos_post_cutoff", True)):
        require(pc.all(pc.equal(forecast[name], expected)).as_py() is True and forecast[name].null_count == 0,
                f"FORECAST_VALUE_DRIFT:{name}")
    inputs, _, source_ref, _ = a34.load_seal(ROOT / "pft_act033a_s_v3_20261124")
    backtest = master["signal_reader"]["backtest"]
    require(inputs["days"][LAST] == backtest, "V4_READER_FROZEN_INPUT_DRIFT")
    bound, symbols, info = f35.bind(backtest)
    require(info == master["signal_reader"], "V4_READER_FREEZE_DRIFT")
    reader = a36.Reader(bound, symbols, LAST, info)
    numeric_path = a33.checked(backtest["numeric_manifest_ref"])
    root = numeric_path.parents[4]
    require(root.name == "a_share" and root.parent.name == "daily_products"
            and (root / "top200").is_dir(), "V4_PRODUCT_ROOT_IDENTITY")
    index_ref = a31.ref(root / "index.json")
    index = a31.read_ref(index_ref)
    require(index["dates"].get(LAST) == backtest["numeric_manifest_ref"], "V4_PRODUCT_INDEX_CURRENT_DATE_DRIFT")
    return Frozen(master, refs, dates, forecast, inputs["days"], source_ref, reader, root, index, index_ref)


def board_for(code):
    if groups.main_board(code):
        return "MAIN_60_00"
    if code.endswith(".SZ") and code.startswith(CHINEXT_PREFIXES):
        return "CHINEXT"
    if code.endswith(".SH") and code.startswith(("688", "689")):
        return "STAR"
    if code.endswith(".BJ"):
        return "BJ"
    raise a31.ContractError(f"ACT039A_UNBOUND_A_BOARD:{code}")


def d_cap(code, ohlc, official, is_st):
    chosen = official if official else ohlc
    evidence = "OFFICIAL" if official else "V4_REBASED_QFQ_DIAGNOSTIC"
    if official and not official["eligible_for_daily_gain_rank"]:
        return None, None, None, "OFFICIAL_D_QUOTE_INVALID_OR_ZERO_VOLUME"
    if is_st is True and not groups.main_board(code):
        return None, None, None, "KNOWN_D_ST_NONMAIN_BAND_UNCONFIRMED"
    band = "0.20" if board_for(code) == "CHINEXT" else a31.inferred_band(code)
    prev = a31.positive(chosen.get("prev_close"))
    high, low, close = (a31.positive(chosen.get(key)) for key in ("high", "low", "close"))
    if band is None or None in (prev, high, low, close):
        return None, None, None, f"{evidence}_D_CAP_INPUT_UNKNOWN"
    upper = r34.cap_price(prev, 1 + Decimal(band))
    lower = r34.cap_price(prev, 1 - Decimal(band))
    if high > upper + 1e-6 or low < lower - 1e-6:
        return float(band), upper, None, f"{evidence}_STANDARD_BAND_EXCEPTION"
    return float(band), upper, abs(close - upper) <= 1e-6, f"{evidence}_STANDARD_BOARD_CLOSE_PROXY"


def d_evidence(code, values, quote):
    is_st = a31.special_treatment(quote.get("name")) if quote else None
    band, cap, closed, status = d_cap(code, values, quote, is_st)
    independent = bool(quote and quote["eligible_for_daily_gain_rank"])
    close = a31.positive(values.get("close"))
    prev = a31.positive(values.get("prev_close"))
    raw_close = a31.positive(quote.get("close")) if independent else None
    raw_prev = a31.positive(quote.get("prev_close")) if independent else None
    return {
        "board": board_for(code), "D_close": close, "D_pre_close": prev,
        "D_close_official_alignment": r34.same_price(close, raw_close) if None not in (close, raw_close) else None,
        "D_pre_close_official_alignment": r34.same_price(prev, raw_prev) if None not in (prev, raw_prev) else None,
        "D_is_st": is_st, "D_st_source": "EXACT_D_OFFICIAL_TDX_NAME" if is_st is not None else "D_ST_STATUS_UNAVAILABLE",
        "D_upper_band_fraction": band, "D_upper_cap_yuan": cap, "D_close_at_upper_cap": closed,
        "D_cap_status": status,
    }


def rank_ret(day, direct, basis, quotes):
    rebased, rebuild = basis.prefix(direct, day, day)
    ranked, omitted = [], Counter()
    for row in rebased.itertuples(index=False):
        code = row.ts_code
        if (row.tradeable_basic != 1 or a31.positive(row.vol) is None or a31.positive(row.amount) is None):
            omitted["NOT_VALID_TRADEABILITY_OR_ACTIVITY"] += 1
            continue
        o, h, low, close, prev = (a31.positive(v) for v in (row.open, row.high, row.low, row.close, row.pre_close))
        if None in (o, h, low, close, prev) or not low <= min(o, close) <= max(o, close) <= h:
            omitted["INVALID_D_BASIS_OHLC_OR_PRECLOSE"] += 1
            continue
        rated = {"open": o, "high": h, "low": low, "close": close, "prev_close": prev}
        ranked.append((close / prev - 1., code, rated))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    require(len(ranked) >= TOP_N, f"RET_FEWER_THAN_200_VALID_D_ROWS:{day}")
    cutoff = ranked[TOP_N - 1][0]
    records = [{"trade_date": day, "ts_code": code, "D_rank": pos, "pool": RET, "D_return": result,
                "D_return_source": RET_SOURCE, **d_evidence(code, detail, quotes.get(code))}
               for pos, (result, code, detail) in enumerate(ranked[:TOP_N], 1)]
    audit = {
        "reader_D_rows": len(direct), "rankable_A_n": len(ranked), "D_basis": rebuild, "omitted": dict(omitted),
        "cutoff_raw_fraction": cutoff, "exact_tie_seen_n": sum(result == cutoff for result, _, _ in ranked),
        "exact_tie_kept_n": sum(row["D_return"] == cutoff for row in records),
        "rank1_raw_fraction": records[0]["D_return"],
    }
    audit["all_rankable_official_valid_n"] = sum(quotes.get(code, {}).get("eligible_for_daily_gain_rank") is True
                                                for _, code, _ in ranked)
    audit["all_rankable_official_close_aligned_n"] = sum(
        q.get("eligible_for_daily_gain_rank") is True
        and r34.same_price(inputs["close"], a31.positive(q.get("close")))
        for _, code, inputs in ranked for q in [quotes.get(code, {})])
    audit["all_rankable_official_prev_close_aligned_n"] = sum(
        q.get("eligible_for_daily_gain_rank") is True
        and r34.same_price(inputs["prev_close"], a31.positive(q.get("prev_close")))
        for _, code, inputs in ranked for q in [quotes.get(code, {})])
    return records, audit


def product_pool(day, frozen, quote_set):
    folder = frozen.product_root / "top200" / day
    physical = sorted(folder.glob("*/top200.json")) if folder.is_dir() else []
    inventory = []
    for path in physical:
        require(path.is_file() and not path.is_symlink() and path.resolve(strict=True) == path,
                f"UNSAFE_LOCAL_PRODUCT_VARIANT:{day}:{path.name}")
        inventory.append(a31.ref(path))
    authority = frozen.index["top200"].get(day)
    frozen_rank = frozen.sources.get(day, {}).get("rank_ref")
    evidence = {"inventory_variants": inventory, "owner_index_current_rank": authority,
                "frozen_rank_reference": frozen_rank, "in_scope_local_variant_count": len(inventory)}
    if authority is None:
        return [], evidence | {"status": "CANNOT_CONFIRM_UNINDEXED_PRODUCT" if inventory else "NOT_LANDED_FOR_D"}
    require(authority in inventory, f"OWNER_INDEX_PRODUCT_PATH_OR_SHA_DRIFT:{day}")
    if authority != frozen_rank:
        return [], evidence | {"status": "CANNOT_CONFIRM_OWNER_AND_FROZEN_RANK_REFERENCE_CONFLICT"}
    payload = a31.read_ref(authority)
    source = frozen.sources[day]
    ranks, rank_source = a31.rank_for_day(day, source, quote_set)
    numeric_ref = payload["numeric_manifest"]
    require(rank_source == "V4_OFFICIAL_TOP200" and len(ranks) == TOP_N
            and payload["top200_count"] == TOP_N and numeric_ref == frozen.index["dates"].get(day),
            f"DATED_PRODUCT_NUMERIC_POINTER_DRIFT:{day}")
    numeric = a31.read_ref(numeric_ref)
    require(numeric["data_date"] == day and numeric["source_generation"] == payload["source_generation"]
            and numeric["input_sha256"] == payload["input_sha256"]
            and payload["official_input"] == source["official_ref"], f"PRODUCT_OWNER_SOURCE_DRIFT:{day}")
    records = []
    for saved in sorted(payload["top200"], key=lambda row: row["rank"]):
        code = saved["symbol"]
        quote = quote_set.get(code)
        pub = groups.finite(saved.get("change_pct"))
        require(pub is not None and quote and quote["eligible_for_daily_gain_rank"]
                and abs(pub - quote["change_pct"]) < 1e-10 and ranks[code] == saved["rank"],
                f"DATED_PRODUCT_QUOTE_OR_PUBLISHED_RANK_DRIFT:{day}:{code}")
        require(all(r34.same_price(a31.positive(saved.get(k)), a31.positive(quote.get(k)))
                    for k in ("close", "prev_close")), f"DATED_PRODUCT_PUBLISHED_PRICE_DRIFT:{day}:{code}")
        records.append({"trade_date": day, "ts_code": code, "pool": PRODUCT, "D_rank": saved["rank"],
                        "D_return": pub / 100., "D_return_source": PRODUCT_SOURCE, **d_evidence(code, quote, quote)})
    return records, evidence | {
        "status": "OWNER_AND_FROZEN_AUTHORITIES_MATCH", "numeric_manifest": numeric_ref,
        "official_package": payload["official_package"], "rank_source": rank_source,
        "authoritative_physical_ref": authority, "alternate_variants": [x for x in inventory if x != authority],
    }


def proof_counts(rows):
    count = len(rows)
    known_at_cap = sum(r["D_close_at_upper_cap"] is not None for r in rows)
    at_cap = sum(r["D_close_at_upper_cap"] is True for r in rows)
    return {
        "members": count, "board_counts": dict(Counter(r["board"] for r in rows)),
        "dated_st_true": sum(r["D_is_st"] is True for r in rows),
        "dated_st_false": sum(r["D_is_st"] is False for r in rows),
        "dated_st_unknown": sum(r["D_is_st"] is None for r in rows),
        "D_close_at_upper_cap_true": at_cap, "D_close_at_upper_cap_known": known_at_cap,
        "D_close_at_upper_cap_fraction": at_cap / known_at_cap if known_at_cap else None,
        "D_close_at_upper_cap_unknown": count - known_at_cap, "D_cap_sources": dict(Counter(r["D_cap_status"] for r in rows)),
        "D_official_close_aligned_n": sum(r["D_close_official_alignment"] is True for r in rows),
        "D_official_close_disagrees_n": sum(r["D_close_official_alignment"] is False for r in rows),
        "D_official_preclose_aligned_n": sum(r["D_pre_close_official_alignment"] is True for r in rows),
        "D_official_preclose_disagrees_n": sum(r["D_pre_close_official_alignment"] is False for r in rows),
    }


def build_pools(frozen, dates):
    require(dates and dates == sorted(set(dates)) and set(dates) <= set(frozen.dates), "D_READER_REQUEST_SCOPE")
    full_range = frozen.dates[frozen.dates.index(dates[0]):frozen.dates.index(dates[-1]) + 1]
    if dates == full_range:
        projected = a36.read_history(frozen.reader, dates[0], dates[-1], columns=CHART_COLS)
    else:
        projected = pd.concat([a36.read_history(frozen.reader, day, day, columns=CHART_COLS)
                               for day in dates], ignore_index=True)
    require(set(projected.trade_date.unique()) == set(dates), "D_READER_MISSING_DATE")
    bound = {"bounds": [dates[0], dates[-1]], "rows": len(projected), "symbols": int(projected.ts_code.nunique()),
             "materialized_memory_bytes": int(projected.memory_usage(index=True, deep=True).sum())}
    basis = a36.Basis(frozen.reader)
    rows, daily = [], {}
    for day, frame in projected.groupby("trade_date", sort=True):
        quotes, proof = a31.day_quotes(day, frozen.sources.get(day, {}))
        quotes = quotes or {}
        ret, ret_proof = rank_ret(day, frame, basis, quotes)
        product, inventory = product_pool(day, frozen, quotes)
        prior_scope = {r["ts_code"] for r in product}
        daily[day] = {
            "official_D_quote_source": proof, "official_D_quote_count": len(quotes),
            "official_D_valid_A_quote_count": sum(q["eligible_for_daily_gain_rank"] is True for q in quotes.values()),
            RET: ret_proof | proof_counts(ret),
            PRODUCT: inventory | proof_counts(product),
            "RET_PRODUCT_overlap": sum(r["ts_code"] in prior_scope for r in ret) if product else None,
        }
        rows.extend(ret)
        rows.extend(product)
    return rows, daily, bound


def left_exact(forecast, rows):
    keys = list(zip(forecast["trade_date"].to_pylist(), forecast["ts_code"].to_pylist(), strict=True))
    original = {key: idx for idx, key in enumerate(keys)}
    require(len(original) == len(keys), "LEFT_JOIN_DUPLICATE_RIGHT_KEY")
    distinct = {(r["pool"], r["trade_date"], r["ts_code"]) for r in rows}
    require(len(distinct) == len(rows), "LEFT_JOIN_DUPLICATE_POOL_KEY")
    positions = [original.get((r["trade_date"], r["ts_code"])) for r in rows]
    picked = pc.take(forecast, pa.array(positions, type=pa.int64()))
    have_unmatched = any(pos is None for pos in positions)
    mutable = {"trade_date", "ts_code"}
    fields, cols, promoted = [], [], []
    for field in forecast.schema:
        if have_unmatched and field.name not in mutable and not field.nullable:
            promoted.append(field.name)
            field = field.with_nullable(True)
        fields.append(field)
        cols.append(pa.array([r[field.name] for r in rows], type=field.type) if field.name in mutable else picked[field.name])
    for col in JOIN_FIELDS:
        fields.append(col)
        if col.name == "prediction_join_status":
            cols.append(pa.array(["MATCHED" if p is not None else "UNMATCHED" for p in positions], type=col.type))
        else:
            cols.append(pa.array([r[col.name] for r in rows], type=col.type))
    schema = pa.schema(fields, metadata={**(forecast.schema.metadata or {}), b"join_schema_id": SCHEMA.encode()})
    joined = pa.Table.from_arrays(cols, schema=schema)
    matched = [i for i, pos in enumerate(positions) if pos is not None]
    original_values = pc.take(forecast, pa.array([positions[i] for i in matched], type=pa.int64()))
    actual_values = pc.take(joined.select(forecast.column_names), pa.array(matched, type=pa.int64()))
    # Table.equals checks order, values, data types and exact null positions.
    # Nullability can only be loosened when carrying a truly unmatched row.
    comparable = pa.Table.from_arrays([actual_values[n] for n in forecast.column_names], schema=forecast.schema)
    require(comparable.equals(original_values, check_metadata=True), "LEFT_JOIN_ORIGINAL_FORECAST_VALUE_OR_TYPE_CHANGED")
    loc = Counter((r["pool"], r["trade_date"], pos is not None) for r, pos in zip(rows, positions, strict=True))
    return joined, loc, promoted


def finish_coverage(days, joins):
    for day, row in days.items():
        for pool in (RET, PRODUCT):
            known, missing = joins[pool, day, True], joins[pool, day, False]
            require(known + missing == row[pool]["members"], f"LEFT_JOIN_POOL_DENOMINATOR_DRIFT:{day}:{pool}")
            row[pool] |= {"forecast_matched_n": known, "forecast_unmatched_n": missing}


def immutable_parquet(path, joined):
    sink = pa.BufferOutputStream()
    pq.write_table(joined, sink, compression="zstd", compression_level=8, use_dictionary=True)
    payload = sink.getvalue().to_pybytes()
    require(0 < len(payload) <= 9_500_000, "JOINED_D_ARTIFACT_CAP")
    temp = path.with_name(f".{path.name}.{os.getpid()}.pending")
    try:
        with temp.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        proof = pq.read_table(temp)
        require(proof.equals(joined, check_metadata=True), "JOINED_D_ARTIFACT_READBACK_DRIFT")
        if path.exists():
            require(path.read_bytes() == payload, "JOINED_D_EXISTING_BYTES_CONFLICT")
        else:
            temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    dates = sorted(set(joined["trade_date"].to_pylist()))
    return a31.ref(path) | {"rows": joined.num_rows, "columns": joined.num_columns,
                          "bytes": path.stat().st_size, "dates": dates}


def seal():
    start = perf_counter()
    frozen = load_frozen()
    prepared = perf_counter()
    rows, daily, projection = build_pools(frozen, frozen.dates)
    accepted = tuple(day for day, value in daily.items() if value[PRODUCT]["members"] == TOP_N)
    require(accepted == EXPECTED_PRODUCT_DAYS and len(rows) == TOP_N * (len(frozen.dates) + len(accepted)),
            "POOL_EXPECTED_OFFICIAL_DATE_COVERAGE_DRIFT")
    require(a31.ref(Path(frozen.index_ref["path"])) == frozen.index_ref, "OWNER_INDEX_MOVED_DURING_D_PROJECTION")
    ranked = perf_counter()
    joined, joins, promoted = left_exact(frozen.forecast, rows)
    finish_coverage(daily, joins)
    ref = immutable_parquet(OUT / JOINED, joined)
    computed = perf_counter()
    require(a31.ref(Path(frozen.index_ref["path"])) == frozen.index_ref, "OWNER_INDEX_MOVED_BEFORE_SEAL")
    proof = {
        "schema": SCHEMA, "phase": "TOP200_SELECTION_SEALED", "outcomes_opened": False,
        "signal_dates": frozen.dates, "cutoff": OBS_CUTOFF,
        "oot_dates": frozen.manifest["oot_early"], "dev_dates": frozen.manifest["dev_21d"],
        "original_forecast_manifest": MASTER, "original_forecast_files": frozen.files,
        "original_forecast_rows": frozen.forecast.num_rows, "original_forecast_column_order": frozen.forecast.column_names,
        "original_forecast_nullable_promotion_for_unmatched": promoted,
        "original_matched_values_verified": True, "files": [ref], "d_join_file": ref,
        "model_version": frozen.manifest["model_version"], "model_commit": frozen.manifest["model_commit"],
        "train_cutoff_date": frozen.manifest["train_cutoff_date"],
        "ret_dates": frozen.dates, "product_dates": list(accepted),
        "product_without_rank_dates": [d for d in frozen.dates if d not in accepted],
        "daily_coverage": daily, "owner_product_index_source": frozen.index_ref,
        "frozen_ACT033A_sources": frozen.source_ref, "V4_D_ret_reader": frozen.reader.identity,
        "policy": POLICY, "SZSE_302_board_evidence": CHINEXT_302_SOURCE, "code": a31.ref(Path(__file__).resolve()),
        "preseal_failure": (a31.ref(OUT / "D_INPUT_PRESEAL_FAILURE.json")
                            if (OUT / "D_INPUT_PRESEAL_FAILURE.json").exists() else None),
        "fit_count": 0, "predict_count": 0, "tuning_count": 0, "model_load_count": 0,
        "historical_PIT": "CANNOT_CONFIRM",
        "runtime": {"cores": os.cpu_count(), "arrow_threads": pa.cpu_count(), "worker_processes": 1,
                    "source_open_and_identity_seconds": prepared - start, "D_ranks_and_product_seconds": ranked - prepared,
                    "join_and_parquet_seconds": computed - ranked, "wall_seconds_before_seal": computed - start,
                    "parent_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                    "V4_D_projection": projection, "known_input_parquet_file_bytes": sum(item["bytes"] for item in frozen.files),
                    "known_join_parquet_written_bytes": ref["bytes"], "physical_read_write_bytes": "CANNOT_CONFIRM",
                    "upload_bytes": 0}, **a31.FLAGS,
    }
    return a31.json_atomic(OUT / SEAL, proof)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-frozen", action="store_true", required=True)
    parser.parse_args(argv)
    pa.set_cpu_count(min(8, os.cpu_count() or 1))
    with a31.exclusive_run(OUT / "inputs_lock"):
        require(not (OUT / SEAL).exists(), "D_SELECTION_ALREADY_SEALED")
        receipt = seal()
    print("TOP200_SELECTION_SEALED", receipt["sha256"], flush=True)


if __name__ == "__main__":
    main()
