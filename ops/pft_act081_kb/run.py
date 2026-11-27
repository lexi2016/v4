"""Sign the 0-FIT method, replay VOL2, then issue isolated ex-post comparisons."""

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import csv
from hashlib import sha256
from importlib import import_module
import multiprocessing
import os
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

from ops.pft_act080_core.archive import read_archive
from ops.pft_act080_core.core import CONFIG_PATH as P1B_CONFIG_PATH
from ops.pft_act080_core.run import PREFIX_DIVISIONS, _assert_no_differences, _compare, _peak_rss_bytes
from ops.pft_act080_core.split import BOUNDARIES, split_evidence
from ops.pft_act080_p2.contracts import JUNDA, METHOD_PATH as P2_METHOD_PATH, verify, digest, claim, write_csv, write_json, read_json
from ops.pft_act080_p2.holdouts import JUNDA_CASES, legacy_rows, parse_exclusions
from ops.pft_act080_p2.sources import first_rows, validate_bundle

from .evaluate import attach_outcomes, fold_flows, outcomes, robustness, screen_clean, summary
from .features import B1, B2, FEATURES, KB, LEGACY, KnowledgeReplay


CHARTER = "PFT_V4_ACT081_CHARTER_KB_ALIGNMENT_V1_0_20261127.md"
P1B = "ACT080_P1B_DETERMINISTIC_BASE_BUNDLE_20261127.zip"
EXCLUSION = "ACT080_P2_72CASE_OOT_EXCLUSION_MANIFEST.csv"
SIGNED = {
    CHARTER: "534ff06bbc318c4ba361c068d6f0566bd3b585076203bcfec5422e8be1858916",
    P1B: "c9f59877448d716a4bba44e45ef0226fe913bd0a6651ae92a69634696efc6701",
    EXCLUSION: "512e28cbf1a1c04eb2893b225f9dcb1e873ed48da5d19af6920690249307e590",
    "KB_B1_ORIGINAL.pdf": "d762486fa89244525f02c1a12fc7535afec78617ed554568533c475466ae89aa",
    "KB_B1_PAGES.txt": "146ae2b726d249343cdd274db1f068499bf704a691ebcb86975014fa833a2da2",
    "KB_TEN_CHARTS_GUIDE.md": "c31ce48fef7f086a23befd7b8ddcc60a104e6618af7d280e4f0adeac521c360e",
}
GOVERNANCE = {
    "FIT": 0, "evaluation_threshold_tuning": 0, "training": 0, "FIT_ALLOWED": False,
    "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": 0,
    "legacy_status": "LEGACY_UNVERIFIABLE_OPERATOR_READ_ONLY", "PIT": "CANNOT_CONFIRM",
    "P5.15": [0, 0, 0, 0], "decision": "NO_GO",
}
LOCK_FILE = "PRE_EVALUATION_LOCK.json"
SELECT_FILE = "ACT081_P1_PNG_SELECTION.json"
P1B_MODULES = ("__init__", "anchors", "archive", "core", "run", "split")
P2_MODULES = ("__init__", "contracts", "outcomes", "holdouts", "sources")


def imported_files(package, modules):
    return {
        f"{name}.py": Path(import_module(package if name == "__init__" else f"{package}.{name}").__file__)
        for name in modules
    }


def verify_p1b_runtime(path):
    runtime = imported_files("ops.pft_act080_core", P1B_MODULES)
    runtime["config.json"] = P1B_CONFIG_PATH
    with ZipFile(path) as archive:
        count = validate_bundle(archive)
        manifest = {
            member: checksum for checksum, member in (
                row.split("  ", 1) for row in archive.read("SHA256SUMS.txt").decode("ascii").splitlines()
            )
        }
    verified = {
        name: verify(file, manifest[f"ops/pft_act080_core/{name}"])
        for name, file in runtime.items()
    }
    return count, verified


