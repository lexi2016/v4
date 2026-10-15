"""Publish an immutable automated readback of one completed natural HK stage.

This is an operation-evidence verifier.  It does not acquire, select, or write
owner data and does not claim human review, cryptographic identity, formal
eligibility, or point-in-time safety.
"""
from __future__ import annotations

import argparse
import csv
import io
import math
from datetime import datetime, timezone
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SHARED_PACKAGE_ROOT = _REPO_ROOT / "upstreams" / "v3_shared_data"
if str(_SHARED_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(1, str(_SHARED_PACKAGE_ROOT))

from infrastructure.owned_io import SafeRoot
from stage_center.contracts import STAGE_BY_ID
from stage_center.raw_store import RawStore, RAW_FIELDS
from stage_center.scheduler import evaluate_due
from stage_center.selection import SelectionStore

_SHA = re.compile(r"[0-9a-f]{64}")
_ATT_IDENTITY = "AUTOMATED_INDEPENDENT_EXECUTION_VERIFIER"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_UTC = timezone.utc
_MAX_JSON = 2 * 1024 * 1024
_MAX_SOURCE = 64 * 1024 * 1024
_SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
           "buy_gate_updated": False, "orders_sent": False}
_SELECTION_PATHS = ("artifact_relative", "manifest_relative", "receipt_relative")
_SELECTION_HASHES = (
    "artifact_bytes_sha256", "manifest_bytes_sha256", "receipt_bytes_sha256",
    "manifest_canonical_sha256", "receipt_canonical_sha256",
)


class VerificationError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _strict_loads(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON key")
            value[key] = item
        return value
    def invalid_constant(_value):
        raise ValueError("non-finite JSON constant")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid_constant)


