"""Immutable, source-neutral morning-news bundle shared by V3 consumers."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .hashing import sha256_json
from .paths import resolve_under, validate_date
from .store import SafeRootStore

SCHEMA_VERSION = "v3_shared_data.morning_news.v1"
LATEST_SCHEMA_VERSION = "v3_shared_data.morning_news_latest.v1"
OWNER = "v3_shared_morning_news_collector"
RESEARCH_SCORE_FORMULA = "V3_HOURLY_RESEARCH_ITEM_V1"
_SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


class MorningNewsConflict(ValueError):
    """An immutable date slot already contains different evidence."""


def _clean_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"^(?:A|SH|SZ)[.:]", "", text)
    text = re.sub(r"[.](?:SH|SZ)$", "", text)
    digits = "".join(character for character in text if character.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _news_score(row: Mapping[str, Any]) -> float:
    score = 20.0
    if str(row.get("preselect_hit") or "").upper() == "Y":
        score += 18.0
    if str(row.get("formal_pool_hit") or "").upper() == "Y":
        score += 16.0
    if row.get("research_hit_status") == "RESEARCH_TRACE_HIT":
        score += 14.0
    if row.get("stock_code"):
        score += 12.0
    if row.get("logic_excerpt"):
        score += 10.0
    if row.get("theme"):
        score += 6.0
    return min(score, 100.0)


def news_quality_score(row: Mapping[str, Any]) -> float:
    """Return the frozen V3 news score from explicit contract fields only."""

    return _news_score(row)


def _research_score(row: Mapping[str, Any], body: str) -> float:
    """Materialize the frozen V3 hourly-research item score once.

    The input contract carries source confidence and pool intersections
    explicitly.  In particular, ``preselect_hit`` is a news intersection and
    is deliberately *not* reused as the research ``visible`` hit; absent
    visible evidence remains zero rather than being inferred from selector
    metadata.
    """

    try:
        score = float(row.get("research_source_confidence") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if len(str(body or "")) >= 120:
        score += 15.0
    if str(row.get("stock_code") or "").strip():
        score += 15.0
    if str(row.get("research_visible_hit") or "").upper() == "Y":
        score += 18.0
    if str(row.get("formal_pool_hit") or "").upper() == "Y":
        score += 12.0
    if str(row.get("theme") or "").strip():
        score += 6.0
    source_type = str(row.get("research_source_type") or row.get("source_type") or "").lower()
    if "研报" in str(body or "") or "research" in str(body or "").lower() or source_type in {"research", "report"}:
        score += 6.0
    return min(score, 100.0)


def _body_logic_excerpt(body: str, stock_name: str) -> str:
    index = body.find(stock_name)
    if index < 0:
        return ""
    start = max(0, index - 80)
    end = min(len(body), index + len(stock_name) + 160)
    return body[start:end].strip()


def _candidate_rows(
    candidate_registry: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    if candidate_registry is None:
        return []
    values: Iterable[Any]
    if isinstance(candidate_registry, Mapping):
        values = candidate_registry.values()
    else:
        values = candidate_registry
    rows: list[dict[str, Any]] = []
    for source in values:
        if not isinstance(source, Mapping):
            continue
        name = str(source.get("stock_name") or source.get("name") or "").strip()
        if len(name) < 2:
            continue
        row = dict(source)
        row["stock_name"] = name
        row["stock_code"] = _clean_code(source.get("stock_code") or source.get("ts_code"))
        rows.append(row)
    return sorted(rows, key=lambda row: (-len(str(row["stock_name"])), str(row["stock_name"])))


def materialize_stock_mentions(
    articles: Iterable[Mapping[str, Any]],
    candidate_registry: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Resolve article bodies once using an explicit shared candidate contract.

    Pool/selector fields are never inferred here.  A registry row must carry
    ``preselect_hit``, ``formal_pool_hit`` and ``research_hit_status`` when a
    consumer needs those V3 fields; absent values remain explicit ``N``/empty.
    """

    candidates = _candidate_rows(candidate_registry)
    mentions: dict[tuple[str, str], dict[str, Any]] = {}
    for article in articles:
        if not isinstance(article, Mapping):
            continue
        body = str(article.get("body_text") or "")
        if not body or str(article.get("body_status") or "ARTICLE_BODY_READ") != "ARTICLE_BODY_READ":
            continue
        title = str(article.get("title") or "").strip()
        source_url = str(article.get("url") or "").strip()
        category = str(article.get("category") or "").strip()
        for candidate in candidates:
            stock_name = str(candidate["stock_name"])
            if stock_name not in body:
                continue
            logic_excerpt = str(candidate.get("logic_excerpt") or "").strip() or _body_logic_excerpt(
                body, stock_name
            )
            theme = str(candidate.get("theme") or category).strip()
            preselect_hit = str(candidate.get("preselect_hit") or "N").upper()
            formal_pool_hit = str(candidate.get("formal_pool_hit") or "N").upper()
            research_hit_status = str(candidate.get("research_hit_status") or "")
            intersection: list[str] = []
            if preselect_hit == "Y":
                intersection.append("预选池")
            if formal_pool_hit == "Y":
                intersection.append("正式池")
            if research_hit_status == "RESEARCH_TRACE_HIT":
                intersection.append("研报")
            # V3 emits one trigger row for each candidate/article source.  A
            # repeated mention in the same source is de-duplicated, while a
            # second article remains independently traceable downstream.
            key = (
                str(candidate.get("stock_code") or stock_name),
                source_url,
            )
            mention = {
                "stock_name": stock_name,
                "stock_code": str(candidate.get("stock_code") or ""),
                "theme": theme,
                "event": str(candidate.get("event") or f"{title} 正文股票名匹配：{stock_name}"),
                "logic_excerpt": logic_excerpt,
                "trigger_basis": str(candidate.get("trigger_basis") or "正文股票名匹配"),
                "preselect_hit": preselect_hit,
                "formal_pool_hit": formal_pool_hit,
                "research_hit_status": research_hit_status,
                "intersection_summary": " / ".join(intersection) or "仅新闻正文触发",
                "source_title": title,
                "source_url": source_url,
                "source_type": str(candidate.get("source_type") or "正文股票名匹配"),
                "news_quality_score": _news_score(
                    {
                        "preselect_hit": preselect_hit,
                        "formal_pool_hit": formal_pool_hit,
                        "research_hit_status": research_hit_status,
                        "stock_code": candidate.get("stock_code"),
                        "logic_excerpt": logic_excerpt,
                        "theme": theme,
                    }
                ),
            }
            research_score = _research_score(
                {
                    **candidate,
                    "stock_code": candidate.get("stock_code"),
                    "formal_pool_hit": formal_pool_hit,
                    "theme": theme,
                },
                logic_excerpt,
            )
            mention.update(
                {
                    "research_quality_score": research_score,
                    "research_score_formula": RESEARCH_SCORE_FORMULA if research_score else "",
                    "research_source_present": research_score > 0,
                }
            )
            # One shared trigger row per candidate keeps stage context stable;
            # the score is unaffected by repeated body occurrences.
            mentions.setdefault(key, mention)
    return sorted(
        mentions.values(),
        key=lambda row: (-float(row.get("news_quality_score") or 0.0), str(row.get("stock_code") or "")),
    )


