"""Fixed, verified universe manifests for shared stage acquisition.

The acquisition CLI never accepts a path or a code list.  It resolves exactly
two store-owned manifests for the requested date: the A-share stage candidate
set and the complete Hong Kong Stock Connect market set.
"""
from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping

from shared_data.hashing import canonical_bytes, is_sha256_hex, sha256_file, sha256_json
from shared_data.paths import resolve_under, validate_date, validate_role

UNIVERSE_SCHEMA_VERSION = "v3_shared_data.stage_universe.v1"
UNIVERSE_SCHEMA_VERSION_V1 = UNIVERSE_SCHEMA_VERSION
UNIVERSE_SCHEMA_VERSION_V2 = "v3_shared_data.stage_universe.v2"
HK_CONNECT_CANONICAL_COUNT = 651
HK_CONNECT_MIN_FULL_COUNT = HK_CONNECT_CANONICAL_COUNT
A_SHARE_MAX_CANDIDATE_COUNT = 300

HK_AUTHORITY_ROLE = "HK_CONNECT_FULL_MARKET_AUTHORITY"
HK_AUTHORITY_MANIFEST_SCHEMA = "v3_shared_data.hk_connect.authority.manifest.v1"
HK_AUTHORITY_RECEIPT_SCHEMA = "v3_shared_data.hk_connect.authority.receipt.v1"
HK_AUTHORITY_CURRENT_SCHEMA = "v3_shared_data.hk_connect.authority.current.v1"
HK_AUTHORITY_STATUS = "READY"
HK_CONNECT_SOURCE_ROLE = "FUTU_HKCONNECT_PLATE_MEMBERSHIP"

A_SHARE_STAGE_CANDIDATES_V1 = "A_SHARE_STAGE_CANDIDATES.json"
A_SHARE_STAGE_CANDIDATES_V2 = "A_SHARE_STAGE_CANDIDATES_V2.json"
A_SHARE_STAGE_CANDIDATES_V2_ROLE = "A_SHARE_STAGE_CANDIDATES_V2"
A_SHARE_STAGE_CANDIDATES_V2_REVISION_DIR = "A_SHARE_STAGE_CANDIDATES_V2.revisions"
A_SHARE_STAGE_CANDIDATES_V2_SUPERSESSION_DIR = "A_SHARE_STAGE_CANDIDATES_V2.supersessions"

V35_STAGE_ACQUISITION_ROLE = "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2"
V35_STAGE_ACQUISITION_ARTIFACT_SCHEMA = V35_STAGE_ACQUISITION_ROLE
V35_STAGE_ACQUISITION_MANIFEST_SCHEMA = "v3_5.stage_acquisition_universe.manifest.v2"
V35_STAGE_ACQUISITION_RECEIPT_SCHEMA = "v3_5.stage_acquisition_universe.receipt.v2"
V35_STAGE_ACQUISITION_CURRENT_SCHEMA = "v3_5.stage_acquisition_universe.current.v2"

_A_FUTU_RE = re.compile(r"^(SH|SZ|BJ)\.\d{6}$")
_HK_FUTU_RE = re.compile(r"^HK\.\d{5}$")
_A_TS_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
_A_CANONICAL_RE = re.compile(r"^A\.(\d{6})$")
_HK_TS_RE = re.compile(r"^(\d{1,5})\.HK_CONNECT$")


@dataclass(frozen=True)
class StageUniverse:
    path: Path
    trade_date: str
    market: str
    scope: str
    codes: tuple[str, ...]
    codes_sha256: str
    source_role: str
    source_sha256: str
    schema_version: str = UNIVERSE_SCHEMA_VERSION_V1
    artifact_role: str = ""
    artifact_version: str = ""
    source_projection_sha256: str = ""
    source_merge_role: str = ""
    stage_selection_eligible: bool = False