def _read_json(root: Path, relative: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = SafeRoot(root).read_bytes(relative, max_bytes=_MAX_JSON)
        value = _strict_loads(raw.decode("utf-8"))
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        raise VerificationError("OWNER_JSON_UNREADABLE") from exc
    if not isinstance(value, dict):
        raise VerificationError("OWNER_JSON_NOT_OBJECT")
    return value, raw


def _same_root(path: Path, root: Path) -> str:
    try:
        normalized_root = root.resolve(strict=True)
        normalized_path = path.resolve(strict=False)
        if path.is_symlink() or normalized_path != path or normalized_path == normalized_root:
            raise ValueError("non-normal path")
        return normalized_path.relative_to(normalized_root).as_posix()
    except (OSError, ValueError) as exc:
        raise VerificationError("SOURCE_PATH_OUTSIDE_SELECTION_PARENT") from exc


def _evidence_pairs(evidence: list[str]) -> list[tuple[str, str, str]]:
    pairs: list[tuple[str, str, str]] = []
    for item in evidence:
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        if key and value:
            pairs.append((key, value, item))
    return pairs


def _value(pairs: list[tuple[str, str, str]], key: str) -> tuple[str, str] | None:
    found = [(value, item) for candidate, value, item in pairs if candidate == key]
    if not found:
        return None
    if len({value for value, _ in found}) != 1:
        raise VerificationError(f"SELECTION_EVIDENCE_CONFLICT:{key}")
    return found[0]


def _bound_source(evidence, key, root, *, relative=None, digest_key=None):
    pairs = _evidence_pairs(evidence)
    path_pair = _value(pairs, key)
    sha_pair = _value(pairs, digest_key or key.rsplit("_", 1)[0] + "_sha256")
    if path_pair is None or sha_pair is None or not _SHA.fullmatch(sha_pair[0]):
        raise VerificationError("CURRENT_SELECTION_SOURCE_BINDING_INCOMPLETE")
    path = Path(path_pair[0])
    source_relative = _same_root(path, root)
    if relative is not None and source_relative != relative:
        raise VerificationError("CURRENT_SELECTION_SOURCE_PATH_SCOPE_MISMATCH")
    try:
        raw = SafeRoot(root).read_bytes(source_relative, max_bytes=_MAX_SOURCE)
        payload = _strict_loads(raw)
    except (OSError, ValueError, UnicodeError) as exc:
        raise VerificationError("CURRENT_SELECTION_SOURCE_SCHEMA_INVALID") from exc
    if not isinstance(payload, dict):
        raise VerificationError("CURRENT_SELECTION_SOURCE_SCHEMA_INVALID")
    return payload, raw, path_pair, sha_pair


def _source_descriptor(path, raw, declared_sha, evidence_entries, *, identity,
                       cutoff, semantics, canonical_sha=None):
    return {"identity": identity, "path": str(path), "sha256": _sha(raw),
            "declared_sha256": declared_sha, "digest_semantics": "FILE_BYTES" if canonical_sha is None else "CANONICAL_SNAPSHOT_ROWS",
            **({"canonical_sha256": canonical_sha} if canonical_sha else {}),
            "cutoff": cutoff, "temporal_semantics": semantics,
            "evidence_entries": list(dict.fromkeys(evidence_entries))}


def _snapshot_source(evidence, raw_root, trade_date, stage_id, codes, pool_sha):
    from stage_center.hk_stage8.snapshot import load_hk_active_snapshot
    from stage_center.contracts import HK_SNAPSHOT_SCHEDULE
    loaded = load_hk_active_snapshot(raw_root, trade_date=trade_date, stage_id=stage_id,
                                    codes=sorted(codes), cutoff_at=HK_SNAPSHOT_SCHEDULE[stage_id][2],
                                    pool_artifact_sha256=pool_sha)
    if loaded.get("status") != "READY":
        raise VerificationError("CURRENT_HK_SNAPSHOT_CONTENT_INVALID:" + ",".join(loaded.get("cannot_confirm", ()))[:150])
    path = Path(str(loaded.get("snapshot_path") or ""))
    relative = _same_root(path, raw_root)
    if relative != f".hk_active_snapshots_v2/{trade_date}/{stage_id}/snapshot.json":
        raise VerificationError("CURRENT_HK_SNAPSHOT_PATH_SCOPE_MISMATCH")
    payload, raw = _read_json(raw_root, relative)
    pairs = _evidence_pairs(evidence)
    sha_pair = _value(pairs, "active_snapshot_sha256") or _value(pairs, "stage8_active_snapshot_sha256")
    path_pair = _value(pairs, "active_snapshot_path")
    if (sha_pair is None or sha_pair[0] != loaded["active_snapshot_sha256"]
            or (path_pair is not None and path_pair[0] != str(path))):
        raise VerificationError("CURRENT_HK_SNAPSHOT_EVIDENCE_MISMATCH")
    # Snapshot timestamps and membership were parsed from the actual file above.
    entries = [sha_pair[1]] + ([path_pair[1]] if path_pair else [])
    entries += [item for item in evidence if item.startswith("active_snapshot_")]
    descriptor = _source_descriptor(path, raw, sha_pair[0], entries,
        identity="FUTU_HKCONNECT_FULL_SCAN", cutoff=STAGE_BY_ID[stage_id].cutoff,
        semantics="EXACT_STAGE_PRECAPTURE; PUBLICATION_PIT_NOT_ESTABLISHED",
        canonical_sha=loaded["active_snapshot_sha256"])
    return descriptor, loaded, payload


def _source_files(evidence, raw_root, *, trade_date=None, stage_id=None,
                  codes=None, pool_sha=None):
    if trade_date is None or stage_id is None or codes is None or pool_sha is None:
        raise VerificationError("SOURCE_CONTENT_SCOPE_REQUIRED")
    snapshot, loaded, snapshot_payload = _snapshot_source(evidence, raw_root, trade_date, stage_id, codes, pool_sha)
    payload, raw, path_pair, sha_pair = _bound_source(evidence, "futu_capture_path", raw_root)
    expected = f".futu_minute_captures/{trade_date}/{stage_id}/{sha_pair[0]}.json"
    if _same_root(Path(path_pair[0]), raw_root) != expected or _sha(raw) != sha_pair[0]:
        raise VerificationError("CURRENT_SELECTION_SOURCE_SHA_OR_PATH_MISMATCH")
    if (payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id
            or payload.get("market") != "HK_CONNECT" or payload.get("adjustment") != "NONE"
            or not isinstance(payload.get("codes"), list) or len(payload["codes"]) != len(codes)
            or set(payload["codes"]) != set(codes) or not isinstance(payload.get("rows"), list)
            or not isinstance(payload.get("errors"), list) or not isinstance(payload.get("no_data_codes"), list)
            or not set(payload["no_data_codes"]).issubset(codes)):
        raise VerificationError("CURRENT_HK_CAPTURE_SCOPE_OR_SCHEMA_INVALID")
    try:
        captured = datetime.fromisoformat(payload["captured_at"])
        if captured.utcoffset() is None or captured.astimezone(_SHANGHAI).strftime("%Y%m%d") != trade_date:
            raise ValueError("capture clock scope")
        for row in payload["rows"]:
            if not isinstance(row, dict) or row.get("code") not in codes:
                raise ValueError("capture member")
            datetime.strptime(row["time_key"], "%Y-%m-%d %H:%M:%S")
            for field in ("open", "close", "high", "low", "last_close", "turnover", "volume"):
                if isinstance(row.get(field), bool) or not math.isfinite(float(row[field])):
                    raise ValueError("capture number")
            if (min(float(row[field]) for field in ("open", "close", "high", "low", "last_close")) <= 0
                    or min(float(row[field]) for field in ("turnover", "volume")) < 0
                    or float(row["high"]) < max(float(row["open"]), float(row["close"]), float(row["low"]))
                    or float(row["low"]) > min(float(row["open"]), float(row["close"]))):
                raise ValueError("capture price/volume semantics")
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise VerificationError("CURRENT_HK_CAPTURE_CONTENT_INVALID") from exc
    pairs = _evidence_pairs(evidence)
    if _value(pairs, "futu_captured_at") != (payload["captured_at"], f"futu_captured_at={payload['captured_at']}"):
        raise VerificationError("CURRENT_HK_CAPTURE_CLOCK_EVIDENCE_MISMATCH")
    provider_sha = _value(pairs, "futu_provider_rows_sha256")
    if provider_sha is None or provider_sha[0] != _sha(_canonical(payload["rows"])):
        raise VerificationError("CURRENT_HK_CAPTURE_PROVIDER_ROWS_SHA_MISMATCH")
    from upstreams.v3_shared_data.scripts.live_acquisition.futu_minute import aggregate_futu_minute_window_rows
    aggregated = aggregate_futu_minute_window_rows(trade_date, stage_id, payload["rows"])
    # Match the existing collector's snapshot order-book overlay exactly.
    for row in aggregated:
        book = loaded["by_code"][row["code"]].get("order_book") or {}
        for side, price, volume in (("Bid", "bid_price", "bid_vol"), ("Ask", "ask_price", "ask_vol")):
            levels = book.get(side) or []
            if levels and len(levels[0]) >= 2:
                row[price], row[volume] = levels[0][:2]
    descriptor = _source_descriptor(path_pair[0], raw, sha_pair[0],
        [path_pair[1], sha_pair[1], provider_sha[1], f"futu_captured_at={payload['captured_at']}",
         *[item for item in evidence if item.startswith("futu_adjustment=")]],
        identity="FUTU_K_1M", cutoff=STAGE_BY_ID[stage_id].cutoff,
        semantics="PROVIDER_BUFFER_FILTERED_BY_EXISTING_STAGE_WINDOW; CAPTURE_CLOCK_IS_NOT_AVAILABILITY")
    return [descriptor, snapshot], aggregated


def _stage8_sources(evidence, raw_root, trade_date, stage_id, codes, pool_sha):
    from stage_center.hk_stage8.rtdata import _stage8_market_timestamp, _stage8_aggregate_rtdata_rows
    snapshot, loaded, _snapshot_payload = _snapshot_source(evidence, raw_root, trade_date, stage_id, codes, pool_sha)
    payload, raw, path_pair, sha_pair = _bound_source(evidence, "stage8_rtdata_capture_path", raw_root)
    relative = f".hk_stage8_rtdata_captures/{trade_date}/{stage_id}/{sha_pair[0]}.json"
    if (_same_root(Path(path_pair[0]), raw_root) != relative or _sha(raw) != sha_pair[0]
            or payload.get("schema_version") != "stage_center.hk_stage8_rtdata_capture.v1"
            or payload.get("trade_date") != trade_date or payload.get("stage_id") != stage_id
            or payload.get("market") != "HK_CONNECT" or payload.get("codes") != sorted(codes)
            or any(payload.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or any(not isinstance(payload.get(key), list) for key in ("rows", "errors", "cleanup_warnings", "missing_codes", "batch_evidence"))
            or not set(payload["missing_codes"]).issubset(codes)):
        raise VerificationError("CURRENT_HK_STAGE8_CAPTURE_SCOPE_OR_SCHEMA_INVALID")
    try:
        start = datetime.fromisoformat(payload["provider_started_at"])
        end = datetime.fromisoformat(payload["provider_finished_at"])
        if (start.utcoffset() is None or end.utcoffset() is None or start > end
                or start.astimezone(_SHANGHAI).strftime("%Y%m%d") != trade_date
                or end.astimezone(_SHANGHAI).strftime("%Y%m%d") != trade_date
                or payload["captured_at"] != payload["provider_finished_at"]):
            raise ValueError("clock scope")
        pairs = _evidence_pairs(evidence)
        for field in ("provider_started_at", "provider_finished_at"):
            if _value(pairs, "stage8_rtdata_" + field)[0] != payload[field]:
                raise ValueError("clock evidence")
        lower = _stage8_market_timestamp("15:45:00", trade_date)
        upper = _stage8_market_timestamp("15:55:00", trade_date)
        grouped = {}
        for row in payload["rows"]:
            if not isinstance(row, dict) or row.get("code") not in codes:
                raise ValueError("member")
            when = _stage8_market_timestamp(row.get("time") or row.get("update_time"), trade_date)
            if (when is None or when.strftime("%Y%m%d") != trade_date
                    or row.get("is_blank") is True or str(row.get("is_blank", "")).lower() == "true"):
                raise ValueError("timestamp or blank")
            for field in ("cur_price", "turnover", "volume"):
                if isinstance(row.get(field), bool) or not math.isfinite(float(row[field])):
                    raise ValueError("number")
            if lower <= when <= upper:
                grouped.setdefault(row["code"], []).append((when, row))
        for code, series in grouped.items():
            expected = f"stage8_rtdata_raw_row_sha256={code}:{_sha(_canonical([row for _, row in series]))}"
            if expected not in evidence:
                raise ValueError("per-code raw hash")
        actual_hashes = {item for item in evidence if item.startswith("stage8_rtdata_raw_row_sha256=")}
        if len(actual_hashes) != len(grouped):
            raise ValueError("per-code hash count")
    except (TypeError, ValueError, KeyError, OverflowError) as exc:
        raise VerificationError("CURRENT_HK_STAGE8_CAPTURE_CONTENT_INVALID") from exc
    aggregated = [_stage8_aggregate_rtdata_rows(grouped[code], code=code,
        active_snapshot_row=loaded["by_code"][code], trade_date=trade_date, batch_index=index)
        for index, code in enumerate(sorted(grouped), 1)]
    descriptor = _source_descriptor(path_pair[0], raw, sha_pair[0],
        [path_pair[1], sha_pair[1], *[item for item in evidence if item.startswith("stage8_rtdata_")]],
        identity="FUTU_RTDATA_NATURAL", cutoff="15:55:00",
        semantics="EXACT_WINDOW_REAGGREGATED; PROVIDER_CLOCK_NOT_PUBLICATION_PIT")
    return [descriptor, snapshot], aggregated


def _auction_sources(evidence, second_root, shared_root, trade_date, stage_id, d1):
    if second_root is None or shared_root is None:
        raise VerificationError("CONFIGURED_AUCTION_SOURCE_ROOTS_REQUIRED")
    from stage_center.runner import _validate_hk_second_filter
    from ops.run_hkconnect_0915_0920_capture import (_restore_source_hash_numeric_types,
        _validate_rows, _csv_bytes, _read_csv, HK_AUCTION_ROLE, HK_D1_ROLE)
    from shared_data.consumer import read_verified_latest
    from shared_data.hk_auction_0920 import build_second_filter_rows
    from domains.opening_second_filter import build_v11_opening_second_filter
    from stage_center._live_collectors_parts.hk_auction import _collect_hk_auction_body
    import stage_center.live_collectors as live
    from types import SimpleNamespace
    try:
        csv_path, acceptance_path, digest = _validate_hk_second_filter(second_root, trade_date)
        owned_root = Path(second_root).resolve(strict=True)
        csv_relative = _same_root(csv_path, owned_root)
        acceptance_relative = _same_root(acceptance_path, owned_root)
        csv_raw = SafeRoot(owned_root).read_bytes(csv_relative, max_bytes=_MAX_SOURCE)
        acceptance, acceptance_raw = _read_json(owned_root, acceptance_relative)
        pairs = _evidence_pairs(evidence)
        for key, expected in (("second_filter_csv", str(csv_path)), ("second_filter_csv_sha256", digest)):
            if _value(pairs, key) is None or _value(pairs, key)[0] != expected:
                raise ValueError("second filter evidence")
        if (acceptance.get("schema_version") != "hkconnect_0920_auction_second_filter.v3"
                or acceptance.get("required_row_count") != 20 or acceptance.get("row_count") != 20
                or acceptance.get("signal_cutoff") != "09:19:59" or acceptance.get("publication_time") != "09:20:00"
                or acceptance.get("signal_date") != d1["source_signal_date"]
                or acceptance.get("temporal_cutoff_safe") is not True):
            raise ValueError("second filter semantics")
        shared_root = Path(shared_root).resolve(strict=True)
        auction = read_verified_latest(shared_root, trade_date, HK_AUCTION_ROLE)
        shared_d1 = read_verified_latest(shared_root, trade_date, HK_D1_ROLE)
        manifest = auction.manifest
        if (manifest.get("trade_date") != trade_date or manifest.get("market") != "HK_CONNECT" or manifest.get("stage_id") != stage_id
                or manifest.get("cutoff_at") != "09:19:59" or manifest.get("row_count") != 50
                or manifest.get("temporal_cutoff_safe") is not True or auction.receipt.get("status") != "READY"
                or shared_d1.manifest.get("trade_date") != trade_date
                or shared_d1.manifest.get("row_count") != 100 or shared_d1.receipt.get("status") != "READY"):
            raise ValueError("auction source trio semantics")
        for field in ("run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256"):
            if acceptance.get("shared_" + field) != auction.verification.get(field):
                raise ValueError("auction source trio identity")
        if (acceptance.get("d1_artifact_sha256") != shared_d1.verification.get("artifact_sha256")
                or acceptance.get("d1_run_id") != shared_d1.verification.get("run_id")):
            raise ValueError("auction D1 source identity")
        source_rows = _read_csv(auction.artifact_path)
        preselect_rows = _read_csv(shared_d1.artifact_path)
        if {row.get("code", row.get("symbol")) for row in preselect_rows} != set(d1["codes"]):
            raise ValueError("auction Top100 mapping")
        _validate_rows(source_rows, trade_date, d1["source_signal_date"])
        frozen = build_second_filter_rows(preselect_rows, _restore_source_hash_numeric_types(source_rows))
        frozen_sha = _sha(_canonical({"contract": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer",
                                     "trade_date": trade_date, "rows": frozen}))
        if len(frozen) != 20 or acceptance.get("source_output_sha256") != frozen_sha:
            raise ValueError("auction Top20 source digest")
        provenance = manifest.get("provenance")
        if (not isinstance(provenance, dict) or provenance.get("source_output_sha256") != frozen_sha
                or provenance.get("signal_date") != d1["source_signal_date"]
                or provenance.get("d1_pool_sha256") != shared_d1.verification.get("artifact_sha256")):
            raise ValueError("auction source provenance")
        projected = build_v11_opening_second_filter(preselect_rows, source_rows, trade_date=trade_date,
            signal_date=d1["source_signal_date"], source_evidence={
                "d1_pool_sha256": acceptance["d1_artifact_sha256"],
                "auction_source_sha256": acceptance["shared_artifact_sha256"], "source_output_sha256": frozen_sha})
        if (projected.get("row_count") != 20 or _csv_bytes(projected["rows"]) != csv_raw
                or [row["code"] for row in projected["rows"]] != [row["code"] for row in frozen]):
            raise ValueError("auction persisted Top20 projection")
        source = _collect_hk_auction_body(live.__dict__, SimpleNamespace(trade_date=trade_date, stage_id=stage_id),
            codes=tuple(d1["codes"]), python_path=None, shared_root=None, auction_root=csv_path,
            process_runner=None, replay_provider=None)
        aggregated = [dict(row) for row in source.rows if row["code"] in set(d1["codes"])]
        descriptors = [_source_descriptor(csv_path, csv_raw, digest,
            [f"second_filter_csv={csv_path}", f"second_filter_csv_sha256={digest}"], identity="HK_AUCTION_SECOND_FILTER_TOP20",
            cutoff="09:19:59", semantics="EXACT_DATE_TOP50_TO_TOP20_REPRODUCED")]
        for path in [acceptance_path, auction.artifact_path, auction.manifest_path, auction.receipt_path,
                     shared_d1.artifact_path, shared_d1.manifest_path, shared_d1.receipt_path]:
            root = owned_root if path == acceptance_path else shared_root
            raw = SafeRoot(root).read_bytes(_same_root(path, root), max_bytes=_MAX_SOURCE)
            descriptors.append(_source_descriptor(path, raw, _sha(raw), [], identity="AUCTION_AUTHORITY_TRIO",
                cutoff="09:19:59", semantics="READ_ONLY_CONFIGURED_SOURCE_TRIO"))
        return descriptors, aggregated
    except VerificationError:
        raise
    except Exception as exc:
        raise VerificationError("CURRENT_HK_AUCTION_CONTENT_OR_LINEAGE_INVALID") from exc


def _reconcile_rows(aggregated, raw_root, raw_verified, lane, codes):
    raw = SafeRoot(raw_root).read_bytes(raw_verified["artifact_relative"], max_bytes=_MAX_SOURCE)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    expected = {row["code"]: row for row in aggregated}
    actual = {row["code"]: row for row in rows}
    if (len(actual) != len(rows) or len(expected) != len(aggregated) or set(actual) != set(expected)
            or not set(actual).issubset(codes) or raw_verified.get("requested_rows") != len(codes)
            or lane.get("source_rows") != len(actual) or lane.get("requested_rows") != len(codes)):
        raise VerificationError("CURRENT_HK_CAPTURE_RAW_MEMBERSHIP_OR_COUNT_MISMATCH")
    numeric = {"batch_index", "last_price", "open_price", "high_price", "low_price", "prev_close_price",
               "turnover", "volume", "bid_price", "ask_price", "bid_vol", "ask_vol", "bar_count"}
    def equal(left, right, field):
        if left in (None, "") or right in (None, ""):
            return left in (None, "") and right in (None, "")
        if field in numeric:
            try:
                return math.isfinite(float(left)) and math.isfinite(float(right)) and math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-10)
            except (TypeError, ValueError):
                return False
        return str(left) == str(right)
    for code, row in expected.items():
        for field in RAW_FIELDS:
            if not equal(row.get(field), actual[code].get(field), field):
                raise VerificationError(f"CURRENT_HK_CAPTURE_RAW_VALUE_MISMATCH:{field}")
    selected = lane.get("rows")
    if not isinstance(selected, list) or len({row.get("code") for row in selected}) != len(selected):
        raise VerificationError("CURRENT_HK_SELECTION_ROWS_INVALID")
    for selected_row in selected:
        row = expected.get(selected_row.get("code"))
        if row is None:
            raise VerificationError("CURRENT_HK_SELECTION_OUTSIDE_SOURCE_MEMBERSHIP")
        # Public selection card levels are direct projections of the verified
        # aggregate. Scores and trade gates retain the existing selector owner.
        for output, source in (("support", "low_price"), ("pressure", "high_price"), ("invalidation", "low_price")):
            if not equal(selected_row.get(output), row.get(source), "last_price"):
                raise VerificationError("CURRENT_HK_SELECTION_SOURCE_PROJECTION_MISMATCH")
    return {"source_rows": len(aggregated), "raw_rows": len(rows), "selected_rows": len(selected),
            "status": "SOURCE_WINDOW_REAGGREGATED_RAW_AND_SELECTION_PROJECTIONS_RECONCILED"}


def _time_facts(evidence: list[str], trade_date: str, stage_id: str) -> dict[str, Any]:
    stage = STAGE_BY_ID[stage_id]
    cutoff = datetime.fromisoformat(f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}T{stage.cutoff}").replace(tzinfo=_SHANGHAI)
    captures: list[dict[str, str]] = []
    malformed: list[str] = []
    for key, value, _entry in _evidence_pairs(evidence):
        if not any(part in key for part in ("captured_at", "capture_time", "provider_started_at", "provider_finished_at")):
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError("timezone missing")
            local = parsed.astimezone(_SHANGHAI)
            captures.append({"field": key, "value": value,
                             "after_stage_cutoff": str(local >= cutoff).lower()})
        except (TypeError, ValueError, OverflowError):
            malformed.append(key)
    reasons = ["FORMAL_ELIGIBILITY_NOT_ESTABLISHED", "FULL_CHAIN_PIT_NOT_ESTABLISHED"]
    if malformed:
        reasons.append("SOURCE_CAPTURE_CLOCK_UNPARSEABLE")
    if not captures:
        reasons.append("SOURCE_CAPTURE_CLOCK_UNAVAILABLE")
    if any(item["after_stage_cutoff"] == "true" for item in captures):
        reasons.append("SOURCE_CAPTURE_AT_OR_AFTER_STAGE_CUTOFF")
    return {
        "operation_status": "VERIFIED",
        "formal_eligibility_status": "CANNOT_CONFIRM",
        "pit_status": "CANNOT_CONFIRM",
        "pit_cannot_confirm": list(dict.fromkeys(reasons)),
        "stage_cutoff_local": cutoff.isoformat(),
        "capture_times": captures,
        "unparseable_clock_fields": malformed,
    }


def _refuse_d1_pending(roots, trade_date):
    for root in dict.fromkeys(Path(root) for root in roots if root is not None):
        for relative in (f"preselection_pending_commits/{trade_date}/hkconnect_d1_top100.json", ".import.lock"):
            try:
                SafeRoot(root).read_bytes(relative, max_bytes=_MAX_JSON)
            except FileNotFoundError:
                continue
            raise VerificationError("CURRENT_HK_D1_PENDING_OR_IMPORT_IN_PROGRESS")


def _d1_pool_semantics(payload, trade_date):
    """Pure HK-specific rules from the deployed D1 input contract."""
    from datetime import timedelta
    from stage_center.calendar import resolve_market_states, TradingDayState
    def previous_session(market):
        cursor = datetime.strptime(trade_date, "%Y%m%d")
        for _ in range(15):
            cursor -= timedelta(days=1)
            candidate = cursor.strftime("%Y%m%d")
            state = resolve_market_states(candidate)[market]
            if state is TradingDayState.UNKNOWN:
                raise ValueError("D1 calendar unknown")
            if state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
                return candidate
        raise ValueError("D1 previous session unavailable")
    signal = previous_session("hk_securities")
    eligibility = previous_session("hk_connect")
    rows = payload.get("rows")
    if (payload.get("status") != "STRICT_0_2_READY" or payload.get("market") != "HK"
            or payload.get("producer_id") != "v3_shared_hk_0_2_consumer_v1"
            or payload.get("source_role") != "SHARED_VERIFIED_HK_0_2"
            or payload.get("trade_date") != trade_date or payload.get("target_date", trade_date) != trade_date
            or payload.get("signal_date") != signal
            or payload.get("stage_selection_eligible", True) is not True
            or not isinstance(rows, list) or len(rows) != 100):
        raise ValueError("D1 exact-date status/source/Top100 scope")
    if signal != eligibility:
        provenance = payload.get("historical_provenance")
        if (not isinstance(provenance, dict)
                or provenance.get("schema_version") != "v4.hk_d1_split_date_provenance.v1"
                or provenance.get("price_signal_date") != signal
                or provenance.get("eligibility_source_date") != eligibility):
            raise ValueError("D1 split-date provenance")
        captured = datetime.fromisoformat(provenance["eligibility_source_captured_at"])
        if captured.utcoffset() is None or captured.astimezone(_SHANGHAI).strftime("%Y%m%d") != eligibility:
            raise ValueError("D1 eligibility capture date")
    models = []
    codes = []
    for item in [payload, *rows]:
        for key in ("model_id", "model", "model_name", "selected_strategy", "weekly_tuning_selected_strategy"):
            if item.get(key) not in (None, ""):
                models.append(str(item[key]))
    if any("prob_active" not in model.lower() for model in models):
        raise ValueError("D1 model identity")
    for row in rows:
        code = row.get("symbol", row.get("code"))
        if (row.get("market") != "HK" or row.get("signal_date") != signal
                or not isinstance(code, str) or re.fullmatch(r"HK\.\d{5}", code) is None
                or any(row.get(key) not in (None, code) for key in ("code", "symbol"))
                or any(row.get(key) not in (None, trade_date) for key in ("trade_date", "target_date"))):
            raise ValueError("D1 member/date/market identity")
        codes.append(code)
    if len(set(codes)) != 100:
        raise ValueError("D1 exact unique Top100")
    return codes


def _d1_pool_time_binding(evidence, d1_root, trade_date, *, preselection_source_root=None):
    from infrastructure.preselection_pool_store import PreselectionSourceResolver, PreselectionPoolStore, validate_pool_artifact
    from infrastructure.data_store import _canonical_bytes
    pairs = _evidence_pairs(evidence)
    path_pair = _value(pairs, "hk_d1_json")
    sha_pair = _value(pairs, "hk_d1_sha256")
    if path_pair is None or sha_pair is None or not _SHA.fullmatch(sha_pair[0]):
        raise VerificationError("CURRENT_HK_D1_POOL_PATH_SHA_MISSING")
    configured_roots = (d1_root, preselection_source_root)
    resolver = PreselectionSourceResolver(d1_root, source_root=preselection_source_root)
    try:
        _refuse_d1_pending(configured_roots, trade_date)
        # root_for_date is the existing pure whole-date ownership rule. Never
        # call a store read facade: those facades own locks and crash recovery.
        physical_root = resolver.root_for_date(trade_date)
        prefix = f"preselection_pools/{trade_date}"
        artifact_relative, receipt_relative = PreselectionPoolStore._relative(trade_date, "hkconnect_d1_top100")
        relatives = {"artifact": artifact_relative,
                     "manifest": f"{prefix}/manifest.json", "receipt": receipt_relative}
        owner_io = SafeRoot(physical_root)
        raw = {key: owner_io.read_bytes(relative, max_bytes=_MAX_JSON) for key, relative in relatives.items()}
        values = {key: _strict_loads(data) for key, data in raw.items()}
        if any(not isinstance(value, dict) or raw[key] != _canonical_bytes(value) for key, value in values.items()):
            raise ValueError("D1 physical trio canonical bytes")
        payload, manifest, receipt = (values[key] for key in ("artifact", "manifest", "receipt"))
        digest = _sha(raw["artifact"])
        path = Path(physical_root) / relatives["artifact"]
        if (str(path) != path_pair[0] or digest != sha_pair[0]
                or manifest.get("hkconnect_d1_top100") != digest
                or validate_pool_artifact(payload) != trade_date or payload.get("pool_id") != "hkconnect_d1_top100"):
            raise ValueError("D1 exact-date configured artifact/manifest identity")
        expected_receipt = PreselectionPoolStore._receipt(trade_date=trade_date,
            pool_id="hkconnect_d1_top100", artifact_path=relatives["artifact"], artifact_sha256=digest, payload=payload)
        if receipt != expected_receipt:
            raise ValueError("D1 physical receipt content")
        codes = _d1_pool_semantics(payload, trade_date)
        for key, relative in relatives.items():
            if owner_io.read_bytes(relative, max_bytes=_MAX_JSON) != raw[key]:
                raise ValueError("D1 physical trio changed")
        _refuse_d1_pending(configured_roots, trade_date)
        if resolver.root_for_date(trade_date) != physical_root:
            raise ValueError("D1 date owner changed")
    except VerificationError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise VerificationError("CURRENT_HK_D1_POOL_CONTENT_OR_OWNER_INVALID") from exc
    return {"status": "CONFIGURED_EXACT_DATE_TOP100_TRIO_VERIFIED", "path": str(path), "sha256": digest,
            "physical_source_root": str(physical_root), "source_trade_date": payload["trade_date"],
            "source_signal_date": payload["signal_date"], "target_date": trade_date, "codes": sorted(codes),
            "manifest_relative": relatives["manifest"], "manifest_sha256": _sha(raw["manifest"]),
            "receipt_relative": relatives["receipt"], "receipt_sha256": _sha(raw["receipt"]),
            "membership_semantics": "exact_date_top100", "source_time_evidence_entries": [path_pair[1], sha_pair[1]],
            "cannot_confirm": ["ORIGINAL_SOURCE_PUBLICATION_PIT_NOT_ESTABLISHED"]}


def _attempt_binding(receipt_root: Path, trade_date: str, stage_id: str,
                     receipt: dict[str, Any]) -> dict[str, Any]:
    journal = receipt.get("attempt_diagnostic")
    attempt_id = journal.get("attempt_id") if isinstance(journal, dict) else None
    if not isinstance(attempt_id, str) or not re.fullmatch(r"[0-9a-f]{32}", attempt_id):
        raise VerificationError("CURRENT_ATTEMPT_ID_MISSING")
    if (receipt.get("dispatch_mode") != "NATURAL" or receipt.get("due_status") != "DUE"
            or receipt.get("node_attempt_count") != 1 or receipt.get("mode") == "BACKFILL"
            or receipt.get("execution_origin") not in (None, "NATURAL")
            or receipt.get("same_day_late_observation_recovery") is True):
        raise VerificationError("CURRENT_RUN_NOT_SINGLE_ATTEMPT_NATURAL_DUE")
    declared = journal.get("relative_paths")
    start_suffix = f"attempt_evidence/{attempt_id}/001_START.json"
    if not isinstance(declared, list) or start_suffix not in declared:
        raise VerificationError("CURRENT_ATTEMPT_START_NOT_DECLARED")
    relative = f"{trade_date}/{stage_id}/{start_suffix}"
    start, raw = _read_json(receipt_root, relative)
    if any(start.get(key) != value for key, value in {
        "schema": "stage.attempt_diagnostic.v1", "event": "START", "attempt_id": attempt_id,
        "trade_date": trade_date, "stage_id": stage_id, "attempt_number": 1,
    }.items()):
        raise VerificationError("CURRENT_ATTEMPT_START_SCOPE_CONFLICT")
    try:
        evaluated = datetime.fromisoformat(start["evaluated_at"])
        observed = datetime.fromisoformat(start["observed_at"])
        if evaluated.utcoffset() is None or observed.utcoffset() is None:
            raise ValueError("timezone required")
        evaluated, observed = evaluated.astimezone(_SHANGHAI), observed.astimezone(_SHANGHAI)
        if (evaluated.strftime("%Y%m%d") != trade_date or observed.strftime("%Y%m%d") != trade_date
                or observed < evaluated):
            raise ValueError("attempt clock conflict")
        due = evaluate_due(stage_id, trade_date, evaluated)
        observed_due = evaluate_due(stage_id, trade_date, observed)
        if due.status != "DUE" or observed_due.status != "DUE" or due.scheduled_at is None:
            raise ValueError("attempt is outside natural schedule")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise VerificationError("CURRENT_ATTEMPT_CLOCK_NOT_ON_SCHEDULE") from exc
    return {
        "mode": "NATURAL", "due_status": "DUE", "attempt_id": attempt_id,
        "attempt_count": 1, "attempt_relative_path": relative, "attempt_sha256": _sha(raw),
        "scheduled_at_local": due.scheduled_at.astimezone(_SHANGHAI).isoformat(),
        "evaluated_at_local": evaluated.isoformat(), "observed_at_local": observed.isoformat(),
    }


def _validated_attestation(*, trade_date: str, stage_id: str, receipt_root: Path,
                       raw_root: Path, selection_root: Path,
                       expected_receipt_sha256: str, hk_d1_root: Path | None = None,
                       preselection_source_root: Path | None = None,
                       hk_second_filter_root: Path | None = None,
                       shared_research_root: Path | None = None) -> dict[str, Any]:
    if not re.fullmatch(r"\d{8}", trade_date) or stage_id not in STAGE_BY_ID:
        raise VerificationError("STAGE_SCOPE_INVALID")
    if "HK_CONNECT" not in STAGE_BY_ID[stage_id].markets:
        raise VerificationError("STAGE_HAS_NO_HK_MARKET")
    if not _SHA.fullmatch(expected_receipt_sha256):
        raise VerificationError("EXPECTED_RECEIPT_SHA_INVALID")
    receipt_root, raw_root, selection_root = (Path(item).expanduser().resolve(strict=True)
                                               for item in (receipt_root, raw_root, selection_root))
    receipt_relative = f"{trade_date}/{stage_id}/receipt.json"
    receipt, receipt_raw = _read_json(receipt_root, receipt_relative)
    actual_receipt_sha = _sha(receipt_raw)
    if actual_receipt_sha != expected_receipt_sha256:
        raise VerificationError("EXPECTED_RECEIPT_SHA_MISMATCH")
    if (receipt.get("schema_version") != "stage_center.runner.receipt.v1"
            or receipt.get("runner") != "stage_center"
            or receipt.get("trade_date") != trade_date
            or receipt.get("stage_id") != stage_id):
        raise VerificationError("CURRENT_RECEIPT_SCOPE_CONFLICT")
    if any(receipt.get(key) is not value for key, value in _SAFETY.items()):
        raise VerificationError("CURRENT_RECEIPT_SAFETY_FLAGS_INCOMPLETE")

    history = receipt.get("receipt_history")
    if not isinstance(history, dict):
        raise VerificationError("OWNER_HISTORY_REFERENCE_MISSING")
    history_sha = history.get("sha256")
    history_relative = history.get("relative_path")
    expected_history = f"{trade_date}/{stage_id}/attempt_evidence/recorded-{history_sha}/RECEIPT.json"
    if not isinstance(history_sha, str) or not _SHA.fullmatch(history_sha) or history_relative != expected_history:
        raise VerificationError("OWNER_HISTORY_REFERENCE_CONFLICT")
    owner_history = SafeRoot(receipt_root).read_bytes(history_relative, max_bytes=_MAX_JSON)
    if _sha(owner_history) != history_sha:
        raise VerificationError("CURRENT_OWNER_HISTORY_SHA_MISMATCH")
    history_expected = {key: value for key, value in receipt.items() if key != "receipt_history"}
    try:
        history_value = json.loads(owner_history.decode("utf-8"))
        if not isinstance(history_value, dict) or _canonical(history_value) != _canonical(history_expected):
            raise VerificationError("CURRENT_OWNER_HISTORY_CONTENT_MISMATCH")
        if (history_value.get("record_time_source") != "OWNER_WRITE_CLOCK_UTC"
                or not isinstance(history_value.get("recorded_at"), str)):
            raise VerificationError("CURRENT_OWNER_HISTORY_WRITE_CLOCK_MISSING")
        recorded_at = datetime.fromisoformat(history_value["recorded_at"].replace("Z", "+00:00"))
        if recorded_at.utcoffset() is None or recorded_at.utcoffset().total_seconds() != 0:
            raise VerificationError("CURRENT_OWNER_HISTORY_WRITE_CLOCK_INVALID")
    except VerificationError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise VerificationError("CURRENT_OWNER_HISTORY_CONTENT_INVALID") from exc

    attempt = _attempt_binding(receipt_root, trade_date, stage_id, receipt)
    lane_receipt = (receipt.get("markets") or {}).get("HK_CONNECT")
    if not isinstance(lane_receipt, dict):
        raise VerificationError("CURRENT_HK_SELECTION_REFERENCE_MISSING")
    selection_store = SelectionStore(selection_root)
    lane = selection_store.read_verified(trade_date, stage_id, "HK_CONNECT")
    run_id = lane.get("run_id")
    if not isinstance(run_id, str) or lane_receipt.get("run_id") != run_id:
        raise VerificationError("CURRENT_HK_SELECTION_RUN_MISMATCH")
    verified_selection = selection_store._verify_run(trade_date, stage_id, "HK_CONNECT", run_id)
    selection_prefix = PurePosixPath(verified_selection["artifact_relative"]).parent
    selection_paths = {
        "artifact_relative": verified_selection["artifact_relative"],
        "manifest_relative": f"{selection_prefix}/manifest.json",
        "receipt_relative": f"{selection_prefix}/receipt.json",
    }
    selection_raw = {key: SafeRoot(selection_root).read_bytes(path, max_bytes=_MAX_SOURCE)
                     for key, path in selection_paths.items()}
    selection_binding = {
        **selection_paths, "run_id": run_id,
        "artifact_bytes_sha256": _sha(selection_raw["artifact_relative"]),
        "manifest_bytes_sha256": _sha(selection_raw["manifest_relative"]),
        "receipt_bytes_sha256": _sha(selection_raw["receipt_relative"]),
        "manifest_canonical_sha256": _sha(_canonical(json.loads(selection_raw["manifest_relative"]))),
        "receipt_canonical_sha256": _sha(_canonical(json.loads(selection_raw["receipt_relative"]))),
    }
    recorded_binding = receipt.get("selection_artifacts", {}).get("HK_CONNECT")
    if not isinstance(recorded_binding, dict) or any(recorded_binding.get(key) != value
                                                     for key, value in selection_binding.items()):
        raise VerificationError("CURRENT_HK_SELECTION_TRIO_MISMATCH")
    if (lane.get("market") != "HK_CONNECT" or lane.get("trade_date") != trade_date
            or lane.get("stage_id") != stage_id or lane.get("source_evidence") != lane_receipt.get("source_evidence")):
        raise VerificationError("CURRENT_HK_SELECTION_SCOPE_OR_EVIDENCE_MISMATCH")

    raw_latest = RawStore(raw_root).verify_latest(trade_date, stage_id, "HK_CONNECT")
    raw_verified = raw_latest["verified"]
    if raw_verified.get("status") not in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}:
        raise VerificationError("CURRENT_HK_RAW_ARTIFACT_NOT_OBSERVABLE")
    if (raw_verified.get("artifact_sha256") != lane.get("raw_artifact_sha256")
            or raw_verified.get("artifact_sha256") != lane_receipt.get("raw_artifact_sha256")):
        raise VerificationError("CURRENT_HK_RAW_ARTIFACT_SHA_MISMATCH")
    stage = STAGE_BY_ID[stage_id]
    expected_window = stage.hk_window if stage_id == "STAGE_0925" else stage.window
    if raw_verified.get("window") != expected_window or raw_verified.get("cutoff_at") != stage.cutoff:
        raise VerificationError("CURRENT_HK_RAW_WINDOW_OR_CUTOFF_MISMATCH")
    raw_source_evidence = raw_verified.get("source_evidence")
    source_evidence = lane.get("source_evidence")
    if (not isinstance(source_evidence, list) or not source_evidence
            or not isinstance(raw_source_evidence, list)
            or not set(raw_source_evidence).issubset(set(source_evidence))):
        raise VerificationError("CURRENT_HK_RAW_SOURCE_EVIDENCE_MISMATCH")
    if hk_d1_root is None:
        raise VerificationError("CONFIGURED_HK_D1_ROOT_REQUIRED")
    hk_d1_root = Path(hk_d1_root).resolve(strict=True)
    preselection_source_root = (Path(preselection_source_root).resolve(strict=True)
                               if preselection_source_root is not None else None)
    d1_pool_binding = _d1_pool_time_binding(source_evidence, hk_d1_root, trade_date,
                                           preselection_source_root=preselection_source_root)
    codes = set(d1_pool_binding["codes"])
    if stage_id == "STAGE_0925":
        source_descriptors, aggregated = _auction_sources(source_evidence, hk_second_filter_root,
            shared_research_root, trade_date, stage_id, d1_pool_binding)
    elif stage_id == "STAGE_1545_1555":
        source_descriptors, aggregated = _stage8_sources(source_evidence, raw_root,
            trade_date, stage_id, codes, d1_pool_binding["sha256"])
    else:
        source_descriptors, aggregated = _source_files(source_evidence, raw_root,
            trade_date=trade_date, stage_id=stage_id, codes=codes, pool_sha=d1_pool_binding["sha256"])
    source_reconciliation = _reconcile_rows(aggregated, raw_root, raw_verified, lane, codes)

    time_facts = _time_facts(source_evidence, trade_date, stage_id)
    reviewed_at = datetime.now(_UTC).isoformat().replace("+00:00", "Z")
    attestation = {
        "schema_version": "stage_center.independent_execution_review.v1",
        "trade_date": trade_date, "stage_id": stage_id, "runner": "stage_center",
        "scope_markets": ["HK_CONNECT"],
        "scope_semantics": "SCHEDULER_AND_ARTIFACT_OPERATION_FACTS_ONLY",
        "reviewer_identity_or_role": _ATT_IDENTITY,
        "reviewer_verifier_code_sha256": _sha(Path(__file__).read_bytes()),
        "reviewed_at_utc": reviewed_at,
        "runner_receipt": {"relative_path": receipt_relative, "sha256": actual_receipt_sha},
        "owner_history": {"relative_path": history_relative, "sha256": history_sha},
        "markets": {"HK_CONNECT": {
            "operation_scope": "SCHEDULER_AND_ARTIFACT_OPERATION_FACTS_ONLY",
            "selection": selection_binding,
            "source_binding": {
                "schema_version": "stage_center.automated_source_binding.v1",
                "source_evidence_sha256": _sha(_canonical(source_evidence)),
                "sources": source_descriptors,
            },
            "operation_status": "VERIFIED",
            "formal_eligibility_status": time_facts["formal_eligibility_status"],
            "pit_status": time_facts["pit_status"],
            "pit_cannot_confirm": time_facts["pit_cannot_confirm"],
        }},
        "dispatch": attempt,
        "safety": dict(_SAFETY),
        "execution_inputs": {
            "raw_artifact": {"relative_path": raw_verified["artifact_relative"],
                              "sha256": raw_verified["artifact_sha256"],
                              "manifest_sha256": raw_verified["manifest_sha256"],
                              "receipt_sha256": raw_verified["receipt_sha256"]},
            "source_files": source_descriptors,
            "source_time_facts": time_facts,
            "source_reconciliation": source_reconciliation,
            "d1_pool_time_binding": d1_pool_binding,
        },
    }
    # Re-read every bound input after constructing the attestation. A change
    # during verification invalidates the whole result.
    io = SafeRoot(receipt_root)
    if io.read_bytes(receipt_relative, max_bytes=_MAX_JSON) != receipt_raw:
        raise VerificationError("CURRENT_RECEIPT_CHANGED_DURING_REVIEW")
    if io.read_bytes(history_relative, max_bytes=_MAX_JSON) != owner_history:
        raise VerificationError("CURRENT_OWNER_HISTORY_CHANGED_DURING_REVIEW")
    attempt_raw = io.read_bytes(attempt["attempt_relative_path"], max_bytes=_MAX_JSON)
    if _sha(attempt_raw) != attempt["attempt_sha256"]:
        raise VerificationError("CURRENT_ATTEMPT_CHANGED_DURING_REVIEW")
    selection_io = SafeRoot(selection_root)
    for key, relative in selection_paths.items():
        if selection_io.read_bytes(relative, max_bytes=_MAX_SOURCE) != selection_raw[key]:
            raise VerificationError("CURRENT_HK_SELECTION_CHANGED_DURING_REVIEW")
    source_file_bindings = [
        (descriptor["path"], descriptor["sha256"]) for descriptor in source_descriptors
    ] + [(d1_pool_binding["path"], d1_pool_binding["sha256"])]
    for source_path, source_sha in dict.fromkeys(source_file_bindings):
        if source_path == d1_pool_binding["path"]:
            source_root = Path(d1_pool_binding["physical_source_root"])
        elif stage_id == "STAGE_0925":
            path = Path(source_path)
            second_root = Path(hk_second_filter_root).resolve(strict=True)
            source_root = second_root if path.is_relative_to(second_root) else Path(shared_research_root).resolve(strict=True)
        else:
            source_root = raw_root
        relative = _same_root(Path(source_path), source_root)
        if _sha(SafeRoot(source_root).read_bytes(relative, max_bytes=_MAX_SOURCE)) != source_sha:
            raise VerificationError("CURRENT_SELECTION_SOURCE_CHANGED_DURING_REVIEW")
    d1_after = _d1_pool_time_binding(source_evidence, hk_d1_root, trade_date,
                                     preselection_source_root=preselection_source_root)
    if d1_after != d1_pool_binding:
        raise VerificationError("CURRENT_HK_D1_TRIO_CHANGED_DURING_REVIEW")
    raw_latest_after = RawStore(raw_root).verify_latest(trade_date, stage_id, "HK_CONNECT")
    if (raw_latest_after.get("latest") != raw_latest.get("latest")
            or raw_latest_after.get("verified", {}).get("artifact_sha256") != raw_verified.get("artifact_sha256")
            or raw_latest_after.get("verified", {}).get("manifest_sha256") != raw_verified.get("manifest_sha256")
            or raw_latest_after.get("verified", {}).get("receipt_sha256") != raw_verified.get("receipt_sha256")):
        raise VerificationError("CURRENT_HK_RAW_CHANGED_DURING_REVIEW")
    # This function and its public validation wrapper never create, repair,
    # lock, or publish any artifact. The writer path starts below.
    return attestation


