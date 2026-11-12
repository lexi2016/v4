from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.stage_acquisition_universe_store import (
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)
from infrastructure.stage_acquisition_universe_commit import EvidenceIdentity
from ops.materialize_stage_acquisition_universe import (
    materialize_stage_acquisition_universe,
)
from domains.stage_preselection_projection import read_complete_a_set
from infrastructure.preselection_pool_store import PreselectionPoolStore


TRADE_DATE = "20260830"
IDENTITY = EvidenceIdentity(
    owner_id="V3_5_STAGE_CENTER",
    producer_id="ops.materialize_stage_acquisition_universe",
    release_id="test-release",
    lane_id="A_SHARE_STAGE_ACQUISITION",
)


def _projection(count: int) -> dict[str, object]:
    contracts = {
        "a_d1_premarket_pool": (
            "V192_CANDIDATE_READY",
            "v3_shared_v192_consumer_v1",
            "SHARED_VERIFIED_V192",
        ),
        "a_d1_fupan_watchlist_pool": (
            "FUPAN_WATCHLIST_POOL_READY_DATA_PARTIAL",
            "v3_fupan_watchlist_contract_v1",
            "VERIFIED_D1_FUPAN_REVIEW",
        ),
        "a_d1_stage7_fenshi_review_pool": (
            "STAGE7_TAIL_POOL_READY_DATA_PARTIAL",
            "v3_stage7_tail_replay_contract_v1",
            "VERIFIED_D1_STAGE7_REPLAY",
        ),
        "a_share_research_recommendation_pool": (
            "RESEARCH_RECOMMENDATION_POOL_READY",
            "v3_5_hourly_research_window_v1",
            "VERIFIED_HOURLY_RESEARCH",
        ),
        "a_share_baimao_research_map": (
            "BAIMAO_RESEARCH_MAP_READY",
            "wechat_baimao_shared_projection_v1",
            "VERIFIED_BAIMAO_RESEARCH",
        ),
        "wechat_public_account_v3_preselect": (
            "WECHAT_V3_PRESELECT_READY",
            "v3_wechat_preselect_upstream_v1",
            "VERIFIED_WECHAT_RESEARCH",
        ),
    }
    rows = [
        {
            "market": "A",
            "symbol": f"A.{index:06d}",
            "pool_id": "a_share_research_recommendation_pool",
            "recommendation_status": "WATCH_ONLY",
        }
        for index in range(1, count + 1)
    ]
    pools = []
    for pool_id, (status, producer_id, source_role) in contracts.items():
        pool_rows = [
            {**row, "pool_id": pool_id}
            for row in (rows if pool_id == "a_d1_premarket_pool" else rows[:1])
        ]
        pools.append(
            {
                "pool_id": pool_id,
                "status": status,
                "producer_id": producer_id,
                "source_role": source_role,
                "source_path": f"fixture://{pool_id}",
                "source_sha256": "a" * 64,
                "trade_date": TRADE_DATE,
                "market": "A",
                "rows": pool_rows,
                "cannot_confirm": [],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
    return {
        "ok": True,
        "trade_date": TRADE_DATE,
        "a_all_pool_rows": rows,
        "a_all_pool_row_count": len(rows),
        "data_status": "READY_WITH_ROWS",
        "status": "READY_WITH_ROWS",
        "cannot_confirm": [],
        "pools": pools,
    }


def _strict_physical_artifact(root: Path, count: int) -> dict[str, object]:
    projection = _projection(count)
    source_store = PreselectionPoolStore(root)
    for pool in projection["pools"]:
        pool["schema_version"] = "v3_5.preselection_pool.v1"
        pool["display_name"] = pool["pool_id"]
        source_store.materialize(pool)
    return build_stage_acquisition_universe(
        read_complete_a_set(root, TRADE_DATE), TRADE_DATE
    )


def test_materializer_rejects_arbitrary_projection_on_a_fresh_slot(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-authoritative"):
        materialize_stage_acquisition_universe(
            tmp_path,
            TRADE_DATE,
            projection_reader=lambda *_args: _projection(403),
            run_id="legacy-fresh-must-not-publish",
        )
    assert not (tmp_path / "current").exists()


def test_materializer_rejects_arbitrary_projection_with_existing_current(
    tmp_path: Path,
) -> None:
    store = StageAcquisitionUniverseStore(tmp_path)
    store.publish(
        _strict_physical_artifact(tmp_path, 1),
        run_id="strict-current",
        identity=IDENTITY,
    )
    current_path = store.read_strict_verified(
        TRADE_DATE, identity=IDENTITY
    )["current_path"]
    current_before = current_path.read_bytes()

    with pytest.raises(ValueError, match="non-authoritative"):
        materialize_stage_acquisition_universe(
            tmp_path,
            TRADE_DATE,
            projection_reader=lambda *_args: _projection(421),
            run_id="legacy-successor-must-not-publish",
        )

    assert current_path.read_bytes() == current_before
    assert not store._run_dir(TRADE_DATE, "legacy-successor-must-not-publish").exists()
