"""Prepare a frozen, causal PFT-S full-A-share sample from the V4 panel.

The command reads the already-bound V4 logical backtest panel. It writes only
sample-specific, case-keyed feature and OHLCV artifacts; it is not a panel
producer and does not fit a model.
"""
from __future__ import annotations

import argparse
import csv
from datetime import date
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from ops.pft_s_full_ashare_features import (  # noqa: E402
    EVIDENCE_COLUMNS,
    FEATURE_SCHEMA,
    FEATURES,
    LABEL_RULE_SCHEMA,
    WEAK_LABEL_RULES,
    feature_frame,
    weak_label_strata,
)

BATCH = "PFT_S_FULL_ASHARE_SCALEUP_20261122_V1"
START_DATE = "20220101"
ASOF_DATE = "20261120"
TRAIN_END = "20251231"
OOS_START = "20260101"
COHORT_FILE = "sealed_all_a_universe_cohorts.csv"
EXCLUSION_FILE = "exclusion_full_frozen.csv"
CROSSWALK_FILE = APP_ROOT / "ops" / "a_share_bse_old_new_code_crosswalk.csv"
SPLIT_FIELDS = ("panel_security_id", "canonical_security_id", "cohort", "hash_prefix_64")
PANEL_SEMANTICS = ("ts_code", "trade_date", "exchange", "market_type", "open", "high", "low", "close", "vol", "bbi", "zge_white_line", "zge_yellow_line")
BAR_FIELDS = ("open", "high", "low", "close", "vol", "bbi", "zge_white_line", "zge_yellow_line")
FLAGS = {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}
TACTIC_BY_SUBTYPE = {
    "positive_pullback": "S01/S14/S17",
    "positive_readvance": "S04/S22",
    "positive_rebuild": "S21",
    "hard_near_anchor_broken": "S19/S26",
    "hard_local_reclaim_below_support": "S20/S21",
    "hard_first_breakout_no_consolidation": "S04/S22",
    "ordinary_active_yellow_or_bear_regime": "S19/S26",
    "ordinary_g2_distribution": "S17/S26",
}
STAGE_BY_SUBTYPE = {
    "positive_pullback": "回调整理／承接",
    "positive_readvance": "启动／再推进",
    "positive_rebuild": "修复重建",
    "hard_near_anchor_broken": "失效",
    "hard_local_reclaim_below_support": "修复／重建待确认",
    "hard_first_breakout_no_consolidation": "启动／再推进待确认",
    "ordinary_active_yellow_or_bear_regime": "失效",
    "ordinary_g2_distribution": "强势外观下放量滞涨",
}


