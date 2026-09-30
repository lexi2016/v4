"""Frozen input contracts for the stage-acquisition consumer.

The stage-acquisition lane is intentionally narrower than the presentation
preselection projection.  These contracts identify the six known, ordered
physical A-share pool lanes.  A materialized aggregate may use any verified
non-empty subset while retaining diagnostics for unavailable lanes.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


REQUIRED_A_STAGE_POOL_IDS = (
    "a_d1_premarket_pool",
    "a_d1_fupan_watchlist_pool",
    "a_d1_stage7_fenshi_review_pool",
    "a_share_research_recommendation_pool",
    "a_share_baimao_research_map",
    "wechat_public_account_v3_preselect",
)

# The six IDs are the graph's known, ordered pool lanes.  They are kept as a
# separate public alias so callers can distinguish the finite allowlist from
# the old wording that implied every lane had to be present and non-empty.
KNOWN_A_STAGE_POOL_IDS = REQUIRED_A_STAGE_POOL_IDS

# Each tuple is (status, producer_id, source_role).  A producer-specific
# allowlist is deliberate: a generic "READY" or a familiar prefix must not
# turn an unknown source into stage membership authority.
_A_POOL_CONTRACTS = {
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

A_POOL_CONTRACTS: Mapping[str, tuple[str, str, str]] = MappingProxyType(
    {pool_id: tuple(contract) for pool_id, contract in _A_POOL_CONTRACTS.items()}
)


def a_pool_contract(pool_id: str) -> tuple[str, str, str]:
    """Return the exact (status, producer, source-role) contract for a pool."""

    try:
        return A_POOL_CONTRACTS[pool_id]
    except KeyError as error:
        raise ValueError(f"unknown required A pool: {pool_id}") from error


__all__ = [
    "A_POOL_CONTRACTS",
    "KNOWN_A_STAGE_POOL_IDS",
    "REQUIRED_A_STAGE_POOL_IDS",
    "a_pool_contract",
]
