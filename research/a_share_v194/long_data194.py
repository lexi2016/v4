"""Bounded long-history adapter for the frozen A-share V194 input contract.

This module reads only the bound shared backtest panel and already accepted
source artifacts.  It does not collect data, write to a source producer, fit a
model, run OOF, score a strategy, or change a BUY/production boundary.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import heapq
import importlib.util
import io
import itertools
import json
import math
import multiprocessing
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from collections import Counter, defaultdict
from datetime import date, datetime, time as dt_time, timezone, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

# Keep numerical libraries at one native thread per process.  The full run is
# parallelized only at the eight frozen outer shards.
for _name in (
    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "BLIS_NUM_THREADS",
):
    os.environ[_name] = "1"

ROOT = Path("/Users/lexi/Desktop/学习/因子工厂")
S = ROOT / "worktrees/a_share_v194_20261023/research/a_share_v194"
CONTRACT_PATH = ROOT / "research/a_share_v194_long_history_20261024/preflight/LONG_INPUT_BUILD_CONTRACT.json"
START_RECEIPT_PATH = ROOT / "research/a_share_v194_long_history_20261024/preflight/LONG_INPUT_BUILD_REGISTRY_RECEIPT.json"
SNAPSHOT_PATH = ROOT / "research/a_share_v194_long_history_20261024/preflight/PANEL_BINDING_SNAPSHOT.json"
IMPLEMENTATION_CHECKPOINT_DIR = ROOT / "research/a_share_v194_long_history_20261024/preflight"
BUILD = ROOT / "research/a_share_v194_long_history_20261024/inputs/long_input_build_r1_20261024_01"
CANARY = ROOT / "research/a_share_v194_long_history_20261024/canary_data/A_SHARE_V194_LONG_INPUT_BUILD_R1_20261024_01/attempt_04"
EXPECTED_CONTRACT_SHA = "96fd0d23275335a84b63e94f6010081bf9ba272306594b0dd0cbde062f738575"
EXPECTED_START_RECEIPT_SHA = "a91cbc8cc52ee03847f5f94a59600823051335c413c2e911b94e06d8a32e893f"
EXPECTED_START_EVENT_SHA = "88de2b09738d942a1c9bf3fea35a4c03275feb8ab69f390b9b97aca780402c47"
EXPECTED_SNAPSHOT_SHA = "c90a0e29537387ad4f4c49020f16d52e0443a582bff0e441c48507b5d61f650d"
EXPECTED_ACCEPTED64_SHA = "04b6bb8ad1bd58e1154bd70234180cad78a29a02f935d04b7ee23cb8ebe181fa"
EXPECTED_ACCEPTED64_PATH = ROOT / "research/today_selection_20261023/stale318_recovery/resolution_02/final_market_event_delta_64/INPUT_MANIFEST.json"
EXPECTED_EVENT_INDEX_SHA = "534cc31866888940fab3eb346278b2e9ee4c39c3d26005b52780c6bd8627fc0e"
EXPECTED_R1_MANIFEST_SHA = "e5f57acb6e5555f3a08e8e76387b427bf50d57eb57560f6f80de2dda9594bfcf"
EXPECTED_CODE_LIST_SHA = "5186c209e784e58875e9f16202d99bd9ced945b9f7adcd0212c2f18869a6040d"
EXPECTED_CODE_LIST_COUNT = 5533
EXECUTION_ID = "A_SHARE_V194_LONG_INPUT_BUILD_R1_20261024_01"
TECHNICAL = [
    "tech_192", "B1", "B2", "B3", "BREAKOUT", "BREAKOUT_DOJI",
    "M2_MINUS", "M2_PLUS", "SINGLE_NEEDLE", "THREE_QUARTER_YIN", "BRICK_FANBAO",
]
SOURCES = ["source_fupan", "source_stage7", "source_research"]
SOURCE_LANE_MAP = {"fupan": "source_fupan", "stage7": "source_stage7", "research": "source_research"}
PANEL_COLUMNS = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]
PANEL_PRICE_FIELDS = ["open", "high", "low", "close"]
RAW_FIELDS = ["open", "high", "low", "close", "volume", "amount"]
SHARD_COUNT = 8
NATIVE_THREADS = 1
TZ = timezone(timedelta(hours=8))
EXPOSED = {"20261016", "20261019", "20261020", "20261021", "20261022"}
FLAGS = {
    "research_only": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
CANARY_CODES = [
    "000001.SZ", "000002.SZ", "000333.SZ", "600000.SH",
    "600036.SH", "600519.SH", "601398.SH", "001239.SZ",
]
RAW_CACHE = BUILD / "_intermediate" / "raw_panel"
CODE_RESULTS = BUILD / "_intermediate" / "per_code"
FULL_RECEIPT = BUILD / "PANEL_SCAN_RECEIPT.json"
RAW_FIELDS_MAP = {"open": "open", "high": "high", "low": "low", "close": "close", "volume": "vol", "amount": "amount"}
CANDIDATE_FIELDS = [
    "target_date", "signal_date", "code", "decision_at", "available_at", *TECHNICAL,
    *SOURCES, "candidate_reasons", "evidence_refs", "technical_status", "technical_exclusion_reason",
]
TRUTH_FIELDS = [
    "target_date", "signal_date", "code", "return", "raw_close", "reference_close", "rank",
    "label", "label_end_at", "label_available_at", "label_maturity_basis", "binding_ref",
]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json(path: Path | str) -> Any:
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def ymd(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii")
    if isinstance(value, (int,)):
        result = f"{value:08d}"
    elif hasattr(value, "item") and isinstance(value.item(), int):
        result = f"{int(value.item()):08d}"
    else:
        result = str(value).strip()
        if result.endswith(".0") and result[:-2].isdigit():
            result = result[:-2]
        result = result.replace("-", "")
    require(len(result) == 8 and result.isdigit(), "PANEL_DATE_NOT_YYYYMMDD:" + repr(value))
    date(int(result[:4]), int(result[4:6]), int(result[6:8]))
    return result


def iso_day(value: str) -> str:
    value = ymd(value)
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


@lru_cache(maxsize=2048)
def decision_at(target: str) -> datetime:
    return datetime.combine(date.fromisoformat(iso_day(target)), dt_time(9, 25), TZ)


def close_available_at(signal: str) -> str:
    return datetime.combine(date.fromisoformat(iso_day(signal)), dt_time(15, 0), TZ).isoformat()


def parse_aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    require(parsed.tzinfo is not None, "SOURCE_TIMEZONE_REQUIRED")
    return parsed


def fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(sha_file(path) == hashlib.sha256(payload).hexdigest(), "OUTPUT_EXISTS_DIFFERENT:" + str(path))
        return
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    require(not tmp.exists(), "TEMP_OUTPUT_EXISTS:" + str(tmp))
    with tmp.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def atomic_json(path: Path, value: Any) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    atomic_bytes(path, payload)


def write_csv_new(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    require(not tmp.exists(), "TEMP_OUTPUT_EXISTS:" + str(tmp))
    with tmp.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(fieldnames), extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_value(row.get(k)) for k in fieldnames})
        stream.flush()
        os.fsync(stream.fileno())
    if path.exists():
        require(sha_file(tmp) == sha_file(path), "OUTPUT_EXISTS_DIFFERENT:" + str(path))
        tmp.unlink()
    else:
        os.replace(tmp, path)
        fsync_dir(path.parent)


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def read_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        yield from csv.DictReader(stream)


def code_list_path() -> Path:
    return BUILD / "RESEARCH_CODE_KEYS.csv"


def read_code_keys(path: Path | None = None) -> list[str]:
    path = path or code_list_path()
    require(path.is_file(), "RESEARCH_CODE_LIST_MISSING")
    require(sha_file(path) == EXPECTED_CODE_LIST_SHA, "RESEARCH_CODE_LIST_SHA_DRIFT")
    rows = list(read_csv_rows(path))
    codes = [row["code"] for row in rows]
    require(len(codes) == EXPECTED_CODE_LIST_COUNT, "RESEARCH_CODE_COUNT_DRIFT")
    require(codes == sorted(set(codes)), "RESEARCH_CODE_KEYS_NOT_SORTED_UNIQUE")
    return codes


def panel_stat(path: Path) -> dict[str, int]:
    st = path.stat()
    return {"inode": int(st.st_ino), "mtime_ns": int(st.st_mtime_ns), "size": int(st.st_size)}


def validate_panel_binding(contract: Mapping[str, Any], snapshot: Mapping[str, Any]) -> tuple[Path, dict[str, int]]:
    binding = snapshot["panel_bindings"]["backtest"]
    require(binding.get("selected_for_long_input_build") is True, "BACKTEST_PANEL_NOT_SELECTED")
    schema = snapshot["selected_panel_schema"]
    require(schema["columns_read_only"] == PANEL_COLUMNS, "PANEL_COLUMN_BINDING_DRIFT")
    require("no additional round/int cast" in schema["conversion_rule"], "PANEL_CAST_RULE_DRIFT")
    pointer = Path(binding["pointer_path"])
    require(sha_file(pointer) == binding["pointer_sha256"], "PANEL_POINTER_SHA_DRIFT")
    pointer_target = pointer.read_text(encoding="utf-8").strip()
    target = Path(binding["target_path"])
    require(pointer_target == str(target), "PANEL_POINTER_TARGET_DRIFT")
    require(schema.get("path") == str(target), "PANEL_SCHEMA_TARGET_DRIFT")
    actual = panel_stat(target)
    expected = binding["target_stat_at_freeze"]
    expected = {"inode": int(expected["inode"]), "mtime_ns": int(expected["mtime_ns"]), "size": int(expected["size"])}
    require(actual == expected, "PANEL_TARGET_STAT_DRIFT")
    require(contract["input_identity"]["panel_target_sha_is_producer_declared_not_currently_rehashed"] is True,
            "PANEL_SHA_POLICY_DRIFT")
    return target, actual


def _verify_file_bindings(paths: Mapping[str, str], skip_own: bool = True) -> dict[str, str]:
    current: dict[str, str] = {}
    own = {str(S / "long_data194.py"), str(S / "test_long_data194.py")}
    for raw_path, expected in sorted(paths.items()):
        path = Path(raw_path)
        if skip_own and str(path) in own:
            continue
        if expected is None:
            continue
        require(path.is_file(), "BOUND_SOURCE_MISSING:" + str(path))
        actual = sha_file(path)
        require(actual == expected, "BOUND_SOURCE_SHA_DRIFT:" + str(path))
        current[str(path)] = actual
    return current


def _check_checkpoint(code_sha: str, test_sha: str, code_sha_list: str) -> dict[str, Any]:
    expected = {"implementation": code_sha, "tests": test_sha, "research_code_list": code_sha_list,
                "contract": EXPECTED_CONTRACT_SHA, "start_receipt": EXPECTED_START_RECEIPT_SHA,
                "accepted64_manifest": EXPECTED_ACCEPTED64_SHA}
    candidates = sorted(IMPLEMENTATION_CHECKPOINT_DIR.glob(
        "LONG_INPUT_BUILD_IMPLEMENTATION_BINDING_CHECKPOINT*.json"))
    matches: list[tuple[Path, dict[str, Any], Path, dict[str, Any]]] = []
    for checkpoint_path in candidates:
        if checkpoint_path.name.endswith("_REGISTRY_RECEIPT.json"):
            continue
        checkpoint = load_json(checkpoint_path)
        bindings = checkpoint.get("bindings", {})
        bound = checkpoint.get("execution_id") == EXECUTION_ID
        for binding, digest in expected.items():
            record = bindings.get(binding, {})
            bound = bound and isinstance(record, Mapping) and record.get("sha256") == digest
        if not bound:
            continue
        registry_receipt_path = checkpoint_path.with_name(checkpoint_path.stem + "_REGISTRY_RECEIPT.json")
        require(registry_receipt_path.is_file(), "IMPLEMENTATION_CHECKPOINT_REGISTRY_RECEIPT_MISSING")
        registry_receipt = load_json(registry_receipt_path)
        require(registry_receipt.get("stage") == checkpoint.get("stage"),
                "IMPLEMENTATION_CHECKPOINT_REGISTRY_STAGE_DRIFT")
        require(isinstance(registry_receipt.get("event_sha256"), str) and
                isinstance(registry_receipt.get("registry_sha256"), str),
                "IMPLEMENTATION_CHECKPOINT_REGISTRY_RECEIPT_INCOMPLETE")
        matches.append((checkpoint_path, checkpoint, registry_receipt_path, registry_receipt))
    require(len(matches) == 1, "IMPLEMENTATION_CHECKPOINT_MATCH_COUNT:" + str(len(matches)))
    checkpoint_path, checkpoint, registry_receipt_path, registry_receipt = matches[0]
    return {"path": str(checkpoint_path), "sha256": sha_file(checkpoint_path),
            "registry_receipt_path": str(registry_receipt_path),
            "registry_receipt_sha256": sha_file(registry_receipt_path),
            "event_sha256": registry_receipt["event_sha256"],
            "registry_sha256": registry_receipt["registry_sha256"],
            "stage": checkpoint["stage"]}


def _accepted64_manifest_path(contract: Mapping[str, Any]) -> Path:
    """Resolve the accepted64 manifest from its frozen input identity.

    This accepted64 manifest is not a member of ``frozen_source_bindings``;
    that map instead binds the separate 63-code parent manifest.  The direct
    event-manifest path and SHA are pinned in ``input_identity``.
    """
    identity = contract["input_identity"]
    path = Path(identity["event_manifest_path"])
    require(path == EXPECTED_ACCEPTED64_PATH, "ACCEPTED64_MANIFEST_PATH_DRIFT")
    require(identity["event_manifest_sha256"] == EXPECTED_ACCEPTED64_SHA,
            "ACCEPTED64_SHA_CONTRACT_DRIFT")
    return path


def load_context(*, require_checkpoint: bool) -> dict[str, Any]:
    require(sha_file(CONTRACT_PATH) == EXPECTED_CONTRACT_SHA, "LONG_INPUT_CONTRACT_SHA_DRIFT")
    require(sha_file(START_RECEIPT_PATH) == EXPECTED_START_RECEIPT_SHA, "LONG_INPUT_START_RECEIPT_SHA_DRIFT")
    require(sha_file(SNAPSHOT_PATH) == EXPECTED_SNAPSHOT_SHA, "PANEL_BINDING_SNAPSHOT_SHA_DRIFT")
    contract = load_json(CONTRACT_PATH)
    require(contract["execution_id"] == EXECUTION_ID and contract["run_stage"] == "LONG_INPUT_BUILD", "LONG_INPUT_EXECUTION_ID_DRIFT")
    code_bindings = contract["code_sha256"]
    require(code_bindings.get(str(S / "long_data194.py")) is None and
            code_bindings.get(str(S / "test_long_data194.py")) is None,
            "CONTRACT_INITIAL_CODE_BINDING_DRIFT")
    require(contract["input_identity"]["event_index_sha256"] == EXPECTED_EVENT_INDEX_SHA, "EVENT_INDEX_SHA_CONTRACT_DRIFT")
    snapshot = load_json(SNAPSHOT_PATH)
    target, initial_stat = validate_panel_binding(contract, snapshot)

    manifest_path = _accepted64_manifest_path(contract)
    event_index_path = Path(contract["input_identity"]["event_index_path"])
    require(sha_file(manifest_path) == EXPECTED_ACCEPTED64_SHA, "ACCEPTED64_MANIFEST_SHA_DRIFT")
    require(sha_file(event_index_path) == EXPECTED_EVENT_INDEX_SHA, "EVENT_INDEX_SHA_DRIFT")
    accepted = load_json(manifest_path)
    codes = read_code_keys()
    statuses_rows = accepted["all_input_statuses"]
    statuses = {row["code"]: row for row in statuses_rows}
    require(len(statuses) == EXPECTED_CODE_LIST_COUNT and sorted(statuses) == codes, "ACCEPTED64_CODE_SET_DRIFT")
    event_index = load_json(event_index_path)
    require(set(event_index) == set(codes), "EVENT_INDEX_CODE_SET_DRIFT")
    for code in codes:
        row = statuses[code]
        event = event_index[code]
        require(event.get("path") == row.get("event_response_path"), "EVENT_PATH_BINDING_DRIFT:" + code)
        require(event.get("sha256") == row.get("event_response_sha256"), "EVENT_SHA_BINDING_DRIFT:" + code)
    source_bindings = _verify_file_bindings(contract["frozen_source_bindings"])

    r1_manifest_path = Path(str(S / "unused"))
    for raw_path in contract["frozen_source_bindings"]:
        if raw_path.endswith("/repair_r1_20261024/inputs/MANIFEST_FINAL.json"):
            r1_manifest_path = Path(raw_path)
            break
    require(r1_manifest_path.is_file() and sha_file(r1_manifest_path) == EXPECTED_R1_MANIFEST_SHA, "R1_SOURCE_MANIFEST_SHA_DRIFT")
    r1_manifest = load_json(r1_manifest_path)
    source_hits_ref = r1_manifest["files"]["source_hits"]
    source_axes_ref = r1_manifest["files"]["research_three_axis"]
    source_hits_path = Path(source_hits_ref["path"])
    source_axes_path = Path(source_axes_ref["path"])
    require(sha_file(source_hits_path) == source_hits_ref["sha256"], "R1_SOURCE_HITS_SHA_DRIFT")
    require(sha_file(source_axes_path) == source_axes_ref["sha256"], "R1_SOURCE_AXES_SHA_DRIFT")

    code_sha = sha_file(S / "long_data194.py")
    test_path = S / "test_long_data194.py"
    require(test_path.is_file(), "LONG_INPUT_TEST_SOURCE_MISSING")
    test_sha = sha_file(test_path)
    code_list_sha = sha_file(code_list_path())
    checkpoint = _check_checkpoint(code_sha, test_sha, code_list_sha) if require_checkpoint else None
    return {
        "contract": contract, "snapshot": snapshot, "target": target, "initial_panel_stat": initial_stat,
        "accepted_manifest_path": manifest_path, "accepted_manifest": accepted, "statuses": statuses,
        "codes": codes, "event_index_path": event_index_path, "event_index": event_index,
        "r1_manifest_path": r1_manifest_path, "r1_manifest": r1_manifest,
        "source_hits_path": source_hits_path, "source_hits_sha256": source_hits_ref["sha256"],
        "source_axes_path": source_axes_path, "source_axes_sha256": source_axes_ref["sha256"],
        "frozen_source_sha256": source_bindings, "code_sha256": code_sha, "test_sha256": test_sha,
        "code_list_sha256": code_list_sha, "checkpoint": checkpoint,
    }


def assert_no_overwrite_dir(path: Path, identity: Mapping[str, Any]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    identity_path = path / "BUILD_IDENTITY.json"
    if identity_path.exists():
        existing = load_json(identity_path)
        require(existing == identity, "OUTPUT_BUILD_IDENTITY_DRIFT:" + str(path))
    else:
        allowed = {code_list_path()} if path == BUILD else set()
        extras = [entry for entry in path.iterdir() if entry not in allowed]
        require(not extras, "OUTPUT_DIRECTORY_HAS_UNBOUND_CONTENT:" + str(path) + ":" + repr(extras[:5]))
        if path == BUILD and code_list_path().exists():
            require(sha_file(code_list_path()) == EXPECTED_CODE_LIST_SHA, "RESEARCH_CODE_LIST_SHA_DRIFT")
        atomic_json(identity_path, identity)


def build_identity(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "V194_LONG_INPUT_BUILD_IDENTITY_V1",
        "execution_id": EXECUTION_ID,
        "contract_sha256": EXPECTED_CONTRACT_SHA,
        "start_receipt_sha256": EXPECTED_START_RECEIPT_SHA,
        "start_event_sha256": EXPECTED_START_EVENT_SHA,
        "panel_snapshot_sha256": EXPECTED_SNAPSHOT_SHA,
        "panel_target_path": str(ctx["target"]),
        "panel_target_stat": ctx["initial_panel_stat"],
        "panel_target_sha256_status": "PRODUCER_DECLARED_NOT_REHASHED",
        "accepted64_manifest_sha256": EXPECTED_ACCEPTED64_SHA,
        "event_index_sha256": EXPECTED_EVENT_INDEX_SHA,
        "research_code_count": EXPECTED_CODE_LIST_COUNT,
        "research_code_list_sha256": ctx["code_list_sha256"],
        "r1_source_manifest_sha256": EXPECTED_R1_MANIFEST_SHA,
        "r1_source_hits_sha256": ctx["source_hits_sha256"],
        "r1_source_axes_sha256": ctx["source_axes_sha256"],
        "implementation_sha256": ctx["code_sha256"],
        "tests_sha256": ctx["test_sha256"],
        "implementation_checkpoint_sha256": ctx["checkpoint"]["sha256"],
        "native_threads": NATIVE_THREADS,
        "outer_workers": SHARD_COUNT,
        "fit_enabled": False,
        "oof_enabled": False,
        **FLAGS,
    }


def replace_atomic_json(path: Path, value: Any) -> None:
    """Atomically replace a checkpoint owned by this execution only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    require(not tmp.exists(), "TEMP_CHECKPOINT_EXISTS:" + str(tmp))
    with tmp.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)
    fsync_dir(path.parent)


