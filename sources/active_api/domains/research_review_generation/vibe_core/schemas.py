"""复盘结论的结构化 schema（市场与板块层面）"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import List, Mapping

from pydantic import BaseModel, Field, field_validator


# 情绪档位五档（模型可能产出「亢奋末期」「修复偏强」等，归一化到含有的那一档）
PHASES = ["冰点", "修复", "发酵", "亢奋", "退潮"]


class FocusDirection(BaseModel):
    direction: str = Field(min_length=2, description="题材/板块/方向名")
    logic: str = Field(min_length=4, description="该方向今日活跃的支撑依据（情绪/资金/题材/龙头 哪几条）")
    risk: str = Field(min_length=2, description="该方向的风险 / 证伪信号")


class VerificationItem(BaseModel):
    """明日验证条件：从固定指标集里选一个读数 + 预期方向"""

    metric: str = Field(description="可核验指标 key（只能从给定清单里选）")
    direction: str = Field(description="预期明日方向：上升/下降/持平")
    reason: str = Field(min_length=2, description="为什么这条能验证今晚的判断")

    @field_validator("direction")
    @classmethod
    def _normalize_direction(cls, v: str) -> str:
        from .verification import DIRECTIONS

        for d in DIRECTIONS:
            if d in v:
                return d
        raise ValueError(f"方向需含 {DIRECTIONS} 之一，得到 {v!r}")

    @field_validator("metric")
    @classmethod
    def _known_metric(cls, v: str) -> str:
        from .verification import METRICS

        keys = {m.key for m in METRICS}
        v = v.strip()
        if v not in keys:
            raise ValueError(f"未知指标 {v!r}，只能从 {sorted(keys)} 里选")
        return v


class TomorrowFocus(BaseModel):
    emotion_phase: str = Field(description="市场情绪档位：冰点/修复/发酵/亢奋/退潮")
    market_oneliner: str = Field(min_length=4, description="今日盘面一句话总结")
    focus_directions: List[FocusDirection] = Field(
        min_length=2, max_length=5, description="当前活跃的题材/板块方向（2-5 个）"
    )
    risk_alerts: List[str] = Field(default_factory=list, description="需要警惕的风险信号")
    verification_items: List[VerificationItem] = Field(
        default_factory=list, max_length=5,
        description="明日验证条件（2-5 条）：明天用哪些市场事实检验今晚的判断",
    )

    @field_validator("emotion_phase")
    @classmethod
    def _normalize_phase(cls, v: str) -> str:
        for p in PHASES:
            if p in v:
                return p
        raise ValueError(f"情绪档位需含 {PHASES} 之一，得到 {v!r}")


# 「涨停家数」和「最高连板」是两个不同的事实字段。模型经常把前者的
# 数字接上「板」（例如把「元件涨停 14 家、最高 1 板」写成「元件以 14
# 板居首」），只靠 prompt 很难保证长期不回归。这里保留一个小而确定的
# 事实闸：只有 `market_facts.theme_structure` 明确给出某行业的两项数字时
# 才校验；找不到证据就不猜，也不重写原文。
_COUNT_RE = re.compile(
    r"涨停(?:家数|数量|股数)?\s*(?P<num>\d{1,4})\s*(?P<unit>家|只)"
    r"|(?P<num_rev>\d{1,4})\s*(?P<unit_rev>家|只)\s*涨停"
)
_COUNT_NO_UNIT_RE = re.compile(
    r"涨停(?:家数|数量|股数)\s*(?:为|是|达|约)?\s*(?P<num>\d{1,4})(?!\s*[家只])"
)
_HIGHEST_RE = re.compile(
    r"最高(?:连板|板位|高度|标)?\s*(?:为|是|达|仅|约)?\s*"
    r"(?P<num>\d{1,4})\s*板"
)
_BOARD_RE = re.compile(r"(?<![\d.])(?P<num>\d{1,4})\s*板")
_CLAUSE_BREAKS = "，,；;。！？!?、：:\n"
_CONNECTORS = "以为有共是达约"


def _fact_int(value: object) -> int | None:
    """Return an integer only for a finite, non-negative scalar fact."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number != int(number):
        return None
    return int(number)


def _theme_fact_index(market_facts: Mapping[str, object] | None) -> dict[str, tuple[int, int]]:
    """Build an unambiguous ``sector -> (limit_up, highest)`` index.

    The index intentionally accepts only the exact structured source used by
    the A-share review.  Textual reports, copied snapshots, and partial rows
    are not evidence for a correction.
    """
    if not isinstance(market_facts, Mapping):
        return {}
    structure = market_facts.get("theme_structure")
    if not isinstance(structure, Mapping) or structure.get("available") is not True:
        return {}
    themes = structure.get("themes")
    if not isinstance(themes, list):
        return {}

    candidates: dict[str, set[tuple[int, int]]] = {}
    for theme in themes:
        if not isinstance(theme, Mapping):
            continue
        sector = str(theme.get("sector") or "").strip()
        limit_up = _fact_int(theme.get("limit_up"))
        highest = _fact_int(theme.get("highest"))
        if len(sector) < 2 or limit_up is None or highest is None or highest < 1:
            continue
        candidates.setdefault(sector, set()).add((limit_up, highest))
    # Duplicate rows are fine; conflicting rows are not safe to resolve.
    return {sector: next(iter(values)) for sector, values in candidates.items() if len(values) == 1}


