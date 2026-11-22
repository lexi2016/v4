"""First fixed PFT-S baseline over the existing A-share QFQ backtest panel.

This is a bounded research runner. It reads one frozen common-label CSV and
the current paired V4 panel, then writes a new, explicit output directory only
after the run gates pass. Preflight never fits a model.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
from datetime import date, datetime
from decimal import Decimal
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


CASE_COLUMNS = (
    "security_id",
    "master_episode_group",
    "D",
    "overall_s_label",
    "partition",
    "exposure_status",
)
IDENTITY_CASE_COLUMNS = ("security_id", "master_episode_group", "D")
OPTIONAL_CASE_COLUMNS = ("case_id", "source_views")
PARTITIONS = {"train", "validation"}
LABELS = {"TRUE", "FALSE", "UNKNOWN"}
MIN_HISTORY_BARS = 61
SCHEMA = "pft_s_first_baseline.v1.1"
MODEL_SCHEMA = "pft_s_logistic_model.v1.1"
METRICS_SCHEMA = "pft_s_first_baseline_metrics.v1.1"
GATE_CONTRACT = {
    "schema": "pft_s_inference_gates.v1",
    "order": ["G1", "G2", "FIXED_LR_V1_1"],
    "G1": {
        "condition": "D_white_line > D_yellow_line",
        "signed_difference": "D_white_line - D_yellow_line",
        "known_equality_or_lower": "HARD_FALSE_NO_MODEL_PROBABILITY",
        "missing_or_invalid": "GAP_ABSTAIN_NO_MODEL_PROBABILITY",
    },
    "G2": {
        "combiner": "OR",
        "branch_1": "D_close / D_yellow_line - 1 >= 0.35",
        "branch_2": (
            "D_close / D_yellow_line - 1 >= 0.25 AND "
            "(D_high - max(D_open, D_close)) / D_minus_1_close >= 0.04 AND "
            "D_volume / mean(volume[D_minus_5:D_minus_1]) >= 1.5"
        ),
        "branch_3": (
            "D_close / max(high[D_minus_29:D_including_D]) - 1 <= -0.22 AND "
            "(D_high - D_low) / D_minus_1_close >= 0.08"
        ),
        "upper_wick_and_amplitude_denominator": "D_minus_1_close",
        "vr5": "D_volume / mean(volume of the preceding five bars D-5..D-1); D excluded",
        "trailing_30_bar_high_window": "D-29..D inclusive",
        "trigger": "HARD_FALSE_NO_MODEL_PROBABILITY",
    },
    "training": "fit all decided TRAIN rows; gates are inference-time only",
    "unknown": "preserve UNKNOWN; exclude from scored decisions and metrics; V1.1 emits no diagnostic LR probability",
    "whole_policy_validation": (
        "all decided validation rows; G1/G2 veto is a FALSE decision and effective ROC-AUC score 0; "
        "model probability remains blank for veto rows"
    ),
    "model_only_validation": "optional metrics on decided, ungated rows with an LR probability",
}
V11_FEATURE_CONTRACT = {
    "schema": "pft_s_v1_1_d_only_features.v1",
    "directional_d_return_predictor": False,
    "repair_split": {
        "y_consec2_5b": "strict two consecutive closes below yellow in the latest five bars including D",
        "prior_pair": "strict consecutive closes below yellow; both bars in D-25..D-6 inclusive",
        "repair": "two later consecutive closes strictly above both white and yellow",
        "no_active_relapse": "no later consecutive close pair below yellow after the latest repair pair",
        "model_feature": "repaired_prior_break",
    },
    "prior_key_k": {
        "search": "nearest qualifying prior upward key K in the R2 helper's 40 bars before D",
        "low_intact": "D low strictly above the selected prior key K low",
        "model_feature": "surge_low_intact",
        "D_in_anchor_search": False,
    },
    "pullback_context": {
        "contraction_ratios": ["volume_5_vs_prior15", "range_5_vs_prior15", "d_volume_vs_prior5_mean",
                               "d_range_vs_prior15_mean"],
        "zero_prior5_volume_encoding": "-1 means the preceding five-bar volume baseline is zero",
        "structure_hold": ["surge_low_intact", "d_close_above_white_line_tri",
                           "d_close_above_yellow_line_tri", "yellow_active_confirmed_break_tri"],
        "ratios_are_continuous_and_untuned": True,
    },
    "readvance_context": {
        "held_prior_anchor": "surge_low_intact",
        "relative_volume": "d_volume_vs_prior5_mean",
        "close_over_earlier_high": ["d_close_breaks_prior10_high_tri", "d_close_breaks_prior20_high_tri"],
        "ratios_are_continuous_and_untuned": True,
    },
    "branch_interactions": {
        "pullback_strength": (
            "max(0, 1-VR5) * max(0, 1-D_range/prior15_range); available only when the prior low is held, "
            "D closes above yellow, no two-below pair occurs in the latest five bars, and D does not close above "
            "the prior ten-bar high"
        ),
        "re_advance_strength": (
            "max(0, VR5-1) * max(0, D_close/prior10_high-1); available only when the prior low is held"
        ),
        "unknown_required_input_encoding": -1,
        "natural_ratio_pivot": 1.0,
    },
    "excluded_from_model_features": {
        "yellow_2below_historical_tri": "pooled 16-bar audit field replaced by the separate recent-5 and prior-break/repaired features",
        "duplicate_readvance_and_rebuild_aliases": "not included; canonical base feature names are used once",
    },
    "range_break": "D close/high compared with prior 10/20 bar highs, excluding D",
}
FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
SECURITY_ID = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BaselineError(RuntimeError):
    """A fail-closed input, identity, or run-gate error."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _day(value: Any, *, field: str) -> str:
    text = str(value).strip().replace("-", "")
    if not re.fullmatch(r"\d{8}", text):
        raise BaselineError(f"INVALID_{field.upper()}:{value!r}")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise BaselineError(f"INVALID_{field.upper()}:{value!r}") from exc
    return text


def _canonical_security(value: Any) -> str:
    code = str(value).strip().upper()
    if not SECURITY_ID.fullmatch(code):
        raise BaselineError(f"INVALID_A_SHARE_SECURITY_ID:{value!r}")
    return code


