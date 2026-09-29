"""Offline-only importer for already exported V3.5 JSON input."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from infrastructure.data_store import NativeDataStore


def _json_file(value: str) -> Path:
    if "://" in value:
        raise argparse.ArgumentTypeError("URLs are not accepted")
    path = Path(value)
    if not path.is_file() or path.suffix.lower() != ".json":
        raise argparse.ArgumentTypeError("input must be a local JSON file")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Import already-exported preselection JSON into V3.5-owned storage")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--catalog", type=_json_file)
    parser.add_argument("--payload", action="append", type=_json_file, default=[])
    arguments = parser.parse_args()
    if arguments.catalog is None and not arguments.payload:
        parser.error("provide --catalog or --payload")
    store = NativeDataStore(arguments.data_root)
    if arguments.catalog:
        store.import_catalog(json.loads(arguments.catalog.read_text(encoding="utf-8")))
    for payload in arguments.payload:
        store.import_payload(json.loads(payload.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
