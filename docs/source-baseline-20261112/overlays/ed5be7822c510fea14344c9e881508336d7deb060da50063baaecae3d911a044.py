"""Compute the frozen canary oracle (input sha256, row_count, max bar_time).

Run once against the frozen source; the values printed here are embedded into
``shared_data/allowlist.py`` as ``expected_input_sha256`` / ``expected_row_count``.
Read-only against v3_system.
"""
from __future__ import annotations

import csv
import hashlib
import sys
from pathlib import Path

SOURCE = Path(
    r"C:\Users\huang\Desktop\学习\v3_system\40_artifacts\runtime_debug\20260716_ashare_open_live\ashare_open_live_1min_bars_20260716.csv"
)


def main() -> int:
    if not SOURCE.exists():
        print(f"source missing: {SOURCE}", file=sys.stderr)
        return 2
    digest = hashlib.sha256()
    with open(SOURCE, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    rows = 0
    max_bar_time = ""
    with open(SOURCE, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        bar_index = header.index("bar_time") if header else -1
        for row in reader:
            if not row or all(not cell.strip() for cell in row):
                continue
            rows += 1
            if bar_index >= 0 and row[bar_index].strip() > max_bar_time:
                max_bar_time = row[bar_index].strip()
    print(f"input_sha256={digest.hexdigest()}")
    print(f"row_count={rows}")
    print(f"max_bar_time={max_bar_time!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
