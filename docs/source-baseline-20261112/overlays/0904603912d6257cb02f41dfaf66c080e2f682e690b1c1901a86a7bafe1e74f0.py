"""Read-only verification for one V4 formula generation.

``CURRENT_FORMULA_GENERATION.json`` is the authority for a selector/backtest
pair.  The legacy text pointers remain compatibility projections and are
never sufficient to grant strict readiness.  This module deliberately has no
publication or producer logic; callers may use it at the public entry,
registry, publisher, and daily-consumer boundaries.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


FORMULA_GENERATION_SCHEMA = "v4.a_formula.generation_pointer.v1"
FORMULA_GENERATION_POINTER_NAME = "CURRENT_FORMULA_GENERATION.json"
V4_STATE_ROOT = Path.home() / "Library" / "Application Support" / "com.lexi.v4.local" / "state"
V4_FORMULA_STATE_OWNER = V4_STATE_ROOT / "data" / "a_formula"
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,160}$")


class FormulaGenerationError(ValueError):
    """Raised when a generation or one of its bound artifacts is unsafe."""


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _normalise_date(value: Any, label: str) -> str:
    text = str(value or "").strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        raise FormulaGenerationError(f"{label} is not an exact YYYYMMDD date")
    try:
        import datetime as _datetime

        _datetime.datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise FormulaGenerationError(f"{label} is not a calendar date") from error
    return text


def _has_symlink_ancestor(path: Path) -> bool:
    path = Path(path).expanduser()
    current = path if path.exists() or path.is_symlink() else path.parent
    while True:
        if current.is_symlink():
            return True
        if current.parent == current:
            return False
        current = current.parent


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def is_v4_formula_state_path(value: Path | str, *, allow_owner: bool = True) -> bool:
    """Return whether an absolute path belongs to the one V4 A owner.

    This predicate is deliberately narrower than ``Application Support``.  It
    validates the caller's raw path before resolving it, rejects traversal and
    symlink ancestry, and then permits only the designated formula state root
    or its descendants.  Callers still apply their own role-specific
    containment, schema, and write guards after this identity check.
    """

    try:
        raw_text = os.fspath(value)
    except TypeError:
        return False
    if not isinstance(raw_text, str) or not raw_text or "\\" in raw_text or "\x00" in raw_text:
        return False
    raw = Path(raw_text)
    if not raw.is_absolute() or ".." in raw.parts:
        return False
    raw = raw.expanduser()
    if _has_symlink_ancestor(raw):
        return False
    try:
        resolved = raw.resolve(strict=False)
        owner = V4_FORMULA_STATE_OWNER.expanduser().resolve(strict=False)
    except OSError:
        return False
    if not _inside(owner, resolved):
        return False
    return allow_owner or resolved != owner


def is_v4_formula_state_owner(value: Path | str) -> bool:
    """Return whether ``value`` is exactly the designated V4 formula root."""

    return is_v4_formula_state_path(value, allow_owner=True) and (
        Path(value).expanduser().resolve(strict=False)
        == V4_FORMULA_STATE_OWNER.expanduser().resolve(strict=False)
    )


def _resolve_bound_file(
    root: Path,
    detail: Mapping[str, Any],
    role: str,
    *,
    require_inside: bool = True,
) -> dict[str, Any]:
    raw_path = detail.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise FormulaGenerationError(f"generation {role} path is missing")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink() or _has_symlink_ancestor(candidate):
        raise FormulaGenerationError(f"generation {role} path has symlink ancestry")
    resolved = candidate.resolve(strict=False)
    if require_inside and not _inside(root, resolved):
        raise FormulaGenerationError(f"generation {role} path escapes output root")
    if not resolved.is_file() or resolved.is_symlink():
        raise FormulaGenerationError(f"generation {role} target is missing or not regular")
    expected_bytes = detail.get("bytes")
    expected_sha = detail.get("sha256")
    if type(expected_bytes) is not int or expected_bytes != resolved.stat().st_size:
        raise FormulaGenerationError(f"generation {role} bytes mismatch")
    if not isinstance(expected_sha, str) or not _SHA256.fullmatch(expected_sha):
        raise FormulaGenerationError(f"generation {role} SHA is invalid")
    actual_sha = _sha256_file(resolved)
    if actual_sha != expected_sha.lower():
        raise FormulaGenerationError(f"generation {role} SHA mismatch")
    return {
        "path": resolved,
        "bytes": expected_bytes,
        "sha256": actual_sha,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parquet_dates(path: Path) -> set[str]:
    try:
        import pyarrow.parquet as parquet

        parquet_file = parquet.ParquetFile(path)
        if "trade_date" not in parquet_file.schema.names:
            raise FormulaGenerationError("generation artifact trade_date column is missing")
        dates: set[str] = set()
        for batch in parquet_file.iter_batches(columns=["trade_date"], batch_size=100_000):
            for value in batch.column(0).to_pylist():
                dates.add(_normalise_date(value, "generation artifact trade_date"))
        if not dates:
            raise FormulaGenerationError("generation artifact trade_date column is empty")
        return dates
    except FormulaGenerationError:
        raise
    except Exception as error:
        raise FormulaGenerationError(f"generation artifact date audit failed: {path}") from error


def read_legacy_pointer(pointer: Path | str) -> Path:
    """Read one compatibility text pointer without accepting symlinks."""
    pointer_path = Path(pointer).expanduser()
    if _has_symlink_ancestor(pointer_path) or pointer_path.is_symlink() or not pointer_path.is_file():
        raise FormulaGenerationError("legacy pointer is missing or symlinked")
    try:
        raw = pointer_path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as error:
        raise FormulaGenerationError("legacy pointer is unreadable") from error
    if not raw:
        raise FormulaGenerationError("legacy pointer is empty")
    target = Path(raw).expanduser()
    if not target.is_absolute():
        target = pointer_path.parent / target
    if _has_symlink_ancestor(target) or target.is_symlink() or not target.is_file():
        raise FormulaGenerationError("legacy pointer target is missing or symlinked")
    return target.resolve()


def read_formula_generation(
    pointer: Path | str,
    *,
    expected_target_date: str | int | None = None,
    require_source: bool = False,
) -> dict[str, Any]:
    """Read and verify a generation pointer and its bound artifact files.

    ``require_source`` is used by strict V4 consumers.  It requires the same
    generation to carry the input manifest, source identity, selector source,
    and auxiliary sidecar provenance needed by the V192 consumer.  Older
    direct unit fixtures may call this reader without that strict requirement.
    """
    raw_pointer = Path(pointer).expanduser()
    pointer_path = raw_pointer / FORMULA_GENERATION_POINTER_NAME if raw_pointer.is_dir() else raw_pointer
    if _has_symlink_ancestor(pointer_path) or pointer_path.is_symlink() or not pointer_path.is_file():
        raise FormulaGenerationError("formula generation pointer is missing or symlinked")
    root = pointer_path.parent.resolve()
    try:
        raw = pointer_path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise FormulaGenerationError("formula generation pointer is unreadable") from error
    if not isinstance(payload, dict):
        raise FormulaGenerationError("formula generation pointer must be an object")
    if payload.get("schema") != FORMULA_GENERATION_SCHEMA or payload.get("status") != "READY":
        raise FormulaGenerationError("formula generation schema/status is invalid")

    identity = {"selector": payload.get("selector"), "backtest": payload.get("backtest")}
    generation_id = payload.get("generation_id")
    expected_id = _sha256_bytes(_canonical_bytes(identity))
    if not isinstance(generation_id, str) or generation_id != expected_id:
        raise FormulaGenerationError("formula generation identity mismatch")
    selector_detail = payload.get("selector")
    backtest_detail = payload.get("backtest")
    if not isinstance(selector_detail, Mapping) or not isinstance(backtest_detail, Mapping):
        raise FormulaGenerationError("formula generation selector/backtest metadata is missing")
    selector = _resolve_bound_file(root, selector_detail, "selector")
    backtest = _resolve_bound_file(root, backtest_detail, "backtest")
    if selector["path"] == backtest["path"]:
        raise FormulaGenerationError("formula generation selector/backtest targets must differ")

    expected_date = None
    if expected_target_date is not None:
        expected_date = _normalise_date(expected_target_date, "expected_target_date")
        payload_date = _normalise_date(payload.get("target_date"), "generation target_date")
        if payload_date != expected_date:
            raise FormulaGenerationError(
                f"formula generation target_date mismatch: {payload_date} != {expected_date}"
            )
        for role, detail in (("selector", selector), ("backtest", backtest)):
            if expected_date not in _parquet_dates(detail["path"]):
                raise FormulaGenerationError(f"generation {role} has no exact target-date rows")

    result: dict[str, Any] = {
        "path": pointer_path.resolve(),
        "schema": payload["schema"],
        "status": payload["status"],
        "sha256": _sha256_bytes(raw),
        "bytes": len(raw),
        "generation_id": generation_id,
        "target_date": expected_date or payload.get("target_date"),
        "run_id": payload.get("run_id"),
        "selector": selector["path"],
        "backtest": backtest["path"],
        "selector_evidence": selector,
        "backtest_evidence": backtest,
        "source": payload.get("source"),
        "input_manifest": payload.get("input_manifest"),
    }

    if require_source:
        run_id = payload.get("run_id")
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise FormulaGenerationError("formula generation run_id is missing or unsafe")
        source = payload.get("source")
        if not isinstance(source, Mapping) or not str(source.get("name") or "").strip():
            raise FormulaGenerationError("formula generation source identity is missing")
        manifest = payload.get("input_manifest")
        if not isinstance(manifest, Mapping):
            raise FormulaGenerationError("formula generation input manifest identity is missing")
        # A strict V4 generation is self-contained: the manifest that names
        # its exact input must live below the same owned root as the pointer.
        # This prevents a legacy release or unrelated state tree from
        # satisfying the source contract by path alone.
        manifest_path = _resolve_bound_file(root, manifest, "input_manifest")
        if manifest_path["sha256"] != str(manifest.get("sha256") or "").lower():
            raise FormulaGenerationError("formula generation input manifest SHA mismatch")
        try:
            manifest_payload = json.loads(manifest_path["path"].read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise FormulaGenerationError("formula generation input manifest is unreadable") from error
        if not isinstance(manifest_payload, Mapping):
            raise FormulaGenerationError("formula generation input manifest is not an object")
        bound_manifest_sha = manifest.get("manifest_sha256")
        if not isinstance(bound_manifest_sha, str) or manifest_payload.get("manifest_sha256") != bound_manifest_sha:
            raise FormulaGenerationError("formula generation input manifest canonical SHA mismatch")
        if expected_date is not None and str(manifest_payload.get("target_date") or "").replace("-", "") != expected_date:
            raise FormulaGenerationError("formula generation input manifest target date mismatch")
        source_sha = source.get("sha256") or source.get("source_sha256")
        if not isinstance(source_sha, str) or not _SHA256.fullmatch(source_sha):
            raise FormulaGenerationError("formula generation source SHA is invalid")
        if str(manifest_payload.get("source_sha256") or "").lower() != source_sha.lower():
            raise FormulaGenerationError("formula generation source and input manifest SHA mismatch")
        source_receipt_sha = source.get("sync_receipt_sha256")
        source_receipt_path = source.get("sync_receipt_path")
        if not isinstance(source_receipt_path, str) or not source_receipt_path.strip():
            raise FormulaGenerationError("formula generation sync receipt path is missing")
        if not isinstance(source_receipt_sha, str) or not _SHA256.fullmatch(source_receipt_sha):
            raise FormulaGenerationError("formula generation sync receipt SHA is invalid")
        receipt_path = Path(source_receipt_path).expanduser()
        if receipt_path.is_symlink() or _has_symlink_ancestor(receipt_path) or not receipt_path.is_file():
            raise FormulaGenerationError("formula generation sync receipt is missing or symlinked")
        receipt_resolved = receipt_path.resolve()
        if not _inside(root, receipt_resolved):
            raise FormulaGenerationError("formula generation sync receipt escapes output root")
        receipt_raw = receipt_path.read_bytes()
        if _sha256_bytes(receipt_raw) != source_receipt_sha.lower():
            raise FormulaGenerationError("formula generation sync receipt SHA mismatch")
        try:
            receipt_payload = json.loads(receipt_raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise FormulaGenerationError("formula generation sync receipt is unreadable") from error
        if not isinstance(receipt_payload, Mapping) or str(receipt_payload.get("status") or "").upper() not in {"READY", "PASS"}:
            raise FormulaGenerationError("formula generation sync receipt is not READY")
        if expected_date is not None and str(receipt_payload.get("target_date") or "").replace("-", "") != expected_date:
            raise FormulaGenerationError("formula generation sync receipt target date mismatch")
        if any(receipt_payload.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
            raise FormulaGenerationError("formula generation sync receipt safety flags are not false")
        source_detail = payload.get("selector_source")
        sidecar_detail = payload.get("selector_sidecar")
        if not isinstance(source_detail, Mapping) or not isinstance(sidecar_detail, Mapping):
            raise FormulaGenerationError("formula generation selector source/sidecar metadata is missing")
        source_file = _resolve_bound_file(root, source_detail, "selector_source")
        sidecar_file = _resolve_bound_file(root, sidecar_detail, "selector_sidecar")
        if expected_date is not None:
            if expected_date not in _parquet_dates(source_file["path"]):
                raise FormulaGenerationError("generation selector_source has no exact target-date rows")
            if expected_date not in _parquet_dates(sidecar_file["path"]):
                raise FormulaGenerationError("generation selector_sidecar has no exact target-date rows")
        result.update(
            {
                "input_manifest_evidence": manifest_path,
                "selector_source": source_file["path"],
                "selector_source_evidence": source_file,
                "selector_sidecar": sidecar_file["path"],
                "selector_sidecar_evidence": sidecar_file,
                "strict_source_verified": True,
            }
        )
    else:
        result["strict_source_verified"] = False
    return result


__all__ = [
    "FORMULA_GENERATION_POINTER_NAME",
    "FORMULA_GENERATION_SCHEMA",
    "V4_FORMULA_STATE_OWNER",
    "V4_STATE_ROOT",
    "FormulaGenerationError",
    "is_v4_formula_state_owner",
    "is_v4_formula_state_path",
    "read_formula_generation",
    "read_legacy_pointer",
]
