"""Verify the signed fit lock, claim both holdouts once, and issue audited results."""

import argparse
from collections import Counter
from pathlib import Path
import re
from time import perf_counter
from zipfile import ZipFile

import numpy as np

from .contracts import (
    BASELINE_MEMBER_SHA, BASELINE_SHA, EXCLUSIONS, JUNDA, METHOD, P1B, VOL2_SHA, claim, digest,
    read_json, seal, source_inventory, sync_directory, verify, verify_payload, verify_signed, write_csv, write_json,
)
from .holdouts import junda_exact_D_ledger, legacy_rows, parse_exclusions, screen
from .model_io import replay_scores
from .outcomes import summarize
from .reporting import compare_clean, junda_cases, research_gate
from .sources import attach_prices, first_rows, load_features, load_prices, validate_bundle


FIT_DIR = "fit_locked"
FIT_LOCK = "ACT080_P2_PRE_OOT_MODEL_LOCK.json"
LEDGER = "ACT080_P2_FIT_LEDGER.csv"
ATTEMPTS = "FIT_ATTEMPTS"
PREP_SEAL = "ACT080_P2_PREP_SEAL.json"
RELEASE_DIR = "oot_issued"
RELEASE_SEAL = "ACT080_P2_OOT_RELEASE_SEAL.json"
OPEN_CLAIM = "OOT_OPEN_ONCE.json"
OPEN_STATUS = "ACT080_P2_OOT_STATUS.json"
CLEAN_PROOF = "ACT080_P2_CLEAN_OOT_EXCLUSION_PROOF.csv"
JUNDA_TABLE = "ACT080_P2_JUNDA_CASES.csv"
JUNDA_SERIES = "ACT080_P2_JUNDA_REVIEW_SERIES.csv"
JUNDA_TRIGGERS = "ACT080_P2_JUNDA_FIRST_COMPARATOR.csv"


def _verify_gate(root, model_sha):
    if not re.fullmatch("[0-9a-f]{64}", model_sha):
        raise ValueError("operator must supply the exact immutable pre-OOT seal checksum")
    signatures = verify_signed(root)
    lock = verify_payload(root / FIT_LOCK, root / FIT_DIR, model_sha)
    if (
        lock["stage"] != "PRE_OOT_MODEL_LOCKED" or lock["FIT"] != 8 or lock["OOT_OPEN_COUNT"] != 0
        or lock["signed"] != signatures or lock["code"] != source_inventory()
    ):
        raise ValueError("frozen FIT, signed source, and source code binding failed")
    verify(root / LEDGER, lock["fit_ledger_sha256"])
    verify(root / PREP_SEAL, lock["prep_seal_sha256"])
    attempts = root / ATTEMPTS
    if {p.name for p in attempts.iterdir()} != set(lock["fit_attempt_sha256"]):
        raise ValueError("unexpected FIT attempt ledger membership")
    for name, recorded in lock["fit_attempt_sha256"].items():
        verify(attempts / name, recorded)
    receipt = read_json(root / FIT_DIR / "FIT_RECEIPT.json")
    if receipt["fit_invoked"] != 8 or receipt["fit_failed"] != 0 or not receipt["selected_reload_exact"]:
        raise ValueError("frozen VALIDATION reload and FIT ledger gate failed")
    selected = read_json(root / FIT_DIR / "SELECTED_MODEL.json")
    return selected