def _read_cases(path: Path, *, start_date: str, asof_date: str,
                allow_identity_only: bool = False) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Read and canonicalize a frozen table while preserving its byte identity."""
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise BaselineError(f"CASE_TABLE_PATH_INVALID:{path}")
    before = path.stat()
    raw = path.read_bytes()
    if path.stat() != before:
        raise BaselineError("CASE_TABLE_CHANGED_DURING_READ")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise BaselineError("CASE_TABLE_NOT_UTF8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)):
        raise BaselineError("CASE_TABLE_DUPLICATE_HEADER")
    missing = sorted(set(IDENTITY_CASE_COLUMNS) - set(headers))
    if missing:
        raise BaselineError("CASE_TABLE_REQUIRED_COLUMNS_MISSING:" + ",".join(missing))
    joint_columns = set(CASE_COLUMNS) - set(IDENTITY_CASE_COLUMNS)
    present_joint_columns = joint_columns.intersection(headers)
    identity_only = not present_joint_columns
    if present_joint_columns and present_joint_columns != joint_columns:
        raise BaselineError("CASE_TABLE_JOINT_LABEL_COLUMNS_INCOMPLETE")
    if identity_only and not allow_identity_only:
        raise BaselineError("JOINT_SIGNED_LABEL_TABLE_REQUIRED")

    cases: list[dict[str, str]] = []
    by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    raw_rows = 0
    exact_duplicates = 0
    for line_number, row in enumerate(reader, start=2):
        raw_rows += 1
        if None in row:
            raise BaselineError(f"CASE_TABLE_EXTRA_FIELDS_AT_LINE:{line_number}")
        item = {key: (row.get(key) or "").strip() for key in (*CASE_COLUMNS, *OPTIONAL_CASE_COLUMNS) if key in headers}
        item["security_id"] = _canonical_security(item["security_id"])
        if "case_id" in item:
            item["case_id"] = item["case_id"].strip()
            if not item["case_id"]:
                raise BaselineError(f"EMPTY_CASE_ID_AT_LINE:{line_number}")
        item["master_episode_group"] = item["master_episode_group"].strip()
        if not item["master_episode_group"]:
            raise BaselineError(f"EMPTY_MASTER_EPISODE_GROUP_AT_LINE:{line_number}")
        item["D"] = _day(item["D"], field="D")
        if identity_only:
            # Internal sentinels are for coverage plumbing only. The report
            # explicitly states that this file carries no labels or split.
            item.update(overall_s_label="UNKNOWN", partition="identity_only", exposure_status="NOT_PROVIDED")
        else:
            item["overall_s_label"] = item["overall_s_label"].strip().upper()
            if item["overall_s_label"] not in LABELS:
                raise BaselineError(f"INVALID_OVERALL_S_LABEL_AT_LINE:{line_number}")
            item["partition"] = item["partition"].strip().lower()
            if item["partition"] not in PARTITIONS:
                raise BaselineError(f"INVALID_PARTITION_AT_LINE:{line_number}")
            item["exposure_status"] = item["exposure_status"].strip()
            if not item["exposure_status"]:
                raise BaselineError(f"EMPTY_EXPOSURE_STATUS_AT_LINE:{line_number}")
        if "source_views" in item:
            item["source_views"] = item["source_views"].strip()
        if not start_date <= item["D"] <= asof_date:
            raise BaselineError(f"CASE_DATE_OUTSIDE_BOUNDED_WINDOW_AT_LINE:{line_number}")
        key = (item["security_id"], item["master_episode_group"], item["D"])
        previous = by_key.get(key)
        if previous is not None:
            semantic_fields = ("security_id", "master_episode_group", "D", "overall_s_label", "partition", "exposure_status")
            if any(previous.get(field) != item.get(field) for field in semantic_fields):
                raise BaselineError("CASE_KEY_CONFLICT:" + "|".join(key))
            if previous.get("case_id") and item.get("case_id") and previous["case_id"] != item["case_id"]:
                raise BaselineError("CASE_KEY_CASE_ID_CONFLICT:" + "|".join(key))
            source_views = sorted({value.strip() for value in
                                   (previous.get("source_views", "") + ";" + item.get("source_views", "")).split(";")
                                   if value.strip()})
            if source_views:
                previous["source_views"] = ";".join(source_views)
            if not previous.get("case_id") and item.get("case_id"):
                previous["case_id"] = item["case_id"]
            exact_duplicates += 1
            continue
        by_key[key] = item
        cases.append(item)
    if not cases:
        raise BaselineError("CASE_TABLE_EMPTY")

    if not identity_only:
        group_partitions: dict[str, set[str]] = {}
        security_partitions: dict[str, set[str]] = {}
        for item in cases:
            group_partitions.setdefault(item["master_episode_group"], set()).add(item["partition"])
            security_partitions.setdefault(item["security_id"], set()).add(item["partition"])
        cross_partition_groups = sorted(group for group, splits in group_partitions.items() if len(splits) > 1)
        if cross_partition_groups:
            raise BaselineError("EPISODE_CROSSES_PARTITIONS:" + ",".join(cross_partition_groups[:20]))
        cross_partition_securities = sorted(code for code, splits in security_partitions.items() if len(splits) > 1)
        if cross_partition_securities:
            raise BaselineError("SECURITY_CROSSES_PARTITIONS:" + ",".join(cross_partition_securities[:20]))

    supplied_case_ids = [row["case_id"] for row in cases if row.get("case_id")]
    if len(supplied_case_ids) != len(set(supplied_case_ids)):
        raise BaselineError("CASE_ID_NOT_UNIQUE")
    cases.sort(key=lambda row: (row["security_id"], row["master_episode_group"], row["D"]))
    identity = {
        "path": str(path),
        "sha256": _sha_bytes(raw),
        "raw_bytes": len(raw),
        "raw_rows": raw_rows,
        "deduplicated_rows": len(cases),
        "exact_duplicate_rows_removed": exact_duplicates,
        "headers": headers,
        "joint_label_columns_present": not identity_only,
    }
    return cases, identity


def _safe_panel_path(path: Path) -> Path:
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or path.is_symlink() or path.resolve() != path or not path.is_file():
        raise BaselineError(f"CURRENT_PANEL_PATH_INVALID:{path}")
    return path


def _read_pointer(pointer: Path) -> tuple[Path, tuple[int, int, int, int], bytes]:
    if not pointer.is_file() or pointer.is_symlink():
        raise BaselineError(f"CURRENT_POINTER_MISSING_OR_UNSAFE:{pointer}")
    before = pointer.stat()
    raw = pointer.read_bytes()
    if pointer.stat() != before:
        raise BaselineError(f"CURRENT_POINTER_CHANGED_DURING_READ:{pointer}")
    try:
        text = raw.decode("utf-8-sig", errors="strict").strip().strip('"')
    except UnicodeDecodeError as exc:
        raise BaselineError(f"CURRENT_POINTER_NOT_UTF8:{pointer}") from exc
    if not text:
        raise BaselineError(f"CURRENT_POINTER_EMPTY:{pointer}")
    target = _safe_panel_path(Path(text))
    return target, (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns), raw


def _read_json_stable(path: Path) -> tuple[dict[str, Any], tuple[int, int, int, int], str]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise BaselineError(f"PRODUCER_RECEIPT_PATH_INVALID:{path}")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    stamp = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    if after != before:
        raise BaselineError(f"PRODUCER_RECEIPT_CHANGED_DURING_READ:{path}")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineError(f"PRODUCER_RECEIPT_INVALID_JSON:{path}") from exc
    if not isinstance(value, dict):
        raise BaselineError(f"PRODUCER_RECEIPT_INVALID_SCHEMA:{path}")
    return value, stamp, _sha_bytes(raw)


def _basis_asof(contract: dict[str, Any]) -> str:
    market_a = (contract.get("market_basis") or {}).get("A")
    basis = market_a if isinstance(market_a, dict) else contract
    if basis.get("price_basis") != "QFQ_ASOF" or basis.get("volume_basis") != "QFQ_EVENT_VOLUME":
        raise BaselineError("BACKTEST_A_QFQ_BASIS_INVALID")
    return _day(basis.get("asof_date", contract.get("asof_date")), field="panel_asof")


def _contract_identity(role: str, panel: Path, contract: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    required = ("schema", "generation_id", "input_sha256", "snapshot_file_sha256", "asof_date", "generation_manifest_path")
    if contract.get("schema") != "a_share_qfq_panel_v1" or any(not contract.get(key) for key in required):
        raise BaselineError(f"PANEL_CONTRACT_INCOMPLETE:{role}")
    asof = _basis_asof(contract)
    manifest_path = Path(contract["generation_manifest_path"])
    if not manifest_path.is_absolute() or ".." in manifest_path.parts or manifest_path.is_symlink():
        raise BaselineError(f"PRODUCER_RECEIPT_PATH_INVALID:{role}")
    receipt, receipt_stat, receipt_sha = _read_json_stable(manifest_path)
    # In the existing publication chain a pointer can be committed while the
    # immutable producer receipt retains CANDIDATE_READY. Current selector and
    # backtest pointers plus role-specific receipt path/hash/date are the
    # active binding; the receipt's historical stage label alone is not.
    if receipt.get("status") not in {"READY", "CANDIDATE_READY"}:
        raise BaselineError(f"PRODUCER_RECEIPT_NOT_CURRENT_CANDIDATE:{role}")
    if (receipt.get("generation_id") != contract.get("generation_id")
            or str(receipt.get("target_date")) != str(contract.get("asof_date"))
            or receipt.get("input_sha256") != contract.get("input_sha256")
            or receipt.get("snapshot_file_sha256") != contract.get("snapshot_file_sha256")):
        raise BaselineError(f"PRODUCER_RECEIPT_CONTRACT_MISMATCH:{role}")
    candidates = receipt.get("candidates") or {}
    candidate_hashes = receipt.get("candidate_sha256") or {}
    if Path(str(candidates.get(role, ""))).resolve() != panel:
        raise BaselineError(f"PRODUCER_RECEIPT_ROLE_PATH_MISMATCH:{role}")

    from ops.research_panel_logical import digest, stamp

    panel_stat = stamp(panel)
    panel_sha = digest(panel)
    if candidate_hashes.get(role) != panel_sha:
        raise BaselineError(f"PRODUCER_RECEIPT_ROLE_SHA_MISMATCH:{role}")
    identity = {
        key: contract.get(key)
        for key in ("generation_id", "input_sha256", "snapshot_file_sha256", "asof_date", "price_basis", "volume_basis")
    }
    identity["a_market_basis"] = (contract.get("market_basis") or {}).get("A")
    source = {
        "role": role,
        "path": str(panel),
        "panel_sha256": panel_sha,
        "panel_stat": panel_stat,
        "generation_manifest_path": str(manifest_path),
        "generation_manifest_sha256": receipt_sha,
        "generation_manifest_stat": receipt_stat,
        "producer_receipt_status": receipt.get("status"),
        "asof_date": asof,
    }
    return identity, source


@contextmanager
def bind_current_panels(data_root: Path):
    """Bind both current pointers to their active QFQ producer receipt.

    The pointer targets are read-only logical anchors; their manifested hashes
    cover those small anchors. The logical reader checks each consumed block
    before and after its read, so this runner does not rehash whole data blocks.
    """
    data_root = Path(data_root)
    if not data_root.is_absolute() or data_root.is_symlink() or not data_root.is_dir():
        raise BaselineError(f"DATA_ROOT_INVALID:{data_root}")
    from ops.research_storage_pair import pointers
    from ops.research_panel_qfq import panel_contract

    pointer_paths = pointers(data_root)
    pointer_state: dict[str, tuple[Path, tuple[int, int, int, int], bytes]] = {}
    for role in ("selector", "backtest"):
        pointer_state[role] = _read_pointer(pointer_paths[role])
    panel_paths = {role: value[0] for role, value in pointer_state.items()}
    contract_values = {role: panel_contract(panel_paths[role]) for role in ("selector", "backtest")}
    contract_identities: dict[str, dict[str, Any]] = {}
    source_rows: dict[str, dict[str, Any]] = {}
    for role in ("selector", "backtest"):
        contract_identities[role], source_rows[role] = _contract_identity(role, panel_paths[role], contract_values[role])
    if contract_identities["selector"] != contract_identities["backtest"]:
        raise BaselineError("CURRENT_POINTER_GENERATION_MISMATCH")
    manifest_paths = {row["generation_manifest_path"] for row in source_rows.values()}
    if len(manifest_paths) != 1:
        raise BaselineError("CURRENT_POINTER_MANIFEST_MISMATCH")
    source = {
        "selector": source_rows["selector"],
        "backtest": source_rows["backtest"],
        "generation_id": contract_identities["backtest"]["generation_id"],
        "input_sha256": contract_identities["backtest"]["input_sha256"],
        "asof_date": _basis_asof(contract_values["backtest"]),
        "identity": contract_identities["backtest"],
    }

    def recheck() -> None:
        for role in ("selector", "backtest"):
            current_path, current_stat, current_raw = _read_pointer(pointer_paths[role])
            old_path, old_stat, old_raw = pointer_state[role]
            if (current_path != old_path or current_stat != old_stat or current_raw != old_raw):
                raise BaselineError(f"CURRENT_POINTER_CHANGED:{role}")
            contract = panel_contract(old_path)
            identity, row = _contract_identity(role, old_path, contract)
            if identity != contract_identities[role] or row != source_rows[role]:
                raise BaselineError(f"CURRENT_PANEL_SOURCE_CHANGED:{role}")

    recheck()
    try:
        yield panel_paths["backtest"], source, recheck
    finally:
        recheck()


def _panel_columns(panel_path: Path) -> tuple[list[str], dict[str, str], Any]:
    from ops.research_panel_logical import parquet
    schema = parquet.read_schema(panel_path)
    actual = {name.lower(): name for name in schema.names}
    aliases = {
        "trade_date": ("trade_date",),
        "ts_code": ("ts_code",),
        "exchange": ("exchange",),
        "market_type": ("market_type",),
        "open": ("open",),
        "high": ("high",),
        "low": ("low",),
        "close": ("close",),
        "vol": ("vol", "volume"),
        "bbi": ("bbi",),
        "zge_white_line": ("zge_white_line",),
        "zge_yellow_line": ("zge_yellow_line",),
        "ma60": ("ma60",),
    }
    columns: dict[str, str] = {}
    for semantic in ("trade_date", "ts_code", "open", "high", "low", "close", "vol",
                     "zge_white_line", "zge_yellow_line"):
        field = next((actual[name] for name in aliases[semantic] if name in actual), None)
        if field is None:
            raise BaselineError(f"BACKTEST_PANEL_REQUIRED_FIELD_MISSING:{semantic}")
        columns[semantic] = field
    for semantic in ("exchange", "market_type", "bbi", "ma60"):
        field = next((actual[name] for name in aliases[semantic] if name in actual), None)
        if field is not None:
            columns[semantic] = field
    read_columns = list(dict.fromkeys(columns.values()))
    return read_columns, columns, schema


def _date_filter_value(schema: Any, field: str, value: str) -> Any:
    import pyarrow as pa
    dtype = schema.field(field).type
    if pa.types.is_integer(dtype):
        return int(value)
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        return value
    if pa.types.is_date(dtype):
        return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    raise BaselineError(f"UNSUPPORTED_BACKTEST_DATE_TYPE:{dtype}")


def _panel_rows(panel_path: Path, *, start_date: str, asof_date: str, codes: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    from ops.research_panel_logical import parquet
    read_columns, columns, schema = _panel_columns(panel_path)
    date_field = columns["trade_date"]
    filters = [
        (date_field, ">=", _date_filter_value(schema, date_field, start_date)),
        (date_field, "<=", _date_filter_value(schema, date_field, asof_date)),
        (columns["ts_code"], "in", sorted(set(codes))),
    ]
    table = parquet.read_table(panel_path, columns=read_columns, filters=filters)
    rows = []
    for raw in table.to_pylist():
        normalized: dict[str, Any] = {}
        for semantic, column in columns.items():
            normalized[semantic] = raw.get(column)
        try:
            normalized["trade_date"] = _day(normalized["trade_date"], field="trade_date")
        except BaselineError:
            normalized["trade_date"] = None
        normalized["ts_code"] = str(normalized.get("ts_code") or "").strip().upper()
        rows.append(normalized)
    return rows, columns


def _numeric(value: Any, *, field: str) -> float:
    if value is None or isinstance(value, bool):
        raise BaselineError(f"INVALID_NUMERIC:{field}")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise BaselineError(f"INVALID_NUMERIC:{field}") from exc
    if not math.isfinite(result):
        raise BaselineError(f"INVALID_NUMERIC:{field}")
    return result


def _exchange_matches(code: str, row: dict[str, Any]) -> bool:
    suffix = code.rsplit(".", 1)[1]
    exchange = row.get("exchange")
    if exchange is None or not str(exchange).strip():
        return True
    value = str(exchange).strip().upper()
    aliases = {
        "SH": {"SH", "SSE", "XSHG", "SHANGHAI"},
        "SZ": {"SZ", "SZSE", "XSHE", "SHENZHEN"},
        "BJ": {"BJ", "BSE", "XBEI", "BEIJING"},
    }
    return value in aliases[suffix]


def _feature_values(panel_rows: list[dict[str, Any]], columns: dict[str, str], *, target_date: str) -> dict[str, float]:
    """Build fixed causal price/volume windows using only rows through D."""
    prefix = sorted((row for row in panel_rows
                     if row.get("trade_date") is not None and row["trade_date"] <= target_date),
                    key=lambda row: row["trade_date"])
    if not prefix or prefix[-1]["trade_date"] != target_date:
        raise BaselineError("EXACT_D_ROW_MISSING")
    if len(prefix) < MIN_HISTORY_BARS:
        raise BaselineError("INSUFFICIENT_HISTORY")
    bars = []
    for row in prefix[-MIN_HISTORY_BARS:]:
        values = {name: _numeric(row.get(name), field=name) for name in ("open", "high", "low", "close", "vol")}
        if min(values["open"], values["high"], values["low"], values["close"]) <= 0 or values["vol"] < 0:
            raise BaselineError("INVALID_HISTORY_OHLCV_RANGE")
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise BaselineError("INVALID_HISTORY_OHLC_ENVELOPE")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise BaselineError("INVALID_HISTORY_OHLC_ENVELOPE")
        bars.append({**row, **values, "range_pct": (values["high"] - values["low"]) / values["close"]})

    current = bars[-1]
    close = current["close"]
    span = current["high"] - current["low"]
    recent_vol = sum(row["vol"] for row in bars[-5:]) / 5.0
    prior_vol = sum(row["vol"] for row in bars[-20:-5]) / 15.0
    prior_range = sum(row["range_pct"] for row in bars[-20:-5]) / 15.0
    recent_range = sum(row["range_pct"] for row in bars[-5:]) / 5.0
    prior5_vol = sum(row["vol"] for row in bars[-6:-1]) / 5.0
    if prior_vol <= 0:
        raise BaselineError("ZERO_PRIOR15_VOLUME_BASELINE")
    if prior_range <= 0:
        raise BaselineError("ZERO_PRIOR15_RANGE_BASELINE")
    recent20, prior20 = bars[-20:], bars[-40:-20]
    high60 = max(row["high"] for row in bars[-60:])
    low60 = min(row["low"] for row in bars[-60:])
    prior10_high = max(row["high"] for row in bars[-11:-1])
    prior20_high = max(row["high"] for row in bars[-21:-1])
    features = {
        "open_close_pct": current["open"] / close - 1.0,
        "high_low_pct": span / close,
        "close_location": (close - current["low"]) / span if span else 0.5,
        "log1p_vol": math.log1p(current["vol"]),
        "close_return_5d": close / bars[-6]["close"] - 1.0,
        "close_return_20d": close / bars[-21]["close"] - 1.0,
        "close_return_60d": close / bars[-61]["close"] - 1.0,
        "volume_5_vs_prior15": recent_vol / prior_vol,
        "range_5_vs_prior15": recent_range / prior_range,
        "d_volume_vs_prior5_mean": current["vol"] / prior5_vol if prior5_vol > 0 else -1.0,
        "d_range_vs_prior15_mean": current["range_pct"] / prior_range,
        "close_vs_high_60d": close / high60 - 1.0,
        "close_vs_low_60d": close / low60 - 1.0,
        "high_20_vs_prior20": max(row["high"] for row in recent20) / max(row["high"] for row in prior20) - 1.0,
        "low_20_vs_prior20": min(row["low"] for row in recent20) / min(row["low"] for row in prior20) - 1.0,
        "d_close_vs_prior10_high_pct": close / prior10_high - 1.0,
        "d_close_vs_prior20_high_pct": close / prior20_high - 1.0,
        "d_high_vs_prior10_high_pct": current["high"] / prior10_high - 1.0,
        "d_high_vs_prior20_high_pct": current["high"] / prior20_high - 1.0,
        "d_close_breaks_prior10_high_tri": float(close > prior10_high),
        "d_close_breaks_prior20_high_tri": float(close > prior20_high),
        "d_high_breaks_prior10_high_tri": float(current["high"] > prior10_high),
        "d_high_breaks_prior20_high_tri": float(current["high"] > prior20_high),
        "d_close_above_white_line_tri": float(close > _numeric(current.get("zge_white_line"), field="zge_white_line")),
        "d_close_above_yellow_line_tri": float(close > _numeric(current.get("zge_yellow_line"), field="zge_yellow_line")),
    }
    if "bbi" in columns:
        bbi = _numeric(current.get("bbi"), field="bbi")
        if bbi <= 0:
            raise BaselineError("INVALID_INDICATOR_RANGE:bbi")
        features["close_bbi_pct"] = close / bbi - 1.0
    if "zge_white_line" in columns and "zge_yellow_line" in columns:
        white = _numeric(current.get("zge_white_line"), field="zge_white_line")
        yellow = _numeric(current.get("zge_yellow_line"), field="zge_yellow_line")
        if white <= 0 or yellow <= 0:
            raise BaselineError("INVALID_INDICATOR_RANGE:zge_lines")
        features["white_yellow_spread_pct"] = (white - yellow) / close
    if "ma60" in columns:
        ma60 = _numeric(current.get("ma60"), field="ma60")
        if ma60 <= 0:
            raise BaselineError("INVALID_INDICATOR_RANGE:ma60")
        features["close_ma60_pct"] = close / ma60 - 1.0
    if any(not math.isfinite(value) for value in features.values()):
        raise BaselineError("INVALID_DERIVED_FEATURE")
    return features


def _line_relation(row: dict[str, Any], line_name: str) -> int | None:
    close = row.get("close")
    line = row.get(line_name)
    try:
        close_value = float(close)
        line_value = float(line)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(close_value) or not math.isfinite(line_value) or line_value <= 0:
        return None
    return 1 if close_value > line_value else (-1 if close_value < line_value else 0)


def _consecutive_pair(
    rows: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool | None],
) -> tuple[bool | None, tuple[int, int] | None]:
    unknown = False
    matches: list[tuple[int, int]] = []
    for index in range(len(rows) - 1):
        first = predicate(rows[index])
        second = predicate(rows[index + 1])
        if first is None or second is None:
            unknown = True
        elif first and second:
            matches.append((index, index + 1))
    if matches:
        return True, matches[-1]
    return (None if unknown else False), None


def _repair_distinguishing_features(
    panel_rows: list[dict[str, Any]], *, target_date: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Separate recent yellow breaks from an older, later repaired pair."""
    prefix = sorted((row for row in panel_rows
                     if row.get("trade_date") is not None and str(row["trade_date"]) <= target_date),
                    key=lambda row: str(row["trade_date"]))
    if not prefix or str(prefix[-1]["trade_date"]) != target_date:
        raise BaselineError("EXACT_D_ROW_MISSING")

    def below_yellow(row: dict[str, Any]) -> bool | None:
        relation = _line_relation(row, "zge_yellow_line")
        return None if relation is None else relation < 0

    def above_white_and_yellow(row: dict[str, Any]) -> bool | None:
        white = _line_relation(row, "zge_white_line")
        yellow = _line_relation(row, "zge_yellow_line")
        return None if white is None or yellow is None else white > 0 and yellow > 0

    latest5 = prefix[-5:]
    recent_pair, recent_pair_indices = _consecutive_pair(latest5, below_yellow)
    prior_window = prefix[-26:-6]  # D-25 through D-6, both endpoints included.
    prior_pair, prior_pair_indices = _consecutive_pair(prior_window, below_yellow)
    repair_pair = False
    repair_pair_indices: tuple[int, int] | None = None
    repair_search_unknown = False
    prior_pair_start_date: str | None = None
    prior_pair_end_date: str | None = None
    repair_pair_start_date: str | None = None
    repair_pair_end_date: str | None = None
    active_relapse: bool | None = None
    repaired_current = -1.0

    if len(prior_window) < 20:
        prior_pair = None
    elif prior_pair_indices is not None:
        base = len(prefix) - len(prior_window)
        first_global, second_global = (base + prior_pair_indices[0], base + prior_pair_indices[1])
        prior_pair_start_date = str(prefix[first_global]["trade_date"])
        prior_pair_end_date = str(prefix[second_global]["trade_date"])
        later_rows = prefix[second_global + 1:]
        repair_result, local_repair = _consecutive_pair(later_rows, above_white_and_yellow)
        repair_search_unknown = repair_result is None
        if local_repair is not None:
            repair_pair = True
            repair_pair_indices = (second_global + 1 + local_repair[0], second_global + 1 + local_repair[1])
            repair_pair_start_date = str(prefix[repair_pair_indices[0]]["trade_date"])
            repair_pair_end_date = str(prefix[repair_pair_indices[1]]["trade_date"])
            after_repair = prefix[repair_pair_indices[1] + 1:]
            active_result, _ = _consecutive_pair(after_repair, below_yellow)
            active_relapse = active_result
            if active_result is False:
                repaired_current = 1.0
            elif active_result is True:
                repaired_current = 0.0
        elif repair_search_unknown:
            repaired_current = -1.0
        else:
            repaired_current = 0.0
    elif prior_pair is None:
        repaired_current = -1.0
    else:
        repaired_current = 0.0

    features = {
        "y_consec2_5b": -1.0 if recent_pair is None else float(recent_pair),
        "y_prior_consec2_d25_d6": -1.0 if prior_pair is None else float(prior_pair),
        "repaired_prior_break": repaired_current,
        "y_prior_pair_current_repair_pair_at_D_tri": float(
            repair_pair_indices is not None and repair_pair_indices[1] == len(prefix) - 1
        ),
    }
    diagnostic = {
        "schema": "pft_s_v1_1_yellow_repair_split.v1",
        "target_date": target_date,
        "y_consec2_5b": "UNKNOWN" if recent_pair is None else str(bool(recent_pair)).upper(),
        "y_consec2_5b_pair_dates": (
            [str(latest5[recent_pair_indices[0]]["trade_date"]),
             str(latest5[recent_pair_indices[1]]["trade_date"])] if recent_pair_indices else None
        ),
        "prior_window_first_date": str(prior_window[0]["trade_date"]) if prior_window else None,
        "prior_window_last_date": str(prior_window[-1]["trade_date"]) if prior_window else None,
        "prior_pair_status": "UNKNOWN" if prior_pair is None else str(bool(prior_pair)).upper(),
        "prior_pair_start_date": prior_pair_start_date,
        "prior_pair_end_date": prior_pair_end_date,
        "repair_pair_status": "TRUE" if repair_pair else ("UNKNOWN" if repair_search_unknown else "FALSE"),
        "repair_pair_start_date": repair_pair_start_date,
        "repair_pair_end_date": repair_pair_end_date,
        "active_relapse_after_latest_repair_pair": (
            "UNKNOWN" if active_relapse is None and repair_pair else
            ("TRUE" if active_relapse is True else "FALSE" if active_relapse is False else "NOT_APPLICABLE")
        ),
        "latest_close_above_white_and_yellow": (
            "UNKNOWN" if above_white_and_yellow(prefix[-1]) is None else
            str(bool(above_white_and_yellow(prefix[-1]))).upper()
        ),
    }
    return features, diagnostic


