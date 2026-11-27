"""Isolated batch entry point for the frozen ACT-080 research archive."""

import argparse
from collections import Counter, defaultdict
import csv
from hashlib import sha256
from io import StringIO
import json
from math import isfinite
import multiprocessing
import os
from pathlib import Path
import platform
import resource
import sys
from time import perf_counter

from .archive import read_archive
from .core import CONFIG, CONFIG_SHA256, FEATURE_FIELDS, LEDGER_FIELDS, ReplayState
from .split import SPLIT_FIELDS, split_evidence


CSV_CAP_BYTES = 9_500_000
PREFIX_DIVISIONS = (1, 2, 3)
GAP_BUCKETS = ("raw", "accepted", "rejected", "first_arm")


def _peak_rss_bytes():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform == "darwin" else value * 1024


def _compare(expected, actual):
    error = Counter()
    error["row_count_difference"] = abs(len(expected) - len(actual))
    for left, right in zip(expected, actual):
        error["field_set_differences"] += left.keys() != right.keys()
        for key, value in left.items():
            other = right.get(key)
            error["cells_compared"] += 1
            error["na_position_differences"] += (value is None) != (other is None)
            if type(value) is float and type(other) is float:
                equal = value.hex() == other.hex()
            else:
                equal = type(value) is type(other) and value == other
            error["cell_differences"] += not equal
    return error


def _assert_no_differences(error, context):
    keys = ("row_count_difference", "field_set_differences", "na_position_differences", "cell_differences")
    differences = {key: error[key] for key in keys}
    if any(differences.values()):
        raise ValueError(f"{context}: {differences}")


def replay_chain(job):
    chain, audit_prefix = job
    bars = chain.bars
    ledger, features = ReplayState(chain.security_id, chain.provenance).consume(bars)
    splits, boundaries = split_evidence(bars, ledger)
    prefix_errors = Counter()
    prefix_checks = []
    if audit_prefix:
        for numerator in PREFIX_DIVISIONS:
            stop = len(bars) * numerator // 4
            if stop == 0:
                continue
            prior_ledger, prior_features = ReplayState(chain.security_id, chain.provenance).consume(bars[:stop])
            expected_ledger = [row for row in ledger if row["session_idx"] < stop]
            expected_features = [row for row in features if row["session_idx"] < stop]
            err = _compare(expected_ledger, prior_ledger)
            err.update(_compare(expected_features, prior_features))
            _assert_no_differences(err, f"prefix {chain.security_id} {bars[stop - 1].trade_date}")
            prefix_errors.update(err)
            prefix_checks.append({
                "prefix_bars": stop, "prefix_end_D": bars[stop - 1].trade_date,
                "appended_future_bars": len(bars) - stop,
                "ledger_rows_compared": len(prior_ledger),
                "feature_rows_compared": len(prior_features),
                "cells_compared": err["cells_compared"],
            })
    return {
        "security_id": chain.security_id,
        "ledger": ledger, "features": features, "splits": splits, "boundaries": boundaries,
        "prefix_errors": dict(prefix_errors), "prefix_checks": prefix_checks,
        "valid_bars": len(bars), "first_D": bars[0].trade_date, "last_D": bars[-1].trade_date,
        "source_chain_sha256": chain.provenance.source_chain_sha256,
        "nonpositive_ohlc_bars": sum(not bar.positive_ohlc for bar in bars),
        "zero_volume_bars": sum(bar.volume == 0 for bar in bars),
        "pid": os.getpid(), "pid_peak_rss_bytes": _peak_rss_bytes(),
    }


def replay_all(chains, workers, audit_prefix=False):
    ordered = sorted(chains, key=lambda chain: chain.security_id)
    if len({chain.security_id for chain in ordered}) != len(ordered):
        raise ValueError("duplicate security input")
    jobs = [(chain, audit_prefix) for chain in ordered]
    if workers == 1:
        return [replay_chain(job) for job in jobs]
    if not 1 < workers <= 18:
        raise ValueError("parallel worker count must be 2..18")
    with multiprocessing.get_context("spawn").Pool(workers) as pool:
        return pool.map(replay_chain, jobs, chunksize=1)


