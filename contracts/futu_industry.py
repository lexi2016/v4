"""Contracts for official Futu board metrics and reviewed business relations."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ops._us_market_digest_parts.futu_boards import FUTU_BOARD_MAP


RELATION_EVIDENCE_FILE = "v4/manager_research/us_mapping_relation_evidence_20261011.json"
RELATION_REVIEW_FILE = "v4/manager_research/us_mapping_relation_evidence_review_20261011.json"


def load_reviewed_business_relations(repository_root: Path | None = None) -> dict[str, Any]:
    """Load only the exact existing reviewed relation artifact; never infer a mapping."""
    root = repository_root or Path(__file__).resolve().parents[1]
    evidence_path = root / RELATION_EVIDENCE_FILE
    review_path = root / RELATION_REVIEW_FILE
    try:
        evidence_bytes = evidence_path.read_bytes()
        review_bytes = review_path.read_bytes()
        evidence = json.loads(evidence_bytes.decode("utf-8"))
        review = json.loads(review_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {
            "status": "CANNOT_CONFIRM",
            "cannot_confirm": [f"RELATION_EVIDENCE_UNAVAILABLE:{type(error).__name__}"],
            "relations": [],
            "review": None,
        }

    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()
    review_sha = hashlib.sha256(review_bytes).hexdigest()
    reason = None
    if not isinstance(evidence, dict) or not isinstance(review, dict):
        reason = "RELATION_EVIDENCE_INVALID_SHAPE"
    elif review.get("status") != "PASS":
        reason = "RELATION_REVIEW_NOT_PASS"
    elif review.get("evidence_file_sha256") != evidence_sha:
        reason = "RELATION_EVIDENCE_FILE_HASH_MISMATCH"
    elif not evidence.get("artifact_sha256") or evidence.get("artifact_sha256") not in {
        review.get("declared_artifact_sha256"), review.get("recomputed_artifact_sha256")
    }:
        reason = "RELATION_ARTIFACT_HASH_MISMATCH"
    elif (
        evidence.get("RESEARCH_ONLY") is not True
        or evidence.get("production_allowed") is not False
        or evidence.get("buy_gate_updated") is not False
        or evidence.get("orders_sent") is not False
    ):
        reason = "RELATION_EVIDENCE_SAFETY_BOUNDARY_INVALID"

    relations = evidence.get("relations") if isinstance(evidence, dict) else None
    reviewed_pairs = review.get("reviewed_pairs") if isinstance(review, dict) else None
    if reason is None:
        relation_pairs = {
            (row.get("us_symbol"), row.get("hk_symbol"), row.get("relationship_type"), row.get("direction"))
            for row in relations
            if isinstance(row, dict)
        } if isinstance(relations, list) else set()
        reviewed_pair_keys = {
            (row.get("us_symbol"), row.get("hk_symbol"), row.get("relationship_type"), row.get("direction"))
            for row in reviewed_pairs
            if isinstance(row, dict)
        } if isinstance(reviewed_pairs, list) else set()
        if not relation_pairs or relation_pairs != reviewed_pair_keys or len(relation_pairs) != len(relations):
            reason = "RELATION_REVIEWED_PAIR_SET_MISMATCH"

    return {
        "status": "READY" if reason is None else "CANNOT_CONFIRM",
        "cannot_confirm": [] if reason is None else [reason],
        "relations": relations if reason is None else [],
        "review": review if reason is None else None,
        "evidence_path": str(evidence_path),
        "evidence_sha256": evidence_sha,
        "review_path": str(review_path),
        "review_sha256": review_sha,
    }


def relations_for_board(
    board_row: dict[str, Any],
    *,
    reviewed_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Intersect exact Futu board membership with the reviewed US-HK pairs."""
    if reviewed_evidence.get("status") != "READY":
        return {
            "status": "CANNOT_CONFIRM",
            "relations": [],
            "cannot_confirm": list(reviewed_evidence.get("cannot_confirm") or ["RELATION_REVIEW_UNAVAILABLE"]),
        }
    if board_row.get("membership_status") != "READY":
        return {"status": "CANNOT_CONFIRM", "relations": [], "cannot_confirm": ["BOARD_MEMBERSHIP_CANNOT_CONFIRM"]}
    members = set(board_row.get("relation_constituents") or [])
    relations = [
        {
            "us_symbol": relation.get("us_symbol"),
            "hk_symbol": relation.get("hk_symbol"),
            "relationship_type": relation.get("relationship_type"),
            "direction": relation.get("direction"),
            "reason": relation.get("reason"),
            "maturity": relation.get("maturity"),
            "available_at": relation.get("available_at"),
            "sources": [
                {
                    "role": source.get("role"),
                    "title": source.get("title"),
                    "url": source.get("url"),
                    "published_at": source.get("published_at"),
                    "retrieved_at": source.get("retrieved_at"),
                }
                for source in relation.get("sources") or []
                if isinstance(source, dict)
            ],
            "limitations": list(relation.get("limitations") or []),
        }
        for relation in reviewed_evidence.get("relations") or []
        if isinstance(relation, dict) and relation.get("us_symbol") in members
    ]
    return {
        "status": "READY" if relations else "NO_REVIEWED_RELATION_INTERSECTION",
        "relations": relations,
        "cannot_confirm": [] if relations else ["NO_REVIEWED_RELATION_INTERSECTION"],
        "target_date_eligibility": "CANNOT_CONFIRM",
    }