def normalize_legacy_morning_news(source: Mapping[str, Any]) -> dict[str, Any]:
    payload = source.get("payload") if isinstance(source.get("payload"), Mapping) else source
    trade_date = validate_date(str(payload.get("trade_date") or source.get("trade_date") or ""))
    articles = []
    for row in payload.get("articles", []):
        if not isinstance(row, Mapping):
            continue
        articles.append(
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "published_at": str(row.get("published_at") or ""),
                "category": str(row.get("category") or ""),
                "body_status": str(row.get("body_status") or ""),
                "body_excerpt_preview": str(row.get("body_excerpt_preview") or ""),
                "source": "韭研公社",
            }
        )
    mentions = []
    for row in payload.get("stock_mentions", []):
        if not isinstance(row, Mapping):
            continue
        code = _clean_code(row.get("stock_code"))
        name = str(row.get("stock_name") or "").strip()
        if not code and not name:
            continue
        reason = str(
            row.get("intersection_summary")
            or row.get("trigger_basis")
            or row.get("source_title")
            or ""
        ).strip()
        try:
            research_quality_score = float(row.get("research_quality_score") or 0.0)
        except (TypeError, ValueError):
            research_quality_score = 0.0
        mentions.append(
            {
                "stock_code": code,
                "stock_name": name,
                "news_quality_score": _news_score(row),
                "reason": reason,
                "source_title": str(row.get("source_title") or ""),
                "source_url": str(row.get("source_url") or ""),
                "preselect_hit": str(row.get("preselect_hit") or "N"),
                "formal_pool_hit": str(row.get("formal_pool_hit") or "N"),
                "research_hit_status": str(row.get("research_hit_status") or ""),
                "research_quality_score": research_quality_score,
                "research_score_formula": (
                    str(row.get("research_score_formula") or RESEARCH_SCORE_FORMULA)
                    if research_quality_score
                    else ""
                ),
                "research_source_present": bool(row.get("research_source_present"))
                or research_quality_score > 0,
            }
        )
    mentions.sort(key=lambda row: (-float(row["news_quality_score"]), row["stock_code"], row["stock_name"]))
    required = payload.get("required_news_contract")
    required = dict(required) if isinstance(required, Mapping) else {}
    cannot_confirm = []
    for item in payload.get("cannot_confirm_items", []):
        if isinstance(item, Mapping):
            text = str(item.get("description") or item.get("reason") or "").strip()
        else:
            text = str(item).strip()
        if text:
            cannot_confirm.append(text)
    result = {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "status": str(payload.get("status") or source.get("status") or "CANNOT_CONFIRM"),
        "display_status": str(payload.get("display_status") or source.get("display_status") or ""),
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
        "source_mode": "OFFLINE_NORMALIZED_MIGRATION",
        "source_input_sha256": sha256_json(source),
        "required_news_contract": required,
        "article_count": len(articles),
        "mention_count": len(mentions),
        "articles": articles,
        "stock_mentions": mentions,
        "cannot_confirm": sorted(set(cannot_confirm)),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        **_SAFETY,
    }
    _validate_payload(result)
    return result