def compare_replays(parallel, serial):
    if len(parallel) != len(serial):
        raise ValueError("serial/parallel stock counts differ")
    error = Counter()
    for first, second in zip(parallel, serial, strict=True):
        if first["security_id"] != second["security_id"]:
            raise ValueError("serial/parallel stock order differs")
        for stream in ("ledger", "features", "splits", "boundaries"):
            error.update(_compare(first[stream], second[stream]))
        _assert_no_differences(error, f"serial/parallel {first['security_id']}")
    return dict(error)


def _audit_stock(result):
    ledger, features, splits = (result[key] for key in ("ledger", "features", "splits"))
    ids = [row["candidate_event_id"] for row in ledger]
    if (
        len(set(ids)) != len(ids)
        or ids != [row["candidate_event_id"] for row in features]
        or ids != [row["candidate_event_id"] for row in splits]
    ):
        raise ValueError(f"{result['security_id']}: candidate coverage or identity mismatch")
    accepted, rejected = [], []
    last_accepted = None
    last_key = None
    episodes = defaultdict(set)
    released_roles = defaultdict(Counter)
    gap_counts = {gap: Counter() for gap in (4, 5, 6)}
    for row, feature, split in zip(ledger, features, splits, strict=True):
        session = row["session_idx"]
        rank = row["day_candidate_rank"]
        expected_before = last_accepted
        gap = None if last_accepted is None else session - last_accepted
        accept = rank == 1 and (gap is None or gap > 5)
        reason = "" if accept else "DUPLICATE_SAME_DAY" if rank > 1 else "COOLDOWN_LE5"
        if accept:
            last_accepted = session
            accepted.append(row)
        else:
            rejected.append(row)
        expected_after_gap = None if last_accepted is None else session - last_accepted
        key = row["trade_date"], rank
        if (
            (last_key is not None and key <= last_key)
            or row["last_accepted_session_idx_before"] != expected_before
            or row["gap_trading_days"] != gap or row["accepted_flag"] != accept
            or row["reject_reason"] != reason
            or row["last_accepted_session_idx_after"] != last_accepted
            or row["gap_trading_days_after"] != expected_after_gap
            or row["qualification_arm"] != row["day_eligible_arms"].split("|")[rank - 1]
            or any(row[field] != feature[field] for field in row.keys() & feature.keys())
        ):
            raise ValueError(f"{result['security_id']}: cooldown/feature mismatch at {key}")
        last_key = key
        episode_id = row["structure_episode_id"]
        if accept:
            released_roles[episode_id][row["accepted_role"]] += 1
        if split["assigned_fold"] is not None:
            episodes[episode_id].add(split["assigned_fold"])
        if gap in gap_counts:
            gap_counts[gap]["raw"] += 1
            gap_counts[gap]["accepted" if accept else "rejected"] += 1
            if rank == 1:
                gap_counts[gap]["first_arm"] += 1
        if any(type(feature[key]) is float and not isfinite(feature[key]) for key in FEATURE_FIELDS):
            raise ValueError(f"{result['security_id']}: nonfinite feature at {key}")
    if any(len(folds) > 1 for folds in episodes.values()):
        raise ValueError(f"{result['security_id']}: an episode crosses assigned folds")
    if any(roles["FIRST"] != 1 or roles["CONFIRM"] > 1 for roles in released_roles.values()):
        raise ValueError(f"{result['security_id']}: released episode role invariant failed")
    if len(ledger) != len(accepted) + len(rejected):
        raise ValueError(f"{result['security_id']}: candidate quantity conservation failed")
    return accepted, rejected, gap_counts


def _row_bytes(writer, scratch, values):
    scratch.seek(0)
    scratch.truncate()
    writer.writerow(values)
    return scratch.getvalue().encode("utf-8")


