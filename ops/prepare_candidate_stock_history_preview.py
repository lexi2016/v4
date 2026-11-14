"""Assemble the 2026-11-12/13 four-stock preview from accepted, frozen inputs."""
import argparse
from copy import deepcopy
import csv
import importlib.util
from pathlib import Path
from shutil import copyfile
import tempfile

from read_candidate_stock_history import CASE_FIELDS, DATES, GROUPS, RAW_FLAGS, SYMBOL, SYMBOLS, BATCH_SCHEMA


EARLY, LATE = sorted(DATES)
LABELS = dict(original="原公式", nav_smallk="小 K", nav_pullback="回踩", nav_breakout="突破")
NAMES = {SYMBOL: "ST京机", "688729.SH": "屹唐股份", "301618.SZ": "长联科技", "301585.SZ": "蓝宇股份"}
FIXES = {"20231127": "TRUE", "20241125": "TRUE", "20250224": "TRUE", "20251231": "TRUE", "20260923": "FALSE"}
PINS = {
    "stjingji-history-canary-20261114/bind_cutoffs.py": "1d64595a379d618adf634ab9b8e6826884db244ffe5f0c607b66d115c9f7aaa8",
    "stjingji-history-canary-20261114/BASELINE.json": "cf2a31fe871d3e2878136564f8b57b89e2c4616d018d2b1ecad17d1b2fb1f31c",
    "stjingji-history-canary-20261114/STOCK_HISTORY_CANDIDATE_OVERLAY.json": "d9ae4f58a5771225fb6e990618f5a18b5068e1b585af2860383d26aeb0b68977",
    "stjingji-history-canary-20261114/run/CANARY_RESULT.json": "e42e9670ed772d158d9f9097729c88f55721345fba3e6894f7bd387724cf318c",
    "stjingji-history-canary-20261114/CUTOFF_DEPENDENCIES.json": "7fe73d32dded5fa3740ff3dad316b45fbd0ae30fb863d28b905df27a85339e7f",
    "stjingji-history-canary-20261114/statistics/2026-11-12/latest.json": "ff3688941ed38fed45a1e71fed403e0bf5b0005e3f228d4b735804c8467357a1",
    "stjingji-history-canary-20261114/statistics/2026-11-13/latest.json": "8c1668c235742a6c6225573a678617aa1cff1a979f7c8dcdacfb182f481c789a",
    "smallk-study-20261114/BATCH_ACCEPTANCE.json": "e8325a957133bb27831c94ae66a0d6f23d30a865567034cee4c1cd1d47895bf8",
    "smallk-study-20261114/source-probes/G4_PARITY_PROBES.json": "3e68a5f9ea27f6d5be496037740334f89dae5c050cd7f97cb8f75c56216d3f6a",
    "smallk-study-20261114/older_cutoff_case_cache.sqlite3": "3a0c9f6b8aecd7bbc24201a0e1adeeb9a79967ac602957e38183c4aa6f1a2a21",
    "smallk-study-20261114/comparison/301585.SZ/2026-11-12-rates.json": "bed92a600948f7b6bdf02c55bfb354f446188bc0d099b02ca8e3a27787b71f24",
    "smallk-study-20261114/comparison/301618.SZ/2026-11-12-rates.json": "ccb76c6b7d14996eef6edc377fcf981d39e845b59a011b047ad018b6990cddeb",
    "smallk-study-20261114/comparison/688729.SH/2026-11-12-rates.json": "9bec41de722b0d77ffbbc5991e1e66e78816a44b4de48d490bb36dfef9a252e1",
    "history-four-sample-20261114/BASELINE.json": "bc5a55aa7519f86266898d29d8b43f15293e133a2fdf75c8599e6987e82b320d",
}


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def patch_group(group, horizons, event_count):
    group.update(status="AVAILABLE" if event_count else "EMPTY_EVENT_SET", eligible_event_count=event_count)
    group["horizons"] = {h: {**{k: v for k, v in full.items() if k not in {"cases", "conditional"}},
                             "cases": [{k: case[k] for k in CASE_FIELDS} for case in full["cases"][:20]]}
                         for h, full in horizons.items()}


