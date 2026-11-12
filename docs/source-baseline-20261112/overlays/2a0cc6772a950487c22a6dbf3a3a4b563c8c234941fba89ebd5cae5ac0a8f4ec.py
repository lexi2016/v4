"""Exact-date HK Connect universe preflight owned by the stage center.

The stage selector panel is A-share-only on the current Mac and is therefore
not an authority for HK Connect membership.  This module uses the local Futu
plate membership bridge instead, producing only the immutable full-market
manifest consumed by :mod:`stage_center.runner`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo


HKCONNECT_PLATE_CODES = ("HK.GangGuTong", "HK.LIST1922")
HK_UNIVERSE_SOURCE_ROLE = "FUTU_HKCONNECT_PLATE_MEMBERSHIP"
HK_UNIVERSE_MIN_COUNT = 600
HK_AUTHORITY_ROLE = "HK_CONNECT_FULL_MARKET_AUTHORITY"
HK_AUTHORITY_MANIFEST_SCHEMA = "v3_shared_data.hk_connect.authority.manifest.v1"
HK_AUTHORITY_RECEIPT_SCHEMA = "v3_shared_data.hk_connect.authority.receipt.v1"
HK_AUTHORITY_CURRENT_SCHEMA = "v3_shared_data.hk_connect.authority.current.v1"
MANUAL_RECOVERY_SOURCE_MATERIALIZATION = "MANUAL_RECOVERY"
MANUAL_RECOVERY_ORIGIN_CLAIM = "MANUAL_RECOVERY_NON_NATURAL"
MANUAL_RECOVERY_EVIDENCE_ROOT = "evidence/hk_connect/manual_recovery"
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
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"FUTU_PLATE_MEMBERSHIP_INCOMPLETE:{plate_code}:row_type")
    return list(rows)


def _validate_hk_codes(
    values: Any,
    *,
    label: str,
    minimum: int,
) -> list[str]:
    if not isinstance(values, list) or len(values) < minimum:
        raise ValueError(f"{label} must contain at least {minimum} HK codes")
    if any(not isinstance(code, str) or not _HK_CODE_RE.fullmatch(code) for code in values):
        raise ValueError(f"{label} contains an invalid HK code")
    if len(set(values)) != len(values):
        raise ValueError(f"{label} contains duplicate HK codes")
    return list(values)


def _validate_plate_evidence(
    plate_codes: Any,
    codes: list[str],
    *,
    label: str,
) -> dict[str, list[str]]:
    if not isinstance(plate_codes, Mapping) or set(plate_codes) != set(HKCONNECT_PLATE_CODES):
        raise ValueError(f"{label} plate_codes must contain exactly the two HK Connect plates")
    normalized = {
        plate: _validate_hk_codes(
            plate_codes.get(plate),
            label=f"{label} plate {plate}",
            minimum=1,
        )
        for plate in HKCONNECT_PLATE_CODES
    }
    if set(code for values in normalized.values() for code in values) != set(codes):
        raise ValueError(f"{label} plate union mismatch")
    return normalized


def _load_shared_universe_reader() -> Callable[..., Any]:
    """Load the existing strict shared-data reader from this release only."""
    from stage_center.live_collectors import _load_shared_module

    package_root = Path(__file__).resolve().parents[1] / "upstreams" / "v3_shared_data"
    module = _load_shared_module(package_root, "scripts.live_acquisition.universe")
    reader = getattr(module, "resolve_stage_universe", None)
    if not callable(reader):
        raise ValueError("shared HK authority reader is unavailable")
    return reader


def _validate_official_evidence(
    path: Path | str,
    *,
    expected_sha256: str,
    official_url: str,
    notice_date: str,
    effective_date: str,
    delta_codes: list[str],
) -> dict[str, Any]:
    evidence_path = Path(path).expanduser()
    if not evidence_path.is_file():
        raise ValueError(f"official evidence file is missing: {evidence_path}")
    try:
        raw = evidence_path.read_bytes()
    except OSError as error:
        raise ValueError(f"official evidence file is unreadable: {evidence_path}") from error
    actual_sha256 = _sha256_bytes(raw)
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha256)):
        raise ValueError("official evidence SHA256 is invalid")
    if actual_sha256 != expected_sha256:
        raise ValueError("official evidence SHA256 mismatch")
    if not isinstance(official_url, str) or not re.fullmatch(
        r"https://(?:www\.)?sse\.com\.cn(?:/.*)?", official_url
    ):
        raise ValueError("official evidence URL must be an SSE HTTPS URL")
    compact_notice = _compact_date(notice_date)
    compact_effective = _compact_date(effective_date)
    if len(compact_notice) != 8 or len(compact_effective) != 8:
        raise ValueError("official evidence dates are invalid")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("official evidence must be UTF-8 text") from error
    try:
        structured = json.loads(text)
    except ValueError:
        structured = None
    if isinstance(structured, Mapping):
        declared_url = structured.get("official_url", structured.get("url"))
        if declared_url is not None and declared_url != official_url:
            raise ValueError("official evidence URL mismatch")
        if _compact_date(structured.get("notice_date")) != compact_notice:
            raise ValueError("official evidence notice date mismatch")
        if _compact_date(structured.get("effective_date")) != compact_effective:
            raise ValueError("official evidence effective date mismatch")
        declared_delta = structured.get("added_codes", structured.get("delta_codes"))
        if declared_delta is not None and list(declared_delta) != delta_codes:
            raise ValueError("official evidence delta mismatch")
    date_text = re.sub(r"[^0-9]", "", text)
    if compact_notice not in date_text or compact_effective not in date_text:
        raise ValueError("official evidence does not state the supplied dates")
    if any(code not in text for code in delta_codes):
        raise ValueError("official evidence does not state the supplied delta")
    return {
        "_raw_bytes": raw,
        "sha256": actual_sha256,
        "url": official_url,
        "notice_date": compact_notice,
        "effective_date": compact_effective,
        "delta_codes": list(delta_codes),
    }


def _materialize_official_evidence(
    root: Path,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Copy validated evidence into the authority store before publishing lineage."""
    raw = evidence.pop("_raw_bytes", None)
    digest = evidence.get("sha256")
    if not isinstance(raw, bytes) or not isinstance(digest, str):
        raise ValueError("official evidence bytes are unavailable")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("official evidence SHA256 is invalid")
    relative = f"{MANUAL_RECOVERY_EVIDENCE_ROOT}/{digest}.evidence"
    destination = _resolve_under(root, relative)
    if destination.exists():
        try:
            existing = destination.read_bytes()
        except OSError as error:
            raise ValueError("official evidence store copy is unreadable") from error
        if existing != raw:
            raise ValueError("official evidence store copy conflicts")
    elif not _atomic_create_bytes(destination, raw):
        try:
            existing = destination.read_bytes()
        except OSError as error:
            raise ValueError("official evidence store copy was not created") from error
        if existing != raw:
            raise ValueError("official evidence store copy conflicts")
    return {"path": relative, **evidence}


