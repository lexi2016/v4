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
import os
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
LIFECYCLE_NOTES_SHA256 = "c16581545c456c04444da16ca631ab8978e41010d3f455bc787e171e48e9e54a"
EMPTY_LIFECYCLE_NOTE_CODES = {"601198.SH", "601059.SH", "832317.BJ", "688287.SH", "833874.BJ", "833994.BJ",
                            "000016.SZ", "920680.BJ", "920305.BJ", "600193.SH"}
DIRECT_KIND = "FUTU_SDK_DIRECT_QFQ_20261026_EXACT76"
DIRECT_UNIVERSE_SHA = "1ae84f8a90b6f54df4e1c29fb2a65e4fa2a3b9bb98dce1df449f22ed0bfa0962"
DIRECT_ADMISSION = "futu_direct_qfq76_admission.json"
SINGLE_QFQ_KIND = "FUTU_SDK_DIRECT_QFQ_SINGLE_SYMBOL"
SINGLE_QFQ_SCHEMA = "futu_direct_qfq_single_symbol_candidate.v1"
SINGLE_QFQ_META = b"futu_direct_qfq_single_symbol_v1"
NUMERIC283_CHART_PROFILE = "V4_DAILY_NUMERIC283_CHART_20261029_R1"
NUMERIC283_START_DATE = "20260101"
NUMERIC283_END_DATE = "20261028"
NUMERIC283_SOURCE_GENERATION = "31d40c5900ced1b2ff637cfbeaa73688ad921d713e3ea748f83ccbca84463c29"
NUMERIC283_SOURCE_ARTIFACT_SHA256 = "28e577a67e5b5b00a04ac181632d7e1e4e6cc0e4f34e1283f69d28896ec893fb"
NUMERIC283_LIST_SHA256 = "6c8f5ed6f46db818c3943deda02b78d3e04441c9f5630d290f56bb62e1c58dea"
NUMERIC283_SOURCE_CSV_SHA256 = "55a65b75d3a03fd767a44d61da8d3d909cbe6c37450fe9796d82980a99a4fefe"
NUMERIC283_SIGNAL_NAMESPACE = "ACTIVE_MA_USER_20261021_V1"


def _unique_json_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Unconfirmed("SINGLE_QFQ_AMBIGUOUS_JSON_KEY:" + key)
        value[key] = item
    return value


def _strict_single_ref(reference):
    path = Path(reference["path"])
    expected = reference["sha256"]
    if (not path.is_absolute() or path.is_symlink() or not isinstance(expected, str)
            or not re.fullmatch("[a-f0-9]{64}", expected)):
        raise Unconfirmed("SINGLE_QFQ_REFERENCE_CONFLICT")
    raw = path.read_bytes()
    if _sha_bytes(raw) != expected:
        raise Unconfirmed("SINGLE_QFQ_REFERENCE_SHA_CONFLICT")
    return json.loads(raw, object_pairs_hook=_unique_json_object)


