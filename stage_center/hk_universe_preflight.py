"""Exact-date HK Connect universe preflight owned by the stage center.

The stage selector panel is A-share-only on the current Mac and is therefore
not an authority for HK Connect membership.  This module uses the local Futu
plate membership bridge instead, producing only the immutable full-market
manifest consumed by :mod:`stage_center.runner`.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo


HKCONNECT_PLATE_CODES = ("HK.GangGuTong", "HK.LIST1922")
HK_UNIVERSE_SOURCE_ROLE = "FUTU_HKCONNECT_PLATE_MEMBERSHIP"
HK_UNIVERSE_CANONICAL_COUNT = 651
HK_UNIVERSE_MIN_COUNT = HK_UNIVERSE_CANONICAL_COUNT
HK_AUTHORITY_ROLE = "HK_CONNECT_FULL_MARKET_AUTHORITY"
HK_AUTHORITY_MANIFEST_SCHEMA = "v3_shared_data.hk_connect.authority.manifest.v1"
HK_AUTHORITY_RECEIPT_SCHEMA = "v3_shared_data.hk_connect.authority.receipt.v1"
HK_AUTHORITY_CURRENT_SCHEMA = "v3_shared_data.hk_connect.authority.current.v1"
HK_CONNECT_CAPTURE_SCHEMA_V2 = "v4.manager_hk_connect_capture.v2"
HK_CONNECT_ARTIFACT_SCHEMA_V2 = "v3_shared_data.stage_universe.capture.v2"
HK_CONNECT_AUTHORITY_MANIFEST_SCHEMA_V2 = "v3_shared_data.hk_connect.authority.manifest.v2"
HK_CONNECT_AUTHORITY_RECEIPT_SCHEMA_V2 = "v3_shared_data.hk_connect.authority.receipt.v2"
HK_CONNECT_AUTHORITY_CURRENT_SCHEMA_V2 = "v3_shared_data.hk_connect.authority.current.v2"
HK_CONNECT_PUBLICATION_SCHEMA_V2 = "v3_shared_data.hk_connect.authority.publication.v2"
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_HK_CODE_RE = re.compile(r"^HK\.\d{5}$")
_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _canonical_json_line(value: Any) -> bytes:
    return _canonical_json(value) + b"\n"


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("HK authority path must be normalized relative POSIX")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("HK authority path must be normalized relative POSIX")
    if path.as_posix() != value:
        raise ValueError("HK authority path must be normalized relative POSIX")
    return value


def _resolve_under(root: Path, relative: str) -> Path:
    """Resolve one candidate path while refusing symlink/path escape."""
    _safe_relative(relative)
    root = Path(root)
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("HK authority path symlink escape")
    real_root = root.resolve()
    real_candidate = (root / relative).resolve()
    if real_candidate != real_root and real_root not in real_candidate.parents:
        raise ValueError("HK authority path escapes root")
    return root / relative


def authority_run_id(trade_date: str, artifact_sha256: str) -> str:
    """Derive a stable, path-safe run identity from date and artifact bytes."""
    target = _compact_date(trade_date)
    if len(target) != 8 or not re.fullmatch(r"[0-9a-f]{64}", str(artifact_sha256)):
        raise ValueError("HK authority run identity inputs are invalid")
    return hashlib.sha256(
        f"HK_CONNECT_FULL_MARKET:{target}:{artifact_sha256}".encode("ascii")
    ).hexdigest()[:24]


def _authority_relative_paths(trade_date: str, run_id: str) -> dict[str, str]:
    if not re.fullmatch(r"[0-9a-f]{24}", run_id):
        raise ValueError("HK authority run_id is unsafe")
    root = f"universes/{trade_date}/HK_CONNECT_FULL_MARKET.authority/{run_id}"
    return {
        "artifact_relative": f"universes/{trade_date}/HK_CONNECT_FULL_MARKET.json",
        "manifest_relative": f"{root}/manifest.json",
        "receipt_relative": f"{root}/receipt.json",
        "current_relative": f"universes/{trade_date}/HK_CONNECT_FULL_MARKET.current.json",
    }


def _atomic_create_bytes(path: Path, encoded: bytes) -> bool:
    """Exclusively publish bytes, never replacing a prior authority file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
            return True
        except FileExistsError:
            return False
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _compact_date(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _current_shanghai(now: datetime | None) -> datetime:
    current = now or datetime.now(_SHANGHAI)
    if current.tzinfo is None:
        return current.replace(tzinfo=_SHANGHAI)
    return current.astimezone(_SHANGHAI)


def _default_quote_context_factory() -> Any:
    from futu import OpenQuoteContext, ft_logger

    ft_logger.logger._console_level = logging.CRITICAL + 1
    ft_logger.logger.console_logger.setLevel(logging.CRITICAL + 1)
    ft_logger.logger.consoleHandler.setLevel(logging.CRITICAL + 1)
    return OpenQuoteContext(host="127.0.0.1", port=11111)


def _plate_rows(frame: Any, plate_code: str) -> list[Mapping[str, Any]]:
    if frame is None or not hasattr(frame, "to_dict"):
        raise ValueError(f"FUTU_PLATE_MEMBERSHIP_INCOMPLETE:{plate_code}:frame")
    try:
        rows = frame.to_dict(orient="records")
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError(f"FUTU_PLATE_MEMBERSHIP_INCOMPLETE:{plate_code}:rows") from error
    if not isinstance(rows, list):
        raise ValueError(f"FUTU_PLATE_MEMBERSHIP_INCOMPLETE:{plate_code}:rows")
    return [row for row in rows if isinstance(row, Mapping)]


def _read_existing_manifest(
    path: Path,
    trade_date: str,
    *,
    min_universe_count: int = HK_UNIVERSE_MIN_COUNT,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"existing HK universe manifest conflict: unreadable {path}") from error
    if not isinstance(payload, dict):
        raise ValueError("existing HK universe manifest conflict: payload must be an object")
    if payload.get("trade_date") != trade_date:
        raise ValueError(
            "existing HK universe trade_date conflict: "
            f"{payload.get('trade_date')!r} != {trade_date!r}"
        )
    if payload.get("market") != "HK_CONNECT" or payload.get("scope") != "FULL_MARKET":
        raise ValueError("existing HK universe manifest conflict: identity/scope mismatch")
    if payload.get("source_role") != HK_UNIVERSE_SOURCE_ROLE:
        raise ValueError("existing HK universe manifest conflict: source_role mismatch")
    if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
        raise ValueError("existing HK universe manifest conflict: safety flags must be false")
    codes = payload.get("codes")
    if (
        not isinstance(codes, list)
        or len(codes) != HK_UNIVERSE_CANONICAL_COUNT
        or len(codes) < min_universe_count
    ):
        raise ValueError("existing HK universe manifest conflict: codes invalid or below minimum")
    if any(not isinstance(code, str) or not _HK_CODE_RE.fullmatch(code) for code in codes) or len(set(codes)) != len(codes):
        raise ValueError("existing HK universe manifest conflict: codes invalid or below minimum")
    if payload.get("code_count") != len(codes) or payload.get("source_date") != trade_date:
        raise ValueError("existing HK universe manifest conflict: count/source_date mismatch")
    if payload.get("codes_sha256") != _sha256(codes):
        raise ValueError("existing HK universe manifest conflict: codes SHA mismatch")
    if raw_bytes != _canonical_json_line(payload):
        raise ValueError("existing HK universe manifest conflict: noncanonical bytes")
    plate_codes = payload.get("plate_codes")
    if not isinstance(plate_codes, Mapping) or set(plate_codes) != set(HKCONNECT_PLATE_CODES):
        raise ValueError("existing HK universe manifest conflict: plate_codes incomplete")
    normalized_plates: dict[str, list[str]] = {}
    for plate in HKCONNECT_PLATE_CODES:
        values = plate_codes.get(plate)
        if not isinstance(values, list) or not values:
            raise ValueError(f"existing HK universe manifest conflict: plate_codes invalid:{plate}")
        if any(not isinstance(code, str) or not _HK_CODE_RE.fullmatch(code) for code in values) or len(set(values)) != len(values):
            raise ValueError(f"existing HK universe manifest conflict: plate_codes invalid:{plate}")
        normalized_plates[plate] = list(values)
    if set(code for values in normalized_plates.values() for code in values) != set(codes):
        raise ValueError("existing HK universe manifest conflict: plate_codes union mismatch")
    captured_at = payload.get("captured_at")
    source_sha = payload.get("source_sha256")
    source_material = {
        "trade_date": trade_date,
        "plate_codes": {plate: normalized_plates[plate] for plate in HKCONNECT_PLATE_CODES},
        "captured_at": captured_at,
    }
    if not isinstance(captured_at, str) or not captured_at or _compact_date(captured_at) != trade_date or source_sha != _sha256(source_material):
        raise ValueError("existing HK universe manifest conflict: source SHA mismatch")
    return payload


def _atomic_create(path: Path, payload: Mapping[str, Any]) -> bool:
    """Create a fully written manifest without ever replacing an existing one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json(payload) + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
            return True
        except FileExistsError:
            return False
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _manifest_payload(
    trade_date: str,
    plate_codes: Mapping[str, list[str]],
    codes: list[str],
    captured_at: str,
) -> dict[str, Any]:
    source_material = {
        "trade_date": trade_date,
        "plate_codes": {plate: plate_codes[plate] for plate in HKCONNECT_PLATE_CODES},
        "captured_at": captured_at,
    }
    return {
        "schema_version": "v3_shared_data.stage_universe.v1",
        "trade_date": trade_date,
        "market": "HK_CONNECT",
        "scope": "FULL_MARKET",
        "codes": codes,
        "code_count": len(codes),
        "codes_sha256": _sha256(codes),
        "source_role": HK_UNIVERSE_SOURCE_ROLE,
        "source_sha256": _sha256(source_material),
        "source_date": trade_date,
        "captured_at": captured_at,
        "plate_codes": {plate: plate_codes[plate] for plate in HKCONNECT_PLATE_CODES},
        **SAFETY_FLAGS,
    }


def _authority_payloads(
    root: Path,
    trade_date: str,
    artifact_payload: Mapping[str, Any],
    *,
    source_materialization: str,
    origin_claim: str,
) -> dict[str, Any]:
    """Build the immutable manifest/receipt/current chain for one artifact."""
    artifact_path = _resolve_under(
        root, f"universes/{trade_date}/HK_CONNECT_FULL_MARKET.json"
    )
    artifact_bytes = artifact_path.read_bytes()
    artifact_sha = _sha256_bytes(artifact_bytes)
    run_id = authority_run_id(trade_date, artifact_sha)
    paths = _authority_relative_paths(trade_date, run_id)
    common = {
        "authority_role": HK_AUTHORITY_ROLE,
        "trade_date": trade_date,
        "source_date": trade_date,
        "market": "HK_CONNECT",
        "scope": "FULL_MARKET",
        "status": "READY",
        "run_id": run_id,
        "artifact_relative": paths["artifact_relative"],
        "artifact_sha256": artifact_sha,
        "artifact_size": len(artifact_bytes),
        "code_count": artifact_payload["code_count"],
        "codes_sha256": artifact_payload["codes_sha256"],
        "source_role": artifact_payload["source_role"],
        "source_sha256": artifact_payload["source_sha256"],
        "captured_at": artifact_payload["captured_at"],
        "plate_codes": artifact_payload["plate_codes"],
        "stage_selection_eligible": True,
        "source_materialization": source_materialization,
        "origin_claim": origin_claim,
        **SAFETY_FLAGS,
    }
    manifest = {
        "schema_version": HK_AUTHORITY_MANIFEST_SCHEMA,
        **common,
    }
    manifest_bytes = _canonical_json_line(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    receipt = {
        "schema_version": HK_AUTHORITY_RECEIPT_SCHEMA,
        **common,
        "manifest_relative": paths["manifest_relative"],
        "manifest_sha256": manifest_sha,
        "write_performed": True,
    }
    receipt_bytes = _canonical_json_line(receipt)
    receipt_sha = _sha256_bytes(receipt_bytes)
    current = {
        "schema_version": HK_AUTHORITY_CURRENT_SCHEMA,
        **common,
        "manifest_relative": paths["manifest_relative"],
        "receipt_relative": paths["receipt_relative"],
        "current_relative": paths["current_relative"],
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
    }
    current_bytes = _canonical_json_line(current)
    return {
        "run_id": run_id,
        "paths": paths,
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_sha256": manifest_sha,
        "receipt": receipt,
        "receipt_bytes": receipt_bytes,
        "receipt_sha256": receipt_sha,
        "current": current,
        "current_bytes": current_bytes,
        "current_sha256": _sha256_bytes(current_bytes),
        "source_materialization": source_materialization,
        "origin_claim": origin_claim,
        "artifact_sha256": artifact_sha,
        "artifact_size": len(artifact_bytes),
    }


def _complete_authority_chain(
    root: Path,
    trade_date: str,
    artifact_payload: Mapping[str, Any],
    *,
    source_materialization: str,
    origin_claim: str,
) -> dict[str, Any]:
    chain = _authority_payloads(
        root,
        trade_date,
        artifact_payload,
        source_materialization=source_materialization,
        origin_claim=origin_claim,
    )
    paths = chain["paths"]
    absolute = {
        name: _resolve_under(root, relative)
        for name, relative in paths.items()
        if name != "artifact_relative"
    }
    expected = {
        "manifest_relative": chain["manifest_bytes"],
        "receipt_relative": chain["receipt_bytes"],
        "current_relative": chain["current_bytes"],
    }
    present = {name: absolute[name].exists() for name in expected}
    if any(present.values()):
        if not all(present.values()):
            raise ValueError("HK authority chain conflict: partial or differing authority")
        actual_payloads: dict[str, dict[str, Any]] = {}
        for name, encoded in expected.items():
            raw = absolute[name].read_bytes()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("HK authority chain conflict: authority is unreadable") from exc
            if not isinstance(payload, dict) or raw != _canonical_json_line(payload):
                raise ValueError("HK authority chain conflict: authority is noncanonical")
            actual_payloads[name] = payload
            if raw == encoded:
                continue
            expected_payload = json.loads(encoded.decode("utf-8"))
            actual_without_materialization = dict(payload)
            expected_without_materialization = dict(expected_payload)
            actual_without_materialization.pop("source_materialization", None)
            expected_without_materialization.pop("source_materialization", None)
            if name == "receipt_relative":
                actual_without_materialization.pop("manifest_sha256", None)
                expected_without_materialization.pop("manifest_sha256", None)
            if name == "current_relative":
                actual_without_materialization.pop("manifest_sha256", None)
                actual_without_materialization.pop("receipt_sha256", None)
                expected_without_materialization.pop("manifest_sha256", None)
                expected_without_materialization.pop("receipt_sha256", None)
            if actual_without_materialization != expected_without_materialization:
                raise ValueError("HK authority chain conflict: partial or differing authority")
            if payload.get("source_materialization") not in {
                "FRESH_FUTU_ARTIFACT",
                "VERIFIED_EXISTING_ARTIFACT_CHAIN_COMPLETION",
            }:
                raise ValueError("HK authority chain conflict: source materialization mismatch")
            if payload.get("origin_claim") != "NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT":
                raise ValueError("HK authority chain conflict: origin claim mismatch")
        actual_manifest = actual_payloads["manifest_relative"]
        actual_receipt = actual_payloads["receipt_relative"]
        actual_current = actual_payloads["current_relative"]
        if (
            actual_receipt.get("manifest_sha256") != _sha256_bytes(absolute["manifest_relative"].read_bytes())
            or actual_current.get("manifest_sha256") != actual_receipt.get("manifest_sha256")
            or actual_current.get("receipt_sha256") != _sha256_bytes(absolute["receipt_relative"].read_bytes())
            or actual_current.get("run_id") != chain["run_id"]
        ):
            raise ValueError("HK authority chain conflict: SHA bindings mismatch")
        chain["manifest"] = actual_manifest
        chain["manifest_bytes"] = absolute["manifest_relative"].read_bytes()
        chain["manifest_sha256"] = _sha256_bytes(chain["manifest_bytes"])
        chain["receipt"] = actual_receipt
        chain["receipt_bytes"] = absolute["receipt_relative"].read_bytes()
        chain["receipt_sha256"] = _sha256_bytes(chain["receipt_bytes"])
        chain["current"] = actual_current
        chain["current_bytes"] = absolute["current_relative"].read_bytes()
        chain["current_sha256"] = _sha256_bytes(chain["current_bytes"])
        chain["source_materialization"] = actual_current["source_materialization"]
        chain["write_performed"] = False
        chain["status"] = "NOOP_ALREADY_VERIFIED"
        return chain

    for name in ("manifest_relative", "receipt_relative", "current_relative"):
        if not _atomic_create_bytes(absolute[name], expected[name]):
            raise ValueError("HK authority chain conflict: exclusive create lost")
    chain["write_performed"] = True
    chain["status"] = "READY_CHAIN_COMPLETED"
    return chain


def ensure_hk_connect_universe(
    store_root: Path | str,
    trade_date: str,
    *,
    now: datetime | None = None,
    quote_context_factory: Callable[[], Any] | None = None,
    min_universe_count: int = HK_UNIVERSE_MIN_COUNT,
) -> dict[str, Any]:
    """Ensure today's Futu-derived HK Connect full-market manifest exists.

    ``quote_context_factory`` and ``now`` are explicit test seams.  No prior
    date is accepted and no existing manifest is overwritten.
    """
    target = _compact_date(trade_date)
    if len(target) != 8:
        raise ValueError("invalid trade date")
    current = _current_shanghai(now)
    if target != current.strftime("%Y%m%d"):
        raise ValueError("Futu HK universe collection is restricted to the current trade date")
    minimum = int(min_universe_count)
    if minimum != HK_UNIVERSE_CANONICAL_COUNT:
        raise ValueError(
            f"HK universe minimum must equal canonical {HK_UNIVERSE_CANONICAL_COUNT}"
        )

    root = Path(store_root).expanduser()
    path = _resolve_under(
        root, f"universes/{target}/HK_CONNECT_FULL_MARKET.json"
    )
    existing = _read_existing_manifest(path, target, min_universe_count=minimum)
    if existing is not None:
        authority = _complete_authority_chain(
            root,
            target,
            existing,
            source_materialization="VERIFIED_EXISTING_ARTIFACT_CHAIN_COMPLETION",
            origin_claim="NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT",
        )
        return {
            "ok": True,
            "status": authority["status"],
            "trade_date": target,
            "manifest": str(path),
            "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "artifact_sha256": authority["artifact_sha256"],
            "code_count": existing["code_count"],
            "write_performed": authority["write_performed"],
            "authority": authority,
            **SAFETY_FLAGS,
        }

    context = (quote_context_factory or _default_quote_context_factory)()
    context_error: Exception | None = None
    try:
        plate_codes: dict[str, list[str]] = {}
        try:
            for plate_code in HKCONNECT_PLATE_CODES:
                try:
                    return_code, frame = context.get_plate_stock(plate_code)
                except Exception as error:
                    raise RuntimeError(f"FUTU_GET_PLATE_STOCK_FAILED:{plate_code}:{error}") from error
                if return_code != 0:
                    raise RuntimeError(f"FUTU_GET_PLATE_STOCK_FAILED:{plate_code}:{frame}")
                codes: set[str] = set()
                for row in _plate_rows(frame, plate_code):
                    code = str(row.get("code") or "").strip().upper()
                    if _HK_CODE_RE.fullmatch(code):
                        codes.add(code)
                if not codes:
                    raise ValueError(f"FUTU plate membership incomplete: {plate_code}")
                plate_codes[plate_code] = sorted(codes)
        except Exception as error:
            context_error = error
            raise
    finally:
        try:
            context.close()
        except Exception as error:
            if context_error is None:
                raise RuntimeError(f"FUTU_CONTEXT_CLOSE_FAILED:{error}") from error

    codes = sorted({code for values in plate_codes.values() for code in values})
    if len(codes) != HK_UNIVERSE_CANONICAL_COUNT:
        raise ValueError(
            "HK Connect plate membership must equal canonical count: "
            f"{len(codes)} != {HK_UNIVERSE_CANONICAL_COUNT}"
        )
    captured_at = current.isoformat(timespec="seconds")
    payload = _manifest_payload(target, plate_codes, codes, captured_at)
    if _atomic_create(path, payload):
        digest = hashlib.sha256((path).read_bytes()).hexdigest()
        authority = _complete_authority_chain(
            root,
            target,
            payload,
            source_materialization="FRESH_FUTU_ARTIFACT",
            origin_claim="NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT",
        )
        return {
            "ok": True,
            "status": "READY",
            "trade_date": target,
            "manifest": str(path),
            "manifest_sha256": digest,
            "artifact_sha256": authority["artifact_sha256"],
            "code_count": len(codes),
            "write_performed": True,
            "authority": authority,
            **SAFETY_FLAGS,
        }

    # Another same-date writer won the exclusive create.  Reuse only if its
    # complete manifest is byte-equivalent; a differing payload is a conflict.
    existing = _read_existing_manifest(path, target, min_universe_count=minimum)
    assert existing is not None
    if path.read_bytes() != _canonical_json_line(payload):
        raise ValueError("existing HK universe manifest conflict: evidence differs")
    authority = _complete_authority_chain(
        root,
        target,
        existing,
        source_materialization="VERIFIED_EXISTING_ARTIFACT_CHAIN_COMPLETION",
        origin_claim="NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT",
    )
    encoded_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "ok": True,
        "status": authority["status"],
        "trade_date": target,
        "manifest": str(path),
        "manifest_sha256": encoded_digest,
        "code_count": len(codes),
        "artifact_sha256": authority["artifact_sha256"],
        "write_performed": authority["write_performed"],
        "authority": authority,
        **SAFETY_FLAGS,
    }


def validate_captured_hk_connect_membership_v2(
    capture: Mapping[str, Any], *, trade_date: str | None = None
) -> dict[str, Any]:
    """Validate and derive membership from the two complete retained SDK frames.

    This helper is deliberately pure: it does not discover paths, read files,
    schedule work, call Futu, inspect quotes, or choose a data root.
    """
    if not isinstance(capture, Mapping):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:envelope")
    target = trade_date or capture.get("target_date")
    if not isinstance(target, str) or not re.fullmatch(r"\d{8}", target):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:trade_date")
    try:
        datetime.strptime(target, "%Y%m%d")
    except ValueError as error:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:trade_date") from error
    if capture.get("schema_version") != HK_CONNECT_CAPTURE_SCHEMA_V2:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:schema")
    if capture.get("status") != "READY" or capture.get("target_date") != target:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:status_or_date")
    if any(capture.get(flag) is not False for flag in SAFETY_FLAGS):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:safety")
    capture_run_id = capture.get("capture_run_id")
    if not isinstance(capture_run_id, str) or not capture_run_id.strip():
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:capture_run_id")
    producer = capture.get("producer_owner")
    if not isinstance(producer, Mapping):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:producer_owner")
    if producer.get("workload_id") != "v35_dispatcher.research_panel_daily_hk":
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:producer_workload")
    if producer.get("code_ref") != "ops/_macos_research_panel_daily_parts/hk_market_capture.py":
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:producer_code_ref")
    if not isinstance(producer.get("code_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", producer["code_sha256"]):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:producer_code_sha")
    forward_set = producer.get("forward_source_set")
    if not isinstance(forward_set, Mapping):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:forward_source_set")
    forward_required = {
        "source_head", "forward_receipt_sha256", "candidate_manifest_sha256",
        "candidate_build_receipt_sha256", "api_writer_receipt_sha256",
        "api_reviewer_receipt_sha256", "api_source_mapping_sha256",
    }
    if set(forward_set) != forward_required:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:forward_source_set_fields")
    if not isinstance(forward_set.get("source_head"), str) or not re.fullmatch(r"[0-9a-f]{40}", forward_set["source_head"]):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:forward_source_head")
    for key in forward_required - {"source_head"}:
        if not isinstance(forward_set.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", forward_set[key]):
            raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:forward_source_sha")
    forward_sha = _sha256(dict(forward_set))
    if producer.get("forward_source_set_sha256") != forward_sha:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:forward_source_set_sha")

    responses = capture.get("plate_responses")
    if not isinstance(responses, Mapping) or set(responses) != set(HKCONNECT_PLATE_CODES):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:plate_responses")
    expected_plates: dict[str, list[str]] = {}
    response_counts: dict[str, int] = {}
    response_shas: dict[str, str] = {}
    completed: list[datetime] = []
    for plate in HKCONNECT_PLATE_CODES:
        response = responses.get(plate)
        if not isinstance(response, Mapping) or response.get("requested_plate") != plate:
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:plate:{plate}")
        if type(response.get("return_code")) is not int or response["return_code"] != 0:
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:return_code:{plate}")
        if response.get("serialization_version") != "futu.dataframe.records.canonical-json.v1":
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:serialization:{plate}")
        columns = response.get("columns")
        records = response.get("rows")
        if (not isinstance(columns, list) or any(not isinstance(column, str) for column in columns)
            or len(columns) != len(set(columns)) or "code" not in columns
            or not isinstance(records, list) or not records):
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:frame:{plate}")
        if type(response.get("row_count")) is not int or response["row_count"] != len(records):
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:row_count:{plate}")
        requested_at = response.get("requested_at")
        completed_at = response.get("completed_at")
        try:
            requested_dt = datetime.fromisoformat(str(requested_at).replace("Z", "+00:00"))
            completed_dt = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:time:{plate}") from error
        if requested_dt.tzinfo is None or completed_dt.tzinfo is None or completed_dt < requested_dt:
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:time:{plate}")
        completed.append(completed_dt)
        response_material = {
            "requested_plate": plate,
            "serialization_version": response["serialization_version"],
            "columns": columns,
            "rows": records,
        }
        response_sha = _sha256(response_material)
        if response.get("response_sha256") != response_sha:
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:response_sha:{plate}")
        values: set[str] = set()
        for row in records:
            if not isinstance(row, Mapping) or set(row) != set(columns):
                raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:row:{plate}")
            code = row.get("code")
            if not isinstance(code, str) or not _HK_CODE_RE.fullmatch(code):
                raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:code:{plate}")
            values.add(code)
        if not values:
            raise ValueError(f"HK_CONNECT_CAPTURE_V2_INVALID:empty_plate:{plate}")
        expected_plates[plate] = sorted(values)
        response_counts[plate] = len(records)
        response_shas[plate] = response_sha

    acquired_at = max(completed).isoformat()
    if capture.get("acquired_at") != acquired_at:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:acquired_at")
    if capture.get("plate_codes") != expected_plates:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:plate_codes")
    if capture.get("plate_response_counts") != response_counts:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:plate_response_counts")
    if capture.get("plate_response_sha256") != response_shas:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:plate_response_sha256")
    plate_sets = [set(expected_plates[plate]) for plate in HKCONNECT_PLATE_CODES]
    union = sorted(plate_sets[0] | plate_sets[1])
    overlap = len(plate_sets[0] & plate_sets[1])
    if capture.get("codes") != union or capture.get("code_count") != len(union):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:membership_union")
    if type(capture.get("overlap_count")) is not int or capture["overlap_count"] != overlap:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:membership_overlap")
    if len(union) != len(expected_plates[HKCONNECT_PLATE_CODES[0]]) + len(expected_plates[HKCONNECT_PLATE_CODES[1]]) - overlap:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:membership_identity")

    source_material = {
        "target_date": target,
        "plate_codes": expected_plates,
        "plate_response_sha256": response_shas,
        "capture_run_id": capture_run_id,
        "acquired_at": acquired_at,
    }
    source_sha = _sha256(source_material)
    if capture.get("membership_source_payload") != source_material or capture.get("membership_source_sha256") != source_sha:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:membership_source_sha")
    capture_sha = capture.get("capture_sha256")
    if not isinstance(capture_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", capture_sha):
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:capture_sha")
    capture_material = dict(capture)
    capture_material.pop("capture_sha256", None)
    if _sha256(capture_material) != capture_sha:
        raise ValueError("HK_CONNECT_CAPTURE_V2_INVALID:capture_sha")
    return {
        "trade_date": target,
        "codes": union,
        "code_count": len(union),
        "overlap_count": overlap,
        "plate_codes": expected_plates,
        "plate_response_counts": response_counts,
        "plate_response_sha256": response_shas,
        "capture_run_id": capture_run_id,
        "capture_sha256": capture_sha,
        "acquired_at": acquired_at,
        "source_payload": source_material,
        "source_sha256": source_sha,
        "producer_owner": dict(producer),
    }


def build_captured_hk_connect_authority_v2(
    capture: Mapping[str, Any], *, trade_date: str,
    producer_owner: Mapping[str, Any], contract_owner: Mapping[str, Any],
) -> dict[str, Any]:
    """Purely serialize a validated captured-input authority and its v2 chain."""
    validated = validate_captured_hk_connect_membership_v2(capture, trade_date=trade_date)
    if dict(producer_owner) != validated["producer_owner"]:
        raise ValueError("HK_CONNECT_AUTHORITY_V2_INVALID:producer_owner_mismatch")
    if (not isinstance(contract_owner, Mapping)
        or contract_owner.get("code_ref") != "stage_center/hk_universe_preflight.py"
        or not isinstance(contract_owner.get("code_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", contract_owner["code_sha256"])):
        raise ValueError("HK_CONNECT_AUTHORITY_V2_INVALID:contract_owner")
    target = validated["trade_date"]
    codes = validated["codes"]
    artifact_payload = {
        "schema_version": HK_CONNECT_ARTIFACT_SCHEMA_V2,
        "target_date": target,
        "effective_date": target,
        "trade_date": target,
        "source_date": target,
        "market": "HK_CONNECT",
        "scope": "FULL_MARKET",
        "codes": codes,
        "code_count": len(codes),
        "codes_sha256": _sha256(codes),
        "overlap_count": validated["overlap_count"],
        "source_role": HK_UNIVERSE_SOURCE_ROLE,
        "source_sha256": validated["source_sha256"],
        "plate_codes": validated["plate_codes"],
        "plate_response_counts": validated["plate_response_counts"],
        "plate_response_sha256": validated["plate_response_sha256"],
        "capture_run_id": validated["capture_run_id"],
        "capture_sha256": validated["capture_sha256"],
        "acquired_at": validated["acquired_at"],
        "producer_owner": dict(producer_owner),
        "contract_owner": dict(contract_owner),
        **SAFETY_FLAGS,
    }
    artifact_bytes = _canonical_json_line(artifact_payload)
    artifact_sha = _sha256_bytes(artifact_bytes)
    run_id = authority_run_id(target, artifact_sha)
    paths = _authority_relative_paths(target, run_id)
    base = f"universes/{target}/HK_CONNECT_FULL_MARKET.authority/{run_id}"
    capture_relative = f"{base}/capture.json"
    publication_relative = f"{base}/publication.json"
    common = {
        "authority_role": HK_AUTHORITY_ROLE,
        "target_date": target,
        "effective_date": target,
        "trade_date": target,
        "source_date": target,
        "market": "HK_CONNECT",
        "scope": "FULL_MARKET",
        "status": "READY",
        "run_id": run_id,
        "artifact_relative": paths["artifact_relative"],
        "artifact_sha256": artifact_sha,
        "artifact_size": len(artifact_bytes),
        "code_count": len(codes),
        "codes_sha256": artifact_payload["codes_sha256"],
        "source_role": HK_UNIVERSE_SOURCE_ROLE,
        "source_sha256": validated["source_sha256"],
        "plate_codes": validated["plate_codes"],
        "plate_response_counts": validated["plate_response_counts"],
        "plate_response_sha256": validated["plate_response_sha256"],
        "capture_run_id": validated["capture_run_id"],
        "capture_sha256": validated["capture_sha256"],
        "capture_relative": capture_relative,
        "publication_relative": publication_relative,
        "acquired_at": validated["acquired_at"],
        "producer_owner": dict(producer_owner),
        "contract_owner": dict(contract_owner),
        "stage_selection_eligible": True,
        "source_materialization": "FRESH_FUTU_CAPTURED_INPUT",
        "origin_claim": "SAME_JOB_CAPTURE_AND_PUBLICATION",
        **SAFETY_FLAGS,
    }
    manifest = {"schema_version": HK_CONNECT_AUTHORITY_MANIFEST_SCHEMA_V2, **common}
    manifest_bytes = _canonical_json_line(manifest)
    manifest_sha = _sha256_bytes(manifest_bytes)
    receipt = {
        "schema_version": HK_CONNECT_AUTHORITY_RECEIPT_SCHEMA_V2,
        **common,
        "manifest_relative": paths["manifest_relative"],
        "manifest_sha256": manifest_sha,
        "write_performed": True,
    }
    receipt_bytes = _canonical_json_line(receipt)
    receipt_sha = _sha256_bytes(receipt_bytes)
    current = {
        "schema_version": HK_CONNECT_AUTHORITY_CURRENT_SCHEMA_V2,
        **common,
        "manifest_relative": paths["manifest_relative"],
        "receipt_relative": paths["receipt_relative"],
        "current_relative": paths["current_relative"],
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
    }
    current_bytes = _canonical_json_line(current)
    capture_bytes = _canonical_json_line(dict(capture))
    return {
        "run_id": run_id,
        "paths": paths,
        "capture_relative": capture_relative,
        "publication_relative": publication_relative,
        "artifact_payload": artifact_payload,
        "artifact_bytes": artifact_bytes,
        "artifact_sha256": artifact_sha,
        "capture_bytes": capture_bytes,
        "manifest": manifest,
        "manifest_bytes": manifest_bytes,
        "manifest_sha256": manifest_sha,
        "receipt": receipt,
        "receipt_bytes": receipt_bytes,
        "receipt_sha256": receipt_sha,
        "current": current,
        "current_bytes": current_bytes,
        "current_sha256": _sha256_bytes(current_bytes),
    }


__all__ = [
    "HKCONNECT_PLATE_CODES",
    "HK_UNIVERSE_SOURCE_ROLE",
    "HK_UNIVERSE_CANONICAL_COUNT",
    "HK_AUTHORITY_MANIFEST_SCHEMA",
    "HK_AUTHORITY_RECEIPT_SCHEMA",
    "HK_AUTHORITY_CURRENT_SCHEMA",
    "authority_run_id",
    "ensure_hk_connect_universe",
    "validate_captured_hk_connect_membership_v2",
    "build_captured_hk_connect_authority_v2",
]
