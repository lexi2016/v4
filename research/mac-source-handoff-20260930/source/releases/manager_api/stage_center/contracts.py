"""Public, frozen contracts for the independent stage center.

Batch 1 deliberately defines the selection envelope only.  It does not
define or migrate any scoring/ranking behavior.
"""
from __future__ import annotations

from dataclasses import dataclass

SAFETY_FLAGS: dict[str, bool] = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

SELECTION_SCHEMA_VERSION = "stage_center.selection.v1"
SELECTION_ALGORITHM_ID = "V3_STAGE_SELECTION_V1"
SELECTION_STATUSES = (
    "READY",
    "PARTIAL_WITH_ROWS",
    "READY_EMPTY",
    "CANNOT_CONFIRM",
)
# The legacy V3 reader and stage workbench both expose at most ten
# recommendations per market. Keep this as a shared contract so producer,
# immutable artifact, and read-only consumers cannot silently diverge.
STAGE_RECOMMENDATION_LIMIT = 10
SELECTION_FIELDS = (
    "schema_version",
    "trade_date",
    "stage_id",
    "market",
    "artifact_id",
    "run_id",
    "algorithm_id",
    "algorithm_sha256",
    "source_status",
    "selection_status",
    "requested_rows",
    "source_rows",
    "selected_rows",
    "coverage_ratio",
    "missing_symbols",
    "rows",
    "source_evidence",
    "cannot_confirm",
    *SAFETY_FLAGS,
)


@dataclass(frozen=True)
class StageSpec:
    stage_id: str
    cutoff: str
    markets: tuple[str, ...]
    window: str
    hk_window: str = ""


EIGHT_STAGES: tuple[StageSpec, ...] = (
    StageSpec("STAGE_0925", "09:25:05", ("A_SHARE", "HK_CONNECT"), "09:20-09:25", "09:15-09:20"),
    StageSpec("STAGE_0930_0935", "09:35:05", ("A_SHARE", "HK_CONNECT"), "09:30-09:35"),
    StageSpec("STAGE_0935_0940", "09:40:05", ("A_SHARE", "HK_CONNECT"), "09:35-09:40"),
    StageSpec("STAGE_0940_0945", "09:45:05", ("A_SHARE", "HK_CONNECT"), "09:40-09:45"),
    StageSpec("STAGE_0945_1030", "10:30:00", ("A_SHARE", "HK_CONNECT"), "09:45-10:30"),
    StageSpec("STAGE_1300_1315", "13:15:00", ("A_SHARE", "HK_CONNECT"), "13:00-13:15"),
    StageSpec("STAGE_1445_1500", "15:00:00", ("A_SHARE", "HK_CONNECT"), "14:45-15:00"),
    StageSpec("STAGE_1545_1555", "15:55:05", ("HK_CONNECT",), "15:45-15:55"),
)

STAGE_BY_ID = {stage.stage_id: stage for stage in EIGHT_STAGES}
if tuple(STAGE_BY_ID) != tuple(stage.stage_id for stage in EIGHT_STAGES):
    raise RuntimeError("stage order must remain chronological")
