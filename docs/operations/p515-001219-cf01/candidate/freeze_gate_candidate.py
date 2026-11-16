"""Versioned synthetic/empty readiness gate for P5.15 common-A work.

This is an isolated candidate derived from the accepted V1 gate. It adds
sealed-history result provenance and separates immutable global_F from each
per-D generation/output/evaluation clock. It never fits or predicts.
"""
from datetime import datetime, time
import hashlib
import json
import re
from zoneinfo import ZoneInfo

VERSION = "P515_CODEX_MAC_COMMON_A_FORWARD_READINESS_CF01_CLOCK_V2"
SHANGHAI = ZoneInfo("Asia/Shanghai")
ZERO = {"fit": 0, "preprocess_fit": 0, "model_predictions": 0, "new_weights": 0, "formal_labels": 0}
PERMISSIONS = {"fit": False, "predict": False, "forward_enroll": False,
               "production": False, "buy_gate_update": False, "frozen_abcd_write": False}
MATERIALS = ("model", "preprocessor", "training_manifest", "model_code",
             "mapping_contract", "panel_manifest", "history_manifest")
RESULTS = ("result_pb", "result_mother")
GLOBAL_F_DOMAIN = "P515_GLOBAL_F_CLOCK_V1"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def global_f_digest(value):
    return digest({"domain": GLOBAL_F_DOMAIN, "global_F": value})


def rule(ok, code):
    if not ok:
        raise ValueError(code)


def time_at(value):
    dt = datetime.fromisoformat(value)
    rule(dt.tzinfo is not None and dt.utcoffset() is not None, "TIMEZONE_REQUIRED")
    return dt


def hash_ok(value):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{64}", value) is not None


def key_of(row):
    return tuple(row[k] for k in ("security", "pb", "mother", "D"))


def append(rows, event):
    prior = rows[-1]["sha256"] if rows else "0" * 64
    new = {**event, "seq": len(rows) + 1, "prior_sha256": prior}
    return [*rows, new | {"sha256": digest(new)}]


def _validate_history_evidence(row, name, sealed_at, global_f):
    result = row[name]
    role, object_id, hop = (("PB", row["pb"], "PB15") if name == "result_pb"
                           else ("MOTHER", row["mother"], "MOTHER_FINAL"))
    rule(result["history_member_id"] == row["history_id"], "HISTORY_EVIDENCE_MEMBER_IDENTITY")
    rule(result["result_role"] == role and result["result_object_id"] == object_id
         and result["hop"] == hop and bool(result["result_id"]) and bool(result["source_id"]),
         "HISTORY_RESULT_OBJECT_IDENTITY")
    payload = result["evidence_payload"]
    expected = {"history_member_id": result["history_member_id"],
                "result_id": result["result_id"], "result_role": role,
                "result_object_id": object_id, "hop": hop, "source_id": result["source_id"],
                "outcome": result["outcome"], "mature_at": result["mature_at"]}
    rule(payload == expected and hash_ok(result["evidence_sha256"])
         and digest(payload) == result["evidence_sha256"], "HISTORY_EVIDENCE_PAYLOAD_HASH")
    mature, acquired = time_at(result["mature_at"]), time_at(result["acquired_at"])
    rule(mature <= acquired <= sealed_at < global_f, "HISTORY_RESULT_AFTER_SEAL")
    return mature, acquired


def _validate_history(record, actual, global_f):
    rows = record["history_rows"]
    ids = [row["history_id"] for row in rows]
    rule(len(ids) == len(set(ids)), "DUPLICATE_HISTORY")
    manifest = record["history_manifest"]
    rule(manifest["seal_status"] == "SEALED", "HISTORY_MANIFEST_UNSEALED")
    rule(manifest["member_count"] == len(rows) and manifest["member_ids"] == sorted(ids),
         "HISTORY_MANIFEST_MEMBER_SET")
    ordered_rows = sorted(rows, key=lambda row: row["history_id"])
    rule(manifest["rows_sha256"] == digest(ordered_rows), "HISTORY_MANIFEST_ROWS_HASH")
    body = {key: value for key, value in manifest.items() if key != "sha256"}
    rule(hash_ok(manifest["sha256"]) and digest(body) == manifest["sha256"],
         "HISTORY_MANIFEST_DIGEST")
    identity = actual["history_manifest"]
    rule(identity["artifact_id"] == manifest["manifest_id"]
         and identity["sha256"] == manifest["sha256"]
         and identity["frozen_at"] == manifest["frozen_at"], "HISTORY_MANIFEST_FREEZE_BINDING")
    sealed_at = time_at(manifest["frozen_at"])
    rule(sealed_at < global_f, "HISTORY_MANIFEST_AFTER_GLOBAL_F")
    for row in rows:
        rule(row["origin"] == "ARCHIVE_PRE_F" and hash_ok(row["prefix_sha256"])
             and time_at(row["available_at"]) <= sealed_at, "HISTORY_FEEDBACK_OR_LATE")
        pb_mature, _ = _validate_history_evidence(row, "result_pb", sealed_at, global_f)
        mother_mature, _ = _validate_history_evidence(row, "result_mother", sealed_at, global_f)
        d = datetime.fromisoformat(row["D"]).date()
        rule(d < pb_mature.astimezone(SHANGHAI).date()
             <= mother_mature.astimezone(SHANGHAI).date(), "HISTORY_IDENTITY_OR_DUAL_MATURITY")
    return {row["history_id"]: row for row in rows}, sealed_at


