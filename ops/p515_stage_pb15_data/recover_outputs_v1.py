#!/usr/bin/env python3
"""Recover duplicated postprocessing from the already frozen PB15 run.

This script reads only existing run outputs. It makes no Reader, R2, feature,
model, preprocessing, or network call. Its scope is exact byte-identical
candidate deduplication followed by the frozen pure fold/serialization builder.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys

ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
RUN = ROOT / "artifacts/p515_stage_pb15_data_materialization_r1_v1/run_p515-stage-pb15-20261119T1407550800-87f5df8cf3b949da9d473b7dc2d63ea2"
RECOVERY = RUN / "recovery_v1"
SHARDS = RUN / "shards"
ORIGINAL_SCRIPT = RUN / "CODE_SNAPSHOT.py"
EXPECTED_WRITER_SHA = "bd7a9b218c3204ea69b8657424b0bcf5ca19e585eab7a07fab0d8361deca26f1"
EXPECTED_RUN_ID = "p515-stage-pb15-20261119T1407550800-87f5df8cf3b949da9d473b7dc2d63ea2"
EXPECTED_SHARDS = 4
MODEL_KEYS = ("model_fit", "preprocessing_fit", "model_api", "new_probability",
              "static_new_score", "model_deserialization", "tuning")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                              indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def jsonl_rows(path: Path):
    with path.open("rb") as f:
        for line_no, raw in enumerate(f, 1):
            if not raw.strip():
                continue
            yield line_no, raw.rstrip(b"\r\n"), json.loads(raw)


def audit_jsonl(path: Path, identity_fields: tuple[str, ...]) -> dict:
    groups = defaultdict(list)
    exact_line_counter = Counter()
    for line_no, raw, doc in jsonl_rows(path):
        key = tuple(doc.get(k) for k in identity_fields)
        groups[key].append((line_no, raw))
        exact_line_counter[raw] += 1
    duplicate_keys = []
    byte_identical_key_groups = 0
    for key, rows in groups.items():
        if len(rows) <= 1:
            continue
        raw_set = {raw for _, raw in rows}
        duplicate_keys.append({"key": list(key), "occurrences": len(rows),
            "line_numbers": [n for n, _ in rows], "byte_identical": len(raw_set) == 1})
        if len(raw_set) == 1:
            byte_identical_key_groups += 1
    return {"path": str(path), "bytes": path.stat().st_size,
        "sha256": sha(path.read_bytes()), "rows": sum(len(x) for x in groups.values()),
        "unique_keys": len(groups), "duplicate_key_groups": len(duplicate_keys),
        "duplicate_excess_rows": sum(len(x) - 1 for x in groups.values() if len(x) > 1),
        "byte_identical_duplicate_key_groups": byte_identical_key_groups,
        "duplicate_keys_sample": duplicate_keys[:8],
        "duplicate_exact_line_excess": sum(n - 1 for n in exact_line_counter.values() if n > 1)}


def audit_csv(path: Path, identity_fields: tuple[str, ...]) -> dict:
    import csv
    import io
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    counts = Counter(tuple(row.get(k) for k in identity_fields) for row in rows)
    return {"path": str(path), "bytes": len(raw), "sha256": sha(raw),
        "rows": len(rows), "columns": len(rows[0]) if rows else len(text.splitlines()[0].split(",")) if text else 0,
        "unique_keys": len(counts), "duplicate_key_groups": sum(n > 1 for n in counts.values()),
        "duplicate_excess_rows": sum(n - 1 for n in counts.values() if n > 1)}


def import_frozen_writer():
    raw = ORIGINAL_SCRIPT.read_bytes()
    digest = sha(raw)
    if digest != EXPECTED_WRITER_SHA:
        raise RuntimeError(f"FROZEN_WRITER_SHA_MISMATCH:{digest}")
    spec = importlib.util.spec_from_file_location("p515_frozen_postprocessor", ORIGINAL_SCRIPT)
    if not spec or not spec.loader:
        raise RuntimeError("FROZEN_WRITER_IMPORT_FAILED")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, digest


def main():
    if RUN.name != f"run_{EXPECTED_RUN_ID}" or not (RUN / "PRE_READ_FREEZE.json").exists():
        raise RuntimeError("UNEXPECTED_RUN_ID_OR_NO_PRE_READ_FREEZE")
    if RECOVERY.exists() and any(RECOVERY.iterdir()):
        raise RuntimeError(f"RECOVERY_DIR_NOT_EMPTY:{RECOVERY}")
    RECOVERY.mkdir(parents=True, exist_ok=True)
    start = {"run_id": EXPECTED_RUN_ID, "recovery_id": "RECOVERY_V1_EXACT_CANDIDATE_DEDUP",
        "started_at": now(), "state": "STARTED", "original_result_preserved": True,
        "reader_calls": 0, "pure_r2_calls": 0, "feature_rebuilds": 0,
        "model_counters": {k: 0 for k in MODEL_KEYS}}
    dump(RECOVERY / "RECOVERY_START.json", start)
    original_counter = json.loads((RUN / "EXECUTION_COUNTERS.json").read_text(encoding="utf-8"))
    original_admission = json.loads((RUN / "DATA_ADMISSION.json").read_text(encoding="utf-8"))
    writer, writer_sha = import_frozen_writer()
    shutil.copyfile(Path(__file__).resolve(), RECOVERY / "RECOVERY_CODE_SNAPSHOT.py")
    recovery_code_sha = sha((RECOVERY / "RECOVERY_CODE_SNAPSHOT.py").read_bytes())

    # Audit logical records before changing anything. These are immutable original outputs.
    audit = {"candidate_shards": [], "other_outputs": {}, "merged_outputs": {}}
    candidate_by_id = defaultdict(list)
    for sid in range(EXPECTED_SHARDS):
        p = SHARDS / f"shard_{sid:02d}" / "CANDIDATE_LEDGER.jsonl"
        item = audit_jsonl(p, ("candidate_id",))
        audit["candidate_shards"].append(item)
        for line_no, raw, doc in jsonl_rows(p):
            candidate_by_id[doc["candidate_id"]].append({"shard_id": sid,
                "line_no": line_no, "raw": raw, "doc": doc})

    for sid in range(EXPECTED_SHARDS):
        sd = SHARDS / f"shard_{sid:02d}"
        for fname, fields in (
            ("R2_MOTHERS.jsonl", ("family_id",)),
            ("R2_PULLBACKS.jsonl", ("pullback_id",)),
            ("R2_CANDIDATE_MOTHER_DAILY.jsonl", ("symbol", "candidate_date", "family_id", "pullback_id")),
            ("BAR_WITNESS.jsonl", ("security", "trade_date")),
            ("SOURCE_COVERAGE.jsonl", ("security",)),
        ):
            audit["other_outputs"][f"shard_{sid:02d}/{fname}"] = audit_jsonl(sd / fname, fields)
    for fname, fields in (
        ("CANDIDATE_LEDGER.jsonl", ("candidate_id",)),
        ("R2_MOTHERS.jsonl", ("family_id",)),
        ("R2_PULLBACKS.jsonl", ("pullback_id",)),
        ("R2_CANDIDATE_MOTHER_DAILY.jsonl", ("symbol", "candidate_date", "family_id", "pullback_id")),
        ("BAR_WITNESS.jsonl", ("security", "trade_date")),
    ):
        audit["merged_outputs"][fname] = audit_jsonl(RUN / fname, fields)
    for fname, fields in (
        ("SOURCE_DISPOSITION.csv", ("代码",)),
        ("HISTORICAL_SCREEN_DAILY.csv", ("security", "decision_date")),
        ("HISTORICAL_SCREEN_ANCHORS.csv", ("security", "decision_date", "anchor_date")),
        ("NATIVE_R2_DAILY_STATUS.csv", ("security", "decision_date", "parent_id", "pb_id")),
    ):
        audit["merged_outputs"][fname] = audit_csv(RUN / fname, fields)

    expected_ids = []
    dedup_records = []
    duplicate_pairs = []
    duplicate_errors = []
    for candidate_id, items in sorted(candidate_by_id.items()):
        raw_set = {x["raw"] for x in items}
        if (len(items) != 2 or len(raw_set) != 1
                or len({x["shard_id"] for x in items}) != 1):
            duplicate_errors.append({"candidate_id": candidate_id, "occurrences": len(items),
                                     "byte_identical_versions": len(raw_set),
                                     "shards": sorted({x["shard_id"] for x in items})})
            continue
        entry = items[0]
        doc = entry["doc"]
        if doc.get("features") is not None:
            packed = bytes.fromhex(doc["input_hex"])
            if len(packed) != 80 or sha(packed) != doc["input_sha256"]:
                duplicate_errors.append({"candidate_id": candidate_id, "error": "INPUT_80B_SHA_MISMATCH"})
                continue
        dedup_records.append((candidate_id, entry["raw"], doc))
        duplicate_pairs.append({"candidate_id": candidate_id,
            "source_shard": entry["shard_id"], "source_lines": [x["line_no"] for x in items],
            "duplicate_count": 2, "byte_identical": True,
            "source_sha256": sha(entry["raw"])})
    if duplicate_errors:
        raise RuntimeError(f"CANDIDATE_DUPLICATE_AUDIT_FAILED:{duplicate_errors[:5]!r}")
    audit["candidate_unique_ids"] = len(candidate_by_id)
    audit["candidate_rows_before"] = sum(len(v) for v in candidate_by_id.values())
    audit["candidate_rows_after_exact_dedup"] = len(dedup_records)
    audit["exact_duplicate_pairs"] = len(duplicate_pairs)
    audit["all_candidate_duplicate_pairs_byte_identical"] = len(duplicate_pairs) == len(candidate_by_id)
    audit["candidate_duplicate_pair_sha256"] = sha(json.dumps(duplicate_pairs, sort_keys=True,
        separators=(",", ":")).encode())
    audit["candidate_duplicate_errors"] = duplicate_errors
    merged_candidate = audit["merged_outputs"]["CANDIDATE_LEDGER.jsonl"]
    if (merged_candidate["rows"] != audit["candidate_rows_before"]
            or merged_candidate["unique_keys"] != audit["candidate_unique_ids"]
            or merged_candidate["duplicate_key_groups"] != audit["candidate_unique_ids"]
            or merged_candidate["duplicate_excess_rows"] != audit["candidate_unique_ids"]
            or merged_candidate["byte_identical_duplicate_key_groups"] != audit["candidate_unique_ids"]):
        raise RuntimeError(f"MERGED_CANDIDATE_DUPLICATION_SHAPE_MISMATCH:{merged_candidate}")
    dump(RECOVERY / "DUPLICATE_AUDIT.json", audit)
    with (RECOVERY / "DUPLICATE_PAIR_INDEX.jsonl").open("w", encoding="utf-8") as f:
        for row in duplicate_pairs:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    canonical = RECOVERY / "CANONICAL_MATERIALIZATION"
    canonical.mkdir()
    dedup_records.sort(key=lambda x: (str(x[2]["security"]), str(x[2]["decision_date"]), x[0]))
    with (canonical / "CANDIDATE_LEDGER_SOURCE_DEDUP.jsonl").open("wb") as f:
        for _, raw, _ in dedup_records:
            f.write(raw + b"\n")
    candidates = [doc for _, _, doc in dedup_records]
    folded = writer.build_folds(canonical, candidates)

    # Revalidate serialized rows and fold boundaries using only materialized values.
    matrix_path = canonical / "MODEL_INPUTS_10_F64LE.bin"
    index_path = canonical / "MODEL_INPUT_INDEX.jsonl"
    index_rows = [json.loads(x) for x in index_path.read_text(encoding="utf-8").splitlines() if x]
    if matrix_path.stat().st_size != 80 * len(index_rows):
        raise RuntimeError("RECOVERED_MATRIX_LENGTH_MISMATCH")
    matrix = matrix_path.read_bytes()
    for i, row in enumerate(index_rows):
        raw = matrix[i * 80:(i + 1) * 80]
        if len(raw) != 80 or sha(raw) != row["input_sha256"]:
            raise RuntimeError(f"RECOVERED_MATRIX_SHA_MISMATCH:{i}")
        vals = struct.unpack("<10d", raw)
        if len(vals) != 10:
            raise RuntimeError(f"RECOVERED_MATRIX_WIDTH_MISMATCH:{i}")
    fold_members = [json.loads(x) for x in (canonical / "FOLD_MEMBERSHIP.jsonl").read_text(encoding="utf-8").splitlines() if x]
    fold_validation = []
    for fold in ("F1", "F2", "F3"):
        members = [x for x in fold_members if x["fold"] == fold]
        train = [x for x in members if x["role"] == "TRAIN"]
        hold = [x for x in members if x["role"] == "HOLDOUT_INPUT"]
        train_mothers = {x["parent_id"] for x in train}
        hold_mothers = {x["parent_id"] for x in hold}
        earliest = next(x["earliest_holdout_mother_first_d"] for x in folded["fold_gates"] if x["fold"] == fold)
        strict = all(x["decision_date"] < earliest and x["label_end_date"] < earliest for x in train) if earliest else False
        sums = defaultdict(float)
        for row in train: sums[row["parent_id"]] += row["sample_weight"]
        weights_one = all(abs(v - 1.0) < 1e-12 for v in sums.values())
        if train_mothers & hold_mothers:
            raise RuntimeError(f"RECOVERED_MOTHER_LEAKAGE:{fold}")
        if not strict:
            raise RuntimeError(f"RECOVERED_TEMPORAL_PURGE_FAILURE:{fold}")
        if not weights_one:
            raise RuntimeError(f"RECOVERED_MOTHER_WEIGHT_FAILURE:{fold}")
        if any(x["label_status"] != "MATURED_TERMINAL" for x in hold):
            raise RuntimeError(f"UNRESOLVED_HOLDOUT_ENTERED_PREDICTION_INPUT:{fold}")
        fold_validation.append({"fold": fold, "train_rows": len(train),
            "train_mothers": len(train_mothers), "holdout_mature_prediction_rows": len(hold),
            "holdout_mothers": len(hold_mothers), "earliest_holdout_mother_first_d": earliest,
            "mother_sets_disjoint": True, "strict_d_and_label_end_purge": True,
            "per_mother_training_weights_sum_to_one": True,
            "holdout_prediction_rows_all_matured": True})

    original_snapshot = []
    for path in sorted(RUN.rglob("*")):
        if path.is_file() and RECOVERY not in path.parents:
            raw = path.read_bytes()
            original_snapshot.append({"path": str(path.relative_to(RUN)),
                "bytes": len(raw), "sha256": sha(raw)})
    original_snapshot_doc = {"run_id": EXPECTED_RUN_ID, "captured_at": now(),
        "note": "Original outputs are preserved; this snapshot includes duplicated pre-recovery ledgers.",
        "members": original_snapshot}
    dump(RECOVERY / "ORIGINAL_OUTPUTS_SNAPSHOT.json", original_snapshot_doc)
    recovery_result = {
        "run_id": EXPECTED_RUN_ID, "recovery_id": "RECOVERY_V1_EXACT_CANDIDATE_DEDUP",
        "recovered_at": now(), "original_writer_sha256": writer_sha,
        "recovery_code_sha256": recovery_code_sha,
        "cause": "candidate rows appended directly and also flushed from candidate_docs; only exact byte-identical pairs were collapsed",
        "source_candidate_rows_before": audit["candidate_rows_before"],
        "source_unique_candidate_ids": audit["candidate_unique_ids"],
        "source_candidate_rows_after": len(candidates),
        "exact_duplicate_pairs_removed": audit["exact_duplicate_pairs"],
        "feature_status_counts": dict(Counter(c.get("feature_status") for c in candidates)),
        "label_status_counts": dict(Counter(c.get("label_status") for c in candidates)),
        "r2_active_track_count_counts": dict(Counter(str(c.get("native_track_count")) for c in candidates)),
        "model_input_rows": len(index_rows), "model_input_binary_bytes": matrix_path.stat().st_size,
        "model_input_binary_sha256": sha(matrix),
        "fold_rebuild": folded, "fold_validation": fold_validation,
        "model_counters": {k: 0 for k in MODEL_KEYS},
        "reader_calls_during_recovery": 0, "pure_r2_calls_during_recovery": 0,
        "feature_recalculations_during_recovery": 0,
        "original_execution_counters_path": str(RUN / "EXECUTION_COUNTERS.json"),
        "original_execution_counters_sha256": sha((RUN / "EXECUTION_COUNTERS.json").read_bytes()),
        "original_data_admission": original_admission,
    }
    dump(RECOVERY / "RECOVERY_RESULT.json", recovery_result)
    recovery_counter = {
        "run_id": EXPECTED_RUN_ID, "recovery_id": "RECOVERY_V1_EXACT_CANDIDATE_DEDUP",
        "recovery_started_at": start["started_at"], "recovery_finished_at": now(),
        "recovery_only_read_existing_outputs": True,
        "reader_calls": 0, "pure_r2_run_symbol_calls": 0, "feature_build_attempts": 0,
        "candidate_input_rows_deduped": len(candidates), "candidate_duplicate_pairs_removed": len(duplicate_pairs),
        "model_input_rows_serialized_from_existing_hex": len(index_rows),
        "model_fit": 0, "preprocessing_fit": 0, "model_api": 0,
        "new_probability": 0, "static_new_score": 0, "model_deserialization": 0, "tuning": 0,
        "original_model_input_bin_bytes": (RUN / "MODEL_INPUTS_10_F64LE.bin").stat().st_size,
        "recovered_model_input_bin_bytes": matrix_path.stat().st_size,
    }
    dump(RECOVERY / "RECOVERY_EXECUTION_COUNTERS.json", recovery_counter)
    dump(RECOVERY / "RECOVERY_END.json", {"run_id": EXPECTED_RUN_ID,
        "recovery_id": "RECOVERY_V1_EXACT_CANDIDATE_DEDUP", "finished_at": now(),
        "state": "RECOVERY_COMPLETE_WITH_ORIGINAL_RUN_PRESERVED"})
    members = []
    for path in sorted(RECOVERY.rglob("*")):
        if path.is_file() and path.name != "RECOVERY_MANIFEST.json":
            raw = path.read_bytes()
            members.append({"path": str(path.relative_to(RECOVERY)), "bytes": len(raw), "sha256": sha(raw)})
    dump(RECOVERY / "RECOVERY_MANIFEST.json", {"run_id": EXPECTED_RUN_ID,
        "recovery_id": "RECOVERY_V1_EXACT_CANDIDATE_DEDUP", "generated_at": now(),
        "original_outputs_preserved": True, "members": members})
    print(json.dumps({"status": "RECOVERY_COMPLETE", "recovery_dir": str(RECOVERY),
        "candidate_rows_before": audit["candidate_rows_before"],
        "candidate_rows_after": len(candidates), "duplicate_pairs_removed": len(duplicate_pairs),
        "model_input_rows": len(index_rows), "model_input_bytes": matrix_path.stat().st_size,
        "dataset_admission": folded["dataset_admission"],
        "reader_r2_feature_model_counters": [0, 0, 0, 0]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
