from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from shared_data.hk_0_2 import compose_historical_hk_0_2_seed


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time composition of the frozen V3 HK 0.2 historical panel seed")
    parser.add_argument("--base-panel", type=Path, required=True)
    parser.add_argument("--prior-panel-root", type=Path, required=True)
    parser.add_argument("--signal-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compose_historical_hk_0_2_seed(
        base_panel_path=args.base_panel,
        prior_signal_panel_root=args.prior_panel_root,
        signal_date=args.signal_date,
        destination=args.output,
    ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
