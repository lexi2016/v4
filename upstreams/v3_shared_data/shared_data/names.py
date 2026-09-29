"""Verified shared Hong Kong security-name dictionary reader."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .hashing import sha256_file
from .paths import resolve_under
from .store import StoreError


def load_verified_hk_names(store_root: Path | str) -> tuple[dict[str, str], str]:
    asset_root = Path(store_root) / "assets" / "hk_0_2"
    try:
        pointer = json.loads((asset_root / "name_latest.json").read_text(encoding="utf-8"))
        manifest_path = resolve_under(
            asset_root, str(pointer.get("manifest_relative") or "")
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        dictionary_path = resolve_under(
            asset_root, str(manifest.get("dictionary_relative") or "")
        )
    except (OSError, ValueError, TypeError) as error:
        raise StoreError(f"HK name dictionary metadata invalid: {error}") from error
    dictionary_sha = sha256_file(dictionary_path)
    if dictionary_sha != str(manifest.get("dictionary_sha256") or ""):
        raise StoreError("HK name dictionary checksum mismatch")
    names: dict[str, str] = {}
    with dictionary_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("code") or "").strip().upper()
            name = str(row.get("name") or "").strip()
            if code and name:
                names[code] = name
    return names, dictionary_sha


__all__ = ["load_verified_hk_names"]
