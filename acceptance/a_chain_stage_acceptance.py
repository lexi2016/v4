"""Offline inspection of captured A-stage API declarations; no live certification."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


STAGES = {
    "STAGE_0925": "09:25:05",
    "STAGE_0930_0935": "09:35:05",
    "STAGE_0935_0940": "09:40:05",
    "STAGE_0940_0945": "09:45:05",
    "STAGE_0945_1030": "10:30:00",
    "STAGE_1300_1315": "13:15:00",
    "STAGE_1445_1500": "15:00:00",
    "STAGE_1545_1555": None,
}
FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")
SHA = re.compile(r"[0-9a-fA-F]{64}\Z")
RECOVERY = ("HISTORICAL_BACKFILL", "LATE_CATCHUP_REPLAY", "AFTERFACT", "REPLAY", "LATE_RECOVERY")


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _finite(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _reject_nonfinite_json(value: str):
    raise ValueError(f"NONFINITE_JSON_CONSTANT:{value}")


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.utcoffset() is not None else None
    except ValueError:
        return None


def _declarations(value: Any, path: str = "$"):
    """Retain gap values and clock/mode declarations without interpreting prose."""
    if isinstance(value, dict):
        for key, item in value.items():
            item_path = f"{path}.{key}"
            if key == "cannot_confirm" or key in FLAGS or key == "RESEARCH_ONLY":
                yield key, item_path, item
            if key in {"mode", "due_status", "execution_mode", "capture_mode", "execution_origin"}:
                yield "mode", item_path, item
            if key in {"execution_verified", "natural_verified"}:
                yield "proof_flag", item_path, item
            if key in {"captured_at", "recorded_at", "started_at", "finished_at", "published_at",
                       "generated_at", "capture_started_at", "query_started_at", "returned_at",
                       "update_time", "source_last_bar_time", "source_update_time", "cutoff_at",
                       "market_cutoff_at", "native_capture_started_at", "native_captured_at",
                       "native_source_update_time"}:
                yield "time", item_path, item
            if key == "source_evidence" and isinstance(item, list):
                for index, marker in enumerate(item):
                    if isinstance(marker, str) and any(token in marker.upper() for token in RECOVERY):
                        yield "recovery_marker", f"{item_path}[{index}]", marker
            yield from _declarations(item, item_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _declarations(item, f"{path}[{index}]")


def check_a_chain(trade_date: str, captures: Mapping[str, Any]) -> dict:
    """Check captured payloads only; never fetch files named inside a payload.

    ``ROW_RESULT_PRESENT_VERIFIED`` means the captured API's explicit trio
    verification declaration and identities agree. It is not a local rehash,
    authenticated ledger audit, business certification or natural execution.
    """
    parsed_date = datetime.strptime(trade_date, "%Y%m%d")
    if parsed_date.strftime("%Y%m%d") != trade_date:
        raise ValueError("trade_date must be an exact valid YYYYMMDD date")
    reports = []
    for stage, cutoff_clock in STAGES.items():
        if cutoff_clock is None:
            reports.append(dict(stage_id=stage, applicability="NOT_APPLICABLE", reason="HK_ONLY_BY_CONTRACT"))
            continue
        cutoff = f"{parsed_date:%Y-%m-%d}T{cutoff_clock}+08:00"
        value = captures.get(stage)
        payload = _object(value)
        issues, business_gaps, declared_gaps, times, recovery, proof_flags = [], [], [], [], [], []
        if not payload:
            issues.append("CAPTURE_MISSING_OR_NOT_AN_OBJECT")
        if payload.get("schema_version") != "stage_center.selection_consumer.v1":
            issues.append("UNKNOWN_OR_MISSING_API_SCHEMA")
        for key, expected in (("trade_date", trade_date), ("stage_id", stage)):
            if payload.get(key) != expected:
                issues.append(f"API_{key.upper()}_MISMATCH")
        for flag in FLAGS:
            if payload.get(flag) is not False:
                issues.append(f"API_SAFETY_FLAG_NOT_FALSE:{flag}")
        for kind, path, item in _declarations(payload):
            if kind == "cannot_confirm":
                declared_gaps.append(dict(path=path, value=item))
                if not isinstance(item, list) or any(not isinstance(gap, str) for gap in item):
                    issues.append(f"INVALID_CANNOT_CONFIRM_SHAPE:{path}")
                elif item:
                    business_gaps.extend(item)
            elif kind in FLAGS and item is not False:
                issues.append(f"SAFETY_FLAG_NOT_FALSE:{path}")
            elif kind == "RESEARCH_ONLY" and item is not True:
                issues.append(f"RESEARCH_ONLY_NOT_TRUE:{path}")
            elif kind == "time":
                times.append(dict(path=path, value=item, timezone_verified=_time(item) is not None))
            elif kind == "proof_flag":
                proof_flags.append(dict(path=path, value=item))
            elif kind == "recovery_marker" or (
                kind == "mode" and isinstance(item, str) and any(token in item.upper() for token in RECOVERY)
            ):
                recovery.append(dict(path=path, value=item))
        markets = _object(payload.get("markets"))
        market = _object(markets.get("A"))
        rows = market.get("rows")
        if not isinstance(rows, list):
            rows = []
            issues.append("A_ROWS_MISSING_OR_INVALID")
        if not 1 <= len(rows) <= 10:
            issues.append("A_ROW_COUNT_OUTSIDE_1_TO_10")
        count = payload.get("selected_a_rows")
        if type(count) is not int or count != len(rows):
            issues.append("SELECTED_A_ROWS_COUNT_MISMATCH")
        codes, row_statuses = [], []
        for index, row in enumerate(rows):
            row = _object(row)
            code = row.get("code")
            if not isinstance(code, str) or not re.fullmatch(r"A\.\d{6}", code):
                issues.append(f"NONCANONICAL_A_CODE:{index}")
            else:
                codes.append(code)
            if row.get("trade_date", trade_date) != trade_date or row.get("stage_id", stage) != stage:
                issues.append(f"A_ROW_DATE_OR_STAGE_MISMATCH:{index}")
            for field in ("status", "selection_status", "source_status", "source_health"):
                if field in row:
                    row_statuses.append(dict(row_index=index, code=code, field=field, value=row[field]))
                    if row[field] != "READY":
                        business_gaps.append(f"A_ROW_{index}_{field.upper()}_NOT_READY:{row[field]!r}")
            if not _finite(row.get("score")):
                business_gaps.append(f"SCORE_MISSING_OR_NONFINITE:{index}")
            if stage != "STAGE_0925":
                for field in ("news_quality_score", "research_quality_score", "research_bonus"):
                    if not _finite(row.get(field)):
                        business_gaps.append(f"QUALITY_MISSING_OR_NONFINITE:{index}:{field}")
        if len(set(codes)) != len(codes):
            issues.append("DUPLICATE_A_CODES")
        execution = _object(payload.get("execution_evidence"))
        executed = _object(_object(execution.get("markets")).get("A_SHARE"))
        declared_identity = _object(executed.get("declared_identity"))
        binding = _object(_object(execution.get("selection_artifact_bindings")).get("A_SHARE"))
        if market.get("selection_manifest_receipt_verified") is not True:
            issues.append("A_SELECTION_TRIO_NOT_EXPLICITLY_VERIFIED")
        if binding.get("status") != "BOUND_TO_VERIFIED_SELECTION_TRIO":
            issues.append("A_SELECTION_TRIO_BINDING_UNAVAILABLE")
        # The owning v1 API puts scope on the two outer envelopes, identity
        # under the execution lane's declared_identity, and trio paths/hashes
        # in the binding. It does not repeat all fields in each object.
        for key, expected in (("trade_date", trade_date), ("stage_id", stage)):
            if execution.get(key) != expected:
                issues.append(f"EXECUTION_{key.upper()}_MISMATCH")
        if market.get("market") != "A_SHARE":
            issues.append("MARKET_MARKET_MISMATCH")
        for label, evidence in (("API", payload), ("EXECUTION", execution)):
            if "market" in evidence and evidence["market"] != "A_SHARE":
                issues.append(f"{label}_OPTIONAL_MARKET_MISMATCH")
        for label, evidence in (("MARKET", market), ("EXECUTION_LANE", executed),
                                ("DECLARED_IDENTITY", declared_identity), ("BINDING", binding)):
            for key, expected in (("trade_date", trade_date), ("stage_id", stage), ("market", "A_SHARE")):
                if key in evidence and evidence[key] != expected:
                    issues.append(f"{label}_{key.upper()}_MISMATCH")
        for key in ("artifact_id", "run_id", "algorithm_sha256", "raw_artifact_sha256"):
            value = market.get(key)
            if not isinstance(value, str) or not value or declared_identity.get(key) != value:
                issues.append(f"A_{key.upper()}_IDENTITY_UNBOUND")
            if key.endswith("sha256") and (not isinstance(value, str) or not SHA.fullmatch(value)):
                issues.append(f"A_{key.upper()}_INVALID")
            for label, evidence in (("EXECUTION_LANE", executed), ("BINDING", binding)):
                if key in evidence and evidence[key] != value:
                    issues.append(f"{label}_{key.upper()}_IDENTITY_CONFLICT")
        run_id = market.get("run_id")
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
            issues.append("A_RUN_ID_UNSAFE_OR_MISSING")
        if binding.get("run_id") != run_id or not run_id:
            issues.append("BINDING_RUN_ID_IDENTITY_UNBOUND")
        prefix = f"selection_runs/{trade_date}/A_SHARE_SELECTION_{stage}/{run_id}"
        for key, filename in (("artifact_relative", "artifact.csv"), ("manifest_relative", "manifest.json"),
                              ("receipt_relative", "receipt.json")):
            if binding.get(key) != f"{prefix}/{filename}":
                issues.append(f"A_TRIO_PATH_SCOPE_MISMATCH:{key}")
        for key in ("artifact_bytes_sha256", "manifest_bytes_sha256", "receipt_bytes_sha256",
                    "manifest_canonical_sha256", "receipt_canonical_sha256"):
            digest = binding.get(key)
            if not isinstance(digest, str) or not SHA.fullmatch(digest):
                issues.append(f"A_TRIO_SHA256_MISSING_OR_INVALID:{key}")
            for label, evidence in (("MARKET", market), ("EXECUTION", executed)):
                if key in evidence and evidence[key] != digest:
                    issues.append(f"{label}_TRIO_SHA256_CONFLICT:{key}")
        # Market JSON identities are canonical hashes, not the serialized
        # manifest/receipt file byte hashes. Artifact CSV is bound by bytes.
        for market_key, binding_key in (("selection_artifact_sha256", "artifact_bytes_sha256"),
                                        ("selection_manifest_sha256", "manifest_canonical_sha256"),
                                        ("selection_receipt_sha256", "receipt_canonical_sha256")):
            digest = market.get(market_key)
            if not isinstance(digest, str) or not SHA.fullmatch(digest) or digest != binding.get(binding_key):
                issues.append(f"A_TRIO_MARKET_SHA256_UNBOUND:{market_key}")
        for key in ("selected_rows",):
            for label, evidence in (("MARKET", market), ("EXECUTION", executed), ("BINDING", binding)):
                if key in evidence and (type(evidence[key]) is not int or evidence[key] != len(rows)):
                    issues.append(f"{label}_ROW_COUNT_MISMATCH")
        for key in ("status", "selection_status", "source_status"):
            if market.get(key) != "READY":
                business_gaps.append(f"A_{key.upper()}_NOT_READY:{market.get(key)!r}")
        # Flags in a captured response are declarations, never a receipt oracle.
        # No owning-receipt proof schema is supplied by this frozen API contract.
        natural_gaps = ["OWNING_RECEIPT_NATURAL_PROOF_NOT_AVAILABLE_IN_SUPPORTED_API_SCHEMA"]
        if stage == "STAGE_0925":
            natural_gaps.append("NATIVE_0925_RAW_MANIFEST_AND_CAPTURE_WINDOW_RECEIPT_BINDING_REQUIRED")
        for timestamp in times:
            parsed = _time(timestamp["value"])
            if parsed is None:
                natural_gaps.append(f"TIMESTAMP_UNKNOWN_OR_WITHOUT_TIMEZONE:{timestamp['path']}")
            elif parsed > _time(cutoff):
                recovery.append(dict(path=timestamp["path"], value=timestamp["value"]))
        if not times:
            natural_gaps.append("EXECUTION_CAPTURE_TIMESTAMPS_NOT_AVAILABLE")
        if recovery:
            natural_gaps.append("RECOVERY_OR_POST_CUTOFF_TIMING_NOT_NATURAL_STAGE_PROOF")
        row_verified = bool(rows) and not issues
        reports.append(dict(
            stage_id=stage, applicability="A_SHARE", stage_cutoff_at=cutoff,
            synthetic=payload.get("synthetic") is True,
            captured_at=payload.get("captured_at"), observed_a_rows=len(rows), selected_a_rows_declared=count,
            row_materialization="ROW_RESULT_PRESENT_VERIFIED" if row_verified else "CANNOT_CONFIRM",
            row_contract_verified=row_verified,
            verification_basis="CAPTURED_API_TRIO_DECLARATIONS_AND_IDENTITY_ONLY_NOT_LOCAL_FILE_REHASH",
            business_status="BUSINESS_PARTIAL" if row_verified and business_gaps else (
                "DECLARED_READY_ONLY" if row_verified else "CANNOT_CONFIRM"),
            business_gaps=list(dict.fromkeys(business_gaps)), declared_gaps=declared_gaps,
            row_status_declarations=row_statuses,
            validation_errors=list(dict.fromkeys(issues)),
            execution_verified_declared=execution.get("execution_verified", payload.get("execution_verified")),
            execution_status="UNVERIFIED_OWNING_RECEIPT_NOT_INSPECTED",
            natural_verified_declared=execution.get("natural_verified", payload.get("natural_verified")),
            execution_natural_declarations=proof_flags,
            natural_status="RECOVERY_ONLY" if recovery else "CANNOT_CONFIRM",
            natural_verified=False, actual_stage_pass=False,
            natural_gaps=natural_gaps, timestamp_declarations=times, recovery_evidence=recovery,
        ))
    return dict(
        schema_version="v4.a_chain.offline_acceptance.v1", trade_date=trade_date,
        checked_at=datetime.now(timezone.utc).isoformat(), preparation_status="OFFLINE_CHECK_COMPLETED",
        overall_status="CANNOT_CONFIRM", actual_live_certification=False,
        applicable_a_stage_count=7, row_contract_verified_count=sum(item.get("row_contract_verified", False) for item in reports),
        natural_verified_count=0, stages=reports,
        close_1605=dict(scope="SEPARATE_FROM_INTRADAY_A_CHAIN", status="CANNOT_CONFIRM", evidence_inspected=False),
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    args = parser.parse_args(argv)
    captures, sources = {}, []
    for stage, cutoff in STAGES.items():
        if cutoff is None:
            continue
        path = args.input_dir / f"{stage}.json"
        digest = None
        try:
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            captures[stage] = json.loads(raw, parse_constant=_reject_nonfinite_json)
            sources.append(dict(stage_id=stage, path=str(path), sha256=digest, error=None))
        except (OSError, ValueError, UnicodeError) as error:
            sources.append(dict(stage_id=stage, path=str(path), sha256=digest, error=f"{type(error).__name__}:{error}"))
    try:
        result = check_a_chain(args.trade_date, captures)
    except ValueError as error:
        parser.error(str(error))
    result["capture_files"] = sources
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0  # Report creation, never a claim that any actual A stage passed.


if __name__ == "__main__":
    raise SystemExit(main())
