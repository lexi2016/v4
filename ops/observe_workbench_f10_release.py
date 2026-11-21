"""Read-only post-cutover checks and natural scheduler receipt correlation."""
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
from urllib.request import urlopen
from zoneinfo import ZoneInfo

OUT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")


def sha(raw):
    return sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def once(path, value):
    if path.exists():
        return
    with path.open("x") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")


EVIDENCE_SCHEMA = "V4_WORKBENCH_NATURAL_F10_OBSERVATION_V1"
DAILY_WORKLOAD_ID = "research_panel_daily_a"
SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")


def _canonical(raw):
    return json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _canonical_sha(raw):
    return sha(_canonical(raw))


def _valid_sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _date8(value):
    text = str(value or "").replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        return None
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return text


def _iso_date(value):
    compact = _date8(value)
    return datetime.strptime(compact, "%Y%m%d").date().isoformat() if compact else None


def _safe(value, *, research_only=False):
    return (isinstance(value, dict)
            and (not research_only or value.get("RESEARCH_ONLY") is True)
            and all(value.get(key) is False for key in SAFETY_FLAGS))


def _reference_shape(reference, *, mutable=False):
    if not isinstance(reference, dict):
        return None
    text, digest = reference.get("path"), reference.get("sha256")
    if not isinstance(text, str) or not Path(text).is_absolute() or not _valid_sha(digest):
        return None
    path = Path(text)
    if mutable:
        if path.name != "latest.json":
            return None
    elif path.name != digest + ".json":
        return None
    return path


def _checked_reference(reference, *, research_only=False):
    path = _reference_shape(reference)
    if path is None or path.is_symlink() or path.resolve(strict=True) != path:
        raise ValueError("NATURAL_WORKBENCH_REFERENCE_PATH_INVALID")
    raw = path.read_bytes()
    if sha(raw) != reference.get("sha256"):
        raise ValueError("NATURAL_WORKBENCH_REFERENCE_SHA_MISMATCH")
    value = json.loads(raw)
    if not isinstance(value, dict) or not _safe(value, research_only=research_only):
        raise ValueError("NATURAL_WORKBENCH_REFERENCE_CONTRACT_INVALID")
    return value


def _workload_rows(dispatch):
    rows = dispatch.get("workload_results")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and row.get("workload_id") == DAILY_WORKLOAD_ID]


