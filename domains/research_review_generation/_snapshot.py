"""Exact-date immutable input snapshot; not a market-data collector.

The single existing shared authority must create this input. Its source counts
are retained as *reported* evidence, not relabelled as measurements by V4.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import re
from typing import Mapping
from zoneinfo import ZoneInfo

from ._owned_io import BoundaryError

FUNCTIONS = (
    "get_sentiment_data", "get_emotion_metrics", "get_market_facts",
    "get_capital_data", "get_macro_sector_data", "get_theme_reasons",
    "get_dragon_tiger_data", "get_leader_data",
)
SECTIONS = (
    "market_facts.breadth", "market_facts.feedback_matrix", "market_facts.loss_effect",
    "market_facts.theme_tree", "market_facts.event_ledger", "emotion_metrics.money_effect",
    "emotion_metrics.promotion", "emotion_metrics.ladder_gap",
)
SOURCE_ROLE = "VIBE_DUANXIAN_DAILY_REVIEW"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TZ = ZoneInfo("Asia/Shanghai")


def sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise BoundaryError("explicit SHA256 binding required")
    return value


def timestamp(value: object, target: str, *, now: datetime) -> str:
    if not isinstance(value, str):
        raise BoundaryError("source data_as_of must be an explicit timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise BoundaryError("source data_as_of is not ISO8601") from exc
    if parsed.tzinfo is None or parsed.astimezone(_TZ).date().isoformat() != target or parsed > now:
        raise BoundaryError("source data_as_of has wrong session, no timezone, or is future")
    return value


def _source(meta: object, target: str, *, now: datetime) -> dict:
    if not isinstance(meta, dict) or meta.get("target_date") != target:
        raise BoundaryError("source target_date identity mismatch")
    if meta.get("status") not in {"READY", "CANNOT_CONFIRM"}:
        raise BoundaryError("source status must be explicit")
    if meta["status"] == "CANNOT_CONFIRM":
        if not isinstance(meta.get("reason"), str) or not meta["reason"].strip():
            raise BoundaryError("unavailable source requires a reason")
        return deepcopy(meta)
    if not isinstance(meta.get("source_id"), str) or not meta["source_id"].strip():
        raise BoundaryError("source identity missing")
    sha(meta.get("source_sha256"))
    timestamp(meta.get("data_as_of"), target, now=now)
    if meta.get("temporal_basis") != "TARGET_SESSION":
        raise BoundaryError("current-only or unknown source cannot impersonate target-session data")
    return deepcopy(meta)


class ReviewSnapshot:
    def __init__(self, payload: object, target: str, *, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        if not isinstance(payload, dict):
            raise BoundaryError("snapshot is not an object")
        if payload.get("schema_version") != "v4.vibe_review_inputs.v1" or payload.get("source_role") != SOURCE_ROLE:
            raise BoundaryError("snapshot schema or source_role mismatch")
        if payload.get("trade_date") != target or payload.get("target_date") != target:
            raise BoundaryError("snapshot exact-date identity mismatch")
        self.target = target
        self.data_as_of = timestamp(payload.get("data_as_of"), target, now=now)
        if not isinstance(payload.get("authority_id"), str) or not payload["authority_id"].strip():
            raise BoundaryError("single shared authority identity missing")
        sha(payload.get("authority_receipt_sha256"))
        calendar = _source(payload.get("calendar"), target, now=now)
        if calendar["status"] != "READY" or calendar.get("settled") is not True:
            raise BoundaryError("settled-session authority did not approve this date")
        functions, sources = payload.get("functions"), payload.get("sources")
        if not isinstance(functions, dict) or set(functions) != set(FUNCTIONS):
            raise BoundaryError("snapshot must include exactly the eight graph data functions")
        if not isinstance(sources, dict):
            raise BoundaryError("per-function and per-section sources are required")
        self.sources = {key: _source(sources.get(key), target, now=now) for key in (*FUNCTIONS, *SECTIONS, "news")}
        for name, value in functions.items():
            if name in {"get_market_facts", "get_emotion_metrics"}:
                valid = isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], dict)
            else:
                valid = isinstance(value, str)
            if not valid:
                raise BoundaryError(f"source value shape invalid: {name}")
        for section in SECTIONS:
            parent, child = section.split(".")
            source_name = "get_" + parent
            value = functions[source_name][1].get(child)
            if not isinstance(value, dict):
                raise BoundaryError(f"source section missing: {section}")
            evidence = self.sources[section]
            if evidence["status"] == "CANNOT_CONFIRM" and value.get("available") is not False:
                raise BoundaryError(f"unavailable evidence must not appear available: {section}")
            if evidence["status"] == "READY" and value.get("available") is not True:
                raise BoundaryError(f"available evidence/value mismatch: {section}")
        news = payload.get("news")
        expected_query = f"{target} A股 今日 涨停 热门题材 板块 龙头 复盘"
        if not isinstance(news, dict) or news.get("query") != expected_query or not isinstance(news.get("text"), str):
            raise BoundaryError("news query/date or text is not bound")
        self._functions = deepcopy(functions)
        self._news = deepcopy(news)
        self.reported_provider_counts = deepcopy(payload.get("provider_counts", {}))
        self.authority_id = payload["authority_id"]
        self.authority_receipt_sha256 = payload["authority_receipt_sha256"]
        self.lookup_counts: Counter = Counter()
        self._calendar = calendar

    def __getattr__(self, name: str):
        if name not in FUNCTIONS:
            raise AttributeError(name)
        def read(target: str):
            if target != self.target:
                raise BoundaryError("snapshot cross-date lookup refused")
            self.lookup_counts[name] += 1
            source = self.sources[name]
            value = deepcopy(self._functions[name])
            if source["status"] == "CANNOT_CONFIRM":
                text = f"[⚠️ {name}｜{target} 数据获取失败已降级：{source['reason']}]"
                if name in {"get_market_facts", "get_emotion_metrics"}:
                    return text, value[1]
                return text
            return tuple(value) if name in {"get_market_facts", "get_emotion_metrics"} else value
        return read

    def is_settled(self, target: str) -> bool:
        if target != self.target:
            raise BoundaryError("cross-date calendar lookup refused")
        self.lookup_counts["is_settled"] += 1
        return self._calendar["settled"] is True

    def search(self, query: str) -> str:
        if query != self._news["query"]:
            raise BoundaryError("unbound news query refused")
        self.lookup_counts["news_snapshot_read"] += 1
        source = self.sources["news"]
        if source["status"] == "CANNOT_CONFIRM":
            return f"[Agent-Reach 未打通：{source['reason']}]"
        return self._news["text"]

    def warnings(self) -> list[str]:
        return [f"{key}: CANNOT_CONFIRM: {meta['reason']}" for key, meta in self.sources.items() if meta["status"] == "CANNOT_CONFIRM"]
