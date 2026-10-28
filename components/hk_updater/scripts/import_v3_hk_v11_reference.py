"""Explicit offline import of V3's frozen v1.1 discovery reference."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shared_data.hk_v11_reference import import_hk_v11_reference
from shared_data.store import StoreError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args(argv)
    root_text = str(os.environ.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
    try:
        if not root_text:
            raise StoreError("V3_SHARED_DATA_STORE_ROOT missing")
        manifest = import_hk_v11_reference(Path(root_text), args.source)
        result = {
            "ok": True,
            "status": "READY",
            "run_id": manifest["run_id"],
            "row_count": manifest["row_count"],
            "source_sha256": manifest["source_sha256"],
        }
    except (OSError, StoreError, ValueError) as error:
        result = {"ok": False, "status": "FAILED", "error": str(error)}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
