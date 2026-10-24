"""Internal full-history QFQ stage of the existing daily A-share authority.

There is deliberately no CLI, collector, default raw fallback or own CURRENT.
The original daily adapter supplies the two original pointers and authorities.
An adjustment snapshot is an immutable input, not an authority price panel.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import base64
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


def rebuild_symbol(code: str, item: dict, target: int, driver) -> pd.DataFrame:
    parts = []
    for ref in item["raw_files"]:
        path = _source(ref, owner=code)
        if path.stat().st_size % driver.DAY_STRUCT.size:
            raise QfqGateError(f"RAW_TRAILING_BYTES:{code}:{path}")
        part = driver.read_day_tail(code, path, tail_records=path.stat().st_size // driver.DAY_STRUCT.size)
        if ref.get("from_date_exclusive") is not None:
            part = part.loc[part.trade_date.gt(int(ref["from_date_exclusive"]))].copy()
        parts.append(part)
    raw = pd.concat(parts, ignore_index=True)
    # Archive and live tails may overlap, but conflicting price/volume history
    # needs a source revision decision, never a keep-last guess.
    fields = ["trade_date", "open", "high", "low", "close", "vol", "amount"]
    unique = raw[fields].drop_duplicates()
    if unique.trade_date.duplicated().any():
        raise QfqGateError(f"RAW_SOURCE_OVERLAP_CONFLICT:{code}")
    raw = raw.drop_duplicates("trade_date").sort_values("trade_date").reset_index(drop=True)
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
    features["bars_since_list"] = np.arange(1, len(features) + 1)
    return features


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


def merge_rebuilt(old: pd.DataFrame, rebuilt: pd.DataFrame, *, role: str, driver) -> pd.DataFrame:
    """Replace every old affected OHLC/formula row; retain historical metadata."""
    if old.empty:
        return rebuilt.copy()
    if old.trade_date.duplicated().any():
        raise QfqGateError(f"CURRENT_DUPLICATE_KEYS:{role}")
    old = old.copy()
    old["trade_date"] = pd.to_numeric(old.trade_date).astype(int)
    source = rebuilt.set_index("trade_date")
    if not set(old.trade_date).issubset(source.index):
        missing = sorted(set(old.trade_date) - set(source.index))
        raise QfqGateError(f"RAW_HISTORY_KEYS_MISSING:{role}:{missing[:10]}")
    fresh = source.loc[source.index >= int(old.trade_date.min())].reset_index()
    preserved = old.set_index("trade_date")
    # Formula fields are generated only by original authorities; other historic
    # data retain their original per-row values rather than latest-row backfill.
    for column in old.columns:
        if driver.is_formula_like_column(column) and column not in fresh.columns:
            raise QfqGateError(f"FORMULA_RECOMPUTATION_MISSING:{role}:{column}")
        if column not in fresh.columns:
            mapping = preserved[column]
            fresh[column] = fresh.trade_date.map(mapping)
            latest = mapping.dropna()
            if not latest.empty:
                new = ~fresh.trade_date.isin(preserved.index)
                fresh.loc[new, column] = latest.iloc[-1]
    return fresh


def _panel_symbols(path: Path) -> set[str]:
    values = set()
    for batch in pq.ParquetFile(path).iter_batches(columns=["ts_code"], batch_size=131072):
        values.update(str(v) for v in batch.column(0).unique().to_pylist())
    return values


def _table(frame: pd.DataFrame, schema: pa.Schema, driver, role: str) -> pa.Table:
    # No original formula field is silently default-filled with zero.
    missing = [f.name for f in schema if driver.is_formula_like_column(f.name) and f.name not in frame]
    if missing:
        raise QfqGateError(f"UNCOMPUTED_FORMULA_FIELDS:{role}:{missing}")
    return driver.build_table_for_schema(frame, schema, role)[0]


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


def run_daily_rebuild(*, driver_path: Path, formula_path: Path, tdx_root: Path, data_root: Path,
                      pointers: dict[str, Path], contract_csv: Path, return_root: Path,
                      target: int, publish: bool = False, workers: int = 2, refresh_inputs: bool = False) -> dict:
    """Called exclusively by the original Mac daily formula authority entry."""
    if not 1 <= workers <= 4:
        raise QfqGateError("WORKER_LIMIT_MUST_BE_1_TO_4")
    with publication_lock(data_root):
        journal = data_root / "runtime/cache/data_layer_daily_formula_increment_update_v1/qfq_publication.json"
        recover_pair(journal, pointers)
        snapshot_file = input_path(data_root)
        baseline_file = snapshot_file.with_name("qfq_expected_current.json")
        if publish and not baseline_file.is_file():
            raise QfqGateError(f"EXPECTED_OLD_CURRENT_BINDING_MISSING:{baseline_file}")
        frozen_baseline = json.loads(baseline_file.read_text()) if publish else baseline_binding(pointers)
        check_baseline(pointers, frozen_baseline)
        driver, _ = authorities(driver_path, formula_path)
        if refresh_inputs:
            required_start = required_a_history(pointers)
            from ops.research_panel_adjustment_inputs import prepare_snapshot
            prepare_snapshot(tdx_root=tdx_root, data_root=data_root, target=target, driver=driver, required_start=required_start,
                             force_refresh=refresh_due(data_root, target) or os.environ.get("RESEARCH_PANEL_QFQ_REFRESH_FACTORS") == "1")
        snapshot = load_snapshot(snapshot_file, target)
        identity = generation_identity(snapshot, driver_path, formula_path, contract_csv)
        # One fixed journal owned by the original entry covers crashes between
        # replacing the original two files, even after a new input revision.
        expected = {role: path.read_bytes() for role, path in pointers.items()}
        currents = {role: Path(value.decode("utf-8-sig").strip()) for role, value in expected.items()}
        contracts = {role: panel_contract(path) for role, path in currents.items()}
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
        run_id = next(iter(generations)) if already_current else canonical_sha(dict(target=target, baseline_panel_sha256=baseline_hashes, **identity))
        run_dir = return_root / ("qfq_" + run_id[:20])
        run_dir.mkdir(parents=True, exist_ok=True)
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
        expected_codes = set().union(*old_symbols.values())
        # The A-share lane must never reprice a foreign market under its basis.
        foreign = {c for c in expected_codes if not CODE.fullmatch(c)}
        legacy_policy = legacy_preservation(snapshot.get("legacy_preservation_policy"))
        legacy_codes = set(snapshot.get("legacy_preservation_codes", [])) & expected_codes
        available = set(snapshot["symbols"])
        quarantined = snapshot.get("quarantine_symbols", {})
        from ops.research_panel_adjustment_inputs import existing_day_files
        discovered = {code for code, _ in existing_day_files(tdx_root)}
        missing = sorted((expected_codes | discovered) - foreign - legacy_codes - available - set(quarantined))
        if missing:
            raise QfqGateError(f"MARKETWIDE_ADJUSTMENT_COVERAGE_MISSING:{missing}")
        meta = dict(schema="a_share_qfq_panel_v1", price_basis="MIXED_BY_MARKET" if foreign else "QFQ_ASOF",
                    volume_basis="MIXED_BY_MARKET" if foreign else "QFQ_EVENT_VOLUME", amount_basis="MIXED_BY_MARKET" if foreign else "RAW_TURNOVER",
                    market_basis={"A": dict(price_basis="QFQ_ASOF", volume_basis="QFQ_EVENT_VOLUME", amount_basis="RAW_TURNOVER", asof_date=target),
                                  **{market: dict(price_basis="UNKNOWN_NATIVE", volume_basis="UNKNOWN_NATIVE", amount_basis="UNKNOWN_NATIVE", asof_date=None,
                                                 retained_original_values=True)
                                     for market in sorted({c.rsplit(".", 1)[-1] for c in foreign})}},
                    legacy_preservation_policy=snapshot.get("legacy_preservation_policy"),
                    schema_contract_version="QFQ_V2_DOUBLE_CORE_EVENT_VOLUME", asof_date=target, generation_id=run_id, snapshot_file_sha256=sha(snapshot_file),
                    baseline_panel_sha256=baseline_hashes,
                    generation_manifest_path=str(run_dir / "candidate_receipt.json"), price_provider="MIXED_TDX_A_AND_RETAINED_ORIGINAL" if foreign else "TDX_DAY",
                    adjustment_snapshot=dict(path=str(retained_snapshot), sha256=sha(retained_snapshot)),
                    adjustment_provider_contract="FUTU_GET_REHAB_WITH_EXPLICIT_TDX_UNSUPPORTED_CONVENTION",
                    quarantine_manifest_path=str(run_dir / "quarantine_manifest.json"),
                    convention=snapshot["convention"], revision=snapshot["revision"], pit_certified=False, **identity, **FLAGS)
        candidates = {
            "selector": data_root / "selector_ready_panels/data_layer_daily_formula_increment_update_v1" / f"selector_ready_current_to_{target}_qfq_{run_id[:16]}" / f"selector_ready_current_to_{target}.parquet",
            "backtest": data_root / "backtest_panels/data_layer_daily_formula_increment_update_v1" / f"tdx_backtest_base_panel_5y_v3_current_to_{target}_qfq_{run_id[:16]}" / "panel" / f"tdx_backtest_base_panel_5y_v3_current_to_{target}.parquet",
        }
        double_core = {"open", "high", "low", "close", "vol", "volume", "pre_close", "pct_chg", "BBI", "bbi", "BBI0", "zge_white_line", "white_line", "zge_yellow_line", "yellow_line", "ma60", "MA60", "ma_close_60", "J", "kdj_j", "zge_j"}
        schemas = {}
        for role, path in currents.items():
            old_schema = pq.ParquetFile(path).schema_arrow
            schemas[role] = pa.schema([pa.field(f.name, pa.float64(), nullable=f.nullable, metadata=f.metadata) if f.name in double_core else f for f in old_schema], metadata=old_schema.metadata)
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
            computed = rebuild_symbol(code, item, target, driver)
            table = pa.Table.from_pandas(computed, preserve_index=False)
            table = table.replace_schema_metadata({META_KEY: json.dumps(dict(checkpoint_id=fingerprint)).encode()})
            temporary = checkpoint.with_suffix(".pending")
            pq.write_table(table, temporary, compression="zstd")
            os.replace(temporary, checkpoint)
            _json(checkpoint_receipt, dict(checkpoint_id=fingerprint, sha256=sha(checkpoint)))
            return code, checkpoint
        codes = sorted(available)
        quarantine_reasons = dict(quarantined)
        quarantine_reasons.update({c: dict(reason=legacy_policy["reason"], legacy_non_target=True,
                                          policy=snapshot["legacy_preservation_policy"])
                                   for c in legacy_codes})
        eligible = snapshot.get("original_quarantine_eligible", {})
        def compute_or_quarantine(code):
            try:
                return one(code)
            except QfqGateError as exc:
                if code not in eligible:
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
                        if code in quarantine_reasons or code in foreign:
                            continue
                        rebuilt_keys = pq.read_table(parts_root / (code + ".parquet"), columns=["trade_date"]).column(0).to_pylist()
                        missing_keys = sorted(set(pd.to_numeric(old_keys.trade_date).astype(int)) - set(rebuilt_keys))
                        if missing_keys:
                            if code not in eligible:
                                raise QfqGateError(f"RAW_HISTORY_KEYS_MISSING:{role}:{code}:{missing_keys[:10]}")
                            quarantine_reasons[code] = dict(reason="RAW_HISTORY_KEYS_MISSING", role=role,
                                missing_dates=missing_keys, original_status=eligible[code])
            codes = [code for code in codes if code not in quarantine_reasons]
            quarantine_artifacts, role_counts = {}, {}
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
                old_rows, replaced_old_rows, retained_non_a_rows = 0, 0, 0
                retained_by_market = {}
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
                            retained = old_table.filter(pa.array([c in foreign for c in old_codes]))
                            if len(retained):
                                writer.write_table(retained.cast(schema))
                                retained_non_a_rows += len(retained)
                                for c in retained["ts_code"].to_pylist():
                                    market = c.rsplit(".", 1)[-1]
                                    retained_by_market[market] = retained_by_market.get(market, 0) + 1
                                rows_written += len(retained)
                        for code in (code for code in codes if _bucket(code) == bucket):
                            if code not in old_symbols[role] and role not in snapshot["symbols"][code]["publish_roles"]:
                                continue
                            rebuilt = pq.read_table(parts_root / (code + ".parquet")).to_pandas()
                            old = old_frame.iloc[old_groups[code]].copy() if code in old_groups else pd.DataFrame()
                            replaced_old_rows += len(old)
                            if old.empty:
                                rebuilt = rebuilt.loc[rebuilt.trade_date.ge(role_start[role])].copy()
                            if rebuilt.empty:
                                continue
                            frame = merge_rebuilt(old, rebuilt, role=role, driver=driver)
                            if role == "selector" and frame.trade_date.eq(target).any():
                                # Same original gate; validation sees generated fields
                                # before output-schema pruning.
                                gate = driver.validate_new_selector_rows(frame.loc[frame.trade_date.eq(target)], schemas[role], target)
                                if gate["status"] != "PASS":
                                    raise QfqGateError(f"ORIGINAL_SELECTOR_FORMULA_GATE_FAILED:{code}:{gate}")
                            table = _table(frame, schema, driver, role)
                            writer.write_table(table)
                            latest = max(latest, int(frame.trade_date.max()))
                            rows_written += len(frame)
                            if frame.trade_date.eq(target).any():
                                latest_codes.add(code)
                if old_rows != replaced_old_rows + quarantined_rows + retained_non_a_rows:
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
                    original_old_rows=old_rows, replaced_old_rows=replaced_old_rows, retained_non_a_by_market=retained_by_market, old_key_conservation=True)
                if latest != target:
                    raise QfqGateError(f"PANEL_TARGET_DATE_MISSING:{role}:{latest}")
                if candidate.exists():
                    # Immutable generations: do not replace an existing file.
                    if sha(candidate) != sha(temporary):
                        raise QfqGateError(f"IMMUTABLE_GENERATION_CONFLICT:{candidate}")
                    temporary.unlink()
                else:
                    os.replace(temporary, candidate)
            # Revalidate source bytes before CURRENT can change.
            if generation_identity(load_snapshot(snapshot_file, target), driver_path, formula_path, contract_csv) != identity:
                raise QfqGateError("INPUT_CHANGED_DURING_BUILD")
            if factor_cache_identity(data_root, target, snapshot) != readiness["factor_cache_identity"]:
                raise QfqGateError("FACTOR_CACHE_CHANGED_DURING_BUILD")
            check_baseline(pointers, frozen_baseline)
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
