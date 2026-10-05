"""Frozen, read-only V4 formula-margin shadow experiment.

This module is deliberately a small boundary around an *already materialized*
V4 HK Connect snapshot.  It does not collect quotes, calculate any formula,
call the production selector, alter a BUY gate, or create a scheduled job.
The caller supplies the real production rows and the verified H/N/U formula
states, then this module records two immutable arms:

* B: the production comparator's Top10;
* F: the same order, with a frozen formula tie-break inside the rank-10
  score-margin class only.

The close truth is a separate append-only input.  In particular, a historic
fixture or a conditional/positive-market-cap Top20 cannot satisfy the current
truth contract.  The implementation keeps that separation in code so a
retrospective archive cannot silently become a forward observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import tempfile
import uuid
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

# Preserve direct-file CLI discovery of the sibling review modules.
if __name__ == "__main__" and not __package__:
    import sys as _v4_import_sys
    from pathlib import Path as _v4_import_Path
    _v4_import_sys.path.insert(0, str(_v4_import_Path(__file__).resolve().parents[1]))



EXPERIMENT_ID = "V4_FORMULA_MARGIN_SHADOW_V1"
SCHEMA_VERSION = "v4.formula_margin_shadow.v1"
INPUT_SCHEMA_VERSION = "v4.formula_margin_shadow.input.v1"
LABEL_SCHEMA_VERSION = "v4.formula_margin_shadow.labels.v1"
RULE_VERSION = "formula_margin_shadow_v1.frozen"

TRUTH_SCOPE = "HK_CONNECT_FULL_UNIVERSE_CLOSE_GAIN_TOP20"
MARKET = "HK_CONNECT"
TOP_K = 10
TRUTH_K = 20
POOL_LIMIT = 100
FORMULA_STATES = ("H", "N", "U")
ENGINEERING_FIXTURE = "ENGINEERING_FIXTURE"
REAL_AUTHORITY = "REAL_AUTHORITY"
ADMISSION_MODES = (ENGINEERING_FIXTURE, REAL_AUTHORITY)
CAPTURE_TIME_RECEIPT_SCHEMA_VERSION = "v4.formula_margin_shadow.capture_time_receipt.v2"
CAPTURE_TIME_SOURCE = "FORMULA_MARGIN_SHADOW_CAPTURE_RUNTIME_V1"
INVOCATION_VERIFICATION_BASIS = "SELECTOR_RETURN_ENVELOPE_AND_CALLBACK_PARITY_V1"
CAPTURE_ORIGIN_DIRECT = "DIRECT_ENGINEERING_FREEZE"
CAPTURE_ORIGIN_SELECTOR = "SELECTOR_INVOCATION_CAPTURE"
INVOCATION_STATUS_DIRECT = "NOT_VERIFIED_ENGINEERING_FREEZE"
INVOCATION_STATUS_VERIFIED = "VERIFIED_SELECTOR_RETURN"
PROVENANCE_FILES = {
    "production_source": ("production_source.bin", "source_artifact"),
    "production_rule": ("production_rule.bin", "rule_artifact"),
    "d1_manifest": ("d1_manifest.bin", "d1_manifest_artifact"),
    "formula_state": ("formula_state.bin", "formula_state_artifact"),
    "formula_rule": ("formula_rule.bin", "formula_rule_artifact"),
}
SHANGHAI = ZoneInfo("Asia/Shanghai")
SHA256_LENGTH = 64

# This is the only natural forward schedule admitted by this experiment.
STAGE_CUTOFFS: dict[str, str] = {
    "STAGE_0930_0935": "09:35:05",
    "STAGE_0945_1030": "10:30:00",
    "STAGE_1445_1500": "15:00:00",
}

STAGE_CAPTURE_WINDOWS: dict[str, tuple[str, str]] = {
    "STAGE_0930_0935": ("09:30:00", "09:35:05"),
    "STAGE_0945_1030": ("09:45:00", "10:30:00"),
    "STAGE_1445_1500": ("14:45:00", "15:00:00"),
}

# hk_legacy_stage_sort_key is a descending tuple.  The first two components
# are the score-before keys and therefore are part of the equivalence class.
COMPARATOR_VERSION = "hk_legacy_stage_sort_key"
COMPARATOR_KEY_NAMES = (
    "bucket_weight",
    "no_trade_gate",
    "stage_score",
    "pct_chg",
    "volume_ratio",
)
PRE_SCORE_KEY_NAMES = COMPARATOR_KEY_NAMES[:2]

SAFETY_FLAGS = {
    "research_only": True,
    "shadow_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
    "automation_created": False,
}


class ShadowInvalid(ValueError):
    """Raised when a snapshot or label cannot satisfy the frozen contract."""


def _admission_mode(value: Mapping[str, Any] | None, *, default: str | None = ENGINEERING_FIXTURE) -> str:
    """Return the explicit truth/capture admission mode.

    The default is intentionally the engineering mode for the in-memory
    shadow builder.  A caller that wants a forward or truth admission must
    state ``REAL_AUTHORITY`` explicitly; that mode is still fail-closed until
    the existing owner membership and final-close contracts are available.
    """
    from stage_center._formula_margin_shadow_parts.capture_policy import __admission_mode_body as _v4_impl
    return _v4_impl(globals(), value, default=default)


def _runtime_capture_timestamp() -> datetime:
    """Return the Shanghai runtime clock used by a real capture.

    This private function is the only test seam.  It is deliberately not a
    CLI/operator input, so a supplied ``captured_at`` cannot prove a natural
    observation.
    """

    return datetime.now(SHANGHAI)


def _validate_runtime_capture_timestamp(value: datetime | str, trade_date: str, stage_id: str) -> datetime:
    """Validate a runtime timestamp against the exact Shanghai stage window."""
    from stage_center._formula_margin_shadow_parts.capture_policy import __validate_runtime_capture_timestamp_body as _v4_impl
    return _v4_impl(globals(), value, trade_date, stage_id)


def canonical_json(value: Any) -> bytes:
    """Return the hash/signature encoding used by every immutable artifact."""
    from stage_center._formula_margin_shadow_parts.capture_policy import _canonical_json_body as _v4_impl
    return _v4_impl(globals(), value)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != SHA256_LENGTH:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _finite(value: Any) -> float:
    if isinstance(value, bool) or value in (None, ""):
        raise ShadowInvalid("finite numeric value is required")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ShadowInvalid(f"not a numeric value: {value!r}") from error
    if not math.isfinite(result):
        raise ShadowInvalid("non-finite numeric value")
    return result


def _exact_date(value: Any, label: str) -> str:
    text = str(value or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        raise ShadowInvalid(f"{label} must be YYYYMMDD")
    try:
        date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as error:
        raise ShadowInvalid(f"{label} is not a calendar date") from error
    return text


def _parse_timestamp(value: Any, trade_date: str, label: str) -> datetime:
    """Parse an explicit Shanghai timestamp; a time-only value uses the date."""
    from stage_center._formula_margin_shadow_parts.capture_policy import __parse_timestamp_body as _v4_impl
    return _v4_impl(globals(), value, trade_date, label)


def _canonical_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        raise ShadowInvalid("security_id/code is required")
    return text


def _lane_labels(value: Any, label: str = "lane") -> tuple[str, ...]:
    """Canonicalize lane labels without guessing from a delimited string.

    A string remains one literal lane label.  A list/tuple/set is a genuine
    multi-label value and compares order-insensitively.  We never map
    ``candidate_bucket`` or ``formal_eligible`` to a lane.
    """
    from stage_center._formula_margin_shadow_parts.capture_policy import __lane_labels_body as _v4_impl
    return _v4_impl(globals(), value, label)


def _formula_state(row: Mapping[str, Any], name: str) -> str:
    value = row.get(name)
    if value not in FORMULA_STATES:
        raise ShadowInvalid(f"{name} must be exactly H, N, or U")
    return str(value)


def _bucket_weight(row: Mapping[str, Any]) -> int:
    from stage_center._formula_margin_shadow_parts.row_scoring import __bucket_weight_body as _v4_impl
    return _v4_impl(globals(), row)


def _no_trade_gate(row: Mapping[str, Any]) -> int:
    from stage_center._formula_margin_shadow_parts.capture_policy import __no_trade_gate_body as _v4_impl
    return _v4_impl(globals(), row)


def hk_legacy_stage_sort_key(row: Mapping[str, Any]) -> tuple[int, int, float, float, float]:
    """The frozen production comparator used for the HK shadow baseline.

    This is a read-only parity copy.  It intentionally does not call or
    modify the production selection module, so the shadow cannot become a
    second production selector.
    """
    from stage_center._formula_margin_shadow_parts.row_scoring import _hk_legacy_stage_sort_key_body as _v4_impl
    return _v4_impl(globals(), row)


def _row_score(row: Mapping[str, Any]) -> float:
    # ``stage_score`` is authoritative.  ``production_score`` is accepted only
    # as an explicit serialized alias; a display ``score`` is never used.
    if row.get("stage_score") not in (None, ""):
        return _finite(row.get("stage_score"))
    if row.get("production_score") not in (None, ""):
        return _finite(row.get("production_score"))
    raise ShadowInvalid("real stage_score/production_score is required")


def _source_binding(
    metadata: Mapping[str, Any],
    *,
    require_artifacts: bool = False,
    require_run_id: bool = True,
) -> dict[str, Any]:
    from stage_center._formula_margin_shadow_parts.artifact_evidence import __source_binding_body as _v4_impl
    return _v4_impl(globals(), metadata, require_artifacts=require_artifacts, require_run_id=require_run_id)


def _checked_file_artifact(
    artifact: Any,
    label: str,
    *,
    expected_sha: str | None = None,
    required: bool = False,
) -> dict[str, Any] | None:
    from stage_center._formula_margin_shadow_parts.artifact_evidence import __checked_file_artifact_body as _v4_impl
    return _v4_impl(globals(), artifact, label, expected_sha=expected_sha, required=required)


def _formula_provenance(
    metadata: Mapping[str, Any],
    trade_date: str,
    cutoff: datetime,
    *,
    require_artifact: bool = False,
) -> dict[str, Any]:
    from stage_center._formula_margin_shadow_parts.artifact_evidence import __formula_provenance_body as _v4_impl
    return _v4_impl(globals(), metadata, trade_date, cutoff, require_artifact=require_artifact)


def _verify_formula_artifact_rows(
    artifact: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Ensure persisted formula states agree with the verified artifact bytes."""
    from stage_center._formula_margin_shadow_parts.artifact_evidence import __verify_formula_artifact_rows_body as _v4_impl
    return _v4_impl(globals(), artifact, rows)


