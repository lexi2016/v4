"""ops.run_stage_center_nodes: stage_dispatch (review candidate, not deployment)."""
from __future__ import annotations
import hashlib
import hashlib as _stage_hashlib
import os
from pathlib import Path
from ._namespace import read_global as _v4_global


_SETTLED_HK_RECOVERY_AUTH_ID = "hk-stage-20261002-1445-1500-r2"
_SETTLED_HK_RECOVERY_INCIDENT = {
    "schema_version": "stage_center.settled_hk_recovery_authorization.v1",
    "authorization_id": _SETTLED_HK_RECOVERY_AUTH_ID,
    "trade_date": "20261002",
    "stage_id": "STAGE_1445_1500",
    "mode": "RECOVERY",
    "prior_receipt_sha256": "b2f4e758f7480c668904e40b6a71181ebc8e19a3916e76f215c4c812fe303a23",
    "prior_node_attempt_count": 2,
    "max_attempts": 3,
    "reserved_node_attempt_count": 3,
    "stale_candidate_current_sha256": "f45233cd1d30d04a8e89c3a08ba8dab4ff63f1d787809b3323307f6f96cb5901",
    "stale_candidate_run_id": "hk-d1-20260930-f45233cd1d30d04a",
    "corrected_pool_id": "hkconnect_d1_top100",
    "corrected_candidate_artifact_sha256": "9486b32cd8290994e1bf82cd15863fb7d0c00100bd52f1f6eb5d03af80b72077",
    "target_date": "20261002",
    "source_date": "20260930",
    "row_count": 100,
    "unique_code_count": 100,
    "execution_limit": 1,
}

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


