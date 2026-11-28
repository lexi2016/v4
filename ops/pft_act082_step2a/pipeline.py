"""A fail-closed DEV preparation entry point. SEALED authorization is separate."""

from argparse import ArgumentParser
from collections import Counter
from csv import DictWriter
from hashlib import sha256
from io import StringIO
from pathlib import Path
from random import Random
from dataclasses import replace
from time import monotonic
import json
import os

from .calendar import build_labels, verify_actual_intervals
from .evidence import canonical_json, evidence_payload, PROTOCOL, QUALITY_TIER
from .sampling import B_COVERAGE, sample_frame, private_rows, SEED
from .sources import digest, load_dev, verified_inputs, verified_qfq_basis
from .vault import require_private_directory, write_new
from .waves import dev_frame, vault_b_cooldown

DEV_POOL_NAME = "DEV_POOL"
DEBUG_POOL_NAME = "DEBUG_ONLY_JUNDA"
VAULT_A = "ACT082_VAULT_A_STRUCTURAL_TRUTH"
VAULT_B = "ACT082_VAULT_B_OUTCOME_AND_EXEC"
FRAME_NAME = "SAMPLING_FRAME_MANIFEST.csv"
QFQ = "QFQ_VERSION_REGISTER.json"
TEMPORAL_DIAGNOSTIC_START = "2024-10-01"
STOCK_DIAGNOSTIC_FOLDS = 5