def _workload_identity(dispatch, workload, work_date):
    """Validate same-dispatch daily and formula-group owner identities."""
    if not isinstance(workload, dict) or workload.get("status") not in {"SUCCEEDED", "ALREADY_EXISTS"}:
        raise ValueError("NATURAL_DAILY_WORKLOAD_NOT_SUCCESSFUL")
    if workload.get("target_date") is not None and _date8(workload.get("target_date")) != work_date:
        raise ValueError("NATURAL_DAILY_WORKLOAD_TARGET_CONFLICT")
    if not _safe(workload):
        raise ValueError("NATURAL_DAILY_WORKLOAD_SAFETY_CONFLICT")

    derivatives = workload.get("daily_derivatives")
    formula = workload.get("formula_groups")
    if not isinstance(derivatives, dict) or not isinstance(formula, dict):
        raise ValueError("NATURAL_DAILY_AUTHORITY_PAYLOAD_MISSING")
    if (derivatives.get("schema") != "V4_A_DAILY_DERIVATIVES_V1"
            or derivatives.get("status") != "COMPLETE_DESCRIPTIVE_NONPIT"
            or _date8(derivatives.get("data_date")) != work_date
            or not _valid_sha(derivatives.get("source_generation"))
            or not _safe(derivatives, research_only=True)):
        raise ValueError("NATURAL_DAILY_DERIVATIVES_IDENTITY_CONFLICT")
    provenance = derivatives.get("completed_source_provenance")
    if (not isinstance(provenance, dict)
            or provenance.get("status") not in {
                "EXACT_COMPLETED_SOURCE", "REVALIDATED_ORIGINAL_COMPLETED_TRANSPORT_PROOF"}
            or not isinstance(provenance.get("numeric_manifest"), dict)):
        raise ValueError("NATURAL_DAILY_DERIVATIVE_PROVENANCE_MISSING")

    source_date = _iso_date(formula.get("source_date"))
    observation_date = _iso_date(formula.get("observation_date"))
    generation = formula.get("source_generation")
    numeric_manifest = formula.get("numeric_manifest")
    formula_ref = formula.get("artifact")
    formula_receipt_ref = formula.get("receipt")
    if (formula.get("status") not in {"COMMITTED", "ALREADY_COMMITTED"}
            or _date8(formula.get("source_date")) != work_date
            or source_date is None or _date8(source_date) != work_date or observation_date is None
            or not _valid_sha(generation) or generation != derivatives.get("source_generation")
            or not isinstance(numeric_manifest, dict) or not _valid_sha(numeric_manifest.get("sha256"))
            or provenance.get("numeric_manifest") != numeric_manifest):
        raise ValueError("NATURAL_FORMULA_GROUP_RUN_IDENTITY_CONFLICT")
    formula_artifact = _checked_reference(formula_ref, research_only=True)
    formula_receipt = _checked_reference(formula_receipt_ref, research_only=True)
    if (formula_artifact.get("schema") != "V4_WORKBENCH_FORMULA_GROUP_OVERRIDE_V1"
            or _iso_date(formula_artifact.get("source_date")) != source_date
            or _iso_date(formula_artifact.get("observation_date")) != observation_date
            or formula_artifact.get("generation") != generation
            or not _valid_sha(formula_artifact.get("input_sha256"))
            or formula_artifact.get("numeric_manifest") != numeric_manifest
            or formula_receipt.get("status") != "COMMITTED"
            or formula_receipt.get("artifact") != formula_ref
            or _iso_date(formula_receipt.get("source_date")) != source_date
            or formula_receipt.get("generation") != generation
            or formula_receipt.get("numeric_manifest") != numeric_manifest):
        raise ValueError("NATURAL_FORMULA_GROUP_RECEIPT_CONFLICT")
    rows = formula_artifact.get("rows")
    if not isinstance(rows, list):
        raise ValueError("NATURAL_FORMULA_GROUP_ROSTER_INVALID")
    symbols = [row.get("symbol") for row in rows if isinstance(row, dict)]
    if (len(symbols) != len(rows) or len(symbols) != len(set(symbols))
            or any(not isinstance(symbol, str) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol)
                   for symbol in symbols)):
        raise ValueError("NATURAL_FORMULA_GROUP_ROSTER_INVALID")
    roster_sha = _canonical_sha(sorted(symbols))
    input_sha = formula_artifact["input_sha256"]
    supplement = formula.get("workbench_supplements")
    if not isinstance(supplement, dict):
        raise ValueError("NATURAL_FORMULA_SUPPLEMENT_AUTHORITY_MISSING")
    identity = dict(source_date=source_date, observation_date=observation_date,
        generation=generation, input_sha256=input_sha,
        numeric_manifest=numeric_manifest,
        selector_sha256=formula_artifact.get("selector_sha256"),
        numeric_manifest_sha256=numeric_manifest["sha256"],
        formula_group_sha256=formula_ref["sha256"], roster_symbols_sha256=roster_sha,
        roster_count=len(symbols))
    for key, expected in (("source_date", source_date), ("observation_date", observation_date),
            ("generation", generation), ("input_sha256", input_sha),
            ("numeric_manifest", numeric_manifest), ("formula_group_sha256", formula_ref["sha256"]),
            ("roster_symbols_sha256", roster_sha), ("roster_count", len(symbols))):
        if supplement.get(key) != expected:
            raise ValueError("NATURAL_FORMULA_SUPPLEMENT_SCOPE_CONFLICT:" + key)
    pointer_ref = supplement.get("pointer")
    if _reference_shape(pointer_ref, mutable=True) is None:
        raise ValueError("NATURAL_FORMULA_SUPPLEMENT_POINTER_MISSING")
    supplement_artifact_ref = supplement.get("artifact")
    supplement_receipt_ref = supplement.get("receipt")
    supplement_artifact = _checked_reference(supplement_artifact_ref, research_only=True)
    supplement_receipt = _checked_reference(supplement_receipt_ref, research_only=True)
    expected_supplement = dict(source_date=source_date, observation_date=observation_date,
        generation=generation, input_sha256=input_sha, numeric_manifest=numeric_manifest,
        selector_sha256=formula_artifact.get("selector_sha256"),
        formula_group_sha256=formula_ref["sha256"], roster_symbols_sha256=roster_sha,
        roster_count=len(symbols))
    if (supplement.get("status") not in {"PARTIAL", "COMPLETE", "ALREADY_COMMITTED"}
            or supplement_artifact.get("schema") != "V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1"
            or supplement_artifact.get("status") not in {"PARTIAL", "COMPLETE"}
            or any(supplement_artifact.get(key) != value for key, value in expected_supplement.items())
            or supplement_receipt.get("schema") != "V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1"
            or supplement_receipt.get("status") != "COMMITTED"
            or supplement_receipt.get("artifact") != supplement_artifact_ref
            or any(supplement_receipt.get(key) != value for key, value in expected_supplement.items())):
        raise ValueError("NATURAL_FORMULA_SUPPLEMENT_RECEIPT_CONFLICT")
    f10_binding = supplement.get("f10")
    if not isinstance(f10_binding, dict):
        # ALREADY_COMMITTED omits the direct result; recover it from the exact
        # immutable supplement artifact bound by the receipt above.
        f10_binding = supplement_artifact.get("f10")
    f10_ref = f10_binding.get("receipt") if isinstance(f10_binding, dict) else None
    f10_sha = None
    if isinstance(f10_ref, dict):
        f10_receipt = _checked_reference(f10_ref)
        if (f10_receipt.get("schema") != "v4.a_share.f10_daily_receipt.v1"
                or f10_receipt.get("status") not in {"COMPLETE", "PARTIAL"}
                or f10_receipt.get("data_date") != source_date.replace("-", "")
                or f10_receipt.get("source_generation") != generation
                or f10_receipt.get("input_sha256") != input_sha
                or f10_receipt.get("selector_sha256") != formula_artifact.get("selector_sha256")
                or f10_receipt.get("numeric_manifest") != numeric_manifest
                or f10_receipt.get("priority_scope", {}).get("symbols") != sorted(symbols)
                or f10_receipt.get("historical_PIT") is not False
                or not _safe(f10_receipt, research_only=True)):
            raise ValueError("NATURAL_FORMULA_SUPPLEMENT_F10_RECEIPT_CONFLICT")
        f10_sha = f10_ref["sha256"]
    elif symbols and f10_binding and f10_binding.get("status") != "CANNOT_CONFIRM":
        raise ValueError("NATURAL_FORMULA_SUPPLEMENT_F10_RECEIPT_MISSING")

    identity.update(owner_formula_receipt_sha256=formula_receipt_ref["sha256"],
        supplement_pointer_sha256=pointer_ref["sha256"],
        supplement_receipt_sha256=supplement_receipt_ref["sha256"],
        supplement_artifact_sha256=supplement_artifact_ref["sha256"],
        owner_f10_receipt_sha256=f10_sha)
    return dict(source_identity=identity, symbols=sorted(symbols),
        expected_f10_receipt_sha256=f10_sha,
        daily_derivatives=_daily_derivatives_summary(derivatives),
        formula_groups=_formula_groups_summary(formula))


