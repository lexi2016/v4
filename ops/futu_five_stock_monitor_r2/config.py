"""Frozen CHATGPT_MASTER anchors, dated 2026-11-20; never auto-rebased."""
from dataclasses import dataclass

BASE_DATE = "2026-11-20"
STREAMS = ("QUOTE", "K_1M", "K_5M", "K_DAY", "TICKER")
SAFETY = dict(RESEARCH_ONLY=True, production_allowed=False,
              buy_gate_updated=False, orders_sent=False)


@dataclass(frozen=True)
class Stock:
    code: str
    name: str
    currency: str
    risk: float
    rises: tuple[tuple[float, str], ...]
    zones: tuple[tuple[float, float, str], ...] = ()
    touch: float | None = None
    notes: str = ""
    key_k: str = "新关键K及有效承接未认证"


STOCKS = {
    s.code: s for s in (
        Stock("SZ.000610", "西安旅游", "CNY", 7.20,
              ((7.33, "结构修复观察"), (7.89, "新一轮攻击观察")),
              ((6.65, 6.66, "次级支撑风险观察"),),
              notes="REORG_ACCEPTED / ST_DELISTING_RISK；重整受理不代表成功",
              key_k="7.20近期风险线；非新关键K认证"),
        Stock("SZ.002865", "钧达股份", "CNY", 27.72,
              ((29.24, "第一修复观察"), (31.60, "趋势恢复观察"), (34.00, "第二级攻击观察")),
              ((31.26, 31.60, "第一压力区"), (33.15, 34.00, "第二压力区")),
              notes="OLD_KEY_K_INVALIDATED：旧33.44–33.50失效；无新关键K及承接不认证完整B买点"),
        Stock("SZ.300920", "润阳科技", "CNY", 29.56,
              ((31.08, "初步修复观察"), (32.32, "进一步转强观察"),
               (32.98, "攻击观察"), (34.50, "更高一级突破观察")),
              notes="11/20放量下跌，不能定义洗盘；新建仓波未认证"),
        Stock("SZ.300893", "松原安全", "CNY", 15.04,
              ((15.97, "重新转强观察"), (16.21, "攻击确认候选"), (16.60, "新高突破观察")),
              touch=15.30, key_k="2026-11-09关键K 15.04–15.97；站回上沿不自动确认买点"),
        Stock("HK.07666", "剂泰科技-P", "HKD", 6.560,
              ((7.345, "止跌修复观察"), (8.360, "初步转强观察"), (8.465, "突破观察")),
              ((8.360, 8.465, "前期压力区"),),
              notes="HK_REFERENCE_ONLY；下降趋势未确认结束；公告不等于买入确认"),
    )
}
