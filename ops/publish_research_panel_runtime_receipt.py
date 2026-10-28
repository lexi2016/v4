"""Project verified A/H research-panel receipts into the V3.5 runtime graph.

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

from infrastructure.formula_generation import (
    FormulaGenerationError,
    V4_FORMULA_STATE_OWNER,
    V4_STATE_ROOT,
    is_v4_formula_state_path,
    read_formula_generation,
)

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))



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
    from ops._publish_research_panel_runtime_receipt_parts.cli import __assert_no_symlink_ancestors_body as _v4_impl
    return _v4_impl(globals(), path)


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
    return Path.home() / "Library" / "Application Support" / "com.lexi.v35.local" / "state" / "data"


def _formal_app_root() -> Path:
    return _formal_data_root().parents[1]


def _v4_data_root() -> Path:
    return V4_STATE_ROOT / "data"


def _allowed_data_root(value: Path | str) -> Path:
    path = _absolute_unresolved(value)
    formal = _formal_data_root()
    if not (
        _within(path, formal)
        or _within(path, _v4_data_root())
        or _is_documents_candidate_path(path)
    ):
        raise EvidenceError("PATH_UNSAFE")
    return path


def _allowed_input_path(value: Path | str) -> Path:
    path = _absolute_unresolved(value)
    app_root = _formal_app_root()
    if not (
        _within(path, app_root)
        or is_v4_formula_state_path(path)
        or _within(path, _v4_data_root())
        or _is_documents_candidate_path(path)
    ):
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
    from ops._publish_research_panel_runtime_receipt_parts.cli import __atomic_json_body as _v4_impl
    return _v4_impl(globals(), path, payload)


def _safe_false(payload: Mapping[str, Any]) -> bool:
    return all(payload.get(name) is False for name in SAFETY_FLAGS)


def _exact_producer_receipt(root: Path | str, lane: str, business_date: str) -> Path:
    base = _allowed_input_path(root)
    path = _allowed_input_path(base / f"{lane.lower()}-{business_date}.json")
    if path.is_symlink() or not path.is_file():
        raise EvidenceError(f"PRODUCER_RECEIPT_MISSING:{lane}:{business_date}")
    return path


def _validate_a_producer_receipt_root(value: Path | str) -> Path:
    """Validate the A-only producer receipt root against the V4 owner.

    The shared producer root remains compatible with the HK lane.  The
    optional A-specific root is narrower: it must be an existing V4 formula
    owner descendant, and the shared predicate must inspect the raw path
    before any path normalization can hide traversal or symlink ancestry.
    """
    if not is_v4_formula_state_path(value, allow_owner=False):
        raise EvidenceError("A_PRODUCER_RECEIPT_ROOT_UNSAFE")
    return _absolute_unresolved(value)


def _exact_a_producer_receipt(
    root: Path | str,
    lane: str,
    business_date: str,
    *,
    owner_bound: bool,
) -> Path:
    validated_root = _validate_a_producer_receipt_root(root) if owner_bound else root
    return _exact_producer_receipt(validated_root, lane, business_date)


_DATE_FIELDS = frozenset(("trade_date", "target_date", "business_date", "signal_date"))


def _normalise_artifact_date(value: Any) -> str:
    from ops._publish_research_panel_runtime_receipt_parts.cli import __normalise_artifact_date_body as _v4_impl
    return _v4_impl(globals(), value)


def _artifact_dates(path: Path) -> set[str]:
    """Read all valid date-column values from a pointed artifact."""
    from ops._publish_research_panel_runtime_receipt_parts.cli import __artifact_dates_body as _v4_impl
    return _v4_impl(globals(), path)


def _pointer_evidence(pointer: Path | str | None, business_date: str, role: str) -> dict[str, Any]:
    from ops._publish_research_panel_runtime_receipt_parts.cli import __pointer_evidence_body as _v4_impl
    return _v4_impl(globals(), pointer, business_date, role)


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
    from ops._publish_research_panel_runtime_receipt_parts.cli import __a_row_count_body as _v4_impl
    return _v4_impl(globals(), receipt)


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
    from ops._publish_research_panel_runtime_receipt_parts.cli import __nested_rebuild_reason_body as _v4_impl
    return _v4_impl(globals(), value)


def _base(node_id: str, business_date: str, source: Path, source_sha: str, *, status: str, reason: str) -> dict[str, Any]:
    from ops._publish_research_panel_runtime_receipt_parts.cli import __base_body as _v4_impl
    return _v4_impl(globals(), node_id, business_date, source, source_sha, status=status, reason=reason)


def _publish_a(
    business_date: str,
    producer_receipt_root: Path | str,
    selector_pointer: Path | str | None,
    backtest_pointer: Path | str | None,
    formula_generation_pointer: Path | str | None = None,
    *,
    owner_bound: bool = False,
) -> dict[str, Any]:
    from ops._publish_research_panel_runtime_receipt_parts.a_receipts import __publish_a_body as _v4_impl
    return _v4_impl(globals(), business_date, producer_receipt_root, selector_pointer, backtest_pointer, formula_generation_pointer, owner_bound=owner_bound)


def _close_review_evidence(
    business_date: str,
    review_path: Path | str | None,
    receipt_path: Path | str | None,
) -> dict[str, Any]:
    from ops._publish_research_panel_runtime_receipt_parts.cli import __close_review_evidence_body as _v4_impl
    return _v4_impl(globals(), business_date, review_path, receipt_path)


def _publish_hk(
    business_date: str,
    producer_receipt_root: Path | str,
    close_review_path: Path | str | None,
    close_review_receipt_path: Path | str | None,
) -> dict[str, Any]:
    from ops._publish_research_panel_runtime_receipt_parts.hk_receipts import __publish_hk_body as _v4_impl
    return _v4_impl(globals(), business_date, producer_receipt_root, close_review_path, close_review_receipt_path)


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
    from ops._publish_research_panel_runtime_receipt_parts.cli import __existing_hashes_body as _v4_impl
    return _v4_impl(globals(), path, existing)


def _commit_lane(
    destination: Path,
    attempted: Mapping[str, Any],
    *,
    supersedes_sha256: str | None,
) -> dict[str, Any]:
    from ops._publish_research_panel_runtime_receipt_parts.cli import __commit_lane_body as _v4_impl
    return _v4_impl(globals(), destination, attempted, supersedes_sha256=supersedes_sha256)


def publish_research_panel_status(
    *,
    business_date: str,
    data_root: Path | str,
    producer_receipt_root: Path | str,
    a_producer_receipt_root: Path | str | None = None,
    selector_pointer: Path | str | None,
    backtest_pointer: Path | str | None,
    formula_generation_pointer: Path | str | None = None,
    close_review_path: Path | str | None = None,
    close_review_receipt_path: Path | str | None = None,
    supersedes_sha256: str | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from ops._publish_research_panel_runtime_receipt_parts.receipt_publish import _publish_research_panel_status_body as _v4_impl
    return _v4_impl(globals(), business_date=business_date, data_root=data_root, producer_receipt_root=producer_receipt_root, a_producer_receipt_root=a_producer_receipt_root, selector_pointer=selector_pointer, backtest_pointer=backtest_pointer, formula_generation_pointer=formula_generation_pointer, close_review_path=close_review_path, close_review_receipt_path=close_review_receipt_path, supersedes_sha256=supersedes_sha256)


def main(argv: list[str] | None = None) -> int:
    from ops._publish_research_panel_runtime_receipt_parts.cli import _main_body as _v4_impl
    return _v4_impl(globals(), argv)


if __name__ == "__main__":
    raise SystemExit(main())