def _daily_derivatives_summary(value):
    def project(item):
        if not isinstance(item, dict):
            return None
        if isinstance(item.get("path"), str) and _valid_sha(item.get("sha256")):
            return {"path": item["path"], "sha256": item["sha256"]}
        scalar_keys = {"status", "schema", "data_date", "source_date", "observation_date",
            "target_date", "source_generation", "mode", "operation"}
        object_keys = {"artifact", "receipt", "pointer", "index", "event", "computation",
            "attempt", "publication", "numeric_manifest", "completed_source_provenance",
            "before", "after"}
        result = {key:item[key] for key in scalar_keys if key in item
            and (isinstance(item[key], (str, int, bool)) or item[key] is None)}
        for key in object_keys:
            if isinstance(item.get(key), dict):
                result[key] = project(item[key])
        return result

    provenance = value.get("completed_source_provenance") or {}
    result = dict(schema=value.get("schema"), status=value.get("status"),
        data_date=value.get("data_date"), source_generation=value.get("source_generation"),
        completed_source_provenance={"status": provenance.get("status"),
            "numeric_manifest": project(provenance.get("numeric_manifest"))},
        top200=project(value.get("top200")), computation=project(value.get("computation")),
        attempt=project(value.get("attempt")), **{key:value.get(key) for key in SAFETY_FLAGS})
    return result


def _formula_groups_summary(value):
    supplements = value.get("workbench_supplements") or {}
    supplement_summary = {key:supplements.get(key) for key in
        ("status", "source_date", "observation_date", "generation", "input_sha256",
         "numeric_manifest", "formula_group_sha256", "roster_symbols_sha256", "roster_count",
         "pointer", "receipt", "artifact", "f10", "counts")}
    return dict(status=value.get("status"), source_date=value.get("source_date"),
        observation_date=value.get("observation_date"), source_generation=value.get("source_generation"),
        numeric_manifest=value.get("numeric_manifest"), artifact=value.get("artifact"),
        receipt=value.get("receipt"), workbench_supplements=supplement_summary,
        RESEARCH_ONLY=value.get("RESEARCH_ONLY"),
        **{key:value.get(key) for key in SAFETY_FLAGS})


def _verified_current_f10(view, authority, expected_f10_receipt_sha256):
    """Verify latest -> immutable supplement receipt/artifact -> F10 receipt."""
    identity = authority["source_identity"]
    groups = authority["formula_groups"].get("workbench_supplements") or {}
    pointer_ref = groups.get("pointer")
    pointer_path = _reference_shape(pointer_ref, mutable=True)
    if (pointer_path is None or pointer_path.is_symlink()
            or pointer_path.resolve(strict=True) != pointer_path):
        raise ValueError("NATURAL_CURRENT_SUPPLEMENT_POINTER_INVALID")
    raw = pointer_path.read_bytes()
    pointer = json.loads(raw)
    expected = dict(source_date=identity["source_date"],
        observation_date=identity["observation_date"], generation=identity["generation"],
        input_sha256=identity["input_sha256"], numeric_manifest=identity["numeric_manifest"],
        selector_sha256=identity["selector_sha256"],
        formula_group_sha256=identity["formula_group_sha256"],
        roster_symbols_sha256=identity["roster_symbols_sha256"],
        roster_count=identity["roster_count"])
    if (pointer.get("schema") != "V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_COMMIT_V1"
            or pointer.get("module") != "formula_group_supplement"
            or any(pointer.get(key) != value for key, value in expected.items())
            or not _safe(pointer, research_only=True)):
        raise ValueError("NATURAL_CURRENT_SUPPLEMENT_POINTER_CONFLICT")
    artifact_ref, receipt_ref = pointer.get("artifact"), pointer.get("receipt")
    artifact_path = _reference_shape(artifact_ref)
    receipt_path = _reference_shape(receipt_ref)
    if (artifact_path is None or receipt_path is None
            or artifact_path.parent != pointer_path.parent / "artifacts"
            or receipt_path.parent != pointer_path.parent / "receipts"):
        raise ValueError("NATURAL_CURRENT_SUPPLEMENT_REFERENCES_OUTSIDE_OWNER_ROOT")
    artifact = _checked_reference(artifact_ref, research_only=True)
    supplement_receipt = _checked_reference(receipt_ref, research_only=True)
    if (artifact.get("schema") != "V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_V1"
            or artifact.get("status") not in {"PARTIAL", "COMPLETE"}
            or any(artifact.get(key) != value for key, value in expected.items())
            or supplement_receipt.get("schema") != "V4_WORKBENCH_FORMULA_GROUP_SUPPLEMENT_RECEIPT_V1"
            or supplement_receipt.get("status") != "COMMITTED"
            or supplement_receipt.get("artifact") != artifact_ref
            or any(supplement_receipt.get(key) != value for key, value in expected.items())
            or not _safe(supplement_receipt, research_only=True)):
        raise ValueError("NATURAL_CURRENT_SUPPLEMENT_RECEIPT_CONFLICT")
    f10 = artifact.get("f10")
    f10_ref = f10.get("receipt") if isinstance(f10, dict) else None
    f10_path = _reference_shape(f10_ref)
    if (f10_path is None or f10_path.parent.name != "receipts"
            or f10_path.parent.parent.name != identity["generation"][:16]
            or f10_path.parent.parent.parent.name != identity["source_date"].replace("-", "")
            or f10_path.parent.parent.parent.parent.name != "f10"):
        raise ValueError("NATURAL_CURRENT_F10_REFERENCE_OUTSIDE_OWNER_ROOT")
    f10_receipt = _checked_reference(f10_ref, research_only=True)
    expected_symbols = sorted(authority["symbols"])
    if (f10_ref.get("sha256") != expected_f10_receipt_sha256
            or f10_receipt.get("schema") != "v4.a_share.f10_daily_receipt.v1"
            or f10_receipt.get("status") not in {"PARTIAL", "COMPLETE"}
            or f10_receipt.get("data_date") != identity["source_date"].replace("-", "")
            or f10_receipt.get("source_generation") != identity["generation"]
            or f10_receipt.get("input_sha256") != identity["input_sha256"]
            or f10_receipt.get("selector_sha256") != identity["selector_sha256"]
            or f10_receipt.get("numeric_manifest") != identity["numeric_manifest"]
            or f10_receipt.get("priority_scope", {}).get("symbols") != expected_symbols
            or f10_receipt.get("historical_PIT") is not False
            or not _safe(f10_receipt, research_only=True)):
        raise ValueError("NATURAL_CURRENT_F10_RECEIPT_CONFLICT")
    return dict(pointer_sha256=sha(raw), supplement_artifact_sha256=artifact_ref["sha256"],
        supplement_receipt_sha256=receipt_ref["sha256"],
        f10_receipt_sha256=f10_ref["sha256"], supplement_status=artifact.get("status"))


