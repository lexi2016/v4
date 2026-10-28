"""Read-only consumer for separately published execution-review attestations.

The review file is deliberately not produced here.  A distinct reviewer must
inspect contemporaneous evidence and publish one immutable attestation plus
its SHA index.  This reader checks those bytes against the current configured
receipt, owner-history, selection, source, and attempt evidence.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from infrastructure.owned_io import SafeRoot
from .contracts import STAGE_BY_ID

_MAX_REVIEW_BYTES = 1_048_576
_MAX_SOURCE_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVIEW_ROOT = "independent_execution_reviews"
_SELECTION_HASHES = (
    "artifact_bytes_sha256", "manifest_bytes_sha256", "receipt_bytes_sha256",
    "manifest_canonical_sha256", "receipt_canonical_sha256",
)
_SELECTION_PATHS = ("artifact_relative", "manifest_relative", "receipt_relative")
_REPLAY_ORIGINS = frozenset({
    "MANUAL_REPLAY", "CURRENT_DAY_RESEARCH_REPLAY", "HISTORICAL_BACKFILL", "LATE_CATCHUP_REPLAY",
})
_SHANGHAI = ZoneInfo("Asia/Shanghai")

# Independently reviewed revalidation-equivalent verifier pair. This permits
# R3's lock-wait-only reader upgrade to revalidate genuine R2 records using
# all current checks; it is not an arbitrary historical-code allowlist.
_AUTOMATED_VERIFIER_REVALIDATION_COMPATIBILITY = {
    "32872ffd4f99ca774252d238d38033c39b3dd0ab9b449a69c2dd35fddc556fc5": frozenset({
        "49a36c3725b8ee2546bc0fdc2044790386da152044053cb10c0750d199f0a7ae",
    }),
}


class _ReviewError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _strict_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _ReviewError("INDEPENDENT_REVIEW_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except _ReviewError:
        raise
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise _ReviewError("INDEPENDENT_REVIEW_JSON_INVALID") from exc


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _read(root: Path, relative: str, *, max_bytes: int = _MAX_REVIEW_BYTES) -> bytes:
    try:
        return SafeRoot(root).read_bytes(relative, max_bytes=max_bytes)
    except FileNotFoundError as exc:
        raise _ReviewError("INDEPENDENT_REVIEW_FILE_MISSING") from exc
    except (OSError, ValueError) as exc:
        raise _ReviewError("INDEPENDENT_REVIEW_PATH_OR_SIZE_REFUSED") from exc


def _utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0
    except (TypeError, ValueError):
        return False


def _default_market_facts(stage_id: str, reason: str) -> dict[str, dict[str, Any]]:
    return {
        market: {
            "status": "CANNOT_CONFIRM", "scope_markets": [],
            "execution_verified": False, "natural_verified": False,
            "cannot_confirm": [reason],
        }
        for market in STAGE_BY_ID[stage_id].markets
    }


def _source_evidence_valid(
    source_binding: Any, source_evidence: Any, stage_state_root: Path,
) -> tuple[list[tuple[Path, str, bytes]], list[dict[str, str]]]:
    if not isinstance(source_binding, dict):
        raise _ReviewError("INDEPENDENT_SOURCE_BINDING_MISSING")
    if not isinstance(source_evidence, (list, tuple)) or not source_evidence or any(not isinstance(item, str) for item in source_evidence):
        raise _ReviewError("CURRENT_SELECTION_SOURCE_EVIDENCE_MISSING")
    if source_binding.get("source_evidence_sha256") != _sha(_canonical_bytes(list(source_evidence))):
        raise _ReviewError("CURRENT_SOURCE_EVIDENCE_SHA_MISMATCH")
    sources = source_binding.get("sources")
    if not isinstance(sources, list) or not sources:
        raise _ReviewError("INDEPENDENT_SOURCE_FILES_MISSING")
    snapshots: list[tuple[Path, str, bytes]] = []
    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in sources:
        if not isinstance(item, dict):
            raise _ReviewError("INDEPENDENT_SOURCE_BINDING_INVALID")
        identity = item.get("identity")
        source_path = item.get("path")
        digest = item.get("sha256")
        cutoff = item.get("cutoff")
        semantics = item.get("temporal_semantics")
        evidence_entries = item.get("evidence_entries")
        if (not isinstance(identity, str) or not identity.strip() or len(identity) > 200
                or not isinstance(source_path, str) or not Path(source_path).is_absolute()
                or not _is_sha(digest) or not isinstance(cutoff, str) or not cutoff.strip()
                or not isinstance(semantics, str) or not semantics.strip()
                or not isinstance(evidence_entries, list) or len(evidence_entries) < 4
                or any(not isinstance(entry, str) or entry not in source_evidence for entry in evidence_entries)):
            raise _ReviewError("INDEPENDENT_SOURCE_BINDING_INVALID")
        if source_path in seen_paths:
            raise _ReviewError("INDEPENDENT_SOURCE_PATH_DUPLICATE")
        seen_paths.add(source_path)
        # The reader never opens a reviewer-supplied arbitrary path.  Source
        # paths must be present in the verified selection's evidence and stay
        # under the configured SelectionStore's parent root.
        if not any("=" in entry and entry.split("=", 1)[1] == source_path
                   and (entry.split("=", 1)[0].endswith("_path") or entry.split("=", 1)[0].endswith("_json"))
                   for entry in evidence_entries):
            raise _ReviewError("SOURCE_PATH_NOT_IN_CURRENT_SELECTION_EVIDENCE")
        if not any("=" in entry and entry.split("=", 1)[1] == identity
                   and any(token in entry.split("=", 1)[0] for token in ("identity", "source", "route"))
                   for entry in evidence_entries):
            raise _ReviewError("SOURCE_IDENTITY_NOT_IN_CURRENT_SELECTION_EVIDENCE")
        if not any("=" in entry and entry.split("=", 1)[1] == digest
                   and "sha256" in entry.split("=", 1)[0]
                   for entry in evidence_entries):
            raise _ReviewError("SOURCE_SHA_NOT_IN_CURRENT_SELECTION_EVIDENCE")
        if not any("=" in entry and entry.split("=", 1)[1] == cutoff
                   and "cutoff" in entry.split("=", 1)[0]
                   for entry in evidence_entries):
            raise _ReviewError("SOURCE_CUTOFF_NOT_IN_CURRENT_SELECTION_EVIDENCE")
        if not any("=" in entry and ("temporal" in entry.split("=", 1)[0] or "semantics" in entry.split("=", 1)[0])
                   for entry in evidence_entries):
            raise _ReviewError("SOURCE_TEMPORAL_SEMANTICS_NOT_IN_CURRENT_SELECTION_EVIDENCE")
        try:
            source_root = stage_state_root.resolve(strict=True)
            resolved_path = Path(source_path).resolve(strict=False)
            if str(resolved_path) != source_path:
                raise ValueError("source path is not normalized or contains a symlink")
            relative = resolved_path.relative_to(source_root).as_posix()
        except (OSError, ValueError):
            raise _ReviewError("SOURCE_PATH_OUTSIDE_BOUND_STAGE_ROOT")
        if not relative or relative.startswith("../") or relative == ".":
            raise _ReviewError("SOURCE_PATH_OUTSIDE_BOUND_STAGE_ROOT")
        raw = _read(source_root, relative, max_bytes=_MAX_SOURCE_BYTES)
        if _sha(raw) != digest:
            raise _ReviewError("CURRENT_SOURCE_BYTES_SHA_MISMATCH")
        snapshots.append((source_root, relative, raw))
        normalized.append({"identity": identity, "path": source_path, "sha256": digest,
                           "cutoff": cutoff, "temporal_semantics": semantics})
    return snapshots, normalized


def _attempt_facts(root: Path, trade_date: str, stage_id: str, receipt: Mapping[str, Any]) -> tuple[dict[str, Any], tuple[Path, str, bytes]]:
    if (receipt.get("dispatch_mode") != "NATURAL" or receipt.get("due_status") != "DUE"
            or receipt.get("mode") == "BACKFILL"
            or receipt.get("execution_origin") not in (None, "NATURAL")
            or receipt.get("execution_origin") in _REPLAY_ORIGINS
            or receipt.get("same_day_late_observation_recovery") is True
            or receipt.get("node_attempt_count") != 1):
        raise _ReviewError("CURRENT_RUN_NOT_SINGLE_ATTEMPT_NATURAL_DUE")
    journal = receipt.get("attempt_diagnostic")
    attempt_id = journal.get("attempt_id") if isinstance(journal, dict) else None
    if not isinstance(attempt_id, str) or re.fullmatch(r"[0-9a-f]{32}", attempt_id) is None:
        raise _ReviewError("CURRENT_ATTEMPT_ID_MISSING")
    expected_relative = f"{trade_date}/{stage_id}/attempt_evidence/{attempt_id}/001_START.json"
    declared = journal.get("relative_paths")
    if not isinstance(declared, list) or f"attempt_evidence/{attempt_id}/001_START.json" not in declared:
        raise _ReviewError("CURRENT_ATTEMPT_START_NOT_DECLARED")
    raw = _read(root, expected_relative)
    start = _strict_json(raw)
    if not isinstance(start, dict) or any(start.get(key) != value for key, value in {
        "schema": "stage.attempt_diagnostic.v1", "event": "START", "attempt_id": attempt_id,
        "trade_date": trade_date, "stage_id": stage_id, "attempt_number": 1,
    }.items()):
        raise _ReviewError("CURRENT_ATTEMPT_START_SCOPE_CONFLICT")
    try:
        evaluated = datetime.fromisoformat(start["evaluated_at"])
        observed = datetime.fromisoformat(start["observed_at"])
        if evaluated.utcoffset() is None or observed.utcoffset() is None:
            raise ValueError("timezone required")
        evaluated = evaluated.astimezone(_SHANGHAI)
        observed = observed.astimezone(_SHANGHAI)
        if evaluated.strftime("%Y%m%d") != trade_date or observed.strftime("%Y%m%d") != trade_date or observed < evaluated:
            raise ValueError("clock conflict")
        from .scheduler import evaluate_due
        due = evaluate_due(stage_id, trade_date, evaluated)
        observed_due = evaluate_due(stage_id, trade_date, observed)
        if due.status != "DUE" or observed_due.status != "DUE" or due.scheduled_at is None:
            raise ValueError("outside natural minute")
        scheduled = due.scheduled_at.astimezone(_SHANGHAI).isoformat()
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise _ReviewError("CURRENT_ATTEMPT_CLOCK_NOT_ON_SCHEDULE") from exc
    facts = {
        "mode": receipt.get("dispatch_mode"), "due_status": receipt.get("due_status"),
        "attempt_id": attempt_id, "attempt_count": 1,
        "attempt_relative_path": expected_relative,
        "attempt_sha256": _sha(raw), "scheduled_at_local": scheduled,
        "evaluated_at_local": evaluated.isoformat(), "observed_at_local": observed.isoformat(),
    }
    return facts, (root, expected_relative, raw)


def _automated_execution_inputs(attestation, *, receipt_root, selection_store,
                                trade_date, stage_id, receipt_sha256, lane):
    """Revalidate typed automatic facts using only locally configured roots."""
    from ops import verify_stage_execution as verifier
    verifier_sha = _sha(Path(verifier.__file__).read_bytes())
    declared_verifier_sha = attestation.get("reviewer_verifier_code_sha256")
    compatible = _AUTOMATED_VERIFIER_REVALIDATION_COMPATIBILITY.get(verifier_sha, ())
    if (not _is_sha(declared_verifier_sha)
            or (declared_verifier_sha != verifier_sha and declared_verifier_sha not in compatible)):
        raise _ReviewError("AUTOMATED_VERIFIER_CODE_SHA_MISMATCH")
    if (attestation.get("scope_markets") != ["HK_CONNECT"]
            or attestation.get("scope_semantics") != "SCHEDULER_AND_ARTIFACT_OPERATION_FACTS_ONLY"):
        raise _ReviewError("AUTOMATED_REVIEW_SCOPE_MISMATCH")
    selection_root = Path(selection_store.root).resolve(strict=True)
    stage_root = selection_root.parent
    receipt_root = Path(receipt_root).resolve(strict=True)
    # All ordinary owner paths are siblings of the bound SelectionStore.
    # External data roots come from the trusted application environment only.
    if receipt_root != stage_root / "receipts":
        raise _ReviewError("AUTOMATED_OWNER_ROOT_BINDING_MISMATCH")
    data_root = Path(os.environ.get("V4_DATA_ROOT") or stage_root.parent / "data").expanduser().resolve(strict=True)
    pool_source = os.environ.get("V4_PRESELECTION_SOURCE_ROOT")
    shared_source = os.environ.get("V4_MORNING_NEWS_DATA_ROOT")
    try:
        inputs = verifier.validate_execution_inputs(
            trade_date=trade_date, stage_id=stage_id, receipt_root=receipt_root,
            raw_root=stage_root / "raw", selection_root=selection_root,
            expected_receipt_sha256=receipt_sha256, hk_d1_root=data_root,
            preselection_source_root=Path(pool_source).expanduser() if pool_source else None,
            hk_second_filter_root=data_root / "opening_second_filter",
            shared_research_root=Path(shared_source).expanduser() if shared_source else None,
        )
    except Exception as exc:
        raise _ReviewError("AUTOMATED_EXECUTION_INPUT_REVALIDATION_FAILED") from exc
    if attestation.get("execution_inputs") != inputs:
        raise _ReviewError("AUTOMATED_EXECUTION_INPUTS_MISMATCH")
    market = attestation.get("markets", {}).get("HK_CONNECT", {})
    expected_binding = {"schema_version": "stage_center.automated_source_binding.v1",
        "source_evidence_sha256": _sha(_canonical_bytes(lane.get("source_evidence"))),
        "sources": inputs["source_files"]}
    if (market.get("source_binding") != expected_binding or market.get("operation_status") != "VERIFIED"
            or market.get("formal_eligibility_status") != "CANNOT_CONFIRM" or market.get("pit_status") != "CANNOT_CONFIRM"
            or market.get("pit_cannot_confirm") != inputs["source_time_facts"]["pit_cannot_confirm"]):
        raise _ReviewError("AUTOMATED_SOURCE_BINDING_MISMATCH")


def read_independent_execution_review(
    root: Path | None,
    trade_date: str,
    stage_id: str,
    *,
    receipt: Mapping[str, Any],
    receipt_bytes: bytes,
    receipt_sha256: str,
    receipt_history_binding: str,
    selection_bindings: Mapping[str, Mapping[str, Any]],
    verified_markets: Mapping[str, Mapping[str, Any]],
    selection_store: Any = None,
    selection_stores: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an indexed independent review; never create or repair evidence."""
    defaults = _default_market_facts(stage_id, "INDEPENDENT_REVIEW_NOT_AVAILABLE")
    if root is None:
        return {"status": "CANNOT_CONFIRM", "scope_markets": [], "markets": defaults,
                "cannot_confirm": ["EXECUTION_RECEIPT_ROOT_NOT_BOUND"]}
    directory = f"{_REVIEW_ROOT}/{trade_date}/{stage_id}"
    attestation_relative = f"{directory}/attestation.json"
    index_relative = f"{directory}/index.json"
    snapshots: list[tuple[Path, str, bytes]] = []
    try:
        expected_receipt_relative = f"{trade_date}/{stage_id}/receipt.json"
        current_receipt = _read(root, expected_receipt_relative)
        if current_receipt != receipt_bytes or _sha(current_receipt) != receipt_sha256:
            raise _ReviewError("CURRENT_RUNNER_RECEIPT_CHANGED")
        if receipt_history_binding != "OWNER_HISTORY_SHA_BOUND":
            raise _ReviewError("OWNER_HISTORY_NOT_SHA_BOUND")
        history = receipt.get("receipt_history")
        if not isinstance(history, dict):
            raise _ReviewError("OWNER_HISTORY_REFERENCE_MISSING")
        history_sha = history.get("sha256")
        history_relative = history.get("relative_path")
        expected_history_relative = f"{trade_date}/{stage_id}/attempt_evidence/recorded-{history_sha}/RECEIPT.json"
        if not _is_sha(history_sha) or history_relative != expected_history_relative:
            raise _ReviewError("OWNER_HISTORY_REFERENCE_CONFLICT")
        current_history = _read(root, history_relative)
        if _sha(current_history) != history_sha:
            raise _ReviewError("CURRENT_OWNER_HISTORY_SHA_MISMATCH")
        snapshots.extend([(Path(root), expected_receipt_relative, current_receipt),
                          (Path(root), history_relative, current_history)])

        index_raw = _read(root, index_relative)
        attestation_raw = _read(root, attestation_relative)
        index = _strict_json(index_raw)
        attestation = _strict_json(attestation_raw)
        if not isinstance(index, dict) or not isinstance(attestation, dict):
            raise _ReviewError("INDEPENDENT_REVIEW_DOCUMENT_NOT_OBJECT")
        if (index.get("schema_version") != "stage_center.independent_execution_review_index.v1"
                or index.get("trade_date") != trade_date or index.get("stage_id") != stage_id
                or index.get("attestation_relative_path") != attestation_relative
                or index.get("attestation_sha256") != _sha(attestation_raw)):
            raise _ReviewError("INDEPENDENT_REVIEW_INDEX_SHA_OR_SCOPE_MISMATCH")
        snapshots.extend([(Path(root), index_relative, index_raw), (Path(root), attestation_relative, attestation_raw)])

        if (attestation.get("schema_version") != "stage_center.independent_execution_review.v1"
                or attestation.get("trade_date") != trade_date or attestation.get("stage_id") != stage_id
                or attestation.get("runner") != "stage_center"):
            raise _ReviewError("INDEPENDENT_REVIEW_IDENTITY_MISMATCH")
        reviewer = attestation.get("reviewer_identity_or_role")
        if not isinstance(reviewer, str) or not reviewer.strip() or len(reviewer) > 200:
            raise _ReviewError("INDEPENDENT_REVIEWER_IDENTITY_MISSING")
        if not _is_sha(attestation.get("reviewer_verifier_code_sha256")) or not _utc_timestamp(attestation.get("reviewed_at_utc")):
            raise _ReviewError("INDEPENDENT_REVIEWER_CODE_OR_CLOCK_INVALID")

        stage_markets = tuple(STAGE_BY_ID[stage_id].markets)
        scope = attestation.get("scope_markets")
        if (not isinstance(scope, list) or not scope
                or any(not isinstance(market, str) for market in scope)
                or len(set(scope)) != len(scope)):
            raise _ReviewError("INDEPENDENT_REVIEW_SCOPE_INVALID")
        expected_scope = [market for market in stage_markets if market in scope]
        if scope != expected_scope or any(market not in stage_markets for market in scope):
            raise _ReviewError("INDEPENDENT_REVIEW_MARKET_SCOPE_MISMATCH")
        market_reviews = attestation.get("markets")
        if not isinstance(market_reviews, dict) or set(market_reviews) != set(scope):
            raise _ReviewError("INDEPENDENT_REVIEW_MARKET_BINDINGS_MISMATCH")

        runner_binding = attestation.get("runner_receipt")
        if (not isinstance(runner_binding, dict)
                or runner_binding.get("relative_path") != expected_receipt_relative
                or runner_binding.get("sha256") != receipt_sha256):
            raise _ReviewError("INDEPENDENT_RUNNER_RECEIPT_SHA_MISMATCH")
        owner_binding = attestation.get("owner_history")
        if (not isinstance(owner_binding, dict)
                or owner_binding.get("relative_path") != history_relative
                or owner_binding.get("sha256") != history_sha):
            raise _ReviewError("INDEPENDENT_OWNER_HISTORY_SHA_MISMATCH")

        safety = attestation.get("safety")
        expected_safety = {"RESEARCH_ONLY": True, "production_allowed": False,
                           "buy_gate_updated": False, "orders_sent": False}
        if not isinstance(safety, dict) or safety != expected_safety:
            raise _ReviewError("INDEPENDENT_REVIEW_SAFETY_FLAGS_INVALID")
        if "RESEARCH_ONLY" not in receipt:
            raise _ReviewError("CURRENT_RECEIPT_RESEARCH_ONLY_MISSING")
        if (receipt.get("RESEARCH_ONLY") is not True
                or any(receipt.get(key) is not value for key, value in expected_safety.items()
                       if key != "RESEARCH_ONLY")):
            raise _ReviewError("CURRENT_RECEIPT_SAFETY_FLAGS_INCOMPLETE")

        dispatch, attempt_snapshot = _attempt_facts(root, trade_date, stage_id, receipt)
        if attestation.get("dispatch") != dispatch:
            raise _ReviewError("INDEPENDENT_DISPATCH_OR_CLOCK_BINDING_MISMATCH")
        snapshots.append(attempt_snapshot)

        source_snapshots: list[tuple[Path, str, bytes]] = []
        for market in scope:
            lane = verified_markets.get(market) or {}
            current_selection = selection_bindings.get(market) or {}
            market_review = market_reviews[market]
            if current_selection.get("status") != "BOUND_TO_VERIFIED_SELECTION_TRIO":
                raise _ReviewError(f"CURRENT_SELECTION_TRIO_UNBOUND:{market}")
            expected_selection = {key: current_selection.get(key) for key in (*_SELECTION_PATHS, "run_id", *_SELECTION_HASHES)}
            declared_selection = market_review.get("selection") if isinstance(market_review, dict) else None
            if not isinstance(declared_selection, dict) or declared_selection != expected_selection:
                raise _ReviewError(f"INDEPENDENT_SELECTION_TRIO_MISMATCH:{market}")
            selected_store = (selection_stores or {}).get(market, selection_store)
            if selected_store is None:
                raise _ReviewError(f"SELECTION_STORE_NOT_BOUND:{market}")
            source_root = Path(selected_store.root).parent
            selected_io = SafeRoot(selected_store.root)
            selection_raw: dict[str, bytes] = {}
            for field in _SELECTION_PATHS:
                relative = current_selection[field]
                raw = selected_io.read_bytes(relative, max_bytes=_MAX_SOURCE_BYTES)
                selection_raw[field] = raw
                snapshots.append((Path(selected_store.root), relative, raw))
            if (_sha(selection_raw["artifact_relative"]) != current_selection.get("artifact_bytes_sha256")
                    or _sha(selection_raw["manifest_relative"]) != current_selection.get("manifest_bytes_sha256")
                    or _sha(selection_raw["receipt_relative"]) != current_selection.get("receipt_bytes_sha256")):
                raise _ReviewError(f"CURRENT_SELECTION_TRIO_BYTES_CHANGED:{market}")
            for field in ("manifest_relative", "receipt_relative"):
                if _sha(_canonical_bytes(_strict_json(selection_raw[field]))) != current_selection.get(
                    "manifest_canonical_sha256" if field == "manifest_relative" else "receipt_canonical_sha256"
                ):
                    raise _ReviewError(f"CURRENT_SELECTION_TRIO_CANONICAL_SHA_CHANGED:{market}")

            if reviewer == "AUTOMATED_INDEPENDENT_EXECUTION_VERIFIER":
                _automated_execution_inputs(attestation, receipt_root=root, selection_store=selected_store,
                    trade_date=trade_date, stage_id=stage_id, receipt_sha256=receipt_sha256, lane=lane)
            else:
                source_snapshots_market, normalized_sources = _source_evidence_valid(
                    market_review.get("source_binding") if isinstance(market_review, dict) else None,
                    lane.get("source_evidence"), source_root,
                )
                source_snapshots.extend(source_snapshots_market)
                # Attest only source descriptors whose bytes and immutable selection
                # evidence were both checked in this read.
                declared_sources = market_review["source_binding"]["sources"]
                descriptor_keys = ("identity", "path", "sha256", "cutoff", "temporal_semantics")
                declared_projection = [{key: source.get(key) for key in descriptor_keys} for source in declared_sources]
                if declared_projection != normalized_sources:
                    raise _ReviewError(f"INDEPENDENT_SOURCE_DESCRIPTORS_MISMATCH:{market}")
        snapshots.extend(source_snapshots)
        # Re-read every bound file so concurrent replacement cannot pass.
        for bound_root, relative, before in snapshots:
            if _read(bound_root, relative, max_bytes=_MAX_SOURCE_BYTES) != before:
                raise _ReviewError("BOUND_EVIDENCE_CHANGED_DURING_READ")

        facts = _default_market_facts(stage_id, "MARKET_NOT_IN_INDEPENDENT_REVIEW_SCOPE")
        for market in scope:
            facts[market] = {
                "status": "VERIFIED", "scope_markets": list(scope),
                "reviewer_identity_or_role": reviewer,
                "reviewed_at_utc": attestation["reviewed_at_utc"],
                "execution_verified": True, "natural_verified": True,
                "cannot_confirm": [],
            }
        return {
            "status": "VERIFIED_FOR_EXPLICIT_SCOPE", "scope_markets": list(scope),
            "reviewer_identity_or_role": reviewer,
            "reviewed_at_utc": attestation["reviewed_at_utc"],
            "attestation_sha256": _sha(attestation_raw), "index_sha256": _sha(index_raw),
            "markets": facts, "cannot_confirm": [],
        }
    except _ReviewError as exc:
        return {"status": "CANNOT_CONFIRM", "scope_markets": [], "markets": _default_market_facts(stage_id, exc.reason),
                "cannot_confirm": [exc.reason]}
    except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError, OverflowError):
        return {"status": "CANNOT_CONFIRM", "scope_markets": [], "markets": _default_market_facts(stage_id, "INDEPENDENT_REVIEW_VALIDATION_FAILED"),
                "cannot_confirm": ["INDEPENDENT_REVIEW_VALIDATION_FAILED"]}
