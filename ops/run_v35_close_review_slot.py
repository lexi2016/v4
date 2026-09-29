"""Fixed close-review slot entry for V3.5 (single-node scheduler).

Each of the 8 close-review nodes is bound to exactly one fixed slot.  This
module is the fixed CLI a Windows task invokes: it validates the business date
against the V3.5-owned A-share calendar with POST_CLOSE session semantics,
guards the node run with a per-date O_EXCL lock, delegates to
``ops.run_v35_close_review_node.run_node`` (never to arbitrary command
strings), and publishes an atomic scheduler receipt under
``runtime_graph/evidence/scheduler_status/``.  The loopback API is fixed to
the V3.5 8872 base URL; safety flags are always false.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from contracts.trading_calendar import MarketScope, RunPolicy, SessionRequirement
from domains.runtime_policy import evaluate_run_policy
from ops.run_v35_close_review_node import run_node

SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_LOOPBACK_BASE = "http://127.0.0.1:8873"
RECEIPT_SCHEMA = "v3_5_close_review_scheduler_receipt.v1"
FUNASR_SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "funasr" / "run_funasr.py"
)

# Fixed canonical node ID -> slot mapping.  The key IS the node_id delegated to
# run_node unchanged; legacy short aliases are deliberately not accepted.
NODE_SLOTS: dict[str, str] = {
    "bilibili_fupan_nightly": "2025",
    "FUPAN_VIDEO_CHECK": "2030",
    "FUPAN_VIDEO_DOWNLOAD_ASR": "2040",
    "FUPAN_STOCKDICT": "2050",
    "FUPAN_VIDEO_TABLE_OCR_ALIGN": "2105",
    "FUPAN_VIDEO_GAP": "2108",
    "FUPAN_V3_PUBLISH": "2110",
    "FUPAN_8771_VERIFY": "2115",
}
NODE_CHOICES: tuple[str, ...] = tuple(NODE_SLOTS)


class CloseReviewLockHeld(RuntimeError):
    """Raised when the per-date O_EXCL close-review lock is already held."""


def _validate_date(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        raise ValueError("DATE_INVALID")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as error:
        raise ValueError("DATE_INVALID") from error
    return value


def _today_shanghai() -> str:
    return datetime.now(SHANGHAI).strftime("%Y%m%d")


def _lock_path(data_root: Path, date: str, node: str) -> Path:
    return (
        data_root / "runtime_graph" / "locks" / "close_review" / date / f"{node}.lock"
    )


def _scheduler_receipt_path(data_root: Path, date: str, node: str) -> Path:
    return (
        data_root
        / "runtime_graph"
        / "evidence"
        / "scheduler_status"
        / date
        / f"{node}.json"
    )


def _acquire_lock(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise CloseReviewLockHeld("close-review lock is held") from error
    payload = {
        "pid": os.getpid(),
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    try:
        os.write(descriptor, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _release_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _atomic_write(path: Path, receipt: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _compose_receipt(
    *,
    node_id: str,
    date: str,
    slot: str,
    status: str,
    reason: str,
    started_at: str,
    completed_at: str,
    node_receipt_path: str,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA,
        "node_id": node_id,
        "date": date,
        "slot": slot,
        "status": status,
        "reason": reason,
        "started_at": started_at,
        "completed_at": completed_at,
        "node_receipt_path": node_receipt_path,
        "exit_code": exit_code,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def run_slot(
    *,
    node: str,
    date: str,
    data_root: str | os.PathLike[str],
    selector_data_root: str | os.PathLike[str] | None = None,
    loopback_base_url: str = DEFAULT_LOOPBACK_BASE,
) -> tuple[int, dict[str, Any]]:
    """Run one fixed close-review slot and publish the scheduler receipt.

    Returns ``(exit_code, receipt)``.  A NON_TRADING_DAY calendar status skips
    the node with exit 0; an UNKNOWN or otherwise ineligible date exits 1 as
    CALENDAR_BLOCKED.  Only an eligible date reaches the O_EXCL lock and the
    node run.
    """
    if node not in NODE_SLOTS:
        raise ValueError(f"NODE_UNKNOWN: {node!r}")
    validated_date = _validate_date(date)
    resolved_root = Path(data_root).expanduser().resolve()
    slot = NODE_SLOTS[node]
    node_id = node

    decision = evaluate_run_policy(
        RunPolicy.A_SHARE_TRADE_DAY,
        validated_date,
        slot,
        market_scope=MarketScope.A_SHARE,
        session_requirement=SessionRequirement.POST_CLOSE,
    )
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    calendar_status = str(decision.calendar_status)
    node_receipt_path = ""
    exit_code = 0

    if calendar_status == "NON_TRADING_DAY":
        status = "NON_TRADING_DAY"
        reason = str(decision.reason or "NON_TRADING_DAY")
    elif not decision.eligible:
        status = "CALENDAR_BLOCKED"
        reason = str(decision.reason or "CALENDAR_BLOCKED")
        exit_code = 1
    else:
        lock = _lock_path(resolved_root, validated_date, node)
        try:
            _acquire_lock(lock)
        except CloseReviewLockHeld:
            completed_at = datetime.now(UTC).isoformat(timespec="seconds")
            receipt = _compose_receipt(
                node_id=node_id,
                date=validated_date,
                slot=slot,
                status="CONCURRENCY_SKIPPED",
                reason="CONCURRENCY_SKIPPED",
                started_at=started_at,
                completed_at=completed_at,
                node_receipt_path="",
                exit_code=0,
            )
            _atomic_write(
                _scheduler_receipt_path(resolved_root, validated_date, node),
                receipt,
            )
            return 0, receipt
        try:
            node_exit, node_receipt = run_node(
                node=node_id,
                date=validated_date,
                data_root=resolved_root,
                selector_data_root=(
                    Path(selector_data_root).expanduser().resolve()
                    if selector_data_root is not None
                    else None
                ),
                funasr_script=FUNASR_SCRIPT,
                loopback_base_url=loopback_base_url,
            )
            node_receipt_path = str(
                resolved_root
                / "runtime_graph"
                / "evidence"
                / "node_action_status"
                / validated_date
                / f"{node_id}.json"
            )
            status = str(node_receipt.get("status") or "FAIL")
            reason = str(node_receipt.get("reason") or "")
            exit_code = int(node_exit)
        except BaseException as error:
            status = "FAILED"
            reason = f"{type(error).__name__}: {error}"
            exit_code = 1
        finally:
            _release_lock(lock)

    completed_at = datetime.now(UTC).isoformat(timespec="seconds")
    receipt = _compose_receipt(
        node_id=node_id,
        date=validated_date,
        slot=slot,
        status=status,
        reason=reason,
        started_at=started_at,
        completed_at=completed_at,
        node_receipt_path=node_receipt_path,
        exit_code=exit_code,
    )
    _atomic_write(
        _scheduler_receipt_path(resolved_root, validated_date, node),
        receipt,
    )
    return exit_code, receipt


def _emit_failure(error: Exception) -> None:
    print(
        json.dumps(
            {
                "schema_version": RECEIPT_SCHEMA,
                "status": "FAILED",
                "reason": f"{type(error).__name__}: {error}",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one fixed V3.5 close-review slot"
    )
    parser.add_argument("--node", required=True, choices=NODE_CHOICES)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--selector-data-root", type=Path)
    parser.add_argument(
        "--loopback-base-url",
        default=DEFAULT_LOOPBACK_BASE,
    )
    parser.add_argument(
        "--business-date",
        help="business date YYYYMMDD (default: today Asia/Shanghai)",
    )
    args = parser.parse_args(argv)
    business_date = args.business_date or _today_shanghai()
    try:
        exit_code, receipt = run_slot(
            node=args.node,
            date=business_date,
            data_root=args.data_root,
            selector_data_root=args.selector_data_root,
            loopback_base_url=args.loopback_base_url,
        )
    except (ValueError, OSError) as error:
        _emit_failure(error)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
