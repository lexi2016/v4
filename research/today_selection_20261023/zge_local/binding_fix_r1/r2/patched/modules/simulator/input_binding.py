"""Explicit provenance and cutoff boundary for resonance input; no provider fallback."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import hashlib
import json
import math
from pathlib import Path


class InputBindingError(ValueError):
    """The requested signal cannot be evaluated on the supplied bound input."""


def digest(value) -> str:
    def enum_value(item):
        if isinstance(item, Enum):
            return item.value
        raise TypeError("UNSUPPORTED_IDENTITY_VALUE:" + type(item).__name__)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False, default=enum_value).encode("utf-8")).hexdigest()


def date8(value: str) -> str:
    if not isinstance(value, str) or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise InputBindingError("INVALID_DATE")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise InputBindingError("INVALID_DATE") from exc
    return value


def configuration_identity(config) -> str:
    # The native detectors also consume the active parameter overrides.
    from ..self_optimizer.param_registry import _ACTIVE_OVERRIDES
    return digest({"simulation_config": asdict(config), "active_strategy_overrides": _ACTIVE_OVERRIDES})


CANONICAL_COLUMNS = ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount", "pct_chg"]


def verify_expected_window(manifest, binding, ts_code, window):
    """Tie the canonical frame to one pre-frozen producer window, not just a filename."""
    if manifest.get("schema") != "RESONANCE_BOUND_INPUT_WINDOWS_V1" or manifest.get("canonical_columns") != CANONICAL_COLUMNS:
        raise InputBindingError("INVALID_SOURCE_MANIFEST_SCHEMA")
    units = dict(price="CNY", volume="SHARES", amount="CNY", pct_chg="PERCENT_POINTS")
    if (manifest.get("signal_asof"), manifest.get("selection_date"), manifest.get("price_basis"), manifest.get("units")) != (binding.signal_asof, binding.selection_date, binding.price_basis, units):
        raise InputBindingError("MANIFEST_SEMANTIC_MISMATCH")
    owner = manifest.get("source_identity", {})
    owner_path = Path(owner.get("path", ""))
    if owner.get("kind") != "REUSED_OWNER_INPUT_BINDING" or not owner_path.is_file() or owner_path.is_symlink():
        raise InputBindingError("OWNER_BINDING_UNAVAILABLE")
    if hashlib.sha256(owner_path.read_bytes()).hexdigest() != owner.get("sha256"):
        raise InputBindingError("OWNER_BINDING_SHA_MISMATCH")
    owner_binding = json.loads(owner_path.read_text(encoding="utf-8"))
    selector = owner_binding["selector"]
    panel = Path(selector["target_path"])
    state = panel.stat()
    actual_stat = dict(inode=state.st_ino, mtime_ns=state.st_mtime_ns, size_bytes=state.st_size)
    if manifest.get("source_panel") != dict(path=str(panel), sha256=selector["expected_sha256"], stat=selector["target_stat"]) or actual_stat != selector["target_stat"]:
        raise InputBindingError("OWNER_PANEL_IDENTITY_DRIFT")
    records = manifest.get("windows", [])
    key = (ts_code, binding.signal_asof, binding.selection_date)
    matches = [r for r in records if (r.get("ts_code"), r.get("signal_asof"), r.get("selection_date")) == key]
    if len(matches) != 1:
        raise InputBindingError("MISSING_OR_NONUNIQUE_BOUND_WINDOW")
    expected = matches[0]
    observed = dict(sha256=digest(window), row_count=len(window), first_date=window[0]["trade_date"], last_date=window[-1]["trade_date"])
    if {k: expected.get(k) for k in observed} != observed:
        raise InputBindingError("PRODUCER_WINDOW_SHA_OR_KEY_MISMATCH")
    return owner, observed


@dataclass(frozen=True)
class ResonanceInputBinding:
    source_manifest_path: str
    source_manifest_sha256: str
    signal_asof: str
    selection_date: str
    configuration_sha256: str
    price_basis: str
    price_unit: str
    volume_unit: str
    amount_unit: str
    pct_chg_unit: str


def prepare_resonance_input(ts_code, trade_date, klines, context, config, binding):
    """Validate before any indicator work, copy fields, cut future rows, retain real window."""
    if not isinstance(binding, ResonanceInputBinding):
        raise InputBindingError("EXPLICIT_INPUT_BINDING_REQUIRED")
    asof = date8(binding.signal_asof)
    selection = date8(binding.selection_date)
    if date8(trade_date) != asof or selection < asof:
        raise InputBindingError("SIGNAL_SELECTION_DATE_MISMATCH")
    if binding.price_basis != "RAW_UNADJUSTED" or (
        binding.price_unit, binding.volume_unit, binding.amount_unit, binding.pct_chg_unit
    ) != ("CNY", "SHARES", "CNY", "PERCENT_POINTS"):
        raise InputBindingError("UNBOUND_PRICE_BASIS_OR_UNITS")
    source = Path(binding.source_manifest_path)
    if not source.is_file() or source.is_symlink():
        raise InputBindingError("SOURCE_MANIFEST_UNAVAILABLE")
    if hashlib.sha256(source.read_bytes()).hexdigest() != binding.source_manifest_sha256:
        raise InputBindingError("SOURCE_MANIFEST_SHA_MISMATCH")
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise InputBindingError("INVALID_SOURCE_MANIFEST") from exc
    if configuration_identity(config) != binding.configuration_sha256:
        raise InputBindingError("CONFIGURATION_SHA_MISMATCH")
    if context is not None and date8(context.date) != asof:
        raise InputBindingError("CONTEXT_DATE_MISMATCH")
    if not isinstance(klines, (list, tuple)) or not klines:
        raise InputBindingError("EMPTY_BOUND_INPUT")
    rows, dates = [], []
    for item in klines:
        def field(key):
            try:
                return item[key] if isinstance(item, Mapping) else getattr(item, key)
            except (KeyError, AttributeError) as exc:
                raise InputBindingError("MISSING_FIELD:" + key) from exc
        code, day = field("ts_code"), date8(field("trade_date"))
        if code != ts_code:
            raise InputBindingError("SYMBOL_MISMATCH")
        dates.append(day)
        if day > asof:
            continue
        row = {"ts_code": code, "trade_date": day}
        for key in ("open", "high", "low", "close", "vol", "amount", "pct_chg"):
            value = field(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise InputBindingError("NONFINITE_OR_NONNUMERIC_FIELD:" + key)
            row[key] = float(value)
        if not (0 < row["low"] <= min(row["open"], row["close"]) <= max(row["open"], row["close"]) <= row["high"]) or row["vol"] < 0 or row["amount"] < 0:
            raise InputBindingError("INVALID_OHLCVA")
        rows.append(row)
    if dates != sorted(set(dates)):
        raise InputBindingError("NONUNIQUE_OR_UNORDERED_DATES")
    if not rows or rows[-1]["trade_date"] != asof:
        raise InputBindingError("STALE_OR_MISSING_SIGNAL_BAR")
    window = rows[-120:]  # Same native 120-row request; cutoff precedes truncation.
    owner_identity, expected_window = verify_expected_window(manifest, binding, ts_code, window)
    identity = {
        "source_manifest_path": str(source.resolve()),
        "source_manifest_sha256": binding.source_manifest_sha256,
        "owner_source_identity": owner_identity,
        "producer_expected_window": expected_window,
        "signal_asof": asof, "selection_date": selection,
        "configuration_sha256": binding.configuration_sha256,
        "price_basis": binding.price_basis,
        "units": [binding.price_unit, binding.volume_unit, binding.amount_unit, binding.pct_chg_unit],
        "window_sha256": digest(window), "window_rows": len(window),
        "window_first_date": window[0]["trade_date"], "window_last_date": window[-1]["trade_date"],
        "context_availability": "EXPLICIT_ASOF_CONTEXT" if context is not None else "UNAVAILABLE_EXPLICIT_NEUTRAL",
        "context_sha256": digest(asdict(context)) if context is not None else digest(None),
    }
    identity["evaluation_identity_sha256"] = digest(identity)
    return window, identity


def evaluate_signal_window(ts_code, signal_window, selection_date, contexts, config, binding, *, evaluator=None):
    """Direct simulator caller boundary: use signal-date context, never entry-date context."""
    if binding is None or not signal_window:
        raise InputBindingError("BOUND_SIGNAL_WINDOW_REQUIRED")
    last = signal_window[-1]
    signal_date = last["trade_date"] if isinstance(last, Mapping) else last.trade_date
    if binding.signal_asof != signal_date or binding.selection_date != selection_date:
        raise InputBindingError("CALLER_WINDOW_BINDING_MISMATCH")
    if evaluator is None:
        from .signal_filter import evaluate_stock
        evaluator = evaluate_stock
    return evaluator(ts_code, signal_date, klines=signal_window, config=config,
        context=contexts.get(signal_date), input_binding=binding)
