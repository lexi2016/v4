"""Capture the shared HK pre-open reference and materialize the V3.5 09:25 input.

The shared package owns the Futu capture and immutable Top50 run.  This module
only verifies that run, reproduces its frozen Top20 lineage, and writes the
V3.5-owned read-only projection consumed by Stage Center.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Mapping, Sequence

from contracts.trading_calendar import TradingDayState, load_market_calendar, resolve_market_states
from domains.opening_second_filter import build_v11_opening_second_filter
from infrastructure.isolated_package_loader import load_isolated_package_module
from infrastructure.opening_second_filter_store import OpeningSecondFilterStore


HK_AUCTION_ROLE = "HK_CONNECT_AUCTION_REFERENCE_STAGE_0925"
HK_D1_ROLE = "HK_CONNECT_D1_TOP100_0_2"
SIGNAL_CUTOFF = "09:19:59"
PUBLICATION_TIME = "09:20:00"
CSV_SCHEMA_VERSION = "hkconnect_0920_auction_second_filter.v3"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CODE = re.compile(r"(?:HK\.)?(\d{5})", re.I)
_CSV_FIELDS = (
    "rank", "code", "ts_code", "name", "target_date", "signal_date",
    "preselect_rank", "preselect_lane", "auction_rank", "auction_score",
    "auction_label", "auction_ref_gap_pct", "first_to_last_ref_pct",
    "visible_depth_hkd", "bid_ask_imbalance", "spread_pct", "last_price",
    "prev_close_price", "bid_price", "ask_price", "bid_vol", "ask_vol",
    "turnover", "update_time", "collector_wall_time", "second_filter_status",
    "recommendation_status", "reference_only", "reference_scope",
    "market_access", "action_level", "research_only", "cannot_confirm",
)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _sha_json(value: Any) -> str:
    return _sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


_SOURCE_HASH_NUMERIC_FIELDS = ("auction_ref_gap_pct", "turnover")


def _restore_source_hash_numeric_types(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Restore the shared producer's in-memory types after CSV round-trip.

    The shared producer freezes ``source_output_sha256`` before serializing its
    Top50 reference rows.  These two fields are floats in that in-memory hash
    input, but ``csv.DictReader`` necessarily returns strings.  Restore only
    those producer-owned numeric fields so the consumer verifies the exact
    original contract without weakening or bypassing the SHA check.
    """
    restored: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        for field in _SOURCE_HASH_NUMERIC_FIELDS:
            value = row.get(field)
            if value in (None, ""):
                row[field] = ""
                continue
            try:
                row[field] = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"shared HK source-hash field {field} is not numeric"
                ) from error
        restored.append(row)
    return restored


