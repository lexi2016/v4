"""Build and publish the V3.5-native HK Connect close review."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from domains.close_review import _REVIEW_STAGE_IDS, build_native_close_review
from infrastructure.data_store import _sha256
from infrastructure.hkconnect_close_store import CloseSnapshotStore
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.review_store import ReviewStore
from stage_center.consumer import StageSelectionConsumer


_HK_MODEL_SOURCE_ROLES = frozenset(
    {"SHARED_VERIFIED_HK_0_2", "VERIFIED_HK_0_2_STANDARD"}
)


def _model_rows(preselection: dict[str, Any], trade_date: str) -> list[dict[str, Any]]:
    if not isinstance(preselection, dict):
        return []
    if (
        preselection.get("pool_id") != "hkconnect_d1_top100"
        or preselection.get("trade_date") != trade_date
        or preselection.get("status") != "STRICT_0_2_READY"
        or preselection.get("source_role") not in _HK_MODEL_SOURCE_ROLES
        or any(preselection.get(flag) is not False for flag in (
            "production_allowed", "buy_gate_updated", "orders_sent",
        ))
    ):
        return []
    source_rows = preselection.get("rows")
    if not isinstance(source_rows, list) or len(source_rows) != 100:
        return []
    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for row in source_rows:
        if not isinstance(row, dict):
            return []
        code = str(row.get("symbol") or row.get("code") or "").strip().upper()
        if (
            str(row.get("market") or "").upper() not in {"HK", "HKCONNECT"}
            or str(row.get("target_date") or row.get("trade_date") or "") != trade_date
            or not code
            or code in seen_codes
        ):
            return []
        seen_codes.add(code)
        rows.append(row)
    return rows if len(seen_codes) == 100 else []


def _stage_rows(
    stage_selection_root: Path | str | None,
    trade_date: str,
) -> dict[str, list[dict[str, Any]] | None]:
    result: dict[str, list[dict[str, Any]] | None] = {}
    if stage_selection_root is None:
        return {stage_id: None for stage_id in _REVIEW_STAGE_IDS}
    consumer = StageSelectionConsumer(stage_selection_root)
    for stage_id in _REVIEW_STAGE_IDS:
        try:
            response = consumer.get(
                trade_date,
                stage_id,
                markets=("HK_CONNECT",),
            )
            market = response.get("markets", {}).get("HK_CONNECT")
            status = str(
                market.get("status") or market.get("selection_status") or ""
            ) if isinstance(market, dict) else ""
            response_safe = all(
                response.get(flag) is False
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
            )
            exact_identity = (
                response.get("trade_date") == trade_date
                and response.get("stage_id") == stage_id
            )
            integrity_gap = (
                list(response.get("cannot_confirm") or ())
                == ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"]
                or list(market.get("cannot_confirm") or ())
                == ["SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID"]
                if isinstance(market, dict)
                else True
            )
            rows = (
                market.get("rows")
                if isinstance(market, dict)
                and status in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"}
                and response_safe
                and exact_identity
                and not integrity_gap
                else None
            )
        except (OSError, TypeError, ValueError):
            rows = None
        if not isinstance(rows, list):
            result[stage_id] = None
            continue
        projected_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            market = str(row.get("market") or "HK").upper()
            if market not in {"HK", "HKCONNECT"}:
                continue
            projected = dict(row)
            projected.setdefault("market", "HK")
            projected_rows.append(projected)
        result[stage_id] = projected_rows
    return result


def build_close_review(
    data_root: Path,
    trade_date: str,
    *,
    stage_selection_root: Path | str | None = None,
) -> dict[str, Any]:
    data_root = Path(data_root)
    snapshot, snapshot_sha = CloseSnapshotStore(data_root).read_snapshot(trade_date)
    try:
        preselection = PreselectionPoolStore(data_root).read_pool(
            trade_date,
            "hkconnect_d1_top100",
        )
    except (FileNotFoundError, OSError, TypeError, ValueError):
        # The verified pool is exact-date input.  A missing or invalid pool is
        # represented as a model-source gap; never substitute the legacy
        # NativeDataStore payload or another date.
        preselection = {}
    review = build_native_close_review(
        trade_date,
        close_rows=snapshot["rows"],
        model_rows=_model_rows(preselection, trade_date),
        stage_rows=_stage_rows(stage_selection_root, trade_date),
        close_source_sha256=snapshot_sha,
    )
    review_store = ReviewStore(data_root)
    current = review_store.read_reference(trade_date)
    expected_sha = _sha256(current) if current is not None else None
    publication = review_store.publish_native(review, expected_sha256=expected_sha)
    return {"review": review, "publication": publication}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the V3.5-native HK Connect close review")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--stage-selection-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(
        build_close_review(
            args.data_root,
            args.date,
            stage_selection_root=args.stage_selection_root,
        ),
        ensure_ascii=False,
    ))


if __name__ == "__main__":
    main()