def _inference_gate(panel_rows: list[dict[str, Any]], *, target_date: str) -> dict[str, Any]:
    prefix = sorted((row for row in panel_rows
                     if row.get("trade_date") is not None and row["trade_date"] <= target_date),
                    key=lambda row: row["trade_date"])
    if len(prefix) < 31 or prefix[-1]["trade_date"] != target_date:
        raise BaselineError("INSUFFICIENT_GATE_HISTORY_OR_EXACT_D_MISSING")
    current = prefix[-1]
    previous = prefix[-2]
    previous_close = _numeric(previous.get("close"), field="previous_close")
    d_open = _numeric(current.get("open"), field="D_open")
    d_high = _numeric(current.get("high"), field="D_high")
    d_low = _numeric(current.get("low"), field="D_low")
    d_close = _numeric(current.get("close"), field="D_close")
    d_volume = _numeric(current.get("vol"), field="D_volume")
    if current.get("zge_white_line") is None or current.get("zge_yellow_line") is None:
        raise BaselineError("MISSING_G1_WHITE_OR_YELLOW_LINE")
    try:
        white = _numeric(current.get("zge_white_line"), field="D_white_line")
        yellow = _numeric(current.get("zge_yellow_line"), field="D_yellow_line")
    except BaselineError as exc:
        raise BaselineError("INVALID_G1_WHITE_OR_YELLOW_LINE") from exc
    if white <= 0 or yellow <= 0:
        raise BaselineError("INVALID_G1_WHITE_OR_YELLOW_LINE")
    signed_white_yellow = white - yellow
    g1_pass = signed_white_yellow > 0
    close_yellow_pct = d_close / yellow - 1.0 if yellow is not None and yellow > 0 else None
    upper_wick_prev_close = (d_high - max(d_open, d_close)) / previous_close if previous_close > 0 else None
    previous5_volumes = [_numeric(row.get("vol"), field="prior_volume") for row in prefix[-6:-1]]
    previous5_mean = sum(previous5_volumes) / len(previous5_volumes) if previous5_volumes else 0.0
    vr5_d_vs_prior5 = d_volume / previous5_mean if previous5_mean > 0 else None
    trailing30_high = max(_numeric(row.get("high"), field="trailing30_high") for row in prefix[-30:])
    drawdown_vs_trailing30_high = d_close / trailing30_high - 1.0 if trailing30_high > 0 else None
    amplitude_prev_close = (d_high - d_low) / previous_close if previous_close > 0 else None
    d_ret_pct = d_close / previous_close - 1.0 if previous_close > 0 else None

    g2_branches = {
        "G2_CLOSE_YELLOW_GE_35": Decimal(str(d_close)) >= Decimal("1.35") * Decimal(str(yellow)),
        "G2_CLOSE_YELLOW_GE_25_WICK_GE_4_VR5_GE_1_5": (
            Decimal(str(d_close)) >= Decimal("1.25") * Decimal(str(yellow))
            and Decimal(str(d_high)) - max(Decimal(str(d_open)), Decimal(str(d_close)))
            >= Decimal("0.04") * Decimal(str(previous_close))
            and previous5_mean > 0
            and Decimal(str(d_volume)) >= Decimal("1.5") * Decimal(str(previous5_mean))
        ),
        "G2_DRAWDOWN_LE_MINUS_22_AMPLITUDE_GE_8": (
            Decimal(str(d_close)) <= Decimal("0.78") * Decimal(str(trailing30_high))
            and Decimal(str(d_high)) - Decimal(str(d_low))
            >= Decimal("0.08") * Decimal(str(previous_close))
        ),
    }
    g2_triggers = [name for name, triggered in g2_branches.items() if triggered]
    if not g1_pass:
        gate_reason = "G1_W_NOT_ABOVE_Y_HARD_FALSE"
    elif g2_triggers:
        gate_reason = ";".join(g2_triggers)
    else:
        gate_reason = ""
    veto = not g1_pass or bool(g2_triggers)
    return {
        "G1_white_D": white,
        "G1_yellow_D": yellow,
        "G1_signed_white_minus_yellow": signed_white_yellow,
        "G1_condition": "D_white_line > D_yellow_line",
        "G1_pass": bool(g1_pass),
        "G2_close_yellow_pct": close_yellow_pct,
        "G2_upper_wick_prev_close_ratio": upper_wick_prev_close,
        "G2_vr5_D_volume_vs_prior5_mean": vr5_d_vs_prior5,
        "G2_prior5_mean_volume_D_minus5_to_D_minus1": previous5_mean,
        "G2_drawdown_vs_trailing30_high_including_D": drawdown_vs_trailing30_high,
        "G2_trailing30_high_D_minus29_to_D": trailing30_high,
        "G2_amplitude_prev_close_ratio": amplitude_prev_close,
        "G2_branch_triggers": g2_triggers,
        "G2_branch_results": g2_branches,
        "gate_would_veto": bool(veto),
        "gate_reason": gate_reason,
        "gate_hard_prediction": "FALSE" if veto else None,
        "d_ret_pct_diagnostic_only": d_ret_pct,
    }


