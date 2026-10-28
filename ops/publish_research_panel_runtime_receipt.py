"""Project verified A/H research-panel receipts into the V4 runtime graph.

Only dated producer receipts and explicitly supplied pointer/close-review
evidence are read.  The output contains lineage metadata and hashes, never the
business rows or a copy of an upstream payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from collections.abc import Mapping
from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA = "v3_5.runtime_graph.research_panel_status.v1"
SAFETY_FLAGS = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_DATE = re.compile(r"^\d{8}$")
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_CAS_FIELDS = frozenset(
    {
        "canonical_sha256",
        "supersedes_sha256",
        "attempt_status",
        "publication_status",
        "no_op",
        "degradation_rejected",
        "conflict_rejected",
        "supersession_rejected",
    }
)
_STATUS_RANK = {"CANNOT_CONFIRM": 0, "PARTIAL": 1, "READY": 2}
_MISSING = object()


class EvidenceError(ValueError):
    """Raised when an explicitly supplied evidence chain is not provable."""


def _path_text(value: Path | str) -> str:
    try:
        text = os.fspath(value)
    except TypeError as error:
        raise EvidenceError("PATH_UNSAFE") from error
    if isinstance(text, bytes):
        raise EvidenceError("PATH_UNSAFE")
    if "\\" in text or _WINDOWS_DRIVE.match(text):
        raise EvidenceError("PATH_UNSAFE")
    return text


def _absolute_unresolved(value: Path | str) -> Path:
    text = os.path.expanduser(_path_text(value))
    path = Path(os.path.abspath(text))
    lowered = {part.casefold() for part in path.parts}
    if "desktop" in lowered or "windows" in lowered:
        raise EvidenceError("PATH_UNSAFE")
    _assert_no_symlink_ancestors(path)
    return path


def _assert_no_symlink_ancestors(path: Path) -> None:
    absolute = Path(os.path.abspath(str(path)))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise EvidenceError("PATH_UNSAFE") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise EvidenceError("PATH_UNSAFE")


def _within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path), str(root))) == str(root)
    except ValueError:
        return False


def _is_documents_candidate_path(path: Path) -> bool:
    base = Path("/Users/lexi/Documents/Codex/2026-08-13")
    try:
        relative = path.relative_to(base)
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0].startswith("v35-stage-selection-")


def _formal_data_root() -> Path:
    return Path.home() / "Library" / "Application Support" / "com.lexi.v4.local" / "state" / "data"


def _formal_app_root() -> Path:
    return _formal_data_root().parents[1]


def _allowed_data_root(value: Path | str) -> Path:
    path = _absolute_unresolved(value)
    formal = _formal_data_root()
    if not (_within(path, formal) or _is_documents_candidate_path(path)):
        raise EvidenceError("PATH_UNSAFE")
    return path


def _allowed_input_path(value: Path | str) -> Path:
    path = _absolute_unresolved(value)
    app_root = _formal_app_root()
    if not (_within(path, app_root) or _is_documents_candidate_path(path)):
        raise EvidenceError("PATH_UNSAFE")
    return path


def _date(value: Any) -> str:
    text = str(value or "")
    if not _DATE.fullmatch(text):
        raise EvidenceError("DATE_INVALID")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise EvidenceError("DATE_INVALID") from error
    return text


def _read_json(path: Path) -> dict[str, Any]:
    _assert_no_symlink_ancestors(path)
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"EVIDENCE_FILE_UNAVAILABLE:{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"EVIDENCE_JSON_UNREADABLE:{path}") from error
    if not isinstance(payload, Mapping):
        raise EvidenceError(f"EVIDENCE_JSON_NOT_OBJECT:{path}")
    return dict(payload)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as error:
        raise EvidenceError(f"EVIDENCE_FILE_UNREADABLE:{path}") from error
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    _assert_no_symlink_ancestors(path.parent)
    if path.is_symlink():
        raise EvidenceError(f"OUTPUT_PATH_UNSAFE:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_false(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(name) is False for name in SAFETY_FLAGS)


def _exact_producer_receipt(root: Path | str, lane: str, business_date: str) -> Path:
    base = _allowed_input_path(root)
    path = _allowed_input_path(base / f"{lane.lower()}-{business_date}.json")
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"PRODUCER_RECEIPT_MISSING:{lane}:{business_date}")
    return path


_DATE_FIELDS = frozenset(("trade_date", "target_date", "business_date", "signal_date"))


def _normalise_artifact_date(value: Any) -> str:
    if isinstance(value, (datetime, date_type)):
        text = value.isoformat()
    else:
        text = str(value).strip()
    compact = re.sub(r"[^0-9]", "", text)
    candidate = compact[:8]
    if not _DATE.fullmatch(candidate):
        raise EvidenceError("POINTER_DATE_INVALID")
    try:
        datetime.strptime(candidate, "%Y%m%d")
    except ValueError as error:
        raise EvidenceError("POINTER_DATE_INVALID") from error
    return candidate


def _artifact_dates(path: Path) -> set[str]:
    """Read all valid date-column values from a pointed artifact."""

    if path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as parquet

            schema_names = set(parquet.read_schema(path).names)
            date_column = next(
                (name for name in ("trade_date", "target_date", "business_date", "signal_date") if name in schema_names),
                None,
            )
            if date_column is None:
                return set()
            values = parquet.read_table(path, columns=[date_column]).column(date_column).to_pylist()
            return {_normalise_artifact_date(value) for value in values if value is not None}
        except Exception as error:
            raise EvidenceError(f"POINTER_ARTIFACT_UNREADABLE:{path}") from error
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"POINTER_ARTIFACT_UNREADABLE:{path}") from error
    values: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in _DATE_FIELDS and child not in (None, ""):
                    if isinstance(child, list):
                        values.update(_normalise_artifact_date(item) for item in child if item not in (None, ""))
                    else:
                        values.add(_normalise_artifact_date(child))
                if isinstance(child, Mapping | list):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return values


def _pointer_evidence(pointer: Path | str | None, business_date: str, role: str) -> dict[str, Any]:
    if pointer is None:
        raise EvidenceError(f"{role.upper()}_POINTER_MISSING")
    try:
        pointer_path = _allowed_input_path(pointer)
    except EvidenceError as error:
        try:
            lexical_pointer = Path(os.path.abspath(os.path.expanduser(_path_text(pointer))))
        except (EvidenceError, TypeError, ValueError):
            lexical_pointer = None
        if lexical_pointer is not None and lexical_pointer.is_symlink():
            raise EvidenceError(f"{role.upper()}_POINTER_UNAVAILABLE") from error
        raise EvidenceError(f"{role.upper()}_POINTER_UNSAFE") from error
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise EvidenceError(f"{role.upper()}_POINTER_UNAVAILABLE")
    try:
        raw = pointer_path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as error:
        raise EvidenceError(f"{role.upper()}_POINTER_UNREADABLE") from error
    target_text = raw
    if raw.startswith("{"):
        try:
            pointer_payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise EvidenceError(f"{role.upper()}_POINTER_MALFORMED") from error
        if not isinstance(pointer_payload, Mapping):
            raise EvidenceError(f"{role.upper()}_POINTER_MALFORMED")
        target_text = str(
            pointer_payload.get("artifact_path")
            or pointer_payload.get("path")
            or pointer_payload.get("target")
            or ""
        )
    if not target_text:
        raise EvidenceError(f"{role.upper()}_POINTER_TARGET_MISSING")
    try:
        target = Path(target_text).expanduser()
        if not target.is_absolute():
            target = pointer_path.parent / target
        target = _allowed_input_path(target)
    except (EvidenceError, TypeError, ValueError) as error:
        raise EvidenceError(f"{role.upper()}_POINTER_TARGET_UNSAFE") from error
    if target.is_symlink() or not target.is_file():
        raise EvidenceError(f"{role.upper()}_POINTER_TARGET_UNAVAILABLE")
    dates = _artifact_dates(target)
    if not dates:
        raise EvidenceError(f"{role.upper()}_POINTER_DATE_COLUMN_MISSING")
    minimum, maximum = min(dates), max(dates)
    if maximum > business_date:
        raise EvidenceError(
            f"{role.upper()}_POINTER_DATE_AFTER_TARGET:min={minimum}:max={maximum}:count={len(dates)}"
        )
    if maximum < business_date:
        raise EvidenceError(
            f"{role.upper()}_POINTER_DATE_BEFORE_TARGET:min={minimum}:max={maximum}:count={len(dates)}"
        )
    return {
        "pointer_path": str(pointer_path),
        "artifact_path": str(target),
        "artifact_sha256": _sha256(target),
        "artifact_date": business_date,
    }


def _finite_number(value: Any, field: str, *, minimum: float = 0.0, maximum: float | None = None, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EvidenceError(f"{field}_NUMERIC_INVALID")
    number = float(value)
    if not math.isfinite(number) or number < minimum or (maximum is not None and number > maximum):
        raise EvidenceError(f"{field}_NUMERIC_INVALID")
    if integer and number != math.floor(number):
        raise EvidenceError(f"{field}_NUMERIC_INVALID")
    return int(number) if integer else number


def _a_row_count(receipt: Mapping[str, Any]) -> tuple[int, str, int | None]:
    if "row_count" in receipt and receipt.get("row_count") is not None:
        return int(_finite_number(receipt.get("row_count"), "A_ROW_COUNT", integer=True)), "receipt.row_count", None
    formula = receipt.get("formula")
    sync = receipt.get("sync")
    authority = formula.get("authority") if isinstance(formula, Mapping) else None
    selector_rows = authority.get("selector_increment_rows") if isinstance(authority, Mapping) else None
    file_count = sync.get("target_date_file_count") if isinstance(sync, Mapping) else None
    if selector_rows is not None and file_count is not None:
        projected = int(_finite_number(selector_rows, "A_SELECTOR_INCREMENT_ROWS", integer=True))
        verified_files = int(_finite_number(file_count, "A_TARGET_DATE_FILE_COUNT", integer=True))
        if verified_files > 0:
            return projected, "formula.authority.selector_increment_rows", verified_files
    return 0, "unavailable", None


def _validate_date_fields(payload: Mapping[str, Any], expected: str, *, prefix: str) -> None:
    for field in ("through_date", "target_date", "date"):
        if field in payload and str(payload[field]) != expected:
            raise EvidenceError(f"{prefix}_DATE_MISMATCH:{field}")


def _validate_hash_fields(payload: Mapping[str, Any], *, prefix: str, allow_empty: bool = False) -> None:
    for field in ("sha256", "source_sha256", "panel_sha256"):
        if field not in payload:
            continue
        if not isinstance(payload[field], str):
            raise EvidenceError(f"{prefix}_HASH_INVALID:{field}")
        if allow_empty and payload[field] == "":
            continue
        if not _SHA256.fullmatch(payload[field]):
            raise EvidenceError(f"{prefix}_HASH_INVALID:{field}")


def _canonical_sha(payload: Mapping[str, Any]) -> str:
    canonical = {key: value for key, value in payload.items() if key not in _CAS_FIELDS}
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _nested_rebuild_reason(value: Any) -> str:
    if isinstance(value, Mapping):
        if value.get("authority_status") == "REBUILD_REQUIRED":
            return "SYNC_AUTHORITY_REBUILD_REQUIRED"
        if value.get("quarantined_rebuild_symbols") not in (None, 0, "0"):
            return "SYNC_QUARANTINED_REBUILD_SYMBOLS"
        if value.get("rebuild_candidates_promoted") is False:
            return "SYNC_REBUILD_CANDIDATES_NOT_PROMOTED"
        for key, child in value.items():
            reason = _nested_rebuild_reason(child)
            if reason:
                return reason
    elif isinstance(value, list):
        for child in value:
            reason = _nested_rebuild_reason(child)
            if reason:
                return reason
    return ""


def _base(node_id: str, business_date: str, source: Path, source_sha: str, *, status: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "node_id": node_id,
        "business_date": business_date,
        "status": status,
        "effective_status": status,
        "reason": reason,
        "source_receipt_path": str(source),
        "source_receipt_sha256": source_sha,
        "row_count": 0,
        "coverage_rate": 0.0,
        **SAFETY_FLAGS,
    }


def _publish_a(
    business_date: str,
    producer_receipt_root: Path | str,
    selector_pointer: Path | str | None,
    backtest_pointer: Path | str | None,
) -> dict[str, Any]:
    try:
        source = _exact_producer_receipt(producer_receipt_root, "A", business_date)
        source_sha = _sha256(source)
        receipt = _read_json(source)
        if receipt.get("target_date") != business_date:
            raise EvidenceError("A_RECEIPT_DATE_MISMATCH")
        if receipt.get("status") != "READY":
            raise EvidenceError(f"A_PRODUCER_NOT_READY:{receipt.get('status')}")
        if not _safe_false(receipt):
            raise EvidenceError("A_RECEIPT_SAFETY_MISMATCH")
        _validate_date_fields(receipt, business_date, prefix="A_RECEIPT")
        _validate_hash_fields(receipt, prefix="A_RECEIPT", allow_empty=True)
        selector = _pointer_evidence(selector_pointer, business_date, "selector")
        backtest = _pointer_evidence(backtest_pointer, business_date, "backtest")
        reason = _nested_rebuild_reason(receipt.get("sync", receipt))
        status = "PARTIAL" if reason else "READY"
        result = _base("ashare_research_panel", business_date, source, source_sha, status=status, reason=reason or "READY")
        row_count, row_count_source, row_count_authority_file_count = _a_row_count(receipt)
        coverage_unavailable = "coverage_rate" not in receipt or receipt.get("coverage_rate") is None
        coverage_rate = (
            0.0
            if coverage_unavailable
            else _finite_number(receipt.get("coverage_rate"), "A_COVERAGE_RATE", maximum=1.0)
        )
        if row_count_source == "unavailable":
            result["reason"] = f"{result['reason']};A_ROW_COUNT_UNAVAILABLE"
        if coverage_unavailable:
            result["reason"] = f"{result['reason']};A_COVERAGE_UNAVAILABLE"
        result.update(
            {
                "row_count": row_count,
                "coverage_rate": coverage_rate,
                "row_count_source": row_count_source,
                "selector_pointer_path": selector["pointer_path"],
                "selector_artifact_path": selector["artifact_path"],
                "selector_artifact_sha256": selector["artifact_sha256"],
                "backtest_pointer_path": backtest["pointer_path"],
                "backtest_artifact_path": backtest["artifact_path"],
                "backtest_artifact_sha256": backtest["artifact_sha256"],
                "sync_authority_status": (receipt.get("sync") or {}).get("authority_status") if isinstance(receipt.get("sync"), Mapping) else None,
            }
        )
        if row_count_authority_file_count is not None:
            result["row_count_authority_file_count"] = row_count_authority_file_count
        return result
    except (EvidenceError, TypeError, ValueError) as error:
        try:
            source = _exact_producer_receipt(producer_receipt_root, "A", business_date)
            source_sha = _sha256(source)
        except EvidenceError:
            source = Path(os.path.abspath(os.path.expanduser(str(producer_receipt_root)))) / f"a-{business_date}.json"
            source_sha = ""
        return _base("ashare_research_panel", business_date, source, source_sha, status="CANNOT_CONFIRM", reason=str(error))


def _close_review_evidence(
    business_date: str,
    review_path: Path | str | None,
    receipt_path: Path | str | None,
) -> dict[str, Any]:
    if review_path is None or receipt_path is None:
        raise EvidenceError("HK_CLOSE_REVIEW_RECEIPT_MISSING")
    review = _allowed_input_path(review_path)
    receipt = _allowed_input_path(receipt_path)
    payload = _read_json(review)
    if payload.get("trade_date") != business_date:
        raise EvidenceError("HK_CLOSE_REVIEW_DATE_MISMATCH")
    if payload.get("status") != "MODEL_REVIEW_READY":
        raise EvidenceError(f"HK_CLOSE_REVIEW_NOT_READY:{payload.get('status')}")
    if not _safe_false(payload):
        raise EvidenceError("HK_CLOSE_REVIEW_SAFETY_MISMATCH")
    review_sha = _sha256(review)
    receipt_payload = _read_json(receipt)
    if (
        receipt_payload.get("trade_date") != business_date
        or receipt_payload.get("source_sha256") != review_sha
        or Path(str(receipt_payload.get("payload_path") or "")).name != review.name
    ):
        raise EvidenceError("HK_CLOSE_REVIEW_RECEIPT_MISMATCH")
    return {
        "close_review_path": str(review),
        "close_review_sha256": review_sha,
        "close_review_receipt_path": str(receipt),
        "close_review_receipt_sha256": _sha256(receipt),
    }


def _publish_hk(
    business_date: str,
    producer_receipt_root: Path | str,
    close_review_path: Path | str | None,
    close_review_receipt_path: Path | str | None,
) -> dict[str, Any]:
    try:
        source = _exact_producer_receipt(producer_receipt_root, "HK", business_date)
        source_sha = _sha256(source)
        receipt = _read_json(source)
        if receipt.get("target_date") != business_date:
            raise EvidenceError("HK_RECEIPT_DATE_MISMATCH")
        if receipt.get("status") != "READY":
            raise EvidenceError(f"HK_PRODUCER_NOT_READY:{receipt.get('status')}")
        if not _safe_false(receipt):
            raise EvidenceError("HK_RECEIPT_SAFETY_MISMATCH")
        _validate_date_fields(receipt, business_date, prefix="HK_RECEIPT")
        _validate_hash_fields(receipt, prefix="HK_RECEIPT")
        authority = receipt.get("authority")
        if authority is not None:
            if not isinstance(authority, Mapping):
                raise EvidenceError("HK_AUTHORITY_INVALID")
            _validate_date_fields(authority, business_date, prefix="HK_AUTHORITY")
            _validate_hash_fields(authority, prefix="HK_AUTHORITY")
        row_count = int(_finite_number(receipt.get("row_count"), "HK_ROW_COUNT", integer=True))
        coverage_rate = _finite_number(receipt.get("coverage_rate"), "HK_COVERAGE_RATE", maximum=1.0)
        digest = next(
            (str(receipt.get(field)) for field in ("sha256", "panel_sha256", "source_sha256") if receipt.get(field) not in (None, "")),
            "",
        )
        if row_count <= 0 or coverage_rate <= 0.0 or not _SHA256.fullmatch(digest):
            raise EvidenceError("HK_PRODUCER_ARTIFACT_NOT_READY")
        close = _close_review_evidence(business_date, close_review_path, close_review_receipt_path)
        result = _base("hkconnect_research_panel", business_date, source, source_sha, status="READY", reason="READY")
        result.update({"row_count": row_count, "coverage_rate": coverage_rate, "producer_artifact_sha256": digest, **close})
        return result
    except (EvidenceError, TypeError, ValueError) as error:
        try:
            source = _exact_producer_receipt(producer_receipt_root, "HK", business_date)
            source_sha = _sha256(source)
        except EvidenceError:
            source = Path(os.path.abspath(os.path.expanduser(str(producer_receipt_root)))) / f"hk-{business_date}.json"
            source_sha = ""
        return _base("hkconnect_research_panel", business_date, source, source_sha, status="CANNOT_CONFIRM", reason=str(error))


def _supersedes_for_lane(value: str | Mapping[str, Any] | None, lane: str) -> str | None:
    if isinstance(value, Mapping):
        raw = value.get(lane)
    else:
        raw = value
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or not _SHA256.fullmatch(raw):
        raise EvidenceError("SUPERSEDES_SHA256_INVALID")
    return raw.lower()


def _existing_hashes(path: Path, existing: Mapping[str, Any]) -> set[str]:
    hashes = set()
    current = existing.get("canonical_sha256")
    if isinstance(current, str) and _SHA256.fullmatch(current):
        hashes.add(current.lower())
    try:
        hashes.add(_sha256(path).lower())
    except EvidenceError:
        pass
    for field in ("receipt_sha256", "canonical_sha256"):
        raw = existing.get(field)
        if isinstance(raw, str) and _SHA256.fullmatch(raw):
            hashes.add(raw.lower())
    return hashes


def _commit_lane(
    destination: Path,
    attempted: Mapping[str, Any],
    *,
    supersedes_sha256: str | None,
) -> dict[str, Any]:
    candidate = dict(attempted)
    candidate["canonical_sha256"] = _canonical_sha(candidate)
    candidate.setdefault("attempt_status", candidate.get("status"))
    candidate.setdefault("degradation_rejected", False)
    candidate.setdefault("conflict_rejected", False)
    candidate.setdefault("supersession_rejected", False)
    candidate.setdefault("no_op", False)
    _assert_no_symlink_ancestors(destination.parent)
    if destination.is_symlink():
        raise EvidenceError(f"OUTPUT_PATH_UNSAFE:{destination}")
    if not destination.exists():
        candidate["publication_status"] = "PUBLISHED"
        _atomic_json(destination, candidate)
        return candidate
    existing = _read_json(destination)
    existing_status = str(existing.get("effective_status") or existing.get("status") or "")
    if existing_status not in _STATUS_RANK or existing.get("business_date") != candidate.get("business_date") or existing.get("node_id") != candidate.get("node_id"):
        candidate.update(
            {
                "attempt_status": candidate.get("status"),
                "reason": "CONFLICT_REJECTED:EXISTING_RECEIPT_IDENTITY_INVALID",
                "conflict_rejected": True,
                "publication_status": "CONFLICT_REJECTED",
            }
        )
        return candidate
    existing_canonical = str(existing.get("canonical_sha256") or _canonical_sha(existing))
    if existing_canonical == candidate["canonical_sha256"]:
        candidate.update(
            {
                "no_op": True,
                "publication_status": "NOOP",
                "effective_status": existing_status or candidate.get("status"),
            }
        )
        return candidate
    candidate_status = str(candidate.get("status") or "")
    existing_rank = _STATUS_RANK.get(existing_status, -1)
    candidate_rank = _STATUS_RANK.get(candidate_status, -1)
    if existing_rank == candidate_rank:
        candidate.update(
            {
                "status": existing_status or candidate_status,
                "effective_status": existing_status or candidate_status,
                "attempt_status": candidate_status,
                "reason": f"CONFLICT_REJECTED:{candidate.get('reason') or 'PROVENANCE_CHANGED'}",
                "conflict_rejected": True,
                "publication_status": "CONFLICT_REJECTED",
            }
        )
        return candidate
    if candidate_rank > existing_rank:
        if supersedes_sha256 is None or supersedes_sha256 not in _existing_hashes(destination, existing):
            candidate.update(
                {
                    "status": existing_status or candidate_status,
                    "effective_status": existing_status or candidate_status,
                    "attempt_status": candidate_status,
                    "reason": f"SUPERSESSION_REJECTED:{candidate.get('reason') or 'SUPERSEDES_SHA256_REQUIRED'}",
                    "supersession_rejected": True,
                    "publication_status": "SUPERSESSION_REJECTED",
                }
            )
            return candidate
        candidate["supersedes_sha256"] = supersedes_sha256
        candidate["publication_status"] = "PUBLISHED"
        _atomic_json(destination, candidate)
        return candidate
    candidate.update(
        {
            "status": existing_status or candidate_status,
            "effective_status": existing_status or candidate_status,
            "attempt_status": candidate_status,
            "reason": f"DEGRADATION_REJECTED:{candidate.get('reason') or 'STATUS_REGRESSION'}",
            "degradation_rejected": True,
            "publication_status": "DEGRADATION_REJECTED",
        }
    )
    return candidate


def publish_research_panel_status(
    *,
    business_date: str,
    data_root: Path | str,
    producer_receipt_root: Path | str,
    selector_pointer: Path | str | None,
    backtest_pointer: Path | str | None,
    close_review_path: Path | str | None = None,
    close_review_receipt_path: Path | str | None = None,
    supersedes_sha256: str | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    date = _date(business_date)
    root = _allowed_data_root(data_root)
    output_dir = root / "runtime_graph" / "evidence" / "research_panel_status" / date
    a_status = _publish_a(date, producer_receipt_root, selector_pointer, backtest_pointer)
    hk_status = _publish_hk(date, producer_receipt_root, close_review_path, close_review_receipt_path)
    destinations = {
        "A": output_dir / "ashare_research_panel.json",
        "HK": output_dir / "hkconnect_research_panel.json",
    }
    a_supersedes = _supersedes_for_lane(supersedes_sha256, "A")
    hk_supersedes = _supersedes_for_lane(supersedes_sha256, "HK")
    a_status = _commit_lane(destinations["A"], a_status, supersedes_sha256=a_supersedes)
    hk_status = _commit_lane(destinations["HK"], hk_status, supersedes_sha256=hk_supersedes)
    return {
        "schema_version": SCHEMA,
        "business_date": date,
        "lanes": {"A": a_status, "HK": hk_status},
        "paths": {lane: str(path) for lane, path in destinations.items()},
        **SAFETY_FLAGS,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish research-panel runtime evidence metadata")
    parser.add_argument("--date", required=True)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--producer-receipt-root", required=True, type=Path)
    parser.add_argument("--selector-pointer", required=True, type=Path)
    parser.add_argument("--backtest-pointer", required=True, type=Path)
    parser.add_argument("--close-review-path", type=Path)
    parser.add_argument("--close-review-receipt", dest="close_review_receipt_path", type=Path)
    parser.add_argument("--supersedes-sha256")
    try:
        args = parser.parse_args(argv)
        result = publish_research_panel_status(
            business_date=args.date,
            data_root=args.data_root,
            producer_receipt_root=args.producer_receipt_root,
            selector_pointer=args.selector_pointer,
            backtest_pointer=args.backtest_pointer,
            close_review_path=args.close_review_path,
            close_review_receipt_path=args.close_review_receipt_path,
            supersedes_sha256=args.supersedes_sha256,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        rejected = any(
            lane.get(flag) is True
            for lane in result["lanes"].values()
            for flag in ("degradation_rejected", "conflict_rejected", "supersession_rejected")
        )
        return 0 if not rejected and result["lanes"]["A"]["status"] in {"READY", "PARTIAL"} and result["lanes"]["HK"]["status"] == "READY" else 2
    except Exception as error:
        print(json.dumps({"schema_version": SCHEMA, "status": "CANNOT_CONFIRM", "reason": str(error), **SAFETY_FLAGS}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