def normalize_symbol(value: str, market: str) -> str:
    """Normalize trusted selector symbols into Futu symbols."""
    text = str(value or "").strip().upper()
    if market == "A_SHARE":
        if _A_FUTU_RE.fullmatch(text):
            return text
        canonical = _A_CANONICAL_RE.fullmatch(text)
        if canonical:
            code = canonical.group(1)
            exchange = (
                "BJ" if code.startswith("920")
                else "SH" if code.startswith(("5", "6", "9"))
                else "SZ"
            )
            return f"{exchange}.{code}"
        match = _A_TS_RE.fullmatch(text)
        if match:
            return f"{match.group(2)}.{match.group(1)}"
        raise ValueError(f"invalid A-share symbol {value!r}")
    if market == "HK_CONNECT":
        if _HK_FUTU_RE.fullmatch(text):
            return text
        match = _HK_TS_RE.fullmatch(text)
        if match:
            return f"HK.{int(match.group(1)):05d}"
        raise ValueError(f"invalid HK Connect symbol {value!r}")
    raise ValueError(f"unknown market {market!r}")


def authority_run_id(trade_date: str, artifact_sha256: str) -> str:
    """Derive a stable path-safe authority run id from date and file SHA."""
    target = validate_date(trade_date)
    if not is_sha256_hex(artifact_sha256):
        raise ValueError("HK authority artifact SHA256 is invalid")
    return hashlib.sha256(
        f"HK_CONNECT_FULL_MARKET:{target}:{artifact_sha256}".encode("ascii")
    ).hexdigest()[:24]


def _hk_authority_paths(store_root: Path | str, trade_date: str, run_id: str) -> dict[str, Path | str]:
    target = validate_date(trade_date)
    if not re.fullmatch(r"[0-9a-f]{24}", str(run_id)):
        raise ValueError("HK authority run_id is unsafe")
    relative_root = f"universes/{target}/HK_CONNECT_FULL_MARKET.authority/{run_id}"
    relative = {
        "artifact_relative": f"universes/{target}/HK_CONNECT_FULL_MARKET.json",
        "manifest_relative": f"{relative_root}/manifest.json",
        "receipt_relative": f"{relative_root}/receipt.json",
        "current_relative": f"universes/{target}/HK_CONNECT_FULL_MARKET.current.json",
    }
    root = Path(store_root)
    return {
        **relative,
        "artifact_path": resolve_under(root, relative["artifact_relative"]),
        "manifest_path": resolve_under(root, relative["manifest_relative"]),
        "receipt_path": resolve_under(root, relative["receipt_relative"]),
        "current_path": resolve_under(root, relative["current_relative"]),
    }


def universe_manifest_path(store_root: Path | str, trade_date: str, market: str) -> Path:
    """Resolve a market/date manifest, preferring the versioned A V2 slot."""
    trade_date = validate_date(trade_date)
    filenames = {
        "A_SHARE": A_SHARE_STAGE_CANDIDATES_V2,
        "HK_CONNECT": "HK_CONNECT_FULL_MARKET.json",
    }
    filename = filenames.get(market)
    if filename is None:
        raise ValueError(f"unknown market {market!r}")
    root = Path(store_root)
    preferred = resolve_under(root, f"universes/{trade_date}/{filename}")
    if market != "A_SHARE":
        return preferred
    legacy = resolve_under(root, f"universes/{trade_date}/{A_SHARE_STAGE_CANDIDATES_V1}")
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


def universe_manifest_publish_path(
    store_root: Path | str, trade_date: str, market: str
) -> Path:
    """Return the immutable publication slot (A V2, HK's existing slot)."""
    trade_date = validate_date(trade_date)
    filename = (
        A_SHARE_STAGE_CANDIDATES_V2
        if market == "A_SHARE"
        else "HK_CONNECT_FULL_MARKET.json"
    )
    if market not in {"A_SHARE", "HK_CONNECT"}:
        raise ValueError(f"unknown market {market!r}")
    return resolve_under(Path(store_root), f"universes/{trade_date}/{filename}")


def universe_manifest_legacy_path(
    store_root: Path | str, trade_date: str
) -> Path:
    """Return the retained V1 A-share path without selecting or writing it."""
    return resolve_under(
        Path(store_root),
        f"universes/{validate_date(trade_date)}/{A_SHARE_STAGE_CANDIDATES_V1}",
    )


def universe_manifest_revision_path(
    store_root: Path | str,
    trade_date: str,
    market: str,
    payload_sha256: str,
) -> Path:
    """Resolve one immutable prior/replacement universe payload revision."""
    if market != "A_SHARE" or not is_sha256_hex(payload_sha256):
        raise ValueError("universe revisions require an A-share payload SHA256")
    return resolve_under(
        Path(store_root),
        f"universes/{validate_date(trade_date)}/{A_SHARE_STAGE_CANDIDATES_V2_REVISION_DIR}/{payload_sha256}.json",
    )


