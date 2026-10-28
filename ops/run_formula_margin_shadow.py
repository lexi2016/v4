"""Manual entry point for the isolated V4 formula-margin shadow tool.

This wrapper intentionally has no scheduler registration and no network/data
client.  It delegates to ``stage_center.formula_margin_shadow`` and therefore
supports only explicit ``preflight``, ``capture``, ``freeze``, ``label``,
``verify`` and ``evaluate`` commands.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stage_center.formula_margin_shadow import _cli


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