def _other_dispatch_claims_f10(ledger, date8, scheduler, current_run_id,
        current_dispatch_sha256, source_identity, f10_receipt_sha256):
    """Find a distinct same-day dispatch whose owner payload names this F10 SHA."""
    for slot in ("1610", "1640"):
        directory = Path(ledger) / "receipts" / "live" / date8 / slot
        for path in sorted(directory.glob("*.dispatch-receipt.json")):
            try:
                raw = path.read_bytes()
                data = json.loads(raw)
                run_id = data.get("run_id")
                dispatch_sha256 = sha(raw)
                if (run_id == current_run_id and dispatch_sha256 == current_dispatch_sha256):
                    continue
                if (not re.fullmatch(r"[a-f0-9]+", str(run_id or ""))
                        or path.name != run_id + ".dispatch-receipt.json"
                        or data.get("release_id") != scheduler.get("candidate_release_id")
                        or _date8(data.get("business_date")) != date8
                        or data.get("mode") != "LIVE" or data.get("slot") != slot
                        or DAILY_WORKLOAD_ID not in data.get("invoked_workload_ids", [])
                        or DAILY_WORKLOAD_ID not in data.get("succeeded_workload_ids", [])
                        or data.get("ledger_sha256") != _canonical_sha(
                            {key:value for key,value in data.items() if key != "ledger_sha256"})
                        or not _safe(data)):
                    continue
                rows = _workload_rows(data)
                if len(rows) != 1:
                    continue
                authority = _workload_identity(data, rows[0], date8)
                if (_stable_source_identity(authority["source_identity"])
                        == _stable_source_identity(source_identity)
                        and authority["expected_f10_receipt_sha256"] == f10_receipt_sha256):
                    return dict(run_id=run_id, dispatch_sha256=dispatch_sha256,
                        workload_result_sha256=_canonical_sha(rows[0]))
            except (OSError, KeyError, TypeError, ValueError, AssertionError):
                continue
    return None


def _stable_source_identity(value):
    keys = ("source_date", "observation_date", "generation", "input_sha256",
        "numeric_manifest_sha256", "selector_sha256", "formula_group_sha256",
        "roster_symbols_sha256", "roster_count", "owner_formula_receipt_sha256")
    return {key:value.get(key) for key in keys} if isinstance(value, dict) else None


def _match_readback(view, authority):
    day = view.get("day_response") if isinstance(view, dict) else None
    versions = view.get("versions") if isinstance(view, dict) else None
    coverage = view.get("formula_coverage") if isinstance(view, dict) else None
    roster_ref = view.get("formula_roster") if isinstance(view, dict) else None
    identity = authority["source_identity"]
    if not all(isinstance(value, dict) for value in (day, versions, coverage, roster_ref)):
        raise ValueError("NATURAL_API_READBACK_INCOMPLETE")
    numeric = day.get("numeric_manifest")
    if (not isinstance(numeric, dict)
            or day.get("source_date") != identity["source_date"]
            or day.get("observation_date") != identity["observation_date"]
            or day.get("generation") != identity["generation"]
            or day.get("input_sha256") != identity["input_sha256"]
            or numeric.get("sha256") != identity["numeric_manifest_sha256"]
            or roster_ref.get("sha256") != identity["formula_group_sha256"]
            or coverage.get("formula_group_sha256") != identity["formula_group_sha256"]
            or coverage.get("roster_symbols_sha256") != identity["roster_symbols_sha256"]
            or coverage.get("roster_count") != identity["roster_count"]
            or coverage.get("source_date") != identity["source_date"]
            or coverage.get("observation_date") != identity["observation_date"]
            or coverage.get("generation") != identity["generation"]
            or coverage.get("input_sha256") != identity["input_sha256"]
            or coverage.get("numeric_manifest_sha256") != identity["numeric_manifest_sha256"]):
        raise ValueError("NATURAL_API_TO_WORKLOAD_SOURCE_IDENTITY_MISMATCH")
    if (versions.get("source_date") != day.get("source_date")
            or versions.get("observation_date") != day.get("observation_date")
            or versions.get("generation") != day.get("generation")
            or versions.get("input_sha256") != day.get("input_sha256")
            or versions.get("numeric_manifest") != numeric
            or not _valid_sha(versions.get("event_id"))
            or not isinstance(versions.get("modules"), dict)
            or not _valid_sha(versions["modules"].get("list"))):
        raise ValueError("NATURAL_VERSIONS_EVENT_IDENTITY_INVALID")
    if not _safe(coverage, research_only=True):
        raise ValueError("NATURAL_API_COVERAGE_SAFETY_CONFLICT")
    status = coverage.get("status")
    if status not in {"COMPLETE", "PARTIAL", "CANNOT_CONFIRM"}:
        raise ValueError("NATURAL_API_COVERAGE_STATUS_INVALID")
    counts = [coverage.get(key) for key in ("observed", "failed", "remaining")]
    if any(type(value) is not int or value < 0 for value in counts) or sum(counts) != identity["roster_count"]:
        raise ValueError("NATURAL_API_COVERAGE_PARTITION_INVALID")
    if status == "COMPLETE" and (counts != [identity["roster_count"], 0, 0]
            or not _valid_sha(coverage.get("receipt_sha256"))):
        raise ValueError("NATURAL_API_COMPLETE_COVERAGE_INVALID")
    if status == "PARTIAL" and counts == [identity["roster_count"], 0, 0]:
        raise ValueError("NATURAL_API_PARTIAL_COVERAGE_CONFLICT")
    current_receipt = coverage.get("receipt_sha256")
    expected_receipt = authority.get("expected_f10_receipt_sha256")
    if current_receipt is not None and not _valid_sha(current_receipt):
        raise ValueError("NATURAL_API_F10_RECEIPT_SHA_INVALID")
    if status in {"COMPLETE", "PARTIAL"} and (current_receipt is None or expected_receipt is None):
        raise ValueError("NATURAL_API_F10_RECEIPT_BINDING_MISSING")
    if status in {"COMPLETE", "PARTIAL"}:
        current_owner = _verified_current_f10(view, authority, current_receipt)
    else:
        current_owner = None
    if status == "PARTIAL" and current_receipt != expected_receipt:
        raise ValueError("NATURAL_PARTIAL_F10_RECEIPT_NOT_DISPATCH_BOUND")
    receipt_relation = ("MATCHED_DISPATCH_SUPPLEMENT_RECEIPT" if current_receipt == expected_receipt
        else "ADVANCED_WITHIN_EXACT_RUN_SOURCE_IDENTITY")
    if receipt_relation != "MATCHED_DISPATCH_SUPPLEMENT_RECEIPT" and status != "COMPLETE":
        raise ValueError("NATURAL_F10_RECEIPT_ADVANCE_REQUIRES_COMPLETE_COVERAGE")
    return dict(versions_event_id=versions["event_id"],
        f10_receipt_sha256=current_receipt, receipt_relation=receipt_relation,
        current_owner=current_owner)