def write_csv(output, stem, fields, rows):
    scratch = StringIO(newline="")
    writer = csv.writer(scratch, lineterminator="\n")
    header = _row_bytes(writer, scratch, fields)
    result = []
    active = None

    def open_part():
        name = f"{stem}_{len(result) + 1:03}.csv"
        handle = (output / name).open("xb")
        digest = sha256(header)
        handle.write(header)
        return handle, name, digest, len(header), 0

    def close_part(part):
        handle, name, digest, size, count = part
        handle.close()
        result.append({"name": name, "rows": count, "bytes": size, "sha256": digest.hexdigest()})

    try:
        active = open_part()
        for row in rows:
            encoded = _row_bytes(writer, scratch, (row[field] for field in fields))
            if len(encoded) + len(header) > CSV_CAP_BYTES:
                raise ValueError(f"{stem}: single CSV row exceeds the byte cap")
            handle, name, digest, size, count = active
            if size + len(encoded) > CSV_CAP_BYTES:
                close_part(active)
                active = open_part()
                handle, name, digest, size, count = active
            handle.write(encoded)
            digest.update(encoded)
            active = handle, name, digest, size + len(encoded), count + 1
        close_part(active)
        active = None
    finally:
        if active is not None:
            active[0].close()
    return result


def audit_and_write(output, results):
    ledgers, features, split_rows, accepted, rejected = [], [], [], [], []
    observed, per_stock = Counter(), []
    total_gap = {gap: Counter() for gap in (4, 5, 6)}
    prefix = Counter()
    na_raw, na_accepted = Counter(), Counter()
    reject_reasons, roles = Counter(), Counter()
    split_flags = Counter()
    for result in results:
        accept, reject, gaps = _audit_stock(result)
        rows = result["ledger"]
        ledgers.extend(rows)
        features.extend(result["features"])
        split_rows.extend(result["splits"])
        accepted.extend(accept)
        rejected.extend(reject)
        observed.update({key: result[key] for key in ("valid_bars", "nonpositive_ohlc_bars", "zero_volume_bars")})
        for gap in total_gap:
            total_gap[gap].update(gaps[gap])
        accepted_roles = Counter(row["accepted_role"] for row in accept)
        roles.update(accepted_roles)
        reject_reasons.update(row["reject_reason"] for row in reject)
        for feature in result["features"]:
            absent = [key for key in FEATURE_FIELDS if feature[key] is None]
            na_raw.update(absent)
            if feature["accepted_flag"]:
                na_accepted.update(absent)
        for split in result["splits"]:
            if split["assigned_fold"] is not None:
                split_flags[f'assigned_{split["assigned_fold"]}'] += 1
            for field in ("purge", "embargo", "cross_period_episode"):
                split_flags[field] += split[field]
        prefix.update(result["prefix_errors"])
        per_stock.append({
            **{key: result[key] for key in (
                "security_id", "valid_bars", "first_D", "last_D", "source_chain_sha256",
                "nonpositive_ohlc_bars", "zero_volume_bars", "prefix_checks", "boundaries",
            )},
            "raw_candidates": len(rows),
            "accepted": len(accept), "rejected": len(reject),
            "conservation_difference": len(rows) - len(accept) - len(reject),
            "gap_distribution": {str(gap): {key: counts[key] for key in GAP_BUCKETS} for gap, counts in gaps.items()},
            "raw_episode_n": len({row["structure_episode_id"] for row in rows}),
            "episode_n": len({row["structure_episode_id"] for row in accept}),
            "first_n": accepted_roles["FIRST"],
            "non_first_n": accepted_roles["CONFIRM"] + accepted_roles["REPEAT"],
            "accepted_roles": {role: accepted_roles[role] for role in ("FIRST", "CONFIRM", "REPEAT")},
        })
    blocks = {
        "raw_candidates": write_csv(output, "RAW_CANDIDATES", LEDGER_FIELDS, ledgers),
        "rejected": write_csv(output, "REJECTED", LEDGER_FIELDS, rejected),
        "accepted": write_csv(output, "ACCEPTED", LEDGER_FIELDS, accepted),
        "D_only_features": write_csv(output, "D_ONLY_FEATURES", FEATURE_FIELDS, features),
        "time_split_sidecar": write_csv(output, "TIME_SPLITS", SPLIT_FIELDS, split_rows),
    }
    return {
        "conservation": {
            "stocks": len(per_stock), "stocks_with_candidates": sum(row["raw_candidates"] > 0 for row in per_stock),
            "raw_candidates": len(ledgers), "accepted": len(accepted), "rejected": len(rejected),
            "raw_minus_accepted_minus_rejected": len(ledgers) - len(accepted) - len(rejected),
            "reject_reasons": dict(reject_reasons),
            "gap_distribution": {str(gap): {key: counts[key] for key in GAP_BUCKETS} for gap, counts in total_gap.items()},
            "raw_episode_n": sum(row["raw_episode_n"] for row in per_stock),
            "episode_n": sum(row["episode_n"] for row in per_stock),
            "trigger_n": len(accepted), "first_n": roles["FIRST"],
            "non_first_n": roles["CONFIRM"] + roles["REPEAT"],
            "accepted_roles": {role: roles[role] for role in ("FIRST", "CONFIRM", "REPEAT")},
            "observed_source_rows": dict(observed), "by_stock": per_stock,
        },
        "D_only_features": {
            "rows": len(features), "accepted_subset_rows": len(accepted),
            "columns": list(FEATURE_FIELDS),
            "na_counts_by_column": {key: na_raw[key] for key in FEATURE_FIELDS},
            "accepted_subset_na_counts_by_column": {key: na_accepted[key] for key in FEATURE_FIELDS},
            "nonfinite_value_count": 0,
            "csv_na_encoding": "empty field",
        },
        "time_splits": {"rows": len(split_rows), "counts": dict(split_flags), "definition": CONFIG["splits"]},
        "prefix": {**dict(prefix), "securities": len(per_stock), "checks": sum(len(row["prefix_checks"]) for row in per_stock)},
        "files": blocks,
    }


