"""Explicit references to existing sealed backfills; never a selection producer.

A reference selects exactly one date/stage/market/backfill/selection run. The
original formal pointer and all immutable run trios remain unchanged. Reads
re-verify the original SelectionStore contract; no directory or mtime search.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from .contracts import SAFETY_FLAGS
from .selection import (
    SelectionError, SelectionStore, _atomic_write_bytes, _read_json,
    _safe_relative, _validate_date, _validate_market, _validate_sha,
)

SCHEMA = "stage_center.historical_readback.v1"
ORIGIN = "HISTORICAL_BACKFILL"
HASH_KEYS = ("artifact_sha256", "manifest_sha256", "receipt_sha256")


def _path(store: SelectionStore, trade_date: str, stage_id: str, market: str) -> Path:
    _validate_date(trade_date)
    _validate_market(stage_id, market)
    return _safe_relative(store.root, f"historical_readbacks/{trade_date}/{stage_id}/{market}.json")


def _bound_run(store: SelectionStore, binding: Mapping[str, Any]) -> dict[str, Any]:
    if (binding.get("schema_version") != SCHEMA or binding.get("owner") != "stage_center"
            or binding.get("origin") != ORIGIN or binding.get("real_time_success") is not False
            or binding.get("recommendation_status") != "RESEARCH_ONLY"
            or any(binding.get(flag) is not False for flag in SAFETY_FLAGS)):
        raise SelectionError("historical readback schema/owner/safety mismatch")
    date, stage, market = (binding.get(k) for k in ("trade_date", "stage_id", "market"))
    _path(store, date, stage, market)
    backfill = binding.get("backfill_run_id")
    if not isinstance(backfill, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", backfill):
        raise SelectionError("historical backfill run id is unsafe")
    scoped = SelectionStore(_safe_relative(store.root, f"backfill/{backfill}"))
    run = binding.get("selection_run_id")
    if not isinstance(run, str):
        raise SelectionError("historical selection run id is required")
    verified = scoped._verify_run(date, stage, market, run)
    for key in HASH_KEYS:
        if _validate_sha(binding.get(key), key) != verified[key]:
            raise SelectionError(f"historical readback {key} mismatch")
    envelope = verified["envelope"]
    if (any(envelope.get(k) != binding[k] for k in ("trade_date", "stage_id", "market"))
            or any(envelope.get(flag) is not False for flag in SAFETY_FLAGS)
            or envelope.get("selected_rows") != len(envelope.get("rows") or [])
            or not envelope.get("rows")
            or envelope.get("selection_status") not in {"READY", "PARTIAL_WITH_ROWS"}):
        raise SelectionError("historical selection envelope identity/status/rows mismatch")
    # Do not relabel a copied formal selection as an historical execution.
    if not set(envelope.get("source_evidence") or []).intersection({
            "HISTORICAL_BACKFILL", "due_status=HISTORICAL_BACKFILL", "historical_backfill=true"}):
        raise SelectionError("historical selection has no explicit backfill evidence")
    return verified


def bind_history(
    root: Path | str, *, trade_date: str, stage_id: str, market: str,
    backfill_run_id: str, selection_run_id: str, expected_artifact_sha256: str,
    expected_manifest_sha256: str, expected_receipt_sha256: str,
) -> dict[str, Any]:
    """Create one immutable reference after independent expected-SHA checks.

    Manifest/receipt hashes follow SelectionStore's canonical JSON convention;
    artifact_sha256 is the CSV byte hash. This does not assert raw/PIT/business
    acceptance beyond the sealed selection contract. Conflicts are rejected.
    """
    store = SelectionStore(root)
    path = _path(store, trade_date, stage_id, market)
    binding = {
        "schema_version": SCHEMA, "owner": "stage_center", "origin": ORIGIN,
        "trade_date": trade_date, "stage_id": stage_id, "market": market,
        "backfill_run_id": backfill_run_id, "selection_run_id": selection_run_id,
        "artifact_sha256": expected_artifact_sha256, "manifest_sha256": expected_manifest_sha256,
        "receipt_sha256": expected_receipt_sha256, "real_time_success": False,
        "recommendation_status": "RESEARCH_ONLY", **SAFETY_FLAGS,
    }
    _bound_run(store, binding)
    with store._lock():
        path = _path(store, trade_date, stage_id, market)
        _bound_run(store, binding)
        if path.exists():
            if _read_json(path) != binding:
                raise SelectionError("historical readback binding conflict; no overwrite")
            return {"binding": binding, "write_performed": False, **SAFETY_FLAGS}
        _atomic_write_bytes(path, (json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":")) + "\n").encode("utf-8"))
    return {"binding": binding, "write_performed": True, **SAFETY_FLAGS}


def read_history(root: Path | str, trade_date: str, stage_id: str, market: str):
    """Read exactly the selected binding, never the backfill store's latest."""
    store = SelectionStore(root)
    path = _path(store, trade_date, stage_id, market)
    if not path.exists():
        return None
    raw = path.read_bytes()
    binding = json.loads(raw)
    if not isinstance(binding, dict) or any(binding.get(k) != v for k, v in
            (("trade_date", trade_date), ("stage_id", stage_id), ("market", market))):
        raise SelectionError("historical readback slot identity mismatch")
    verified = _bound_run(store, binding)
    return verified["envelope"], {**binding, "binding_sha256": hashlib.sha256(raw).hexdigest()}


def resolve_market(
    store: SelectionStore, trade_date: str, stage_id: str, market: str,
    formal: Mapping[str, Any], *, project_market: Callable,
) -> dict[str, Any]:
    """Fallback only from an empty failed formal lane, never from READY_EMPTY."""
    if formal.get("rows") or formal.get("status") != "CANNOT_CONFIRM":
        return dict(formal)
    try:
        history = read_history(store.root, trade_date, stage_id, market)
        if history is None:
            return dict(formal)
        envelope, binding = history
        projected = project_market(market, envelope)
    except (SelectionError, OSError, ValueError, TypeError, KeyError):
        return {**formal, "historical_readback_error": "HISTORICAL_READBACK_UNAVAILABLE_OR_INVALID"}
    original = {key: deepcopy(formal.get(key)) for key in
                ("status", "selection_status", "artifact_id", "run_id", "selected_rows", "cannot_confirm")}
    projected.update(result_origin=ORIGIN, historical_readback={**binding, "original_formal": original})
    projected["cannot_confirm"] = list(dict.fromkeys([
        *projected["cannot_confirm"], "HISTORICAL_BACKFILL_NOT_REALTIME",
        *(f"ORIGINAL_FORMAL:{reason}" for reason in original["cannot_confirm"] or []),
    ]))
    return projected


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bind one verified historical selection; no collection or service changes")
    parser.add_argument("--selection-root", required=True)
    for name in ("trade-date", "stage-id", "market", "backfill-run-id", "selection-run-id",
                 "expected-artifact-sha256", "expected-manifest-sha256", "expected-receipt-sha256"):
        parser.add_argument(f"--{name}", required=True)
    args = vars(parser.parse_args(argv))
    root = args.pop("selection_root")
    try:
        result = bind_history(root, **args)
    except (SelectionError, OSError, ValueError, TypeError) as error:
        parser.exit(2, f"historical readback refused: {error}\n")
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