def _rows_and_scores(root, scratch, python, vol2, selected):
    prices = load_prices(vol2, development_only=False)
    refs = parse_exclusions(root / EXCLUSIONS, prices)
    with ZipFile(root / P1B) as archive:
        validate_bundle(archive)
        rows = first_rows(archive, development_only=False)
        oot = [r for r in rows if r["fold"] == "OOT"]
        junda = [r for r in rows if r["security_id"] == JUNDA]
        junda_folds = Counter(r["fold"] for r in junda)
        if len(oot) != 826 or junda_folds != {"TRAIN": 78, "VAL": 5, "OOT": 15, "EXCLUDED": 1}:
            raise ValueError(f"frozen OOT/Junda FIRST cohort disagrees ({len(oot)}, {dict(junda_folds)})")
        after_72, proof = screen(oot, refs, "P1B_FIRST_OOT")
        clean = [r for r in after_72 if r["security_id"] != JUNDA]
        combined = clean + junda
        values = np.asarray(load_features(archive, combined), dtype=float)
        junda_exact = junda_exact_D_ledger(archive)
    scores = replay_scores(root / FIT_DIR / "weights" / selected["fit_id"], selected, values, python, scratch, "sealed_holdouts")
    attach_prices(combined, prices, pricing=False)
    for row, score in zip(combined, scores, strict=True):
        row.update(safety_score=float(score), threshold=selected["threshold"],
                   selected=float(score) >= selected["threshold"] and row["fold"] != "EXCLUDED")
    return prices, refs, clean, junda, junda_exact, proof, {
        "P1B_OOT_FIRST_original": len(oot),
        "excluded_by_signed_72_unique": len(oot) - len(after_72),
        "excluded_by_signed_72_pair_witnesses": len(proof),
        "remaining_after_72": len(after_72),
        "original_Junda_OOT_FIRST": junda_folds["OOT"],
        "Junda_removed_by_signed_72": junda_folds["OOT"] - sum(r["security_id"] == JUNDA for r in after_72),
        "Junda_separated_after_72": len(after_72) - len(clean),
        "clean_non_Junda": len(clean),
        "clean_non_Junda_sampled_stocks": len({r["security_id"] for r in clean}),
        "eligible_non_Junda_roster": len(set(prices) - {JUNDA}),
        "signed_samples_mapped_observed_ordinal": sum(map(len, refs.values())),
        "clean_overlap_proof_pairs_remaining": len(screen(clean, refs, "SELF_CHECK")[1]),
        "Junda_FIRST_full_by_fold": dict(junda_folds),
    }


def _issue(root, scratch, vol2, baseline, python, selected):
    prices, refs, clean, junda, exact, proof, flow = _rows_and_scores(root, scratch, python, vol2, selected)
    write_csv(scratch / CLEAN_PROOF, proof)
    write_json(scratch / "ACT080_P2_CLEAN_OOT_FLOW.json", flow)
    write_csv(scratch / "ACT080_P2_CLEAN_OOT_SCORE_DETAIL.csv", clean)
    write_csv(scratch / "ACT080_P2_JUNDA_LOCKED_SCORE_CHECKPOINT.csv", junda)
    prior = legacy_rows(baseline, prices)
    legacy_junda_all = [r for r in prior if r["security_id"] == JUNDA]
    legacy_junda = [r for r in legacy_junda_all if r["role"] == "FIRST"]
    legacy_non_junda = [r for r in prior if r["role"] == "FIRST" and r["security_id"] != JUNDA]
    old_oot_eligible = [r for r in legacy_non_junda if r["fold"] == "OOT"]
    old_oot, old_proof = screen(old_oot_eligible, refs, "V21_ALL_FIRST_OOT")
    old_a = [r for r in old_oot if r["legacy_A"]]
    attach_prices(old_oot + legacy_junda, prices, pricing=False)
    for event in legacy_junda:
        event["selected"] = event["legacy_A"] and event["fold"] != "EXCLUDED"
    selected_clean = [r for r in clean if r["selected"]]
    metrics, loso = compare_clean(selected_clean, old_a, old_oot, clean, prices)
    cases = junda_cases(exact, junda, legacy_junda_all, prices)
    write_csv(scratch / "ACT080_P2_V21_CLEAN_OOT_EXCLUSION_PROOF.csv", old_proof)
    write_csv(scratch / "ACT080_P2_V21_CLEAN_OOT_DETAIL.csv", old_oot)
    write_csv(scratch / "ACT080_P2_LOSO_SENSITIVITY.csv", loso)
    write_csv(scratch / JUNDA_TABLE, cases)
    write_csv(scratch / JUNDA_TRIGGERS, [{"policy": "P1B", **r} for r in junda]
              + [{"policy": "V21", **r} for r in legacy_junda])
    write_csv(scratch / JUNDA_SERIES, ({"D": day, "close_qfq": close} for day, close in zip(prices[JUNDA][0], prices[JUNDA][2], strict=True)))
    legacy_val = [r for r in legacy_non_junda if r["fold"] == "VAL"]
    attach_prices(legacy_val, prices, pricing=True)
    write_json(scratch / "ACT080_P2_VAL_POST_LOCK_BASELINE.json", {
        "basis": "post-lock comparison only; does not participate in model or threshold selection",
        "P1B_selected_operating_point": selected,
        "V21_grade_A_FIRST": summarize([r for r in legacy_val if r["legacy_A"]]),
        "V21_all_FIRST": summarize(legacy_val),
    })
    junda_overview = {
        "P1B_first_full": summarize(junda),
        "P1B_selected_full": summarize([r for r in junda if r["selected"]]),
        "P1B_first_OOT": summarize([r for r in junda if r["fold"] == "OOT"]),
        "P1B_selected_OOT": summarize([r for r in junda if r["fold"] == "OOT" and r["selected"]]),
        "V21_first_full": summarize(legacy_junda),
        "V21_A_selected_full": summarize([r for r in legacy_junda if r["selected"]]),
        "V21_first_OOT": summarize([r for r in legacy_junda if r["fold"] == "OOT"]),
        "V21_A_selected_OOT": summarize([r for r in legacy_junda if r["fold"] == "OOT" and r["selected"]]),
        "seven_cases_expected_direction": {
            "P1B": sum(r["P1B_expected_direction_match"] for r in cases),
            "V21_same_FIRST_policy_basis": sum(r["V21_expected_direction_match"] for r in cases),
            "V21_exact_A_any_role_reference": sum(r["V21_exact_A_expected_direction_match"] for r in cases),
            "total": len(cases),
        },
    }
    result = {
        "OOT_OPEN_COUNT": 1, "FIT": 8, "OOT_and_Junda_refit": 0, "junda_dev_use_count": 0,
        "model": selected, "clean_exclusion": flow, "legacy_clean": {
            "original_non_Junda_OOT_FIRST_before_72": len(old_oot_eligible),
            "excluded_unique": len(old_oot_eligible) - len(old_oot), "remaining": len(old_oot),
            "grade_A_FIRST": len(old_a), "archive_SHA256": BASELINE_SHA, "member_SHA256": BASELINE_MEMBER_SHA,
            "grade_A_exact": METHOD["frozen_baseline_a_tier"], "read_fields": ["D", "security_id", "structure_episode_id", "kb_anchor_date", "visual_tier"],
        },
        "statistics": metrics, "Junda": junda_overview, "promotion_research_gate": research_gate(metrics, cases),
        "governance": METHOD["governance"],
    }
    write_json(scratch / "ACT080_P2_FINAL_RESEARCH_METRICS.json", result)
    return result


