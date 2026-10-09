"""Date-scoped, research-only US-to-HK relation projection for the Manager owner.

The reviewed 2026-09-30 report is an immutable retrospective research artifact.
Daily runs read only the injected exact-session US owner and a small reviewed
relation registry; they never fetch prices, assert PIT eligibility, or change
the existing Stage/selection/BUY paths.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from .contracts import sha256_json, strict_trade_date
from .workspace_projection import FLAGS, HK, digest, timestamp
from .workspace_plan import plan_context

SCHEMA = "v4.manager_research.us_mapping_research.v1"
DAILY_SCHEMA = "v4.manager_research.us_mapping_daily_run.v1"
REVIEWED_PATH = Path(__file__).with_name("us_mapping_reviewed_20260930.json")
RELATION_REGISTRY_PATH = Path(__file__).with_name("us_mapping_relation_registry.json")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_TARGET_SEED = "20260930"
_DAILY_RELATION_TYPES = {"DIRECT_NAMED_COMPONENT_SUPPLY", "PRODUCT_PEER", "OPTICAL_TRANSPORT_PEER"}


def _now_text(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _safe_tree(value: Mapping[str, Any]) -> None:
    for key, expected in FLAGS.items():
        if value.get(key) is not expected:
            raise ValueError("US_MAPPING_SAFETY_INVALID")


def _read_reviewed() -> dict[str, Any]:
    raw = REVIEWED_PATH.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("US_MAPPING_REVIEWED_ARTIFACT_INVALID")
    unsigned = {key: item for key, item in value.items() if key != "artifact_sha256"}
    if (value.get("schema_version") != "v4.manager_research.us_mapping_reviewed.v1"
            or value.get("target_trade_date") != _TARGET_SEED
            or value.get("artifact_sha256") != sha256_json(unsigned)
            or not isinstance(value.get("cards"), list)):
        raise ValueError("US_MAPPING_REVIEWED_ARTIFACT_INTEGRITY_FAILED")
    _safe_tree(value)
    return value


def _read_saved(store: Any, date: str) -> dict[str, Any] | None:
    path = store.root / "us_mapping_research" / date / "latest.json"
    pointer = store._read(path)
    if pointer is None:
        return None
    if (pointer.get("schema_version") != "v4.manager_research.us_mapping_daily_pointer.v1"
            or pointer.get("target_trade_date") != date
            or not isinstance(pointer.get("run_id"), str)
            or not _SHA.fullmatch(str(pointer.get("artifact_sha256") or ""))):
        raise ValueError("US_MAPPING_DAILY_POINTER_INVALID")
    artifact = store._read(path.parent / "runs" / f"{pointer['run_id']}.json")
    if artifact is None:
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_MISSING")
    unsigned = {key: item for key, item in artifact.items() if key != "artifact_sha256"}
    if (artifact.get("schema_version") != DAILY_SCHEMA
            or artifact.get("target_trade_date") != date
            or artifact.get("run_id") != pointer["run_id"]
            or artifact.get("artifact_sha256") != pointer["artifact_sha256"]
            or sha256_json(unsigned) != pointer["artifact_sha256"]):
        raise ValueError("US_MAPPING_DAILY_ARTIFACT_INTEGRITY_FAILED")
    _safe_tree(artifact)
    return artifact


def read_workspace_mapping(service: Any, target_trade_date: str) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    try:
        daily = _read_saved(service.store, date)
    except (OSError, ValueError, KeyError, TypeError):
        daily = None
        read_status = "FAILED"
    else:
        read_status = "NOT_RUN"
    if daily is None:
        daily = {
            "schema_version": DAILY_SCHEMA,
            "status": read_status,
            "target_trade_date": date,
            "run_id": None,
            "generated_at": None,
            "us_session_date": None,
            "research_cutoff": None,
            "coverage": {
                "reviewed_us_symbol_count": 4,
                "matched_us_symbol_count": None,
                "matched_hk_relation_count": None,
                "configured_us_universe_count": None,
                "available_us_universe_count": None,
                "full_market_coverage": False,
            },
            "matches": [],
            "gaps": ["DAILY_MAPPING_NOT_MATERIALIZED" if read_status == "NOT_RUN" else "DAILY_MAPPING_READBACK_INVALID"],
            "source_identity": None,
            "input_identity": None,
            **FLAGS,
        }
    if date == _TARGET_SEED:
        try:
            reviewed = _read_reviewed()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            reviewed = {
                "schema_version": "v4.manager_research.us_mapping_reviewed.v1",
                "target_trade_date": date,
                "status": "CANNOT_CONFIRM",
                "reviewed_at": None,
                "cards": [],
                "gaps": ["REVIEWED_US_HK_RELATION_ARTIFACT_INVALID"],
                **FLAGS,
            }
    else:
        reviewed = None
    return {
        "schema_version": SCHEMA,
        "target_trade_date": date,
        "daily_run": daily,
        "reviewed_research": reviewed,
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _relation_index() -> dict[str, list[dict[str, Any]]]:
    reviewed = _read_reviewed()
    out: dict[str, list[dict[str, Any]]] = {}
    for card in reviewed["cards"]:
        if not isinstance(card, Mapping):
            continue
        for symbol in card.get("daily_match_symbols", []):
            if isinstance(symbol, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
                out.setdefault(symbol, []).append(dict(card))
    return out


def _relation_available_at(reviewed: Mapping[str, Any]) -> tuple[datetime | None, str | None]:
    """Return only a release-pinned system availability time for reviewed rows.

    The report's ``reviewed_at`` is a retrospective calendar date. It cannot
    establish when the rows became available inside this application. Daily
    joins therefore require the separately pinned deployment registry.
    """
    try:
        raw = RELATION_REGISTRY_PATH.read_bytes()
        registry = json.loads(raw)
        if not isinstance(registry, Mapping):
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED"
        unsigned = {key: item for key, item in registry.items() if key != "artifact_sha256"}
        seed_sha = hashlib.sha256(REVIEWED_PATH.read_bytes()).hexdigest()
        availability = timestamp(registry.get("available_at"))
        if (not isinstance(registry, Mapping)
                or registry.get("schema_version") != "v4.manager_research.us_mapping_relation_registry.v1"
                or registry.get("artifact_sha256") != sha256_json(unsigned)
                or registry.get("source_seed_sha256") != seed_sha
                or registry.get("source_report_sha256") != (reviewed.get("report") or {}).get("sha256")
                or not availability
                or registry.get("availability_basis") != "V4_RELEASE_PUBLICATION"
                or not isinstance(registry.get("release_id"), str)
                or not registry.get("release_id")
                or not _SHA.fullmatch(str(registry.get("release_manifest_sha256") or ""))
                or not _SHA.fullmatch(str(registry.get("deployment_receipt_sha256") or ""))):
            return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED"
        return availability, None
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None, "US_HK_RELATION_AVAILABILITY_UNVERIFIED"


def build_daily_run(service: Any, target_trade_date: str, *, now: datetime) -> dict[str, Any]:
    date = strict_trade_date(target_trade_date)
    if now.tzinfo is None:
        raise ValueError("US_MAPPING_CLOCK_MUST_BE_AWARE")
    context = plan_context(date, now=now)
    from .us_market_bridge import project_us_market

    bridge = project_us_market(getattr(service, "_workspace_us_market_reader", None), date, context)
    reviewed = _read_reviewed()
    source_status = bridge.get("status")
    gaps = list(bridge.get("gaps") or [])
    matches: list[dict[str, Any]] = []
    complete_snapshot = source_status == "READY"
    relation_available_at, relation_registry_gap = _relation_available_at(reviewed)
    cutoff = timestamp(bridge.get("research_cutoff"))
    relation_available = bool(
        relation_available_at is not None and cutoff is not None and relation_available_at <= cutoff
    )
    if relation_registry_gap:
        gaps.append(relation_registry_gap)
    elif not relation_available:
        gaps.append("US_HK_RELATION_NOT_AVAILABLE_AT_RESEARCH_CUTOFF")
    if complete_snapshot and relation_available:
        relations = _relation_index()
        for row in bridge.get("raw_individual_up") or []:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper()
            for card in relations.get(symbol, []):
                matches.append({
                    "us_symbol": symbol,
                    "change_pct": row.get("change_pct"),
                    "session_date": row.get("session_date"),
                    "hk_symbol": card.get("hk_symbol"),
                    "hk_name": card.get("hk_name"),
                    "research_priority": card.get("research_priority"),
                    "relationship_type": card.get("relationship_type"),
                    "reason": card.get("reason"),
                    "maturity": card.get("maturity"),
                    "limitations": card.get("limitations"),
                    "official_sources": deepcopy(card.get("official_sources", [])),
                    "reviewed_relation_artifact_sha256": reviewed.get("artifact_sha256"),
                    "target_date_eligibility": "CANNOT_CONFIRM",
                    "source_row": deepcopy(dict(row)),
                })
    if source_status == "SOURCE_FAILED":
        status = "FAILED"
    elif source_status in {"INPUT_MISSING", "CANNOT_CONFIRM"}:
        status = "INPUT_MISSING" if source_status == "INPUT_MISSING" else "CANNOT_CONFIRM"
    elif source_status == "PARTIAL":
        status = "PARTIAL"
        gaps.append("US_MARKET_SOURCE_PARTIAL")
    elif complete_snapshot:
        status = "COMPLETED" if matches else "VALID_EMPTY" if relation_available else "PARTIAL"
    else:
        status = "CANNOT_CONFIRM"
        gaps.append("US_MARKET_SOURCE_STATUS_UNRECOGNIZED")

    coverage = bridge.get("coverage") if isinstance(bridge.get("coverage"), Mapping) else {}
    source_identity = bridge.get("source_identity") if isinstance(bridge.get("source_identity"), Mapping) else None
    relation_sha = reviewed.get("artifact_sha256") if relation_available else None
    identity = digest([date, bridge.get("expected_us_session"), bridge.get("research_cutoff"), source_identity,
                       matches, relation_sha])
    run_id = uuid4().hex
    value = {
        "schema_version": DAILY_SCHEMA,
        "status": status,
        "target_trade_date": date,
        "run_id": run_id,
        "generated_at": _now_text(now),
        "us_session_date": bridge.get("expected_us_session"),
        "research_cutoff": bridge.get("research_cutoff"),
        "coverage_scope": "FOUR_REVIEWED_US_TICKER_RELATIONS_WITHIN_FIXED_33_CONFIGURED_SYMBOL_SAMPLE_NOT_FULL_MARKET",
        "coverage": {
            "reviewed_us_symbol_count": 4,
            "matched_us_symbol_count": len({row["us_symbol"] for row in matches}) if complete_snapshot and relation_available else None,
            "matched_hk_relation_count": len(matches) if complete_snapshot and relation_available else None,
            "configured_us_universe_count": coverage.get("requested_symbol_count") if complete_snapshot else None,
            "available_us_universe_count": coverage.get("available_symbol_count") if complete_snapshot else None,
            "full_market_coverage": False,
        },
        "matches": matches,
        "source_status": source_status,
        "source_identity": deepcopy(dict(source_identity)) if source_identity else None,
        "source_gaps": gaps,
        "input_identity": identity,
        "relation_artifact_sha256": relation_sha,
        "target_date_eligibility": "CANNOT_CONFIRM",
        "producer_owner": "ManagerResearchJobService / ResearchPeripheralStore read adapter",
        "readback_required": True,
        "gaps": sorted(set(gaps)),
        **FLAGS,
    }
    return value


def persist_daily_run(service: Any, target_trade_date: str, *, now: datetime) -> dict[str, Any]:
    value = build_daily_run(service, target_trade_date, now=now)
    unsigned = dict(value)
    value["artifact_sha256"] = sha256_json(unsigned)
    _safe_tree(value)
    store = service.store
    directory = store.root / "us_mapping_research" / value["target_trade_date"]
    run_path = directory / "runs" / f"{value['run_id']}.json"
    pointer_path = directory / "latest.json"
    with store._transaction(value["target_trade_date"], value["input_identity"]):
        store._write_atomic(run_path, value)
        pointer = {
            "schema_version": "v4.manager_research.us_mapping_daily_pointer.v1",
            "target_trade_date": value["target_trade_date"],
            "run_id": value["run_id"],
            "artifact_sha256": value["artifact_sha256"],
            **FLAGS,
        }
        store._write_atomic(pointer_path, pointer)
    saved = _read_saved(store, value["target_trade_date"])
    if saved is None or saved.get("artifact_sha256") != value["artifact_sha256"]:
        raise ValueError("US_MAPPING_DAILY_READBACK_FAILED")
    return saved


__all__ = ["DAILY_SCHEMA", "SCHEMA", "build_daily_run", "persist_daily_run", "read_workspace_mapping"]
