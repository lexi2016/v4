"""ops.run_stage_center_nodes: stage_dispatch (review candidate, not deployment)."""
from __future__ import annotations
import hashlib
import sys
import subprocess
import hashlib as _stage_hashlib
import os
from pathlib import Path
from ._namespace import read_global as _v4_global


_HK_0930_0935_CUTOFF_RECOVERY_DATE = "20261012"
_HK_0930_0935_CUTOFF_RECOVERY_STAGE = "STAGE_0930_0935"
_HK_0930_0935_CUTOFF_RECOVERY_REASONS = [
    "PyTDX ExHQ batch coverage incomplete: completed=100/100",
    "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",
]
_HK_0930_0935_RECOVERY_DEADLINE_ERRORS = {
    "END_TO_END_5S_EXCEEDED_BEFORE_RECEIPT",
    "END_TO_END_5S_EXCEEDED_AFTER_RECEIPT_DURABILITY",
}
_HK_1300_1315_CUTOFF_RECOVERY_DATE = "20261012"
_HK_1300_1315_CUTOFF_RECOVERY_STAGE = "STAGE_1300_1315"
_HK_1300_1315_CUTOFF_RECOVERY_CAUSE = "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"
_HK_1300_1315_CUTOFF_RECOVERY_A_RUN_ID = "run-3b2d201a7635f0fab5ab4f6d"
_NATURAL_LATE_OBSERVATION_DATE = "20261012"
_NATURAL_LATE_OBSERVATION_STAGES = frozenset({
    "STAGE_1300_1315",
    "STAGE_1445_1500",
})
_HK_FUTU_1445_RECOVERY_DATE = "20261012"
_HK_FUTU_1445_RECOVERY_STAGE = "STAGE_1445_1500"
_HK_FUTU_1445_PRIOR_RECEIPT_SHA256 = "907f00b0c7b2280315cc642c37fc71360fdfcc9d3949374c0c183c7ab7cc837f"
_HK_FUTU_1445_DATASET_SHA256 = "4a310b4920dc5c6ebb7ac8b9f50d1e73d2dcb4d0ef685fef329358c09c2223d0"
_HK_FUTU_1300_RECOVERY_DATE = "20261012"
_HK_FUTU_1300_RECOVERY_STAGE = "STAGE_1300_1315"
_HK_FUTU_1300_PRIOR_RECEIPT_SHA256 = "1e7a2fe0b3236de35b79688af6c34b4b2798f16a8bd1e0d6bc0bcf9d7758d0d6"
_HK_FUTU_1300_DATASET_SHA256 = "63cba10b805b60dc7108ac7d633b0b1c32da2211b04fd976e1cd637ce083afe0"
_HK_FUTU_1300_CONSUMPTION_MARKER = "futu_afterfact_1300_once.json"