def validate_execution_inputs(**kwargs):
    """Re-read configured owner inputs only; this entry point performs no writes."""
    return _validated_attestation(**kwargs)["execution_inputs"]


def verify_and_publish(**kwargs):
    attestation = _validated_attestation(**kwargs)
    trade_date, stage_id = kwargs["trade_date"], kwargs["stage_id"]
    receipt_root = Path(kwargs["receipt_root"])
    actual_receipt_sha = kwargs["expected_receipt_sha256"]
    time_facts = attestation["execution_inputs"]["source_time_facts"]
    io = SafeRoot(receipt_root)
    attestation_relative = f"independent_execution_reviews/{trade_date}/{stage_id}/attestation.json"
    index_relative = f"independent_execution_reviews/{trade_date}/{stage_id}/index.json"
    attestation_raw = _canonical(attestation)
    index = {
        "schema_version": "stage_center.independent_execution_review_index.v1",
        "trade_date": trade_date, "stage_id": stage_id,
        "attestation_relative_path": attestation_relative,
        "attestation_sha256": _sha(attestation_raw),
    }
    index_raw = _canonical(index)
    lock_relative = f"independent_execution_reviews/.locks/{trade_date}-{stage_id}.lock"
    with io.kernel_lock(lock_relative):
        try:
            existing_attestation = io.read_bytes(attestation_relative, max_bytes=_MAX_JSON)
            existing_index = io.read_bytes(index_relative, max_bytes=_MAX_JSON)
        except FileNotFoundError:
            existing_attestation = existing_index = None
        if existing_attestation is not None or existing_index is not None:
            if (existing_attestation == attestation_raw and existing_index == index_raw):
                return {"status": "IDEMPOTENT_EXISTING", "receipt_sha256": actual_receipt_sha,
                        "attestation_sha256": _sha(existing_attestation), "index_sha256": _sha(existing_index),
                        "pit_status": time_facts["pit_status"],
                        "pit_cannot_confirm": time_facts["pit_cannot_confirm"]}
            # The reviewed_at clock changes on a duplicate invocation; accept
            # only a complete pair already bound to the same current receipt.
            try:
                old_index, _ = _read_json(receipt_root, index_relative)
                old_attestation = json.loads(existing_attestation.decode("utf-8")) if existing_attestation else None
            except (OSError, ValueError, UnicodeError, RecursionError):
                old_index, old_attestation = {}, None
            expected_old_attestation = dict(attestation)
            if isinstance(old_attestation, dict):
                expected_old_attestation["reviewed_at_utc"] = old_attestation.get("reviewed_at_utc")
            expected_old_index = {
                "schema_version": "stage_center.independent_execution_review_index.v1",
                "trade_date": trade_date, "stage_id": stage_id,
                "attestation_relative_path": attestation_relative,
                "attestation_sha256": _sha(existing_attestation or b""),
            }
            if (isinstance(old_index, dict) and isinstance(old_attestation, dict)
                    and old_attestation == expected_old_attestation
                    and old_index == expected_old_index):
                return {"status": "IDEMPOTENT_EXISTING", "receipt_sha256": actual_receipt_sha,
                        "attestation_sha256": _sha(existing_attestation), "index_sha256": _sha(existing_index or b""),
                        "pit_status": time_facts["pit_status"],
                        "pit_cannot_confirm": time_facts["pit_cannot_confirm"]}
            raise VerificationError("INDEPENDENT_REVIEW_PUBLICATION_CONFLICT")
        try:
            io.write_bytes(attestation_relative, attestation_raw, require_absent=True)
            io.write_bytes(index_relative, index_raw, require_absent=True)
        except (OSError, ValueError) as exc:
            raise VerificationError("INDEPENDENT_REVIEW_PUBLICATION_CONFLICT") from exc
    return {"status": "PUBLISHED", "receipt_sha256": actual_receipt_sha,
            "attestation_sha256": _sha(attestation_raw), "index_sha256": _sha(index_raw),
            "pit_status": time_facts["pit_status"],
            "pit_cannot_confirm": time_facts["pit_cannot_confirm"]}