def universe_manifest_supersession_dir(
    store_root: Path | str,
    trade_date: str,
    market: str,
    previous_sha256: str,
    replacement_sha256: str,
) -> Path:
    """Resolve immutable evidence for one CAS replacement."""
    if (
        market != "A_SHARE"
        or not is_sha256_hex(previous_sha256)
        or not is_sha256_hex(replacement_sha256)
    ):
        raise ValueError("universe supersession requires A-share payload SHA256s")
    return resolve_under(
        Path(store_root),
        # Keep the Windows path comfortably below MAX_PATH.  The receipt
        # retains full hashes and is checked before reusing a shortened key.
        f"universes/{validate_date(trade_date)}/{A_SHARE_STAGE_CANDIDATES_V2_SUPERSESSION_DIR}/{previous_sha256[:16]}__to__{replacement_sha256[:16]}",
    )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_sha(payload: Mapping[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not is_sha256_hex(value):
        raise ValueError(f"{label} {key} must be a 64-hex SHA256")
    return value


def _require_false_flags(payload: Mapping[str, Any], label: str) -> None:
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(key) is not False:
            raise ValueError(f"{label} safety flag {key} must be false")


def _require_stage_codes(payload: Mapping[str, Any]) -> list[str]:
    codes = payload.get("codes")
    if not isinstance(codes, list) or not codes:
        raise ValueError("V3.5 stage-acquisition codes must be a nonempty array")
    seen: set[str] = set()
    for code in codes:
        if not isinstance(code, str) or not _A_CANONICAL_RE.fullmatch(code) or code in seen:
            raise ValueError("V3.5 stage-acquisition codes must be ordered, unique A codes")
        seen.add(code)
    row_count = payload.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count != len(codes):
        raise ValueError("V3.5 stage-acquisition row_count mismatch")
    if not is_sha256_hex(payload.get("codes_sha256")):
        raise ValueError("V3.5 stage-acquisition codes_sha256 must be a 64-hex SHA256")
    if payload["codes_sha256"] != sha256_json(codes):
        raise ValueError("V3.5 stage-acquisition codes SHA mismatch")
    return codes


def read_verified_v35_stage_acquisition_universe(
    v35_data_root: Path | str, trade_date: str
) -> dict[str, Any]:
    """Read and independently verify the exact V3.5 V2 current/run trio.

    Only the six JSON files in the V3.5 ``current`` pointer and its immutable
    ``runs`` directory are read.  No V3.5 Python modules, HTTP endpoints, or
    source pool files are imported or inspected.
    """
    trade_date = validate_date(trade_date)
    role = validate_role(V35_STAGE_ACQUISITION_ROLE)
    root = Path(v35_data_root)
    current_path = resolve_under(
        root, f"current/{trade_date}/{role}/current.json"
    )
    current = _read_json(current_path, "V3.5 stage-acquisition current pointer")
    if (
        current.get("schema_version") != V35_STAGE_ACQUISITION_CURRENT_SCHEMA
        or current.get("trade_date") != trade_date
        or current.get("role") != role
        or current.get("status") != "READY"
    ):
        raise ValueError("V3.5 stage-acquisition current identity/status mismatch")
    _require_false_flags(current, "V3.5 stage-acquisition current pointer")
    run_id = current.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(
        r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$", run_id
    ):
        raise ValueError("V3.5 stage-acquisition current run_id is unsafe")
    expected_prefix = f"runs/{trade_date}/{role}/{run_id}/"
    artifact_relative = current.get("artifact_relative")
    if artifact_relative != expected_prefix + "artifact.json":
        raise ValueError("V3.5 stage-acquisition current artifact path mismatch")

    pointer_artifact_sha = _require_sha(current, "artifact_sha256", "V3.5 current")
    pointer_manifest_sha = _require_sha(current, "manifest_sha256", "V3.5 current")
    pointer_receipt_sha = _require_sha(current, "receipt_sha256", "V3.5 current")
    pointer_codes_sha = _require_sha(current, "codes_sha256", "V3.5 current")
    pointer_projection_sha = _require_sha(
        current, "source_projection_sha256", "V3.5 current"
    )
    pointer_row_count = current.get("row_count")
    if isinstance(pointer_row_count, bool) or not isinstance(pointer_row_count, int):
        raise ValueError("V3.5 current row_count is invalid")

    run_dir = resolve_under(root, f"runs/{trade_date}/{role}/{run_id}")
    artifact_path = resolve_under(
        root, f"runs/{trade_date}/{role}/{run_id}/artifact.json"
    )
    manifest_path = resolve_under(
        root, f"runs/{trade_date}/{role}/{run_id}/manifest.json"
    )
    receipt_path = resolve_under(
        root, f"runs/{trade_date}/{role}/{run_id}/receipt.json"
    )
    if not run_dir.is_dir() or any(
        not path.is_file() for path in (artifact_path, manifest_path, receipt_path)
    ):
        raise ValueError("V3.5 stage-acquisition artifact/manifest/receipt trio is incomplete")

    artifact = _read_json(artifact_path, "V3.5 stage-acquisition artifact")
    manifest = _read_json(manifest_path, "V3.5 stage-acquisition manifest")
    receipt = _read_json(receipt_path, "V3.5 stage-acquisition receipt")
    if (
        artifact.get("schema_version") != V35_STAGE_ACQUISITION_ARTIFACT_SCHEMA
        or artifact.get("artifact_role") != role
        or artifact.get("artifact_version") != "V2"
        or artifact.get("status") != "READY"
        or artifact.get("trade_date") != trade_date
        or artifact.get("source_merge_role") != "STAGE_ACQUISITION_INPUT"
        or artifact.get("stage_selection_eligible") is not True
    ):
        raise ValueError("V3.5 stage-acquisition artifact identity/status mismatch")
    _require_false_flags(artifact, "V3.5 stage-acquisition artifact")
    codes = _require_stage_codes(artifact)
    projection_sha = _require_sha(
        artifact, "source_projection_sha256", "V3.5 artifact"
    )
    if artifact.get("source_projection_row_count") != artifact.get("row_count"):
        raise ValueError("V3.5 stage-acquisition source projection row_count mismatch")
    cannot_confirm = artifact.get("cannot_confirm")
    if cannot_confirm is not None and (
        not isinstance(cannot_confirm, list)
        or any(not isinstance(item, str) for item in cannot_confirm)
    ):
        raise ValueError("V3.5 stage-acquisition cannot_confirm is invalid")

    expected_artifact_relative = expected_prefix + "artifact.json"
    for label, payload, schema in (
        ("manifest", manifest, V35_STAGE_ACQUISITION_MANIFEST_SCHEMA),
        ("receipt", receipt, V35_STAGE_ACQUISITION_RECEIPT_SCHEMA),
    ):
        if (
            payload.get("schema_version") != schema
            or payload.get("trade_date") != trade_date
            or payload.get("role") != role
            or payload.get("run_id") != run_id
            or payload.get("status") != "READY"
            or payload.get("artifact_relative") not in (None, expected_artifact_relative)
        ):
            raise ValueError(f"V3.5 stage-acquisition {label} identity/status mismatch")
        _require_false_flags(payload, f"V3.5 stage-acquisition {label}")
        if payload.get("row_count") != artifact.get("row_count"):
            raise ValueError(f"V3.5 stage-acquisition {label} row_count mismatch")
        if payload.get("codes_sha256") != artifact.get("codes_sha256"):
            raise ValueError(f"V3.5 stage-acquisition {label} codes SHA mismatch")
        if payload.get("source_projection_sha256") != projection_sha:
            raise ValueError(f"V3.5 stage-acquisition {label} source projection SHA mismatch")
        _require_sha(payload, "artifact_sha256", f"V3.5 {label}")
    if manifest.get("artifact_relative") != expected_artifact_relative:
        raise ValueError("V3.5 stage-acquisition manifest artifact path mismatch")

    artifact_sha = sha256_json(artifact)
    manifest_sha = sha256_json(manifest)
    receipt_sha = sha256_json(receipt)
    if (
        artifact_sha != pointer_artifact_sha
        or manifest_sha != pointer_manifest_sha
        or receipt_sha != pointer_receipt_sha
        or manifest.get("artifact_sha256") != artifact_sha
        or receipt.get("artifact_sha256") != artifact_sha
        or receipt.get("manifest_sha256") != manifest_sha
    ):
        raise ValueError("V3.5 stage-acquisition JSON SHA bindings mismatch")
    if (
        pointer_row_count != artifact.get("row_count")
        or pointer_codes_sha != artifact.get("codes_sha256")
        or pointer_projection_sha != projection_sha
        or current.get("status") != artifact.get("status")
    ):
        raise ValueError("V3.5 stage-acquisition current bindings mismatch")
    return {
        "current": current,
        "artifact": artifact,
        "manifest": manifest,
        "receipt": receipt,
        "run_id": run_id,
        "codes": codes,
        "artifact_sha256": artifact_sha,
        "manifest_sha256": manifest_sha,
        "receipt_sha256": receipt_sha,
        "artifact_path": artifact_path,
        "manifest_path": manifest_path,
        "receipt_path": receipt_path,
        "current_path": current_path,
    }


def _read_canonical_json_line(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    if raw != canonical_bytes(payload) + b"\n":
        raise ValueError(f"{label} must use canonical UTF-8 JSON bytes")
    return payload


def _require_hk_safety(payload: Mapping[str, Any], label: str) -> None:
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(key) is not False:
            raise ValueError(f"{label} safety flag {key} must be false")


def _require_hk_common(
    payload: Mapping[str, Any],
    *,
    label: str,
    schema: str,
    trade_date: str,
    run_id: str,
) -> None:
    if (
        payload.get("schema_version") != schema
        or payload.get("authority_role") != HK_AUTHORITY_ROLE
        or payload.get("trade_date") != trade_date
        or payload.get("source_date") != trade_date
        or payload.get("market") != "HK_CONNECT"
        or payload.get("scope") != "FULL_MARKET"
        or payload.get("status") != HK_AUTHORITY_STATUS
        or payload.get("run_id") != run_id
    ):
        raise ValueError(f"{label} identity/status mismatch")
    if payload.get("stage_selection_eligible") is not True:
        raise ValueError(f"{label} must be stage-selection eligible")
    _require_hk_safety(payload, label)
    source_sha = payload.get("source_sha256")
    codes_sha = payload.get("codes_sha256")
    if not is_sha256_hex(source_sha) or not is_sha256_hex(codes_sha):
        raise ValueError(f"{label} source/codes SHA missing")
    if payload.get("source_role") != HK_CONNECT_SOURCE_ROLE:
        raise ValueError(f"{label} source role mismatch")
    if payload.get("source_materialization") not in {
        "FRESH_FUTU_ARTIFACT",
        "VERIFIED_EXISTING_ARTIFACT_CHAIN_COMPLETION",
    }:
        raise ValueError(f"{label} source materialization is not verified")
    if payload.get("origin_claim") != "NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT":
        raise ValueError(f"{label} origin claim must remain not asserted")


def _resolve_verified_hk_connect_universe(
    store_root: Path | str,
    trade_date: str,
) -> StageUniverse:
    target = validate_date(trade_date)
    root = Path(store_root)
    current_path = resolve_under(
        root, f"universes/{target}/HK_CONNECT_FULL_MARKET.current.json"
    )
    if not current_path.is_file():
        raise ValueError("HK_CONNECT authority current pointer missing")
    current = _read_canonical_json_line(current_path, "HK_CONNECT authority current")
    run_id = current.get("run_id")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{24}", run_id):
        raise ValueError("HK_CONNECT authority current run_id is unsafe")
    _require_hk_common(
        current,
        label="HK_CONNECT authority current",
        schema=HK_AUTHORITY_CURRENT_SCHEMA,
        trade_date=target,
        run_id=run_id,
    )
    paths = _hk_authority_paths(root, target, run_id)
    for key in ("artifact_relative", "manifest_relative", "receipt_relative", "current_relative"):
        if current.get(key) != paths[key]:
            raise ValueError(f"HK_CONNECT authority current {key} mismatch")
    if paths["current_path"] != current_path:
        raise ValueError("HK_CONNECT authority current path mismatch")
    artifact_path = paths["artifact_path"]
    manifest_path = paths["manifest_path"]
    receipt_path = paths["receipt_path"]
    if not all(path.is_file() for path in (artifact_path, manifest_path, receipt_path)):
        raise ValueError("HK_CONNECT authority chain is incomplete")

    artifact = _read_canonical_json_line(artifact_path, "HK_CONNECT artifact")
    if (
        artifact.get("schema_version") != UNIVERSE_SCHEMA_VERSION_V1
        or artifact.get("trade_date") != target
        or artifact.get("source_date") != target
        or artifact.get("market") != "HK_CONNECT"
        or artifact.get("scope") != "FULL_MARKET"
        or artifact.get("source_role") != HK_CONNECT_SOURCE_ROLE
        or artifact.get("code_count") != HK_CONNECT_CANONICAL_COUNT
    ):
        raise ValueError("HK_CONNECT artifact identity/count mismatch")
    _require_hk_safety(artifact, "HK_CONNECT artifact")
    raw_codes = artifact.get("codes")
    if not isinstance(raw_codes, list) or len(raw_codes) != HK_CONNECT_CANONICAL_COUNT:
        raise ValueError("HK_CONNECT artifact must contain canonical 651 codes")
    codes = tuple(normalize_symbol(code, "HK_CONNECT") for code in raw_codes)
    if len(set(codes)) != HK_CONNECT_CANONICAL_COUNT:
        raise ValueError("HK_CONNECT artifact codes must be unique")
    if artifact.get("code_count") != len(codes):
        raise ValueError("HK_CONNECT artifact code_count mismatch")
    codes_sha256 = artifact.get("codes_sha256")
    if codes_sha256 != sha256_json(list(codes)):
        raise ValueError("HK_CONNECT artifact codes SHA mismatch")
    source_sha256 = artifact.get("source_sha256")
    if not is_sha256_hex(source_sha256):
        raise ValueError("HK_CONNECT artifact source SHA missing")
    plate_codes = artifact.get("plate_codes")
    if not isinstance(plate_codes, Mapping):
        raise ValueError("HK_CONNECT artifact plate evidence missing")
    plate_union: set[str] = set()
    for values in plate_codes.values():
        if not isinstance(values, list):
            raise ValueError("HK_CONNECT artifact plate evidence invalid")
        plate_union.update(normalize_symbol(value, "HK_CONNECT") for value in values)
    if plate_union != set(codes):
        raise ValueError("HK_CONNECT artifact plate union mismatch")
    artifact_sha256 = sha256_file(artifact_path)
    artifact_size = artifact_path.stat().st_size

    manifest = _read_canonical_json_line(manifest_path, "HK_CONNECT authority manifest")
    receipt = _read_canonical_json_line(receipt_path, "HK_CONNECT authority receipt")
    _require_hk_common(
        manifest,
        label="HK_CONNECT authority manifest",
        schema=HK_AUTHORITY_MANIFEST_SCHEMA,
        trade_date=target,
        run_id=run_id,
    )
    _require_hk_common(
        receipt,
        label="HK_CONNECT authority receipt",
        schema=HK_AUTHORITY_RECEIPT_SCHEMA,
        trade_date=target,
        run_id=run_id,
    )
    for label, payload in (("manifest", manifest), ("receipt", receipt), ("current", current)):
        if (
            payload.get("artifact_relative") != paths["artifact_relative"]
            or payload.get("artifact_sha256") != artifact_sha256
            or payload.get("artifact_size") != artifact_size
            or payload.get("code_count") != HK_CONNECT_CANONICAL_COUNT
            or payload.get("codes_sha256") != codes_sha256
            or payload.get("source_sha256") != source_sha256
        ):
            raise ValueError(f"HK_CONNECT authority {label} artifact binding mismatch")
        if payload.get("plate_codes") != plate_codes:
            raise ValueError(f"HK_CONNECT authority {label} plate evidence mismatch")
    manifest_sha256 = sha256_file(manifest_path)
    receipt_sha256 = sha256_file(receipt_path)
    if manifest.get("manifest_relative") not in (None, paths["manifest_relative"]):
        raise ValueError("HK_CONNECT authority manifest path mismatch")
    if receipt.get("manifest_relative") != paths["manifest_relative"]:
        raise ValueError("HK_CONNECT authority receipt manifest path mismatch")
    if receipt.get("manifest_sha256") != manifest_sha256:
        raise ValueError("HK_CONNECT authority receipt manifest SHA mismatch")
    if current.get("manifest_sha256") != manifest_sha256 or current.get("receipt_sha256") != receipt_sha256:
        raise ValueError("HK_CONNECT authority current SHA bindings mismatch")
    return StageUniverse(
        path=artifact_path,
        trade_date=target,
        market="HK_CONNECT",
        scope="FULL_MARKET",
        codes=codes,
        codes_sha256=str(codes_sha256),
        source_role=HK_CONNECT_SOURCE_ROLE,
        source_sha256=str(source_sha256),
        schema_version=UNIVERSE_SCHEMA_VERSION_V1,
        stage_selection_eligible=True,
    )


def resolve_stage_universe(
    store_root: Path | str,
    trade_date: str,
    market: str,
) -> StageUniverse:
    """Load and verify one fixed universe manifest; fail closed on drift."""
    if market == "HK_CONNECT":
        return _resolve_verified_hk_connect_universe(store_root, trade_date)
    path = universe_manifest_path(store_root, trade_date, market)
    if not path.is_file():
        raise ValueError(f"trusted universe manifest missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"trusted universe manifest unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("trusted universe manifest must be a JSON object")
    schema_version = str(payload.get("schema_version") or "")
    expected_schema = (
        UNIVERSE_SCHEMA_VERSION_V2
        if market == "A_SHARE" and path.name == A_SHARE_STAGE_CANDIDATES_V2
        else UNIVERSE_SCHEMA_VERSION_V1
    )
    if schema_version != expected_schema:
        raise ValueError("trusted universe schema mismatch")
    if payload.get("trade_date") != validate_date(trade_date):
        raise ValueError("trusted universe trade_date mismatch")
    if payload.get("market") != market:
        raise ValueError("trusted universe market mismatch")
    expected_scope = "STAGE_CANDIDATES" if market == "A_SHARE" else "FULL_MARKET"
    if payload.get("scope") != expected_scope:
        raise ValueError("trusted universe scope mismatch")
    raw_codes = payload.get("codes")
    if not isinstance(raw_codes, list) or not raw_codes:
        raise ValueError("trusted universe codes must be a nonempty array")
    codes = tuple(normalize_symbol(code, market) for code in raw_codes)
    if len(set(codes)) != len(codes):
        raise ValueError("trusted universe contains duplicate symbols")
    if payload.get("code_count") != len(codes):
        raise ValueError("trusted universe code_count mismatch")
    codes_sha256 = str(payload.get("codes_sha256") or "")
    if codes_sha256 != sha256_json(list(codes)):
        raise ValueError("trusted universe codes_sha256 mismatch")
    source_role = str(payload.get("source_role") or "")
    source_sha256 = str(payload.get("source_sha256") or "")
    if not source_role or not is_sha256_hex(source_sha256):
        raise ValueError("trusted universe source evidence missing")
    artifact_role = str(payload.get("artifact_role") or "")
    artifact_version = str(payload.get("artifact_version") or "")
    source_projection_sha256 = str(payload.get("source_projection_sha256") or "")
    source_merge_role = str(payload.get("source_merge_role") or "")
    stage_selection_eligible = payload.get("stage_selection_eligible") is True
    if expected_schema == UNIVERSE_SCHEMA_VERSION_V2:
        if artifact_role != A_SHARE_STAGE_CANDIDATES_V2_ROLE or artifact_version != "V2":
            raise ValueError("trusted A-share V2 universe identity mismatch")
        if not is_sha256_hex(source_projection_sha256):
            raise ValueError("trusted A-share V2 source projection SHA missing")
        if source_merge_role != "STAGE_ACQUISITION_INPUT" or not stage_selection_eligible:
            raise ValueError("trusted A-share V2 stage eligibility mismatch")
    if market == "A_SHARE" and len(codes) > A_SHARE_MAX_CANDIDATE_COUNT:
        raise ValueError("A-share stage candidates exceed frozen 300-code cap")
    if market == "HK_CONNECT" and len(codes) < HK_CONNECT_MIN_FULL_COUNT:
        raise ValueError(
            f"HK Connect universe has {len(codes)} codes; full-market minimum is "
            f"{HK_CONNECT_MIN_FULL_COUNT} (Top100 is forbidden)"
        )
    for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
        if payload.get(key) is not False:
            raise ValueError(f"trusted universe safety flag {key} must be false")
    return StageUniverse(
        path=path,
        trade_date=trade_date,
        market=market,
        scope=expected_scope,
        codes=codes,
        codes_sha256=codes_sha256,
        source_role=source_role,
        source_sha256=source_sha256,
        schema_version=schema_version,
        artifact_role=artifact_role,
        artifact_version=artifact_version,
        source_projection_sha256=source_projection_sha256,
        source_merge_role=source_merge_role,
        stage_selection_eligible=stage_selection_eligible,
    )
