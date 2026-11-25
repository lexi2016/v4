"""Build a private, time-causal ACT-048A event cache from sealed D-only shards."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import struct
import time
from zipfile import ZipFile

from ops import act044a_kb47_qualification as qualification
from ops import act046a_kb47_event_skeleton as skeleton
from ops import act047a_kb47_audit as audit

WORKERS = 10
ARROW_THREADS = 2
N = 60
OLD = "ACT041A_D_SIGNALS_"
NEW = "ACT043A_V11_SIGNAL_PROJECTION_"
CODE_BUNDLE = "f382c43ee3574e615e40cc0f84ef1a8616969d5bcb6216986adc09f4324daa83"
PRICE = dict(zip(
    ("open", "high", "low", "close", "pre_close", "white", "yellow", "bbi", "atr14", "dif", "dea", "hist"),
    ("D_open", "D_high", "D_low", "D_close", "D_pre_close", "D_zge_white_line", "D_zge_yellow_line",
     "D_BBI", "atr14", "D_macd_dif", "D_macd_dea", "D_macd_hist"),
))
BASE = (*audit.KEYS, *PRICE.values(), "D_raw_volume", "D_bar_state", "ratio_formula_bars_in_segment",
        "D_ratio_hfq_segment", "D_return", "board", "board_epoch", "D_J", "D_K", "D_KDJ_D",
        "user_v1_breakout", "prior_active_anchor_date", "prior_active_anchor_low",
        "prior_active_anchor_close_broken", "prior_active_anchor_reclaim", "active_anchor_date",
        "upper_wick_fraction", *(f"kb_{m:02}" for m in audit.ORIG_BUY))
V11 = (*audit.KEYS, *(f"v11_{m:02}" for m in audit.L1))
PRIVATE_ENV = {}
require = audit.require
positive = audit.positive


def file_sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def private_dir(path):
    path = Path(path)
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
    require(path.is_dir() and not path.is_symlink() and path.stat().st_mode & 0o077 == 0,
            "PRIVATE_DIRECTORY_MUST_BE_OWNER_ONLY")
    return path


def private_write(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        f.write(data)


def finite(value):
    return float(value) if value is not None and math.isfinite(value) else None


def divide(num, denom):
    return num / denom if num is not None and positive(denom) else None


def minus(l, r):
    return l - r if l is not None and r is not None else None


def market_calendar(ref, cutoff):
    # Same two sealed index-date members and owner 2026 calendar as ACT-041A.
    p = Path(ref["archive"]["path"])
    require(file_sha(p) == ref["archive"]["sha256"], "CALENDAR_ARCHIVE_SHA")
    dates = set()
    with ZipFile(p) as z:
        for member, expected in ref["members"].items():
            data = z.read(member)
            require(hashlib.sha256(data).hexdigest() == expected and len(data) % 32 == 0,
                    "CALENDAR_MEMBER_SHA")
            session_days = [d[0] for d in struct.iter_unpack("<I28x", data)]
            require(session_days == sorted(set(session_days)) and session_days[-1] == 20261019,
                    "INDEX_DATE_SEQUENCE")
            dates.update(session_days)
    path = Path(ref["exchange"]["path"])
    require(file_sha(path) == ref["exchange"]["sha256"], "EXCHANGE_CALENDAR_SHA")
    config = json.loads(path.read_bytes())
    pattern = config["markets"]["a_share"]["holiday_periods"]
    from datetime import date, timedelta

    closed = [(int(x["start"]), int(x["end"])) for x in pattern]
    next_day, end = date(2026, 1, 1), date(2026, 11, 24)
    scheduled = []
    while next_day <= end:
        n = int(next_day.strftime("%Y%m%d"))
        if next_day.weekday() < 5 and not any(a <= n <= b for a,b in closed):
            scheduled.append(n)
        next_day += timedelta(days=1)
    require([d for d in scheduled if d <= 20261019] == sorted(d for d in dates if d >= 20260101),
            "CALENDAR_OVERLAP")
    dates.update(d for d in scheduled if d > 20261019)
    require(max(dates) == cutoff, "CALENDAR_CUTOFF")
    return dict((d, i) for i, d in enumerate(sorted(dates)))


def bound(root):
    reads = audit.Reads()
    info = json.loads(reads.bytes(root / audit.A41 / "ACT041A_D_SIGNAL_SEAL.json"))
    rules = json.loads(reads.bytes(root / audit.A43 / "ACT043A_RUN_RECEIPT.json"))
    require(info["phase"] == "D_SIGNAL_SEALED" and info["outcomes_opened"] is False and
            rules["phase"] == "D_ONLY_RUN_COMPLETE" and rules["panel_outcomes_opened"] == 0,
            "D_ONLY_PHASE")
    old = reads.info(root / audit.A41, info["files"], OLD)
    new = reads.info(root / audit.A43, rules["overlay"]["files"], NEW)
    b0, b1 = audit.custodian(reads, root)
    bundle = reads.bytes(root / audit.A46 / "ACT046A_CODE_AND_TESTS_20261125.zip", CODE_BUNDLE)
    import io
    with ZipFile(io.BytesIO(bundle)) as z:
        require(z.read("ops/act046a_kb47_event_skeleton.py") == Path(skeleton.__file__).read_bytes(),
                "FROZEN_SKELETON_CODE_DRIFT")
    adj = info["sources"]["adjustment"]
    raw = json.loads(reads.bytes(Path(adj["path"]), adj["sha256"]))
    require((raw["asof_date"], raw["coverage_end_date"], raw["price_basis"], raw["volume_basis"]) ==
            (info["cutoff"], info["cutoff"], "QFQ_ASOF", "QFQ_EVENT_VOLUME"), "ADJUSTMENT_SCOPE")
    calendar = market_calendar(info["sources"]["calendar"], int(info["cutoff"]))
    excluded = {audit.security_day(row) for row in b0 + b1}
    require(len(excluded) == 252, "OLD_EXCLUSION_SCOPE")
    return dict(old=old, new=new, position=calendar, adjustment=raw["symbols"], excluded=excluded,
                codes=sorted(raw["symbols"].keys() & {r["ts_code"] for r in b0+b1}),
                source_refs=reads.refs, generation=info["sources"]["generation"],
                calendar_source=info["sources"]["calendar"], cutoff=info["cutoff"])


def scanner(paths, columns, code):
    import pyarrow.dataset as ds

    for p in paths:
        scan = ds.dataset(p, format="parquet").scanner(columns=list(columns), use_threads=True,
                                                       filter=ds.field("ts_code") == code, batch_size=8192)
        for batch in scan.to_batches():
            yield from batch.to_pylist()


def init_worker(env):
    import pyarrow as pa

    pa.set_cpu_count(ARROW_THREADS)
    pa.set_io_thread_count(ARROW_THREADS)
    PRIVATE_ENV.update(env)


def actual(row):
    return row["D_bar_state"] == "VALID_TDX_DAILY" and all(positive(row[key]) for key in
            ("D_open", "D_high", "D_low", "D_close", "D_raw_volume"))


def build_links(stock, authority):
    events = (authority or {}).get("events", [])
    dates = [int(e["ex_date"]) for e in events]
    require(dates == sorted(dates), "UNSORTED_ACTION_EVENTS")
    history_start = int((authority or {}).get("history_start_date") or 99999999)
    ledger_known = (authority or {}).get("event_coverage_complete") is True
    links = [(None, None, "FIRST_VISIBLE_BAR")]
    for before, after in zip(stock, stock[1:]):
        left, right = before["trade_date"], after["trade_date"]
        seg = before["D_ratio_hfq_segment"]
        known = ledger_known and left >= history_start and seg is not None and seg == after["D_ratio_hfq_segment"]
        pre = after["D_pre_close"]
        if not known or not positive(pre):
            links.append((None, None, "D_BASIS_UNVERIFIED"))
            continue
        chosen = events[bisect_right(dates, left):bisect_right(dates, right)]
        old_close = before["D_close"]
        theo = old_close
        vf = 1.0
        for event in chosen:
            a, b, v = (float(event[k]) for k in ("a", "b", "volume_a"))
            require(positive(a) and positive(v) and math.isfinite(b), "BAD_EFFECTIVE_EVENT")
            theo = theo * a + b
            vf *= v
        if not positive(theo) or not positive(vf) or abs(theo - pre) > .00500001:
            links.append((None, None, "D_REFERENCE_CONFLICT"))
        else:
            links.append((theo / old_close, vf,
                          "STITCHED_POSITIVE_RATIO_CHAIN" if chosen else "SAME_SEALED_ADJACENT_REFERENCE"))
    return links


def crop(stock, links, end, position):
    start = max(0, end - N + 1)
    d = stock[end]["trade_date"]
    pf = vf = 1.0
    out = []
    for i in range(end, start - 1, -1):
        row = stock[i]
        offset = position[row["trade_date"]] - position[d]
        unit = lambda field: x * pf if (x := finite(row[field])) is not None else None
        cached = {field: unit(column) for field, column in PRICE.items()}
        cached.update(session=offset, volume=row["D_raw_volume"] * vf, j=finite(row["D_J"]),
                      k=finite(row["D_K"]), kdj=finite(row["D_KDJ_D"]), link=links[i][2])
        out.append(cached)
        if i == start or links[i][0] is None:
            break
        pf *= links[i][0]
        vf *= links[i][1]
    out.reverse()
    return out


def wave(row, position):
    d = row["trade_date"]
    prior = row["prior_active_anchor_date"]
    active = row["active_anchor_date"]
    return sorted({position[x] for x in (prior, active) if x is not None and x in position and x < d})


def review(row, window, positions, code):
    day = window[-1]
    prev = next((b for b in window if b["session"] == -1), None)
    w, y, close = (day[k] for k in ("white", "yellow", "close"))
    w_gt_y = w > y if positive(w) and positive(y) else None
    fixed_day = row["prior_active_anchor_date"]
    fixed = finite(row["prior_active_anchor_low"])
    prior_offset = (positions[fixed_day] - positions[row["trade_date"]]
                    if fixed_day in positions and fixed_day < row["trade_date"] and positive(fixed) else None)
    support = (skeleton.Support("FIXED", prior_offset, "FIXED_LOW", fixed)
               if prior_offset is not None else None)
    bars = {x["session"]: skeleton.Bar(
        x["session"], "D", x["link"], x["open"], x["high"], x["low"], x["close"], x["pre_close"],
        x["volume"], x["white"], x["yellow"], x["bbi"], x["dif"], x["dea"], x["hist"], x["atr14"])
        for x in window}
    tri = skeleton.tri
    f08, f08_long, f08_short = qualification.f08_atom(window[-21:])
    f05 = row["user_v1_breakout"]
    values = dict(anon_id=f"{code}:{row['trade_date']}", m05_raw_f08=tri(f08), m05_r3=tri(w_gt_y),
                  m05_eligible_state=tri(audit.tri_and(audit.tri_and(f08, w_gt_y), None)),
                  m17_raw_f05=tri(f05), m17_eligible_state=tri(audit.tri_and(f05,None)),
                  m25_eligible_state="UNKNOWN")
    old_close_broken = close < fixed if prior_offset is not None else None
    a17 = skeleton.d17(values, bars)
    a25 = skeleton.d25(values, bars, support)
    a05 = skeleton.d05(values, bars, support, dict(close_broken_through_D=old_close_broken,
                                                  reclaim_through_D=row["prior_active_anchor_reclaim"]))
    require(all(x == "FALSE" for result in (a17, a25, a05) for k, x in result.items() if
                k.endswith("auto_L1_confirm")), "AUTO_CONFIRM_FORBIDDEN")
    high20 = max(b["high"] for b in window[-21:-1]) if len(window) >= 21 else None
    active20 = [b["close"] > b["white"] for b in window[-20:] if positive(b["white"])]
    sh = day["high"] - max(day["close"], day["open"])
    spread = day["high"] - day["low"]
    card = dict(white=w, yellow=y, white_minus_yellow=minus(w,y),
                white_distance_atr=a17["r3_white_dist_atr"], gap_pct=a17["r3_gap_pct"],
                body_pct=a17["r3_body_pct"], range_pct=divide(100*spread,day["pre_close"]),
                upper_shadow_pct=divide(100*sh,day["pre_close"]), upper_range_fraction=divide(sh,spread),
                close_above_white_count20=sum(active20), white_known_count20=len(active20),
                close_above_white_fraction20=divide(sum(active20),len(active20)),
                f08_long21=f08_long, f08_short3=f08_short, f05_high20=high20,
                f05_close_minus_high20=minus(close,high20), f05_volume_ratio_prev=divide(day["volume"], prev["volume"]) if prev else None,
                f05_return_pct=100*row["D_return"] if finite(row["D_return"]) is not None else None,
                dif_D=day["dif"], dea_D=day["dea"], dif_prev=prev["dif"] if prev else None, dea_prev=prev["dea"] if prev else None,
                f09_spread_D=minus(day["dif"],day["dea"]), f09_spread_prev=minus(prev["dif"],prev["dea"]) if prev else None,
                fixed_anchor_low=fixed if prior_offset is not None else None, fixed_anchor_offset=prior_offset,
                fixed_anchor_close_minus=minus(close,fixed) if prior_offset is not None else None,
                d_offset=a25["m25_damage_session"], t_offset=a25["m25_test_session"], c_offset=a25["m25_observed_reclaim_session"])
    # Facts-only cache; eligibility remains frozen/unknown and is never a package label.
    cue_top = a17["r3_is_gap_up_yin_bar"] == "TRUE" or bool(
        card["upper_range_fraction"] is not None and card["upper_range_fraction"] >= .45 and
        card["white_distance_atr"] is not None and card["white_distance_atr"] >= 3.5)
    return dict(
        window_bars=len(window), first_session=window[0]["session"]+positions[row["trade_date"]],
        w_gt_y=w_gt_y, old_anchor_below=old_close_broken, high_refutation=cue_top,
        f08_raw=f08, f05_raw=f05, **a17, **a25, **a05, **card,
    )


def stock_state(code, env):
    old = list(scanner(env["old"], BASE, code))
    new = list(scanner(env["new"], V11, code))
    require(len(old) == len(new) and [r["trade_date"] for r in old] == [r["trade_date"] for r in new],
            "STOCK_PROJECTION_MISMATCH")
    require(old and [r["trade_date"] for r in old] == sorted({r["trade_date"] for r in old}),
            "STOCK_D_SEQUENCE")
    stock = [r for r in old if actual(r)]
    ordinal = {r["trade_date"]: i for i,r in enumerate(stock)}
    return old, new, stock, ordinal, build_links(stock, env["adjustment"].get(code))


def worker(code):
    t = time.perf_counter()
    cpu = time.process_time()
    env = PRIVATE_ENV
    pos = env["position"]
    old, new, stock, ordinal, links = stock_state(code, env)
    rows = []
    skip = []
    for row, amended in zip(old,new):
        d = row["trade_date"]
        key = (code,d)
        methods = [m for m in audit.L1 if amended[f"v11_{m:02}"] is True]
        old_hit = [m for m in audit.ORIG_BUY if row[f"kb_{m:02}"] is True]
        hit = bool(methods or old_hit)
        ready = hit and d in ordinal and row["D_high"] > row["D_low"] and (row["ratio_formula_bars_in_segment"] or 0) >= 114
        common = dict(ts_code=code, trade_date=d, session=pos[d], wave=wave(row,pos), methods=methods,
                      old_methods=old_hit, board=row["board"], board_epoch=row["board_epoch"],
                      warmup=row["ratio_formula_bars_in_segment"])
        if key in env["excluded"]:
            skip.append(common)
        elif ready:
            window = crop(stock,links,ordinal[d],pos)
            rows.append(dict(**common, **review(row,window,pos,code)))
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rows, skip, dict(pid=os.getpid(), peak_worker_rss_bytes=int(peak), cpu_s=time.process_time()-cpu,
                            wall_s=time.perf_counter()-t, source_rows=len(old), candidate_rows=len(rows))


def setup(root):
    env = bound(root)
    import pyarrow.dataset as ds

    # Derive the roster from sealed shards rather than from the adjustment ledger.
    all_codes = set()
    for path in env["old"]:
        tab = ds.dataset(path,format="parquet").to_table(columns=["ts_code"])
        all_codes.update(tab["ts_code"].unique().to_pylist())
    require(len(all_codes)==47, "STOCK_ROSTER_DRIFT")
    env["codes"] = sorted(all_codes)
    return env


def precompute(root, escrow, workers):
    import pyarrow as pa
    import pyarrow.parquet as pq

    t0 = time.perf_counter()
    env = setup(root)
    init_worker(env)
    setup_s = time.perf_counter()-t0
    sample = env["codes"][::len(env["codes"])//workers][:workers]
    t = time.perf_counter()
    serial = [worker(code) for code in sample]
    serial_s = time.perf_counter()-t
    t = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker, initargs=(env,)) as pool:
        parallel = list(pool.map(worker,sample))
        parallel_s = time.perf_counter()-t
        require(all(a[:2] == b[:2] for a,b in zip(serial,parallel)), "PARALLEL_CANARY_DRIFT")
        del serial
        remaining = list(pool.map(worker,[c for c in env["codes"] if c not in sample]))
    compute_s = time.perf_counter()-t
    rows = sorted([row for block, _, _ in parallel+remaining for row in block], key=audit.security_day)
    excluded = sorted([row for _, block, _ in parallel+remaining for row in block], key=audit.security_day)
    stats = [stat for _,_,stat in parallel+remaining]
    require(len(rows)==33875 and len(excluded)==252 and sum(s["source_rows"] for s in stats)==162897,
            "ACT047A_BASE_OR_EXCLUSION_DRIFT")
    t=time.perf_counter()
    path=escrow/"skeleton_cache.parquet"
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),"wb") as f:
        pq.write_table(pa.Table.from_pylist(rows),f,compression="zstd")
    private_write(escrow/"prior_exposure.json",json.dumps(excluded).encode())
    facts=dict(rows=len(rows),complete60=sum(r["window_bars"]==60 for r in rows),
               short_basis_or_history=sum(r["window_bars"]!=60 for r in rows),
               w_gt_y=dict(Counter(str(r["w_gt_y"]) for r in rows)),
               repair_clock=dict(Counter(r["m25_repair_clock"] for r in rows)),
               repair_clock_reasons=dict(Counter(r["m25_repair_clock_reason"] for r in rows)),
               f05=dict(Counter(str(r["f05_raw"]) for r in rows)),
               f08=dict(Counter(str(r["f08_raw"]) for r in rows)),
               f09=dict(Counter(r["m17_USER_F09_SIGNAL_CROSS"] for r in rows)),
               axis=dict(Counter(r["m17_COURSE_260422_DIF_AXIS_CROSS"] for r in rows)),
               auto_true=0)
    result=dict(**audit.FLAGS, facts=facts, stocks=len(env["codes"]), workers_configured=workers,
                worker_processes=len({s["pid"] for s in stats}), arrow_threads_per_worker=ARROW_THREADS,
                worker_max_rss_bytes=max(s["peak_worker_rss_bytes"] for s in stats),
                worker_peak_rss_sum_bound_bytes=sum(max(s["peak_worker_rss_bytes"] for s in stats if s["pid"]==p)
                                                   for p in {s["pid"] for s in stats}),
                coordinator_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                worker_cpu_s=sum(s["cpu_s"] for s in stats), benchmark_stocks=len(sample),
                benchmark_keys=sum(s["candidate_rows"] for _,_,s in parallel),
                benchmark_serial_s=serial_s, benchmark_parallel_s=parallel_s,
                benchmark_speedup=serial_s/parallel_s, pool_s=compute_s, setup_s=setup_s,
                cache_write_s=time.perf_counter()-t, precompute_total_s=time.perf_counter()-t0,
                source_generation=env["generation"], source_refs=env["source_refs"],
                calendar_reference=env["calendar_source"], d_after_files=0,
                cache_bytes=path.stat().st_size, cache_sha256=file_sha(path),
                previous_exposure_sha256=file_sha(escrow/"prior_exposure.json"))
    private_write(escrow/"precompute_receipt.json",json.dumps(result,ensure_ascii=False,indent=2).encode())
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--artifacts",type=Path,required=True)
    p.add_argument("--private",type=Path,required=True)
    p.add_argument("--workers",type=int,choices=range(8,13),default=WORKERS)
    a=p.parse_args()
    result=precompute(a.artifacts, private_dir(a.private), a.workers)
    print(json.dumps({k:v for k,v in result.items() if k not in ("source_refs","calendar_reference")},ensure_ascii=False))


if __name__=="__main__":
    main()
