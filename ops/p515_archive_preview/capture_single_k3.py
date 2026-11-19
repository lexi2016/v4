#!/usr/bin/env python3
"""One bounded native-input capture for the pinned D17 single K3 case.

This script is deliberately one-shot: it refuses an existing run directory and
records START before its sole V4 data read. It never loads or scores a model.
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import importlib.util
import json
import math
import os
import platform
import shutil
import struct
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo


PROJECT = Path("/Users/lexi/Desktop/学习/v4_app")
ARTIFACT_ROOT = PROJECT / "artifacts/p515_d17_single_k3_native_input_20261119"
ORIGINAL = PROJECT / "artifacts/p515_d17_anomaly_wave_shrink_d18_review_20261118"
PREVIOUS_RUN = PROJECT / "artifacts/p515_d18_native_archive_preview_20261119/native/run"
AUDIT_ZIP = ARTIFACT_ROOT / "reference/master-archive-audit.zip"
V3_ZIP = PROJECT / "artifacts/p515_d18_master_followup_20261119_v2/_reference/gemini-v3.zip"
SOURCE_RECEIPT = ARTIFACT_ROOT / "SOURCE_READ_RECEIPT.json"
PROMPT = ARTIFACT_ROOT / "PROMPT_ORIGINAL.md"
PANEL_PYTHON_FALLBACK = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
)
DASH = "20261117"
SECURITY = "000407.SZ"
FEATURE_ROW_BYTES = 160
OHLCV = ("open", "high", "low", "close", "volume")
BAR_ORDER = ("ts_code", "trade_date", "open", "high", "low", "close", "volume")

PINS = {
    "02_模型输入资格逐股.csv": "405a6ebd9f2647c678bb9ad864e4aa17f94678f4a52c042c4a559e98a7dfce76",
    "MODEL_INPUTS_20.csv": "7f8065e846662fc0715bb0d5c495cc1779473eaeea040abfde06bb24ad306e28",
    "MODEL_INPUT_FREEZE.json": "dbe5bca93d69d5672f607b7848b58fe13ddb4b311a2c35401c0851ad64d07ea7",
    "rank.py": "d5dfc16a870f62a9e118d7ed798d7e09caef6ea56d6a85d0d624bfb83073ddd1",
    "screen.py": "5bdbef2fe8dd33016bae095f3984dab06e9a0b3f9f04647e13ce37a5cc9a32ae",
    "01_量价初筛.csv": "1cb9eea994d571c5da2969cf93ea49d9777b59936a61c5c4c496f2dd52420c3d",
    "R2_FROZEN_event_rules.py": "0c5f20e93072701c2c06d9cddcf4b28832888028b67eece2d7fc14be1ccb1381",
    "FROZEN_wiring.py": "873edeaa5c3d6d751a96cc17a94b48e792b43382b3266301915e10e7081cedbd",
    "ORIGINAL_EXCHANGE_CALENDARS.json": "cbfcce38d5689b0d967d0611d32b154f36a51c06061bb047e73a4d512fb77745",
    "R2_EFFECTIVE_CALENDAR.json": "2610bb6e8054351d7066fcfc5876f083d0e43c938f3bea43b17a592d08498a6d",
    "AUDIT_ZIP": "b79ed9a34997effdde30d1c8b2c7a405b74d68bca17ad0aaa8a87c85ab24c998",
    "V3_ZIP": "ee213ab48d96d951aa4810901cb11619ac2a5aee8b387fdc4d9a458fb08bacc0",
    "V3_SOURCE": "ebe66235d2f27c0e84bd1680cc368f90ef0be7e2d6b215fc5cb1727604656d65",
    "CANDIDATE_MANIFEST": "3c2298f89556806aeb1b59e2516fe246ebbb53cda998a24814f811ed9b577f08",
    "V4_READER": "4f096d4995aa862296e0b918ca9dd136bd35dd0b1309efa1239f312be5f25565",
    "SCOPE_PIN": "f188e5858511e2b2ecb878bd1ebe1413d623dbe882cf8cf9ff8250efa7e0a6dc",
}


class BoundedStop(RuntimeError):
    def __init__(self, code: str, detail: dict[str, Any]):
        super().__init__(code)
        self.code = code
        self.detail = detail


def now_beijing() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="microseconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any, *, newline: bool = False) -> bytes:
    data = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return data + (b"\n" if newline else b"")


def dump_json(path: Path, value: Any) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return data


def dump_jsonl(path: Path, rows: list[dict[str, Any]]) -> bytes:
    data = b"".join(canonical_json(row, newline=True) for row in rows)
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return data


def file_record(path: Path, relative: str | None = None) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": relative or str(path), "bytes": len(data), "sha256": sha256(data)}


def copy_exact(source: Path, target: Path) -> dict[str, Any]:
    data = source.read_bytes()
    with target.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    return {"source": str(source), "path": str(target), "bytes": len(data), "sha256": sha256(data)}


def normalize_date(value: Any) -> str:
    if value is None:
        raise ValueError("NULL_TRADE_DATE")
    raw = str(value).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    normalized = raw.replace("-", "").replace("/", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError(f"UNSUPPORTED_TRADE_DATE:{raw}")
    return normalized


def load_csv_rows(path: Path) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        rows = [(index, dict(row)) for index, row in enumerate(reader, start=2)]
    return headers, rows


def assert_pin(path: Path, expected: str, label: str) -> bytes:
    if not path.is_file():
        raise BoundedStop("PINNED_SOURCE_NOT_FOUND", {"label": label, "path": str(path)})
    data = path.read_bytes()
    actual = sha256(data)
    if actual != expected:
        raise BoundedStop("PINNED_SOURCE_SHA_MISMATCH", {
            "label": label, "path": str(path), "expected_sha256": expected,
            "actual_sha256": actual, "bytes": len(data),
        })
    return data


def select_old_case() -> dict[str, Any]:
    qual_path = ORIGINAL / "02_模型输入资格逐股.csv"
    headers, source_rows = load_csv_rows(qual_path)
    if "状态" not in headers or "代码" not in headers:
        raise BoundedStop("OLD_QUALIFICATION_SCHEMA_MISSING", {"headers": headers})
    ready = [(line, row) for line, row in source_rows if row.get("状态") == "MODEL_READY"]
    ordered = sorted(ready, key=lambda pair: pair[1].get("代码", ""))
    if len(ordered) != 33 or not ordered or ordered[0][1].get("代码") != SECURITY:
        raise BoundedStop("OLD_QUALIFICATION_SELECTION_MISMATCH", {
            "model_ready_count": len(ordered), "first_code": ordered[0][1].get("代码") if ordered else None,
        })
    selected_line, selected = ordered[0]
    if selected.get("状态口径") != "HISTORICAL_PREFIX_CONCORDANCE_ONLY":
        raise BoundedStop("OLD_STATE_BASIS_MISMATCH", {"state_basis": selected.get("状态口径")})

    freeze = json.loads((ORIGINAL / "MODEL_INPUT_FREEZE.json").read_bytes())
    feature_order = freeze.get("feature_order")
    if not isinstance(feature_order, list) or len(feature_order) != 20:
        raise BoundedStop("FROZEN_FEATURE_ORDER_INVALID", {"feature_order_count": len(feature_order or [])})
    input_headers, input_rows = load_csv_rows(ORIGINAL / "MODEL_INPUTS_20.csv")
    matches = [(line, row) for line, row in input_rows if row.get("代码") == SECURITY]
    if len(matches) != 1:
        raise BoundedStop("OLD_MODEL_ROW_NOT_UNIQUE", {"count": len(matches)})
    input_line, old_input = matches[0]
    if old_input.get("PB") != selected.get("原R2_PB"):
        raise BoundedStop("OLD_ROW_PB_IDENTITY_MISMATCH", {
            "qualification_pb": selected.get("原R2_PB"), "input_pb": old_input.get("PB"),
        })

    primary_headers, primary_rows = load_csv_rows(ORIGINAL / "01_量价初筛.csv")
    primary_matches = [(line, row) for line, row in primary_rows if row.get("代码") == SECURITY]
    if len(primary_matches) != 1:
        raise BoundedStop("D17_PREFILTER_ROW_NOT_UNIQUE", {"count": len(primary_matches)})
    primary_line, primary = primary_matches[0]
    return {
        "security": SECURITY,
        "selected_by": "first full-code lexical order among the original 33 MODEL_READY rows; no probability, rank, or D18 return used",
        "eligible_row_count": len(ordered),
        "qualification_row": {"source_data_line_1based": selected_line, "values": selected},
        "old_model_input_row": {
            "source_data_line_1based": input_line,
            "columns": ["代码", "PB", *feature_order],
            "values": {"代码": old_input["代码"], "PB": old_input["PB"],
                       **{name: old_input[name] for name in feature_order}},
            "feature_order": feature_order,
        },
        "original_d17_prefilter_row": {
            "source_data_line_1based": primary_line,
            "used_fields_only": {
                key: primary.get(key) for key in
                ("代码", "简称", "市场", "信号类型", "锚日", "确认日", "回调首日", "上涨段高点", "结构回调日数")
            },
        },
        "source_schemas": {
            "qualification_headers": headers,
            "model_input_headers": input_headers,
            "prefilter_headers": primary_headers,
        },
    }


def exact_node_source(lines: list[str], node: ast.AST) -> str:
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None or end is None:
        raise ValueError("AST_NODE_LOCATION_REQUIRED")
    return "".join(lines[start - 1:end])


def extract_frozen_features(wiring_bytes: bytes, outdir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    source = wiring_bytes.decode("utf-8")
    tree = ast.parse(source)
    wanted = {"_PRICE", "_BAR", "_MATURE", "_valid", "_r2_features"}
    selected: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)] if isinstance(node, ast.Assign) else [node.target.id] if isinstance(node.target, ast.Name) else []
            for name in names:
                if name in wanted:
                    selected[name] = node
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            selected[node.name] = node
    if set(selected) != wanted:
        raise BoundedStop("FROZEN_FEATURE_AST_NODE_MISSING", {"found": sorted(selected), "needed": sorted(wanted)})
    original_lines = source.splitlines(keepends=True)
    entries = []
    for name in ("_PRICE", "_BAR", "_MATURE", "_valid", "_r2_features"):
        node = selected[name]
        segment = exact_node_source(original_lines, node)
        entries.append({
            "name": name,
            "source_lines_1based": [node.lineno, node.end_lineno],
            "exact_source_sha256": sha256(segment.encode("utf-8")),
            "ast_sha256": sha256(ast.dump(node, include_attributes=False).encode("utf-8")),
        })
    copied_nodes = [ast.fix_missing_locations(selected[name]) for name in ("_PRICE", "_BAR", "_MATURE", "_valid", "_r2_features")]
    extracted = ast.Module(body=copied_nodes, type_ignores=[])
    ast.fix_missing_locations(extracted)
    # Parse the extracted module again and prove every selected AST node equals
    # its corresponding node from the frozen source before compiling it.
    extracted_tree = ast.parse(ast.unparse(extracted))
    extracted_names: dict[str, ast.AST] = {}
    for node in extracted_tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    extracted_names[target.id] = node
        elif isinstance(node, ast.FunctionDef):
            extracted_names[node.name] = node
    for name in wanted:
        if ast.dump(selected[name], include_attributes=False) != ast.dump(extracted_names[name], include_attributes=False):
            raise BoundedStop("EXTRACTED_FEATURE_AST_MISMATCH", {"node": name})
    # Keep human-readable exact source excerpt from the frozen bytes; execution
    # itself uses the exact frozen AST nodes above, with stdlib mean injected.
    exact_source = "\n".join(exact_node_source(original_lines, selected[name]).rstrip("\n") for name in ("_PRICE", "_BAR", "_MATURE", "_valid", "_r2_features")) + "\n"
    extract_path = outdir / "FROZEN_FEATURES_AST_EXTRACT.py.txt"
    with extract_path.open("xb") as f:
        f.write(exact_source.encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    namespace: dict[str, Any] = {"__builtins__": __builtins__, "mean": mean}
    exec(compile(extracted, "<frozen-wiring-selected-AST>", "exec"), namespace)
    manifest = {
        "frozen_wiring_sha256": sha256(wiring_bytes),
        "source_module_imported": False,
        "model_or_scaler_dependency_imported": False,
        "extracted_names": ["_PRICE", "_BAR", "_MATURE", "_valid", "_r2_features"],
        "ast_extraction": entries,
        "stdlib_mean": {"module": "statistics", "callable": "mean", "injected_exact_object": True},
        "execution_ast_reparse_equivalence": "PASS",
        "exact_source_excerpt_file": str(extract_path),
        "exact_source_excerpt_sha256": sha256(exact_source.encode("utf-8")),
    }
    return namespace, manifest


def native_bar_rows(raw: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    expected_columns = {"ts_code", "trade_date", *OHLCV}
    missing = sorted(expected_columns - set(raw.columns))
    extras = sorted(set(raw.columns) - expected_columns)
    if missing or extras:
        raise BoundedStop("READER_PROJECTION_COLUMNS_MISMATCH", {"missing": missing, "extras": extras})
    source_types = {column: str(raw[column].dtype) for column in raw.columns}
    rows: list[dict[str, Any]] = []
    type_rows: list[dict[str, Any]] = []
    hashes: list[dict[str, Any]] = []
    seen_dates: set[str] = set()
    dates_in_reader_order: list[str] = []
    for source_index, (_, series) in enumerate(raw.iterrows(), start=1):
        code = str(series["ts_code"])
        day = normalize_date(series["trade_date"])
        if code != SECURITY:
            raise BoundedStop("READER_RETURNED_OUT_OF_SCOPE_SECURITY", {"source_index": source_index, "code": code})
        if not ("20240408" <= day <= DASH):
            raise BoundedStop("READER_RETURNED_OUT_OF_SCOPE_DATE", {"source_index": source_index, "trade_date": day})
        if day in seen_dates:
            raise BoundedStop("READER_DUPLICATE_SECURITY_DAY", {"trade_date": day})
        seen_dates.add(day)
        dates_in_reader_order.append(day)
        row = {"ts_code": code, "trade_date": day}
        raw_types = {"ts_code": type(series["ts_code"]).__name__, "trade_date": type(series["trade_date"]).__name__}
        for column in OHLCV:
            value = series[column]
            if value is None:
                raise BoundedStop("READER_NULL_REQUIRED_OHLCV", {"trade_date": day, "column": column})
            numeric = float(value)
            if not math.isfinite(numeric):
                raise BoundedStop("READER_NONFINITE_REQUIRED_OHLCV", {"trade_date": day, "column": column, "value": str(value)})
            row[column] = numeric
            raw_types[column] = type(value).__name__
        rows.append(row)
        type_rows.append({"source_order_1based": source_index, "trade_date": day, "source_scalar_types": raw_types})
        raw_bytes = canonical_json(row)
        hashes.append({"source_order_1based": source_index, "security": code, "bar_date": day,
                       "input_row_sha256": sha256(raw_bytes)})
    if not rows:
        raise BoundedStop("READER_RETURNED_ZERO_ROWS", {"security": SECURITY})
    if len(rows) > 634:
        raise BoundedStop("READER_ROW_BUDGET_EXCEEDED", {"rows": len(rows), "max_rows": 634})
    if dates_in_reader_order != sorted(dates_in_reader_order):
        raise BoundedStop("READER_ROW_ORDER_NOT_CHRONOLOGICAL", {
            "first_dates": dates_in_reader_order[:5], "last_dates": dates_in_reader_order[-5:],
        })
    return rows, type_rows, [{"reader_column_dtypes": source_types,
                              "reader_row_order_preserved": True,
                              "rows": len(rows), "first_trade_date": dates_in_reader_order[0],
                              "last_trade_date": dates_in_reader_order[-1]}]


def check_gate_oracle(rank_bytes: bytes) -> dict[str, Any]:
    tree = ast.parse(rank_bytes.decode("utf-8"))
    replay = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "replay"), None)
    if replay is None:
        raise BoundedStop("FROZEN_RANK_REPLAY_FUNCTION_MISSING", {})
    source_lines = rank_bytes.decode("utf-8").splitlines(keepends=True)
    source = exact_node_source(source_lines, replay)
    gate_terms = ["SAME_EVENT_PULLBACK", "pullback_sessions", "terminal_observed_today", "end_date", "features is None"]
    absent = [term for term in gate_terms if term not in source]
    if absent:
        raise BoundedStop("FROZEN_RANK_GATE_ORACLE_UNEXPECTED", {"missing_terms": absent})
    return {
        "source_sha256": sha256(rank_bytes),
        "entry_function": "rank.py::replay",
        "entry_ast_sha256": sha256(ast.dump(replay, include_attributes=False).encode("utf-8")),
        "executed": False,
        "source_excerpt": source,
        "gate_terms_present": gate_terms,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=None)
    args = parser.parse_args()
    run_id = f"p515-single-k3-{SECURITY.replace('.', '-')}-{datetime.now().strftime('%Y%m%dT%H%M%S')}-{os.urandom(4).hex()}"
    run_dir = args.run_dir or ARTIFACT_ROOT / "runs" / run_id
    run_dir = run_dir.expanduser().resolve()
    if run_dir.exists():
        raise SystemExit(f"REFUSE_EXISTING_RUN_DIRECTORY:{run_dir}")
    run_dir.mkdir(parents=True, exist_ok=False)
    counters = {
        "reader_data_calls": 0,
        "r2_author_runs": 0,
        "feature_author_calls": 0,
        "v3_strict_calls": 0,
        "v3_layered_calls": 0,
        "model_fit": 0,
        "preprocessing_fit": 0,
        "model_api": 0,
        "new_probability": 0,
        "static_new_score": 0,
        "model_deserialization": 0,
    }
    status = "RUNNING"
    stop_code = None
    stop_detail: dict[str, Any] = {}
    result_summary: dict[str, Any] = {}
    file_inventory: list[dict[str, Any]] = []
    call_events_path = run_dir / "CALL_EVENTS.jsonl"

    def event(data: dict[str, Any]) -> None:
        record = {"at": now_beijing(), **data}
        with call_events_path.open("ab") as f:
            f.write(canonical_json(record, newline=True))
            f.flush()
            os.fsync(f.fileno())

    try:
        # Validate every finite source pin before the first Reader or R2 call.
        source_receipt_bytes = assert_pin(SOURCE_RECEIPT, sha256(SOURCE_RECEIPT.read_bytes()), "source_read_receipt_self_read")
        prompt_bytes = assert_pin(PROMPT, "987f3bb9659f2ec8f490499227303f4d8333715afc18cf0c54cbff6b9ba35c57", "formal_prompt")
        source_files = {
            "qualification": (ORIGINAL / "02_模型输入资格逐股.csv", PINS["02_模型输入资格逐股.csv"]),
            "old_input_matrix": (ORIGINAL / "MODEL_INPUTS_20.csv", PINS["MODEL_INPUTS_20.csv"]),
            "old_feature_freeze": (ORIGINAL / "MODEL_INPUT_FREEZE.json", PINS["MODEL_INPUT_FREEZE.json"]),
            "frozen_rank_source": (ORIGINAL / "rank.py", PINS["rank.py"]),
            "reader_binding_source": (ORIGINAL / "screen.py", PINS["screen.py"]),
            "original_d17_prefilter": (ORIGINAL / "01_量价初筛.csv", PINS["01_量价初筛.csv"]),
            "r2_source": (PREVIOUS_RUN / "R2_FROZEN_event_rules.py", PINS["R2_FROZEN_event_rules.py"]),
            "wiring_source": (PREVIOUS_RUN / "FROZEN_wiring.py", PINS["FROZEN_wiring.py"]),
            "original_calendar": (PREVIOUS_RUN / "ORIGINAL_EXCHANGE_CALENDARS.json", PINS["ORIGINAL_EXCHANGE_CALENDARS.json"]),
            "effective_calendar": (PREVIOUS_RUN / "R2_EFFECTIVE_CALENDAR.json", PINS["R2_EFFECTIVE_CALENDAR.json"]),
            "archive_audit_zip": (AUDIT_ZIP, PINS["AUDIT_ZIP"]),
            "gemini_v3_zip": (V3_ZIP, PINS["V3_ZIP"]),
        }
        bytes_by_label = {label: assert_pin(path, expected, label) for label, (path, expected) in source_files.items()}
        if sha256(bytes_by_label["gemini_v3_zip"]) != PINS["V3_ZIP"]:
            raise BoundedStop("V3_PACKAGE_PIN_MISMATCH", {})
        with zipfile.ZipFile(V3_ZIP) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise BoundedStop("V3_ZIP_CRC_FAILURE", {"member": bad_member})
            source_members = [name for name in zf.namelist() if name.endswith("selection_output_adapter.py")]
            if len(source_members) != 1:
                raise BoundedStop("V3_SOURCE_MEMBER_NOT_UNIQUE", {"members": source_members})
            v3_member_name = source_members[0]
            v3_bytes = zf.read(v3_member_name)
        if sha256(v3_bytes) != PINS["V3_SOURCE"]:
            raise BoundedStop("V3_SOURCE_PIN_MISMATCH", {"member": v3_member_name, "sha256": sha256(v3_bytes)})
        with zipfile.ZipFile(AUDIT_ZIP) as zf:
            bad_member = zf.testzip()
            if bad_member is not None:
                raise BoundedStop("AUDIT_ZIP_CRC_FAILURE", {"member": bad_member})
            pin_members = [name for name in zf.namelist() if name.endswith("NEXT_SINGLE_K3_SCOPE_PIN.json")]
            if len(pin_members) != 1:
                raise BoundedStop("SCOPE_PIN_MEMBER_NOT_UNIQUE", {"members": pin_members})
            scope_pin_name = pin_members[0]
            scope_pin_bytes = zf.read(scope_pin_name)
        if sha256(scope_pin_bytes) != PINS["SCOPE_PIN"]:
            raise BoundedStop("SCOPE_PIN_SHA_MISMATCH", {"member": scope_pin_name, "sha256": sha256(scope_pin_bytes)})
        scope_pin = json.loads(scope_pin_bytes)
        if scope_pin.get("selected_original_eligibility_row", {}).get("代码") != SECURITY:
            raise BoundedStop("SCOPE_PIN_SECURITY_MISMATCH", {})
        if (scope_pin.get("eligible_rows") != 33
                or scope_pin.get("source_eligibility_sha256") != PINS["02_模型输入资格逐股.csv"]
                or scope_pin.get("input_source_sha256") != PINS["MODEL_INPUTS_20.csv"]
                or scope_pin.get("window_first") != "20240408"
                or scope_pin.get("window_last") != DASH
                or scope_pin.get("max_unique_bar_rows") != 634
                or scope_pin.get("provided_calendar_sessions_in_window") != 634):
            raise BoundedStop("SCOPE_PIN_CONTRACT_MISMATCH", {"scope_pin": scope_pin})

        old_case = select_old_case()
        rank_gate = check_gate_oracle(bytes_by_label["frozen_rank_source"])
        original_cal = json.loads(bytes_by_label["original_calendar"])
        effective_cal_raw = json.loads(bytes_by_label["effective_calendar"])
        if not isinstance(effective_cal_raw, list):
            raise BoundedStop("EFFECTIVE_CALENDAR_SCHEMA_MISMATCH", {"type": type(effective_cal_raw).__name__})
        calendar = tuple(normalize_date(value) for value in effective_cal_raw)
        if list(calendar) != sorted(set(calendar)):
            raise BoundedStop("EFFECTIVE_CALENDAR_NOT_UNIQUE_SORTED", {})
        sessions = tuple(day for day in calendar if "20240408" <= day <= DASH)
        if len(sessions) != 634 or sessions[0] != "20240408" or sessions[-1] != DASH:
            raise BoundedStop("AUTHORIZED_CALENDAR_WINDOW_MISMATCH", {
                "sessions": len(sessions), "first": sessions[0] if sessions else None,
                "last": sessions[-1] if sessions else None,
            })

        worktree = Path(__file__).resolve().parents[2]
        run_script = run_dir / "capture_single_k3.py"
        copy_exact(Path(__file__).resolve(), run_script)
        copied_sources = []
        for filename, source_bytes in (
            ("PROMPT_ORIGINAL_COPY.md", prompt_bytes),
            ("rank.py", bytes_by_label["frozen_rank_source"]),
            ("screen.py", bytes_by_label["reader_binding_source"]),
            ("MODEL_INPUT_FREEZE.json", bytes_by_label["old_feature_freeze"]),
            ("R2_FROZEN_event_rules.py", bytes_by_label["r2_source"]),
            ("FROZEN_wiring.py", bytes_by_label["wiring_source"]),
            ("ORIGINAL_EXCHANGE_CALENDARS.json", bytes_by_label["original_calendar"]),
            ("R2_EFFECTIVE_CALENDAR.json", bytes_by_label["effective_calendar"]),
            ("selection_output_adapter.py", v3_bytes),
            ("NEXT_SINGLE_K3_SCOPE_PIN.json", scope_pin_bytes),
        ):
            target = run_dir / filename
            with target.open("xb") as f:
                f.write(source_bytes)
                f.flush()
                os.fsync(f.fileno())
            copied_sources.append({"path": str(target), "bytes": len(source_bytes), "sha256": sha256(source_bytes)})

        interpreter = Path(os.environ.get("PANEL_PYTHON", str(PANEL_PYTHON_FALLBACK))).expanduser().resolve()
        start = {
            "run_id": run_id,
            "started_at": now_beijing(),
            "timezone": "Asia/Shanghai",
            "security": SECURITY,
            "decision_date": DASH,
            "task": "MASTER_FOLLOWUP_20261119_V4_SINGLE_K3_NATIVE_INPUT",
            "worktree": str(worktree),
            "worktree_branch": "codex/p515-d17-single-k3-native-20261119",
            "frozen_worktree_base_commit": "b5ac15f32e1186132c1fdd49905baa8d7b0d22b5",
            "source_selection": old_case["selected_by"],
            "selected_old_row": old_case["qualification_row"],
            "allowed_reader_scope": {"security": SECURITY, "start_date": "20240408", "end_date": DASH,
                                     "columns": list(OHLCV), "maximum_unique_rows": 634,
                                     "effective_calendar_sessions": len(sessions)},
            "source_pins": {label: {"path": str(path), "bytes": len(data), "sha256": sha256(data),
                                    "expected_sha256": source_files[label][1]}
                            for label, (path, _expected) in ((k, v) for k, v in source_files.items())
                            for data in [bytes_by_label[label]]},
            "v3_source_member": {"member": v3_member_name, "bytes": len(v3_bytes), "sha256": sha256(v3_bytes)},
            "scope_pin_member": {"member": scope_pin_name, "bytes": len(scope_pin_bytes), "sha256": sha256(scope_pin_bytes)},
            "prompt_original": {"bytes": len(prompt_bytes), "sha256": sha256(prompt_bytes)},
            "source_read_receipt_sha256": sha256(source_receipt_bytes),
            "reader_interpreter": str(interpreter),
            "python": sys.version,
            "platform": platform.platform(),
            "model_execution_counts_at_start": counters,
            "planned_call_limits": {"reader_data_calls": 1, "r2_author_runs": 1,
                                     "feature_author_calls": 1, "v3_strict_calls": 1,
                                     "v3_layered_calls": 1, **{k: 0 for k in counters if k.startswith("model_") or k in ("preprocessing_fit", "new_probability", "static_new_score")}},
            "status": "STARTED_BEFORE_V4_READER_DATA_READ",
        }
        dump_json(run_dir / "START.json", start)

        # Execute the original, narrow screen binding only to obtain the fixed
        # V4 Reader and metadata; it does not scan candidate lists or load a model.
        screen_path = ORIGINAL / "screen.py"
        spec = importlib.util.spec_from_file_location("p515_single_k3_frozen_screen_binding", screen_path)
        if spec is None or spec.loader is None:
            raise BoundedStop("SCREEN_BINDING_IMPORT_SPEC_FAILED", {"path": str(screen_path)})
        screen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(screen)
        reader, panel_meta, identity = screen.setup()
        if identity.get("generation") != "dce3fe65d342f59043dc11e032a2058cb67b3a7a0db0f70759c7c337d6f66673":
            raise BoundedStop("READER_GENERATION_MISMATCH", {"identity": identity})
        if identity.get("input_sha256") != "40e0e5e15be05920c8d959b5e5147185000bf9af43c0a1a74760832918fecfa4":
            raise BoundedStop("READER_BATCH_INPUT_SHA_MISMATCH", {"identity": identity})
        if identity.get("manifest_sha256") != PINS["CANDIDATE_MANIFEST"]:
            raise BoundedStop("READER_CANDIDATE_MANIFEST_SHA_MISMATCH", {"identity": identity})
        if identity.get("reader_sha256") != PINS["V4_READER"]:
            raise BoundedStop("READER_SOURCE_SHA_MISMATCH", {"identity": identity})
        event({"event": "READER_DATA_CALL_START", "columns": list(OHLCV), "start_date": "20240408",
               "end_date": DASH, "ts_codes": [SECURITY], "panel_path": str(screen.PANEL)})
        counters["reader_data_calls"] += 1
        try:
            raw = reader.load_selector_ready(columns=list(OHLCV), start_date="20240408", end_date=DASH,
                                             ts_codes=[SECURITY], panel_path=screen.PANEL)
            event({"event": "READER_DATA_CALL_RETURN", "returned_rows": len(raw),
                   "columns": list(raw.columns), "generation": identity.get("generation")})
        except Exception as exc:
            event({"event": "READER_DATA_CALL_ERROR", "error_type": type(exc).__name__, "error": str(exc)})
            raise BoundedStop("V4_READER_DATA_CALL_FAILED_NO_RETRY", {"error_type": type(exc).__name__, "error": str(exc)}) from exc
        rows, type_rows, source_summary = native_bar_rows(raw)
        unexpected_session_dates = sorted({row["trade_date"] for row in rows} - set(sessions))
        if unexpected_session_dates:
            raise BoundedStop("READER_DATE_OUTSIDE_EFFECTIVE_CALENDAR", {"dates": unexpected_session_dates[:10]})
        if rows[-1]["trade_date"] != DASH:
            raise BoundedStop("D17_BAR_MISSING", {"last_trade_date": rows[-1]["trade_date"], "rows": len(rows)})
        source_meta = raw.attrs.get("panel_metadata", {}) if hasattr(raw, "attrs") else {}
        if source_meta and source_meta.get("generation_id") != identity.get("generation"):
            raise BoundedStop("READER_RETURN_METADATA_GENERATION_MISMATCH", {
                "reader_identity": identity.get("generation"), "returned_metadata": source_meta.get("generation_id")})
        prefix_bytes = dump_jsonl(run_dir / "R2_READER_PREFIX.jsonl", rows)
        type_bytes = dump_jsonl(run_dir / "R2_READER_NATIVE_TYPES.jsonl", type_rows)
        row_sha_bytes = dump_jsonl(run_dir / "R2_READER_ROW_SHA256.jsonl", [
            {"source_order_1based": index, "security": row["ts_code"], "bar_date": row["trade_date"],
             "input_row_sha256": sha256(canonical_json(row))}
            for index, row in enumerate(rows, start=1)
        ])
        dump_json(run_dir / "READER_SOURCE_IDENTITY.json", {
            "identity": identity,
            "panel_metadata_subset": {key: panel_meta.get(key) for key in
                                       ("generation_id", "input_sha256", "manifest_path", "manifest_sha256",
                                        "market_basis", "target_date", "reader_sha256") if key in panel_meta},
            "returned_panel_metadata": {key: source_meta.get(key) for key in
                                        ("generation_id", "input_sha256", "target_date") if key in source_meta},
            "reader_data_calls": counters["reader_data_calls"],
            "source_projection": {"security": SECURITY, "start_date": "20240408", "end_date": DASH,
                                  "columns": list(OHLCV)},
            "row_count": len(rows), "first_date": rows[0]["trade_date"], "last_date": rows[-1]["trade_date"],
            "unique_security_day_count": len(rows), "reader_row_order_preserved": source_summary[0]["reader_row_order_preserved"],
            "canonical_reader_prefix_file": {"bytes": len(prefix_bytes), "sha256": sha256(prefix_bytes)},
            "native_type_file": {"bytes": len(type_bytes), "sha256": sha256(type_bytes)},
            "row_sha_file": {"bytes": len(row_sha_bytes), "sha256": sha256(row_sha_bytes)},
            "reader_column_dtypes": source_summary[0]["reader_column_dtypes"],
        })
        if len(rows) != len({row["trade_date"] for row in rows}):
            raise BoundedStop("READER_UNIQUE_BAR_COUNT_MISMATCH", {"rows": len(rows)})

        # Use only the D17 observation from one author R2 call over the one
        # authorized symbol prefix. No historical full-pool runner is imported.
        r2_path = run_dir / "R2_FROZEN_event_rules.py"
        r2_spec = importlib.util.spec_from_file_location("p515_single_k3_frozen_r2", r2_path)
        if r2_spec is None or r2_spec.loader is None:
            raise BoundedStop("R2_IMPORT_SPEC_FAILED", {})
        r2 = importlib.util.module_from_spec(r2_spec)
        r2_spec.loader.exec_module(r2)
        event({"event": "R2_AUTHOR_RUN_START", "security": SECURITY, "bar_rows": len(rows),
               "calendar_sessions": len(sessions), "source_prefix": [rows[0]["trade_date"], rows[-1]["trade_date"]]})
        counters["r2_author_runs"] += 1
        try:
            r2_result = r2.run_symbol(SECURITY, rows, sessions)
            observations, candidates, completed_families, pullbacks = r2_result
            event({"event": "R2_AUTHOR_RUN_RETURN", "observation_count": len(observations),
                   "candidate_observation_count": len(candidates), "completed_family_count": len(completed_families),
                   "pullback_record_count": len(pullbacks)})
        except Exception as exc:
            event({"event": "R2_AUTHOR_RUN_ERROR", "error_type": type(exc).__name__, "error": str(exc)})
            raise BoundedStop("R2_AUTHOR_RUN_FAILED_NO_RETRY", {"error_type": type(exc).__name__, "error": str(exc)}) from exc
        d17_observations = [o for o in observations if o.get("candidate_date") is not None
                            and normalize_date(o.get("candidate_date")) == DASH]
        if len(d17_observations) != 1:
            raise BoundedStop("R2_D17_OBSERVATION_NOT_UNIQUE", {"count": len(d17_observations)})
        observation = d17_observations[0]
        family_id = observation.get("family_id")
        pb_id = observation.get("pullback_id")
        native_family_records = [f for f in completed_families if f.get("family_id") == family_id]
        native_pb_records = [p for p in pullbacks if p.get("pullback_id") == pb_id] if pb_id else []
        current_pb_ended_d = any(p.get("pullback_id") == pb_id and p.get("end_date") == DASH for p in pullbacks)
        native_dbar = next((row for row in rows if row["trade_date"] == DASH), None)
        dbar_valid = bool(native_dbar and r2._valid(native_dbar))
        old_qualification = old_case["qualification_row"]["values"]
        old_prefilter = old_case["original_d17_prefilter_row"]["used_fields_only"]
        native_high = observation.get("frozen_wave_high")
        old_prefilter_high = old_prefilter.get("上涨段高点")
        native_anchor_matches = bool(
            observation.get("wave_end_confirmed_at")
            and old_prefilter.get("回调首日")
            and native_high is not None
            and old_prefilter_high not in (None, "")
            and observation.get("wave_end_confirmed_at") == old_prefilter.get("回调首日")
            and math.isclose(float(native_high), float(old_prefilter_high), rel_tol=1e-7, abs_tol=1e-7)
        )
        gate = {
            "d17_valid_ohlcv": dbar_valid,
            "d17_stage_same_event_pullback": observation.get("stage") == "SAME_EVENT_PULLBACK",
            "d17_pullback_sessions_is_3": observation.get("pullback_sessions") == 3,
            "no_terminal_observed_d17": not bool(observation.get("terminal_observed_today")),
            "native_pullback_id_present": isinstance(pb_id, str) and bool(pb_id),
            "native_family_id_present": isinstance(family_id, str) and bool(family_id),
            "native_pullback_not_ended_on_d17": not current_pb_ended_d,
            "original_prefilter_k1_matches_native": observation.get("wave_end_confirmed_at") == old_prefilter.get("回调首日"),
            "original_prefilter_wave_high_matches_native_with_rank_oracle_tolerance": native_anchor_matches,
        }
        r2_output = {
            "run_id": run_id,
            "observed_at": now_beijing(),
            "security": SECURITY,
            "decision_date": DASH,
            "rule_version": observation.get("rule_version"),
            "native_observation": observation,
            "native_family_records_for_observation": native_family_records,
            "native_pullback_records_for_observation": native_pb_records,
            "native_ids": {"family_id": family_id, "pullback_id": pb_id},
            "source_old_qualification_context": {
                "old_r2_stage": old_qualification.get("原R2状态"),
                "old_r2_pullback_sessions": old_qualification.get("原R2回调日数"),
                "old_family_origin": old_qualification.get("原R2母起点"),
                "old_pb_id": old_qualification.get("原R2_PB"),
                "old_state_basis": old_qualification.get("状态口径"),
            },
            "gate_checks": gate,
            "gate_all_pass": all(gate.values()),
            "r2_run_summary": {"observation_count": len(observations), "candidate_count": len(candidates),
                               "family_count": len(completed_families), "pullback_count": len(pullbacks),
                               "bar_count": len(rows), "calendar_session_count": len(sessions)},
        }
        dump_json(run_dir / "R2_D17_NATIVE_OBSERVATION.json", r2_output)
        if not r2_output["gate_all_pass"]:
            raise BoundedStop("ACTUAL_D17_K3_GATE_NOT_MET", {"gate_checks": gate,
                                                               "native_stage": observation.get("stage"),
                                                               "native_pullback_id": pb_id})

        wiring_bytes = bytes_by_label["wiring_source"]
        feature_ns, feature_manifest = extract_frozen_features(wiring_bytes, run_dir)
        dump_json(run_dir / "FEATURE_AST_EXTRACTION_MANIFEST.json", feature_manifest)
        history = {row["trade_date"]: row for row in rows}
        event({"event": "FROZEN_FEATURE_CALL_START", "feature_function": "_r2_features",
               "r2_observation_sha256": sha256(canonical_json(observation)),
               "input_history_rows": len(history), "calendar_sessions": len(sessions)})
        counters["feature_author_calls"] += 1
        try:
            feature_values = feature_ns["_r2_features"](observation, history, sessions, pullbacks)
            event({"event": "FROZEN_FEATURE_CALL_RETURN", "returned_null": feature_values is None,
                   "returned_count": len(feature_values) if feature_values is not None else 0})
        except Exception as exc:
            event({"event": "FROZEN_FEATURE_CALL_ERROR", "error_type": type(exc).__name__, "error": str(exc)})
            raise BoundedStop("FROZEN_FEATURE_CALL_FAILED_NO_RETRY", {"error_type": type(exc).__name__, "error": str(exc)}) from exc
        if feature_values is None or len(feature_values) != 20:
            raise BoundedStop("FROZEN_FEATURE_ROW_MISSING_OR_WRONG_WIDTH", {"returned_count": len(feature_values) if feature_values is not None else None})

        old_input = old_case["old_model_input_row"]["values"]
        feature_order = old_case["old_model_input_row"]["feature_order"]
        comparison = []
        numeric_values: list[float] = []
        for index, (name, new_value) in enumerate(zip(feature_order, feature_values, strict=True), start=1):
            try:
                new_float = float(new_value)
                old_float = float(old_input[name])
            except (TypeError, ValueError) as exc:
                raise BoundedStop("FEATURE_VALUE_NOT_NUMERIC", {"index": index, "feature": name}) from exc
            if not math.isfinite(new_float) or not math.isfinite(old_float):
                raise BoundedStop("FEATURE_VALUE_NONFINITE", {"index": index, "feature": name})
            numeric_values.append(new_float)
            comparison.append({
                "index_1based": index,
                "feature": name,
                "old_original_csv_text": old_input[name],
                "old_parsed_float": old_float,
                "new_original_python_type": type(new_value).__name__,
                "new_original_value": new_value,
                "new_float64_value": new_float,
                "difference_new_minus_old": new_float - old_float,
                "strict_float_roundtrip_equal": new_float == old_float,
            })
        feature_blob = struct.pack("<20d", *numeric_values)
        if len(feature_blob) != FEATURE_ROW_BYTES:
            raise BoundedStop("FEATURE_ROW_BYTE_WIDTH_MISMATCH", {"bytes": len(feature_blob)})
        feature_sha = sha256(feature_blob)
        all_equal = all(row["strict_float_roundtrip_equal"] for row in comparison)
        old_pb = old_input["PB"]
        pb_identity_equal = pb_id == old_pb
        input_row = {
            "run_id": run_id,
            "security": SECURITY,
            "decision_date": DASH,
            "rule_version": observation.get("rule_version"),
            "family_id": family_id,
            "pullback_id": pb_id,
            "feature_order": feature_order,
            "original_function_return_type": type(feature_values).__name__,
            "original_function_return_value_types": [type(value).__name__ for value in feature_values],
            "original_function_return_values": list(feature_values),
            "float64_le_values": numeric_values,
            "dtype": "float64",
            "byte_order": "little-endian",
            "serialization": "struct.pack('<20d', *values), exact 20 values, no header/metadata/trailer",
            "bytes": len(feature_blob),
            "input_sha256": feature_sha,
            "this_hash_is_only_the_160_byte_model_pending_input_row": True,
            "historical_pit_status": "UNKNOWN",
            "model_consumption_count": 0,
        }
        dump_json(run_dir / "FEATURE_ROW_20.json", input_row)
        with (run_dir / "FEATURE_ROW_20_F64_LE.bin").open("xb") as f:
            f.write(feature_blob)
            f.flush()
            os.fsync(f.fileno())
        with (run_dir / "FEATURE_COMPARISON_OLD_VS_NATIVE.csv").open("x", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(comparison[0]))
            writer.writeheader()
            writer.writerows(comparison)
            f.flush()
            os.fsync(f.fileno())
        comparison_result = {
            "old_pullback_id": old_pb,
            "new_native_pullback_id": pb_id,
            "pullback_identity_equal": pb_identity_equal,
            "feature_values_compared": len(comparison),
            "strict_float_roundtrip_equal_count": sum(row["strict_float_roundtrip_equal"] for row in comparison),
            "strict_float_roundtrip_all_equal": all_equal,
            "feature_row_bytes": len(feature_blob),
            "feature_row_sha256": feature_sha,
            "positive_path_eligible": bool(pb_identity_equal and all_equal),
        }
        dump_json(run_dir / "OLD_ROW_COMPARISON_SUMMARY.json", comparison_result)
        if not pb_identity_equal or not all_equal:
            raise BoundedStop("NATIVE_ROW_DIFFERS_FROM_FROZEN_OLD_ROW", comparison_result)

        # Use exact V3 bytes verified above and actual R2 fields. Both calls are
        # made once with an explicit empty score set and no full-pool evidence.
        v3_path = run_dir / "selection_output_adapter.py"
        v3_spec = importlib.util.spec_from_file_location("p515_single_k3_pinned_gemini_v3", v3_path)
        if v3_spec is None or v3_spec.loader is None:
            raise BoundedStop("V3_IMPORT_SPEC_FAILED", {})
        adapter = importlib.util.module_from_spec(v3_spec)
        v3_spec.loader.exec_module(adapter)
        v3_input = {
            "security": SECURITY,
            "decision_date": "2026-11-17",
            "security_name": old_case["qualification_row"]["values"].get("简称", "胜利股份"),
            "prefilter_disposition": "PASS",
            "pullback_stage_k": 3,
            "r2_k3_qualified": True,
            "rule_version": observation.get("rule_version"),
            "parent_id": family_id,
            "pb_id": pb_id,
            "input_sha256": feature_sha,
            "parent_state": observation.get("stage"),
        }
        call_args = {
            "prefilter_records": [v3_input],
            "model_score_records": [],
            "full_pool_denominator_available": False,
            "d18_outcome_map": None,
            "pb15_audit_records": None,
        }
        dump_json(run_dir / "V3_EMPTY_SCORE_CALL_INPUT.json", call_args)
        v3_outputs: dict[str, Any] = {}
        for counter_key, function_name in (
            ("v3_strict_calls", "attach_model_scores_production"),
            ("v3_layered_calls", "build_selection_views_layered"),
        ):
            event({"event": "V3_ENTRY_CALL_START", "entry": function_name,
                   "prefilter_rows": 1, "model_score_rows": 0,
                   "full_pool_denominator_available": False,
                   "d18_outcome_map": None, "pb15_audit_records": None,
                   "input_6tuple": [v3_input[key] for key in
                                    ("security", "decision_date", "rule_version", "parent_id", "pb_id", "input_sha256")]})
            counters[counter_key] += 1
            try:
                output = getattr(adapter, function_name)(**call_args)
                v3_outputs[function_name] = {"call_status": "RETURNED", "output": output}
                event({"event": "V3_ENTRY_CALL_RETURN", "entry": function_name,
                       "model_score_rows": 0, "attached_score_count": output.get("counts", {}).get("k3_auxiliary_scored_total"),
                       "counts": output.get("counts"), "guard_execution_audit": output.get("guard_execution_audit")})
            except Exception as exc:
                v3_outputs[function_name] = {"call_status": "ERROR", "error_type": type(exc).__name__, "error": str(exc)}
                event({"event": "V3_ENTRY_CALL_ERROR", "entry": function_name,
                       "error_type": type(exc).__name__, "error": str(exc)})
        dump_json(run_dir / "V3_EMPTY_SCORE_CALL_OUTPUTS.json", {
            "pinned_v3_source_sha256": PINS["V3_SOURCE"],
            "actual_prefilter_input": v3_input,
            "model_score_records": [],
            "model_score_count": 0,
            "explicit_parameters": {"full_pool_denominator_available": False, "d18_outcome_map": None,
                                    "pb15_audit_records": None},
            "outputs": v3_outputs,
        })
        returned = [value for value in v3_outputs.values() if value.get("call_status") == "RETURNED"]
        zero_attachment = all(
            output["output"].get("counts", {}).get("k3_auxiliary_scored_total") == 0
            and output["output"].get("counts", {}).get("prefilter_pass_total") == 1
            and all(row.get("model_prob") is None for row in output["output"].get("main_candidates_pass", []))
            for output in returned
        )
        result_summary = {
            "run_id": run_id,
            "security": SECURITY,
            "decision_date": DASH,
            "reader_rows": len(rows),
            "reader_first_date": rows[0]["trade_date"],
            "reader_last_date": rows[-1]["trade_date"],
            "native_family_id": family_id,
            "native_pullback_id": pb_id,
            "r2_stage": observation.get("stage"),
            "pullback_sessions": observation.get("pullback_sessions"),
            "feature_row_bytes": len(feature_blob),
            "feature_row_sha256": feature_sha,
            "feature_comparison": comparison_result,
            "v3_output_entry_call_count": len(returned),
            "v3_two_calls_both_returned": len(returned) == 2,
            "v3_zero_attachment_confirmed": zero_attachment,
            "model_execution_counts": counters,
            "old_33_attach_count": 0,
            "historical_pit_status": "UNKNOWN",
            "unexposed_independent_validation_rows": 0,
            "production_published": False,
            "production_abcde_changed": False,
            "old_33_rows_modified": False,
            "old_26_rows_recomputed": False,
        }
        dump_json(run_dir / "RESULT_SUMMARY.json", result_summary)
        if len(returned) != 2 or not zero_attachment:
            raise BoundedStop("V3_EMPTY_SCORE_WIRING_ACCEPTANCE_FAILED", {
                "returned_entries": len(returned), "zero_attachment_confirmed": zero_attachment,
            })
        status = "PASS_SINGLE_NATIVE_K3_INPUT_CHAIN_ZERO_SCORE"
    except BoundedStop as exc:
        status = "BOUNDED_FAILURE"
        stop_code = exc.code
        stop_detail = exc.detail
    except Exception as exc:
        status = "BOUNDED_FAILURE"
        stop_code = "UNEXPECTED_FAILURE_NO_RETRY"
        stop_detail = {"error_type": type(exc).__name__, "error": str(exc)}
    finally:
        if call_events_path.exists():
            event({"event": "RUN_END", "status": status, "stop_code": stop_code, "counters": counters})
        receipt = {
            "run_id": run_id,
            "completed_at": now_beijing(),
            "status": status,
            "stop_code": stop_code,
            "stop_detail": stop_detail,
            "result_summary": result_summary,
            "actual_call_counters": counters,
            "source_files_copied": copied_sources if "copied_sources" in locals() else [],
            "unexecuted": ["model fit", "preprocessing fit", "model API", "new probabilities", "static new scores", "model deserialization"],
            "full_market_read": False,
            "other_security_read": False,
            "historical_dates_after_d17_read": False,
            "new_market_acquisition": 0,
        }
        try:
            dump_json(run_dir / "RUN_RECEIPT.json", receipt)
        except FileExistsError:
            pass
        # File manifest excludes itself and the independent parent receipt.
        manifest_rows = []
        for path in sorted(run_dir.iterdir()):
            if path.is_file() and path.name not in {"FILE_MANIFEST.json", "RUN_RECEIPT.json"}:
                data = path.read_bytes()
                manifest_rows.append({"file": path.name, "bytes": len(data), "sha256": sha256(data)})
        manifest = {
            "run_id": run_id,
            "generated_at": now_beijing(),
            "files": manifest_rows,
            "file_count_excluding_manifest_and_receipt": len(manifest_rows),
            "manifest_self_hash": "OMITTED_BY_CONTRACT",
        }
        try:
            dump_json(run_dir / "FILE_MANIFEST.json", manifest)
        except FileExistsError:
            pass
    print(json.dumps({"run_dir": str(run_dir), "run_id": run_id, "status": status,
                      "stop_code": stop_code, "stop_detail": stop_detail,
                      "counters": counters}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS_SINGLE_NATIVE_K3_INPUT_CHAIN_ZERO_SCORE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