def _stage_contract(metadata: Mapping[str, Any]) -> tuple[str, str, str, datetime]:
    from stage_center._formula_margin_shadow_parts.capture_policy import __stage_contract_body as _v4_impl
    return _v4_impl(globals(), metadata)


def _validate_price(row: Mapping[str, Any], cutoff: datetime) -> dict[str, Any]:
    from stage_center._formula_margin_shadow_parts.capture_policy import __validate_price_body as _v4_impl
    return _v4_impl(globals(), row, cutoff)


def _normalise_row(row: Mapping[str, Any], cutoff: datetime) -> dict[str, Any]:
    from stage_center._formula_margin_shadow_parts.row_scoring import __normalise_row_body as _v4_impl
    return _v4_impl(globals(), row, cutoff)


def _validate_rows(rows: Sequence[Mapping[str, Any]], cutoff: datetime, *, require_full_pool: bool) -> list[dict[str, Any]]:
    from stage_center._formula_margin_shadow_parts.row_scoring import __validate_rows_body as _v4_impl
    return _v4_impl(globals(), rows, cutoff, require_full_pool=require_full_pool)


def _equivalence_class(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (tuple(row["lane"]), *tuple(row["pre_score_key"]))


def _derive_candidate(eligible: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from stage_center._formula_margin_shadow_parts.row_scoring import __derive_candidate_body as _v4_impl
    return _v4_impl(globals(), eligible)


def _metadata_from_input(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        merged = dict(metadata)
        for key, value in payload.items():
            if key not in {"metadata", "rows"} and key not in merged:
                merged[key] = value
        return merged
    return payload


def _read_json(path: Path | str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ShadowInvalid(f"JSON is unreadable: {path}") from error


def _immutable_json(path: Path, payload: Any) -> str:
    from stage_center._formula_margin_shadow_parts.capture_policy import __immutable_json_body as _v4_impl
    return _v4_impl(globals(), path, payload)


def _immutable_bytes(path: Path, encoded: bytes) -> str:
    """Publish exact consumed bytes once, without following symlinks."""
    from stage_center._formula_margin_shadow_parts.capture_policy import __immutable_bytes_body as _v4_impl
    return _v4_impl(globals(), path, encoded)


def _read_exact_artifact(artifact: Mapping[str, Any], label: str) -> bytes:
    """Read and recheck the exact bytes named by an already-bound artifact."""

    path = Path(str(artifact.get("path") or "")).expanduser()
    declared = str(artifact.get("sha256") or "").lower()
    if path.is_symlink() or not path.is_file() or not _is_sha(declared):
        raise ShadowInvalid(f"{label} path/SHA is invalid")
    encoded = path.read_bytes()
    if sha256_bytes(encoded) != declared:
        raise ShadowInvalid(f"{label} SHA mismatch")
    return encoded


def _ensure_output_root(root: Path | str) -> Path:
    path = Path(root).expanduser()
    if not path.is_absolute():
        raise ShadowInvalid("shadow output root must be absolute")
    if path.is_symlink():
        raise ShadowInvalid("shadow output root cannot be symlinked")
    text = str(path)
    if any(marker in text for marker in ("/Library/Application Support/", "/releases/", "/.runtime/")):
        raise ShadowInvalid("shadow output root cannot target formal/runtime state")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _source_artifact_check(
    metadata: Mapping[str, Any],
    *,
    expected_sha: str | None = None,
    required: bool = False,
) -> dict[str, Any] | None:
    from stage_center._formula_margin_shadow_parts.artifact_evidence import __source_artifact_check_body as _v4_impl
    return _v4_impl(globals(), metadata, expected_sha=expected_sha, required=required)


def _verify_source_artifact_rows(
    artifact: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    """Check the selector snapshot's member identities and shared inputs."""
    from stage_center._formula_margin_shadow_parts.artifact_evidence import __verify_source_artifact_rows_body as _v4_impl
    return _v4_impl(globals(), artifact, rows)


def _reject_archive_or_proxy_metadata(metadata: Mapping[str, Any]) -> None:
    """Reject labels that identify a historical/proxy source at the boundary."""

    values = (
        str(metadata.get("source_mode") or ""),
        str(metadata.get("source_kind") or ""),
        str(metadata.get("source_version") or ""),
    )
    blocked = ("LEGACY", "ARCHIVE", "HISTORICAL", "FIXTURE", "REPLAY", "PROXY", "CF")
    if any(token in value.upper() for value in values for token in blocked):
        raise ShadowInvalid("legacy/archive/proxy source cannot be a forward snapshot")


def _verified_manifest_binding(
    value: Any,
    label: str,
    *,
    require_artifact: bool = False,
) -> dict[str, Any]:
    """Return a small, hash-bound manifest descriptor for a capture input."""
    from stage_center._formula_margin_shadow_parts.manifest_binding import __verified_manifest_binding_body as _v4_impl
    return _v4_impl(globals(), value, label, require_artifact=require_artifact)


def _formula_manifest_states(manifest: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Extract explicit per-code H/N/U states without calculating formulas."""
    from stage_center._formula_margin_shadow_parts.manifest_binding import __formula_manifest_states_body as _v4_impl
    return _v4_impl(globals(), manifest)


def _selector_result_codes(selector_result: Mapping[str, Any]) -> list[str]:
    from stage_center._formula_margin_shadow_parts.capture_policy import __selector_result_codes_body as _v4_impl
    return _v4_impl(globals(), selector_result)


def _validate_selector_return(
    selector_result: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    expected_raw_artifact_sha: str,
) -> dict[str, Any]:
    """Validate the actual envelope returned by ``select_hk_four_lane``."""
    from stage_center._formula_margin_shadow_parts.capture_payload import __validate_selector_return_body as _v4_impl
    return _v4_impl(globals(), selector_result, metadata, expected_raw_artifact_sha=expected_raw_artifact_sha)


def _capture_time_receipt_payload(
    metadata: Mapping[str, Any],
    *,
    selector_result: Mapping[str, Any],
    selector_started_at: datetime,
    selector_finished_at: datetime,
) -> dict[str, Any]:
    """Build a v2 receipt from the actual post-selector return envelope."""
    from stage_center._formula_margin_shadow_parts.capture_price_receipt import __capture_time_receipt_payload_body as _v4_impl
    return _v4_impl(globals(), metadata, selector_result=selector_result, selector_started_at=selector_started_at, selector_finished_at=selector_finished_at)


def _validate_capture_time_receipt(
    receipt: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    require_runtime: bool = False,
    allow_invocation_verified: bool = False,
    selector_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a v2 receipt and keep direct freeze fail-closed."""
    from stage_center._formula_margin_shadow_parts.capture_price_receipt import __validate_capture_time_receipt_body as _v4_impl
    return _v4_impl(globals(), receipt, metadata, require_runtime=require_runtime, allow_invocation_verified=allow_invocation_verified, selector_result=selector_result)


def _capture_price_alias(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if row.get(name) not in (None, ""):
            return row.get(name)
    return None


def build_selector_capture_payload(
    *,
    metadata: Mapping[str, Any],
    raw_rows: Sequence[Mapping[str, Any]],
    sorted_rows: Sequence[Mapping[str, Any]],
    production_rows: Sequence[Mapping[str, Any]],
    formula_manifest: Mapping[str, Any],
    time_evidence: Mapping[str, Any],
    d1_manifest: Mapping[str, Any],
    raw_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Adapt a real selector hook capture into a frozen shadow input.

    The adapter assigns ``production_rank`` from the selector's full sorted
    output.  It never accepts a caller-supplied rank and never derives
    eligibility from ``formal_eligible``: rows that the selector actually
    ranked carry ``selection_eligible=True`` and become the shadow's explicit
    eligible set.  Formula states are joined only from the verified manifest;
    no formula producer or fallback is called here.
    """
    from stage_center._formula_margin_shadow_parts.capture_payload import _build_selector_capture_payload_body as _v4_impl
    return _v4_impl(globals(), metadata=metadata, raw_rows=raw_rows, sorted_rows=sorted_rows, production_rows=production_rows, formula_manifest=formula_manifest, time_evidence=time_evidence, d1_manifest=d1_manifest, raw_artifact_sha256=raw_artifact_sha256)


def _validate_capture_request_static(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the raw selector capture contract before invoking production.

    This gate deliberately stops before rank, baseline, or tau calculation.
    It is shared by the capture-specific preflight and the manual capture
    entrypoint so a preflight PASS means only that the selector may be called.
    """
    from stage_center._formula_margin_shadow_parts.capture_request import __validate_capture_request_static_body as _v4_impl
    return _v4_impl(globals(), payload)


def build_shadow(
    payload: Mapping[str, Any],
    *,
    require_full_pool: bool = False,
    require_artifacts: bool = False,
    allow_invocation_verified: bool = False,
) -> dict[str, Any]:
    """Validate one input and build the frozen B/F artifacts in memory.

    No output is written by this function.  The returned object is suitable
    for ``freeze_snapshot`` and is also useful for a small deterministic
    canary test.
    """
    from stage_center._formula_margin_shadow_parts.shadow_build import _build_shadow_body as _v4_impl
    return _v4_impl(globals(), payload, require_full_pool=require_full_pool, require_artifacts=require_artifacts, allow_invocation_verified=allow_invocation_verified)


def _provenance_material(built: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any] | None]:
    """Read all consumed source bytes before publishing an invocation freeze."""
    from stage_center._formula_margin_shadow_parts.snapshot_freeze import __provenance_material_body as _v4_impl
    return _v4_impl(globals(), built)


def _freeze_snapshot_internal(
    payload: Mapping[str, Any],
    output_root: Path | str,
    *,
    require_full_pool: bool = True,
    allow_invocation_verified: bool = False,
) -> dict[str, Any]:
    from stage_center._formula_margin_shadow_parts.snapshot_freeze import __freeze_snapshot_internal_body as _v4_impl
    return _v4_impl(globals(), payload, output_root, require_full_pool=require_full_pool, allow_invocation_verified=allow_invocation_verified)


def freeze_snapshot(
    payload: Mapping[str, Any],
    output_root: Path | str,
    *,
    require_full_pool: bool = True,
) -> dict[str, Any]:
    """Direct engineering freeze; it cannot prove a selector invocation."""
    from stage_center._formula_margin_shadow_parts.snapshot_freeze import _freeze_snapshot_body as _v4_impl
    return _v4_impl(globals(), payload, output_root, require_full_pool=require_full_pool)


def record_invalid_capture(
    output_root: Path | str,
    metadata: Mapping[str, Any] | None,
    reasons: Iterable[Any],
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write one immutable pre-freeze capture invalid ledger.

    This is intentionally separate from ``labels/invalid_ledger.json``:
    capture failures happen before a baseline can be frozen and therefore
    must never look like a labelled run.  The function is best-effort for the
    selector observer boundary and returns ``CANNOT_CONFIRM`` on write
    failure instead of raising a second error into production selection.
    """
    from stage_center._formula_margin_shadow_parts.frozen_readers import _record_invalid_capture_body as _v4_impl
    return _v4_impl(globals(), output_root, metadata, reasons, context=context)


def _read_frozen(run_root: Path | str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    from stage_center._formula_margin_shadow_parts.frozen_readers import __read_frozen_body as _v4_impl
    return _v4_impl(globals(), run_root)


def _external_source_revalidation(receipt: Mapping[str, Any], root: Path) -> str:
    from stage_center._formula_margin_shadow_parts.frozen_readers import __external_source_revalidation_body as _v4_impl
    return _v4_impl(globals(), receipt, root)


def verify_frozen_artifacts(
    run_root: Path | str,
    *,
    external_revalidate: bool = False,
) -> dict[str, Any]:
    from stage_center._formula_margin_shadow_parts.frozen_readers import _verify_frozen_artifacts_body as _v4_impl
    return _v4_impl(globals(), run_root, external_revalidate=external_revalidate)


def _truth_metadata(labels: Mapping[str, Any], trade_date: str, cutoff: datetime) -> tuple[dict[str, Any], list[Mapping[str, Any]], list[str]]:
    from stage_center._formula_margin_shadow_parts.label_truth import __truth_metadata_body as _v4_impl
    return _v4_impl(globals(), labels, trade_date, cutoff)


def _normalise_label_rows(
    label_rows: Sequence[Mapping[str, Any]],
    members: Mapping[str, Any],
    top20_codes: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    from stage_center._formula_margin_shadow_parts.label_truth import __normalise_label_rows_body as _v4_impl
    return _v4_impl(globals(), label_rows, members, top20_codes)


def append_labels(run_root: Path | str, labels: Mapping[str, Any]) -> dict[str, Any]:
    """Append close labels after the frozen selection files exist.

    Invalid/incomplete truth is recorded as an immutable invalid ledger and is
    never converted to a zero or a negative hit.  The function never rewrites
    any selection artifact.
    """
    from stage_center._formula_margin_shadow_parts.label_truth import _append_labels_body as _v4_impl
    return _v4_impl(globals(), run_root, labels)


def _summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "average": None, "median": None, "positive_ratio": None, "worst": None}
    return {
        "count": len(values),
        "average": sum(values) / len(values),
        "median": statistics.median(values),
        "positive_ratio": sum(value > 0 for value in values) / len(values),
        "worst": min(values),
    }


def _markout_for_codes(rows: Sequence[Mapping[str, Any]], label_by_code: Mapping[str, Mapping[str, Any]], codes: Sequence[str]) -> tuple[list[float], list[str]]:
    from stage_center._formula_margin_shadow_parts.evaluation import __markout_for_codes_body as _v4_impl
    return _v4_impl(globals(), rows, label_by_code, codes)


def evaluate_run(run_root: Path | str) -> dict[str, Any]:
    """Evaluate one frozen unit; labels are never used to rebuild a candidate."""
    from stage_center._formula_margin_shadow_parts.evaluation import _evaluate_run_body as _v4_impl
    return _v4_impl(globals(), run_root)


def evaluate_runs(run_roots: Iterable[Path | str]) -> dict[str, Any]:
    from stage_center._formula_margin_shadow_parts.evaluation import _evaluate_runs_body as _v4_impl
    return _v4_impl(globals(), run_roots)


def preflight_input(payload_or_path: Mapping[str, Any] | Path | str) -> dict[str, Any]:
    """Check whether an input is eligible for a forward manual observation.

    Existing archives, fixtures, replays, and CF/proxy inputs are deliberately
    rejected.  This is an engineering preflight and never counts as a natural
    canary day.
    """
    from stage_center._formula_margin_shadow_parts.shadow_build import _preflight_input_body as _v4_impl
    return _v4_impl(globals(), payload_or_path)


def preflight_capture_input(payload_or_path: Mapping[str, Any] | Path | str) -> dict[str, Any]:
    """Run the static admission gate for a raw selector capture request.

    ``READY_FOR_CAPTURE_INVOCATION`` authorizes only the subsequent selector
    invocation.  It is never a frozen run and never increments a natural-day
    counter.
    """
    from stage_center._formula_margin_shadow_parts.capture_request import _preflight_capture_input_body as _v4_impl
    return _v4_impl(globals(), payload_or_path)


def capture_selector_snapshot(
    payload_or_path: Mapping[str, Any] | Path | str,
    output_root: Path | str,
) -> dict[str, Any]:
    """Capture a real HK four-lane selector call through its opt-in hook.

    The input contains the same raw rows and verified provenance consumed by
    the selector.  This function invokes ``select_hk_four_lane`` and lets the
    hook assign ranks from the real full sorted output; callers never provide a
    hand-ranked production list.  A failed shadow capture is recorded as an
    immutable invalid ledger while the returned selector envelope remains the
    production result.
    """
    from stage_center._formula_margin_shadow_parts.live_capture import _capture_selector_snapshot_body as _v4_impl
    return _v4_impl(globals(), payload_or_path, output_root)


def _cli() -> int:
    from stage_center._formula_margin_shadow_parts.capture_policy import __cli_body as _v4_impl
    return _v4_impl(globals())


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI tests
    raise SystemExit(_cli())


__all__ = [
    "ADMISSION_MODES",
    "CAPTURE_TIME_RECEIPT_SCHEMA_VERSION",
    "CAPTURE_TIME_SOURCE",
    "INVOCATION_VERIFICATION_BASIS",
    "CAPTURE_ORIGIN_DIRECT",
    "CAPTURE_ORIGIN_SELECTOR",
    "INVOCATION_STATUS_DIRECT",
    "INVOCATION_STATUS_VERIFIED",
    "COMPARATOR_KEY_NAMES",
    "COMPARATOR_VERSION",
    "EXPERIMENT_ID",
    "ENGINEERING_FIXTURE",
    "FORMULA_STATES",
    "INPUT_SCHEMA_VERSION",
    "LABEL_SCHEMA_VERSION",
    "MARKET",
    "POOL_LIMIT",
    "RULE_VERSION",
    "REAL_AUTHORITY",
    "SAFETY_FLAGS",
    "SCHEMA_VERSION",
    "ShadowInvalid",
    "STAGE_CUTOFFS",
    "STAGE_CAPTURE_WINDOWS",
    "TOP_K",
    "TRUTH_K",
    "TRUTH_SCOPE",
    "append_labels",
    "build_shadow",
    "build_selector_capture_payload",
    "capture_selector_snapshot",
    "canonical_json",
    "evaluate_run",
    "evaluate_runs",
    "freeze_snapshot",
    "hk_legacy_stage_sort_key",
    "preflight_input",
    "preflight_capture_input",
    "record_invalid_capture",
    "sha256_file",
    "verify_frozen_artifacts",
]
