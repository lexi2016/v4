"""Seal the fixed method, replay 41 observed clocks, then attach ex-post labels."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from importlib import import_module
from io import TextIOWrapper
import multiprocessing
import os
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

from ops.pft_act080_core.archive import read_archive
from ops.pft_act080_core.run import PREFIX_DIVISIONS, _assert_no_differences, _compare, _peak_rss_bytes
from ops.pft_act080_core.split import BOUNDARIES, split_evidence
from ops.pft_act080_p2.contracts import (
    BASELINE_SHA, JUNDA, VOL2_SHA, claim, digest, read_json, verify, write_csv, write_json,
)
from ops.pft_act080_p2.holdouts import JUNDA_CASES, legacy_rows, parse_exclusions
from ops.pft_act080_p2.sources import validate_bundle
from ops.pft_act081_kb.evaluate import attach_outcomes, outcomes, robustness, screen_clean, summary
from ops.pft_act081_kb.features import B1 as STATIC
from ops.pft_act081_kb.features import LEGACY
from ops.pft_act081_kb.run import EXCLUSION, GOVERNANCE, P1B, SIGNED as P1_SIGNED, _prices, verify_p1b_runtime

from .replay import CORE, METHOD_PATH, STRICT, replay


P1 = "ACT081_P1_KB_SOUL_B1B2_AND_60BAR_BUNDLE_20261127.zip"
SIGNED = {
    P1: "cfeedfa7b4af14af772954727b790d69627566dcc3f3643d6afe222fcb59e5c4",
    P1B: P1_SIGNED[P1B], EXCLUSION: P1_SIGNED[EXCLUSION],
}
LOCK = "PRE_EVALUATION_LOCK.json"
POLICIES = (CORE, STRICT, STATIC, LEGACY)
CASE_DATES = {day for _, day, _ in JUNDA_CASES}
RUNTIME = {
    "pft_act081_kb": ("__init__.py", "features.py", "evaluate.py", "run.py"),
    "pft_act080_p2": ("__init__.py", "contracts.py", "sources.py", "holdouts.py", "outcomes.py", "method.json"),
}


def imported_runtime_member(package, name):
    package_path = Path(import_module(f"ops.{package}").__file__).parent
    if name.endswith(".py") and name != "__init__.py":
        return Path(import_module(f"ops.{package}.{Path(name).stem}").__file__)
    return package_path / name


def verify_p1_runtime(path):
    with ZipFile(path) as archive:
        count = validate_bundle(archive)
        sums = dict((member, sha) for sha, member in (
            line.split("  ", 1) for line in archive.read("SHA256SUMS.txt").decode("ascii").splitlines()
        ))
    runtime = {}
    for package, names in RUNTIME.items():
        for name in names:
            member = f"ops/{package}/{name}"
            runtime[member] = verify(imported_runtime_member(package, name), sums[member])
    return count, runtime


def lock_contents(root, vol2, baseline):
    source = METHOD_PATH.parent
    source_files = [*sorted(source.glob("*.py")), METHOD_PATH, source / "README.md", *sorted((source / "tests").glob("*.py"))]
    signed = {name: verify(root / name, checksum) for name, checksum in SIGNED.items()}
    p1_count, p1_runtime = verify_p1_runtime(root / P1)
    p1b_count, p1b_runtime = verify_p1b_runtime(root / P1B)
    return {
        "schema": "ACT081_P2_DYNAMIC_ANOMALY_B1_V1", "governance": GOVERNANCE,
        "signed_input_hashes": signed, "vol2_sha256": verify(vol2, VOL2_SHA),
        "frozen_baseline_sha256": verify(baseline, BASELINE_SHA),
        "p1_members_verified": p1_count, "p1_imported_runtime_hashes": p1_runtime,
        "p1b_members_verified": p1b_count, "p1b_imported_runtime_hashes": p1b_runtime,
        "source_hashes": {str(path.relative_to(source)): digest(path) for path in source_files},
    }


def replay_chain(chain):
    daily, events = replay(chain.security_id, chain.bars)
    prefixes = []
    for numerator in PREFIX_DIVISIONS:
        stop = len(daily) * numerator // 4
        short_daily, short_events = replay(chain.security_id, chain.bars[:stop])
        differences = _compare(daily[:stop], short_daily)
        differences.update(_compare([row for row in events if row["session_idx"] < stop], short_events))
        _assert_no_differences(differences, f"{chain.security_id}/prefix={stop}")
        prefixes.append({
            "security_id": chain.security_id, "prefix_bars": stop, "prefix_end_D": daily[stop - 1]["trade_date"],
            "appended_bars": len(daily) - stop, "daily_rows_compared": len(short_daily),
            "event_rows_compared": len(short_events), **dict(differences),
        })
    flags, boundaries = split_evidence(chain.bars, events)
    for event, split in zip(events, flags, strict=True):
        event.update({
            "D": event["trade_date"], "fold": split["assigned_fold"] or "EXCLUDED",
            "calendar_fold": split["calendar_fold"], "episode_origin_fold": split["episode_origin_fold"],
            "split_exclusion_reasons": split["split_exclusion_reasons"],
        })
    cases = [row for row in daily if row["trade_date"] in CASE_DATES] if chain.security_id == JUNDA else []
    roots = [row for row in daily if row["anchor_age_sessions"] == 0]
    return len(daily), events, prefixes, boundaries, cases, roots


def check_cooldown(events):
    last, last_raw, first = {}, {}, set()
    counts = Counter()
    for row in events:
        stock, idx, episode = (row[k] for k in ("security_id", "session_idx", "structure_episode_id"))
        before = last.get(stock)
        if idx <= last_raw.get(stock, -1):
            raise ValueError("duplicate or non-increasing raw security session")
        last_raw[stock] = idx
        gap = None if before is None else idx - before
        allowed = gap is None or gap > 5
        if allowed:
            last[stock] = idx
        after = last.get(stock)
        expected = {
            "last_accepted_session_idx_before": before, "gap_trading_days": gap,
            "accepted_flag": allowed, "reject_reason": "" if allowed else "COOLDOWN_LE5",
            "last_accepted_session_idx_after": after,
            "gap_trading_days_after": idx - after if after is not None else None,
            "accepted_role": ("REPEAT" if episode in first else "FIRST") if allowed else None,
        }
        if any(row[k] != v for k, v in expected.items()):
            raise ValueError(f"independent cooldown ledger mismatch at {stock}/{idx}")
        if allowed:
            first.add(episode)
        if row["strict_first_hit"] != (
            expected["accepted_role"] == "FIRST" and row["strict_eligible_pre_cooldown"]
        ):
            raise ValueError("STRICT escaped CORE FIRST")
        counts["accepted" if allowed else "rejected"] += 1
        counts[f"{'accepted' if allowed else 'rejected'}_gap_{gap}"] += 1
    counts["raw"] = len(events)
    counts["conservation_delta"] = counts["raw"] - counts["accepted"] - counts["rejected"]
    if counts["conservation_delta"]:
        raise ValueError("cooldown conservation failed")
    return dict(counts)


def archive_rows(archive, name):
    with archive.open(f"results/ACT081_P1_{name}.csv") as data:
        return list(csv.DictReader(TextIOWrapper(data, encoding="utf-8-sig", newline="")))


EVENT_KEYS = ("candidate_event_id", "security_id", "D", "trade_date", "structure_episode_id", "key_k_date", "fold")


def identities(rows):
    return {
        (row["candidate_event_id"], row["security_id"], row["D"], int(row["session_idx"]), row["structure_episode_id"])
        for row in rows
    }


def read_static_and_reference(path):
    with ZipFile(path) as archive:
        static = [
            {**{k: row[k] for k in EVENT_KEYS}, "session_idx": int(row["session_idx"])}
            for row in archive_rows(archive, "TRACK_LEDGER")
            if row["track"] == STATIC and row["accepted_flag"] == "True" and row["accepted_role"] == "FIRST"
        ]
        phase1_clean = archive_rows(archive, "CLEAN_OOT_DETAIL")
        phase1_junda = archive_rows(archive, "JUNDA_FIRST_DETAIL")
        signed_cases = {row["case_id"]: row for row in archive_rows(archive, "JUNDA_7_CASES")}
    return static, {
        policy: {
            "clean": identities(row for row in phase1_clean if row["policy"] == policy),
            "junda": identities(row for row in phase1_junda if row["policy"] == policy),
        }
        for policy in (STATIC, LEGACY)
    }, signed_cases


def select_cohorts(core, static, legacy, refs, signed_reference):
    candidates = {
        CORE: core, STRICT: [row for row in core if row["strict_first_hit"]], STATIC: static, LEGACY: legacy,
    }
    clean, junda, flows, proof = {}, {}, {}, []
    for policy, rows in candidates.items():
        if len(rows) != len(identities(rows)) or len(rows) != len({r["structure_episode_id"] for r in rows}):
            raise ValueError(f"{policy}: FIRST identity uniqueness failed")
        oot = [r for r in rows if r["fold"] == "OOT"]
        same_universe = [r for r in oot if r["security_id"] != JUNDA]
        clean[policy], exclusions = screen_clean(same_universe, refs, policy)
        junda[policy] = [r for r in rows if r["security_id"] == JUNDA]
        _, residual = screen_clean(clean[policy], refs, policy)
        if residual or any(row["security_id"] == JUNDA for row in clean[policy]):
            raise ValueError(f"{policy}: contaminated Clean OOT")
        if policy in signed_reference and (
            identities(clean[policy]) != signed_reference[policy]["clean"]
            or identities(junda[policy]) != signed_reference[policy]["junda"]
        ):
            raise ValueError(f"{policy}: changed frozen P1 cohort identity")
        proof.extend(exclusions)
        flows[policy] = {
            "all_history_first": len(rows), "oot_first_with_junda": len(oot),
            "junda_oot_separated": len(oot) - len(same_universe),
            "distinct_reference_case_excluded_oot": len(same_universe) - len(clean[policy]),
            "clean_oot_first": len(clean[policy]), "clean_oot_active_stocks": len({r["security_id"] for r in clean[policy]}),
            "junda_first_all_history": len(junda[policy]), "residual_matches": len(residual),
        }
    if not identities(clean[STRICT]).issubset(identities(clean[CORE])):
        raise ValueError("Clean OOT STRICT is not a subset of CORE")
    return clean, junda, flows, proof


def membership(clean, junda):
    return [
        {
            "scope": scope, "policy": policy, **{key: row[key] for key in EVENT_KEYS},
            "session_idx": row["session_idx"],
        }
        for scope, families in (("CLEAN_OOT_40", clean), ("JUNDA_WHOLE_HISTORY", junda))
        for policy, rows in families.items()
        for row in rows
    ]


def case_breakdown(daily, events, junda, signed_cases, junda_prices):
    daily_by_day = {row["trade_date"]: row for row in daily}
    event_by_day = {row["D"]: row for row in events if row["security_id"] == JUNDA}
    policy_days = {policy: {row["D"] for row in rows} for policy, rows in junda.items()}
    rows, tallies = [], {
        policy: {"positive_recall": 0, "negative_exclusion": 0, "directionally_correct": 0} for policy in POLICIES
    }
    for case, day, expected in JUNDA_CASES:
        daily_row = daily_by_day[day]
        event, old = event_by_day.get(day), signed_cases[case]
        if old["D"] != day or old["expected"] != expected:
            raise ValueError(f"changed signed Junda marker {case}")
        hits = {policy: day in dates for policy, dates in policy_days.items()}
        if hits[STATIC] != (old["b1_first_hit"] == "True") or hits[LEGACY] != (old["v21_first_a_hit"] == "True"):
            raise ValueError(f"changed signed comparator Junda status {case}")
        if hits[CORE]:
            core_status = "FIRST_HIT"
        elif event:
            core_status = "REPEAT_NOT_FIRST" if event["accepted_flag"] else event["reject_reason"]
        else:
            core_status = "GATE_REJECTED"
        strict_status = (
            "FIRST_HIT" if hits[STRICT] else "STRICT_GATE_REJECTED" if hits[CORE] else core_status
        )
        for policy, hit in hits.items():
            correct = hit if expected == "RECALL" else not hit
            if correct:
                tallies[policy]["directionally_correct"] += 1
                tallies[policy]["positive_recall" if expected == "RECALL" else "negative_exclusion"] += 1
        rows.append({
            "case_id": case, "D": day, "expected": expected,
            "core_first_hit": hits[CORE], "strict_first_hit": hits[STRICT],
            "static_p1_first_hit": hits[STATIC], "frozen_v21_A_first_hit": hits[LEGACY],
            "core_status": core_status, "strict_status": strict_status,
            "raw_core_cooldown_gap": event["gap_trading_days"] if event else None,
            "static_p1_failed_gates": old["b1_failed_gates"],
            "frozen_v21_exact_tiers": old["v21_exact_tiers"], **daily_row,
            **outcomes(junda_prices, daily_row["session_idx"]),
        })
    return rows, tallies


def run(root, output, vol2, baseline, workers):
    start = perf_counter()
    locked = lock_contents(root, vol2, baseline)
    lock_sha = digest(output / LOCK)
    saved = read_json(output / LOCK)
    if saved != {**locked, "claimed_ns": saved["claimed_ns"], "pid": saved["pid"]}:
        raise ValueError("code, method, or source hashes changed after method freeze")
    claim(output / "ACT081_P2_EXECUTION_CLAIM.json", method_sha256=lock_sha)
    volume = read_archive(vol2)
    chains = volume.chains
    prices = _prices(chains)
    stocks = sorted(set(prices) - {JUNDA})
    if len(stocks) != 40 or JUNDA not in prices:
        raise ValueError("expected 40 non-Junda securities plus Junda")
    replay_start = perf_counter()
    if workers == 1:
        results = list(map(replay_chain, chains))
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(replay_chain, chains))
    replay_seconds = perf_counter() - replay_start
    event_rows, prefixes, boundaries, junda_daily, roots = [], [], [], [], []
    observed = 0
    for chain, (length, events, audit, cuts, daily, starts) in zip(chains, results, strict=True):
        observed += length
        event_rows.extend(events)
        prefixes.extend(audit)
        boundaries.extend({"security_id": chain.security_id, **row} for row in cuts)
        junda_daily.extend(daily)
        roots.extend(starts)
    if len(prefixes) != 123 or observed != sum(len(chain.bars) for chain in chains):
        raise ValueError("incomplete 41-stock causal prefix coverage")
    event_rows.sort(key=lambda row: (row["security_id"], row["session_idx"]))
    cooldown = check_cooldown(event_rows)
    core = [row for row in event_rows if row["accepted_role"] == "FIRST"]
    refs = parse_exclusions(root / EXCLUSION, prices)
    static, signed_reference, signed_cases = read_static_and_reference(root / P1)
    legacy = [row for row in legacy_rows(baseline, prices) if row["role"] == "FIRST" and row["legacy_A"]]
    clean, junda, flows, proof = select_cohorts(core, static, legacy, refs, signed_reference)
    write_csv(output / "ACT081_P2_DYNAMIC_LEDGER.csv", event_rows)
    write_csv(output / "ACT081_P2_MOTHER_STARTS.csv", roots)
    write_csv(output / "ACT081_P2_PREFIX_AUDIT.csv", prefixes)
    write_csv(output / "ACT081_P2_TIME_BOUNDARIES.csv", boundaries)
    write_csv(output / "ACT081_P2_CLEAN_OOT_EXCLUSION_PROOF.csv", proof)
    cohort_file = output / "ACT081_P2_PRE_OUTCOME_COHORT.csv"
    write_csv(cohort_file, membership(clean, junda))
    cohort_sha = digest(cohort_file)
    claim(output / "ACT081_P2_PRE_OUTCOME_COHORT_SEAL.json", method_sha256=lock_sha, cohort_sha256=cohort_sha)
    report_start = perf_counter()
    for groups in (clean, junda):
        for policy in (CORE, STATIC, LEGACY):
            attach_outcomes(groups[policy], prices)
    robust, loso, sensitivity = robustness(clean, stocks, CORE)
    for row in robust:
        if row["scenario"] == "REMOVE_SHARED_TOP3_B1_T5_SUM":
            row["scenario"] = "REMOVE_SHARED_TOP3_CORE_T5_SUM"
    cases, tallies = case_breakdown(junda_daily, event_rows, junda, signed_cases, prices[JUNDA])
    for filename, groups in (("CLEAN_OOT_DETAIL", clean), ("JUNDA_FIRST_DETAIL", junda)):
        write_csv(output / f"ACT081_P2_{filename}.csv", (
            {"policy": policy, **row} for policy, rows in groups.items() for row in rows
        ))
    write_csv(output / "ACT081_P2_JUNDA_7_CASES.csv", cases)
    write_csv(output / "ACT081_P2_ROBUSTNESS.csv", robust)
    write_csv(output / "ACT081_P2_LEAVE_ONE_STOCK_OUT.csv", loso)
    errors = {
        key: sum(r[key] for r in prefixes)
        for key in ("cells_compared", "row_count_difference", "field_set_differences", "na_position_differences", "cell_differences")
    }
    metrics = {
        "schema": locked["schema"], "governance": GOVERNANCE, "input_lock": locked,
        "pre_evaluation_lock_sha256": lock_sha, "pre_outcome_cohort_sha256": cohort_sha,
        "observed_bars": observed, "mother_starts": len(roots),
        "root_kind_counts": dict(Counter(row["mother_kind"] for row in roots)),
        "prefix": {"chains": len(chains), "checks": len(prefixes), **errors}, "cooldown": cooldown,
        "clean_scope": {"stock_roster": stocks, "reference_cases": sum(map(len, refs.values())), **flows},
        "clean_oot": {policy: summary(rows) for policy, rows in clean.items()},
        "junda_all_history": {policy: summary(rows) for policy, rows in junda.items()},
        "junda_case_tallies": tallies, "robustness": sensitivity,
        "runtime": {
            "configured_workers": workers, "logical_cpu": os.cpu_count(), "peak_parent_rss_bytes": _peak_rss_bytes(),
            "replay_including_prefix_seconds": replay_seconds, "post_cohort_seconds": perf_counter() - report_start,
            "total_seconds": perf_counter() - start,
        },
    }
    write_json(output / "ACT081_P2_METRICS.json", metrics)
    print(f"ACT081 P2 complete. Prefix {len(prefixes)}. Clean OOT: " + "/".join(str(len(clean[k])) for k in POLICIES))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "run"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vol2", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=14)
    args = parser.parse_args()
    if args.command == "freeze":
        args.output.mkdir(parents=True, exist_ok=True)
        write_once = args.output / LOCK
        claim(write_once, **lock_contents(args.root, args.vol2, args.baseline))
        print(f"ACT081 P2 method locked: {digest(write_once)}")
    else:
        run(args.root, args.output, args.vol2, args.baseline, args.workers)


if __name__ == "__main__":
    main()
