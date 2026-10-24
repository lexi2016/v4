"""Registered long-history runner for the frozen V194 reconstruction route.

Numerical modules are imported only after the native thread budget and the
independent input-pass receipt have been checked. Legacy run194.py stays intact.
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
import io
import multiprocessing
import os
from pathlib import Path
import sys
import uuid
from typing import Any

from long_training_adapter import (
    RunnerHeartbeat,
    configure_native_thread_budget,
    load_json,
    require,
    read_frozen_universe_codes,
    runtime_snapshot,
    sha256_file,
    canonical_json_sha256,
    select_safe_fit_workers,
    verify_independent_input_pass,
)


ALLOWED_STAGES = {"canary", "oof", "refit", "predict"}
FLAGS = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

_WORKER_CONTEXT: dict[str, Any] = {}


def _initialize_fold_worker(
    rows: list[dict[str, Any]], model_config: dict[str, Any], identity: dict[str, Any],
    threads_per_worker: int, total_thread_budget: int,
) -> None:
    """Install native limits before a spawned worker imports the legacy model."""
    configure_native_thread_budget(
        processes=1,
        threads_per_process=threads_per_worker,
        total_thread_budget=total_thread_budget,
    )
    _WORKER_CONTEXT.update(rows=rows, model_config=model_config, identity=identity)


def _run_fold_worker(split: dict[str, Any], temporary_dir: str) -> dict[str, Any]:
    """Build one isolated fold in a unique incomplete directory."""
    # The initializer has already set native thread variables in this spawned
    # process. Import numerical/model kernels only after those limits are set.
    module_dir = str(Path(__file__).resolve().parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    import run194 as legacy_pipeline

    for key in legacy_pipeline.m.FIT_COUNTS:
        legacy_pipeline.m.FIT_COUNTS[key] = 0
    result = legacy_pipeline.m.run_fold(
        _WORKER_CONTEXT["rows"],
        _WORKER_CONTEXT["model_config"],
        split,
        temporary_dir,
    )
    legacy_pipeline.seal_fold(temporary_dir, _WORKER_CONTEXT["identity"])
    return {
        "split_id": split["id"],
        "temporary_dir": temporary_dir,
        "result": result,
        "fit_counts": dict(legacy_pipeline.m.FIT_COUNTS),
    }


def _fit_canary_peak_rss(
    config: dict[str, Any], input_pass: dict[str, Any], *, route_id: str,
) -> dict[str, Any]:
    binding = config.get("fit_canary_runtime")
    require(isinstance(binding, dict), "FIT_CANARY_RUNTIME_BINDING_REQUIRED")
    path = Path(str(binding.get("path", ""))).resolve()
    expected_sha = binding.get("sha256")
    require(path.is_file() and isinstance(expected_sha, str) and bool(expected_sha), "FIT_CANARY_RUNTIME_FILE_REQUIRED")
    require(sha256_file(path) == expected_sha, "FIT_CANARY_RUNTIME_SHA_DRIFT")
    receipt = load_json(path)
    require(receipt.get("exit_status") == "SUCCESS", "FIT_CANARY_NOT_SUCCESSFUL")
    require(receipt.get("run_stage") == "canary", "FIT_CANARY_STAGE_DRIFT")
    require(receipt.get("route_id") == route_id, "FIT_CANARY_ROUTE_DRIFT")
    budget = receipt.get("runtime_budget")
    require(isinstance(budget, dict), "FIT_CANARY_BUDGET_MISSING")
    require(budget.get("input_manifest_sha256") == input_pass["input_manifest_sha256"], "FIT_CANARY_MANIFEST_DRIFT")
    require(budget.get("input_review_sha256") == input_pass["review_receipt_sha256"], "FIT_CANARY_REVIEW_DRIFT")
    require(budget.get("threads_per_process") == config.get("runtime_budget", {}).get("threads_per_process", 1), "FIT_CANARY_THREAD_CONFIG_DRIFT")
    fit_counts = budget.get("fit_counts")
    require(isinstance(fit_counts, dict), "FIT_CANARY_FIT_COUNTS_MISSING")
    entered = fit_counts.get("real_fit_entered")
    returned = fit_counts.get("real_fit_returned")
    require(type(entered) is int and entered == 2, "FIT_CANARY_REAL_FIT_COUNT_INVALID")
    require(type(returned) is int and returned == entered, "FIT_CANARY_REAL_FIT_RETURN_COUNT_INVALID")
    require(fit_counts.get("synthetic_fit_entered") == 0, "FIT_CANARY_SYNTHETIC_FIT_FORBIDDEN")
    require(fit_counts.get("synthetic_fit_returned") == 0, "FIT_CANARY_SYNTHETIC_FIT_FORBIDDEN")
    fit_identity = budget.get("fit_canary_identity")
    require(isinstance(fit_identity, dict), "FIT_CANARY_IDENTITY_MISSING")
    require(fit_identity.get("schema_version") == "a_share_v194.fit_canary_identity.v1", "FIT_CANARY_IDENTITY_SCHEMA_DRIFT")
    require(fit_identity.get("route_id") == route_id, "FIT_CANARY_IDENTITY_ROUTE_DRIFT")
    require(fit_identity.get("input_manifest_sha256") == input_pass["input_manifest_sha256"], "FIT_CANARY_IDENTITY_MANIFEST_DRIFT")
    require(fit_identity.get("input_manifest_path") == input_pass["input_manifest_path"], "FIT_CANARY_IDENTITY_MANIFEST_PATH_DRIFT")
    require(fit_identity.get("input_review_sha256") == input_pass["review_receipt_sha256"], "FIT_CANARY_IDENTITY_REVIEW_DRIFT")
    require(fit_identity.get("input_review_path") == input_pass["review_receipt_path"], "FIT_CANARY_IDENTITY_REVIEW_PATH_DRIFT")
    require(fit_identity.get("universe_code_list_sha256") == input_pass["universe_code_list_sha256"], "FIT_CANARY_IDENTITY_UNIVERSE_DRIFT")
    require(fit_identity.get("universe_code_list_path") == input_pass["universe_code_list_path"], "FIT_CANARY_IDENTITY_UNIVERSE_PATH_DRIFT")
    require(fit_identity.get("universe_code_count") == input_pass["universe_code_count"], "FIT_CANARY_IDENTITY_UNIVERSE_COUNT_DRIFT")
    require(fit_identity.get("universe_scope") == input_pass["universe_scope"], "FIT_CANARY_IDENTITY_UNIVERSE_SCOPE_DRIFT")
    require(fit_identity.get("long_runner_code_sha256") == sha256_file(Path(__file__).resolve()), "FIT_CANARY_RUNNER_CODE_DRIFT")
    require(fit_identity.get("adapter_code_sha256") == sha256_file(Path(__file__).with_name("long_training_adapter.py")), "FIT_CANARY_ADAPTER_CODE_DRIFT")
    require(fit_identity.get("threads_per_process") == budget.get("threads_per_process"), "FIT_CANARY_IDENTITY_THREAD_DRIFT")
    for key in ("model_config_sha256", "frozen_identity_sha256", "frozen_plan_sha256", "first_fold_sha256"):
        value = fit_identity.get(key)
        require(isinstance(value, str) and len(value) == 64, "FIT_CANARY_IDENTITY_HASH_MISSING:" + key)
    require(isinstance(fit_identity.get("first_fold_id"), str) and bool(fit_identity["first_fold_id"]), "FIT_CANARY_FIRST_FOLD_ID_MISSING")
    legacy_code_hashes = fit_identity.get("legacy_code_sha256")
    require(isinstance(legacy_code_hashes, dict), "FIT_CANARY_LEGACY_CODE_IDENTITY_MISSING")
    require(all(isinstance(legacy_code_hashes.get(key), str) and len(legacy_code_hashes[key]) == 64
                for key in ("model_code_sha256", "report_code_sha256", "runner_code_sha256")),
            "FIT_CANARY_LEGACY_CODE_IDENTITY_MISSING")
    runtime = receipt.get("runtime")
    require(isinstance(runtime, dict), "FIT_CANARY_RUNTIME_MISSING")
    peak = runtime.get("process_peak_rss_bytes")
    require(type(peak) is int and peak > 0, "FIT_CANARY_RSS_MISSING")
    return {
        "path": str(path),
        "sha256": expected_sha,
        "peak_rss_bytes": peak,
        "execution_id": receipt.get("execution_id"),
        "threads_per_process": budget.get("threads_per_process"),
        "fit_counts": fit_counts,
        "fit_identity": fit_identity,
    }


def _fit_canary_identity(
    frozen: dict[str, Any], input_pass: dict[str, Any], *, route_id: str,
    threads_per_process: int,
) -> dict[str, Any]:
    splits = frozen.get("splits")
    require(isinstance(splits, list) and bool(splits), "FIT_CANARY_FROZEN_SPLITS_MISSING")
    first_fold = splits[0]
    identity = frozen.get("identity")
    model_config = frozen.get("model_config")
    require(isinstance(identity, dict), "FIT_CANARY_FROZEN_IDENTITY_MISSING")
    require(isinstance(model_config, dict), "FIT_CANARY_MODEL_CONFIG_MISSING")
    require(isinstance(first_fold, dict) and bool(first_fold.get("id")), "FIT_CANARY_FIRST_FOLD_MISSING")
    required_code_hashes = ("model_code_sha256", "report_code_sha256", "runner_code_sha256")
    require(all(isinstance(identity.get(key), str) and len(identity[key]) == 64 for key in required_code_hashes), "FIT_CANARY_LEGACY_CODE_IDENTITY_MISSING")
    return {
        "schema_version": "a_share_v194.fit_canary_identity.v1",
        "route_id": route_id,
        "input_manifest_path": input_pass["input_manifest_path"],
        "input_manifest_sha256": input_pass["input_manifest_sha256"],
        "input_review_path": input_pass["review_receipt_path"],
        "input_review_sha256": input_pass["review_receipt_sha256"],
        "universe_code_list_path": input_pass["universe_code_list_path"],
        "universe_code_list_sha256": input_pass["universe_code_list_sha256"],
        "universe_code_count": input_pass["universe_code_count"],
        "universe_scope": input_pass["universe_scope"],
        "threads_per_process": threads_per_process,
        "model_config_sha256": canonical_json_sha256(model_config),
        "frozen_identity_sha256": canonical_json_sha256(identity),
        "frozen_plan_sha256": canonical_json_sha256({
            key: frozen[key]
            for key in ("model_config", "splits", "eligible_target_dates", "evaluation_asof", "bootstrap")
            if key in frozen
        }),
        "first_fold_id": first_fold["id"],
        "first_fold_sha256": canonical_json_sha256(first_fold),
        "long_runner_code_sha256": sha256_file(Path(__file__).resolve()),
        "adapter_code_sha256": sha256_file(Path(__file__).with_name("long_training_adapter.py")),
        "legacy_code_sha256": {key: identity[key] for key in required_code_hashes},
    }


def _verify_fit_canary_identity(
    canary: dict[str, Any], frozen: dict[str, Any], input_pass: dict[str, Any], *, route_id: str,
    threads_per_process: int,
) -> None:
    expected = _fit_canary_identity(
        frozen, input_pass, route_id=route_id, threads_per_process=threads_per_process
    )
    require(canary.get("fit_identity") == expected, "FIT_CANARY_MODEL_FOLD_IDENTITY_DRIFT")


def _source_coverage_counts(row: dict[str, Any]) -> dict[str, Any]:
    """Validate and expose the frozen raw/model per-source row-count schema."""
    scopes = ("raw", "model")
    lanes = ("fupan", "stage7", "research")
    states = ("hit", "confirmed_absent", "unknown")
    result: dict[str, Any] = {}
    for scope in scopes:
        denominator = int(row[scope + "_source_state_denominator"])
        require(denominator >= 0, "NEGATIVE_SOURCE_COVERAGE_DENOMINATOR")
        result[scope + "_source_state_denominator"] = denominator
        for lane in lanes:
            counts = {state: int(row[f"{scope}_source_{lane}_{state}_rows"]) for state in states}
            require(all(value >= 0 for value in counts.values()), "NEGATIVE_SOURCE_COVERAGE_COUNT")
            require(sum(counts.values()) == denominator, "SOURCE_COVERAGE_ROW_DENOMINATOR_DRIFT")
            for state, value in counts.items():
                result[f"{scope}_source_{lane}_{state}_rows"] = value
    return result


def _source_coverage_by_year(coverage_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize both frozen candidate scopes without converting unknown to absent."""
    scopes = ("raw", "model")
    lanes = ("fupan", "stage7", "research")
    by_date: dict[str, dict[str, Any]] = {}
    for row in coverage_rows:
        target_date = row["target_date"]
        require(target_date not in by_date, "DUPLICATE_SOURCE_COVERAGE_DATE")
        by_date[target_date] = _source_coverage_counts(row)

    yearly: dict[str, dict[str, Any]] = {}
    for target_date in sorted(by_date):
        year = target_date[:4]
        period = yearly.setdefault(year, {
            "target_dates": 0,
            "scopes": {
                scope: {
                    "state_denominator_rows": 0,
                    "sources": {lane: {
                        "hit_rows": 0,
                        "confirmed_absent_rows": 0,
                        "unknown_rows": 0,
                        "dates_with_any_hit": 0,
                        "dates_with_any_confirmed_absent": 0,
                        "dates_with_any_unknown": 0,
                        "fully_unknown_dates": 0,
                    } for lane in lanes},
                } for scope in scopes
            },
        })
        period["target_dates"] += 1
        for scope in scopes:
            counts_by_scope = by_date[target_date]
            scope_summary = period["scopes"][scope]
            denominator = counts_by_scope[scope + "_source_state_denominator"]
            scope_summary["state_denominator_rows"] += denominator
            for lane in lanes:
                counts = {
                    state: counts_by_scope[f"{scope}_source_{lane}_{state}_rows"]
                    for state in ("hit", "confirmed_absent", "unknown")
                }
                summary = scope_summary["sources"][lane]
                summary["hit_rows"] += counts["hit"]
                summary["confirmed_absent_rows"] += counts["confirmed_absent"]
                summary["unknown_rows"] += counts["unknown"]
                summary["dates_with_any_hit"] += int(counts["hit"] > 0)
                summary["dates_with_any_confirmed_absent"] += int(counts["confirmed_absent"] > 0)
                summary["dates_with_any_unknown"] += int(counts["unknown"] > 0)
                summary["fully_unknown_dates"] += int(denominator > 0 and counts["unknown"] == denominator)
    return {
        "source_state_semantics": "hit|confirmed_absent|unknown; unknown is never treated as zero/absent",
        "daily_target_date_count": len(by_date),
        "scope_semantics": {
            "raw": "frozen RAW_CANDIDATE_UNION rows for target_date",
            "model": "frozen candidates rows for target_date",
        },
        "by_year": yearly,
    }


