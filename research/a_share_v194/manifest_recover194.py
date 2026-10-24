"""Finalize saved R3 metadata only; never project bars, evaluate labels or fit."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

EVIDENCE_ROOT = Path("/Users/lexi/Desktop/学习/因子工厂/research/a_share_v194_full_history_20261024")
TEMPLATE_SHA = "84031e4500dff48411e6b3665b62650cacbd66567e727d56c9cb2978766f9a29"
EXPECTED_CODE_COUNT = 5533
TECHNICAL = ["tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI", "M2_MINUS", "M2_PLUS", "SINGLE_NEEDLE", "THREE_QUARTER_YIN", "BRICK_FANBAO"]
SOURCES = ["source_fupan", "source_stage7", "source_research"]
EXPOSED = {"20261016", "20261019", "20261020", "20261021", "20261022"}
TARGET_DATE_CAP = "20261022"
FLAGS = dict(research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
OUTPUT_FILES = {
    "stock_coverage": "STOCK_COVERAGE.csv", "raw_formula_natural": "RAW_FORMULA_NATURAL.csv",
    "raw_candidate_union": "RAW_CANDIDATE_UNION.csv", "candidates": "candidates.csv",
    "truth": "truth.csv", "calendar": "calendar.csv", "coverage": "coverage.csv",
    "technical_exclusions": "TECHNICAL_EXCLUSIONS.json", "source_axes": "SOURCE_AXES.csv",
    "date_policy": "DATE_POLICY.json", "dictionary": "DATA_DICTIONARY.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def sha_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def panel_stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return dict(inode=st.st_ino, mtime_ns=st.st_mtime_ns, size=st.st_size)


def bound_json(ref: Mapping[str, Any]) -> tuple[Path, Any]:
    path = Path(ref["path"]).resolve()
    require(sha_file(path) == ref["sha256"], "RECOVERY_BOUND_JSON_DRIFT:" + str(path))
    return path, load_json(path)


def write_new(path: Path, value: Any) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def fingerprint_saved(path: Path, expected_stat: Mapping[str, int]) -> tuple[dict[str, Any], Any]:
    """One byte pass for SHA and physical CSV lines, same old row-count rule."""
    before = panel_stat(path)
    require(before == dict(expected_stat), "SAVED_OUTPUT_STAT_DRIFT:" + str(path))
    digest = hashlib.sha256()
    lines = 0
    tail = b""
    chunks = [] if path.suffix == ".json" else None
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
            lines += chunk.count(b"\n")
            tail = chunk[-1:]
            if chunks is not None:
                chunks.append(chunk)
    require(panel_stat(path) == before, "SAVED_OUTPUT_CHANGED_DURING_READ:" + str(path))
    value = json.loads(b"".join(chunks)) if chunks is not None else None
    rows = max(0, lines + int(bool(tail) and tail != b"\n") - 1) if chunks is None else (len(value) if isinstance(value, list) else -1)
    return dict(path=str(path), sha256=digest.hexdigest(), rows=rows), value


def saved_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def saved_counts(calendar: list[dict[str, str]], stocks: list[dict[str, str]], files: Mapping[str, Any]) -> dict[str, int]:
    counts = dict(rankable_truth_rows=sum(int(r["truth_rankable_research_rows"]) for r in calendar),
                  candidate_rows=files["candidates"]["rows"], raw_candidate_union_rows=files["raw_candidate_union"]["rows"],
                  raw_formula_natural_rows=files["raw_formula_natural"]["rows"],
                  technical_candidate_exclusions=files["technical_exclusions"]["rows"])
    # Physical truth rows and rankable outcomes are deliberately separate.
    for field, key in (("candidate_rows", "candidate_rows"), ("raw_candidate_union_rows", "raw_candidate_union_rows")):
        require(sum(int(r[field]) for r in calendar) == counts[key], "SAVED_CALENDAR_COUNT_DRIFT:" + field)
    for field, key in (("candidate_union_rows", "raw_candidate_union_rows"), ("raw_formula_natural_rows", "raw_formula_natural_rows"),
                       ("technical_candidate_exclusions", "technical_candidate_exclusions")):
        require(sum(int(r[field]) for r in stocks) == counts[key], "SAVED_STOCK_COUNT_DRIFT:" + field)
    require(counts["raw_candidate_union_rows"] - counts["candidate_rows"] == counts["technical_candidate_exclusions"], "SAVED_CANDIDATE_EXCLUSION_COUNT_DRIFT")
    return counts


def recovered_manifest(original_config: Mapping[str, Any], identity: Mapping[str, Any], snapshot: Mapping[str, Any],
                       contract: Mapping[str, Any], scan_receipt: Mapping[str, Any], files: Mapping[str, Any],
                       revised_calendar: list[dict[str, Any]], date_policy: Mapping[str, Any], dictionary: Mapping[str, Any],
                       counts: Mapping[str, int], source_code_paths: list[Path], output: Path) -> dict[str, Any]:
    """Original R3 manifest expression, with explicit saved-count equivalents.

    Only dataset/calendar provenance and the old daily-SHA alias are corrected.
    No original expression that constructs a bar, feature or label runs here.
    """
    original_build = Path(original_config["build_dir"])
    ctx = dict(target=Path(identity["panel_target_path"]), snapshot=snapshot, contract=contract)
    pairs = [(r["signal_date"].replace("-", ""), r["target_date"].replace("-", "")) for r in revised_calendar]
    eligible_dates = date_policy["eligible_target_dates"]
    EXECUTION_ID = original_config["execution_id"]
    EXPECTED_ACCEPTED64_SHA = identity["accepted64_manifest_sha256"]
    EXPECTED_CODE_LIST_COUNT = identity["research_code_count"]
    EXPECTED_CODE_LIST_SHA = identity["research_code_list_sha256"]
    EXPECTED_START_EVENT_SHA = original_config["start_event_sha256"]
    FULL_RECEIPT = original_build / "PANEL_SCAN_RECEIPT.json"
    CANARY = Path(original_config["canary_dir"])
    BUILD_CONFIG = original_config
    work_dir = original_build / "_intermediate/processing"
    target_sha = snapshot["panel_bindings"]["backtest"]["target_sha256"]
    def code_list_path():
        return original_build / "RESEARCH_CODE_KEYS.csv"
    def iso_day(day):
        return day[:4] + "-" + day[4:6] + "-" + day[6:]
    manifest = {"schema": "V194_DATASET_MANIFEST_V2", "dataset_kind": "FROZEN_RAW_TDX_EVENT_DERIVED_HISTORY_INPUT",
        "execution_id": EXECUTION_ID, "status": "INPUT_BUILD_READY_FOR_INDEPENDENT_REVIEW",
        "evidence_level": "CANNOT_CONFIRM", "historical_availability_bound": False,
        "historical_availability_reason": "PANEL_VINTAGE_AND_EVENT_SOURCE_HISTORICAL_CAPTURE_TIME_NOT_CERTIFIED",
        "semantic_ready": False, "passport_status": "NOT_YET_A194_DATASET_PASSPORT_FAST_BIND",
        "lineage_review_pass": False, "design_review_pass": False, "files": files,
        "input_sha256": canonical_sha(files), "formula_identity": "FORMULA255_OFFLINE",
        "technical_features": TECHNICAL, "source_state_columns": SOURCES,
        "source_unknown": "UNKNOWN_NEVER_ZERO_NO_CONFIRMED_ABSENCE",
        "source_coverage": "Bound research source hits; all non-hit keys are unknown.",
        "universe_scope": "Exact accepted 5,533 research code keys; not all-A historical certification.",
        "research_code_list": {"path": str(code_list_path()), "sha256": EXPECTED_CODE_LIST_SHA,
                               "count": EXPECTED_CODE_LIST_COUNT,
                               "accepted64_manifest_sha256": EXPECTED_ACCEPTED64_SHA},
        "panel_binding": {"path": str(ctx["target"]), "pointer_path": ctx["snapshot"]["panel_bindings"]["backtest"]["pointer_path"],
            "pointer_sha256": ctx["snapshot"]["panel_bindings"]["backtest"]["pointer_sha256"],
            "target_stat": panel_stat(ctx["target"]),
            "target_sha256_status": "RAW_PROJECTION_RECEIPT_BOUND",
            "target_sha256_declared": target_sha,
            "panel_scan_receipt": {"path": str(FULL_RECEIPT), "sha256": sha_file(FULL_RECEIPT)},
            "row_count_scanned": scan_receipt["panel_rows_scanned"], "pool_rows_retained": scan_receipt["pool_rows_retained"]},
        "calendar": [row["target_date"] for row in revised_calendar],
        "calendar_source": "FROZEN_RAW_PROJECTION_OBSERVED_TRADE_DATE_KEYS_NOT_LIVE_CURRENT",
        "official_calendar_parity": "CANNOT_CONFIRM",
        "signal_date_range": [pairs[0][0], pairs[-1][0]] if pairs else [],
        "target_date_range": [pairs[0][1], pairs[-1][1]] if pairs else [],
        "target_date_cap": iso_day(TARGET_DATE_CAP),
        "qfq_manifest": BUILD_CONFIG["history_binding"]["qfq_manifest"],
        "engine_source_bindings": BUILD_CONFIG["engine_source_bindings"],
        "source_state_parent_binding": BUILD_CONFIG["source_manifest"],
        "exposed_targets_excluded": sorted(iso_day(day) for day in EXPOSED),
        "label_definition": dictionary["label_definition"],
        "label_price_series_identity": "ORIGINAL_ACCEPTED_ENGINE_SAME_SOURCE_TARGET_D_QFQ_ANCHOR",
        "label_historical_vintage": "CANNOT_CONFIRM",
        "truth_positive_denominator_by_date": {row["target_date"]: row["truth_positive_denominator"] for row in revised_calendar},
        "selection_slots_by_date": {row["target_date"]: row["selection_slots"] for row in revised_calendar},
        "candidate_rows": counts["candidate_rows"], "raw_candidate_union_rows": counts["raw_candidate_union_rows"],
        "raw_formula_natural_rows": counts["raw_formula_natural_rows"], "truth_rows": counts["rankable_truth_rows"],
        "technical_candidate_exclusions": counts["technical_candidate_exclusions"],
        "eligible_dates": len(eligible_dates), "eligible_target_dates": eligible_dates,
        "initial_train_target_dates": date_policy["initial_train_target_dates"],
        "oof_target_dates": date_policy["oof_target_dates"],
        "excluded_incomplete_target_dates": date_policy["excluded_incomplete_target_dates"],
        "all_incomplete_target_dates": date_policy["all_incomplete_target_dates"],
        "effect_acceptance_ceiling": date_policy["effect_acceptance_ceiling"],
        "training_allowed": False, "fit_count": 0, "oof_count": 0, "top50_selection_count": 0,
        "top100_truth_used_for_candidate_admission": False,
        "source_code_sha256": {str(path): sha_file(path) for path in source_code_paths},
        "canary_receipt": {"path": str(CANARY / "RECEIPT.json"), "sha256": sha_file(CANARY / "RECEIPT.json")},
        "full_projection_resource_receipt": {"path": str(work_dir / "PROJECTION_RESOURCE_RECEIPT.json"),
                                               "sha256": sha_file(work_dir / "PROJECTION_RESOURCE_RECEIPT.json")},
        "start_event_sha256": EXPECTED_START_EVENT_SHA,
        "input_review_status": "PENDING_INDEPENDENT_INPUT_REVIEW", **FLAGS}
    return manifest


def recover(config: Mapping[str, Any]) -> dict[str, Any]:
    require(config.get("schema") == "V194_MANIFEST_ONLY_RECOVERY_CONFIG_V1", "RECOVERY_CONFIG_SCHEMA_DRIFT")
    require(sha_file(__file__) == config["recovery_source_sha256"], "RECOVERY_SOURCE_DRIFT")
    _, control = bound_json(config["contract"])
    _, start = bound_json(config["start_receipt"])
    require(control["execution_id"] == start["execution_id"] == config["execution_id"]
            and start["event_type"] == "RUN_STARTED" and start["event_sha256"] == config["start_event_sha256"], "RECOVERY_START_IDENTITY_DRIFT")
    _, original = bound_json(config["original_build_config"])
    require(config["execution_id"] != original["execution_id"], "RECOVERY_EXECUTION_MUST_BE_DISTINCT")
    build = Path(original["build_dir"]).resolve()
    output = Path(config["output_dir"]).resolve()
    root = EVIDENCE_ROOT.resolve()
    require(build.is_relative_to(root / "inputs") and output.is_relative_to(root / "inputs")
            and not output.is_relative_to(build) and not build.is_relative_to(output), "RECOVERY_OUTPUT_ISOLATION_REQUIRED")
    require(not output.exists(), "RECOVERY_OUTPUT_ALREADY_EXISTS")
    _, identity = bound_json(config["original_build_identity"])
    require(identity["build_config_sha256"] == canonical_sha(original), "ORIGINAL_CONFIG_IDENTITY_DRIFT")
    require(identity["implementation_sha256"] == TEMPLATE_SHA, "ORIGINAL_SOURCE_IDENTITY_DRIFT")
    require(config["original_source"]["sha256"] == TEMPLATE_SHA
            and sha_file(config["original_source"]["path"]) == TEMPLATE_SHA, "ORIGINAL_SOURCE_DRIFT")
    _, original_contract = bound_json(original["contract"])
    _, snapshot = bound_json(original["panel_snapshot"])
    _, old_start = bound_json(original["start_receipt"])
    require(identity["contract_sha256"] == original["contract"]["sha256"]
            and identity["panel_snapshot_sha256"] == original["panel_snapshot"]["sha256"]
            and identity["start_receipt_sha256"] == original["start_receipt"]["sha256"]
            and old_start["event_sha256"] == original["start_event_sha256"], "ORIGINAL_CONTROL_IDENTITY_DRIFT")
    _, terminal = bound_json(config["original_failed_terminal"])
    require(terminal["child_returncode"] == 1 and terminal["fit_count"] == 0
            and terminal["execution_id"] == original["execution_id"], "ORIGINAL_FAILURE_PROVENANCE_DRIFT")
    _, scan = bound_json(config["panel_scan_receipt"])
    _, projection = bound_json(config["projection_receipt"])
    _, canary = bound_json(config["canary_receipt"])
    original_identity_sha = canonical_sha(identity)
    require(canary["build_identity_sha256"] == projection["identity_sha256"] == original_identity_sha, "PROJECTION_IDENTITY_DRIFT")
    require(projection["codes"] == identity["research_code_count"] == EXPECTED_CODE_COUNT, "PROJECTION_CODE_COUNT_DRIFT")
    keys_path = build / "RESEARCH_CODE_KEYS.csv"
    require(sha_file(keys_path) == identity["research_code_list_sha256"], "RESEARCH_KEYS_DRIFT")
    keys = [r["code"] for r in saved_csv(keys_path)]
    require(len(keys) == len(set(keys)) == EXPECTED_CODE_COUNT, "RESEARCH_KEY_COUNT_DRIFT")
    target = Path(identity["panel_target_path"])
    require(panel_stat(target) == identity["panel_target_stat"], "ORIGINAL_RAW_TARGET_STAT_DRIFT")
    _, raw_binding = bound_json(original["history_binding"]["qfq_manifest"])
    target_sha = snapshot["panel_bindings"]["backtest"]["target_sha256"]
    require(raw_binding["raw_artifact"]["path"] == str(target) and raw_binding["raw_artifact"]["sha256"] == target_sha,
            "RAW_PROJECTION_PROVENANCE_DRIFT")
    files, values = {}, {}
    for key, filename in OUTPUT_FILES.items():
        path = build / filename
        record = config["saved_outputs"][key]
        require(Path(record["path"]).resolve() == path.resolve(), "SAVED_OUTPUT_PATH_DRIFT:" + key)
        files[key], values[key] = fingerprint_saved(path, record["stat"])
    calendar = saved_csv(files["calendar"]["path"])
    coverage = saved_csv(files["coverage"]["path"])
    stocks = saved_csv(files["stock_coverage"]["path"])
    require([r["code"] for r in stocks] == keys, "SAVED_STOCK_UNIVERSE_DRIFT")
    require(len(calendar) == len(coverage) and calendar, "SAVED_CALENDAR_COVERAGE_DRIFT")
    numeric = ("truth_positive_denominator", "truth_rankable_research_rows", "selection_slots", "candidate_rows", "raw_candidate_union_rows")
    for row, cover in zip(calendar, coverage):
        require(row["target_date"] == cover["target_date"], "SAVED_COVERAGE_DATE_DRIFT")
        for field in numeric:
            require(int(row[field]) == int(cover[field]), "SAVED_COVERAGE_COUNT_DRIFT:" + field)
            row[field] = int(row[field])
        require(row["truth_positive_denominator"] == min(100, row["truth_rankable_research_rows"])
                and row["selection_slots"] == 0, "SAVED_DENOMINATOR_OR_SELECTION_DRIFT")
        require(row["target_date"].replace("-", "") <= TARGET_DATE_CAP, "TARGET_CAP_DRIFT")
    counts = saved_counts(calendar, stocks, files)
    policy = values["date_policy"]
    require(not (set(policy["eligible_target_dates"]) & {d[:4]+"-"+d[4:6]+"-"+d[6:] for d in EXPOSED}), "EXPOSED_TARGET_ELIGIBILITY_DRIFT")
    original_dictionary = values["dictionary"]
    dictionary = dict(original_dictionary)
    dictionary["panel_numeric_policy"] = snapshot["selected_panel_schema"]["conversion_rule"]
    output.mkdir(parents=True)
    corrected_dictionary = output / "DATA_DICTIONARY.json"
    write_new(corrected_dictionary, dictionary)
    dictionary_original = dict(files["dictionary"])
    files["dictionary"] = dict(path=str(corrected_dictionary), sha256=sha_file(corrected_dictionary), rows=-1)
    source_code_paths = []
    for raw_path, expected in config["original_source_code_bindings"].items():
        path = Path(raw_path)
        require(sha_file(path) == expected, "ORIGINAL_DEPENDENCY_SOURCE_DRIFT:" + str(path))
        source_code_paths.append(path)
    manifest = recovered_manifest(original, identity, snapshot, original_contract, scan, files, calendar,
                                  policy, dictionary, counts, source_code_paths, output)
    provenance = dict(recovery_execution_id=config["execution_id"], original_producer_execution_id=original["execution_id"],
        original_producer_terminal=config["original_failed_terminal"], original_build_identity=config["original_build_identity"],
        original_config=config["original_build_config"], original_source=config["original_source"],
        recovery_source_sha256=config["recovery_source_sha256"], recovery_contract=config["contract"],
        recovery_start_receipt=config["start_receipt"], raw_projection_receipt=raw_binding["raw_projection_result"],
        target_sha_source="Frozen RAW R2 producer result; not an existing daily-receipt certification.",
        dictionary_correction=dict(original=dictionary_original, corrected=files["dictionary"],
            changed_fields={"panel_numeric_policy":dict(before=original_dictionary["panel_numeric_policy"],after=dictionary["panel_numeric_policy"])}),
        preserved_outputs=config["saved_outputs"], physical_truth_rows=files["truth"]["rows"],
        rankable_truth_rows=counts["rankable_truth_rows"], formula_evaluations=0, labels_recomputed=0, fits=0,
        **FLAGS)
    manifest.update(metadata_recovery=provenance, maximum_claim="DIRECTION_ONLY", whole_input_status="CANNOT_CONFIRM")
    write_new(output / "RECOVERY_PROVENANCE.json", provenance)
    write_new(output / "MANIFEST.json", manifest)
    receipt = dict(schema="V194_LONG_INPUT_BUILD_RECEIPT_V1", execution_id=config["execution_id"],
        original_producer_execution_id=original["execution_id"], manifest_path=str(output/"MANIFEST.json"),
        manifest_sha256=sha_file(output/"MANIFEST.json"), input_files=files, research_code_count=len(keys),
        calendar_count=len(calendar), truth_rows=counts["rankable_truth_rows"],
        physical_truth_file_rows=files["truth"]["rows"], **{k:v for k,v in counts.items() if k != "rankable_truth_rows"},
        fit_count=0, oof_count=0, top50_selection_count=0, status="INPUT_BUILD_READY_FOR_INDEPENDENT_REVIEW",
        original_csv_writes=0, original_dictionary_writes=0, formula_evaluations=0, labels_recomputed=0,
        CANNOT_CONFIRM=["historical all-A universe", "official calendar parity", "historical capture-time PIT",
                       "historical label maturity", "per-route A194 dataset passport", "independent review"], **FLAGS)
    write_new(output / "BUILD_RECEIPT.json", receipt)
    for key, filename in OUTPUT_FILES.items():
        require(panel_stat(build/filename) == config["saved_outputs"][key]["stat"], "SAVED_OUTPUT_CHANGED_AFTER_RECOVERY:"+key)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--config-sha256", required=True)
    args = parser.parse_args()
    require(sha_file(args.config) == args.config_sha256, "RECOVERY_CONFIG_SHA_DRIFT")
    result = recover(load_json(args.config))
    print(json.dumps({k:result[k] for k in ("status","manifest_path","manifest_sha256","truth_rows","candidate_rows","fit_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