def lock_contents(root):
    source = Path(__file__).resolve().parent
    p2 = imported_files("ops.pft_act080_p2", P2_MODULES)
    files = sorted(source.glob("*.py")) + [source / "README.md", *p2.values(), P2_METHOD_PATH]
    signed = {name: verify(root / name, expected) for name, expected in SIGNED.items()}
    p1b_count, p1b_runtime = verify_p1b_runtime(root / P1B)
    return {
        "schema": "ACT081_P1_0FIT_V1", "governance": GOVERNANCE,
        "source_hashes": {f"{p.parent.name}/{p.name}": digest(p) for p in files},
        "signed_input_hashes": signed, "p1b_member_hashes_verified": p1b_count,
        "p1b_imported_runtime_hashes": p1b_runtime,
    }


def _replay(chain):
    def run(bars):
        return KnowledgeReplay(chain.security_id, chain.provenance).consume(bars)

    daily, events = run(chain.bars)
    verification, rows = Counter(), []
    for numerator in PREFIX_DIVISIONS:
        stop = len(daily) * numerator // 4
        prior_daily, prior_events = run(chain.bars[:stop])
        error = _compare(daily[:stop], prior_daily)
        error.update(_compare([row for row in events if row["session_idx"] < stop], prior_events))
        _assert_no_differences(error, f"{chain.security_id}/prefix={stop}")
        verification.update(error)
        rows.append({
            "security_id": chain.security_id, "prefix_bars": stop, "prefix_end_D": daily[stop - 1]["trade_date"],
            "appended_bars": len(daily) - stop, "daily_rows_compared": len(prior_daily),
            "event_rows_compared": len(prior_events), **dict(error),
        })
    flags, boundaries = split_evidence(chain.bars, events)
    for event, split in zip(events, flags, strict=True):
        event.update({
            "D": event["trade_date"], "fold": split["assigned_fold"] or "EXCLUDED",
            "calendar_fold": split["calendar_fold"], "episode_origin_fold": split["episode_origin_fold"],
            "split_exclusion_reasons": split["split_exclusion_reasons"],
        })
    return daily, events, rows, verification, boundaries


def _na(rows):
    return {"rows": len(rows), "na_counts": {field: sum(r[field] is None for r in rows) for field in FEATURES}}


def _cooldown_audit(events):
    last, b1, b2, gaps = {}, set(), set(), Counter()
    for row in events:
        stock, d = row["security_id"], row["session_idx"]
        before = last.get(stock)
        expected_gap = None if before is None else d - before
        allowed = expected_gap is None or expected_gap > 5
        if (
            before != row["last_accepted_session_idx_before"] or expected_gap != row["gap_trading_days"]
            or allowed != row["accepted_flag"] or (d if allowed else before) != row["last_accepted_session_idx_after"]
        ):
            raise ValueError("invalid shared P1B cooldown replay")
        keys, other = (b1, b2) if row["track"] == B1 else (b2, b1)
        identity = stock, d
        if identity in keys or identity in other:
            raise ValueError("B1/B2 raw identity intersection or repeated D")
        keys.add(identity)
        if allowed:
            last[stock] = d
        gaps[f"{'accepted' if allowed else 'rejected'}_gap_{expected_gap}"] += 1
    accepted = sum(row["accepted_flag"] for row in events)
    return {
        "raw": len(events), "accepted": accepted, "rejected": len(events) - accepted,
        "conservation_delta": len(events) - sum(gaps.values()), "cross_track_session_intersection": len(b1 & b2),
        "gap_counts": dict(gaps),
    }


def _first(events, track):
    rows = [row for row in events if row["track"] == track and row["accepted_role"] == "FIRST"]
    if len(rows) != len({row["structure_episode_id"] for row in rows}):
        raise ValueError("FIRST is not unique by track/episode")
    return rows


def _prices(chains):
    return {
        chain.security_id: tuple(tuple(getattr(bar, field) for bar in chain.bars)
                                 for field in ("trade_date", "open", "close", "low"))
        for chain in chains
    }


def image_ready(chain, ordinal):
    # Y has 114 observed bars of warmup, including the first visible D-60 bar.
    return ordinal >= 173 and all(bar.positive_ohlc for bar in chain.bars[ordinal - 60:ordinal + 1])


