"""Mac research-panel adapter for the daily A/H authority chain.

The public module keeps the historical interface while the implementations live
in path-neutral child modules.  Receipts and safety flags remain research-only:
they do not grant production or trading permission.
"""

from __future__ import annotations

import argparse
import csv
import datetime as _datetime
import hashlib
import json
import math
import os
import importlib.util
import shutil
import subprocess
import sys
import struct
import tempfile
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


if __package__ in (None, ""):
    __package__ = "ops"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from . import macos_research_panel_daily_common as _common
from . import macos_research_panel_daily_collectors as _collectors
from . import macos_research_panel_daily_authority as _authority
from . import macos_research_panel_daily_pack as _pack
from . import macos_research_panel_daily_gate as _gate


A_DAY_STRUCT = _common.A_DAY_STRUCT
HK_DAY_STRUCT = _common.HK_DAY_STRUCT
SAFETY_FLAGS = _common.SAFETY_FLAGS
LANE_CHOICES = _common.LANE_CHOICES
SnapshotGateError = _common.SnapshotGateError
SnapshotGateError.__module__ = __name__
HKCONNECT_PLATE_CODES = _common.HKCONNECT_PLATE_CODES
PYTDX_KLINE_DAY = _common.PYTDX_KLINE_DAY
MAX_EXCLUDED_EVIDENCE = _common.MAX_EXCLUDED_EVIDENCE
COMMON_A_PREFIXES = _common.COMMON_A_PREFIXES
AUTHORITY_DAY_MINIMUM_DEFAULT = _common.AUTHORITY_DAY_MINIMUM_DEFAULT
DEFAULT_A_SYNC_RUN_BUDGET_SECONDS = _gate.DEFAULT_A_SYNC_RUN_BUDGET_SECONDS
A_SYNC_RUN_BUDGET_ENV = _gate.A_SYNC_RUN_BUDGET_ENV
A_SYNC_HOST_ENV = _gate.A_SYNC_HOST_ENV


_FUNCTION_MODULES = {
    **{name: _common for name in (
        "_today_shanghai",
        "_scheduled_day_is_cross_market_trading_day",
        "_frame_records",
        "_compact_datetime",
        "_canonical_sha",
        "_universe_code",
        "_date",
        "_rows",
        "_number",
        "_code",
        "_validate_rows",
        "_sha",
        "_atomic_write",
        "_after_1700_attempt_path",
        "_normalize_lane",
        "_not_requested_lane",
        "build_subprocess_command",
        "_load_universe",
        "_a_day_files",
        "_absolute_path_argument",
    )},
    **{name: _collectors for name in (
        "collect_a_pytdx_rows",
        "collect_hk_futu_rows",
    )},
    **{name: _authority for name in (
        "_load_authority_module",
        "_accepted_formula_input_root",
        "run_windows_a_sync_authority",
        "_parquet_max_date",
        "_ensure_pointer_seed",
        "_formula_artifact_binding",
        "run_windows_a_formula_authority",
        "run_hk_0_2_authority",
    )},
    **{name: _pack for name in (
        "_panel_frame",
        "bootstrap_a_vipdoc_from_panel",
        "_validate_seed_rows",
        "_day_file_last_date",
        "_existing_records",
        "_a_record",
        "_hk_record",
        "_pack_day_file",
        "_a_exchange",
        "_grouped_result",
        "pack_a_day",
        "pack_hk_day",
        "validate_snapshot",
    )},
    **{name: _gate for name in (
        "selector_pointer_is_ready",
        "_read_lane_receipt",
        "_receipt_safety_is_false",
        "_a_lane_receipt_ready",
        "_hk_lane_receipt_ready",
        "ensure_after_1700",
        "ensure_exit_code",
        "_receipt",
        "run_lanes",
        "_non_trading_day_result",
        "run_scheduled_lanes",
        "_resolve_a_sync_run_budget",
        "main",
    )},
}


for _function_name, _function_module in _FUNCTION_MODULES.items():
    _source = getattr(_function_module, _function_name)
    _rebound = __import__("types", fromlist=("FunctionType",)).FunctionType(
        _source.__code__,
        vars(),
        name=_source.__name__,
        argdefs=_source.__defaults__,
        closure=_source.__closure__,
    )
    _rebound.__name__ = _source.__name__
    _rebound.__qualname__ = _source.__qualname__
    _rebound.__doc__ = _source.__doc__
    _rebound.__module__ = __name__
    _rebound.__kwdefaults__ = _source.__kwdefaults__
    _rebound.__annotations__ = _source.__annotations__
    _rebound.__dict__ = _source.__dict__.copy()
    if hasattr(_source, "__type_params__"):
        _rebound.__type_params__ = _source.__type_params__
    globals()[_function_name] = _rebound


del _common, _collectors, _authority, _pack, _gate
del _FUNCTION_MODULES, _function_name, _function_module, _source, _rebound


if __name__ == "__main__":
    raise SystemExit(main())