def _coverage(cases: list[dict[str, str]]) -> dict[str, Any]:
    if cases and cases[0].get("partition") == "identity_only":
        return {
            "cases": len(cases),
            "unique_securities": len({row["security_id"] for row in cases}),
            "unique_master_episode_groups": len({row["master_episode_group"] for row in cases}),
            "joint_labels_present": False,
            "label_counts": None,
            "partition_label_counts": None,
            "scored_case_counts": None,
            "unknown_case_count": None,
            "missing_binary_classes": None,
        }
    counts = {label: 0 for label in ("TRUE", "FALSE", "UNKNOWN")}
    by_partition = {partition: {label: 0 for label in counts} for partition in ("train", "validation")}
    for item in cases:
        counts[item["overall_s_label"]] += 1
        by_partition[item["partition"]][item["overall_s_label"]] += 1
    known = {partition: sum(value for label, value in values.items() if label != "UNKNOWN")
             for partition, values in by_partition.items()}
    missing_classes = {
        partition: sorted({"TRUE", "FALSE"} - {label for label, count in values.items() if count > 0})
        for partition, values in by_partition.items()
    }
    return {
        "cases": len(cases),
        "label_counts": counts,
        "partition_label_counts": by_partition,
        "scored_case_counts": known,
        "unknown_case_count": counts["UNKNOWN"],
        "missing_binary_classes": missing_classes,
    }


