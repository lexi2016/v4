"""V3 adapter-compatible entry that reuses the single shared collection."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .collector import collect


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    temporary.write_bytes(source.read_bytes())
    os.replace(temporary, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--refetch-timeout", type=int, default=420)
    arguments = parser.parse_args()
    trade_date = os.environ.get("V3_SHARED_RESEARCH_DATE") or __import__("datetime").datetime.now().strftime("%Y%m%d")
    result = collect(
        state_root=Path(os.environ["V3_SHARED_RESEARCH_STATE_ROOT"]),
        trade_date=trade_date,
        slot="0830",
        cli=Path(os.environ["V3_SHARED_ZSXQ_CLI"]),
        selector_panel=Path(os.environ["V3_SHARED_SELECTOR_PANEL"]),
    )
    for key, name in (
        ("fetch_result", "zsxq_recent_topics_fetch_result.json"),
        ("recent_topics", "zsxq_recent_topics.json"),
        ("summary", "zsxq_summary.json"),
    ):
        _atomic_copy(Path(result["paths"][key]), arguments.output_dir / name)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