def _validate_payload(payload: Mapping[str, Any]) -> str:
    trade_date = validate_date(str(payload.get("trade_date") or ""))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("morning news schema mismatch")
    if payload.get("source_role") != "JIUYANGONGSHE_MORNING_NEWS":
        raise ValueError("morning news source role mismatch")
    articles = payload.get("articles")
    mentions = payload.get("stock_mentions")
    if not isinstance(articles, list) or payload.get("article_count") != len(articles):
        raise ValueError("morning news article count mismatch")
    if not isinstance(mentions, list) or payload.get("mention_count") != len(mentions):
        raise ValueError("morning news mention count mismatch")
    if any(payload.get(key) is not False for key in _SAFETY):
        raise ValueError("morning news safety boundary changed")
    if payload.get("recommendation_status") != "RESEARCH_ONLY":
        raise ValueError("morning news recommendation boundary changed")
    return trade_date


def _latest_path(root: Path) -> Path:
    return resolve_under(root, "morning_news/latest.json")


def _load_latest(root: Path) -> dict[str, Any]:
    path = _latest_path(root)
    if not path.is_file():
        return {"schema_version": LATEST_SCHEMA_VERSION, "entries": {}}
    value = SafeRootStore(root)._read_json(path)
    if value.get("schema_version") != LATEST_SCHEMA_VERSION or not isinstance(value.get("entries"), Mapping):
        raise ValueError("morning news latest pointer is corrupt")
    return value


def publish_morning_news(root: Path | str, payload: Mapping[str, Any]) -> dict[str, Any]:
    root = Path(root)
    trade_date = _validate_payload(payload)
    digest = sha256_json(payload)
    run_id = f"{trade_date}-morning-news-{digest[:12]}"
    run_relative = f"morning_news/runs/{trade_date}/{run_id}"
    payload_relative = f"{run_relative}/payload.json"
    manifest_relative = f"{run_relative}/manifest.json"
    receipt_relative = f"{run_relative}/receipt.json"
    store = SafeRootStore(root)
    with store._lock():
        latest = _load_latest(root)
        existing = latest["entries"].get(trade_date)
        if isinstance(existing, Mapping):
            current = read_morning_news(root, trade_date)
            if existing.get("payload_sha256") == digest and current == dict(payload):
                return {**dict(existing), "already_exists": True}
            raise MorningNewsConflict(f"morning news date slot changed: {trade_date}")
        run_dir = resolve_under(root, run_relative)
        run_dir.mkdir(parents=True, exist_ok=False)
        store._write_json(resolve_under(root, payload_relative), payload)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "trade_date": trade_date,
            "run_id": run_id,
            "payload_relative": payload_relative,
            "payload_sha256": digest,
            "article_count": payload["article_count"],
            "mention_count": payload["mention_count"],
            **_SAFETY,
        }
        store._write_json(resolve_under(root, manifest_relative), manifest)
        receipt = {
            **manifest,
            "manifest_relative": manifest_relative,
            "manifest_sha256": sha256_json(manifest),
            "receipt_relative": receipt_relative,
            "status": payload["status"],
        }
        store._write_json(resolve_under(root, receipt_relative), receipt)
        entry = {
            "trade_date": trade_date,
            "run_id": run_id,
            "payload_relative": payload_relative,
            "payload_sha256": digest,
            "manifest_relative": manifest_relative,
            "receipt_relative": receipt_relative,
        }
        entries = dict(latest["entries"])
        entries[trade_date] = entry
        store._write_json(_latest_path(root), {"schema_version": LATEST_SCHEMA_VERSION, "entries": entries})
    read_morning_news(root, trade_date)
    return {**entry, "already_exists": False}


def read_morning_news(root: Path | str, trade_date: str) -> dict[str, Any]:
    root = Path(root)
    trade_date = validate_date(trade_date)
    entry = _load_latest(root)["entries"].get(trade_date)
    if not isinstance(entry, Mapping):
        raise ValueError(f"morning news slot missing: {trade_date}")
    store = SafeRootStore(root)
    payload = store._read_json(resolve_under(root, str(entry.get("payload_relative") or "")))
    manifest = store._read_json(resolve_under(root, str(entry.get("manifest_relative") or "")))
    receipt = store._read_json(resolve_under(root, str(entry.get("receipt_relative") or "")))
    digest = sha256_json(payload)
    if (
        _validate_payload(payload) != trade_date
        or digest != entry.get("payload_sha256")
        or manifest.get("payload_sha256") != digest
        or receipt.get("manifest_sha256") != sha256_json(manifest)
        or any(receipt.get(key) is not False for key in _SAFETY)
    ):
        raise ValueError("morning news manifest or receipt mismatch")
    return payload


__all__ = [
    "MorningNewsConflict",
    "materialize_stock_mentions",
    "news_quality_score",
    "normalize_legacy_morning_news",
    "publish_morning_news",
    "read_morning_news",
]
