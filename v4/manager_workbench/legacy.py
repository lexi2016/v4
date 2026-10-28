"""Read-only historical evidence adapter. Never imports old business functions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import validate_date


class LegacyHistory:
    def __init__(self, root: Path | None):
        self.root = root

    def read_index(self, target_date: str) -> list[dict[str, Any]]:
        validate_date(target_date)
        if self.root is None or not self.root.is_dir() or self.root.is_symlink():
            return []
        # Restrict traversal to a date-specific directory. No implicit workspace calls.
        folder = self.root / target_date
        if not folder.is_dir() or folder.is_symlink():
            return []
        records: list[dict[str, Any]] = []
        for file in sorted(folder.glob("*.json")):
            if file.is_symlink() or not file.is_file():
                records.append({"origin":"LEGACY", "verification":"CANNOT_CONFIRM", "gaps":["LEGACY_FILE_UNSAFE"]})
                continue
            try:
                raw = file.read_bytes()
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("invalid object")
                schema = value.get("schema_version") or value.get("schema")
                old_id = value.get("run_id") or value.get("plan_run_id")
                identity_ok = isinstance(old_id, str) and bool(old_id) and isinstance(schema, str) and bool(schema)
                # A byte SHA is proven, but old owner/receipt provenance is NOT.
                # Unknown schemas never inherit a VERIFIED label from parseability.
                records.append({"origin":"LEGACY", "original_schema":schema if isinstance(schema, str) else None,
                                "original_run_id":old_id if isinstance(old_id, str) else None,
                                "original_sha256":hashlib.sha256(raw).hexdigest(),
                                "verification":"CANNOT_CONFIRM",
                                "gaps":["LEGACY_PROVENANCE_UNVERIFIED"] if identity_ok else ["LEGACY_SCHEMA_OR_IDENTITY_UNKNOWN"]})
            except (OSError, ValueError, UnicodeDecodeError):
                records.append({"origin":"LEGACY", "original_schema":None, "original_run_id":None,
                                "original_sha256":None,"verification":"CANNOT_CONFIRM",
                                "gaps":["LEGACY_SCHEMA_UNRECOGNIZED"]})
        return records