def _number_group(match: re.Match[str]) -> str:
    return "num" if match.group("num") is not None else "num_rev"


def _replace_number(match: re.Match[str], value: int) -> str:
    group = _number_group(match)
    start, end = match.span(group)
    text = match.string
    return text[match.start():start] + str(value) + text[end:match.end()]


def _clause_start(text: str, position: int) -> int:
    start = position
    while start > 0 and text[start - 1] not in _CLAUSE_BREAKS:
        start -= 1
    return start


def _sector_for_board(text: str, position: int, sectors: list[str]) -> str | None:
    """Find one sector in the same short clause as a generic ``N板`` token."""
    start = _clause_start(text, position)
    clause = text[start:position]
    hits = [(clause.find(sector), sector) for sector in sectors if sector in clause]
    hits = [(index, sector) for index, sector in hits if index >= 0]
    if len(hits) == 1:
        return hits[0][1]
    # When a clause names several sectors, only a sector immediately before
    # the number can be attributed without guessing.
    nearby = [(index, sector) for index, sector in hits if position - (start + index) <= 18]
    if len(nearby) == 1:
        return nearby[0][1]
    return None


def _guard_fact_text(text: str, facts: Mapping[str, tuple[int, int]]) -> tuple[str, list[str]]:
    """Align sector count/height mentions with structured facts.

    A direct, explicitly labelled count or height is repaired by replacing its
    number with the source number.  An unlabeled ``N板`` is repaired only when
    ``N`` exactly equals the source count; this is the known count-to-board
    failure mode.  Other ambiguous values become a visible CANNOT_CONFIRM
    marker carrying the two source facts.
    """
    if not isinstance(text, str) or not text or not facts:
        return text, []

    sectors = sorted(facts, key=len, reverse=True)
    if not any(sector in text for sector in sectors):
        return text, []

    notes: list[str] = []
    # Work on explicitly labelled fields first.  Replacing only the numeric
    # span keeps the model's surrounding explanation intact.
    for sector in sectors:
        if sector not in text:
            continue
        limit_up, highest = facts[sector]

        def replace_count(match: re.Match[str]) -> str:
            if _sector_for_board(text, match.start(), sectors) != sector:
                return match.group(0)
            number_group = _number_group(match)
            number = int(match.group(number_group))
            if number == limit_up:
                return match.group(0)
            notes.append(f"{sector}涨停家数 {number}→{limit_up}")
            return _replace_number(match, limit_up)

        text = _COUNT_RE.sub(replace_count, text)

        def replace_count_without_unit(match: re.Match[str]) -> str:
            if _sector_for_board(text, match.start(), sectors) != sector:
                return match.group(0)
            number = int(match.group("num"))
            if number == limit_up:
                return match.group(0)
            notes.append(f"{sector}涨停家数 {number}→{limit_up}")
            return _replace_number(match, limit_up)

        text = _COUNT_NO_UNIT_RE.sub(replace_count_without_unit, text)

        def replace_highest(match: re.Match[str]) -> str:
            if _sector_for_board(text, match.start(), sectors) != sector:
                return match.group(0)
            number = int(match.group("num"))
            if number == highest:
                return match.group(0)
            notes.append(f"{sector}最高连板 {number}→{highest}")
            return _replace_number(match, highest)

        text = _HIGHEST_RE.sub(replace_highest, text)

    # Generic board mentions need a sector attribution.  A direct highest
    # phrase has already been checked; skip the same token here.
    # Apply from right to left so a longer replacement cannot invalidate the
    # offsets of another board token in the same field.
    for match in reversed(list(_BOARD_RE.finditer(text))):
        position = match.start()
        before = text[_clause_start(text, position):position]
        if re.search(r"最高(?:连板|板位|高度|标)?\s*(?:为|是|达|仅|约)?\s*$", before):
            continue
        sector = _sector_for_board(text, position, sectors)
        if sector is None:
            continue
        limit_up, highest = facts[sector]
        number = int(match.group("num"))
        if number == highest or number == limit_up == highest:
            continue
        if number == limit_up:
            replacement = f"涨停{limit_up}家（最高{highest}板）"
            notes.append(f"{sector}将{number}板校正为涨停{limit_up}家、最高{highest}板")
            # Pull a small count connector into the replacement so the
            # canonical wording stays grammatical: ``元件以14板`` becomes
            # ``元件涨停14家（最高1板）`` rather than ``元件以涨停14家``.
            clause_start = _clause_start(text, position)
            sector_start = text.rfind(sector, clause_start, position)
            if sector_start >= 0:
                between = text[sector_start + len(sector):position]
                if re.fullmatch(r"(?:板块)?\s*(?:以|为|有|共|是|达|约|达到)?\s*", between):
                    label = text[sector_start:sector_start + len(sector)]
                    if "板块" in between:
                        label += "板块"
                    text = text[:sector_start] + label + replacement + text[match.end():]
                    continue
        else:
            replacement = f"CANNOT_CONFIRM（{sector}客观事实：涨停{limit_up}家，最高{highest}板）"
            notes.append(f"{sector}板位数字 {number} 无法与客观事实对齐，标记 CANNOT_CONFIRM")
        text = text[:match.start()] + replacement + text[match.end():]

    return text, notes