def _same_day_hk_0930_0935_cutoff_recovery_shape(
    receipt, /, *, mode, trade_date, stage_id, attempt_count, max_attempts
):
    """Match only the original 2026-10-12 zero-HK cutoff failure."""
    if (
        mode != "RECOVERY"
        or trade_date != _HK_0930_0935_CUTOFF_RECOVERY_DATE
        or stage_id != _HK_0930_0935_CUTOFF_RECOVERY_STAGE
        or not isinstance(receipt, dict)
        or type(attempt_count) is not int
        or type(max_attempts) is not int
        or not (0 < attempt_count < max_attempts)
    ):
        return False
    if any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    required = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": _HK_0930_0935_CUTOFF_RECOVERY_DATE,
        "stage_id": _HK_0930_0935_CUTOFF_RECOVERY_STAGE,
        "node_id": _HK_0930_0935_CUTOFF_RECOVERY_STAGE,
        "status": "PARTIAL_WITH_ROWS",
        "due_status": "DUE",
        "dispatch_mode": "NATURAL",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": attempt_count,
        "write_performed": True,
    }
    if any(receipt.get(key) != expected for key, expected in required.items()):
        return False
    if type(receipt.get("node_attempt_count")) is not int:
        return False
    markets = receipt.get("markets")
    hk = markets.get("HK_CONNECT") if isinstance(markets, dict) else None
    return (
        isinstance(hk, dict)
        and hk.get("status") == "CANNOT_CONFIRM"
        and hk.get("source_status") == "CANNOT_CONFIRM"
        and hk.get("selection_status") == "CANNOT_CONFIRM"
        and type(hk.get("selected_rows")) is int
        and hk.get("selected_rows") == 0
        and hk.get("write_performed") is False
        and hk.get("cannot_confirm") == _HK_0930_0935_CUTOFF_RECOVERY_REASONS
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



_HK_FUTU_1445_RECOVERY_DATE = "20261012"
_HK_FUTU_1445_RECOVERY_STAGE = "STAGE_1445_1500"
_HK_FUTU_1445_PRIOR_RECEIPT_SHA256 = "907f00b0c7b2280315cc642c37fc71360fdfcc9d3949374c0c183c7ab7cc837f"
_HK_FUTU_1445_DATASET_SHA256 = "4a310b4920dc5c6ebb7ac8b9f50d1e73d2dcb4d0ef685fef329358c09c2223d0"
_HK_FUTU_1300_RECOVERY_DATE = "20261012"
_HK_FUTU_1300_RECOVERY_STAGE = "STAGE_1300_1315"
_HK_FUTU_1300_PRIOR_RECEIPT_SHA256 = "1e7a2fe0b3236de35b79688af6c34b4b2798f16a8bd1e0d6bc0bcf9d7758d0d6"
_HK_FUTU_1300_DATASET_SHA256 = "63cba10b805b60dc7108ac7d633b0b1c32da2211b04fd976e1cd637ce083afe0"
_HK_FUTU_1300_CONSUMPTION_MARKER = "futu_afterfact_1300_once.json"


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


class _ScopedRecoveryExecution:
    """Merge one existing market lane into the original stage receipt."""

    def __init__(self, markets, prior, attempt_count, origin):
        from copy import deepcopy
        self.markets = tuple(markets)
        self.prior = deepcopy(prior)
        self.attempt_count = attempt_count
        self.origin = origin

    def merge(self, payload, trade_date, stage_id):
        from copy import deepcopy
        if trade_date != self.prior["trade_date"] or stage_id != self.prior["stage_id"]:
            raise ValueError("recovery receipt slot changed")
        result = {**deepcopy(self.prior), **deepcopy(payload)}
        old_markets = self.prior.get("markets") or {}
        new_markets = payload.get("markets") or {}
        result["markets"] = {
            **deepcopy(old_markets),
            **{market: deepcopy(new_markets[market]) for market in self.markets if market in new_markets},
        }
        result["node_attempt_count"] = self.attempt_count
        result["execution_pending"] = payload.get("execution_pending", False)
        result["execution_markets"] = list(self.markets)
        result["execution_origin"] = self.origin
        result["execution_status"] = payload.get("execution_status", payload.get("status", "CANNOT_CONFIRM"))
        for key, value in self.prior.items():
            if key.startswith(("repair_recovery_", "dependency_rearm_")):
                result[key] = deepcopy(value)
        if "A_SHARE" not in self.markets and "A_SHARE" in old_markets:
            for key in ("candidate_current_sha256", "candidate_run_id"):
                if key in self.prior:
                    result[key] = deepcopy(self.prior[key])
        if result.get("status") in {"READY", "READY_EMPTY", "NOOP_ALREADY_VERIFIED"}:
            states = {
                str(lane.get("selection_status", lane.get("status", "CANNOT_CONFIRM")))
                for lane in result["markets"].values()
            }
            if not states <= {"READY", "READY_EMPTY", "NOOP_ALREADY_VERIFIED"}:
                result["status"] = "PARTIAL_WITH_ROWS"
        return result


def scoped_recovery_runner(runner, *, markets, prior_receipt, attempt_count, origin):
    """Attach HK-only receipt merging to the same runner and stores."""
    from copy import copy
    import hashlib as _hashlib
    import json as _json
    from infrastructure.owned_io import SafeRoot

    if tuple(markets) not in {("A_SHARE",), ("HK_CONNECT",)}:
        raise ValueError("recovery requires one existing market lane")
    path = runner._receipt_path(prior_receipt["trade_date"], prior_receipt["stage_id"])
    io = SafeRoot(path.parent)
    raw = io.read_bytes(path.name)
    if _json.loads(raw) != prior_receipt:
        raise ValueError("recovery receipt changed before scoping")
    digest = _hashlib.sha256(raw).hexdigest()
    relative = f"attempt_evidence/preserved-{digest}/PRIOR_RECEIPT.json"
    try:
        io.write_bytes(relative, raw, require_absent=True)
    except FileExistsError:
        if io.read_bytes(relative) != raw:
            raise ValueError("preserved recovery receipt conflict")
    scoped = copy(runner)
    scope = _ScopedRecoveryExecution(markets, prior_receipt, attempt_count, origin)
    original_write_receipt = runner._write_receipt

    def write_scoped_receipt(payload, trade_date, stage_id):
        return original_write_receipt(scope.merge(payload, trade_date, stage_id), trade_date, stage_id)

    scoped._execution_scope = scope
    scoped._write_receipt = write_scoped_receipt
    return scoped


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


def _same_day_late_observation_recovery(_v4_scope, /, *, mode, trade_date, evaluated_at, decision):
    if mode != "RECOVERY" or getattr(decision, "status", None) != "LATE_CATCHUP_REPLAY":
        return False
    if getattr(decision, "trade_date", None) != trade_date:
        return False
    scheduled_at = getattr(decision, "scheduled_at", None)
    if scheduled_at is None:
        return False
    local_now = _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
    local_cutoff = _v4_global(_v4_scope, '_as_shanghai')(scheduled_at)
    return local_now.strftime("%Y%m%d") == trade_date and local_now > local_cutoff


def _settled_hk_recovery_result(_v4_scope, /, *, status, trade_date, stage_id, mode, attempt_count, reason):
    return {
        "status": status,
        "stage_id": stage_id,
        "node_id": stage_id,
        "trade_date": trade_date,
        "dispatch_mode": mode,
        "node_attempt_count": attempt_count,
        "first_failed_layer": reason,
        "write_performed": False,
        **_v4_global(_v4_scope, '_safe_flags')(),
    }


def _settled_hk_recovery_authorization(_v4_scope, /, path_value):
    path = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(path_value)).expanduser()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise _v4_global(_v4_scope, 'ValueError')("authorization must be an absolute regular file")
    if path.stat().st_size > 65536:
        raise _v4_global(_v4_scope, 'ValueError')("authorization file exceeds the bounded size")
    raw = path.read_bytes()
    payload = _v4_global(_v4_scope, 'json').loads(raw.decode("utf-8"))
    if not _v4_global(_v4_scope, 'isinstance')(payload, _v4_global(_v4_scope, 'dict')):
        raise _v4_global(_v4_scope, 'ValueError')("authorization must be a JSON object")
    if any(payload.get(key) != expected for key, expected in _SETTLED_HK_RECOVERY_INCIDENT.items()):
        raise _v4_global(_v4_scope, 'ValueError')("authorization incident binding mismatch")
    for key in ("prior_node_attempt_count", "max_attempts", "reserved_node_attempt_count", "row_count", "unique_code_count", "execution_limit"):
        if _v4_global(_v4_scope, 'type')(payload.get(key)) is not _v4_global(_v4_scope, 'int'):
            raise _v4_global(_v4_scope, 'ValueError')("authorization count fields must be integers")
    if payload.get("authorization_status") != "AUTHORIZED" or payload.get("review_status") != "APPROVED":
        raise _v4_global(_v4_scope, 'ValueError')("authorization is not approved for one-shot execution")
    authorized_by = payload.get("authorized_by")
    writer_id = payload.get("implementation_writer_id")
    reviewer_id = payload.get("independent_reviewer_id")
    if (not _v4_global(_v4_scope, 'isinstance')(authorized_by, _v4_global(_v4_scope, 'str'))
            or not authorized_by.strip()
            or not _v4_global(_v4_scope, 'isinstance')(writer_id, _v4_global(_v4_scope, 'str'))
            or not writer_id.strip()
            or not _v4_global(_v4_scope, 'isinstance')(reviewer_id, _v4_global(_v4_scope, 'str'))
            or not reviewer_id.strip()
            or len({authorized_by.strip(), writer_id.strip(), reviewer_id.strip()}) != 3
            or not _v4_global(_v4_scope, 'isinstance')(payload.get("approval_id"), _v4_global(_v4_scope, 'str'))
            or not payload.get("approval_id", "").strip()):
        raise _v4_global(_v4_scope, 'ValueError')("authorization approval identity is incomplete")
    for key in ("authorized_at", "independently_reviewed_at"):
        try:
            approved_at = _v4_global(_v4_scope, 'datetime').fromisoformat(payload.get(key, ""))
        except (_v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError')) as error:
            raise _v4_global(_v4_scope, 'ValueError')("authorization approval timestamp is invalid") from error
        if (approved_at.tzinfo is None
                or _v4_global(_v4_scope, '_as_shanghai')(approved_at).strftime("%Y%m%d") != _SETTLED_HK_RECOVERY_INCIDENT["trade_date"]):
            raise _v4_global(_v4_scope, 'ValueError')("authorization approval timestamp is outside the incident date")
    flags = payload.get("safety_flags")
    if (not _v4_global(_v4_scope, 'isinstance')(flags, _v4_global(_v4_scope, 'Mapping'))
            or any(flags.get(key) is not False for key in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise _v4_global(_v4_scope, 'ValueError')("authorization safety flags must remain false")
    digest = _stage_hashlib.sha256(raw).hexdigest()
    return payload, raw, digest


def _settled_hk_recovery_receipt_matches(_v4_scope, /, receipt):
    if not _v4_global(_v4_scope, 'isinstance')(receipt, _v4_global(_v4_scope, 'dict')):
        return False
    if any(receipt.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    required = {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": _SETTLED_HK_RECOVERY_INCIDENT["trade_date"],
        "stage_id": _SETTLED_HK_RECOVERY_INCIDENT["stage_id"],
        "node_id": _SETTLED_HK_RECOVERY_INCIDENT["stage_id"],
        "dispatch_mode": "RECOVERY",
        "status": "PARTIAL_WITH_ROWS",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": 2,
        "write_performed": True,
        "candidate_current_sha256": _SETTLED_HK_RECOVERY_INCIDENT["stale_candidate_current_sha256"],
        "candidate_run_id": _SETTLED_HK_RECOVERY_INCIDENT["stale_candidate_run_id"],
        "due_status": "LATE_CATCHUP_REPLAY",
    }
    if any(receipt.get(key) != expected for key, expected in required.items()):
        return False
    if _v4_global(_v4_scope, 'type')(receipt.get("node_attempt_count")) is not _v4_global(_v4_scope, 'int'):
        return False
    markets = receipt.get("markets")
    hk = markets.get("HK_CONNECT") if _v4_global(_v4_scope, 'isinstance')(markets, _v4_global(_v4_scope, 'Mapping')) else None
    return (
        _v4_global(_v4_scope, 'isinstance')(hk, _v4_global(_v4_scope, 'Mapping'))
        and hk.get("source_status") == "PARTIAL_WITH_ROWS"
        and hk.get("selection_status") == "PARTIAL_WITH_ROWS"
        and _v4_global(_v4_scope, 'type')(hk.get("selected_rows")) is _v4_global(_v4_scope, 'int')
        and hk.get("selected_rows") == 10
        and hk.get("cannot_confirm") == ["HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE"]
        and not any(hk.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
    )


def __dispatch_settled_hk_recovery_body(
    _v4_scope, /, config, trade_date, stage_id, evaluated_at, *, mode, runner,
    precaptures, observed_receipt, authorization_path, max_attempts,
):
    """Consume one exact, approved recovery authorization under the original slot lock."""
    from stage_center.runner import SlotLock, _slot_lock_path, _build_hk_stage_binding

    scope_reason = "SETTLED_HK_RECOVERY_SCOPE_MISMATCH"
    if (mode != "RECOVERY" or trade_date != _SETTLED_HK_RECOVERY_INCIDENT["trade_date"]
            or stage_id != _SETTLED_HK_RECOVERY_INCIDENT["stage_id"] or max_attempts != 3):
        return _settled_hk_recovery_result(
            _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
            mode=mode, attempt_count=_v4_global(_v4_scope, '_node_attempt_count')(observed_receipt), reason=scope_reason,
        )
    decision = _v4_global(_v4_scope, 'next')((
        item for item in runner.due_decisions(
            trade_date, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at), historical_backfill=False
        ) if item.stage_id == stage_id
    ), None)
    if decision is None:
        return _settled_hk_recovery_result(
            _v4_scope, status="SKIPPED_SETTLED_RECOVERY_NOT_DUE", trade_date=trade_date,
            stage_id=stage_id, mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_STAGE_NOT_DUE",
        )

    lock = SlotLock(_slot_lock_path(runner.config, trade_date, stage_id))
    _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRE_START", trade_date=trade_date, stage_id=stage_id)
    if not lock.acquire():
        return _settled_hk_recovery_result(
            _v4_scope, status="SKIPPED_SLOT_LOCKED", trade_date=trade_date, stage_id=stage_id,
            mode=mode, attempt_count=2, reason="STAGE_SLOT_LOCKED",
        )
    try:
        _v4_global(_v4_scope, '_deadline').checkpoint("LOCK_ACQUIRED", trade_date=trade_date, stage_id=stage_id)
        decision = _v4_global(_v4_scope, 'next')((
            item for item in runner.due_decisions(
                trade_date, _v4_global(_v4_scope, '_as_shanghai')(evaluated_at), historical_backfill=False
            ) if item.stage_id == stage_id
        ), None)
        if decision is None:
            return _settled_hk_recovery_result(
                _v4_scope, status="SKIPPED_SETTLED_RECOVERY_NOT_DUE", trade_date=trade_date,
                stage_id=stage_id, mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_STAGE_NOT_DUE",
            )
        receipt_path = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id)
        history_root = receipt_path.parent / "settled_hk_recovery_r2"
        history_dir = history_root / _SETTLED_HK_RECOVERY_AUTH_ID
        if history_root.is_symlink() or history_dir.exists() or history_dir.is_symlink():
            return _settled_hk_recovery_result(
                _v4_scope, status="SKIPPED_SETTLED_RECOVERY_ALREADY_CONSUMED", trade_date=trade_date,
                stage_id=stage_id, mode=mode, attempt_count=3, reason="SETTLED_HK_RECOVERY_ALREADY_CONSUMED",
            )

        try:
            authorization, authorization_raw, authorization_sha = _settled_hk_recovery_authorization(
                _v4_scope, authorization_path
            )
            now = _v4_global(_v4_scope, '_as_shanghai')(_v4_global(_v4_scope, '_rearm_wall_now')())
            authorized_at = _v4_global(_v4_scope, '_as_shanghai')(
                _v4_global(_v4_scope, 'datetime').fromisoformat(authorization["authorized_at"])
            )
            reviewed_at = _v4_global(_v4_scope, '_as_shanghai')(
                _v4_global(_v4_scope, 'datetime').fromisoformat(authorization["independently_reviewed_at"])
            )
            if reviewed_at > authorized_at or authorized_at > now or reviewed_at > now:
                raise _v4_global(_v4_scope, 'ValueError')("authorization approval timestamps are invalid")
            if receipt_path.is_symlink():
                raise _v4_global(_v4_scope, 'ValueError')("settled receipt must be a regular file")
            if _v4_global(_v4_scope, 'os').path.realpath(receipt_path.parent) != _v4_global(_v4_scope, 'os').path.realpath(
                    _v4_global(_v4_scope, 'Path')(config["receipt_root"]).expanduser() / trade_date / stage_id):
                raise _v4_global(_v4_scope, 'ValueError')("stage receipt path is not the configured slot path")
            raw_receipt = receipt_path.read_bytes()
            if len(raw_receipt) > 2 * 1024 * 1024:
                raise _v4_global(_v4_scope, 'ValueError')("settled receipt exceeds the bounded size")
            receipt_sha = _stage_hashlib.sha256(raw_receipt).hexdigest()
            current_receipt = _v4_global(_v4_scope, 'json').loads(raw_receipt.decode("utf-8"))
            reread_receipt = _v4_global(_v4_scope, '_read_receipt')(config, trade_date, stage_id)
            if (receipt_sha != _SETTLED_HK_RECOVERY_INCIDENT["prior_receipt_sha256"]
                    or current_receipt != observed_receipt or reread_receipt != current_receipt
                    or not _settled_hk_recovery_receipt_matches(_v4_scope, current_receipt)):
                raise _v4_global(_v4_scope, 'ValueError')("settled receipt identity mismatch")
            if (max_attempts != authorization.get("max_attempts")
                    or _v4_global(_v4_scope, '_node_attempt_count')(current_receipt) != authorization.get("prior_node_attempt_count")):
                raise _v4_global(_v4_scope, 'ValueError')("attempt reservation binding mismatch")
            rearm_marker = receipt_path.parent / "dependency_rearm.json"
            if rearm_marker.exists() or rearm_marker.is_symlink():
                raise _v4_global(_v4_scope, 'ValueError')("dependency rearm marker is present")

            local_evaluated = _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
            scheduled_at = getattr(decision, "scheduled_at", None)
            expected_cutoff = _v4_global(_v4_scope, 'datetime').strptime(
                f"{trade_date} {_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].cutoff}",
                "%Y%m%d %H:%M:%S",
            ).replace(tzinfo=_v4_global(_v4_scope, 'SHANGHAI'))
            if (evaluated_at.tzinfo is None or now.tzinfo is None
                    or local_evaluated.strftime("%Y%m%d") != trade_date
                    or now.strftime("%Y%m%d") != trade_date
                    or local_evaluated > now
                    or decision.status != "LATE_CATCHUP_REPLAY"
                    or getattr(decision, "trade_date", None) != trade_date
                    or getattr(decision, "stage_id", None) != stage_id
                    or scheduled_at is None
                    or _v4_global(_v4_scope, '_as_shanghai')(scheduled_at) != expected_cutoff
                    or local_evaluated <= expected_cutoff):
                raise _v4_global(_v4_scope, 'ValueError')("same-day late recovery decision is invalid")
            gate = _v4_global(_v4_scope, '_calendar_gate')(
                trade_date, markets=_v4_global(_v4_scope, 'STAGE_BY_ID')[stage_id].markets
            )
            if gate.get("status") != "ELIGIBLE":
                raise _v4_global(_v4_scope, 'ValueError')("stage calendar is not eligible")
            safety_config = config.get("safety")
            if (safety_config is not None
                    and (not _v4_global(_v4_scope, 'isinstance')(safety_config, _v4_global(_v4_scope, 'Mapping'))
                         or any(safety_config.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent")))):
                raise _v4_global(_v4_scope, 'ValueError')("configured safety flags must remain false")
            pool_root = _v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(config["hk_d1_root"]))
            source_root = config.get("preselection_source_root")
            if not source_root:
                raise _v4_global(_v4_scope, 'ValueError')("exact HK preselection source root is required")
            binding = _build_hk_stage_binding(
                pool_root, trade_date,
                preselection_source_root=_v4_global(_v4_scope, 'Path')(_v4_global(_v4_scope, 'str')(source_root)),
            )
            expected_pool_sha = _SETTLED_HK_RECOVERY_INCIDENT["corrected_candidate_artifact_sha256"]
            if (binding.status != "READY" or binding.market != "HK_CONNECT"
                    or binding.trade_date != trade_date or binding.role != "HK_CONNECT_D1_TOP100"
                    or len(binding.codes) != 100 or len(set(binding.codes)) != 100
                    or binding.sha256 != expected_pool_sha
                    or binding.source_run_id != "hk-d1-" + expected_pool_sha[:16]):
                raise _v4_global(_v4_scope, 'ValueError')("corrected exact-date HK D-1 pool binding mismatch")
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'RuntimeError'),
                _v4_global(_v4_scope, 'TypeError'), _v4_global(_v4_scope, 'ValueError'),
                _v4_global(_v4_scope, 'KeyError'), _v4_global(_v4_scope, 'AttributeError'),
                _v4_global(_v4_scope, 'ImportError')) as error:
            return _settled_hk_recovery_result(
                _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
                mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_VALIDATION_FAILED",
            ) | {"error": _v4_global(_v4_scope, 'str')(error)}

        history_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if history_root.is_symlink():
            return _settled_hk_recovery_result(
                _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
                mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_HISTORY_PATH_UNSAFE",
            )
        try:
            history_dir.mkdir(mode=0o700)
            prior_copy = history_dir / "prior_receipt.json"
            fd = _v4_global(_v4_scope, 'os').open(
                prior_copy, _v4_global(_v4_scope, 'os').O_WRONLY | _v4_global(_v4_scope, 'os').O_CREAT | _v4_global(_v4_scope, 'os').O_EXCL, 0o600
            )
            with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as stream:
                stream.write(raw_receipt)
                stream.flush()
                _v4_global(_v4_scope, 'os').fsync(stream.fileno())
            reservation = {
                "schema_version": "stage_center.settled_hk_recovery_reservation.v1",
                "authorization_id": _SETTLED_HK_RECOVERY_AUTH_ID,
                "authorization_sha256": authorization_sha,
                "prior_receipt_sha256": receipt_sha,
                "original_node_attempt_count": 2,
                "reserved_node_attempt_count": 3,
                "corrected_pool_sha256": binding.sha256,
                "corrected_pool_source_run_id": binding.source_run_id,
                "decision_status": decision.status,
                "reserved_at": now.isoformat(),
                "status": "RESERVED_BEFORE_PROVIDER",
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
            reservation_raw = _v4_global(_v4_scope, 'json').dumps(
                reservation, ensure_ascii=False, sort_keys=True, indent=2
            ).encode("utf-8") + b"\n"
            fd = _v4_global(_v4_scope, 'os').open(
                history_dir / "reservation.json",
                _v4_global(_v4_scope, 'os').O_WRONLY | _v4_global(_v4_scope, 'os').O_CREAT | _v4_global(_v4_scope, 'os').O_EXCL, 0o600,
            )
            with _v4_global(_v4_scope, 'os').fdopen(fd, "wb") as stream:
                stream.write(reservation_raw)
                stream.flush()
                _v4_global(_v4_scope, 'os').fsync(stream.fileno())
            directory_fd = _v4_global(_v4_scope, 'os').open(history_dir, _v4_global(_v4_scope, 'os').O_RDONLY)
            try:
                _v4_global(_v4_scope, 'os').fsync(directory_fd)
            finally:
                _v4_global(_v4_scope, 'os').close(directory_fd)
            for protected_path in (prior_copy, history_dir / "reservation.json"):
                _v4_global(_v4_scope, 'os').chmod(protected_path, 0o400)
            for directory in (history_dir, history_root, receipt_path.parent):
                directory_fd = _v4_global(_v4_scope, 'os').open(directory, _v4_global(_v4_scope, 'os').O_RDONLY)
                try:
                    _v4_global(_v4_scope, 'os').fsync(directory_fd)
                finally:
                    _v4_global(_v4_scope, 'os').close(directory_fd)
            _v4_global(_v4_scope, 'os').chmod(history_dir, 0o500)
            _v4_global(_v4_scope, 'os').chmod(history_root, 0o500)
        except (_v4_global(_v4_scope, 'OSError'), _v4_global(_v4_scope, 'FileExistsError')) as error:
            return _settled_hk_recovery_result(
                _v4_scope, status="CANNOT_CONFIRM", trade_date=trade_date, stage_id=stage_id,
                mode=mode, attempt_count=2, reason="SETTLED_HK_RECOVERY_RESERVATION_FAILED",
            ) | {"error": _v4_global(_v4_scope, 'str')(error)}

        if hasattr(decision, "same_day_late_observation_recovery"):
            decision.same_day_late_observation_recovery = True
        captured = _v4_global(_v4_scope, 'list')(precaptures or ())
        attempt_count = 3
        _v4_global(_v4_scope, '_deadline').due(
            decision.scheduled_at, trade_date=trade_date, stage_id=stage_id,
            due_status=decision.status, dispatch_mode=mode,
        )
        _v4_global(_v4_scope, '_deadline').checkpoint("BUSINESS_START", trade_date=trade_date, stage_id=stage_id)
        from stage_center.attempt_evidence import capture_attempt
        with capture_attempt(
            runner._receipt_path(trade_date, stage_id).parent,
            trade_date=trade_date, stage_id=stage_id, attempt_number=attempt_count,
            evaluated_at=_v4_global(_v4_scope, '_as_shanghai')(evaluated_at).isoformat(),
            due_status=decision.status,
        ) as attempt_journal:
            result = _v4_global(_v4_scope, 'dict')(runner._run_one(decision))
            attempt_journal.finish(result)
        result["attempt_diagnostic"] = attempt_journal.summary()
        _v4_global(_v4_scope, '_deadline').event("BUSINESS_RETURN", status=result.get("status"))
        result.update({
            "node_id": stage_id,
            "dispatch_mode": mode,
            "node_attempt_count": attempt_count,
            "pre_captures": captured,
            "settled_hk_recovery": {
                "schema_version": "stage_center.settled_hk_recovery_result.v1",
                "authorization_id": _SETTLED_HK_RECOVERY_AUTH_ID,
                "authorization_sha256": authorization_sha,
                "prior_receipt_sha256": receipt_sha,
                "reserved_node_attempt_count": attempt_count,
                "corrected_pool_sha256": binding.sha256,
                "reservation_path": str(history_dir / "reservation.json"),
                "prior_receipt_archive_path": str(history_dir / "prior_receipt.json"),
                "same_day_late_observation_recovery": True,
            },
        })
        if result.get("status") == "PARTIAL_WITH_ROWS" and result.get("write_performed") is False:
            result["status"] = "CANNOT_CONFIRM"
            result.setdefault("blocked_layer", "PARTIAL_STAGE_WITHOUT_WRITE")
        status = _v4_global(_v4_scope, 'str')(result.get("status") or "CANNOT_CONFIRM")
        outcome = _v4_global(_v4_scope, '_node_outcome')(status, result)
        result["node_outcome"] = outcome
        result["retry_exhausted"] = _v4_global(_v4_scope, 'bool')(outcome == "TRANSIENT" and attempt_count >= max_attempts)
        if outcome == "TRANSIENT" and not result["retry_exhausted"]:
            result["retry_after"] = (
                _v4_global(_v4_scope, '_as_shanghai')(evaluated_at)
                + _v4_global(_v4_scope, 'timedelta')(seconds=_v4_global(_v4_scope, '_config_float')(
                    config, "node_retry_backoff_seconds", _v4_global(_v4_scope, 'DEFAULT_RETRY_BACKOFF_SECONDS')
                ))
            ).isoformat()
        else:
            result.pop("retry_after", None)
        persisted = runner._write_receipt(result, trade_date, stage_id)
        persisted = _v4_global(_v4_scope, '_deadline').complete_receipt(
            runner._receipt_path(trade_date, stage_id), persisted,
            rewrite=lambda failed: runner._write_receipt(failed, trade_date, stage_id),
        )
        return persisted
    finally:
        lock.release()


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
    authorization_path = config.get("_settled_hk_recovery_authorization_path")
    if authorization_path is not None:
        return __dispatch_settled_hk_recovery_body(
            _v4_scope, config, trade_date, stage_id, evaluated_at,
            mode=mode, runner=runner, precaptures=precaptures,
            observed_receipt=receipt, authorization_path=authorization_path,
            max_attempts=max_attempts,
        )
    hk_0930_recovery = (
        _same_day_hk_0930_0935_cutoff_recovery_shape(
            receipt,
            mode=mode,
            trade_date=trade_date,
            stage_id=stage_id,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
        )
        or _continued_hk_0930_0935_recovery(
            receipt,
            mode=mode,
            trade_date=trade_date,
            stage_id=stage_id,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
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
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
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
    futu_1445_receipt_sha256, futu_1445_dataset_sha256 = _frozen_hk_futu_1445_hashes(
        config, trade_date, stage_id, mode
    )
    same_day_futu_1445_recovery = _same_day_hk_1445_futu_recovery_shape(
        receipt,
        mode=mode,
        trade_date=trade_date,
        stage_id=stage_id,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        receipt_sha256=futu_1445_receipt_sha256,
        dataset_sha256=futu_1445_dataset_sha256,
    )
    futu_hk_recovery = same_day_futu_1300_recovery or same_day_futu_1445_recovery
    if (
        trade_date == _HK_0930_0935_CUTOFF_RECOVERY_DATE
        and stage_id == _HK_0930_0935_CUTOFF_RECOVERY_STAGE
        and existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES')
        and isinstance(receipt, dict)
        and ("execution_origin" in receipt or "execution_markets" in receipt)
        and not hk_0930_recovery
    ):
        return {
            "status": "CANNOT_CONFIRM",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "node_attempt_count": attempt_count,
            "first_failed_layer": "HK_RECOVERY_CONTINUATION_RECEIPT_INVALID",
            "write_performed": False,
            "recovery_rejected": True,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }
    scoped_runner_factory = scoped_recovery_runner
    if hk_0930_recovery:
        try:
            from stage_center._runner_parts.runner_receipts import scoped_recovery_runner as scoped_runner_factory
        except ImportError:
            return {
                "status": "CANNOT_CONFIRM",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "first_failed_layer": "HK_ONLY_SCOPED_RECOVERY_CAPABILITY_UNAVAILABLE",
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
    if hk_0930_recovery or futu_hk_recovery:
        wall = _v4_global(_v4_scope, '_rearm_wall_now')()
        safety = config.get("safety")
        if (
            evaluated_at.tzinfo is None
            or wall.tzinfo is None
            or _v4_global(_v4_scope, '_as_shanghai')(wall).strftime("%Y%m%d") != trade_date
            or _v4_global(_v4_scope, '_as_shanghai')(evaluated_at).strftime("%Y%m%d") != trade_date
            or evaluated_at > wall
            or not isinstance(safety, dict)
            or any(safety.get(flag) is not False for flag in ("production_allowed", "buy_gate_updated", "orders_sent"))
        ):
            return {
                "status": "CANNOT_CONFIRM",
                "stage_id": stage_id,
                "node_id": stage_id,
                "trade_date": trade_date,
                "dispatch_mode": mode,
                "first_failed_layer": "HK_RECOVERY_SCOPE_UNSAFE",
                "write_performed": False,
                **_v4_global(_v4_scope, '_safe_flags')(),
            }
        if (
            not same_day_futu_1300_recovery
            and
            existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES')
            and not _v4_global(_v4_scope, '_retry_is_due')(
                receipt,
                _v4_global(_v4_scope, '_as_shanghai')(evaluated_at),
                retry_backoff_seconds=retry_backoff,
            )
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
    # The inner runner may replace receipt.json before it exits. This immutable
    # reservation survives that write and prevents a crash from reopening retries.
    rearm_marker = _v4_global(_v4_scope, '_receipt_path')(config, trade_date, stage_id).parent / "dependency_rearm.json"
    if rearm_marker.exists() and not _v4_global(_v4_scope, '_stage_settled')(receipt):
        attempt_count = _v4_global(_v4_scope, 'max')(attempt_count, max_attempts + 1)
        existing_status = "CANNOT_CONFIRM"
    if (_v4_global(_v4_scope, '_stage_settled')(receipt)
            and existing_status not in _v4_global(_v4_scope, 'TRANSIENT_STATUSES')
            and not hk_0930_recovery
            and not same_day_futu_1445_recovery):
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
    rearm = None
    if existing_status in _v4_global(_v4_scope, 'TRANSIENT_STATUSES') and not hk_0930_recovery and not same_day_futu_1300_recovery:
        if attempt_count >= max_attempts:
            rearm = _v4_global(_v4_scope, '_exact_hk_d1_dependency_rearm')(config, trade_date, receipt, evaluated_at)
        if attempt_count >= max_attempts and rearm is None:
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
        if rearm is None and not _v4_global(_v4_scope, '_retry_is_due')(
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

    decision = _v4_global(_v4_scope, 'next')(
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
    decision.same_day_late_observation_recovery = bool(
        (hk_0930_recovery or futu_hk_recovery)
        and _same_day_late_observation_recovery(
            _v4_scope,
            mode=mode,
            trade_date=trade_date,
            evaluated_at=evaluated_at,
            decision=decision,
        )
    )
    if (hk_0930_recovery or futu_hk_recovery) and not decision.same_day_late_observation_recovery:
        return {
            "status": "CANNOT_CONFIRM",
            "stage_id": stage_id,
            "node_id": stage_id,
            "trade_date": trade_date,
            "dispatch_mode": mode,
            "first_failed_layer": "HK_RECOVERY_NOT_SAME_DAY_LATE_REPLAY",
            "write_performed": False,
            **_v4_global(_v4_scope, '_safe_flags')(),
        }

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
        if same_day_futu_1445_recovery:
            locked_receipt_sha256, locked_dataset_sha256 = _frozen_hk_futu_1445_hashes(
                config, trade_date, stage_id, mode
            )
            if not _same_day_hk_1445_futu_recovery_shape(
                receipt,
                mode=mode,
                trade_date=trade_date,
                stage_id=stage_id,
                attempt_count=attempt_count,
                max_attempts=max_attempts,
                receipt_sha256=locked_receipt_sha256,
                dataset_sha256=locked_dataset_sha256,
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
        if hk_0930_recovery or futu_hk_recovery:
            reserved_attempt = attempt_count + 1
            runner = scoped_runner_factory(
                runner,
                markets=("HK_CONNECT",),
                prior_receipt=receipt,
                attempt_count=reserved_attempt,
                origin="HK_ORIGINAL_BUDGET_RECOVERY",
            )
            runner._write_receipt(
                {
                    **(receipt or {}),
                    "status": "CANNOT_CONFIRM",
                    "node_outcome": "TRANSIENT",
                    "node_attempt_count": reserved_attempt,
                    "retry_exhausted": reserved_attempt >= max_attempts,
                    "dispatch_mode": mode,
                    "execution_pending": True,
                    "partial_commit_possible": True,
                    "write_performed": False,
                },
                trade_date,
                stage_id,
            )
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
            result = _v4_global(_v4_scope, 'dict')(runner._run_one(decision))
            if futu_hk_recovery:
                result = _clear_stale_scoped_recovery_failure(
                    receipt or {}, result, origin="HK_ORIGINAL_BUDGET_RECOVERY"
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
        # Preserve consumed re-arm metadata across both success and failure.
        result.update({k: v for k, v in (receipt or {}).items()
                       if k.startswith("dependency_rearm_")})
        if rearm is not None:
            result.update(rearm)
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
        return persisted
    finally:
        lock.release()