def _csv_bytes(rows):
    rows = list(rows)
    if not rows:
        raise ValueError("required CSV has no records")
    keys = list(dict.fromkeys(k for row in rows for k in row))
    stream = StringIO(newline="")
    writer = DictWriter(stream, keys, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _sources_sha():
    import_root = Path(__file__).resolve().parent.parent
    names = ("pft_act082_step2a", "pft_act080_core", "pft_act080_p2", "pft_act081_kb")
    bound = {}
    for name in names:
        package = import_root / name
        for path in sorted(package.glob("*.py")):
            bound[f"{name}/{path.name}"] = digest(path)
    core_config = import_root / "pft_act080_core" / "config.json"
    bound["pft_act080_core/config.json"] = digest(core_config)
    return sha256(canonical_json(bound)).hexdigest()


def require_prepared_source(lock):
    actual = _sources_sha()
    if lock.get("source_code_sha256") != actual:
        raise ValueError("prepared source code hash mismatch")
    return actual


def diagnostics_by_stock(stocks):
    order = sorted(set(stocks))
    if len(order) != 40:
        raise ValueError("stock diagnostic requires the 40 distinct DEV instruments")
    Random(SEED).shuffle(order)
    folds = {stock: rank % STOCK_DIAGNOSTIC_FOLDS + 1 for rank, stock in enumerate(order)}
    return dict(sorted(folds.items()))


def temporal_diagnostic(actual):
    if actual["mother_start_date"] >= TEMPORAL_DIAGNOSTIC_START:
        return "RECENT_DIAGNOSTIC", False
    crosses = actual["D"] < TEMPORAL_DIAGNOSTIC_START <= actual["label_end_date_actual"]
    if actual["label_end_date_actual"] >= TEMPORAL_DIAGNOSTIC_START:
        return "PURGED_FROM_TEMPORAL_SPLIT_DIAGNOSTIC", crosses
    return "DEV_EARLY", False


def _mutate_future_only(bars, D):
    """Perturb all subsequent bar fields without changing the D or earlier data."""
    return tuple(replace(
        bar, open=bar.open * 1.61, high=bar.high * 1.61, low=bar.low * 1.61,
        close=bar.close * 1.61, volume=bar.volume * 3.0 + 177771.0,
    ) if bar.trade_date > D else bar for bar in bars)


def _projected_records(phases, chains, calendars, suspensions):
    for row, candidate in phases:
        bars = chains[candidate.security_id].bars
        cal = calendars[candidate.security_id[-2:]]
        known_halts = suspensions.get(candidate.security_id, frozenset())
        truncated = tuple(bar for bar in bars if bar.trade_date <= candidate.D)
        plain = evidence_payload(bars, candidate, cal, known_halts)
        control = evidence_payload(truncated, candidate, cal, known_halts)
        treatment = evidence_payload(_mutate_future_only(bars, candidate.D), candidate, cal, known_halts)
        bodies = [canonical_json(item) for item in (plain, control, treatment)]
        if not all(body == bodies[0] for body in bodies[1:]):
            raise ValueError("prefix truncation or post-D numeric perturbation changed D evidence")
        if len(truncated) == len(bars):
            raise ValueError("no real pre-DEV-cutoff post-D perturbation bars")
        yield {"blind_id": row["blind_id"], "phase": row["phase"], "evidence": plain, "batch": row["batch"]}


def prep_dev(root, vol2, p1b, exclusion, output, *, owner_basis_reference, suspension_facts=None):
    started = monotonic()
    prepared_source = _sources_sha()
    refs = verified_inputs(root, p1b, exclusion)
    qfq = verified_qfq_basis(owner_basis_reference)
    output = require_private_directory(output)
    dev = require_private_directory(output / DEV_POOL_NAME)
    private = require_private_directory(output / VAULT_B)
    debug = require_private_directory(output / DEBUG_POOL_NAME)
    write_new(debug / "POOL_STATE.json", canonical_json({
        "pool": DEBUG_POOL_NAME, "instrument": "002865.SZ", "whole_stock": True,
        "status": "DEFERRED_TO_ISOLATED_DEBUG", "data_loaded": 0, "pngs": 0,
    }))
    chains, calendars, source = load_dev(vol2, prepared_source)
    suspensions = suspension_facts or {}
    frame, intervals, raw, unavailable = dev_frame(chains, calendars, suspensions)
    draw = sample_frame(frame, seed=SEED)
    rows, relabel = private_rows(draw)
    pairs = list(zip(rows, [candidate for phase in ("formal", "pilot") for candidate, _ in draw["selected"][phase]],
                     strict=True))
    frame_path = private / FRAME_NAME
    write_new(frame_path, _csv_bytes(rows))
    frame_sha = digest(frame_path)
    write_new(private / "SAMPLING_STRATUM_POPULATIONS.csv", _csv_bytes(draw["strata"]))
    write_new(private / "SAMPLING_ELIGIBLE_RAW_GROUPS.csv", _csv_bytes({
        "wave_group_id": group, "bucket_eligibility": "B" if bucket in B_COVERAGE["formal"] else bucket,
        "coverage_subtype": bucket if bucket in B_COVERAGE["formal"] else "",
        "security_id": candidate.security_id,
        "mother_start_date": candidate.mother_start_date, "D": candidate.D, "source_rule": candidate.source_rule,
    } for group, reps in sorted(frame.items()) for bucket, candidate in sorted(reps.items())))
    write_new(private / "PREREGISTERED_AGREEMENT_AUDIT.csv", _csv_bytes({
        "blind_id": row["blind_id"], "batch": row["batch"],
    } for row in rows if row["agreement_audit_preregistered"]))
    write_new(private / "PREREGISTERED_RELABEL_JOIN.csv", _csv_bytes(relabel))
    lock = {
        "seed": SEED, "sha256": frame_sha, "rows": len(rows), "stock_cap_formal": 8,
        "source_code_sha256": prepared_source, "probability_contract": draw["probability_design"],
        "qfq_basis_sha256": sha256(canonical_json(qfq)).hexdigest(),
        "direct_join_sha256": digest(private / "PREREGISTERED_RELABEL_JOIN.csv"),
        "audit_sha256": digest(private / "PREREGISTERED_AGREEMENT_AUDIT.csv"),
    }
    require_prepared_source(lock)
    write_new(private / QFQ, canonical_json(qfq))
    write_new(private / "PRE_RENDER_LOCK.json", canonical_json(lock))
    if digest(frame_path) != frame_sha:
        raise ValueError("sampling frame changed before loading chart inputs")
    # All label values and execution flags are downstream of the physical sampling lock.
    cooldown = vault_b_cooldown(raw)
    by_stock = {chain.security_id: chain for chain in chains}
    folds = diagnostics_by_stock(by_stock)
    write_new(private / "PREREGISTERED_STOCK_FOLDS.csv", _csv_bytes({
        "security_id": stock, "stock_diagnostic_fold": fold,
    } for stock, fold in folds.items()))
    bars_by_stock = {stock: {bar.trade_date: bar for bar in chain.bars} for stock, chain in by_stock.items()}
    outcomes = []
    for row, candidate in pairs:
        actual = build_labels(candidate, bars_by_stock[candidate.security_id], calendars[candidate.security_id[-2:]],
                              suspensions.get(candidate.security_id, frozenset()), outcomes=True)
        if any(actual[key] != value for key, value in intervals[candidate].items()):
            raise ValueError("post-lock label dates fail pre-lock actual interval consistency")
        diag, label_crosses = temporal_diagnostic(actual)
        outcomes.append({
            "blind_id": row["blind_id"], "security_id": row["security_id"], "wave_group_id": row["wave_group_id"],
            "temporal_diagnostic": diag, "purged_early_label_crosses_temporal_boundary": label_crosses,
            "stock_diagnostic_fold": folds[row["security_id"]], **actual, **cooldown[candidate],
        })
    audit = verify_actual_intervals(outcomes)
    write_new(private / "OUTCOMES_EXEC_AND_ACTUAL_INTERVALS.csv", _csv_bytes(outcomes))
    if digest(frame_path) != frame_sha:
        raise ValueError("sampling manifest changed after outcomes")
    render_job = dev / "NUMERIC_RENDER_JOB.jsonl"
    with render_job.open("xb") as job:
        os.fchmod(job.fileno(), 0o600)
        for record in _projected_records(pairs, by_stock, calendars, suspensions):
            job.write(canonical_json(record))
    phase_counts = lambda phase, key: dict(sorted(Counter(
        str(row[key]) for row in rows if row["phase"] == phase
    ).items()))
    year_counts = {phase: dict(sorted(Counter(row["D"][:4] for row in rows if row["phase"] == phase).items()))
                   for phase in ("formal", "pilot")}
    receipt = {
        **refs, **source, **audit, "stage": "DEV_PREPARATION_ONLY", "sealed_ready": False,
        "cooldown_membership_dependencies": 0, "sampling_frame_sha256": frame_sha,
        "numeric_render_job_sha256": digest(render_job), "render_inputs": len(pairs), "fit": 0,
        "tuning": 0, "training": 0, "fit_allowed": False, "per_bucket_formal": phase_counts("formal", "bucket"),
        "per_bucket_pilot": phase_counts("pilot", "bucket"), "year_counts": year_counts,
        "B_coverage_quota_formal": dict(Counter(row["coverage_subtype"] for row in rows
                                               if row["phase"] == "formal" and row["bucket"] == "B")),
        "B_coverage_quota_pilot": dict(Counter(row["coverage_subtype"] for row in rows
                                              if row["phase"] == "pilot" and row["bucket"] == "B")),
        "max_formal_per_stock": max(phase_counts("formal", "security_id").values()),
        "distinct_formal_stocks": len(phase_counts("formal", "security_id")),
        "excluded_raw_proposals_by_reason": unavailable, "eligible_wave_groups": len(frame),
        "numeric_prefix_differences": 0, "numeric_perturbation_differences": 0,
        "protocol_id": PROTOCOL, "quality_tier": QUALITY_TIER, "wall_seconds": round(monotonic() - started, 6),
        "suspension_feed_supplied": bool(suspensions), "data_date_min": min(chain.bars[0].trade_date for chain in chains),
        "stock_diagnostic_fold_sizes": dict(Counter(folds.values())),
        "temporal_diagnostic_counts": dict(Counter(row["temporal_diagnostic"] for row in outcomes)),
        "early_labels_purged_from_temporal_diagnostic": sum(
            row["purged_early_label_crosses_temporal_boundary"] for row in outcomes),
    }
    require_prepared_source(lock)
    write_new(output / "DEV_PREPARATION_RECEIPT.json", canonical_json(receipt))
    return receipt


def main():
    parser = ArgumentParser(description=__doc__)
    for name in ("root", "vol2", "p1b", "exclusion", "output", "owner-basis-reference"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prep_dev(args.root, args.vol2, args.p1b, args.exclusion, args.output,
                              owner_basis_reference=args.owner_basis_reference), ensure_ascii=False))


if __name__ == "__main__":
    main()