def open_once(root, vol2, baseline, python, expected_lock):
    existing = root / OPEN_CLAIM
    if existing.exists():
        raise FileExistsError("OOT already claimed; repackage issued or partial outputs without reopening")
    selection = _verify_gate(root, expected_lock)
    verify(vol2, VOL2_SHA)
    verify(baseline, BASELINE_SHA)
    if not python.is_file():
        raise FileNotFoundError("verified MPS runtime path missing")
    if (root / RELEASE_DIR).exists() or (root / ".oot_pending").exists():
        raise FileExistsError("existing OOT output conflicts with exclusive opening")
    claim(existing, stage="CLEAN_OOT_AND_JUNDA_SHARED_OPEN", OOT_OPEN_COUNT=1,
          fit_lock_sha256=expected_lock, OOT_or_Junda_refit=0)
    started = perf_counter()
    location = root / ".oot_pending"
    write_json(root / OPEN_STATUS, {"status": "CLAIMED", "OOT_OPEN_COUNT": 1, "output": location.name})
    try:
        location.mkdir(mode=0o700)
        result = _issue(root, location, vol2, baseline, python, selection)
        location.rename(root / RELEASE_DIR)
        sync_directory(root)
        completed = seal(root / RELEASE_SEAL, root / RELEASE_DIR, stage="OPENED_ONCE_ISSUED",
                         fit_lock_sha256=expected_lock, open_claim_sha256=digest(existing), OOT_OPEN_COUNT=1,
                         vol2_sha256=VOL2_SHA, baseline_sha256=BASELINE_SHA, elapsed_seconds=perf_counter() - started)
        write_json(root / OPEN_STATUS, {"status": "ISSUED", "OOT_OPEN_COUNT": 1, "release_sha256": completed})
    except BaseException as exc:
        write_json(root / OPEN_STATUS, {
            "status": "PARTIAL_DO_NOT_REOPEN", "OOT_OPEN_COUNT": 1, "type": type(exc).__name__, "error": str(exc),
            "partial_output": RELEASE_DIR if (root / RELEASE_DIR).exists() else location.name,
            "elapsed_seconds": perf_counter() - started,
        })
        raise
    return {"release_sha256": completed, "OOT_OPEN_COUNT": 1, "clean_non_Junda": result["clean_exclusion"]["clean_non_Junda"],
            "research_status": result["promotion_research_gate"]["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--vol2", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--mps-python", required=True, type=Path)
    parser.add_argument("--expected-lock-sha256", required=True)
    args = parser.parse_args()
    root = args.run_root.resolve(strict=True)
    print(open_once(root, args.vol2, args.baseline, args.mps_python, args.expected_lock_sha256))


if __name__ == "__main__":
    main()
