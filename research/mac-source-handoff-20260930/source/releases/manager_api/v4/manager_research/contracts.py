"""Strict contracts for the V4 manager research job.

This module deliberately contains no I/O and no imports from the legacy
runtime.  Dates, stage identity, source cut-off and the four research-only
flags are validated before a job is admitted to the store.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence
from infrastructure.trading_safety import assert_safe_tree


PRODUCT_SCHEMA_VERSION = "v4.manager_research.product.v1"
JOB_SCHEMA_VERSION = "v4.manager_research.job.v1"
TARGET_STAGE_ID = "STAGE_0935_0940"
MARKET = "HK_CONNECT"
CUTOFF_LOCAL_TIME = "09:40:00+08:00"
FOUR_FLAGS = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}

_DATE_RE = re.compile(r"^\d{8}$")
_CODE_RE = re.compile(r"^HK\.(\d{5})$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_UTC8 = timezone(timedelta(hours=8))
# Row-bearing containers in the live stage-center payload shapes.  Their row
# content is validated per row after extraction; the layer guard must not
# descend into them (the rows carry integer ``order`` rank aliases there).
_ROW_CONTAINER_KEYS = frozenset(
    {"rows", "markets", "selection_markets", "market_summaries", "unified_rows"}
)


class ContractError(ValueError):
    """An input or persisted product violated the V4 research contract."""


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("value is not canonical JSON") from exc


def sha256_json(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def strict_trade_date(value: Any) -> str:
    if not isinstance(value, str) or _DATE_RE.fullmatch(value) is None:
        raise ContractError("target_trade_date must use YYYYMMDD")
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise ContractError("target_trade_date must be a real calendar date") from exc
    return parsed.strftime("%Y%m%d")


def cutoff_at(target_trade_date: str) -> str:
    """Return the fixed HKEX research cut-off for a target date."""

    target = strict_trade_date(target_trade_date)
    parsed = datetime.strptime(f"{target} 09:40:00", "%Y%m%d %H:%M:%S")
    return parsed.replace(tzinfo=_UTC8).isoformat(timespec="seconds")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_sha(value: Any, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise ContractError(f"{name} must be a SHA-256 digest")
    return value.lower()


def _json_safe(value: Any) -> Any:
    """Keep the input identity deterministic without trusting arbitrary objects."""

    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ContractError("observation mapping keys must be strings")
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_json_safe(item) for item in value]
    raise ContractError("observation contains a non-JSON value")


def _row_source_date(value: Any, target_trade_date: str) -> str:
    if not isinstance(value, str) or not value.strip() or not re.search(r"[T ]\d{2}:\d{2}", value):
        raise ContractError("observation source_last_bar_time must prove an exact timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("observation source_last_bar_time is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_UTC8)  # documented stage-host timezone
    parsed = parsed.astimezone(_UTC8)
    if parsed.strftime("%Y%m%d") != target_trade_date:
        raise ContractError("observation source_last_bar_time is from another date")
    if parsed > datetime.fromisoformat(cutoff_at(target_trade_date)):
        raise ContractError("observation source_last_bar_time exceeds cutoff")
    return value.strip()


def _assert_identity(value: Mapping[str, Any], target: str) -> None:
    for key, expected in (("market", MARKET), ("stage_id", TARGET_STAGE_ID), ("target_trade_date", target), ("trade_date", target)):
        if key in value and value[key] != expected:
            raise ContractError(f"observation {key} conflicts with exact input")


def _extract_stage_payload(payload: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], list[Any]]:
    target = payload.get("target_trade_date", payload.get("trade_date", payload.get("date")))
    stage_id = payload.get("stage_id")
    if not isinstance(stage_id, str):
        stage_id = payload.get("stage", {}).get("stage_id") if isinstance(payload.get("stage"), Mapping) else None
    if not isinstance(stage_id, str):
        raise ContractError("stage_id is required")
    markets = payload.get("markets")
    market_payload: Mapping[str, Any] | None = None
    if isinstance(markets, Mapping):
        market_payload = markets.get(MARKET) or markets.get("HK")
    if not isinstance(market_payload, Mapping):
        market_payload = payload
    rows = market_payload.get("rows") if isinstance(market_payload, Mapping) else None
    if rows is None:
        rows = payload.get("rows")
    if not isinstance(rows, list):
        raise ContractError("HK_CONNECT rows are required")
    return strict_trade_date(target), market_payload, rows


def normalise_observation_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and freeze the exact stage rows used by a research job.

    The host may provide a full stage-centre response or a small adapter
    response.  The caller cannot supply an alternate list after this function
    returns.  ``input_identity`` includes the source artifact digest and every
    normalized row, and is the idempotency key used by the store.
    """

    if not isinstance(payload, Mapping):
        raise ContractError("observation input must be an object")
    target_trade_date, market_payload, rows = _extract_stage_payload(payload)
    stage_id = payload.get("stage_id")
    if not isinstance(stage_id, str) and isinstance(payload.get("stage"), Mapping):
        stage_id = payload["stage"].get("stage_id")
    if stage_id != TARGET_STAGE_ID:
        raise ContractError(f"stage_id must be {TARGET_STAGE_ID}")
    if len(rows) == 0:
        raise ContractError("HK_CONNECT rows must not be empty")
    if len(rows) > 50:
        raise ContractError("HK_CONNECT rows exceed the manager display bound")
    source_sha = _optional_sha(
        market_payload.get("raw_artifact_sha256", market_payload.get("artifact_sha256")),
        "input_source_sha256",
    )
    raw_cannot_confirm = market_payload.get("cannot_confirm", payload.get("cannot_confirm", []))
    cannot_confirm = _json_safe(raw_cannot_confirm)
    source_status = market_payload.get("status", payload.get("status", "CANNOT_CONFIRM"))
    _assert_identity(payload, target_trade_date)
    _assert_identity(market_payload, target_trade_date)
    normalized_rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            raise ContractError("observation rows must be objects")
        _assert_identity(row, target_trade_date)
        code = row.get("code", row.get("symbol"))
        if not isinstance(code, str) or _CODE_RE.fullmatch(code.strip()) is None:
            raise ContractError("observation code must be normalized HK.#####")
        code = code.strip()
        if code in seen_codes:
            raise ContractError(f"duplicate observation code: {code}")
        seen_codes.add(code)
        name = row.get("name", row.get("stock_name"),)
        name = _text(name, f"{code}.name")
        source_last_bar_time = _row_source_date(
            row.get("source_last_bar_time", row.get("observed_at", "")),
            target_trade_date,
        )
        # Keep the complete stage row for evidence, but canonicalize it into
        # plain JSON so a later client response cannot mutate the identity.
        row_copy = _json_safe(dict(row))
        if not isinstance(row_copy, dict):
            raise ContractError("observation row must remain an object")
        row_copy["code"] = code
        row_copy["name"] = name
        row_copy["market"] = MARKET
        row_copy["stage_id"] = TARGET_STAGE_ID
        row_copy["target_trade_date"] = target_trade_date
        raw_rank = row.get("stage_rank", row.get("rank", row.get("order", index)))
        try:
            # Do not silently turn a fractional or boolean rank into a new
            # position.  The stage order is part of the input identity.
            if isinstance(raw_rank, bool):
                raise ValueError
            numeric_rank = int(raw_rank)
            if isinstance(raw_rank, float) and raw_rank != numeric_rank:
                raise ValueError
            if isinstance(raw_rank, str) and raw_rank.strip() != str(numeric_rank):
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ContractError(f"{code}.stage_rank must be a positive integer") from exc
        if numeric_rank < 1:
            raise ContractError(f"{code}.stage_rank must be a positive integer")
        # "order" is a legacy integer rank alias at this input boundary only.
        # Keep it in the row for evidence and identity compatibility with
        # existing exact caches; validate it against the stage rank and
        # exclude exactly this validated alias from the strict guard view.
        if "order" in row_copy:
            if isinstance(row_copy["order"], bool) or str(row_copy["order"]) != str(numeric_rank):
                raise ContractError("legacy order must equal validated stage_rank")
        try:
            guard_view = {key: value for key, value in row_copy.items() if key != "order"}
            assert_safe_tree(guard_view, label="manager observation")
        except ValueError as error:
            raise ContractError(f"unsafe observation row {code}: {error}") from error
        row_copy["stage_rank"] = numeric_rank
        row_copy["source_last_bar_time"] = source_last_bar_time
        normalized_rows.append(row_copy)
    normalized_rows.sort(key=lambda item: (int(item["stage_rank"]), item["code"]))
    for expected_rank, row in enumerate(normalized_rows, start=1):
        if not isinstance(row["stage_rank"], int) or row["stage_rank"] < 1:
            raise ContractError("stage_rank must be a positive integer")
        row["stage_position"] = expected_rank
    identity_payload = {
        "target_trade_date": target_trade_date,
        "stage_id": TARGET_STAGE_ID,
        "market": MARKET,
        "input_source_sha256": source_sha,
        "source_status": source_status,
        "cannot_confirm": cannot_confirm,
        "rows": normalized_rows,
    }
    for layer in (payload, market_payload):
        try:
            assert_safe_tree(
                {key: value for key, value in layer.items() if key not in _ROW_CONTAINER_KEYS},
                label="manager input",
            )
        except ValueError as error:
            raise ContractError(f"unsafe manager input: {error}") from error
    return {
        "target_trade_date": target_trade_date,
        "stage_id": TARGET_STAGE_ID,
        "market": MARKET,
        "cutoff_at": cutoff_at(target_trade_date),
        "input_source_sha256": source_sha,
        "input_row_count": len(normalized_rows),
        "input_identity": sha256_json(identity_payload),
        "rows": normalized_rows,
        "source_status": source_status,
        "stage_status": source_status,
        "cannot_confirm": cannot_confirm,
        "source_artifact_id": market_payload.get("artifact_id", payload.get("artifact_id")),
        "identity_payload": identity_payload,
    }


def validate_safety(value: Mapping[str, Any] | None) -> dict[str, bool]:
    if value is None:
        return dict(FOUR_FLAGS)
    if dict(value) != FOUR_FLAGS:
        raise ContractError("research safety flags changed")
    return dict(FOUR_FLAGS)
