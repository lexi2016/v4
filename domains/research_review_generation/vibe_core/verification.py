"""Pure verification menu and optional LLM extraction, no user-state writes."""
from __future__ import annotations
from typing import Callable, Optional

# 方向的含义：预期这个读数明天往哪走
DIRECTIONS = ["上升", "下降", "持平"]


def _pick(d: dict, *path, need_available: bool = True):
    """从嵌套 dict 里取值；中途 available=False 或缺键都返回 None。"""
    node = d
    for i, k in enumerate(path):
        if not isinstance(node, dict):
            return None
        if i == 0 and need_available and not node.get(k, {}).get("available", True):
            return None
        node = node.get(k)
        if node is None:
            return None
    return node if isinstance(node, (int, float)) else None


class Metric:
    """一个可核验的市场读数。

    `eps` 是"变了才算变"的阈值 —— 没有它的话，涨停家数 40→41 会被当成"上升"，
    把噪声当成判断兑现。
    `higher_is_hotter` 只用于给 UI 提示语义（炸板率升 = 情绪转弱），不影响核验。
    """

    def __init__(self, key: str, label: str, hint: str, eps: float,
                 getter: Callable[[dict, dict], Optional[float]],
                 higher_is_hotter: bool = True, unit: str = ""):
        self.key, self.label, self.hint = key, label, hint
        self.eps, self.getter = eps, getter
        self.higher_is_hotter, self.unit = higher_is_hotter, unit


METRICS: list[Metric] = [
    Metric("limit_up_count", "涨停家数", "市场整体的赚钱意愿", eps=5,
           getter=lambda m, f: _pick(m, "promotion", "limit_up_count"), unit="家"),
    Metric("highest_board", "最高连板高度", "情绪的天花板，压缩=周期见顶", eps=0.5,
           getter=lambda m, f: _pick(m, "ladder_gap", "highest"), unit="板"),
    Metric("promotion_1to2", "1进2 晋级率", "最敏感的一档，走低=接力意愿收缩", eps=0.05,
           getter=lambda m, f: _pick(m, "promotion", "tiers", "1进2", "rate"), unit=""),
    Metric("money_effect_median", "赚钱效应中位数", "多数人的体感", eps=0.5,
           getter=lambda m, f: _pick(m, "money_effect", "median"), unit="%"),
    Metric("broken_rate", "炸板率", "资金分歧程度（炸板未回封占尝试数）", eps=0.05,
           getter=lambda m, f: _pick(f, "seal_quality", "broken_rate"),
           higher_is_hotter=False, unit=""),
    Metric("deep_loss_count", "跌超5%家数", "大面的量级，判退潮先看它", eps=5,
           getter=lambda m, f: _pick(f, "loss_effect", "deep_loss_5_count"),
           higher_is_hotter=False, unit="家"),
    Metric("theme_concentration", "头部题材集中度", "一枝独秀还是遍地开花", eps=0.05,
           getter=lambda m, f: _pick(f, "theme_structure", "concentration"), unit=""),
    Metric("market_limit_down", "全市场跌停家数", "极端风险的直接读数", eps=5,
           getter=lambda m, f: _pick(f, "loss_effect", "market_limit_down"),
           higher_is_hotter=False, unit="家"),
]

_BY_KEY = {m.key: m for m in METRICS}



def describe_items(items: list[dict], metrics: dict, facts: dict) -> list[dict]:
    """给今晚落盘的验证条件补上「今日基准值 + 变了才算变的阈值」。

    只写"预期上升"，第二天没法对账 —— 从多少涨到多少才算上升？
    阈值本来就定义在上面的 METRICS 里，今日读数也在同一份复盘里，
    不带出去的话，读者第二天只能凭感觉，而凭感觉的结论怎么变都能自圆其说。

    认不出的 metric key 原样返回（裁判偶尔会写出菜单外的键），不猜、不编。
    """
    out = []
    for it in items or []:
        m = _BY_KEY.get(str(it.get("metric") or ""))
        if m is None:
            out.append(dict(it))
            continue
        base = m.getter(metrics or {}, facts or {})
        out.append({**it, "label": m.label, "unit": m.unit, "eps": m.eps,
                    "base_value": base, "higher_is_hotter": m.higher_is_hotter})
    return out

def metric_menu() -> str:
    """给裁判 prompt 的可选指标清单。"""
    return "\n".join(f"  - {m.key}（{m.label}）：{m.hint}" for m in METRICS)

_EXTRACT_SKELETON = """{
  "items": [
    {"metric": "指标key", "direction": "上升/下降/持平", "reason": "这条为什么能验证今晚的判断"}
  ]
}"""


def extract_items(llm, focus_md: str, phase: str = "") -> list[dict]:
    """从已产出的复盘结论里，提炼 2-5 条明日可核验条件。

    失败返回空列表 —— 验证条件是增强，不该拖垮整条复盘。
    """
    from pydantic import BaseModel, Field, field_validator

    keys = {m.key for m in METRICS}

    class _Item(BaseModel):
        metric: str = Field(description="指标 key")
        direction: str = Field(description="上升/下降/持平")
        reason: str = Field(min_length=2, description="理由")

        @field_validator("direction")
        @classmethod
        def _d(cls, v: str) -> str:
            for d in DIRECTIONS:
                if d in v:
                    return d
            raise ValueError(f"方向需含 {DIRECTIONS} 之一")

        @field_validator("metric")
        @classmethod
        def _m(cls, v: str) -> str:
            v = v.strip()
            if v not in keys:
                raise ValueError(f"未知指标 {v!r}，只能从 {sorted(keys)} 选")
            return v

    class _Items(BaseModel):
        items: list[_Item] = Field(min_length=2, max_length=5)

    prompt = f"""下面是今晚的 A 股短线复盘结论{f'（情绪档位：{phase}）' if phase else ''}：

{focus_md[:2500]}

请挑 2-5 个**明日可核验的市场读数**，用来第二天检验今晚这份判断对不对。
只能从下面这份清单里选 metric（填 key），并给出预期方向（上升/下降/持平）与理由。

{metric_menu()}

要求：
- 挑**最能分辨这份判断对错**的读数：判退潮就挑退潮该有的变化，判修复就挑修复该有的。
- 方向要和今晚的判断一致 —— 这是自我检验，不是许愿。
- ⚠️ 这不是"明天买什么"，是"明天用哪些客观读数证明或证伪今晚的档位判断"。
  只涉及市场层面读数，不涉及任何个股、点位或买卖时机。"""

    try:
        from .structured import invoke_json_schema

        _, obj = invoke_json_schema(
            llm, prompt, _Items, lambda o: "", "验证条件抽取", _EXTRACT_SKELETON,
        )
        if obj is None:
            return []
        return [it.model_dump() for it in obj.items]
    except Exception:  # noqa: BLE001  抽不出来就不给，不影响复盘主流程
        return []
