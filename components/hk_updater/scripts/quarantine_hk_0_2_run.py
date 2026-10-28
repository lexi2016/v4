from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from shared_data.hk_0_2 import quarantine_rejected_hk_0_2_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Recoverably quarantine one checksum-pinned rejected HK 0.2 run")
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    print(json.dumps(quarantine_rejected_hk_0_2_run(
        args.store_root,
        target_date=args.target_date,
        expected_run_id=args.run_id,
        expected_artifact_sha256=args.artifact_sha256,
        reason=args.reason,
    ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
