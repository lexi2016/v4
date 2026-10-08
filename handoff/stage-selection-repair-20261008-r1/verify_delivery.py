#!/usr/bin/env python3
"""Verify this handoff's recorded files without touching any application owner."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
    failures: list[dict[str, object]] = []
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            failures.append({"path": str(relative), "error": "unsafe manifest path"})
            continue
        path = root / relative
        if path.is_symlink() or not path.is_file():
            failures.append({"path": str(relative), "error": "missing file or symlink"})
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if len(raw) != entry["bytes"] or digest != entry["sha256"]:
            failures.append({"path": str(relative), "error": "size or SHA256 mismatch"})
    print(json.dumps({
        "scope": "DELIVERED_FILES_ONLY_NOT_ACTIVE_RUNTIME",
        "checked_files": len(manifest["files"]),
        "passed": not failures,
        "failures": failures,
    }, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
