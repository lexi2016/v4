"""Fail-closed reader for the one explicit V3.5 candidate input root."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .calendar import TradingDayState, resolve_market_states

ROLE = "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2"
CURRENT_SCHEMA = "v3_5.stage_acquisition_universe.current.v2"
ARTIFACT_SCHEMA = ROLE
MANIFEST_SCHEMA = "v3_5.stage_acquisition_universe.manifest.v2"
RECEIPT_SCHEMA = "v3_5.stage_acquisition_universe.receipt.v2"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$")


class CandidateInputError(ValueError):
    """Candidate input is absent, malformed, or SHA-inconsistent."""


@dataclass(frozen=True)
class CandidateInput:
    root: Path
    trade_date: str
    current_relative: str
    current_sha256: str
    run_id: str
    codes: tuple[str, ...]
    artifact_sha256: str
    manifest_sha256: str
    receipt_sha256: str
    source_projection_sha256: str
    source_evidence: tuple[str, ...]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise CandidateInputError(f"{label} unreadable") from error
    if not isinstance(value, dict):
        raise CandidateInputError(f"{label} must be an object")
    return value


def _false_flags(payload: dict[str, Any], label: str) -> None:
    if any(payload.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise CandidateInputError(f"{label} safety flags must be false")


def _require_sha(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise CandidateInputError(f"{label} {key} must be a SHA256")
    return value


def _safe_relative(root: Path, relative: str, label: str) -> Path:
    if (
        not isinstance(relative, str)
        or not relative
        or Path(relative).is_absolute()
        or "\\" in relative
        or (len(relative) > 1 and relative[1] == ":")
    ):
        raise CandidateInputError(f"{label} path is not relative")
    parsed = PurePosixPath(relative)
    if parsed.as_posix() != relative or any(part in {"", ".", ".."} for part in parsed.parts):
        raise CandidateInputError(f"{label} path is not normalized")
    root = root.resolve()
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            raise CandidateInputError(f"{label} symlink component is forbidden")
    candidate = current.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise CandidateInputError(f"{label} path escapes candidate root") from error
    return current


def read_candidate_input(
    root: Path | str,
    trade_date: str,
    *,
    expected_current_sha256: str | None = None,
) -> CandidateInput:
    """Read only ``current/{date}/{ROLE}/current.json`` and its bound trio.

    No fallback to V3.5 ``data/``, ``selector/`` or ``shared`` relative paths
    is permitted.  The caller may pin the pointer SHA before an acquisition.
    """
    if not re.fullmatch(r"\d{8}", str(trade_date)):
        raise CandidateInputError("trade_date must be YYYYMMDD")
    root_path = Path(root).expanduser().resolve()
    if not root_path.is_dir():
        raise CandidateInputError(f"candidate input root missing: {root_path}")
    current_relative = f"current/{trade_date}/{ROLE}/current.json"
    current_path = _safe_relative(root_path, current_relative, "current.json")
    if not current_path.is_file():
        raise CandidateInputError("candidate current.json missing")
    current_sha = _sha(current_path)
    if expected_current_sha256 is not None and current_sha != expected_current_sha256:
        raise CandidateInputError("current.json SHA mismatch")
    current = _json(current_path, "candidate current.json")
    if current.get("schema_version") != CURRENT_SCHEMA or current.get("trade_date") != trade_date or current.get("role") != ROLE or current.get("status") != "READY":
        raise CandidateInputError("candidate current identity/status mismatch")
    _false_flags(current, "candidate current")
    run_id = current.get("run_id")
    if not isinstance(run_id, str) or not _SAFE_RUN_ID.fullmatch(run_id):
        raise CandidateInputError("candidate run_id unsafe")
    expected_prefix = f"runs/{trade_date}/{ROLE}/{run_id}/"
    artifact_relative = current.get("artifact_relative")
    if artifact_relative != expected_prefix + "artifact.json":
        raise CandidateInputError("candidate artifact path mismatch")
    artifact_path = _safe_relative(root_path, artifact_relative, "candidate artifact")
    manifest_path = _safe_relative(root_path, expected_prefix + "manifest.json", "candidate manifest")
    receipt_path = _safe_relative(root_path, expected_prefix + "receipt.json", "candidate receipt")
    for path in (artifact_path, manifest_path, receipt_path):
        if not path.is_file():
            raise CandidateInputError("candidate artifact/manifest/receipt trio incomplete")
    artifact = _json(artifact_path, "candidate artifact")
    manifest = _json(manifest_path, "candidate manifest")
    receipt = _json(receipt_path, "candidate receipt")
    if artifact.get("schema_version") != ARTIFACT_SCHEMA or artifact.get("artifact_role") != ROLE or artifact.get("artifact_version") != "V2" or artifact.get("status") != "READY" or artifact.get("trade_date") != trade_date or artifact.get("source_merge_role") != "STAGE_ACQUISITION_INPUT" or artifact.get("stage_selection_eligible") is not True:
        raise CandidateInputError("candidate artifact identity/status mismatch")
    for payload, schema, label in ((manifest, MANIFEST_SCHEMA, "candidate manifest"), (receipt, RECEIPT_SCHEMA, "candidate receipt")):
        if payload.get("schema_version") != schema or payload.get("trade_date") != trade_date or payload.get("role") != ROLE or payload.get("run_id") != run_id or payload.get("status") != "READY":
            raise CandidateInputError(f"{label} identity/status mismatch")
        _false_flags(payload, label)
    _false_flags(artifact, "candidate artifact")
    codes = artifact.get("codes")
    if (
        not isinstance(codes, list)
        or not codes
        or any(not isinstance(code, str) or not re.fullmatch(r"A\.\d{6}", code) for code in codes)
        or len(set(codes)) != len(codes)
    ):
        raise CandidateInputError("candidate codes invalid")
    codes_sha = hashlib.sha256(json.dumps(codes, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if (
        isinstance(artifact.get("row_count"), bool)
        or not isinstance(artifact.get("row_count"), int)
        or artifact.get("row_count") != len(codes)
        or artifact.get("codes_sha256") != codes_sha
    ):
        raise CandidateInputError("candidate codes binding mismatch")
    artifact_sha, manifest_sha, receipt_sha = _sha(artifact_path), _sha(manifest_path), _sha(receipt_path)
    canonical_artifact_sha = _canonical_sha(artifact)
    canonical_manifest_sha = _canonical_sha(manifest)
    canonical_receipt_sha = _canonical_sha(receipt)
    expected_artifact_relative = expected_prefix + "artifact.json"
    expected_manifest_relative = expected_prefix + "manifest.json"
    expected_receipt_relative = expected_prefix + "receipt.json"
    if manifest.get("artifact_relative") != expected_artifact_relative:
        raise CandidateInputError("candidate manifest artifact path mismatch")
    if receipt.get("artifact_relative") not in (None, expected_artifact_relative):
        raise CandidateInputError("candidate receipt artifact path mismatch")
    if any(
        isinstance(payload.get("row_count"), bool)
        or not isinstance(payload.get("row_count"), int)
        or payload.get("row_count") != len(codes)
        for payload in (manifest, receipt)
    ):
        raise CandidateInputError("candidate component row_count mismatch")
    if any(payload.get("codes_sha256") != codes_sha for payload in (manifest, receipt)):
        raise CandidateInputError("candidate component codes SHA mismatch")
    if any(payload.get("source_projection_sha256") != projection for payload, projection in ((manifest, artifact.get("source_projection_sha256")), (receipt, artifact.get("source_projection_sha256")))):
        raise CandidateInputError("candidate component projection SHA mismatch")
    if receipt.get("manifest_sha256") != canonical_manifest_sha:
        raise CandidateInputError("candidate receipt manifest SHA mismatch")
    current_bindings = (current.get("artifact_sha256"), current.get("manifest_sha256"), current.get("receipt_sha256"))
    canonical_bindings = (canonical_artifact_sha, canonical_manifest_sha, canonical_receipt_sha)
    if current_bindings != canonical_bindings:
        raise CandidateInputError("candidate current JSON SHA bindings mismatch")
    if manifest.get("artifact_sha256") != canonical_artifact_sha or receipt.get("artifact_sha256") != canonical_artifact_sha:
        raise CandidateInputError("candidate component SHA bindings mismatch")
    if (
        isinstance(current.get("row_count"), bool)
        or not isinstance(current.get("row_count"), int)
        or current.get("row_count") != len(codes)
        or current.get("codes_sha256") != codes_sha
        or current.get("source_projection_sha256") != artifact.get("source_projection_sha256")
    ):
        raise CandidateInputError("candidate current field bindings mismatch")
    states = resolve_market_states(trade_date)
    if states["a_share"] is TradingDayState.UNKNOWN or states["hk_connect"] is TradingDayState.UNKNOWN:
        raise CandidateInputError("market calendar unknown for trade_date")
    projection_sha = _require_sha(artifact, "source_projection_sha256", "candidate artifact")
    if artifact.get("source_projection_row_count") != len(codes):
        raise CandidateInputError("candidate source projection binding mismatch")
    return CandidateInput(
        root=root_path,
        trade_date=trade_date,
        current_relative=current_relative,
        current_sha256=current_sha,
        run_id=run_id,
        codes=tuple(codes),
        artifact_sha256=canonical_artifact_sha,
        manifest_sha256=canonical_manifest_sha,
        receipt_sha256=canonical_receipt_sha,
        source_projection_sha256=projection_sha,
        source_evidence=(current_relative, expected_artifact_relative, expected_manifest_relative, expected_receipt_relative),
    )