def _choose_images(b1, by_stock, prices):
    junda_pos = {day: idx for idx, day in enumerate(prices[JUNDA][0])}
    cases = [
        {"universe": "JUNDA_BENCHMARKS", "security_id": JUNDA, "D": day,
         "session_idx": junda_pos[day], "source_key": case}
        for case, day, _ in sorted(JUNDA_CASES)
    ]
    oot = [
        {"universe": "CLEAN_OOT_B1_FIRST", "security_id": row["security_id"], "D": row["D"],
         "session_idx": row["session_idx"], "source_key": row["candidate_event_id"]}
        for row in sorted(b1, key=lambda event: event["candidate_event_id"])
        if image_ready(by_stock[row["security_id"]], row["session_idx"])
    ]
    if not all(image_ready(by_stock[JUNDA], row["session_idx"]) for row in cases):
        raise ValueError("one or more exact Junda benchmark dates lack a 61-bar OHLCV/W/Y chart")
    # Anonymous alpha-numeric name derived from outcome-blind identifiers, independent of row order.
    rows = cases + oot[:20]
    for row in rows:
        material = f"ACT081_IMAGE_V1|{row['security_id']}|{row['D']}|{row['source_key']}"
        row["image_id"] = sha256(material.encode("ascii")).hexdigest()[:20]
    if len({row["image_id"] for row in rows}) != len(rows):
        raise ValueError("anonymous image ID collision")
    return {"n_chart_eligible_oot": len(oot), "requested_oot": 20, "rows": sorted(rows, key=lambda r: r["image_id"])}


def _case_records(junda_daily, junda_events, junda_legacy, junda_price):
    daily = {row["trade_date"]: row for row in junda_daily}
    events = {row["D"]: row for row in junda_events}
    cases, tallies = [], Counter()
    for case, day, expected in sorted(JUNDA_CASES):
        base = daily[day]
        event = events.get(day) or {}
        legacy = [r for r in junda_legacy if r["D"] == day]
        first = event.get("track") == B1 and event.get("accepted_role") == "FIRST"
        hits = {
            B1: first, KB: first and event["kb_subset"],
            LEGACY: any(r["role"] == "FIRST" and r["legacy_A"] for r in legacy),
        }
        for policy, passed in hits.items():
            tallies[policy] += passed == (expected == "RECALL")
        cases.append({
            "case_id": case, "D": day, "expected": expected, "qualification_track": base["track"],
            "b1_failed_gates": base["b1_failed_gates"], "b1_raw_hit": base["track"] == B1,
            "event_accepted_role": event.get("accepted_role"), "cooldown_reject_reason": event.get("reject_reason"),
            "b1_first_hit": hits[B1], "kb_subset_first_hit": hits[KB], "v21_first_a_hit": hits[LEGACY],
            "v21_exact_tiers": "|".join(sorted({r["legacy_tier"] for r in legacy})),
            "active_anchor_D": base["key_k_date"], "anchor_age_sessions": base["anchor_age_sessions"],
            **{field: base[field] for field in FEATURES}, **outcomes(junda_price, base["session_idx"]),
        })
    return cases, {**tallies, "ACT080_P2_CHARTER_REFERENCE": 2, "cases": len(cases)}