def resource_snapshot(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"cpu_count": os.cpu_count(), "disk_free_bytes": shutil.disk_usage(path).free}
    try:
        import psutil
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        result.update(memory_total_bytes=int(vm.total), memory_available_bytes=int(vm.available),
                      memory_percent=float(vm.percent), swap_total_bytes=int(sw.total), swap_used_bytes=int(sw.used))
    except Exception as exc:
        result["psutil_status"] = "UNAVAILABLE:" + type(exc).__name__
        if platform.system() == "Darwin":
            try:
                raw = subprocess.run(["/usr/sbin/sysctl", "-n", "vm.swapusage"], check=True,
                                     capture_output=True, text=True, timeout=5).stdout.strip()
                result["swap_sysctl_raw"] = raw
                used = re.search(r"used\s*=\s*([0-9.]+)\s*([KMGT])", raw, re.IGNORECASE)
                if used:
                    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
                    result["swap_used_bytes"] = int(float(used.group(1)) * units[used.group(2).upper()])
            except Exception as e:
                result["swap_sysctl_status"] = "UNAVAILABLE:" + type(e).__name__
            try:
                result["memory_total_bytes"] = int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
            except Exception:
                pass
            try:
                result["memory_pressure_raw"] = subprocess.run(["/usr/bin/memory_pressure", "-Q"], check=True,
                    capture_output=True, text=True, timeout=5).stdout.strip()
                free = re.search(r"free percentage:\s*([0-9.]+)%", result["memory_pressure_raw"], re.IGNORECASE)
                if free and result.get("memory_total_bytes"):
                    result["memory_percent"] = 100.0 - float(free.group(1))
                    result["memory_available_bytes"] = int(result["memory_total_bytes"] * float(free.group(1)) / 100.0)
            except Exception as e:
                result["memory_pressure_status"] = "UNAVAILABLE:" + type(e).__name__
    return result


def validate_panel_schema(path: Path) -> dict[str, str]:
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pq.ParquetFile(path).schema_arrow
    require(all(schema.names.count(name) == 1 for name in PANEL_COLUMNS),
            "PANEL_SCHEMA_COLUMNS_DRIFT:" + repr(schema.names))
    types = {name: str(schema.field(name).type) for name in PANEL_COLUMNS}
    require(pa.types.is_dictionary(schema.field("ts_code").type) or pa.types.is_string(schema.field("ts_code").type),
            "PANEL_CODE_TYPE_UNSUPPORTED:" + types["ts_code"])
    require(pa.types.is_int32(schema.field("trade_date").type), "PANEL_DATE_TYPE_UNSUPPORTED:" + types["trade_date"])
    for name in PANEL_PRICE_FIELDS + ["vol", "amount"]:
        require(pa.types.is_float32(schema.field(name).type), "PANEL_FLOAT32_REQUIRED:" + name + ":" + types[name])
    return types