class PrepareError(RuntimeError):
    """A fail-closed identity, data, or sample-construction error."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PrepareError(f"FROZEN_JSON_PATH_INVALID:{path}")
    before = path.stat()
    raw = path.read_bytes()
    if path.stat() != before:
        raise PrepareError(f"FROZEN_JSON_CHANGED_DURING_READ:{path.name}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise PrepareError(f"FROZEN_JSON_NOT_OBJECT:{path.name}")
    return value


def _read_csv(path: Path) -> tuple[list[dict[str, str]], str]:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PrepareError(f"FROZEN_CSV_PATH_INVALID:{path}")
    before = path.stat()
    raw = path.read_bytes()
    if path.stat() != before:
        raise PrepareError(f"FROZEN_CSV_CHANGED_DURING_READ:{path.name}")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="strict"), newline=""))
    except UnicodeDecodeError as exc:
        raise PrepareError(f"FROZEN_CSV_NOT_UTF8:{path.name}") from exc
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise PrepareError(f"FROZEN_CSV_HEADER_INVALID:{path.name}")
    rows = list(reader)
    if any(None in row for row in rows):
        raise PrepareError(f"FROZEN_CSV_ROW_WIDTH_INVALID:{path.name}")
    return rows, _sha_bytes(raw)


def _day(value: Any) -> str:
    text = str(value).strip().replace("-", "")
    if len(text) >= 10 and text[4] == "-":
        text = text[:10].replace("-", "")
    if not (len(text) == 8 and text.isdigit()):
        raise PrepareError(f"INVALID_TRADE_DATE:{value!r}")
    date(int(text[:4]), int(text[4:6]), int(text[6:]))
    return text


def _code(value: Any) -> str:
    text = str(value or "").strip().upper()
    if len(text) != 9 or text[-3:] not in {".SH", ".SZ", ".BJ"} or not text[:6].isdigit():
        raise PrepareError(f"INVALID_A_SHARE_CODE:{value!r}")
    return text


def _is_a_code(value: Any) -> bool:
    text = str(value or "").strip().upper()
    return bool(re.fullmatch(r"\d{6}\.(SH|SZ|BJ)", text))


def _hash64(value: str) -> int:
    return int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")


def _validate_inputs(artifact_root: Path) -> dict[str, Any]:
    scope = _read_json(artifact_root / "scope_frozen.json")
    cohort_identity = _read_json(artifact_root / "sealed_all_a_universe_cohorts_identity.json")
    exclusion_identity = _read_json(artifact_root / "exclusion_full_identity.json")
    cohorts, cohort_sha = _read_csv(artifact_root / COHORT_FILE)
    exclusions, exclusion_sha = _read_csv(artifact_root / EXCLUSION_FILE)
    if scope.get("batch") != BATCH:
        raise PrepareError("FROZEN_BATCH_MISMATCH")
    if cohort_identity.get("universe_cohorts_sha256") != cohort_sha:
        raise PrepareError("FROZEN_COHORT_SHA_MISMATCH")
    if exclusion_identity.get("exclusion_sha256") != exclusion_sha or scope.get("exclusion_sha256") != exclusion_sha:
        raise PrepareError("FROZEN_EXCLUSION_SHA_MISMATCH")
    crosswalk_sha = _sha_file(CROSSWALK_FILE)
    if cohort_identity.get("crosswalk_sha256") != crosswalk_sha:
        raise PrepareError("BSE_CROSSWALK_SHA_MISMATCH")
    required = set(SPLIT_FIELDS)
    if any(not required.issubset(row) for row in cohorts):
        raise PrepareError("COHORT_COLUMNS_MISSING")
    raw_to_canonical: dict[str, str] = {}
    canonical_partition: dict[str, str] = {}
    hash_prefixes: dict[str, str] = {}
    for row in cohorts:
        raw = _code(row["panel_security_id"])
        canonical = _code(row["canonical_security_id"])
        cohort = row["cohort"].strip().upper()
        if cohort not in {"TRAIN", "OOS", "EXCLUDED"}:
            raise PrepareError(f"INVALID_FROZEN_COHORT:{cohort}")
        if raw in raw_to_canonical and raw_to_canonical[raw] != canonical:
            raise PrepareError(f"CONFLICTING_CANONICAL_ALIAS:{raw}")
        if canonical in canonical_partition and canonical_partition[canonical] != cohort:
            raise PrepareError(f"CANONICAL_SPLIT_CONFLICT:{canonical}")
        raw_to_canonical[raw] = canonical
        canonical_partition[canonical] = cohort
        hash_prefixes[canonical] = row["hash_prefix_64"].strip().lower()

    aliases: dict[str, str] = {raw: canonical for raw, canonical in raw_to_canonical.items()}
    crosswalk_aliases: list[dict[str, str]] = []
    with CROSSWALK_FILE.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        for row in reader:
            if not (row.get("old_ts_code") or "").strip() or not (row.get("new_ts_code") or "").strip():
                continue
            old = _code(row["old_ts_code"])
            new = _code(row["new_ts_code"])
            canonical = raw_to_canonical.get(old) or raw_to_canonical.get(new)
            if canonical is None:
                continue
            if raw_to_canonical.get(old, canonical) != canonical or raw_to_canonical.get(new, canonical) != canonical:
                raise PrepareError(f"BSE_ALIAS_CANONICAL_MISMATCH:{old}:{new}")
            aliases[old] = canonical
            aliases[new] = canonical
            crosswalk_aliases.append({"old": old, "new": new, "effective": str(row.get("code_change_effective_date") or "20251009").replace("-", "")})

    # Recompute the frozen hash-held-out assignment and require it to match the
    # sealed identity table before any data read.
    reserved = 2**62
    for canonical, cohort in canonical_partition.items():
        expected_prefix = hashlib.sha256(f"{BATCH}|OOS|{canonical}".encode()).hexdigest()[:16]
        if hash_prefixes.get(canonical) != expected_prefix:
            raise PrepareError(f"FROZEN_SECURITY_HASH_MISMATCH:{canonical}")
        if cohort != "EXCLUDED":
            expected = "OOS" if int(expected_prefix, 16) < reserved else "TRAIN"
            if cohort != expected:
                raise PrepareError(f"FROZEN_PARTITION_HASH_MISMATCH:{canonical}")

    excluded_codes = {_code(row.get("security_id")) for row in exclusions}
    excluded_canonical = {aliases.get(code, code) for code in excluded_codes}
    excluded_canonical.update(canonical for canonical, cohort in canonical_partition.items() if cohort == "EXCLUDED")
    return {
        "scope": scope,
        "cohort_identity": cohort_identity,
        "cohort_rows": cohorts,
        "raw_to_canonical": raw_to_canonical,
        "canonical_partition": canonical_partition,
        "aliases": aliases,
        "crosswalk_aliases": crosswalk_aliases,
        "exclusions": sorted(excluded_codes),
        "excluded_canonical": excluded_canonical,
        "input_sha256": {COHORT_FILE: cohort_sha, EXCLUSION_FILE: exclusion_sha, CROSSWALK_FILE.name: crosswalk_sha},
    }


def _schema_names(schema: Any) -> dict[str, str]:
    return {str(name).lower(): str(name) for name in schema.names}


def _date_value(schema: Any, field: str, text: str) -> Any:
    import pyarrow as pa
    dtype = schema.field(field).type
    if pa.types.is_integer(dtype):
        return int(text)
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        return text
    if pa.types.is_date(dtype):
        return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    raise PrepareError(f"UNSUPPORTED_PANEL_DATE_TYPE:{dtype}")


def _panel_columns(schema: Any) -> tuple[dict[str, str], list[str]]:
    actual = _schema_names(schema)
    aliases = {
        "ts_code": ("ts_code",), "trade_date": ("trade_date",), "exchange": ("exchange",),
        "market_type": ("market_type",), "open": ("open",), "high": ("high",),
        "low": ("low",), "close": ("close",), "vol": ("vol", "volume"),
        "bbi": ("bbi",), "zge_white_line": ("zge_white_line",),
        "zge_yellow_line": ("zge_yellow_line",),
    }
    required = ("ts_code", "trade_date", "open", "high", "low", "close", "vol", "bbi", "zge_white_line", "zge_yellow_line")
    mapping: dict[str, str] = {}
    for semantic, choices in aliases.items():
        field = next((actual[name] for name in choices if name in actual), None)
        if field is not None:
            mapping[semantic] = field
        elif semantic in required:
            raise PrepareError(f"BACKTEST_PANEL_REQUIRED_FIELD_MISSING:{semantic}")
    return mapping, list(dict.fromkeys(mapping.values()))


def _key_rows_universe(panel_path: Path, logical_reader: Any, frozen_raw_codes: set[str]) -> tuple[set[str], set[str]]:
    logical = logical_reader.parquet.ParquetFile(panel_path)
    if not hasattr(logical, "blocks") or not hasattr(logical, "value"):
        raise PrepareError("BOUND_BACKTEST_PANEL_NOT_LOGICAL")
    union: set[str] = set()
    for index, block in enumerate(logical.blocks):
        key_rows = block.get("key_rows")
        if not isinstance(key_rows, dict):
            raise PrepareError(f"LOGICAL_BLOCK_KEY_ROWS_MISSING:{index}")
        for value in key_rows:
            if _is_a_code(value):
                union.add(_code(value))
    excluded = {_code(value) for value in logical.value.get("excluded_symbols", []) if _is_a_code(value)}
    observed = union - excluded
    if observed != frozen_raw_codes:
        missing = sorted(frozen_raw_codes - observed)[:10]
        extra = sorted(observed - frozen_raw_codes)[:10]
        raise PrepareError(f"FROZEN_KEY_ROWS_UNIVERSE_MISMATCH:missing={missing}:extra={extra}")
    return observed, excluded


def _code_cohorts(canonical_to_codes: dict[str, list[str]], limit: int) -> list[list[str]]:
    if not 256 <= limit <= 512:
        raise PrepareError("CODE_COHORT_SIZE_MUST_BE_256_TO_512")
    batches: list[list[str]] = []
    current: list[str] = []
    for canonical in sorted(canonical_to_codes):
        group = sorted(set(canonical_to_codes[canonical]))
        if len(group) > limit:
            raise PrepareError(f"CANONICAL_ALIAS_GROUP_TOO_LARGE:{canonical}")
        if current and len(current) + len(group) > limit:
            batches.append(current)
            current = []
        current.extend(group)
    if current:
        batches.append(current)
    return batches


def _a_market_row(code: str, row: dict[str, Any]) -> bool:
    suffix = code.rsplit(".", 1)[-1]
    market_type = str(row.get("market_type") or "").strip().upper()
    if market_type:
        if market_type not in {"A_SHARE", "BJ"}:
            return False
    elif suffix not in {"SH", "SZ", "BJ"}:
        return False
    exchange = str(row.get("exchange") or "").strip().upper()
    if exchange:
        accepted = {"SH": {"SH", "SSE", "XSHG", "SHANGHAI"},
                    "SZ": {"SZ", "SZSE", "XSHE", "SHENZHEN"},
                    "BJ": {"BJ", "BSE", "XBEI", "BEIJING"}}
        if exchange not in accepted[suffix]:
            return False
    return True


def _normalize_panel_rows(table: Any, mapping: dict[str, str], raw_to_canonical: dict[str, str]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    result: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for raw in table.to_pylist():
        raw_code = _code(raw.get(mapping["ts_code"]))
        canonical = raw_to_canonical.get(raw_code)
        if canonical is None:
            raise PrepareError(f"PANEL_CODE_NOT_IN_FROZEN_UNIVERSE:{raw_code}")
        row = {semantic: raw.get(field) for semantic, field in mapping.items()}
        row["ts_code"] = raw_code
        row["trade_date"] = _day(row["trade_date"])
        if not _a_market_row(raw_code, row):
            continue
        for name in BAR_FIELDS:
            value = row.get(name)
            try:
                row[name] = float(value) if value is not None else math.nan
            except (TypeError, ValueError, OverflowError):
                row[name] = math.nan
            if not math.isfinite(row[name]):
                row[name] = math.nan
        result.setdefault(canonical, {}).setdefault(raw_code, []).append(row)
    for canonical, by_code in result.items():
        for code, rows in by_code.items():
            rows.sort(key=lambda item: item["trade_date"])
            dates = [row["trade_date"] for row in rows]
            if len(dates) != len(set(dates)):
                raise PrepareError(f"DUPLICATE_PANEL_KEY:{code}")
    return result


def _read_panel_batch(panel_path: Path, schema: Any, mapping: dict[str, str], columns: list[str],
                      code_batch: list[str], raw_to_canonical: dict[str, str], logical_reader: Any) -> tuple[dict[str, dict[str, list[dict[str, Any]]]], int]:
    date_field, code_field = mapping["trade_date"], mapping["ts_code"]
    filters = [[
        (date_field, ">=", _date_value(schema, date_field, START_DATE)),
        (date_field, "<=", _date_value(schema, date_field, ASOF_DATE)),
        (code_field, "in", code_batch),
    ]]
    table = logical_reader.parquet.read_table(panel_path, columns=columns, filters=filters, use_threads=True)
    return _normalize_panel_rows(table, mapping, raw_to_canonical), table.num_rows


def _deduplicate_alias_history(by_code: dict[str, list[dict[str, Any]]], crosswalk_aliases: list[dict[str, str]]) -> list[dict[str, Any]]:
    cutover_by_pair: dict[frozenset[str], tuple[str, str, str]] = {}
    for item in crosswalk_aliases:
        cutover_by_pair[frozenset((item["old"], item["new"]))] = (item["old"], item["new"], item["effective"])
    rows_by_date: dict[str, list[dict[str, Any]]] = {}
    for rows in by_code.values():
        for row in rows:
            rows_by_date.setdefault(row["trade_date"], []).append(row)
    result: list[dict[str, Any]] = []
    for day in sorted(rows_by_date):
        candidates = rows_by_date[day]
        if len(candidates) == 1:
            result.append(candidates[0])
            continue
        winner = None
        codes = {row["ts_code"] for row in candidates}
        for pair, (old_code, new_code, effective) in cutover_by_pair.items():
            if codes.issubset(pair):
                desired = old_code if day < effective else new_code
                winner = next((row for row in candidates if row["ts_code"] == desired), None)
                break
        if winner is None:
            raise PrepareError(f"AMBIGUOUS_CANONICAL_DUPLICATE_DATE:{day}:{sorted(codes)}")
        result.append(winner)
    result.sort(key=lambda item: item["trade_date"])
    return result


def _valid_d(row: dict[str, Any]) -> bool:
    values = [row.get(name) for name in BAR_FIELDS]
    if any(value is None or not math.isfinite(float(value)) for value in values):
        return False
    o, h, low, close, vol = (float(row[name]) for name in ("open", "high", "low", "close", "vol"))
    lines = (float(row["bbi"]), float(row["zge_white_line"]), float(row["zge_yellow_line"]))
    return (min(o, h, low, close, *lines) > 0 and vol > 0
            and h >= max(o, close, low) and low <= min(o, close, h))


def _candidate_rank(split: str, stratum: str, canonical: str, day: str) -> str:
    return hashlib.sha256(f"{BATCH}|SAMPLE|{split}|{stratum}|{canonical}|{day}".encode("utf-8")).hexdigest()


def _episode_id(canonical: str, day: str) -> str:
    return hashlib.sha256(f"{BATCH}|EPISODE|{canonical}|{day}".encode("utf-8")).hexdigest()[:24]


def _find_candidates(by_canonical: dict[str, dict[str, list[dict[str, Any]]]], inputs: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    best_by_security_stratum: dict[tuple[str, str, str], dict[str, Any]] = {}
    counters = {"canonical_histories": 0, "valid_d_rows": 0, "unlabelled_valid_d_rows": 0,
                "invalid_d_rows": 0, "train_candidate_rows": 0, "oos_candidate_rows": 0}
    for canonical in sorted(by_canonical):
        if canonical in inputs["excluded_canonical"]:
            continue
        split = inputs["canonical_partition"].get(canonical)
        if split not in {"TRAIN", "OOS"}:
            continue
        history = _deduplicate_alias_history(by_canonical[canonical], inputs["crosswalk_aliases"])
        history = [row for row in history if START_DATE <= row["trade_date"] <= ASOF_DATE]
        if not history:
            continue
        counters["canonical_histories"] += 1
        frame = feature_frame(__import__("pandas").DataFrame(history))
        history_by_day = {row["trade_date"]: row for row in history}
        for _, feature_row in frame.iterrows():
            day = str(feature_row["trade_date"])
            if not START_DATE <= day <= ASOF_DATE:
                continue
            row = history_by_day[day]
            if not _valid_d(row):
                counters["invalid_d_rows"] += 1
                continue
            if split == "TRAIN" and day > TRAIN_END:
                continue
            if split == "OOS" and day < OOS_START:
                continue
            counters["valid_d_rows"] += 1
            strata = weak_label_strata(feature_row)
            if not strata:
                counters["unlabelled_valid_d_rows"] += 1
                continue
            label, subtype = strata[0]
            stratum = subtype
            candidate = {
                "canonical_security_id": canonical,
                "D": day,
                "split": split,
                "label": label,
                "subtype": subtype,
                "tactic": TACTIC_BY_SUBTYPE[subtype],
                "stage": STAGE_BY_SUBTYPE[subtype],
                "label_group": "POSITIVE" if label == "TRUE" else ("HARD_NEGATIVE" if subtype.startswith("hard_") else "ORDINARY_NEGATIVE"),
                "rank_hash": _candidate_rank(split, stratum, canonical, day),
                "episode_id": _episode_id(canonical, day),
                "feature_values": {name: feature_row.get(name) for name in FEATURES},
                "evidence": {name: feature_row.get(name) for name in EVIDENCE_COLUMNS},
                "gates": {name: feature_row.get(name) for name in ("g1_wy_pass", "g2_s26_reject", "gate_pass", "gate_reasons")},
                "stratum": stratum,
            }
            key = (split, canonical, stratum)
            previous = best_by_security_stratum.get(key)
            if previous is None or candidate["rank_hash"] < previous["rank_hash"]:
                best_by_security_stratum[key] = candidate
            counters[f"{split.lower()}_candidate_rows"] += 1
    return list(best_by_security_stratum.values()), counters


def _attach_case_histories(items: list[dict[str, Any]], *, panel_path: Path, schema: Any,
                           mapping: dict[str, str], columns: list[str], inputs: dict[str, Any],
                           logical_reader: Any, code_cohort_size: int) -> int:
    selected = {row["canonical_security_id"] for row in items}
    codes_by_canonical: dict[str, list[str]] = {}
    for code, canonical in inputs["raw_to_canonical"].items():
        if canonical in selected:
            codes_by_canonical.setdefault(canonical, []).append(code)
    grouped_items: dict[str, dict[str, list[dict[str, Any]]]] = {}
    rows_read = 0
    for code_batch in _code_cohorts(codes_by_canonical, code_cohort_size):
        grouped, count = _read_panel_batch(panel_path, schema, mapping, columns, code_batch,
                                           inputs["raw_to_canonical"], logical_reader)
        rows_read += count
        for canonical, by_code in grouped.items():
            grouped_items[canonical] = by_code
    by_security: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_security.setdefault(item["canonical_security_id"], []).append(item)
    for canonical, cases in by_security.items():
        by_code = grouped_items.get(canonical)
        if not by_code:
            raise PrepareError(f"SELECTED_CANONICAL_HISTORY_MISSING:{canonical}")
        history = _deduplicate_alias_history(by_code, inputs["crosswalk_aliases"])
        for item in cases:
            prefix = [row for row in history if row["trade_date"] <= item["D"]]
            if not prefix or prefix[-1]["trade_date"] != item["D"]:
                raise PrepareError(f"SELECTED_EXACT_D_ROW_MISSING:{canonical}:{item['D']}")
            item["raw_history"] = prefix
    return rows_read


def _sorted(candidates: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(candidates, key=lambda row: (row["rank_hash"], row["canonical_security_id"], row["D"]))


def _take(candidates: list[dict[str, Any]], count: int, *, split: str, stratum: str,
          used_securities: set[str]) -> list[dict[str, Any]]:
    pool = [row for row in candidates if row["split"] == split and row["stratum"] == stratum]
    chosen: list[dict[str, Any]] = []
    for row in _sorted(pool):
        security = row["canonical_security_id"]
        if security in used_securities:
            continue
        chosen.append(row)
        used_securities.add(security)
        if len(chosen) == count:
            break
    if len(chosen) != count:
        raise PrepareError(f"SAMPLE_QUOTA_UNAVAILABLE:{split}:{stratum}:need={count}:have={len(chosen)}")
    return chosen


def _select(candidates: list[dict[str, Any]], scope: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive_names = ("positive_pullback", "positive_readvance", "positive_rebuild")
    hard_names = ("hard_near_anchor_broken", "hard_local_reclaim_below_support", "hard_first_breakout_no_consolidation")
    train: list[dict[str, Any]] = []
    train_used: set[str] = set()
    for name in hard_names:
        train.extend(_take(candidates, 40, split="TRAIN", stratum=name, used_securities=train_used))
    for name in positive_names:
        train.extend(_take(candidates, 60, split="TRAIN", stratum=name, used_securities=train_used))
    ordinary = _sorted(row for row in candidates if row["split"] == "TRAIN" and row["label"] == "FALSE"
                       and row["label_group"] == "ORDINARY_NEGATIVE")
    for row in ordinary:
        if row["canonical_security_id"] in train_used:
            continue
        train.append(row)
        train_used.add(row["canonical_security_id"])
        if sum(item["label_group"] == "ORDINARY_NEGATIVE" for item in train) == 150:
            break
    ordinary_count = sum(item["label_group"] == "ORDINARY_NEGATIVE" for item in train)
    if ordinary_count != 150:
        raise PrepareError(f"SAMPLE_QUOTA_UNAVAILABLE:TRAIN:ordinary_negative:need=150:have={ordinary_count}")

    oos_security_count = len({row["canonical_security_id"] for row in candidates if row["split"] == "OOS"})
    oos_total = min(int(scope["oos_target"]), oos_security_count)
    if oos_total < int(scope["oos_minimum"]):
        raise PrepareError(f"OOS_SAMPLE_BELOW_FLOOR:{oos_total}<{scope['oos_minimum']}")
    positive_total = round(oos_total * 0.40)
    hard_total = min(40, oos_total - positive_total)
    hard_counts = (14, 13, 13) if hard_total == 40 else _apportion(hard_total, (14, 13, 13))
    positive_counts = _apportion(positive_total, (1, 1, 1))
    oos: list[dict[str, Any]] = []
    oos_used: set[str] = set()
    for name, count in zip(hard_names, hard_counts):
        oos.extend(_take(candidates, count, split="OOS", stratum=name, used_securities=oos_used))
    for name, count in zip(positive_names, positive_counts):
        oos.extend(_take(candidates, count, split="OOS", stratum=name, used_securities=oos_used))
    ordinary_target = oos_total - len(oos)
    ordinary = _sorted(row for row in candidates if row["split"] == "OOS" and row["label_group"] == "ORDINARY_NEGATIVE")
    ordinary_count = 0
    for row in ordinary:
        security = row["canonical_security_id"]
        if security in oos_used:
            continue
        oos.append(row)
        oos_used.add(security)
        ordinary_count += 1
        if ordinary_count == ordinary_target:
            break
    if ordinary_count != ordinary_target:
        raise PrepareError(f"SAMPLE_QUOTA_UNAVAILABLE:OOS:ordinary_negative:need={ordinary_target}:have={ordinary_count}")

    for items, split in ((train, "TRAIN"), (oos, "OOS")):
        if any(row["split"] != split for row in items):
            raise PrepareError("SAMPLE_SPLIT_CONTAMINATION")
        keys = [(row["canonical_security_id"], row["D"]) for row in items]
        if len(keys) != len(set(keys)):
            raise PrepareError(f"DUPLICATE_CANONICAL_EPISODE:{split}")
        securities = [row["canonical_security_id"] for row in items]
        if len(securities) != len(set(securities)):
            raise PrepareError(f"DUPLICATE_CANONICAL_SECURITY:{split}")
    if len({row["canonical_security_id"] for row in train} & {row["canonical_security_id"] for row in oos}):
        raise PrepareError("CANONICAL_SECURITY_CROSSES_TRAIN_OOS")
    return sorted(train, key=lambda row: (row["rank_hash"], row["episode_id"])), sorted(oos, key=lambda row: (row["rank_hash"], row["episode_id"]))


def _apportion(total: int, weights: tuple[int, ...]) -> tuple[int, ...]:
    denominator = sum(weights)
    raw = [total * weight / denominator for weight in weights]
    counts = [int(value) for value in raw]
    for index in sorted(range(len(weights)), key=lambda i: (-(raw[i] - counts[i]), i))[:total - sum(counts)]:
        counts[index] += 1
    return tuple(counts)


def _write_csv(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in columns})


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    try:
        if not math.isfinite(float(value)):
            return ""
    except (TypeError, ValueError, OverflowError):
        pass
    if hasattr(value, "item"):
        value = value.item()
    return value


def _case_rows(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    manifests, matrices = [], []
    for index, item in enumerate(items):
        manifest = {key: item.get(key) for key in ("episode_id", "canonical_security_id", "D", "split", "label", "subtype", "tactic", "stage", "label_group", "stratum", "rank_hash")}
        manifest["feature_row"] = index
        manifest.update(item["gates"])
        manifest.update(item["evidence"])
        manifests.append(manifest)
        matrices.append(item["feature_values"])
    return manifests, matrices


def _write_case_ohlcv(path: Path, items: list[dict[str, Any]]) -> None:
    columns = ["episode_id", "canonical_security_id", "D", "panel_security_id", "trade_date", *BAR_FIELDS]
    with gzip.open(path, "wt", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for item in items:
            for row in item["raw_history"]:
                if row["trade_date"] > item["D"]:
                    continue
                writer.writerow({
                    "episode_id": item["episode_id"],
                    "canonical_security_id": item["canonical_security_id"],
                    "D": item["D"],
                    "panel_security_id": row["ts_code"],
                    "trade_date": row["trade_date"],
                    **{name: _csv_value(row.get(name)) for name in BAR_FIELDS},
                })


def _counts(items: list[dict[str, Any]]) -> dict[str, Any]:
    labels = {key: sum(row["label"] == key for row in items) for key in ("TRUE", "FALSE")}
    subtypes: dict[str, int] = {}
    stages: dict[str, int] = {}
    tactics: dict[str, int] = {}
    for row in items:
        subtypes[row["subtype"]] = subtypes.get(row["subtype"], 0) + 1
        stages[row["stage"]] = stages.get(row["stage"], 0) + 1
        tactics[row["tactic"]] = tactics.get(row["tactic"], 0) + 1
    return {"rows": len(items), "label_counts": labels, "subtype_counts": dict(sorted(subtypes.items())),
            "stage_counts": dict(sorted(stages.items())), "tactic_family_counts": dict(sorted(tactics.items())),
            "unique_canonical_securities": len({row["canonical_security_id"] for row in items}),
            "unique_episodes": len({row["episode_id"] for row in items})}


def _atomic_write_text(path: Path, text: str) -> None:
    temp = path.with_name(path.name + ".tmp")
    with temp.open("x", encoding="utf-8", newline="") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def prepare(*, artifact_root: Path, data_root: Path, output_dir: Path, code_cohort_size: int = 384) -> dict[str, Any]:
    artifact_root = artifact_root.expanduser().resolve(strict=True)
    data_root = data_root.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise PrepareError(f"OUTPUT_ALREADY_EXISTS:{output_dir}")
    if output_dir.parent.resolve(strict=True) != artifact_root:
        raise PrepareError("OUTPUT_MUST_BE_DIRECT_ARTIFACT_ROOT_CHILD")
    staging_dir = output_dir.with_name(output_dir.name + ".partial")
    if staging_dir.exists() or staging_dir.is_symlink():
        raise PrepareError(f"PARTIAL_OUTPUT_ALREADY_EXISTS:{staging_dir}")
    if not 256 <= code_cohort_size <= 512:
        raise PrepareError("CODE_COHORT_SIZE_MUST_BE_256_TO_512")
    inputs = _validate_inputs(artifact_root)
    frozen_codes = set(inputs["raw_to_canonical"])
    canonical_to_codes: dict[str, list[str]] = {}
    for code, canonical in inputs["raw_to_canonical"].items():
        if canonical not in inputs["excluded_canonical"]:
            canonical_to_codes.setdefault(canonical, []).append(code)

    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as logical_reader

    all_candidates: list[dict[str, Any]] = []
    counters = {"code_cohorts": 0, "panel_rows_read": 0, "rows_after_market_filter": 0,
                "canonical_histories": 0, "valid_d_rows": 0, "unlabelled_valid_d_rows": 0,
                "invalid_d_rows": 0, "train_candidate_rows": 0, "oos_candidate_rows": 0}
    with baseline.bind_current_panels(data_root) as (panel_path, source, recheck):
        source_identity = source["identity"]
        frozen_source = inputs["scope"]["authoritative_v4"]
        if source_identity.get("generation_id") != frozen_source.get("generation"):
            raise PrepareError("CURRENT_PANEL_GENERATION_MISMATCH")
        if _day(source_identity.get("asof_date")) != _day(frozen_source.get("asof")):
            raise PrepareError("CURRENT_PANEL_ASOF_MISMATCH")
        a_basis = source_identity.get("a_market_basis") or {}
        if a_basis.get("price_basis") != frozen_source.get("price_basis") or a_basis.get("volume_basis") != frozen_source.get("volume_basis"):
            raise PrepareError("CURRENT_PANEL_BASIS_MISMATCH")
        expected_sha = frozen_source.get("backtest_sha256")
        backtest_sha = (source.get("backtest") or {}).get("panel_sha256")
        matching_fields = ["backtest.panel_sha256"] if backtest_sha == expected_sha else []
        if not matching_fields:
            raise PrepareError("CURRENT_PANEL_BACKTEST_SHA_MISMATCH")
        observed_codes, logical_excluded = _key_rows_universe(panel_path, logical_reader, frozen_codes)
        canonical_to_codes = {}
        for code in sorted(observed_codes):
            canonical = inputs["raw_to_canonical"][code]
            if canonical not in inputs["excluded_canonical"]:
                canonical_to_codes.setdefault(canonical, []).append(code)
        schema = logical_reader.parquet.read_schema(panel_path)
        mapping, read_columns = _panel_columns(schema)
        date_field, code_field = mapping["trade_date"], mapping["ts_code"]
        cohorts = _code_cohorts(canonical_to_codes, code_cohort_size)
        for code_batch in cohorts:
            grouped, rows_read = _read_panel_batch(panel_path, schema, mapping, read_columns, code_batch,
                                                   inputs["raw_to_canonical"], logical_reader)
            counters["panel_rows_read"] += rows_read
            for canonical, by_code in grouped.items():
                counters["rows_after_market_filter"] += sum(len(rows) for rows in by_code.values())
                if canonical in inputs["excluded_canonical"]:
                    continue
                found, local = _find_candidates({canonical: by_code}, inputs)
                all_candidates.extend(found)
                for key in ("canonical_histories", "valid_d_rows", "unlabelled_valid_d_rows", "invalid_d_rows", "train_candidate_rows", "oos_candidate_rows"):
                    counters[key] += local[key]
            counters["code_cohorts"] += 1
        train, oos = _select(all_candidates, inputs["scope"])
        selected_items = train + oos
        selected_rows_read = _attach_case_histories(selected_items, panel_path=panel_path, schema=schema,
                                                    mapping=mapping, columns=read_columns, inputs=inputs,
                                                    logical_reader=logical_reader, code_cohort_size=code_cohort_size)
        counters["selected_case_history_rows_read"] = selected_rows_read
        recheck()

    train_manifest, train_matrix = _case_rows(train)
    oos_manifest, oos_matrix = _case_rows(oos)
    # Labels and evidence are separated from matrices; the fit path must only
    # consume train_manifest + train_features before locking OOS predictions.
    staging_dir.mkdir(parents=False, exist_ok=False)
    train_case_columns = list(dict.fromkeys(key for row in train_manifest for key in row))
    oos_case_columns = list(dict.fromkeys(key for row in oos_manifest for key in row))
    _write_csv(staging_dir / "train_manifest.csv", train_case_columns, train_manifest)
    _write_csv(staging_dir / "oos_labels_and_evidence.csv", oos_case_columns, oos_manifest)
    _write_csv(staging_dir / "train_features.csv", list(FEATURES), train_matrix)
    _write_csv(staging_dir / "oos_features.csv", list(FEATURES), oos_matrix)
    _write_case_ohlcv(staging_dir / "train_case_ohlcv.csv.gz", train)
    _write_case_ohlcv(staging_dir / "oos_case_ohlcv.csv.gz", oos)

    output_hashes = {path.name: _sha_file(path) for path in sorted(staging_dir.iterdir()) if path.is_file()}
    manifest = {
        "schema": "pft_s_full_ashare_prepared.v1",
        "batch": BATCH,
        "feature_schema": FEATURE_SCHEMA,
        "label_rule_schema": LABEL_RULE_SCHEMA,
        "feature_columns": list(FEATURES),
        "feature_count": len(FEATURES),
        "weak_label_rules": WEAK_LABEL_RULES,
        "source": source,
        "source_sha_field_matched": matching_fields,
        "frozen_input_sha256": inputs["input_sha256"],
        "scope_sha256": _sha_file(artifact_root / "scope_frozen.json"),
        "cohort_identity": inputs["cohort_identity"],
        "reader": {"method": "V4 bind_current_panels + LogicalFile key_rows union + projected parquet.read_table DNF",
                   "range": [START_DATE, ASOF_DATE], "code_cohort_size": code_cohort_size,
                   "code_cohort_count": counters["code_cohorts"], "logical_excluded_symbols": sorted(logical_excluded),
                   "market_type_rule": "A_SHARE or BJ; where absent, A panel key suffix SH/SZ/BJ is used",
                   "projected_semantics": list(mapping)},
        "split": {"train_D_through": TRAIN_END, "oos_D_from": OOS_START, "oos_D_through": ASOF_DATE,
                  "oos_security_hash": "SHA256 first64 of BATCH|OOS|canonical_security_id < 2**62",
                  "rank_hash": "SHA256 of BATCH|SAMPLE|split|stratum|canonical_security_id|D"},
        "sampling": {"train_target": 450, "train_positive_target": 180, "train_negative_target": 270,
                     "train_hard_negative_by_stratum": {"near_anchor_broken": 40, "local_reclaim_below_support": 40, "first_breakout_no_consolidation": 40},
                     "oos_target": 150, "oos_minimum": 100, "actual_train": _counts(train), "actual_oos": _counts(oos)},
        "counters": counters,
        "flags": FLAGS,
        "outputs_sha256": output_hashes,
        "notes": ["Feature CSVs are numeric model inputs only and have exactly the allowlisted columns.",
                  "OOS labels/evidence are separate; freeze model, train input identity, and predictions before reading that file.",
                  "No panel, model fit, API, Drive, BUY-gate, or order write occurred."],
    }
    _atomic_write_text(staging_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    lines = [f"{digest}  {name}" for name, digest in sorted(output_hashes.items())]
    lines.append(f"{_sha_file(staging_dir / 'manifest.json')}  manifest.json")
    _atomic_write_text(staging_dir / "SHA256SUMS", "\n".join(lines) + "\n")
    staging_dir.replace(output_dir)
    return {"output_dir": str(output_dir), "train": _counts(train), "oos": _counts(oos), "files": sorted([*output_hashes, "manifest.json", "SHA256SUMS"]), "source_generation": source_identity.get("generation_id")}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare frozen PFT-S full-A-share sample; no model fit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("--artifact-root", type=Path, required=True)
    prepare_parser.add_argument("--data-root", type=Path, required=True)
    prepare_parser.add_argument("--output-dir", type=Path, required=True)
    prepare_parser.add_argument("--code-cohort-size", type=int, default=384)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "prepare":
        try:
            result = prepare(artifact_root=args.artifact_root, data_root=args.data_root,
                             output_dir=args.output_dir, code_cohort_size=args.code_cohort_size)
        except Exception as exc:
            print(json.dumps({"status": "FAILED", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
            return 2
        print(json.dumps({"status": "PREPARED", **result}, ensure_ascii=False, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