def _evidence_identity(run_id, dispatch_sha256, work_date, workload_result_sha256,
        source_identity=None, versions_event_id=None, f10_receipt_sha256=None, reason=None):
    return dict(run_id=run_id, dispatch_sha256=dispatch_sha256, work_date=work_date,
        workload_result_sha256=workload_result_sha256,
        source_identity=source_identity,
        versions_event_id=versions_event_id,
        f10_receipt_sha256=f10_receipt_sha256,
        reason=reason)


def _append_json_once(path, value):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return path.read_bytes() == raw
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        raise
    return True


def _business_record_valid(record):
    if (not isinstance(record, dict) or record.get("schema") != EVIDENCE_SCHEMA
            or record.get("evidence_kind") != "BUSINESS_READBACK"
            or record.get("business_status") != "SOURCE_BOUND_READBACK_PRESENT"
            or not isinstance(record.get("work_date"), str)
            or not _date8(record.get("work_date"))
            or not re.fullmatch(r"[a-f0-9]+", str(record.get("run_id") or ""))
            or not _valid_sha(record.get("dispatch_sha256"))
            or not _valid_sha(record.get("evidence_id"))):
        return False
    readback = record.get("readback")
    identity = record.get("source_identity")
    if not isinstance(readback, dict) or not isinstance(identity, dict):
        return False
    coverage, versions, roster, day = (readback.get("formula_coverage"), readback.get("versions"),
        readback.get("formula_roster"), readback.get("day"))
    evidence_identity = record.get("evidence_identity")
    if (not isinstance(coverage, dict) or not isinstance(versions, dict) or not isinstance(roster, dict)
            or not isinstance(day, dict) or not isinstance(evidence_identity, dict)
            or coverage.get("status") != "COMPLETE"
            or coverage.get("observed") != identity.get("roster_count")
            or coverage.get("failed") != 0 or coverage.get("remaining") != 0
            or coverage.get("source_date") != identity.get("source_date")
            or _date8(identity.get("source_date")) != _date8(record.get("work_date"))
            or coverage.get("observation_date") != identity.get("observation_date")
            or coverage.get("generation") != identity.get("generation")
            or coverage.get("input_sha256") != identity.get("input_sha256")
            or coverage.get("numeric_manifest_sha256") != identity.get("numeric_manifest_sha256")
            or coverage.get("receipt_sha256") != record.get("f10_receipt_sha256")
            or versions.get("event_id") != record.get("versions_event_id")
            or versions.get("source_date") != identity.get("source_date")
            or versions.get("observation_date") != identity.get("observation_date")
            or versions.get("generation") != identity.get("generation")
            or versions.get("input_sha256") != identity.get("input_sha256")
            or not isinstance(versions.get("modules"), dict)
            or not _valid_sha(versions["modules"].get("list"))
            or day.get("source_date") != identity.get("source_date")
            or day.get("observation_date") != identity.get("observation_date")
            or day.get("generation") != identity.get("generation")
            or day.get("input_sha256") != identity.get("input_sha256")
            or roster.get("sha256") != identity.get("formula_group_sha256")
            or coverage.get("formula_group_sha256") != identity.get("formula_group_sha256")
            or coverage.get("roster_symbols_sha256") != identity.get("roster_symbols_sha256")
            or coverage.get("roster_count") != identity.get("roster_count")
            or not _valid_sha(record.get("versions_event_id"))
            or not _valid_sha(record.get("f10_receipt_sha256"))):
        return False
    return (evidence_identity.get("run_id") == record.get("run_id")
        and evidence_identity.get("dispatch_sha256") == record.get("dispatch_sha256")
        and evidence_identity.get("work_date") == record.get("work_date")
        and evidence_identity.get("source_identity") == identity
        and evidence_identity.get("versions_event_id") == record.get("versions_event_id")
        and evidence_identity.get("f10_receipt_sha256") == record.get("f10_receipt_sha256")
        and _canonical_sha(evidence_identity) == record.get("evidence_id"))