def run(root, output, vol2, baseline, workers):
    start = perf_counter()
    lock = lock_contents(root)
    lock_path = output / LOCK_FILE
    locked = read_json(lock_path)
    if any(locked[k] != value for k, value in lock.items()):
        raise ValueError("code, rule, or source hashes changed after the 0-FIT method freeze")
    claim(output / "ACT081_P1_EXECUTION_CLAIM.json", method_sha256=digest(lock_path))
    with ZipFile(root / P1B) as archive:
        original = first_rows(archive, development_only=False)
    verified_vol2 = read_archive(vol2)
    chains = verified_vol2.chains
    by_stock = {chain.security_id: chain for chain in chains}
    prices = _prices(chains)
    stocks = sorted(set(prices) - {JUNDA})
    if len(stocks) != 40:
        raise ValueError("expected exactly 40 non-Junda stocks")
    replay_start = perf_counter()
    if workers == 1:
        results = list(map(_replay, chains))
    else:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(_replay, chains))
    replay_seconds = perf_counter() - replay_start
    features_dir = output / "features"
    features_dir.mkdir()
    all_daily, all_events, prefixes, boundary_rows = [], [], [], []
    errors = Counter()
    for (daily, events, evidence, differences, boundaries), chain in zip(results, chains, strict=True):
        write_csv(features_dir / f"{chain.security_id}.csv", daily)
        all_daily.extend(daily)
        all_events.extend(events)
        prefixes.extend(evidence)
        errors.update(differences)
        boundary_rows.extend({"security_id": chain.security_id, **row} for row in boundaries)
    if len(prefixes) != 123 or len(all_daily) != sum(len(chain.bars) for chain in chains):
        raise ValueError("incomplete causal feature or prefix coverage")
    cooldown = _cooldown_audit(all_events)
    flows = fold_flows(all_events)
    b1, b2 = _first(all_events, B1), _first(all_events, B2)
    junda_b1 = [row for row in b1 if row["security_id"] == JUNDA]
    refs = parse_exclusions(root / EXCLUSION, prices)
    clean_b1, exclusion = screen_clean(
        [row for row in b1 if row["fold"] == "OOT" and row["security_id"] != JUNDA], refs, B1,
    )
    clean_kb = [r for r in clean_b1 if r["kb_subset"]]
    selection = _choose_images(clean_b1, by_stock, prices)
    write_json(output / SELECT_FILE, selection)
    write_csv(output / "ACT081_P1_TRACK_LEDGER.csv", all_events)
    write_csv(output / "ACT081_P1_PREFIX_AUDIT.csv", prefixes)
    write_csv(output / "ACT081_P1_TRACK_FLOWS.csv", flows)
    write_csv(output / "ACT081_P1_TIME_BOUNDARIES.csv", boundary_rows)
    joined = {(r["security_id"], r["D"], r["structure_episode_id"]) for r in original}
    intersection = {
        track: sum((row["security_id"], row["D"], row["structure_episode_id"]) in joined for row in rows)
        for track, rows in ((B1, b1), (B2, b2))
    }

    legacy = legacy_rows(baseline, prices)
    legacy_a = [row for row in legacy if row["role"] == "FIRST" and row["legacy_A"]]
    junda_v21 = [row for row in legacy_a if row["security_id"] == JUNDA]
    clean_v21, legacy_exclusion = screen_clean(
        [row for row in legacy_a if row["fold"] == "OOT" and row["security_id"] != JUNDA], refs, LEGACY,
    )
    if any(screen_clean(group, refs, policy)[1] for policy, group in ((B1, clean_b1), (LEGACY, clean_v21))):
        raise ValueError("Clean OOT residual exclusion match")
    if any(row["security_id"] == JUNDA for row in (*clean_b1, *clean_v21)):
        raise ValueError("Junda leaked into the 40-stock comparison")
    write_csv(output / "ACT081_P1_CLEAN_OOT_EXCLUSION_PROOF.csv", exclusion + legacy_exclusion)
    clean = {B1: clean_b1, KB: clean_kb, LEGACY: clean_v21}
    junda = {B1: junda_b1, KB: [r for r in junda_b1 if r["kb_subset"]], LEGACY: junda_v21}
    outcome_start = perf_counter()
    for group in (clean_b1, clean_v21, junda_b1, junda_v21):
        attach_outcomes(group, prices)
    junda_partitioned = {}
    cutoff = dict(zip(("TRAIN", "VAL"), BOUNDARIES, strict=True))
    for fold in ("TRAIN", "VAL", "OOT", "EXCLUDED"):
        junda_partitioned[fold] = {}
        for policy, rows in junda.items():
            partition = [dict(row) for row in rows if row["fold"] == fold]
            attach_outcomes(partition, prices, cutoff.get(fold))
            junda_partitioned[fold][policy] = summary(partition)
    robust, loso, sensitivity = robustness(clean, stocks, B1)
    cases, tallies = _case_records(
        [r for r in all_daily if r["security_id"] == JUNDA],
        [r for r in all_events if r["security_id"] == JUNDA],
        [r for r in legacy if r["security_id"] == JUNDA],
        prices[JUNDA],
    )
    write_csv(output / "ACT081_P1_CLEAN_OOT_DETAIL.csv", (
        {"policy": key, **row} for key, rows in clean.items() for row in rows
    ))
    write_csv(output / "ACT081_P1_JUNDA_FIRST_DETAIL.csv", (
        {"policy": key, **row} for key, rows in junda.items() for row in rows
    ))
    write_csv(output / "ACT081_P1_JUNDA_7_CASES.csv", cases)
    write_csv(output / "ACT081_P1_ROBUSTNESS.csv", robust)
    write_csv(output / "ACT081_P1_LEAVE_ONE_STOCK_OUT.csv", loso)
    feature_parts = []
    for chain, result in zip(chains, results, strict=True):
        expected = result[0]
        path = features_dir / f"{chain.security_id}.csv"
        with path.open(encoding="utf-8", newline="") as source:
            reader = csv.DictReader(source)
            schema = reader.fieldnames
            for actual, row in zip(reader, expected, strict=True):
                if actual != {key: "" if value is None else str(value) for key, value in row.items()}:
                    raise ValueError(f"feature partition value parity failure: {chain.security_id}")
        if not 0 < path.stat().st_size <= 9_500_000:
            raise ValueError("feature partition byte cap failure")
        feature_parts.append({
            "file": f"features/{path.name}", "rows": len(expected), "bytes": path.stat().st_size,
            "sha256": digest(path), "schema": schema,
        })
    if any(item["schema"] != feature_parts[0]["schema"] for item in feature_parts):
        raise ValueError("feature stock partition schema drift")
    metrics = {
        "governance": GOVERNANCE,
        "pre_evaluation_lock_sha256": digest(lock_path), "sample_selection_sha256": digest(output / SELECT_FILE),
        "input_hashes": locked["signed_input_hashes"], "p1b_member_hashes_verified": locked["p1b_member_hashes_verified"],
        "p1b_imported_runtime_hashes": locked["p1b_imported_runtime_hashes"],
        "frozen_baseline_sha256": digest(baseline), "VOL2": verified_vol2.evidence,
        "feature_parts": feature_parts,
        "NA": {"all_observed_bars": _na(all_daily), "raw_tracks": _na(all_events), "clean_b1": _na(clean_b1)},
        "prefix": {"chains": len(chains), "checks": len(prefixes), **dict(errors)},
        "cooldown": cooldown, "track_flows": flows, "p1b_first_identity_intersection": intersection,
        "clean_scope": {
            "stock_roster": stocks, "reference_cases": sum(map(len, refs.values())), "residual_matches": 0,
            "b1_oot_first_including_junda": sum(r["fold"] == "OOT" for r in b1),
            "b1_oot_first_junda_separated": sum(r["fold"] == "OOT" for r in junda_b1),
            "b1_oot_72_case_excluded": len({r["candidate_event_id"] for r in exclusion}),
            "v21_oot_72_case_excluded": len({r["candidate_event_id"] for r in legacy_exclusion}),
        },
        "clean_oot": {key: summary(rows) for key, rows in clean.items()},
        "robustness": sensitivity,
        "junda_all_history": {key: summary(rows) for key, rows in junda.items()},
        "junda_by_fold": junda_partitioned,
        "junda_case_tallies": tallies,
        "chart_selection": {"junda": 7, "clean_oot": len(selection["rows"]) - 7},
        "runtime": {
            "logical_cpu": os.cpu_count(), "configured_workers": workers, "peak_parent_rss_bytes": _peak_rss_bytes(),
            "replay_including_prefix_seconds": replay_seconds,
            "post_selection_reporting_seconds": perf_counter() - outcome_start,
            "total_seconds": perf_counter() - start,
        },
    }
    write_json(output / "ACT081_P1_METRICS.json", metrics)
    print(f"ACT081 analytics complete. Prefix={len(prefixes)}. B1 Clean FIRST={len(clean_b1)}. PNG selection={len(selection['rows'])}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--vol2", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    if args.mode == "freeze":
        contents = lock_contents(args.root)
        args.output.mkdir()
        claim(args.output / LOCK_FILE, **contents)
        print(f"0-FIT method freeze SHA-256 {digest(args.output / LOCK_FILE)}")
    else:
        if args.vol2 is None or args.baseline is None or args.workers < 1:
            parser.error("run requires --vol2, --baseline and a positive --workers")
        run(args.root, args.output, args.vol2, args.baseline, args.workers)


if __name__ == "__main__":
    main()
