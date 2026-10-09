"""Emit actual reader DTOs from temporary synthetic inputs for frontend tests.

No argument can redirect output writes to a business root. The original reader
and test-only fixture publishers operate inside TemporaryDirectory only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
for path in reversed((ROOT, ROOT / "upstreams", ROOT / "tests")):
    sys.path.insert(0, str(path))
import r3_scoped_loader
r3_scoped_loader.install()

from test_manager_three_channel_hk_reader import (
    _panel, _publish_master, _screen, DAY, TARGET, owner,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", choices=("hk_missing", "hk_valid"), required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="manager-three-channel-ui-") as temporary:
        root = Path(temporary)
        _panel(root)
        _publish_master(root, TARGET if args.fixture == "hk_missing" else DAY)
        screen = _screen(root)
        print(json.dumps({"scope": "SYNTHETIC_ACTUAL_READER_DTO",
            "owner_module": str(Path(owner.__file__).resolve()),
            "market_screen": screen}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