def project_industry_rows(
    proxy_rows: list[dict[str, Any]],
    *,
    futu_snapshot: dict[str, Any] | None,
    reviewed_evidence: dict[str, Any],
    capture_session_date: str,
) -> list[dict[str, Any]]:
    """Separate official board metrics from the legacy ETF/basket reference."""
    boards = {
        row.get("label"): row
        for row in (futu_snapshot or {}).get("rows", [])
        if isinstance(row, dict)
    }
    expected = {item["label"]: item for item in FUTU_BOARD_MAP}
    projected: list[dict[str, Any]] = []
    for proxy in proxy_rows:
        label = proxy.get("label")
        mapping = expected.get(label)
        board = boards.get(label)
        if board is None:
            board = {
                "label": label,
                "metric_kind": "OFFICIAL_BOARD",
                "market": "US",
                "plate_type": mapping.get("plate_type") if mapping else None,
                "expected_board_name": mapping.get("plate_name") if mapping else None,
                "board_name": None,
                "board_code": None,
                "update_time": None,
                "session_date": None,
                "timezone": "America/New_York",
                "last": None,
                "previous_close": None,
                "change_pct": None,
                "plate_valid": None,
                "rise_count": None,
                "fall_count": None,
                "equal_count": None,
                "member_count": None,
                "relation_constituents": [],
                "membership_status": "CANNOT_CONFIRM",
                "membership_sha256": "",
                "source_response_sha256": "",
                "status": "CANNOT_CONFIRM",
                "cannot_confirm": ["FUTU_BOARD_SNAPSHOT_MISSING"],
            }
        official_ready = (
            board.get("status") == "READY"
            and board.get("plate_valid") is True
            and board.get("session_date") == capture_session_date
            and isinstance(board.get("change_pct"), (int, float))
            and not isinstance(board.get("change_pct"), bool)
        )
        change = float(board["change_pct"]) if official_ready else None
        direction = "UP" if change is not None and change > 0 else "DOWN" if change is not None and change < 0 else "FLAT" if change is not None else "CANNOT_CONFIRM"
        row_reasons = [] if official_ready else list(board.get("cannot_confirm") or ["FUTU_BOARD_METRIC_CANNOT_CONFIRM"])
        if not official_ready and board.get("session_date") and board.get("session_date") != capture_session_date:
            row_reasons = sorted(set(row_reasons) | {"FUTU_BOARD_SESSION_DATE_MISMATCH"})
        relation = relations_for_board(board, reviewed_evidence=reviewed_evidence)
        proxy_status = proxy.get("status") or "CANNOT_CONFIRM"
        proxy_kind = "STOCK_BASKET_REFERENCE" if "basket" in str(proxy.get("mapping_type") or "") else "ETF_REFERENCE"
        proxy_reference = {
            "metric_kind": proxy_kind,
            "provider": "Tencent qt.gtimg.cn",
            "mapping_type": proxy.get("mapping_type"),
            "proxy_symbols": list(proxy.get("proxy_symbols") or []),
            "available_symbols": list(proxy.get("available_symbols") or []),
            "missing_symbols": list(proxy.get("missing_symbols") or []),
            "requested_symbol_count": proxy.get("requested_symbol_count"),
            "available_symbol_count": proxy.get("available_symbol_count"),
            "coverage": proxy.get("coverage"),
            "coverage_pct": proxy.get("coverage_pct"),
            "change_pct": proxy.get("change_pct"),
            "direction": proxy.get("direction") or "CANNOT_CONFIRM",
            "status": proxy_status,
            "quote_session_dates": list(proxy.get("quote_session_dates") or []),
            "quote_session_times": list(proxy.get("quote_session_times") or []),
            "cannot_confirm": list(proxy.get("cannot_confirm") or []),
        }
        projected.append({
            "label": label,
            "group": proxy.get("group"),
            "mapping_type": proxy.get("mapping_type"),
            "proxy_symbols": list(proxy.get("proxy_symbols") or []),
            "metric_kind": "OFFICIAL_BOARD",
            "available_symbols": [],
            "missing_symbols": [],
            "requested_symbol_count": 0,
            "available_symbol_count": 0,
            "coverage": {"available": 0, "requested": 0},
            "coverage_pct": None,
            "change_pct": change,
            "pct_change": change,
            "direction": direction,
            "status": "READY" if official_ready else "CANNOT_CONFIRM",
            "quote_session_dates": [board["session_date"]] if official_ready else [],
            "quote_session_times": [board["update_time"]] if official_ready and board.get("update_time") else [],
            "official_board": {
                **board,
                "status": "READY" if official_ready else "CANNOT_CONFIRM",
                "cannot_confirm": row_reasons,
                "relations": relation["relations"],
                "relation_status": relation["status"],
                "relation_cannot_confirm": relation["cannot_confirm"],
                "target_date_eligibility": relation.get("target_date_eligibility", "CANNOT_CONFIRM"),
            },
            "proxy_reference": proxy_reference,
            "cannot_confirm": row_reasons,
        })
    return projected

