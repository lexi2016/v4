"""Frozen contracts for the v3_shared_data raw store (Task 1 batch).

Only file-replay of already-frozen raw artifacts is implemented. No live
collectors, no shell execution, no trading / BUY gate semantics live here.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Schema versions
# ---------------------------------------------------------------------------
ARTIFACT_SCHEMA_VERSION = "v3_shared_data.artifact.csv.v1"
MANIFEST_SCHEMA_VERSION = "v3_shared_data.manifest.v1"
RECEIPT_SCHEMA_VERSION = "v3_shared_data.receipt.v1"
LATEST_SCHEMA_VERSION = "v3_shared_data.latest.v1"
OWNERS_SCHEMA_VERSION = "v3_shared_data.owners.v1"

# ---------------------------------------------------------------------------
# Frozen stage ids (mirror of V3 HKCONNECT_RTDATA_AUTO_STAGE_IDS, frozen 2026-08-06)
# ---------------------------------------------------------------------------
FROZEN_STAGE_IDS = frozenset(
    {
        "STAGE_0925",
        "STAGE_0930_0935",
        "STAGE_0935_0940",
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
        "STAGE_1545_1555",
    }
)

# ---------------------------------------------------------------------------
# Explicit zero-row / unproven statuses. READY is never derived from a
# header-only or unparseable input.
# ---------------------------------------------------------------------------
READY = "READY"
READY_EMPTY = "READY_EMPTY"
CANNOT_CONFIRM = "CANNOT_CONFIRM"
FAILED = "FAILED"
EXPLICIT_STATUSES = frozenset({READY, READY_EMPTY, CANNOT_CONFIRM})

# ---------------------------------------------------------------------------
# Safety flags: a receipt is only accepted when these are false.
# ---------------------------------------------------------------------------
SAFETY_FLAG_KEYS = ("production_allowed", "buy_gate_updated", "orders_sent")

# ---------------------------------------------------------------------------
# Owner registry. Single writer: only v3_shared_data may write the shared raw
# store. V3 and V3.5 are read-only consumers and are rejected as writers.
# ---------------------------------------------------------------------------
OWNER_REGISTRY: dict[str, dict[str, object]] = {
    "v3": {"write_policy": "read_only_consumer", "can_write": False},
    "v3.5": {"write_policy": "read_only_consumer", "can_write": False},
    "v3_shared_data": {"write_policy": "shared_raw_only", "can_write": True},
}

STORE_LOCK_NAME = ".store.lock"
STORE_LOCK_TIMEOUT_SECONDS = 10.0
STORE_LOCK_STALE_SECONDS = 30.0
