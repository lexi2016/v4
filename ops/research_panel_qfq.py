"""Internal full-history QFQ stage of the existing daily A-share authority.

There is deliberately no CLI, collector, default raw fallback or own CURRENT.
The original daily adapter supplies the two original pointers and authorities.
An adjustment snapshot is an immutable input, not an authority price panel.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import base64
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import zlib
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

DRIVER_SHA = "1b5f4caa099add5f0c369b72e0c6b9d8d80c964fe245a662290971e5142dcdae"
FORMULA_SHA = "074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258"
USER_FORMULA_SHA = "924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6"
META_KEY = b"a_share_qfq_contract_v1"
INPUT_NAME = "qfq_adjustment_input.json"
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
CODE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


from ops.research_panel_factor_cache import QfqGateError


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _json(path: Path, value: Any) -> None:
    _write(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def input_path(data_root: Path) -> Path:
    return data_root / "runtime/cache/data_layer_daily_formula_increment_update_v1" / INPUT_NAME


def _source(ref: dict, *, owner: str) -> Path:
    path = Path(ref["path"])
    if not path.is_absolute() or not path.is_file() or sha(path) != ref["sha256"]:
        raise QfqGateError(f"SOURCE_BINDING_FAILED:{owner}:{path}")
    return path


# This exception is the controller-reviewed D23 source gap, not a general
# permission to quarantine symbols outside the current universe.
EXACT_LEGACY_POLICY_SHA = "1cd95f23d7ce35a45348da5c939c61c2460fb5bb950d1b55be3d25c46cd5280d"


def legacy_preservation(ref: dict | None) -> dict:
    if not ref:
        return {}
    if ref.get("sha256") != EXACT_LEGACY_POLICY_SHA:
        raise QfqGateError("LEGACY_PRESERVATION_POLICY_NOT_APPROVED")
    policy = json.loads(_source(ref, owner="exact legacy preservation policy").read_text())
    if policy.get("schema") != "qfq_exact_legacy_preservation_v1":
        raise QfqGateError("LEGACY_PRESERVATION_POLICY_SCHEMA_INVALID")
    # Frozen projection of the SHA-bound original summary. Its live path can
    # legitimately be refreshed by a later daily sync; do not reread that path
    # as if it were the old receipt. The exact approved policy hash binds this
    # complete membership projection and every permitted old key hash.
    present = set(policy["original_membership_codes"])
    if canonical_sha(sorted(present)) != policy["original_membership_sha256"]:
        raise QfqGateError("LEGACY_ORIGINAL_MEMBERSHIP_PROJECTION_INVALID")
    if present.intersection(policy["codes"]):
        raise QfqGateError("LEGACY_PRESERVATION_OVERLAPS_ORIGINAL_UNIVERSE")
    return policy


def required_a_history(pointers: dict[str, Path]) -> dict[str, int]:
    """The shared files also contain HK rows, which this A lane must copy."""
    result = {}
    for pointer in pointers.values():
        path = Path(pointer.read_text(encoding="utf-8-sig").strip())
        for batch in pq.ParquetFile(path).iter_batches(columns=["ts_code", "trade_date"]):
            for code, date in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist()):
                if CODE.fullmatch(code):
                    result[code] = min(result.get(code, int(date)), int(date))
    return result


def load_snapshot(path: Path, target: int) -> dict:
    """Require explicit complete event coverage, including no-action symbols.

    events use a positive affine transform on prices STRICTLY BEFORE ex_date.
    They must be derived from a bound source (not a fitted chart offset).
    Volume uses the provider's independent backwardA, turnover stays actual.
    """
    if not path.is_file():
        raise QfqGateError(f"ADJUSTMENT_INPUT_MISSING:{path}")
    value = json.loads(path.read_text())
    if value.get("schema") != "a_share_qfq_adjustment_input_v1":
        raise QfqGateError("ADJUSTMENT_SCHEMA_INVALID")
    if value.get("asof_date") != target or value.get("coverage_end_date") != target:
        raise QfqGateError("ADJUSTMENT_ASOF_OR_COVERAGE_STALE")
    if value.get("price_basis") != "QFQ_ASOF" or value.get("volume_basis") != "QFQ_EVENT_VOLUME" or value.get("amount_basis") != "RAW_TURNOVER":
        raise QfqGateError("ADJUSTMENT_BASIS_CONFLICT")
    if not value.get("convention") or not value.get("revision") or not value.get("observed_at"):
        raise QfqGateError("ADJUSTMENT_PROVENANCE_MISSING")
    if not value.get("source_files") or not value.get("symbols"):
        raise QfqGateError("ADJUSTMENT_SOURCE_OR_SYMBOLS_EMPTY")
    for ref in value["source_files"]:
        _source(ref, owner="adjustment")
    legacy = legacy_preservation(value.get("legacy_preservation_policy"))
    legacy_codes = set(value.get("legacy_preservation_codes", []))
    if (not legacy_codes.issubset(legacy.get("codes", []))
            or legacy_codes & (set(value["symbols"]) | set(value.get("original_target_codes", []))
                               | set(value.get("quarantine_symbols", {})))):
        raise QfqGateError("LEGACY_PRESERVATION_OUTSIDE_EXACT_NON_TARGET_POLICY")
    for code, item in value.get("quarantine_symbols", {}).items():
        status = item.get("original_status", {})
        if (not CODE.fullmatch(code) or not item.get("reason") or status.get("classification") != "QUARANTINED"
                or status.get("quarantine") is not True or status.get("target_date_ready") is not False):
            raise QfqGateError(f"QUARANTINE_OUTSIDE_ORIGINAL_SOURCE_POLICY:{code}")
    for code, item in value["symbols"].items():
        if not CODE.fullmatch(code) or item.get("event_coverage_complete") is not True or "events" not in item:
            raise QfqGateError(f"ADJUSTMENT_SYMBOL_COVERAGE_UNCONFIRMED:{code}")
        start = item.get("history_start_date")
        if not isinstance(start, int) or start > target or not item.get("raw_files"):
            raise QfqGateError(f"RAW_HISTORY_BINDING_MISSING:{code}")
        if not isinstance(item.get("publish_roles"), list) or not set(item["publish_roles"]).issubset({"selector", "backtest"}):
            raise QfqGateError(f"PUBLISH_ROLE_BINDING_MISSING:{code}")
        if item.get("history_extension") and (not (value.get("history_extension") or value.get("history_retention_binding")) or item.get("raw_resolution") != HISTORY_RESOLUTION):
            raise QfqGateError(f"HISTORY_SNAPSHOT_POLICY_UNBOUND:{code}")
        dates = []
        for event in item["events"]:
            date, a, b, volume_a = int(event["ex_date"]), float(event["a"]), float(event["b"]), float(event["volume_a"])
            if not np.isfinite([a, b, volume_a]).all() or min(a, volume_a) <= 0 or date > target or date <= start:
                raise QfqGateError(f"ADJUSTMENT_EVENT_INVALID:{code}:{date}")
            dates.append(date)
        if dates != sorted(set(dates)):
            raise QfqGateError(f"ADJUSTMENT_EVENT_ORDER_OR_DUPLICATE:{code}")
        for ref in item["raw_files"]:
            _source(ref, owner=code)
    return value


def apply_adjustments(raw: pd.DataFrame, events: list[dict], target: int) -> pd.DataFrame:
    out = raw.loc[raw.trade_date.le(target)].copy().sort_values("trade_date").reset_index(drop=True)
    if out.empty or out.trade_date.duplicated().any():
        raise QfqGateError("RAW_HISTORY_EMPTY_OR_DUPLICATED")
    if raw[["open", "high", "low", "close"]].le(0).any().any():
        raise QfqGateError("RAW_PRICE_INVALID")
    out[["vol", "volume"]] = out[["vol", "volume"]].astype(float)
    for event in events:  # chronological composition: the newest event applies last
        before = out.trade_date.lt(int(event["ex_date"]))
        out.loc[before, ["open", "high", "low", "close"]] = (
            out.loc[before, ["open", "high", "low", "close"]] * float(event["a"]) + float(event["b"])
        )
        # Futu supplies its own backwardA for volume. It is not reconstructed
        # as 1/forwardA (the supplied values have independent precision).
        out.loc[before, ["vol", "volume"]] *= float(event["volume_a"])
    prices = out[["open", "high", "low", "close"]]
    if not np.isfinite(prices.to_numpy()).all():
        raise QfqGateError("ADJUSTED_PRICE_INVALID")
    if (out.high.lt(out[["open", "close", "low"]].max(axis=1)) | out.low.gt(out[["open", "close", "high"]].min(axis=1))).any():
        raise QfqGateError("ADJUSTED_OHLC_INVALID")
    return out


def _load(path: Path, expected: str, name: str):
    if sha(path) != expected:
        raise QfqGateError(f"AUTHORITY_SOURCE_DRIFT:{path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def authorities(driver_path: Path, formula_path: Path):
    formula = _load(formula_path, FORMULA_SHA, "qfq_original_canonical_formula")
    driver = _load(driver_path, DRIVER_SHA, "qfq_original_daily_driver")
    driver._CANONICAL_FORMULA_MODULE = formula
    return driver, formula


HISTORY_RESOLUTION = "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"


def resolved_raw_history(code: str, item: dict, target: int, driver) -> pd.DataFrame:
    """Read original whole rows, using the frozen archive-first key policy."""
    parts = []
    history = item.get("raw_resolution") == HISTORY_RESOLUTION
    if item.get("raw_resolution") and not history:
        raise QfqGateError(f"RAW_RESOLUTION_UNSUPPORTED:{code}")
    for ref in item["raw_files"]:
        path = _source(ref, owner=code)
        if path.stat().st_size % driver.DAY_STRUCT.size:
            raise QfqGateError(f"RAW_TRAILING_BYTES:{code}:{path}")
        part = driver.read_day_tail(code, path, tail_records=path.stat().st_size // driver.DAY_STRUCT.size)
        if history:
            if ref.get("source_role") not in {"archive", "native"} or ref.get("from_date_exclusive") is not None:
                raise QfqGateError(f"HISTORY_WHOLE_ROW_POLICY_CONFLICT:{code}")
            if part.trade_date.duplicated().any():
                raise QfqGateError(f"HISTORY_SOURCE_DUPLICATE_DATE:{code}")
            part["raw_source_role"] = ref["source_role"]
            part["raw_source_ref_sha256"] = ref["sha256"]
            part["raw_source_record_index"] = np.arange(len(part))
        elif ref.get("from_date_exclusive") is not None:
            part = part.loc[part.trade_date.gt(int(ref["from_date_exclusive"]))].copy()
        parts.append(part)
    raw = pd.concat(parts, ignore_index=True)
    if history:
        for role in ("archive", "native"):
            if raw.loc[raw.raw_source_role.eq(role), "trade_date"].duplicated().any():
                raise QfqGateError(f"HISTORY_AMBIGUOUS_SOURCE_ROLE:{code}:{role}")
        # Priority chooses a whole row. Native internal gaps and tails both
        # survive; no field-level reconciliation or max-archive-date clipping.
        raw["_priority"] = raw.raw_source_role.map({"archive": 0, "native": 1})
        raw = raw.sort_values(["trade_date", "_priority"], kind="stable").drop_duplicates("trade_date").drop(columns="_priority")
        raw = raw.loc[raw.trade_date.le(target)]
    else:
        fields = ["trade_date", "open", "high", "low", "close", "vol", "amount"]
        if raw[fields].drop_duplicates().trade_date.duplicated().any():
            raise QfqGateError(f"RAW_SOURCE_OVERLAP_CONFLICT:{code}")
        raw = raw.drop_duplicates("trade_date")
    return raw.sort_values("trade_date").reset_index(drop=True)



USER_FORMULA_VERSION = "ACTIVE_MA_USER_20261021_V1"
LEGACY_FORMULA_VERSION = "CANONICAL_V192_BRICK_B3_DOUBLE_BREAKOUT_V1"
USER_FORMULA_COMPONENTS = {
    "B1": "B1", "B2": "B2", "B3": "B3", "breakout": "breakout",
    "breakout_cross_star": "breakout_cross_star", "three_quarter_yin_volume_line": "three_quarter_yin_volume_line",
    "single_needle_under20": "single_needle_under20", "break_prev_low": "didi_break_prev_low",
    "under_yellow": "under_yellow_not_break", "first_fly": "first_fly", "second_fly": "second_fly",
    "white_yellow_death_cross": "white_yellow_death_cross",
}
USER_FORMULA_SIGNAL_FIELDS = tuple("user_v1_" + name for name in (
    *USER_FORMULA_COMPONENTS, "macd_golden_cross", "macd_below_zero_second_gold",
    "macd_above_zero_second_gold", "level1_buy_signal", "level2_buy_signal",
    "hold_yesterday_keyline_daily", "break_yesterday_keyline_daily", "hold_yesterday_keyline_display_asof",
    "break_yesterday_keyline_display_asof", "sell_signal_daily", "sell_signal_display_asof"))


def _user_count_since_reset(golden: pd.Series, reset: pd.Series) -> pd.Series:
    """COUNT(golden, BARSLAST(reset)); COUNT(X,0) counts the whole prefix."""
    cumulative = np.cumsum(golden.fillna(False).to_numpy(dtype=np.int64))
    values, last = [], None
    for i, flag in enumerate(reset.fillna(False).to_numpy(dtype=bool)):
        if flag:
            last = i
        # BARSLAST has no known reset before the first reset; do not invent one.
        if last is None:
            values.append(np.nan)
        elif i == last:
            values.append(int(cumulative[i]))
        else:
            values.append(int(cumulative[i] - cumulative[last]))
    return pd.Series(values, index=golden.index)


def append_user_formula_v1(features: pd.DataFrame, target: int) -> pd.DataFrame:
    """Version the supplied user's labels without changing legacy model fields.

    Price/BBI/white/yellow/J/B123 and equivalent component expressions use the
    pinned original engine's full-prefix numerical convention. The original
    canonical single-cross M2 fields and brick-based primary remain unchanged.
    """
    out = features.copy()
    for name, original in USER_FORMULA_COMPONENTS.items():
        out["user_v1_" + name] = out[original].astype("int8")
    dif, dea = out.macd_dif, out.macd_dea
    golden = dif.gt(dea) & dif.shift(1).le(dea.shift(1))
    above_count = _user_count_since_reset(golden, dea.le(0))
    below_count = _user_count_since_reset(golden, dea.ge(0))
    above = golden & dea.gt(0) & above_count.ge(2)
    below = golden & dea.lt(0) & below_count.eq(2).rolling(21, min_periods=1).sum().eq(1)
    out["user_v1_macd_golden_cross"] = golden.astype("int8")
    out["user_v1_macd_above_zero_second_gold"] = above.astype("int8")
    out["user_v1_macd_below_zero_second_gold"] = below.astype("int8")
    level1 = out.B3.eq(1) | above
    out["user_v1_level1_buy_signal"] = level1.astype("int8")
    out["user_v1_level2_buy_signal"] = ((out.B1.eq(1) | out.B2.eq(1) | out.breakout.eq(1)
        | out.breakout_cross_star.eq(1) | below) & ~level1).astype("int8")
    today = pd.to_numeric(out.trade_date).eq(target)
    hold, broken = out.hold_yesterday_keyline.eq(1), out.break_yesterday_keyline.eq(1)
    out["user_v1_hold_yesterday_keyline_daily"] = hold.astype("int8")
    out["user_v1_break_yesterday_keyline_daily"] = broken.astype("int8")
    out["user_v1_hold_yesterday_keyline_display_asof"] = (today & hold).astype("int8")
    out["user_v1_break_yesterday_keyline_display_asof"] = (today & broken).astype("int8")
    timeless_sell = out.white_yellow_death_cross.eq(1) | out.didi_break_prev_low.eq(1)
    out["user_v1_sell_signal_daily"] = (broken | timeless_sell).astype("int8")
    out["user_v1_sell_signal_display_asof"] = ((today & broken) | timeless_sell).astype("int8")
    return out


def user_formula_schema(schema: pa.Schema) -> pa.Schema:
    """Add nullable versioned labels; retained foreign-market rows remain null."""
    fields = list(schema)
    for name in USER_FORMULA_SIGNAL_FIELDS:
        if name not in schema.names:
            fields.append(pa.field(name, pa.int8(), nullable=True))
    return pa.schema(fields, metadata=schema.metadata)


def rebuild_symbol(code: str, item: dict, target: int, driver) -> pd.DataFrame:
    raw = resolved_raw_history(code, item, target, driver)
    if raw.empty or int(raw.trade_date.min()) != item["history_start_date"]:
        raise QfqGateError(f"RAW_HISTORY_START_MISMATCH:{code}")
    if item.get("compute_start_date") is not None:
        raw = raw.loc[raw.trade_date.ge(item["compute_start_date"])].reset_index(drop=True)
    amount_bits = raw.amount.to_numpy(dtype=np.float32).view(np.uint32)
    malformed = (amount_bits == 0x00400000) & raw.vol.eq(0).to_numpy()
    if malformed.any():
        dates = raw.loc[malformed, "trade_date"].astype(int).tolist()
        raise QfqGateError(f"ORIGINAL_RAW_FIELD_SIGNATURE_QUARANTINED:{code}:{dates[:10]}")
    adjusted = apply_adjustments(raw, item["events"], target)
    features = driver.compute_formula_features(adjusted, 0, {}, driver._NoopLogger(), emit_all_rows=True, xdxr_events=None)
    canonical = driver._compute_canonical_v192_formula(adjusted)
    for column in canonical.columns:
        features[column] = canonical[column].to_numpy()
    # Aggregates from the original canonical build_canonical entry, whose pure
    # partition function emits the component signals.
    features["sell_signal"] = (features.break_yesterday_keyline.eq(1) | features.white_yellow_death_cross.eq(1)
                               | features.macd_top_divergence.eq(1) | features.didi_break_prev_low.eq(1)).astype("int8")
    for n in (120, 250):
        features[f"ma{n}"] = features.close.rolling(n, min_periods=1).mean()
    features["macd_above_zero"] = features.macd_dif.gt(0).astype("int8")
    features["macd_below_zero"] = features.macd_dif.lt(0).astype("int8")
    features["macd_golden_cross"] = (features.macd_dif.gt(features.macd_dea) & features.macd_dif.shift().le(features.macd_dea.shift())).astype("int8")
    features["zge_white_above_yellow"] = features.zge_white_line.gt(features.zge_yellow_line).astype("int8")
    features["close_above_bbi"] = features.close.gt(features.BBI).astype("int8")
    features = driver.append_backtest_provenance_and_tradeability(features, Path("QFQ_FULL_HISTORY"))
    # Tradeability describes observed raw-market activity, including histories
    # where an affine chart adjustment legitimately makes an old price < 0.
    features["tradeable_basic"] = (raw[["open", "high", "low", "close"]].gt(0).all(axis=1)
                                   & raw.amount.gt(0) & raw.vol.gt(0)).to_numpy(dtype="int8")[:len(features)]
    # QFQ closes already include all corporate actions. Original REF(CLOSE,1)
    # means the preceding adjusted close; a second XDXR pre-close is forbidden.
    expected = adjusted.close.shift(1)
    if not np.allclose(features.pre_close, expected, equal_nan=True):
        raise QfqGateError(f"DOUBLE_ADJUSTED_PRE_CLOSE:{code}")
    features["pct_chg_source"] = "qfq_asof_previous_adjusted_close"
    features["source"] = "tdx_vipdoc_qfq_full_history"
    if item.get("history_extension"):
        # Observed bars are not an authenticated listing date. The role schema
        # must explicitly permit this null before any candidate can be written.
        features["bars_since_list"] = None
        for column in ("raw_source_role", "raw_source_ref_sha256", "raw_source_record_index"):
            features[column] = raw[column].to_numpy()
    else:
        features["bars_since_list"] = np.arange(1, len(features) + 1)
    return append_user_formula_v1(features, target)


def _bucket(code: str) -> int:
    return zlib.crc32(code.encode()) % 32


def spool_current(path: Path, destination: Path, source_sha256: str) -> dict[int, Path]:
    """One bounded scan, rather than thousands of predicate full-table scans."""
    receipt_path = destination / "receipt.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("source_sha256") == source_sha256 and receipt.get("row_copy") == "ARROW_V1":
            files = {int(k): Path(v["path"]) for k, v in receipt["files"].items()}
            if all(p.is_file() and sha(p) == receipt["files"][str(k)]["sha256"] for k, p in files.items()):
                return files
    destination.mkdir(parents=True, exist_ok=True)
    schema = pq.ParquetFile(path).schema_arrow
    writers, files = {}, {}
    try:
        for batch in pq.ParquetFile(path).iter_batches(batch_size=32768):
            table = pa.Table.from_batches([batch])
            buckets = [_bucket(code) for code in table["ts_code"].to_pylist()]
            for index in sorted(set(buckets)):
                part = table.filter(pa.array([b == index for b in buckets]))
                if index not in writers:
                    files[index] = destination / f"bucket_{index:02}.parquet"
                    writers[index] = pq.ParquetWriter(files[index].with_suffix(".pending"), schema, compression="zstd")
                writers[index].write_table(part)
    finally:
        for writer in writers.values():
            writer.close()
    for path in files.values():
        os.replace(path.with_suffix(".pending"), path)
    _json(receipt_path, dict(source_sha256=source_sha256, row_copy="ARROW_V1", files={str(k): dict(path=str(p), sha256=sha(p)) for k, p in files.items()}))
    return files


LEGACY_STATIC_FIELDS = frozenset("""raw_code name total_share_10k float_share_10k market_cap_yi float_market_cap_yi turnover_rate_pct finance_source_date list_date tdx_finance_area_code tdx_finance_industry_code tdx_industry_code sw_industry_code static_fundamental_source fundamental_snapshot_note tdx_industry_name is_st_snapshot research_panel_scope candidate_pool_policy minute_data_policy minute_data_output_root minute_data_contract_path minute_data_default_scope minute_data_required_outputs""".split())
LEGACY_RAW_CONTEXT_FIELDS = frozenset("""price_limit_pct_est limit_up_price_est limit_down_price_est is_limit_up_est is_limit_down_est is_one_word_limit_up_est limit_board_count_est limit_down_board_count_est price_limit_source limit_up_approx limit_down_approx""".split())
LEGACY_MARKET_CONTEXT_FIELDS = frozenset("""market_active_stock_count market_up_count market_down_count market_flat_count market_limit_up_count_est market_limit_down_count_est market_max_limit_board_count_est market_total_amount_yi market_context_source""".split())
LEGACY_AUX_FIELDS = LEGACY_STATIC_FIELDS | LEGACY_RAW_CONTEXT_FIELDS | LEGACY_MARKET_CONTEXT_FIELDS


def field_basis_contract(driver) -> dict:
    result = {name: dict(basis=basis, scope="A", recomputed=False, historical_values="RETAIN_ORIGINAL", new_dates="NULL")
              for fields, basis in ((LEGACY_STATIC_FIELDS, "LEGACY_STATIC_CONTEXT"),
                                    (LEGACY_RAW_CONTEXT_FIELDS, "LEGACY_RAW_CONTEXT"),
                                    (LEGACY_MARKET_CONTEXT_FIELDS, "LEGACY_MARKET_CONTEXT")) for name in sorted(fields)}
    result["field_contract_version"] = dict(basis="AUTHORITATIVE_LINEAGE_METADATA", scope="A", value=driver.CONTRACT_PROVENANCE_FIELD_DEFAULTS["field_contract_version"])
    return result


def computation_kernel_sha(source: Path) -> str:
    tree = ast.parse(source.read_text())
    names = {"apply_adjustments", "resolved_raw_history", "rebuild_symbol", "authorities", "_load"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise QfqGateError("CHECKPOINT_COMPUTATION_KERNEL_MISSING")
    return canonical_sha([ast.dump(node, include_attributes=False) for node in nodes])


def checkpoint_recovery(ref: dict | None, snapshot: dict, identity: dict, baseline: dict, data_root: Path,
                        *, tail_delta: dict | None = None) -> dict:
    if not ref:
        return {}
    recovery = json.loads(_source(ref, owner="reviewed checkpoint recovery").read_text())
    old = recovery["source_identity"]
    if (recovery.get("schema") != "qfq_original_checkpoint_recovery_v1"
            or any(old.get(k) != v for k, v in identity.items() if k != "adapter_sha256")
            or recovery.get("baseline_panel_sha256") != baseline):
        raise QfqGateError("CHECKPOINT_RECOVERY_INPUT_OR_FORMULA_CHANGED")
    original_snapshot = _source(recovery["original_snapshot"], owner="original prepared input snapshot")
    if json.loads(original_snapshot.read_text()) != snapshot or factor_cache_identity(data_root, snapshot["asof_date"], snapshot) != recovery["factor_cache_identity"]:
        raise QfqGateError("CHECKPOINT_RECOVERY_INPUT_OR_FACTOR_CACHE_CHANGED")
    old_source = _source(recovery["source_core"], owner="original chunk computation source")
    if old["adapter_sha256"] != recovery["source_core"]["sha256"] or computation_kernel_sha(old_source) != computation_kernel_sha(Path(__file__)):
        raise QfqGateError("CHECKPOINT_RECOVERY_COMPUTATION_CHANGED")
    run = Path(recovery["source_run"])
    old_generation = canonical_sha(dict(target=snapshot["asof_date"], baseline_panel_sha256=baseline, **old))
    if run.name != "qfq_" + old_generation[:20] or json.loads((run / "adjustment_input_snapshot.json").read_text()) != snapshot:
        raise QfqGateError("CHECKPOINT_RECOVERY_SOURCE_GENERATION_CONFLICT")
    chunks, retry = recovery["chunks"], set(recovery["retry_original_quarantined"])
    if tail_delta is not None:
        binding = tail_delta.get("binding_ref")
        tail_codes = tail_delta.get("codes")
        if (tail_delta.get("schema") != "qfq_native_tail_delta_v2"
                or not isinstance(tail_codes, dict) or len(tail_codes) != 37
                or not set(tail_codes).issubset(snapshot["symbols"])
                or not isinstance(binding, dict) or recovery.get("tail_delta") != binding
                or retry or set(chunks) != set(tail_codes)):
            raise QfqGateError("CHECKPOINT_RECOVERY_EXACT37_TAIL_SCOPE_CONFLICT")
        # The caller passes the result of tail_delta_binding, not a new scope.
        bound_tail = json.loads(_source(binding, owner="validated tail checkpoint scope").read_text())
        if bound_tail != {k: v for k, v in tail_delta.items() if k != "binding_ref"}:
            raise QfqGateError("CHECKPOINT_RECOVERY_TAIL_BINDING_CHANGED")
    elif (recovery.get("tail_delta") is not None or set(chunks) & retry
            or set(chunks) | retry != set(snapshot["symbols"])
            or not retry.issubset(snapshot.get("original_quarantine_eligible", {}))):
        raise QfqGateError("CHECKPOINT_RECOVERY_SYMBOL_COVERAGE_CONFLICT")
    paths = set()
    for code, item in chunks.items():
        path = _source(item["artifact"], owner="recovered chunk " + code)
        receipt_path = _source(item["receipt"], owner="recovered chunk receipt " + code)
        if path != run / "symbol_checkpoints" / (code + ".parquet") or receipt_path != path.with_suffix(".receipt.json") or str(path) in paths:
            raise QfqGateError("CHECKPOINT_RECOVERY_MAPPING_CONFLICT:" + code)
        paths.add(str(path))
        fingerprint = canonical_sha(dict(code=code, item=snapshot["symbols"][code], **old))
        receipt = json.loads(receipt_path.read_text())
        if receipt.get("checkpoint_id") != fingerprint or panel_contract(path).get("checkpoint_id") != fingerprint or receipt.get("sha256") != item["artifact"]["sha256"]:
            raise QfqGateError("CHECKPOINT_RECOVERY_FINGERPRINT_CONFLICT:" + code)
    return chunks


def merge_rebuilt(old: pd.DataFrame, rebuilt: pd.DataFrame, *, role: str, driver, history_extension: bool = False) -> pd.DataFrame:
    """Replace every old affected OHLC/formula row; retain historical metadata."""
    rebuilt = rebuilt.copy()
    # This is lineage metadata from the pinned original authoritative contract,
    # not a numerical formula input and never an old-row price fallback.
    rebuilt["field_contract_version"] = driver.CONTRACT_PROVENANCE_FIELD_DEFAULTS["field_contract_version"]
    if old.empty:
        if history_extension:
            for column in (set(rebuilt) & LEGACY_AUX_FIELDS) | {"bars_since_list"}:
                rebuilt[column] = None
        return rebuilt
    if old.trade_date.duplicated().any():
        raise QfqGateError(f"CURRENT_DUPLICATE_KEYS:{role}")
    old = old.copy()
    old["trade_date"] = pd.to_numeric(old.trade_date).astype(int)
    source = rebuilt.set_index("trade_date")
    if not set(old.trade_date).issubset(source.index):
        missing = sorted(set(old.trade_date) - set(source.index))
        raise QfqGateError(f"RAW_HISTORY_KEYS_MISSING:{role}:{missing[:10]}")
    fresh = (source if history_extension else source.loc[source.index >= int(old.trade_date.min())]).reset_index()
    preserved = old.set_index("trade_date")
    # Formula fields are generated only by original authorities; other historic
    # data retain their original per-row values rather than latest-row backfill.
    for column in old.columns:
        if column not in fresh.columns:
            if column not in LEGACY_AUX_FIELDS:
                raise QfqGateError(f"FORMULA_RECOMPUTATION_MISSING:{role}:{column}")
            # Preserve only explicitly classified, non-target legacy context.
            # No latest-row fill for a new date, including numeric auxiliaries.
            fresh[column] = fresh.trade_date.map(preserved[column])
    if history_extension:
        for column in (set(fresh) & LEGACY_AUX_FIELDS) | {"bars_since_list"}:
            fresh[column] = fresh.trade_date.map(preserved[column]) if column in preserved else None
    return fresh


def _panel_symbols(path: Path) -> set[str]:
    values = set()
    for batch in pq.ParquetFile(path).iter_batches(columns=["ts_code"], batch_size=131072):
        values.update(str(v) for v in batch.column(0).unique().to_pylist())
    return values


def _table(frame: pd.DataFrame, schema: pa.Schema, driver, role: str, *, history_extension: bool = False) -> pa.Table:
    # No original formula field is silently default-filled with zero.
    missing = [f.name for f in schema if f.name not in frame and f.name not in LEGACY_AUX_FIELDS]
    if missing:
        raise QfqGateError(f"UNCOMPUTED_FORMULA_FIELDS:{role}:{missing}")
    nullable_context = LEGACY_AUX_FIELDS | ({"bars_since_list"} if history_extension else set())
    for field in schema:
        if field.name in nullable_context:
            values = frame[field.name] if field.name in frame else pd.Series([None] * len(frame))
            if history_extension and values.isna().any() and not field.nullable:
                raise QfqGateError(f"HISTORY_CONTEXT_NOT_NULLABLE:{role}:{field.name}")
    table = driver.build_table_for_schema(frame, schema, role)[0]
    # The legacy driver fills nullable ints/bools with 0/False. That would
    # fabricate auxiliary context on new dates; preserve its explicit nulls.
    for field in schema:
        if field.name in nullable_context:
            values = frame[field.name] if field.name in frame else pd.Series([None] * len(frame))
            table = table.set_column(schema.get_field_index(field.name), field, pa.Array.from_pandas(values, type=field.type))
    return table


def history_extension_binding(ref: dict, *, data_root: Path, return_root: Path,
                              pointers: dict[str, Path], publish: bool) -> dict:
    """Fail closed before locks/writes; history runs only in an isolated root."""
    if publish:
        raise QfqGateError("HISTORY_EXTENSION_PUBLICATION_FORBIDDEN")
    value = json.loads(_source(ref, owner="history extension contract").read_text())
    if (value.get("schema") != "qfq_shared_history_extension_v1" or value.get("historical_PIT") is not False
            or value.get("maximum_claim") != "DIRECTION_ONLY" or set(value.get("roles", {})) != {"selector", "backtest"}):
        raise QfqGateError("HISTORY_EXTENSION_CONTRACT_INVALID")
    # Array refs are optional when the source uses no archive or extra evidence.
    for name in ("archive_refs", "accepted_evidence"):
        value.setdefault(name, [])
        if not isinstance(value[name], list):
            raise QfqGateError("HISTORY_EXTENSION_REFERENCE_LIST_INVALID:" + name)
    root = Path(value["isolation_root"]).resolve()
    for path in [data_root, return_root, *pointers.values()]:
        if not Path(path).resolve().is_relative_to(root) or Path(path).resolve() == root:
            raise QfqGateError(f"HISTORY_EXTENSION_PATH_OUTSIDE_ISOLATION:{path}")
    if set(pointers) != {"selector", "backtest"}:
        raise QfqGateError("HISTORY_EXTENSION_DUAL_ROLE_REQUIRED")
    for role, binding in value["roles"].items():
        path = _source(binding["panel"], owner="history baseline " + role)
        pointer_target = Path(pointers[role].read_text(encoding="utf-8-sig").strip())
        baseline_contract = panel_contract(path)
        if pointer_target != path or baseline_contract.get("generation_id") != value["baseline_generation_id"]:
            raise QfqGateError(f"HISTORY_BASELINE_ROLE_GENERATION_CONFLICT:{role}")
        # The independent extractor must bind ordered fields, type/nullability,
        # and both key sets. They are role-specific, not a shared 5533 mask.
        if not binding.get("key_sha256") or not binding.get("schema_sha256") or "sidecars" not in binding:
            raise QfqGateError(f"HISTORY_BASELINE_KEY_SCHEMA_UNBOUND:{role}")
        if baseline_contract.get("quarantine_manifest_path"):
            quarantine = _source(value["quarantine_manifest"], owner="baseline same-generation quarantine")
            prior = json.loads(quarantine.read_text())
            expected_sidecar = prior.get("artifacts", {}).get(role, {})
            if (str(quarantine) != baseline_contract["quarantine_manifest_path"]
                    or prior.get("generation_id") != value["baseline_generation_id"]
                    or not expected_sidecar.get("sha256")
                    or not any(all(ref.get(k) == expected_sidecar.get(k) for k in ("path", "sha256")) for ref in binding["sidecars"])):
                raise QfqGateError(f"HISTORY_BASELINE_SIDECAR_MEMBERSHIP_UNBOUND:{role}")
        for sidecar in binding["sidecars"]:
            side = _source(sidecar, owner="history baseline sidecar " + role)
            metadata = pq.ParquetFile(side).schema_arrow.metadata or {}
            side_meta = json.loads(metadata.get(b"quarantine_contract", b"{}"))
            if side_meta.get("generation_id") != value["baseline_generation_id"]:
                raise QfqGateError(f"HISTORY_SIDECAR_GENERATION_CONFLICT:{role}")
    return {**value, "binding_ref": ref}


def history_role_identity(path: Path) -> dict:
    """Bounded per-role key/footer identity, executed only after registration."""
    schema = pq.ParquetFile(path).schema_arrow
    ordered_schema = [dict(name=f.name, type=str(f.type), nullable=f.nullable) for f in schema]
    digest, rows = hashlib.sha256(), 0
    # This digest binds the actual artifact's ordered keys. Old-key set
    # containment is independently enforced in the existing spool/merge gates.
    for batch in pq.ParquetFile(path).iter_batches(columns=["ts_code", "trade_date"]):
        for code, date in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist()):
            digest.update(json.dumps([str(code), int(date)], separators=(",", ":")).encode() + b"\n")
            rows += 1
    return dict(key_sha256=digest.hexdigest(), schema_sha256=canonical_sha(ordered_schema), rows=rows)


def generation_identity(snapshot: dict, driver_path: Path, formula_path: Path, contract_csv: Path) -> dict:
    return dict(input_sha256=canonical_sha(snapshot), driver_sha256=sha(driver_path), formula_sha256=sha(formula_path),
                adapter_sha256=sha(Path(__file__)), input_adapter_sha256=sha(Path(__file__).with_name("research_panel_adjustment_inputs.py")),
                factor_cache_sha256=sha(Path(__file__).with_name("research_panel_factor_cache.py")),
                tdx_adapter_sha256=sha(Path(__file__).with_name("research_panel_tdx_adjustment_inputs.py")),
                field_contract_sha256=sha(contract_csv), user_formula_sha256=USER_FORMULA_SHA)


def refresh_due(data_root: Path, target: int, max_age_hours: int = 6) -> bool:
    root = input_path(data_root).parent
    binding = root / "qfq_factor_cache_binding.json"
    cache_root = Path(json.loads(binding.read_text())["path"]) if binding.is_file() else root / "futu_rehab"
    checkpoint = cache_root / str(target) / "checkpoint.json"
    try:
        payload = json.loads(checkpoint.read_text())
        timestamps = [datetime.fromisoformat(item["queried_at"]) for item in payload["symbols"].values() if item.get("status") in ("OK", "EMPTY")]
        completed = min(timestamps) if timestamps else datetime.fromisoformat(payload["completed_at"])
        return (datetime.now(timezone.utc) - completed).total_seconds() > max_age_hours * 3600
    except (OSError, ValueError, KeyError, TypeError):
        return True


def panel_contract(path: Path) -> dict:
    raw = (pq.ParquetFile(path).schema_arrow.metadata or {}).get(META_KEY)
    return json.loads(raw) if raw else {}


def factor_cache_identity(data_root: Path, target: int, snapshot: dict) -> str | None:
    """Bind relevant cached semantic states, excluding requery timestamps.

    A new successful response must also belong to the normalized input's
    bound sources. This prevents pinning a revised cache beside an old input
    while a long price rebuild is still running.
    """
    if snapshot.get("history_extension"):
        # Offline history binds immutable original metadata, not a concurrently
        # refreshed live daily checkpoint with a different membership/window.
        history = json.loads(_source(snapshot["history_extension"], owner="offline history cache identity").read_text())
        metadata = _source(history["adjustment_metadata"], owner="bound offline factor receipts")
        return sha(metadata)
    root = input_path(data_root).parent
    binding = root / "qfq_factor_cache_binding.json"
    cache_root = Path(json.loads(binding.read_text())["path"]) if binding.is_file() else root / "futu_rehab"
    checkpoint = cache_root / str(target) / "checkpoint.json"
    if not checkpoint.is_file():
        return None
    cache = json.loads(checkpoint.read_text())
    if not isinstance(cache, dict) or cache.get("asof_date") != target or not isinstance(cache.get("symbols"), dict):
        raise QfqGateError("LATEST_FACTOR_CACHE_SCHEMA_OR_ASOF_INVALID")
    source_hashes = {ref["sha256"] for ref in snapshot["source_files"]}
    relevant = dict(snapshot["symbols"])
    for code, item in snapshot.get("quarantine_symbols", {}).items():
        if item.get("factor_evidence"):
            relevant[code] = item
    semantic = {}
    for code, item in sorted(relevant.items()):
        state = cache["symbols"].get(code)
        if not isinstance(state, dict):
            raise QfqGateError(f"LATEST_FACTOR_CACHE_CODE_MISSING:{code}")
        status = state.get("status")
        if status in ("OK", "EMPTY"):
            ref = state["response"]
            _source(ref, owner=f"latest factor cache {code}")
            if ref["sha256"] not in source_hashes:
                raise QfqGateError(f"LATEST_FACTOR_RESPONSE_NOT_IN_NORMALIZED_INPUT:{code}")
            semantic[code] = dict(status=status, response_sha256=ref["sha256"])
        elif status == "UNSUPPORTED_MARKET" and item.get("source_method") == "TDX_OFFICIAL_TERMS_BOUND_CONVERSION":
            ref = state["response"]
            _source(ref, owner=f"latest unsupported factor cache {code}")
            semantic[code] = dict(status=status, response_sha256=ref["sha256"])
        else:
            evidence = item.get("factor_evidence", {})
            if status == "UNSUPPORTED_MARKET" and evidence.get("status") == status:
                ref = state["response"]
                _source(ref, owner=f"latest quarantined factor cache {code}")
                if ref["sha256"] != evidence.get("response", {}).get("sha256"):
                    raise QfqGateError(f"LATEST_FACTOR_QUARANTINE_RESPONSE_CHANGED:{code}")
                semantic[code] = dict(status=status, response_sha256=ref["sha256"])
                continue
            if status != "ERROR" or evidence.get("status") != status or not state.get("error") or state.get("error") != evidence.get("error"):
                raise QfqGateError(f"LATEST_FACTOR_CACHE_STATE_INVALID_OR_CHANGED:{code}:{status}")
            semantic[code] = dict(status=status, error=state["error"])
    return canonical_sha(semantic)


def pointer_ready(selector_pointer: Path, target: int, snapshot_path: Path) -> bool:
    """Cheap scheduler check: changed event cache bytes invalidate same-date READY.

    Full byte binding (including raw sources) is repeated inside the write lock.
    Stat checks here detect normal TDX appends/revisions without hashing GB/minute.
    """
    try:
        if os.environ.get("RESEARCH_PANEL_QFQ_REFRESH_FACTORS") == "1" or refresh_due(selector_pointer.parent.parent, target):
            return False
        current = Path(selector_pointer.read_text(encoding="utf-8-sig").strip())
        contract = panel_contract(current)
        snapshot = json.loads(snapshot_path.read_text())
        if contract.get("asof_date") != target or contract.get("snapshot_file_sha256") != sha(snapshot_path):
            return False
        if contract.get("adapter_sha256") != sha(Path(__file__)):
            return False
        if contract.get("input_adapter_sha256") != sha(Path(__file__).with_name("research_panel_adjustment_inputs.py")):
            return False
        if contract.get("factor_cache_sha256") != sha(Path(__file__).with_name("research_panel_factor_cache.py")):
            return False
        if contract.get("tdx_adapter_sha256") != sha(Path(__file__).with_name("research_panel_tdx_adjustment_inputs.py")):
            return False
        backtest_pointer = selector_pointer.parent.parent / "backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt"
        backtest = Path(backtest_pointer.read_text(encoding="utf-8-sig").strip())
        if panel_contract(backtest).get("generation_id") != contract.get("generation_id"):
            return False
        readiness = json.loads(snapshot_path.with_name("qfq_readiness.json").read_text())
        if readiness.get("generation_id") != contract.get("generation_id"):
            return False
        cache_identity = factor_cache_identity(selector_pointer.parent.parent, target, snapshot)
        if not cache_identity or readiness.get("factor_cache_identity") != cache_identity:
            return False
        for ref in readiness["code_refs"]:
            if sha(Path(ref["path"])) != ref["sha256"]:
                return False
        for ref in readiness["source_stats"]:
            stat = Path(ref["path"]).stat()
            if stat.st_size != ref["size"] or stat.st_mtime_ns != ref["mtime_ns"]:
                return False
        return snapshot.get("asof_date") == target
    except (OSError, ValueError, KeyError, TypeError, AttributeError, QfqGateError):
        return False


@contextmanager
def publication_lock(data_root: Path):
    path = data_root / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publish.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QfqGateError("QFQ_OWNER_ALREADY_ACTIVE") from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def baseline_binding(pointers: dict[str, Path]) -> dict:
    before = {role: path.read_bytes() for role, path in pointers.items()}
    result = dict(schema="qfq_expected_current_v1", roles={role: dict(pointer_path=str(pointers[role]),
                  pointer_sha256=hashlib.sha256(value).hexdigest(), target_path=value.decode("utf-8-sig").strip(),
                  target_sha256=sha(Path(value.decode("utf-8-sig").strip()))) for role, value in before.items()})
    if any(path.read_bytes() != before[role] for role, path in pointers.items()):
        raise QfqGateError("CURRENT_CHANGED_WHILE_BINDING_BASELINE")
    return result


def check_baseline(pointers: dict[str, Path], binding: dict) -> None:
    if binding.get("schema") != "qfq_expected_current_v1" or baseline_binding(pointers) != binding:
        raise QfqGateError("EXPECTED_OLD_CURRENT_OR_TARGET_HASH_CONFLICT")


def publish_pair(pointers: dict[str, Path], candidates: dict[str, Path], expected: dict[str, bytes], journal: Path,
                 expected_baseline: dict | None = None) -> None:
    """Same original paired publication, durable backups and bounded rollback.

    Two filesystem files cannot be atomically replaced for uncooperating readers.
    The journal preserves that limitation and permits crash recovery by owner.
    """
    if expected_baseline is not None:
        check_baseline(pointers, expected_baseline)
    for role, pointer in pointers.items():
        if pointer.read_bytes() != expected[role]:
            raise QfqGateError(f"CURRENT_CHANGED_DURING_BUILD:{role}")
    record = dict(status="PREPARED", pointers={r: str(p) for r, p in pointers.items()},
                  before_base64={r: base64.b64encode(b).decode() for r, b in expected.items()},
                  after={r: str(p) + "\n" for r, p in candidates.items()})
    _json(journal, record)
    try:
        for role in ("selector", "backtest"):
            _write(pointers[role], record["after"][role].encode())
        for role, pointer in pointers.items():
            if pointer.read_bytes() != record["after"][role].encode():
                raise QfqGateError(f"POINTER_READBACK_FAILED:{role}")
        _json(journal, {**record, "status": "COMMITTED"})
    except BaseException:
        for role, pointer in pointers.items():
            # Do not overwrite a third party's intervening publication.
            now = pointer.read_bytes()
            if now not in (expected[role], record["after"][role].encode()):
                raise QfqGateError(f"ROLLBACK_CONCURRENT_POINTER_CONFLICT:{role}")
            _write(pointer, expected[role])
        _json(journal, {**record, "status": "ROLLED_BACK"})
        raise


def recover_pair(journal: Path, pointers: dict[str, Path]) -> None:
    if not journal.is_file():
        return
    record = json.loads(journal.read_text())
    if record.get("status") != "PREPARED":
        return
    if record.get("pointers") != {r: str(p) for r, p in pointers.items()}:
        raise QfqGateError("RECOVERY_POINTER_SCOPE_CONFLICT")
    for role, pointer in pointers.items():
        before = base64.b64decode(record["before_base64"][role])
        if pointer.read_bytes() not in (before, record["after"][role].encode()):
            raise QfqGateError(f"RECOVERY_CONCURRENT_POINTER_CONFLICT:{role}")
    for role, pointer in pointers.items():
        _write(pointer, base64.b64decode(record["before_base64"][role]))
    _json(journal, {**record, "status": "ROLLED_BACK_AFTER_INTERRUPTION"})


def verify_display_oracle(oracle: dict, output: Path, identity: dict, target: int) -> None:
    """Independent displayed precision gate, never a tolerance/offset fit."""
    if oracle.get("asof_date") != target or oracle.get("input_sha256") != identity["input_sha256"]:
        raise QfqGateError("FUTU_ORACLE_ASOF_OR_INPUT_MISMATCH")
    rows = oracle.get("rows", [])
    if not oracle.get("observed_at") or not oracle.get("source_files"):
        raise QfqGateError("FUTU_ORACLE_PROVENANCE_MISSING")
    for ref in oracle["source_files"]:
        _source(ref, owner="Futu independent oracle")
    if {r.get("ts_code") for r in rows} != {"002612.SZ", "001283.SZ"}:
        raise QfqGateError("FUTU_ORACLE_TWO_SYMBOL_COVERAGE_MISSING")
    for code in ("002612.SZ", "001283.SZ"):
        dates = oracle.get("required_dates", {}).get(code, [])
        actual = [r["trade_date"] for r in rows if r["ts_code"] == code]
        if target not in dates or len(set(dates)) < 2 or set(actual) != set(dates) or len(actual) != len(set(actual)):
            raise QfqGateError(f"FUTU_ORACLE_RECENT_SIGNAL_DATES_MISSING:{code}")
    for row in rows:
        date_type = pq.ParquetFile(output).schema_arrow.field("trade_date").type
        date = str(row["trade_date"]) if pa.types.is_string(date_type) or pa.types.is_large_string(date_type) else int(row["trade_date"])
        frame = pq.read_table(output, filters=[("ts_code", "=", row["ts_code"]), ("trade_date", "=", date)]).to_pandas()
        if len(frame) != 1:
            raise QfqGateError(f"FUTU_ORACLE_KEY_MISSING:{row['ts_code']}:{row['trade_date']}")
        for column in ("BBI", "zge_white_line", "zge_yellow_line", "J"):
            if format(float(frame.iloc[0][column]), ".3f") != str(row[column]):
                raise QfqGateError(f"PROVIDER_CONVENTION_CONFLICT:{row['ts_code']}:{row['trade_date']}:{column}")
        for column in ("B1", "B2", "B3"):
            if int(frame.iloc[0][column]) != row[column]:
                raise QfqGateError(f"FUTU_FORMULA_SIGNAL_CONFLICT:{row['ts_code']}:{column}")


def _code_binding(identity: dict) -> dict:
    return {key: identity[key] for key in ("driver_sha256", "formula_sha256", "adapter_sha256", "input_adapter_sha256", "factor_cache_sha256", "tdx_adapter_sha256", "user_formula_sha256", "field_contract_sha256")}


def verify_release_gate(root: Path, output: Path, identity: dict, target: int, convention: str) -> None:
    oracle_path = root / "qfq_futu_oracle.json"
    if oracle_path.is_file():
        oracle = json.loads(oracle_path.read_text())
        if oracle.get("asof_date") == target:
            verify_display_oracle(oracle, output, identity, target)
            return
    acceptance_path = root / "qfq_convention_acceptance.json"
    if acceptance_path.is_file():
        accepted = json.loads(acceptance_path.read_text())
        if (accepted.get("status") == "PASS" and accepted.get("reviewer_id")
                and accepted.get("code_binding") == _code_binding(identity)
                and accepted.get("convention") == convention and isinstance(accepted.get("initial_asof_date"), int)
                and target > accepted["initial_asof_date"]):
            receipt_path = _source(accepted["initial_oracle_receipt"], owner="independent convention acceptance")
            receipt = json.loads(receipt_path.read_text())
            if (receipt.get("status") == "PASS_FUTU_DISPLAY_ORACLE" and receipt.get("asof_date") == accepted["initial_asof_date"]
                    and receipt.get("code_binding") == _code_binding(identity)):
                return
    raise QfqGateError(f"FUTU_DISPLAY_ORACLE_MISSING_OR_CONVENTION_NOT_ACCEPTED:{oracle_path}:{acceptance_path}")



def accepted_history_retention(pointers: dict[str, Path]) -> dict | None:
    """The accepted dual-role generation carries the next daily source binding."""
    bindings = [panel_contract(Path(p.read_text(encoding="utf-8-sig").strip())).get("history_retention_binding")
                for p in pointers.values()]
    if not any(bindings):
        return None
    if not all(bindings) or any(binding != bindings[0] for binding in bindings):
        raise QfqGateError("DAILY_HISTORY_DUAL_ROLE_BINDING_CONFLICT")
    value = bindings[0]
    for ref in [value["source_config"], value["source_policy"], *value["archive_refs"], *value["accepted_evidence"]]:
        _source(ref, owner="accepted daily history retention")
    return value


TAIL_DELTA_ASOF_FIELDS = frozenset({
    "user_v1_hold_yesterday_keyline_display_asof", "user_v1_break_yesterday_keyline_display_asof",
    "user_v1_sell_signal_display_asof",
})


def _native_tail_extension(before: dict, after: dict, dates: list[int], code: str) -> None:
    """A composite keeps original native bytes, including archive conflicts."""
    if (before.get("name"), before.get("kind")) != ("native", "day_bytes") or (after.get("name"), after.get("kind")) != ("native", "day_bytes"):
        raise QfqGateError("TAIL_DELTA_NATIVE_SOURCE_KIND:" + code)
    old = _source(before, owner="delta original native " + code).read_bytes()
    new = _source(after, owner="delta composed native " + code).read_bytes()
    if not old or len(old) % 32 or len(new) % 32 or not new.startswith(old):
        raise QfqGateError("TAIL_DELTA_OLD_NATIVE_BYTES_CHANGED:" + code)
    old_dates = np.frombuffer(old, dtype=np.dtype([("date", "<u4"), ("_", "V28")]))["date"].astype(int).tolist()
    added = np.frombuffer(new[len(old):], dtype=np.dtype([("date", "<u4"), ("_", "V28")]))["date"].astype(int).tolist()
    if (added != dates or set(added) & set(old_dates) or not dates or min(dates) <= max(old_dates)):
        raise QfqGateError("TAIL_DELTA_NATIVE_NEW_KEYS_CHANGED:" + code)


def _tail_selected_raw_rows(refs: list[dict], target: int) -> dict[int, bytes]:
    """Select exactly the original archive-first whole raw32 rows, before decode."""
    selected = {}
    for role in ("native", "archive"):
        matching = [ref for ref in refs if ref.get("source_role") == role]
        if len(matching) > 1:
            raise QfqGateError("TAIL_DELTA_DUPLICATE_SOURCE_ROLE")
        for ref in matching:
            payload = _source(ref, owner="tail reviewed complete source").read_bytes()
            if not payload or len(payload) % 32:
                raise QfqGateError("TAIL_DELTA_RAW_RECORD_BOUNDARY")
            dates = np.frombuffer(payload, dtype=np.dtype([("date", "<u4"), ("_", "V28")]))["date"].astype(int).tolist()
            if dates != sorted(set(dates)) or min(dates) <= 19000101:
                raise QfqGateError("TAIL_DELTA_RAW_DATE_KEYS_INVALID")
            selected.update({date: payload[index*32:(index+1)*32]
                             for index, date in enumerate(dates) if date <= target})
    return selected


def _tail_selected_bytes_sha(refs: list[dict], target: int) -> str:
    selected = _tail_selected_raw_rows(refs, target)
    return hashlib.sha256(b"".join(selected[date] for date in sorted(selected))).hexdigest()


# Controller-approved scope, not authority inferred from a self-described
# receipt. These immutable metadata digests authorize only this batch/old8.
TAIL_BATCH_V2_SOURCE_BINDING_SHA = "aec0ce66a1431fb3b23f44b34f7d52717e0823f4742893dc495231f8e6a3b5aa"
TAIL_BATCH_V2_ARCHIVE_ADDITIONS_SHA = "f8c8c796858c2167b3a1fac2daa4fd54149de542419aa1bc121e814aeea036ee"
TAIL_SEED_RESTORATION_PLAN_SHA = "a42060751e10665b1613d20e158890b3dd4632632c3f1a6be16e88a9ae5ce759"
TAIL_ARCHIVE_SEED_GAP_PLAN_SHA = "1860fa34ea80fd64a9c6797bdb3356c03f2b16632801baa5a5fd9a95bd1ca0ab"
TAIL_ARCHIVE_SEED_GAP_RESULT_SHA = "616d17a2a5d7a461eef9b898d5ba8f35e363f13fba04ad705e3bdf0f5ddae9d2"
TAIL_COHERENT_ADOPTED_SNAPSHOT_SHA = "43f0f752ced849225da4ab49b0ac3c5026ff458ab8fad403a68f7be6d1844301"
TAIL_COHERENT_SOURCE_POLICY_SHA = "80d8637e0a77bc9e3cddcec257faad92afb8de1237941984914421f43bd22977"
TAIL_COHERENT_REVIEW_INDEX_SHA = "a1e7946ee06c9d41c9c56485446e165b104e4c2be8b3c8d8f1da301baee023b6"
TAIL_COHERENT_ROOT_PINS = {
    "300533.SZ": "087ec6210111c1e0caf28635017edfbeac266df5a6f1afbb2821a89ebb892b0d",
    "300573.SZ": "087ec6210111c1e0caf28635017edfbeac266df5a6f1afbb2821a89ebb892b0d",
    **{code: "e3e2103a15e91ae4e657fa56f6c7a1f8ce2ada794ca8230c1577c2c4d92b99bf"
       for code in ("301191.SZ", "301283.SZ", "301319.SZ", "301550.SZ", "301631.SZ")},
    "688489.SH": "f9b44ee53631be195bf6f58643901f5315fd3a0f0daab44a6f08584a69b01819",
}
TAIL_688110_GAP_PLAN_SHA = "662d3b8f164f4c729088acc52e5e6db7c5c32c486bafeb4a5b2a2a8b04aaa503"
TAIL_688110_GAP_RESULT_SHA = "7a65fccf61903197c9726920eaecd99f4b7eb4a7db9e998197e1750e54cbb792"
TAIL_688110_GAP_ROOT_SHA = "fa38536f2a8acd2580c6dbcef0cec5f742991d3df1949bd8e02349142533ccce"
TAIL_688110_GAP_REVIEW_SHA = "c5f543c65ff37b0840cbe63e7cb7851b777c42a2cda7065c2567aadd31d81683"


def _tail_archive_seed_gap_scope(value: dict, observed: dict) -> dict:
    """Bind only the independently reviewed R28 002961 physical archive gap."""
    ref = value.get("archive_seed_gap_restoration")
    if ref is None:
        return {}
    review = json.loads(_source(ref, owner="archive seed gap independent review").read_text())
    plan_ref, result_ref = review.get("plan", {}), review.get("canary_result", {})
    if (plan_ref.get("sha256") != TAIL_ARCHIVE_SEED_GAP_PLAN_SHA
            or result_ref.get("sha256") != TAIL_ARCHIVE_SEED_GAP_RESULT_SHA):
        raise QfqGateError("TAIL_ARCHIVE_GAP_APPROVED_ARTIFACTS_UNBOUND")
    plan = json.loads(_source(plan_ref, owner="exact 002961 archive gap plan").read_text())
    result = json.loads(_source(result_ref, owner="actual 002961 archive gap canary").read_text())
    if (review.get("schema") != "qfq_archive_seed_gap_restoration_review_v1"
            or review.get("verdict") != "REVIEWED/PASS_EXACT_002961_ARCHIVE_SEED_GAP"
            or not review.get("reviewer_id") or review["reviewer_id"] in {
                "/root", "/root/local_panel_completion_main", "/root/local_panel_completion_writer"}
            or review.get("asof_date") != 20261023 or review.get("network_requests") != 0
            or review.get("research_only") is not True
            or any(review.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or plan.get("schema") != "R28_002961_EXACT_ARCHIVE_GAP_PLAN" or plan.get("code") != "002961.SZ"
            or "002961.SZ" not in observed
            or plan.get("original_native", {}).get("sha256") != observed["002961.SZ"]["native"]["sha256"]
            or result.get("schema") != "R28_002961_ORIGINAL_ARCHIVE_GAP_CANARY_RESULT"
            or result.get("ts_code") != "002961.SZ" or result.get("gap_plan") != plan_ref
            or result.get("physical_archive_dates") != plan.get("physical_archive_dates")
            or result.get("added_dates") != [20261020, 20261021, 20261022, 20261023]
            or result.get("physical_archive_rows") != 13 or result.get("physical_provider_rows") != 4
            or any(result.get(k) is not True for k in ("old_observed_native_prefix_unchanged",
                "old_native_prefix_unchanged", "old_selected_raw32_unchanged", "full_seed_gate_passed",
                "field_signature_gate_passed", "returned_continuity_gate_passed"))
            or any(result.get(k) is not False for k in ("canonical_modified", "default_pointer_modified", "admission_allowed"))):
        raise QfqGateError("TAIL_ARCHIVE_GAP_REVIEW_OR_SCOPE_CHANGED")
    return dict(code="002961.SZ", review_ref=ref, plan_ref=plan_ref, result_ref=result_ref,
                plan=plan, result=result)


def _tail_archive_gap_native_binding(context: dict, binding: dict, before_item: dict,
                                     retained: dict) -> dict:
    """Prove observed bytes + exact original archive rows, without relabelling."""
    plan, result = context["plan"], context["result"]
    original, restored = binding.get("original_native_before", {}), binding["native_before"]
    if (context["review_ref"] not in retained.get("accepted_evidence", [])
            or original != result.get("original_native_before") or restored != result.get("native_before")
            or original.get("sha256") != plan["original_native"]["sha256"]):
        raise QfqGateError("TAIL_ARCHIVE_GAP_PHYSICAL_BINDING_CHANGED")
    old = _source(original, owner="observed 002961 native seed").read_bytes()
    new = _source(restored, owner="archive-restored 002961 seed").read_bytes()
    archives = [r for r in before_item["raw_files"] if r.get("source_role") == "archive"]
    if len(archives) != 1 or archives[0].get("sha256") != plan["archive_payload"]["sha256"]:
        raise QfqGateError("TAIL_ARCHIVE_GAP_ARCHIVE_CHANGED")
    archive = _source(archives[0], owner="accepted 002961 whole archive").read_bytes()
    rows, dates = plan.get("rows", []), plan.get("physical_archive_dates", [])
    start, stop = plan.get("archive_start_row_index"), plan.get("archive_stop_row_index_exclusive")
    if (plan.get("record_bytes") != 32 or not old or len(old) % 32 or len(archive) % 32
            or type(start) is not int or type(stop) is not int or start < 1 or stop - start != 13
            or stop * 32 > len(archive) or len(rows) != 13 or len(dates) != 13
            or dates != sorted(set(dates)) or dates[0] <= 20260922 or dates[-1] != 20261019
            or plan.get("native_cutoff") != 20260922 or plan.get("archive_cutoff") != 20261019
            or int.from_bytes(old[-32:-28], "little") != 20260922
            or any(row.get("trade_date") != dates[i] or row.get("archive_row_index") != start+i
                   or row.get("archive_byte_offset") != (start+i)*32 for i, row in enumerate(rows))):
        raise QfqGateError("TAIL_ARCHIVE_GAP_RECORD_SCOPE_CHANGED")
    gap = archive[start*32:stop*32]
    if (hashlib.sha256(gap).hexdigest() != plan.get("archive_gap_bytes_sha256")
            or any(int.from_bytes(gap[i*32:i*32+4], "little") != dates[i]
                   or hashlib.sha256(gap[i*32:(i+1)*32]).hexdigest() != row.get("raw32_sha256")
                   for i, row in enumerate(rows))
            or old + gap != new or hashlib.sha256(new).hexdigest() != plan.get("staged_seed_expected_sha256")):
        raise QfqGateError("TAIL_ARCHIVE_GAP_NOT_EXACT_APPEND_ONLY_ARCHIVE_BYTES")
    return original


def _tail_seed_restoration_scope(value: dict, observed: dict) -> dict:
    """Optional, separately reviewed original -> corrected physical seed proof."""
    ref = value.get("seed_restoration")
    if ref is None:
        return {}
    review = json.loads(_source(ref, owner="exact27 seed restoration review").read_text())
    plan_ref = review.get("plan", {})
    if plan_ref.get("sha256") != TAIL_SEED_RESTORATION_PLAN_SHA:
        raise QfqGateError("TAIL_SEED_RESTORATION_APPROVED_PLAN_UNBOUND")
    plan = json.loads(_source(plan_ref, owner="approved exact27 seed rows").read_text())
    rows = plan.get("rows", [])
    planned = {row["code"]: row for row in rows}
    reports = review.get("reports", [])
    indexed = {row["code"]: row for row in reports}
    if (review.get("schema") != "qfq_native_seed_restoration_review_v1"
            or review.get("verdict") != "REVIEWED/PASS_EXACT27_ORIGINAL_ARCHIVE_SEED_RESTORATION"
            or not review.get("reviewer_id") or review["reviewer_id"] in {
                "/root/local_panel_completion_main", "/root/local_panel_completion_writer"}
            or review.get("network_requests") != 0 or review.get("research_only") is not True
            or any(review.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or plan.get("schema") != "R27_EXACT27_ACCEPTED_ARCHIVE_ROW_RESTORATION_PLAN"
            or len(rows) != len(planned) or len(planned) != 27
            or len(reports) != len(indexed) or set(indexed) != set(planned)
            or not set(planned).issubset(observed) or "301139.SZ" in planned
            or any(row["target_native_before"]["sha256"] != observed[code]["native"]["sha256"]
                   for code, row in planned.items())):
        raise QfqGateError("TAIL_SEED_RESTORATION_REVIEW_OR_EXACT27_CHANGED")
    return dict(review_ref=ref, plan_ref=plan_ref, planned=planned, reports=indexed)


def _tail_coherent_seed_scope(value: dict, observed: dict) -> dict:
    """Only the eight independently accepted adopted-RAW physical recoveries."""
    refs = value.get("coherent_seed_restorations")
    if refs is None:
        return {}
    if not isinstance(refs, dict) or set(refs) != set(TAIL_COHERENT_ROOT_PINS) or not set(refs).issubset(observed):
        raise QfqGateError("TAIL_COHERENT_EXACT_EIGHT_SCOPE_CHANGED")
    index_ref = value.get("coherent_seed_restoration_index", {})
    if index_ref.get("sha256") != TAIL_COHERENT_REVIEW_INDEX_SHA:
        raise QfqGateError("TAIL_COHERENT_APPROVED_REVIEW_INDEX_UNBOUND")
    index = json.loads(_source(index_ref, owner="already accepted eight-case review index").read_text())
    rows = index.get("reviews", [])
    approved = {row["code"]: row["review"] for row in rows}
    if (index.get("schema") != "R28_EIGHT_INDEPENDENTLY_ACCEPTED_COHERENT_CASE_RECEIPTS_INDEX"
            or index.get("count") != len(TAIL_COHERENT_ROOT_PINS) or len(rows) != len(approved)
            or refs != approved):
        raise QfqGateError("TAIL_COHERENT_REVIEW_NOT_IN_APPROVED_INDEX")
    contexts = {}
    for code, review_ref in refs.items():
        review = json.loads(_source(review_ref, owner="coherent seed independent review " + code).read_text())
        root_ref, result_ref = review.get("root_scope", {}), review.get("canary_result", {})
        if (root_ref.get("sha256") != TAIL_COHERENT_ROOT_PINS[code]
                or review.get("schema") != "qfq_coherent_adopted_raw_seed_review_v1"
                or review.get("verdict") != "REVIEWED/PASS_EXACT_" + code[:6] + "_COHERENT_ADOPTED_RAW_SEED_STAGING"
                or review.get("code") != code or review.get("asof_date") != 20261023
                or not review.get("reviewer_id") or review["reviewer_id"] in {
                    "/root", "/root/local_panel_completion_main", "/root/local_panel_completion_writer"}
                or review.get("network_requests") != 0 or review.get("research_only") is not True
                or any(review.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise QfqGateError("TAIL_COHERENT_REVIEW_OR_ROOT_CHANGED:" + code)
        _source(root_ref, owner="approved coherent seed scope " + code)
        result = json.loads(_source(result_ref, owner="actual coherent seed canary " + code).read_text())
        if (result.get("schema") != "R28_COHERENT_ADOPTED_RAW_SEED_CANARY_RESULT" or result.get("code") != code
                or result.get("added_dates") != [20261020, 20261021, 20261022, 20261023]
                or result.get("native_appended_dates") != result["added_dates"]
                or result.get("selected_added_rows") != 4 or result.get("native_cutoff") != 20261019
                or any(result.get(k) is not True for k in ("coherent_seed_equals_adopted_whole_raw",
                    "old_selected_raw32_unchanged", "old_selected_rows_unchanged", "old_physical_bytes_preserved",
                    "original_vs_r27_vs_coherent_identities_separate", "full_seed_gate_passed",
                    "field_signature_gate_passed", "returned_continuity_gate_passed"))
                or any(result.get(k) is not False for k in ("original_physical_prefix_claimed_unchanged",
                    "canonical_modified", "default_pointer_modified", "admission_allowed"))
                or result.get("actual_network_calls") != 0
                or result.get("old_keys_lost") != 0 or result.get("old_values_changed") != 0
                or review.get("coherent_native_before") != result.get("native_before")
                or review.get("original_native_before") != result.get("original_native_before")
                or review.get("r27_native_before") != result.get("r27_native_before")
                or review.get("native_after") != result.get("native_after")
                or review.get("coherent_provenance") != result.get("coherent_seed_provenance")
                or result.get("original_response") != observed[code].get("original_MAC_response")
                or result.get("original_native_before", {}).get("sha256") != observed[code]["native"]["sha256"]
                or review.get("original_observed_native", {}).get("sha256") != observed[code]["native"]["sha256"]):
            raise QfqGateError("TAIL_COHERENT_ACTUAL_RESULT_CHANGED:" + code)
        provenance_ref, ledger_ref = review["coherent_provenance"], review["conflict_ledger"]
        provenance = json.loads(_source(provenance_ref, owner="coherent whole-row provenance " + code).read_text())
        ledger = json.loads(_source(ledger_ref, owner="preserved coherent conflict ledger " + code).read_text())
        acceptance_ref = review["independent_acceptance"]
        acceptance = json.loads(_source(acceptance_ref, owner="independent coherent actual acceptance " + code).read_text())
        expected_verdict = ("REVIEWED/PASS_EXACT_FIVE_COHERENT_ADOPTED_RAW_SEED_STAGING"
            if code in {"301191.SZ", "301283.SZ", "301319.SZ", "301550.SZ", "301631.SZ"} else review["verdict"])
        # Older accepted batch/last-case summaries do not have actual_result.
        # Their exact code/result/acceptance mapping is carried by the fixed
        # index above, not by a newly supplied caller digest or invented field.
        if (acceptance.get("verdict") != expected_verdict
                or acceptance.get("reviewer_id") != review["reviewer_id"]
                or ("code" in acceptance and acceptance["code"] != code)
                or ("actual_result" in acceptance and acceptance["actual_result"] != result_ref)
                or acceptance.get("research_only") is not True
                or any(acceptance.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise QfqGateError("TAIL_COHERENT_INDEPENDENT_ACCEPTANCE_CONFLICT:" + code)
        if (not isinstance(ledger.get("before"), list) or not ledger["before"] or ledger.get("after") != []
                or review.get("conflicts_before") != len(ledger["before"]) or review.get("conflicts_after") != 0
                or any(row.get("code") != code for row in ledger["before"])):
            raise QfqGateError("TAIL_COHERENT_CONFLICT_ACCOUNTING_CHANGED:" + code)
        closure = [index_ref, review_ref, root_ref, result_ref, provenance_ref, ledger_ref, acceptance_ref,
                   result["original_native_before"], result["r27_native_before"], result["native_before"]]
        contexts[code] = dict(review_ref=review_ref, review=review, result=result, provenance=provenance,
                              acceptance_ref=acceptance_ref, closure_refs=closure)
    return contexts


def _tail_coherent_native_binding(scope: dict, code: str, binding: dict,
                                  before_item: dict, retained: dict) -> dict:
    context = scope["coherent_seeds"][code]
    review, result, provenance = context["review"], context["result"], context["provenance"]
    original, intermediate, coherent = (binding.get("original_native_before", {}),
        binding.get("r27_native_before", {}), binding["native_before"])
    if (any(ref not in retained.get("accepted_evidence", [])
            for ref in (context["review_ref"], context["acceptance_ref"]))
            or original != result["original_native_before"] or intermediate != result["r27_native_before"]
            or coherent != result["native_before"] or binding["native_after"] != result["native_after"]
            or provenance.get("schema") != "R28_WHOLE_ADOPTED_RAW_PHYSICAL_SEED_PROVENANCE"
            or provenance.get("code") != code or provenance.get("original_rollback") != original
            or provenance.get("r27_rollback") != intermediate or provenance.get("coherent_seed") != coherent
            or provenance.get("original_observed_native", {}).get("sha256") != original.get("sha256")
            or provenance.get("r27_physical_native", {}).get("sha256") != intermediate.get("sha256")
            or provenance.get("adopted_raw_refs") != before_item["raw_files"]
            or provenance.get("old_selected_raw_unchanged") is not True
            or provenance.get("original_physical_bytes_preserved") is not True
            or provenance.get("no_fourbar_patch") is not True or provenance.get("price_or_volume_conversion") != "NONE"):
        raise QfqGateError("TAIL_COHERENT_PHYSICAL_CHAIN_CHANGED:" + code)
    old = _source(original, owner="preserved original physical seed " + code).read_bytes()
    middle = _source(intermediate, owner="preserved R27 physical seed " + code).read_bytes()
    new = _source(coherent, owner="complete adopted RAW coherent seed " + code).read_bytes()
    restorations = scope.get("restorations", {})
    if code in restorations.get("planned", {}):
        report = restorations["reports"][code]
        legacy = dict(scope, coherent_seeds={})
        legacy_binding = dict(original_native_before=report["original_native_before"],
                              native_before=report["restored_native_before"])
        verified = _tail_original_native_binding(legacy, code, legacy_binding, before_item, retained)
        if verified["sha256"] != original["sha256"] or report["restored_native_before"]["sha256"] != intermediate["sha256"]:
            raise QfqGateError("TAIL_COHERENT_R27_BRIDGE_CHANGED:" + code)
    elif old != middle:
        raise QfqGateError("TAIL_COHERENT_UNAPPROVED_INTERMEDIATE_CHANGE:" + code)
    snapshot_ref, policy_ref = provenance.get("adopted_snapshot", {}), provenance.get("source_policy", {})
    if (snapshot_ref.get("sha256") != TAIL_COHERENT_ADOPTED_SNAPSHOT_SHA
            or policy_ref.get("sha256") != TAIL_COHERENT_SOURCE_POLICY_SHA):
        raise QfqGateError("TAIL_COHERENT_ADOPTED_AUTHORITY_UNBOUND:" + code)
    snapshot = json.loads(_source(snapshot_ref, owner="already adopted RAW snapshot").read_text())
    policy = json.loads(_source(policy_ref, owner="unchanged whole-row source policy").read_text())
    if (snapshot["symbols"][code]["raw_files"] != before_item["raw_files"]
            or policy.get("name") != "ARCHIVE_PRIMARY_NATIVE_MISSING_AND_TAIL_V2"
            or policy.get("selection_unit") != "COMPLETE_SOURCE_BAR" or policy.get("price_or_volume_conversion") != "NONE"):
        raise QfqGateError("TAIL_COHERENT_RAW_POLICY_CHANGED:" + code)
    selected = _tail_selected_raw_rows(before_item["raw_files"], 20261023)
    expected = b"".join(selected[day] for day in sorted(selected))
    if (not old or len(old) % 32 or not middle or len(middle) % 32 or not new or new != expected
            or len(new) != 32 * result.get("coherent_seed_rows", -1)
            or _source(result["selected_before"], owner="reviewed old selected RAW " + code).read_bytes() != new):
        raise QfqGateError("TAIL_COHERENT_NOT_COMPLETE_ADOPTED_RAW:" + code)
    # These immutable dependencies remain part of the source input after admission.
    context["closure_refs"].extend(ref for ref in (snapshot_ref, policy_ref) if ref not in context["closure_refs"])
    return original


def _tail_688110_gap_scope(value: dict, observed: dict) -> dict:
    ref = value.get("additional_archive_seed_gap_restoration")
    if ref is None:
        return {}
    if ref.get("sha256") != TAIL_688110_GAP_REVIEW_SHA:
        raise QfqGateError("TAIL_688110_GAP_APPROVED_REVIEW_UNBOUND")
    review = json.loads(_source(ref, owner="688110 independent archive gap review").read_text())
    plan_ref, result_ref, root_ref = review.get("plan", {}), review.get("canary_result", {}), review.get("root_scope", {})
    if (plan_ref.get("sha256") != TAIL_688110_GAP_PLAN_SHA or result_ref.get("sha256") != TAIL_688110_GAP_RESULT_SHA
            or root_ref.get("sha256") != TAIL_688110_GAP_ROOT_SHA
            or review.get("schema") != "qfq_archive_seed_gap_restoration_review_v1"
            or review.get("verdict") != "REVIEWED/PASS_EXACT_688110_ARCHIVE_SEED_GAP"
            or review.get("code") != "688110.SH" or "688110.SH" not in observed
            or review.get("asof_date") != 20261023 or not review.get("reviewer_id")
            or review["reviewer_id"] in {"/root", "/root/local_panel_completion_main", "/root/local_panel_completion_writer"}
            or review.get("network_requests") != 0 or review.get("research_only") is not True
            or any(review.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise QfqGateError("TAIL_688110_GAP_REVIEW_OR_ROOT_CHANGED")
    _source(root_ref, owner="approved exact 688110 gap scope")
    plan = json.loads(_source(plan_ref, owner="exact six archive whole rows").read_text())
    result = json.loads(_source(result_ref, owner="actual 688110 archive gap canary").read_text())
    acceptance_ref = review["independent_acceptance"]
    acceptance = json.loads(_source(acceptance_ref, owner="independent 688110 actual acceptance").read_text())
    if (acceptance.get("verdict") != review["verdict"] or acceptance.get("reviewer_id") != review["reviewer_id"]
            or ("code" in acceptance and acceptance["code"] != "688110.SH")
            or ("actual_result" in acceptance and acceptance["actual_result"] != result_ref)
            or acceptance.get("research_only") is not True
            or any(acceptance.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise QfqGateError("TAIL_688110_GAP_INDEPENDENT_ACCEPTANCE_CONFLICT")
    if (plan.get("schema") != "R28_688110_EXACT_ARCHIVE_GAP_PLAN" or plan.get("code") != "688110.SH"
            or plan.get("original_native", {}).get("sha256") != observed["688110.SH"]["native"]["sha256"]
            or result.get("schema") != "R28_688110_ORIGINAL_ARCHIVE_GAP_CANARY_RESULT"
            or result.get("ts_code") != "688110.SH" or result.get("gap_plan") != plan_ref
            or result.get("original_response") != observed["688110.SH"].get("original_MAC_response")
            or result.get("physical_archive_dates") != plan.get("physical_archive_dates")
            or result.get("physical_archive_rows") != 6 or result.get("physical_provider_rows") != 4
            or result.get("added_dates") != [20261020, 20261021, 20261022, 20261023]
            or any(result.get(k) is not True for k in ("old_observed_native_prefix_unchanged", "old_native_prefix_unchanged",
                "old_selected_raw32_unchanged", "full_seed_gate_passed", "field_signature_gate_passed", "returned_continuity_gate_passed"))
            or any(result.get(k) is not False for k in ("canonical_modified", "default_pointer_modified", "admission_allowed"))):
        raise QfqGateError("TAIL_688110_GAP_ACTUAL_SCOPE_CHANGED")
    return dict(code="688110.SH", review_ref=ref, plan_ref=plan_ref, result_ref=result_ref, plan=plan, result=result,
                acceptance_ref=acceptance_ref, closure_refs=[ref, root_ref, plan_ref, result_ref, acceptance_ref])


def _tail_688110_gap_native_binding(context: dict, binding: dict, before_item: dict, retained: dict) -> dict:
    plan, result = context["plan"], context["result"]
    original, restored = binding.get("original_native_before", {}), binding["native_before"]
    if (any(ref not in retained.get("accepted_evidence", []) for ref in (context["review_ref"], context["acceptance_ref"]))
            or original != result.get("original_native_before") or restored != result.get("native_before")
            or original.get("sha256") != plan["original_native"]["sha256"]):
        raise QfqGateError("TAIL_688110_GAP_PHYSICAL_BINDING_CHANGED")
    old = _source(original, owner="original 688110 physical seed").read_bytes()
    new = _source(restored, owner="six-row restored 688110 seed").read_bytes()
    archives = [ref for ref in before_item["raw_files"] if ref.get("source_role") == "archive"]
    if len(archives) != 1 or archives[0].get("sha256") != plan["archive_payload"]["sha256"]:
        raise QfqGateError("TAIL_688110_GAP_ARCHIVE_CHANGED")
    archive = _source(archives[0], owner="already accepted 688110 whole archive").read_bytes()
    dates = [20261012, 20261013, 20261014, 20261015, 20261016, 20261019]
    rows = plan.get("rows", [])
    if (plan.get("record_bytes") != 32 or not old or len(old) % 32 or len(archive) % 32
            or plan.get("native_cutoff") != 20261009 or plan.get("archive_cutoff") != 20261019
            or int.from_bytes(old[-32:-28], "little") != 20261009
            or plan.get("archive_start_row_index") != 1165 or plan.get("archive_stop_row_index_exclusive") != 1171
            or len(archive) != 1171 * 32 or plan.get("physical_archive_dates") != dates or len(rows) != 6
            or any(row.get("trade_date") != dates[i] or row.get("archive_row_index") != 1165 + i
                   or row.get("archive_byte_offset") != (1165 + i) * 32 for i, row in enumerate(rows))):
        raise QfqGateError("TAIL_688110_GAP_EXACT_RECORD_SCOPE_CHANGED")
    gap = archive[1165 * 32:1171 * 32]
    if (hashlib.sha256(gap).hexdigest() != plan.get("archive_gap_bytes_sha256")
            or any(int.from_bytes(gap[i*32:i*32+4], "little") != dates[i]
                   or hashlib.sha256(gap[i*32:(i+1)*32]).hexdigest() != row.get("raw32_sha256") for i, row in enumerate(rows))
            or old + gap != new or hashlib.sha256(new).hexdigest() != plan.get("staged_seed_expected_sha256")):
        raise QfqGateError("TAIL_688110_GAP_NOT_EXACT_APPEND_ONLY_WHOLE_ROWS")
    return original


def _tail_original_native_binding(scope: dict, code: str, binding: dict,
                                  before_item: dict, retained: dict) -> dict:
    """Verify whole-row restoration; never relabel the frozen observed seed."""
    if code in scope.get("coherent_seeds", {}):
        return _tail_coherent_native_binding(scope, code, binding, before_item, retained)
    extension = scope.get("archive_seed_gap_extension", {})
    if extension and code == extension["code"]:
        return _tail_688110_gap_native_binding(extension, binding, before_item, retained)
    gap = scope.get("archive_seed_gaps", {})
    if gap and code == gap["code"]:
        return _tail_archive_gap_native_binding(gap, binding, before_item, retained)
    context = scope.get("restorations", {})
    if code not in context.get("planned", {}):
        if "original_native_before" in binding:
            raise QfqGateError("TAIL_SEED_RESTORATION_OUTSIDE_EXACT27:" + code)
        return binding["native_before"]
    plan, report = context["planned"][code], context["reports"][code]
    original, restored = binding.get("original_native_before", {}), binding["native_before"]
    if (context["review_ref"] not in retained.get("accepted_evidence", [])
            or report.get("original_native_before") != original
            or report.get("restored_native_before") != restored
            or original.get("sha256") != plan["target_native_before"]["sha256"]
            or report.get("trade_date") != 20260722 or plan.get("trade_date") != 20260722
            or plan.get("record_bytes") != 32):
        raise QfqGateError("TAIL_SEED_RESTORATION_PHYSICAL_BINDING_CHANGED:" + code)
    old = _source(original, owner="original observed seed " + code).read_bytes()
    new = _source(restored, owner="corrected physical seed " + code).read_bytes()
    archives = [ref for ref in before_item["raw_files"] if ref.get("source_role") == "archive"]
    if len(archives) != 1 or archives[0].get("sha256") != plan["archive_payload"]["sha256"]:
        raise QfqGateError("TAIL_SEED_RESTORATION_ARCHIVE_CHANGED:" + code)
    archive = _source(archives[0], owner="already selected archive winner " + code).read_bytes()
    offset, archive_offset = plan["native_byte_offset"], plan["archive_byte_offset"]
    if (type(offset) is not int or type(archive_offset) is not int or min(offset, archive_offset) < 0
            or offset % 32 or archive_offset % 32 or offset + 32 > len(old)
            or archive_offset + 32 > len(archive) or not old or len(old) % 32 or len(new) != len(old)):
        raise QfqGateError("TAIL_SEED_RESTORATION_RECORD_BOUNDARY_CHANGED:" + code)
    prior, winner = old[offset:offset + 32], archive[archive_offset:archive_offset + 32]
    if (hashlib.sha256(prior).hexdigest() != plan["native_original_row_sha256"]
            or hashlib.sha256(winner).hexdigest() != plan["archive_whole_row_sha256"]
            or any(int.from_bytes(row[:4], "little") != 20260722 for row in (prior, winner))
            or prior == winner or old[:offset] + winner + old[offset + 32:] != new):
        raise QfqGateError("TAIL_SEED_RESTORATION_NOT_EXACT_ARCHIVE_WHOLE_ROW:" + code)
    return original


def _tail_batch_v2_scope(value: dict, target: int) -> dict:
    binding_ref, addition_ref = value.get("source_binding", {}), value.get("accepted_archive_additions", {})
    if (binding_ref.get("sha256") != TAIL_BATCH_V2_SOURCE_BINDING_SHA
            or addition_ref.get("sha256") != TAIL_BATCH_V2_ARCHIVE_ADDITIONS_SHA):
        raise QfqGateError("TAIL_BATCH_V2_APPROVED_SCOPE_UNBOUND")
    binding = json.loads(_source(binding_ref, owner="approved exact tail batch").read_text())
    addition = json.loads(_source(addition_ref, owner="already accepted archive additions").read_text())
    rows = binding.get("source_binding_rows", [])
    indexed = {r["ts_code"]: r for r in rows}
    keys = binding.get("frozen_keys", [])
    codes = value["codes"]
    if (binding.get("schema") != "R19_FROZEN_SOURCE_KEYS_37_148"
            or binding.get("expected_stock_count") != 37 or binding.get("expected_key_count") != 148
            or len(rows) != len(indexed) or len(indexed) != 37 or set(codes) != set(indexed)
            or len(keys) != 148 or len({tuple(k) for k in keys}) != 148
            or sorted(keys) != sorted([[c, d] for c in codes for d in codes[c].get("added_dates", [])])
            or addition.get("schema") != "qfq_archive_only_history_additions_v1"
            or addition.get("asof_date") != target or len(addition.get("codes", {})) != 8
            or not set(addition["codes"]).issubset(codes)):
        raise QfqGateError("TAIL_BATCH_V2_EXACT_CODES_OR_KEYS_CHANGED")
    for code, row in indexed.items():
        if row.get("target_date") != target or row.get("expected_strict_new_keys") != [[code, d] for d in codes[code].get("added_dates", [])]:
            raise QfqGateError("TAIL_BATCH_V2_SOURCE_TARGET_OR_KEYS_CHANGED:" + code)
    review_ref = value["independent_raw_review"]
    review = json.loads(_source(review_ref, owner="actual independent batch raw review").read_text())
    reports = review.get("reports", [])
    approved = {r["code"]: r for r in reports}
    if (review.get("schema") != "qfq_native_tail_recovery_review_v2"
            or review.get("verdict") != "REVIEWED/PASS_EXACT_MAC_NATIVE_TAIL_BATCH_V2"
            or not review.get("reviewer_id") or review["reviewer_id"] in {
                "/root/local_panel_completion_writer", "/root/security_master_normalization_sol", "/root/current_mac_control"}
            or review.get("asof_date") != target or review.get("source_binding") != binding_ref
            or review.get("network_requests") != 0 or review.get("research_only") is not True
            or any(review.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))
            or len(reports) != len(approved) or set(approved) != set(codes)):
        raise QfqGateError("TAIL_BATCH_V2_ACTUAL_RAW_REVIEW_NOT_ACCEPTED")
    return dict(rows=indexed, archive_only=set(addition["codes"]), reports=approved, review_ref=review_ref,
                restorations=_tail_seed_restoration_scope(value, indexed),
                archive_seed_gaps=_tail_archive_seed_gap_scope(value, indexed),
                coherent_seeds=_tail_coherent_seed_scope(value, indexed),
                archive_seed_gap_extension=_tail_688110_gap_scope(value, indexed))


def _tail_batch_v2_code(scope: dict, code: str, binding: dict, before: dict, after: dict,
                        before_item: dict, after_item: dict, retained: dict, target: int) -> None:
    dates = binding["added_dates"]
    report, observed = scope["reports"][code], scope["rows"][code]
    before_ref, after_ref = binding["native_before"], binding["native_after"]
    original_ref = _tail_original_native_binding(scope, code, binding, before_item, retained)
    physical = binding["native_appended_dates"]
    if (scope["review_ref"] not in retained.get("accepted_evidence", [])
            or binding.get("independent_review") != scope["review_ref"]
            or original_ref.get("sha256") != observed["native"]["sha256"]
            or report.get("native_before") != before_ref or report.get("native_after") != after_ref
            or report.get("native_appended_dates") != physical or report.get("added_dates") != dates
            or report.get("provider_response") != observed["original_MAC_response"]
            or report.get("provider_query_started_utc") != observed["source_query_started_utc"]
            or not isinstance(physical, list) or not physical or physical != sorted(set(physical))
            or any(type(d) is not int or d > target for d in physical)
            or any(report.get(k) is not True for k in ("old_native_prefix_unchanged", "full_seed_gate_passed",
                "field_signature_gate_passed", "returned_continuity_gate_passed"))
            or report.get("old_keys_lost") != 0 or report.get("old_values_changed") != 0
            or report.get("buffer_admitted_as_full_history") is not False):
        raise QfqGateError("TAIL_BATCH_V2_PHYSICAL_OR_REVIEW_BINDING_CHANGED:" + code)
    _source(observed["original_MAC_response"], owner="reviewed original MAC response " + code)
    _native_tail_extension(dict(**before_ref, name="native", kind="day_bytes"),
                           dict(**after_ref, name="native", kind="day_bytes"), physical, code)
    old_bytes = Path(before_ref["path"]).read_bytes()
    old_last = int(np.frombuffer(old_bytes, dtype=np.dtype([("date", "<u4"), ("_", "V28")]))["date"][-1])
    if binding.get("native_cutoff") != old_last or report.get("native_cutoff") != old_last:
        raise QfqGateError("TAIL_BATCH_V2_PHYSICAL_CUTOFF_CHANGED:" + code)
    pairs = [{x["name"]: x for x in stock["sources"]} for stock in (before, after)]
    expected_before = {"archive"} if code in scope["archive_only"] else {"archive", "native"}
    if (len(pairs[0]) != len(before["sources"]) or len(pairs[1]) != len(after["sources"])
            or set(pairs[0]) != expected_before or set(pairs[1]) != {"archive", "native"}
            or pairs[0]["archive"] != pairs[1]["archive"]
            or any(pairs[1]["native"].get(k) != after_ref.get(k) for k in ("path", "sha256"))
            or pairs[1]["native"].get("kind") != "day_bytes"
            or ("native" in pairs[0] and (pairs[0]["native"].get("kind") != "day_bytes" or pairs[0]["native"].get("sha256") != original_ref.get("sha256")))):
        raise QfqGateError("TAIL_BATCH_V2_ARCHIVE_OR_NATIVE_ROLES_CHANGED:" + code)
    old_refs = {x["source_role"]: x for x in before_item["raw_files"]}
    new_refs = {x["source_role"]: x for x in after_item["raw_files"]}
    archive = pairs[0]["archive"]
    archive_bound = (old_refs.get("archive", {}).get("sha256") == archive.get("member_sha256")
                     if archive.get("kind") == "archive_member" else
                     archive.get("kind") == "day_bytes" and all(
                         old_refs.get("archive", {}).get(k) == archive.get(k) for k in ("path", "sha256")))
    if (len(old_refs) != len(before_item["raw_files"]) or len(new_refs) != len(after_item["raw_files"])
            or set(old_refs) != expected_before or set(new_refs) != {"archive", "native"}
            or old_refs["archive"] != new_refs["archive"]
            or any(new_refs["native"].get(k) != after_ref.get(k) for k in ("path", "sha256"))
            or not archive_bound
            or ("native" in old_refs and old_refs["native"].get("sha256") != original_ref.get("sha256"))):
        raise QfqGateError("TAIL_BATCH_V2_ITEM_RAW_ROLES_CHANGED:" + code)
    selected_before = _tail_selected_raw_rows(before_item["raw_files"], target)
    selected_after = _tail_selected_raw_rows(after_item["raw_files"], target)
    if (not selected_before or before_item.get("history_end_date") != max(selected_before)
            or set(selected_after) != set(selected_before) | set(dates) or set(selected_before) & set(dates)
            or any(selected_after[d] != row for d, row in selected_before.items())
            or report.get("old_selected_raw_sha256") != _tail_selected_bytes_sha(before_item["raw_files"], target)
            or report.get("staged_sha256") != _tail_selected_bytes_sha(after_item["raw_files"], target)):
        raise QfqGateError("TAIL_BATCH_V2_SELECTED_KEYS_OR_OLD_RAW_CHANGED:" + code)


def tail_delta_binding(ref: dict | None, *, snapshot: dict, pointers: dict[str, Path],
                       identity: dict, target: int, retained_history: dict | None) -> dict | None:
    """Verify a same-asof, independently accepted native-tail-only revision.

    All symbols remain in the snapshot. Unchanged active rows are an explicit
    Arrow-copy category, never disguised as inactive retained history.
    """
    if ref is None:
        return None
    value = json.loads(_source(ref, owner="tail delta contract").read_text())
    codes = value.get("codes", {})
    v2 = value.get("schema") == "qfq_native_tail_delta_v2"
    if (value.get("schema") not in {"qfq_native_tail_delta_v1", "qfq_native_tail_delta_v2"}
            or value.get("asof_date") != target
            or not isinstance(codes, dict) or not (len(codes) == 37 if v2 else 1 <= len(codes) <= 6)
            or any(not CODE.fullmatch(c) for c in codes) or not retained_history):
        raise QfqGateError("TAIL_DELTA_CONTRACT_INVALID")
    batch = _tail_batch_v2_scope(value, target) if v2 else None
    old = json.loads(_source(value["baseline_snapshot"], owner="delta baseline snapshot").read_text())
    if (old.get("asof_date") != target or set(old["symbols"]) != set(snapshot["symbols"])
            or not set(codes).issubset(old["symbols"]) or set(value.get("baseline_roles", {})) != set(pointers)):
        raise QfqGateError("TAIL_DELTA_ASOF_OR_MEMBERSHIP_CHANGED")
    original_core = _source(value["baseline_core"], owner="delta baseline computation kernel")
    if computation_kernel_sha(original_core) != computation_kernel_sha(Path(__file__)):
        raise QfqGateError("TAIL_DELTA_COMPUTATION_CHANGED")
    for role, pointer in pointers.items():
        bound = value["baseline_roles"][role]
        path = _source(bound, owner="delta baseline " + role)
        meta = panel_contract(path)
        if (path != Path(pointer.read_text(encoding="utf-8-sig").strip())
                or meta.get("generation_id") != value["baseline_generation_id"]
                or meta.get("input_sha256") != canonical_sha(old) or meta.get("asof_date") != target
                or meta.get("adapter_sha256") != sha(original_core)
                or any(meta.get(k) != v for k, v in identity.items() if k not in {"adapter_sha256", "input_sha256"})
                or not set(USER_FORMULA_SIGNAL_FIELDS).issubset(pq.ParquetFile(path).schema_arrow.names)):
            raise QfqGateError("TAIL_DELTA_BASELINE_OR_FORMULA_CHANGED:" + role)
    changed_top = {"symbols", "source_files", "revision", "observed_at", "history_extension", "history_retention_binding"}
    if ({k: v for k, v in old.items() if k not in changed_top}
            != {k: v for k, v in snapshot.items() if k not in changed_top}):
        raise QfqGateError("TAIL_DELTA_NON_RAW_SNAPSHOT_CHANGED")
    if not all(ref in snapshot["source_files"] for ref in old["source_files"]):
        raise QfqGateError("TAIL_DELTA_OLD_SOURCE_CLOSURE_LOST")
    retained = snapshot.get("history_retention_binding")
    if not isinstance(retained, dict) or snapshot.get("history_extension") is not None:
        raise QfqGateError("TAIL_DELTA_FUTURE_RETENTION_UNBOUND")
    if ({k: v for k, v in retained_history.items() if k not in {"source_config", "accepted_evidence"}}
            != {k: v for k, v in retained.items() if k not in {"source_config", "accepted_evidence"}}
            or not all(x in retained.get("accepted_evidence", []) for x in retained_history.get("accepted_evidence", []))):
        raise QfqGateError("TAIL_DELTA_SOURCE_POLICY_CHANGED")
    configs = [json.loads(_source(x["source_config"], owner="delta whole-row config").read_text())
               for x in (retained_history, retained)]
    if ({k: v for k, v in configs[0].items() if k != "stocks"}
            != {k: v for k, v in configs[1].items() if k != "stocks"}):
        raise QfqGateError("TAIL_DELTA_SOURCE_CONFIG_POLICY_CHANGED")
    stocks = [{x["code"]: x for x in c["stocks"]} for c in configs]
    if (set(stocks[0]) != set(stocks[1]) or not set(codes).issubset(stocks[0])
            or any(len(stocks[i]) != len(configs[i]["stocks"]) for i in (0, 1))):
        raise QfqGateError("TAIL_DELTA_SOURCE_MEMBERSHIP_CHANGED")
    for code, before in stocks[0].items():
        after = stocks[1][code]
        if code not in codes:
            if before != after:
                raise QfqGateError("TAIL_DELTA_THIRD_CODE_SOURCE_CHANGED:" + code)
            continue
        dates = codes[code].get("added_dates")
        if (not isinstance(dates, list) or not dates or dates != sorted(set(dates))
                or any(type(d) is not int or d > target for d in dates)):
            raise QfqGateError("TAIL_DELTA_DATE_CONTRACT_INVALID:" + code)
        if not v2:
            review = json.loads(_source(codes[code]["independent_review"], owner="tail recovery review " + code).read_text())
            if review.get("verdict") != "REVIEWED/PASS_ISOLATED_TWO_STOCK_TAIL_RECOVERY_ONLY":
                raise QfqGateError("TAIL_DELTA_RECOVERY_REVIEW_NOT_ACCEPTED:" + code)
            approved = [row for row in review.get("reports", []) if row.get("code") == code]
            if (codes[code]["independent_review"] not in retained.get("accepted_evidence", [])
                    or len(approved) != 1 or approved[0].get("added_dates") != dates
                    or approved[0].get("old_keys_lost") != 0 or approved[0].get("old_values_changed") != 0
                    or approved[0].get("old_raw32_prefix_unchanged") is not True
                    or approved[0].get("buffer_admitted_as_full_history") is not False
                    or approved[0].get("staged_sha256") != _tail_selected_bytes_sha(snapshot["symbols"][code]["raw_files"], target)):
                raise QfqGateError("TAIL_DELTA_REVIEW_CODE_KEYS_OR_COMPLETE_SOURCE_CONFLICT:" + code)
        if ({k: v for k, v in before.items() if k != "sources"}
                != {k: v for k, v in after.items() if k != "sources"}):
            raise QfqGateError("TAIL_DELTA_SOURCE_STOCK_METADATA_CHANGED:" + code)
        if v2:
            _tail_batch_v2_code(batch, code, codes[code], before, after, old["symbols"][code],
                                snapshot["symbols"][code], retained, target)
        else:
            pairs = [{x["name"]: x for x in stock["sources"]} for stock in (before, after)]
            if (len(pairs[0]) != len(before["sources"]) or len(pairs[1]) != len(after["sources"])
                    or set(pairs[0]) != set(pairs[1]) or "native" not in pairs[0]
                    or any(pairs[0][k] != pairs[1][k] for k in pairs[0] if k != "native")):
                raise QfqGateError("TAIL_DELTA_ARCHIVE_OR_SOURCE_ROLES_CHANGED:" + code)
            _native_tail_extension(pairs[0]["native"], pairs[1]["native"], dates, code)
    if not all(x in snapshot["source_files"] for x in [retained["source_config"], retained["source_policy"],
            *retained.get("accepted_evidence", [])]):
        raise QfqGateError("TAIL_DELTA_NEW_SOURCE_CLOSURE_UNBOUND")
    item_metadata = {"source_config", "accepted_evidence"}
    for code, before in old["symbols"].items():
        after = snapshot["symbols"][code]
        allowed = item_metadata | ({"raw_files", "history_end_date"} if code in codes else set())
        if ({k: v for k, v in before.items() if k not in allowed}
                != {k: v for k, v in after.items() if k not in allowed}):
            raise QfqGateError("TAIL_DELTA_EVENT_OR_THIRD_CODE_INPUT_CHANGED:" + code)
        if after.get("source_config") != retained["source_config"]:
            raise QfqGateError("TAIL_DELTA_SYMBOL_RETENTION_CONFLICT:" + code)
        if not all(x in after.get("accepted_evidence", []) for x in before.get("accepted_evidence", [])):
            raise QfqGateError("TAIL_DELTA_ACCEPTED_EVIDENCE_LOST:" + code)
        if code in codes:
            if min(codes[code]["added_dates"]) <= before["history_end_date"] or after["history_end_date"] != max(codes[code]["added_dates"]):
                raise QfqGateError("TAIL_DELTA_NOT_TAIL_ONLY:" + code)
            old_refs = {x["source_role"]: x for x in before["raw_files"]}
            new_refs = {x["source_role"]: x for x in after["raw_files"]}
            if not v2 and (set(old_refs) != set(new_refs) or len(new_refs) != len(after["raw_files"])
                    or any(old_refs[k] != new_refs[k] for k in old_refs if k != "native")
                    or any(new_refs["native"].get(k) != stocks[1][code]["sources"][[x["name"] for x in stocks[1][code]["sources"]].index("native")].get(k) for k in ("path", "sha256"))):
                raise QfqGateError("TAIL_DELTA_NATIVE_ITEM_BINDING_CHANGED:" + code)
    if v2 and not all(x in snapshot["source_files"] for x in (
            value["source_binding"], value["accepted_archive_additions"], value["independent_raw_review"])):
        raise QfqGateError("TAIL_BATCH_V2_SOURCE_CLOSURE_UNBOUND")
    if v2 and batch.get("restorations") and not all(x in snapshot["source_files"] for x in (
            batch["restorations"]["review_ref"], batch["restorations"]["plan_ref"])):
        raise QfqGateError("TAIL_SEED_RESTORATION_SOURCE_CLOSURE_UNBOUND")
    if v2 and batch.get("archive_seed_gaps") and not all(x in snapshot["source_files"] for x in (
            batch["archive_seed_gaps"]["review_ref"], batch["archive_seed_gaps"]["plan_ref"],
            batch["archive_seed_gaps"]["result_ref"])):
        raise QfqGateError("TAIL_ARCHIVE_GAP_SOURCE_CLOSURE_UNBOUND")
    if v2:
        contexts = list(batch.get("coherent_seeds", {}).values())
        if batch.get("archive_seed_gap_extension"):
            contexts.append(batch["archive_seed_gap_extension"])
        if any(ref not in snapshot["source_files"] for context in contexts for ref in context["closure_refs"]):
            raise QfqGateError("TAIL_OPTIONAL_SEED_RECOVERY_SOURCE_CLOSURE_UNBOUND")
    return {**value, "binding_ref": ref}


def tail_delta_prefix(old: pa.Table, fresh: pa.Table, dates: list[int], code: str) -> list[dict]:
    """Old prefix values stay exact; enumerate only original asof/lineage changes."""
    old_dates = [int(x) for x in old["trade_date"].to_pylist()]
    new_dates = [int(x) for x in fresh["trade_date"].to_pylist()]
    if (len(set(old_dates)) != len(old_dates) or len(set(new_dates)) != len(new_dates)
            or set(new_dates) != set(old_dates) | set(dates) or set(old_dates) & set(dates)):
        raise QfqGateError("TAIL_DELTA_OUTPUT_KEYS_CHANGED:" + code)
    positions = {d: i for i, d in enumerate(new_dates)}
    prefix = fresh.take(pa.array([positions[d] for d in old_dates]))
    changes = []
    for name in old.schema.names:
        if pa.types.is_dictionary(old[name].type) and pa.types.is_dictionary(prefix[name].type):
            left = old[name].combine_chunks().dictionary_decode()
            right = prefix[name].combine_chunks().dictionary_decode()
            equal = left.is_null().equals(right.is_null()) and left.to_pandas().equals(right.to_pandas())
        else:
            equal = old[name].to_pandas().equals(prefix[name].to_pandas())
        if equal:
            continue
        if name not in TAIL_DELTA_ASOF_FIELDS | {"raw_source_ref_sha256"}:
            raise QfqGateError("TAIL_DELTA_PREFIX_VALUE_CHANGED:" + code + ":" + name)
        # These values still come directly from original rebuild_symbol and
        # merge_rebuilt. No replacement or equality-forcing is performed here.
        a, b = old[name].to_pandas(), prefix[name].to_pandas()
        for i, date in enumerate(old_dates):
            left, right = a.iloc[i], b.iloc[i]
            if (pd.isna(left) and pd.isna(right)) or left == right:
                continue
            changes.append(dict(code=code, trade_date=date, field=name,
                                before=None if pd.isna(left) else left.item() if hasattr(left, "item") else left,
                                after=None if pd.isna(right) else right.item() if hasattr(right, "item") else right,
                                reason="ORIGINAL_ASOF_DISPLAY" if name in TAIL_DELTA_ASOF_FIELDS else "BOUND_NATIVE_SOURCE_SHA_REVISION"))
    return changes


def archive_addition_binding(ref: dict | None, *, snapshot: dict, pointers: dict[str, Path],
                             identity: dict, target: int, retained_history: dict | None) -> dict | None:
    """A separate bounded membership addition; never a native-tail exception.

    Both original raw keys/bytes and adjustment inputs need independently
    accepted, exact-code receipts. The ordinary formula/publication gates still
    apply after this input binding. No missing current-date bar is synthesized.
    """
    if ref is None:
        return None
    value = json.loads(_source(ref, owner="archive addition contract").read_text())
    codes = value.get("codes", {})
    if (value.get("schema") != "qfq_archive_only_history_additions_v1" or value.get("asof_date") != target
            or not isinstance(codes, dict) or not 1 <= len(codes) <= 8 or not retained_history
            or any(not CODE.fullmatch(c) for c in codes)):
        raise QfqGateError("ARCHIVE_ADDITION_CONTRACT_INVALID")
    old = json.loads(_source(value["baseline_snapshot"], owner="archive addition baseline input").read_text())
    if (old.get("asof_date") != target or set(old["symbols"]) & set(codes)
            or set(snapshot["symbols"]) != set(old["symbols"]) | set(codes)
            or set(value.get("baseline_roles", {})) != set(pointers)):
        raise QfqGateError("ARCHIVE_ADDITION_BASELINE_OR_NEW_MEMBERSHIP_CONFLICT")
    core = _source(value["baseline_core"], owner="archive addition original kernel")
    if computation_kernel_sha(core) != computation_kernel_sha(Path(__file__)):
        raise QfqGateError("ARCHIVE_ADDITION_COMPUTATION_CHANGED")
    for role, pointer in pointers.items():
        path = _source(value["baseline_roles"][role], owner="archive addition original " + role)
        meta = panel_contract(path)
        if (path != Path(pointer.read_text(encoding="utf-8-sig").strip())
                or meta.get("generation_id") != value["baseline_generation_id"]
                or meta.get("input_sha256") != canonical_sha(old) or meta.get("asof_date") != target
                or meta.get("adapter_sha256") != sha(core)
                or any(meta.get(k) != v for k, v in identity.items() if k not in {"adapter_sha256", "input_sha256"})
                or set(codes) & _panel_symbols(path)
                or not set(USER_FORMULA_SIGNAL_FIELDS).issubset(pq.ParquetFile(path).schema_arrow.names)):
            raise QfqGateError("ARCHIVE_ADDITION_BASELINE_FORMULA_OR_OLD_CODE_CONFLICT:" + role)
    changed_top = {"symbols", "source_files", "revision", "observed_at", "history_retention_binding"}
    if ({k: v for k, v in old.items() if k not in changed_top}
            != {k: v for k, v in snapshot.items() if k not in changed_top}):
        raise QfqGateError("ARCHIVE_ADDITION_OLD_POLICY_OR_FLOOR_CHANGED")
    retained = snapshot.get("history_retention_binding")
    if (not isinstance(retained, dict)
            or {k: v for k, v in retained_history.items() if k not in {"source_config", "accepted_evidence"}}
            != {k: v for k, v in retained.items() if k not in {"source_config", "accepted_evidence"}}
            or not all(x in retained.get("accepted_evidence", []) for x in retained_history.get("accepted_evidence", []))
            or not all(x in snapshot["source_files"] for x in old["source_files"])):
        raise QfqGateError("ARCHIVE_ADDITION_RETENTION_POLICY_OR_SOURCE_CLOSURE_CHANGED")
    configs = [json.loads(_source(x["source_config"], owner="archive addition original source config").read_text())
               for x in (retained_history, retained)]
    stocks = [{row["code"]: row for row in cfg["stocks"]} for cfg in configs]
    if (any(len(stocks[i]) != len(configs[i]["stocks"]) for i in (0, 1))
            or {k: v for k, v in configs[0].items() if k != "stocks"}
            != {k: v for k, v in configs[1].items() if k != "stocks"}
            or set(stocks[0]) & set(codes) or set(stocks[1]) != set(stocks[0]) | set(codes)
            or any(stocks[1][c] != row for c, row in stocks[0].items())):
        raise QfqGateError("ARCHIVE_ADDITION_OLD_SOURCE_CONFIG_CHANGED")
    for code, before in old["symbols"].items():
        after = snapshot["symbols"][code]
        if ({k: v for k, v in before.items() if k not in {"source_config", "accepted_evidence"}}
                != {k: v for k, v in after.items() if k not in {"source_config", "accepted_evidence"}}
                or after.get("source_config") != retained["source_config"]
                or not all(x in after.get("accepted_evidence", []) for x in before.get("accepted_evidence", []))):
            raise QfqGateError("ARCHIVE_ADDITION_OLD_SYMBOL_CHANGED:" + code)
    archives = {r["path"]: r for r in retained.get("archive_refs", [])}
    for code, binding in codes.items():
        item = snapshot["symbols"][code]
        dates = binding.get("dates")
        if (not isinstance(dates, list) or not dates or dates != sorted(set(dates))
                or any(type(d) is not int or not 19000101 < d <= target for d in dates)
                or item.get("history_start_date") != dates[0] or item.get("history_end_date") != dates[-1]
                or item.get("compute_start_date", dates[0]) != dates[0]
                or item.get("required_output_start_date", dates[0]) != dates[0]
                or item.get("event_coverage_complete") is not True
                or not isinstance(item.get("source_method"), str) or not item["source_method"]
                or set(item.get("publish_roles", [])) != set(pointers)
                or item.get("source_config") != retained["source_config"]
                or code in snapshot.get("quarantine_symbols", {}) or code in snapshot.get("legacy_preservation_codes", [])
                or code in snapshot.get("retained_history_codes", [])):
            raise QfqGateError("ARCHIVE_ADDITION_EXACT_INPUT_WINDOW_UNBOUND:" + code)
        sources = stocks[1][code].get("sources", [])
        refs = item.get("raw_files", [])
        if (len(sources) != 1 or sources[0].get("name") != "archive" or sources[0].get("kind") != "archive_member"
                or sources[0].get("path") not in archives or len(refs) != 1 or refs[0].get("source_role") != "archive"
                or refs[0].get("original_ref") != sources[0] or refs[0].get("sha256") != sources[0].get("member_sha256")):
            raise QfqGateError("ARCHIVE_ADDITION_ORIGINAL_MEMBER_BINDING_CONFLICT:" + code)
        payload = _source(refs[0], owner="archive addition original member bytes").read_bytes()
        if len(payload) != len(dates) * 32:
            raise QfqGateError("ARCHIVE_ADDITION_SOURCE_RECORD_COUNT_CHANGED:" + code)
        actual_dates = np.frombuffer(payload, dtype=np.dtype([("date", "<u4"), ("_", "V28")]))["date"].astype(int).tolist()
        if actual_dates != dates:
            raise QfqGateError("ARCHIVE_ADDITION_SOURCE_DATE_KEYS_CHANGED:" + code)
        adjustment_sources = binding.get("adjustment_source_files")
        if (not isinstance(adjustment_sources, list) or not adjustment_sources
                or not all(x in snapshot["source_files"] for x in adjustment_sources)):
            raise QfqGateError("ARCHIVE_ADDITION_ADJUSTMENT_SOURCE_PROVENANCE_UNBOUND:" + code)
        for source in adjustment_sources:
            _source(source, owner="archive addition accepted adjustment evidence")
        for kind, verdict, expected in (
            ("raw_review", "REVIEWED/PASS_ARCHIVE_ONLY_SOURCE_KEYS_AND_BYTES",
             dict(original_ref=sources[0], raw32_sha256=sha(Path(refs[0]["path"])), dates_sha256=canonical_sha(dates),
                  rows=len(dates), first_date=dates[0], last_date=dates[-1])),
            ("adjustment_review", "REVIEWED/PASS_ARCHIVE_ADDITION_ADJUSTMENT_INPUTS",
             dict(events_sha256=canonical_sha(item["events"]), source_method=item.get("source_method"),
                  history_coverage_start_date=dates[0], history_coverage_end_date=target,
                  source_files=adjustment_sources))):
            review_ref = binding[kind]
            review = json.loads(_source(review_ref, owner="archive addition " + kind).read_text())
            if (review.get("verdict") != verdict or not review.get("reviewer_id")
                    or review.get("reviewer_id") == "/root/local_panel_completion_writer"
                    or review.get("asof_date") != target or review.get("codes", {}).get(code) != expected
                    or review_ref not in retained.get("accepted_evidence", [])
                    or review_ref not in item.get("accepted_evidence", [])):
                raise QfqGateError("ARCHIVE_ADDITION_INDEPENDENT_" + kind.upper() + "_UNBOUND:" + code)
    if not all(x in snapshot["source_files"] for x in [retained["source_config"], retained["source_policy"],
            *retained.get("archive_refs", []), *retained.get("accepted_evidence", [])]):
        raise QfqGateError("ARCHIVE_ADDITION_NEW_SOURCE_CLOSURE_UNBOUND")
    return {**value, "binding_ref": ref}


def run_daily_rebuild(*, driver_path: Path, formula_path: Path, tdx_root: Path, data_root: Path,
                      pointers: dict[str, Path], contract_csv: Path, return_root: Path,
                      target: int, publish: bool = False, workers: int = 2, refresh_inputs: bool = False,
                      checkpoint_resume: dict | None = None, history_extension: dict | None = None,
                      tail_delta: dict | None = None, archive_additions: dict | None = None) -> dict:
    """Called exclusively by the original Mac daily formula authority entry."""
    if tail_delta is not None and (history_extension is not None or refresh_inputs):
        raise QfqGateError("TAIL_DELTA_EXPLICIT_SNAPSHOT_ONLY_NO_GLOBAL_CHECKPOINT_REUSE")
    if tail_delta is not None and checkpoint_resume is not None and publish:
        raise QfqGateError("TAIL_CHECKPOINT_RECOVERY_ISOLATED_ONLY")
    if archive_additions is not None and any(x is not None for x in (tail_delta, history_extension, checkpoint_resume)):
        raise QfqGateError("ARCHIVE_ADDITION_MUTUALLY_EXCLUSIVE_MODE")
    if archive_additions is not None and refresh_inputs:
        raise QfqGateError("ARCHIVE_ADDITION_EXPLICIT_SNAPSHOT_ONLY")
    if not 1 <= workers <= 4:
        raise QfqGateError("WORKER_LIMIT_MUST_BE_1_TO_4")
    history = (history_extension_binding(history_extension, data_root=data_root, return_root=return_root,
                                        pointers=pointers, publish=publish) if history_extension is not None else None)
    with publication_lock(data_root):
        journal = data_root / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
        if history is None:
            recover_pair(journal, pointers)
        snapshot_file = input_path(data_root)
        baseline_file = snapshot_file.with_name("qfq_expected_current.json")
        if publish and not baseline_file.is_file():
            raise QfqGateError(f"EXPECTED_OLD_CURRENT_BINDING_MISSING:{baseline_file}")
        frozen_baseline = json.loads(baseline_file.read_text()) if publish else baseline_binding(pointers)
        check_baseline(pointers, frozen_baseline)
        driver, _ = authorities(driver_path, formula_path)
        retained_history = accepted_history_retention(pointers) if history is None else None
        if refresh_inputs:
            required_start = required_a_history(pointers)
            from ops.research_panel_adjustment_inputs import prepare_snapshot
            prepare_snapshot(tdx_root=tdx_root, data_root=data_root, target=target, driver=driver, required_start=required_start,
                             force_refresh=False if history is not None else refresh_due(data_root, target) or os.environ.get("RESEARCH_PANEL_QFQ_REFRESH_FACTORS") == "1",
                             history_extension=history, retained_history=retained_history)
        snapshot = load_snapshot(snapshot_file, target)
        if tail_delta is None and archive_additions is None and snapshot.get("history_retention_binding") != retained_history:
            raise QfqGateError("DAILY_HISTORY_SNAPSHOT_BINDING_CONFLICT")
        if archive_additions is None and snapshot.get("history_extension") != history_extension:
            raise QfqGateError("HISTORY_SNAPSHOT_RUNTIME_BINDING_CONFLICT")
        identity = generation_identity(snapshot, driver_path, formula_path, contract_csv)
        delta = tail_delta_binding(tail_delta, snapshot=snapshot, pointers=pointers, identity=identity,
                                   target=target, retained_history=retained_history)
        addition = archive_addition_binding(archive_additions, snapshot=snapshot, pointers=pointers, identity=identity,
                                           target=target, retained_history=retained_history)
        incremental = delta or addition
        # One fixed journal owned by the original entry covers crashes between
        # replacing the original two files, even after a new input revision.
        expected = {role: path.read_bytes() for role, path in pointers.items()}
        currents = {role: Path(value.decode("utf-8-sig").strip()) for role, value in expected.items()}
        contracts = {role: panel_contract(path) for role, path in currents.items()}
        if history is not None:
            for role, path in currents.items():
                actual = history_role_identity(path)
                if any(actual[k] != history["roles"][role][k] for k in ("key_sha256", "schema_sha256")):
                    raise QfqGateError(f"HISTORY_BASELINE_KEY_SCHEMA_DRIFT:{role}")
        inherited_quarantine = {}
        for contract in contracts.values():
            if contract.get("quarantine_manifest_path"):
                prior_receipt = json.loads(Path(contract["generation_manifest_path"]).read_text())
                ref = prior_receipt.get("quarantine_manifest")
                if not ref or ref["path"] != contract["quarantine_manifest_path"]:
                    raise QfqGateError("PRIOR_QUARANTINE_MANIFEST_BINDING_MISSING")
                _source(ref, owner="prior-generation quarantine")
                inherited_quarantine[ref["path"]] = ref
        generations = {item.get("generation_id") for item in contracts.values()}
        already_current = (len(generations) == 1 and None not in generations
                           and all(item.get("asof_date") == target and all(item.get(k) == v for k, v in identity.items()) for item in contracts.values()))
        baseline_hashes = {} if already_current else {role: sha(path) for role, path in currents.items()}
        recovered = checkpoint_recovery(checkpoint_resume, snapshot, identity, baseline_hashes, data_root,
                                        tail_delta=delta)
        run_id = next(iter(generations)) if already_current else canonical_sha(dict(target=target, baseline_panel_sha256=baseline_hashes, **identity))
        run_dir = return_root / ("qfq_" + run_id[:20])
        run_dir.mkdir(parents=True, exist_ok=True)
        retained_history_sidecars = {}
        if history is not None:
            for role, binding in history["roles"].items():
                retained_history_sidecars[role] = []
                for ref in binding["sidecars"]:
                    source = _source(ref, owner="history sidecar preservation")
                    destination = run_dir / "inherited_sidecars" / role / (ref["sha256"] + ".parquet")
                    if destination.exists():
                        if sha(destination) != ref["sha256"]:
                            raise QfqGateError("IMMUTABLE_HISTORY_SIDECAR_CONFLICT")
                    else:
                        # A same-generation legacy sidecar remains excluded;
                        # byte preservation never promotes unknown basis rows.
                        _write(destination, source.read_bytes())
                    retained_history_sidecars[role].append(dict(original=ref, retained=dict(path=str(destination), sha256=ref["sha256"]),
                        generation_id=history["baseline_generation_id"], excluded_from_accepted=True, byte_identical=True))
        retained_snapshot = run_dir / "adjustment_input_snapshot.json"
        if retained_snapshot.exists():
            if json.loads(retained_snapshot.read_text()) != snapshot:
                raise QfqGateError("IMMUTABLE_GENERATION_INPUT_SNAPSHOT_CONFLICT")
        else:
            _json(retained_snapshot, snapshot)
        refs = snapshot["source_files"] + [ref for item in snapshot["symbols"].values() for ref in item["raw_files"]]
        source_stats = []
        for ref in refs:
            stat = Path(ref["path"]).stat()
            source_stats.append(dict(path=ref["path"], size=stat.st_size, mtime_ns=stat.st_mtime_ns))
        readiness = dict(generation_id=run_id, source_stats=source_stats,
                         factor_cache_identity=factor_cache_identity(data_root, target, snapshot),
                         code_refs=[dict(path=str(p), sha256=sha(p)) for p in (driver_path, formula_path, contract_csv)])
        if already_current:
            _json(snapshot_file.with_name("qfq_readiness.json"), readiness)
            return dict(status="READY", already_current=True, target_date=target, selector=str(currents["selector"]), backtest=str(currents["backtest"]),
                        selector_pointer_ready=True, backtest_pointer_ready=True, run_dir=str(run_dir),
                        authority=dict(final_status="PASS_QFQ_FULL_HISTORY_IDEMPOTENT", source_sha256=identity["input_sha256"], generation_id=run_id), **FLAGS)
        old_symbols = {role: _panel_symbols(path) for role, path in currents.items()}
        if delta and any(not set(delta["codes"]).issubset(values) for values in old_symbols.values()):
            raise QfqGateError("TAIL_DELTA_CANNOT_ADMIT_NONBASELINE_CODE")
        expected_codes = set().union(*old_symbols.values())
        # The A-share lane must never reprice a foreign market under its basis.
        foreign = {c for c in expected_codes if not CODE.fullmatch(c)}
        legacy_policy = legacy_preservation(snapshot.get("legacy_preservation_policy"))
        legacy_codes = set(snapshot.get("legacy_preservation_codes", [])) & expected_codes
        available = set(snapshot["symbols"])
        retained_history_codes = set(snapshot.get("retained_history_codes", [])) & expected_codes
        if delta and set(delta["codes"]) & (retained_history_codes | legacy_codes | set(snapshot.get("quarantine_symbols", {}))):
            raise QfqGateError("TAIL_DELTA_CHANGED_CODE_CANNOT_BE_EXCLUDED_OR_INACTIVE")
        quarantined = snapshot.get("quarantine_symbols", {})
        from ops.research_panel_adjustment_inputs import existing_day_files
        discovered = {code for code, _ in existing_day_files(tdx_root)}
        missing = sorted((expected_codes | discovered) - foreign - legacy_codes - available - set(quarantined) - retained_history_codes)
        if missing:
            raise QfqGateError(f"MARKETWIDE_ADJUSTMENT_COVERAGE_MISSING:{missing}")
        meta = dict(schema="a_share_qfq_panel_v1", field_basis=field_basis_contract(driver), checkpoint_recovery=checkpoint_resume, price_basis="MIXED_BY_MARKET" if foreign else "QFQ_ASOF",
                    volume_basis="MIXED_BY_MARKET" if foreign else "QFQ_EVENT_VOLUME", amount_basis="MIXED_BY_MARKET" if foreign else "RAW_TURNOVER",
                    market_basis={"A": dict(price_basis="QFQ_ASOF", volume_basis="QFQ_EVENT_VOLUME", amount_basis="RAW_TURNOVER", asof_date=target),
                                  **{market: dict(price_basis="UNKNOWN_NATIVE", volume_basis="UNKNOWN_NATIVE", amount_basis="UNKNOWN_NATIVE", asof_date=None,
                                                 retained_original_values=True)
                                     for market in sorted({c.rsplit(".", 1)[-1] for c in foreign})}},
                    legacy_preservation_policy=snapshot.get("legacy_preservation_policy"),
                    user_formula_contract=dict(version=USER_FORMULA_VERSION, source_sha256=USER_FORMULA_SHA,
                        signal_fields=list(USER_FORMULA_SIGNAL_FIELDS), numerical_convention="PINNED_ORIGINAL_FULL_PREFIX_ENGINE",
                        level1="B3 OR STRICT_ABOVE_ZERO_SECOND_GOLD", legacy_formula_version=LEGACY_FORMULA_VERSION,
                        legacy_primary="brick_buy2_attack OR B3 OR double_breakout",
                        display_today_rule="CURRBARSCOUNT=1 means target-date row; *_daily is prefix-local historical signal"),
                    schema_contract_version="QFQ_V2_DOUBLE_CORE_EVENT_VOLUME", asof_date=target, generation_id=run_id, snapshot_file_sha256=sha(snapshot_file),
                    baseline_panel_sha256=baseline_hashes,
                    generation_manifest_path=str(run_dir / "candidate_receipt.json"), price_provider="MIXED_TDX_A_AND_RETAINED_ORIGINAL" if foreign else "TDX_DAY",
                    adjustment_snapshot=dict(path=str(retained_snapshot), sha256=sha(retained_snapshot)),
                    adjustment_provider_contract="FUTU_GET_REHAB_WITH_EXPLICIT_TDX_UNSUPPORTED_CONVENTION",
                    quarantine_manifest_path=str(run_dir / "quarantine_manifest.json"),
                    convention=snapshot["convention"], revision=snapshot["revision"], pit_certified=False, **identity, **FLAGS)
        retention_binding = ({key: history[key] for key in ("source_config", "source_policy", "archive_refs", "accepted_evidence")}
                             if history is not None else snapshot["history_retention_binding"] if incremental else retained_history)
        if retention_binding is not None:
            meta.update(history_retention_binding=retention_binding,
                retained_history_codes=sorted(retained_history_codes),
                retained_history_asof={code: next(iter(contracts.values())).get("retained_history_asof", {}).get(
                    code, next(iter(contracts.values())).get("asof_date")) for code in retained_history_codes},
                history_retention_semantics="ACCEPTED_INACTIVE_HISTORY_RETAINS_ORIGINAL_BASIS_ASOF; ACTIVE_TARGET_MEMBERSHIP_SEPARATE")
        if history is not None:
            meta.update(history_extension=history_extension, maximum_claim="DIRECTION_ONLY",
                historical_PIT=False, inherited_history_sidecars=retained_history_sidecars,
                history_source_policy=history["source_policy"], history_source_config=history["source_config"],
                nullable_context_reason="NO_AUTHENTICATED_HISTORICAL_CONTEXT; BARS_OBSERVED_NOT_LISTING_AGE")
        if delta:
            meta.update(tail_delta=tail_delta, maximum_claim="DIRECTION_ONLY", historical_PIT=False,
                        tail_delta_semantics="CHANGED_FULL_PREFIX_ONLY_UNCHANGED_ARROW_ROWS_EXACT",
                        tail_delta_baseline_generation=delta["baseline_generation_id"])
        if addition:
            meta.update(archive_additions=archive_additions, maximum_claim="DIRECTION_ONLY", historical_PIT=False,
                        archive_addition_semantics="NEW_BOUND_ARCHIVE_HISTORY_ONLY_UNCHANGED_ARROW_ROWS_EXACT",
                        archive_addition_baseline_generation=addition["baseline_generation_id"])
        candidates = {
            "selector": data_root / "selector_ready_panels/data_layer_daily_formula_increment_update_v1" / f"selector_ready_current_to_{target}_qfq_{run_id[:16]}" / f"selector_ready_current_to_{target}.parquet",
            "backtest": data_root / "backtest_panels/data_layer_daily_formula_increment_update_v1" / f"tdx_backtest_base_panel_5y_v3_current_to_{target}_qfq_{run_id[:16]}" / "panel" / f"tdx_backtest_base_panel_5y_v3_current_to_{target}.parquet",
        }
        double_core = {"open", "high", "low", "close", "vol", "volume", "pre_close", "pct_chg", "BBI", "bbi", "BBI0", "zge_white_line", "white_line", "zge_yellow_line", "yellow_line", "ma60", "MA60", "ma_close_60", "J", "kdj_j", "zge_j"}
        schemas = {}
        for role, path in currents.items():
            old_schema = pq.ParquetFile(path).schema_arrow
            schemas[role] = pa.schema([pa.field(f.name, pa.float64(), nullable=f.nullable, metadata=f.metadata) if f.name in double_core else f for f in old_schema], metadata=old_schema.metadata)
        # History activation adds explicit user labels. Later daily runs inherit
        # these fields from the accepted schema and recompute them from prefix.
        if history is not None:
            schemas = {role: user_formula_schema(schema) for role, schema in schemas.items()}
        role_start = {r: driver.scan_trade_date_min_max(p)[0] for r, p in currents.items()}
        parts_root = run_dir / "symbol_checkpoints"
        parts_root.mkdir(exist_ok=True)
        _json(run_dir / "stage_status.json", dict(status="RUNNING", stage="FULL_HISTORY_QFQ_REBUILD", **meta))
        # Submit only one small batch at a time: memory is bounded by workers x
        # one stock history and two output tables, not the full market frame.
        def one(code: str):
            item = snapshot["symbols"][code]
            checkpoint = parts_root / (code + ".parquet")
            checkpoint_receipt = parts_root / (code + ".receipt.json")
            fingerprint = canonical_sha(dict(code=code, item=item, **identity))
            if checkpoint.is_file() and checkpoint_receipt.is_file():
                check = panel_contract(checkpoint)
                bound = json.loads(checkpoint_receipt.read_text())
                if check.get("checkpoint_id") == fingerprint and bound.get("sha256") == sha(checkpoint):
                    return code, checkpoint
            if code in recovered:
                ref = recovered[code]["artifact"]
                computed = pq.read_table(_source(ref, owner="reused pure computation " + code)).to_pandas()
                if set(computed.ts_code.astype(str)) != {code}:
                    raise QfqGateError("CHECKPOINT_RECOVERY_ROW_CODE_CONFLICT:" + code)
            else:
                computed = rebuild_symbol(code, item, target, driver)
            table = pa.Table.from_pandas(computed, preserve_index=False)
            table = table.replace_schema_metadata({META_KEY: json.dumps(dict(checkpoint_id=fingerprint)).encode()})
            temporary = checkpoint.with_suffix(".pending")
            pq.write_table(table, temporary, compression="zstd")
            os.replace(temporary, checkpoint)
            _json(checkpoint_receipt, dict(checkpoint_id=fingerprint, sha256=sha(checkpoint)))
            return code, checkpoint
        codes = sorted(incremental["codes"] if incremental else available)
        unchanged_codes = ((expected_codes & available) - set(codes) - foreign - legacy_codes
                                  - set(quarantined) - retained_history_codes) if incremental else set()
        quarantine_reasons = dict(quarantined)
        quarantine_reasons.update({c: dict(reason=legacy_policy["reason"], legacy_non_target=True,
                                          policy=snapshot["legacy_preservation_policy"])
                                   for c in legacy_codes})
        eligible = snapshot.get("original_quarantine_eligible", {})
        def compute_or_quarantine(code):
            try:
                return one(code)
            except QfqGateError as exc:
                if incremental or code not in eligible:
                    raise
                quarantine_reasons[code] = dict(reason=str(exc), original_status=eligible[code])
                return code, None
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                for offset in range(0, len(codes), workers):
                    futures = [executor.submit(compute_or_quarantine, c) for c in codes[offset:offset + workers]]
                    for future in futures:
                        future.result()
                    _json(run_dir / "progress.json", dict(completed=min(offset + workers, len(codes)), total=len(codes), generation_id=run_id))
            # Check all old key sets before either role is written. A key absent
            # from raw is a concrete source gap, not permission to drop a row.
            old_spools = {role: spool_current(path, run_dir / ("current_" + role + "_buckets"), baseline_hashes[role])
                          for role, path in currents.items()}
            for role, buckets in old_spools.items():
                for bucket_path in buckets.values():
                    frame = pq.read_table(bucket_path, columns=["ts_code", "trade_date"]).to_pandas()
                    for code, old_keys in frame.groupby("ts_code"):
                        if code in legacy_codes:
                            approved_role = legacy_policy["roles"][role]
                            actual_dates = sorted(pd.to_numeric(old_keys.trade_date).astype(int).tolist())
                            approved = approved_role["keys"].get(code, {})
                            if (approved_role["original_sha256"] != baseline_hashes[role]
                                    or approved.get("date_sha256") != canonical_sha(actual_dates)
                                    or approved.get("rows") != len(actual_dates)):
                                raise QfqGateError(f"LEGACY_PRESERVATION_KEYS_OR_BASELINE_CHANGED:{role}:{code}")
                        if code in quarantine_reasons or code in foreign or code in retained_history_codes or code in unchanged_codes:
                            continue
                        rebuilt_keys = pq.read_table(parts_root / (code + ".parquet"), columns=["trade_date"]).column(0).to_pylist()
                        missing_keys = sorted(set(pd.to_numeric(old_keys.trade_date).astype(int)) - set(rebuilt_keys))
                        if missing_keys:
                            if incremental or code not in eligible:
                                raise QfqGateError(f"RAW_HISTORY_KEYS_MISSING:{role}:{code}:{missing_keys[:10]}")
                            quarantine_reasons[code] = dict(reason="RAW_HISTORY_KEYS_MISSING", role=role,
                                missing_dates=missing_keys, original_status=eligible[code])
            codes = [code for code in codes if code not in quarantine_reasons]
            quarantine_artifacts, role_counts, delta_prefix_changes = {}, {}, {}
            for role, candidate in candidates.items():
                old_buckets = old_spools[role]
                candidate.parent.mkdir(parents=True, exist_ok=True)
                schema = schemas[role].with_metadata({**(schemas[role].metadata or {}), META_KEY: json.dumps(meta).encode()})
                temporary = candidate.with_suffix(".pending")
                latest = 0
                rows_written = 0
                latest_codes, old_latest_codes = set(), set()
                quarantine_path = run_dir / "quarantine" / (role + ".parquet")
                quarantine_path.parent.mkdir(parents=True, exist_ok=True)
                legacy_schema = pq.ParquetFile(currents[role]).schema_arrow
                quarantine_schema = legacy_schema.with_metadata({b"quarantine_contract": json.dumps(dict(
                    generation_id=run_id, legacy_basis_unknown=True, excluded_from_accepted=True,
                    original_path=str(currents[role]), original_sha256=baseline_hashes[role])).encode()})
                quarantined_rows = 0
                old_rows, replaced_old_rows, retained_non_a_rows, retained_a_history_rows = 0, 0, 0, 0
                retained_by_market = {}
                unchanged_active_rows = 0
                unchanged_inactive_rows = 0
                delta_prefix_changes[role] = []
                with pq.ParquetWriter(temporary, schema, compression="zstd") as writer, pq.ParquetWriter(quarantine_path, quarantine_schema, compression="zstd") as quarantine_writer:
                    for bucket in range(32):
                        old_table = pq.read_table(old_buckets[bucket]) if bucket in old_buckets else None
                        old_frame = old_table.to_pandas() if old_table is not None else pd.DataFrame()
                        old_groups = old_frame.groupby("ts_code", sort=False).indices if not old_frame.empty else {}
                        if not old_frame.empty:
                            old_rows += len(old_frame)
                            old_latest_codes.update(old_frame.loc[pd.to_numeric(old_frame.trade_date).eq(target)
                                & old_frame.ts_code.map(lambda c: bool(CODE.fullmatch(c))), "ts_code"].astype(str))
                            # Arrow copies preserve null/NaN and the original values.
                            # Double promotion is lossless for retained float32 values.
                            old_codes = old_table["ts_code"].to_pylist()
                            excluded = old_table.filter(pa.array([c in quarantine_reasons for c in old_codes]))
                            if len(excluded):
                                quarantine_writer.write_table(excluded.replace_schema_metadata(quarantine_schema.metadata))
                                quarantined_rows += len(excluded)
                            retained = old_table.filter(pa.array([c in foreign or c in retained_history_codes or c in unchanged_codes for c in old_codes]))
                            if len(retained):
                                for field in schema:
                                    if field.name not in retained.schema.names and field.name in USER_FORMULA_SIGNAL_FIELDS:
                                        retained = retained.append_column(field, pa.nulls(len(retained), type=field.type))
                                if incremental and not retained.schema.equals(schema, check_metadata=False):
                                    raise QfqGateError("TAIL_DELTA_UNCHANGED_SCHEMA_CHANGED:" + role)
                                writer.write_table(retained.replace_schema_metadata(schema.metadata) if incremental else retained.cast(schema))
                                retained_non_a_rows += sum(c in foreign for c in retained["ts_code"].to_pylist())
                                retained_a_history_rows += sum(c in retained_history_codes for c in retained["ts_code"].to_pylist())
                                unchanged_target_here = set(old_frame.loc[pd.to_numeric(old_frame.trade_date).eq(target), "ts_code"]) & unchanged_codes
                                unchanged_active_rows += sum(c in unchanged_target_here for c in retained["ts_code"].to_pylist())
                                unchanged_inactive_rows += sum(c in unchanged_codes - unchanged_target_here for c in retained["ts_code"].to_pylist())
                                if incremental:
                                    for c, d in zip(retained["ts_code"].to_pylist(), retained["trade_date"].to_pylist()):
                                        if CODE.fullmatch(c) and int(d) == target:
                                            latest_codes.add(c)
                                            latest = target
                                for c in retained["ts_code"].to_pylist():
                                    if c not in foreign:
                                        continue
                                    market = c.rsplit(".", 1)[-1]
                                    retained_by_market[market] = retained_by_market.get(market, 0) + 1
                                rows_written += len(retained)
                        for code in (code for code in codes if _bucket(code) == bucket):
                            if code not in old_symbols[role] and role not in snapshot["symbols"][code]["publish_roles"]:
                                continue
                            rebuilt = pq.read_table(parts_root / (code + ".parquet")).to_pandas()
                            old = old_frame.iloc[old_groups[code]].copy() if code in old_groups else pd.DataFrame()
                            replaced_old_rows += len(old)
                            if old.empty and history is None and addition is None:
                                rebuilt = rebuilt.loc[rebuilt.trade_date.ge(role_start[role])].copy()
                            if rebuilt.empty:
                                continue
                            frame = merge_rebuilt(old, rebuilt, role=role, driver=driver, history_extension=history is not None or retained_history is not None)
                            if role == "selector" and frame.trade_date.eq(target).any():
                                # Same original gate; validation sees generated fields
                                # before output-schema pruning.
                                gate = driver.validate_new_selector_rows(frame.loc[frame.trade_date.eq(target)], schemas[role], target)
                                if gate["status"] != "PASS":
                                    raise QfqGateError(f"ORIGINAL_SELECTOR_FORMULA_GATE_FAILED:{code}:{gate}")
                            table = _table(frame, schema, driver, role, history_extension=history is not None or retained_history is not None)
                            if delta:
                                original = old_table.take(pa.array(old_groups[code]))
                                delta_prefix_changes[role].extend(tail_delta_prefix(original, table, delta["codes"][code]["added_dates"], code))
                            writer.write_table(table)
                            latest = max(latest, int(frame.trade_date.max()))
                            rows_written += len(frame)
                            if frame.trade_date.eq(target).any():
                                latest_codes.add(code)
                if old_rows != replaced_old_rows + quarantined_rows + retained_non_a_rows + retained_a_history_rows + unchanged_active_rows + unchanged_inactive_rows:
                    raise QfqGateError(f"OLD_KEYS_PRESERVATION_COUNT_FAILED:{role}")
                if not old_latest_codes.issubset(latest_codes):
                    raise QfqGateError(f"ORIGINAL_TARGET_ACCEPTED_KEYS_LOST:{role}:{sorted(old_latest_codes-latest_codes)}")
                floor = int(snapshot.get("accepted_target_date_floor", 1))
                if len(latest_codes) < floor:
                    raise QfqGateError(f"ORIGINAL_ACCEPTED_FLOOR_FAILED:{role}:{len(latest_codes)}<{floor}")
                quarantine_artifacts[role] = dict(path=str(quarantine_path), sha256=sha(quarantine_path), rows=quarantined_rows,
                    original_path=str(currents[role]), original_sha256=baseline_hashes[role],
                    old_keys_preservation="REBUILT_A_OR_RETAINED_NON_A_OR_EXACT_LEGACY_QUARANTINE_DISJOINT")
                role_counts[role] = dict(accepted_rows=rows_written - retained_non_a_rows, panel_rows=rows_written, retained_non_a_old_rows=retained_non_a_rows, target_date_symbols=len(latest_codes), quarantined_old_rows=quarantined_rows,
                    original_old_rows=old_rows, replaced_old_rows=replaced_old_rows, retained_a_history_rows=retained_a_history_rows, unchanged_active_rows=unchanged_active_rows, unchanged_inactive_rows=unchanged_inactive_rows, retained_non_a_by_market=retained_by_market, old_key_conservation=True)
                if history is not None:
                    role_counts[role].update(added_accepted_history_rows=rows_written - retained_non_a_rows - replaced_old_rows,
                        inherited_sidecar_files=len(retained_history_sidecars[role]),
                        inherited_sidecar_preservation="BYTE_IDENTICAL_SEPARATE_EXCLUDED_ARTIFACTS")
                if addition:
                    role_counts[role].update(archive_added_codes=sorted(addition["codes"]),
                                            archive_added_rows=rows_written - old_rows)
                if latest != target:
                    raise QfqGateError(f"PANEL_TARGET_DATE_MISSING:{role}:{latest}")
                if candidate.exists():
                    # Immutable generations: do not replace an existing file.
                    if sha(candidate) != sha(temporary):
                        raise QfqGateError(f"IMMUTABLE_GENERATION_CONFLICT:{candidate}")
                    temporary.unlink()
                else:
                    os.replace(temporary, candidate)
            if delta:
                _json(run_dir / "tail_delta_changes.json", dict(generation_id=run_id, codes=sorted(delta["codes"]),
                    expected_new_keys=sum(len(x["added_dates"]) for x in delta["codes"].values()),
                    prefix_display_or_lineage_changes=delta_prefix_changes,
                    unchanged_active_rows={role: counts["unchanged_active_rows"] for role, counts in role_counts.items()},
                    unchanged_inactive_rows={role: counts["unchanged_inactive_rows"] for role, counts in role_counts.items()},
                    unchanged_row_method="ORIGINAL_ARROW_FILTER_REPLACE_FOOTER_ONLY"))
            # Revalidate source bytes before CURRENT can change.
            if generation_identity(load_snapshot(snapshot_file, target), driver_path, formula_path, contract_csv) != identity:
                raise QfqGateError("INPUT_CHANGED_DURING_BUILD")
            if factor_cache_identity(data_root, target, snapshot) != readiness["factor_cache_identity"]:
                raise QfqGateError("FACTOR_CACHE_CHANGED_DURING_BUILD")
            check_baseline(pointers, frozen_baseline)
            if delta:
                _source(tail_delta, owner="tail delta contract before publication")
            if addition:
                _source(archive_additions, owner="archive addition contract before publication")
            for ref in inherited_quarantine.values():
                _source(ref, owner="prior-generation quarantine")
            _json(run_dir / "quarantine_manifest.json", dict(generation_id=run_id, reasons=quarantine_reasons,
                  artifacts=quarantine_artifacts, counts=role_counts, inherited_quarantine_manifests=list(inherited_quarantine.values()),
                  legacy_basis_unknown=True, excluded_from_accepted=True))
            receipt = dict(status="CANDIDATE_READY", target_date=target, run_dir=str(run_dir), candidates={r: str(p) for r, p in candidates.items()},
                           quarantine_manifest=dict(path=str(run_dir / "quarantine_manifest.json"), sha256=sha(run_dir / "quarantine_manifest.json")),
                           counts=role_counts, candidate_sha256={r: sha(p) for r, p in candidates.items()}, **meta)
            _json(run_dir / "candidate_receipt.json", receipt)
            if publish:
                verify_release_gate(snapshot_file.parent, candidates["selector"], identity, target, snapshot["convention"])
                publish_pair(pointers, candidates, expected, journal, expected_baseline=frozen_baseline)
                _json(baseline_file, baseline_binding(pointers))
                _json(snapshot_file.with_name("qfq_readiness.json"), readiness)
                receipt.update(status="READY", selector_pointer_ready=True, backtest_pointer_ready=True)
            final_status = "PASS_QFQ_FULL_HISTORY" if receipt["status"] == "READY" else "CANDIDATE_READY"
            receipt.update(selector=str(candidates["selector"]), backtest=str(candidates["backtest"]),
                           authority=dict(final_status=final_status, source_sha256=identity["input_sha256"], generation_id=run_id))
            # Preserve the original Mac authority's machine handoff names.
            compatibility = dict(final_status=final_status, run_dir=str(run_dir), latest_trade_date=target,
                                 selector_current_after=str(candidates["selector"]), backtest_current_after=str(candidates["backtest"]),
                                 canonical_rebuild_stage_status="FULL_HISTORY_ORIGINAL_CANONICAL_PURE_FUNCTION", qfq_contract=meta,
                                 formula_processing=dict(worker_context=dict(driver_path=str(driver_path), driver_sha256=sha(driver_path),
                                                                             canonical_formula_path=str(formula_path), canonical_formula_sha256=sha(formula_path))), **FLAGS)
            _json(run_dir / "meta.json", compatibility)
            _json(run_dir / "task_summary.json", compatibility)
            _json(run_dir / "stage_status.json", receipt)
            return receipt
        except BaseException as exc:
            _json(run_dir / "stage_status.json", dict(status="FAILED", error=str(exc), generation_id=run_id, **FLAGS))
            raise