def _a_0925_original_budget_recovery(
    _v4_scope, /, config, receipt, *, mode, trade_date, stage_id, evaluated_at,
    attempt_count, max_attempts,
):
    """Reopen only a same-day empty A auction lane under its original budget."""
    if (mode != "RECOVERY" or stage_id != "STAGE_0925"
            or "a_0925_recovery_authorization" in config
            or type(attempt_count) is not int or type(max_attempts) is not int
            or max_attempts != 3 or not 0 < attempt_count < max_attempts
            or not isinstance(receipt, dict)
            or receipt.get("schema_version") != "stage_center.runner.receipt.v1"
            or receipt.get("trade_date") != trade_date or receipt.get("stage_id") != stage_id
            or type(receipt.get("node_attempt_count")) is not int
            or receipt["node_attempt_count"] != attempt_count
            or any(receipt.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or any(k.startswith(("repair_recovery_", "dependency_rearm_")) for k in receipt)):
        return False
    wall = _v4_global(_v4_scope, '_rearm_wall_now')()
    safety = config.get("safety")
    if (evaluated_at.tzinfo is None or wall.tzinfo is None
            or _v4_global(_v4_scope, '_as_shanghai')(wall).strftime("%Y%m%d") != trade_date
            or _v4_global(_v4_scope, '_as_shanghai')(evaluated_at).strftime("%Y%m%d") != trade_date
            or evaluated_at > wall or not isinstance(safety, dict)
            or any(safety.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        return False
    markets = receipt.get("markets")
    if not isinstance(markets, dict):
        return False
    a, hk = markets.get("A_SHARE"), markets.get("HK_CONNECT")
    if (not isinstance(a, dict) or not isinstance(hk, dict)
            or a.get("selection_status") != "CANNOT_CONFIRM"
            or type(a.get("selected_rows")) is not int or a["selected_rows"] != 0
            or a.get("write_performed") is not False
            or hk.get("selection_status") not in {"READY", "PARTIAL_WITH_ROWS"}
            or type(hk.get("selected_rows")) is not int or hk["selected_rows"] <= 0
            or not hk.get("run_id")):
        return False
    continued = (receipt.get("execution_origin") == "A_ORIGINAL_BUDGET_RECOVERY"
        and receipt.get("execution_markets") == ["A_SHARE"]
        and receipt.get("status") in {"CANNOT_CONFIRM", "PARTIAL_COMMIT_RETRY_REQUIRED"})
    original = (receipt.get("status") == "PARTIAL_WITH_ROWS"
        and receipt.get("node_outcome") == "SETTLED_PARTIAL"
        and receipt.get("write_performed") is True
        and not receipt.get("execution_origin")
        and a.get("status") == a.get("source_status") == "CANNOT_CONFIRM"
        and isinstance(a.get("cannot_confirm"), (list, tuple))
        and any(isinstance(reason, str) and reason.startswith("PYTDX_0925_REPLAY_ERROR:")
                for reason in a.get("cannot_confirm", ())))
    if not (original or continued):
        return False
    from stage_center.candidate_input import CandidateInputError, read_candidate_input
    try:
        candidate = read_candidate_input(Path(str(config["candidate_acquisition_root"])), trade_date,
            expected_current_sha256=receipt.get("candidate_current_sha256"))
    except (CandidateInputError, KeyError, OSError, TypeError, ValueError):
        return False
    return (candidate.current_sha256 == receipt.get("candidate_current_sha256")
            and candidate.run_id == receipt.get("candidate_run_id") and bool(candidate.codes))


def _clear_stale_scoped_recovery_failure(prior, result, *, origin):
    """Drop only an unchanged prior failure after a row-bearing HK recovery."""
    if origin != "HK_ORIGINAL_BUDGET_RECOVERY" or not isinstance(prior, dict) or not isinstance(result, dict):
        return result
    prior_error = prior.get("error")
    prior_layer = prior.get("first_failed_layer")
    if not prior_error or result.get("error") != prior_error or result.get("first_failed_layer") != prior_layer:
        return result
    hk = (result.get("markets") or {}).get("HK_CONNECT")
    if (
        result.get("status") != "PARTIAL_WITH_ROWS"
        or not isinstance(hk, dict)
        or hk.get("selection_status") != "PARTIAL_WITH_ROWS"
        or type(hk.get("selected_rows")) is not int
        or hk.get("selected_rows") <= 0
        or not isinstance(hk.get("run_id"), str)
        or not hk.get("run_id")
        or not isinstance(hk.get("raw_artifact_sha256"), str)
        or len(hk.get("raw_artifact_sha256")) != 64
        or any(char not in "0123456789abcdef" for char in hk["raw_artifact_sha256"])
    ):
        return result
    cleaned = dict(result)
    # Explicit nulls override the frozen prior receipt during the final
    # scoped merge while the byte-exact prior remains archived separately.
    cleaned["error"] = None
    cleaned["first_failed_layer"] = None
    return cleaned


def _same_day_hk_1445_futu_recovery_shape(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts,
    receipt_sha256, dataset_sha256,
):
    """Allow one exact cached Futu observation recovery inside the existing slot."""

    if (
        mode != "RECOVERY"
        or trade_date != _HK_FUTU_1445_RECOVERY_DATE
        or stage_id != _HK_FUTU_1445_RECOVERY_STAGE
        or receipt_sha256 != _HK_FUTU_1445_PRIOR_RECEIPT_SHA256
        or dataset_sha256 != _HK_FUTU_1445_DATASET_SHA256
        or type(attempt_count) is not int
        or type(max_attempts) is not int
        or attempt_count != 1
        or max_attempts != 3
        or not isinstance(receipt, dict)
        or any(
            receipt.get(flag) is not False
            for flag in ("production_allowed", "buy_gate_updated", "orders_sent")
        )
    ):
        return False
    required = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": _HK_FUTU_1445_RECOVERY_DATE,
        "stage_id": _HK_FUTU_1445_RECOVERY_STAGE,
        "node_id": _HK_FUTU_1445_RECOVERY_STAGE,
        "status": "PARTIAL_WITH_ROWS",
        "due_status": "LATE_CATCHUP_REPLAY",
        "dispatch_mode": "NATURAL",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": 1,
        "write_performed": True,
        "retry_exhausted": False,
        "candidate_current_sha256": "c26102284e3eca12614118c3481e139ad805d65719d300f23e30887a9bf548b9",
        "candidate_run_id": "20261012-a_share_stage_acquisition_universe_v3-8923902e3cc4",
    }
    if type(receipt.get("node_attempt_count")) is not int or any(
        receipt.get(key) != value for key, value in required.items()
    ):
        return False
    markets = receipt.get("markets")
    if not isinstance(markets, dict):
        return False
    a_share = markets.get("A_SHARE")
    hk = markets.get("HK_CONNECT")
    return (
        isinstance(a_share, dict)
        and a_share.get("market") == "A_SHARE"
        and a_share.get("selection_status") == "PARTIAL_WITH_ROWS"
        and type(a_share.get("selected_rows")) is int
        and a_share.get("selected_rows") == 10
        and a_share.get("run_id") == "run-6bb61f95527796da3cd57bd2"
        and isinstance(hk, dict)
        and hk.get("market") == "HK_CONNECT"
        and hk.get("status") == "CANNOT_CONFIRM"
        and hk.get("source_status") == "CANNOT_CONFIRM"
        and hk.get("selection_status") == "CANNOT_CONFIRM"
        and type(hk.get("selected_rows")) is int
        and hk.get("selected_rows") == 0
        and hk.get("write_performed") is False
        and hk.get("cannot_confirm") == [
            "PyTDX ExHQ probe execution failed",
            "PyTDX ExHQ probe returned an error",
            "PyTDX ExHQ batch coverage incomplete: completed=0/100",
        ]
    )


def _frozen_hk_futu_1445_hashes(config, trade_date, stage_id, mode):
    if (
        mode != "RECOVERY"
        or trade_date != _HK_FUTU_1445_RECOVERY_DATE
        or stage_id != _HK_FUTU_1445_RECOVERY_STAGE
    ):
        return None, None
    receipt_path = (
        Path(str(config["receipt_root"])).expanduser().resolve()
        / trade_date / stage_id / "receipt.json"
    )
    dataset_path = os.environ.get("V4_HK_FUTU_AFTERFACT_DATASET")
    try:
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    except OSError:
        receipt_sha256 = None
    try:
        dataset_sha256 = hashlib.sha256(Path(dataset_path).expanduser().read_bytes()).hexdigest() if dataset_path else None
    except OSError:
        dataset_sha256 = None
    return receipt_sha256, dataset_sha256


def _frozen_hk_futu_1300_hashes(config, trade_date, stage_id, mode):
    if (
        mode != "RECOVERY"
        or trade_date != _HK_FUTU_1300_RECOVERY_DATE
        or stage_id != _HK_FUTU_1300_RECOVERY_STAGE
    ):
        return None, None
    receipt_path = (
        Path(str(config["receipt_root"])).expanduser().resolve()
        / trade_date / stage_id / "receipt.json"
    )
    dataset_path = os.environ.get("V4_HK_FUTU_AFTERFACT_DATASET")
    try:
        receipt_sha256 = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    except OSError:
        receipt_sha256 = None
    try:
        dataset_sha256 = hashlib.sha256(Path(dataset_path).expanduser().read_bytes()).hexdigest() if dataset_path else None
    except OSError:
        dataset_sha256 = None
    return receipt_sha256, dataset_sha256


def _same_day_hk_1300_futu_recovery_shape(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts,
    receipt_sha256, dataset_sha256,
):
    """Authorize one exact new-source recovery after the original budget is exhausted."""
    if (
        mode != "RECOVERY"
        or trade_date != _HK_FUTU_1300_RECOVERY_DATE
        or stage_id != _HK_FUTU_1300_RECOVERY_STAGE
        or receipt_sha256 != _HK_FUTU_1300_PRIOR_RECEIPT_SHA256
        or dataset_sha256 != _HK_FUTU_1300_DATASET_SHA256
        or type(attempt_count) is not int
        or type(max_attempts) is not int
        or attempt_count != 3
        or max_attempts != 3
        or not isinstance(receipt, dict)
        or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        return False
    required = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": _HK_FUTU_1300_RECOVERY_DATE,
        "stage_id": _HK_FUTU_1300_RECOVERY_STAGE,
        "node_id": _HK_FUTU_1300_RECOVERY_STAGE,
        "status": "CANNOT_CONFIRM",
        "due_status": "LATE_CATCHUP_REPLAY",
        "dispatch_mode": "RECOVERY",
        "node_outcome": "TRANSIENT",
        "node_attempt_count": 3,
        "retry_exhausted": True,
        "write_performed": False,
        "candidate_current_sha256": "c26102284e3eca12614118c3481e139ad805d65719d300f23e30887a9bf548b9",
        "candidate_run_id": "20261012-a_share_stage_acquisition_universe_v3-8923902e3cc4",
        "execution_origin": "HK_ORIGINAL_BUDGET_RECOVERY",
        "execution_markets": ["HK_CONNECT"],
    }
    if type(receipt.get("node_attempt_count")) is not int or any(
        receipt.get(key) != value for key, value in required.items()
    ):
        return False
    markets = receipt.get("markets")
    if not isinstance(markets, dict):
        return False
    a_share = markets.get("A_SHARE")
    hk = markets.get("HK_CONNECT")
    return (
        isinstance(a_share, dict)
        and a_share.get("selection_status") == "PARTIAL_WITH_ROWS"
        and type(a_share.get("selected_rows")) is int
        and a_share.get("selected_rows") == 10
        and a_share.get("run_id") == "run-3b2d201a7635f0fab5ab4f6d"
        and isinstance(hk, dict)
        and hk.get("selected_rows") in (None, 0)
        and hk.get("write_performed") in (None, False)
        and hk.get("cannot_confirm") == [
            "PyTDX ExHQ probe execution failed",
            "PyTDX ExHQ probe returned an error",
            "PyTDX ExHQ batch coverage incomplete: completed=0/100",
        ]
    )


def _same_day_late_observation_recovery(
    _v4_scope, /, *, mode, trade_date, evaluated_at, decision, stage_id=None
):
    natural_afternoon_observation = (
        mode == "NATURAL"
        and trade_date == _NATURAL_LATE_OBSERVATION_DATE
        and stage_id in _NATURAL_LATE_OBSERVATION_STAGES
        and getattr(decision, "stage_id", None) == stage_id
    )
    if (mode != "RECOVERY" and not natural_afternoon_observation) or decision.status != "LATE_CATCHUP_REPLAY":
        return False
    if getattr(decision, "trade_date", None) != trade_date:
        return False
    scheduled_at = getattr(decision, "scheduled_at", None)
    if scheduled_at is None:
        return False
    local_now = _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
    if local_now.strftime("%Y%m%d") != trade_date:
        return False
    local_cutoff = _v4_global(_v4_scope, '_as_shanghai')(scheduled_at)
    return local_now > local_cutoff


def _same_day_hk_1300_1315_cutoff_recovery_shape(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts
):
    """Match only the original 2026-10-12 13:00 natural HK cutoff receipt."""

    if (
        mode != "RECOVERY"
        or trade_date != _HK_1300_1315_CUTOFF_RECOVERY_DATE
        or stage_id != _HK_1300_1315_CUTOFF_RECOVERY_STAGE
        or not isinstance(receipt, dict)
        or type(attempt_count) is not int
        or type(max_attempts) is not int
        or attempt_count != 1
        or max_attempts != 3
        or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        return False
    required = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": _HK_1300_1315_CUTOFF_RECOVERY_DATE,
        "stage_id": _HK_1300_1315_CUTOFF_RECOVERY_STAGE,
        "node_id": _HK_1300_1315_CUTOFF_RECOVERY_STAGE,
        "status": "PARTIAL_WITH_ROWS",
        "due_status": "LATE_CATCHUP_REPLAY",
        "dispatch_mode": "NATURAL",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": 1,
        "write_performed": True,
    }
    if type(receipt.get("node_attempt_count")) is not int or any(
        receipt.get(key) != value for key, value in required.items()
    ):
        return False
    markets = receipt.get("markets")
    if not isinstance(markets, dict):
        return False
    a_share = markets.get("A_SHARE")
    hk = markets.get("HK_CONNECT")
    return (
        isinstance(a_share, dict)
        and a_share.get("market") == "A_SHARE"
        and a_share.get("selection_status") == "PARTIAL_WITH_ROWS"
        and type(a_share.get("selected_rows")) is int
        and a_share.get("selected_rows") == 10
        and a_share.get("run_id") == _HK_1300_1315_CUTOFF_RECOVERY_A_RUN_ID
        and isinstance(hk, dict)
        and hk.get("market") == "HK_CONNECT"
        and hk.get("status") == "CANNOT_CONFIRM"
        and hk.get("source_status") == "CANNOT_CONFIRM"
        and hk.get("selection_status") == "CANNOT_CONFIRM"
        and type(hk.get("selected_rows")) is int
        and hk.get("selected_rows") == 0
        and hk.get("write_performed") is False
        and hk.get("cannot_confirm") == [_HK_1300_1315_CUTOFF_RECOVERY_CAUSE]
    )


def _same_day_hk_1300_1315_recovery(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts
):
    if (
        mode != "RECOVERY"
        or trade_date != _HK_1300_1315_CUTOFF_RECOVERY_DATE
        or stage_id != _HK_1300_1315_CUTOFF_RECOVERY_STAGE
    ):
        return False
    if _same_day_hk_1300_1315_cutoff_recovery_shape(
        receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
        attempt_count=attempt_count, max_attempts=max_attempts,
    ):
        return True
    return (
        isinstance(receipt, dict)
        and receipt.get("trade_date") == trade_date
        and receipt.get("stage_id") == stage_id
        and receipt.get("node_id") == stage_id
        and receipt.get("dispatch_mode") == "RECOVERY"
        and type(attempt_count) is int
        and type(max_attempts) is int
        and _continued_hk_lane_recovery(
            receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
            attempt_count=attempt_count, max_attempts=max_attempts,
        )
    )


def _settled_partial_hk_cutoff_recovery_shape(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts
):
    """Recognize an unexhausted retry for the observed HK cutoff failure."""

    if mode != "RECOVERY" or not isinstance(receipt, dict):
        return False
    if (
        receipt.get("trade_date") != trade_date
        or receipt.get("stage_id") != stage_id
        or receipt.get("node_id") != stage_id
    ):
        return False
    if receipt.get("dispatch_mode") != "RECOVERY":
        return False
    if any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    if receipt.get("status") != "PARTIAL_WITH_ROWS":
        return False
    if receipt.get("node_outcome") != "SETTLED_PARTIAL":
        return False
    recorded_attempt_count = receipt.get("node_attempt_count")
    if (
        not isinstance(recorded_attempt_count, int)
        or isinstance(recorded_attempt_count, bool)
        or recorded_attempt_count != attempt_count
    ):
        return False
    # Reopen only after at least one attempt, while the original budget remains.
    if max_attempts <= 0 or not (0 < attempt_count < max_attempts):
        return False

    markets = receipt.get("markets")
    if not isinstance(markets, dict):
        return False
    hk = markets.get("HK_CONNECT")
    if not isinstance(hk, dict):
        return False
    cannot_confirm = hk.get("cannot_confirm")
    selected_rows = hk.get("selected_rows")
    return (
        hk.get("market") == "HK_CONNECT"
        and hk.get("status") == "CANNOT_CONFIRM"
        and hk.get("source_status") == "CANNOT_CONFIRM"
        and hk.get("selection_status") == "CANNOT_CONFIRM"
        and isinstance(selected_rows, int)
        and not isinstance(selected_rows, bool)
        and selected_rows == 0
        and hk.get("write_performed") is False
        and isinstance(cannot_confirm, (list, tuple))
        and len(cannot_confirm) == 1
        and "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in cannot_confirm
    )


def _same_day_hk_0930_0935_cutoff_recovery_shape(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts
):
    """Match a zero-row HK cutoff failure within the original retry budget."""

    if (
        mode != "RECOVERY"
        or stage_id != _HK_0930_0935_CUTOFF_RECOVERY_STAGE
        or not isinstance(receipt, dict)
        or type(attempt_count) is not int
        or type(max_attempts) is not int
        or not (0 < attempt_count < max_attempts)
        or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        return False
    required = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": trade_date,
        "stage_id": _HK_0930_0935_CUTOFF_RECOVERY_STAGE,
        "node_id": _HK_0930_0935_CUTOFF_RECOVERY_STAGE,
        "status": "PARTIAL_WITH_ROWS",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": attempt_count,
        "write_performed": True,
    }
    if type(receipt.get("node_attempt_count")) is not int or any(receipt.get(key) != value for key, value in required.items()):
        return False
    markets = receipt.get("markets")
    hk = markets.get("HK_CONNECT") if isinstance(markets, dict) else None
    return (
        isinstance(hk, dict)
        and hk.get("market") == "HK_CONNECT"
        and hk.get("status") == "CANNOT_CONFIRM"
        and hk.get("source_status") == "CANNOT_CONFIRM"
        and hk.get("selection_status") == "CANNOT_CONFIRM"
        and type(hk.get("selected_rows")) is int
        and hk.get("selected_rows") == 0
        and hk.get("write_performed") is False
        and "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in hk.get("cannot_confirm", ())
        and receipt.get("due_status") in {"DUE", "LATE_CATCHUP_REPLAY"}
        and receipt.get("dispatch_mode") in {"NATURAL", "RECOVERY"}
    )


def _continued_hk_0930_0935_recovery(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts
):
    if (
        mode != "RECOVERY"
        or trade_date != _HK_0930_0935_CUTOFF_RECOVERY_DATE
        or stage_id != _HK_0930_0935_CUTOFF_RECOVERY_STAGE
        or not isinstance(receipt, dict)
        or receipt.get("trade_date") != trade_date
        or receipt.get("stage_id") != stage_id
        or receipt.get("node_id") != stage_id
        or receipt.get("dispatch_mode") != "RECOVERY"
        or receipt.get("execution_origin") != "HK_ORIGINAL_BUDGET_RECOVERY"
        or receipt.get("execution_markets") != ["HK_CONNECT"]
        or type(attempt_count) is not int
        or type(max_attempts) is not int
        or type(receipt.get("node_attempt_count")) is not int
        or receipt["node_attempt_count"] != attempt_count
        or not (0 < attempt_count < max_attempts)
        or receipt.get("status") not in {"CANNOT_CONFIRM", "PARTIAL_COMMIT_RETRY_REQUIRED"}
        or receipt.get("node_outcome") != "TRANSIENT"
        or type(receipt.get("execution_pending")) is not bool
        or any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    ):
        return False

    markets = receipt.get("markets")
    hk = markets.get("HK_CONNECT") if isinstance(markets, dict) else None
    if not isinstance(hk, dict) or hk.get("market") != "HK_CONNECT":
        return False
    reasons = hk.get("cannot_confirm")
    if not isinstance(reasons, (list, tuple)) or any(
        not isinstance(reason, str) or reason not in _HK_0930_0935_CUTOFF_RECOVERY_REASONS
        for reason in reasons
    ):
        return False

    status = receipt.get("status")
    failed_layer = receipt.get("first_failed_layer")
    error = receipt.get("error")
    if status == "CANNOT_CONFIRM":
        if (
            receipt.get("write_performed") is not False
            or hk.get("status") != "CANNOT_CONFIRM"
            or hk.get("source_status") != "CANNOT_CONFIRM"
            or hk.get("selection_status") != "CANNOT_CONFIRM"
            or type(hk.get("selected_rows")) is not int
            or hk.get("selected_rows") != 0
            or hk.get("write_performed") is not False
        ):
            return False
        known_source_failure = (
            failed_layer is None and error is None and bool(reasons)
            and (
                (receipt.get("execution_pending") is True
                 and receipt.get("partial_commit_possible") is True)
                or (receipt.get("execution_pending") is False
                    and receipt.get("partial_commit_possible") is not True)
            )
        )
        known_deadline_failure = (
            failed_layer == "END_TO_END_DEADLINE"
            and error in _HK_0930_0935_RECOVERY_DEADLINE_ERRORS
            and receipt.get("deadline_status") == "EXCEEDED"
            and receipt.get("partial_commit_possible") is False
            and bool(reasons)
        )
        return known_source_failure or known_deadline_failure

    return (
        failed_layer == "END_TO_END_DEADLINE"
        and error in _HK_0930_0935_RECOVERY_DEADLINE_ERRORS
        and receipt.get("deadline_status") == "EXCEEDED"
        and receipt.get("partial_commit_possible") is True
        and receipt.get("write_performed") is True
        and (not reasons or bool(set(reasons) & set(_HK_0930_0935_CUTOFF_RECOVERY_REASONS)))
    )


def _same_day_hk_0930_0935_recovery(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts
):
    return (
        _same_day_hk_0930_0935_cutoff_recovery_shape(
            receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
            attempt_count=attempt_count, max_attempts=max_attempts,
        )
        or _continued_hk_0930_0935_recovery(
            receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
            attempt_count=attempt_count, max_attempts=max_attempts,
        )
    )



def _continued_hk_lane_recovery(receipt, *, mode, trade_date, stage_id, attempt_count, max_attempts):
    return (
        mode == "RECOVERY" and isinstance(receipt, dict)
        and receipt.get("trade_date") == trade_date and receipt.get("stage_id") == stage_id
        and receipt.get("execution_origin") == "HK_ORIGINAL_BUDGET_RECOVERY"
        and receipt.get("execution_markets") == ["HK_CONNECT"]
        and type(receipt.get("node_attempt_count")) is int
        and receipt["node_attempt_count"] == attempt_count
        and 0 < attempt_count < max_attempts
        and receipt.get("status") in {"CANNOT_CONFIRM", "PARTIAL_COMMIT_RETRY_REQUIRED"}
        and all(receipt.get(k) is False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
    )


def _automatic_review_failure(receipt_root, trade_date, stage_id, receipt_sha256, reason):
    """Persist bounded sidecar diagnostics without changing the owner receipt."""
    if not receipt_root or not receipt_sha256:
        return
    try:
        import json
        from infrastructure.owned_io import SafeRoot
        relative = f"independent_execution_reviews/rejections/{trade_date}/{stage_id}/{receipt_sha256}.json"
        raw = json.dumps({
            "schema_version": "stage_center.automatic_execution_review_rejection.v1",
            "trade_date": trade_date, "stage_id": stage_id,
            "expected_receipt_sha256": receipt_sha256,
            "reviewer_identity_or_role": "AUTOMATED_INDEPENDENT_EXECUTION_VERIFIER",
            "reason": reason[:240],
        }, sort_keys=True, separators=(",", ":")).encode()
        SafeRoot(receipt_root).write_bytes(relative, raw, require_absent=True)
    except (OSError, ValueError):
        return


def _maybe_publish_automatic_execution_review(
    _v4_scope, /, runner, trade_date, stage_id, *, mode, persisted,
):
    """Run the independent readback once, after a completed natural HK receipt."""
    if (
        mode != "NATURAL"
        or not isinstance(persisted, dict)
        or persisted.get("dispatch_mode") != "NATURAL"
        or persisted.get("due_status") != "DUE"
        or persisted.get("mode") == "BACKFILL"
        or persisted.get("execution_origin") not in (None, "NATURAL")
        or persisted.get("same_day_late_observation_recovery") is True
        or not isinstance(persisted.get("markets"), dict)
        or not isinstance(persisted["markets"].get("HK_CONNECT"), dict)
        or "HK_CONNECT" not in _v4_global(_v4_scope, "STAGE_BY_ID")[stage_id].markets
    ):
        return
    if persisted["markets"]["HK_CONNECT"].get("selection_mode") == "BACKFILL":
        return
    runner_config = getattr(runner, "config", None)
    if runner_config is None:
        return
    receipt_sha256 = None
    receipt_root = getattr(runner_config, "receipt_root", None)
    try:
        receipt_path = runner._receipt_path(trade_date, stage_id)
        receipt_raw = _v4_global(_v4_scope, "Path")(receipt_path).read_bytes()
        receipt_sha256 = _stage_hashlib.sha256(receipt_raw).hexdigest()
        roots = {
            "root": getattr(runner_config, "receipt_root", None),
            "raw_root": getattr(runner_config, "raw_root", None),
            "selection_root": getattr(runner_config, "selection_root", None),
        }
        if any(value is None for value in roots.values()):
            _automatic_review_failure(receipt_root, trade_date, stage_id, receipt_sha256, "SIDECAR_CONFIGURED_ROOT_MISSING")
            return
        if getattr(runner_config, "hk_d1_root", None) is None:
            _automatic_review_failure(receipt_root, trade_date, stage_id, receipt_sha256, "SIDECAR_CONFIGURED_HK_D1_ROOT_MISSING")
            return
        facade_path = _v4_global(_v4_scope, "Path")(_v4_global(_v4_scope, "__file__")).resolve()
        verifier_path = facade_path.parent / "verify_stage_execution.py"
        command = [
            sys.executable,
            str(verifier_path),
            "--date", trade_date,
            "--stage", stage_id,
            "--root", str(roots["root"]),
            "--raw-root", str(roots["raw_root"]),
            "--selection-root", str(roots["selection_root"]),
            "--expected-receipt-sha256", receipt_sha256,
            "--hk-d1-root", str(runner_config.hk_d1_root),
        ]
        for argument, field in (("--preselection-source-root", "preselection_source_root"),
                                ("--hk-second-filter-root", "hk_second_filter_root"),
                                ("--shared-research-root", "v4_morning_news_root")):
            if getattr(runner_config, field, None) is not None:
                command.extend((argument, str(getattr(runner_config, field))))
        completed = subprocess.run(
            command, cwd=str(facade_path.parent.parent), check=False,
            capture_output=True, text=True, timeout=30,
        )
        if completed.returncode != 0:
            _automatic_review_failure(receipt_root, trade_date, stage_id, receipt_sha256, f"SIDECAR_EXIT_NONZERO:{completed.returncode}")
    except subprocess.TimeoutExpired:
        _automatic_review_failure(receipt_root, trade_date, stage_id, receipt_sha256, "SIDECAR_TIMEOUT")
    except Exception as exc:
        _automatic_review_failure(receipt_root, trade_date, stage_id, receipt_sha256, "SIDECAR_STARTUP_OR_WAIT_ERROR:" + type(exc).__name__)
        # Review publication is a nonfatal readback sidecar.  The already
        # completed selection receipt remains the dispatch result.
        return


def __dispatch_stage_body(_v4_scope, /, config, trade_date, stage_id, evaluated_at, *, mode, runner, precaptures):
    """Run exactly one stage under the runner's existing per-stage lock."""

    if stage_id not in _v4_global(_v4_scope, 'STAGE_BY_ID'):
        raise _v4_global(_v4_scope, 'ValueError')(f"unknown stage node {stage_id!r}")
    gate = _v4_global(_v4_scope, '_calendar_gate')(trade_date, markets=_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets)
    if gate["status"] != "ELIGIBLE":
        return {**gate, "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode}
    runner = runner or _v4_global(_v4_scope, '_build_runner')(config)
    max_attempts = _v4_global(_v4_scope, '_config_int')(config, "node_max_attempts", _v4_global(_v4_scope, 'DEFAULT_MAX_ATTEMPTS'))
    retry_backoff = _v4_global(_v4_scope, '_config_float')(
        config, "node_retry_backoff_seconds", _v4_global(_v4_scope, 'DEFAULT_RETRY_BACKOFF_SECONDS')
    )
    receipt = _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id)
    attempt_count = _v4_global(_v4_scope, '_node_attempt_count')(receipt)
    existing_status = _v4_global(_v4_scope, 'str')((receipt or {}).get("status") or "")
    # The inner runner may replace receipt.json before it exits. This immutable
    # reservation survives that write and prevents a crash from reopening retries.
    rearm_marker = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id).parent / "dependency_rearm.json"
    if rearm_marker.exists() and not _v4_global(_v4_scope, '_stage_settled')(receipt):
        attempt_count = _v4_global(_v4_scope, 'max')(attempt_count, max_attempts + 1)
        existing_status = "CANNOT_CONFIRM"
    futu_1445_receipt_sha256, futu_1445_dataset_sha256 = _frozen_hk_futu_1445_hashes(
        config, trade_date, stage_id, mode
    )
    same_day_futu_1445_recovery = (
        not rearm_marker.exists()
        and _same_day_hk_1445_futu_recovery_shape(
            receipt,
            mode=mode,
            trade_date=trade_date,
            stage_id=stage_id,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            receipt_sha256=futu_1445_receipt_sha256,
            dataset_sha256=futu_1445_dataset_sha256,
        )
    )
    futu_1300_receipt_sha256, futu_1300_dataset_sha256 = _frozen_hk_futu_1300_hashes(
        config, trade_date, stage_id, mode
    )
    futu_1300_marker = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id).parent / _HK_FUTU_1300_CONSUMPTION_MARKER
    if (
        trade_date == _HK_FUTU_1300_RECOVERY_DATE
        and stage_id == _HK_FUTU_1300_RECOVERY_STAGE
        and (futu_1300_marker.exists() or futu_1300_marker.is_symlink())
    ):
        return {
            "status": "SKIPPED_FUTU_RECOVERY_CONSUMED",
            "trade_date": trade_date,
            "stage_id": stage_id,
            "node_id": stage_id,
            "dispatch_mode": mode,
            "node_attempt_count": attempt_count,
            "retry_exhausted": True,
            "write_performed": False,
            "first_failed_layer": "FUTU_AFTERFACT_ONE_TIME_ALLOWANCE_ALREADY_CONSUMED",
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    same_day_futu_1300_recovery = _same_day_hk_1300_futu_recovery_shape(
        receipt,
        mode=mode,
        trade_date=trade_date,
        stage_id=stage_id,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        receipt_sha256=futu_1300_receipt_sha256,
        dataset_sha256=futu_1300_dataset_sha256,
    )
    from .node_entry import _a_0925_repair_authority, _ISSUE11_MARKER
    repair = None
    a_lane_recovery = _a_0925_original_budget_recovery(
        _v4_scope, config, receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
        evaluated_at=evaluated_at, attempt_count=attempt_count, max_attempts=max_attempts,
    )
    if (stage_id == "STAGE_0925" and isinstance(receipt, dict)
            and receipt.get("execution_origin") == "A_ORIGINAL_BUDGET_RECOVERY"
            and existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES')
            and not a_lane_recovery):
        return {"status": "SKIPPED_RETRY_EXHAUSTED" if attempt_count >= max_attempts else "CANNOT_CONFIRM",
            "stage_id": stage_id, "trade_date": trade_date, "node_attempt_count": attempt_count,
            "retry_exhausted": attempt_count >= max_attempts,
            "first_failed_layer": "A_0925_RECOVERY_CONTINUATION_INVALID_OR_EXHAUSTED",
            "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
    repair_marker = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id).parent / _ISSUE11_MARKER
    if trade_date == "20260930" and stage_id == "STAGE_0925" and (repair_marker.exists() or repair_marker.is_symlink()):
        return {"status": "SKIPPED_REPAIR_RECOVERY_CONSUMED", "trade_date": trade_date,
                "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode,
                "node_attempt_count": 4, "retry_exhausted": True, "write_performed": False,
                "first_failed_layer": "ISSUE11_RECOVERY_ALLOWANCE_ALREADY_CONSUMED",
                **_v4_global(_v4_scope, '_safe_flags')()}
    hk_lane_recovery = (
        stage_id == "STAGE_0925" and (
            _settled_partial_hk_cutoff_recovery_shape(
                receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
                attempt_count=attempt_count, max_attempts=max_attempts)
            or _continued_hk_lane_recovery(
                receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
                attempt_count=attempt_count, max_attempts=max_attempts)
        )
    ) or _same_day_hk_0930_0935_recovery(
        receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
        attempt_count=attempt_count, max_attempts=max_attempts,
    ) or _same_day_hk_1300_1315_recovery(
        receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
        attempt_count=attempt_count, max_attempts=max_attempts,
    ) or same_day_futu_1445_recovery or same_day_futu_1300_recovery
    if (
        (
            trade_date == _HK_0930_0935_CUTOFF_RECOVERY_DATE
            and stage_id == _HK_0930_0935_CUTOFF_RECOVERY_STAGE
            or trade_date == _HK_1300_1315_CUTOFF_RECOVERY_DATE
            and stage_id == _HK_1300_1315_CUTOFF_RECOVERY_STAGE
        )
        and existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES')
        and isinstance(receipt, dict)
        and ("execution_origin" in receipt or "execution_markets" in receipt)
        and not hk_lane_recovery
    ):
        return {"status": "CANNOT_CONFIRM", "trade_date": trade_date,
                "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode,
                "node_attempt_count": attempt_count,
                "first_failed_layer": "HK_RECOVERY_CONTINUATION_RECEIPT_INVALID",
                "write_performed": False, "recovery_rejected": True,
                **_v4_global(_v4_scope, '_safe_flags')()}
    if hk_lane_recovery:
        wall = _v4_global(_v4_scope, '_rearm_wall_now')()
        safety = config.get("safety")
        if (evaluated_at.tzinfo is None or wall.tzinfo is None
                or _v4_global(_v4_scope, '_as_shanghai')(wall).strftime("%Y%m%d") != trade_date
                or _v4_global(_v4_scope, '_as_shanghai')(evaluated_at).strftime("%Y%m%d") != trade_date
                or evaluated_at > wall or not isinstance(safety, dict)
                or any(safety.get(k) is not False for k in
                       ("production_allowed", "buy_gate_updated", "orders_sent"))):
            return {"status": "CANNOT_CONFIRM", "trade_date": trade_date,
                    "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode,
                    "first_failed_layer": "HK_RECOVERY_SCOPE_UNSAFE", "write_performed": False,
                    **_v4_global(_v4_scope, '_safe_flags')()}
    if (hk_lane_recovery and not same_day_futu_1300_recovery
            and existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES')
            and not _v4_global(_v4_scope, '_retry_is_due')(
                receipt, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at),
                retry_backoff_seconds=retry_backoff)):
        return {"status": "SKIPPED_RETRY_BACKOFF", "trade_date": trade_date,
                "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode,
                "node_outcome": "TRANSIENT", "node_attempt_count": attempt_count,
                "retry_after": (receipt or {}).get("retry_after"), "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')()}
    settled_recovery_decision = None
    if a_lane_recovery:
        # Settled partials predate retry metadata; their owner write clock is
        # the original attempt clock. Keep the existing backoff calculation.
        retry_receipt = dict(receipt)
        retry_receipt.setdefault("attempted_at", receipt.get("recorded_at"))
        if not _v4_global(_v4_scope, '_retry_is_due')(
                retry_receipt, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at),
                retry_backoff_seconds=retry_backoff):
            return {"status": "SKIPPED_RETRY_BACKOFF", "trade_date": trade_date,
                "stage_id": stage_id, "node_attempt_count": attempt_count,
                "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
    if _v4_global(_v4_scope, '_stage_settled')(receipt) and existing_status not in _v4_global(_v4_scope, 'TRANSIENT_STATUSES'):
        if (
            _settled_partial_hk_cutoff_recovery_shape(
                receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
                attempt_count=attempt_count, max_attempts=max_attempts,
            )
            or _same_day_hk_0930_0935_cutoff_recovery_shape(
                receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
                attempt_count=attempt_count, max_attempts=max_attempts,
            )
            or _same_day_hk_1300_1315_cutoff_recovery_shape(
                receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
                attempt_count=attempt_count, max_attempts=max_attempts,
            )
            or same_day_futu_1445_recovery or a_lane_recovery
        ):
            settled_recovery_decision = _v4_global(_v4_scope, 'next')(
                (
                    item
                    for item in runner.due_decisions(
                        trade_date,
                        _v4_global(_v4_scope, '_as_shanghai')(evaluated_at),
                        historical_backfill=False,
                    )
                    if item.stage_id == stage_id
                ),
                None,
            )
        settled_recovery_is_due = (
            settled_recovery_decision is not None
            and getattr(settled_recovery_decision, "stage_id", None) == stage_id
            and _same_day_late_observation_recovery(
                _v4_scope,
                mode=mode,
                trade_date=trade_date,
                evaluated_at=evaluated_at,
                decision=settled_recovery_decision,
            )
        )
        if not settled_recovery_is_due:
            return {
                "status": "SKIPPED_ALREADY_SETTLED",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": (receipt or {}).get("node_outcome", "SETTLED"),
                "node_attempt_count": attempt_count,
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
    # An explicit repair request cannot fall back to the ordinary first-attempt
    # path when its frozen failed receipt is absent, malformed or not transient.
    if ("a_0925_recovery_authorization" in config
            and not hk_lane_recovery
            and existing_status not in _v4_global(_v4_scope, 'TRANSIENT_STATUSES')):
        return {"status": "CANNOT_CONFIRM", "trade_date": trade_date,
                "first_failed_layer": "ISSUE11_REPAIR_AUTHORITY_MISSING",
                "stage_id": stage_id, "node_id": stage_id, "dispatch_mode": mode,
                "node_attempt_count": attempt_count, "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')()}
    rearm = None
    if existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES') and not hk_lane_recovery and not a_lane_recovery:
        if attempt_count >= max_attempts:
            if "a_0925_recovery_authorization" in config:
                repair = _a_0925_repair_authority(_v4_scope, config, trade_date, stage_id, receipt, evaluated_at, mode)
            else:
                rearm = _v4_global(_v4_scope, '_exact_hk_d1_dependency_rearm')(config, trade_date, receipt, evaluated_at)
        if (attempt_count >= max_attempts or "a_0925_recovery_authorization" in config) and rearm is None and repair is None:
            previous = receipt or {}
            return {
                "status": "SKIPPED_RETRY_EXHAUSTED",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT_EXHAUSTED",
                "node_attempt_count": attempt_count,
                "retry_exhausted": True,
                "first_failed_layer": (
                    previous.get("first_failed_layer")
                    or previous.get("blocked_layer")
                    or "STAGE_RETRY_BUDGET_EXHAUSTED"
                ),
                "error": previous.get("error"),
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
        if rearm is None and repair is None and not _v4_global(_v4_scope, '_retry_is_due')(
            receipt,
            _v4_global(_v4_scope, '_as_shanghai')(evaluated_at),
            retry_backoff_seconds=retry_backoff,
        ):
            return {
                "status": "SKIPPED_RETRY_BACKOFF",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "node_outcome": "TRANSIENT",
                "node_attempt_count": attempt_count,
                "retry_after": (receipt or {}).get("retry_after"),
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }

    from stage_center.runner import SlotLock, _slot_lock_path

    decision = settled_recovery_decision or _v4_global(_v4_scope, 'next')(
        item
        for item in runner.due_decisions(
            trade_date, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at), historical_backfill=False
        )
        if item.stage_id == stage_id
    )
    if decision.status not in {"DUE", "LATE_CATCHUP_REPLAY"}:
        return {
            "status": decision.status,
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    decision.same_day_late_observation_recovery = _same_day_late_observation_recovery(
        _v4_scope,
        mode=mode,
        trade_date=trade_date,
        evaluated_at=evaluated_at,
        decision=decision,
        stage_id=stage_id,
    )

    lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
    _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRE_START", trade_date=trade_date, stage_id=stage_id)
    if not lock.acquire():
        return {
            "status": "SKIPPED_SLOT_LOCKED",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    try:
        _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRED", trade_date=trade_date, stage_id=stage_id)
        # Recheck after acquiring the original lock; never overwrite a newer run.
        if _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id) != receipt:
            return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                    "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
        if a_lane_recovery and not _a_0925_original_budget_recovery(
                _v4_scope, config, receipt, mode=mode, trade_date=trade_date, stage_id=stage_id,
                evaluated_at=evaluated_at, attempt_count=attempt_count, max_attempts=max_attempts):
            return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
        if same_day_futu_1445_recovery:
            locked_receipt_sha256, locked_dataset_sha256 = _frozen_hk_futu_1445_hashes(
                config, trade_date, stage_id, mode
            )
            if (
                rearm_marker.exists()
                or not _same_day_hk_1445_futu_recovery_shape(
                    receipt,
                    mode=mode,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    attempt_count=attempt_count,
                    max_attempts=max_attempts,
                    receipt_sha256=locked_receipt_sha256,
                    dataset_sha256=locked_dataset_sha256,
                )
            ):
                return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False,
                        **_v4_global(_v4_scope, '_safe_flags')()}
        if same_day_futu_1300_recovery:
            locked_receipt_sha256, locked_dataset_sha256 = _frozen_hk_futu_1300_hashes(
                config, trade_date, stage_id, mode
            )
            if (
                futu_1300_marker.exists()
                or futu_1300_marker.is_symlink()
                or not _same_day_hk_1300_futu_recovery_shape(
                    receipt,
                    mode=mode,
                    trade_date=trade_date,
                    stage_id=stage_id,
                    attempt_count=attempt_count,
                    max_attempts=max_attempts,
                    receipt_sha256=locked_receipt_sha256,
                    dataset_sha256=locked_dataset_sha256,
                )
            ):
                return {"status": "SKIPPED_FUTU_RECOVERY_IDENTITY_CHANGED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False,
                        **_v4_global(_v4_scope, '_safe_flags')()}
            from infrastructure.owned_io import SafeRoot
            grant = {
                "schema_version": "stage_center.futu_afterfact_one_time.v1",
                "trade_date": _HK_FUTU_1300_RECOVERY_DATE,
                "stage_id": _HK_FUTU_1300_RECOVERY_STAGE,
                "source_id": "futu_rt_data_afterfact",
                "original_receipt_sha256": _HK_FUTU_1300_PRIOR_RECEIPT_SHA256,
                "dataset_sha256": _HK_FUTU_1300_DATASET_SHA256,
                "consumed_before_runner": True,
                "consumed_attempt_number": attempt_count + 1,
                "consumed_at": _v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
            raw_grant = (_v4_global(_v4_scope, 'json').dumps(
                grant, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ) + "\n").encode()
            try:
                SafeRoot(futu_1300_marker.parent).write_bytes(
                    _HK_FUTU_1300_CONSUMPTION_MARKER,
                    raw_grant,
                    require_absent=True,
                )
            except FileExistsError:
                return {"status": "SKIPPED_FUTU_RECOVERY_CONSUMED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False,
                        "first_failed_layer": "FUTU_AFTERFACT_ONE_TIME_ALLOWANCE_ALREADY_CONSUMED",
                        **_v4_global(_v4_scope, '_safe_flags')()}
        if repair is not None:
            from infrastructure.owned_io import SafeRoot
            refreshed = _a_0925_repair_authority(_v4_scope, config, trade_date, stage_id, receipt, evaluated_at, mode)
            if refreshed is None:
                return {"status": "CANNOT_CONFIRM", "stage_id": stage_id,
                        "first_failed_layer": "ISSUE11_REPAIR_AUTHORITY_CHANGED",
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
            # Revalidation is under the original slot lock. Persist old bytes
            # and the consumed one-shot grant atomically BEFORE any runner call.
            repair = refreshed
            raw = (_v4_global(_v4_scope, 'json').dumps(repair, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":"), allow_nan=False) + "\n").encode()
            try:
                SafeRoot(repair_marker.parent).write_bytes(_ISSUE11_MARKER, raw, require_absent=True)
            except FileExistsError:
                return {"status": "SKIPPED_REPAIR_RECOVERY_CONSUMED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
        if rearm is not None:
            rearm = _v4_global(_v4_scope, '_exact_hk_d1_dependency_rearm')(config, trade_date, receipt, evaluated_at)
            if rearm is None:
                return {"status": "SKIPPED_DEPENDENCY_NOT_READY", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
            rearm_marker.parent.mkdir(parents=True, exist_ok=True)
            try:
                with rearm_marker.open("x", encoding="utf-8") as stream:
                    _v4_global(_v4_scope, 'json').dump({"schema_version": "stage_center.dependency_rearm.v1",
                               "trade_date": trade_date, "stage_id": stage_id,
                               **rearm, **_v4_global(_v4_scope, '_safe_flags')()}, stream, sort_keys=True)
                    stream.flush()
                    _v4_global(_v4_scope, 'os').fsync(stream.fileno())
            except _v4_global(_v4_scope, 'FileExistsError'):
                return {"status": "SKIPPED_RECEIPT_CHANGED", "stage_id": stage_id,
                        "trade_date": trade_date, "write_performed": False, **_v4_global(_v4_scope, '_safe_flags')()}
            runner._write_receipt({**(receipt or {}), **rearm}, trade_date, stage_id)
        if hk_lane_recovery or repair is not None or a_lane_recovery:
            from stage_center._runner_parts.runner_receipts import scoped_recovery_runner
            runner = scoped_recovery_runner(
                runner, markets=("HK_CONNECT",) if hk_lane_recovery else ("A_SHARE",),
                prior_receipt=receipt, attempt_count=attempt_count + 1,
                origin=("HK_ORIGINAL_BUDGET_RECOVERY" if hk_lane_recovery else
                    "A_ORIGINAL_BUDGET_RECOVERY" if a_lane_recovery else "A_REPAIR_RECOVERY"),
            )
            # Reserve the SAME shared stage counter before any collector or
            # inner receipt write; a crash must not reopen original budget.
            runner._write_receipt({**receipt, "status": "CANNOT_CONFIRM", "node_outcome": "TRANSIENT",
                "node_attempt_count": attempt_count + 1,
                "retry_exhausted": attempt_count + 1 >= max_attempts,
                "dispatch_mode": mode,
                "attempted_at": _v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
                "retry_after": (_v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
                    + _v4_global(_v4_scope, 'timedelta')(seconds=retry_backoff)).isoformat(),
                "execution_pending": True, "partial_commit_possible": True,
                "write_performed": False}, trade_date, stage_id)
        # Stage-8 pre-capture is scheduled at 15:50 and, when a launch lands
        # exactly on 15:55:00, may be retried once more before the 15:55:05
        # consumer cutoff.  Never invoke it after the immutable window.
        captured = _v4_global(_v4_scope, 'list')(precaptures or ())
        attempt_count += 1
        _v4_global(_v4_scope, '_deadline').due(
            decision.scheduled_at,
            trade_date=trade_date,
            stage_id=stage_id,
            due_status=decision.status,
            dispatch_mode=mode,
        )
        _v4_global(_v4_scope, '_deadline').checkpoint("BUSINESS_START", trade_date=trade_date, stage_id=stage_id)
        # Diagnostics only; slot lock, attempt budget and cutoff policy are unchanged.
        from stage_center.attempt_evidence import capture_attempt
        with capture_attempt(
            runner._receipt_path(trade_date, stage_id).parent,
            trade_date=trade_date, stage_id=stage_id, attempt_number=attempt_count,
            evaluated_at=_v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
            due_status=decision.status,
        ) as attempt_journal:
            try:
                result = _v4_global(_v4_scope, 'dict')(runner._run_one(decision))
            except Exception as error:
                scope = getattr(runner, "_execution_scope", None)
                if scope is None:
                    raise
                # Preserve completed sibling results on unexpected builder,
                # provider or store errors as well as the runner's known errors.
                result = runner._write_receipt({
                    "status": "CANNOT_CONFIRM", "trade_date": trade_date, "stage_id": stage_id,
                    "error": f"{type(error).__name__}:{error}",
                    "first_failed_layer": "SCOPED_EXECUTION",
                    "markets": {market: {"status": "CANNOT_CONFIRM", "selection_status": "CANNOT_CONFIRM",
                        "selected_rows": 0, "cannot_confirm": [f"{type(error).__name__}:{error}"],
                        "write_performed": False} for market in scope.markets},
                    "write_performed": False,
                }, trade_date, stage_id)
            result = _clear_stale_scoped_recovery_failure(
                receipt or {}, result,
                origin="HK_ORIGINAL_BUDGET_RECOVERY" if hk_lane_recovery else "A_REPAIR_RECOVERY",
            )
            attempt_journal.finish(result)
        result["attempt_diagnostic"] = attempt_journal.summary()
        _v4_global(_v4_scope, '_deadline').event("BUSINESS_RETURN", status=result.get("status"))
        result.update(
            {
                "node_id": stage_id,
                "dispatch_mode": mode,
                "node_attempt_count": attempt_count,
                "pre_captures": captured,
            }
        )
        # Preserve consumed re-arm metadata across both success and failure.
        result.update({k: v for k, v in (receipt or {}).items()
                       if k.startswith("dependency_rearm_")})
        if rearm is not None:
            result.update(rearm)
        if repair is not None:
            result.update(repair_recovery_original_attempt_count=3, repair_recovery_attempt_count=1,
                          repair_recovery_authorization_sha256=repair["authorization_sha256"],
                          repair_recovery_original_receipt_sha256=repair["original_receipt_sha256"],
                          repair_recovery_marker=_ISSUE11_MARKER,
                          result_origin="CODE_REPAIR_RECOVERY", real_time_success=False,
                          evidence_limit=repair["evidence_limit"])
        if a_lane_recovery:
            result.update(result_origin="CODE_REPAIR_RECOVERY", real_time_success=False,
                attempted_at=_v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
                evidence_limit="PYTDX_0925_HISTORY_TRANSACTION_L0_WATCH_ONLY_RECOVERY")
        if same_day_futu_1300_recovery:
            result.update(
                futu_afterfact_authorization_consumed=True,
                futu_afterfact_original_receipt_sha256=_HK_FUTU_1300_PRIOR_RECEIPT_SHA256,
                futu_afterfact_dataset_sha256=_HK_FUTU_1300_DATASET_SHA256,
                futu_afterfact_consumption_marker=_HK_FUTU_1300_CONSUMPTION_MARKER,
            )
        hk_result = (result.get("markets") or {}).get("HK_CONNECT")
        hk_evidence = hk_result.get("source_evidence", ()) if isinstance(hk_result, dict) else ()
        if (
            "futu_observation_contract=HK_FUTU_RTDATA_AFTERFACT_RESEARCH_20261012_R1" in hk_evidence
            and "futu_afterfact_temporal_cutoff_safe=false" in hk_evidence
        ):
            result.update(
                temporal_cutoff_safe=False,
                execution_verified=False,
                selection_action_boundary="NO_BUY",
            )
        status = _v4_global(_v4_scope, 'str')(result.get("status") or "CANNOT_CONFIRM")
        if status == "PARTIAL_WITH_ROWS" and result.get("write_performed") is False:
            # A partial status without a committed write is not a valid
            # settled partial.  Reclassify it into the bounded retry lane.
            result["status"] = status = "CANNOT_CONFIRM"
            result.setdefault("blocked_layer", "PARTIAL_STAGE_WITHOUT_WRITE")
        outcome = _v4_global(_v4_scope, '_node_outcome')(status, result)
        result["node_outcome"] = outcome
        result["retry_exhausted"] = _v4_global(_v4_scope, 'bool')(
            outcome == "TRANSIENT" and attempt_count >= max_attempts
        )
        if outcome == "TRANSIENT" and not result["retry_exhausted"]:
            result["retry_after"] = (
                _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
                + _v4_global(_v4_scope, 'timedelta')(seconds=retry_backoff)
            ).isoformat()
        else:
            result.pop("retry_after", None)
        # _record_dispatch_metadata is the existing receipt writer and keeps
        # the base runner's schema and safety flags.  The final write adds the
        # node cap metadata atomically through the same per-stage lock.
        persisted = runner._write_receipt(result, trade_date, stage_id)
        persisted = _v4_global(_v4_scope, '_deadline').complete_receipt(
            runner._receipt_path(trade_date, stage_id),
            persisted,
            rewrite=lambda failed: runner._write_receipt(failed, trade_date, stage_id),
        )
        # The sidecar reads only completed artifacts after releasing the slot lock.
        lock.release()
        _maybe_publish_automatic_execution_review(
            _v4_scope, runner, trade_date, stage_id, mode=mode, persisted=persisted,
        )
        return persisted
    finally:
        lock.release()
