"""ops.macos_research_panel_daily: hk_market_capture (review candidate, not deployment)."""
from __future__ import annotations
import base64
import hashlib
import json
import math
import re
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Mapping


_HK_CAPTURE_V2_SCHEMA = "v4.manager_hk_connect_capture.v2"
_HK_CAPTURE_SERIALIZATION_V2 = "futu.dataframe.records.canonical-json.v1"
_HK_FORWARD_SOURCE_SET = {
    "source_head": "55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054",
    "forward_receipt_sha256": "69ed8c29225b9476ed358f76769ac1ec37a7f4d94806a8b803138901f789523e",
    "candidate_manifest_sha256": "75f6f5543137319810b1f433cefa83ae89c204c2bf6ab56c42effa4be89a6366",
    "candidate_build_receipt_sha256": "439d5ffba4475b5183a2d74e7cc518693391b7b3b9a3fcc18f95be4b77aea194",
    "api_writer_receipt_sha256": "3ea98364f997591e1cecba92758a35dff6c4cb0bb0136a43bcb3524f1d734a4d",
    "api_reviewer_receipt_sha256": "daf18d4bf0a763187708c8f263385d09f668a77ac1d9c4948361b4a8c9855790",
    "api_source_mapping_sha256": "5c66286e130e971cf89f256e8cb001e2d951dc67ac3db27d93a0f37ff76e1feb",
}