def _build_examples(
    cases: list[dict[str, str]],
    panel_rows: list[dict[str, Any]],
    columns: dict[str, str],
    *,
    start_date: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, str]], list[str]]:
    by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in panel_rows:
        if row.get("trade_date") is None or not row.get("ts_code"):
            continue
        by_key.setdefault((row["ts_code"], row["trade_date"]), []).append(row)
    for key, rows in by_key.items():
        if len(rows) > 1:
            rows.sort(key=lambda r: tuple(str(r.get(k)) for k in sorted(r)))

    gaps: list[dict[str, str]] = []
    unknown_exclusions: list[dict[str, str]] = []
    all_features: set[str] = set()
    examples: list[dict[str, Any]] = []

    def record_gap(item: dict[str, str], reason: str, **extra: str) -> None:
        row = {"case_id": _case_id(item), "security_id": item["security_id"], "D": item["D"],
               "reason": reason, **extra}
        if item.get("overall_s_label") == "UNKNOWN" and item.get("partition") != "identity_only":
            unknown_exclusions.append(row)
        else:
            gaps.append(row)

    for item in cases:
        code, target = item["security_id"], item["D"]
        history_keys = sorted(day for (row_code, day) in by_key if row_code == code and start_date <= day <= target)
        duplicate_history = [(row_code, day) for (row_code, day), rows in by_key.items()
                             if row_code == code and start_date <= day <= target and len(rows) > 1]
        if duplicate_history:
            record_gap(item, "DUPLICATE_PANEL_KEY_WITHIN_HISTORY")
            continue
        exact = by_key.get((code, target), [])
        if len(exact) != 1:
            record_gap(item, "EXACT_D_ROW_MISSING" if not exact else "DUPLICATE_EXACT_D_ROW")
            continue
        if len(history_keys) < MIN_HISTORY_BARS:
            record_gap(item, "INSUFFICIENT_HISTORY", available_bars=str(len(history_keys)),
                       required_bars=str(MIN_HISTORY_BARS))
            continue
        row = exact[0]
        if not _exchange_matches(code, row):
            record_gap(item, "TS_CODE_EXCHANGE_MISMATCH")
            continue
        try:
            history_rows = [by_key[(code, day)][0] for day in history_keys]
            gate_diagnostics = _inference_gate(history_rows, target_date=target)
            vector = _feature_values(history_rows, columns, target_date=target)
            from ops.pft_s_structure_features import structure_repair_features as build_structure_features
            structure_features, structure_diagnostics = build_structure_features(
                history_rows, target_date=target,
            )
            repair_features, repair_diagnostics = _repair_distinguishing_features(
                history_rows, target_date=target,
            )
            structure_features["surge_low_intact"] = structure_features.pop("key_k_D_low_held_above_tri")
            structure_features.update(repair_features)
            surge_low_intact = structure_features["surge_low_intact"]
            structure_features["pullback_strength"] = _guarded_positive_interaction(
                vector["d_volume_vs_prior5_mean"],
                1.0 - vector["d_range_vs_prior15_mean"],
                low_volume_side=True,
                tri_guards={
                    "surge_low_intact": (surge_low_intact, 1),
                    "above_yellow": (vector["d_close_above_yellow_line_tri"], 1),
                    "no_latest5_break": (repair_features["y_consec2_5b"], 0),
                    "no_close_breakthrough": (vector["d_close_breaks_prior10_high_tri"], 0),
                },
            )
            structure_features["re_advance_strength"] = _guarded_positive_interaction(
                vector["d_volume_vs_prior5_mean"],
                vector["d_close_vs_prior10_high_pct"],
                low_volume_side=False,
                tri_guards={"surge_low_intact": (surge_low_intact, 1)},
            )
            if any(not math.isfinite(value) for value in structure_features.values()):
                raise BaselineError("INVALID_STRUCTURE_REPAIR_FEATURE")
            # Keep the helper's pooled 16-session event in the row audit, while
            # the V1.1 model uses the explicitly separated recent and repaired
            # break features instead.
            vector.update({name: value for name, value in structure_features.items()
                           if name != "yellow_2below_historical_tri"})
            structure_diagnostics = {**structure_diagnostics, **repair_diagnostics}
        except (BaselineError, ValueError) as exc:
            record_gap(item, str(exc))
            continue
        zero_volume = _numeric(row.get("vol"), field="vol") == 0.0
        if zero_volume and item.get("overall_s_label") in {"TRUE", "FALSE"}:
            record_gap(item, "ZERO_D_VOLUME_WITH_DECIDED_LABEL")
            continue
        all_features.update(vector)
        examples.append({
            **item,
            "case_id": _case_id(item),
            "features": vector,
            "structure_features": structure_features,
            "structure_diagnostics": structure_diagnostics,
            "inference_gate": gate_diagnostics,
            "history_bars": len(history_keys),
            "zero_volume_on_D": zero_volume,
            "d_volume": _numeric(row.get("vol"), field="vol"),
            "gate_would_disagree_with_signed_label": (
                bool(gate_diagnostics["gate_would_veto"] and item.get("overall_s_label") == "TRUE")
                if item.get("overall_s_label") in {"TRUE", "FALSE"} else None
            ),
        })
    examples.sort(key=lambda row: (row["security_id"], row["master_episode_group"], row["D"]))
    gaps.sort(key=lambda row: (row["security_id"], row["D"], row["case_id"], row["reason"]))
    unknown_exclusions.sort(key=lambda row: (row["security_id"], row["D"], row["case_id"], row["reason"]))
    return examples, gaps, unknown_exclusions, sorted(all_features)


