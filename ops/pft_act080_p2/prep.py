"""Prepare and seal non-Junda TRAIN/VAL FIRST features and historical labels."""

import argparse
from bisect import bisect_left
from collections import Counter
import math
from pathlib import Path
from time import perf_counter
from zipfile import ZipFile

import numpy as np

from .contracts import (
    FEATURE_SETS, JUNDA, METHOD, P1B, VOL2_SHA, claim, digest, seal, source_inventory, sync_directory, verify_signed, write_json,
)
from .outcomes import summarize
from .sources import attach_prices, first_rows, load_features, load_prices, validate_bundle


DEV_DIR = "dev_locked"
PREP_SEAL = "ACT080_P2_PREP_SEAL.json"


def mlp_train_partition(events, prices):
    """Use last 20% of unique TRAIN dates and a 10-observed-session buffer."""
    train_days = sorted({r["D"] for r in events if r["fold"] == "TRAIN"})
    cutoff = train_days[-math.ceil(len(train_days) * METHOD["family_parameters"]["MLP_MPS"]["stop_date_fraction"])]
    horizon = METHOD["horizon_sessions"]
    cut_ordinals = {stock: bisect_left(chain[0], cutoff) for stock, chain in prices.items()}
    groups = []
    for event in events:
        if event["fold"] != "TRAIN":
            groups.append("NOT_TRAIN")
            continue
        ordinal = cut_ordinals[event["security_id"]]
        distance = event["session_idx"] - ordinal
        if distance < -horizon:
            groups.append("GRADIENT")
        elif distance >= horizon:
            groups.append("EARLY_STOP")
        else:
            groups.append("INNER_PURGE" if distance < 0 else "INNER_EMBARGO")
    return cutoff, groups


def prep(run_root, vol2):
    started = perf_counter()
    signatures = verify_signed(run_root)
    claim(run_root / "PREP_CLAIM.json", stage="PREP", FIT=0, OOT_OPEN_COUNT=0)
    staging = run_root / ".prep_pending"
    stage = run_root / DEV_DIR
    if stage.exists():
        raise FileExistsError(stage)
    staging.mkdir(mode=0o700)
    with ZipFile(run_root / P1B) as archive:
        member_count = validate_bundle(archive)
        events = first_rows(archive, development_only=True)
        if Counter(r["fold"] for r in events) != {"TRAIN": 4129, "VAL": 342}:
            raise ValueError("wrong FIRST development sample counts")
        if any(r["security_id"] == JUNDA for r in events):
            raise ValueError("Junda identity reached the development projection")
        values = load_features(archive, events)
    prices = load_prices(vol2, development_only=True)
    attach_prices(events, prices, pricing=True)
    cutoff, partition = mlp_train_partition(events, prices)
    for row, group in zip(events, partition, strict=True):
        row["mlp_train_partition"] = group
    np.savez_compressed(staging / "TRAIN_VAL_X.npz", values=np.asarray(values, dtype=float))
    write_json(staging / "TRAIN_VAL_EVENTS.json", events)
    write_json(staging / "PREP_RECEIPT.json", {
        "phase": "PREP", "FIT": 0, "OOT_OPEN_COUNT": 0,
        "elapsed_seconds": perf_counter() - started,
        "signature_sha256": signatures,
        "p1b_verified_member_count": member_count,
        "vol2": {"sha256": VOL2_SHA, "bytes": Path(vol2).stat().st_size},
        "feature_sets": {k: list(v) for k, v in FEATURE_SETS.items()},
        "dev_roster": sorted(prices), "dev_roster_count": len(prices), "junda_rows": 0,
        "serialized_only": "FIRST non-Junda TRAIN and VAL allowlist features with outcomes before respective cutoffs",
        "dev": {fold: summarize([row for row in events if row["fold"] == fold]) for fold in ("TRAIN", "VAL")},
        "mlp_internal_cutoff": cutoff,
        "mlp_internal_partition": dict(Counter(partition)),
        "mlp_internal_mature": dict(Counter(
            row["mlp_train_partition"] for row in events if row["tail_std"] is not None
        )),
    })
    staging.rename(stage)
    sync_directory(run_root)
    prepared = seal(
        run_root / PREP_SEAL, stage, signed=signatures, code=source_inventory(prep_only=True),
        stage="PREP_SEALED", FIT=0, OOT_OPEN_COUNT=0,
    )
    return {"prep_seal_sha256": prepared, "TRAIN": 4129, "VAL": 342, "JUNDA": 0, "FIT": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--vol2", required=True, type=Path)
    args = parser.parse_args()
    print(prep(args.run_root.resolve(strict=True), args.vol2.resolve(strict=True)))


if __name__ == "__main__":
    main()
