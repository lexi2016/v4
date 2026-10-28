"""Verified shared Baimao observation adapter for the D-1 preselection pool.

The shared observation store owns artifact, manifest, receipt and SHA checks.
This adapter only selects one exact effective trade-date entry and projects its
A/BJ observations into the V3.5 research-only pool contract.  It never falls
back to the newest source date and never projects HK observations into the
A-share lane.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from infrastructure.isolated_package_loader import load_isolated_package_module


_ASSET_NAME = "baimao_observations"
_LATEST_SCHEMA = "BAIMAO_RESEARCH_OBSERVATION_LATEST_V1"
_POOL_ID = "a_share_baimao_research_map"
_DISPLAY_NAME = "白毛卡点研究池"
_EMPTY_SOURCE_SHA = hashlib.sha256(b"").hexdigest()
_SHA = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^\d{8}$")
_A_CODE = re.compile(r"^(\d{6})\.(?:SH|SZ|BJ)$", re.IGNORECASE)


def _date(value: Any, label: str) -> str:
    text = str(value or "")
    if not _DATE.fullmatch(text):
        raise ValueError(f"{label} must use YYYYMMDD")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as error:
        raise ValueError(f"{label} is not a real calendar date") from error
    return text


def _asset_root(shared_data_root: Path) -> Path:
    root = Path(shared_data_root).expanduser().resolve()
    return root if root.name == _ASSET_NAME else root / _ASSET_NAME


def _empty(trade_date: str, reason: str, *, source_path: str = "") -> dict[str, Any]:
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": _POOL_ID,
        "display_name": _DISPLAY_NAME,
        "market": "A",
        "status": "CANNOT_CONFIRM",
        "producer_id": "shared_data.baimao_observations.v1",
        "source_role": "RAW_SOURCE",
        "source_path": source_path,
        "source_sha256": _EMPTY_SOURCE_SHA,
        "rows": [],
        "cannot_confirm": [reason],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _read_latest(asset_root: Path) -> Mapping[str, Any]:
    latest_path = asset_root / "latest.json"
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"latest snapshot unreadable: {latest_path}") from error
    if not isinstance(payload, Mapping) or payload.get("schema_version") != _LATEST_SCHEMA:
        raise ValueError("latest snapshot schema mismatch")
    entries = payload.get("entries")
    if not isinstance(entries, Mapping):
        raise ValueError("latest snapshot entries are invalid")
    return payload


def _verifier(shared_package_root: Path):
    module = load_isolated_package_module(
        Path(shared_package_root).expanduser().resolve(),
        package_directory="shared_data",
        module_leaf="baimao_observations",
        namespace_prefix="v35_baimao",
    )
    verifier = getattr(module, "load_verified_observations", None)
    if not callable(verifier):
        raise ValueError("shared Baimao observation verifier is unavailable")
    return verifier


def _artifact_path(asset_root: Path, entry: Mapping[str, Any]) -> Path:
    relative = str(entry.get("artifact_relative") or "")
    path = (asset_root / relative).resolve()
    if path != asset_root and asset_root not in path.parents:
        raise ValueError("Baimao artifact path escapes shared observation root")
    return path


def _project(
    payload: Mapping[str, Any],
    *,
    trade_date: str,
    artifact_path: Path,
    artifact_sha: str,
) -> dict[str, Any]:
    if payload.get("effective_trade_date") != trade_date:
        return _empty(trade_date, "BAIMAO_EFFECTIVE_TRADE_DATE_MISMATCH")
    observations = payload.get("observations")
    a_rows = observations.get("a_bj") if isinstance(observations, Mapping) else None
    hk_rows = observations.get("hk") if isinstance(observations, Mapping) else None
    if not isinstance(a_rows, list) or not isinstance(hk_rows, list):
        return _empty(trade_date, "BAIMAO_OBSERVATIONS_GROUPS_INVALID")
    if not _SHA.fullmatch(artifact_sha):
        return _empty(trade_date, "BAIMAO_ARTIFACT_SHA_INVALID")

    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(a_rows, start=1):
        if not isinstance(raw, Mapping) or raw.get("market") != "A/BJ":
            return _empty(trade_date, "BAIMAO_A_BJ_OBSERVATION_INVALID")
        match = _A_CODE.fullmatch(str(raw.get("code") or ""))
        if match is None:
            return _empty(trade_date, "BAIMAO_A_BJ_CODE_INVALID")
        # Keep every verified research/evidence field; only add V3.5 routing
        # fields needed by the independent pool store.
        row = dict(raw)
        row.update({
            "symbol": f"A.{match.group(1)}",
            "market": "A",
            "pool_id": _POOL_ID,
            "pool_rank": index,
            "stock_name": str(raw.get("name") or f"A.{match.group(1)}"),
            "source_date": str(payload.get("source_date") or ""),
            "effective_trade_date": trade_date,
            "target_date": trade_date,
            "recommendation_status": "RESEARCH_ONLY",
            "trade_status_contract": "RESEARCH_ONLY_NO_BUY_GATE",
            "formal_pool_write": False,
            "buy_gate_write": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        })
        rows.append(row)

    # The verifier validates HK rows as CANNOT_CONFIRM.  They are intentionally
    # not projected into this A-share pool.
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": _POOL_ID,
        "display_name": _DISPLAY_NAME,
        "market": "A",
        "status": "BAIMAO_RESEARCH_MAP_READY" if rows else "CANNOT_CONFIRM",
        "producer_id": "shared_data.baimao_observations.v1",
        "source_role": "RAW_SOURCE",
        "source_path": str(artifact_path),
        "source_sha256": artifact_sha,
        "source_run_id": str(payload.get("source_run_id") or ""),
        "source_row_count": len(a_rows),
        "rows": rows,
        "cannot_confirm": ["RESEARCH_ONLY_NO_BUY_GATE"] if rows else ["BAIMAO_A_BJ_OBSERVATIONS_EMPTY"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def load_baimao_preselection_pool(
    shared_data_root: Path | str,
    shared_package_root: Path | str,
    trade_date: str,
) -> dict[str, Any]:
    """Build the exact effective-date A/BJ research map or a typed empty pool."""
    trade_date = _date(trade_date, "trade_date")
    asset_root = _asset_root(Path(shared_data_root))
    try:
        latest = _read_latest(asset_root)
        entries = latest["entries"]
        candidates: list[tuple[str, Mapping[str, Any]]] = []
        for source_date, entry in entries.items():
            if not _DATE.fullmatch(str(source_date)) or not isinstance(entry, Mapping):
                continue
            if entry.get("effective_trade_date") == trade_date:
                candidates.append((str(source_date), entry))
        if not candidates:
            return _empty(trade_date, "BAIMAO_RESEARCH_MAP_NOT_FOUND", source_path=str(asset_root / "latest.json"))
        if len(candidates) != 1:
            return _empty(trade_date, "BAIMAO_EFFECTIVE_TRADE_DATE_NOT_UNIQUE", source_path=str(asset_root / "latest.json"))

        source_date, entry = candidates[0]
        artifact_path = _artifact_path(asset_root, entry)
        verifier = _verifier(Path(shared_package_root))
        payload = verifier(asset_root, source_date)
        if not isinstance(payload, Mapping):
            raise ValueError("shared verifier returned a non-object")
        if payload.get("source_date") != source_date or payload.get("effective_trade_date") != trade_date:
            raise ValueError("verified Baimao exact-date metadata mismatch")
        artifact_sha = str(entry.get("artifact_sha256") or "")
        return _project(
            payload,
            trade_date=trade_date,
            artifact_path=artifact_path,
            artifact_sha=artifact_sha,
        )
    except Exception as error:
        return _empty(
            trade_date,
            f"BAIMAO_SHARED_SOURCE_UNVERIFIED:{type(error).__name__}:{error}",
            source_path=str(asset_root / "latest.json"),
        )


__all__ = ["load_baimao_preselection_pool"]