def _case_id(item: dict[str, str]) -> str:
    supplied = item.get("case_id", "").strip()
    if supplied:
        return supplied
    material = "\0".join((item["security_id"], item["master_episode_group"], item["D"], item.get("partition", "")))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]


def _gate_category(gate: dict[str, Any]) -> str:
    if not gate.get("G1_pass"):
        return "G1"
    if gate.get("G2_branch_triggers"):
        return "G2"
    return "NONE"


def _gate_precheck_support(examples: list[dict[str, Any]]) -> dict[str, Any]:
    support: dict[str, Any] = {}
    for partition in ("train", "validation"):
        rows = [row for row in examples if row.get("partition") == partition]
        categories = {name: [row for row in rows if _gate_category(row["inference_gate"]) == name]
                      for name in ("G1", "G2", "NONE")}
        decided = [row for row in rows if row.get("overall_s_label") in {"TRUE", "FALSE"}]
        disagreements = [row for row in decided
                         if row.get("inference_gate", {}).get("gate_would_veto")
                         and row["overall_s_label"] != "FALSE"]
        support[partition] = {
            "case_count": len(rows),
            "known_label_count": len(decided),
            "unknown_label_count": sum(row.get("overall_s_label") == "UNKNOWN" for row in rows),
            "would_veto_count": len(categories["G1"]) + len(categories["G2"]),
            "would_veto_by_gate": {name: len(categories[name]) for name in ("G1", "G2")},
            "model_eligible_count": len(categories["NONE"]),
            "signed_label_disagreements": [
                {"case_id": row["case_id"], "overall_s_label": row["overall_s_label"],
                 "gate_reason": row["inference_gate"].get("gate_reason", "")}
                for row in disagreements
            ],
            "decided_fit_rows_preserved": len(decided) if partition == "train" else None,
        }
    return support


def _guarded_positive_interaction(
    volume_ratio: float,
    price_ratio: float,
    *,
    low_volume_side: bool,
    tri_guards: dict[str, tuple[float, int]],
) -> float:
    """Apply a continuous ratio interaction, preserving UNKNOWN as -1."""
    if not math.isfinite(volume_ratio) or volume_ratio < 0 or not math.isfinite(price_ratio):
        return -1.0
    for _name, (value, expected) in tri_guards.items():
        if not math.isfinite(value) or value < 0:
            return -1.0
        if value != float(expected):
            return 0.0
    volume_strength = max(0.0, 1.0 - volume_ratio) if low_volume_side else max(0.0, volume_ratio - 1.0)
    return volume_strength * max(0.0, price_ratio)


def _structure_output_fields(item: dict[str, Any]) -> dict[str, str]:
    features = item.get("structure_features")
    if features is None:
        return {}
    return {
        "structure_features_json": json.dumps(features, sort_keys=True, separators=(",", ":"), allow_nan=False),
        "structure_diagnostics_json": json.dumps(item.get("structure_diagnostics") or {}, sort_keys=True,
                                                  separators=(",", ":"), allow_nan=False),
    }


def _report_base(
    *,
    cases_path: Path,
    start_date: str,
    asof_date: str,
    cases: list[dict[str, str]],
    cases_identity: dict[str, Any],
    source: dict[str, Any],
    examples: list[dict[str, Any]],
    gaps: list[dict[str, str]],
    unknown_exclusions: list[dict[str, str]],
    features: list[str],
    expected_sha256: str | None,
) -> dict[str, Any]:
    if asof_date > source["asof_date"]:
        raise BaselineError("REQUESTED_ASOF_AFTER_PANEL_ASOF")
    case_sha = cases_identity["sha256"]
    if expected_sha256 is not None and expected_sha256 != case_sha:
        raise BaselineError("SIGNED_CASE_TABLE_SHA256_MISMATCH")
    coverage = _coverage(cases)
    identity_only = not cases_identity["joint_label_columns_present"]
    no_missing_classes = identity_only or all(not values for values in coverage["missing_binary_classes"].values())
    coverage.update({
        "feature_ready_case_count": len(examples),
        "input_gap_case_count": len(gaps),
        "input_gaps": gaps,
        "unknown_exclusion_case_count": len(unknown_exclusions),
        "unknown_exclusions": unknown_exclusions,
        "feature_names": features,
        "zero_volume_D_case_ids": [row["case_id"] for row in examples if row.get("zero_volume_on_D")],
        "zero_volume_D_cases": [
            {key: row.get(key) for key in ("case_id", "security_id", "master_episode_group", "D",
                                           "overall_s_label", "partition", "source_views", "d_volume")}
            for row in examples if row.get("zero_volume_on_D")
        ],
        "inference_gate_precheck": _gate_precheck_support(examples),
    })
    ready = not gaps and len(examples) + len(unknown_exclusions) == len(cases) and no_missing_classes
    if ready and identity_only:
        status = "PREFLIGHT_IDENTITY_ONLY"
    elif ready and expected_sha256 is None:
        status = "PREFLIGHT_READY_UNSIGNED"
    elif ready:
        status = "PREFLIGHT_READY_SIGNED"
    else:
        status = "BLOCKED_INPUT_OR_SPLIT_GAPS"
    return {
        "schema": SCHEMA,
        "status": status,
        "mode": "preflight",
        "fit_status": "NOT_RUN_PREFLIGHT_ONLY",
        **FLAGS,
        "bounded_window": {"start_date": start_date, "asof_date": asof_date,
                           "panel_asof_date": source["asof_date"], "max_case_date": max(row["D"] for row in cases)},
        "cases": {**cases_identity, "expected_sha256": expected_sha256,
                  "signature_match": expected_sha256 == case_sha if expected_sha256 else False,
                  "path_argument": str(cases_path)},
        "source": source,
        "coverage": coverage,
        "inference_gates": GATE_CONTRACT,
        "feature_contract": V11_FEATURE_CONTRACT,
        "partition_policy": {
            "master_episode_group_cross_split": "REJECTED",
            "security_across_multiple_partitions": "REJECTED_CONSERVATIVE_OVERLAP_GUARD",
            "unknown_labels": "LABEL_PRESERVED_AND_NEVER_IN_METRICS; ELIGIBLE_UNGATED_DIAGNOSTIC_PROBABILITY_ONLY",
            "identity_only_cases": "NO_JOINT_LABELS_OR_SPLIT_CLAIMS",
            "validation_development_exposed": True,
        },
    }


