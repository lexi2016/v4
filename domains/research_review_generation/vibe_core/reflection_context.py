"""Read-only reflection projection from caller-supplied records."""
from __future__ import annotations
import datetime
from typing import Optional
_MIN_SAMPLES_FOR_RATE = 30

def _parse_iso_date(value: object) -> Optional[datetime.date]:
    """只接受明确的 ISO 日期；未知日期不能进入历史 prompt。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None

def _visible_reflection(record: object, as_of: Optional[str] = None) -> bool:
    """判断回看记录是否能用于目标日，避免未来预测/评估泄漏。"""
    if not isinstance(record, dict):
        return False
    prediction = _parse_iso_date(record.get("prediction_date"))
    if prediction is None:
        return False
    if as_of is None:
        return True
    target = _parse_iso_date(as_of)
    if target is None or prediction >= target:
        return False
    evaluated = _parse_iso_date(record.get("eval_date"))
    return evaluated is not None and evaluated <= target


def _all_reflections(records: list[dict], as_of: Optional[str] = None) -> list[dict]:
    return [r for r in records if _visible_reflection(r, as_of)]

def latest_reflection(records: list[dict], as_of: Optional[str] = None) -> Optional[dict]:
    visible = _all_reflections(records, as_of)
    return visible[-1] if visible else None

def scoreboard(records: list[dict], as_of: Optional[str] = None) -> dict:
    """AI 判断的累计战绩 —— 「回测→先验→判断→次日验证」这个环的最后一块"""
    recs = _all_reflections(records, as_of)
    decided = [(r, (r.get("phase_eval") or {})) for r in recs]
    phase_rows = [(r, pe) for r, pe in decided if pe.get("hit") is not None]

    by_phase: dict[str, dict] = {}
    for _r, pe in phase_rows:
        b = by_phase.setdefault(pe["phase"], {"n": 0, "hit": 0})
        b["n"] += 1
        b["hit"] += 1 if pe["hit"] else 0
    for b in by_phase.values():
        b["hit_rate"] = round(b["hit"] / b["n"], 3) if b["n"] else None

    hits = sum(1 for _r, pe in phase_rows if pe["hit"])
    flat = sum(1 for _r, pe in decided if pe.get("hit") is None and pe.get("phase"))

    stock_hits = stock_samples = 0
    stock_days = 0
    for r in recs:
        rate = r.get("direction_hit_rate")
        if rate is None:
            continue
        stock_days += 1
        n = r.get("direction_samples")
        h = r.get("direction_hits")
        if not isinstance(n, int) or not isinstance(h, int):
            n = len([d for d in (r.get("directions") or []) if d.get("avg_next_ret") is not None]) or 1
            h = round(rate * n)
        stock_samples += n
        stock_hits += h

    decided_n = len(phase_rows)
    return {
        "phase": {
            "decided": decided_n,
            "hits": hits,
            "flat": flat,          # 持平未分胜负，不计入分母
            "next_day_direction_rate": round(hits / decided_n, 3) if decided_n else None,
            # 样本够不够撑得起一个百分比 —— 前端据此决定显不显示醒目数字
            "enough_samples": decided_n >= _MIN_SAMPLES_FOR_RATE,
            "min_samples": _MIN_SAMPLES_FOR_RATE,
            "by_phase": by_phase,
        },
        "stock": {
            "days": stock_days,              # 有个股靶子的天数
            "samples": stock_samples,        # 累计评估过的方向数 = 命中率的分母
            "hits": stock_hits,
            "hit_rate": round(stock_hits / stock_samples, 3) if stock_samples else None,
        },
        "recent": [
            {"prediction_date": r.get("prediction_date"),
             "eval_date": r.get("eval_date"),
             "phase": (r.get("phase_eval") or {}).get("phase"),
             "hit": (r.get("phase_eval") or {}).get("hit")}
            for r in recs[-10:]
        ],
    }

def get_past_context(records: list[dict], limit: int = 5, as_of: Optional[str] = None) -> str:
    """把近 limit 次命中回看摘成一段，供裁判 prompt 参考（记吃记打）。"""
    records_all = records
    records = _all_reflections(records, as_of)
    records = records[-limit:]
    if not records:
        return ""
    lines = ["【过往预测命中回看（供参考，避免重复追高/踏空）】"]

    # 累计战绩：让裁判知道自己历史上判得准不准，尤其是哪个档位常判错
    sb = scoreboard(records_all, as_of)["phase"]
    if sb["decided"]:
        weak = "；".join(
            f"{p} {b['hit']}/{b['n']}" for p, b in sb["by_phase"].items() if b["n"]
        )
        rate = sb.get("next_day_direction_rate")
        rate_txt = (f"，方向验证率 {rate:.0%}" if sb.get("enough_samples") and rate is not None
                    else f"（样本 {sb['decided']}/{sb.get('min_samples', 30)} 天，尚不足以谈比率）")
        lines.append(
            f"- 你过往档位隐含的次日方向：{sb['hits']}/{sb['decided']} 次对上{rate_txt}，"
            f"另有 {sb['flat']} 次次日持平未分胜负；分档位 [{weak}]。"
            f"⚠️ 这量的是「档位→次日方向」这套映射，不等于档位判断本身的对错。"
        )
    for r in reversed(records):
        parts = []

        # 情绪档位验证（市场层面靶子，任何 prompt 包都有）
        pe = r.get("phase_eval") or {}
        if pe.get("phase"):
            verdict = {True: "判对", False: "判错", None: "持平未分胜负"}[pe.get("hit")]
            parts.append(
                f"档位[{pe['phase']}]（预期情绪{'走强' if pe['expected_direction'] == 'up' else '转弱'}"
                f"、实际{ {'up': '走强', 'down': '转弱', 'flat': '持平'}[pe['actual_direction']] }→{verdict}）"
            )
        elif r.get("emotion_phase"):
            parts.append(f"档位[{r['emotion_phase']}]")

        # 个股靶子（仅当 prompt 包产出龙头预测时才有）
        hr = r.get("direction_hit_rate")
        if hr is not None:
            onr = r.get("overall_next_ret")
            onr_s = f"{onr:+.1f}%" if onr is not None else "—"
            dirs = "、".join(
                f"{d['direction']}({d['avg_next_ret']:+.1f}%)" if d.get("avg_next_ret") is not None
                else f"{d['direction']}(无数据)"
                for d in r.get("directions", [])
            )
            parts.append(f"方向命中率{hr:.0%}、龙头次日均涨{onr_s}；分方向[{dirs}]")

        if parts:
            lines.append(f"- {r['prediction_date']}预测→{r.get('eval_date','次日')}：" + "；".join(parts))
    return "\n".join(lines) if len(lines) > 1 else ""
