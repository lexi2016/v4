"""Materialize exact-date HK names with distinct universe and asset roots.

The shared producer historically assumed that immutable universe manifests and
mutable assets lived below one root.  The Mac runtime deliberately separates
those roots, so this bounded bridge verifies the exact universe from its
read-only root and publishes only the security-master asset to the shared
runtime store.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

from infrastructure.isolated_package_loader import load_isolated_package_module


_CAPTURE_SCHEMA = "v3.macos.research_panel_hk_capture.v1"
_CAPTURE_SCHEMA_V2 = "v4.manager_hk_connect_capture.v2"
_CAPTURE_PLATES = ("HK.GangGuTong", "HK.LIST1922")
_SECURITY_FIELDS = (
    "code",
    "name",
    "outstanding_shares",
    "circular_market_val",
    "listing_date",
    "lot_size",
    "stock_owner",
    "stock_child_type",
    "sec_status",
)
_PANEL_FIELDS = (
    "trade_date",
    "code",
    "name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "source",
)
_PANEL_NUMERIC_FIELDS = ("open", "high", "low", "close", "volume", "turnover")
_SECURITY_NUMERIC_FIELDS = ("outstanding_shares", "circular_market_val", "lot_size")
_NULLABLE_SECURITY_NUMERIC_FIELDS = frozenset(
    {"outstanding_shares", "circular_market_val"}
)
_HK_CODE_PATTERN = r"HK\.\d{5}"


def _canonical_sha(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdefABCDEF" for character in value
    )


def _read_verified_hk_panel_authority(
    *,
    asset_root: Path,
    package_root: Path,
    authority: Mapping[str, Any],
    trade_date: str,
) -> str:
    """Read the updater's canonical panel manifest and verify its bytes."""

    root = Path(asset_root).expanduser().resolve()

    def resolve_asset_path(value: Any, label: str) -> tuple[Path, str]:
        if not isinstance(value, str) or not value.strip() or Path(value).is_absolute():
            raise ValueError(f"HK panel {label} path invalid")
        candidate = (root / value).resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError as error:
            raise ValueError(f"HK panel {label} path escapes asset root") from error
        if not candidate.is_file():
            raise ValueError(f"HK panel {label} artifact missing: {candidate}")
        return candidate, relative.as_posix()

    try:
        pointer = json.loads((root / "panel_latest.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("HK panel authority pointer unreadable") from error
    if not isinstance(pointer, Mapping):
        raise ValueError("HK panel authority pointer invalid")
    manifest_path, manifest_relative = resolve_asset_path(pointer.get("manifest_relative"), "manifest")
    authority_relative = authority.get("manifest_relative")
    if not isinstance(authority_relative, str):
        raise ValueError("HK panel authority manifest identity missing")
    authority_manifest_path, authority_manifest_relative = resolve_asset_path(authority_relative, "updater manifest")
    if authority_manifest_path != manifest_path or authority_manifest_relative != manifest_relative:
        raise ValueError("HK panel authority manifest identity mismatch")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("HK panel authority manifest unreadable") from error
    if not isinstance(manifest, Mapping):
        raise ValueError("HK panel authority manifest invalid")

    try:
        from infrastructure import isolated_package_loader

        reader_module = isolated_package_loader.load_isolated_package_module(
            Path(package_root),
            package_directory="shared_data",
            module_leaf="hk_0_2",
            namespace_prefix="v35_hk_daily_panel_authority",
        )
        assets = getattr(reader_module, "load_frozen_hk_0_2_assets")(root)
    except Exception as error:
        raise ValueError("HK panel authority reader failed") from error
    trusted_manifest = getattr(assets, "panel_manifest", None)
    trusted_panel_path = getattr(assets, "panel_path", None)
    if not isinstance(trusted_manifest, Mapping) or not isinstance(trusted_panel_path, (str, Path)):
        raise ValueError("HK panel authority reader returned invalid identity")
    if _canonical_sha(dict(trusted_manifest)) != _canonical_sha(dict(manifest)):
        raise ValueError("HK panel authority manifest identity changed")
    if manifest.get("asset_schema_version") not in {
        "v3_shared_data.hk_0_2_panel_asset.v1",
        "v3_shared_data.hk_0_2_panel_asset.v2",
    }:
        raise ValueError("HK panel authority manifest schema invalid")
    if manifest.get("panel_max_date") != trade_date:
        raise ValueError("HK panel authority manifest target date mismatch")
    if manifest.get("production_allowed") is not False or any(
        name in manifest and manifest.get(name) is not False
        for name in ("buy_gate_updated", "orders_sent")
    ):
        raise ValueError("HK panel authority manifest safety contract invalid")
    panel_path, _panel_relative = resolve_asset_path(manifest.get("panel_relative"), "panel")
    if Path(trusted_panel_path).expanduser().resolve() != panel_path:
        raise ValueError("HK panel authority panel identity mismatch")
    manifest_panel_sha = manifest.get("panel_sha256")
    if not _is_sha256(manifest_panel_sha):
        raise ValueError("HK panel manifest SHA invalid")
    actual_panel_sha = hashlib.sha256(panel_path.read_bytes()).hexdigest()
    if actual_panel_sha.lower() != str(manifest_panel_sha).lower() or actual_panel_sha.lower() != str(authority.get("panel_sha256")).lower():
        raise ValueError("HK panel SHA does not match manifest artifact")
    try:
        pointer_after = json.loads((root / "panel_latest.json").read_text(encoding="utf-8"))
        manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("HK panel authority identity changed") from error
    if (
        not isinstance(pointer_after, Mapping)
        or pointer_after.get("manifest_relative") != pointer.get("manifest_relative")
        or not isinstance(manifest_after, Mapping)
        or _canonical_sha(dict(manifest_after)) != _canonical_sha(dict(manifest))
    ):
        raise ValueError("HK panel authority identity changed")
    if hashlib.sha256(panel_path.read_bytes()).hexdigest() != actual_panel_sha:
        raise ValueError("HK panel SHA changed during authority binding")
    return actual_panel_sha


def _valid_hk_code(value: Any) -> bool:
    import re

    return isinstance(value, str) and re.fullmatch(_HK_CODE_PATTERN, value) is not None


def _non_placeholder_name(value: Any, code: str) -> bool:
    name = str(value or "").strip()
    return bool(name) and name.upper() != code and name not in {
        code[3:],
        f"{code[3:]}.HK",
        f"{code[3:]}.HK_CONNECT",
    }


def _value_is_missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _value_is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or _value_is_missing(value):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _value_is_numeric_nan(value: Any) -> bool:
    """Return whether a non-string value is the numeric NaN sentinel."""

    if value is None or isinstance(value, (bool, str, bytes, bytearray)):
        return False
    try:
        return math.isnan(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _validate_complete_row(
    row: Mapping[str, Any],
    *,
    fields: tuple[str, ...],
    numeric_fields: tuple[str, ...],
    label: str,
    nullable_fields: frozenset[str] = frozenset(),
    nullable_numeric_fields: frozenset[str] = frozenset(),
) -> None:
    missing_fields = [field for field in fields if field not in row]
    if missing_fields:
        raise ValueError(f"{label} fields missing: {', '.join(missing_fields)}")
    missing_values = [
        field
        for field in fields
        if field not in nullable_fields and _value_is_missing(row.get(field))
    ]
    if missing_values:
        raise ValueError(f"{label} value missing: {', '.join(missing_values)}")
    invalid_numbers = [
        field
        for field in numeric_fields
        if not (
            field in nullable_fields
            and (
                _value_is_missing(row.get(field))
                or (
                    field in nullable_numeric_fields
                    and _value_is_numeric_nan(row.get(field))
                )
            )
        )
        and not _value_is_finite_number(row.get(field))
    ]
    if invalid_numbers:
        raise ValueError(f"{label} numeric value invalid: {', '.join(invalid_numbers)}")
    negative_numbers = [
        field
        for field in numeric_fields
        if _value_is_finite_number(row.get(field)) and float(row.get(field)) < 0
    ]
    if negative_numbers:
        raise ValueError(f"{label} numeric value invalid: {', '.join(negative_numbers)}")


def _validate_security_master_rows(
    rows: Mapping[str, Mapping[str, Any]], *, expected_codes: list[str] | tuple[str, ...] | set[str]
) -> None:
    if not isinstance(rows, Mapping):
        raise ValueError("HK security-master rows invalid")
    expected = list(expected_codes)
    if set(rows) != set(expected):
        raise ValueError("HK security-master rows coverage mismatch")
    for code in expected:
        row = rows.get(code)
        if not isinstance(row, Mapping):
            raise ValueError(f"HK security-master row invalid: {code}")
        _validate_complete_row(
            row,
            fields=_SECURITY_FIELDS,
            numeric_fields=_SECURITY_NUMERIC_FIELDS,
            label=f"HK security-master {code}",
            nullable_fields=frozenset(
                {"stock_child_type", "outstanding_shares", "circular_market_val"}
            ),
            nullable_numeric_fields=_NULLABLE_SECURITY_NUMERIC_FIELDS,
        )
        if row.get("code") != code:
            raise ValueError(f"HK security-master row code mismatch: {code}")
        if not _non_placeholder_name(row.get("name"), code):
            raise ValueError(f"HK security-master name missing: {code}")


def _normalized_master_value(field: str, value: Any) -> object:
    if field in {"outstanding_shares", "circular_market_val", "lot_size"}:
        if value in (None, ""):
            return ""
        try:
            return float(value)
        except (TypeError, ValueError):
            return str(value).strip()
    return str(value or "").strip()


def _capture_rows_match(
    existing: Mapping[str, Mapping[str, Any]],
    captured: list[Mapping[str, Any]],
) -> bool:
    for expected in captured:
        code = str(expected.get("code") or "")
        current = existing.get(code)
        if not isinstance(current, Mapping):
            return False
        if any(
            _normalized_master_value(field, current.get(field))
            != _normalized_master_value(field, expected.get(field))
            for field in _SECURITY_FIELDS
        ):
            return False
    return True


def _panel_capture_binding_sha256(
    capture: Mapping[str, Any], panel_sha256: str
) -> str:
    if not _is_sha256(panel_sha256):
        raise ValueError("HK panel SHA invalid")
    return _canonical_sha(
        {
            "capture_sha256": capture["capture_sha256"],
            "codes": capture["codes"],
            "rows": capture["rows"],
            "panel_sha256": panel_sha256,
        }
    )


def _validated_capture(
    capture: Mapping[str, Any], *, trade_date: str, panel_sha256: str | None
) -> dict[str, Any]:
    if not isinstance(capture, Mapping):
        raise ValueError("HK panel capture envelope invalid")
    envelope = dict(capture)
    capture_schema = envelope.get("schema_version")
    if capture_schema not in {_CAPTURE_SCHEMA, _CAPTURE_SCHEMA_V2}:
        raise ValueError("HK panel capture schema mismatch")
    if capture_schema == _CAPTURE_SCHEMA_V2:
        contract, _contract_owner = _load_hk_connect_v2_contract()
        try:
            contract.validate_captured_hk_connect_membership_v2(
                envelope, trade_date=trade_date
            )
        except (TypeError, ValueError) as error:
            raise ValueError("HK panel capture v2 membership invalid") from error
    if envelope.get("target_date") != trade_date:
        raise ValueError("HK panel capture target date mismatch")
    if list(envelope.get("plates") or []) != list(_CAPTURE_PLATES):
        raise ValueError("HK panel capture plates mismatch")
    if any(envelope.get(name) is not False for name in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("HK panel capture safety contract invalid")
    if panel_sha256 is not None and not _is_sha256(panel_sha256):
        raise ValueError("HK panel SHA invalid")

    codes = envelope.get("codes")
    if not isinstance(codes, list) or not codes or any(not _valid_hk_code(code) for code in codes):
        raise ValueError("HK panel capture codes invalid")
    if codes != sorted(codes) or len(codes) != len(set(codes)):
        raise ValueError("HK panel capture codes duplicate or unsorted")

    rows = envelope.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("HK panel capture rows missing")

    source_payload = envelope.get("source_payload")
    source_sha256 = envelope.get("source_sha256")
    if not isinstance(source_payload, Mapping) or not _is_sha256(source_sha256):
        raise ValueError("HK panel capture source hash missing")
    if source_payload.get("target_date") != trade_date:
        raise ValueError("HK panel capture source target date mismatch")
    if list(source_payload.get("plates") or []) != list(_CAPTURE_PLATES):
        raise ValueError("HK panel capture source plates mismatch")
    if source_payload.get("rows") != rows or _canonical_sha(source_payload) != source_sha256:
        raise ValueError("HK panel capture source hash mismatch")

    excluded_codes = source_payload.get("excluded_codes")
    if not isinstance(excluded_codes, list) or any(
        not _valid_hk_code(code) for code in excluded_codes
    ):
        raise ValueError("HK panel capture excluded codes invalid")
    if excluded_codes != sorted(excluded_codes):
        raise ValueError("HK panel capture excluded codes unsorted")
    if len(excluded_codes) != len(set(excluded_codes)):
        raise ValueError("HK panel capture excluded codes duplicate")
    if any(code not in codes for code in excluded_codes):
        raise ValueError("HK panel capture excluded code outside universe")
    excluded_count = source_payload.get("excluded_count")
    if (
        isinstance(excluded_count, bool)
        or not isinstance(excluded_count, int)
        or excluded_count != len(excluded_codes)
    ):
        raise ValueError("HK panel capture excluded count mismatch")
    excluded_reasons = source_payload.get("excluded_reasons")
    if not isinstance(excluded_reasons, Mapping):
        raise ValueError("HK panel capture excluded reason/quarantine evidence missing")
    if set(excluded_reasons) != set(excluded_codes):
        raise ValueError("HK panel capture excluded reason/quarantine set mismatch")
    for code in excluded_codes:
        reasons = excluded_reasons.get(code)
        if not isinstance(reasons, list) or not reasons or any(
            not isinstance(reason, str) or not reason.strip() for reason in reasons
        ):
            raise ValueError(
                f"HK panel capture excluded reason/quarantine missing: {code}"
            )

    row_codes: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("HK panel capture row invalid")
        _validate_complete_row(
            row,
            fields=_PANEL_FIELDS,
            numeric_fields=_PANEL_NUMERIC_FIELDS,
            label="HK panel capture panel",
        )
        if row.get("trade_date") != trade_date:
            raise ValueError("HK panel capture row date mismatch")
        code = row.get("code")
        if not _valid_hk_code(code) or code not in codes:
            raise ValueError("HK panel capture row code outside universe")
        if not _non_placeholder_name(row.get("name"), code):
            raise ValueError(f"HK panel capture panel name missing: {code}")
        row_codes.append(code)
    if len(row_codes) != len(set(row_codes)):
        raise ValueError("HK panel capture rows duplicate")
    expected_row_codes = set(codes) - set(excluded_codes)
    if set(row_codes) != expected_row_codes:
        raise ValueError("HK panel capture rows coverage mismatch")

    security_rows = envelope.get("security_master_rows")
    if not isinstance(security_rows, list) or len(security_rows) != len(codes):
        raise ValueError("HK security-master capture coverage mismatch")
    security_codes: list[str] = []
    for row in security_rows:
        if not isinstance(row, Mapping):
            raise ValueError("HK security-master capture row invalid")
        _validate_complete_row(
            row,
            fields=_SECURITY_FIELDS,
            numeric_fields=_SECURITY_NUMERIC_FIELDS,
            label="HK security-master capture",
            nullable_fields=frozenset(
                {"stock_child_type", "outstanding_shares", "circular_market_val"}
            ),
            nullable_numeric_fields=_NULLABLE_SECURITY_NUMERIC_FIELDS,
        )
        code = row.get("code")
        if not _valid_hk_code(code) or code not in codes:
            raise ValueError("HK security-master capture code outside universe")
        if not _non_placeholder_name(row.get("name"), code):
            raise ValueError(f"HK security-master capture name missing: {code}")
        security_codes.append(code)
    if security_codes != codes or len(security_codes) != len(set(security_codes)):
        raise ValueError("HK security-master capture codes duplicate or incomplete")

    capture_digest = envelope.get("capture_sha256")
    if not _is_sha256(capture_digest):
        raise ValueError("HK panel capture hash missing")
    digest_payload = dict(envelope)
    digest_payload.pop("capture_sha256", None)
    if _canonical_sha(digest_payload) != capture_digest:
        raise ValueError("HK panel capture hash mismatch")
    return envelope


def _load_hk_connect_v2_contract():
    """Load the adjacent, exact candidate pure v2 contract by file identity."""
    app_root = Path(__file__).resolve().parents[1]
    path = app_root / "stage_center" / "hk_universe_preflight.py"
    if path.is_symlink() or not path.is_file():
        raise ValueError("HK Connect v2 contract source missing or symlinked")
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(
        "_hk_connect_v2_contract_" + source_sha256, path
    )
    if spec is None or spec.loader is None:
        raise ValueError("HK Connect v2 contract loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (
        Path(module.__file__).resolve() != path.resolve()
        or hashlib.sha256(path.read_bytes()).hexdigest() != source_sha256
        or not callable(getattr(module, "validate_captured_hk_connect_membership_v2", None))
        or not callable(getattr(module, "build_captured_hk_connect_authority_v2", None))
    ):
        raise ValueError("HK Connect v2 contract source identity changed")
    owner = {
        "code_ref": "stage_center/hk_universe_preflight.py",
        "code_sha256": source_sha256,
        "role": "PURE_CAPTURED_HK_CONNECT_CONTRACT_V2",
    }
    return module, owner


def _authority_path(root: Path, relative: str) -> Path:
    """Resolve one normalized authority path below the existing store root."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("HK Connect authority path invalid")
    path = PurePosixPath(relative)
    if path.is_absolute() or path.as_posix() != relative or any(
        part in {"", ".", ".."} for part in path.parts
    ):
        raise ValueError("HK Connect authority path invalid")
    real_root = root.expanduser().resolve()
    candidate = real_root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("HK Connect authority path symlink")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(real_root)
    except ValueError as error:
        raise ValueError("HK Connect authority path escapes store root") from error
    return candidate


def _create_immutable_authority_file(path: Path, payload: bytes) -> bool:
    """Create exact authority bytes without ever replacing an existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("HK Connect authority file symlink")
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise ValueError(f"HK Connect authority immutable conflict: {path.name}")
        return False
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary_path, path)
            return True
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
                raise ValueError(f"HK Connect authority immutable conflict: {path.name}")
            return False
    finally:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _publish_captured_hk_connect_authority_v2(
    *, store_root: Path, trade_date: str, capture: Mapping[str, Any]
) -> dict[str, Any]:
    """Publish one captured-input v2 chain within the existing store root."""
    contract, contract_owner = _load_hk_connect_v2_contract()
    producer_owner = capture.get("producer_owner")
    if not isinstance(producer_owner, Mapping):
        raise ValueError("HK Connect v2 producer owner missing")
    built = contract.build_captured_hk_connect_authority_v2(
        capture,
        trade_date=trade_date,
        producer_owner=producer_owner,
        contract_owner=contract_owner,
    )
    root = store_root.expanduser().resolve()
    file_payloads = [
        (built["paths"]["artifact_relative"], built["artifact_bytes"]),
        (built["paths"]["manifest_relative"], built["manifest_bytes"]),
        (built["paths"]["receipt_relative"], built["receipt_bytes"]),
        (built["capture_relative"], built["capture_bytes"]),
        (built["paths"]["current_relative"], built["current_bytes"]),
    ]
    written = {}
    for relative, encoded in file_payloads:
        path = _authority_path(root, relative)
        created = _create_immutable_authority_file(path, encoded)
        actual = path.read_bytes()
        if actual != encoded:
            raise ValueError(f"HK Connect authority readback mismatch: {relative}")
        written[relative] = {
            "sha256": hashlib.sha256(actual).hexdigest(),
            "size_bytes": len(actual),
            "created": created,
        }

    # Availability is witnessed only after every upstream immutable byte has
    # been read back from disk. Existing publication bytes remain immutable.
    publication_relative = built["publication_relative"]
    publication_path = _authority_path(root, publication_relative)
    if publication_path.exists():
        try:
            publication = json.loads(publication_path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("HK Connect v2 publication receipt unreadable") from error
        if not isinstance(publication, Mapping):
            raise ValueError("HK Connect v2 publication receipt invalid")
        publication_material = dict(publication)
        publication_digest = publication_material.pop("publication_sha256", None)
        if not _is_sha256(publication_digest) or _canonical_sha(publication_material) != publication_digest:
            raise ValueError("HK Connect v2 publication receipt hash mismatch")
        expected_identity = {
            "schema_version": contract.HK_CONNECT_PUBLICATION_SCHEMA_V2,
            "status": "READY",
            "target_date": trade_date,
            "run_id": built["run_id"],
            "capture_run_id": capture["capture_run_id"],
            "capture_sha256": capture["capture_sha256"],
            "artifact_sha256": built["artifact_sha256"],
            "current_sha256": built["current_sha256"],
            "producer_owner": dict(producer_owner),
            "contract_owner": contract_owner,
            **contract.SAFETY_FLAGS,
        }
        if any(publication.get(key) != value for key, value in expected_identity.items()):
            raise ValueError("HK Connect v2 publication receipt identity mismatch")
        available_at = publication.get("available_at")
        try:
            available_dt = datetime.fromisoformat(str(available_at).replace("Z", "+00:00"))
        except (TypeError, ValueError) as error:
            raise ValueError("HK Connect v2 publication availability invalid") from error
        if available_dt.tzinfo is None:
            raise ValueError("HK Connect v2 publication availability is naive")
    else:
        publication = {
            "schema_version": contract.HK_CONNECT_PUBLICATION_SCHEMA_V2,
            "status": "READY",
            "target_date": trade_date,
            "effective_date": trade_date,
            "trade_date": trade_date,
            "source_date": trade_date,
            "market": "HK_CONNECT",
            "scope": "FULL_MARKET",
            "run_id": built["run_id"],
            "publication_relative": publication_relative,
            "available_at": datetime.now().astimezone().isoformat(timespec="microseconds"),
            "acquired_at": capture["acquired_at"],
            "capture_run_id": capture["capture_run_id"],
            "capture_sha256": capture["capture_sha256"],
            "artifact_relative": built["paths"]["artifact_relative"],
            "artifact_sha256": built["artifact_sha256"],
            "manifest_relative": built["paths"]["manifest_relative"],
            "receipt_relative": built["paths"]["receipt_relative"],
            "current_relative": built["paths"]["current_relative"],
            "current_sha256": built["current_sha256"],
            "workload_id": producer_owner.get("workload_id"),
            "producer_owner": dict(producer_owner),
            "contract_owner": contract_owner,
            "forward_source_set": producer_owner.get("forward_source_set"),
            "forward_source_set_sha256": producer_owner.get("forward_source_set_sha256"),
            **contract.SAFETY_FLAGS,
        }
        publication["publication_sha256"] = _canonical_sha(publication)
        publication_bytes = contract._canonical_json_line(publication)
        _create_immutable_authority_file(publication_path, publication_bytes)
        if publication_path.read_bytes() != publication_bytes:
            raise ValueError("HK Connect v2 publication receipt readback mismatch")

    return {
        "status": "READY",
        "run_id": built["run_id"],
        "trade_date": trade_date,
        "artifact_sha256": built["artifact_sha256"],
        "current_sha256": built["current_sha256"],
        "capture_run_id": capture["capture_run_id"],
        "capture_sha256": capture["capture_sha256"],
        "available_at": publication["available_at"],
        "publication_relative": publication_relative,
        "written_files": written,
        **contract.SAFETY_FLAGS,
    }


def _capture_result(
    *,
    capture: Mapping[str, Any],
    trade_date: str,
    panel_sha256: str | None,
    rows: Mapping[str, Mapping[str, Any]],
    manifest: Mapping[str, Any],
    reused: bool,
    run_id: Any,
    artifact_sha256: Any,
    manifest_sha256: Any,
) -> dict[str, object]:
    result = {
        "ok": True,
        "status": "READY",
        "reused": reused,
        "trade_date": trade_date,
        "row_count": len(rows),
        "run_id": run_id,
        "security_master_run_id": run_id,
        "universe_codes_sha256": _canonical_sha(capture["codes"]),
        "capture_sha256": capture["capture_sha256"],
        "source_sha256": capture["source_sha256"],
        "panel_sha256": panel_sha256,
        "panel_capture_binding_sha256": _panel_capture_binding_sha256(
            capture, panel_sha256
        ),
        "security_master_artifact_sha256": artifact_sha256,
        "security_master_manifest_sha256": manifest_sha256,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return result


def ensure_hk_security_master(
    *,
    store_root: Path,
    universe_root: Path,
    shared_package_root: Path,
    trade_date: str,
    futu_python: Path,
    capture: Mapping[str, Any] | None = None,
    panel_sha256: str | None = None,
    panel_binding_sha256: str | None = None,
    membership_only: bool = False,
    reuse_only: bool = False,
) -> dict[str, object]:
    package_root = shared_package_root.expanduser().resolve()
    if not package_root.is_dir():
        raise ValueError(f"shared package root missing: {package_root}")
    if membership_only:
        if capture is None or panel_sha256 is not None or panel_binding_sha256 is not None:
            raise ValueError("HK membership-only ensure requires capture without panel binding")
        contract, _contract_owner = _load_hk_connect_v2_contract()
        try:
            validated_membership = contract.validate_captured_hk_connect_membership_v2(
                capture, trade_date=trade_date
            )
        except (TypeError, ValueError) as error:
            raise ValueError("HK membership-only capture v2 invalid") from error
        authority = _publish_captured_hk_connect_authority_v2(
            store_root=store_root.expanduser().resolve(),
            trade_date=trade_date,
            capture=capture,
        )
        return {
            "ok": True,
            "status": authority.get("status", "READY"),
            "trade_date": trade_date,
            "row_count": validated_membership["code_count"],
            "capture_sha256": validated_membership["capture_sha256"],
            "source_sha256": validated_membership["source_sha256"],
            "panel_sha256": None,
            "panel_capture_binding_sha256": None,
            "universe_authority": authority,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    validated_capture = (
        _validated_capture(capture, trade_date=trade_date, panel_sha256=panel_sha256)
        if capture is not None
        else None
    )
    expected_panel_binding_sha256: str | None = None
    if validated_capture is not None:
        if not _is_sha256(panel_sha256):
            raise ValueError("HK panel SHA missing")
        expected_panel_binding_sha256 = _panel_capture_binding_sha256(
            validated_capture, panel_sha256
        )
        if panel_binding_sha256 is not None:
            if not _is_sha256(panel_binding_sha256):
                raise ValueError("HK panel capture binding SHA invalid")
            if panel_binding_sha256 != expected_panel_binding_sha256:
                raise ValueError("HK panel capture binding SHA mismatch")

    acquire_module = load_isolated_package_module(
        package_root,
        package_directory="scripts",
        module_leaf="acquire_hk_security_master",
        namespace_prefix="v35_hk_security_master_acquire",
    )
    load_verified_hk_security_master = getattr(
        acquire_module, "load_verified_hk_security_master"
    )
    store_error = getattr(acquire_module, "StoreError")
    if not isinstance(store_error, type) or not issubclass(store_error, Exception):
        raise ValueError("trusted acquire module has invalid StoreError")

    def verify_captured_master_readback(result, validated_capture, expected_codes):
        """Independently read the exact master after a captured-input publication."""
        rows, manifest = load_verified_hk_security_master(store_root, trade_date)
        _validate_security_master_rows(rows, expected_codes=expected_codes)
        if (manifest.get("trade_date") != trade_date
                or manifest.get("run_id") != result.get("security_master_run_id")
                or manifest.get("artifact_sha256") != result.get("security_master_artifact_sha256")
                or manifest.get("universe_codes_sha256") != _canonical_sha(expected_codes)
                or not _capture_rows_match(rows, validated_capture["security_master_rows"])):
            raise ValueError("HK security-master final readback identity mismatch")
        manifest_sha256 = _canonical_sha(manifest)
        if result.get("security_master_manifest_sha256") != manifest_sha256:
            raise ValueError("HK security-master final manifest SHA mismatch")
        if (result.get("panel_sha256") != panel_sha256
                or result.get("panel_capture_binding_sha256")
                != _panel_capture_binding_sha256(validated_capture, panel_sha256)):
            raise ValueError("HK security-master final panel binding mismatch")
        asset_root = store_root.expanduser().resolve() / "assets" / "hk_security_master"
        latest = json.loads((asset_root / "latest.json").read_text(encoding="utf-8"))
        entry = latest.get("entries", {}).get(trade_date)
        if (not isinstance(entry, Mapping) or entry.get("run_id") != manifest.get("run_id")
                or entry.get("manifest_relative") is None or entry.get("receipt_relative") is None):
            raise ValueError("HK security-master final latest entry mismatch")
        manifest_path = (asset_root / str(entry["manifest_relative"])).resolve()
        receipt_path = (asset_root / str(entry["receipt_relative"])).resolve()
        manifest_path.relative_to(asset_root)
        receipt_path.relative_to(asset_root)
        result["security_master_manifest_relative"] = str(manifest_path.relative_to(asset_root))
        result["security_master_receipt_relative"] = str(receipt_path.relative_to(asset_root))
        result["security_master_artifact_relative"] = manifest.get("artifact_relative")
        result["security_master_manifest_sha256"] = manifest_sha256
        result["security_master_readback_status"] = "VERIFIED"
        result["security_master_readback_row_count"] = len(rows)
        return result

    if validated_capture is not None:
        codes = list(validated_capture["codes"])
        try:
            rows, manifest = load_verified_hk_security_master(store_root, trade_date)
        except store_error:
            rows, manifest = {}, {}
        existing_is_valid = True
        if rows:
            try:
                _validate_security_master_rows(rows, expected_codes=codes)
            except ValueError:
                existing_is_valid = False
        if (
            existing_is_valid
            and
            manifest.get("universe_codes_sha256") == _canonical_sha(codes)
            and manifest.get("valuation_eligibility_field") == "circular_market_val"
            and set(rows) == set(codes)
            and _capture_rows_match(rows, validated_capture["security_master_rows"])
        ):
            result = _capture_result(
                capture=validated_capture,
                trade_date=trade_date,
                panel_sha256=panel_sha256,
                rows=rows,
                manifest=manifest,
                reused=True,
                run_id=manifest.get("run_id"),
                artifact_sha256=manifest.get("artifact_sha256"),
                manifest_sha256=_canonical_sha(manifest),
            )
            if validated_capture.get("schema_version") == _CAPTURE_SCHEMA_V2:
                result["universe_authority"] = _publish_captured_hk_connect_authority_v2(
                    store_root=store_root,
                    trade_date=trade_date,
                    capture=validated_capture,
                )
            return verify_captured_master_readback(result, validated_capture, codes)

        publish_hk_security_master = getattr(acquire_module, "publish_hk_security_master")
        _validate_security_master_rows(
            {str(row["code"]): row for row in validated_capture["security_master_rows"]},
            expected_codes=codes,
        )
        published = publish_hk_security_master(
            store_root,
            trade_date=trade_date,
            rows=validated_capture["security_master_rows"],
            universe_codes_sha256=_canonical_sha(codes),
            captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        published_manifest = published.get("manifest")
        if not isinstance(published_manifest, Mapping):
            published_manifest = {}
        result = _capture_result(
            capture=validated_capture,
            trade_date=trade_date,
            panel_sha256=panel_sha256,
            rows={str(row["code"]): row for row in validated_capture["security_master_rows"]},
            manifest=published_manifest,
            reused=False,
            run_id=published.get("run_id"),
            artifact_sha256=published.get("artifact_sha256"),
            manifest_sha256=published.get("manifest_sha256") or _canonical_sha(published_manifest),
        )
        if validated_capture.get("schema_version") == _CAPTURE_SCHEMA_V2:
            result["universe_authority"] = _publish_captured_hk_connect_authority_v2(
                store_root=store_root,
                trade_date=trade_date,
                capture=validated_capture,
            )
        return verify_captured_master_readback(result, validated_capture, codes)

    resolve_stage_universe = getattr(acquire_module, "resolve_stage_universe", None)

    try:
        if not callable(resolve_stage_universe):
            raise ValueError("trusted acquire module has no universe resolver")
        universe = resolve_stage_universe(universe_root, trade_date, "HK_CONNECT")
        universe_codes = list(universe.codes)
        universe_codes_sha256 = universe.codes_sha256
    except Exception as resolution_error:
        # The exact-date panel may seed a reuse/collection only when the
        # legacy authority's current pointer is explicitly absent.  Any
        # checksum, schema, scope, date, or tamper error is authoritative and
        # must fail closed rather than being hidden by a fallback.
        if not (
            isinstance(resolution_error, ValueError)
            and str(resolution_error) == "HK_CONNECT authority current pointer missing"
        ):
            raise
        panel_codes_loader = getattr(acquire_module, "_load_exact_date_hk_panel_codes", None)
        if not callable(panel_codes_loader):
            raise resolution_error
        try:
            universe_codes, universe_codes_sha256 = panel_codes_loader(store_root, trade_date)
        except Exception:
            raise resolution_error
    try:
        rows, manifest = load_verified_hk_security_master(store_root, trade_date)
    except store_error:
        rows, manifest = {}, {}
    if (
        manifest.get("universe_codes_sha256") == universe_codes_sha256
        and manifest.get("valuation_eligibility_field") == "circular_market_val"
        and set(rows) == set(universe_codes)
    ):
        _validate_security_master_rows(rows, expected_codes=universe_codes)
        result: dict[str, object] = {
            "ok": True,
            "status": "READY",
            "reused": True,
            "trade_date": trade_date,
            "row_count": len(rows),
            "run_id": manifest.get("run_id"),
            "universe_codes_sha256": universe_codes_sha256,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        if reuse_only:
            result.update(
                {
                    "security_master_run_id": manifest.get("run_id"),
                    "security_master_artifact_sha256": manifest.get("artifact_sha256"),
                    "security_master_manifest_sha256": _canonical_sha(manifest),
                }
            )
        return result

    if reuse_only:
        raise store_error(
            f"HK security-master exact-date authority unavailable for reuse: {trade_date}"
        )

    publish_hk_security_master = getattr(acquire_module, "publish_hk_security_master")
    collect_futu_hk_security_master = getattr(
        acquire_module, "collect_futu_hk_security_master"
    )
    collected = collect_futu_hk_security_master(futu_python, list(universe_codes))
    collected_rows = {
        str(row.get("code") or ""): row
        for row in collected
        if isinstance(row, Mapping)
    }
    _validate_security_master_rows(collected_rows, expected_codes=universe_codes)
    published = publish_hk_security_master(
        store_root,
        trade_date=trade_date,
        rows=collected,
        universe_codes_sha256=universe_codes_sha256,
        captured_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    )
    return {
        "ok": True,
        "status": "READY",
        "reused": False,
        "trade_date": trade_date,
        "row_count": published["row_count"],
        "run_id": published["run_id"],
        "universe_codes_sha256": universe_codes_sha256,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-root", required=True, type=Path)
    parser.add_argument("--universe-root", required=True, type=Path)
    parser.add_argument("--shared-package-root", required=True, type=Path)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--futu-python", required=True, type=Path)
    parser.add_argument(
        "--reuse-only",
        action="store_true",
        help="Reuse an exact dated master; never invoke a Futu collector",
    )
    args = parser.parse_args(argv)
    try:
        result = ensure_hk_security_master(
            store_root=args.store_root,
            universe_root=args.universe_root,
            shared_package_root=args.shared_package_root,
            trade_date=args.trade_date,
            futu_python=args.futu_python,
            reuse_only=args.reuse_only,
        )
    except Exception as error:  # scheduler boundary: emit one fail-closed JSON result
        result = {
            "ok": False,
            "status": "FAILED",
            "error": f"{type(error).__name__}: {error}",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
