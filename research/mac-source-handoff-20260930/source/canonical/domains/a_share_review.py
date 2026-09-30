"""Canonical, read-only A-share close-review domain object."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from contracts.a_share_review import A_SHARE_REVIEW_SCHEMA, SAFETY_FLAGS
from infrastructure.data_store import _date
from domains.close_review_chain import validate_close_review_chain


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ROW_COLLECTIONS = (
    "big_picture",
    "mainlines",
    "core_stocks",
    "observation_pool",
    "next_day_trigger_tree",
    "quality_gate",
)


def _rows(value: list[dict[str, Any]], *, trade_date: str, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    normalized: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, Mapping):
            raise ValueError(f"{label} rows must be objects")
        copied = deepcopy(dict(row))
        for date_key in ("trade_date", "review_date"):
            value_date = copied.get(date_key)
            if value_date not in (None, "") and str(value_date) != trade_date:
                raise ValueError(f"{label} row date does not match trade date")
        copied["trade_date"] = trade_date
        normalized.append(copied)
    return normalized


def build_a_share_review(
    trade_date: str,
    *,
    big_picture: list[dict[str, Any]],
    mainlines: list[dict[str, Any]],
    core_stocks: list[dict[str, Any]],
    observation_pool: list[dict[str, Any]],
    trigger_rows: list[dict[str, Any]],
    quality_gate_rows: list[dict[str, Any]],
    source_sha256: str,
    market_regime: str = "CANNOT_CONFIRM",
    risk_tone: str = "CANNOT_CONFIRM",
    cannot_confirm: list[str] | None = None,
    model_review: Mapping[str, Any] | None = None,
    source_evidence: list[dict[str, Any]] | None = None,
    source_role: str = "LEGACY_FINAL_API_ORACLE",
    close_chain: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one exact-date review without promoting observation rows to core stocks."""
    trade_date = _date(trade_date)
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise ValueError("source SHA-256 must be a lowercase hexadecimal digest")
    result = {
        "schema_version": A_SHARE_REVIEW_SCHEMA,
        "trade_date": trade_date,
        "headline": f"A股复盘 {trade_date}",
        "market_regime": str(market_regime),
        "risk_tone": str(risk_tone),
        "big_picture": _rows(big_picture, trade_date=trade_date, label="big_picture"),
        "mainlines": _rows(mainlines, trade_date=trade_date, label="mainlines"),
        "core_stocks": _rows(core_stocks, trade_date=trade_date, label="core_stocks"),
        "observation_pool": _rows(
            observation_pool, trade_date=trade_date, label="observation_pool"
        ),
        "next_day_trigger_tree": _rows(
            trigger_rows, trade_date=trade_date, label="next_day_trigger_tree"
        ),
        "quality_gate": _rows(quality_gate_rows, trade_date=trade_date, label="quality_gate"),
        "cannot_confirm": list(cannot_confirm) if cannot_confirm is not None else [
            "MARKET_REGIME_NOT_MATERIALIZED", "RISK_TONE_NOT_MATERIALIZED"
        ],
        "model_review": deepcopy(dict(model_review)) if model_review is not None else {
            "status": "NOT_MATERIALIZED",
            "cannot_confirm": ["A_SHARE_CLOSE_MODEL_NOT_MATERIALIZED"],
        },
        "source_evidence": deepcopy(source_evidence or []),
        "source_role": str(source_role),
        "close_chain": deepcopy(dict(close_chain)) if close_chain is not None else None,
        "source_sha256": source_sha256,
        "write_policy": "review_only_read_only",
        **SAFETY_FLAGS,
    }
    return result


def validate_a_share_review(payload: Mapping[str, Any]) -> str:
    """Validate the canonical identity and date boundary before storage."""
    if not isinstance(payload, Mapping) or payload.get("schema_version") != A_SHARE_REVIEW_SCHEMA:
        raise ValueError("invalid A-share review schema")
    trade_date = _date(str(payload.get("trade_date") or ""))
    if not isinstance(payload.get("source_sha256"), str) or not _SHA256.fullmatch(payload["source_sha256"]):
        raise ValueError("invalid A-share review source SHA-256")
    if any(payload.get(key) is not expected for key, expected in SAFETY_FLAGS.items()):
        raise ValueError("unsafe A-share review boundary")
    for key in ("headline", "market_regime", "risk_tone", "write_policy", "source_role"):
        if not isinstance(payload.get(key), str):
            raise ValueError(f"invalid A-share review {key}")
    if not isinstance(payload.get("cannot_confirm"), list):
        raise ValueError("invalid A-share review cannot_confirm")
    for key in _ROW_COLLECTIONS:
        rows = payload.get(key)
        if not isinstance(rows, list):
            raise ValueError(f"invalid A-share review {key}")
        for row in rows:
            if (
                not isinstance(row, Mapping)
                or str(row.get("trade_date") or "") != trade_date
                or any(
                    row.get(date_key) not in (None, "")
                    and str(row[date_key]) != trade_date
                    for date_key in ("trade_date", "review_date")
                )
            ):
                raise ValueError("A-share review row date does not match trade date")
    if not isinstance(payload.get("source_evidence"), list) or any(
        not isinstance(row, Mapping) for row in payload["source_evidence"]
    ):
        raise ValueError("invalid A-share review source evidence")
    model = payload.get("model_review")
    if not isinstance(model, Mapping):
        raise ValueError("invalid A-share model review")
    if model.get("status") != "NOT_MATERIALIZED":
        if (
            model.get("schema_version") != "replay_model_v1"
            or model.get("status") != "INDEPENDENT_CLOSE_REVIEW_READY"
            or model.get("producer_type") != "DETERMINISTIC_PYTHON"
            or str(model.get("review_date") or "") != trade_date
            or model.get("visibility_stage") != "POST_CLOSE_REVIEW_ONLY"
            or model.get("semantic_model_call_count") != 0
        ):
            raise ValueError("invalid deterministic A-share close model contract")
        safety = model.get("safety") if isinstance(model.get("safety"), Mapping) else {}
        if (
            any(safety.get(key) is not True for key in ("SHADOW_ONLY", "NOT_BUY_ADVICE", "NO_BUY_GATE"))
            or safety.get("HOLDOUT_ACCESS_COUNT") != 0
            or model.get("model_promotion") != "NO_MODEL_PROMOTED"
        ):
            raise ValueError("unsafe A-share close model contract")
    close_chain = payload.get("close_chain")
    if close_chain is not None:
        if not isinstance(close_chain, Mapping):
            raise ValueError("invalid close-review chain")
        validate_close_review_chain(close_chain, trade_date)
    return trade_date