def _canonical_capture_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sdk_json_value(value: Any) -> Any:
    """Encode SDK DataFrame values without dropping columns or row positions."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"$float": repr(value)}
    if isinstance(value, Decimal):
        return {"$decimal": str(value)}
    if isinstance(value, (datetime, date, time)):
        return {"$datetime": value.isoformat()}
    if isinstance(value, bytes):
        return {"$bytes_base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Futu SDK row has a non-string key")
        return {key: _sdk_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sdk_json_value(item) for item in value]
    if type(value).__name__ in {"NAType", "NaTType"}:
        return {"$missing_scalar": type(value).__name__}
    item = getattr(value, "item", None)
    if callable(item):
        try:
            scalar = item()
        except (TypeError, ValueError):
            scalar = value
        if scalar is not value:
            return _sdk_json_value(scalar)
    raise TypeError(f"unsupported Futu SDK value type: {type(value).__name__}")


def _sdk_dataframe_records(frame: Any) -> tuple[list[str], list[dict[str, Any]]]:
    if frame is None or not callable(getattr(frame, "to_dict", None)):
        raise TypeError("Futu plate response is not a usable DataFrame")
    columns_value = getattr(frame, "columns", None)
    if columns_value is None:
        raise TypeError("Futu plate DataFrame columns are missing")
    columns = [str(_sdk_json_value(column)) for column in list(columns_value)]
    if len(columns) != len(set(columns)):
        raise TypeError("Futu plate DataFrame columns are duplicated")
    records = frame.to_dict(orient="records")
    if not isinstance(records, list):
        raise TypeError("Futu plate DataFrame records are malformed")
    normalized = []
    for record in records:
        if not isinstance(record, Mapping):
            raise TypeError("Futu plate DataFrame row is malformed")
        row = _sdk_json_value(record)
        if not isinstance(row, dict):
            raise TypeError("Futu plate DataFrame row is malformed")
        normalized.append(row)
    return columns, normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")



def capture_hk_connect_monthly_membership(*, trade_date: str, store_root, shared_package_root,
                                          futu_python, context_factory=None):
    """Capture only the two native Connect plate frames and publish v2 authority.

    The returned membership is verified again by the caller through the
    read-only manager evidence adapter. This entry point deliberately skips
    market snapshots, quotes, Stage rows, and the legacy 651-row gate.
    """
    from datetime import datetime
    from pathlib import Path
    import importlib
    import uuid

    if not isinstance(trade_date, str) or re.fullmatch(r"\d{8}", trade_date) is None:
        raise ValueError("HK_CONNECT_MONTHLY_SOURCE_DATE_INVALID")
    try:
        datetime.strptime(trade_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("HK_CONNECT_MONTHLY_SOURCE_DATE_INVALID") from exc

    ensure_module = importlib.import_module("ops.ensure_hk_security_master")
    contract, _contract_owner = ensure_module._load_hk_connect_v2_contract()
    plates = tuple(contract.HKCONNECT_PLATE_CODES)
    if set(plates) != {"HK.GangGuTong", "HK.LIST1922"}:
        raise ValueError("HK_CONNECT_MONTHLY_NATIVE_PLATE_CONTRACT_INVALID")
    if context_factory is None:
        def context_factory():
            import futu
            return futu.OpenQuoteContext(host="127.0.0.1", port=11111)

    capture_run_id = uuid.uuid4().hex
    source_path = Path(__file__).resolve()
    forward_source_set = dict(_HK_FORWARD_SOURCE_SET)
    producer_owner = {
        "workload_id": "v35_dispatcher.research_panel_daily_hk",
        "code_ref": "ops/_macos_research_panel_daily_parts/hk_market_capture.py",
        "code_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "forward_source_set": forward_source_set,
        "forward_source_set_sha256": hashlib.sha256(
            _canonical_capture_bytes(forward_source_set)).hexdigest(),
    }
    context = None
    responses: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    close_error = None
    try:
        context = context_factory()
        if context is None:
            raise ValueError("HK_CONNECT_MONTHLY_FUTU_CONTEXT_MISSING")
        for plate in plates:
            requested_at = _utc_now_iso()
            try:
                returned = context.get_plate_stock(plate)
                if not isinstance(returned, (tuple, list)) or len(returned) != 2:
                    raise TypeError("Futu plate return is not (RET, DataFrame)")
                return_code, frame = returned
                columns, rows = _sdk_dataframe_records(frame)
            except Exception as exc:
                errors.append(f"PLATE_CAPTURE_FAILED:{plate}:{type(exc).__name__}")
                continue
            completed_at = _utc_now_iso()
            response_material = {
                "requested_plate": plate,
                "serialization_version": _HK_CAPTURE_SERIALIZATION_V2,
                "columns": columns,
                "rows": rows,
            }
            return_code_ok = type(return_code) is int and return_code == 0
            response = {
                **response_material,
                "return_code": return_code if return_code_ok else None,
                "return_code_type": type(return_code).__name__,
                "return_code_ok": return_code_ok,
                "requested_at": requested_at,
                "completed_at": completed_at,
                "row_count": len(rows),
                "response_sha256": hashlib.sha256(
                    _canonical_capture_bytes(response_material)).hexdigest(),
            }
            if not return_code_ok:
                errors.append(f"RET_NOT_OK:{plate}")
            if not rows:
                errors.append(f"FRAME_EMPTY:{plate}")
            response_codes = [row.get("code") for row in rows]
            if any(not isinstance(code, str) or re.fullmatch(r"HK\.\d{5}", code) is None
                   for code in response_codes):
                errors.append(f"CODE_INVALID:{plate}")
            responses[plate] = response
    except Exception as exc:
        errors.append(f"CONTEXT_OR_FRAME_CAPTURE_FAILED:{type(exc).__name__}")
    finally:
        close = getattr(context, "close", None)
        if callable(close):
            try:
                close()
            except Exception as exc:
                close_error = type(exc).__name__
    if close_error:
        errors.append("CONTEXT_CLOSE_FAILED:" + close_error)
    if errors or set(responses) != set(plates):
        raise ValueError("HK_CONNECT_MONTHLY_CAPTURE_INCOMPLETE:" + ",".join(errors or ["PLATE_SET_INCOMPLETE"]))

    plate_codes: dict[str, list[str]] = {}
    for plate in plates:
        codes = [row.get("code") for row in responses[plate]["rows"]]
        if len(codes) != len(set(codes)):
            raise ValueError("HK_CONNECT_MONTHLY_CAPTURE_DUPLICATE_PLATE_CODE:" + plate)
        plate_codes[plate] = sorted(codes)
    union = sorted(set(plate_codes[plates[0]]) | set(plate_codes[plates[1]]))
    if not union:
        raise ValueError("HK_CONNECT_MONTHLY_CAPTURE_EMPTY_UNION")
    acquired_at = max(datetime.fromisoformat(responses[plate]["completed_at"]).astimezone(timezone.utc)
                      for plate in plates).isoformat()
    response_counts = {plate: responses[plate]["row_count"] for plate in plates}
    response_shas = {plate: responses[plate]["response_sha256"] for plate in plates}
    membership_source_payload = {
        "target_date": trade_date,
        "plate_codes": plate_codes,
        "plate_response_sha256": response_shas,
        "capture_run_id": capture_run_id,
        "acquired_at": acquired_at,
    }
    capture = {
        "schema_version": _HK_CAPTURE_V2_SCHEMA,
        "status": "READY",
        "membership_status": "READY",
        "target_date": trade_date,
        "capture_run_id": capture_run_id,
        "capture_receipt_ref": None,
        "producer_owner": producer_owner,
        "plate_responses": responses,
        "plate_codes": plate_codes,
        "plate_response_counts": response_counts,
        "plate_response_sha256": response_shas,
        "acquired_at": acquired_at,
        "membership_source_payload": membership_source_payload,
        "membership_source_sha256": hashlib.sha256(
            _canonical_capture_bytes(membership_source_payload)).hexdigest(),
        "overlap_count": len(set(plate_codes[plates[0]]) & set(plate_codes[plates[1]])),
        "code_count": len(union),
        "plates": list(plates),
        "codes": union,
        "sdk_capture_ref": None,
        "sdk_capture_sha256": None,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    capture["capture_sha256"] = hashlib.sha256(_canonical_capture_bytes(capture)).hexdigest()
    store = Path(store_root).expanduser().resolve(strict=True)
    package = Path(shared_package_root).expanduser().resolve(strict=True)
    if not store.is_dir() or not package.is_dir():
        raise ValueError("HK_CONNECT_MONTHLY_OWNER_ROOT_MISSING")
    published = ensure_module.ensure_hk_security_master(
        store_root=store, universe_root=store, shared_package_root=package,
        trade_date=trade_date, futu_python=Path(futu_python), capture=capture,
        membership_only=True,
    )
    if (not isinstance(published, Mapping) or published.get("ok") is not True
            or published.get("trade_date") != trade_date
            or published.get("capture_sha256") != capture["capture_sha256"]
            or not isinstance(published.get("universe_authority"), Mapping)
            or published["universe_authority"].get("status") != "READY"):
        raise ValueError("HK_CONNECT_MONTHLY_NATIVE_PUBLICATION_READBACK_INVALID")
    return {"capture": capture, "publication": dict(published), **{
        "status": "PUBLISHED_NATIVE_MEMBERSHIP_ONLY",
        "source_date": trade_date,
        "code_count": len(union),
    }}
