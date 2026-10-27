"""Publish one exact-date A-share selector security registry from a parquet file."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.a_share_security_master import (publish_a_share_security_master, acquire_current_display_names, publish_current_display_names)
from shared_data.store import StoreError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selector-parquet")
    parser.add_argument("--current-display-names", action="store_true")
    parser.add_argument("--observation-date")
    parser.add_argument("--request-json", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--official-observations", type=Path)
    parser.add_argument("--store-root", required=True)
    parser.add_argument("--signal-date", required=True)
    args = parser.parse_args(argv)
    try:
        if args.current_display_names:
            if not args.observation_date or not args.request_json or not args.evidence_root:
                parser.error("display mode requires observation-date/request-json/evidence-root")
            observation = acquire_current_display_names(args.evidence_root, observation_date=args.observation_date, requested_codes=json.loads(args.request_json.read_text()), official_rows=json.loads(args.official_observations.read_text()) if args.official_observations else None)
            result = publish_current_display_names(args.store_root, observation)
        else:
            if not args.selector_parquet:
                parser.error("selector mode requires --selector-parquet")
            result = publish_a_share_security_master(
                Path(args.store_root),
                signal_date=args.signal_date,
                selector_path=Path(args.selector_parquet),
            )
    except (OSError, StoreError, ValueError) as error:
        result = {"ok": False, "status": "FAILED", "error": str(error)}
    else:
        result = {"ok": True, **result}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
