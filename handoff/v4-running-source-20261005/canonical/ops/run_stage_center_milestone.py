"""Read-only Stage Center milestone receipts for the close timeline."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stage_center.consumer import StageSelectionConsumer


MILESTONE_STAGES = {
    "FUPAN_CLOSE_MATERIALS": ("1500", "STAGE_1445_1500", "A_SHARE"),
    "FUPAN_REVIEW_START": ("1555", "STAGE_1545_1555", "HK_CONNECT"),
}
RECEIPT_SCHEMA = "v3_5_stage_center_milestone_receipt.v1"


def _receipt_path(data_root: Path, date: str, node: str) -> Path:
    return data_root / "runtime_graph" / "evidence" / "scheduler_status" / date / f"{node}.json"


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_milestone(
    *, node: str, date: str, data_root: Path | str, selection_root: Path | str
) -> dict[str, Any]:
    try:
        slot, stage_id, market = MILESTONE_STAGES[node]
    except KeyError as error:
        raise ValueError(f"NODE_UNKNOWN: {node!r}") from error
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    selection = StageSelectionConsumer(Path(selection_root)).get(
        date, stage_id, markets=(market,)
    )
    selection_status = str(selection.get("status") or "CANNOT_CONFIRM")
    status = selection_status if selection_status in {"READY", "READY_EMPTY", "PARTIAL_WITH_ROWS"} else "CANNOT_CONFIRM"
    cannot_confirm = list(selection.get("cannot_confirm") or [])
    if status == "CANNOT_CONFIRM" and not cannot_confirm:
        cannot_confirm = ["STAGE_CENTER_SELECTION_CANNOT_CONFIRM"]
    completed_at = datetime.now(UTC).isoformat(timespec="seconds")
    receipt = {
        "schema_version": RECEIPT_SCHEMA,
        "node_id": node,
        "date": date,
        "business_date": date,
        "trade_date": date,
        "slot": slot,
        "stage_id": stage_id,
        "status": status,
        "reason": cannot_confirm[0] if cannot_confirm else "STAGE_CENTER_SELECTION_VERIFIED",
        "result_code": selection_status,
        "started_at": started_at,
        "completed_at": completed_at,
        "selection_status": selection_status,
        "artifact_id": selection.get("artifact_id"),
        "run_id": selection.get("run_id"),
        "markets": selection.get("markets", {}),
        "cannot_confirm": cannot_confirm,
        "selection_root": str(Path(selection_root).expanduser().resolve()),
        "write_performed": True,
        "source_write_performed": False,
        "receipt_write_performed": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    receipt_path = _receipt_path(Path(data_root).expanduser().resolve(), date, node)
    _atomic_write(receipt_path, receipt)
    receipt["receipt_path"] = str(receipt_path)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, choices=tuple(MILESTONE_STAGES))
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--date", required=True)
    parser.add_argument("--stage-id", required=True)
    parser.add_argument("--selection-root", required=True, type=Path)
    args = parser.parse_args(argv)
    expected = MILESTONE_STAGES[args.node][1]
    if args.stage_id != expected:
        raise SystemExit(f"stage id does not match node: {args.node}")
    try:
        result = run_milestone(
            node=args.node,
            date=args.date,
            data_root=args.data_root,
            selection_root=args.selection_root,
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "FAILED", "reason": f"{type(error).__name__}: {error}", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["MILESTONE_STAGES", "main", "run_milestone"]