def inputs(candidate):
    from hashlib import sha256
    refs = {}
    for relative, digest in PINS.items():
        path = candidate / relative
        require(path.resolve(strict=True) == path and sha256(path.read_bytes()).hexdigest() == digest,
                "FROZEN_PREVIEW_INPUT_DRIFT: " + relative)
        refs[path.name if path.name not in {"BASELINE.json", "latest.json", "2026-11-12-rates.json"} else relative] = dict(path=str(path), sha256=digest)
    # Reuse the previous cutoff adapter's verified chart, cache, and case helpers.
    helper = importlib.util.spec_from_file_location("accepted_cutoff", refs["bind_cutoffs.py"]["path"])
    m = importlib.util.module_from_spec(helper)
    helper.loader.exec_module(m)
    return m, refs


def paired_bars(m, charts):
    bars = {}
    for day, chart in charts.items():
        m.original_bootstrap.TARGET = int(day)
        bars[day] = m.projection_bars(m.load(chart))
    require(bars[EARLY] == bars[LATE][:-1], "FROZEN_OHLCV_PREFIX_CHANGED")
    return {day: {m.stats_date(b["trade_date"]): float(b["close"]) for b in rows} for day, rows in bars.items()}


def event_build(store, m, dates, closes, cal, day, symbol, product, group, seeds):
    source = product["source_identity"]
    return store.build(identity=dict(symbol=symbol, market=symbol[-2:],
        source_authority=source["reader_provenance"]["transport_equivalence"]["historical_mathematical_reader"],
        basis={k: v for k, v in source["basis"].items() if k != "asof_date"},
        rule_sha256=group["rule_sha256"], formula_sha256=group["source_identity"]["formula"]),
        event_dates=dates, close_rows=[dict(date=d, close=p) for d, p in closes.items()],
        calendar=cal, asof=m.stats_date(day), accepted_seed=seeds)


def original(m, record, symbol):
    row = m.load(record["product"]["row_refs"][symbol])
    shard = m.load(record["events"]["items"][symbol])
    require(shard["projection"] == record["chart"]["samples"][symbol]["projection"]
            and shard["statistics_sha256"] == m.raw_hash(row["statistics"])
            and shard["numeric_manifest"] == record["binding"]["numeric_manifest"], "ORIGINAL_CASE_BINDING")
    return row, shard


def assemble_st(m, refs, records, accepted, store):
    old = {day: (m.load(accepted[day]["detail_row"]), m.load(accepted[day]["event_cases"])) for day in DATES}
    probes = m.load(refs["G4_PARITY_PROBES.json"])
    canary = m.load(refs["CANARY_RESULT.json"])
    contract = m.load(canary["contract"])
    require(probes["symbol"] == SYMBOL and probes["case"] == canary["contract"]
            and m.load(refs["CUTOFF_DEPENDENCIES.json"])["status"] == "PASS", "ST_ACCEPTANCE")
    checkpoint = m.load_checkpoint_ref(canary["history_cache"])
    evaluations = checkpoint["evaluations"]
    patch = {}
    for day, state in FIXES.items():
        sample = probes["probes"][day]
        require(day < EARLY and evaluations[day]["groups"]["nav_smallk"] == sample["original_label"] == "UNKNOWN"
                and state == sample["probe_label"] == sample["raw_check"]["status"]
                and sample["source"] == sample["raw"]["source"] == m.ref(sample["source"]["path"]), "ST_FIVE_LABEL_SCOPE")
        patch[day] = dict(before="UNKNOWN", after=state, source=sample["source"])
    patch_ref = m.save(records[EARLY]["out"] / "ST_SMALLK_LABEL_PATCH.json", dict(symbol=SYMBOL, group="nav_smallk",
        previous_checkpoint=canary["history_cache"], parity=refs["G4_PARITY_PROBES.json"], changes=patch, **RAW_FLAGS))
    bars = paired_bars(m, {day: old[day][1]["projection"] for day in sorted(DATES)})
    calendar_by_day = {day: m.load(old[day][1]["calendar"])["dates"] for day in DATES}
    require(calendar_by_day[LATE] == m.load(contract["refs"]["calendar"])["dates"], "ST_CALENDAR_DRIFT")
    calendars = {day: list(map(m.stats_date, calendar_by_day[day]["SZ"])) for day in DATES}
    additions = {m.stats_date(d) for d, value in FIXES.items() if value == "TRUE"}
    results, counters = {}, {}
    for day in sorted(DATES, reverse=True):
        before_row, before_cases = old[day]
        row, cases = deepcopy(before_row), deepcopy(before_cases)
        coverage = row["historical_coverage"]
        require(coverage["unknown_by_group"]["nav_smallk"] == 1389, "ST_UNKNOWN_BASELINE")
        coverage["unknown_by_group"]["nav_smallk"] -= len(patch)
        group = next(g for g in row["statistics"]["groups"] if g["group_id"] == "nav_smallk")
        baseline = before_cases["groups"]["nav_smallk"]
        retained_dates = {c["event_date"] for c in baseline["d2"]["cases"]}
        require(retained_dates == {m.stats_date(d) for d, v in evaluations.items()
                                   if d <= day and v["groups"]["nav_smallk"] == "TRUE"}
                and retained_dates.isdisjoint(additions), "ST_BASELINE_EVENT_DATES")
        dates = sorted(retained_dates | additions)
        newer = results[LATE][1]["groups"]["nav_smallk"] if day == EARLY else baseline
        seeds = m.exact_reuse_seed(baseline, newer, dates, calendars[day], calendars[LATE],
                                   bars[day], bars[LATE], m.stats_date(day))
        result = event_build(store, m, dates, bars[day], calendars[day], day, SYMBOL, records[day]["product"], group, seeds)
        counters[day] = result["cache"]
        require(counters[day]["return_evaluations"] == (8 if day == LATE else 0), "ST_RETURN_WORK_SCOPE")
        cases["groups"]["nav_smallk"] = result["horizons"]
        m.verify_old_cases(before_cases["groups"], cases["groups"])
        patch_group(group, result["horizons"], len(dates))
        cases.update(statistics_sha256=m.raw_hash(row["statistics"]), accepted_label_patch=patch_ref,
                     candidate_label_patch_cache=result["cache"])
        results[day] = (row, cases)
    return results, dict(changes=patch_ref, return_cache=counters)


