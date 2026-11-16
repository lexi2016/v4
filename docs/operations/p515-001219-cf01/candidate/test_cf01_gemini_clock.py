"""Targeted synthetic regression tests for C-F01 and the two-clock handoff.

No market data, fitted estimator, predicted probability, or real outcome is used.
Run with: "$PANEL_PYTHON" -B candidate/test_cf01_gemini_clock.py
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from freeze_gate_candidate import (MATERIALS, PERMISSIONS, VERSION, ZERO, append,
                                  digest, global_f_digest, validate)

ROOT = Path(__file__).resolve().parent
ORIGINAL = ROOT.parent.parent / "p515_001219_common_a_route_v1_20261116"
SOURCE_PREPARATION = ORIGINAL / "FREEZE_EXPOSURE_PREPARATION.json"
SOURCE_ENGINE_SHA = json.loads(SOURCE_PREPARATION.read_text())["readiness_binding"]["engine_candidate_sha256"]
GATE = ROOT / "freeze_gate_candidate.py"
SCHEMA = ROOT / "FREEZE_EXPOSURE_SCHEMA_CF01_V2.json"
OUT_PREPARATION = ROOT / "FREEZE_EXPOSURE_PREPARATION_V2.json"
OUT_RESULTS = ROOT / "DETERMINISTIC_TESTS_CF01_GEMINI_CLOCK_V2.json"
TS = lambda day, hh="16:00": f"2026-11-{day}T{hh}:00+08:00"
FILE_SHA = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
CASES = []


def record_prep():
    rec = json.loads(SOURCE_PREPARATION.read_text())
    rec["schema_version"] = VERSION
    rec["global_F"] = rec.pop("F")
    rec["global_F_sha256"] = None
    rec["history_manifest"] = None
    rec["readiness_binding"]["gate_validator_sha256"] = FILE_SHA(GATE)
    rec["readiness_binding"]["schema_sha256"] = FILE_SHA(SCHEMA)
    return rec


def evidence(member, object_id, role, hop, result_id, source_id, outcome, mature_at, acquired_at):
    item = {"history_member_id": member, "result_id": result_id, "result_role": role,
            "result_object_id": object_id, "hop": hop, "source_id": source_id,
            "outcome": outcome, "mature_at": mature_at, "acquired_at": acquired_at}
    payload = {k: item[k] for k in ("history_member_id", "result_id", "result_role",
                                     "result_object_id", "hop", "source_id", "outcome", "mature_at")}
    item["evidence_payload"] = payload
    item["evidence_sha256"] = digest(payload)
    return item


def seal_history(rec, rehash_evidence=True, synchronize_members=True):
    """Recompute synthetic evidence hashes and the exact sealed history roster."""
    rows = rec["history_rows"]
    for row in rows:
        for key in ("result_pb", "result_mother"):
            item = row[key]
            if rehash_evidence:
                item["evidence_payload"] = {k: item[k] for k in ("history_member_id", "result_id",
                    "result_role", "result_object_id", "hop", "source_id", "outcome", "mature_at")}
                item["evidence_sha256"] = digest(item["evidence_payload"])
    manifest = rec["history_manifest"]
    if synchronize_members:
        manifest["member_ids"] = sorted(row["history_id"] for row in rows)
        manifest["member_count"] = len(rows)
    manifest["rows_sha256"] = digest(sorted(rows, key=lambda row: row["history_id"]))
    manifest.pop("sha256", None)
    manifest["sha256"] = digest(manifest)
    ident = rec["actual_freezes"]["history_manifest"]
    ident["artifact_id"] = manifest["manifest_id"]
    ident["sha256"] = manifest["sha256"]
    ident["frozen_at"] = manifest["frozen_at"]


def fixture():
    rec = record_prep()
    rec.update(mode="SYNTHETIC_FIXTURE", global_F=TS("20", "10:00"),
               fit_completed_at=TS("19", "13:59"))
    rec["global_F_sha256"] = global_f_digest(rec["global_F"])
    rec["actual_freezes"] = {
        k: {"artifact_id": "SYN-" + k, "sha256": digest(k), "frozen_at": TS("19", "14:00")}
        for k in MATERIALS
    }
    rec["training_rows"] = [
        {"security":"000001.SZ","pb":f"SYN-TRAIN-PB{i}","mother":f"SYN-TRAIN-M{i}",
         "D":"2026-11-13","source_sha256":digest(i),"source_permission":"SYNTHETIC_ONLY",
         "result_mature_at":TS("16"),"target":"Y_PB_PATH_15D","y":y}
        for i,y in enumerate((0,1))
    ]
    hist = {"security":"001219.SZ","pb":"SYN-H-PB","mother":"SYN-H-M","D":"2026-11-09",
            "history_id":"SYN-H","origin":"ARCHIVE_PRE_F","prefix_sha256":digest("H-PREFIX"),
            "available_at":TS("12"),"ordinal_group":"PB1","pb_age":3,"at_risk_at_k3":True}
    hist["result_pb"] = evidence("SYN-H", hist["pb"], "PB", "PB15", "SYN-H-PB15", "SYN-PB-SOURCE",
                                  "SUCCESS_RESTART", TS("12", "17:00"), TS("13", "09:00"))
    hist["result_mother"] = evidence("SYN-H", hist["mother"], "MOTHER", "MOTHER_FINAL", "SYN-H-MFINAL",
                                      "SYN-MOTHER-SOURCE", "CLOSED", TS("18", "16:00"), TS("19", "15:30"))
    rec["history_rows"] = [hist]
    rec["history_manifest"] = {"manifest_id":"SYN-HISTORY-MANIFEST","seal_status":"SEALED",
        "frozen_at":TS("19"),"member_count":0,"member_ids":[],"rows_sha256":"0"*64,"sha256":"0"*64}
    seal_history(rec)
    row = {"security":"001219.SZ","pb":"SYN-V-PB","mother":"SYN-V-M","D":"2026-11-25",
           "pb_age":3,"ordinal_group":"PB1","exposure":"FIRST_SEEN_AFTER_F","status":"PAIRED_FROZEN",
           "global_F_binding_sha256":rec["global_F_sha256"],"mother_formed_at":TS("23"),
           "D_cutoff":TS("25","15:00"),"generated_at":TS("25","17:20"),
           "output_frozen_at":TS("25","17:25"),"first_evaluation_bar_at":TS("26","09:30"),
           "history_refs":["SYN-H"],
           "input":{"sha256":digest("D-input"),"source_manifest_sha256":digest("source"),
                    "available_at":TS("25","17:00"),"max_feature_time":TS("25","15:00"),
                    "reference_version":"SYN-REF-v1"}}
    row["outputs"] = {}
    for arm in ("A","B"):
        row["outputs"][arm] = {"pair_key":[row[k] for k in ("security","pb","mother","D")],
            "input_sha256":row["input"]["sha256"],"model_sha256":rec["actual_freezes"]["model"]["sha256"],
            "history_manifest_sha256":rec["history_manifest"]["sha256"],
            "contract_sha256":rec["actual_freezes"]["mapping_contract"]["sha256"],
            "output_sha256":digest("synthetic opaque output "+arm)}
    rec["forward_rows"] = [row]
    return rec


def ok(name, condition):
    assert condition, name
    CASES.append({"case":name,"result":"PASS"})


def reject(name, mutate, expected, reseal=False, base=None):
    rec = deepcopy(BASE if base is None else base)
    mutate(rec)
    if reseal:
        seal_history(rec, rehash_evidence=(reseal is True), synchronize_members=(reseal is True))
        for row in rec["forward_rows"]:
            for arm in ("A","B"):
                row["outputs"][arm]["history_manifest_sha256"] = rec["history_manifest"]["sha256"]
    try:
        validate(rec)
    except ValueError as exc:
        assert str(exc) == expected, (name, str(exc), expected)
        CASES.append({"case":name,"result":"PASS","expected_rejection":expected})
    else:
        raise AssertionError(f"{name}: expected {expected}")


BASE = fixture()
PREP = record_prep()
ok("preparation_has_null_global_F_and_zero_permissions", validate(PREP)
   and PREP["global_F"] is None and PREP["global_F_sha256"] is None
   and PREP["history_manifest"] is None and PREP["permissions"] == PERMISSIONS
   and PREP["new_counts"] == ZERO)
ok("engine_and_gate_validator_hashes_are_distinct_and_bound",
   PREP["readiness_binding"]["engine_candidate_sha256"] == SOURCE_ENGINE_SHA
   and PREP["readiness_binding"]["gate_validator_sha256"] == FILE_SHA(GATE)
   and PREP["readiness_binding"]["schema_sha256"] == FILE_SHA(SCHEMA))
ok("synthetic_two_clock_fixture_is_valid", validate(BASE))
hist0 = BASE["history_rows"][0]
ok("result_acquisition_is_distinct_from_prefix_availability",
   hist0["available_at"] != hist0["result_pb"]["acquired_at"]
   and hist0["available_at"] != hist0["result_mother"]["acquired_at"])
ok("Gemini_clock_interface_fields_are_explicit",
   "global_F" in BASE and "global_F_binding_sha256" in BASE["forward_rows"][0]
   and all(k in BASE["forward_rows"][0] for k in
           ("generated_at","output_frozen_at","first_evaluation_bar_at","D_cutoff"))
   and "generated_at" not in BASE["forward_rows"][0]["input"]
   and "frozen_at" not in BASE["forward_rows"][0]["outputs"])


def change_result(rec, name, **fields):
    item = rec["history_rows"][0][name]
    item.update(fields)


reject("CF01_mother_matures_11_23_after_seal_before_D_11_25",
       lambda r: change_result(r, "result_mother", mature_at=TS("23"), acquired_at=TS("24")),
       "HISTORY_RESULT_AFTER_SEAL", reseal=True)
reject("late_PB_maturity_after_seal_before_D",
       lambda r: change_result(r, "result_pb", mature_at=TS("23"), acquired_at=TS("24")),
       "HISTORY_RESULT_AFTER_SEAL", reseal=True)
reject("PB_result_evidence_acquired_after_seal",
       lambda r: change_result(r, "result_pb", acquired_at=TS("20","11:00")),
       "HISTORY_RESULT_AFTER_SEAL", reseal=True)
reject("mother_result_evidence_acquired_after_seal",
       lambda r: change_result(r, "result_mother", acquired_at=TS("21")),
       "HISTORY_RESULT_AFTER_SEAL", reseal=True)
reject("manifest_member_id_set_mismatch_even_when_manifest_rehashed",
       lambda r: r["history_manifest"].update(member_ids=["SYN-OTHER"]),
       "HISTORY_MANIFEST_MEMBER_SET", reseal="manifest_only")
reject("manifest_member_count_mismatch",
       lambda r: r["history_manifest"].update(member_count=2),
       "HISTORY_MANIFEST_MEMBER_SET", reseal="manifest_only")
reject("result_member_identity_mismatch_even_when_manifest_rehashed",
       lambda r: r["history_rows"][0]["result_pb"].update(history_member_id="SYN-OTHER"),
       "HISTORY_EVIDENCE_MEMBER_IDENTITY", reseal="manifest_only")
reject("PB_result_object_identity_mismatch_even_when_manifest_rehashed",
       lambda r: r["history_rows"][0]["result_pb"].update(result_object_id="SYN-WRONG-PB"),
       "HISTORY_RESULT_OBJECT_IDENTITY", reseal="manifest_only")
reject("result_payload_hash_mismatch_even_when_roster_resealed",
       lambda r: r["history_rows"][0]["result_mother"]["evidence_payload"].update(outcome="OTHER"),
       "HISTORY_EVIDENCE_PAYLOAD_HASH", reseal="roster_only")

# A roster mutation without refreshing the manifest must fail closed.
def mismatched_row(r):
    r["history_rows"][0]["result_mother"]["acquired_at"] = TS("19","15:59")
reject("sealed_history_rows_hash_mismatch", mismatched_row, "HISTORY_MANIFEST_ROWS_HASH")

def unseal(r):
    r["history_manifest"]["seal_status"] = "DRAFT"
reject("unsealed_history_manifest_rejected", unseal, "HISTORY_MANIFEST_UNSEALED", reseal="manifest_only")

def freeze_hash_mismatch(r):
    r["actual_freezes"]["history_manifest"]["sha256"] = digest("other manifest")
reject("history_manifest_digest_not_bound_to_freeze_identity", freeze_hash_mismatch,
       "HISTORY_MANIFEST_FREEZE_BINDING")

def result_acquisition_after_prefix(r):
    r["history_rows"][0]["available_at"] = TS("12")
    r["history_rows"][0]["result_mother"]["acquired_at"] = TS("24")
reject("prefix_availability_cannot_substitute_for_result_acquisition", result_acquisition_after_prefix,
       "HISTORY_MANIFEST_ROWS_HASH")
reject("legacy_F_alias_is_not_accepted", lambda r: r.update(F=r["global_F"]),
       "LEGACY_F_ALIAS_FORBIDDEN")
reject("row_level_rolling_global_F_is_not_accepted",
       lambda r: r["forward_rows"][0].update(global_F=TS("24")), "ROW_LEVEL_GLOBAL_F_FORBIDDEN")

def rolling_global_f(r):
    r["global_F"] = TS("24")
    r["global_F_sha256"] = global_f_digest(r["global_F"])
    r["forward_rows"][0]["global_F_binding_sha256"] = r["global_F_sha256"]
reject("per_D_rolling_global_F_cannot_reclassify_preexisting_mother",
       rolling_global_f, "EXPOSED_OR_PRE_F_EVENT")
reject("global_F_digest_mismatch", lambda r: r.update(global_F_sha256=digest("wrong")),
       "GLOBAL_F_BINDING_MISMATCH")
reject("row_must_bind_exact_global_F",
       lambda r: r["forward_rows"][0].update(global_F_binding_sha256=digest("other")),
       "ROW_GLOBAL_F_BINDING_MISMATCH")
reject("source_acquisition_after_generation",
       lambda r: r["forward_rows"][0]["input"].update(available_at=TS("25","18:30")),
       "GEMINI_PER_D_CLOCK_ORDER")
reject("generation_before_D_close", lambda r: r["forward_rows"][0].update(generated_at=TS("25","14:59")),
       "GEMINI_PER_D_CLOCK_ORDER")
reject("output_frozen_before_generation",
       lambda r: r["forward_rows"][0].update(output_frozen_at=TS("25","17:19")),
       "GEMINI_PER_D_CLOCK_ORDER")
reject("output_at_first_evaluation_bar_rejected",
       lambda r: r["forward_rows"][0].update(output_frozen_at=TS("26","09:30")),
       "GEMINI_PER_D_CLOCK_ORDER")
reject("future_feature_after_D_cutoff_rejected",
       lambda r: r["forward_rows"][0]["input"].update(max_feature_time=TS("25","15:01")),
       "GEMINI_PER_D_CLOCK_ORDER")
reject("mother_formation_after_D_cutoff_rejected",
       lambda r: r["forward_rows"][0].update(mother_formed_at=TS("25","15:01")),
       "INVALID_EVENT_OR_EVALUATION_CLOCK")
reject("preparation_does_not_allow_global_F",
       lambda r: r.update(global_F=TS("20")), "PREPARATION_MUST_REMAIN_EMPTY", base=PREP)

# Confirm the schema advertises the same split and forbids the old conflated field.
SCHEMA_DOC = json.loads(SCHEMA.read_text())
ok("schema_exposes_two_clock_contract_and_sealed_history",
   "F" not in SCHEMA_DOC["properties"] and "global_F" in SCHEMA_DOC["properties"]
   and SCHEMA_DOC["properties"]["schema_version"]["const"] == VERSION
   and "history_manifest" in SCHEMA_DOC["properties"]
   and "global_F_binding_sha256" in SCHEMA_DOC["$defs"]["event"]["properties"]
   and "generated_at" in SCHEMA_DOC["$defs"]["event"]["properties"]
   and "output_frozen_at" in SCHEMA_DOC["$defs"]["event"]["properties"]
   and "result_evidence" in SCHEMA_DOC["$defs"]
   and "gate_validator_sha256" in SCHEMA_DOC["properties"]["readiness_binding"]["required"])

OUT_PREPARATION.write_text(json.dumps(PREP, ensure_ascii=False, indent=2) + "\n")
summary = {
    "status":"PASS", "version":VERSION, "passed":len(CASES), "failed":0,
    "fixture":"synthetic IDs and opaque hashes only; no market rows, fitted model, probabilities, or predictions",
    "gemini_live_integration":"NOT_RUN by this candidate suite; parent is running the Gemini R2.4 cross-runtime subset separately",
    "new_fit_count":0,"new_preprocessor_fit_count":0,"new_model_predict_count":0,
    "new_model_weight_count":0,"new_formal_training_labels":0,
    "test_cases":CASES,
}
OUT_RESULTS.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
print(f"PASS {len(CASES)} targeted C-F01/Gemini-clock checks; Gemini live integration NOT_RUN")
