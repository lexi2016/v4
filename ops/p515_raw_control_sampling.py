#!/usr/bin/env python3
"""Freeze a metadata-only P5.15 RAW control sample before opening price rows.

This task-scoped utility reads only the R1.3 sample-frame CSV and two existing
exposure manifests. It does not resolve, open, or inspect any RAW source.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_FRAME_SHA256 = "d5121c91395cc342ebe9d3c2b732c2534dc9e8de3735656f4f79457ab4be1ae9"
EXPECTED_COHORT_ROLE = "NATIVE_NON_BUY_WITH_ARCHIVE_NON_CONF"
EXPECTED_COHORT_N = 2325
EXPECTED_MARKETS = ("SH", "SZ", "BJ")
EXPECTED_MONTHS = ("202609", "202610", "202611")
SEED = "P515_R1_3_RAW_CONTROL_BATCH01_FIXED_SEED_20261113_V1"
PRIMARY_PER_MARKET_MONTH = 10
P1_COLUMN = "inclusion_probability"

PROXY_TO_GROUP = {
    "ORDINARY_REBOUND_PROXY": "REBOUND_OR_DOWNTREND",
    "DOWNTREND_CONTINUATION_PROXY": "REBOUND_OR_DOWNTREND",
    "TREND_CONSOLIDATION_PROXY": "TREND_OR_STRENGTH",
    "STRONG_STOCK_D_ONLY_PROXY": "TREND_OR_STRENGTH",
    "FALSE_INTRADAY_BREAKOUT_PROXY": "BREAKOUT_OR_FAILURE",
    "BREAKOUT_FAILURE_NEXT_SESSION_PROXY": "BREAKOUT_OR_FAILURE",
    "FAILURE_STOCK_D_ONLY_PROXY": "BREAKOUT_OR_FAILURE",
    "HIGH_VOLUME_AT_HIGH_PROXY": "HIGH_VOLUME_OR_REVERSAL_RISK",
    "HIGH_INTRADAY_REVERSAL_PROXY": "HIGH_VOLUME_OR_REVERSAL_RISK",
    "NO_OBVIOUS_ATTACK_10D_PROXY": "NO_ATTACK_OR_OTHER",
    "OTHER_NON_SIGNAL_PROXY": "NO_ATTACK_OR_OTHER",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    return rows, fields


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})


def allocate_quota(counts: dict[str, int], seats: int) -> dict[str, int]:
    """Hamilton allocation with one seat per present group and capacity caps."""
    groups = sorted(k for k, n in counts.items() if n > 0)
    if len(groups) > seats:
        raise ValueError(f"{len(groups)} proxy groups exceed {seats} seats")
    quota = {g: 1 for g in groups}
    remaining = seats - len(groups)
    while remaining:
        capacity = {g: counts[g] - quota[g] for g in groups if quota[g] < counts[g]}
        capacity_total = sum(capacity.values())
        if capacity_total < remaining:
            raise ValueError(f"quota capacity {capacity_total} below remaining seats {remaining}")
        exact = {g: remaining * capacity[g] / capacity_total for g in capacity}
        base = {g: min(capacity[g], int(exact[g])) for g in capacity}
        used = sum(base.values())
        for g, n in base.items():
            quota[g] += n
        remaining -= used
        if remaining:
            ranked = sorted(
                (g for g in capacity if quota[g] < counts[g]),
                key=lambda g: (-(exact[g] - int(exact[g])), g),
            )
            if not ranked:
                raise ValueError("no remaining capacity while seats remain")
            for g in ranked[:remaining]:
                quota[g] += 1
            remaining = 0
    if sum(quota.values()) != seats or any(quota[g] > counts[g] for g in quota):
        raise AssertionError(f"invalid quota allocation: {quota}")
    return quota


def key_for(row: dict[str, str]) -> tuple[str, str]:
    return row["stable_security_id"].strip(), row["observation_date"].strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frame", type=Path, default=Path(
        "/Users/lexi/Desktop/学习/v4_app/artifacts/p5_15_local_training_20261113/"
        "stage5_r1_3_20261113/FULL_A_UNIVERSE_NEGATIVE_SAMPLE_FRAME.csv"
    ))
    ap.add_argument("--h1-manifest", type=Path, default=Path(
        "/Users/lexi/Desktop/学习/v4_app/artifacts/p5_15_local_training_20261113/"
        "stage5_r1_3_20261113/H1_R1_3_ADJUDICATION/INPUT_MANIFEST.csv"
    ))
    ap.add_argument("--sup-raw-manifest", type=Path, default=Path(
        "/Users/lexi/Desktop/学习/v4_app/artifacts/p5_15_local_training_20261113/"
        "stage5_r1_3_20261113/SUP_RAW_14_EXPORT_MANIFEST.csv"
    ))
    ap.add_argument("--output-dir", type=Path, default=Path(
        "/Users/lexi/Desktop/学习/v4_app/artifacts/p5_15_local_training_20261113/"
        "stage5_r1_3_20261113/raw_control_batch01_20261113"
    ))
    args = ap.parse_args()

    frame_sha = sha256_file(args.frame)
    if frame_sha != EXPECTED_FRAME_SHA256:
        raise SystemExit(f"frame SHA mismatch: expected {EXPECTED_FRAME_SHA256}, got {frame_sha}")
    frame_rows, frame_fields = read_csv(args.frame)
    if P1_COLUMN not in frame_fields:
        raise SystemExit(f"missing stage-one inclusion probability column {P1_COLUMN}")
    eligible = [r for r in frame_rows if r.get("research_sample_role") == EXPECTED_COHORT_ROLE]
    if len(eligible) != EXPECTED_COHORT_N:
        raise SystemExit(f"expected {EXPECTED_COHORT_N} exact-role rows, got {len(eligible)}")

    # Only manifest rows/identities are read here; their referenced RAW files are not opened.
    h1_rows, _ = read_csv(args.h1_manifest)
    sup_rows, _ = read_csv(args.sup_raw_manifest)
    h1_keys = {(r["stable_security_id"].strip(), r["observation_date"].strip()) for r in h1_rows}
    sup_keys = {(r["stable_security_id"].strip(), r["observation_date"].strip()) for r in sup_rows}
    if len(h1_keys) != len(h1_rows) or len(sup_keys) != len(sup_rows):
        raise SystemExit("duplicate stable_security_id+observation_date in prior exposure manifest")
    if h1_keys & sup_keys:
        raise SystemExit(f"prior manifests overlap on {len(h1_keys & sup_keys)} observation keys")
    prior_keys = h1_keys | sup_keys
    cohort_keys = [key_for(r) for r in eligible]
    if len(set(cohort_keys)) != len(cohort_keys):
        raise SystemExit("duplicate stable_security_id+observation_date within exact candidate cohort")
    overlaps = set(cohort_keys) & prior_keys
    if overlaps:
        raise SystemExit(f"candidate cohort reuses {len(overlaps)} prior exposure keys")

    expected_cells = {(m, month) for m in EXPECTED_MARKETS for month in EXPECTED_MONTHS}
    cell_rows: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    unknown_shapes = Counter()
    shape_group_counts = Counter()
    stage1_p1: dict[tuple[str, str], float] = {}
    prior_dates_by_security: dict[str, list[str]] = defaultdict(list)
    for k in prior_keys:
        prior_dates_by_security[k[0]].append(k[1])

    for row in eligible:
        sec, day = key_for(row)
        exchange = row.get("exchange", "").strip()
        month = day[:6]
        shape = row.get("proxy_category", "").strip()
        if exchange not in EXPECTED_MARKETS or month not in EXPECTED_MONTHS:
            raise SystemExit(f"unexpected exchange/month in exact cohort: {exchange}/{month}/{sec}/{day}")
        if shape not in PROXY_TO_GROUP:
            unknown_shapes[shape or "<EMPTY>"] += 1
            continue
        try:
            p1 = float(row[P1_COLUMN])
        except (TypeError, ValueError):
            raise SystemExit(f"invalid stage-one probability for {sec} {day}: {row.get(P1_COLUMN)!r}")
        if not (0 < p1 <= 1):
            raise SystemExit(f"stage-one probability outside (0,1] for {sec} {day}: {p1}")
        row["freeze_market_month"] = month
        row["freeze_proxy_group"] = PROXY_TO_GROUP[shape]
        row["freeze_selection_key_sha256"] = hashlib.sha256(
            f"{SEED}|{sec}|{day}".encode("utf-8")
        ).hexdigest()
        row["freeze_rank_key_sha256"] = hashlib.sha256(
            f"{SEED}|rank|{exchange}|{month}|{PROXY_TO_GROUP[shape]}|{sec}|{day}".encode("utf-8")
        ).hexdigest()
        row["same_security_as_prior_exposure"] = "TRUE" if sec in prior_dates_by_security else "FALSE"
        row["prior_exposure_dates_same_security"] = ";".join(sorted(prior_dates_by_security.get(sec, [])))
        row["exact_key_in_prior_exposure_manifest"] = "FALSE"
        row["freeze_input_state"] = "METADATA_ONLY_RAW_NOT_OPENED"
        row["selection_seed"] = SEED
        row["proxy_group_mapping"] = PROXY_TO_GROUP[shape]
        cell_rows[(exchange, month)].append(row)
        shape_group_counts[(exchange, month, shape)] += 1
        stage1_p1[(sec, day)] = p1
    if unknown_shapes:
        raise SystemExit(f"unmapped proxy shapes: {dict(unknown_shapes)}")
    if set(cell_rows) != expected_cells:
        raise SystemExit(f"market-month cell mismatch: expected {sorted(expected_cells)}, got {sorted(cell_rows)}")

    all_ranked: list[dict[str, Any]] = []
    allocations: dict[str, Any] = {}
    for market in EXPECTED_MARKETS:
        for month in EXPECTED_MONTHS:
            rows = cell_rows[(market, month)]
            if len(rows) < PRIMARY_PER_MARKET_MONTH:
                raise SystemExit(f"insufficient rows in {market}/{month}: {len(rows)}")
            grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in rows:
                grouped[row["freeze_proxy_group"]].append(row)
            counts = {g: len(v) for g, v in grouped.items()}
            quotas = allocate_quota(counts, PRIMARY_PER_MARKET_MONTH)
            allocations[f"{market}|{month}"] = {
                "cohort_n": len(rows),
                "proxy_group_counts": dict(sorted(counts.items())),
                "primary_quota_by_proxy_group": dict(sorted(quotas.items())),
            }
            for group, group_rows in grouped.items():
                group_rows.sort(key=lambda r: (r["freeze_rank_key_sha256"], key_for(r)))
                n_group = len(group_rows)
                q_group = quotas[group]
                p2 = q_group / n_group
                for rank, row in enumerate(group_rows, start=1):
                    sec, day = key_for(row)
                    row["freeze_stratum"] = f"{market}|{month}|{group}"
                    row["freeze_stratum_population_n"] = n_group
                    row["freeze_stratum_primary_quota_n"] = q_group
                    row["freeze_rank_within_stratum"] = rank
                    row["p1_stage1_nominal_inclusion_probability"] = f"{stage1_p1[(sec, day)]:.16g}"
                    row["p2_stage2_nominal_inclusion_probability"] = f"{p2:.16g}"
                    row["combined_nominal_inclusion_probability"] = f"{stage1_p1[(sec, day)] * p2:.16g}"
                    if rank <= q_group:
                        row["frozen_selection_status"] = "PRIMARY_SELECTED"
                        row["primary_slot"] = rank
                        row["conditional_replacement_status"] = "NOT_APPLICABLE_PRIMARY"
                        row["conditional_replacement_order"] = ""
                        row["conditional_replacement_probability"] = "NOT_ESTIMATED_ADAPTIVE_FAILURE_DEPENDENT"
                    else:
                        row["frozen_selection_status"] = "FROZEN_REPLACEMENT_ORDER"
                        row["primary_slot"] = ""
                        row["conditional_replacement_status"] = "ORDER_ONLY_IF_PRIMARY_IN_SAME_STRATUM_FAILS"
                        row["conditional_replacement_order"] = rank - q_group
                        row["conditional_replacement_probability"] = "NOT_ESTIMATED_ADAPTIVE_FAILURE_DEPENDENT"
                    all_ranked.append(row)

    primary = [r for r in all_ranked if r["frozen_selection_status"] == "PRIMARY_SELECTED"]
    reserves = [r for r in all_ranked if r["frozen_selection_status"] == "FROZEN_REPLACEMENT_ORDER"]
    if len(primary) != 90 or len(reserves) != EXPECTED_COHORT_N - 90:
        raise AssertionError(f"expected 90 primary and 2235 reserve rows, got {len(primary)}/{len(reserves)}")
    primary.sort(key=lambda r: (r["exchange"], r["freeze_market_month"], r["freeze_stratum"], int(r["primary_slot"])))
    reserves.sort(key=lambda r: (r["exchange"], r["freeze_market_month"], r["freeze_stratum"], int(r["conditional_replacement_order"])))
    all_ranked.sort(key=lambda r: (r["exchange"], r["freeze_market_month"], r["freeze_stratum"], int(r["freeze_rank_within_stratum"])))

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    extra_fields = [
        "freeze_market_month", "freeze_proxy_group", "freeze_selection_key_sha256",
        "freeze_rank_key_sha256", "same_security_as_prior_exposure",
        "prior_exposure_dates_same_security", "exact_key_in_prior_exposure_manifest",
        "freeze_input_state", "selection_seed", "proxy_group_mapping", "freeze_stratum",
        "freeze_stratum_population_n", "freeze_stratum_primary_quota_n",
        "freeze_rank_within_stratum", "p1_stage1_nominal_inclusion_probability",
        "p2_stage2_nominal_inclusion_probability", "combined_nominal_inclusion_probability",
        "frozen_selection_status", "primary_slot", "conditional_replacement_status",
        "conditional_replacement_order", "conditional_replacement_probability",
    ]
    fields = list(frame_fields) + [x for x in extra_fields if x not in frame_fields]
    primary_path = out / "PREFROZEN_PRIMARY_90.csv"
    reserves_path = out / "PREFROZEN_RESERVE_ORDER_2235.csv"
    all_path = out / "PREFROZEN_ALL_RANKS_2325.csv"
    write_csv(primary_path, primary, fields)
    write_csv(reserves_path, reserves, fields)
    write_csv(all_path, all_ranked, fields)

    script_path = Path(__file__).resolve()
    freeze = {
        "freeze_id": "P515_RAW_CONTROL_BATCH01_R1_3_20261113",
        "freeze_created_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_seed": SEED,
        "status": "FROZEN_BEFORE_RAW_PRICE_ROWS_OPENED",
        "scope": "METADATA_ONLY_SAMPLE_SELECTION_AND_REPLACEMENT_ORDER",
        "source_frame": {
            "path": str(args.frame),
            "sha256": frame_sha,
            "rows_total": len(frame_rows),
            "exact_role_filter": EXPECTED_COHORT_ROLE,
            "cohort_rows": len(eligible),
            "stage1_probability_column": P1_COLUMN,
        },
        "prior_exposure_manifests": [
            {"path": str(args.h1_manifest), "sha256": sha256_file(args.h1_manifest), "rows": len(h1_rows), "unique_observation_keys": len(h1_keys)},
            {"path": str(args.sup_raw_manifest), "sha256": sha256_file(args.sup_raw_manifest), "rows": len(sup_rows), "unique_observation_keys": len(sup_keys)},
        ],
        "prior_exposure_dedup": {
            "key": "stable_security_id+observation_date",
            "prior_unique_rows": len(prior_keys),
            "overlap_between_prior_manifests": 0,
            "candidate_cohort_overlap": 0,
            "same_security_different_date": "RECORDED_PER_CANDIDATE_ROW; NOT TREATED AS SAME OBSERVATION",
        },
        "design": {
            "stage1_probability_source": "Carried unchanged from original sample-frame inclusion_probability; this is the sample-frame design probability, not a claim of full-market inclusion probability.",
            "stage2_population": "Exact 2325-row role cohort in the 6000-row frame.",
            "month_coverage": list(EXPECTED_MONTHS),
            "markets": list(EXPECTED_MARKETS),
            "quota_per_market_month": PRIMARY_PER_MARKET_MONTH,
            "primary_total": len(primary),
            "reserve_order_total": len(reserves),
            "proxy_group_mapping": PROXY_TO_GROUP,
            "probability_interpretation": "p2=q/N is a nominal design inclusion rate within each frozen market-month-proxy-group stratum. Combined nominal probability is p1*p2. This is not a population estimator or generalization claim. Adaptive replacements have no fabricated realized probability; their frozen order and conditional trigger are recorded.",
            "cell_allocations": allocations,
        },
        "blindness_and_execution_boundary": {
            "raw_price_bytes_opened": False,
            "source_raw_file_resolver_invoked": False,
            "d_only_input_export_started": False,
            "candidate_source_proxy_metadata_seen_by_sampler": True,
            "selected_labels_or_future_returns_used": False,
            "fit_count": 0,
            "new_prediction_count": 0,
            "production_allowed": False,
        },
        "selection_script": {"path": str(script_path), "sha256": sha256_file(script_path)},
        "output_files": {
            "primary": primary_path.name,
            "reserves": reserves_path.name,
            "all_ranked": all_path.name,
        },
    }
    freeze_path = out / "SAMPLE_SELECTION_FREEZE.json"
    freeze_path.write_text(json.dumps(freeze, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    sums_path = out / "SHA256SUMS_PRE_RAW_FREEZE.txt"
    files = [primary_path, reserves_path, all_path, freeze_path]
    sums_path.write_text("".join(f"{sha256_file(p)}  {p.name}\n" for p in files), encoding="utf-8")

    # Verify the frozen bytes and mechanical quotas after writing.
    primary_check, _ = read_csv(primary_path)
    reserves_check, _ = read_csv(reserves_path)
    all_check, _ = read_csv(all_path)
    assert len(primary_check) == 90 and len(reserves_check) == 2235 and len(all_check) == 2325
    assert len({(r["stable_security_id"], r["observation_date"]) for r in primary_check}) == 90
    assert Counter((r["exchange"], r["freeze_market_month"]) for r in primary_check) == Counter(
        {(m, month): PRIMARY_PER_MARKET_MONTH for m in EXPECTED_MARKETS for month in EXPECTED_MONTHS}
    )
    assert not ({(r["stable_security_id"], r["observation_date"]) for r in primary_check} & prior_keys)
    print(json.dumps({
        "status": "FROZEN_BEFORE_RAW_PRICE_ROWS_OPENED",
        "primary_n": len(primary_check),
        "reserve_n": len(reserves_check),
        "all_ranked_n": len(all_check),
        "primary_by_exchange_month": {f"{k[0]}|{k[1]}": v for k, v in sorted(Counter((r["exchange"], r["freeze_market_month"]) for r in primary_check).items())},
        "output_dir": str(out),
        "sha256sums": str(sums_path),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
