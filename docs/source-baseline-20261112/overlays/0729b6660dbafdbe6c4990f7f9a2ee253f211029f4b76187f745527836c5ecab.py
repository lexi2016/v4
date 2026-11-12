"""Read-only V4-owned baimao X digest reader.

Reads only ``<data_root>/baimao_x/latest_baimao_x_digest.json``. Absence is
``None`` (an explicit ``NO_BAIMAO_X_DIGEST`` upstream); a present-but-malformed
or unsafe digest raises so the API fails closed as ``CANNOT_CONFIRM`` instead of
masquerading as missing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from infrastructure.owned_path import resolve_owned_path


def _is_false(value: Any) -> bool:
    return value in (False, 0, None, "")


class BaimaoXSource:
    def __init__(self, data_root: Path) -> None:
        self.data_root = Path(data_root)

    def _resolve(self, relative: str) -> Path:
        return resolve_owned_path(self.data_root, relative)

    def read_latest(self) -> dict[str, Any] | None:
        candidate = self._resolve("baimao_x/latest_baimao_x_digest.json")
        if not candidate.is_file():
            if candidate.exists():
                raise ValueError("invalid owned baimao_x digest path")
            return None
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
            raise ValueError("invalid owned baimao_x digest payload") from error
        if not isinstance(payload, Mapping):
            raise ValueError("invalid owned baimao_x digest payload")
        if (
            not _is_false(payload.get("production_allowed"))
            or not _is_false(payload.get("buy_gate_updated"))
            or not _is_false(payload.get("orders_sent"))
        ):
            raise ValueError("unsafe owned baimao_x digest")
        return dict(payload)


__all__ = ["BaimaoXSource"]
