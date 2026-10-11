"""Post-09:35 research-only fallback for a missing HK 09:20/09:25 result.

This module reads the immutable same-day 09:30-09:35 HK raw artifact, binds it
to the exact D-1 Top100, reruns the already configured 09:30 selector, and
publishes only into the ordinary 09:25 SelectionStore slot.  It never creates
or rewrites a raw artifact and never edits the deadline owner's receipt.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from stage_center import SAFETY_FLAGS
from stage_center.live_collectors import production_selection_builders
from stage_center.raw_store import RawStore, RawStoreError
from stage_center.runner import (
    RunnerError,
    _attach_hk_authority,
    _build_hk_stage_binding,
    _latest_entry,
    _normal_code,
    _read_verified_raw_source,
    _selection_source,
)
from stage_center.selection import SelectionError, SelectionStore, _selection_envelope


SOURCE_STAGE = "STAGE_0930_0935"
TARGET_STAGE = "STAGE_0925"
SOURCE_WINDOW = "09:30-09:35"
SOURCE_CUTOFF = "09:35:05"
SUBSTITUTE_KIND = "HK_0930_0935_FOR_HK_0925"
SUBSTITUTE_SOURCE_MODE = "HK_CONNECT_0930_0935_SUBSTITUTE_STAGE_0925"
SUBSTITUTE_LABEL = "09:30-09:35开盘数据替代补算"
SUBSTITUTE_ROW_LABEL = "09:30-09:35开盘数据替代补算；实际数据截止09:35"
SUBSTITUTE_LANE = "09:30-09:35_OPENING_DATA_SUBSTITUTE_FOR_0920"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _result(status: str, trade_date: str, *, layer: str | None = None, reason: str | None = None, **extra: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "trade_date": trade_date,
        "stage_id": TARGET_STAGE,
        "market": "HK_CONNECT",
        "write_performed": False,
        "RESEARCH_ONLY": True,
        **SAFETY_FLAGS,
    }
    if layer:
        result["first_failed_layer"] = layer
    if reason:
        result["cannot_confirm"] = [reason]
    result.update(extra)
    return result


def _receipt_expired(receipt_root: Path, trade_date: str) -> tuple[bool, str]:
    path = receipt_root / trade_date / TARGET_STAGE / "receipt.json"
    marker = Path(f"{path}.deadline-pending")
    if marker.exists() or marker.is_symlink():
        return True, "DEADLINE_PENDING"
    if not path.exists() and not path.is_symlink():
        return True, "MISSING"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False, "UNREADABLE"
    if not isinstance(value, dict) or value.get("trade_date") != trade_date or value.get("stage_id") != TARGET_STAGE:
        return False, "IDENTITY_MISMATCH"
    if value.get("status") == "SKIPPED_NON_TRADING_DAY":
        return False, "NON_TRADING_DAY"
    if (value.get("status") in {"CANNOT_CONFIRM", "PARTIAL_COMMIT_RETRY_REQUIRED", "SKIPPED_RETRY_EXHAUSTED"}
            or value.get("retry_exhausted") is True
            or value.get("deadline_status") in {"EXCEEDED", "CANNOT_CONFIRM"}
            or value.get("deadline_receipt_pending") is True):
        return True, "EXPIRED"
    return False, "NOT_EXPIRED"


def _is_healthy_auction_selection(envelope: Mapping[str, Any], trade_date: str) -> bool:
    """Preserve a verified, correctly identified completed 09:25 outcome."""
    if (envelope.get("trade_date") != trade_date
            or envelope.get("stage_id") != TARGET_STAGE
            or envelope.get("market") != "HK_CONNECT"):
        return False
    status = envelope.get("selection_status")
    source_status = envelope.get("source_status")
    rows = envelope.get("rows")
    if status == "READY_EMPTY":
        # READY_EMPTY is the completed auction's legitimate zero-candidate
        # outcome. Keep it distinct from a zero-row CANNOT_CONFIRM slot.
        return (
            source_status == "READY"
            and isinstance(rows, list)
            and not rows
            and envelope.get("selected_rows") == 0
            and not envelope.get("missing_symbols")
            and not envelope.get("cannot_confirm")
        )
    if status not in {"READY", "PARTIAL_WITH_ROWS"} or source_status not in {"READY", "PARTIAL_WITH_ROWS"}:
        return False
    if not isinstance(rows, list) or not rows or envelope.get("selected_rows") != len(rows):
        return False
    codes: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return False
        code = _normal_code("HK_CONNECT", row.get("code"))
        if not code:
            return False
        codes.append(code)
    return len(codes) == len(set(codes))


def _prior_selection_provenance(envelope: Mapping[str, Any]) -> list[str]:
    """Carry a failed/empty 09:25 slot's identity and diagnostic evidence."""
    evidence: list[str] = []
    for key in ("run_id", "selection_status", "raw_artifact_sha256", "selected_rows"):
        value = envelope.get(key)
        if value is not None:
            evidence.append(f"prior_0925_selection_{key}={value}")
    for reason in envelope.get("cannot_confirm") or ():
        evidence.append(f"prior_0925_selection_cannot_confirm={reason}")
    for item in envelope.get("source_evidence") or ():
        evidence.append(f"prior_0925_selection_source_evidence={item}")
    return list(dict.fromkeys(evidence))