def _single_symbol_direct_qfq_rows(root, candidate, code, start, end, manifest_sha):
    """Read one reviewed27day capture; original73 retain their legacy reader."""
    import pyarrow.parquet as pq
    source_sha = candidate["source"]["sha256"]
    first, row_count = candidate.get("history_start_date"), candidate.get("row_count")
    if (not re.fullmatch(r"\d{6}\.(SH|SZ)", code) or not isinstance(source_sha, str)
            or not re.fullmatch("[a-f0-9]{64}", source_sha) or not isinstance(first, str)
            or not re.fullmatch(r"\d{8}", first) or type(row_count) is not int or not 1 <= row_count <= 20000):
        raise Unconfirmed("SINGLE_QFQ_SOURCE_IDENTITY_CONFLICT")
    datetime.strptime(first, "%Y%m%d")
    if (candidate.get("schema") != SINGLE_QFQ_SCHEMA or candidate.get("source_kind") != SINGLE_QFQ_KIND
            or candidate.get("ts_code") != code or candidate.get("asof_date") != "20261027"
            or candidate.get("history_start_date") != first or candidate.get("row_count") != row_count
            or not first <= start <= end <= "20261027"
            or candidate.get("adjustment_anchor") != "UNKNOWN_NONPIT"
            or candidate.get("volume_basis") != "FUTU_SDK_NATIVE_UNSCALED"
            or candidate.get("amount_basis") != "FUTU_SDK_TURNOVER_UNSCALED"
            or candidate.get("formula_version") != VERSION
            or candidate.get("formula_sha256") != FORMULA_SHA
            or candidate.get("canonical_formula_sha256") != "074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258"
            or candidate.get("signal_fields") != list(SIGNALS)
            or candidate.get("research_only") is not True
            or any(candidate.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise Unconfirmed("SINGLE_QFQ_COORDINATE_OR_PREFIX_CONFLICT")
    for reference in (candidate["source"], candidate["artifact"]):
        path = Path(reference["path"])
        observed = _stat(path)
        if not _hash_new_generation_once(str(path), reference["sha256"], tuple(observed.values())):
            raise Unconfirmed("SINGLE_QFQ_SOURCE_OR_ARTIFACT_SHA_CONFLICT")
    path = Path(candidate["artifact"]["path"])
    observed = _stat(path)
    parquet = pq.ParquetFile(path)
    metadata = json.loads(parquet.schema_arrow.metadata[SINGLE_QFQ_META], object_pairs_hook=_unique_json_object)
    expected = dict(source_kind=SINGLE_QFQ_KIND, ts_code=code, asof_date="20261027", history_start_date=first,
                    input_sha256=source_sha, row_count=row_count,
                    original_producer_sha256="b4f86bb7c383ef9c1240197b9f75a28bde2fbaa04f7ff1a55008ec4913ed9ebd",
                    canonical_formula_sha256=candidate["canonical_formula_sha256"], user_formula_sha256=FORMULA_SHA,
                    adjustment_anchor="UNKNOWN_NONPIT", volume_basis="FUTU_SDK_NATIVE_UNSCALED", amount_basis="FUTU_SDK_TURNOVER_UNSCALED",
                    research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
    if (metadata != candidate["artifact_metadata"] or any(metadata.get(k) != value for k, value in expected.items())
            or parquet.metadata.num_rows != row_count):
        raise Unconfirmed("SINGLE_QFQ_METADATA_CONFLICT")
    reader_path = root / "data_layer_interface_current/DATA_LAYER_INTERFACE.py"
    if (candidate["reader"]["path"] != str(reader_path) or candidate["reader"]["sha256"] != "5fd9024fc4ee858a62eaac050532187b171289eac82837bc7ca406e938509ded"
            or _sha_bytes(reader_path.read_bytes()) != candidate["reader"]["sha256"]):
        raise Unconfirmed("SINGLE_QFQ_ORIGINAL_READER_CONFLICT")
    spec = importlib.util.spec_from_file_location("a_share_single_symbol_direct_reader", reader_path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    frame = reader.load_selector_ready(columns=list(COLUMNS), start_date=start, end_date=end,
        ts_codes=[code], filters=[("ts_code", "=", code), ("trade_date", ">=", int(start)),
                                 ("trade_date", "<=", int(end))], panel_path=path, profile=None)
    if (_stat(path) != observed or frame[["ts_code", "trade_date"]].duplicated().any()
            or not frame.ts_code.eq(code).all() or not frame.market_type.eq("A_SHARE").all()
            or not frame.trade_date.astype(str).between(start, end).all()
            or frame[list(SIGNALS)].isna().any().any()
            or not frame[list(SIGNALS)].isin([0, 1]).all().all()):
        raise Unconfirmed("SINGLE_QFQ_READER_ROWS_CONFLICT")
    rows = json.loads(frame.sort_values("trade_date").to_json(orient="records", double_precision=15))
    for row in rows:
        row["trade_date"] = str(row["trade_date"])
    generation = _sha_bytes(json.dumps(metadata, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode())
    return dict(status="READY" if rows else "EMPTY_EXACT_RANGE", rows=rows, columns=list(COLUMNS), profile_id=VERSION,
        identity=dict(source_kind=SINGLE_QFQ_KIND, generation_id=generation, input_sha256=source_sha,
            manifest_sha256=manifest_sha, artifact_sha256=candidate["artifact"]["sha256"],
            formula_source_sha256=FORMULA_SHA, canonical_formula_source_sha256=candidate["canonical_formula_sha256"],
            asof_date=20261027, history_start_date=first, adjustment_anchor="UNKNOWN_NONPIT", historical_PIT=False,
            maximum_claim="DIRECTION_ONLY", volume_basis="FUTU_SDK_NATIVE_UNSCALED", amount_basis="FUTU_SDK_TURNOVER_UNSCALED",
            reader_source_sha256=candidate["reader"]["sha256"], artifact_stat=observed,
            verification_basis="SINGLE_REVIEWED_SDK_CAPTURE; ORIGINAL_FORMULA; NATIVE_VOLUME_AND_TURNOVER; ASOF_20261027; UNKNOWN_NONPIT"))


def _direct_qfq_rows(root, candidate, code, start, end):
    """Read a typed candidate with the original reader and exact formula fields.

    The full request must fit this single captured prefix and vintage. There is
    no fallback to another adjustment coordinate for an admitted symbol.
    """
    import csv
    import io
    import pyarrow.parquet as pq
    if (candidate.get("schema") != "futu_direct_qfq76_consumer_candidate_v1"
            or candidate.get("source_kind") != DIRECT_KIND
            or candidate.get("asof_date") != "20261026"
            or candidate.get("adjustment_anchor") != "UNKNOWN_NONPIT"
            or candidate.get("volume_basis") != "FUTU_SDK_NATIVE_UNSCALED"
            or candidate.get("amount_basis") != "FUTU_SDK_TURNOVER_UNSCALED"
            or candidate.get("formula_sha256") != "074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258"
            or candidate.get("user_formula_sha256") != FORMULA_SHA
            or candidate.get("signal_fields") != list(SIGNALS)
            or candidate.get("research_only") is not True
            or any(candidate.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
        raise Unconfirmed("DIRECT_QFQ_CANDIDATE_COORDINATE_CONFLICT")
    universe = candidate["universe"]
    raw = Path(universe["path"]).read_bytes()
    if _sha_bytes(raw) != DIRECT_UNIVERSE_SHA or universe["sha256"] != DIRECT_UNIVERSE_SHA:
        raise Unconfirmed("DIRECT_QFQ_EXACT76_UNIVERSE_CONFLICT")
    records = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    allowed = {r["ts_code"] for r in records}
    entries = candidate["symbols"]
    if (len(records) != 76 or len(allowed) != 76 or not entries or not set(entries).issubset(allowed)
            or code not in entries):
        raise Unconfirmed("DIRECT_QFQ_SYMBOL_SCOPE_CONFLICT")
    item = entries[code]
    if not item["history_start_date"] <= start <= end <= candidate["asof_date"]:
        raise Unconfirmed("DIRECT_QFQ_REQUEST_OUTSIDE_CAPTURED_PREFIX_OR_VINTAGE")
    for ref in (candidate["artifact"], item["source"]):
        path = Path(ref["path"])
        stat = _stat(path)
        if not _hash_new_generation_once(str(path), ref["sha256"], tuple(stat.values())):
            raise Unconfirmed("DIRECT_QFQ_ARTIFACT_OR_SOURCE_SHA_CONFLICT")
    path = Path(candidate["artifact"]["path"])
    before = _stat(path)
    metadata = json.loads(pq.ParquetFile(path).schema_arrow.metadata[b"futu_direct_qfq76_v1"])
    if metadata != candidate["artifact_metadata"] or metadata.get("source_kind") != DIRECT_KIND:
        raise Unconfirmed("DIRECT_QFQ_ARTIFACT_METADATA_CONFLICT")
    reader_path = root / "data_layer_interface_current/DATA_LAYER_INTERFACE.py"
    spec = importlib.util.spec_from_file_location("a_share_direct_history_reader", reader_path)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    if _sha_bytes(reader_path.read_bytes()) != candidate["reader_sha256"]:
        raise Unconfirmed("DIRECT_QFQ_READER_SOURCE_DRIFT")
    frame = reader.load_selector_ready(columns=list(COLUMNS), start_date=start, end_date=end,
        ts_codes=[code], filters=[("ts_code", "=", code), ("trade_date", ">=", int(start)),
                                 ("trade_date", "<=", int(end))], panel_path=path, profile=None)
    if _stat(path) != before or len(frame) > 20000:
        raise Unconfirmed("DIRECT_QFQ_CHANGED_OR_EXCESSIVE_RANGE")
    if (frame[["ts_code", "trade_date"]].duplicated().any() or not frame.ts_code.eq(code).all()
            or not frame.market_type.eq("A_SHARE").all()
            or not frame.trade_date.astype(str).between(start, end).all()
            or frame[list(SIGNALS)].isna().any().any()):
        raise Unconfirmed("DIRECT_QFQ_EXACT_HISTORY_OR_LABEL_CONFLICT")
    rows = json.loads(frame.sort_values("trade_date").to_json(orient="records", double_precision=15))
    for row in rows:
        row["trade_date"] = str(row["trade_date"])
    manifest_sha = _sha_bytes((json.dumps(candidate, sort_keys=True, ensure_ascii=False,
        indent=2, allow_nan=False) + "\n").encode())
    generation_id = _sha_bytes(json.dumps(metadata, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode())
    return dict(status="READY" if rows else "EMPTY_EXACT_RANGE", rows=rows, columns=list(COLUMNS), profile_id=VERSION,
        identity=dict(source_kind=DIRECT_KIND, input_sha256=item["source"]["sha256"],
            generation_id=generation_id, manifest_sha256=manifest_sha,
            source=item["source"], artifact_sha256=candidate["artifact"]["sha256"],
            formula_source_sha256=FORMULA_SHA, canonical_formula_source_sha256=candidate["formula_sha256"],
            user_formula_source_sha256=FORMULA_SHA,
            asof_date=20261026, adjustment_anchor="UNKNOWN_NONPIT", historical_PIT=False,
            maximum_claim="DIRECTION_ONLY", volume_basis=candidate["volume_basis"],
            amount_basis=candidate["amount_basis"], history_start_date=item["history_start_date"],
            reader_source_sha256=candidate["reader_sha256"], artifact_stat=before,
            verification_basis="FUTU_SDK_DIRECT_QFQ_CAPTURE; ORIGINAL_FORMULA; SDK_VOLUME_UNSCALED; "
                "ASOF_20261026; UNKNOWN_NONPIT; SINGLE_CAPTURED_PREFIX; DEFAULT_PANEL_PRESERVED"))


def _admitted_direct_qfq(root, cache, code, start, end):
    admission_path = cache / DIRECT_ADMISSION
    if not admission_path.exists():
        return None
    admission, _ = _json(admission_path)
    if admission.get("schema") == "futu_direct_qfq76_admission_v2":
        # v1 keeps its original parser/behavior. New dynamic references refuse
        # duplicate JSON keys and non-absolute or symlink manifest locators.
        admission = _strict_single_ref(dict(path=str(admission_path), sha256=_sha_bytes(admission_path.read_bytes())))
        overrides = admission.get("symbol_overrides")
        legacy = admission.get("legacy_admission")
        if (admission.get("status") != "REVIEWED_READY" or not isinstance(overrides, dict)
                or not overrides or not isinstance(legacy, dict)
                or legacy.get("schema") != "futu_direct_qfq76_admission_v1"
                or admission.get("research_only") is not True
                or any(admission.get(k) is not False for k in ("production_allowed", "buy_gate_updated", "orders_sent"))):
            raise Unconfirmed("SINGLE_QFQ_ADMISSION_V2_CONFLICT")
        legacy_candidate = _ref(legacy["candidate"])
        legacy_review = _ref(legacy["independent_review"])
        if (legacy_review.get("verdict") != "PASS_FUTU76_MAC_PRICE_SIGNAL_DISPLAY_CANDIDATE"
                or legacy_review.get("candidate_manifest_sha256") != legacy["candidate"]["sha256"]
                or not legacy_review.get("reviewer_id") or legacy_candidate.get("source_kind") != DIRECT_KIND
                or legacy_candidate.get("asof_date") != "20261026"):
            raise Unconfirmed("SINGLE_QFQ_LEGACY_SCOPE_REVIEW_REQUIRED")
        import csv
        import io
        universe = legacy_candidate["universe"]
        raw = Path(universe["path"]).read_bytes()
        if universe["sha256"] != DIRECT_UNIVERSE_SHA or _sha_bytes(raw) != DIRECT_UNIVERSE_SHA:
            raise Unconfirmed("SINGLE_QFQ_LEGACY_UNIVERSE_CONFLICT")
        records = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
        allowed = {row["ts_code"] for row in records}
        if (len(records) != 76 or len(allowed) != 76 or set(legacy_candidate["symbols"]) != allowed
                or not set(overrides).issubset(allowed)):
            raise Unconfirmed("SINGLE_QFQ_OVERRIDE_ALLOWLIST_CONFLICT")
        if code in overrides:
            selected = overrides[code]
            candidate = _strict_single_ref(selected["candidate"])
            review = _strict_single_ref(selected["independent_review"])
            reviewed = review.get("per_symbol_candidates", {}).get(code)
            expected_reviewed = dict(candidate_manifest_sha256=selected["candidate"]["sha256"],
                source_sha256=candidate["source"]["sha256"], artifact_sha256=candidate["artifact"]["sha256"])
            if (review.get("verdict") != "PASS" or not review.get("reviewer_id") or reviewed != expected_reviewed):
                raise Unconfirmed("SINGLE_QFQ_INDEPENDENT_REVIEW_REQUIRED")
            return _single_symbol_direct_qfq_rows(root, candidate, code, start, end, selected["candidate"]["sha256"])
        # The complete reviewed legacy object is retained. Nothing in the
        # new per-code payload is read for the other73 or default symbols.
        admission = legacy
    candidate = _ref(admission["candidate"])
    # A malformed global binding fails closed. Unselected symbols continue the
    # original default path without reading the candidate payload.
    if admission.get("schema") != "futu_direct_qfq76_admission_v1":
        raise Unconfirmed("DIRECT_QFQ_ADMISSION_SCHEMA_CONFLICT")
    if code not in candidate.get("symbols", {}):
        return None
    review = _ref(admission["independent_review"])
    if (review.get("verdict") != "PASS_FUTU76_MAC_PRICE_SIGNAL_DISPLAY_CANDIDATE"
            or review.get("candidate_manifest_sha256") != admission["candidate"]["sha256"]
            or not review.get("reviewer_id")):
        raise Unconfirmed("DIRECT_QFQ_INDEPENDENT_ACCEPTANCE_REQUIRED")
    return _direct_qfq_rows(root, candidate, code, start, end)


def _profile_direct_qfq(root, cache, code, start, end, *, numeric283_chart):
    """The numeric283 chart uses the frozen selector only; other profiles keep the overlay."""
    if numeric283_chart:
        return None
    return _admitted_direct_qfq(root, cache, code, start, end)


def _with_pending_status_note(response):
    # Exact exception only. Zero turnover is never a general suspension rule.
    if response.get("ts_code") != "688496.SH" or response.get("end_date", "") < "20260911":
        return response
    reason = "SUSPENSION_EVIDENCE_BINDING_UNAVAILABLE"
    fact, expired = None, False
    try:
        raw = Path(__file__).with_name("a_share_lifecycle_notes.json").read_bytes()
        if _sha_bytes(raw) != LIFECYCLE_NOTES_SHA256:
            raise ValueError("pending evidence binding drift")
        asset = json.loads(raw)
        matches = [row for row in asset.get("pending_trading_status", []) if row.get("ts_code") == "688496.SH"]
        if len(matches) != 1:
            raise ValueError("pending evidence missing or ambiguous")
        fact = matches[0]
        if (fact.get("verified_suspension_start") is not True or fact.get("suspension_start_date") != "20260911"
                or not fact.get("official_source_refs")):
            raise ValueError("pending source unconfirmed")
        resumed = fact.get("resumption_effective_date")
        if fact.get("resumption_verified") is True and fact.get("resumption_source_refs"):
            datetime.strptime(resumed, "%Y%m%d")
            if resumed >= "20260911" and response["start_date"] >= resumed:
                return response
        asof = fact["status_verification_asof_date"]
        datetime.strptime(asof, "%Y%m%d")
        expired = response["end_date"] > asof
        reason = "SUSPENSION_SOURCE_STALE_REVERIFY_REQUIRED" if expired else "SUSPENSION_PENDING_RESUMPTION_VERIFICATION"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    errors = response.get("cannot_confirm")
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        errors = []
    note = reason + "：已核停牌起点2026-09-11；查询包含未核实复牌/交易状态的日期，需重新绑定官方证据；原数据及历史错误保留，未确认永久停牌或摘牌"
    if response.get("status_verification", {}).get("reason_code") == reason and note in errors:
        return response
    return {**response, "status": "CANNOT_CONFIRM", "rows": [],
        "cannot_confirm": [*errors, *([] if note in errors else [note])],
        "quarantined_original_row_count": response.get("quarantined_original_row_count", len(response.get("rows", []))),
        "status_verification": dict(reason_code=reason, evidence_expired=expired, current_suspension_verified=False,
            source_asset_sha256=LIFECYCLE_NOTES_SHA256, fact=fact, historical_PIT=False,
            required_next_action="BIND_OFFICIAL_RESUMPTION_OR_TERMINATION_EVIDENCE_AND_REVIEW")}


def _with_post_termination_rows(response):
    # Exact saved-source evidence:20 post-effective rows for each old BJ code.
    # The other newly audited codes have no such observed rows and keep their
    # original READY behavior. A query containing only earlier rows is unchanged.
    affected = {"832317.BJ": "20220426", "833874.BJ": "20220718", "833994.BJ": "20220725"}
    code, rows = response.get("ts_code"), response.get("rows")
    day = affected.get(code)
    if not day or response.get("status") != "READY" or not isinstance(rows, list):
        return response
    offending = [row for row in rows if isinstance(row, dict)
        and re.fullmatch(r"\d{8}", str(row.get("trade_date", ""))) and str(row["trade_date"]) >= day]
    if not offending:
        return response
    fact, bound = None, False
    try:
        raw = Path(__file__).with_name("a_share_lifecycle_notes.json").read_bytes()
        if _sha_bytes(raw) != LIFECYCLE_NOTES_SHA256:
            raise ValueError("termination evidence binding drift")
        asset = json.loads(raw)
        matches = [row for row in asset["verified_delistings"] if row["ts_code"] == code and row.get("verified") is True]
        if len(matches) == 1 and matches[0].get("delisting_effective_date") == day:
            fact, bound = matches[0], True
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    reason = "POST_TERMINATION_SOURCE_ROWS_QUARANTINED" if bound else "POST_TERMINATION_EVIDENCE_BINDING_UNAVAILABLE"
    note = reason + f"：原{code}市场上市终止日{day}；返回行含该日或之后记录，原行与源身份仅保留诊断，不作为有效当前交易K线"
    errors = response.get("cannot_confirm", [])
    return {**response, "status": "CANNOT_CONFIRM", "rows": [],
        "quarantined_original_rows": rows, "cannot_confirm": [*errors, note],
        "status_verification": dict(reason_code=reason, effective_date=day, affected_row_count=len(offending),
            original_row_count=len(rows), original_status="READY", fact=fact, evidence_bound=bound,
            source_asset_sha256=LIFECYCLE_NOTES_SHA256, historical_PIT=False)}


def _with_lifecycle_note(response):
    """Pinned notes plus the two explicitly scoped status-quarantine cases."""
    if response.get("status_verification", {}).get("reason_code", "").startswith("POST_TERMINATION_"):
        return response
    pending = _with_pending_status_note(response)
    if pending is not response:
        return pending
    post_termination = _with_post_termination_rows(response)
    if post_termination is not response:
        return post_termination
    verified_empty_note = (response.get("status") == "EMPTY_EXACT_RANGE"
                           and response.get("ts_code") in EMPTY_LIFECYCLE_NOTE_CODES)
    if (response.get("status") != "CANNOT_CONFIRM" and not verified_empty_note) or response.get("rows") != []:
        return response
    errors = response.get("cannot_confirm")
    if not isinstance(errors, list) or not all(isinstance(item, str) for item in errors):
        return response
    try:
        raw = Path(__file__).with_name("a_share_lifecycle_notes.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != LIFECYCLE_NOTES_SHA256:
            return response
        asset = json.loads(raw)
        if asset["schema_version"] != "a_share_lifecycle_notes.v1":
            return response
        facts = [item for item in asset["verified_delistings"]
                 if item["ts_code"] == response["ts_code"] and item.get("verified") is True]
        if len(facts) != 1:
            return response
        fact = facts[0]
        day = fact["delisting_effective_date"]
        datetime.strptime(day, "%Y%m%d")
        start, end = response["start_date"], response["end_date"]
        if not re.fullmatch(r"\d{8}", day) or not day <= start <= end:
            return response
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return response
    label = "官方原市场终止上市日期" if fact.get("event_type") == "MARKET_TRANSFER_TERMINATION" else "官方摘牌日期"
    note = (f"{label}：{day[:4]}-{day[4:6]}-{day[6:]}；"
            "本窗口已在摘牌日及之后，无需补上市交易K线；原数据状态及拒绝原因保留")
    if fact.get("source_quality") == "issuer_mirror__original_exchange_bytes_unverified":
        note += "；本地依据为发行人公告镜像，原交易所文件字节未核实"
    elif fact.get("source_quality") == "CONFIRMED_WITH_MIRROR_PROVENANCE_CAVEAT":
        note += "；本地依据含主办券商公告第三方镜像及交叉核证，未读取官方PDF原字节"
    if any(item.startswith("ORIGINAL_QUARANTINE:") for item in errors):
        note += "；原隔离条目为存量记录，发生日期未确认"
    if verified_empty_note and note in errors:
        return response
    return {**response, "cannot_confirm": [*errors, note]}


class Unconfirmed(RuntimeError):
    pass


def _numeric283_duplicate_key_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Unconfirmed("NUMERIC283_SCOPE_DUPLICATE_JSON_KEY:" + key)
        value[key] = item
    return value


def _numeric283_scope_symbols():
    configured_root = os.environ.get("V4_RESEARCH_PANEL_ROOT")
    if not configured_root:
        raise Unconfirmed("NUMERIC283_STATIC_ROOT_NOT_CONFIGURED")
    root = Path(configured_root).expanduser()
    if not root.is_absolute() or ".." in root.parts or root.is_symlink():
        raise Unconfirmed("NUMERIC283_STATIC_ROOT_UNSAFE")
    path = root / "numeric283-candidates.json"
    if path.is_symlink() or not path.is_file():
        raise Unconfirmed("NUMERIC283_SCOPE_ARTIFACT_MISSING")
    raw = path.read_bytes()
    if len(raw) > 2_000_000 or _sha_bytes(raw) != NUMERIC283_LIST_SHA256:
        raise Unconfirmed("NUMERIC283_SCOPE_ARTIFACT_SHA_CONFLICT")
    payload = json.loads(raw, object_pairs_hook=_numeric283_duplicate_key_object)
    if not isinstance(payload, dict):
        raise Unconfirmed("NUMERIC283_SCOPE_ARTIFACT_IDENTITY_CONFLICT")
    rows = payload.get("rows")
    if (payload.get("schema_version") != "v4.numeric283.daily.v1"
            or payload.get("data_date") != NUMERIC283_END_DATE
            or payload.get("observation_date") != "20261029"
            or payload.get("source_generation") != NUMERIC283_SOURCE_GENERATION
            or payload.get("source_csv_sha256") != NUMERIC283_SOURCE_CSV_SHA256
            or payload.get("unique_count") != 283 or not isinstance(rows, list) or len(rows) != 283):
        raise Unconfirmed("NUMERIC283_SCOPE_ARTIFACT_IDENTITY_CONFLICT")
    symbols = []
    for row in rows:
        symbol = row.get("symbol") if isinstance(row, dict) else None
        if not isinstance(symbol, str) or not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", symbol):
            raise Unconfirmed("NUMERIC283_SCOPE_SYMBOL_INVALID")
        symbols.append(symbol)
    if len(set(symbols)) != 283:
        raise Unconfirmed("NUMERIC283_SCOPE_MEMBERSHIP_NOT_UNIQUE")
    return frozenset(symbols)


def _numeric283_response(code, start, end):
    return dict(schema_version="v4.a_share_numeric283_chart.v1", ts_code=code,
        start_date=start, end_date=end, formula_version=NUMERIC283_CHART_PROFILE,
        profile_id=NUMERIC283_CHART_PROFILE, signal_namespace=NUMERIC283_SIGNAL_NAMESPACE,
        status="CANNOT_CONFIRM", rows=[], cannot_confirm=[], research_only=True,
        production_allowed=False, buy_gate_updated=False, orders_sent=False)


def _numeric283_finalize(response, code):
    if response.get("status") == "EMPTY_EXACT_RANGE":
        return {**response, "status": "CANNOT_CONFIRM", "rows": [],
            "cannot_confirm": [*response.get("cannot_confirm", []), "NUMERIC283_TARGET_D28_ROW_MISSING"]}
    if response.get("status") != "READY":
        return response
    identity = response.get("identity")
    rows = response.get("rows")
    if (not isinstance(identity, dict)
            or identity.get("generation_id") != NUMERIC283_SOURCE_GENERATION
            or identity.get("artifact_sha256") != NUMERIC283_SOURCE_ARTIFACT_SHA256
            or identity.get("asof_date") != 20261028
            or not isinstance(rows, list) or not rows
            or any(not isinstance(row, dict) for row in rows)
            or rows[-1].get("trade_date") != NUMERIC283_END_DATE
            or any(row.get("ts_code") != code or not NUMERIC283_START_DATE <= row.get("trade_date", "") <= NUMERIC283_END_DATE for row in rows)):
        return {**response, "status": "CANNOT_CONFIRM", "rows": [],
            "cannot_confirm": [*response.get("cannot_confirm", []), "NUMERIC283_SOURCE_BINDING_OR_D28_RANGE_CONFLICT"]}
    return {**response, "signal_namespace": NUMERIC283_SIGNAL_NAMESPACE,
        "identity": {**identity, "profile_namespace": NUMERIC283_SIGNAL_NAMESPACE,
            "numeric283_scope_count": 283, "numeric283_source_generation": NUMERIC283_SOURCE_GENERATION,
            "numeric283_source_artifact_sha256": NUMERIC283_SOURCE_ARTIFACT_SHA256}}


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
    if version == "R19_FROZEN_151_20261027":
        _request(code, start, end, VERSION)
        from apps.api.v4_api.a_share_r19_profile import read_profile
        response = dict(schema_version="v4.a_share_original_formula_history.v1", ts_code=code,
            start_date=start, end_date=end, formula_version=version, profile_id=version,
            status="CANNOT_CONFIRM", rows=[], cannot_confirm=[])
        return read_profile(shared_data_root, code, start, end, response)
    numeric283_chart = version == NUMERIC283_CHART_PROFILE
    if numeric283_chart:
        _request(code, start, end, VERSION)
        response = _numeric283_response(code, start, end)
        if start != NUMERIC283_START_DATE or end != NUMERIC283_END_DATE:
            return {**response, "cannot_confirm": ["NUMERIC283_EXACT_20260101_20261028_RANGE_REQUIRED"]}
        try:
            scope = _numeric283_scope_symbols()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
            return {**response, "cannot_confirm": [str(error) or type(error).__name__]}
        if code not in scope:
            return {**response, "cannot_confirm": ["NUMERIC283_SYMBOL_OUTSIDE_PINNED_SCOPE"]}
    else:
        _request(code, start, end, version)
        response = dict(schema_version="v4.a_share_original_formula_history.v1", ts_code=code,
                        start_date=start, end_date=end, formula_version=version, profile_id=version,
                        status="CANNOT_CONFIRM", rows=[], cannot_confirm=[], research_only=True,
                        production_allowed=False, buy_gate_updated=False, orders_sent=False)
    if shared_data_root is None:
        return _with_lifecycle_note({**response, "cannot_confirm": ["SHARED_DATA_ROOT_NOT_CONFIGURED"]})
    root = Path(shared_data_root)
    cache = root / "runtime/cache/data_layer_daily_formula_increment_update_v1"
    pointer = root / "data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt"
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        with _read_lock(cache):
            direct = _profile_direct_qfq(root, cache, code, start, end, numeric283_chart=numeric283_chart)
            if direct is not None:
                return {**response, **direct}
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
                if (not frame.ts_code.eq(code).all() or not frame.market_type.eq("BJ" if code.endswith(".BJ") else "A_SHARE").all()
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
            result = _with_lifecycle_note({**response, "status": "READY" if rows else "EMPTY_EXACT_RANGE", "rows": rows,
                "columns": list(COLUMNS), "identity": dict(generation_id=meta["generation_id"],
                    input_sha256=meta["input_sha256"], manifest_sha256=manifest_sha,
                    artifact_sha256=bound["target_sha256"], formula_source_sha256=FORMULA_SHA,
                    user_formula_contract=formula, verification_basis=verification, artifact_stat=observed,
                    asof_date=meta["asof_date"], historical_PIT=False, maximum_claim="DIRECTION_ONLY",
                    reader_source_sha256=_sha_bytes(reader_path.read_bytes()))})
            return _numeric283_finalize(result, code) if numeric283_chart else result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as error:
        return _with_lifecycle_note({**response, "cannot_confirm": [str(error) or type(error).__name__]})