def assemble_three(m, refs, records, batch, symbol, store):
    witness = batch["symbols"][symbol]
    canary = m.load(witness["result"])
    contract = m.load(canary["contract"])
    newest_row, newest_shard = m.load(canary["row"]), m.load(canary["event_cases"])
    old_row, old_shard = original(m, records[EARLY], symbol)
    require(canary["status"] == "COMPLETE_DESCRIPTIVE_NONPIT" and canary["symbol"] == symbol
            and canary["event_cases"] == witness["later_cutoff_case_ref"]
            and canary["formula_engine_compute_calls"] == 0 and not canary["remaining_dates"]
            and m.no_stats(newest_row) == m.no_stats(original(m, records[LATE], symbol)[0])
            and newest_shard["statistics_sha256"] == m.raw_hash(newest_row["statistics"]), "ACCEPTED_CANARY_BINDING")
    m.verify_old_cases(original(m, records[LATE], symbol)[1]["groups"], newest_shard["groups"])
    bars = paired_bars(m, {EARLY: old_shard["projection"], LATE: newest_shard["projection"]})
    by_market = m.load(contract["refs"]["calendar"])["dates"]
    # The prior three-stock acceptance already matched this exact market calendar across both dates.
    require(by_market == records[EARLY]["calendar"] == records[LATE]["calendar"], "BATCH_CALENDAR_DRIFT")
    calendar = list(map(m.stats_date, by_market[symbol[-2:]]))
    checkpoint = m.load_checkpoint_ref(canary["history_cache"])
    labels = {d: v for d, v in checkpoint["evaluations"].items() if d <= EARLY}
    require({m.stats_date(d) for d in labels} == set(bars[EARLY]), "EARLY_LABEL_COVERAGE")
    early_row = deepcopy(old_row)
    early_row["historical_coverage"] = {**checkpoint["coverage"], "requested_end": int(EARLY),
        "evaluated_dates": sorted(map(int, labels)), "available_prefix_dates": len(labels), "evaluated_count": len(labels),
        "unknown_by_group": {group: sum(v["groups"][group] == "UNKNOWN" for v in labels.values()) for group in GROUPS}}
    groups, counters = {}, {}
    for group in early_row["statistics"]["groups"]:
        name = group["group_id"]
        dates = sorted(m.stats_date(d) for d, value in labels.items() if value["groups"][name] == "TRUE")
        seeds = m.exact_reuse_seed(old_shard["groups"][name], newest_shard["groups"][name], dates, calendar, calendar,
                                  bars[EARLY], bars[LATE], m.stats_date(EARLY))
        result = event_build(store, m, dates, bars[EARLY], calendar, EARLY, symbol, records[EARLY]["product"], group, seeds)
        require(result["cache"]["return_evaluations"] == result["cache"]["percentile_evaluations"] == 0,
                "EARLY_BATCH_MUST_REUSE_CACHE")
        groups[name], counters[name] = result["horizons"], result["cache"]
        patch_group(group, result["horizons"], len(dates))
    prior_rates = refs[f"smallk-study-20261114/comparison/{symbol}/2026-11-12-rates.json"]
    require(m.horizons_only(early_row) == m.load(prior_rates)["groups"], "EARLY_ACCEPTED_RATE_DRIFT")
    m.verify_old_cases(old_shard["groups"], groups)
    early_shard = m.shell_cases(old_shard, records[EARLY]["binding"]["numeric_manifest"], records[EARLY]["product"],
        EARLY, early_row, groups, old_shard["projection"], records[EARLY]["calendar_ref"])
    early_shard.update(cache_reuse=counters, accepted_later_cases=canary["event_cases"], accepted_earlier_rates=prior_rates)
    return {EARLY: (early_row, early_shard), LATE: (newest_row, newest_shard)}, dict(
        result=witness["result"], accepted_later_row=canary["row"], accepted_later_cases=canary["event_cases"],
        accepted_earlier_rates=prior_rates, earlier_return_cache=counters)