def _validate_delta_codes(values: Any) -> list[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError("manual recovery delta_codes must be a list")
    normalized = _validate_hk_codes(
        list(values),
        label="manual recovery delta_codes",
        minimum=1,
    )
    if len(normalized) != 1:
        raise ValueError("manual recovery requires exactly one explicit delta code")
    return normalized


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
    if payload.get("schema_version") != "v3_shared_data.stage_universe.v1":
        raise ValueError("existing HK universe manifest conflict: schema mismatch")
    if payload.get("source_role") != HK_UNIVERSE_SOURCE_ROLE:
        raise ValueError("existing HK universe manifest conflict: source_role mismatch")
    if any(payload.get(flag) is not False for flag in SAFETY_FLAGS):
        raise ValueError("existing HK universe manifest conflict: safety flags must be false")
    codes = _validate_hk_codes(
        payload.get("codes"),
        label="existing HK universe manifest conflict: codes",
        minimum=min_universe_count,
    )
    code_count = payload.get("code_count")
    if (
        isinstance(code_count, bool)
        or not isinstance(code_count, int)
        or code_count != len(codes)
        or payload.get("source_date") != trade_date
    ):
        raise ValueError("existing HK universe manifest conflict: count/source_date mismatch")
    if payload.get("codes_sha256") != _sha256(codes):
        raise ValueError("existing HK universe manifest conflict: codes SHA mismatch")
    if raw_bytes != _canonical_json_line(payload):
        raise ValueError("existing HK universe manifest conflict: noncanonical bytes")
    normalized_plates = _validate_plate_evidence(
        payload.get("plate_codes"),
        codes,
        label="existing HK universe manifest conflict",
    )
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
    *,
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source_material = {
        "trade_date": trade_date,
        "plate_codes": {plate: plate_codes[plate] for plate in HKCONNECT_PLATE_CODES},
        "captured_at": captured_at,
    }
    payload = {
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
    if extra_fields:
        payload.update(extra_fields)
    return payload


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
    for key in (
        "plate_codes_sha256",
        "recovery_lineage",
        "natural_verified",
        "recovered_at",
        "corroborated_at",
    ):
        if key in artifact_payload:
            common[key] = artifact_payload[key]
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
            if source_materialization == MANUAL_RECOVERY_SOURCE_MATERIALIZATION:
                for name, encoded in expected.items():
                    if absolute[name].exists():
                        if absolute[name].read_bytes() != encoded:
                            raise ValueError(
                                "HK authority chain conflict: partial or differing authority"
                            )
                for name, encoded in expected.items():
                    if absolute[name].exists():
                        continue
                    if not _atomic_create_bytes(absolute[name], encoded):
                        try:
                            existing = absolute[name].read_bytes()
                        except OSError as error:
                            raise ValueError(
                                "HK authority chain conflict: exclusive create lost"
                            ) from error
                        if existing != encoded:
                            raise ValueError(
                                "HK authority chain conflict: partial or differing authority"
                            )
                chain["write_performed"] = True
                chain["status"] = "READY_CHAIN_COMPLETED"
                return chain
            raise ValueError("HK authority chain conflict: partial or differing authority")
        if source_materialization == MANUAL_RECOVERY_SOURCE_MATERIALIZATION:
            for name, encoded in expected.items():
                try:
                    actual = absolute[name].read_bytes()
                except OSError as error:
                    raise ValueError("HK authority chain conflict: authority is unreadable") from error
                if actual != encoded:
                    raise ValueError("HK authority chain conflict: differing authority")
            chain["write_performed"] = False
            chain["status"] = "NOOP_ALREADY_VERIFIED"
            return chain
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


def recover_hk_connect_universe(
    store_root: Path | str,
    trade_date: str,
    *,
    parent_trade_date: str,
    parent_artifact_sha256: str,
    parent_codes_sha256: str,
    official_evidence_path: Path | str,
    official_evidence_sha256: str,
    official_evidence_url: str,
    notice_date: str,
    effective_date: str,
    delta_codes: Sequence[str],
    now: datetime | None = None,
    quote_context_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """Publish one explicit, non-natural recovery authority chain.

    Recovery is intentionally a separate entry point from the normal Futu
    preflight.  It proves one verified parent authority, one official
    evidence file, and one live corroboration from both existing Futu plates;
    it never changes the parent artifact or treats a replay as natural.
    """
    target = _compact_date(trade_date)
    parent_target = _compact_date(parent_trade_date)
    effective_target = _compact_date(effective_date)
    if len(target) != 8 or len(parent_target) != 8 or len(effective_target) != 8:
        raise ValueError("manual recovery dates are invalid")
    try:
        target_day = datetime.strptime(target, "%Y%m%d")
        parent_day = datetime.strptime(parent_target, "%Y%m%d")
        datetime.strptime(effective_target, "%Y%m%d")
    except ValueError as error:
        raise ValueError("manual recovery dates are invalid") from error
    if parent_day >= target_day:
        raise ValueError("manual recovery parent date must be earlier than target")
    if target == parent_target or effective_target != target:
        raise ValueError("manual recovery target/effective date mismatch")
    delta = _validate_delta_codes(delta_codes)
    if not re.fullmatch(r"[0-9a-f]{64}", str(parent_artifact_sha256)):
        raise ValueError("manual recovery parent artifact SHA256 is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(parent_codes_sha256)):
        raise ValueError("manual recovery parent codes SHA256 is invalid")

    root = Path(store_root).expanduser()
    reader = _load_shared_universe_reader()
    try:
        parent = reader(root, parent_target, "HK_CONNECT")
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise ValueError("manual recovery parent authority is not verified") from error
    expected_parent_path = _resolve_under(
        root, f"universes/{parent_target}/HK_CONNECT_FULL_MARKET.json"
    )
    actual_parent_sha256 = _sha256_bytes(parent.path.read_bytes())
    if (
        parent.path != expected_parent_path
        or actual_parent_sha256 != parent_artifact_sha256
        or parent.codes_sha256 != parent_codes_sha256
    ):
        raise ValueError("manual recovery parent authority binding mismatch")
    if delta[0] in set(parent.codes):
        raise ValueError("manual recovery delta must not already be in parent authority")

    path = _resolve_under(root, f"universes/{target}/HK_CONNECT_FULL_MARKET.json")
    existing_artifact_payload: dict[str, Any] | None = None
    if path.exists():
        try:
            existing_bytes = path.read_bytes()
            existing_payload = json.loads(existing_bytes.decode("utf-8"))
        except (OSError, UnicodeError, ValueError) as error:
            raise ValueError("manual recovery target artifact conflict") from error
        if (
            not isinstance(existing_payload, dict)
            or existing_bytes != _canonical_json_line(existing_payload)
            or not isinstance(existing_payload.get("captured_at"), str)
            or not existing_payload.get("captured_at")
        ):
            raise ValueError("manual recovery target artifact conflict")
        existing_artifact_payload = existing_payload

    current = _current_shanghai(now)
    captured_at = (
        existing_artifact_payload.get("captured_at")
        if existing_artifact_payload is not None
        else current.isoformat(timespec="seconds")
    )
    official = _validate_official_evidence(
        official_evidence_path,
        expected_sha256=official_evidence_sha256,
        official_url=official_evidence_url,
        notice_date=notice_date,
        effective_date=effective_target,
        delta_codes=delta,
    )
    official = _materialize_official_evidence(root, official)

    context = (quote_context_factory or _default_quote_context_factory)()
    context_error: Exception | None = None
    try:
        plate_codes: dict[str, list[str]] = {}
        try:
            for plate_code in HKCONNECT_PLATE_CODES:
                try:
                    return_code, frame = context.get_plate_stock(plate_code)
                except Exception as error:
                    raise RuntimeError(
                        f"FUTU_GET_PLATE_STOCK_FAILED:{plate_code}:{error}"
                    ) from error
                if return_code != 0:
                    raise RuntimeError(
                        f"FUTU_GET_PLATE_STOCK_FAILED:{plate_code}:{frame}"
                    )
                codes: list[str] = []
                for row in _plate_rows(frame, plate_code):
                    raw_code = row.get("code")
                    code = raw_code.strip().upper() if isinstance(raw_code, str) else ""
                    if not _HK_CODE_RE.fullmatch(code):
                        raise ValueError(
                            f"FUTU plate membership invalid code: {plate_code}"
                        )
                    if code in codes:
                        raise ValueError(
                            f"FUTU plate membership duplicate code: {plate_code}:{code}"
                        )
                    codes.append(code)
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

    expected_codes = set(parent.codes).union(delta)
    if plate_codes[HKCONNECT_PLATE_CODES[0]] != plate_codes[HKCONNECT_PLATE_CODES[1]]:
        raise ValueError("manual recovery Futu plate captures are not equal")
    if set(plate_codes[HKCONNECT_PLATE_CODES[0]]) != expected_codes:
        raise ValueError("manual recovery Futu plates do not equal parent plus delta")
    codes = sorted(expected_codes)
    if len(codes) < HK_UNIVERSE_MIN_COUNT:
        raise ValueError("manual recovery union is below the full-market minimum")
    _validate_plate_evidence(plate_codes, codes, label="manual recovery Futu authority")
    plate_codes_sha256 = {
        plate: _sha256(plate_codes[plate]) for plate in HKCONNECT_PLATE_CODES
    }
    plate_capture = {
        "captured_at": captured_at,
        "plate_codes": {plate: plate_codes[plate] for plate in HKCONNECT_PLATE_CODES},
        "plate_codes_sha256": plate_codes_sha256,
    }
    lineage = {
        "schema_version": "v35.hk_connect.manual_recovery.lineage.v1",
        "kind": MANUAL_RECOVERY_SOURCE_MATERIALIZATION,
        "target_trade_date": target,
        "parent": {
            "trade_date": parent_target,
            "artifact_relative": f"universes/{parent_target}/HK_CONNECT_FULL_MARKET.json",
            "artifact_sha256": parent_artifact_sha256,
            "codes_sha256": parent_codes_sha256,
            "code_count": len(parent.codes),
        },
        "official_evidence": official,
        "delta_codes": list(delta),
        "plate_capture": plate_capture,
        "recovered_at": captured_at,
        "corroborated_at": captured_at,
        "natural_verified": False,
    }
    payload = _manifest_payload(
        target,
        plate_codes,
        codes,
        captured_at,
        extra_fields={
            "source_materialization": MANUAL_RECOVERY_SOURCE_MATERIALIZATION,
            "origin_claim": MANUAL_RECOVERY_ORIGIN_CLAIM,
            "plate_codes_sha256": plate_codes_sha256,
            "recovery_lineage": lineage,
            "recovered_at": captured_at,
            "corroborated_at": captured_at,
            "natural_verified": False,
        },
    )
    artifact_bytes = _canonical_json_line(payload)
    if path.exists():
        try:
            existing_bytes = path.read_bytes()
        except OSError as error:
            raise ValueError("manual recovery target artifact conflict") from error
        if existing_bytes != artifact_bytes:
            raise ValueError("manual recovery target artifact conflict")
        try:
            artifact_payload = json.loads(existing_bytes.decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise ValueError("manual recovery target artifact conflict") from error
        if not isinstance(artifact_payload, dict):
            raise ValueError("manual recovery target artifact conflict")
    else:
        if not _atomic_create(path, payload):
            try:
                existing_bytes = path.read_bytes()
            except OSError as error:
                raise ValueError("manual recovery target artifact creation lost") from error
            if existing_bytes != artifact_bytes:
                raise ValueError("manual recovery target artifact conflict")
        artifact_payload = payload
    authority = _complete_authority_chain(
        root,
        target,
        artifact_payload,
        source_materialization=MANUAL_RECOVERY_SOURCE_MATERIALIZATION,
        origin_claim=MANUAL_RECOVERY_ORIGIN_CLAIM,
    )
    try:
        verified = reader(root, target, "HK_CONNECT")
    except (OSError, TypeError, ValueError, KeyError) as error:
        raise ValueError("manual recovery authority chain failed self-verification") from error
    return {
        "ok": True,
        "status": authority["status"],
        "trade_date": target,
        "manifest": str(path),
        "manifest_sha256": authority["manifest_sha256"],
        "artifact_sha256": authority["artifact_sha256"],
        "code_count": len(verified.codes),
        "source_materialization": MANUAL_RECOVERY_SOURCE_MATERIALIZATION,
        "natural_verified": False,
        "write_performed": True,
        "authority": authority,
        **SAFETY_FLAGS,
    }


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
    try:
        minimum = int(min_universe_count)
    except (TypeError, ValueError) as error:
        raise ValueError("HK universe minimum must be an integer") from error
    if minimum < HK_UNIVERSE_MIN_COUNT:
        raise ValueError(f"HK universe minimum must be at least {HK_UNIVERSE_MIN_COUNT}")

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
                codes: list[str] = []
                for row in _plate_rows(frame, plate_code):
                    raw_code = row.get("code")
                    code = raw_code.strip().upper() if isinstance(raw_code, str) else ""
                    if not _HK_CODE_RE.fullmatch(code):
                        raise ValueError(f"FUTU plate membership invalid code: {plate_code}")
                    if code in codes:
                        raise ValueError(f"FUTU plate membership duplicate code: {plate_code}:{code}")
                    codes.append(code)
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
    if len(codes) < minimum:
        raise ValueError(
            "HK Connect plate membership is below minimum count: "
            f"{len(codes)} < {minimum}"
        )
    _validate_plate_evidence(
        plate_codes,
        codes,
        label="FUTU HK Connect authority",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run one explicit MANUAL_RECOVERY authority publication.

    The command deliberately accepts every recovery fact as an argument.  It
    does not infer dates, deltas, or evidence from a panel, and it never marks
    the resulting authority as natural.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--parent-trade-date", required=True)
    parser.add_argument("--parent-artifact-sha256", required=True)
    parser.add_argument("--parent-codes-sha256", required=True)
    parser.add_argument("--official-evidence-path", type=Path, required=True)
    parser.add_argument("--official-evidence-sha256", required=True)
    parser.add_argument("--official-evidence-url", required=True)
    parser.add_argument("--notice-date", required=True)
    parser.add_argument("--effective-date", required=True)
    parser.add_argument("--delta-code", dest="delta_codes", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        result = recover_hk_connect_universe(
            args.store_root,
            args.trade_date,
            parent_trade_date=args.parent_trade_date,
            parent_artifact_sha256=args.parent_artifact_sha256,
            parent_codes_sha256=args.parent_codes_sha256,
            official_evidence_path=args.official_evidence_path,
            official_evidence_sha256=args.official_evidence_sha256,
            official_evidence_url=args.official_evidence_url,
            notice_date=args.notice_date,
            effective_date=args.effective_date,
            delta_codes=args.delta_codes,
        )
    except (OSError, RuntimeError, TypeError, ValueError, KeyError) as error:
        failure = {
            "ok": False,
            "status": "MANUAL_RECOVERY_FAILED",
            "error": str(error),
            "source_materialization": MANUAL_RECOVERY_SOURCE_MATERIALIZATION,
            "natural_verified": False,
            **SAFETY_FLAGS,
        }
        print(json.dumps(failure, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


__all__ = [
    "HKCONNECT_PLATE_CODES",
    "HK_UNIVERSE_SOURCE_ROLE",
    "HK_AUTHORITY_MANIFEST_SCHEMA",
    "HK_AUTHORITY_RECEIPT_SCHEMA",
    "HK_AUTHORITY_CURRENT_SCHEMA",
    "MANUAL_RECOVERY_SOURCE_MATERIALIZATION",
    "MANUAL_RECOVERY_ORIGIN_CLAIM",
    "authority_run_id",
    "ensure_hk_connect_universe",
    "recover_hk_connect_universe",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
