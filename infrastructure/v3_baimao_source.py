"""Read-only adapter over the V3 baimao_x latest digest."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class V3BaimaoXSource:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root

    def read_latest(self) -> dict[str, Any] | None:
        candidate = self.data_root / "baimao_x" / "latest_baimao_x_digest.json"
        if not candidate.is_file():
            return None
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return None
        if not isinstance(payload, Mapping):
            return None
        return dict(payload)


__all__ = ["V3BaimaoXSource"]
