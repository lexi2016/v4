"""Load the frozen store by default; all writes stay inside pytest temp roots."""
from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
SOURCE_ROOT = Path(os.environ.get("HISTORICAL_POOL_SOURCE_ROOT", ROOT / "before")).resolve()
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "support"))
sys.path.insert(0, str(SOURCE_ROOT))
sys.path.insert(0, str(ROOT))

from infrastructure import preselection_pool_store

if Path(preselection_pool_store.__file__).resolve() != SOURCE_ROOT / "infrastructure/preselection_pool_store.py":
    raise RuntimeError("historical validator import did not use the selected source root")
