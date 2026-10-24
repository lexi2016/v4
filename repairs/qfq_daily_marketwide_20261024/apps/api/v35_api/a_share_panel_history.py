"""Read one exact A-share history from the accepted default shared panel.

No collector, producer, indicator calculation or selectable artifact path.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re

VERSION = "ACTIVE_MA_USER_20261021_V1"
FORMULA_SHA = "924ab78f0adb0ee0705e41d7824282f40ec275a97da532ffee5b61e29d2925e6"
SIGNALS = tuple("user_v1_" + name for name in (
    "B1", "B2", "B3", "breakout", "breakout_cross_star", "three_quarter_yin_volume_line",
    "single_needle_under20", "break_prev_low", "under_yellow", "first_fly", "second_fly",
    "white_yellow_death_cross", "macd_golden_cross", "macd_below_zero_second_gold",
    "macd_above_zero_second_gold", "level1_buy_signal", "level2_buy_signal",
    "hold_yesterday_keyline_daily", "break_yesterday_keyline_daily",
    "hold_yesterday_keyline_display_asof", "break_yesterday_keyline_display_asof",
    "sell_signal_daily", "sell_signal_display_asof"))
COLUMNS = ("trade_date", "ts_code", "name", "market_type", "open", "high", "low", "close",
           "volume", "amount", "BBI", "zge_white_line", "zge_yellow_line", "ma60", "J",
           "macd_dif", "macd_dea", "macd_hist", *SIGNALS)
CODE_KEYS = ("driver_sha256", "formula_sha256", "adapter_sha256", "input_adapter_sha256",
             "factor_cache_sha256", "tdx_adapter_sha256", "user_formula_sha256", "field_contract_sha256")
META = b"a_share_qfq_contract_v1"


class Unconfirmed(RuntimeError):
    pass


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _json(path):
    raw = Path(path).read_bytes()
    return json.loads(raw), _sha_bytes(raw)


def _ref(ref):
    value, sha = _json(ref["path"])
    if sha != ref["sha256"]:
        raise Unconfirmed("ACCEPTANCE_REFERENCE_SHA_CONFLICT")
    return value


def _stat(path):
    s = path.stat()
    return {k: getattr(s, k) for k in ("st_dev", "st_ino", "st_size", "st_mtime_ns")}


@lru_cache(maxsize=8)
def _hash_new_generation_once(path, expected_sha, stat_tuple):
    """A later daily generation lacks the initial audit stat: hash once per stat.

    The original producer/convention gate remains the semantic authority. This
    cache only verifies file identity, never computes features or certification.
    """
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    # Cache a negative outcome too: lru_cache does not memoize exceptions.
    return h.hexdigest() == expected_sha


def _artifact_identity(path, sha, meta, receipt):
    observed = _stat(path)
    if receipt.get("generation_id") == meta["generation_id"]:
        report = _ref(receipt["independent_review"])
        if (report.get("verdict") != "REVIEWED/PASS_LOCAL_PANEL_HISTORY_CANDIDATE"
                or report.get("candidate_generation") != meta["generation_id"]
                or report.get("input_sha256") != meta["input_sha256"]
                or report.get("candidate_sha256", {}).get("selector") != sha):
            raise Unconfirmed("INDEPENDENT_CANDIDATE_ACCEPTANCE_CONFLICT")
        a = report["A_receipt"]
        audit = _ref(dict(path=a["report_path"], sha256=a["report_sha256"]))
        refs = [r for r in audit["evidence_paths"] if r["sha256"] == audit["identity"]["audit_input_binding_sha256"]]
        if len(refs) != 1:
            raise Unconfirmed("INDEPENDENT_STAT_BINDING_MISSING")
        bound = _ref(refs[0])["candidate_roles"]["selector"]
        if bound["path"] != str(path) or bound["sha256"] != sha or bound["stat_binding"] != observed:
            raise Unconfirmed("INDEPENDENT_ARTIFACT_STAT_CONFLICT")
        return observed, "INDEPENDENT_ACCEPTANCE_SHA_AND_UNCHANGED_STAT; NO_PAYLOAD_REHASH"
    if not _hash_new_generation_once(str(path), sha, tuple(observed.values())):
        raise Unconfirmed("ACCEPTED_ARTIFACT_SHA_CONFLICT")
    return observed, "ORIGINAL_DAILY_RECEIPT_AND_SHA_VERIFIED_ONCE_PER_ARTIFACT_STAT; NOT_NEW_SEMANTIC_REVIEW"


@contextmanager
def _read_lock(cache):
    # The original publisher owns this existing lock. API never creates it.
    with (cache / "qfq_publish.lock").open("rb") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Unconfirmed("PUBLICATION_IN_PROGRESS") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _request(code, start, end, version):
    if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", code):
        raise ValueError("ts_code must be an exact A-share code with .SH/.SZ/.BJ")
    for value in (start, end):
        if not re.fullmatch(r"\d{8}", value):
            raise ValueError("dates must use YYYYMMDD")
        datetime.strptime(value, "%Y%m%d")
    if start > end:
        raise ValueError("start_date must not exceed end_date")
    if version != VERSION:
        raise ValueError("unsupported formula_version")


def read_history(shared_data_root, code, start, end, version):
    _request(code, start, end, version)
    response = dict(schema_version="v4.a_share_original_formula_history.v1", ts_code=code,
                    start_date=start, end_date=end, formula_version=version, profile_id=version,
                    status="CANNOT_CONFIRM", rows=[], cannot_confirm=[], research_only=True,
                    production_allowed=False, buy_gate_updated=False, orders_sent=False)
    if shared_data_root is None:
        return {**response, "cannot_confirm": ["SHARED_DATA_ROOT_NOT_CONFIGURED"]}
    root = Path(shared_data_root)
    cache = root / "runtime/cache/data_layer_daily_formula_increment_update_v1"
    pointer = root / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt"
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        with _read_lock(cache):
            pointer_bytes = pointer.read_bytes()
            path = Path(pointer_bytes.decode("utf-8-sig").strip())
            expected, _ = _json(cache / "qfq_expected_current.json")
            bound = expected["roles"]["selector"]
            if (expected.get("schema") != "qfq_expected_current_v1" or bound["pointer_path"] != str(pointer)
                    or bound["pointer_sha256"] != _sha_bytes(pointer_bytes) or bound["target_path"] != str(path)):
                raise Unconfirmed("DEFAULT_POINTER_ACCEPTANCE_CONFLICT")
            pf = pq.ParquetFile(path)
            meta = json.loads((pf.schema_arrow.metadata or {})[META])
            if int(end) > meta["asof_date"]:
                raise Unconfirmed("REQUEST_END_AFTER_ACCEPTED_PANEL_ASOF")
            formula = meta["user_formula_contract"]
            if (formula.get("version") != VERSION or formula.get("source_sha256") != FORMULA_SHA
                    or meta.get("user_formula_sha256") != FORMULA_SHA
                    or formula.get("signal_fields") != list(SIGNALS)
                    or formula.get("level1") != "B3 OR STRICT_ABOVE_ZERO_SECOND_GOLD"
                    or not set(COLUMNS).issubset(pf.schema_arrow.names)):
                raise Unconfirmed("ORIGINAL_FORMULA_NAMESPACE_UNCONFIRMED")
            manifest, manifest_sha = _json(meta["generation_manifest_path"])
            if (manifest.get("generation_id") != meta["generation_id"]
                    or manifest.get("input_sha256") != meta["input_sha256"]
                    or manifest["candidates"]["selector"] != str(path)
                    or manifest["candidate_sha256"]["selector"] != bound["target_sha256"]):
                raise Unconfirmed("PRODUCER_MANIFEST_IDENTITY_CONFLICT")
            convention, _ = _json(cache / "qfq_convention_acceptance.json")
            receipt = _ref(convention["initial_oracle_receipt"])
            binding = {k: meta[k] for k in CODE_KEYS}
            if (convention.get("status") != "PASS" or not convention.get("reviewer_id")
                    or convention.get("code_binding") != binding or receipt.get("code_binding") != binding
                    or convention.get("convention") != meta.get("convention")
                    or receipt.get("status") != "PASS_FUTU_DISPLAY_ORACLE"
                    or receipt.get("asof_date") != convention.get("initial_asof_date")
                    or meta["asof_date"] < convention["initial_asof_date"]):
                raise Unconfirmed("INDEPENDENT_FORMULA_CONVENTION_CONFLICT")
            observed, verification = _artifact_identity(path, bound["target_sha256"], meta, receipt)
            # Reuse the original shared reader, pinned to its resolved default
            # pointer during this request; no browser-supplied path is accepted.
            reader_path = pointer.with_name("DATA_LAYER_INTERFACE.py")
            spec = importlib.util.spec_from_file_location("a_share_default_history_reader", reader_path)
            reader = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(reader)
            kind = pf.schema_arrow.field("trade_date").type
            cast = str if pa.types.is_string(kind) or pa.types.is_large_string(kind) else int
            frame = reader.load_selector_ready(columns=list(COLUMNS), start_date=start, end_date=end,
                ts_codes=[code], filters=[("ts_code", "=", code), ("trade_date", ">=", cast(start)),
                                         ("trade_date", "<=", cast(end))], panel_path=path, profile=None)
            if (pointer.read_bytes() != pointer_bytes or _stat(path) != observed):
                raise Unconfirmed("DEFAULT_ARTIFACT_CHANGED_DURING_READ")
            if len(frame) > 20000 or frame[["ts_code", "trade_date"]].duplicated().any():
                raise Unconfirmed("EXACT_HISTORY_ROW_CONTRACT_CONFLICT")
            if not frame.empty:
                dates = frame.trade_date.astype(str)
                if (not frame.ts_code.eq(code).all() or not frame.market_type.eq("A_SHARE").all()
                        or not dates.between(start, end).all() or frame[list(SIGNALS)].isna().any().any()):
                    raise Unconfirmed("EXACT_HISTORY_OR_LABEL_COVERAGE_CONFLICT")
            frame = frame.sort_values("trade_date")
            rows = json.loads(frame.to_json(orient="records"))
            if not rows:
                excluded = _ref(manifest["quarantine_manifest"]) if manifest.get("quarantine_manifest") else {}
                if code in excluded.get("reasons", {}):
                    raise Unconfirmed("ORIGINAL_QUARANTINE:" + str(excluded["reasons"][code]))
                if meta.get("legacy_preservation_policy"):
                    legacy = _ref(meta["legacy_preservation_policy"])
                    if code in legacy.get("codes", []):
                        raise Unconfirmed("EXCLUDED_LEGACY_IDENTITY_OR_BASIS_UNCONFIRMED")
            for row in rows:
                row["trade_date"] = str(row["trade_date"])
            return {**response, "status": "READY" if rows else "EMPTY_EXACT_RANGE", "rows": rows,
                "columns": list(COLUMNS), "identity": dict(generation_id=meta["generation_id"],
                    input_sha256=meta["input_sha256"], manifest_sha256=manifest_sha,
                    artifact_sha256=bound["target_sha256"], formula_source_sha256=FORMULA_SHA,
                    user_formula_contract=formula, verification_basis=verification, artifact_stat=observed,
                    asof_date=meta["asof_date"], historical_PIT=False, maximum_claim="DIRECTION_ONLY",
                    reader_source_sha256=_sha_bytes(reader_path.read_bytes()))}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
        return {**response, "cannot_confirm": [str(error) or type(error).__name__]}