def _daily_model_report_rows(
    *, oof_daily: list[dict[str, Any]], coverage_rows: list[dict[str, Any]],
    calendar_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return every frozen target date, leaving non-OOF results null with their reason."""
    oof_by_date = {row["target_date"]: row for row in oof_daily}
    require(len(oof_by_date) == len(oof_daily), "DUPLICATE_OOF_DAILY_REPORT_DATE")
    coverage_by_date = {row["target_date"]: row for row in coverage_rows}
    calendar_by_date = {row["target_date"]: row for row in calendar_rows}
    require(len(coverage_by_date) == len(coverage_rows), "DUPLICATE_SOURCE_COVERAGE_DATE")
    require(len(calendar_by_date) == len(calendar_rows), "DUPLICATE_CALENDAR_DATE")
    require(set(coverage_by_date) == set(calendar_by_date), "SOURCE_COVERAGE_CALENDAR_DATE_DRIFT")
    require(set(oof_by_date).issubset(calendar_by_date), "OOF_DATE_MISSING_DAILY_REPORT_CONTEXT")

    result: list[dict[str, Any]] = []
    for target_date in sorted(calendar_by_date):
        context = coverage_by_date[target_date]
        source_counts = _source_coverage_counts(context)
        oof = oof_by_date.get(target_date)
        role = context.get("cohort_role", "")
        eligible = context.get("training_eligible", "").lower() == "true"
        if oof is not None:
            status, reason = "OOF_EVALUATED", ""
            selection_slots = 50
        elif role == "diagnostic":
            status, reason = "DIAGNOSTIC", context.get("eligibility_exclusion_reason", "") or "EXPOSED_DIAGNOSTIC_ONLY"
            selection_slots = None
        elif not eligible:
            status = "EXCLUDED"
            reason = context.get("eligibility_exclusion_reason", "") or "NOT_ELIGIBLE_FOR_TRAINING_OR_OOF"
            selection_slots = None
        else:
            status, reason = "TRAINING_ONLY", "TRAINING_TARGET_DATE_NOT_EVALUATED_IN_OOF"
            selection_slots = None

        row: dict[str, Any] = {
            "target_date": target_date,
            "status": status,
            "reason": reason,
            "cohort_role": role,
            "training_eligible": context.get("training_eligible", ""),
            "eligibility_exclusion_reason": context.get("eligibility_exclusion_reason", ""),
            "technical_input_availability": context.get("technical_input_availability", ""),
            "official_calendar_parity": context.get("official_calendar_parity", ""),
            "baseline_id": "TECHNICAL11_L2_TOP50",
            "candidate_id": "V194_TOP50",
            "selection_slots": selection_slots,
            "top100_truth_count": int(context["truth_positive_denominator"])
            if context.get("truth_positive_denominator", "") != "" else None,
            "baseline_selected": oof["technical11_l2_selected"] if oof is not None else None,
            "baseline_hits": oof["technical11_l2_hits"] if oof is not None else None,
            "v194_selected": oof["v194_selected"] if oof is not None else None,
            "v194_hits": oof["v194_hits"] if oof is not None else None,
            "baseline_v194_common": oof["technical11_l2_vs_v194_common"] if oof is not None else None,
            "baseline_v194_new": oof["technical11_l2_vs_v194_new"] if oof is not None else None,
            "baseline_v194_lost": oof["technical11_l2_vs_v194_lost"] if oof is not None else None,
            "formula255_offline_selected": oof["raw_formula255_selected"] if oof is not None else None,
            "formula255_offline_hits": oof["raw_formula255_hits"] if oof is not None else None,
        }
        row.update(source_counts)
        result.append(row)
    return result


def _fold_source_state_audit(
    rows: list[dict[str, Any]], splits: list[dict[str, Any]], output: Path, model_module: Any,
) -> dict[str, dict[str, Any]]:
    """Record source-state variation actually available to each fold's training rows."""
    audit: dict[str, dict[str, Any]] = {}
    for split in splits:
        train, _ = model_module.split_rows(rows, split)
        lanes: dict[str, Any] = {}
        for lane in model_module.SOURCES:
            counts = {state: 0 for state in model_module.STATES}
            dates_by_state = {state: set() for state in model_module.STATES}
            for row in train:
                state = row[lane]
                require(state in model_module.STATES, "TRAINING_SOURCE_STATE_INVALID")
                counts[state] += 1
                dates_by_state[state].add(row["target_date"])
            lanes[lane] = {
                "row_counts": counts,
                "target_dates_with_state": {state: len(dates) for state, dates in dates_by_state.items()},
                "observed_state_values": sorted(state for state, count in counts.items() if count),
            }
        candidate_model = model_module.load(output / split["id"] / "candidate_model.json")
        coefficients = {
            feature: float(coefficient)
            for feature, coefficient in zip(candidate_model["features"], candidate_model["coef"])
            if feature.startswith("source_")
        }
        all_unknown = all(lanes[lane]["row_counts"]["hit"] == 0 and
                          lanes[lane]["row_counts"]["confirmed_absent"] == 0
                          for lane in model_module.SOURCES)
        audit[split["id"]] = {
            "training_target_dates": sorted({row["target_date"] for row in train}),
            "source_states": lanes,
            "any_source_state_variation_seen": any(len(lanes[lane]["observed_state_values"]) > 1
                                                    for lane in model_module.SOURCES),
            "all_source_lanes_unknown": all_unknown,
            "candidate_source_feature_coefficients": coefficients,
            "all_source_feature_coefficients_zero_with_tolerance_1e-12": all(
                abs(value) <= 1e-12 for value in coefficients.values()
            ),
        }
    return audit


def _selection_comparison(
    *, oof_dates: list[str], truth_rows: list[dict[str, Any]], raw_natural_rows: list[dict[str, Any]],
    technical_rows: list[dict[str, Any]], v194_rows: list[dict[str, Any]],
    calendar_rows: list[dict[str, Any]], universe_codes: set[str],
    fold_for_date: dict[str, str], fold_source_audit: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Create OOF-only three-model membership and paired count/hit comparisons."""
    require(len(oof_dates) == len(set(oof_dates)), "DUPLICATE_OOF_DATE")
    calendar = {row["target_date"]: row for row in calendar_rows}
    require(len(calendar) == len(calendar_rows), "DUPLICATE_CALENDAR_DATE")
    truth_by_date: dict[str, list[dict[str, Any]]] = {}
    for row in truth_rows:
        truth_by_date.setdefault(row["target_date"], []).append(row)
    raw_by_date: dict[str, set[str]] = {}
    for row in raw_natural_rows:
        target_date, code = row["target_date"], row["code"]
        if target_date in oof_dates:
            require(int(float(row["tech_192"])) == 1, "RAW_FORMULA_NATURAL_TRIGGER_NOT_ONE")
            require(code in universe_codes, "RAW_FORMULA_CODE_OUTSIDE_FROZEN_UNIVERSE")
            require(code not in raw_by_date.setdefault(target_date, set()), "DUPLICATE_RAW_FORMULA_SELECTION")
            raw_by_date[target_date].add(code)
    technical_by_date: dict[str, set[str]] = {}
    v194_by_date: dict[str, set[str]] = {}
    for source_rows, destination, label in (
        (technical_rows, technical_by_date, "TECHNICAL11_L2"),
        (v194_rows, v194_by_date, "V194"),
    ):
        for row in source_rows:
            target_date, code = row["target_date"], row["code"]
            require(target_date in oof_dates, "PREDICTION_DATE_OUTSIDE_OOF")
            require(code in universe_codes, label + "_CODE_OUTSIDE_FROZEN_UNIVERSE")
            require(code not in destination.setdefault(target_date, set()), "DUPLICATE_" + label + "_SELECTION")
            destination[target_date].add(code)

    daily: list[dict[str, Any]] = []
    top100_rows: list[dict[str, Any]] = []
    for target_date in oof_dates:
        require(target_date in calendar, "OOF_DATE_MISSING_CALENDAR")
        day_truth = truth_by_date.get(target_date, [])
        truth_codes = [row["code"] for row in day_truth]
        require(len(truth_codes) == len(universe_codes), "OOF_TRUTH_UNIVERSE_ROW_COUNT_DRIFT")
        require(len(set(truth_codes)) == len(universe_codes) and set(truth_codes) == universe_codes,
                "OOF_TRUTH_UNIVERSE_KEYSET_DRIFT")
        positives = {row["code"] for row in day_truth if int(float(row["label"])) == 1}
        denominator = int(calendar[target_date]["truth_positive_denominator"])
        require(denominator == 100, "OOF_TOP100_EXPECTED_100_POSITIVES")
        require(len(positives) == denominator, "OOF_TOP100_DENOMINATOR_DRIFT")
        raw = raw_by_date.get(target_date, set())
        technical = technical_by_date.get(target_date, set())
        v194 = v194_by_date.get(target_date, set())
        require(len(technical) <= 50 and len(v194) <= 50, "OOF_MODEL_SELECTION_EXCEEDS_TOP50")
        sets = {
            "raw_formula255": raw,
            "technical11_l2": technical,
            "v194": v194,
        }
        pairwise: dict[str, int] = {}
        pair_specs = (
            ("raw_formula255", "technical11_l2"),
            ("raw_formula255", "v194"),
            ("technical11_l2", "v194"),
        )
        for left_name, right_name in pair_specs:
            left, right = sets[left_name], sets[right_name]
            prefix = left_name + "_vs_" + right_name
            common = left & right
            added = right - left
            lost = left - right
            pairwise.update({
                prefix + "_common": len(common),
                prefix + "_new": len(added),
                prefix + "_lost": len(lost),
                prefix + "_common_hits": len(common & positives),
                prefix + "_new_hits": len(added & positives),
                prefix + "_lost_hits": len(lost & positives),
            })
        fold_id = fold_for_date.get(target_date)
        fold_audit = fold_source_audit.get(fold_id, {}) if fold_id else {}
        daily.append({
            "target_date": target_date,
            "fold_id": fold_id,
            "raw_formula255_selected": len(raw),
            "raw_formula255_hits": len(raw & positives),
            "technical11_l2_selected": len(technical),
            "technical11_l2_hits": len(technical & positives),
            "v194_selected": len(v194),
            "v194_hits": len(v194 & positives),
            "truth_positive_denominator": denominator,
            "technical11_l2_equals_v194": technical == v194,
            "training_source_state_variation_seen": fold_audit.get("any_source_state_variation_seen"),
            "training_all_source_lanes_unknown": fold_audit.get("all_source_lanes_unknown"),
            **pairwise,
        })
        for code in sorted(positives):
            top100_rows.append({
                "target_date": target_date,
                "code": code,
                "raw_formula255_selected": int(code in raw),
                "technical11_l2_selected": int(code in technical),
                "v194_selected": int(code in v194),
            })
    return daily, top100_rows, {
        "oof_dates": len(oof_dates),
        "top100_list_rows": len(top100_rows),
        "technical11_l2_equals_v194_dates": sum(row["technical11_l2_equals_v194"] for row in daily),
        "daily": daily,
    }


def _read_bound_manifest_csv(manifest: dict[str, Any], manifest_path: Path, key: str, reader: Any) -> list[dict[str, Any]]:
    files = manifest.get("files")
    require(isinstance(files, dict) and isinstance(files.get(key), dict), "MANIFEST_ARTIFACT_BINDING_MISSING:" + key)
    item = files[key]
    path = Path(str(item.get("path", "")))
    if not path.is_absolute():
        path = manifest_path.parent / path
    expected_sha = item.get("sha256")
    require(path.is_file() and isinstance(expected_sha, str) and bool(expected_sha), "MANIFEST_ARTIFACT_FILE_MISSING:" + key)
    require(sha256_file(path) == expected_sha, "MANIFEST_ARTIFACT_SHA_DRIFT:" + key)
    return reader(path)


def _verify_date_policy_binding(config: dict[str, Any], model_module: Any) -> dict[str, Any]:
    """Bind model split dates to the exact input DATE_POLICY before any fit."""
    manifest_path = Path(str(config.get("input_manifest", ""))).resolve()
    expected_manifest_sha = config.get("input_manifest_sha256")
    require(manifest_path.is_file(), "DATE_POLICY_INPUT_MANIFEST_MISSING")
    require(isinstance(expected_manifest_sha, str) and bool(expected_manifest_sha), "DATE_POLICY_INPUT_MANIFEST_SHA_REQUIRED")
    require(sha256_file(manifest_path) == expected_manifest_sha, "DATE_POLICY_INPUT_MANIFEST_SHA_DRIFT")
    manifest = load_json(manifest_path)

    files = manifest.get("files")
    require(isinstance(files, dict) and isinstance(files.get("date_policy"), dict), "DATE_POLICY_MANIFEST_BINDING_MISSING")
    binding = files["date_policy"]
    bound_path = Path(str(binding.get("path", "")))
    if not bound_path.is_absolute():
        bound_path = manifest_path.parent / bound_path
    bound_path = bound_path.resolve()
    config_path = Path(str(config.get("date_policy_path", ""))).resolve()
    expected_policy_sha = binding.get("sha256")
    config_policy_sha = config.get("date_policy_sha256")
    require(config_path.is_file(), "DATE_POLICY_FILE_MISSING")
    require(config_path == bound_path, "DATE_POLICY_PATH_DRIFT")
    require(isinstance(expected_policy_sha, str) and bool(expected_policy_sha), "DATE_POLICY_MANIFEST_SHA_REQUIRED")
    require(config_policy_sha == expected_policy_sha, "DATE_POLICY_CONFIG_SHA_DRIFT")
    require(sha256_file(config_path) == expected_policy_sha, "DATE_POLICY_FILE_SHA_DRIFT")
    policy = load_json(config_path)

    manifest_eligible = manifest.get("eligible_target_dates")
    policy_eligible = policy.get("eligible_target_dates")
    require(isinstance(manifest_eligible, list) and bool(manifest_eligible), "DATE_POLICY_MANIFEST_ELIGIBLE_DATES_MISSING")
    require(isinstance(policy_eligible, list) and bool(policy_eligible), "DATE_POLICY_ELIGIBLE_DATES_MISSING")
    require(manifest_eligible == sorted(set(manifest_eligible)), "DATE_POLICY_MANIFEST_ELIGIBLE_DATES_NOT_SORTED_UNIQUE")
    require(policy_eligible == manifest_eligible, "DATE_POLICY_ELIGIBLE_DATE_DRIFT")

    expected_exposed = manifest.get("exposed_targets_excluded")
    diagnostic_dates = policy.get("diagnostic_target_dates")
    require(isinstance(expected_exposed, list) and isinstance(diagnostic_dates, list), "DATE_POLICY_DIAGNOSTIC_DATES_MISSING")
    require(diagnostic_dates == expected_exposed, "DATE_POLICY_DIAGNOSTIC_DATE_DRIFT")

    expected_top_n = 50
    require(policy.get("planned_model_selection_top_n") == expected_top_n, "DATE_POLICY_TOP_N_DRIFT")
    require(policy.get("input_build_model_fit_count") == 0, "DATE_POLICY_INPUT_BUILD_FIT_COUNT_DRIFT")
    require(policy.get("input_build_oof_count") == 0, "DATE_POLICY_INPUT_BUILD_OOF_COUNT_DRIFT")

    expected_splits = model_module.make_splits(manifest_eligible)
    require(bool(expected_splits), "DATE_POLICY_EXPECTED_SPLITS_EMPTY")
    expected_initial_train = expected_splits[0]["train_target_dates"]
    policy_initial_train = policy.get("initial_train_target_dates")
    require(policy_initial_train == expected_initial_train, "DATE_POLICY_INITIAL_TRAIN_DATES_DRIFT")
    expected_folds = [split["evaluation_target_dates"] for split in expected_splits]
    policy_folds = policy.get("oof_date_folds")
    require(policy_folds == expected_folds, "DATE_POLICY_OOF_FOLDS_DRIFT")
    expected_oof_dates = [date for fold in expected_folds for date in fold]
    require(policy.get("oof_target_dates") == expected_oof_dates, "DATE_POLICY_OOF_DATES_DRIFT")

    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": expected_manifest_sha,
        "date_policy_path": str(config_path),
        "date_policy_sha256": expected_policy_sha,
        "eligible_target_dates": manifest_eligible,
        "diagnostic_target_dates": diagnostic_dates,
        "expected_splits": expected_splits,
        "initial_train_target_date_count": len(expected_initial_train),
        "oof_target_date_count": len(expected_oof_dates),
        "oof_fold_count": len(expected_splits),
        "plan_sha256": canonical_json_sha256({
            "eligible_target_dates": manifest_eligible,
            "initial_train_target_dates": expected_initial_train,
            "oof_date_folds": expected_folds,
            "oof_target_dates": expected_oof_dates,
        }),
    }


def _verify_date_policy_against_frozen_plan(date_policy: dict[str, Any], frozen: dict[str, Any]) -> None:
    """Require the real legacy prepare() plan to equal the bound DATE_POLICY."""
    require(frozen.get("eligible_target_dates") == date_policy["eligible_target_dates"], "DATE_POLICY_FROZEN_ELIGIBLE_DATES_DRIFT")
    require(frozen.get("splits") == date_policy["expected_splits"], "DATE_POLICY_FROZEN_SPLITS_DRIFT")
    require(frozen.get("model_config", {}).get("top_n") == 50, "DATE_POLICY_FROZEN_TOP_N_DRIFT")
    require(frozen.get("excluded_target_dates") == sorted(set(date_policy.get("diagnostic_target_dates", []))), "DATE_POLICY_FROZEN_DIAGNOSTIC_DATES_DRIFT")


def _validate_bounded_research_manifest(
    manifest: dict[str, Any], *, synthetic: bool, input_pass: dict[str, Any], model_module: Any,
) -> None:
    """Validate the current reviewed V2 input without upgrading its old gates.

    The legacy validator expects fields from a different certified-pipeline
    contract (`mode`, `complete_ten_buy_points`, and `semantic_ready=true`).
    This narrow adapter accepts only the exact R2-bounded research chain and
    current V2 feature/label bindings; the manifest itself remains unchanged,
    and historical/PIT/passport flags remain CANNOT_CONFIRM/false.
    """
    require(input_pass.get("review_scope") == "BOUNDED_RECONSTRUCTED_RESEARCH_INPUT",
            "BOUNDED_RESEARCH_VALIDATION_REVIEW_SCOPE_REQUIRED")
    require(input_pass.get("bounded_research_input_readiness") == "PASS", "BOUNDED_RESEARCH_INPUT_NOT_PASS")
    require(input_pass.get("whole_input_status") == "CANNOT_CONFIRM", "WHOLE_INPUT_STATUS_MUST_REMAIN_CANNOT_CONFIRM")
    require(input_pass.get("maximum_claim") == "DIRECTION_ONLY", "BOUNDED_RESEARCH_MAXIMUM_CLAIM_DRIFT")
    require(not synthetic, "SYNTHETIC_FIT_FORBIDDEN_FOR_BOUNDED_INPUT")
    for name, expected in {
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }.items():
        require(manifest.get(name) is expected, "UNSAFE_FLAGS:" + name)
    require(manifest.get("schema") == "V194_DATASET_MANIFEST_V2", "BOUNDED_INPUT_SCHEMA_DRIFT")
    require(manifest.get("historical_availability_bound") is False, "NO_FALSE_PIT_CERTIFICATION")
    require(manifest.get("semantic_ready") is False, "BOUNDED_INPUT_SEMANTIC_STATUS_MUST_REMAIN_UNCERTIFIED")
    require(manifest.get("evidence_level") == "CANNOT_CONFIRM", "BOUNDED_INPUT_EVIDENCE_LEVEL_DRIFT")
    require(manifest.get("label_historical_vintage") == "CANNOT_CONFIRM", "LABEL_VINTAGE_STATUS_DRIFT")
    require(manifest.get("official_calendar_parity") == "CANNOT_CONFIRM", "OFFICIAL_CALENDAR_STATUS_DRIFT")
    require(manifest.get("passport_status") == "NOT_YET_A194_DATASET_PASSPORT_FAST_BIND", "A194_PASSPORT_STATUS_DRIFT")
    require(manifest.get("lineage_review_pass") is False and manifest.get("design_review_pass") is False,
            "INPUT_REVIEW_STATUS_MUST_REMAIN_UNCERTIFIED")
    require(manifest.get("formula_identity") == "FORMULA255_OFFLINE", "FORMULA255_OFFLINE_IDENTITY_REQUIRED")
    require(manifest.get("technical_features") == model_module.TECHNICAL, "TECHNICAL_FEATURE_SET_DRIFT")
    require(manifest.get("source_state_columns") == model_module.SOURCES, "SOURCE_STATE_COLUMNS_DRIFT")
    require(manifest.get("label_definition") ==
            "close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1 using same source and target-D event anchor.",
            "LABEL_DEFINITION_DRIFT")
    require(manifest.get("universe_scope") == input_pass.get("universe_scope"), "BOUNDED_UNIVERSE_SCOPE_DRIFT")
    code_binding = manifest.get("research_code_list")
    require(isinstance(code_binding, dict), "BOUNDED_UNIVERSE_BINDING_MISSING")
    require(code_binding.get("count") == input_pass.get("universe_code_count"), "BOUNDED_UNIVERSE_COUNT_DRIFT")
    require(code_binding.get("sha256") == input_pass.get("universe_code_list_sha256"), "BOUNDED_UNIVERSE_SHA_DRIFT")
    require(Path(str(code_binding.get("path", ""))).resolve() ==
            Path(str(input_pass.get("universe_code_list_path", ""))).resolve(), "BOUNDED_UNIVERSE_PATH_DRIFT")
    require(manifest.get("training_allowed") is False, "BOUNDED_INPUT_TRAINING_POLICY_DRIFT")
    require(manifest.get("whole_input_status", "CANNOT_CONFIRM") == "CANNOT_CONFIRM",
            "WHOLE_INPUT_STATUS_MUST_REMAIN_CANNOT_CONFIRM")


def _prepare_bounded_research_plan(config: dict[str, Any], legacy_pipeline: Any) -> tuple[Any, ...]:
    """Build the legacy RUN_FREEZE plan with one-pass label/date validation.

    The inherited `run194.prepare` constructs each date's truth list by
    rescanning the full truth table. For the 1,326-date input this is
    date-count × truth-row-count work. This equivalent adapter preserves the
    same validation and frozen return shape while grouping counts once.
    """
    model = legacy_pipeline.m
    manifest, tables, rows, model_config, identity = legacy_pipeline.bound_dataset(config)
    eligible = sorted(set(manifest["eligible_target_dates"]) - model.EXPOSED)
    eligible_set = set(eligible)
    splits = model.make_splits(eligible)
    by_date = {row["target_date"]: row for row in tables["calendar"]}
    model.require(len(by_date) == len(tables["calendar"]), "DUPLICATE_CALENDAR_DATE")
    model.require(set(eligible) <= by_date.keys(), "ELIGIBLE_CALENDAR_MISSING")
    row_dates = {row["target_date"] for row in rows}
    model.require(row_dates <= by_date.keys(), "ROW_DATE_OUTSIDE_CALENDAR")

    truth_positive_by_date: dict[str, int] = {}
    truth_count_by_date: dict[str, int] = {}
    for row in tables["truth"]:
        date = row["target_date"]
        if date in by_date:
            truth_count_by_date[date] = truth_count_by_date.get(date, 0) + 1
            if date in eligible_set:
                truth_positive_by_date[date] = truth_positive_by_date.get(date, 0) + int(model.number(row["label"]))
    for date in eligible:
        model.require(truth_count_by_date.get(date, 0) > 0, "TRUTH_MISSING_DATE:" + date)
        model.require(truth_positive_by_date.get(date, 0) == int(by_date[date]["truth_positive_denominator"]),
                      "TRUTH_DENOMINATOR_DRIFT")

    asof = model.instant(config["evaluation_asof"])
    model.require(
        all(model.instant(row["label_available_at"]) <= asof for row in rows if row["target_date"] in eligible),
        "EVAL_LABEL_IMMATURE",
    )

    # `split_rows` is called on each fold in the actual fit as well. Preflight
    # the exact same two-class/maturity condition through date-level buckets
    # rather than scanning the full candidate list for every fold here.
    class_counts_by_date: dict[str, dict[tuple[Any, int], int]] = {}
    for row in rows:
        date = row["target_date"]
        if date not in eligible_set:
            continue
        key = (model.instant(row["label_available_at"]), int(model.number(row["label"])))
        counts = class_counts_by_date.setdefault(date, {})
        counts[key] = counts.get(key, 0) + 1
    for split in splits:
        train_dates = set(split["train_target_dates"])
        eval_dates = set(split["evaluation_target_dates"])
        model.require(train_dates and eval_dates and max(train_dates) < min(eval_dates), "CHRONOLOGICAL_SPLIT_REQUIRED")
        model.require(not (train_dates | eval_dates) & model.EXPOSED, "EXPOSED_TARGET_DATE_FORBIDDEN")
        cutoff = model.decision(min(eval_dates))
        train_count = 0
        train_classes: set[int] = set()
        for date in train_dates:
            for (available_at, label), count in class_counts_by_date.get(date, {}).items():
                if available_at < cutoff:
                    train_count += count
                    train_classes.add(label)
        model.require(train_count > 0 and train_classes == {0, 1}, "TRAIN_REQUIRES_TWO_CLASSES")

    frozen = dict(
        schema="V194_RUN_FREEZE_V2",
        identity=identity,
        model_config=model_config,
        splits=splits,
        eligible_target_dates=eligible,
        evaluation_asof=config["evaluation_asof"],
        bootstrap=legacy_pipeline.BOOTSTRAP,
        excluded_target_dates=sorted(model.EXPOSED & set(by_date)),
        **model.FLAGS,
    )
    return manifest, tables, rows, model_config, frozen


def _write_csv_exclusive(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _summary_csv_bytes(rows: list[dict[str, Any]], columns: list[str]) -> bytes:
    """Serialize the approved daily count summary without any stock-code list."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _write_summary_csv_idempotent(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> str:
    """Create the slim summary once; an existing file is reusable only byte-for-byte."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _summary_csv_bytes(rows, columns)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        require(path.read_bytes() == payload, "SLIM_DAILY_SUMMARY_EXISTS_DIFFERENT")
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    return sha256_file(path)


def _selection_totals(daily: list[dict[str, Any]]) -> dict[str, Any]:
    count_fields = (
        "raw_formula255_selected", "raw_formula255_hits", "technical11_l2_selected",
        "technical11_l2_hits", "v194_selected", "v194_hits", "truth_positive_denominator",
    )
    totals: dict[str, Any] = {field: sum(int(row[field]) for row in daily) for field in count_fields}
    for field in daily[0]:
        if "_vs_" in field and any(field.endswith("_" + suffix) for suffix in ("common", "new", "lost", "common_hits", "new_hits", "lost_hits")):
            totals[field] = sum(int(row[field]) for row in daily)
    totals["technical11_l2_equals_v194_dates"] = sum(bool(row["technical11_l2_equals_v194"]) for row in daily)
    totals["oof_dates"] = len(daily)
    totals["top100_rows"] = sum(int(row["truth_positive_denominator"]) for row in daily)
    return totals


def _execute_oof_parallel(
    config: dict[str, Any], checkpoint: Any, *, requested_workers: int,
    threads_per_worker: int, total_thread_budget: int,
    canary: dict[str, Any], input_pass: dict[str, Any],
    identity_runtime: dict[str, Any], set_runtime_budget: Any,
    date_policy: dict[str, Any],
) -> tuple[dict[str, Any], Path, dict[str, Any], dict[str, Any]]:
    """Reuse the V194 kernels while running independent expanding folds safely."""
    module_dir = str(Path(__file__).resolve().parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    import run194 as legacy_pipeline
    from report194 import evaluate, write_report

    output = Path(config["output_dir"]).resolve()
    manifest, tables, rows, model_config, frozen = legacy_pipeline.prepare(config)
    _verify_date_policy_against_frozen_plan(date_policy, frozen)
    legacy_pipeline.freeze_file(output, frozen, create=False)
    _verify_fit_canary_identity(
        canary,
        frozen,
        input_pass,
        route_id=identity_runtime["route_id"],
        threads_per_process=threads_per_worker,
    )
    available_memory_bytes = runtime_snapshot()["available_memory_bytes"]
    memory_safety_fraction = config.get("runtime_budget", {}).get("memory_safety_fraction", 0.5)
    selection = select_safe_fit_workers(
        requested_workers=requested_workers,
        threads_per_worker=threads_per_worker,
        total_thread_budget=total_thread_budget,
        canary_peak_rss_bytes=canary["peak_rss_bytes"],
        available_memory_bytes=available_memory_bytes,
        memory_safety_fraction=memory_safety_fraction,
    )
    workers = selection["actual_workers"]
    actual_budget = configure_native_thread_budget(
        processes=workers,
        threads_per_process=threads_per_worker,
        total_thread_budget=total_thread_budget,
    )
    actual_budget.update({
        "requested_fit_workers": requested_workers,
        "fit_worker_selection": {
            **selection,
            "available_memory_sampled_after_input_load": True,
        },
        "fit_canary": canary,
        "input_manifest_sha256": input_pass["input_manifest_sha256"],
        "input_review_sha256": input_pass["review_receipt_sha256"],
        "frozen_universe_code_list_sha256": input_pass["universe_code_list_sha256"],
    })
    set_runtime_budget(actual_budget)
    predictions = {"baseline": [], "candidate": []}
    reused: list[str] = []
    pending: list[tuple[dict[str, Any], Path]] = []
    for split in frozen["splits"]:
        folder = output / split["id"]
        if folder.exists():
            legacy_pipeline.reuse_fold(folder, frozen["identity"])
            reused.append(split["id"])
        else:
            incomplete = output / "_incomplete" / str(identity_runtime["execution_id"])
            incomplete.mkdir(parents=True, exist_ok=True)
            temp_dir = incomplete / (split["id"] + "." + uuid.uuid4().hex)
            pending.append((split, temp_dir))

    fit_counts = {key: 0 for key in legacy_pipeline.m.FIT_COUNTS}
    if pending:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_initialize_fold_worker,
            initargs=(rows, model_config, frozen["identity"], threads_per_worker, total_thread_budget),
            max_tasks_per_child=1,
        ) as pool:
            futures = {
                pool.submit(_run_fold_worker, split, str(temp_dir)): (split, temp_dir)
                for split, temp_dir in pending
            }
            try:
                for future in as_completed(futures):
                    split, temp_dir = futures[future]
                    worker_result = future.result()
                    require(worker_result["split_id"] == split["id"], "FOLD_WORKER_ID_DRIFT")
                    canonical = output / split["id"]
                    require(not canonical.exists(), "FOLD_CACHE_APPEARED_DURING_RUN")
                    os.replace(temp_dir, canonical)
                    for key, value in worker_result["fit_counts"].items():
                        fit_counts[key] += int(value)
                    legacy_pipeline.m.FIT_COUNTS.update(fit_counts)
                    checkpoint(split["id"].upper() + "_COMPLETE", canonical / "FOLD_RESULT.json")
            except BaseException:
                for future in futures:
                    future.cancel()
                raise

    # Aggregate in the frozen split order even when workers finish out of order.
    for split in frozen["splits"]:
        folder = output / split["id"]
        for arm in predictions:
            predictions[arm] += legacy_pipeline.m.load(folder / (arm + "_top50.json"))
    legacy_pipeline.m.FIT_COUNTS.update(fit_counts)
    dates = [date for split in frozen["splits"] for date in split["evaluation_target_dates"]]
    result = evaluate(dates, predictions["baseline"], predictions["candidate"], tables["truth"], tables["calendar"])
    coverage = dict(
        eligible_dates=frozen["eligible_target_dates"],
        excluded_exposed_dates=frozen["excluded_target_dates"],
        input_exclusions=manifest.get("exclusions", []),
        failed_folds=[],
        reused_folds=reused,
        empty_candidate_dates=[date for date in dates if not any(row["target_date"] == date for row in rows)],
    )

    manifest_path = Path(config["input_manifest"]).resolve()
    raw_natural_rows = _read_bound_manifest_csv(manifest, manifest_path, "raw_formula_natural", legacy_pipeline.m.read_csv)
    source_coverage_rows = _read_bound_manifest_csv(manifest, manifest_path, "coverage", legacy_pipeline.m.read_csv)
    require({row["target_date"] for row in source_coverage_rows} == set(manifest["eligible_target_dates"])
            or {row["target_date"] for row in source_coverage_rows} == set(row["target_date"] for row in tables["calendar"]),
            "SOURCE_COVERAGE_DATE_RANGE_DRIFT")
    code_list_path = Path(str(config["frozen_universe"]["code_list_path"]))
    universe_codes = set(read_frozen_universe_codes(code_list_path))
    fold_source_audit = _fold_source_state_audit(rows, frozen["splits"], output, legacy_pipeline.m)
    fold_for_date = {
        target_date: split["id"]
        for split in frozen["splits"]
        for target_date in split["evaluation_target_dates"]
    }
    daily_comparison, top100_flags, selection_audit = _selection_comparison(
        oof_dates=dates,
        truth_rows=tables["truth"],
        raw_natural_rows=raw_natural_rows,
        technical_rows=predictions["baseline"],
        v194_rows=predictions["candidate"],
        calendar_rows=tables["calendar"],
        universe_codes=universe_codes,
        fold_for_date=fold_for_date,
        fold_source_audit=fold_source_audit,
    )
    selection_audit.update({
        "summary": _selection_totals(daily_comparison),
        "formula_route": "FORMULA255_OFFLINE_RESEARCH_ONLY",
        "raw_formula_membership_source": "manifest.files.raw_formula_natural: raw formula tech_192==1 membership, natural and untruncated; unrelated technical unknowns do not filter it",
        "source_state_policy": "R1 row semantics are preserved: bound hit is hit; nonmembership is unknown unless an explicit producer-complete record says confirmed_absent. No absence is inferred by complement.",
        **FLAGS,
    })
    source_coverage = _source_coverage_by_year(source_coverage_rows)
    source_coverage["source_state_parent_binding"] = {
        "r1_manifest_path": "/Users/lexi/Desktop/学习/因子工厂/research/a_share_v194_20261023/repair_r1_20261024/inputs/MANIFEST_FINAL.json",
        "r1_manifest_sha256": "e5f57acb6e5555f3a08e8e76387b427bf50d57eb57560f6f80de2dda9594bfcf",
        "r1_data194_sha256": "57f2ea925106859e8152a13f52c61f51b74bed8218ee2acea2e37f89cfb84fa2",
        "interpretation": "The R1 producer binds observed hit records; nonmembership remained unknown and no confirmed_absent rows were present. This long-window report preserves that state and does not infer absence from pool complement.",
    }
    selection_path = output / "LONG_SELECTION_AUDIT.json"
    fold_state_path = output / "LONG_FOLD_SOURCE_STATE_AUDIT.json"
    coverage_year_path = output / "LONG_SOURCE_COVERAGE_BY_YEAR.json"
    comparison_csv_path = output / "OOF_DAILY_SELECTION_COMPARISON.csv"
    top100_csv_path = output / "OOF_TOP100_WITH_SELECTIONS.csv"
    daily_model_report = _daily_model_report_rows(
        oof_daily=daily_comparison,
        coverage_rows=source_coverage_rows,
        calendar_rows=tables["calendar"],
    )
    legacy_pipeline.m.save(fold_state_path, fold_source_audit)
    legacy_pipeline.m.save(coverage_year_path, source_coverage)
    _write_csv_exclusive(
        comparison_csv_path,
        daily_comparison,
        list(daily_comparison[0].keys()) if daily_comparison else [],
    )
    daily_summary_path = Path(__file__).resolve().with_name("LONG_DAILY_MODEL_COUNTS.csv")
    daily_summary_sha = _write_summary_csv_idempotent(
        daily_summary_path,
        daily_model_report,
        list(daily_model_report[0].keys()) if daily_model_report else [],
    )
    selection_audit["long_daily_model_counts_path"] = str(daily_summary_path)
    selection_audit["long_daily_model_counts_sha256"] = daily_summary_sha
    selection_audit["long_daily_model_counts_dates"] = len(daily_model_report)
    selection_audit["long_daily_model_counts_statuses"] = {
        status: sum(row["status"] == status for row in daily_model_report)
        for status in sorted({row["status"] for row in daily_model_report})
    }
    legacy_pipeline.m.save(selection_path, selection_audit)
    _write_csv_exclusive(
        top100_csv_path,
        top100_flags,
        ["target_date", "code", "raw_formula255_selected", "technical11_l2_selected", "v194_selected"],
    )
    coverage.update({
        "long_selection_audit_path": str(selection_path),
        "long_fold_source_state_audit_path": str(fold_state_path),
        "long_source_coverage_by_year_path": str(coverage_year_path),
        "oof_daily_selection_comparison_path": str(comparison_csv_path),
        "oof_top100_with_selection_flags_path": str(top100_csv_path),
        "long_daily_model_counts_path": str(daily_summary_path),
        "long_daily_model_counts_sha256": daily_summary_sha,
        "source_state_semantics": source_coverage["source_state_semantics"],
    })
    write_report(output, result, coverage)
    same_dates = selection_audit["summary"]["technical11_l2_equals_v194_dates"]
    oof_count = selection_audit["summary"]["oof_dates"]
    all_unknown_folds = [fold for fold, value in fold_source_audit.items() if value["all_source_lanes_unknown"]]
    explanation = (
        f"Technical11 L2 and V194 selected the same set on {same_dates}/{oof_count} OOF dates. "
        f"The OOF fold training windows with all source lanes unknown were {all_unknown_folds}. "
        "When a fold had no source-state variation, the added source features could not separate training rows; this is not evidence that source information is effective."
    )
    with (output / "LONG_SELECTION_AUDIT.md").open("x", encoding="utf-8") as handle:
        handle.write(
            "# Long-window V194 selection audit\n\n"
            f"OOF dates: {oof_count}. Formula route: `FORMULA255_OFFLINE_RESEARCH_ONLY`.\n\n"
            f"{explanation}\n\n"
            "Source states are preserved as hit, confirmed_absent, or unknown. Nonmembership is not treated as absence. "
            "The full raw natural formula membership list remains in the bound local input artifact; this report contains OOF dates only.\n"
        )
    for arm, picks in predictions.items():
        legacy_pipeline.m.save(output / (arm + "_OOF_TOP50.json"), picks)
    result["fit_counts"] = dict(legacy_pipeline.m.FIT_COUNTS)
    result["long_selection_audit"] = str(selection_path)
    result["long_fold_source_state_audit"] = str(fold_state_path)
    result["long_source_coverage_by_year"] = str(coverage_year_path)
    result["long_daily_model_counts_path"] = str(daily_summary_path)
    result["long_daily_model_counts_sha256"] = daily_summary_sha
    result["registered_artifacts"] = [str(daily_summary_path)]
    legacy_pipeline.m.save(output / "OOF_RESULT.json", result)
    return result, output / "OOF_RESULT.json", dict(legacy_pipeline.m.FIT_COUNTS), actual_budget


def run_registered_contract(contract_path: str | Path) -> dict[str, Any]:
    contract_path = Path(contract_path).resolve()
    require(contract_path.is_file(), "EXECUTION_CONTRACT_MISSING")
    contract = load_json(contract_path)
    route_id = contract.get("route_id")
    execution_id = contract.get("execution_id")
    stage = contract.get("run_stage")
    require(bool(route_id) and bool(execution_id), "REGISTRY_IDENTITY_REQUIRED")
    require(stage in ALLOWED_STAGES, "UNSUPPORTED_LONG_RUN_STAGE")

    from registry_bridge import register

    stage_name = stage.upper()
    start_receipt = register(
        contract_path,
        "RUN_STARTED",
        stage_name + "_START",
        decision="RUNNING_LONG_HISTORY_" + stage_name,
    )
    output_dir: Path | None = None
    heartbeat: RunnerHeartbeat | None = None
    legacy_pipeline = None
    original_validate_manifest = None
    original_prepare = None
    try:
        config_path = Path(str(contract.get("run_config_path", ""))).resolve()
        expected_config_sha = contract.get("run_config_sha256")
        require(config_path.is_file() and isinstance(expected_config_sha, str), "RUN_CONFIG_BINDING_REQUIRED")
        require(sha256_file(config_path) == expected_config_sha, "RUN_CONFIG_DRIFT")
        config = load_json(config_path)
        output_dir = Path(str(config.get("output_dir", ""))).resolve()
        require(bool(str(config.get("output_dir", ""))), "OUTPUT_DIR_REQUIRED")

        runtime = config.get("runtime_budget", {})
        require(isinstance(runtime, dict), "RUNTIME_BUDGET_OBJECT_REQUIRED")
        threads = runtime.get("threads_per_process", 1)
        total_budget = runtime.get("total_thread_budget", 12)
        requested_workers = runtime.get("fit_workers", runtime.get("processes", 1))
        require(type(requested_workers) is int and requested_workers >= 1, "FIT_WORKER_COUNT_INVALID")
        require(type(threads) is int and threads >= 1, "THREAD_COUNT_INVALID")
        input_pass = verify_independent_input_pass(config)
        canary = None
        if stage == "oof":
            canary = _fit_canary_peak_rss(config, input_pass, route_id=route_id)
            # Input tables are loaded under the heartbeat; the final memory
            # cap is measured after that load immediately before worker spawn.
            workers = 1
            selection = {"actual_workers": 1, "selection_reason": "PENDING_POST_INPUT_LOAD_MEMORY_SAMPLE"}
        else:
            # The reusable first-fold canary and final refit/predict stages are
            # kept single-process. OOF is the only stage that fans out folds.
            workers = 1
            selection = {
                "requested_workers": requested_workers,
                "actual_workers": workers,
                "threads_per_worker": threads,
                "effective_threads": threads,
                "selection_reason": "CANARY_OR_SINGLE_STAGE_SERIAL",
            }
        actual_budget = configure_native_thread_budget(
            processes=workers,
            threads_per_process=threads,
            total_thread_budget=total_budget,
        )
        actual_budget.update({
            "requested_fit_workers": requested_workers,
            "fit_worker_selection": selection,
            "fit_canary": canary,
            "input_manifest_sha256": input_pass["input_manifest_sha256"],
            "input_review_sha256": input_pass["review_receipt_sha256"],
            "frozen_universe_code_list_sha256": input_pass["universe_code_list_sha256"],
        })
        require(actual_budget["effective_native_threads"] <= 12, "GLOBAL_THREAD_CAP_EXCEEDED")

        heartbeat_seconds = float(runtime.get("heartbeat_seconds", 30.0))
        runtime_dir = output_dir / "_runtime" / str(execution_id) / stage
        heartbeat = RunnerHeartbeat(
            runtime_dir,
            route_id=route_id,
            execution_id=execution_id,
            heartbeat_seconds=heartbeat_seconds,
            runtime_budget=actual_budget,
            run_stage=stage,
        )
        with heartbeat:
            # run194 imports model194/report194, which lazily imports numerical
            # libraries during fit. Import only after the thread cap above.
            module_dir = str(Path(__file__).resolve().parent)
            if module_dir not in sys.path:
                sys.path.insert(0, module_dir)
            import run194 as legacy_pipeline
            fit_counts_before = dict(legacy_pipeline.m.FIT_COUNTS)
            original_validate_manifest = getattr(legacy_pipeline.m, "validate_manifest", None)
            original_prepare = getattr(legacy_pipeline, "prepare", None)
            if input_pass.get("review_scope") == "BOUNDED_RECONSTRUCTED_RESEARCH_INPUT":
                require(callable(original_validate_manifest), "LEGACY_MANIFEST_VALIDATOR_MISSING")
                require(callable(original_prepare), "LEGACY_PREPARE_MISSING")
                def validate_bounded_manifest(manifest: dict[str, Any], synthetic: bool = False) -> None:
                    _validate_bounded_research_manifest(
                        manifest,
                        synthetic=synthetic,
                        input_pass=input_pass,
                        model_module=legacy_pipeline.m,
                    )

                legacy_pipeline.m.validate_manifest = validate_bounded_manifest
                legacy_pipeline.prepare = lambda run_config: _prepare_bounded_research_plan(
                    run_config, legacy_pipeline
                )
            date_policy = None
            if stage in {"canary", "oof", "refit"}:
                date_policy = _verify_date_policy_binding(config, legacy_pipeline.m)

            def checkpoint(name: str, artifact_path: str | Path) -> None:
                metrics = dict(legacy_pipeline.m.FIT_COUNTS)
                heartbeat.checkpoint(name, artifact_path, metrics)
                register(
                    contract_path,
                    "CHECKPOINT",
                    name,
                    [artifact_path],
                    metrics=metrics,
                    decision="DIRECTION_ONLY_CHECKPOINT",
                )

            if stage == "oof":
                result, artifact, fit_counts, actual_budget = _execute_oof_parallel(
                    config,
                    checkpoint,
                    requested_workers=requested_workers,
                    threads_per_worker=threads,
                    total_thread_budget=total_budget,
                    canary=canary,
                    input_pass=input_pass,
                    identity_runtime={"execution_id": execution_id, "route_id": route_id},
                    set_runtime_budget=heartbeat.set_runtime_budget,
                    date_policy=date_policy,
                )
                legacy_pipeline.m.FIT_COUNTS.update(fit_counts)
            else:
                prepare_for_stage = legacy_pipeline.prepare
                if date_policy is not None:
                    def guarded_prepare(run_config: dict[str, Any]) -> tuple[Any, ...]:
                        prepared = prepare_for_stage(run_config)
                        _verify_date_policy_against_frozen_plan(date_policy, prepared[-1])
                        return prepared

                    legacy_pipeline.prepare = guarded_prepare
                try:
                    result, artifact = legacy_pipeline.execute_stage(config, stage, checkpoint)
                finally:
                    if date_policy is not None:
                        legacy_pipeline.prepare = prepare_for_stage
                if stage == "canary":
                    stage_fit_counts = {
                        key: int(legacy_pipeline.m.FIT_COUNTS.get(key, 0)) - int(fit_counts_before.get(key, 0))
                        for key in legacy_pipeline.m.FIT_COUNTS
                    }
                    require(stage_fit_counts.get("real_fit_entered") == 2, "FIT_CANARY_REAL_FIT_COUNT_INVALID")
                    require(stage_fit_counts.get("real_fit_returned") == 2, "FIT_CANARY_REAL_FIT_RETURN_COUNT_INVALID")
                    require(stage_fit_counts.get("synthetic_fit_entered") == 0, "FIT_CANARY_SYNTHETIC_FIT_FORBIDDEN")
                    require(stage_fit_counts.get("synthetic_fit_returned") == 0, "FIT_CANARY_SYNTHETIC_FIT_FORBIDDEN")
                    frozen = load_json(output_dir / "RUN_FREEZE.json")
                    fit_identity = _fit_canary_identity(
                        frozen,
                        input_pass,
                        route_id=route_id,
                        threads_per_process=threads,
                    )
                    actual_budget.update({
                        "fit_counts": stage_fit_counts,
                        "fit_canary_identity": fit_identity,
                    })
                    heartbeat.set_runtime_budget(actual_budget)
            result = {
                **result,
                "input_pass": input_pass,
                "runtime_budget": actual_budget,
                "runner_pid": os.getpid(),
                **FLAGS,
            }
            legacy_pipeline.m.validate_manifest = original_validate_manifest
            if original_prepare is not None:
                legacy_pipeline.prepare = original_prepare

        terminal_artifacts = [artifact]
        terminal_artifacts.extend(result.get("registered_artifacts", []))
        terminal_path = runtime_dir / "RUNNER_TERMINAL.json"
        if terminal_path.exists():
            terminal_artifacts.append(terminal_path)
        terminal_receipt = register(
            contract_path,
            "TERMINAL",
            stage_name + "_COMPLETE",
            terminal_artifacts,
            metrics=dict(legacy_pipeline.m.FIT_COUNTS),
            decision=result.get("status", "DIRECTION_ONLY"),
        )
        return {
            "status": result.get("status", "DIRECTION_ONLY"),
            "execution_id": execution_id,
            "stage": stage,
            "result_path": str(artifact),
            "registry_event_sha256": terminal_receipt["event_sha256"],
            "registry_start_event_sha256": start_receipt["event_sha256"],
            "fit_counts": dict(legacy_pipeline.m.FIT_COUNTS),
            **FLAGS,
        }
    except BaseException as exc:
        if legacy_pipeline is not None and original_validate_manifest is not None:
            legacy_pipeline.m.validate_manifest = original_validate_manifest
        if legacy_pipeline is not None and original_prepare is not None:
            legacy_pipeline.prepare = original_prepare
        artifacts: list[str | Path] = []
        if output_dir is not None:
            runtime_dir = output_dir / "_runtime" / str(execution_id) / stage
            terminal_path = runtime_dir / "RUNNER_TERMINAL.json"
            if terminal_path.exists():
                artifacts.append(terminal_path)
        try:
            register(
                contract_path,
                "TERMINAL",
                stage_name + "_FAILED",
                artifacts,
                decision="FAILED:" + type(exc).__name__ + ":" + str(exc)[:250],
            )
        except BaseException as registry_exc:
            raise exc from registry_exc
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("execution_contract")
    args = parser.parse_args()
    result = run_registered_contract(args.execution_contract)
    print(result)


if __name__ == "__main__":
    main()