def chain(log):
    prior, timestamp, chain_ids = "0" * 64, None, set()
    for idx, row in enumerate(log, 1):
        r = dict(row)
        seal = r.pop("sha256")
        rule(r["seq"] == idx and r["prior_sha256"] == prior and digest(r) == seal, "APPEND_ONLY_CHAIN")
        stamp = time_at(r["recorded_at"])
        rule(timestamp is None or stamp >= timestamp, "APPEND_ONLY_TIME_ORDER")
        rule(r["record_id"] not in chain_ids, "DUPLICATE_RECORD_ID")
        if r["kind"] in {"CORRECTION", "REVOKED"}:
            rule(r.get("related_record_id") in chain_ids, "CORRECTION_WITHOUT_ORIGINAL")
        prior, timestamp = seal, stamp
        chain_ids.add(r["record_id"])
    return prior


def validate(record):
    rule(record["schema_version"] == VERSION, "VERSION_MISMATCH")
    rule("F" not in record and "formal_F" not in record, "LEGACY_F_ALIAS_FORBIDDEN")
    rule(record["permissions"] == PERMISSIONS and record["new_counts"] == ZERO, "UNAUTHORIZED_EXECUTION")
    codes = record["panel"]
    rule(codes and codes[0] == "001219.SZ" and len(codes) <= 20 and len(set(codes)) == len(codes)
         and codes[1:] == sorted(codes[1:]) and all(re.fullmatch(r"[0-9]{6}\.(SZ|SH|BJ)", s) for s in codes),
         "BAD_PANEL")
    anchor = record["readiness_binding"]
    rule(all(hash_ok(anchor[x]) for x in ("master_route_sha256", "inventory_sha256",
                                           "panel_proposal_sha256", "engine_candidate_sha256",
                                           "old_riskset_sha256", "schema_sha256",
                                           "gate_validator_sha256")), "BAD_READINESS_BINDING")
    log = record["exposure_log"]
    rule(chain(log) == record["exposure_head_sha256"], "EXPOSURE_HEAD_MISMATCH")
    if record["mode"] == "PREPARATION_ONLY":
        rule(record["global_F"] is None and record["global_F_sha256"] is None
             and record["fit_completed_at"] is None and record["forward_rows"] == []
             and record["history_rows"] == [] and record["history_manifest"] is None
             and record["training_rows"] == [] and record["actual_freezes"] is None,
             "PREPARATION_MUST_REMAIN_EMPTY")
        return True
    rule(record["mode"] == "SYNTHETIC_FIXTURE", "FORMAL_FORBIDDEN_IN_V2")
    global_f = time_at(record["global_F"])
    rule(record["global_F_sha256"] == global_f_digest(record["global_F"]), "GLOBAL_F_BINDING_MISMATCH")
    actual = record["actual_freezes"]
    for name in MATERIALS:
        identity = actual[name]
        rule(hash_ok(identity["sha256"]) and identity["artifact_id"].startswith("SYN-"),
             "UNBOUND_FREEZE_ARTIFACT")
        rule(time_at(identity["frozen_at"]) < global_f, "GLOBAL_F_PRECEDES_FREEZE")
    rule(time_at(record["fit_completed_at"]) <= time_at(actual["model"]["frozen_at"]),
         "MODEL_FREEZE_PRECEDES_FIT")
    train = record["training_rows"]
    rule(all(row["security"] not in codes for row in train), "VALIDATION_SECURITY_IN_A")
    rule(all(datetime.fromisoformat(row["D"]).date() < time_at(row["result_mature_at"]).astimezone(SHANGHAI).date()
             and time_at(row["result_mature_at"]) < global_f and type(row["y"]) is int
             and row["target"] == "Y_PB_PATH_15D" and row["source_permission"] == "SYNTHETIC_ONLY"
             and hash_ok(row["source_sha256"]) for row in train), "TRAINING_ADMISSION_OR_MATURITY")
    rule({x["y"] for x in train} == {0, 1} and len({key_of(x) for x in train}) == len(train),
         "TWO_CLASSES_AND_UNIQUE_TRAINING_KEYS")
    known, sealed_at = _validate_history(record, actual, global_f)
    used = set()
    for row in record["forward_rows"]:
        key = key_of(row)
        rule(key not in used and row["security"] in codes, "DUPLICATE_OR_UNKNOWN_FORWARD_KEY")
        used.add(key)
        rule(not any(name in row for name in ("F", "formal_F", "global_F")),
             "ROW_LEVEL_GLOBAL_F_FORBIDDEN")
        rule(row["global_F_binding_sha256"] == record["global_F_sha256"], "ROW_GLOBAL_F_BINDING_MISMATCH")
        unknown = row["status"] == "EXPOSURE_UNKNOWN" and row["exposure"] == "UNKNOWN"
        rule(row["pb_age"] == 3 and (unknown or row["exposure"] == "FIRST_SEEN_AFTER_F")
             and time_at(row["mother_formed_at"]) > global_f, "EXPOSED_OR_PRE_F_EVENT")
        d = datetime.fromisoformat(row["D"]).date()
        cut = time_at(row["D_cutoff"])
        rule(cut.astimezone(SHANGHAI) == datetime.combine(d, time(15), SHANGHAI), "WRONG_D_CUTOFF")
        first_bar = time_at(row["first_evaluation_bar_at"])
        formed = time_at(row["mother_formed_at"])
        rule(formed <= cut < first_bar, "INVALID_EVENT_OR_EVALUATION_CLOCK")
        features = row["input"]
        if row["status"] in {"INPUT_MISSING", "INPUT_LATE", "OUTPUT_LATE", "EXPOSURE_UNKNOWN"}:
            rule(row["outputs"] is None, "NO_BACKFILL_OUTPUT")
            rule(row["generated_at"] is None and row["output_frozen_at"] is None,
                 "INCOMPLETE_ROW_CANNOT_HAVE_CLOCKED_OUTPUT")
            continue
        rule(row["status"] == "PAIRED_FROZEN", "UNKNOWN_FORWARD_STATUS")
        rule(hash_ok(features["sha256"]) and hash_ok(features["source_manifest_sha256"])
             and bool(features["reference_version"]), "UNBOUND_D_INPUT")
        generated, output_frozen = time_at(row["generated_at"]), time_at(row["output_frozen_at"])
        available = time_at(features["available_at"])
        rule(time_at(features["max_feature_time"]) <= cut
             and max(cut, available) <= generated <= output_frozen < first_bar,
             "GEMINI_PER_D_CLOCK_ORDER")
        rule(all(hid in known for hid in row["history_refs"]), "UNKNOWN_HISTORY_KEY")
        hist_rows = [known[hid] for hid in row["history_refs"]]
        rule(len({h["mother"] for h in hist_rows}) == len(hist_rows), "DUPLICATE_HISTORICAL_MOTHER")
        rule(all(h["security"] == row["security"] and h["mother"] != row["mother"]
                 and h["ordinal_group"] == row["ordinal_group"] and h["pb_age"] == 3
                 and h["at_risk_at_k3"] and h["D"] < row["D"]
                 and datetime.fromisoformat(h["D"]).date()
                 < time_at(h["result_pb"]["mature_at"]).astimezone(SHANGHAI).date()
                 <= time_at(h["result_mother"]["mature_at"]).astimezone(SHANGHAI).date()
                 < d and time_at(h["available_at"]) <= generated
                 and time_at(h["result_pb"]["acquired_at"]) <= sealed_at
                 and time_at(h["result_mother"]["acquired_at"]) <= sealed_at for h in hist_rows),
             "HISTORY_IDENTITY_OR_DUAL_MATURITY")
        for arm in ("A", "B"):
            arm_record = row["outputs"][arm]
            rule(arm_record["pair_key"] == list(key) and arm_record["input_sha256"] == features["sha256"]
                 and arm_record["model_sha256"] == actual["model"]["sha256"]
                 and arm_record["history_manifest_sha256"] == actual["history_manifest"]["sha256"]
                 and arm_record["contract_sha256"] == actual["mapping_contract"]["sha256"]
                 and hash_ok(arm_record["output_sha256"]), "AB_PAIR_OR_ASSET_DRIFT")
    return True
