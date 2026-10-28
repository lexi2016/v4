"""ops.materialize_research_peripherals: entity_topics (review candidate, not deployment)."""
from __future__ import annotations
from ._namespace import read_global as _v4_global


def __detect_stock_focus_body(_v4_scope, /, text, symbols, entities):
    focus: list[str] = []
    for symbol in symbols:
        if symbol and symbol not in focus:
            focus.append(symbol)
    for raw_name in entities:
        name = _v4_global(_v4_scope, '_normalize_entity_name')(raw_name)
        if _v4_global(_v4_scope, '_is_noise_entity')(name):
            continue
        if not _v4_global(_v4_scope, 'any')(name in item for item in focus):
            focus.append(f"{name}(代码待核)")
        if _v4_global(_v4_scope, 'len')(focus) >= 8:
            break
    return focus[:8]


def __theme_score_map_body(_v4_scope, /, text):
    normalized = _v4_global(_v4_scope, '_clean_markup')(text)
    scores: Counter[str] = _v4_global(_v4_scope, 'Counter')()
    for theme, keywords in _v4_global(_v4_scope, '_AI_THEME_RULES'):
        score = _v4_global(_v4_scope, 'sum')(_v4_global(_v4_scope, '_keyword_hits')(normalized.lower(), keyword) for keyword in keywords)
        if theme == "PCB/电子布/电子材料":
            if _v4_global(_v4_scope, '_has_keyword')(normalized, "PCB"):
                score += 3
            if "电子布" in normalized:
                score += 2
        if score:
            scores[theme] = score
    return scores


def __priority_score_body(_v4_scope, /, item):
    if item.get("status_item") or item.get("credibility_warning"):
        return -20
    score = {"L4": 6, "L3": 4, "L2": 2, "L1": 0}.get(_v4_global(_v4_scope, 'str')(item.get("evidence_level")), 0)
    if item.get("theme") and item.get("theme") != "其他待复核":
        score += 2
    if item.get("source_type") == "ZSXQ":
        score += 3
    elif item.get("source_type") == "finance":
        score += 1
    if item.get("freshness_label") == "本小时新增":
        score += 4
    if item.get("freshness_label") == "本轮抓取":
        score += 1
    score += _v4_global(_v4_scope, 'min')(
        4,
        2
        * _v4_global(_v4_scope, 'sum')(
            1
            for key in ("target_price", "rating", "earnings_forecast", "valuation_assumption")
            if item.get(key)
        ),
    )
    if item.get("stock_focus"):
        score += 2
    if item.get("source_url"):
        score += 1
    if _v4_global(_v4_scope, 'len')(_v4_global(_v4_scope, 'str')(item.get("event_fact") or "")) >= 80:
        score += 1
    if _v4_global(_v4_scope, 'any')(marker in _v4_global(_v4_scope, 'clean_text')(item.get("title")) for marker in ("周报", "复盘", "舆情热点", "全天涨停复盘", "市场+宏观", "市场综述", "市场终评", "交易台")):
        score -= 4
    if _v4_global(_v4_scope, 'len')(item.get("stock_focus") or []) >= 6:
        score -= 2
    return score
