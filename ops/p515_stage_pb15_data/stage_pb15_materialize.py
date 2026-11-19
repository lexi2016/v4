#!/usr/bin/env python3
"""Bounded, zero-model historical PB15 materializer for P5.15.

The only market-data producer used here is the frozen V4 Reader named by the
run manifest. This script does not fit, load, score, or call a model.
"""
from __future__ import annotations

import argparse
import ast
import csv
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
import platform
from pathlib import Path
import shutil
import statistics
import struct
import sys
import traceback
from collections import Counter, defaultdict

import numpy as np
import pandas as pd


ROOT = Path("/Users/lexi/Desktop/学习/v4_app")
WORKTREE = Path("/Users/lexi/.codex/worktrees/p515-stage-pb15-data-r1-20261119")
RUNS_ROOT = ROOT / "artifacts/p515_stage_pb15_data_materialization_r1_v1"
RUN_ID = "p515-stage-pb15-20261119T1407550800-87f5df8cf3b949da9d473b7dc2d63ea2"
RUN_DIR = RUNS_ROOT / f"run_{RUN_ID}"
DATA_ROOT = ROOT / "artifacts/p515_d17_anomaly_wave_shrink_d18_review_20261118"
R2_ROOT = ROOT / "artifacts/p515_d18_native_archive_preview_20261119/native/run"
SCREEN_PATH = DATA_ROOT / "screen.py"
UNIVERSE_PATH = DATA_ROOT / "00_全范围处置.csv"
PREFILTER_PATH = DATA_ROOT / "01_量价初筛.csv"
READER_PATH = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/data_layer_interface_current/DATA_LAYER_INTERFACE.py")
RUNTIME_PATH = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-panel-throughput-storage-20261118-r3/api/app")
PANEL_PATH = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据/selector_ready_panels/data_layer_daily_formula_increment_update_v1/selector_ready_current_to_20261117_qfq_dce3fe65d342f590/selector_ready_current_to_20261117.parquet")
EXPECTED_GENERATION = "dce3fe65d342f59043dc11e032a2058cb67b3a7a0db0f70759c7c337d6f66673"
EXPECTED_INPUT_SHA = "40e0e5e15be05920c8d959b5e5147185000bf9af43c0a1a74760832918fecfa4"
EXPECTED_READER_SHA = "4f096d4995aa862296e0b918ca9dd136bd35dd0b1309efa1239f312be5f25565"
EXPECTED_UNIVERSE_SHA = "5be9f005f4fdf50cc14dde4e4d7efdb66ae3753b1e323b0f3f8e43832810e89c"
EXPECTED_R2_SHA = "0c5f20e93072701c2c06d9cddcf4b28832888028b67eece2d7fc14be1ccb1381"
EXPECTED_WIRING_SHA = "873edeaa5c3d6d751a96cc17a94b48e792b43382b3266301915e10e7081cedbd"
EXPECTED_R2_CAL_SHA = "2610bb6e8054351d7066fcfc5876f083d0e43c938f3bea43b17a592d08498a6d"
EXPECTED_ADAPTER_V3_SHA = "ebe66235d2f27c0e84bd1680cc368f90ef0be7e2d6b215fc5cb1727604656d65"
PROMPT_PATH = RUNS_ROOT / "PROMPT_ORIGINAL.md"
R2_PATH = R2_ROOT / "R2_FROZEN_event_rules.py"
WIRING_PATH = R2_ROOT / "FROZEN_wiring.py"
R2_CAL_PATH = R2_ROOT / "R2_EFFECTIVE_CALENDAR.json"
ORIGINAL_CAL_PATH = R2_ROOT / "ORIGINAL_EXCHANGE_CALENDARS.json"
SCREEN_RECEIPT_PATH = DATA_ROOT / "SCREEN_RECEIPT.json"
D17_SCOPE_PATH = DATA_ROOT / "D17_REPLAY_SCOPE.json"
OHLCV = ("open", "high", "low", "close", "volume")
FEATURE_NAMES = (
    "pullback_stage_k", "d_close_to_wave_high_pct", "d_low_to_wave_high_pct",
    "max_close_dd_so_far_pct", "d_vol_over_upwave_mean",
    "pb_mean_vol_over_upwave_mean", "pb_min_vol_over_upwave_mean",
    "d_close_to_anchor_low_pct", "stage_is_early", "stage_is_extended",
)
TERMINAL_LABELS = {"FAILED_RISK": 0, "FAILED_SUPPORT": 0,
                   "SUCCESS_RESTART": 1, "EXPIRED_PULLBACK": 0}