def _write_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        handle.write("\n")


def run(archive_path, output, workers):
    start = perf_counter()
    stages = {}
    original = read_archive(archive_path)
    stages["verify_load_archive"] = perf_counter() - start
    output.mkdir()
    stage = perf_counter()
    parallel = replay_all(original.chains, workers, audit_prefix=True)
    stages["primary_replay_and_three_prefixes"] = perf_counter() - stage
    stage = perf_counter()
    serial = replay_all(original.chains, 1)
    comparison = compare_replays(parallel, serial)
    stages["serial_replay_and_exact_comparison"] = perf_counter() - stage
    del serial
    stage = perf_counter()
    results = audit_and_write(output, parallel)
    stages["audit_and_csv_write"] = perf_counter() - stage
    csv_files = [part for parts in results["files"].values() for part in parts]
    seen_workers = sorted({row["pid"] for row in parallel})
    result = {
        "schema": CONFIG["schema"],
        "input": original.evidence,
        "config_sha256": CONFIG_SHA256,
        "charter_sha256": CONFIG["charter_sha256"],
        "historical_adjustment_pit": CONFIG["historical_adjustment_pit"],
        "governance": CONFIG["governance"],
        **results,
        "serial_parallel_equality": comparison,
        "runtime": {
            "elapsed_seconds_through_csv": perf_counter() - start,
            "stages_seconds": stages,
            "python": sys.version.split()[0], "python_executable": sys.executable,
            "machine": platform.machine(), "available_cpu_count": os.cpu_count(),
            "workers_configured": workers, "worker_pids_with_job": seen_workers,
            "workers_with_job": len(seen_workers),
            "parent_peak_rss_bytes": _peak_rss_bytes(),
            "max_single_worker_peak_rss_bytes": max(row["pid_peak_rss_bytes"] for row in parallel),
            "bytes_written_csv": sum(part["bytes"] for part in csv_files),
            "physical_io_bytes": "UNAVAILABLE",
        },
    }
    _write_json(output / "CONSERVATION_AND_FEATURE_AUDIT.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, choices=range(1, 19), default=18)
    args = parser.parse_args()
    result = run(args.archive, args.output, args.workers)
    metrics = result["conservation"]
    print(json.dumps({
        "output": str(args.output),
        **{key: metrics[key] for key in ("stocks", "raw_candidates", "accepted", "rejected", "episode_n", "first_n", "non_first_n")},
        "prefix_checks": result["prefix"]["checks"],
        "workers_with_job": result["runtime"]["workers_with_job"],
        "elapsed_seconds_through_csv": result["runtime"]["elapsed_seconds_through_csv"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