def compare_before(m, kept_rows, previous_stats, old_row, old_shard, captured):
    symbol = old_row["symbol"]
    stock = captured["stocks"][symbol]
    original = stock["detail"]["row"]
    require(original["statistics"] == old_row["statistics"] and original["historical_coverage"] == old_row["historical_coverage"]
            and kept_rows[symbol]["history_rates"] == previous_stats["rows"][symbol] == m.horizons_only(old_row), "CAPTURED_BEFORE_DETAIL")
    for group, value in old_shard["groups"].items():
        for horizon, case in value.items():
            api = stock["cases"][group][horizon]
            require({k: api[k] for k in case} == case, "CAPTURED_BEFORE_CASES")


def materialize(candidate):
    m, refs = inputs(candidate)
    out = candidate / "history-four-sample-20261114"
    accepted = m.load(refs["STOCK_HISTORY_CANDIDATE_OVERLAY.json"])["dates"]
    baseline = m.load(refs["history-four-sample-20261114/BASELINE.json"])
    index = m.load(m.baseline["original_product_index"])
    batch = m.load(refs["BATCH_ACCEPTANCE.json"])
    require(set(batch["symbols"]) == SYMBOLS - {SYMBOL} and set(batch["dates"]) == DATES, "BATCH_SAMPLES")
    records, compared, outputs, lineage = {}, {}, {}, {}
    for day in sorted(DATES):
        iso = m.stats_date(day)
        binding = {k: accepted[day][k] for k in ("numeric_manifest", "generation", "input_sha256", "chart_manifest")}
        product = m.load(m.load(binding["numeric_manifest"])["artifact"])
        calendar_ref = m.load(accepted[day]["event_cases"])["calendar"]
        records[day] = dict(out=out, binding=binding, product=product, chart=m.load(binding["chart_manifest"]),
                            events=m.load(index["event_cases"][day]), calendar_ref=calendar_ref, calendar=m.load(calendar_ref)["dates"],
                            previous_pointer=refs[f"stjingji-history-canary-20261114/statistics/{iso}/latest.json"],
                            captured=m.load(baseline["dates"][iso]))
    st_cache = m.EventCaseCache(":memory:")
    try:
        outputs[SYMBOL], lineage[SYMBOL] = assemble_st(m, refs, records, accepted, st_cache)
    finally:
        st_cache.close()
    # Never write to the accepted SQLite file; remove only this temporary copy.
    with tempfile.TemporaryDirectory(dir=out, prefix=".cache-") as directory:
        copy = Path(directory) / "accepted.sqlite3"
        copyfile(refs["older_cutoff_case_cache.sqlite3"]["path"], copy)
        store = m.EventCaseCache(copy)
        try:
            for symbol in sorted(SYMBOLS - {SYMBOL}):
                outputs[symbol], lineage[symbol] = assemble_three(m, refs, records, batch, symbol, store)
        finally:
            store.close()
    manifest = dict(schema=BATCH_SCHEMA, dates={}, **RAW_FLAGS)
    for day, record in records.items():
        iso = m.stats_date(day)
        captured = record["captured"]
        kept_rows = {row["symbol"]: row for row in captured["workbench"]["rows"]}
        pointer = m.load(record["previous_pointer"])
        previous_stats = m.load(pointer["artifact"])
        new_stats = deepcopy(previous_stats)
        require(captured["workbench"]["statistics_version"] == pointer["artifact"]["sha256"]
                and set(kept_rows) == set(previous_stats["rows"]), "CURRENT_PREVIEW_LIST_BASELINE")
        views, compared[iso] = {}, {}
        for symbol, by_day in outputs.items():
            row, shard = by_day[day]
            old_row, old_shard = ((m.load(accepted[day]["detail_row"]), m.load(accepted[day]["event_cases"]))
                                  if symbol == SYMBOL else original(m, record, symbol))
            compare_before(m, kept_rows, previous_stats, old_row, old_shard, captured)
            require(m.no_stats(row) == m.no_stats(old_row), "UNCHANGED_CURRENT_DETAIL")
            m.verify_old_cases(old_shard["groups"], shard["groups"])
            hits = [g for g in LABELS if kept_rows[symbol]["group_states"][g] == "TRUE"]
            require(set(hits) == set(row["groups"].split("|")), "UNCHANGED_MEMBERSHIP")
            folder = out / "projection" / iso / symbol
            view = dict(detail_row=m.save(folder / "detail-row.json", row), event_cases=m.save(folder / "event-cases.json", shard))
            if day == LATE and symbol != SYMBOL:
                for local, original_ref in (("detail_row", "accepted_later_row"), ("event_cases", "accepted_later_cases")):
                    require(view[local]["sha256"] == lineage[symbol][original_ref]["sha256"], "LATE_RESULT_BYTE_DRIFT")
            views[symbol] = view
            new_stats["rows"][symbol] = m.horizons_only(row)
            compared[iso][symbol] = dict(name=NAMES[symbol], current_hit_groups=hits, before=m.horizons_only(old_row),
                after=m.horizons_only(row), before_coverage={k:v for k,v in old_row["historical_coverage"].items() if k != "evaluated_dates"},
                after_coverage={k:v for k,v in row["historical_coverage"].items() if k != "evaluated_dates"}, **view)
        require({s for s, v in new_stats["rows"].items() if v != previous_stats["rows"][s]} == SYMBOLS, "FOUR_LIST_ROWS_ONLY")
        date_root = out / "statistics" / iso
        version = m.raw_hash(new_stats)
        artifact = m.save(date_root / version / "statistics.json", new_stats)
        receipt = m.save(date_root / version / "receipt.json", dict(status="COMMITTED", artifact=artifact,
            previous_statistics=record["previous_pointer"], symbols=sorted(SYMBOLS), **RAW_FLAGS))
        latest = m.save(date_root / "latest.json", {**pointer, "artifact": artifact, "receipt": receipt})
        manifest["dates"][day] = dict(**record["binding"], views=views, statistics_pointer=latest,
                                       previous_statistics_pointer=record["previous_pointer"])
    report = dict(dates=compared, source_refs=refs, lineage=lineage, historical_PIT=False, **RAW_FLAGS)
    m.save(out / "COMPARISON.json", report)
    with (out / "D2_D5_COMPARISON.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        fields = ["date", "symbol", "name", "group", "current_hit", "horizon", "before_positive", "before_valid",
                  "before_not_matured", "after_positive", "after_valid", "after_not_matured"]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for date, stocks in compared.items():
            for symbol, item in stocks.items():
                for group in LABELS:
                    for horizon in ("d2", "d5"):
                        amounts = {f"{phase}_{k}": item[phase][group][horizon][k]
                                   for phase in ("before", "after") for k in ("positive", "valid", "not_matured")}
                        writer.writerow(dict(date=date, symbol=symbol, name=item["name"], group=group,
                            current_hit=group in item["current_hit_groups"], horizon=horizon, **amounts))
    print(m.save(out / "STOCK_HISTORY_CANDIDATE_OVERLAY.json", manifest))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_root", type=Path)
    materialize(parser.parse_args().candidate_root.resolve(strict=True))
