"""One-time offline normalization of a morning-news manifest into shared data."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from shared_data.morning_news import normalize_legacy_morning_news, publish_morning_news


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--shared-data-root", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = args.shared_data_root
    if root is None:
        value = str(os.environ.get("V3_SHARED_DATA_STORE_ROOT") or "").strip()
        root = Path(value) if value else None
    if root is None:
        print(json.dumps({"ok": False, "error": "shared data root missing"}))
        return 1
    try:
        source = json.loads(args.source_manifest.read_text(encoding="utf-8-sig"))
        payload = normalize_legacy_morning_news(source)
        result = publish_morning_news(root, payload)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