def _npz_bytes(arrays: Mapping[str, Any]) -> bytes:
    import numpy as np
    generated = io.BytesIO()
    np.savez(generated, **arrays)
    normalized = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(generated.getvalue()), "r") as source:
        with zipfile.ZipFile(normalized, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as target:
            for name in source.namelist():
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = 0o600 << 16
                target.writestr(info, source.read(name))
    return normalized.getvalue()


def _raw_identity(identity: Mapping[str, Any], codes: Sequence[str], panel_stat_at_start: Mapping[str, int]) -> dict[str, Any]:
    return {"schema": "V194_LONG_PANEL_RAW_CACHE_V1", "execution_id": EXECUTION_ID,
            "build_identity_sha256": canonical_sha(identity), "code_list_sha256": EXPECTED_CODE_LIST_SHA,
            "codes": list(codes), "panel_target_stat": dict(panel_stat_at_start),
            "columns": PANEL_COLUMNS, "conversion_rule": "PANEL_FLOAT32_VALUES_AS_READ_NO_ROUND_OR_INT_CAST"}


def _raw_cache_path(directory: Path, code: str) -> Path:
    return directory / (code.replace(".", "_") + ".npz")


def scan_panel(ctx: Mapping[str, Any], codes: Sequence[str], directory: Path, receipt_path: Path,
               identity: Mapping[str, Any]) -> dict[str, Any]:
    """Read the bound panel once, retaining only requested pool keys and observed global dates."""
    import numpy as np
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    target: Path = ctx["target"]
    before = panel_stat(target)
    require(before == ctx["initial_panel_stat"], "PANEL_TARGET_STAT_DRIFT_BEFORE_SCAN")
    expected_raw = _raw_identity(identity, codes, before)
    if receipt_path.is_file():
        receipt = load_json(receipt_path)
        require(receipt.get("raw_identity") == expected_raw, "PANEL_SCAN_RECEIPT_IDENTITY_DRIFT")
        for code, binding in receipt["raw_files"].items():
            path = directory / binding["filename"]
            require(path.is_file() and sha_file(path) == binding["sha256"], "RAW_PANEL_CACHE_SHA_DRIFT:" + code)
        require(receipt.get("calendar_sessions") and receipt.get("panel_rows_scanned", 0) > 0,
                "PANEL_SCAN_RECEIPT_INCOMPLETE")
        require(panel_stat(target) == before, "PANEL_TARGET_STAT_DRIFT_AFTER_CACHE_READ")
        return receipt

    directory.mkdir(parents=True, exist_ok=True)
    id_path = directory / "RAW_CACHE_IDENTITY.json"
    if id_path.exists():
        require(load_json(id_path) == expected_raw, "RAW_PANEL_CACHE_IDENTITY_DRIFT")
    else:
        require(not any(directory.iterdir()), "RAW_PANEL_CACHE_HAS_UNBOUND_CONTENT")
        atomic_json(id_path, expected_raw)

    types = validate_panel_schema(target)
    code_index = {code: i for i, code in enumerate(codes)}
    buckets: list[dict[str, dict[str, list[Any]]]] = [dict() for _ in range(SHARD_COUNT)]
    sessions: set[str] = set()
    panel_rows = 0
    selected_rows = 0
    parquet = pq.ParquetFile(target)
    for batch in parquet.iter_batches(batch_size=131072, columns=PANEL_COLUMNS, use_threads=False):
        panel_rows += batch.num_rows
        dates = batch.column(batch.schema.get_field_index("trade_date")).to_numpy(zero_copy_only=False).astype("int32", copy=False)
        sessions.update(f"{int(d):08d}" for d in np.unique(dates))
        codes_array = batch.column(batch.schema.get_field_index("ts_code"))
        if pa.types.is_dictionary(codes_array.type):
            codes_array = pc.cast(codes_array, pa.string())
        ranks_arrow = pc.index_in(codes_array, value_set=pa.array(codes, type=pa.string()))
        ranks = pc.fill_null(ranks_arrow, -1).to_numpy(zero_copy_only=False).astype("int32", copy=False)
        selected = np.flatnonzero(ranks >= 0)
        if not len(selected):
            continue
        selected_rows += len(selected)
        selected_ranks = ranks[selected]
        order = np.argsort(selected_ranks, kind="stable")
        ordered_rows = selected[order]
        ordered_ranks = selected_ranks[order]
        boundaries = np.r_[0, np.flatnonzero(np.diff(ordered_ranks)) + 1, len(ordered_ranks)]
        col_arrays = {name: batch.column(batch.schema.get_field_index(name)).to_numpy(zero_copy_only=False)
                      for name in ["trade_date", *RAW_FIELDS_MAP.values()]}
        for left, right in zip(boundaries[:-1], boundaries[1:]):
            rank = int(ordered_ranks[left])
            code = codes[rank]
            shard = rank % SHARD_COUNT
            refs = buckets[shard].setdefault(code, {k: [] for k in ["trade_date", *RAW_FIELDS_MAP]})
            idx = ordered_rows[left:right]
            refs["trade_date"].append(col_arrays["trade_date"][idx].astype("int32", copy=True))
            for raw_name, panel_name in RAW_FIELDS_MAP.items():
                values = col_arrays[panel_name][idx]
                require(values.dtype == np.dtype("float32"), "PANEL_FLOAT32_VALUES_DTYPE_DRIFT:" + panel_name)
                refs[raw_name].append(values.copy())

    final_stat = panel_stat(target)
    require(final_stat == before, "PANEL_TARGET_STAT_DRIFT_DURING_SCAN")
    raw_files: dict[str, Any] = {}
    per_code_rows: dict[str, Any] = {}
    for shard in range(SHARD_COUNT):
        for code in sorted(buckets[shard]):
            parts = buckets[shard][code]
            arrays = {key: np.concatenate(value) if value else np.array([], dtype="int32" if key == "trade_date" else "float32")
                      for key, value in parts.items()}
            order = np.argsort(arrays["trade_date"], kind="stable")
            arrays = {key: value[order] for key, value in arrays.items()}
            dates = arrays["trade_date"]
            require(len(dates) == len(np.unique(dates)), "DUPLICATE_PANEL_CODE_DATE:" + code)
            for key, value in arrays.items():
                if key != "trade_date":
                    require(value.dtype == np.dtype("float32"), "RAW_CACHE_FLOAT32_CAST:" + code + ":" + key)
            path = _raw_cache_path(directory, code)
            atomic_bytes(path, _npz_bytes(arrays))
            raw_files[code] = {"filename": path.name, "sha256": sha_file(path), "rows": len(dates),
                               "first_date": f"{int(dates[0]):08d}" if len(dates) else None,
                               "last_date": f"{int(dates[-1]):08d}" if len(dates) else None,
                               "shard": shard}
            per_code_rows[code] = len(dates)
    missing_cache = sorted(set(codes) - set(raw_files))
    # A zero-row pool key still receives an explicit empty raw cache.
    for code in missing_cache:
        arrays = {key: np.array([], dtype="int32" if key == "trade_date" else "float32") for key in ["trade_date", *RAW_FIELDS_MAP]}
        path = _raw_cache_path(directory, code)
        atomic_bytes(path, _npz_bytes(arrays))
        raw_files[code] = {"filename": path.name, "sha256": sha_file(path), "rows": 0,
                           "first_date": None, "last_date": None, "shard": code_index[code] % SHARD_COUNT}
        per_code_rows[code] = 0
    receipt = {
        "schema": "V194_LONG_PANEL_SCAN_RECEIPT_V1", "raw_identity": expected_raw,
        "panel_path": str(target), "panel_stat_before": before, "panel_stat_after": final_stat,
        "panel_rows_scanned": panel_rows, "pool_rows_retained": selected_rows,
        "research_code_count": len(codes), "research_codes_with_rows": sum(v > 0 for v in per_code_rows.values()),
        "research_codes_without_rows": sorted(code for code, count in per_code_rows.items() if count == 0),
        "per_code_rows": per_code_rows, "raw_files": raw_files,
        "calendar_sessions": sorted(sessions), "calendar_count": len(sessions),
        "calendar_first": min(sessions) if sessions else None, "calendar_last": max(sessions) if sessions else None,
        "observed_panel_types": types, "conversion_rule": "PANEL_FLOAT32_VALUES_AS_READ_NO_ROUND_OR_INT_CAST",
        "official_calendar_parity": "CANNOT_CONFIRM", **FLAGS,
    }
    require(len(receipt["calendar_sessions"]) >= 2, "PANEL_CALENDAR_TOO_SHORT")
    atomic_json(receipt_path, receipt)
    require(panel_stat(target) == before, "PANEL_TARGET_STAT_DRIFT_AFTER_SCAN")
    return receipt


def _load_engines() -> tuple[Any, Any, Any, Any, Any, Any]:
    if str(S) not in sys.path:
        sys.path.insert(0, str(S))
    import data194
    engine, old_contract, original, kernel, program = data194.engines()
    require(list(kernel.RULES) == TECHNICAL[1:], "FROZEN_11_FLAG_DEFINITION_DRIFT")
    return engine, old_contract, original, kernel, program, data194


def load_source_axes(ctx: Mapping[str, Any]) -> dict[str, Any]:
    hits_raw = load_json(ctx["source_hits_path"])
    axes_path = ctx["source_axes_path"]
    topic_ref = ctx["r1_manifest"]["files"].get("research_topic_entities")
    if topic_ref:
        require(sha_file(Path(topic_ref["path"])) == topic_ref["sha256"], "R1_TOPIC_ENTITY_SHA_DRIFT")
        topic_rows = load_json(topic_ref["path"])
    else:
        topic_rows = []
    hits: dict[tuple[str, str], dict[str, Any]] = {}
    excluded_late: list[dict[str, Any]] = []
    for row in hits_raw:
        target = ymd(row["target_date"])
        code = str(row["code"])
        cutoff = decision_at(target)
        good: dict[str, Any] = {}
        for lane, evidence in row.get("lanes", {}).items():
            out_name = SOURCE_LANE_MAP.get(lane)
            if not out_name:
                continue
            try:
                available = parse_aware(evidence["available_at"])
            except Exception as exc:
                excluded_late.append({"target_date": target, "code": code, "lane": lane,
                                      "reason": "SOURCE_TIME_INVALID:" + type(exc).__name__})
                continue
            if available <= cutoff:
                good[out_name] = {**evidence, "available_at": available.isoformat(), "state": "hit"}
            else:
                excluded_late.append({"target_date": target, "code": code, "lane": lane,
                                      "available_at": available.isoformat(), "reason": "SOURCE_AFTER_0925_CUTOFF"})
        if good:
            hits[(target, code)] = good
    axes: dict[tuple[str, str], dict[str, str]] = {}
    for row in read_csv_rows(axes_path):
        target = ymd(row["target_date"])
        code = str(row["code"])
        axes[(target, code)] = row
    topic_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    code_by_six = {code[:6]: code for code in ctx["codes"]}
    for row in topic_rows:
        code = str(row.get("code") or "")
        if len(code) == 6 and code.isdigit():
            # The accepted topic artifact uses six-digit entity keys; bind it to the explicit pool code suffix.
            full_code = code_by_six.get(code)
            if full_code:
                topic_by_key[(ymd(row["target_date"]), full_code)].append(row)
    return {"hits": hits, "axes": axes, "topics": topic_by_key, "late_exclusions": excluded_late,
            "source_hit_input_rows": len(hits_raw), "three_axis_rows": len(axes), "topic_entity_rows": len(topic_rows)}


def _sma_series(values: Sequence[float], period: int) -> list[float]:
    if not values:
        return []
    weight = 1.0 / period
    result = [float(values[0])]
    for value in values[1:]:
        result.append(float(value) * weight + result[-1] * (1.0 - weight))
    return result


def brick_value_series(high: Sequence[float], low: Sequence[float], close: Sequence[float]) -> list[float]:
    """O(N) equivalent of calculate_brick_value for every full prefix."""
    n = len(close)
    require(len(high) == len(low) == n, "BRICK_INPUT_LENGTH_MISMATCH")
    values = [0.0] * n
    if n < 12:
        return values
    var3: list[float] = []
    var1: list[float] = []
    for i in range(3, n):
        hhv = max(float(x) for x in high[max(0, i - 3):i + 1])
        llv = min(float(x) for x in low[max(0, i - 3):i + 1])
        if hhv == llv:
            var3.append(50.0)
            var1.append(-90.0)
        else:
            var3.append((float(close[i]) - llv) / (hhv - llv) * 100.0)
            var1.append((hhv - float(close[i])) / (hhv - llv) * 100.0 - 90.0)
    var4 = _sma_series(var3, 6)
    var5 = _sma_series(var4, 6)
    var2 = _sma_series(var1, 4)
    for i in range(11, n):
        offset = i - 3
        var6 = var5[offset] - var2[offset]
        values[i] = round(var6 - 4.0 if var6 > 4.0 else 0.0, 2)
    return values


def brick_fanbao_series(high: Sequence[float], low: Sequence[float], close: Sequence[float], valid_prefix: Sequence[bool]) -> list[int | None]:
    values = brick_value_series(high, low, close)
    result: list[int | None] = [None] * len(close)
    prefix_ok = True
    for i in range(len(close)):
        prefix_ok = prefix_ok and bool(valid_prefix[i])
        if i < 13 or not prefix_ok:
            continue
        today, yesterday, before = values[i], values[i - 1], values[i - 2]
        gap = abs(yesterday - before)
        threshold = min(yesterday, before) + gap * 2.0 / 3.0
        result[i] = int(today > yesterday and yesterday < before and gap > 0 and today > threshold)
    return result


def _clean_kernel_columns(projected: Mapping[str, Any]) -> dict[str, Any]:
    import numpy as np
    columns = {key: np.asarray(projected[field], dtype=float).copy()
               for key, field in (("C", "close"), ("H", "high"), ("L", "low"), ("VOL", "volume"))}
    for key, values in columns.items():
        values[(~np.isfinite(values)) | (values < 0 if key == "VOL" else values <= 0)] = np.nan
    c, h, l = (columns[k] for k in ("C", "H", "L"))
    bad = np.isfinite(c) & np.isfinite(h) & np.isfinite(l) & ((h < c) | (l > c) | (h < l))
    for key in ("C", "H", "L"):
        columns[key][bad] = np.nan
    return columns


def raw_array_sha(dates: Sequence[str], raw: Mapping[str, Any]) -> str:
    import numpy as np
    h = hashlib.sha256()
    h.update(b"V194_PANEL_RAW_STOCK_V1\0")
    for value in dates:
        h.update(value.encode("ascii"))
        h.update(b"\0")
    for field in RAW_FIELDS:
        arr = np.asarray(raw[field], dtype="float32")
        h.update(field.encode("ascii") + b"\0")
        h.update(arr.astype("<f4", copy=False).tobytes(order="C"))
    return h.hexdigest()


def _source_row(target: str, code: str, source_axes: Mapping[str, Any], signal: str) -> tuple[dict[str, str], dict[str, Any]]:
    decision = decision_at(target)
    hits = source_axes["hits"].get((target, code), {})
    states = {column: "unknown" for column in SOURCES}
    evidence: dict[str, Any] = {}
    for column, item in hits.items():
        if parse_aware(item["available_at"]) <= decision:
            states[column] = "hit"
            evidence[column] = item
    axes = source_axes["axes"].get((target, code), {})
    topics = source_axes["topics"].get((target, code), [])
    refs = sorted({str(row.get("resource_ref_sha256")) for row in topics if row.get("resource_ref_sha256")})
    raw_text_status = sorted({str(row.get("raw_publication_reconstruction_state") or "unknown") for row in topics})
    return states, {"source_evidence": evidence, "pool_membership": axes.get("actual_pool_snapshot_membership", "UNKNOWN_NOT_BOUND_FOR_THIS_KEY"),
                    "pool_snapshot_not_decision_complete": axes.get("actual_pool_snapshot_not_decision_complete", "True"),
                    "raw_text_resource_refs": refs, "raw_text_status": raw_text_status,
                    "subject_true_topics": axes.get("subject_true_topics", "0"),
                    "subject_false_topics": axes.get("subject_false_topics", "0"),
                    "subject_unknown_topics": axes.get("subject_unknown_topics", "0"),
                    "declared_topics": axes.get("declared_topics", "0"),
                    "compatibility_topics": axes.get("compatibility_topics", "0"),
                    "research_subject_evidence_qualification": ";".join(sorted({str(row.get("research_subject_evidence_qualification") or "UNKNOWN") for row in topics})),
                    "subject_qualification_used_as_admission_filter": False,
                    "raw_source_text_sha256_refs": refs}


def classify_candidate(flags: Mapping[str, Any], states: Mapping[str, str]) -> dict[str, Any]:
    technical_triggers = [field for field in TECHNICAL if flags.get(field) == 1]
    source_triggers = [field for field in SOURCES if states.get(field) == "hit"]
    return {"technical_triggers": technical_triggers, "source_triggers": source_triggers,
            "model_complete": all(flags.get(field) is not None for field in TECHNICAL),
            "raw_union_member": bool(technical_triggers or source_triggers),
            "formula_natural_member": flags.get("tech_192") == 1}


def _truth_arrays(dates: Sequence[str], raw: Mapping[str, Any], events: Sequence[Mapping[str, Any]], unsupported: Sequence[str],
                  calendar_pairs: Sequence[tuple[str, str]]) -> tuple[Any, Any, Any, list[str]]:
    import numpy as np
    index = {day: i for i, day in enumerate(dates)}
    event_dates = [str(e["date"]) for e in events]
    returns = np.full(len(calendar_pairs), np.nan, dtype="float64")
    raw_closes = np.full(len(calendar_pairs), np.nan, dtype="float64")
    ref_closes = np.full(len(calendar_pairs), np.nan, dtype="float64")
    from bisect import bisect_right
    close = np.asarray(raw["close"], dtype="float64")
    for pos, (signal, target) in enumerate(calendar_pairs):
        si = index.get(signal)
        ti = index.get(target)
        if si is None or ti is None or ti != si + 1:
            continue
        if any(signal < day <= target for day in unsupported):
            continue
        ref = float(close[si])
        target_close = float(close[ti])
        if not (math.isfinite(ref) and math.isfinite(target_close) and ref > 0 and target_close > 0):
            continue
        for event in events[bisect_right(event_dates, signal):bisect_right(event_dates, target)]:
            ref = ref * float(event["A"]) + float(event["B"])
        if math.isfinite(ref) and ref > 0:
            raw_closes[pos] = target_close
            ref_closes[pos] = ref
            returns[pos] = target_close / ref - 1.0
    return returns, raw_closes, ref_closes, event_dates


def _evaluate_stock(code: str, raw: Mapping[str, Any], status: Mapping[str, Any], calendar_pairs: Sequence[tuple[str, str]],
                    source_axes: Mapping[str, Any], identity_sha: str, engines: tuple[Any, Any, Any, Any, Any, Any],
                    *, exact_parity: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    import numpy as np
    engine, old_contract, original, kernel, program, data_module = engines
    dates_int = np.asarray(raw["trade_date"], dtype="int32")
    dates = [f"{int(value):08d}" for value in dates_int]
    require(dates == sorted(set(dates)), "RAW_PANEL_DATES_NOT_SORTED_UNIQUE:" + code)
    raw_values = {field: np.asarray(raw[field], dtype="float64") for field in RAW_FIELDS}
    raw_sha = raw_array_sha(dates, raw)
    stock_binding = {"code": code, "raw_panel_sha256": raw_sha, "panel_rows": len(dates),
                     "first_date": dates[0] if dates else None, "last_date": dates[-1] if dates else None,
                     "event_response_path": status.get("event_response_path"),
                     "event_response_sha256": status.get("event_response_sha256"),
                     "status": status.get("status"), "event_projection": "ACCEPTED_ENGINE_PROJECT"}
    binding_ref = canonical_sha(stock_binding)
    truth_returns = np.full(len(calendar_pairs), np.nan, dtype="float64")
    truth_raw_close = np.full(len(calendar_pairs), np.nan, dtype="float64")
    truth_ref_close = np.full(len(calendar_pairs), np.nan, dtype="float64")
    event_dates: list[str] = []
    event_error = None
    events: list[dict[str, Any]] = []
    unsupported: list[str] = []
    if status.get("status") not in {"READY", "READY_WITH_ROUTE_LEVEL_MISSING_FIELDS"}:
        event_error = "EVENT_SOURCE_STATUS:" + str(status.get("status"))
    else:
        try:
            events, unsupported = engine.events(status)
            truth_returns, truth_raw_close, truth_ref_close, event_dates = _truth_arrays(
                dates, raw_values, events, unsupported, calendar_pairs)
        except Exception as exc:
            event_error = type(exc).__name__ + ":" + str(exc)

    idx_by_date = {day: i for i, day in enumerate(dates)}
    groups: dict[tuple[str, ...], list[tuple[str, str]]] = defaultdict(list)
    unavailable_signals: dict[str, str] = {}
    for signal, target in calendar_pairs:
        i = idx_by_date.get(signal)
        if i is None:
            unavailable_signals[signal] = "EXACT_SIGNAL_BAR_MISSING"
            continue
        if event_error:
            unavailable_signals[signal] = "EVENT_INPUT_UNAVAILABLE"
            continue
        regime = tuple(str(e["date"]) for e in events if str(e["date"]) <= signal)
        groups[regime].append((signal, target))

    technical_by_target: dict[str, dict[str, Any]] = {}
    parity_rows: list[dict[str, Any]] = []
    parity_target_dates: set[str] = set()
    for regime, pairs in groups.items():
        end = max(signal for signal, _ in pairs)
        end_index = idx_by_date[end]
        prefix_dates = dates[:end_index + 1]
        prefix_raw = {field: values[:end_index + 1] for field, values in raw_values.items()}
        regime_events = [e for e in events if str(e["date"]) <= end]
        projected = engine.project(prefix_dates, prefix_raw, regime_events, end)
        try:
            formula_values = original.evaluate(program, {
                "O": projected["open"], "H": projected["high"], "L": projected["low"],
                "C": projected["close"], "VOL": projected["volume"], "AMOUNT": projected["amount"],
            }, code)["XG"]
            formula_values = np.asarray(formula_values, dtype="float64")
        except Exception:
            formula_values = None
        try:
            columns = _clean_kernel_columns(projected)
            kernel_engine = kernel.Engine(columns)
            kernel_values = {rid: kernel_engine.named(name) for rid, name in kernel.RULES.items() if rid != "BRICK_FANBAO"}
            brick_valid = np.isfinite(columns["C"]) & np.isfinite(columns["H"]) & np.isfinite(columns["L"])
            bricks = brick_fanbao_series(columns["H"], columns["L"], columns["C"], brick_valid)
        except Exception:
            columns = None
            kernel_values = {}
            bricks = [None] * len(prefix_dates)
        for signal, target in pairs:
            i = idx_by_date[signal]
            flags: dict[str, int | None] = {field: None for field in TECHNICAL}
            reasons: list[str] = []
            if any(dates[0] < d <= signal for d in unsupported):
                reasons.append("UNSUPPORTED_SPLIT_EVENT")
            else:
                if formula_values is None or i >= len(formula_values) or not math.isfinite(float(formula_values[i])):
                    reasons.append("tech_192:TECHNICAL_192_UNAVAILABLE")
                else:
                    flags["tech_192"] = int(float(formula_values[i]) != 0.0)
                if columns is None:
                    reasons.append("TEN_BUY_POINT_ENGINE_UNAVAILABLE")
                else:
                    for rid in kernel.RULES:
                        if rid == "BRICK_FANBAO":
                            if bricks[i] is None:
                                reasons.append("BRICK_FANBAO:BRICK_HISTORY_UNAVAILABLE")
                            else:
                                flags[rid] = int(bricks[i])
                        else:
                            values = kernel_values.get(rid)
                            if values is None or i >= len(values) or not math.isfinite(float(values[i])):
                                reasons.append(rid + ":TECHNICAL_ROUTE_UNAVAILABLE")
                            else:
                                flags[rid] = int(float(values[i]) != 0.0)
            technical_by_target[target] = {
                "signal_date": signal, "flags": flags,
                "complete": all(flags[field] is not None for field in TECHNICAL),
                "reason": ";".join(sorted(set(reasons))) or None,
                "binding_ref": binding_ref,
            }
            if exact_parity and not reasons and all(flags[field] is not None for field in TECHNICAL):
                # Per-day exact calls are intentionally limited to frozen canary anchors.
                should_check = False
                position = i
                anchor_positions = {13, max(13, len(dates) // 4), max(13, len(dates) // 2),
                                    max(13, (3 * len(dates)) // 4), max(13, len(dates) - 1)}
                for event_date in event_dates:
                    event_pos = idx_by_date.get(event_date)
                    if event_pos is not None and position in {event_pos - 1, event_pos, event_pos + 1}:
                        should_check = True
                if position in anchor_positions:
                    should_check = True
                if should_check and target not in parity_target_dates:
                    exact_dates = dates[:i + 1]
                    exact_events = [e for e in events if str(e["date"]) <= signal]
                    exact_projected = engine.project(exact_dates,
                        {field: values[:i + 1] for field, values in raw_values.items()}, exact_events, signal)
                    exact_formula = original.evaluate(program, {
                        "O": exact_projected["open"], "H": exact_projected["high"], "L": exact_projected["low"],
                        "C": exact_projected["close"], "VOL": exact_projected["volume"], "AMOUNT": exact_projected["amount"],
                    }, code)["XG"][-1]
                    exact_model = kernel.evaluate_stock(code, exact_dates,
                        {"C": exact_projected["close"], "H": exact_projected["high"],
                         "L": exact_projected["low"], "VOL": exact_projected["volume"]}, signal_date=signal)
                    exact = {"tech_192": int(float(exact_formula) != 0.0),
                             **{row["rule_id"]: int(row["value"]) for row in exact_model["rules"] if row["value"] is not None}}
                    require(len(exact) == 11 and exact == flags, "CANARY_11_FLAG_PARITY_FAIL:" + code + ":" + target)
                    parity_rows.append({"code": code, "target_date": target, "signal_date": signal,
                                        "flags": flags, "event_regime": list(regime),
                                        "status": "EXACT_PER_DAY_ENGINE_PARITY"})
                    parity_target_dates.add(target)

    feature_complete = np.zeros(len(calendar_pairs), dtype="uint8")
    candidate_rows: list[dict[str, Any]] = []
    formula_rows: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    truth_index = {target: i for i, (_, target) in enumerate(calendar_pairs)}
    for signal, target in calendar_pairs:
        tech = technical_by_target.get(target)
        if tech and tech["complete"]:
            feature_complete[truth_index[target]] = 1
        flags = tech["flags"] if tech else {field: None for field in TECHNICAL}
        reason = tech["reason"] if tech else unavailable_signals.get(signal, "EXACT_SIGNAL_BAR_MISSING")
        states, source_evidence = _source_row(target, code, source_axes, signal)
        classified = classify_candidate(flags, states)
        technical_triggers = classified["technical_triggers"]
        source_triggers = classified["source_triggers"]
        if classified["formula_natural_member"]:
            formula_rows.append(_candidate_record(target, signal, code, flags, states, technical_triggers,
                                                  source_evidence, tech, reason, status, raw_sha))
        if not classified["raw_union_member"]:
            continue
        row = _candidate_record(target, signal, code, flags, states, technical_triggers,
                                source_evidence, tech, reason, status, raw_sha)
        candidate_rows.append(row)
        if not row["technical_status"] == "COMPLETE_11_FLAGS":
            exclusions.append({"target_date": target, "signal_date": signal, "code": code,
                               "reason": reason or "UNKNOWN_TECHNICAL_DEPENDENCY",
                               "known_flags": {k: v for k, v in flags.items()},
                               "unknown_flags": [field for field in TECHNICAL if flags.get(field) is None],
                               "source_triggers": source_triggers})
    stock = {**stock_binding, "binding_ref": binding_ref, "complete_11_flag_target_rows": int(feature_complete.sum()),
             "candidate_union_rows": len(candidate_rows), "formula_natural_rows": len(formula_rows),
             "technical_candidate_exclusions": len(exclusions), "event_count": len(events),
             "unsupported_event_dates": sorted(set(unsupported)), "event_status": "BOUND" if not event_error else event_error,
             "available_panel_history": bool(dates)}
    arrays = {"truth_returns": truth_returns, "truth_raw_close": truth_raw_close,
              "truth_reference_close": truth_ref_close, "technical_complete": feature_complete}
    details = {"code": code, "identity_sha256": identity_sha, "stock": stock,
               "candidate_rows": candidate_rows, "formula_rows": formula_rows,
               "technical_exclusions": exclusions, "parity_rows": parity_rows,
               "raw_panel_sha256": raw_sha}
    return details, arrays


def _candidate_record(target: str, signal: str, code: str, flags: Mapping[str, Any], states: Mapping[str, str],
                      technical_triggers: Sequence[str], source_evidence: Mapping[str, Any], tech: Mapping[str, Any] | None,
                      reason: str | None, status: Mapping[str, Any], raw_sha: str) -> dict[str, Any]:
    available_values = [close_available_at(signal)]
    available_values.extend(item["available_at"] for item in source_evidence["source_evidence"].values())
    available_at = max(available_values, key=parse_aware)
    decision = decision_at(target)
    require(parse_aware(available_at) <= decision, "CANDIDATE_DEPENDENCY_AFTER_0925:" + target + ":" + code)
    complete = all(flags.get(field) is not None for field in TECHNICAL)
    evidence = {"technical_binding_sha256": tech["binding_ref"] if tech else None,
                "raw_panel_sha256": raw_sha, "event_response_sha256": status.get("event_response_sha256"),
                "source_hits": source_evidence["source_evidence"],
                "pool_membership_axis": source_evidence["pool_membership"],
                "raw_source_text_sha256_refs": source_evidence["raw_text_resource_refs"],
                "subject_qualification_axis": source_evidence["research_subject_evidence_qualification"]}
    triggers = list(technical_triggers) + [field for field in SOURCES if states[field] == "hit"]
    return {"target_date": iso_day(target), "signal_date": iso_day(signal), "code": code,
            "decision_at": decision.isoformat(), "available_at": available_at,
            **{field: flags.get(field) for field in TECHNICAL}, **states,
            "candidate_reasons": "|".join(triggers), "evidence_refs": evidence,
            "technical_status": "COMPLETE_11_FLAGS" if complete else "UNKNOWN_TECHNICAL_DEPENDENCY",
            "technical_exclusion_reason": reason if not complete else ""}


def _result_path(directory: Path, code: str) -> Path:
    return directory / (code.replace(".", "_") + ".npz")


def _write_code_checkpoint(directory: Path, details: Mapping[str, Any], arrays: Mapping[str, Any]) -> tuple[Path, Path]:
    import numpy as np
    checkpoint_path = _result_path(directory, str(details["code"]))
    metadata = json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    compressed = gzip.compress(metadata, compresslevel=6, mtime=0)
    numeric = _npz_bytes({**arrays, "metadata_gzip": np.frombuffer(compressed, dtype="uint8")})
    if checkpoint_path.exists():
        old, old_arrays = _load_code_checkpoint(directory, str(details["code"]), str(details["identity_sha256"]))
        require(old == details, "CODE_CHECKPOINT_CONTENT_DRIFT:" + str(details["code"]))
        require(sha_file(checkpoint_path) == hashlib.sha256(numeric).hexdigest(), "CODE_NUMERIC_CHECKPOINT_DRIFT:" + str(details["code"]))
    else:
        atomic_bytes(checkpoint_path, numeric)
    return checkpoint_path, checkpoint_path


def _load_code_checkpoint(directory: Path, code: str, identity_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    import numpy as np
    checkpoint_path = _result_path(directory, code)
    require(checkpoint_path.is_file(), "CODE_CHECKPOINT_MISSING:" + code)
    with np.load(checkpoint_path, allow_pickle=False) as f:
        arrays = {key: f[key].copy() for key in f.files}
    details = json.loads(gzip.decompress(arrays.pop("metadata_gzip").tobytes()).decode("utf-8"))
    require(details.get("code") == code and details.get("identity_sha256") == identity_sha,
            "CODE_CHECKPOINT_IDENTITY_DRIFT:" + code)
    return details, arrays


def _process_shard(payload: Mapping[str, Any]) -> dict[str, Any]:
    import numpy as np
    code_list = list(payload["codes"])
    raw_dir = Path(payload["raw_dir"])
    out_dir = Path(payload["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    require(load_json(out_dir / "SHARD_IDENTITY.json") == payload["shard_identity"], "SHARD_IDENTITY_DRIFT")
    engines = _load_engines()
    completed = 0
    candidate_count = 0
    formula_count = 0
    exclusion_count = 0
    worker_peak_rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    progress_path = out_dir / "SHARD_PROGRESS.json"
    for code in code_list:
        checkpoint_path = _result_path(out_dir / "per_code", code)
        if checkpoint_path.exists():
            details, arrays = _load_code_checkpoint(out_dir / "per_code", code, payload["identity_sha256"])
        else:
            reusable = payload.get("reusable_checkpoints", {}).get(code)
            if reusable:
                details, arrays = _load_code_checkpoint(Path(reusable), code, payload["identity_sha256"])
            else:
                source = np.load(_raw_cache_path(raw_dir, code), allow_pickle=False)
                with source:
                    raw = {key: source[key].copy() for key in source.files}
                details, arrays = _evaluate_stock(code, raw, payload["statuses"][code], payload["calendar_pairs"],
                    payload["source_axes"], payload["identity_sha256"], engines, exact_parity=bool(payload["exact_parity"]))
            _write_code_checkpoint(out_dir / "per_code", details, arrays)
        completed += 1
        candidate_count += len(details["candidate_rows"])
        formula_count += len(details["formula_rows"])
        exclusion_count += len(details["technical_exclusions"])
        worker_peak_rss = max(worker_peak_rss, int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss))
        replace_atomic_json(progress_path, {"schema": "V194_LONG_INPUT_SHARD_PROGRESS_V1",
            "execution_id": EXECUTION_ID, "identity_sha256": payload["identity_sha256"],
            "shard": payload["shard"], "completed_codes": code_list[:completed], "completed_count": completed,
            "candidate_union_rows": candidate_count, "raw_formula_natural_rows": formula_count,
            "technical_candidate_exclusions": exclusion_count, "worker_peak_rss_raw": worker_peak_rss})
    return {"shard": payload["shard"], "codes": len(code_list), "completed_codes": completed,
            "candidate_union_rows": candidate_count, "raw_formula_natural_rows": formula_count,
            "technical_candidate_exclusions": exclusion_count, "worker_peak_rss_raw": worker_peak_rss,
            "progress_path": str(progress_path), "progress_sha256": sha_file(progress_path)}


def _subset_source_axes(source_axes: Mapping[str, Any], codes: Sequence[str]) -> dict[str, Any]:
    wanted = set(codes)
    return {key: {identity: row for identity, row in source_axes[key].items() if identity[1] in wanted}
            for key in ("hits", "axes", "topics")}


def run_projection(ctx: Mapping[str, Any], codes: Sequence[str], calendar_pairs: Sequence[tuple[str, str]],
                   source_axes: Mapping[str, Any], raw_dir: Path, output_dir: Path,
                   identity: Mapping[str, Any], *, exact_parity: bool,
                   selected_panel_rows: int = 0,
                   reusable_checkpoints: Mapping[str, str] | None = None) -> dict[str, Any]:
    out_code_dir = output_dir / "per_code"
    out_code_dir.mkdir(parents=True, exist_ok=True)
    identity_sha = canonical_sha(identity)
    shards: list[list[str]]
    if exact_parity:
        require(len(codes) == SHARD_COUNT, "CANARY_MUST_HAVE_EIGHT_CODES")
        shards = [[code] for code in codes]
    else:
        shards = [list(codes[i::SHARD_COUNT]) for i in range(SHARD_COUNT)]
    shard_root = output_dir / "shards"
    shard_root.mkdir(parents=True, exist_ok=True)
    payloads = []
    for shard_no, shard_codes in enumerate(shards):
        shard_dir = shard_root / f"shard_{shard_no:02d}"
        shard_dir.mkdir(parents=True, exist_ok=True)
        shard_identity = {"schema": "V194_LONG_INPUT_SHARD_IDENTITY_V1", "execution_id": EXECUTION_ID,
                          "identity_sha256": identity_sha, "shard": shard_no, "codes": shard_codes,
                          "outer_workers": SHARD_COUNT, "native_threads": NATIVE_THREADS}
        shard_identity_path = shard_dir / "SHARD_IDENTITY.json"
        if shard_identity_path.exists():
            require(load_json(shard_identity_path) == shard_identity, "SHARD_IDENTITY_DRIFT:" + str(shard_no))
        else:
            require(not any(shard_dir.iterdir()), "SHARD_DIR_UNBOUND_CONTENT:" + str(shard_dir))
            atomic_json(shard_identity_path, shard_identity)
        payloads.append({"shard": shard_no, "codes": shard_codes, "raw_dir": str(raw_dir),
                         "output_dir": str(shard_dir), "shard_identity": shard_identity,
                         "identity_sha256": identity_sha, "statuses": {c: ctx["statuses"][c] for c in shard_codes},
                         "calendar_pairs": list(calendar_pairs), "source_axes": _subset_source_axes(source_axes, shard_codes),
                         "exact_parity": exact_parity,
                         "reusable_checkpoints": {c: reusable_checkpoints[c] for c in shard_codes
                             if reusable_checkpoints and c in reusable_checkpoints}})
    start = time.monotonic()
    before = resource_snapshot(output_dir)
    require(before.get("disk_free_bytes", 0) > 10 * 1024**3, "INSUFFICIENT_FREE_DISK_BEFORE_PROJECTION")
    with ProcessPoolExecutor(max_workers=SHARD_COUNT, mp_context=multiprocessing.get_context("spawn")) as pool:
        summaries = list(pool.map(_process_shard, payloads, chunksize=1))
    elapsed = time.monotonic() - start
    after = resource_snapshot(output_dir)
    summaries.sort(key=lambda r: r["shard"])
    return {"schema": "V194_LONG_INPUT_PROJECTION_RESOURCE_RECEIPT_V1", "codes": len(codes),
            "elapsed_seconds": elapsed, "codes_per_second": len(codes) / elapsed if elapsed else None,
            "workers": SHARD_COUNT, "native_threads_per_worker": NATIVE_THREADS,
            "before_resources": before, "after_resources": after,
            "worker_peak_rss_raw": [row["worker_peak_rss_raw"] for row in summaries],
            "shard_summaries": summaries, "panel_rows_for_codes": selected_panel_rows,
            "execution_id": EXECUTION_ID, "identity_sha256": identity_sha, **FLAGS}


def calendar_pairs_from_receipt(receipt: Mapping[str, Any]) -> list[tuple[str, str]]:
    sessions = list(receipt["calendar_sessions"])
    require(sessions == sorted(set(sessions)), "PANEL_CALENDAR_NOT_SORTED_UNIQUE")
    return [(sessions[i - 1], sessions[i]) for i in range(1, len(sessions))]


def _event_anchor_checks(ctx: Mapping[str, Any], codes: Sequence[str], raw_dir: Path,
                         receipt: Mapping[str, Any], calendar_pairs: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    import numpy as np
    engine, old_contract, original, kernel, program, _ = _load_engines()
    target_prev = {target: signal for signal, target in calendar_pairs}
    checks: list[dict[str, Any]] = []
    for code in codes:
        status = ctx["statuses"][code]
        if status.get("status") not in {"READY", "READY_WITH_ROUTE_LEVEL_MISSING_FIELDS"}:
            continue
        ev, unsupported = engine.events(status)
        raw_path = _raw_cache_path(raw_dir, code)
        with np.load(raw_path, allow_pickle=False) as src:
            raw = {field: src[field].astype("float64") for field in RAW_FIELDS}
            dates = [f"{int(value):08d}" for value in src["trade_date"]]
        idx = {day: i for i, day in enumerate(dates)}
        for event in ev:
            target = str(event["date"])
            signal = target_prev.get(target)
            if signal is None or signal not in idx or target not in idx:
                continue
            si, ti = idx[signal], idx[target]
            projected = engine.project(dates[:ti + 1], {k: v[:ti + 1] for k, v in raw.items()},
                                       [e for e in ev if str(e["date"]) <= target], target)
            ref = float(raw["close"][si])
            applied = []
            for item in ev:
                if signal < str(item["date"]) <= target:
                    ref = ref * float(item["A"]) + float(item["B"])
                    applied.append(str(item["date"]))
            engine_ref = float(projected["close"][si])
            engine_target = float(projected["close"][ti])
            expected_target = float(raw["close"][ti])
            require(math.isclose(engine_ref, ref, rel_tol=0.0, abs_tol=1e-10),
                    "EVENT_ANCHOR_REFERENCE_PARITY_FAIL:" + code + ":" + target)
            require(math.isclose(engine_target, expected_target, rel_tol=0.0, abs_tol=1e-10),
                    "EVENT_ANCHOR_TARGET_PARITY_FAIL:" + code + ":" + target)
            checks.append({"code": code, "target_date": target, "signal_date": signal,
                           "event_dates_applied_between_signal_and_target": applied,
                           "event_response_path": status["event_response_path"],
                           "event_response_sha256": status["event_response_sha256"],
                           "reference_close_engine": engine_ref, "reference_close_manual": ref,
                           "target_close_engine": engine_target, "target_close_raw": expected_target,
                           "status": "SAME_TARGET_D_ANCHOR_EXACT_AFFINE_PARITY"})
    return checks


def _load_all_details(result_dir: Path, codes: Sequence[str], identity: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    identity_sha = canonical_sha(identity)
    details: list[dict[str, Any]] = []
    for index, code in enumerate(codes):
        item, _ = _load_code_checkpoint(_projection_code_dir(result_dir, index), code, identity_sha)
        details.append(item)
    return details, []


def _projection_code_dir(result_dir: Path, code_index: int) -> Path:
    """Read the authoritative shard checkpoint, including on a resumed run."""
    return result_dir / "shards" / f"shard_{code_index % SHARD_COUNT:02d}" / "per_code"


def run_canary() -> dict[str, Any]:
    require(CANARY_CODES == sorted(set(CANARY_CODES)) or len(CANARY_CODES) == len(set(CANARY_CODES)),
            "CANARY_CODE_LIST_DUPLICATE")
    ctx = load_context(require_checkpoint=True)
    require(set(CANARY_CODES) <= set(ctx["codes"]), "CANARY_CODE_NOT_IN_FROZEN_POOL")
    identity = build_identity(ctx)
    assert_no_overwrite_dir(CANARY, identity)
    source_axes = load_source_axes(ctx)
    before_resources = resource_snapshot(CANARY)
    scan_started = time.monotonic()
    scan_receipt = scan_panel(ctx, CANARY_CODES, CANARY / "raw_panel", CANARY / "PANEL_SCAN_RECEIPT.json", identity)
    scan_elapsed = time.monotonic() - scan_started
    pairs = calendar_pairs_from_receipt(scan_receipt)
    process_receipt = run_projection(ctx, CANARY_CODES, pairs, source_axes, CANARY / "raw_panel", CANARY,
                                     identity, exact_parity=True, selected_panel_rows=int(scan_receipt["pool_rows_retained"]))
    details, _ = _load_all_details(CANARY, CANARY_CODES, identity)
    parity_rows = [r for item in details for r in item["parity_rows"]]
    parity_by_code = Counter(row["code"] for row in parity_rows)
    require(all(parity_by_code.get(code, 0) > 0 for code in CANARY_CODES), "CANARY_NO_EXACT_PARITY_ANCHOR_PER_CODE")
    eventful = [code for code in CANARY_CODES if ctx["statuses"][code].get("event_count_le_D22", 0) > 0]
    require(eventful, "CANARY_HAS_NO_EVENT_AFFECTED_CODE")
    event_checks = _event_anchor_checks(ctx, CANARY_CODES, CANARY / "raw_panel", scan_receipt, pairs)
    require(any(row["event_dates_applied_between_signal_and_target"] for row in event_checks),
            "CANARY_NO_EVENT_ANCHOR_TRANSITION")
    import numpy as np
    volume_max: list[tuple[float, str]] = []
    amount_max: list[tuple[float, str]] = []
    precision: list[dict[str, Any]] = []
    for code in CANARY_CODES:
        path = _raw_cache_path(CANARY / "raw_panel", code)
        with np.load(path, allow_pickle=False) as src:
            volume = src["volume"]
            amount = src["amount"]
            require(volume.dtype == np.dtype("float32") and amount.dtype == np.dtype("float32"),
                    "CANARY_FLOAT32_RAW_VALUE_CAST:" + code)
            max_volume = float(np.nanmax(volume)) if len(volume) else float("nan")
            max_amount = float(np.nanmax(amount)) if len(amount) else float("nan")
            volume_max.append((max_volume if math.isfinite(max_volume) else -1.0, code))
            amount_max.append((max_amount if math.isfinite(max_amount) else -1.0, code))
            precision.append({"code": code, "panel_float32_dtype": str(volume.dtype),
                              "volume_max_as_stored": max_volume, "amount_max_as_stored": max_amount,
                              "float32_storage_preserved": True,
                              "volume_values_not_integer_cast": True, "amount_values_not_rounded": True})
    high_volume_code = max(volume_max)[1]
    after_resources = resource_snapshot(CANARY)
    available = after_resources.get("memory_available_bytes")
    mem_percent = after_resources.get("memory_percent")
    disk_free = after_resources.get("disk_free_bytes", 0)
    swap_before = before_resources.get("swap_used_bytes")
    swap_after = after_resources.get("swap_used_bytes")
    swap_delta = (swap_after - swap_before) if isinstance(swap_before, int) and isinstance(swap_after, int) else None
    resource_gate = bool(available is not None and mem_percent is not None and swap_delta is not None and
                         available >= 8 * 1024**3 and mem_percent < 90.0 and disk_free >= 20 * 1024**3 and
                         swap_delta <= 4 * 1024**3)
    require(resource_gate, "CANARY_RESOURCE_GATE_FAIL")
    code_coverage = [{"code": item["code"], "status": item["status"],
                      "history_first_date": item["first_date"], "history_last_date": item["last_date"],
                      "history_rows": item["panel_rows"], "event_count": item["event_count"],
                      "event_status": item["event_status"], "complete_11_flag_target_rows": item["complete_11_flag_target_rows"],
                      "exact_11_flag_parity_anchors": parity_by_code.get(item["code"], 0)}
                     for details_item in details for item in [details_item["stock"]]]
    receipt = {"schema": "V194_LONG_INPUT_CANARY_RECEIPT_V1", "execution_id": EXECUTION_ID,
               "contract_sha256": EXPECTED_CONTRACT_SHA, "start_event_sha256": EXPECTED_START_EVENT_SHA,
               "implementation_sha256": ctx["code_sha256"], "test_sha256": ctx["test_sha256"],
               "implementation_checkpoint": ctx["checkpoint"], "build_identity_sha256": canonical_sha(identity),
               "panel_scan_receipt": {"path": str(CANARY / "PANEL_SCAN_RECEIPT.json"),
                                      "sha256": sha_file(CANARY / "PANEL_SCAN_RECEIPT.json")},
               "panel_target_stat_before": ctx["initial_panel_stat"], "panel_target_stat_after": panel_stat(ctx["target"]),
               "panel_stat_unchanged": panel_stat(ctx["target"]) == ctx["initial_panel_stat"],
               "panel_rows_scanned": scan_receipt["panel_rows_scanned"], "pool_rows_retained": scan_receipt["pool_rows_retained"],
               "calendar_count": len(scan_receipt["calendar_sessions"]),
               "calendar_first": scan_receipt["calendar_first"], "calendar_last": scan_receipt["calendar_last"],
               "scan_wall_seconds": scan_elapsed, "scan_rows_per_second": scan_receipt["panel_rows_scanned"] / scan_elapsed if scan_elapsed else None,
               "projection_receipt": process_receipt, "canary_codes": CANARY_CODES,
               "coverage": code_coverage, "exact_per_day_engine_parity_rows": parity_rows,
               "event_anchor_checks": event_checks, "float32_precision_checks": precision,
               "measured_high_volume_code": high_volume_code,
               "max_canary_volume": max(volume_max), "max_canary_amount": max(amount_max),
               "resource_before_scan": before_resources, "resource_after_projection": after_resources,
               "swap_delta_bytes": swap_delta, "resource_gate_policy": {
                   "minimum_available_memory_bytes": 8 * 1024**3, "maximum_memory_percent": 90.0,
                   "minimum_free_disk_bytes": 20 * 1024**3, "maximum_swap_increase_bytes": 4 * 1024**3,
                   "unavailable_optional_metric_is_reported_not_inferred": True},
               "resource_gate_passed": resource_gate, "fit_count": 0, "oof_count": 0,
               "top50_selection_count": 0, "top100_truth_use": "LABEL_CONSTRUCTION_ONLY_NOT_ADMISSION",
               "status": "CANARY_PASS_INPUT_BUILD_MAY_CONTINUE", "official_calendar_parity": "CANNOT_CONFIRM", **FLAGS}
    require(receipt["panel_stat_unchanged"], "PANEL_TARGET_STAT_DRIFT_AFTER_CANARY")
    atomic_json(CANARY / "RECEIPT.json", receipt)
    return {"status": receipt["status"], "receipt_path": str(CANARY / "RECEIPT.json"),
            "receipt_sha256": sha_file(CANARY / "RECEIPT.json"), "codes": len(CANARY_CODES),
            "parity_rows": len(parity_rows), "event_anchor_checks": len(event_checks),
            "scan_rows_per_second": receipt["scan_rows_per_second"],
            "projection_codes_per_second": process_receipt["codes_per_second"],
            "resource_gate_passed": resource_gate, **FLAGS}


def _source_axis_rows(source_axes: Mapping[str, Any]) -> list[dict[str, Any]]:
    keys = set(source_axes["hits"]) | set(source_axes["axes"]) | set(source_axes["topics"])
    rows: list[dict[str, Any]] = []
    for target, code in sorted(keys):
        states, axes = _source_row(target, code, source_axes, "")
        rows.append({"target_date": iso_day(target), "code": code,
            **states,
            "actual_pool_snapshot_membership": axes["pool_membership"],
            "actual_pool_snapshot_not_decision_complete": axes["pool_snapshot_not_decision_complete"],
            "raw_publication_reconstruction_states": axes["raw_text_status"],
            "raw_source_text_sha256_refs": axes["raw_source_text_sha256_refs"],
            "declared_topics": axes["declared_topics"], "compatibility_topics": axes["compatibility_topics"],
            "subject_true_topics": axes["subject_true_topics"], "subject_false_topics": axes["subject_false_topics"],
            "subject_unknown_topics": axes["subject_unknown_topics"],
            "research_subject_evidence_qualification": axes["research_subject_evidence_qualification"],
            "subject_qualification_used_as_admission_filter": False,
            "source_evidence_refs": axes["source_evidence"]})
    return rows


def _finalize_date_policy(calendar: list[dict[str, Any]], candidate_rows: Sequence[Mapping[str, Any]],
                          truth_keys: set[tuple[str, str]], data_module: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidate_keys = [(row["target_date"], row["code"]) for row in candidate_rows]
    revised, policy = data_module.freeze_date_policy(calendar, candidate_keys, truth_keys)
    for row in revised:
        day = str(row["target_date"])
        if int(row.get("technical_complete_rows", 0)) == 0:
            row.update(training_eligible=False, cohort_role="data_unavailable",
                       eligibility_exclusion_reason="NO_COMPUTABLE_TECHNICAL_INPUT_DAY")
        elif int(row.get("truth_rankable_research_rows", 0)) == 0:
            row.update(training_eligible=False, cohort_role="data_unavailable",
                       eligibility_exclusion_reason="NO_RANKABLE_LABELS_FOR_TARGET_DATE")
        if day.replace("-", "") in EXPOSED:
            row.update(training_eligible=False, cohort_role="diagnostic",
                       eligibility_exclusion_reason="EXPOSED_DIAGNOSTIC_ONLY" +
                       (";NO_COMPUTABLE_TECHNICAL_INPUT_DAY" if int(row.get("technical_complete_rows", 0)) == 0 else ""))
    eligible = sorted(row["target_date"] for row in revised if row["training_eligible"])
    training = eligible[:len(eligible) // 2]
    oof = eligible[len(eligible) // 2:]
    policy.update({"schema": "V194_LONG_HISTORY_COMPLETE_CANDIDATE_LABEL_DATE_POLICY_V1",
        "eligible_target_dates": eligible, "initial_train_target_dates": training,
        "oof_target_dates": oof, "oof_date_folds": [oof[i:i + 5] for i in range(0, len(oof), 5)],
        "excluded_incomplete_target_dates": sorted(row["target_date"] for row in revised
            if row["cohort_role"] == "excluded_incomplete_truth"),
        "all_incomplete_target_dates": sorted(row["target_date"] for row in revised if row.get("unknown_candidate_label_rows")
            and row["cohort_role"] not in {"unlabelled_prediction", "data_unavailable"}),
        "diagnostic_target_dates": sorted(row["target_date"] for row in revised if row["cohort_role"] == "diagnostic"),
        "data_unavailable_target_dates": sorted(row["target_date"] for row in revised if row["cohort_role"] == "data_unavailable"),
        "minimum_total_eligible_dates": 20, "minimum_oof_dates_for_effect_pass": 20,
        "total_date_gate_met": len(eligible) >= 20,
        "effect_date_gate_met": len(oof) >= 20,
        "effect_acceptance_ceiling": "DIRECTION_ONLY" if len(oof) >= 20 else "CANNOT_CONFIRM_INSUFFICIENT_OOF_DATES",
        "selection_slots": 0, "planned_model_selection_top_n": 50,
        "truth_positive_denominator_is_separate_from_selection_slots": True,
        "no_computable_day_policy": "ZERO_COMPLETE_11_ROWS_IS_DATA_UNAVAILABLE_NOT_VALID_EMPTY_SELECTION",
        "input_build_model_fit_count": 0, "input_build_oof_count": 0, **FLAGS})
    return revised, policy


def assemble_full(ctx: Mapping[str, Any], identity: Mapping[str, Any], scan_receipt: Mapping[str, Any],
                  source_axes: Mapping[str, Any], work_dir: Path) -> dict[str, Any]:
    import numpy as np
    codes = ctx["codes"]
    pairs = calendar_pairs_from_receipt(scan_receipt)
    targets = [target for _, target in pairs]
    identity_sha = canonical_sha(identity)
    n_codes, n_targets = len(codes), len(targets)
    return_matrix = np.full((n_codes, n_targets), np.nan, dtype="float64")
    raw_close_matrix = np.full((n_codes, n_targets), np.nan, dtype="float64")
    reference_close_matrix = np.full((n_codes, n_targets), np.nan, dtype="float64")
    complete_matrix = np.zeros((n_codes, n_targets), dtype="uint8")
    code_index = {code: i for i, code in enumerate(codes)}
    target_index = {target: i for i, target in enumerate(targets)}
    details_by_code: dict[str, dict[str, Any]] = {}
    candidates: list[dict[str, Any]] = []
    raw_formula: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    stock_coverage: list[dict[str, Any]] = []
    for code in codes:
        index = code_index[code]
        details, arrays = _load_code_checkpoint(_projection_code_dir(work_dir, index), code, identity_sha)
        for key, matrix in (("truth_returns", return_matrix), ("truth_raw_close", raw_close_matrix),
                            ("truth_reference_close", reference_close_matrix), ("technical_complete", complete_matrix)):
            require(arrays[key].shape == (n_targets,), "PER_CODE_ARRAY_SHAPE_DRIFT:" + code + ":" + key)
            matrix[index, :] = arrays[key]
        details_by_code[code] = details
        candidates.extend(details["candidate_rows"])
        raw_formula.extend(details["formula_rows"])
        exclusions.extend(details["technical_exclusions"])
        stock = details["stock"]
        stock_coverage.append({"code": code, "name": ctx["statuses"][code].get("name", ""),
            "status": ctx["statuses"][code].get("status"), "panel_rows": stock["panel_rows"],
            "history_first_date": stock["first_date"], "history_last_date": stock["last_date"],
            "event_status": stock["event_status"], "event_count": stock["event_count"],
            "unsupported_event_dates": stock["unsupported_event_dates"],
            "complete_11_flag_target_rows": stock["complete_11_flag_target_rows"],
            "candidate_union_rows": stock["candidate_union_rows"],
            "raw_formula_natural_rows": stock["formula_natural_rows"],
            "technical_candidate_exclusions": stock["technical_candidate_exclusions"],
            "raw_panel_sha256": stock["raw_panel_sha256"], "binding_ref": stock["binding_ref"],
            "event_response_path": stock["event_response_path"],
            "event_response_sha256": stock["event_response_sha256"]})
    candidates.sort(key=lambda row: (row["target_date"], row["code"]))
    raw_formula.sort(key=lambda row: (row["target_date"], row["code"]))
    exclusions.sort(key=lambda row: (row["target_date"], row["code"]))
    stock_coverage.sort(key=lambda row: row["code"])
    model_candidates = [row for row in candidates if row["technical_status"] == "COMPLETE_11_FLAGS"]
    model_candidates.sort(key=lambda row: (row["target_date"], row["code"]))
    candidate_code_index = {row["code"]: code_index[row["code"]] for row in model_candidates}
    candidate_counts = Counter(row["target_date"] for row in model_candidates)
    raw_candidate_counts = Counter(row["target_date"] for row in candidates)
    source_hit_counts = {lane: Counter() for lane in SOURCES}
    for row in candidates:
        for lane in SOURCES:
            if row[lane] == "hit":
                source_hit_counts[lane][row["target_date"]] += 1
    candidate_labelled = Counter()
    unknown_candidate_labels = Counter()
    candidate_keys: list[tuple[str, str]] = []
    truth_keys: set[tuple[str, str]] = set()
    for row in model_candidates:
        d = row["target_date"]
        j = target_index[d.replace("-", "")]
        i = candidate_code_index[row["code"]]
        candidate_keys.append((d, row["code"]))
        if math.isfinite(float(return_matrix[i, j])):
            candidate_labelled[d] += 1
            truth_keys.add((d, row["code"]))
        else:
            unknown_candidate_labels[d] += 1

    date_rankable = np.zeros(n_targets, dtype="int32")
    date_positive_denominator = np.zeros(n_targets, dtype="int32")
    truth_rows_path = BUILD / "truth.csv"
    truth_tmp = truth_rows_path.with_name(truth_rows_path.name + f".tmp-{os.getpid()}")
    require(not truth_tmp.exists(), "TEMP_OUTPUT_EXISTS:" + str(truth_tmp))
    with truth_tmp.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=TRUTH_FIELDS, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        for j, target in enumerate(targets):
            valid_idx = np.flatnonzero(np.isfinite(return_matrix[:, j]))
            if len(valid_idx):
                order = valid_idx[np.argsort(-return_matrix[valid_idx, j], kind="stable")]
                date_rankable[j] = len(order)
                date_positive_denominator[j] = min(100, len(order))
                for rank, i in enumerate(order, 1):
                    code = codes[int(i)]
                    day = iso_day(target)
                    row = {"target_date": day, "signal_date": iso_day(pairs[j][0]), "code": code,
                           "return": float(return_matrix[i, j]), "raw_close": float(raw_close_matrix[i, j]),
                           "reference_close": float(reference_close_matrix[i, j]), "rank": rank,
                           "label": int(rank <= 100), "label_end_at": close_available_at(target),
                           "label_available_at": close_available_at(target),
                           "label_maturity_basis": "ECONOMIC_SESSION_CLOSE_RECONSTRUCTION_NOT_HISTORICAL_CAPTURE",
                           "binding_ref": details_by_code[code]["stock"]["binding_ref"]}
                    writer.writerow({k: _csv_value(row.get(k)) for k in TRUTH_FIELDS})
            # Candidate keys are date-keyed; the selected result will be written after all rows are flushed.
        stream.flush()
        os.fsync(stream.fileno())
    if truth_rows_path.exists():
        require(sha_file(truth_tmp) == sha_file(truth_rows_path), "OUTPUT_EXISTS_DIFFERENT:" + str(truth_rows_path))
        truth_tmp.unlink()
    else:
        os.replace(truth_tmp, truth_rows_path)
        fsync_dir(BUILD)

    base_calendar: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    for j, (signal, target) in enumerate(pairs):
        target_iso = iso_day(target)
        complete = int(complete_matrix[:, j].sum())
        raw_rows = raw_candidate_counts[target_iso]
        model_rows = candidate_counts[target_iso]
        if complete == 0:
            availability = "NO_COMPUTABLE_TECHNICAL_INPUT_DAY"
        else:
            availability = "COMPUTABLE_TECHNICAL_INPUT_DAY"
        base = {"target_date": target_iso, "signal_date": iso_day(signal),
            "truth_positive_denominator": int(date_positive_denominator[j]),
            "truth_rankable_research_rows": int(date_rankable[j]), "research_pool_size": n_codes,
            "selection_slots": 0, "planned_model_selection_top_n": 50,
            "cohort_role": "diagnostic" if target in EXPOSED else "eligible",
            "label_available_at": close_available_at(target) if date_rankable[j] else "",
            "technical_complete_rows": complete, "technical_missing_rows": n_codes - complete,
            "technical_input_availability": availability, "raw_candidate_union_rows": raw_rows,
            "candidate_rows": model_rows, "candidate_labelled_rows": candidate_labelled[target_iso],
            "unknown_candidate_label_rows": unknown_candidate_labels[target_iso],
            **{lane + "_hit_rows": source_hit_counts[lane][target_iso] for lane in SOURCES},
            "source_absence_confirmed_rows": 0, "official_calendar_parity": "CANNOT_CONFIRM", **FLAGS}
        base_calendar.append(base)
        coverage_rows.append(dict(base))
    revised_calendar, date_policy = _finalize_date_policy(base_calendar, model_candidates, truth_keys,
                                                           _load_engines()[5])
    by_day = {row["target_date"]: row for row in revised_calendar}
    for row in coverage_rows:
        policy_row = by_day[row["target_date"]]
        row.update({key: policy_row[key] for key in ("cohort_role", "training_eligible", "eligibility_exclusion_reason")})

    axes_rows = _source_axis_rows(source_axes)
    source_fields = ["target_date", "code", *SOURCES, "actual_pool_snapshot_membership",
        "actual_pool_snapshot_not_decision_complete", "raw_publication_reconstruction_states",
        "raw_source_text_sha256_refs", "declared_topics", "compatibility_topics", "subject_true_topics",
        "subject_false_topics", "subject_unknown_topics", "research_subject_evidence_qualification",
        "subject_qualification_used_as_admission_filter", "source_evidence_refs"]
    write_csv_new(BUILD / "STOCK_COVERAGE.csv", ["code", "name", "status", "panel_rows", "history_first_date",
        "history_last_date", "event_status", "event_count", "unsupported_event_dates", "complete_11_flag_target_rows",
        "candidate_union_rows", "raw_formula_natural_rows", "technical_candidate_exclusions", "raw_panel_sha256",
        "binding_ref", "event_response_path", "event_response_sha256"], stock_coverage)
    write_csv_new(BUILD / "RAW_FORMULA_NATURAL.csv", CANDIDATE_FIELDS, raw_formula)
    write_csv_new(BUILD / "RAW_CANDIDATE_UNION.csv", CANDIDATE_FIELDS, candidates)
    write_csv_new(BUILD / "candidates.csv", CANDIDATE_FIELDS, model_candidates)
    write_csv_new(BUILD / "calendar.csv", list(revised_calendar[0].keys()), revised_calendar)
    write_csv_new(BUILD / "coverage.csv", list(coverage_rows[0].keys()), coverage_rows)
    write_csv_new(BUILD / "SOURCE_AXES.csv", source_fields, axes_rows)
    atomic_json(BUILD / "TECHNICAL_EXCLUSIONS.json", exclusions)
    atomic_json(BUILD / "DATE_POLICY.json", date_policy)

    engine, old_contract, original, kernel, program, data_module = _load_engines()
    formula_path = Path(old_contract["input_identity"]["formula_a"])
    kernel_rules = load_json(kernel.HERE / "RULES.json")
    definitions = [dict(column="tech_192", original_name="XG", definition_sha256=sha_file(formula_path),
                        definition="Original complete 255-assignment FORMULA255_OFFLINE XG output")]
    for rule_id, name in kernel.RULES.items():
        rule = next(row for row in kernel_rules["rules"] if row["id"] == rule_id)
        definitions.append(dict(column=rule_id, original_name=name, definition_sha256=canonical_sha(rule), definition=rule))
    dictionary = {"schema": "V194_LONG_INPUT_DATA_DICTIONARY_V1", "row_key": ["target_date", "code"],
        "formula_identity": "FORMULA255_OFFLINE", "formula_sha256": sha_file(formula_path),
        "technical_columns": TECHNICAL, "technical_definitions": definitions,
        "source_state_columns": SOURCES, "source_states": ["hit", "confirmed_absent", "unknown"],
        "source_absence_policy": "No producer-complete date coverage was certified; every non-hit remains unknown.",
        "source_axes": {"pool_membership": "actual_pool_snapshot_membership; descriptive only",
                        "raw_text": "resource SHA references and publication reconstruction state; raw text is not an admission feature",
                        "report_subject": "original report-subject qualification; false/unknown never filters candidates"},
        "feature_time_basis": "Previous observed panel session close; candidate decision cutoff is target date 09:25 Asia/Shanghai.",
        "label_definition": "close_QFQ_anchor_D(D)/close_QFQ_anchor_D(D-1)-1 using same source and target-D event anchor.",
        "label_construction": "Accepted engine.project; raw panel close values and accepted event path/SHA; no pre_close or pct_chg.",
        "label_maturity": "Economic session-close reconstruction; historical source capture time CANNOT_CONFIRM.",
        "truth_positive_denominator": "min(100, rankable research code outcomes for target date); Top100 outcome only.",
        "selection_slots": "0 in this input build; later model contract selection Top50 is a separate field and stage.",
        "panel_numeric_policy": "Float32 values consumed as stored; no round, int cast, or rescaling.",
        "calendar_policy": "Observed selected-panel trade_date keys only; official calendar parity CANNOT_CONFIRM.",
        "universe": "Exact existing 5,533 research code keys from accepted64; not certified historical all-A.",
        "zero_computable_technical_day": "NO_COMPUTABLE_TECHNICAL_INPUT_DAY, never a valid empty selection.",
        "whole_date_label_policy": "Keep unknown labels in raw output; exclude a target date from train/OOF when any retained model candidate label is missing.",
        "fit_count": 0, "oof_count": 0, **FLAGS}
    atomic_json(BUILD / "DATA_DICTIONARY.json", dictionary)

    files = {}
    for key, filename in (("stock_coverage", "STOCK_COVERAGE.csv"), ("raw_formula_natural", "RAW_FORMULA_NATURAL.csv"),
        ("raw_candidate_union", "RAW_CANDIDATE_UNION.csv"), ("candidates", "candidates.csv"),
        ("truth", "truth.csv"), ("calendar", "calendar.csv"), ("coverage", "coverage.csv"),
        ("technical_exclusions", "TECHNICAL_EXCLUSIONS.json"), ("source_axes", "SOURCE_AXES.csv"),
        ("date_policy", "DATE_POLICY.json"), ("dictionary", "DATA_DICTIONARY.json")):
        path = BUILD / filename
        files[key] = {"path": str(path), "sha256": sha_file(path), "rows": _file_row_count(path)}
    source_code_paths = [S / "long_data194.py", S / "test_long_data194.py", S / "data194.py",
        Path(old_contract["input_identity"]["formula_a"]), Path(old_contract["input_identity"]["model_a"]),
        Path(old_contract["input_identity"]["model_b"]), Path(ctx["contract"]["input_identity"]["accepted_benchmark_contract_path"]),
        Path(ctx["contract"]["input_identity"]["event_index_path"]), Path(ctx["contract"]["input_identity"]["event_manifest_path"])]
    eligible_dates = date_policy["eligible_target_dates"]
    manifest = {"schema": "V194_DATASET_MANIFEST_V2", "dataset_kind": "SHARED_PANEL_DERIVED_LONG_HISTORY_VIEW",
        "execution_id": EXECUTION_ID, "status": "INPUT_BUILD_READY_FOR_INDEPENDENT_REVIEW",
        "evidence_level": "CANNOT_CONFIRM", "historical_availability_bound": False,
        "historical_availability_reason": "PANEL_VINTAGE_AND_EVENT_SOURCE_HISTORICAL_CAPTURE_TIME_NOT_CERTIFIED",
        "semantic_ready": False, "passport_status": "NOT_YET_A194_DATASET_PASSPORT_FAST_BIND",
        "lineage_review_pass": False, "design_review_pass": False, "files": files,
        "input_sha256": canonical_sha(files), "formula_identity": "FORMULA255_OFFLINE",
        "technical_features": TECHNICAL, "source_state_columns": SOURCES,
        "source_unknown": "UNKNOWN_NEVER_ZERO_NO_CONFIRMED_ABSENCE",
        "source_coverage": "Bound research source hits; all non-hit keys are unknown.",
        "universe_scope": "Exact accepted 5,533 research code keys; not all-A historical certification.",
        "research_code_list": {"path": str(code_list_path()), "sha256": EXPECTED_CODE_LIST_SHA,
                               "count": EXPECTED_CODE_LIST_COUNT,
                               "accepted64_manifest_sha256": EXPECTED_ACCEPTED64_SHA},
        "panel_binding": {"path": str(ctx["target"]), "pointer_path": ctx["snapshot"]["panel_bindings"]["backtest"]["pointer_path"],
            "pointer_sha256": ctx["snapshot"]["panel_bindings"]["backtest"]["pointer_sha256"],
            "target_stat": panel_stat(ctx["target"]),
            "target_sha256_status": "EXISTING_PRODUCER_DECLARED_SHA; CURRENT PARQUET BYTES NOT REHASHED",
            "target_sha256_declared": ctx["snapshot"]["panel_bindings"]["backtest"]["target_sha256_declared_by_existing_daily_receipt"],
            "panel_scan_receipt": {"path": str(FULL_RECEIPT), "sha256": sha_file(FULL_RECEIPT)},
            "row_count_scanned": scan_receipt["panel_rows_scanned"], "pool_rows_retained": scan_receipt["pool_rows_retained"]},
        "calendar": [row["target_date"] for row in revised_calendar],
        "calendar_source": "BOUND_ACTIVE_BACKTEST_PANEL_OBSERVED_TRADE_DATE_KEYS",
        "official_calendar_parity": "CANNOT_CONFIRM",
        "signal_date_range": [pairs[0][0], pairs[-1][0]] if pairs else [],
        "target_date_range": [pairs[0][1], pairs[-1][1]] if pairs else [],
        "exposed_targets_excluded": sorted(iso_day(day) for day in EXPOSED),
        "label_definition": dictionary["label_definition"],
        "label_price_series_identity": "ORIGINAL_ACCEPTED_ENGINE_SAME_SOURCE_TARGET_D_QFQ_ANCHOR",
        "label_historical_vintage": "CANNOT_CONFIRM",
        "truth_positive_denominator_by_date": {row["target_date"]: row["truth_positive_denominator"] for row in revised_calendar},
        "selection_slots_by_date": {row["target_date"]: row["selection_slots"] for row in revised_calendar},
        "candidate_rows": len(model_candidates), "raw_candidate_union_rows": len(candidates),
        "raw_formula_natural_rows": len(raw_formula), "truth_rows": int(date_rankable.sum()),
        "technical_candidate_exclusions": len(exclusions),
        "eligible_dates": len(eligible_dates), "eligible_target_dates": eligible_dates,
        "initial_train_target_dates": date_policy["initial_train_target_dates"],
        "oof_target_dates": date_policy["oof_target_dates"],
        "excluded_incomplete_target_dates": date_policy["excluded_incomplete_target_dates"],
        "all_incomplete_target_dates": date_policy["all_incomplete_target_dates"],
        "effect_acceptance_ceiling": date_policy["effect_acceptance_ceiling"],
        "training_allowed": False, "fit_count": 0, "oof_count": 0, "top50_selection_count": 0,
        "top100_truth_used_for_candidate_admission": False,
        "source_code_sha256": {str(path): sha_file(path) for path in source_code_paths},
        "canary_receipt": {"path": str(CANARY / "RECEIPT.json"), "sha256": sha_file(CANARY / "RECEIPT.json")},
        "full_projection_resource_receipt": {"path": str(work_dir / "PROJECTION_RESOURCE_RECEIPT.json"),
                                               "sha256": sha_file(work_dir / "PROJECTION_RESOURCE_RECEIPT.json")},
        "start_event_sha256": EXPECTED_START_EVENT_SHA,
        "input_review_status": "PENDING_INDEPENDENT_INPUT_REVIEW", **FLAGS}
    atomic_json(BUILD / "MANIFEST.json", manifest)
    build_receipt = {"schema": "V194_LONG_INPUT_BUILD_RECEIPT_V1", "execution_id": EXECUTION_ID,
        "manifest_path": str(BUILD / "MANIFEST.json"), "manifest_sha256": sha_file(BUILD / "MANIFEST.json"),
        "input_files": files, "research_code_count": n_codes, "calendar_count": n_targets,
        "truth_rows": int(date_rankable.sum()), "candidate_rows": len(model_candidates),
        "raw_candidate_union_rows": len(candidates), "raw_formula_natural_rows": len(raw_formula),
        "technical_candidate_exclusions": len(exclusions), "fit_count": 0, "oof_count": 0,
        "top50_selection_count": 0, "status": "INPUT_BUILD_READY_FOR_INDEPENDENT_REVIEW",
        "CANNOT_CONFIRM": ["historical all-A universe", "official calendar parity", "historical capture-time PIT",
                           "historical label maturity", "per-route A194 dataset passport", "independent review"], **FLAGS}
    atomic_json(BUILD / "BUILD_RECEIPT.json", build_receipt)
    return {"status": build_receipt["status"], "manifest_path": build_receipt["manifest_path"],
            "manifest_sha256": build_receipt["manifest_sha256"], "truth_rows": build_receipt["truth_rows"],
            "candidate_rows": build_receipt["candidate_rows"], "raw_candidate_union_rows": len(candidates),
            "eligible_dates": len(eligible_dates), "technical_candidate_exclusions": len(exclusions), **FLAGS}


def _file_row_count(path: Path) -> int:
    if path.suffix == ".csv":
        with path.open("r", newline="", encoding="utf-8-sig") as stream:
            return max(0, sum(1 for _ in stream) - 1)
    value = load_json(path)
    return len(value) if isinstance(value, list) else -1


def run_full() -> dict[str, Any]:
    ctx = load_context(require_checkpoint=True)
    identity = build_identity(ctx)
    canary = load_json(CANARY / "RECEIPT.json")
    require(canary.get("build_identity_sha256") == canonical_sha(identity), "CANARY_BUILD_IDENTITY_DRIFT")
    require(canary.get("implementation_sha256") == ctx["code_sha256"] and
            canary.get("test_sha256") == ctx["test_sha256"], "CANARY_CODE_IDENTITY_DRIFT")
    reusable = {code: str(_projection_code_dir(CANARY, index)) for index, code in enumerate(CANARY_CODES)}
    assert_no_overwrite_dir(BUILD, identity)
    work_dir = BUILD / "_intermediate" / "processing"
    assert_no_overwrite_dir(work_dir, identity)
    source_axes = load_source_axes(ctx)
    scan_receipt = scan_panel(ctx, ctx["codes"], RAW_CACHE, FULL_RECEIPT, identity)
    pairs = calendar_pairs_from_receipt(scan_receipt)
    projection_receipt = run_projection(ctx, ctx["codes"], pairs, source_axes, RAW_CACHE,
        work_dir, identity, exact_parity=False, selected_panel_rows=int(scan_receipt["pool_rows_retained"]),
        reusable_checkpoints=reusable)
    atomic_json(work_dir / "PROJECTION_RESOURCE_RECEIPT.json", projection_receipt)
    require(panel_stat(ctx["target"]) == ctx["initial_panel_stat"], "PANEL_TARGET_STAT_DRIFT_BEFORE_ASSEMBLY")
    result = assemble_full(ctx, identity, scan_receipt, source_axes, work_dir)
    require(panel_stat(ctx["target"]) == ctx["initial_panel_stat"], "PANEL_TARGET_STAT_DRIFT_AFTER_FULL_BUILD")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Frozen research-only long-history A-share V194 input projection")
    parser.add_argument("phase", choices=["canary", "full"])
    args = parser.parse_args()
    if args.phase == "canary":
        result = run_canary()
    else:
        # A persisted canary pass is mandatory before the 5,533-code projection.
        canary_receipt_path = CANARY / "RECEIPT.json"
        require(canary_receipt_path.is_file(), "CANARY_RECEIPT_MISSING")
        canary = load_json(canary_receipt_path)
        require(canary.get("status") == "CANARY_PASS_INPUT_BUILD_MAY_CONTINUE" and
                canary.get("resource_gate_passed") is True and canary.get("fit_count") == 0,
                "CANARY_PASS_SIGNAL_MISSING")
        result = run_full()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

