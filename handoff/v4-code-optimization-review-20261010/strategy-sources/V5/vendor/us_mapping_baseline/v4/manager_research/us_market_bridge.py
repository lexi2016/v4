"""Read-only bridge from the existing US peripheral owner into Manager.

No fetching, scheduling or mutation lives here.  The bridge resolves the
latest completed official US equity session before the Manager cutoff, asks
an injected owner reader for that exact stored artifact, validates its close
snapshot, and projects auditable raw movers.  HK mappings are deliberately
left to ``research_attention`` where issuer evidence is available.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from contracts.us_equity_calendar import latest_completed_session
from .workspace_projection import FLAGS, HK, timestamp

SCHEMA = "v4.manager_research.us_market_bridge.v1"
_SNAPSHOT_SCHEMA = "v3_5.us_market_snapshot.v1"
_MAPPING_VERSION = "v3_5.global_industry_proxy_map.v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_HARD_MAPPING_GAPS = frozenset({
    "US_MARKET_LINEAGE_UNVERIFIED",
    "US_MARKET_SNAPSHOT_VERSION_INVALID",
    "US_MARKET_SESSION_IDENTITY_MISMATCH",
    "US_MARKET_PROVIDER_SESSION_DATE_UNIQUE_REQUIRED",
    "US_MARKET_SNAPSHOT_NOT_READY",
    "US_MARKET_CAPTURE_AFTER_MANAGER_CUTOFF_OR_UNKNOWN",
    "US_MARKET_SAFETY_BOUNDARY_INVALID",
})


class ExactUsMarketReader(Protocol):
    def read_exact_session(self, session_date: str) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]: ...


class ResearchPeripheralUsMarketReader:
    """Adapter over the existing ``ResearchPeripheralStore`` only.

    The import is local because the audit bundle intentionally omits the host
    store module.  The full V4 repository already owns this producer/store.
    """

    def __init__(self, data_root: Path | str) -> None:
        from infrastructure.research_peripheral_store import ResearchPeripheralStore
        self.root = Path(data_root)
        self.store = ResearchPeripheralStore(self.root)

    @staticmethod
    def _sha_bytes(value: bytes) -> str:
        return sha256(value).hexdigest()

    def read_exact_session(self, session_date: str) -> tuple[Mapping[str, Any] | None, Mapping[str, Any]]:
        from infrastructure.owned_io import SafeRoot
        relative = f"research/peripherals/{session_date}/external_finance.json"
        receipt_relative = f"receipts/research/peripherals/{session_date}/external_finance.json"
        manifest_relative = "research/peripherals/manifest.json"
        payload: Mapping[str, Any] | None = None
        lineage: dict[str, Any] = {
            "owner": "ResearchPeripheralStore",
            "source": "external_finance",
            "session_date": session_date,
            "payload_path": relative,
            "receipt_path": receipt_relative,
            "manifest_path": manifest_relative,
            "status": "CANNOT_CONFIRM",
        }
        # Reuse the existing owner's import lock around its exact validated
        # read and the raw payload/receipt/manifest bytes. A concurrent owner
        # replace writes these three files sequentially under the same lock.
        with self.store._lock():
            payload = self.store.read_exact(session_date, "external_finance")
            if payload is None:
                lineage["status"] = "NOT_MATERIALIZED"
                return None, lineage
            io = SafeRoot(self.root)
            try:
                payload_raw = io.read_bytes(relative, max_bytes=64 * 1024 * 1024)
                receipt_raw = io.read_bytes(receipt_relative, max_bytes=4 * 1024 * 1024)
                manifest_raw = io.read_bytes(manifest_relative, max_bytes=16 * 1024 * 1024)
                payload_from_bytes = json.loads(payload_raw)
                receipt_from_bytes = json.loads(receipt_raw)
                manifest_from_bytes = json.loads(manifest_raw)
                payload_sha = self._sha_bytes(payload_raw)
                if (not isinstance(payload, Mapping)
                        or not isinstance(payload_from_bytes, Mapping)
                        or dict(payload_from_bytes) != dict(payload)
                        or not isinstance(receipt_from_bytes, Mapping)
                        or not isinstance(manifest_from_bytes, Mapping)
                        or manifest_from_bytes.get(relative) != payload_sha
                        or receipt_from_bytes != self.store._receipt(payload_from_bytes, payload_sha)):
                    raise ValueError("US_MARKET_OWNER_READ_BYTES_MISMATCH")
            except (FileNotFoundError, OSError, ValueError, TypeError):
                lineage.update(status="CANNOT_CONFIRM", reason="US_MARKET_LINEAGE_BYTES_INVALID")
                return payload, lineage
            lineage.update(
                status="VERIFIED",
                payload_sha256=payload_sha,
                receipt_sha256=self._sha_bytes(receipt_raw),
                manifest_sha256=self._sha_bytes(manifest_raw),
            )
        return payload, lineage


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _time_not_after(value: Any, cutoff: datetime) -> bool:
    parsed = timestamp(value)
    return parsed is not None and parsed <= cutoff


def _safe_lineage(lineage: Mapping[str, Any]) -> bool:
    return lineage.get("status") == "VERIFIED" and all(
        isinstance(lineage.get(key), str) and _SHA.fullmatch(str(lineage[key]))
        for key in ("payload_sha256", "receipt_sha256", "manifest_sha256")
    )


def _same_session_time_recheck(
    snapshot: Mapping[str, Any],
    *,
    session_date: str,
) -> tuple[Mapping[str, Any] | None, Mapping[str, Any] | None]:
    """Offline-replay the one known false positive from verified stored rows.

    The replay is diagnostic only: it consumes the exact normalized quote
    rows already read from the owner and never writes the original payload.
    It admits no other owner error, session/date defect, missing quote, or
    parser/arithmetic failure.
    """
    if (snapshot.get("status") != "PARTIAL"
            or snapshot.get("capture_phase") != "POST_CLOSE"
            or snapshot.get("capture_session_date") != session_date
            or snapshot.get("provider_session_dates") != [session_date]
            or snapshot.get("cannot_confirm") is None
            or set(snapshot.get("cannot_confirm") or [])
            != {"MARKET_SNAPSHOT_INCOMPLETE", "QUOTE_SESSION_TIME_MIXED"}):
        return None, None
    rows = snapshot.get("rows")
    quotes = snapshot.get("quotes")
    if not isinstance(rows, list) or len(rows) != 24 or not isinstance(quotes, list):
        return None, None
    if any(not isinstance(row, Mapping)
           or set(row.get("cannot_confirm") or []) - {"QUOTE_SESSION_TIME_MIXED"}
           for row in rows):
        return None, None
    from ops.us_market_digest import GLOBAL_INDUSTRY_PROXY_MAP, build_us_market_snapshot
    requested = sorted({symbol for item in GLOBAL_INDUSTRY_PROXY_MAP for symbol in item["proxy_symbols"]})
    quote_map: dict[str, dict[str, Any]] = {}
    for quote in quotes:
        if not isinstance(quote, Mapping):
            return None, None
        symbol = quote.get("symbol")
        if (not isinstance(symbol, str) or symbol in quote_map
                or quote.get("session_date") != session_date
                or not isinstance(quote.get("session_time"), str)
                or not quote.get("session_time")):
            return None, None
        quote_map[symbol] = {
            "last": quote.get("last"),
            "previous_close": quote.get("previous_close"),
            "change_pct": quote.get("change_pct"),
            "session_date": quote.get("session_date"),
            "session_time": quote.get("session_time"),
        }
    if sorted(quote_map) != requested or snapshot.get("requested_symbol_count") != len(requested) or snapshot.get("available_symbol_count") != len(requested):
        return None, None
    try:
        cutoff_capture = snapshot.get("captured_at")
        replay = build_us_market_snapshot(
            session_date,
            capture_phase="POST_CLOSE",
            captured_at=cutoff_capture,
            fetch_quotes=lambda *_args, **_kwargs: quote_map,
        )
    except (OSError, ValueError, TypeError, KeyError):
        return None, None
    if (replay.get("status") != "READY"
            or replay.get("provider_session_dates") != [session_date]
            or replay.get("requested_symbol_count") != len(requested)
            or replay.get("available_symbol_count") != len(requested)
            or len(replay.get("rows") or []) != 24
            or any(row.get("status") != "READY" for row in replay.get("rows") or [])):
        return None, None
    canonical_input = json.dumps(
        {"session_date": session_date, "quotes": [quote_map[symbol] | {"symbol": symbol} for symbol in requested]},
        sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    replay_meta = {
        "status": "RECHECKED_READY",
        "basis": "EXISTING_US_SNAPSHOT_BUILDER_FROM_VERIFIED_STORED_NORMALIZED_QUOTES",
        "rechecked_at": datetime.now(timezone.utc).isoformat(),
        "session_date": session_date,
        "stored_snapshot_status": snapshot.get("status"),
        "stored_capture_at": snapshot.get("captured_at"),
        "stored_source_response_sha256": snapshot.get("source_response_sha256"),
        "replay_input_sha256": sha256(canonical_input).hexdigest(),
        "replay_status": replay.get("status"),
        "replay_cannot_confirm": list(replay.get("cannot_confirm") or []),
        "storage_mutated": False,
    }
    return replay, replay_meta


def _empty(target: str, cutoff: str | None, *, status: str, gaps: list[str], expected_session: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "target_trade_date": target,
        "research_cutoff": cutoff,
        "status": status,
        "expected_us_session": expected_session,
        "coverage_scope": "FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET",
        "selection_semantics": "POSITIVE_CHANGE_GT_ZERO_NOT_LARGE_GAIN_SCREEN",
        "selection_threshold_pct": 0.0,
        "raw_industry_up": [],
        "raw_individual_up": [],
        "coverage": {"industry_proxy_count": 24, "requested_symbol_count": 33, "available_symbol_count": 0},
        "source_identity": None,
        "mapping_eligible": False,
        "mapping_ineligible_reasons": sorted(set(gaps)),
        "mapping_diagnostics": {"accepted_hk_mapping_count": None, "status": "NOT_COMPUTED_BY_BRIDGE", "relation_layer": "MANAGER_TWO_SOURCE_RELATION_REQUIRED"},
        "gaps": sorted(set(gaps)),
        **FLAGS,
    }


def project_us_market(reader: ExactUsMarketReader | None, target_trade_date: str, context: Mapping[str, Any]) -> dict[str, Any]:
    cutoff = timestamp(context.get("research_cutoff"))
    if cutoff is None:
        return _empty(target_trade_date, None, status="CANNOT_CONFIRM", gaps=["US_MANAGER_CUTOFF_UNVERIFIED"])
    try:
        session = latest_completed_session(cutoff)
    except ValueError as exc:
        reason = str(exc)
        if reason not in {
            "US_EQUITY_CALENDAR_YEAR_OUT_OF_COVERAGE",
            "US_EQUITY_LOOKBACK_RANGE_INVALID",
        }:
            reason = "US_OFFICIAL_SESSION_RESOLUTION_FAILED"
        return _empty(target_trade_date, cutoff.isoformat(), status="CANNOT_CONFIRM", gaps=[reason])
    except (OSError, TypeError):
        return _empty(target_trade_date, cutoff.isoformat(), status="CANNOT_CONFIRM", gaps=["US_OFFICIAL_SESSION_RESOLUTION_FAILED"])
    if reader is None:
        return _empty(target_trade_date, cutoff.isoformat(), status="INPUT_MISSING", gaps=["US_MARKET_OWNER_READER_NOT_BOUND"], expected_session=session.session_date)
    try:
        payload, lineage = reader.read_exact_session(session.session_date)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return _empty(target_trade_date, cutoff.isoformat(), status="SOURCE_FAILED",
                      gaps=[f"US_MARKET_OWNER_READ_FAILED:{type(exc).__name__}"], expected_session=session.session_date)
    if not isinstance(payload, Mapping):
        return _empty(target_trade_date, cutoff.isoformat(), status="INPUT_MISSING",
                      gaps=["US_MARKET_EXACT_SESSION_NOT_MATERIALIZED"], expected_session=session.session_date)
    snapshot = payload.get("market_snapshot")
    if not isinstance(snapshot, Mapping):
        return _empty(target_trade_date, cutoff.isoformat(), status="CANNOT_CONFIRM",
                      gaps=["US_MARKET_SNAPSHOT_NOT_MATERIALIZED"], expected_session=session.session_date)
    gaps: list[str] = []
    if not _safe_lineage(lineage):
        gaps.append("US_MARKET_LINEAGE_UNVERIFIED")
    if snapshot.get("schema_version") != _SNAPSHOT_SCHEMA or snapshot.get("mapping_version") != _MAPPING_VERSION:
        gaps.append("US_MARKET_SNAPSHOT_VERSION_INVALID")
    if snapshot.get("capture_phase") != "POST_CLOSE" or snapshot.get("capture_session_date") != session.session_date:
        gaps.append("US_MARKET_SESSION_IDENTITY_MISMATCH")
    provider_dates = [str(item) for item in snapshot.get("provider_session_dates") or [] if str(item)]
    if provider_dates != [session.session_date]:
        gaps.append("US_MARKET_PROVIDER_SESSION_DATE_UNIQUE_REQUIRED")
    if snapshot.get("status") not in {"READY", "PARTIAL"}:
        gaps.append("US_MARKET_SNAPSHOT_NOT_READY")
    if not _time_not_after(snapshot.get("captured_at"), cutoff):
        gaps.append("US_MARKET_CAPTURE_AFTER_MANAGER_CUTOFF_OR_UNKNOWN")
    for key, expected in FLAGS.items():
        if snapshot.get(key) is not expected:
            gaps.append("US_MARKET_SAFETY_BOUNDARY_INVALID")
            break
    stored_snapshot = snapshot
    replay_evidence = None
    if not gaps and snapshot.get("status") == "PARTIAL":
        replay_snapshot, replay_evidence = _same_session_time_recheck(snapshot, session_date=session.session_date)
        if replay_snapshot is not None:
            snapshot = replay_snapshot
    rows = snapshot.get("rows")
    quotes = snapshot.get("quotes")
    if not isinstance(rows, list):
        gaps.append("US_MARKET_INDUSTRY_PROXY_ROWS_INVALID")
        rows = []
    elif len(rows) != 24:
        # Preserve valid rows from a partial owner snapshot. Each row remains
        # bound to the verified snapshot identity below.
        gaps.append("US_MARKET_INDUSTRY_PROXY_ROWS_INVALID")
    if not isinstance(quotes, list):
        gaps.append("US_MARKET_QUOTES_INVALID")
        quotes = []
    raw_industry_up: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pct = _finite(row.get("pct_change", row.get("change_pct")))
        if pct is None or pct <= 0:
            continue
        raw_industry_up.append({
            "label": str(row.get("label") or ""),
            "group": str(row.get("group") or ""),
            "mapping_type": str(row.get("mapping_type") or ""),
            "instrument_classification": "INDUSTRY_PROXY_NOT_FULL_MARKET_SECURITY_SCREEN",
            "pct_change": pct,
            "status": str(row.get("status") or "CANNOT_CONFIRM"),
            "proxy_symbols": list(row.get("proxy_symbols") or []),
            "available_symbols": list(row.get("available_symbols") or []),
            "coverage": deepcopy(row.get("coverage") or {}),
            "cannot_confirm": list(row.get("cannot_confirm") or []),
        })
    raw_individual_up: list[dict[str, Any]] = []
    for quote in quotes:
        if not isinstance(quote, Mapping) or str(quote.get("session_date") or "") != session.session_date:
            continue
        pct = _finite(quote.get("change_pct"))
        if pct is None or pct <= 0:
            continue
        raw_individual_up.append({
            "symbol": str(quote.get("symbol") or ""),
            "instrument_classification": "CONFIGURED_US_SYMBOL_NOT_FULL_MARKET_SCREEN",
            "change_pct": pct,
            "session_date": session.session_date,
            "session_time": str(quote.get("session_time") or ""),
            "provider": str(quote.get("provider") or snapshot.get("provider") or ""),
        })
    raw_industry_up.sort(key=lambda row: (-float(row["pct_change"]), row["label"]))
    raw_individual_up.sort(key=lambda row: (-float(row["change_pct"]), row["symbol"]))
    mapping_ineligible_reasons = sorted(set(gaps).intersection(_HARD_MAPPING_GAPS))
    mapping_eligible = not mapping_ineligible_reasons
    if not mapping_eligible:
        status = "CANNOT_CONFIRM"
    elif not gaps and snapshot.get("status") == "READY":
        status = "READY"
    elif snapshot.get("status") == "PARTIAL" or raw_industry_up or raw_individual_up:
        status = "PARTIAL"
    else:
        status = "CANNOT_CONFIRM"
    return {
        "schema_version": SCHEMA,
        "target_trade_date": target_trade_date,
        "research_cutoff": cutoff.isoformat(),
        "status": status,
        "expected_us_session": session.session_date,
        "session_state": session.state,
        "session_close_at": session.close_at.isoformat() if session.close_at else None,
        "session_calendar_source": session.source_url,
        "coverage_scope": "FIXED_24_INDUSTRY_PROXY_ROWS_AND_33_CONFIGURED_US_SYMBOLS_NOT_FULL_US_MARKET",
        "selection_semantics": "POSITIVE_CHANGE_GT_ZERO_NOT_LARGE_GAIN_SCREEN",
        "selection_threshold_pct": 0.0,
        "raw_industry_up": raw_industry_up,
        "raw_individual_up": raw_individual_up,
        "coverage": {
            "industry_proxy_count": 24,
            "requested_symbol_count": int(snapshot.get("requested_symbol_count") or 0),
            "available_symbol_count": int(snapshot.get("available_symbol_count") or 0),
        },
        "mapping_eligible": mapping_eligible,
        "mapping_ineligible_reasons": mapping_ineligible_reasons,
        "mapping_diagnostics": {"accepted_hk_mapping_count": None, "status": "NOT_COMPUTED_BY_BRIDGE", "relation_layer": "MANAGER_TWO_SOURCE_RELATION_REQUIRED"},
        "source_identity": deepcopy(dict(lineage)),
        "source_response_sha256": stored_snapshot.get("source_response_sha256"),
        "captured_at": stored_snapshot.get("captured_at"),
        "stored_snapshot_status": stored_snapshot.get("status"),
        "stored_payload_status": payload.get("status"),
        "stored_snapshot_cannot_confirm": list(stored_snapshot.get("cannot_confirm") or []),
        "recheck_evidence": replay_evidence,
        "gaps": sorted(set(gaps)),
        **FLAGS,
    }


__all__ = ["ExactUsMarketReader", "ResearchPeripheralUsMarketReader", "SCHEMA", "project_us_market"]
