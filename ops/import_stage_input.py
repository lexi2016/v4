"""Offline-only importer for reviewed V4 stage input JSON."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from infrastructure.stage_store import StageStore


def import_stage_input(source: str | Path, data_root: str | Path) -> dict[str, Any]:
    source_text = str(source)
    if "://" in source_text:
        raise ValueError("stage input source must be a local JSON file")
    source_path = Path(source)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    payload = json.loads(source_path.read_text(encoding="utf-8-sig"))
    result = StageStore(Path(data_root)).import_input(payload)
    return {
        "status": "STAGE_INPUT_IMPORTED",
        "trade_date": payload["trade_date"],
        "stage_id": payload["stage_id"],
        **result,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a reviewed local V4 stage input JSON file")
    parser.add_argument("source", type=Path)
    parser.add_argument("--data-root", type=Path, default=Path.cwd() / ".runtime" / "data")
    arguments = parser.parse_args()
    print(json.dumps(import_stage_input(arguments.source, arguments.data_root), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