EARLIEST = "20240408"
LATEST = "20261117"
DECISION_START = "20260701"
DECISION_END = "20261030"
MAX_ROWS_PER_SECURITY = 634
MAX_PROCESSES = 4
MODEL_COUNTER_KEYS = (
    "model_fit", "preprocessing_fit", "model_api", "new_probability",
    "static_new_score", "model_deserialization", "tuning",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                              indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def append_jsonl(path: Path, value, durable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(value, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False) + "\n")
        f.flush()
        if durable:
            f.flush()
            os.fsync(f.fileno())


def durable_jsonl(path: Path, value) -> None:
    append_jsonl(path, value, durable=True)


def write_jsonl(path: Path, rows, append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(jsonable(row), ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def jsonable(v):
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        x = float(v)
        return x if math.isfinite(x) else None
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if pd.isna(v):
        return None
    return v


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"IMPORT_SPEC_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def normalize_date(v) -> str:
    if hasattr(v, "strftime"):
        return v.strftime("%Y%m%d")
    s = str(v).strip()
    if len(s) >= 10 and s[4] == "-":
        s = s[:10].replace("-", "")
    if len(s) > 8 and s[:8].isdigit():
        s = s[:8]
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"INVALID_TRADE_DATE:{v!r}")
    return s


def load_universe() -> pd.DataFrame:
    raw = UNIVERSE_PATH.read_bytes()
    if sha256_bytes(raw) != EXPECTED_UNIVERSE_SHA:
        raise RuntimeError("D17_UNIVERSE_SHA_MISMATCH")
    df = pd.read_csv(UNIVERSE_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"代码", "简称", "简称来源日", "市场", "可见上市日", "结构初筛", "合格锚数"}
    if set(df.columns) != required:
        raise RuntimeError(f"D17_UNIVERSE_COLUMNS_MISMATCH:{list(df.columns)!r}")
    if len(df) != 5572 or df["代码"].nunique() != 5572:
        raise RuntimeError(f"D17_UNIVERSE_CARDINALITY:{len(df)}:{df['代码'].nunique()}")
    codes = df["代码"].astype(str)
    if not codes.str.fullmatch(r"\d{6}\.(SH|SZ|BJ)").all():
        raise RuntimeError("D17_UNIVERSE_BAD_CODE")
    return df.sort_values("代码", kind="stable").reset_index(drop=True)


def reader_setup():
    sys.path.insert(0, str(RUNTIME_PATH))
    reader = load_module(READER_PATH, "p515_v4_authoritative_reader")
    meta = reader.get_panel_meta(panel_path=PANEL_PATH, include_dates=False)
    if meta.get("generation_id") != EXPECTED_GENERATION:
        raise RuntimeError("READER_GENERATION_MISMATCH")
    if meta.get("input_sha256") != EXPECTED_INPUT_SHA:
        raise RuntimeError("READER_INPUT_SHA_MISMATCH")
    if str(meta.get("panel_path")) != str(PANEL_PATH):
        raise RuntimeError("READER_PANEL_PATH_MISMATCH")
    basis = meta.get("market_basis", {}).get("A")
    expected_basis = {"price_basis": "QFQ_ASOF", "volume_basis": "QFQ_EVENT_VOLUME",
                      "amount_basis": "RAW_TURNOVER", "asof_date": int(LATEST)}
    if basis != expected_basis:
        raise RuntimeError(f"READER_QFQ_BASIS_MISMATCH:{basis!r}")
    manifest_path = Path(meta["manifest_path"])
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if (manifest.get("generation_id") != EXPECTED_GENERATION
            or manifest.get("input_sha256") != EXPECTED_INPUT_SHA
            or str(manifest.get("target_date")) != LATEST):
        raise RuntimeError("READER_MANIFEST_IDENTITY_MISMATCH")
    return reader, meta, manifest_path, manifest_raw


def frozen_sources() -> dict:
    paths = [UNIVERSE_PATH, PREFILTER_PATH, SCREEN_PATH, R2_PATH, WIRING_PATH,
             R2_CAL_PATH, ORIGINAL_CAL_PATH, READER_PATH, SCREEN_RECEIPT_PATH,
             D17_SCOPE_PATH, PROMPT_PATH]
    idents = {p.name: file_identity(p) for p in paths}
    expected = {
        UNIVERSE_PATH.name: EXPECTED_UNIVERSE_SHA,
        SCREEN_PATH.name: "5bdbef2fe8dd33016bae095f3984dab06e9a0b3f9f04647e13ce37a5cc9a32ae",
        R2_PATH.name: EXPECTED_R2_SHA,
        WIRING_PATH.name: EXPECTED_WIRING_SHA,
        R2_CAL_PATH.name: EXPECTED_R2_CAL_SHA,
        READER_PATH.name: EXPECTED_READER_SHA,
    }
    for name, digest in expected.items():
        if idents[name]["sha256"] != digest:
            raise RuntimeError(f"PINNED_SOURCE_SHA_MISMATCH:{name}:{idents[name]['sha256']}")
    prefilter = pd.read_csv(PREFILTER_PATH, dtype=str, encoding="utf-8-sig").fillna("")
    if "代码" not in prefilter.columns:
        raise RuntimeError("D17_PREFILTER_CODE_COLUMN_MISSING")
    if len(prefilter) != 822 or prefilter["代码"].nunique() != 822:
        raise RuntimeError(f"D17_PREFILTER_CARDINALITY:{len(prefilter)}:{prefilter['代码'].nunique()}")
    d17_scope = json.loads(D17_SCOPE_PATH.read_text(encoding="utf-8"))
    screen_receipt = json.loads(SCREEN_RECEIPT_PATH.read_text(encoding="utf-8"))
    calendar_raw = R2_CAL_PATH.read_bytes()
    calendar = json.loads(calendar_raw)
    if not (isinstance(calendar, list) and calendar == sorted(set(calendar))):
        raise RuntimeError("R2_EFFECTIVE_CALENDAR_FORMAT")
    if calendar[-1] != LATEST or calendar[0] > EARLIEST:
        raise RuntimeError("R2_EFFECTIVE_CALENDAR_BOUNDARY")
    return {
        "files": idents,
        "declared_adapter_v3_sha256": EXPECTED_ADAPTER_V3_SHA,
        "adapter_v3_execution": "NOT_USED_DATA_ONLY_TASK",
        "generation": EXPECTED_GENERATION,
        "reader_input_sha256": EXPECTED_INPUT_SHA,
        "reader_sha256": EXPECTED_READER_SHA,
        "r2_rule_version": "P5146_EVENT_RULE_R2",
        "calendar_start": calendar[0], "calendar_end": calendar[-1],
        "calendar_sessions": len(calendar),
        "d17_screen_dates": screen_receipt.get("date_scope", []),
        "d17_screen_manifest_sha256": screen_receipt.get("manifest_sha256"),
        "d17_screen_generation": screen_receipt.get("generation"),
        "d17_source_script_sha256": d17_scope.get("derived_script_sha256", {}).get("screen.py"),
    }


def ast_bindings() -> dict:
    bindings = {}
    for key, path, wanted in (
        ("screen", SCREEN_PATH, {"valid", "shape_for_anchor", "main"}),
        ("r2", R2_PATH, {"run_symbol"}),
    ):
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        lines = text.splitlines(keepends=True)
        tree = ast.parse(text, filename=str(path))
        funcs = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
                end = getattr(node, "end_lineno", node.lineno)
                source = "".join(lines[node.lineno - 1:end])
                funcs[node.name] = {"line_start": node.lineno, "line_end": end,
                                    "source_sha256": sha256_bytes(source.encode("utf-8")),
                                    "source": source}
        if set(funcs) != wanted:
            raise RuntimeError(f"SOURCE_AST_FUNCTION_SET_MISMATCH:{key}:{set(funcs)}")
        bindings[key] = {"path": str(path), "file_bytes": len(raw),
                         "file_sha256": sha256_bytes(raw), "functions": funcs}
    return bindings


def write_frozen_scope() -> None:
    if RUN_DIR.exists() and any(RUN_DIR.iterdir()):
        raise RuntimeError(f"RUN_DIR_NOT_EMPTY:{RUN_DIR}")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).resolve()
    script_raw = script_path.read_bytes()
    script_copy = RUN_DIR / "CODE_SNAPSHOT.py"
    script_copy.write_bytes(script_raw)
    prompt_dest = RUN_DIR / "PROMPT_ORIGINAL.md"
    shutil.copyfile(PROMPT_PATH, prompt_dest)
    universe = load_universe()
    reader, meta, manifest_path, manifest_raw = reader_setup()
    sources = frozen_sources()
    sources["panel"] = {
        "path": str(PANEL_PATH), "bytes": PANEL_PATH.stat().st_size,
        "manifest_path": str(manifest_path), "manifest_sha256": sha256_bytes(manifest_raw),
        "manifest_bytes": len(manifest_raw),
        "generation_id": meta.get("generation_id"), "input_sha256": meta.get("input_sha256"),
        "market_basis": meta.get("market_basis"), "rows": meta.get("rows"),
        "columns": meta.get("column_names"),
    }
    sources["new_code"] = {"path": str(script_path), "bytes": len(script_raw),
                            "sha256": sha256_bytes(script_raw)}
    sources["prompt_copy"] = file_identity(prompt_dest)
    if sources["prompt_copy"]["sha256"] != sources["files"][PROMPT_PATH.name]["sha256"]:
        raise RuntimeError("PROMPT_COPY_SHA_MISMATCH")
    config = {
        "task_id": "P515_MAC_STAGE_PB15_DATA_MATERIALIZATION_R1_V1",
        "run_id": RUN_ID,
        "created_at": utc_now(),
        "history_start": EARLIEST, "history_end": LATEST,
        "decision_start": DECISION_START, "decision_end": DECISION_END,
        "security_count": len(universe), "max_rows_per_security": MAX_ROWS_PER_SECURITY,
        "columns": list(OHLCV), "parallel_reader_shards": 4,
        "worker_limit": MAX_PROCESSES,
        "feature_names": list(FEATURE_NAMES),
        "feature_encoding": "10 finite float64 little-endian values, struct.pack('<10d'), exactly 80 bytes",
        "row_key": ["security", "decision_date", "rule_version", "parent_id", "pb_id", "input_sha256"],
        "source_cutoff_assumption": "D close, 18:00 Asia/Shanghai; retrospective protocol assumption, not historical publication proof",
        "label_cutoff": LATEST,
        "labels": TERMINAL_LABELS,
        "model_counters": {k: 0 for k in MODEL_COUNTER_KEYS},
        "fit_permission": False,
        "true_unexposed_validation_rows": 0,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    atomic_json(RUN_DIR / "RUN_CONFIG.json", config)
    atomic_json(RUN_DIR / "SOURCE_REFERENCES.json", sources)
    atomic_json(RUN_DIR / "SOURCE_AST_BINDING.json", ast_bindings())
    try:
        import psutil
        memory = {"total_bytes": psutil.virtual_memory().total,
                  "available_bytes": psutil.virtual_memory().available,
                  "percent_used": psutil.virtual_memory().percent}
    except Exception:
        memory = {"status": "PSUTIL_UNAVAILABLE"}
    disk = shutil.disk_usage(RUNS_ROOT)
    runtime = {"python_executable": sys.executable, "python_version": sys.version,
        "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "memory": memory, "artifact_disk_free_bytes": disk.free,
        "numpy_version": np.__version__, "pandas_version": pd.__version__,
        "configured_workers": MAX_PROCESSES}
    atomic_json(RUN_DIR / "RUNTIME_ENVIRONMENT.json", runtime)
    atomic_json(RUN_DIR / "PRE_READ_FREEZE.json", {
        "task_id": config["task_id"], "run_id": RUN_ID, "frozen_at": utc_now(),
        "state": "FROZEN_BEFORE_FIRST_ROW_READ", "first_selector_row_read": False,
        "new_code_sha256": sha256_bytes(script_raw),
        "source_references_sha256": sha256_bytes((RUN_DIR / "SOURCE_REFERENCES.json").read_bytes()),
        "source_ast_binding_sha256": sha256_bytes((RUN_DIR / "SOURCE_AST_BINDING.json").read_bytes()),
        "runtime_environment_sha256": sha256_bytes((RUN_DIR / "RUNTIME_ENVIRONMENT.json").read_bytes()),
        "run_config_sha256": sha256_bytes((RUN_DIR / "RUN_CONFIG.json").read_bytes()),
        "universe_codes": 5572, "universe_source_sha256": EXPECTED_UNIVERSE_SHA,
        "decision_scope": [DECISION_START, DECISION_END],
        "reader_scope": [EARLIEST, LATEST], "columns": list(OHLCV),
        "read_shards": 4, "models_all_zero": True,
    })
    atomic_json(RUN_DIR / "RUN_START.json", {
        "run_id": RUN_ID, "started_at": utc_now(), "state": "FROZEN_NOT_YET_READ",
        "writer_worktree_head": os.environ.get("P515_WRITER_BASELINE", "e6782c7eefb245f00e8c4db6d01ddab77c92475b"),
        "new_code_sha256": sha256_bytes(script_raw), "reader_row_reads": 0,
        "model_counters": {k: 0 for k in MODEL_COUNTER_KEYS},
    })


def _canonical_bar_sha(code: str, date: str, values: list[float]) -> str:
    payload = json.dumps([code, date, *values], ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    return sha256_bytes(payload)


def _csv_append_writer(path: Path, fieldnames: list[str]):
    exists = path.exists() and path.stat().st_size > 0
    f = path.open("a" if exists else "w", encoding="utf-8-sig", newline="")
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    if not exists:
        w.writeheader()
    return f, w


def _date_to_idx(calendar: list[str]) -> dict[str, int]:
    return {d: i for i, d in enumerate(calendar)}


def _screen_one_date(code: str, d: str, dates: list[str], bar_by_date: dict,
                     screen_mod, d17_meta: dict) -> tuple[dict, list[dict]]:
    gdates = dates[-31:]
    b = np.array([bar_by_date.get(x, (np.nan,) * 5) for x in gdates], dtype=float)
    mask = screen_mod.valid(b)
    hit, rejects, anchors = [], [], []
    found_anchor = False
    for a in range(len(gdates) - 11, len(gdates) - 1):
        if not (mask[a] and mask[a - 1] and all(mask[a:])):
            continue
        o, h, lo, c, v = b[a]
        prev = b[a - 1, 3]
        vr5 = v / float(screen_mod.mean(b[a - 5:a, 4])) if all(mask[a - 5:a]) else None
        vr20 = v / float(screen_mod.median(b[a - 20:a, 4])) if all(mask[a - 20:a]) else None
        ret = c / prev - 1
        anomaly = vr5 is not None and ret >= 0.02 and vr5 >= 2
        build_raw = (vr20 is not None and vr20 >= 1.5 and c > o and c > prev
                     and c / b[a - 20, 3] - 1 <= 0.25)
        confirmed = any(b[j, 3] > h for j in range(a + 1, len(b)))
        build = bool(build_raw and confirmed)
        if not (anomaly or build_raw):
            continue
        found_anchor = True
        status, info = screen_mod.shape_for_anchor(b, a, anomaly, build)
        rejects.append(status)
        item = {
            "security": code, "decision_date": d, "anchor_date": gdates[a],
            "anchor_index_in_31": a, "trigger_return": float(ret),
            "trigger_vr5": None if vr5 is None else float(vr5),
            "trigger_vr20": None if vr20 is None else float(vr20),
            "anomaly_trigger": bool(anomaly), "build_raw_trigger": bool(build_raw),
            "build_confirmed_by_D": bool(build), "shape_status": status,
            "screen_anchor_pb_date": gdates[info["pb"]] if info else None,
            "screen_anchor_wave_start": gdates[info["wave_start"]] if info else None,
            "screen_anchor_confirmation": gdates[info["confirmation"]] if info and info["confirmation"] is not None else None,
            "screen_anchor_high": None if not info else float(info["wave_high"]),
            "screen_anchor_low": None if not info else float(info["support"]),
            "screen_anchor_upwave_mean_volume": None if not info else float(info["wave_avg"]),
            "screen_anchor_pb_mean_volume": None if not info else float(info["pullback_avg"]),
            "screen_anchor_type": None if not info else info["type"],
            "screen_window_start": gdates[0], "screen_window_end": gdates[-1],
        }
        anchors.append(item)
        if info is not None:
            hit.append((info, ret, vr5, vr20, item))
    if not hit:
        priority = ("PULLBACK_NOT_SHRUNK", "ANCHOR_BROKEN", "RESTARTED",
                    "NO_ACTIVE_PULLBACK", "UNCONFIRMED_WAVE")
        status = next((x for x in priority if x in rejects), None)
        if status is None:
            status = "UNKNOWN_SHORT_OR_BAD_HISTORY" if not mask.all() else "NO_ANOMALY_OR_WAVE"
        selected = None
    else:
        info, ret, vr5, vr20, item = max(hit, key=lambda x: (x[0]["pb"], x[0]["a"]))
        item["selected"] = True
        for anchor in anchors:
            anchor.setdefault("selected", False)
        selected = item
        status = "PASS"
    if selected is None:
        for anchor in anchors:
            anchor.setdefault("selected", False)
    daily = {
        "security": code, "decision_date": d, "screen_status": status,
        "has_trigger_anchor": found_anchor, "qualifying_anchor_count": len(hit),
        "trigger_anchor_count": len(anchors),
        "selected_anchor_date": None if selected is None else selected["anchor_date"],
        "selected_screen_pb_date": None if selected is None else selected["screen_anchor_pb_date"],
        "selected_screen_wave_start": None if selected is None else selected["screen_anchor_wave_start"],
        "history_valid_days_31": int(mask.sum()), "screen_window_start": gdates[0],
        "screen_window_end": gdates[-1],
        "d17_structure_disposition_reference_only": d17_meta.get("结构初筛"),
    }
    return daily, anchors


def _feature_values(code: str, d: str, obs: dict, bar_by_date: dict,
                    calendar: list[str], cal_idx: dict[str, int]) -> tuple[list[float] | None, dict]:
    k = obs.get("pullback_sessions")
    h = obs.get("frozen_wave_high")
    l = obs.get("origin_low")
    wave_start = obs.get("wave_start")
    # In R2 observation rows candidate_date is the observation D. The first
    # pullback session is wave_end_confirmed_at; the pullback table's
    # candidate_date uses that latter meaning, so keep the two namespaces apart.
    pb_start = obs.get("wave_end_confirmed_at")
    if not (isinstance(k, int) and 1 <= k <= 8):
        return None, {"reason": "K_OUTSIDE_1_8", "k": k}
    if not all(isinstance(x, str) and x in cal_idx for x in (d, wave_start, pb_start)):
        return None, {"reason": "EVENT_DATE_NOT_IN_FROZEN_CALENDAR"}
    if not (isinstance(h, (int, float)) and math.isfinite(float(h)) and float(h) > 0
            and isinstance(l, (int, float)) and math.isfinite(float(l)) and float(l) > 0):
        return None, {"reason": "WAVE_HIGH_OR_ORIGIN_LOW_NOT_POSITIVE"}
    start_i, pb_i, d_i = cal_idx[wave_start], cal_idx[pb_start], cal_idx[d]
    if not (start_i < pb_i <= d_i):
        return None, {"reason": "WAVE_PB_D_ORDER_INVALID"}
    u_dates = calendar[start_i:pb_i]
    p_dates = calendar[pb_i:d_i + 1]
    if len(p_dates) != k:
        return None, {"reason": "PB_SESSION_COUNT_CALENDAR_MISMATCH", "expected_k": k,
                      "calendar_pb_count": len(p_dates)}
    if not u_dates or any(x not in bar_by_date for x in u_dates + p_dates):
        return None, {"reason": "FEATURE_SOURCE_ROW_MISSING", "u_dates": u_dates, "p_dates": p_dates}
    u = np.array([bar_by_date[x] for x in u_dates], dtype=float)
    p = np.array([bar_by_date[x] for x in p_dates], dtype=float)
    if (not np.isfinite(u).all() or not np.isfinite(p).all()
            or not all(screen_valid_bar(row) for row in np.vstack([u, p]))):
        return None, {"reason": "FEATURE_SOURCE_BAR_INVALID", "u_dates": u_dates, "p_dates": p_dates}
    u_mean = float(statistics.mean(float(x) for x in u[:, 4]))
    if not math.isfinite(u_mean) or u_mean <= 0:
        return None, {"reason": "UPWAVE_MEAN_VOLUME_NOT_POSITIVE"}
    day = np.array(bar_by_date[d], dtype=float)
    pb_closes = p[:, 3]
    features = [
        float(k),
        (float(day[3]) - float(h)) / float(h),
        (float(day[2]) - float(h)) / float(h),
        max(0.0, float(np.max((float(h) - pb_closes) / float(h)))),
        float(day[4]) / u_mean,
        float(statistics.mean(float(x) for x in p[:, 4])) / u_mean,
        float(np.min(p[:, 4])) / u_mean,
        (float(day[3]) - float(l)) / float(l),
        float(k in (1, 2)),
        float(4 <= k <= 8),
    ]
    if len(features) != 10 or not all(math.isfinite(x) for x in features):
        return None, {"reason": "NONFINITE_FEATURE"}
    return features, {
        "feature_u_start": u_dates[0], "feature_u_end": u_dates[-1],
        "feature_u_dates": u_dates, "feature_p_start": p_dates[0],
        "feature_p_dates": p_dates, "feature_d_date": d,
        "wave_high_h": float(h), "anchor_low_l": float(l),
        "upwave_mean_volume": u_mean,
        "pullback_mean_volume": float(statistics.mean(float(x) for x in p[:, 4])),
        "pullback_min_volume": float(np.min(p[:, 4])),
    }


def screen_valid_bar(values) -> bool:
    a = np.asarray(values, dtype=float)
    if a.shape != (5,) or not np.isfinite(a).all() or np.min(a) <= 0:
        return False
    o, h, l, c, v = a
    return bool(l <= min(o, c) <= max(o, c) <= h)


def _shard_worker(payload: dict) -> dict:
    shard_id = payload["shard_id"]
    run_dir = Path(payload["run_dir"])
    shard_dir = run_dir / "shards" / f"shard_{shard_id:02d}"
    shard_dir.mkdir(parents=True, exist_ok=True)
    state_path = shard_dir / "SHARD_CHECKPOINT.json"
    source_sha = payload["source_sha256"]
    if sha256_bytes(SCREEN_PATH.read_bytes()) != source_sha["screen.py"]:
        raise RuntimeError("SCREEN_SOURCE_CHANGED_AFTER_FREEZE")
    if sha256_bytes(R2_PATH.read_bytes()) != source_sha["R2_FROZEN_event_rules.py"]:
        raise RuntimeError("R2_SOURCE_CHANGED_AFTER_FREEZE")
    screen_mod = load_module(SCREEN_PATH, f"screen_replay_{shard_id}")
    r2_mod = load_module(R2_PATH, f"r2_replay_{shard_id}")
    df = payload["frame"].copy()
    df["ts_code"] = df["ts_code"].astype(str)
    df["trade_date"] = df["trade_date"].map(normalize_date)
    df = df.sort_values(["ts_code", "trade_date"], kind="stable")
    shard_codes = payload["codes"]
    expected_code_set = set(shard_codes)
    actual_code_set = set(df["ts_code"].unique())
    extra_codes = sorted(actual_code_set - expected_code_set)
    if extra_codes:
        raise RuntimeError(f"READER_RETURNED_UNREQUESTED_CODES:{extra_codes[:5]}")
    duplicated = set(df.loc[df.duplicated(["ts_code", "trade_date"], keep=False), "ts_code"])
    d17_meta = payload["d17_meta"]
    calendar = payload["r2_calendar"]
    cal_idx = _date_to_idx(calendar)
    screen_dates = payload["screen_dates"]
    decision_dates = payload["decision_dates"]
    screen_date_index = {d: i for i, d in enumerate(screen_dates)}
    stats = Counter()
    coverage_rows = []
    daily_path = shard_dir / "HISTORICAL_SCREEN_DAILY.csv"
    anchors_path = shard_dir / "HISTORICAL_SCREEN_ANCHORS.csv"
    r2_daily_path = shard_dir / "NATIVE_R2_DAILY_STATUS.csv"
    candidates_path = shard_dir / "CANDIDATE_LEDGER.jsonl"
    mothers_path = shard_dir / "R2_MOTHERS.jsonl"
    pullbacks_path = shard_dir / "R2_PULLBACKS.jsonl"
    native_obs_path = shard_dir / "R2_CANDIDATE_MOTHER_DAILY.jsonl"
    witness_path = shard_dir / "BAR_WITNESS.jsonl"
    daily_f = anchors_f = None
    daily_w = anchors_w = None
    daily_f, daily_w = _csv_append_writer(daily_path, [
        "security", "decision_date", "screen_status", "has_trigger_anchor",
        "qualifying_anchor_count", "trigger_anchor_count", "selected_anchor_date",
        "selected_screen_pb_date", "selected_screen_wave_start", "history_valid_days_31",
        "screen_window_start", "screen_window_end", "d17_structure_disposition_reference_only",
    ])
    anchors_f, anchors_w = _csv_append_writer(anchors_path, [
        "security", "decision_date", "anchor_date", "anchor_index_in_31", "trigger_return",
        "trigger_vr5", "trigger_vr20", "anomaly_trigger", "build_raw_trigger",
        "build_confirmed_by_D", "shape_status", "screen_anchor_pb_date",
        "screen_anchor_wave_start", "screen_anchor_confirmation", "screen_anchor_high",
        "screen_anchor_low", "screen_anchor_upwave_mean_volume", "screen_anchor_pb_mean_volume",
        "screen_anchor_type", "screen_window_start", "screen_window_end", "selected",
    ])
    r2_daily_f, r2_daily_w = _csv_append_writer(r2_daily_path, [
        "security", "decision_date", "screen_status", "native_observation_count",
        "r2_disposition", "r2_stage", "parent_id", "event_id", "pb_id",
        "r2_observation_d", "r2_pb_first_date", "pullback_index", "pullback_stage_k",
        "terminal_observed_today", "native_track_count", "native_track_conflict",
        "active_k1_k8", "screen_pass_r2_intersection",
    ])
    mother_docs, pullback_docs, candidate_docs, native_docs = [], [], [], []
    candidate_mothers_all = set()
    source_status_counts = Counter()
    witness = {}
    checkpoint = {"run_id": RUN_ID, "shard_id": shard_id, "state": "RUNNING",
                  "started_at": utc_now(), "source_rows": len(df), "codes": len(shard_codes),
                  "processed_codes": 0, "last_code": None, "reader_call_count": 1,
                  "pure_r2_run_symbol_calls": 0, "decision_rows": 0,
                  "screen_pass_rows": 0, "candidate_rows": 0}
    def flush_shard_buffers():
        for path, rows in ((candidates_path, candidate_docs), (mothers_path, mother_docs),
                           (pullbacks_path, pullback_docs), (native_obs_path, native_docs),
                           (shard_dir / "SOURCE_COVERAGE.jsonl", coverage_rows)):
            if rows:
                write_jsonl(path, rows, append=path.exists())
                rows.clear()
        stats["witness_bar_rows"] += len(witness)
        if witness:
            docs = []
            for _, item in sorted(witness.items()):
                docs.append({**item, "roles": sorted(item["roles"])})
            write_jsonl(witness_path, docs, append=witness_path.exists())
            witness.clear()
        for f in (daily_f, anchors_f, r2_daily_f):
            f.flush()
            os.fsync(f.fileno())
        atomic_json(state_path, checkpoint)

    atomic_json(state_path, checkpoint)
    try:
        grouped = {str(code): grp for code, grp in df.groupby("ts_code", sort=True)}
        for code in shard_codes:
            code = str(code)
            grp = grouped.get(code)
            if grp is None:
                coverage_rows.append({"security": code, "reader_row_count": 0,
                    "unique_trade_dates": 0, "first_trade_date": None, "last_trade_date": None,
                    "valid_ohlcv_count": 0, "duplicate_dates": False,
                    "source_status": "NO_SOURCE_ROWS",
                    "historical_name_identity": "UNKNOWN",
                    "historical_tradability_identity": "UNKNOWN"})
                stats["source_NO_SOURCE_ROWS"] += 1
                source_status_counts["NO_SOURCE_ROWS"] += 1
                for d in decision_dates:
                    result = {"security": code, "decision_date": d,
                        "screen_status": "UNKNOWN_NO_SOURCE_ROWS", "has_trigger_anchor": False,
                        "qualifying_anchor_count": 0, "trigger_anchor_count": 0,
                        "selected_anchor_date": None, "selected_screen_pb_date": None,
                        "selected_screen_wave_start": None, "history_valid_days_31": 0,
                        "screen_window_start": None, "screen_window_end": d,
                        "source_status": "NO_SOURCE_ROWS",
                        "d17_structure_disposition_reference_only": d17_meta[code].get("结构初筛")}
                    daily_w.writerow(result)
                    r2_daily_w.writerow({"security": code, "decision_date": d,
                        "screen_status": result["screen_status"], "native_observation_count": 0,
                        "r2_disposition": "UNKNOWN_NO_SOURCE_ROWS", "active_k1_k8": False,
                        "native_track_count": 0, "native_track_conflict": False,
                        "screen_pass_r2_intersection": False})
                    stats["decision_rows"] += 1
                checkpoint["processed_codes"] += 1
                checkpoint["last_code"] = code
                if checkpoint["processed_codes"] % 50 == 0:
                    flush_shard_buffers()
                continue
            grp = grp.sort_values("trade_date", kind="stable")
            dates = grp["trade_date"].tolist()
            valid_codes = [x for x in dates if x in cal_idx]
            values = grp[list(OHLCV)].astype(float).to_numpy()
            bar_by_date = {d: tuple(float(v) for v in row) for d, row in zip(dates, values)}
            source_status = "OK"
            if code in duplicated:
                source_status = "DUPLICATE_SECURITY_DATE"
            elif len(dates) > MAX_ROWS_PER_SECURITY:
                source_status = "ROW_LIMIT_EXCEEDED"
            elif any(d < EARLIEST or d > LATEST for d in dates):
                source_status = "DATE_OUTSIDE_FROZEN_WINDOW"
            elif len(valid_codes) != len(dates):
                source_status = "DATE_OUTSIDE_R2_CALENDAR"
            coverage_rows.append({
                "security": code, "reader_row_count": len(grp),
                "unique_trade_dates": len(set(dates)),
                "first_trade_date": min(dates) if dates else None,
                "last_trade_date": max(dates) if dates else None,
                "valid_ohlcv_count": sum(screen_valid_bar(x) for x in values),
                "duplicate_dates": code in duplicated,
                "source_status": source_status,
                "historical_name_identity": "UNKNOWN",
                "historical_tradability_identity": "UNKNOWN",
            })
            source_status_counts[source_status] += 1
            if source_status != "OK":
                stats[f"source_{source_status}"] += 1
                for d in decision_dates:
                    daily_w.writerow({"security": code, "decision_date": d,
                        "screen_status": f"UNKNOWN_{source_status}", "has_trigger_anchor": False,
                        "qualifying_anchor_count": 0, "trigger_anchor_count": 0,
                        "selected_anchor_date": None, "selected_screen_pb_date": None,
                        "selected_screen_wave_start": None, "history_valid_days_31": 0,
                        "screen_window_start": None, "screen_window_end": d,
                        "source_status": source_status,
                        "d17_structure_disposition_reference_only": d17_meta[code].get("结构初筛")})
                    r2_daily_w.writerow({"security": code, "decision_date": d,
                        "screen_status": f"UNKNOWN_{source_status}", "native_observation_count": 0,
                        "r2_disposition": f"UNKNOWN_{source_status}", "active_k1_k8": False,
                        "native_track_count": 0, "native_track_conflict": False,
                        "screen_pass_r2_intersection": False})
                    stats["decision_rows"] += 1
                checkpoint["processed_codes"] += 1
                checkpoint["last_code"] = code
                if checkpoint["processed_codes"] % 50 == 0:
                    flush_shard_buffers()
                continue
            rows = [{"trade_date": d, **dict(zip(OHLCV, row))}
                    for d, row in zip(dates, values)]
            observations, native_candidates, families, pullbacks = r2_mod.run_symbol(code, rows, calendar)
            stats["pure_r2_run_symbol_calls"] += 1
            obs_by_date = defaultdict(list)
            for observation in observations:
                if observation.get("candidate_date") is not None:
                    obs_by_date[str(observation["candidate_date"])].append(observation)
            pb_by_id = {str(p["pullback_id"]): p for p in pullbacks if p.get("pullback_id")}
            per_code_screen = {}
            active_native_by_date = defaultdict(list)
            native_track_count_by_date = {}
            for d in decision_dates:
                # Frozen script's rule: a 31-day common window is chosen from panel dates
                # with majority coverage across the fixed 5,572-code universe.
                seen_days = [x for x in screen_dates if x <= d]
                if len(seen_days) < 31:
                    result = {"security": code, "decision_date": d,
                              "screen_status": "UNKNOWN_SHORT_OR_BAD_HISTORY",
                              "has_trigger_anchor": False, "qualifying_anchor_count": 0,
                              "trigger_anchor_count": 0, "selected_anchor_date": None,
                              "selected_screen_pb_date": None, "selected_screen_wave_start": None,
                              "history_valid_days_31": 0, "screen_window_start": None,
                              "screen_window_end": d,
                              "d17_structure_disposition_reference_only": d17_meta[code].get("结构初筛")}
                    anchor_rows = []
                else:
                    result, anchor_rows = _screen_one_date(code, d, seen_days[-31:], bar_by_date, screen_mod, d17_meta[code])
                result["source_status"] = "OK"
                daily_w.writerow(result)
                for ar in anchor_rows:
                    anchors_w.writerow(ar)
                stats["decision_rows"] += 1
                if result["screen_status"] == "PASS":
                    stats["screen_pass_rows"] += 1
                    per_code_screen[d] = (result, anchor_rows)
                obs_list = obs_by_date.get(d, [])
                unique_tracks = {(o.get("family_id"), o.get("pullback_id")) for o in obs_list}
                native_track_count_by_date[d] = len(unique_tracks)
                for obs in obs_list:
                    k = obs.get("pullback_sessions")
                    active = bool(obs.get("pullback_id") and obs.get("stage") == "SAME_EVENT_PULLBACK"
                                  and isinstance(k, int) and 1 <= k <= 8
                                  and not obs.get("terminal_observed_today"))
                    if active:
                        active_native_by_date[d].append(obs)
                    if len(unique_tracks) > 1:
                        disposition = "MULTI_NATIVE_TRACK_CONFLICT"
                    elif obs.get("terminal_observed_today") or obs.get("stage") in (
                            "RESTART_AFTER_PULLBACK", "PULLBACK_EXPIRED", "STRUCTURE_FAILED",
                            "DISTRIBUTION_RISK_CANDIDATE"):
                        disposition = "TERMINAL_OR_NO_ACTIVE_PB"
                    elif obs.get("stage") == "ADVANCE_LATE_ACTIVITY":
                        disposition = "LATE_ACTIVITY_NO_MOTHER"
                    elif not obs.get("pullback_id"):
                        disposition = "ACTIVE_MOTHER_NO_PB"
                    elif isinstance(k, int) and k > 8:
                        disposition = "ACTIVE_K_GT_8"
                    elif active:
                        disposition = "ACTIVE_K1_K8"
                    else:
                        disposition = "R2_OBSERVATION_OUTSIDE_ACTIVE_PB_SCOPE"
                    if result["screen_status"] == "PASS" and disposition == "ACTIVE_K1_K8":
                        stats["screen_pass_r2_intersection_rows"] += 1
                        if not active:
                            disposition = "ACTIVE_K1_K8_TERMINAL_TODAY"
                    r2_daily_w.writerow({"security": code, "decision_date": d,
                        "screen_status": result["screen_status"], "native_observation_count": len(obs_list),
                        "r2_disposition": disposition, "r2_stage": obs.get("stage"),
                        "parent_id": obs.get("family_id"), "event_id": obs.get("event_id"),
                        "pb_id": obs.get("pullback_id"), "r2_observation_d": obs.get("candidate_date"),
                        "r2_pb_first_date": obs.get("wave_end_confirmed_at"),
                        "pullback_index": obs.get("pullback_index"), "pullback_stage_k": k,
                        "terminal_observed_today": obs.get("terminal_observed_today"),
                        "active_k1_k8": active,
                        "screen_pass_r2_intersection": result["screen_status"] == "PASS" and active})
                if not obs_list:
                    prior_mothers = [fm for fm in families
                        if fm.get("origin_key_k_date") is not None
                        and str(fm.get("origin_key_k_date")) <= d
                        and ((fm.get("end_date") is not None and str(fm.get("end_date")) <= d)
                             or (fm.get("end_date") is None and fm.get("observed_boundary_date") is not None
                                 and str(fm.get("observed_boundary_date")) <= d))]
                    latest_prior = max(prior_mothers, key=lambda x: str(x.get("observed_boundary_date") or x.get("end_date"))) if prior_mothers else {}
                    if latest_prior:
                        prior_status = "PRIOR_MOTHER_TERMINAL" if latest_prior.get("outcome") in r2_mod.MATURE_FAMILY else "PRIOR_MOTHER_UNKNOWN_END"
                    else:
                        prior_status = "NO_MOTHER_OBSERVED_BY_D"
                    r2_daily_w.writerow({"security": code, "decision_date": d,
                        "screen_status": result["screen_status"], "native_observation_count": 0,
                        "r2_disposition": prior_status,
                        "parent_id": latest_prior.get("family_id"),
                        "event_id": latest_prior.get("event_id"),
                        "pb_id": latest_prior.get("last_pullback_id"),
                        "active_k1_k8": False,
                        "native_track_count": 0, "native_track_conflict": False,
                        "screen_pass_r2_intersection": False})
            # Model-ready development observations are the intersection of historical original
            # prefilter PASS and actual R2 active K1-K8. Identities remain separately recorded.
            code_candidates = []
            for d in decision_dates:
                if d not in per_code_screen or not active_native_by_date.get(d):
                    continue
                result, anchor_rows = per_code_screen[d]
                for obs in active_native_by_date[d]:
                    feature_values, source = _feature_values(code, d, obs, bar_by_date, calendar, cal_idx)
                    pb = pb_by_id.get(str(obs.get("pullback_id")), {})
                    outcome = pb.get("outcome")
                    if outcome in TERMINAL_LABELS:
                        label = TERMINAL_LABELS[outcome]
                        label_status = "MATURED_TERMINAL"
                    elif outcome == "UNKNOWN_OPEN_AT_SNAPSHOT":
                        label = None
                        label_status = "PENDING"
                    else:
                        label = None
                        label_status = "UNKNOWN_OR_UNRESOLVED"
                    all_anchor_dates = [x["anchor_date"] for x in anchor_rows]
                    all_screen_pb_dates = [x.get("screen_anchor_pb_date") for x in anchor_rows]
                    selected = next((x for x in anchor_rows if x.get("selected")), None)
                    raw_key = [code, d, r2_mod.RULE, obs.get("family_id"), obs.get("pullback_id")]
                    pb_first = obs.get("wave_end_confirmed_at")
                    candidate = {
                        "candidate_id": sha256_bytes(json.dumps(raw_key, separators=(",", ":")).encode()),
                        "security": code, "decision_date": d, "rule_version": r2_mod.RULE,
                        "parent_id": obs.get("family_id"), "event_id": obs.get("event_id"),
                        "pb_id": obs.get("pullback_id"), "pullback_index": obs.get("pullback_index"),
                        "pullback_stage_k": obs.get("pullback_sessions"),
                        "screen_status": result["screen_status"],
                        "screen_selected_anchor_date": None if selected is None else selected.get("anchor_date"),
                        "screen_selected_pb_date": None if selected is None else selected.get("screen_anchor_pb_date"),
                        "screen_all_anchor_dates": all_anchor_dates,
                        "screen_all_pb_dates": all_screen_pb_dates,
                        "r2_origin_date": obs.get("origin_key_k_date"),
                        "r2_wave_start": obs.get("wave_start"),
                        "r2_wave_end": obs.get("wave_end"),
                        "r2_wave_end_confirmed_at": pb_first,
                        "r2_observation_d": obs.get("candidate_date"),
                        "r2_pb_first_date": pb_first,
                        "native_track_count": native_track_count_by_date.get(d, 0),
                        "native_track_conflict": native_track_count_by_date.get(d, 0) > 1,
                        "screen_selected_anchor_equals_r2_origin": bool(selected and selected.get("anchor_date") == obs.get("origin_key_k_date")),
                        "screen_any_anchor_equals_r2_origin": bool(obs.get("origin_key_k_date") in all_anchor_dates),
                        "screen_selected_pb_equals_r2_pb": bool(selected and selected.get("screen_anchor_pb_date") == pb_first),
                        "screen_any_pb_equals_r2_pb": bool(pb_first in all_screen_pb_dates),
                        "native_track_count": native_track_count_by_date.get(d, 0),
                        "native_track_conflict": native_track_count_by_date.get(d, 0) > 1,
                        "terminal_outcome": outcome,
                        "label": label, "label_status": label_status,
                        "label_end_date": pb.get("end_date"),
                        "label_observed_boundary_date": pb.get("observed_boundary_date"),
                        "label_source": pb.get("stage_label_source", "RESEARCH_RULE_WEAK_LABEL"),
                        "feature_status": "FEATURE_OK" if feature_values is not None else "FEATURE_FAILED",
                        "feature_failure": None if feature_values is not None else source,
                        "feature_source": source,
                        "features": feature_values,
                        "r2_observation": {k: obs.get(k) for k in (
                            "candidate_date", "stage", "family_id", "event_id", "origin_key_k_date",
                            "origin_low", "wave_start", "wave_end", "wave_end_confirmed_at",
                            "frozen_wave_high", "pullback_id", "pullback_index", "pullback_sessions",
                            "first_pullback_observation", "terminal_observed_today", "feature_available_at",
                        )},
                        "generation": EXPECTED_GENERATION, "run_id": RUN_ID,
                    }
                    if feature_values is not None:
                        packed = struct.pack("<10d", *feature_values)
                        if len(packed) != 80:
                            raise AssertionError("PACKED_FEATURE_BYTES_NOT_80")
                        candidate["input_sha256"] = sha256_bytes(packed)
                        candidate["input_hex"] = packed.hex()
                    else:
                        candidate["input_sha256"] = None
                        candidate["input_hex"] = None
                    code_candidates.append(candidate)
                    stats["candidate_rows"] += 1
            # An active screen/R2 intersection is a candidate even when one of its
            # ten feature fields cannot be materialized; preserve its mother and PB.
            candidate_mothers = {x["parent_id"] for x in code_candidates}
            candidate_mothers_all.update(candidate_mothers)
            # Keep every mother's lifecycle and the exact event bars needed to re-run its pure R2
            # state, plus the screen window and feature U/P witnesses for its candidate rows.
            relevant_obs = [o for o in observations if o.get("family_id") in candidate_mothers]
            relevant_families = [x for x in families if x.get("family_id") in candidate_mothers]
            relevant_pbs = [x for x in pullbacks if x.get("family_id") in candidate_mothers]
            # Preserve all native mother/PB summaries, including expired, rejected,
            # unresolved and non-candidate events; only dense daily states and bar
            # witnesses are restricted to actual screen/R2 candidate mothers.
            mother_docs.extend(jsonable(x) for x in families)
            pullback_docs.extend(jsonable(x) for x in pullbacks)
            native_docs.extend(jsonable(x) for x in relevant_obs)
            for cand in code_candidates:
                candidate_docs.append(jsonable(cand))
                # 31-bar proof for the actual historical PASS that admitted this row.
                pass_d = cand["decision_date"]
                pass_dates = screen_dates[:screen_date_index[pass_d] + 1][-31:]
                for bd in pass_dates:
                    if bd in bar_by_date:
                        witness.setdefault((code, bd), {"security": code, "trade_date": bd,
                            "bar": list(bar_by_date[bd]), "row_sha256": _canonical_bar_sha(code, bd, list(bar_by_date[bd])),
                            "roles": set()})["roles"].add("SCREEN_WINDOW")
                fsrc = cand.get("feature_source") or {}
                for bd in fsrc.get("feature_u_dates", []) + fsrc.get("feature_p_dates", []):
                    if bd in bar_by_date:
                        witness.setdefault((code, bd), {"security": code, "trade_date": bd,
                            "bar": list(bar_by_date[bd]), "row_sha256": _canonical_bar_sha(code, bd, list(bar_by_date[bd])),
                            "roles": set()})["roles"].add("FEATURE_U_P")
            if candidate_mothers:
                mother_origin = {m: min(str(o.get("origin_key_k_date")) for o in relevant_obs if o.get("family_id") == m)
                                 for m in candidate_mothers}
                mother_end = {}
                family_by_id = {str(x.get("family_id")): x for x in relevant_families}
                for mother in candidate_mothers:
                    fm = family_by_id.get(str(mother), {})
                    mother_end[mother] = str(fm.get("end_date") or fm.get("observed_boundary_date") or LATEST)
                for mother, origin in mother_origin.items():
                    if origin not in cal_idx:
                        continue
                    start_i = max(0, cal_idx[origin] - 20)
                    end_i = cal_idx.get(mother_end[mother], cal_idx[LATEST])
                    for bd in calendar[start_i:end_i + 1]:
                        if bd in bar_by_date:
                            witness.setdefault((code, bd), {"security": code, "trade_date": bd,
                                "bar": list(bar_by_date[bd]), "row_sha256": _canonical_bar_sha(code, bd, list(bar_by_date[bd])),
                                "roles": set()})["roles"].add("R2_MOTHER_STATE")
            checkpoint["processed_codes"] += 1
            checkpoint["last_code"] = code
            checkpoint["pure_r2_run_symbol_calls"] = stats["pure_r2_run_symbol_calls"]
            checkpoint["decision_rows"] = stats["decision_rows"]
            checkpoint["screen_pass_rows"] = stats["screen_pass_rows"]
            checkpoint["candidate_rows"] = stats["candidate_rows"]
            if checkpoint["processed_codes"] % 50 == 0:
                flush_shard_buffers()
        # Flush remaining rows only after each result is durable and included in the
        # final checkpoint; no per-row fsync loop for high-volume result files.
        flush_shard_buffers()
        checkpoint.update({"state": "SHARD_COMPLETE", "finished_at": utc_now(),
                           "source_status_counts": dict(source_status_counts),
                           "pure_r2_run_symbol_calls": stats["pure_r2_run_symbol_calls"],
                           "decision_rows": stats["decision_rows"],
                           "screen_pass_rows": stats["screen_pass_rows"],
                           "candidate_rows": stats["candidate_rows"],
                           "screen_anchor_rows": len(anchors_path.read_text(encoding="utf-8-sig").splitlines()) - 1,
                           "candidate_mother_count": len(candidate_mothers_all),
                           "witness_bar_rows": stats["witness_bar_rows"]})
        atomic_json(state_path, checkpoint)
    except Exception as exc:
        checkpoint.update({"state": "SHARD_FAILED", "failed_at": utc_now(),
                           "error": repr(exc), "traceback": traceback.format_exc(),
                           "processed_codes": checkpoint.get("processed_codes", 0),
                           "pure_r2_run_symbol_calls": stats["pure_r2_run_symbol_calls"]})
        atomic_json(state_path, checkpoint)
        raise
    finally:
        if daily_f: daily_f.close()
        if anchors_f: anchors_f.close()
    return {"shard_id": shard_id, "state": checkpoint["state"],
            "codes": checkpoint["processed_codes"], "rows": checkpoint["source_rows"],
            "r2_calls": checkpoint["pure_r2_run_symbol_calls"],
            "daily_rows": checkpoint["decision_rows"], "candidates": checkpoint["candidate_rows"],
            "mothers": checkpoint["candidate_mother_count"]}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip(): out.append(json.loads(line))
    return out


def _candidate_row_key(c: dict):
    return (str(c["security"]), str(c["decision_date"]), str(c["rule_version"]),
            str(c["parent_id"]), str(c["pb_id"]), str(c.get("input_sha256") or ""))


def build_folds(run_dir: Path, candidate_rows: list[dict]) -> dict:
    same_day_tracks = defaultdict(set)
    candidate_id_counts = Counter(c["candidate_id"] for c in candidate_rows)
    for c in candidate_rows:
        same_day_tracks[(c["security"], c["decision_date"])].add((c["parent_id"], c["pb_id"]))
    for c in candidate_rows:
        tracks = same_day_tracks.get((c["security"], c["decision_date"]), set())
        c["native_track_conflict"] = bool(c.get("native_track_conflict") or len(tracks) > 1
                                          or candidate_id_counts[c["candidate_id"]] > 1)
        c["model_ready"] = c.get("feature_status") == "FEATURE_OK" and not c["native_track_conflict"]
        c["row_key"] = list(_candidate_row_key(c)) if c.get("input_sha256") else None
    ready = [c for c in candidate_rows if c.get("model_ready")]
    # Group assignment uses the first actual screen-pass/native-active candidate D,
    # even when its feature serialization later fails. This cannot shift a mother
    # into a later month because a field was inconvenient to materialize.
    by_mother = defaultdict(list)
    for c in candidate_rows:
        by_mother[c["parent_id"]].append(c)
    mother_group = {}
    for mother, rows in by_mother.items():
        first_d = min(c["decision_date"] for c in rows)
        month = first_d[4:6]
        group = {"07": "TRAIN_JULY", "08": "HOLDOUT_AUG", "09": "HOLDOUT_SEP", "10": "HOLDOUT_OCT"}.get(month, "OUTSIDE_FIXED_GROUPS")
        mother_group[mother] = {"mother_first_eligible_d": first_d, "group": group}
    for c in candidate_rows:
        m = mother_group.get(c.get("parent_id"))
        c["mother_first_eligible_d"] = None if m is None else m["mother_first_eligible_d"]
        c["development_group"] = None if m is None else m["group"]
    mature = [c for c in ready if c.get("label_status") == "MATURED_TERMINAL"]
    global_stage = []
    stage_bins = {
        "EARLY_K1_K2": lambda k: k in (1, 2),
        "REFERENCE_K3": lambda k: k == 3,
        "EXTENDED_K4_K8": lambda k: 4 <= k <= 8,
    }
    for name, pred in stage_bins.items():
        rows = [c for c in mature if pred(c["pullback_stage_k"])]
        all_m = {c["parent_id"] for c in rows}
        pos_m = {c["parent_id"] for c in rows if c["label"] == 1}
        neg_m = {c["parent_id"] for c in rows if c["label"] == 0}
        global_stage.append({"stage_bucket": name, "mature_rows": len(rows),
            "independent_mothers": len(all_m), "positive_rows": sum(c["label"] == 1 for c in rows),
            "negative_rows": sum(c["label"] == 0 for c in rows),
            "positive_mothers": len(pos_m), "negative_mothers": len(neg_m),
            "positive_negative_mother_intersection": len(pos_m & neg_m),
            "gate_mothers_ge_20": len(all_m) >= 20,
            "gate_positive_mothers_ge_8": len(pos_m) >= 8,
            "gate_negative_mothers_ge_8": len(neg_m) >= 8,
            "stage_gate_pass": len(all_m) >= 20 and len(pos_m) >= 8 and len(neg_m) >= 8})
    fold_specs = [
        ("F1", "HOLDOUT_AUG", "20260731", "20260801", "20260831"),
        ("F2", "HOLDOUT_SEP", "20260831", "20260901", "20260930"),
        ("F3", "HOLDOUT_OCT", "20260930", "20261001", "20261030"),
    ]
    fold_gates, fold_counts, fold_members = [], [], []
    for fid, hold_group, train_cut, hold_start, hold_end in fold_specs:
        hold_mothers = {m for m, g in mother_group.items() if g["group"] == hold_group}
        earliest_hold = min((mother_group[m]["mother_first_eligible_d"] for m in hold_mothers), default=None)
        train_rows, hold_rows = [], []
        for c in candidate_rows:
            group = mother_group[c["parent_id"]]["group"]
            role, reason = "EXCLUDED", "NOT_TRAIN_OR_TARGET_HOLDOUT_GROUP"
            if not c.get("model_ready"):
                reason = "NATIVE_TRACK_CONFLICT" if c.get("native_track_conflict") else "FEATURE_FAILED"
            elif group == "TRAIN_JULY":
                if c["decision_date"] > train_cut:
                    reason = "TRAIN_ROW_AFTER_FOLD_CUTOFF"
                elif c.get("label_status") != "MATURED_TERMINAL":
                    reason = "TRAIN_LABEL_NOT_MATURED"
                elif earliest_hold is None:
                    reason = "NO_TARGET_HOLDOUT_MOTHER"
                elif c["decision_date"] >= earliest_hold:
                    reason = "TRAIN_D_NOT_STRICTLY_BEFORE_EARLIEST_HOLDOUT"
                elif c.get("label_end_date") is None or c["label_end_date"] >= earliest_hold:
                    reason = "TRAIN_LABEL_END_NOT_STRICTLY_BEFORE_EARLIEST_HOLDOUT"
                else:
                    role, reason = "TRAIN", "INCLUDED"
                    train_rows.append(c)
            elif group == hold_group and hold_start <= c["decision_date"] <= hold_end:
                if c.get("label_status") == "MATURED_TERMINAL":
                    role, reason = "HOLDOUT_INPUT", "FIXED_HOLDOUT_GROUP_MATURED"
                    hold_rows.append(c)
                elif c.get("label_status") == "PENDING":
                    role, reason = "HOLDOUT_PENDING", "NOT_PREDICTION_INPUT_UNRESOLVED"
                else:
                    role, reason = "HOLDOUT_UNKNOWN", "NOT_PREDICTION_INPUT_UNKNOWN_LABEL"
            fold_members.append({"fold": fid, "role": role, "reason": reason,
                "candidate_id": c["candidate_id"], "row_key": c.get("row_key"),
                "security": c["security"], "decision_date": c["decision_date"],
                "parent_id": c["parent_id"], "pb_id": c["pb_id"],
                "mother_first_eligible_d": mother_group[c["parent_id"]]["mother_first_eligible_d"],
                "development_group": group, "label_status": c["label_status"],
                "label": c["label"], "label_end_date": c["label_end_date"],
                "native_track_conflict": c.get("native_track_conflict"),
                "input_sha256": c.get("input_sha256"), "feature_values": c.get("features"),
                "sample_weight": None, "holdout_eval_weight": None})
        by_train_mother = Counter(c["parent_id"] for c in train_rows)
        for r in fold_members:
            if r["fold"] == fid and r["role"] == "TRAIN":
                r["sample_weight"] = 1.0 / by_train_mother[r["parent_id"]]
        eval_rows = [c for c in hold_rows if c.get("label_status") == "MATURED_TERMINAL"]
        by_eval_mother = Counter(c["parent_id"] for c in eval_rows)
        for r in fold_members:
            if r["fold"] == fid and r["role"] == "HOLDOUT_INPUT":
                r["holdout_eval_weight"] = 1.0 / by_eval_mother[r["parent_id"]]
        train_classes = {c["label"] for c in train_rows}
        supported_bins = {name for name, pred in stage_bins.items() if any(pred(c["pullback_stage_k"]) for c in train_rows)}
        fold_stage_counts = {}
        for stage_name, pred in stage_bins.items():
            fold_stage_counts[stage_name] = {
                "train_rows": sum(pred(c["pullback_stage_k"]) for c in train_rows),
                "train_mothers": len({c["parent_id"] for c in train_rows if pred(c["pullback_stage_k"])}),
                "holdout_rows": sum(pred(c["pullback_stage_k"]) for c in hold_rows),
                "holdout_mothers": len({c["parent_id"] for c in hold_rows if pred(c["pullback_stage_k"])}),
            }
        gate = {
            "fold": fid, "target_holdout_group": hold_group,
            "earliest_holdout_mother_first_d": earliest_hold,
            "train_rows": len(train_rows), "train_mothers": len(by_train_mother),
            "train_positive_rows": sum(c["label"] == 1 for c in train_rows),
            "train_negative_rows": sum(c["label"] == 0 for c in train_rows),
            "train_positive_mothers": len({c["parent_id"] for c in train_rows if c["label"] == 1}),
            "train_negative_mothers": len({c["parent_id"] for c in train_rows if c["label"] == 0}),
            "holdout_input_rows": len(hold_rows), "holdout_mothers": len({c["parent_id"] for c in hold_rows}),
            "holdout_candidate_rows": sum(1 for c in candidate_rows if c.get("development_group") == hold_group
                                           and hold_start <= c["decision_date"] <= hold_end),
            "holdout_mature_rows": len(eval_rows),
            "holdout_pending_rows": sum(1 for c in candidate_rows if c.get("development_group") == hold_group
                                        and hold_start <= c["decision_date"] <= hold_end
                                        and c["label_status"] == "PENDING"),
            "holdout_unknown_rows": sum(1 for c in candidate_rows if c.get("development_group") == hold_group
                                        and hold_start <= c["decision_date"] <= hold_end
                                        and c["label_status"] == "UNKNOWN_OR_UNRESOLVED"),
            "train_has_both_classes": train_classes == {0, 1},
            "train_has_all_three_stage_buckets": supported_bins == set(stage_bins),
            "stage_counts": fold_stage_counts,
        }
        gate["fold_data_gate_pass"] = bool(gate["train_rows"] > 0 and gate["holdout_input_rows"] > 0
            and gate["holdout_mature_rows"] > 0
            and gate["train_has_both_classes"] and gate["train_has_all_three_stage_buckets"])
        fold_gates.append(gate)
        fold_counts.append({"fold": fid, **{k: gate[k] for k in (
            "target_holdout_group", "earliest_holdout_mother_first_d", "train_rows", "train_mothers",
            "train_positive_rows", "train_negative_rows", "train_positive_mothers",
            "train_negative_mothers", "holdout_input_rows", "holdout_mothers",
            "holdout_candidate_rows", "holdout_mature_rows", "holdout_pending_rows", "holdout_unknown_rows",
            "train_has_both_classes", "train_has_all_three_stage_buckets", "fold_data_gate_pass")}})
    final_rows = mature
    by_final_mother = Counter(c["parent_id"] for c in final_rows)
    final_members = [{"candidate_id": c["candidate_id"], "row_key": c["row_key"],
        "security": c["security"], "decision_date": c["decision_date"],
        "parent_id": c["parent_id"], "pb_id": c["pb_id"], "label": c["label"],
        "label_status": c["label_status"], "label_end_date": c["label_end_date"],
        "input_sha256": c["input_sha256"], "features": c["features"],
        "sample_weight": 1.0 / by_final_mother[c["parent_id"]]} for c in final_rows]
    # Save exact row bytes in stable key order. Candidate IDs and input hashes are not model scores.
    sorted_ready = sorted(ready, key=_candidate_row_key)
    bin_path = run_dir / "MODEL_INPUTS_10_F64LE.bin"
    index_rows = []
    with bin_path.open("wb") as f:
        for idx, c in enumerate(sorted_ready):
            raw = bytes.fromhex(c["input_hex"])
            if len(raw) != 80 or sha256_bytes(raw) != c["input_sha256"]:
                raise RuntimeError(f"INPUT_BINARY_REVALIDATION_FAILED:{c['candidate_id']}")
            f.write(raw)
            index_rows.append({"input_row_index": idx, "byte_offset": idx * 80,
                "byte_length": 80, "candidate_id": c["candidate_id"], "row_key": c["row_key"],
                "input_sha256": c["input_sha256"], "features": c["features"]})
    with (run_dir / "MODEL_INPUT_INDEX.jsonl").open("w", encoding="utf-8") as f:
        for row in index_rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    with (run_dir / "CANDIDATE_LEDGER.jsonl").open("w", encoding="utf-8") as f:
        for row in sorted(candidate_rows, key=lambda x: (x["security"], x["decision_date"], x["candidate_id"])):
            f.write(json.dumps(jsonable(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    for name, rows in [
        ("STAGE_GLOBAL_COUNTS.csv", global_stage),
        ("FOLD_GATE.csv", fold_counts),
        ("FOLD_MEMBERSHIP.jsonl", fold_members),
        ("FINAL_DEV_MEMBERS.jsonl", final_members),
    ]:
        path = run_dir / name
        if name.endswith(".csv"):
            pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
        else:
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(jsonable(row), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    gate_doc = {
        "run_id": RUN_ID, "global_stage_gates": global_stage,
        "global_stage_gate_pass": all(x["stage_gate_pass"] for x in global_stage),
        "fold_gates": fold_gates,
        "all_three_folds_pass": all(x["fold_data_gate_pass"] for x in fold_gates),
        "final_dev_rows": len(final_members),
        "final_dev_prediction_rows": 0,
        "dataset_admission": "PASS_DATA_GATE" if all(x["stage_gate_pass"] for x in global_stage) and all(x["fold_data_gate_pass"] for x in fold_gates) else "DATA_ADMISSION_INSUFFICIENT",
        "unexposed_independent_validation_rows": 0,
        "model_execution_counters": {k: 0 for k in MODEL_COUNTER_KEYS},
    }
    atomic_json(run_dir / "DATA_ADMISSION.json", gate_doc)
    return {"ready_rows": len(ready), "candidate_rows": len(candidate_rows),
            "mature_rows": len(mature), "final_dev_rows": len(final_members),
            "global_stage_gates": global_stage, "fold_gates": fold_gates,
            "dataset_admission": gate_doc["dataset_admission"],
            "mother_groups": {g: sum(1 for x in mother_group.values() if x["group"] == g)
                              for g in ("TRAIN_JULY", "HOLDOUT_AUG", "HOLDOUT_SEP", "HOLDOUT_OCT")}}


def _merge_shard_outputs(run_dir: Path, shard_count: int) -> dict:
    shard_root = run_dir / "shards"
    candidates, source_coverage = [], []
    aggregate = Counter()
    for sid in range(shard_count):
        sd = shard_root / f"shard_{sid:02d}"
        checkpoint = json.loads((sd / "SHARD_CHECKPOINT.json").read_text(encoding="utf-8"))
        if checkpoint.get("state") != "SHARD_COMPLETE":
            raise RuntimeError(f"SHARD_NOT_COMPLETE:{sid}:{checkpoint.get('state')}")
        aggregate["source_rows"] += checkpoint["source_rows"]
        aggregate["processed_codes"] += checkpoint["processed_codes"]
        aggregate["pure_r2_run_symbol_calls"] += checkpoint["pure_r2_run_symbol_calls"]
        aggregate["decision_rows"] += checkpoint["decision_rows"]
        aggregate["screen_pass_rows"] += checkpoint["screen_pass_rows"]
        aggregate["candidate_rows"] += checkpoint["candidate_rows"]
        candidates.extend(read_jsonl(sd / "CANDIDATE_LEDGER.jsonl"))
        source_coverage.extend(read_jsonl(sd / "SOURCE_COVERAGE.jsonl"))
    if len(source_coverage) != 5572:
        raise RuntimeError(f"SOURCE_COVERAGE_LEDGER_COUNT:{len(source_coverage)}")
    # Merge by streaming copied CSV bodies; headers are invariant and each shard owns a file.
    for out_name, shard_name in [
        ("HISTORICAL_SCREEN_DAILY.csv", "HISTORICAL_SCREEN_DAILY.csv"),
        ("HISTORICAL_SCREEN_ANCHORS.csv", "HISTORICAL_SCREEN_ANCHORS.csv"),
        ("NATIVE_R2_DAILY_STATUS.csv", "NATIVE_R2_DAILY_STATUS.csv"),
    ]:
        out = run_dir / out_name
        with out.open("wb") as w:
            for sid in range(shard_count):
                part = shard_root / f"shard_{sid:02d}" / shard_name
                raw = part.read_bytes()
                # Every partial is UTF-8 BOM; keep the first BOM/header only.
                if sid:
                    raw = raw.lstrip(b"\xef\xbb\xbf")
                    raw = raw.splitlines(keepends=True)
                    raw = b"".join(raw[1:])
                w.write(raw)
    for out_name, shard_name in [
        ("R2_MOTHERS.jsonl", "R2_MOTHERS.jsonl"),
        ("R2_PULLBACKS.jsonl", "R2_PULLBACKS.jsonl"),
        ("R2_CANDIDATE_MOTHER_DAILY.jsonl", "R2_CANDIDATE_MOTHER_DAILY.jsonl"),
        ("BAR_WITNESS.jsonl", "BAR_WITNESS.jsonl"),
    ]:
        with (run_dir / out_name).open("wb") as w:
            for sid in range(shard_count):
                part = shard_root / f"shard_{sid:02d}" / shard_name
                if part.exists(): w.write(part.read_bytes())
    original = load_universe()
    coverage_df = pd.DataFrame(source_coverage)
    full_disposition = original.merge(coverage_df, left_on="代码", right_on="security",
                                      how="left", validate="one_to_one")
    full_disposition["source_status"] = full_disposition["source_status"].fillna("CANNOT_CONFIRM_NO_DISPOSITION_ROW")
    if len(full_disposition) != 5572 or full_disposition["代码"].nunique() != 5572:
        raise RuntimeError("FULL_SOURCE_DISPOSITION_NOT_5572")
    full_disposition = full_disposition.sort_values("代码", kind="stable")
    full_disposition.to_csv(run_dir / "SOURCE_DISPOSITION.csv", index=False, encoding="utf-8-sig")
    fold_stats = build_folds(run_dir, candidates)
    return {"aggregate": dict(aggregate), "source_coverage_rows": len(source_coverage),
            "source_status_counts": dict(Counter(x["source_status"] for x in source_coverage)),
            "folds": fold_stats}


def _run_real() -> None:
    pre = json.loads((RUN_DIR / "PRE_READ_FREEZE.json").read_text(encoding="utf-8"))
    if pre.get("state") != "FROZEN_BEFORE_FIRST_ROW_READ" or pre.get("first_selector_row_read") is not False:
        raise RuntimeError("PRE_READ_FREEZE_INVALID")
    script_sha = sha256_bytes(Path(__file__).read_bytes())
    if script_sha != pre.get("new_code_sha256"):
        raise RuntimeError("EXECUTION_CODE_CHANGED_AFTER_FREEZE")
    src = json.loads((RUN_DIR / "SOURCE_REFERENCES.json").read_text(encoding="utf-8"))
    if src.get("new_code", {}).get("sha256") != script_sha:
        raise RuntimeError("CODE_SOURCE_REFERENCE_CHANGED")
    universe = load_universe()
    codes = universe["代码"].tolist()
    d17_meta = universe.set_index("代码").to_dict("index")
    r2_calendar = json.loads(R2_CAL_PATH.read_text(encoding="utf-8"))
    screen_mod = load_module(SCREEN_PATH, "p515_screen_for_date_list")
    reader, meta, manifest_path, manifest_raw = reader_setup()
    if sha256_bytes(manifest_raw) != src["panel"]["manifest_sha256"]:
        raise RuntimeError("PANEL_MANIFEST_CHANGED_AFTER_FREEZE")
    shards = [codes[i::4] for i in range(4)]
    shard_frames = []
    read_log = RUN_DIR / "READER_ATTEMPTS.jsonl"
    for sid, shard_codes in enumerate(shards):
        attempt = {"run_id": RUN_ID, "shard_id": sid, "phase": "READER_LOAD",
                   "attempted_at": utc_now(), "codes_requested": len(shard_codes),
                   "first_code": shard_codes[0], "last_code": shard_codes[-1],
                   "date_scope": [EARLIEST, LATEST], "columns": list(OHLCV),
                   "reader_sha256": EXPECTED_READER_SHA, "status": "STARTED"}
        append_jsonl(read_log, attempt)
        try:
            frame = reader.load_selector_ready(columns=list(OHLCV), start_date=EARLIEST,
                end_date=LATEST, ts_codes=shard_codes, panel_path=PANEL_PATH)
            if set(["ts_code", "trade_date", *OHLCV]) - set(frame.columns):
                raise RuntimeError(f"READER_RETURNED_COLUMNS:{list(frame.columns)}")
            frame = frame[["ts_code", "trade_date", *OHLCV]].copy()
            frame["ts_code"] = frame["ts_code"].astype(str)
            frame["trade_date"] = frame["trade_date"].map(normalize_date)
            if frame["trade_date"].lt(EARLIEST).any() or frame["trade_date"].gt(LATEST).any():
                raise RuntimeError("READER_RETURNED_OUT_OF_SCOPE_DATE")
            if not set(frame["ts_code"].unique()).issubset(set(shard_codes)):
                raise RuntimeError("READER_RETURNED_OUT_OF_SCOPE_SECURITY")
            shard_frames.append(frame)
            attempt.update({"status": "SUCCESS", "finished_at": utc_now(),
                            "returned_rows": len(frame),
                            "returned_unique_codes": frame["ts_code"].nunique(),
                            "returned_min_date": frame["trade_date"].min() if len(frame) else None,
                            "returned_max_date": frame["trade_date"].max() if len(frame) else None})
            append_jsonl(read_log, attempt)
        except Exception as exc:
            attempt.update({"status": "FAILED", "failed_at": utc_now(),
                            "error": repr(exc), "traceback": traceback.format_exc()})
            append_jsonl(read_log, attempt)
            raise
    combined = pd.concat(shard_frames, ignore_index=True)
    duplicate_count = int(combined.duplicated(["ts_code", "trade_date"], keep=False).sum())
    coverage = combined.groupby("trade_date")["ts_code"].nunique().sort_index()
    screen_dates = [normalize_date(d) for d, n in coverage.items() if int(n) > len(codes) // 2]
    expected_d17_dates = json.loads(SCREEN_RECEIPT_PATH.read_text(encoding="utf-8"))["date_scope"]
    d17_recent = screen_dates[-31:]
    if screen_dates[-1:] != [LATEST]:
        raise RuntimeError(f"SCREEN_DATE_LIST_NOT_END_D17:{screen_dates[-3:]}")
    date_match = d17_recent == expected_d17_dates
    if not date_match:
        raise RuntimeError(f"D17_SCREEN_DATE_SCOPE_MISMATCH:{d17_recent!r}:{expected_d17_dates!r}")
    decision_dates = [d for d in screen_dates if DECISION_START <= d <= DECISION_END]
    if not decision_dates:
        raise RuntimeError("NO_DECISION_DATES_IN_FIXED_WINDOW")
    actual_d17_codes = set(combined.loc[combined["trade_date"] == LATEST, "ts_code"].unique())
    universe_codes = set(codes)
    panel_universe_diff = {"missing_d17_rows": sorted(universe_codes - actual_d17_codes),
                           "extra_d17_codes": sorted(actual_d17_codes - universe_codes)}
    read_summary = {
        "run_id": RUN_ID, "completed_at": utc_now(), "reader_call_attempts": 4,
        "reader_calls_success": 4, "reader_rows_total": len(combined),
        "reader_unique_codes": combined["ts_code"].nunique(),
        "reader_trade_dates": combined["trade_date"].nunique(),
        "row_count_max_per_security": int(combined.groupby("ts_code").size().max()) if len(combined) else 0,
        "row_count_min_per_security": int(combined.groupby("ts_code").size().min()) if len(combined) else 0,
        "duplicate_security_date_rows": duplicate_count,
        "screen_common_dates": len(screen_dates), "screen_common_dates_sha256": sha256_bytes("\n".join(screen_dates).encode()),
        "d17_recent_31_dates_match_original_screen_receipt": date_match,
        "d17_recent_31_dates": d17_recent,
        "decision_date_count": len(decision_dates), "decision_date_start": decision_dates[0],
        "decision_date_end": decision_dates[-1], "d17_universe_vs_reader_rows": panel_universe_diff,
        "model_counters": {k: 0 for k in MODEL_COUNTER_KEYS},
    }
    atomic_json(RUN_DIR / "READER_SCOPE_RECEIPT.json", read_summary)
    # Repartition the already-read projections in memory. The workers receive disjoint security
    # slices; they do not each query or load the entire panel.
    frames_by_code = {sid: frame for sid, frame in enumerate(shard_frames)}
    source_sha = {k: v["sha256"] for k, v in src["files"].items()}
    payloads = []
    for sid, frame in frames_by_code.items():
        payloads.append({"shard_id": sid, "run_dir": str(RUN_DIR), "frame": frame,
            "codes": shards[sid], "source_sha256": source_sha,
            "d17_meta": {code: d17_meta[code] for code in shards[sid]},
            "r2_calendar": r2_calendar, "screen_dates": screen_dates,
            "decision_dates": decision_dates})
    results = []
    with ProcessPoolExecutor(max_workers=MAX_PROCESSES) as pool:
        futures = {pool.submit(_shard_worker, p): p["shard_id"] for p in payloads}
        for future in as_completed(futures):
            sid = futures[future]
            try:
                results.append(future.result())
                append_jsonl(RUN_DIR / "SHARD_EXECUTION_LOG.jsonl",
                    {"run_id": RUN_ID, "shard_id": sid, "status": "SUCCESS",
                     "completed_at": utc_now(), "result": results[-1]})
            except Exception as exc:
                append_jsonl(RUN_DIR / "SHARD_EXECUTION_LOG.jsonl",
                    {"run_id": RUN_ID, "shard_id": sid, "status": "FAILED",
                     "failed_at": utc_now(), "error": repr(exc), "traceback": traceback.format_exc()})
                raise
    merge = _merge_shard_outputs(RUN_DIR, 4)
    counters = {
        "run_id": RUN_ID, "completed_at": utc_now(),
        "reader_call_attempts": 4, "reader_calls_success": 4,
        "pure_r2_run_symbol_calls": merge["aggregate"]["pure_r2_run_symbol_calls"],
        "feature_build_attempts": merge["aggregate"]["candidate_rows"],
        "feature_build_valid": None, "candidate_rows": merge["aggregate"]["candidate_rows"],
        "daily_screen_rows": merge["aggregate"]["decision_rows"],
        "screen_pass_rows": merge["aggregate"]["screen_pass_rows"],
        "source_rows": merge["aggregate"]["source_rows"],
        "source_disposition_rows": merge["source_coverage_rows"],
        "model_counters": {k: 0 for k in MODEL_COUNTER_KEYS},
        "shard_results": results,
        "source_status_counts": merge["source_status_counts"],
        "dataset_summary": merge["folds"],
        "d17_universe_vs_reader_rows": panel_universe_diff,
        "actual_model_calls": False, "model_source_imported": False,
    }
    # Count actual valid feature rows from the frozen binary length and candidate ledger.
    counters["feature_build_valid"] = (RUN_DIR / "MODEL_INPUTS_10_F64LE.bin").stat().st_size // 80
    atomic_json(RUN_DIR / "EXECUTION_COUNTERS.json", counters)
    finalize_local_manifest(RUN_DIR)


def finalize_local_manifest(run_dir: Path) -> dict:
    members = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name not in ("LOCAL_MANIFEST.json", "EXECUTION_COUNTERS.json"):
            raw = path.read_bytes()
            members.append({"path": str(path.relative_to(run_dir)), "bytes": len(raw), "sha256": sha256_bytes(raw)})
    doc = {"task_id": "P515_MAC_STAGE_PB15_DATA_MATERIALIZATION_R1_V1",
           "run_id": RUN_ID, "generated_at": utc_now(), "members": members}
    atomic_json(run_dir / "LOCAL_MANIFEST.json", doc)
    counters_path = run_dir / "EXECUTION_COUNTERS.json"
    counters = json.loads(counters_path.read_text(encoding="utf-8")) if counters_path.exists() else {}
    counters["local_manifest_sha256"] = sha256_bytes((run_dir / "LOCAL_MANIFEST.json").read_bytes())
    counters["local_manifest_members"] = len(members)
    if counters_path.exists(): atomic_json(counters_path, counters)
    return doc


def synthetic_self_test() -> dict:
    # No Reader, panel, R2 state, data generation, or model entrypoint is touched here.
    values = [2.0, -0.1, -0.15, 0.2, 0.7, 0.8, 0.5, 0.12, 1.0, 0.0]
    packed = struct.pack("<10d", *values)
    assert len(packed) == 80 and struct.unpack("<10d", packed) == tuple(values)
    assert sha256_bytes(packed) == sha256_bytes(struct.pack("<10d", *struct.unpack("<10d", packed)))
    calendar = ["20260701", "20260702", "20260703", "20260706", "20260707"]
    bars = {
        "20260701": (10, 11, 9, 10, 100),
        "20260702": (11, 13, 10, 12, 200),
        "20260703": (13, 20, 12, 19, 300),
        "20260706": (18, 19, 17, 18, 150),
        "20260707": (17, 18, 16, 17, 80),
    }
    synthetic_obs = {"pullback_sessions": 2, "frozen_wave_high": 20,
        "origin_low": 10, "wave_start": "20260701",
        "wave_end_confirmed_at": "20260706", "candidate_date": "20260707"}
    features, _ = _feature_values("000001.SZ", "20260707", synthetic_obs, bars,
                                  calendar, _date_to_idx(calendar))
    expected = (2.0, -0.15, -0.2, 0.15, 0.4, 0.575, 0.4, 0.7, 1.0, 0.0)
    assert features is not None and all(abs(a - b) < 1e-14 for a, b in zip(features, expected)), features
    assert TERMINAL_LABELS == {"FAILED_RISK": 0, "FAILED_SUPPORT": 0,
                               "SUCCESS_RESTART": 1, "EXPIRED_PULLBACK": 0}
    assert len(FEATURE_NAMES) == 10
    return {"status": "PASS_SYNTHETIC_CONTRACT_CHECK", "reader_calls": 0,
            "pure_r2_calls": 0, "feature_bytes": len(packed),
            "roundtrip_exact": True, "synthetic_k2_feature_check": "PASS",
            "model_counters": {k: 0 for k in MODEL_COUNTER_KEYS},
            "generated_at": utc_now()}


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--freeze", action="store_true")
    g.add_argument("--run", action="store_true")
    args = p.parse_args()
    if args.self_test:
        print(json.dumps(synthetic_self_test(), ensure_ascii=False, sort_keys=True))
    elif args.freeze:
        write_frozen_scope()
        print(json.dumps({"status": "FROZEN_BEFORE_FIRST_ROW_READ", "run_dir": str(RUN_DIR),
                          "code_sha256": sha256_bytes(Path(__file__).read_bytes())}, ensure_ascii=False))
    elif args.run:
        _run_real()
        print(json.dumps({"status": "MATERIALIZATION_COMPLETE", "run_dir": str(RUN_DIR)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