def _valid_business_days():
    days = set()
    for path in OUT.glob("NATURAL_*_BUSINESS_READBACK.json"):
        try:
            record = read(path)
        except (OSError, ValueError, TypeError):
            continue
        if _business_record_valid(record):
            days.add(_date8(record["work_date"]))
    return days


def http(path):
    with urlopen("http://127.0.0.1:8873" + path, timeout=12) as response:
        return json.load(response)


def role_status(kind, suffix, expected):
    label = f"com.lexi.v4.{suffix}"
    launchagent = Path.home() / f"Library/LaunchAgents/{label}.plist"
    raw = launchagent.read_bytes()
    cfg = plistlib.loads(raw)
    env = cfg["EnvironmentVariables"]
    expected_ref = expected["candidate_manifest_sha256"]
    load = subprocess.check_output(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"], text=True)
    loaded_ref = re.search(r"^\s*V4_RELEASE_MANIFEST_SHA256 => ([0-9a-f]{64})\s*$", load, re.M)
    pid_match = re.search(r"^\s*pid = (\d+)\s*$", load, re.M)
    assert loaded_ref and pid_match and loaded_ref[1] == expected_ref
    assert env["V4_RELEASE_MANIFEST_SHA256"] == sha(Path(env["V4_RELEASE_MANIFEST_PATH"]).read_bytes()) == expected_ref
    assert sha(raw) == expected["candidate_plist_sha256"]
    return dict(role=kind, pid=int(pid_match[1]), release_id=env["V4_RELEASE_ID"],
                manifest_sha256=expected_ref, config_sha256=sha(raw))


def collect(base_date, rows):
    roles = [role_status(kind, suffix, rows[kind])
             for kind, suffix in (("api", "api"), ("main", "scheduler"))]
    assert http("/healthz")["status"] == "ok"
    route = "/api/v4/research/workbench/days/" + base_date
    day = http(route)
    versions = http(route + "/versions")
    assert all(day[k] == versions[k] for k in ("source_date", "observation_date", "generation", "input_sha256", "numeric_manifest"))
    summary = day["formula_groups"].get("f10_coverage")
    roster = day["formula_groups"].get("artifact")
    if roster is not None:
        assert isinstance(summary, dict) and summary["formula_group_sha256"] == roster["sha256"]
        assert summary["numeric_manifest_sha256"] == day["numeric_manifest"]["sha256"]
        assert all(summary[k] == day[k] for k in ("source_date", "observation_date", "generation", "input_sha256"))
        assert sum(summary[k] for k in ("observed", "failed", "remaining")) == day["scope_count"]
    return dict(role_state=roles, day={k: day[k] for k in ("source_date", "observation_date", "generation", "input_sha256", "numeric_manifest", "scope_count")},
                formula_coverage=summary, formula_roster=roster,
                versions=versions, day_response=day)


def natural_tick(config, rows, now):
    if now.date().isoformat() < config["first_natural_date"] or now.weekday() >= 5 or now.hour < 16:
        return
    required_days = config.get("observations_required", 3)
    if type(required_days) is not int or required_days < 1:
        required_days = 3
    if len(_valid_business_days()) >= required_days:
        return
    date8 = now.strftime("%Y%m%d")
    ledger = Path(config["ledger_root"])
    scheduler = rows["main"]

    def append_record(kind, *, data, raw, dispatch_path, run_id, slot,
            observations, workload=None, authority=None, readback=None,
            binding=None, error=None, recovered_from=None, recovery_relationship=None,
            publisher_attribution=None):
        dispatch_sha256 = sha(raw)
        workload_sha256 = _canonical_sha(workload) if isinstance(workload, dict) else None
        identity = authority.get("source_identity") if isinstance(authority, dict) else None
        versions_event_id = binding.get("versions_event_id") if isinstance(binding, dict) else None
        f10_receipt_sha256 = binding.get("f10_receipt_sha256") if isinstance(binding, dict) else None
        evidence_identity = _evidence_identity(run_id, dispatch_sha256, date8,
            workload_sha256, identity, versions_event_id, f10_receipt_sha256,
            None if readback is not None else (error or "CANNOT_CONFIRM"))
        evidence_id = _canonical_sha(evidence_identity)
        invocation_status = ("INVOKED" if DAILY_WORKLOAD_ID in data.get("invoked_workload_ids", [])
                             else "NOT_INVOKED")
        workload_status = workload.get("status") if isinstance(workload, dict) else "NOT_RECORDED"
        coverage = readback.get("formula_coverage", {}) if isinstance(readback, dict) else {}
        if kind == "BUSINESS_READBACK":
            business_status = "SOURCE_BOUND_READBACK_PRESENT"
        elif kind == "RECOVERY" and coverage.get("status") == "COMPLETE" and not error:
            business_status = "FOLLOWUP_READBACK_COMPLETE"
        elif coverage.get("status") == "PARTIAL":
            business_status = "PARTIAL"
        elif error:
            business_status = "CANNOT_CONFIRM"
        else:
            business_status = coverage.get("status", "CANNOT_CONFIRM")
        record = dict(schema=EVIDENCE_SCHEMA, evidence_kind=kind, evidence_id=evidence_id,
            evidence_identity=evidence_identity, status=kind, natural_trigger="OBSERVED_LIVE_DISPATCH",
            trigger_status=("NOT_TRIGGERED" if invocation_status == "NOT_INVOKED" else "TRIGGERED"),
            run_id=run_id, slot=slot, work_date=date8, dispatch_sha256=dispatch_sha256,
            dispatch_path=dispatch_path.name, source_release=data.get("release_id"),
            dispatch_status=data.get("status"),
            workload_invocation_status=invocation_status,
            workload_execution_status=workload_status,
            workload_result_sha256=workload_sha256,
            source_identity=identity,
            daily_derivatives=(authority.get("daily_derivatives") if isinstance(authority, dict) else None),
            formula_groups=(authority.get("formula_groups") if isinstance(authority, dict) else None),
            formula_group_run_status=(authority.get("formula_groups", {}).get("status")
                if isinstance(authority, dict) else None),
            daily_derivatives_status=(authority.get("daily_derivatives", {}).get("status")
                if isinstance(authority, dict) else None),
            business_status=business_status, versions_event_id=versions_event_id,
            f10_receipt_sha256=f10_receipt_sha256,
            receipt_relation=binding.get("receipt_relation") if isinstance(binding, dict) else None,
            current_supplement=binding.get("current_owner") if isinstance(binding, dict) else None,
            scheduler_observations=observations, browser_refresh="NOT_OBSERVED",
            readback=readback, error=error, recovered_from=recovered_from,
            recovery_relationship=recovery_relationship,
            publisher_attribution=publisher_attribution,
            RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
        path = OUT / f"NATURAL_{date8}_{slot}_{run_id}_{evidence_id}_{kind}.json"
        _append_json_once(path, record)
        return record

    def matching_pending(run_id, slot, dispatch_sha256, workload_sha256, authority):
        source_identity = authority.get("source_identity") if isinstance(authority, dict) else None
        if not isinstance(source_identity, dict):
            return []
        found = []
        pattern = f"NATURAL_{date8}_{slot}_{run_id}_*_PENDING.json"
        for path in sorted(OUT.glob(pattern)):
            try:
                record = read(path)
            except (OSError, ValueError, TypeError):
                continue
            readback = record.get("readback") if isinstance(record, dict) else None
            coverage = readback.get("formula_coverage") if isinstance(readback, dict) else None
            if (record.get("schema") == EVIDENCE_SCHEMA
                    and record.get("run_id") == run_id and record.get("slot") == slot
                    and record.get("work_date") == date8
                    and record.get("status") == "PENDING"
                    and record.get("business_status") == "PARTIAL"
                    and record.get("dispatch_sha256") == dispatch_sha256
                    and record.get("workload_result_sha256") == workload_sha256
                    and record.get("source_identity") == source_identity
                    and isinstance(coverage, dict) and coverage.get("status") == "PARTIAL"
                    and record.get("f10_receipt_sha256") == authority.get("expected_f10_receipt_sha256")
                    and _valid_sha(record.get("versions_event_id"))
                    and _valid_sha(record.get("evidence_id"))
                    and isinstance(record.get("evidence_identity"), dict)
                    and _canonical_sha(record["evidence_identity"]) == record["evidence_id"]):
                found.append(record)
        return found

    for slot in ("1610", "1640"):
        for path in sorted((ledger / "receipts" / "live" / date8 / slot).glob("*.dispatch-receipt.json")):
            raw = path.read_bytes()
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            run_id = data.get("run_id")
            if (not re.fullmatch(r"[a-f0-9]+", str(run_id or ""))
                    or path.name != run_id + ".dispatch-receipt.json"
                    or _date8(data.get("business_date")) != date8
                    or data.get("mode") != "LIVE"):
                continue
            dispatch = OUT / f"NATURAL_{date8}_{slot}_{run_id}_DISPATCH.json"
            if not dispatch.exists():
                dispatch.write_bytes(raw)
            elif sha(dispatch.read_bytes()) != sha(raw):
                dispatch = OUT / f"NATURAL_{date8}_{slot}_{run_id}_{sha(raw)}_DISPATCH.json"
                if not dispatch.exists():
                    dispatch.write_bytes(raw)
            dispatch_valid = (data.get("slot") == slot
                and data.get("ledger_sha256") == _canonical_sha(
                    {key:value for key,value in data.items() if key != "ledger_sha256"})
                and _safe(data))
            observation_dir = ledger / "scheduler_observations" / "live" / date8 / slot
            observations = [read(p) for p in sorted(observation_dir.glob("*.observation.json"))]
            workload_matches = _workload_rows(data)
            workload = workload_matches[0] if len(workload_matches) == 1 else None
            if not dispatch_valid:
                append_record("PENDING", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations, workload=workload,
                    error="DISPATCH_RECEIPT_UNCONFIRMED")
                continue
            if DAILY_WORKLOAD_ID not in data.get("invoked_workload_ids", []):
                append_record("NOT_TRIGGERED", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations,
                    error="DAILY_WORKLOAD_NOT_INVOKED")
                continue
            if data.get("release_id") != scheduler.get("candidate_release_id"):
                append_record("PENDING", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations, workload=workload,
                    error="DISPATCH_RELEASE_NOT_CURRENT")
                continue
            if (DAILY_WORKLOAD_ID not in data.get("succeeded_workload_ids", []) or workload is None):
                append_record("PENDING", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations, workload=workload,
                    error="DISPATCH_OR_WORKLOAD_RESULT_UNCONFIRMED")
                continue
            try:
                authority = _workload_identity(data, workload, date8)
            except (OSError, KeyError, TypeError, ValueError, AssertionError) as error:
                append_record("PENDING", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations, workload=workload,
                    error=f"{type(error).__name__}: {error}")
                continue
            try:
                view = collect(datetime.strptime(date8, "%Y%m%d").date().isoformat(), rows)
                binding = _match_readback(view, authority)
            except (OSError, KeyError, TypeError, ValueError, AssertionError) as error:
                append_record("PENDING", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations, workload=workload,
                    authority=authority,
                    error=f"{type(error).__name__}: {error}")
                continue

            linkage = dict(view)
            route = "/api/v4/research/workbench/days/" + datetime.strptime(date8, "%Y%m%d").date().isoformat()
            try:
                day_rows = view["day_response"].get("rows", [])
                for name, suffix in (("chart", "formula-daily-k"), ("score", "single-research"), ("f10", "f10")):
                    if day_rows:
                        linkage[name] = http(route + "/" + suffix + "/" + day_rows[0]["symbol"])
                with urlopen("http://127.0.0.1:8873" + route + "/events", timeout=12) as stream:
                    frame = []
                    while True:
                        line = stream.readline()
                        frame.append(line.decode("utf-8"))
                        if line in (b"\n", b""):
                            break
                linkage["server_sse_frame"] = "".join(frame)
            except (OSError, KeyError, TypeError, ValueError, AssertionError) as error:
                linkage["detail_readback_error"] = f"{type(error).__name__}: {error}"
            coverage = linkage.get("formula_coverage") or {}
            if coverage.get("status") == "COMPLETE":
                recovered = matching_pending(run_id, slot, sha(raw),
                    _canonical_sha(workload), authority)
                recovered_ids = sorted({record["evidence_id"] for record in recovered})
                if binding.get("receipt_relation") == "ADVANCED_WITHIN_EXACT_RUN_SOURCE_IDENTITY":
                    progressed = [record for record in recovered
                        if record.get("f10_receipt_sha256") != binding.get("f10_receipt_sha256")
                        and record.get("versions_event_id") != binding.get("versions_event_id")]
                    if not progressed:
                        append_record("PENDING", data=data, raw=raw, dispatch_path=dispatch,
                            run_id=run_id, slot=slot, observations=observations, workload=workload,
                            authority=authority, readback=linkage, binding=binding,
                            error="F10_ADVANCE_WITHOUT_SAME_RUN_PARTIAL_VERSION")
                        continue
                    owner_dispatch = _other_dispatch_claims_f10(ledger, date8, scheduler,
                        run_id, sha(raw), authority["source_identity"], binding["f10_receipt_sha256"])
                    if owner_dispatch:
                        append_record("RECOVERY", data=data, raw=raw, dispatch_path=dispatch,
                            run_id=run_id, slot=slot, observations=observations, workload=workload,
                            authority=authority, readback=linkage, binding=binding,
                            recovered_from=sorted({record["evidence_id"] for record in progressed}),
                            recovery_relationship="SAME_SOURCE_FOLLOWUP_CLAIMED_BY_DISTINCT_DISPATCH",
                            publisher_attribution="CANNOT_CONFIRM_OLDER_RUN_AS_PUBLISHER",
                            error="F10_ADVANCE_OWNED_BY_DISTINCT_DISPATCH:" + owner_dispatch["run_id"])
                        continue
                    append_record("RECOVERY", data=data, raw=raw, dispatch_path=dispatch,
                        run_id=run_id, slot=slot, observations=observations, workload=workload,
                        authority=authority, readback=linkage, binding=binding,
                        recovered_from=sorted({record["evidence_id"] for record in progressed}),
                        recovery_relationship="SAME_SOURCE_FOLLOWUP_NO_POINTER_PREDECESSOR_SHA",
                        publisher_attribution="CANNOT_CONFIRM_FROM_POINTER_PREDECESSOR")
                append_record("BUSINESS_READBACK", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations, workload=workload,
                    authority=authority, readback=linkage, binding=binding,
                    recovered_from=recovered_ids or None,
                    recovery_relationship=("SAME_SOURCE_FOLLOWUP_NO_POINTER_PREDECESSOR_SHA"
                        if binding.get("receipt_relation") == "ADVANCED_WITHIN_EXACT_RUN_SOURCE_IDENTITY"
                        else None),
                    publisher_attribution=("CANNOT_CONFIRM_FROM_POINTER_PREDECESSOR"
                        if binding.get("receipt_relation") == "ADVANCED_WITHIN_EXACT_RUN_SOURCE_IDENTITY"
                        else "DISPATCH_OWNER_RECEIPT_MATCHED"))
                if len(_valid_business_days()) >= required_days:
                    return
            else:
                append_record("PENDING", data=data, raw=raw, dispatch_path=dispatch,
                    run_id=run_id, slot=slot, observations=observations, workload=workload,
                    authority=authority, readback=linkage, binding=binding,
                    error=("F10_COVERAGE_PARTIAL" if coverage.get("status") == "PARTIAL"
                           else "F10_COVERAGE_CANNOT_CONFIRM"))


def main():
    now = datetime.now(TZ)
    plan = read(OUT / "MONITOR_CONFIG.json")
    activated = read(OUT / "ACTIVATION_RECEIPT.json")
    assert activated["status"] == "DEPLOYED"
    assert sha((OUT / "ACTIVATION_RECEIPT.json").read_bytes()) == plan["activation_receipt_sha256"]
    assert sha((OUT / "INTEGRATED_CANDIDATE.json").read_bytes()) == plan["candidate_receipt_sha256"]
    rows = {r["role"]: r for r in read(OUT / "INTEGRATED_CANDIDATE.json")["roles"]}
    seconds = (now - datetime.fromisoformat(activated["activated_at"])).total_seconds()
    for minute in (0, 5, 30):
        receipt = OUT / f"MONITOR_T_PLUS_{minute}.json"
        if seconds < minute * 60 or receipt.exists():
            continue
        try:
            health = collect(plan["reference_source_date"], rows)
            health.pop("day_response")
            report = dict(status="PASS", **health)
        except (OSError, KeyError, TypeError, ValueError, AssertionError, subprocess.CalledProcessError) as error:
            report = dict(status="HEALTH_REGRESSION", error=f"{type(error).__name__}: {error}")
        once(receipt, dict(checked_at=now.isoformat(), seconds_after_activation=seconds,
                           planned_minutes=minute, head=activated["head"], **report))
    natural_tick(plan, rows, now)


if __name__ == "__main__":
    main()