def _source_cutoff_flag(verified: Mapping[str, Any], rows: tuple[Mapping[str, Any], ...]) -> bool:
    for item in verified.get("source_evidence") or ():
        if isinstance(item, str) and item.startswith("active_snapshot_temporal_cutoff_safe="):
            return item.rsplit("=", 1)[-1].lower() == "true"
    return bool(rows) and all(row.get("temporal_cutoff_safe") is True for row in rows)


def _validate_minute_rows(trade_date: str, verified: Mapping[str, Any], source: Any, membership: set[str]) -> tuple[bool, str | None, str | None]:
    if verified.get("trade_date") != trade_date or verified.get("stage_id") != SOURCE_STAGE or verified.get("market") != "HK_CONNECT":
        return False, "HK_0930_RAW_IDENTITY_MISMATCH", None
    if verified.get("window") != SOURCE_WINDOW or verified.get("cutoff_at") != SOURCE_CUTOFF:
        return False, "HK_0930_RAW_WINDOW_OR_CUTOFF_MISMATCH", None
    if verified.get("status") not in {"READY", "PARTIAL_WITH_ROWS"} or not source.rows:
        return False, "HK_0930_MINUTE_RAW_HAS_NO_USABLE_ROWS", None
    if source.requested_rows != 100 or len(membership) != 100:
        return False, "HK_D1_TOP100_COUNT_MISMATCH", None
    seen: set[str] = set()
    times: list[datetime] = []
    lower = datetime.strptime(f"{trade_date} 09:30:00", "%Y%m%d %H:%M:%S")
    upper = datetime.strptime(f"{trade_date} {SOURCE_CUTOFF}", "%Y%m%d %H:%M:%S")
    for row in source.rows:
        code = _normal_code("HK_CONNECT", row.get("code"))
        if not code or code in seen or code not in membership:
            return False, "HK_0930_RAW_CODE_OUTSIDE_OR_DUPLICATE_D1_POOL", None
        seen.add(code)
        try:
            bar_time = datetime.strptime(str(row.get("update_time") or ""), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False, "HK_0930_RAW_BAR_TIME_UNREADABLE", None
        if not lower <= bar_time <= upper:
            return False, "HK_0930_RAW_BAR_OUTSIDE_SOURCE_CUTOFF", None
        times.append(bar_time)
    if not times:
        return False, "HK_0930_MINUTE_RAW_HAS_NO_USABLE_ROWS", None
    return True, None, max(times).strftime("%Y-%m-%d %H:%M:%S")


def maybe_publish_0925_substitute(
    config: Mapping[str, Any],
    trade_date: str,
    evaluated_at: datetime,
    stage_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Run once after the scheduled 09:30-09:35 stage dispatch.

    Exact ordinary 09:25 raw/selection results have priority. Missing or
    expired target receipts are read-only inputs; the deadline owner is not
    modified. Failure to verify the source remains a specific wait/fail result.
    """
    try:
        if (stage_result.get("stage_id") != SOURCE_STAGE
                or stage_result.get("trade_date") != trade_date
                or evaluated_at.tzinfo is None):
            return _result("SKIPPED", trade_date, layer="AUTOMATIC_0930_ENTRY_IDENTITY")
        local = evaluated_at.astimezone(ZoneInfo("Asia/Shanghai"))
        cutoff = datetime.strptime(f"{trade_date} {SOURCE_CUTOFF}", "%Y%m%d %H:%M:%S").replace(tzinfo=local.tzinfo)
        if local.strftime("%Y%m%d") != trade_date or local < cutoff:
            return _result("SKIPPED", trade_date, layer="AUTOMATIC_0930_ENTRY_BEFORE_SOURCE_CUTOFF")

        raw_root = Path(str(config["raw_root"])).expanduser()
        selection_root = Path(str(config["selection_root"])).expanduser()
        receipt_root = Path(str(config["receipt_root"])).expanduser()
        raw_store = RawStore(raw_root)
        raw_latest = _latest_entry(raw_root, "latest.json", f"{trade_date}/{TARGET_STAGE}/HK_CONNECT")
        if raw_latest is not None:
            try:
                raw_store.verify_run(trade_date, TARGET_STAGE, "HK_CONNECT", str(raw_latest.get("run_id") or ""))
            except (RawStoreError, OSError, ValueError, TypeError):
                return _result("CANNOT_CONFIRM", trade_date, layer="EXISTING_0925_AUCTION_RAW_INVALID", reason="Existing 09:25 HK raw slot is present but cannot be verified; automatic substitute did not overwrite it.")
            return _result("SKIPPED_AUCTION_PRESENT", trade_date, layer="EXACT_0925_AUCTION_RAW_PRESENT", source_raw_run_id=raw_latest.get("run_id"))

        selection_store = SelectionStore(selection_root)
        key = selection_store._key(trade_date, TARGET_STAGE, "HK_CONNECT")
        ordinary = selection_store._latest().get("entries", {}).get(key)
        ordinary_envelope = None
        ordinary_is_substitute = False
        prior_selection_evidence: list[str] = []
        if ordinary is not None:
            try:
                ordinary_envelope = selection_store.read_verified(trade_date, TARGET_STAGE, "HK_CONNECT")
            except (SelectionError, OSError, ValueError, TypeError):
                return _result("CANNOT_CONFIRM", trade_date, layer="EXISTING_0925_SELECTION_INVALID", reason="Existing 09:25 HK selection slot is present but cannot be verified; automatic substitute did not overwrite it.")
            evidence = set(ordinary_envelope.get("source_evidence") or ())
            if f"substitute_kind={SUBSTITUTE_KIND}" in evidence:
                ordinary_is_substitute = True
            elif _is_healthy_auction_selection(ordinary_envelope, trade_date):
                return _result("SKIPPED_AUCTION_PRESENT", trade_date, layer="EXACT_0925_SELECTION_PRESENT", source_selection_run_id=ordinary_envelope.get("run_id"))
            else:
                prior_selection_evidence = _prior_selection_provenance(ordinary_envelope)

        expired, receipt_state = _receipt_expired(receipt_root, trade_date)
        if not expired:
            if receipt_state == "NON_TRADING_DAY":
                return _result("SKIPPED_NON_TRADING_DAY", trade_date, layer="HK_0925_CALENDAR_CLOSED")
            return _result("CANNOT_CONFIRM", trade_date, layer="HK_0925_NOT_MISSING_OR_EXPIRED", reason=f"The 09:25 owner receipt is {receipt_state}; no substitute was written.")

        d1_root = Path(str(config["hk_d1_root"])).expanduser()
        binding = _build_hk_stage_binding(d1_root, trade_date, preselection_source_root=config.get("preselection_source_root"))
        codes = set(binding.codes)
        if (binding.status != "READY" or binding.market != "HK_CONNECT" or binding.trade_date != trade_date
                or binding.role != "HK_CONNECT_D1_TOP100" or len(binding.codes) != 100 or len(codes) != 100):
            return _result("CANNOT_CONFIRM", trade_date, layer="EXACT_HK_D1_TOP100_BINDING", reason="Exact same-date HK Connect D-1 Top100 binding is unavailable or not 100 unique rows.")
        if not _SHA_RE.fullmatch(str(binding.sha256 or "")):
            return _result("CANNOT_CONFIRM", trade_date, layer="EXACT_HK_D1_TOP100_BINDING", reason="Exact HK D-1 pool SHA is invalid.")

        minute_latest = _latest_entry(raw_root, "latest.json", f"{trade_date}/{SOURCE_STAGE}/HK_CONNECT")
        if minute_latest is None:
            return _result("WAITING_MINUTE_DATA", trade_date, layer="HK_0930_0935_MINUTE_RAW_MISSING", reason="The existing same-date 09:30-09:35 HK minute raw artifact is not available yet.", deadline_receipt_state=receipt_state)
        try:
            verified = raw_store.verify_run(trade_date, SOURCE_STAGE, "HK_CONNECT", str(minute_latest.get("run_id") or ""))
            source = _read_verified_raw_source(raw_root, verified)
        except (RawStoreError, RunnerError, OSError, ValueError, TypeError):
            return _result("WAITING_MINUTE_DATA", trade_date, layer="HK_0930_0935_MINUTE_RAW_UNVERIFIED", reason="The existing same-date 09:30-09:35 HK minute raw artifact is not yet verifiable.", deadline_receipt_state=receipt_state)
        raw_evidence = set(verified.get("source_evidence") or ())
        if (f"candidate_current_sha256={binding.sha256}" not in raw_evidence
                and f"hk_d1_json_sha256={binding.sha256}" not in raw_evidence
                and f"hk_d1_sha256={binding.sha256}" not in raw_evidence):
            return _result("CANNOT_CONFIRM", trade_date, layer="HK_0930_RAW_D1_PROVENANCE_MISMATCH", reason="The 09:30 raw artifact does not bind to the exact same-date D-1 Top100 SHA.")
        source = _attach_hk_authority(
            source,
            d1_root=d1_root,
            second_root=None,
            preselection_source_root=config.get("preselection_source_root"),
            trade_date=trade_date,
            stage_id=SOURCE_STAGE,
            hk_binding=binding,
        )
        source = _selection_source(source, market="HK_CONNECT", membership=codes)
        valid, failure, last_bar = _validate_minute_rows(trade_date, verified, source, codes)
        if not valid:
            return _result("CANNOT_CONFIRM", trade_date, layer=failure, reason=failure, source_raw_run_id=verified.get("run_id"))

        if ordinary_envelope is not None:
            existing_evidence = set(ordinary_envelope.get("source_evidence") or ())
            required_identity = {
                f"source_raw_run_id={verified['run_id']}",
                f"source_raw_artifact_sha256={verified['artifact_sha256']}",
                f"d1_pool_sha256={binding.sha256}",
            }
            if ordinary_is_substitute:
                if required_identity.issubset(existing_evidence):
                    return _result("NOOP_ALREADY_VERIFIED", trade_date, source_raw_run_id=verified["run_id"], source_raw_artifact_sha256=verified["artifact_sha256"], d1_pool_sha256=binding.sha256, selected_rows=ordinary_envelope.get("selected_rows"))
                return _result("CANNOT_CONFIRM", trade_date, layer="EXISTING_0925_SUBSTITUTE_IDENTITY_CONFLICT", reason="The ordinary 09:25 slot already contains a substitute with a different source identity.")

        builders = production_selection_builders(SOURCE_STAGE)
        builder = builders.get("HK_CONNECT")
        if builder is None:
            return _result("CANNOT_CONFIRM", trade_date, layer="HK_0930_ORIGINAL_SELECTOR_UNAVAILABLE", reason="The original 09:30 HK selector is unavailable.")
        base = builder(source, SimpleNamespace(trade_date=trade_date, stage_id=SOURCE_STAGE), dict(verified))
        selected_rows = base.get("rows") if isinstance(base, Mapping) else None
        if base.get("selection_status") not in {"READY", "PARTIAL_WITH_ROWS"} or not isinstance(selected_rows, list) or not selected_rows:
            return _result("CANNOT_CONFIRM", trade_date, layer="HK_0930_ORIGINAL_SELECTOR_EMPTY", reason="The original 09:30 HK selector did not produce usable rows.", source_raw_run_id=verified.get("run_id"))

        source_safe = _source_cutoff_flag(verified, tuple(source.rows))
        evidence = list(base.get("source_evidence") or ())
        evidence.extend((
            "substitute_kind=" + SUBSTITUTE_KIND,
            "substitute_label=" + SUBSTITUTE_LABEL,
            "source_stage_id=" + SOURCE_STAGE,
            "source_window=" + SOURCE_WINDOW,
            "source_trade_date=" + trade_date,
            "source_last_bar_time=" + str(last_bar),
            "source_raw_run_id=" + str(verified["run_id"]),
            "source_raw_artifact_sha256=" + str(verified["artifact_sha256"]),
            "source_manifest_sha256=" + str(verified["manifest_sha256"]),
            "source_receipt_sha256=" + str(verified["receipt_sha256"]),
            "source_manifest_temporal_cutoff_safe=" + str(source_safe).lower(),
            "target_stage_temporal_cutoff_safe=false",
            "d1_membership_status=STRICT_0_2_READY",
            "d1_pool_role=HK_CONNECT_D1_TOP100",
            "d1_pool_count=100",
            "d1_pool_sha256=" + str(binding.sha256),
            "selection_mode=BACKFILL",
            "recovery_mode=HISTORICAL_BACKFILL",
            "automatic_trigger=STAGE_0930_0935_AFTER_SOURCE_CUTOFF",
            "deadline_receipt_state=" + receipt_state,
        ))
        evidence.extend(prior_selection_evidence)
        evidence = list(dict.fromkeys(evidence))
        remapped_rows: list[dict[str, Any]] = []
        for selected in selected_rows:
            row = dict(selected)
            row.update({
                "trade_date": trade_date,
                "stage_id": TARGET_STAGE,
                "source_mode": SUBSTITUTE_SOURCE_MODE,
                "lane_evidence": list(dict.fromkeys([*(row.get("lane_evidence") or []), SUBSTITUTE_LANE])),
                "substitute_label": SUBSTITUTE_ROW_LABEL,
                "substitute_source_stage_id": SOURCE_STAGE,
                "substitute_source_window": SOURCE_WINDOW,
                "source_last_bar_time": str(row.get("source_last_bar_time") or last_bar),
                "source_temporal_cutoff_safe": source_safe,
                "target_stage_temporal_cutoff_safe": False,
                "source_raw_run_id": str(verified["run_id"]),
                "source_raw_artifact_sha256": str(verified["artifact_sha256"]),
                "source_manifest_sha256": str(verified["manifest_sha256"]),
                "source_receipt_sha256": str(verified["receipt_sha256"]),
                "d1_pool_sha256": str(binding.sha256),
                "d1_pool_role": "HK_CONNECT_D1_TOP100",
                "formal_eligible": False,
                "action_level": "NO_BUY",
                "trade_status": "WATCH_ONLY",
                "status": "WATCH_ONLY",
                "next_validation_time": SOURCE_CUTOFF,
            })
            remapped_rows.append(row)
        cannot = list(dict.fromkeys([*(base.get("cannot_confirm") or ()), "TARGET_STAGE_0925_CUTOFF_NOT_MET_BY_0930_0935_SUBSTITUTE"]))
        envelope = _selection_envelope(
            trade_date=trade_date,
            stage_id=TARGET_STAGE,
            market="HK_CONNECT",
            raw_artifact_sha256=str(verified["artifact_sha256"]),
            source_status="PARTIAL_WITH_ROWS",
            input_rows=len(source.rows),
            rows=remapped_rows,
            requested_rows=source.requested_rows,
            missing_symbols=source.missing_symbols,
            cannot_confirm=cannot,
            source_evidence=evidence,
            algorithm_sha256=str(base["algorithm_sha256"]),
        )
        published = selection_store.publish(
            envelope,
            market="HK_CONNECT",
            replace_failed_run_id=(str(ordinary_envelope.get("run_id") or "") if ordinary_envelope is not None else None),
        )
        return _result(
            "PARTIAL_WITH_ROWS", trade_date,
            source_raw_run_id=verified["run_id"],
            source_raw_artifact_sha256=verified["artifact_sha256"],
            source_manifest_sha256=verified["manifest_sha256"],
            source_receipt_sha256=verified["receipt_sha256"],
            source_stage_id=SOURCE_STAGE,
            source_window=SOURCE_WINDOW,
            source_last_bar_time=last_bar,
            d1_pool_sha256=binding.sha256,
            d1_pool_role=binding.role,
            d1_pool_count=len(codes),
            selected_rows=published.get("selected_rows"),
            missing_symbols=published.get("missing_symbols"),
            selection_run_id=published.get("run_id"),
            selection_status=published.get("selection_status"),
            write_performed=True,
            automatic_substitute=True,
        )
    except (AttributeError, KeyError, OSError, RawStoreError, RunnerError, SelectionError, TypeError, ValueError) as error:
        return _result("CANNOT_CONFIRM", trade_date, layer="HK_0925_AUTOMATIC_SUBSTITUTE_ERROR", reason=f"{type(error).__name__}: {error}")