def guard_focus_against_market_facts(
    focus: Mapping[str, object] | None,
    market_facts: Mapping[str, object] | None,
) -> tuple[dict[str, object] | None, list[str]]:
    """Guard structured focus prose against exact sector facts.

    This function is deliberately pure and idempotent.  It does not inspect or
    rewrite an on-disk review; callers decide whether to use the returned copy
    for a new render/save operation.  Existing historical evidence therefore
    remains byte-for-byte untouched.
    """
    if not isinstance(focus, Mapping):
        return focus if focus is None else dict(focus), []
    facts = _theme_fact_index(market_facts)
    if not facts:
        return deepcopy(dict(focus)), []

    guarded = deepcopy(dict(focus))
    notes: list[str] = []

    def guard_value(value: object) -> object:
        if not isinstance(value, str):
            return value
        updated, value_notes = _guard_fact_text(value, facts)
        notes.extend(value_notes)
        return updated

    for key in ("market_oneliner",):
        if key in guarded:
            guarded[key] = guard_value(guarded[key])
    directions = guarded.get("focus_directions")
    if isinstance(directions, list):
        for direction in directions:
            if not isinstance(direction, dict):
                continue
            for key in ("logic", "risk"):
                if key in direction:
                    direction[key] = guard_value(direction[key])
    alerts = guarded.get("risk_alerts")
    if isinstance(alerts, list):
        guarded["risk_alerts"] = [guard_value(value) for value in alerts]

    # The same phrase may appear in both logic and risk; a warning is useful,
    # but duplicate entries are noise and make serialized evidence harder to
    # inspect.
    return guarded, list(dict.fromkeys(notes))


# 给 JSON 模式的英文键名骨架（比 with_structured_output 对中文 LLM 更稳）
FOCUS_SKELETON = """{
  "emotion_phase": "情绪档位，只能填：冰点/修复/发酵/亢奋/退潮 之一",
  "market_oneliner": "今日盘面一句话总结",
  "focus_directions": [
    {"direction": "题材/板块名", "logic": "今日活跃的支撑依据(逻辑链；涨停家数写N家/只，最高连板写N板)", "risk": "风险/证伪点"}
  ],
  "risk_alerts": ["风险信号1", "风险信号2"]
}
（focus_directions 必须 2~5 个）
（硬约束：涨停家数=N家/只；最高连板=N板；两者不可混写。无法和客观事实表对齐时填 CANNOT_CONFIRM。）"""

_DISCLAIMER = "> ⚠️ 本页由 AI 多 agent 生成，仅供参考，不构成投资建议；市场有风险，决策与盈亏自负。\n"


def render_tomorrow_focus(tf: TomorrowFocus) -> str:
    """把结构化结论渲染成 markdown。"""
    lines = ["# 盘面研判\n", _DISCLAIMER]
    lines.append(f"**情绪档位**：{tf.emotion_phase}\n")
    lines.append(f"**今日盘面**：{tf.market_oneliner}\n")
    lines.append("\n## 活跃方向\n")
    if not tf.focus_directions:
        lines.append("（无）\n")
    for i, d in enumerate(tf.focus_directions, 1):
        lines.append(f"### {i}. {d.direction}")
        lines.append(f"- 依据：{d.logic}")
        lines.append(f"- 风险/证伪：{d.risk}\n")
    lines.append("## 风险提示")
    if tf.risk_alerts:
        for r in tf.risk_alerts:
            lines.append(f"- {r}")
    else:
        lines.append("- （无）")
    if tf.verification_items:
        # 明日验证条件：不是"明天买什么"，是"明天用哪些客观读数检验今晚的判断"
        from .verification import METRICS

        label = {m.key: m.label for m in METRICS}
        lines.append("## 明日验证条件")
        for v in tf.verification_items:
            lines.append(f"- **{label.get(v.metric, v.metric)}** 预期{v.direction} —— {v.reason}")
        lines.append("")
    return "\n".join(lines)
