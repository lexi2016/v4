from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from shared_data.hk_0_2 import import_frozen_hk_0_2_assets


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time checksum-pinned import of frozen HK Connect 0.2 assets")
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--panel-sha256", required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--model-bundle", type=Path, required=True)
    parser.add_argument("--name-dictionary", type=Path)
    args = parser.parse_args()
    assets = import_frozen_hk_0_2_assets(
        args.asset_root,
        panel_path=args.panel,
        model_manifest_path=args.model_manifest,
        model_bundle_path=args.model_bundle,
        expected_panel_sha256=args.panel_sha256,
        name_dictionary_path=args.name_dictionary,
    )
    print(json.dumps({
        "ok": True,
        "panel_sha256": assets.panel_manifest["panel_sha256"],
        "panel_max_date": assets.panel_manifest["panel_max_date"],
        "model_bundle_sha256": assets.model_manifest["bundle_sha256"],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
