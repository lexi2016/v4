"""Independent Mac stage market and selection center (batch 1)."""

from .contracts import EIGHT_STAGES, SAFETY_FLAGS, SELECTION_ALGORITHM_ID
from .acquisition import build_plan, dry_run_acquisition
from .calendar import calendar_provenance
from .selection import (
    ALGORITHM_SHA256,
    SelectionError,
    SelectionStore,
    a_stage_score,
    hk_four_lane_score,
    publish_selection,
    read_verified_selection,
    select_a_0925_auction,
    select_a_stage,
    select_hk_0925_second_filter,
    select_hk_four_lane,
)
from .consumer import StageSelectionConsumer, read_stage_selection

__all__ = [
    "EIGHT_STAGES",
    "SAFETY_FLAGS",
    "SELECTION_ALGORITHM_ID",
    "build_plan",
    "calendar_provenance",
    "dry_run_acquisition",
    "ALGORITHM_SHA256",
    "SelectionError",
    "SelectionStore",
    "a_stage_score",
    "hk_four_lane_score",
    "publish_selection",
    "read_verified_selection",
    "select_a_0925_auction",
    "select_a_stage",
    "select_hk_0925_second_filter",
    "select_hk_four_lane",
    "StageSelectionConsumer",
    "read_stage_selection",
]