def _reject(receipt_root: Path, trade_date: str, stage_id: str,
            expected_receipt_sha256: str, reason: str) -> None:
    if not _SHA.fullmatch(expected_receipt_sha256 or ""):
        return
    relative = f"independent_execution_reviews/rejections/{trade_date}/{stage_id}/{expected_receipt_sha256}.json"
    raw = _canonical({"schema_version": "stage_center.automatic_execution_review_rejection.v1",
                      "trade_date": trade_date, "stage_id": stage_id,
                      "expected_receipt_sha256": expected_receipt_sha256,
                      "reviewer_identity_or_role": _ATT_IDENTITY,
                      "reason": reason[:240]})
    try:
        SafeRoot(receipt_root).write_bytes(relative, raw, require_absent=True)
    except (OSError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--root", required=True, help="configured owner receipt root")
    parser.add_argument("--raw-root", required=True)
    parser.add_argument("--selection-root", required=True)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--hk-d1-root", required=True)
    parser.add_argument("--preselection-source-root")
    parser.add_argument("--hk-second-filter-root")
    parser.add_argument("--shared-research-root")
    args = parser.parse_args(argv)
    receipt_root = Path(args.root).expanduser()
    try:
        result = verify_and_publish(
            trade_date=args.date, stage_id=args.stage, receipt_root=receipt_root,
            raw_root=Path(args.raw_root).expanduser(),
            selection_root=Path(args.selection_root).expanduser(),
            expected_receipt_sha256=args.expected_receipt_sha256,
            hk_d1_root=Path(args.hk_d1_root),
            preselection_source_root=Path(args.preselection_source_root) if args.preselection_source_root else None,
            hk_second_filter_root=Path(args.hk_second_filter_root) if args.hk_second_filter_root else None,
            shared_research_root=Path(args.shared_research_root) if args.shared_research_root else None,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (VerificationError, OSError, ValueError, TypeError, KeyError, AttributeError,
            UnicodeError, RecursionError, OverflowError) as exc:
        reason = exc.reason if isinstance(exc, VerificationError) else "AUTOMATIC_REVIEW_VALIDATION_FAILED"
        _reject(receipt_root, args.date, args.stage, args.expected_receipt_sha256, reason)
        print(json.dumps({"status": "REJECTED", "reason": reason}, sort_keys=True,
                         separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
