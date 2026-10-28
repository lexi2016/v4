"""Explicit prompt objects; no environment or HOME lookup.

The caller must explicitly select the frozen built-in pack. Custom packs require
a separate source-bound review; they are never silently replaced by this pack.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from pydantic import BaseModel
from . import schemas
from .deepdive import schemas as dd_schemas

@dataclass(frozen=True)
class PromptPack:
    """一套完整的分析口径。引擎只认这个接口，不关心里面写了什么。"""

    name: str
    analyst_style: str            # 五个复盘分析师的语气/尺度
    analyst_len: str              # 篇幅约束
    judge_requirements: str       # 复盘裁判的产出要求（编号列表正文）
    focus_model: type[BaseModel]  # 复盘结论 schema
    focus_skeleton: str           # 给 JSON 模式的英文键骨架
    render_focus: Callable[[Any], str]
    chat_guidance: str = (
        "只做两件事：① 解释、展开、比较上面已经给出的结论与数据；② 讲清计算口径、"
        "证据来源、历史同类情况。个股一律只作客观陈述（题材归属、涨停梯队、龙虎榜席位等公开事实），"
        "不给参与倾向（能不能买/值不值得参与/谁更稳）、不给买卖点位或时机、不做品种推荐。"
        "上面没覆盖的就说没覆盖，别编。"
    )
    # 个股深挖（按需跑的单股 agent）的口径。⚠️ 与 chat_guidance 同理，**必须带默认值**：
    # 用户的本地包多半是在这几条字段加进来之前写的，不给默认值会让它构造 PromptPack 时
    # 因缺参报错 → 静默回退默认包（表现是"跑起来了但口径全变了"，最难发现）。
    deepdive_style: str = (
        "基于数据讲清楚这只标的当前是什么状态、依据是什么。"
        "只作客观描述与风险披露，不给参与倾向、不给买卖点位。"
    )
    deepdive_requirements: str = """1. 一句话概括这只标的当前的客观状态。
2. 题材归属与它和当前市场主线的关系。
3. 资金面状态（龙虎榜/量能/主力动向）。
4. 技术位置（所处区间、形态、连板情况）。
5. 需要披露的风险点。
6. 总结正反两方的核心分歧。
⚠️ 只做事实描述与风险披露：不给参与倾向（值得关注/回避之类）、不给关注点位或买卖时机。"""
    verdict_model: type[BaseModel] = dd_schemas.StockProfile   # 个股结论 schema
    verdict_skeleton: str = dd_schemas.PROFILE_SKELETON
    render_verdict: Callable[[Any], str] = dd_schemas.render_profile


RESEARCH_PACK = PromptPack(
    name="research",
    analyst_style=(
        "基于数据讲清楚今天盘面发生了什么、为什么，把依据摆出来。"
        "个股只作客观陈述（涨停梯队、龙虎榜席位、题材归属等公开事实），"
        "不点名推荐、不给参与倾向、不给买卖点位。"
    ),
    analyst_len="控制在 350 字内。",
    judge_requirements="""1. 判断当前市场情绪档位（冰点/修复/发酵/亢奋/退潮）。
2. 梳理 2-5 个当前活跃的题材/板块方向，每个含：支撑依据（情绪/资金/题材/龙头 哪几条）、以及该方向的风险与证伪信号。
3. 列出需警惕的风险信号。
4. 给出你对**市场所处阶段**的判断。
5. **事实单位必须严格区分**：涨停家数写成“涨停 N 家/只”，最高连板写成“最高 N 板”。
   “元件涨停 14 家、最高 1 板”绝不能写成“元件 14 板”；同一句同时出现两项时，
   必须分别保留“家/只”和“板”单位，不得用“板”代替家数。
6. 只引用今日客观事实表中能对上题材/板块的数字；找不到对应来源或数字无法对齐时，写
   `CANNOT_CONFIRM`，不要按语义猜测或把涨停家数改成连板高度。
⚠️ 全程只做市场与板块层面的研判：不点名推荐个股、不给个股参与倾向、不给买卖点位或时机。""",
    focus_model=schemas.TomorrowFocus,
    focus_skeleton=schemas.FOCUS_SKELETON,
    render_focus=schemas.render_tomorrow_focus,
)