def preflight(
    *,
    data_root: Path,
    cases_path: Path,
    start_date: str,
    asof_date: str,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    start_date = _day(start_date, field="start_date")
    asof_date = _day(asof_date, field="asof_date")
    if start_date > asof_date:
        raise BaselineError("START_AFTER_ASOF")
    if expected_sha256 is not None and not SHA256.fullmatch(expected_sha256):
        raise BaselineError("EXPECTED_CASES_SHA256_INVALID")
    cases, cases_identity = _read_cases(cases_path, start_date=start_date, asof_date=asof_date,
                                        allow_identity_only=True)
    with bind_current_panels(data_root) as (panel_path, source, recheck):
        if asof_date > source["asof_date"]:
            raise BaselineError("REQUESTED_ASOF_AFTER_PANEL_ASOF")
        panel_rows, columns = _panel_rows(panel_path, start_date=start_date, asof_date=asof_date,
                                          codes=(row["security_id"] for row in cases))
        examples, gaps, unknown_exclusions, feature_names = _build_examples(
            cases, panel_rows, columns, start_date=start_date,
        )
        recheck()
        report = _report_base(cases_path=cases_path, start_date=start_date, asof_date=asof_date,
                              cases=cases, cases_identity=cases_identity, source=source, examples=examples,
                              gaps=gaps, unknown_exclusions=unknown_exclusions, features=feature_names,
                              expected_sha256=expected_sha256)
        report["panel_rows_read"] = len(panel_rows)
        return report


def _manual_probabilities(model_payload: dict[str, Any], matrix: Any) -> list[float]:
    import numpy as np
    means = np.asarray(model_payload["scaler_mean"], dtype=float)
    scales = np.asarray(model_payload["scaler_scale"], dtype=float)
    coefficients = np.asarray(model_payload["coefficient_true"], dtype=float)
    transformed = (matrix - means) / scales
    logits = transformed @ coefficients + float(model_payload["intercept"])
    return [1.0 / (1.0 + math.exp(-max(-700.0, min(700.0, float(value))))) for value in logits]


def _top_contributions(model: Any, row: Any, feature_names: list[str], *, limit: int = 3) -> list[dict[str, Any]]:
    scaler = model.named_steps["scale"]
    classifier = model.named_steps["logistic"]
    scaled = (row - scaler.mean_) / scaler.scale_
    terms = []
    for name, value, weight in zip(feature_names, scaled, classifier.coef_[0]):
        contribution = float(value * weight)
        terms.append({"feature": name, "standardized_value": float(value),
                      "coefficient": float(weight), "logit_contribution": contribution})
    return sorted(terms, key=lambda item: (-abs(item["logit_contribution"]), item["feature"]))[:limit]


def _validate_output_dir(output_dir: Path, data_root: Path) -> Path:
    output_dir = Path(output_dir)
    data_root = Path(data_root).resolve()
    if not output_dir.is_absolute() or output_dir.exists() or output_dir.is_symlink():
        raise BaselineError("OUTPUT_DIR_MUST_BE_NEW_ABSOLUTE_PATH")
    output_dir = output_dir.parent.resolve() / output_dir.name
    if output_dir == data_root or data_root in output_dir.parents or output_dir in data_root.parents:
        raise BaselineError("OUTPUT_DIR_OVERLAPS_PANEL_DATA_ROOT")
    if not output_dir.parent.is_dir():
        raise BaselineError("OUTPUT_DIR_PARENT_MISSING")
    return output_dir


def _reserve_output_dir(output_dir: Path, data_root: Path) -> Path:
    """Atomically claim the only destination before the authorized fit starts."""
    output_dir = _validate_output_dir(output_dir, data_root)
    try:
        output_dir.mkdir(parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise BaselineError("OUTPUT_DIR_WAS_CLAIMED_CONCURRENTLY") from exc
    return output_dir


def _fit_and_materialize(report: dict[str, Any], examples: list[dict[str, Any]], output_dir: Path,
                         *, before_write: Callable[[], None]) -> dict[str, Any]:
    import numpy as np
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    feature_names = report["coverage"]["feature_names"]
    train = [row for row in examples if row["partition"] == "train" and row["overall_s_label"] != "UNKNOWN"]
    validation = [row for row in examples if row["partition"] == "validation" and row["overall_s_label"] != "UNKNOWN"]
    unknown = [row for row in examples if row["overall_s_label"] == "UNKNOWN"]
    if not train or not validation:
        raise BaselineError("TRAIN_OR_VALIDATION_EMPTY")
    y_train = np.asarray([1 if row["overall_s_label"] == "TRUE" else 0 for row in train], dtype=int)
    y_validation = np.asarray([1 if row["overall_s_label"] == "TRUE" else 0 for row in validation], dtype=int)
    if set(y_train.tolist()) != {0, 1}:
        raise BaselineError("TRAINING_REQUIRES_BOTH_BINARY_CLASSES")
    if set(y_validation.tolist()) != {0, 1}:
        raise BaselineError("VALIDATION_REQUIRES_BOTH_BINARY_CLASSES")
    x_train = np.asarray([[row["features"][name] for name in feature_names] for row in train], dtype=float)
    x_validation = np.asarray([[row["features"][name] for name in feature_names] for row in validation], dtype=float)

    model = Pipeline([
        ("scale", StandardScaler()),
        ("logistic", LogisticRegression(C=1.0, penalty="l2", solver="liblinear", random_state=0,
                                         class_weight="balanced", max_iter=1000, tol=1e-8)),
    ])
    # The model is trained on every decided TRAIN row. G1/G2 are inference-time
    # policy gates and must never shrink this frozen fit population.
    model.fit(x_train, y_train)
    positive_index = list(model.named_steps["logistic"].classes_).index(1)
    majority = int(y_train.sum() * 2 >= len(y_train))

    decided = [*train, *validation]
    eligible = [row for row in decided if not row["inference_gate"]["gate_would_veto"]]
    eligible_case_ids = [row["case_id"] for row in eligible]
    if len(eligible_case_ids) != len(set(eligible_case_ids)):
        raise BaselineError("DUPLICATE_CASE_ID_IN_UNGATED_PREDICTION_SET")
    probability_by_case_id: dict[str, float] = {}
    eligible_matrix = np.asarray(
        [[row["features"][name] for name in feature_names] for row in eligible], dtype=float,
    ).reshape((len(eligible), len(feature_names)))
    if eligible:
        # This is the only predict_proba call. Its matrix is constructed after
        # removing all G1/G2 veto rows, so vetoed rows receive no LR probability.
        eligible_probabilities = model.predict_proba(eligible_matrix)[:, positive_index]
        probability_by_case_id = {
            row["case_id"]: float(probability)
            for row, probability in zip(eligible, eligible_probabilities)
        }
    if any(row["case_id"] in probability_by_case_id for row in decided
           if row["inference_gate"]["gate_would_veto"]):
        raise BaselineError("GATE_VETO_RECEIVED_MODEL_PROBABILITY")

    def confusion(actual: Any, predicted: Any) -> dict[str, int]:
        actual = np.asarray(actual, dtype=int)
        predicted = np.asarray(predicted, dtype=int)
        return {
            "true_positive": int(np.sum((actual == 1) & (predicted == 1))),
            "false_positive": int(np.sum((actual == 0) & (predicted == 1))),
            "true_negative": int(np.sum((actual == 0) & (predicted == 0))),
            "false_negative": int(np.sum((actual == 1) & (predicted == 0))),
        }

    def score(actual: Any, predicted: Any, effective_scores: Any | None = None) -> dict[str, Any]:
        counts = confusion(actual, predicted)
        precision_den = counts["true_positive"] + counts["false_positive"]
        recall_den = counts["true_positive"] + counts["false_negative"]
        precision = counts["true_positive"] / precision_den if precision_den else 0.0
        recall = counts["true_positive"] / recall_den if recall_den else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        result = {"n": len(actual), "confusion": counts, "precision": precision, "recall": recall, "f1": f1,
                  "accuracy": float(np.mean(np.asarray(actual) == np.asarray(predicted)))}
        if effective_scores is not None:
            values = np.asarray(effective_scores, dtype=float)
            result["roc_auc"] = (float(roc_auc_score(actual, values))
                                 if len(set(np.asarray(actual, dtype=int).tolist())) == 2 else None)
        return result

    policy_validation_predictions: list[int] = []
    policy_validation_scores: list[float] = []
    eligible_validation: list[dict[str, Any]] = []
    for item in validation:
        gate = item["inference_gate"]
        if gate["gate_would_veto"]:
            policy_validation_predictions.append(0)
            policy_validation_scores.append(0.0)
        else:
            probability = probability_by_case_id[item["case_id"]]
            policy_validation_predictions.append(int(probability >= 0.5))
            policy_validation_scores.append(probability)
            eligible_validation.append(item)
    validation_metrics = score(y_validation, policy_validation_predictions, policy_validation_scores)
    model_only_validation_predictions = [
        int(probability_by_case_id[item["case_id"]] >= 0.5) for item in eligible_validation
    ]
    model_only_validation_actual = np.asarray(
        [1 if item["overall_s_label"] == "TRUE" else 0 for item in eligible_validation], dtype=int,
    )
    model_only_validation_scores = [probability_by_case_id[item["case_id"]] for item in eligible_validation]
    model_only_validation_metrics = (
        score(model_only_validation_actual, model_only_validation_predictions, model_only_validation_scores)
        if eligible_validation else None
    )
    majority_metrics = score(y_validation, np.full(len(y_validation), majority, dtype=int))
    model_probabilities = [probability_by_case_id[row["case_id"]] for row in eligible]
    model_payload = {
        "schema": MODEL_SCHEMA, "feature_names": feature_names,
        "scaler_mean": [float(value) for value in model.named_steps["scale"].mean_],
        "scaler_scale": [float(value) for value in model.named_steps["scale"].scale_],
        "coefficient_true": [float(value) for value in model.named_steps["logistic"].coef_[0]],
        "intercept": float(model.named_steps["logistic"].intercept_[0]),
        "classes": [int(value) for value in model.named_steps["logistic"].classes_],
        "decision_threshold": 0.5,
        "configuration": {"C": 1.0, "penalty": "l2", "solver": "liblinear", "random_state": 0,
                          "class_weight": "balanced", "max_iter": 1000, "tol": 1e-8,
                          "scale": "StandardScaler", "fit_population": "all_decided_train_rows",
                          "inference_gate_used_during_fit": False},
        "training_case_ids": [row["case_id"] for row in train],
        "sklearn_version": sklearn.__version__,
    }
    serialized_model = json.dumps(model_payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    reloaded_model_payload = json.loads(serialized_model)
    reloaded_probabilities = _manual_probabilities(reloaded_model_payload, eligible_matrix)
    max_probability_diff = max((abs(float(a) - float(b)) for a, b in zip(model_probabilities, reloaded_probabilities)), default=0.0)
    if max_probability_diff > 1e-12:
        raise BaselineError("MODEL_RELOAD_NUMERICAL_MISMATCH")

    rows_out: list[dict[str, Any]] = []
    for item in examples:
        actual = item["overall_s_label"]
        gate = item["inference_gate"]
        probability = probability_by_case_id.get(item["case_id"])
        veto = bool(gate["gate_would_veto"])
        if veto:
            predicted_label = "FALSE"
            effective_decision_score: float | str = 0.0
            decision_source = "G1_GATE" if not gate["G1_pass"] else "G2_GATE"
            contribution: list[dict[str, Any]] = []
        elif actual == "UNKNOWN":
            # Unknown labels stay unknown and unscored. This baseline omits the
            # optional diagnostic LR probability for these rows.
            predicted_label = ""
            effective_decision_score = ""
            decision_source = "UNKNOWN_UNSCORED"
            contribution = []
        else:
            if probability is None:
                raise BaselineError("UNGATED_DECIDED_CASE_MISSING_MODEL_PROBABILITY")
            predicted_label = "TRUE" if probability >= 0.5 else "FALSE"
            effective_decision_score = probability
            decision_source = "MODEL_LR"
            vector = np.asarray([item["features"][name] for name in feature_names], dtype=float)
            contribution = _top_contributions(model, vector, feature_names)
        is_error = (predicted_label != actual) if actual != "UNKNOWN" else None
        rows_out.append({
            "case_id": item["case_id"], "security_id": item["security_id"],
            "master_episode_group": item["master_episode_group"], "D": item["D"],
            "overall_s_label": actual, "partition": item["partition"],
            "exposure_status": item["exposure_status"], "source_views": item.get("source_views", ""),
            "prediction": predicted_label,
            "probability_true": "" if veto or probability is None else probability,
            "effective_decision_score": effective_decision_score,
            "decision_source": decision_source,
            "gate_reason": gate.get("gate_reason", ""),
            "gate_would_disagree_with_signed_label": (
                item.get("gate_would_disagree_with_signed_label") if actual != "UNKNOWN" else ""
            ),
            "scored": actual != "UNKNOWN", "is_error": is_error,
            "exclusion_reason": "" if actual != "UNKNOWN" else "UNKNOWN_LABEL_NEVER_SCORED",
            "history_bars": item["history_bars"], "d_volume": item["d_volume"],
            "top_numeric_contributions": json.dumps(contribution, sort_keys=True, separators=(",", ":")),
            "inference_gate_json": json.dumps(gate, sort_keys=True, separators=(",", ":"), allow_nan=False),
            **_structure_output_fields(item),
        })
    rows_out.sort(key=lambda row: (row["partition"], row["security_id"], row["master_episode_group"], row["D"]))
    errors = [row for row in rows_out if row["partition"] == "validation" and row["is_error"] is True]
    gate_conflicts = [
        {"case_id": row["case_id"], "security_id": row["security_id"], "D": row["D"],
         "partition": row["partition"], "overall_s_label": row["overall_s_label"],
         "gate_reason": row["gate_reason"]}
        for row in rows_out if row["gate_would_disagree_with_signed_label"] is True
    ]

    metrics = {
        "schema": METRICS_SCHEMA,
        "validation_whole_policy": {**validation_metrics, "n_expected_all_decided_validation_rows": len(validation)},
        "validation_model_only_ungated": {
            "n": len(eligible_validation), "metrics": model_only_validation_metrics,
            "excluded_gate_veto_rows": len(validation) - len(eligible_validation),
        },
        "train_majority_comparator_on_validation": {"majority_label": "TRUE" if majority else "FALSE", **majority_metrics},
        "training": {"n": len(train), "label_counts": {"TRUE": int(y_train.sum()), "FALSE": int(len(y_train) - y_train.sum())}},
        "validation_label_counts": {"TRUE": int(y_validation.sum()), "FALSE": int(len(y_validation) - y_validation.sum())},
        "validation_errors": len(errors),
        "unknown_cases_excluded_from_prediction_and_scoring": report["coverage"]["unknown_case_count"],
        "zero_volume_unknown_cases_excluded": sum(bool(row.get("zero_volume_on_D")) for row in unknown),
        "inference_gate_counts": report["coverage"]["inference_gate_precheck"],
        "gate_signed_label_conflicts": gate_conflicts,
        "veto_rows_receive_model_probability": False,
        "unknown_diagnostic_probabilities_emitted": 0,
        "validation_development_exposed": True,
        "metrics_claim": "one frozen development-exposed validation split; no tuning, no OOS claim",
    }
    run_record = {
        **report,
        "schema": SCHEMA,
        "status": "FIT_COMPLETED",
        "mode": "run",
        "fit_status": "FIT_COMPLETED",
        "output_dir": str(output_dir),
        "model": model_payload["configuration"],
        "model_artifact": model_payload,
        "model_load_check": {"status": "PASS_SERIALIZED_WEIGHTS", "prediction_count": int(len(model_probabilities)),
                             "ungated_decided_case_count": len(eligible),
                             "veto_case_model_probability_count": 0,
                             "max_probability_difference": max_probability_diff, "tolerance": 1e-12},
        "runtime": {"python": sys.version.split()[0], "sklearn": sklearn.__version__},
        "metrics": metrics,
    }
    before_write()
    _write_json(output_dir / "run.json", run_record)
    _write_csv(output_dir / "predictions.csv", rows_out)
    return run_record


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = ["case_id", "security_id", "master_episode_group", "D", "overall_s_label", "partition",
              "exposure_status", "source_views", "prediction", "probability_true", "effective_decision_score",
              "decision_source", "gate_reason", "gate_would_disagree_with_signed_label", "scored", "is_error", "exclusion_reason",
              "history_bars", "d_volume", "top_numeric_contributions"]
    if any("inference_gate_json" in row for row in rows):
        fields.append("inference_gate_json")
    if any("structure_features_json" in row for row in rows):
        fields.extend(("structure_features_json", "structure_diagnostics_json"))
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run_once(
    *,
    data_root: Path,
    cases_path: Path,
    start_date: str,
    asof_date: str,
    expected_sha256: str,
    output_dir: Path,
) -> dict[str, Any]:
    start_date = _day(start_date, field="start_date")
    asof_date = _day(asof_date, field="asof_date")
    if start_date > asof_date:
        raise BaselineError("START_AFTER_ASOF")
    if not SHA256.fullmatch(expected_sha256):
        raise BaselineError("EXPECTED_CASES_SHA256_INVALID")
    cases, cases_identity = _read_cases(cases_path, start_date=start_date, asof_date=asof_date)
    if cases_identity["sha256"] != expected_sha256:
        raise BaselineError("SIGNED_CASE_TABLE_SHA256_MISMATCH")
    with bind_current_panels(data_root) as (panel_path, source, recheck):
        if asof_date > source["asof_date"]:
            raise BaselineError("REQUESTED_ASOF_AFTER_PANEL_ASOF")
        panel_rows, columns = _panel_rows(panel_path, start_date=start_date, asof_date=asof_date,
                                          codes=(row["security_id"] for row in cases))
        examples, gaps, unknown_exclusions, feature_names = _build_examples(
            cases, panel_rows, columns, start_date=start_date,
        )
        report = _report_base(cases_path=cases_path, start_date=start_date, asof_date=asof_date,
                              cases=cases, cases_identity=cases_identity, source=source, examples=examples,
                              gaps=gaps, unknown_exclusions=unknown_exclusions, features=feature_names,
                              expected_sha256=expected_sha256)
        report["panel_rows_read"] = len(panel_rows)
        if report["status"] != "PREFLIGHT_READY_SIGNED":
            raise BaselineError("RUN_BLOCKED_BY_PREFLIGHT:" + report["status"])
        if report["coverage"]["missing_binary_classes"]["train"] or report["coverage"]["missing_binary_classes"]["validation"]:
            raise BaselineError("BOTH_SPLIT_CLASSES_REQUIRED")
        # Reject invalid/occupied destinations before the one authorized fit.
        reserved_output = _reserve_output_dir(output_dir, Path(data_root))
        try:
            recheck()
            result = _fit_and_materialize(report, examples, reserved_output, before_write=recheck)
            recheck()
            return result
        except Exception as exc:
            failure = {
                **report,
                "schema": SCHEMA,
                "status": "FIT_FAILED_OR_SOURCE_CHANGED",
                "mode": "run",
                "fit_status": "FAILED_OR_UNACCEPTED",
                "output_dir": str(reserved_output),
                "failure": {"exception_type": type(exc).__name__, "reason": str(exc)},
                **FLAGS,
            }
            try:
                _write_json(reserved_output / "run.json", failure)
            except OSError:
                pass
            raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path(os.environ["V4_DATA_ROOT"]) if os.environ.get("V4_DATA_ROOT") else None)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--asof-date", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--expected-cases-sha256")
    parser.add_argument("--output-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.data_root is None:
            raise BaselineError("DATA_ROOT_REQUIRED_USE_V4_DATA_ROOT_OR_ARGUMENT")
        if args.run:
            if args.expected_cases_sha256 is None:
                raise BaselineError("SIGNED_CASES_SHA256_REQUIRED_FOR_RUN")
            if args.output_dir is None:
                raise BaselineError("NEW_OUTPUT_DIR_REQUIRED_FOR_RUN")
            result = run_once(data_root=args.data_root, cases_path=args.cases,
                              start_date=args.start_date, asof_date=args.asof_date,
                              expected_sha256=args.expected_cases_sha256,
                              output_dir=args.output_dir)
        else:
            result = preflight(data_root=args.data_root, cases_path=args.cases,
                               start_date=args.start_date, asof_date=args.asof_date,
                               expected_sha256=args.expected_cases_sha256)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        if result.get("status") == "BLOCKED_INPUT_OR_SPLIT_GAPS":
            return 2
        return 0
    except BaselineError as exc:
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "reason": str(exc), **FLAGS},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
