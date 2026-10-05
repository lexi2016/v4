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
from ._namespace import read_global as _v4_global


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


def _collect_hk_futu_rows_body(_v4_scope, /, target_date, *, context_factory, batch_size, minimum_universe_count, required_coverage_ratio, membership_ready_callback=None):
    """Collect an exact-date full HK Connect snapshot from Futu OpenD."""
    target = _v4_global(_v4_scope, '_date')(target_date)
    capture_manifest_value = _v4_global(_v4_scope, 'os').environ.get("V35_HK_CAPTURE_PATH")
    capture_manifest_path = (
        _v4_global(_v4_scope, 'Path')(capture_manifest_value).expanduser()
        if capture_manifest_value
        else None
    )
    capture_raw_path = (
        capture_manifest_path.with_name(f"{capture_manifest_path.stem}.capture.json")
        if capture_manifest_path is not None
        else None
    )
    capture_run_id = (
        _v4_global(_v4_scope, 'os').environ.get("V35_HK_CAPTURE_RUN_ID")
        or capture_manifest_path.stem
        if capture_manifest_path is not None
        else None
    )

    def write_manifest(payload):
        if capture_manifest_path is None:
            return
        if capture_manifest_path.is_symlink():
            raise _v4_global(_v4_scope, 'SnapshotGateError')("HK capture manifest path must not be a symlink")
        if capture_manifest_path.exists():
            try:
                existing = _v4_global(_v4_scope, 'json').loads(
                    capture_manifest_path.read_bytes().decode("utf-8-sig")
                )
            except (OSError, UnicodeError, _v4_global(_v4_scope, 'json').JSONDecodeError) as error:
                raise _v4_global(_v4_scope, 'SnapshotGateError')(
                    f"HK capture manifest path is not a pending or ready envelope: {capture_manifest_path}"
                ) from error
            if _v4_global(_v4_scope, 'isinstance')(existing, _v4_global(_v4_scope, 'Mapping')) and existing.get("status") == "READY":
                if capture_manifest_path.read_bytes() != payload:
                    raise _v4_global(_v4_scope, 'SnapshotGateError')(
                        f"HK capture manifest is immutable and already READY: {capture_manifest_path}"
                    )
                return
        _v4_global(_v4_scope, '_atomic_write')(capture_manifest_path, payload)

    def write_raw_capture(payload):
        if capture_raw_path is None:
            return
        if capture_raw_path.is_symlink():
            raise _v4_global(_v4_scope, 'SnapshotGateError')("HK capture raw path must not be a symlink")
        if capture_raw_path.exists():
            if capture_raw_path.read_bytes() != payload:
                raise _v4_global(_v4_scope, 'SnapshotGateError')(
                    f"HK raw capture path is immutable: {capture_raw_path}"
                )
            return
        _v4_global(_v4_scope, '_atomic_write')(capture_raw_path, payload)

    if capture_manifest_path is not None:
        write_manifest(
            _v4_global(_v4_scope, 'json').dumps(
                {
                    "schema_version": "v3.macos.research_panel_hk_capture_manifest.v1",
                    "status": "PENDING",
                    "target_date": target,
                    "capture_run_id": capture_run_id,
                    "capture_relative_path": capture_raw_path.name,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    plates = tuple(_v4_global(_v4_scope, 'HKCONNECT_PLATE_CODES'))
    source_path = _v4_global(_v4_scope, 'Path')(__file__).resolve()
    forward_source_set = dict(_HK_FORWARD_SOURCE_SET)
    producer_owner = {
        "workload_id": "v35_dispatcher.research_panel_daily_hk",
        "code_ref": "ops/_macos_research_panel_daily_parts/hk_market_capture.py",
        "code_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "forward_source_set": forward_source_set,
        "forward_source_set_sha256": hashlib.sha256(_canonical_capture_bytes(forward_source_set)).hexdigest(),
    }

    def _write_sdk_capture(payload):
        if capture_manifest_path is None:
            return None
        path = capture_manifest_path.with_name(f"{capture_manifest_path.stem}.sdk.capture.json")
        encoded = _canonical_capture_bytes(payload)
        if path.is_symlink():
            raise _v4_global(_v4_scope, 'SnapshotGateError')("HK SDK capture path must not be a symlink")
        if path.exists() and path.read_bytes() != encoded:
            raise _v4_global(_v4_scope, 'SnapshotGateError')("HK SDK capture path is immutable")
        if not path.exists():
            _v4_global(_v4_scope, '_atomic_write')(path, encoded)
        return path, encoded

    def _save_failed_capture(responses, errors, *, sdk_receipt=None):
        capture = {
            "schema_version": _HK_CAPTURE_V2_SCHEMA,
            "status": "FAILED",
            "membership_status": "FAILED",
            "target_date": target,
            "capture_run_id": capture_run_id,
            "capture_receipt_ref": capture_manifest_path.name if capture_manifest_path is not None else None,
            "producer_owner": producer_owner,
            "plate_responses": responses,
            "capture_errors": list(errors),
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        if sdk_receipt is not None:
            capture["sdk_capture_ref"] = sdk_receipt[0].name
            capture["sdk_capture_sha256"] = hashlib.sha256(sdk_receipt[1]).hexdigest()
        capture["capture_sha256"] = _v4_global(_v4_scope, '_canonical_sha')(capture)
        if capture_manifest_path is not None:
            capture_bytes = _canonical_capture_bytes(capture)
            capture_raw_sha = hashlib.sha256(capture_bytes).hexdigest()
            write_raw_capture(capture_bytes)
            write_manifest(_canonical_capture_bytes({
                "schema_version": "v3.macos.research_panel_hk_capture_manifest.v1",
                "status": "FAILED",
                "target_date": target,
                "capture_run_id": capture_run_id,
                "capture_relative_path": capture_raw_path.name,
                "capture_path": capture_raw_path.name,
                "capture": capture,
                "capture_sha256": capture["capture_sha256"],
                "capture_raw_sha256": capture_raw_sha,
                "capture_errors": list(errors),
            }))
        raise _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK Futu membership capture incomplete: " + ",".join(errors)
        )

    if context_factory is None:
        def context_factory():
            import futu

            return futu.OpenQuoteContext(host="127.0.0.1", port=11111)
    context = None
    context_error = None
    try:
        context = context_factory()
    except Exception as error:
        context_error = type(error).__name__
    plate_responses: dict[str, dict[str, Any]] = {}
    capture_errors: list[str] = []
    if context is None:
        capture_errors.append("CONTEXT_INIT:" + (context_error or "FAILED"))
        for plate_code in plates:
            response_material = {
                "requested_plate": plate_code,
                "serialization_version": _HK_CAPTURE_SERIALIZATION_V2,
                "columns": [], "rows": [],
            }
            plate_responses[plate_code] = {
                **response_material,
                "row_count": 0,
                "return_code": None,
                "requested_at": _utc_now_iso(),
                "completed_at": _utc_now_iso(),
                "error_kind": "CONTEXT_INIT_FAILED",
                "response_sha256": _v4_global(_v4_scope, '_canonical_sha')(response_material),
            }
        sdk_receipt = _write_sdk_capture({
            "schema_version": _HK_CAPTURE_V2_SCHEMA,
            "target_date": target,
            "capture_run_id": capture_run_id,
            "producer_owner": producer_owner,
            "plate_responses": plate_responses,
            "status": "FAILED",
        })
        _save_failed_capture(plate_responses, capture_errors, sdk_receipt=sdk_receipt)

    universe: dict[str, str] = {}
    per_plate_codes: dict[str, list[str]] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    codes: list[str] = []
    close_error = None
    snapshot_failure = None
    try:
        for plate_code in plates:
            requested_at = _utc_now_iso()
            return_code = None
            frame = None
            error_kind = None
            try:
                returned = context.get_plate_stock(plate_code)
                if not isinstance(returned, (tuple, list)) or len(returned) != 2:
                    raise TypeError("Futu plate return is not (RET, DataFrame)")
                return_code, frame = returned
            except Exception as error:
                error_kind = type(error).__name__
            completed_at = _utc_now_iso()
            try:
                columns, frame_rows = _sdk_dataframe_records(frame)
            except Exception as error:
                columns, frame_rows = [], []
                error_kind = error_kind or type(error).__name__
            return_code_type = type(return_code).__name__
            return_code_ok = type(return_code) is int and return_code == 0
            try:
                # Keep JSON-native SDK values unchanged for audit.  A value
                # that cannot be serialized is represented with its type and
                # repr, and is never treated as RET_OK.
                captured_return_code = json.loads(json.dumps(
                    return_code, ensure_ascii=False, allow_nan=False
                ))
            except (TypeError, ValueError, OverflowError):
                captured_return_code = {
                    "unserializable_type": f"{type(return_code).__module__}.{type(return_code).__qualname__}",
                    "repr": repr(return_code)[:256],
                }
            response_material = {
                "requested_plate": plate_code,
                "serialization_version": _HK_CAPTURE_SERIALIZATION_V2,
                "columns": columns,
                "rows": frame_rows,
            }
            response = {
                **response_material,
                "return_code": captured_return_code,
                "return_code_type": return_code_type,
                "return_code_ok": return_code_ok,
                "requested_at": requested_at,
                "completed_at": completed_at,
                "row_count": len(frame_rows),
                "response_sha256": _v4_global(_v4_scope, '_canonical_sha')(response_material),
            }
            if error_kind:
                response["error_kind"] = error_kind
            plate_responses[plate_code] = response
            if not return_code_ok:
                capture_errors.append(f"RET_NOT_OK:{plate_code}")
            if error_kind:
                capture_errors.append(f"FRAME_INVALID:{plate_code}")
            if not frame_rows:
                capture_errors.append(f"FRAME_EMPTY:{plate_code}")

        # Persist the complete structured SDK frames before deriving the
        # membership sets or requesting quote snapshots.  This is SDK output,
        # not a claim about the provider's wire bytes or upstream completeness.
        sdk_payload = {
            "schema_version": _HK_CAPTURE_V2_SCHEMA,
            "target_date": target,
            "capture_run_id": capture_run_id,
            "producer_owner": producer_owner,
            "plate_responses": plate_responses,
            "status": "RAW_CAPTURED" if not capture_errors else "FAILED",
            **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
        }
        sdk_receipt = _write_sdk_capture(sdk_payload)

        # Membership derives only from the two retained plate frames.  Quote
        # rows and same-day quote coverage never alter this set.
        for plate_code in plates:
            response = plate_responses.get(plate_code)
            if not isinstance(response, Mapping):
                capture_errors.append(f"PLATE_MISSING:{plate_code}")
                continue
            frame_rows = response.get("rows")
            if not isinstance(frame_rows, list):
                capture_errors.append(f"FRAME_INVALID:{plate_code}")
                continue
            plate_codes: set[str] = set()
            for item in frame_rows:
                code = item.get("code")
                if not isinstance(code, str) or not re.fullmatch(r"HK\.\d{5}", code):
                    capture_errors.append(f"CODE_INVALID:{plate_code}")
                    continue
                plate_codes.add(code)
                universe.setdefault(code, _v4_global(_v4_scope, 'str')(item.get("stock_name") or item.get("name") or "").strip())
            per_plate_codes[plate_code] = sorted(plate_codes)

        if not capture_errors:
            if len(per_plate_codes) != len(plates) or any(not per_plate_codes.get(plate) for plate in plates):
                capture_errors.append("PLATE_SET_INCOMPLETE")
            else:
                codes = _v4_global(_v4_scope, 'sorted')(universe)
                minimum_universe = _v4_global(_v4_scope, 'max')(
                    600, _v4_global(_v4_scope, 'int')(minimum_universe_count)
                )
                if _v4_global(_v4_scope, 'len')(codes) < minimum_universe:
                    raise _v4_global(_v4_scope, 'SnapshotGateError')(
                        f"HK universe below minimum: {_v4_global(_v4_scope, 'len')(codes)} < {minimum_universe_count}"
                    )
                step = _v4_global(_v4_scope, 'max')(1, _v4_global(_v4_scope, 'int')(batch_size))
                for offset in _v4_global(_v4_scope, 'range')(0, _v4_global(_v4_scope, 'len')(codes), step):
                    try:
                        return_code, frame = context.get_market_snapshot(codes[offset : offset + step])
                        if return_code != 0:
                            raise _v4_global(_v4_scope, 'SnapshotGateError')(
                                f"Futu market snapshot failed at offset {offset}"
                            )
                        batch_codes: set[str] = _v4_global(_v4_scope, 'set')()
                        for item in _v4_global(_v4_scope, '_frame_records')(frame):
                            code = _v4_global(_v4_scope, 'str')(item.get("code") or "").strip().upper()
                            if not code or code not in universe:
                                raise _v4_global(_v4_scope, 'SnapshotGateError')(
                                    f"Futu market snapshot returned unmatched code: {code!r}"
                                )
                            if code in batch_codes:
                                raise _v4_global(_v4_scope, 'SnapshotGateError')(
                                    f"Futu market snapshot returned duplicate code: {code}"
                                )
                            batch_codes.add(code)
                            snapshots[code] = item
                    except Exception as error:
                        snapshot_failure = error
                        break
    finally:
        close = _v4_global(_v4_scope, 'getattr')(context, "close", None)
        if _v4_global(_v4_scope, 'callable')(close):
            try:
                close()
            except Exception as error:
                close_error = type(error).__name__
    if close_error:
        snapshot_failure = snapshot_failure or _v4_global(_v4_scope, 'SnapshotGateError')(
            "HK Futu context close failed: " + close_error
        )
    if capture_errors:
        _save_failed_capture(plate_responses, capture_errors, sdk_receipt=sdk_receipt)
    if len(per_plate_codes) != len(plates) or any(not per_plate_codes.get(plate) for plate in plates):
        _save_failed_capture(plate_responses, ["PLATE_SET_INCOMPLETE"], sdk_receipt=sdk_receipt)
    rows: list[dict[str, Any]] = []
    excluded: dict[str, list[str]] = {}
    positive_volume_count = 0
    positive_turnover_count = 0
    required_fields = ("open_price", "high_price", "low_price", "last_price", "volume", "turnover")
    for code in codes:
        source = snapshots.get(code) or {}
        if _v4_global(_v4_scope, '_compact_datetime')(source.get("update_time")) != target:
            excluded[code] = ["stale_or_missing_date"]
            continue
        missing = [field for field in required_fields if field not in source or source.get(field) in (None, "")]
        if missing:
            excluded[code] = [f"missing_{field}" for field in missing]
            continue
        try:
            open_price = _v4_global(_v4_scope, '_number')(source, "open_price")
            high_price = _v4_global(_v4_scope, '_number')(source, "high_price")
            low_price = _v4_global(_v4_scope, '_number')(source, "low_price")
            last_price = _v4_global(_v4_scope, '_number')(source, "last_price")
            volume = _v4_global(_v4_scope, '_number')(source, "volume")
            turnover = _v4_global(_v4_scope, '_number')(source, "turnover")
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'SnapshotGateError')):
            excluded[code] = ["non_numeric_fields"]
            continue
        reasons: list[str] = []
        if volume > 0:
            positive_volume_count += 1
        else:
            reasons.append("non_positive_volume")
        if turnover > 0:
            positive_turnover_count += 1
        else:
            reasons.append("non_positive_turnover")
        if _v4_global(_v4_scope, 'min')(open_price, high_price, low_price, last_price) <= 0 or high_price < low_price or last_price < low_price or last_price > high_price:
            reasons.append("non_positive_ohlc")
        if reasons:
            excluded[code] = reasons
            continue
        try:
            row = {
                "trade_date": target,
                "code": code,
                "name": _v4_global(_v4_scope, 'str')(source.get("name") or universe.get(code) or "").strip(),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": last_price,
                "volume": _v4_global(_v4_scope, 'int')(_v4_global(_v4_scope, 'round')(volume)),
                "turnover": turnover,
                "source": "FUTU_HKCONNECT_SNAPSHOT",
            }
            rows.append(row)
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'), _v4_global(_v4_scope, 'SnapshotGateError')):
            excluded[code] = ["row_encoding_error"]
            continue
    coverage = _v4_global(_v4_scope, 'len')(rows) / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(codes), 1)
    positive_volume_coverage = positive_volume_count / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(codes), 1)
    positive_turnover_coverage = positive_turnover_count / _v4_global(_v4_scope, 'max')(_v4_global(_v4_scope, 'len')(codes), 1)
    minimum_universe = _v4_global(_v4_scope, 'max')(600, _v4_global(_v4_scope, 'int')(minimum_universe_count))
    quote_errors = []
    if snapshot_failure is not None:
        safe_detail = (
            str(snapshot_failure)
            if isinstance(snapshot_failure, _v4_global(_v4_scope, 'SnapshotGateError'))
            else "SDK_EXCEPTION"
        )
        quote_errors.append(type(snapshot_failure).__name__ + ":" + safe_detail)
    if _v4_global(_v4_scope, 'len')(rows) < minimum_universe:
        quote_errors.append(
            "HK exact-date coverage below gate: "
            f"universe={_v4_global(_v4_scope, 'len')(codes)},rows={_v4_global(_v4_scope, 'len')(rows)},coverage={coverage:.8f}"
        )
    if positive_volume_coverage + 1e-12 < 0.8 or positive_turnover_coverage + 1e-12 < 0.8:
        quote_errors.append(
            "HK positive-trade coverage below gate: "
            f"volume={positive_volume_coverage:.8f},turnover={positive_turnover_coverage:.8f}"
        )
    if coverage + 1e-12 < _v4_global(_v4_scope, 'float')(required_coverage_ratio):
        quote_errors.append(f"HK exact-date coverage below gate: universe={_v4_global(_v4_scope, 'len')(codes)},rows={_v4_global(_v4_scope, 'len')(rows)},coverage={coverage:.8f}")
    evidence_codes = _v4_global(_v4_scope, 'sorted')(excluded)
    evidence_codes_limited = evidence_codes[:_v4_global(_v4_scope, 'MAX_EXCLUDED_EVIDENCE')]
    evidence_reasons = {code: _v4_global(_v4_scope, 'sorted')(excluded[code]) for code in evidence_codes_limited}
    source_payload = {
        "target_date": target,
        "plates": _v4_global(_v4_scope, 'HKCONNECT_PLATE_CODES'),
        "rows": rows,
        "excluded_count": _v4_global(_v4_scope, 'len')(evidence_codes),
        "excluded_codes": evidence_codes,
        "excluded_reasons": {code: _v4_global(_v4_scope, 'sorted')(excluded[code]) for code in evidence_codes},
        "positive_volume_coverage_rate": positive_volume_coverage,
        "positive_turnover_coverage_rate": positive_turnover_coverage,
    }
    source_sha = _v4_global(_v4_scope, '_canonical_sha')(source_payload)
    security_fields = (
        "code", "name", "outstanding_shares", "circular_market_val", "listing_date",
        "lot_size", "stock_owner", "stock_child_type", "sec_status",
    )
    security_master_rows = [
        {
            field: (
                code
                if field == "code"
                else source.get(field)
                if field != "name"
                else _v4_global(_v4_scope, 'str')(
                    source.get("name") or universe.get(code) or ""
                ).strip()
            )
            for field in security_fields
        }
        for code in codes
        for source in (snapshots.get(code) or {},)
    ]
    plate_sets = [set(per_plate_codes[plate]) for plate in plates]
    acquired_at = max(
        datetime.fromisoformat(plate_responses[plate]["completed_at"].replace("Z", "+00:00"))
        for plate in plates
    ).isoformat()
    plate_response_counts = {plate: plate_responses[plate]["row_count"] for plate in plates}
    plate_response_sha256 = {plate: plate_responses[plate]["response_sha256"] for plate in plates}
    membership_source_payload = {
        "target_date": target,
        "plate_codes": {plate: per_plate_codes[plate] for plate in plates},
        "plate_response_sha256": plate_response_sha256,
        "capture_run_id": capture_run_id,
        "acquired_at": acquired_at,
    }
    sdk_capture_ref = sdk_receipt[0].name if sdk_receipt is not None else None
    sdk_capture_sha256 = hashlib.sha256(sdk_receipt[1]).hexdigest() if sdk_receipt is not None else None
    capture = {
        "schema_version": _HK_CAPTURE_V2_SCHEMA,
        "status": "READY",
        "membership_status": "READY",
        "target_date": target,
        "capture_run_id": capture_run_id,
        "capture_receipt_ref": capture_manifest_path.name if capture_manifest_path is not None else None,
        "producer_owner": producer_owner,
        "plate_responses": plate_responses,
        "plate_codes": {plate: per_plate_codes[plate] for plate in plates},
        "plate_response_counts": plate_response_counts,
        "plate_response_sha256": plate_response_sha256,
        "acquired_at": acquired_at,
        "membership_source_payload": membership_source_payload,
        "membership_source_sha256": _v4_global(_v4_scope, '_canonical_sha')(membership_source_payload),
        "overlap_count": len(plate_sets[0] & plate_sets[1]),
        "code_count": len(codes),
        "plates": list(plates),
        "codes": list(codes),
        "sdk_capture_ref": sdk_capture_ref,
        "sdk_capture_sha256": sdk_capture_sha256,
        "rows": rows,
        "security_master_rows": security_master_rows,
        "source_payload": source_payload,
        "source_sha256": source_sha,
        "quote_status": "FAILED" if quote_errors else "READY",
        "quote_errors": quote_errors,
        "panel_status": "BLOCKED_BY_QUOTE_GATE" if quote_errors else "PENDING_PANEL_GATE",
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    capture["capture_sha256"] = _v4_global(_v4_scope, '_canonical_sha')(capture)
    if capture_manifest_path is not None:
        capture_bytes = _canonical_capture_bytes(capture)
        capture_raw_sha256 = _v4_global(_v4_scope, 'hashlib').sha256(capture_bytes).hexdigest()
        write_raw_capture(capture_bytes)
        stale_codes = sorted(
            code for code in evidence_codes
            if "stale_or_missing_date" in set(excluded.get(code, ()))
        )
        write_manifest(
            _v4_global(_v4_scope, 'json').dumps(
                {
                    "schema_version": "v3.macos.research_panel_hk_capture_manifest.v1",
                    "status": "PENDING" if quote_errors else "READY",
                    "target_date": target,
                    "capture_run_id": capture_run_id,
                    "capture_relative_path": capture_raw_path.name,
                    "capture_path": capture_raw_path.name,
                    "capture": capture,
                    "capture_schema_version": _HK_CAPTURE_V2_SCHEMA,
                    "capture_sha256": capture["capture_sha256"],
                    "capture_raw_sha256": capture_raw_sha256,
                    "codes": list(capture["codes"]),
                    "plate_response_counts": plate_response_counts,
                    "plate_response_sha256": plate_response_sha256,
                    "excluded_codes": evidence_codes,
                    "stale_codes": stale_codes,
                    "quote_status": capture["quote_status"],
                    "quote_errors": quote_errors,
                    "panel_status": capture["panel_status"],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    _v4_scope["_LAST_HK_CAPTURE"] = capture
    if membership_ready_callback is not None:
        membership_ready_callback(capture)
    if snapshot_failure is not None:
        raise snapshot_failure
    if quote_errors:
        first_error = quote_errors[0]
        if first_error.startswith("HK exact-date coverage below gate:"):
            raise _v4_global(_v4_scope, 'SnapshotGateError')(first_error)
        if first_error.startswith("HK positive-trade coverage below gate:"):
            raise _v4_global(_v4_scope, 'SnapshotGateError')(first_error)
        raise _v4_global(_v4_scope, 'SnapshotGateError')(first_error)
    result = {
        "status": "READY",
        "target_date": target,
        "rows": rows,
        "universe_count": _v4_global(_v4_scope, 'len')(codes),
        "row_count": _v4_global(_v4_scope, 'len')(rows),
        "coverage_rate": coverage,
        "positive_volume_coverage_rate": positive_volume_coverage,
        "positive_turnover_coverage_rate": positive_turnover_coverage,
        "excluded_count": _v4_global(_v4_scope, 'len')(evidence_codes),
        "excluded_codes": evidence_codes_limited,
        "excluded_reasons": evidence_reasons,
        "source_sha256": source_sha,
        "sha256": source_sha,
        **_v4_global(_v4_scope, 'SAFETY_FLAGS'),
    }
    if capture_manifest_path is not None:
        result.update(
            {
                "capture_manifest_path": str(capture_manifest_path),
                "capture_raw_path": str(capture_raw_path),
                "capture_raw_sha256": capture_raw_sha256,
            }
        )
    return result