def _timestamp(value: Any, trade_date: str, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise ValueError(f"{field} must include target-date timestamp") from error
    if parsed.strftime("%Y%m%d") != trade_date or parsed.strftime("%H:%M:%S") > SIGNAL_CUTOFF:
        raise ValueError(f"{field} is outside target-date cutoff")
    return parsed


def _validate_rows(rows: Sequence[Mapping[str, Any]], trade_date: str, signal_date: str) -> None:
    if len(rows) != 50:
        raise ValueError(f"shared HK reference must contain Top50, got {len(rows)}")
    codes: set[str] = set()
    for row in rows:
        if str(row.get("trade_date") or "") != trade_date or str(row.get("target_date") or "") != trade_date:
            raise ValueError("shared HK row trade/target date mismatch")
        if str(row.get("signal_date") or "") != signal_date:
            raise ValueError("shared HK row signal date mismatch")
        match = _CODE.search(str(row.get("code") or ""))
        if match is None or match.group(1) in codes:
            raise ValueError("shared HK row code set is not unique Top50")
        codes.add(match.group(1))
        bar = str(row.get("bar_time") or "")
        if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", bar) or not ("09:15:00" <= bar <= SIGNAL_CUTOFF):
            raise ValueError("shared HK row bar_time outside 09:15:00-09:19:59")
        _timestamp(row.get("collector_wall_time"), trade_date, "collector_wall_time")
        _timestamp(row.get("update_time"), trade_date, "update_time")


def _csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        values: dict[str, Any] = {}
        for key in _CSV_FIELDS:
            value = row.get(key, "")
            values[key] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if isinstance(value, (list, dict)) else ("" if value is None else value)
        writer.writerow(values)
    return stream.getvalue().encode("utf-8-sig")


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _preflight_pair(csv_path: Path, acceptance_path: Path, csv_data: bytes, acceptance: Mapping[str, Any]) -> str:
    if csv_path.exists() or acceptance_path.exists():
        if not csv_path.is_file() or not acceptance_path.is_file():
            raise ValueError("conflicting incomplete HK second-filter pair")
        if csv_path.read_bytes() != csv_data or json.loads(acceptance_path.read_text(encoding="utf-8-sig")) != dict(acceptance):
            raise ValueError("conflicting HK second-filter re-entry")
        return "ALREADY_COMPLETE"
    return "MATERIALIZED_FROM_SHARED_HK_0920"


def _ensure_pair(csv_path: Path, acceptance_path: Path, csv_data: bytes, acceptance: Mapping[str, Any]) -> str:
    status = _preflight_pair(csv_path, acceptance_path, csv_data, acceptance)
    if status == "ALREADY_COMPLETE":
        return status
    _atomic_bytes(csv_path, csv_data)
    _atomic_bytes(acceptance_path, json.dumps(acceptance, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"))
    return status


def _load_shared(package_root: Path) -> tuple[ModuleType, ModuleType]:
    module = load_isolated_package_module(package_root, package_directory="shared_data", module_leaf="hk_auction_0920", namespace_prefix="v35_hk_auction")
    consumer = load_isolated_package_module(package_root, package_directory="shared_data", module_leaf="consumer", namespace_prefix="v35_hk_auction")
    return module, consumer


def _read_existing_verified_capture(
    consumer_module: ModuleType | Any,
    shared_root: Path | str,
    trade_date: str,
) -> tuple[dict[str, Any], Any] | None:
    """Reuse an exact verified shared run when bridge publication is retried.

    The single shared collector publishes before the V3.5 projection.  A
    projection failure after 09:19:59 must therefore reuse that immutable,
    verified run; recollecting after cutoff is both impossible and unsafe.
    """
    store_error = getattr(consumer_module, "StoreError", None)
    if not isinstance(store_error, type) or not issubclass(store_error, Exception):
        raise ValueError("shared consumer StoreError contract missing")
    try:
        verified = consumer_module.read_verified_latest(
            shared_root,
            trade_date,
            HK_AUCTION_ROLE,
        )
    except store_error:
        return None
    verification = dict(verified.verification)
    provenance = verified.manifest.get("provenance")
    source_sha = str(provenance.get("source_output_sha256") or "") if isinstance(provenance, Mapping) else ""
    return (
        {
            "ok": True,
            "status": "READY",
            "run": {"run_id": str(verification.get("run_id") or "")},
            "source_output_sha256": source_sha,
            "reused_verified_capture": True,
        },
        verified,
    )


def _calendar_gate(trade_date: str) -> dict[str, Any]:
    states = resolve_market_states(load_market_calendar(), trade_date)
    if states["hk_securities"] is TradingDayState.UNKNOWN:
        raise ValueError("HK_SECURITIES calendar state is unknown")
    serialized = {key: value.value for key, value in states.items()}
    if states["hk_securities"] is TradingDayState.NON_TRADING_DAY:
        return {"ok": True, "status": "SKIPPED_NON_TRADING_DAY", "trade_date": trade_date, "calendar": serialized}
    return {"ok": True, "status": "ELIGIBLE", "trade_date": trade_date, "calendar": serialized}


def materialize_hkconnect_0915_0920(
    data_root: Path | str,
    shared_data_root: Path | str,
    shared_package_root: Path | str,
    trade_date: str,
    futu_python: Path | str,
    *,
    shared_module: ModuleType | Any | None = None,
    consumer_module: ModuleType | Any | None = None,
    capture_runner: Callable[..., Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    gate = _calendar_gate(trade_date)
    if gate["status"] != "ELIGIBLE":
        return {**gate, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    shared_root = Path(shared_data_root)
    if shared_module is None or consumer_module is None:
        shared_module, consumer_module = _load_shared(Path(shared_package_root))
    existing = (
        _read_existing_verified_capture(consumer_module, shared_root, trade_date)
        if capture_runner is None
        else None
    )
    auction = None
    if existing is not None:
        capture, auction = existing
    else:
        run_capture = capture_runner or shared_module.run_capture
        capture = dict(run_capture(shared_root, trade_date, Path(futu_python), sleeper=time.sleep))
    if capture.get("ok") is not True or str(capture.get("status")) != "READY":
        raise ValueError(f"shared HK capture did not complete: {capture.get('status')}")
    capture_run = capture.get("run")
    if not isinstance(capture_run, Mapping) or not str(capture_run.get("run_id") or ""):
        raise ValueError("shared HK capture run_id missing")
    if auction is None:
        auction = consumer_module.read_verified_latest(shared_root, trade_date, HK_AUCTION_ROLE)
    verification = dict(auction.verification)
    if verification.get("run_id") != capture_run.get("run_id"):
        raise ValueError("shared HK capture/read run_id mismatch")
    manifest, receipt = dict(auction.manifest), dict(auction.receipt)
    if receipt.get("status") != "READY" or receipt.get("role") != HK_AUCTION_ROLE:
        raise ValueError("shared HK reference receipt is not READY/authoritative")
    if any(receipt.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("shared HK reference safety boundary is unsafe")
    if manifest.get("trade_date") != trade_date or manifest.get("market") != "HK_CONNECT" or manifest.get("stage_id") != "STAGE_0925" or manifest.get("cutoff_at") != SIGNAL_CUTOFF or manifest.get("temporal_cutoff_safe") is not True or manifest.get("row_count") != 50:
        raise ValueError("shared HK reference manifest contract mismatch")
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("shared HK reference provenance missing")
    signal_date = str(provenance.get("signal_date") or manifest.get("signal_date") or "")
    if not re.fullmatch(r"\d{8}", signal_date) or signal_date >= trade_date:
        raise ValueError("shared HK signal_date invalid")
    auction_sha = str(verification.get("artifact_sha256") or "").lower()
    manifest_sha = str(verification.get("manifest_sha256") or "").lower()
    receipt_sha = str(verification.get("receipt_sha256") or "").lower()
    source_sha = str(provenance.get("source_output_sha256") or "").lower()
    if not all(_SHA256.fullmatch(value) for value in (auction_sha, manifest_sha, receipt_sha, source_sha)) or capture.get("source_output_sha256") != source_sha:
        raise ValueError("shared HK source_output SHA mismatch")
    if _sha_file(Path(auction.artifact_path)) != auction_sha:
        raise ValueError("shared HK artifact SHA mismatch")
    auction_rows = _read_csv(Path(auction.artifact_path))
    _validate_rows(auction_rows, trade_date, signal_date)
    d1 = consumer_module.read_verified_latest(shared_root, trade_date, HK_D1_ROLE)
    d1_verification = dict(d1.verification)
    d1_sha = str(d1_verification.get("artifact_sha256") or "").lower()
    if not _SHA256.fullmatch(d1_sha) or d1.receipt.get("status") != "READY" or d1.manifest.get("trade_date") != trade_date or d1.manifest.get("row_count") != 100:
        raise ValueError("shared HK D1 evidence is not READY/Top100")
    if any(d1.receipt.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent")):
        raise ValueError("shared HK D1 safety boundary is unsafe")
    if str(provenance.get("d1_pool_sha256") or "").lower() != d1_sha:
        raise ValueError("shared HK D1 provenance SHA mismatch")
    if hasattr(shared_module, "load_verified_candidates"):
        preselect_rows, pool_evidence = shared_module.load_verified_candidates(shared_root, trade_date)
        if pool_evidence.get("d1_pool_sha256") and str(pool_evidence["d1_pool_sha256"]).lower() != d1_sha:
            raise ValueError("shared HK D1 candidate SHA mismatch")
    else:
        preselect_rows = _read_csv(Path(d1.artifact_path))
    frozen_rows = shared_module.build_second_filter_rows(
        preselect_rows,
        _restore_source_hash_numeric_types(auction_rows),
    )
    if len(frozen_rows) != 20:
        raise ValueError("shared HK frozen Top20 shortfall")
    digest_builder = getattr(shared_module, "sha256_json", _sha_json)
    frozen_sha = str(digest_builder({"contract": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer", "trade_date": trade_date, "rows": frozen_rows})).lower()
    if frozen_sha != source_sha:
        raise ValueError("shared HK frozen Top20 source_output SHA mismatch")
    payload = build_v11_opening_second_filter(preselect_rows, auction_rows, trade_date=trade_date, signal_date=signal_date, source_evidence={"d1_pool_sha256": d1_sha, "auction_source_sha256": auction_sha, "source_output_sha256": source_sha})
    if payload.get("status") != "AUCTION_SECOND_FILTER_READY" or payload.get("row_count") != 20 or [row.get("code") for row in payload["rows"]] != [row.get("code") for row in frozen_rows]:
        raise ValueError("V3.5 Top20 diverges from shared frozen Top20")
    csv_data = _csv_bytes(payload["rows"])
    csv_sha = _sha_bytes(csv_data)
    payload["exact_csv_sha256"] = csv_sha
    pair_root = Path(data_root) / "opening_second_filter" / trade_date
    stem = f"hkconnect_0920_auction_second_filter_{trade_date}"
    acceptance = {
        "schema_version": CSV_SCHEMA_VERSION, "status": "AUCTION_SECOND_FILTER_READY", "target_date": trade_date, "signal_date": signal_date,
        "row_count": 20, "required_row_count": 20, "signal_cutoff": SIGNAL_CUTOFF, "publication_time": PUBLICATION_TIME,
        "csv_sha256": csv_sha, "csv_path": f"opening_second_filter/{trade_date}/{stem}.csv",
        "shared_role": HK_AUCTION_ROLE, "shared_run_id": verification["run_id"], "shared_artifact_sha256": auction_sha,
        "shared_manifest_sha256": manifest_sha, "shared_receipt_sha256": receipt_sha,
        "source_output_sha256": source_sha, "d1_run_id": d1_verification.get("run_id"), "d1_artifact_sha256": d1_sha,
        "temporal_cutoff_safe": True, "reference_only": True, "market_access": "NOT_TRADABLE_PREOPEN", "action_level": "NO_BUY", "research_only": True,
        "shadow_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    _preflight_pair(pair_root / f"{stem}.csv", pair_root / f"{stem}.acceptance.json", csv_data, acceptance)
    published = OpeningSecondFilterStore(Path(data_root)).publish(payload)
    status = _ensure_pair(pair_root / f"{stem}.csv", pair_root / f"{stem}.acceptance.json", csv_data, acceptance)
    return {"ok": True, "status": status, "trade_date": trade_date, "row_count": 20, "payload_path": published["payload_path"], "shared_run_id": verification["run_id"], "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--shared-data-root", required=True, type=Path)
    parser.add_argument("--shared-package-root", required=True, type=Path)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--futu-python", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = materialize_hkconnect_0915_0920(args.data_root, args.shared_data_root, args.shared_package_root, args.trade_date, args.futu_python)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"ok": False, "status": "CANNOT_CONFIRM", "error": str(error), "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
