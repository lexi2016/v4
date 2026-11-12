"""A-share KB authority; source attribution and full MIT permission follow.

MIT License

Copyright (c) 2026 Huashu (花叔)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Selected pinned upstream functions are retained below for audit and reference.
Prefix caching and null policies are defined after those functions.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
import json
import logging
import math
from pathlib import Path
import pandas as pd
logger = logging.getLogger(__name__)

# Pinned source: core.py sha256=8423882092943a11d92b125e2834ef50641053faf984b4592cd12ff599a6c4c7
@dataclass
class DailyData:
    """单日行情数据"""

    ts_code: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    vol: float
    amount: float
    pct_chg: float
    prev_close: float = 0

    # 扩展形态与特征字段（供 strategies 策略计算使用）
    is_rise: bool = False
    is_beidou: bool = False
    is_suoliang: bool = False
    is_jiayin: bool = False
    is_yinxian: bool = False
    is_fangliang_yinxian: bool = False
    kdj_k: float | None = None
    kdj_d: float | None = None
    kdj_j: float | None = None
    bbi: float | None = None
    macd_dif: float | None = None
    macd_dea: float | None = None
    macd_hist: float | None = None

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        """dict 风格取值：缺失时返回 default。"""
        return getattr(self, key, default)


def calculate_ma(prices: list[float], period: int) -> float:
    """计算简单移动平均"""
    if len(prices) < period:
        return 0
    return sum(prices[-period:]) / period


def calculate_ema_series(prices: list[float], period: int) -> list[float]:
    """计算完整 EMA 序列，初值与 :func:`calculate_ema` 保持一致。"""
    if len(prices) < period:
        return []

    k = 2 / (period + 1)
    ema = prices[0]
    series = [ema]

    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
        series.append(ema)

    return series


def calculate_sma_series(values: list[float], period: int, m: int) -> list[float]:
    """
    通达信 SMA 递推序列（返回完整序列）

    与通达信完全一致：从序列第一个值开始递推，
    每个点的 SMA 都承接前一个点的结果。

    公式: SMA[i] = values[i] * M/N + SMA[i-1] * (1 - M/N)
    初始值: SMA[0] = values[0]

    Args:
        values: 输入序列
        period: 周期 N
        m: 权重 M

    Returns:
        SMA 序列（长度与输入一致）
    """
    if not values:
        return []

    weight = m / period
    sma = values[0]
    result = [sma]

    for v in values[1:]:
        sma = v * weight + sma * (1 - weight)
        result.append(sma)

    return result


def calculate_slope(values: list[float], period: int) -> float:
    """
    通达信 SLOPE 函数（线性回归斜率）

    公式: SLOPE = (N * SUM(X*Y) - SUM(X) * SUM(Y)) / (N * SUM(X^2) - SUM(X)^2)

    Args:
        values: 数据序列
        period: 周期 N

    Returns:
        斜率值（每bar变化量）
    """
    if len(values) < period:
        period = len(values)

    if period < 2:
        return 0

    recent = values[-period:]

    # 线性回归: y = a * x + b
    # slope a = (N*SUM(xy) - SUM(x)*SUM(y)) / (N*SUM(x^2) - SUM(x)^2)
    n = period
    sum_x = n * (n - 1) / 2  # 0+1+2+...+n-1
    sum_xx = (n - 1) * n * (2 * n - 1) / 6  # 0^2+1^2+...+(n-1)^2

    sum_y = sum(recent)
    sum_xy = sum(recent[i] * i for i in range(n))

    denominator = n * sum_xx - sum_x * sum_x
    if denominator == 0:
        return 0

    slope = (n * sum_xy - sum_x * sum_y) / denominator
    return slope


def _normalize_klines(klines: list) -> list[DailyData]:
    """将 list[dict] 或 list[DailyData] 统一为 list[DailyData]。"""
    if not klines:
        return []
    if isinstance(klines[0], DailyData):
        return klines
    # lazy import 避免循环依赖
    from modules.datasource import dict_to_daily

    return dict_to_daily(klines)


def calculate_kdj(klines: list, period: int = 9, k_ma: int = 3, d_ma: int = 3) -> tuple[float, float, float]:
    """
    计算 KDJ 指标

    Args:
        klines: K线数据（list[DailyData] 或 list[dict]，需要至少 period 天）
        period: RSV 周期，默认9
        k_ma: K 线的 MA 周期
        d_ma: D 线的 MA 周期

    Returns:
        (K, D, J) 值
    """
    klines = _normalize_klines(klines)
    if len(klines) < period:
        return 50, 50, 50  # 默认值

    # 计算 RSV
    rsv_list: list[float] = []
    for i in range(period - 1, len(klines)):
        low_list = [klines[j].low for j in range(i - period + 1, i + 1)]
        high_list = [klines[j].high for j in range(i - period + 1, i + 1)]

        low_min = min(low_list)
        high_max = max(high_list)

        if high_max == low_min:
            rsv = 50.0
        else:
            rsv = (klines[i].close - low_min) / (high_max - low_min) * 100

        rsv_list.append(rsv)

    if not rsv_list:
        return 50.0, 50.0, 50.0

    # 计算 K、D、J
    k = 50.0
    d = 50.0

    for rsv in rsv_list:
        k = (2 / 3) * k + (1 / 3) * rsv
        d = (2 / 3) * d + (1 / 3) * k

    j = 3 * k - 2 * d

    return round(k, 2), round(d, 2), round(j, 2)


def precompute_macd_sequence(
    klines: list[DailyData], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    """
    预计算全量 MACD 序列，使用 Pandas 向量化优化。

    返回每一天的 (DIF, DEA, MACD_HIST)。
    对于数据不足的天数，返回 0.0。
    """

    n = len(klines)
    if n < slow:
        return [0.0] * n, [0.0] * n, [0.0] * n

    df = pd.DataFrame({"close": [k.close for k in klines]})

    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow

    # Strictly match TDX loop initialization
    dif_series = dif.copy()
    dif_series.loc[: slow - 2] = 0.0

    dea_valid = dif_series.iloc[slow - 1 :].ewm(span=signal, adjust=False).mean()
    dea_series = pd.concat([pd.Series([0.0] * (slow - 1)), dea_valid]).reset_index(drop=True)

    macd_series = (dif_series - dea_series) * 2

    return dif_series.tolist(), dea_series.tolist(), macd_series.tolist()



# Pinned source: price_patterns/base.py sha256=999c2cb21dc24a1fec37add14a5a49e4b7ed2a5911e0149d8a54474893b7835c
def calculate_zg_white(klines: list[DailyData]) -> float:
    """
    计算 Z哥白线 = EMA(EMA(C,10),10)

    双重平滑后的短期动能线
    """
    if len(klines) < 10:
        return 0
    closes = [k.close for k in klines]
    ema1_series = calculate_ema_series(closes, 10)
    ema2_series = calculate_ema_series(ema1_series, 10)
    return round(ema2_series[-1], 2) if ema2_series else 0


def calculate_dg_yellow(klines: list[DailyData]) -> float:
    """
    计算 大哥线 = (MA14 + MA28 + MA57 + MA114) / 4

    多空生命线，长期均线系统
    """
    if len(klines) < 114:
        return 0
    closes = [k.close for k in klines]
    ma14 = calculate_ma(closes, 14)
    ma28 = calculate_ma(closes, 28)
    ma57 = calculate_ma(closes, 57)
    ma114 = calculate_ma(closes, 114)
    return round((ma14 + ma28 + ma57 + ma114) / 4, 2)


def detect_double_line_cross(klines: list[DailyData]) -> tuple[bool, bool]:
    """
    检测双线战法金叉死叉

    Returns:
        (is_gold_cross, is_dead_cross)
    """
    if len(klines) < 3:
        return False, False

    # 需要足够数据计算大哥线
    if len(klines) < 115:
        return False, False

    # 计算历史白线和大哥线
    white_values = []
    dg_values = []

    for i in range(60, len(klines) + 1):
        sub_klines = klines[:i]
        if len(sub_klines) >= 114:
            white = calculate_zg_white(sub_klines)
            dg = calculate_dg_yellow(sub_klines)
            white_values.append(white)
            dg_values.append(dg)

    if len(white_values) < 3:
        return False, False

    # 今天、前天、昨天
    w_today = white_values[-1]
    w_yesterday = white_values[-2]

    d_today = dg_values[-1]
    d_yesterday = dg_values[-2]

    # 金叉：白线从下方上穿大哥线
    gold_cross = w_yesterday <= d_yesterday and w_today > d_today

    # 死叉：白线从上方下穿大哥线
    dead_cross = w_yesterday >= d_yesterday and w_today < d_today

    return gold_cross, dead_cross


def calculate_rsl(klines: list[DailyData], period: int) -> float:
    """
    计算 RSL 相对强度定位（通达信标准公式）

    100*(C-LLV(L,N))/(HHV(C,N)-LLV(L,N))
    """
    if len(klines) < period:
        return 50

    recent = klines[-period:]
    lows = [k.low for k in recent]
    closes = [k.close for k in recent]
    current_close = klines[-1].close

    llv = min(lows)
    hhv = max(closes)  # 通达信用 HHV(CLOSE)，不是 HHV(HIGH)

    if hhv == llv:
        return 50

    rsl = (current_close - llv) / (hhv - llv) * 100
    return round(rsl, 2)


def detect_needle_20(klines: list[DailyData]) -> tuple[float, float, bool]:
    """
    检测单针下20信号（通达信标准）

    条件：短期RSL(3) <= 20 AND 长期RSL(21) >= 60
    即白线下20买：散户浮筹<20 且 主力控盘>60

    Returns:
        (rsl_short, rsl_long, is_needle_20)
    """
    if len(klines) < 22:
        return 50, 50, False

    rsl_short = calculate_rsl(klines, 3)
    rsl_long = calculate_rsl(klines, 21)

    is_needle = rsl_short <= 20 and rsl_long >= 60  # 对齐通达信

    return rsl_short, rsl_long, is_needle


def detect_needle_30(klines: list[DailyData]) -> bool:
    """
    检测单针下30信号（单针下20的迭代版）

    量化资金介入后阈值上移：
    - 红线(主力控盘) > 85
    - 白线(散户浮筹) < 30

    舍弃部分低位空间，换取更高确定性与入场频次
    """
    if len(klines) < 22:
        return False
    rsl_short = calculate_rsl(klines, 3)
    rsl_long = calculate_rsl(klines, 21)
    return rsl_long > 85 and rsl_short < 30



# Pinned source: price_patterns/brick.py sha256=a87ed7f6025387b6c1977d27ff0662bce0ed4f97b3360bc86a004cf83292401e
def calculate_brick_value(klines: list[DailyData]) -> float:
    """
    计算砖型图数值（通达信标准公式 - 短期砖型图指标v2026）

    VAR1A = (HHV(HIGH,4) - CLOSE) / (HHV(HIGH,4) - LLV(LOW,4)) * 100 - 90
    VAR2A = SMA(VAR1A, 4, 1) + 100
    VAR3A = (CLOSE - LLV(LOW,4)) / (HHV(HIGH,4) - LLV(LOW,4)) * 100
    VAR4A = SMA(VAR3A, 6, 1)
    VAR5A = SMA(VAR4A, 6, 1) + 100
    VAR6A = VAR5A - VAR2A
    砖型图 = IF(VAR6A > 4, VAR6A - 4, 0)
    """
    if len(klines) < 12:
        return 0

    highs = [k.high for k in klines]
    lows = [k.low for k in klines]
    closes = [k.close for k in klines]

    # 构建 VAR3A 序列（需要至少 6 个值来算 SMA(VAR3A,6,1)）
    var3a_list: list[float] = []
    for i in range(3, len(klines)):  # HHV/LLV 需要 4 天，所以从索引 3 开始
        hhv4 = max(highs[max(0, i - 3) : i + 1])
        llv4 = min(lows[max(0, i - 3) : i + 1])
        if hhv4 == llv4:
            v3 = 50.0
        else:
            v3 = (closes[i] - llv4) / (hhv4 - llv4) * 100
        var3a_list.append(v3)

    if len(var3a_list) < 6:
        return 0

    # VAR4A = SMA(VAR3A, 6, 1) —— 递推序列，每个点承接前一个结果
    var4a_list = calculate_sma_series(var3a_list, 6, 1)

    if len(var4a_list) < 6:
        return 0

    # VAR5A = SMA(VAR4A, 6, 1) + 100 —— 递推序列
    var5a_list = calculate_sma_series(var4a_list, 6, 1)
    var5a = var5a_list[-1] + 100

    # 构建 VAR1A 序列
    var1a_list = []
    for i in range(3, len(klines)):
        hhv4 = max(highs[max(0, i - 3) : i + 1])
        llv4 = min(lows[max(0, i - 3) : i + 1])
        if hhv4 == llv4:
            v1: float = -90.0
        else:
            v1 = (hhv4 - closes[i]) / (hhv4 - llv4) * 100 - 90.0
        var1a_list.append(v1)

    if len(var1a_list) < 4:
        var2a = (var1a_list[-1] if var1a_list else -90) + 100
    else:
        # VAR2A = SMA(VAR1A, 4, 1) + 100 —— 递推序列
        var2a_list = calculate_sma_series(var1a_list, 4, 1)
        var2a = var2a_list[-1] + 100

    # VAR6A = VAR5A - VAR2A
    var6a = var5a - var2a

    # 砖型图 = IF(VAR6A > 4, VAR6A - 4, 0)
    brick = var6a - 4 if var6a > 4 else 0

    return round(brick, 2)


def detect_brick_trend(klines: list[DailyData]) -> bool:
    """
    检测命值趋势是否上升

    条件：SLOPE(命值, 7) > -0.02 AND 运值 > 命值
    """
    if len(klines) < 115:
        return False

    closes = [k.close for k in klines]

    # 计算命值序列
    ming_values = []
    for i in range(113, len(klines)):
        sub = closes[: i + 1]
        ma14 = calculate_ma(sub, 14)
        ma28 = calculate_ma(sub, 28)
        ma57 = calculate_ma(sub, 57)
        ma114 = calculate_ma(sub, 114)
        ming = (ma14 + ma28 + ma57 + ma114) / 4
        ming_values.append(ming)

    if len(ming_values) < 8:
        return False

    # 使用正确的 SLOPE 函数计算7日斜率
    slope = calculate_slope(ming_values, 7)

    # 计算当前运值 and 命值
    current_ming = ming_values[-1]
    yun_zhi = calculate_zg_white(klines)

    return slope > -0.02 and yun_zhi > current_ming


def detect_four_brick_system(klines: list[DailyData]) -> dict:
    """
    四块砖交易体系检测

    通达信公式逻辑（与官方一致）：
    - 红砖 = 上涨动量（今日砖值 >= 昨日砖值）→ COLORRED
    - 绿砖 = 下跌动量（今日砖值 < 昨日砖值）→ COLOR00FF00

    规则：
    1. 红砖数满4块 → 减仓至少一半
    2. 红砖翻绿 → 立刻止损
    3. 绿砖下跌 → 绝不抄底，先数4块
    4. 买入后3天不涨 → 止损（DSZ铁律）
    """
    result = {
        "brick_consecutive": 0,  # 当前连续砖数
        "brick_action": "观望",  # 操作建议
        "brick_action_desc": "",  # 操作描述
        "is_brick_flip_green": False,  # 红砖刚翻绿（上涨转下跌）
    }

    if len(klines) < 10:
        result["brick_action_desc"] = "数据不足"
        return result

    # 计算历史砖值序列（至少需要8天才能开始算砖值）
    brick_history = []
    for i in range(8, len(klines) + 1):
        sub_klines = klines[:i]
        brick_val = calculate_brick_value(sub_klines)
        brick_history.append(brick_val)

    if len(brick_history) < 3:
        result["brick_action_desc"] = "数据不足"
        return result

    # 计算红绿砖：与官方公式一致
    # 1=红砖(上涨), -1=绿砖(下跌)
    colors = []
    for i in range(1, len(brick_history)):
        if brick_history[i] >= brick_history[i - 1]:
            colors.append(1)  # 红砖 = 上涨
        else:
            colors.append(-1)  # 绿砖 = 下跌

    if not colors:
        result["brick_action_desc"] = "无砖型数据"
        return result

    # 从最新往前数连续同色砖
    current_color = colors[-1]
    count = 1
    for i in range(len(colors) - 2, -1, -1):
        if colors[i] == current_color:
            count += 1
        else:
            break

    result["brick_consecutive"] = count

    # === 规则判断 ===

    # 1. 红砖翻绿（止损信号）- 上涨转下跌
    if current_color == -1 and len(colors) >= 2:
        prev_color = colors[-2] if len(colors) >= 2 else 1
        if prev_color == 1:
            # 刚翻绿
            result["is_brick_flip_green"] = True
            result["brick_action"] = "止损"
            result["brick_action_desc"] = f"红砖翻绿！立刻止损（连续红砖{count}块后翻绿）"
            return result

    # 2. 红砖数满4块 → 减仓（连续上涨）
    if current_color == 1 and count >= 4:
        result["brick_action"] = "减仓"
        if count == 4:
            result["brick_action_desc"] = "红砖已满4块，至少减仓一半"
        else:
            result["brick_action_desc"] = f"红砖已延续{count}块，趋势延续中，但未减仓需警惕"
        return result

    # 3. 绿砖下跌 → 禁止抄底（连续下跌）
    if current_color == -1:
        result["brick_action"] = "禁止抄底"
        if count >= 4:
            result["brick_action_desc"] = f"绿砖已连续{count}块，跌势可能接近尾声但仍禁止抄底"
        else:
            result["brick_action_desc"] = f"绿砖下跌中（{count}块），绝不抄底，先数4块"
        return result

    # 4. 红砖不足4块 → 持有/观察（上涨中）
    if current_color == 1 and count < 4:
        result["brick_action"] = "持有"
        result["brick_action_desc"] = f"红砖上涨中（{count}块），继续持有"
        return result

    result["brick_action"] = "观望"
    result["brick_action_desc"] = "中性"
    return result



# Pinned source: price_patterns/screener_helper.py sha256=e27ccaea93af97729969395bb8bc3f5dc526177cdcec7496d96fb9fa3bcffefd
def detect_volume_pattern(today: DailyData, yesterday: DailyData | None = None) -> dict[str, bool]:
    """
    检测量价形态
    """
    result = {
        "is_beidou": False,  # 倍量
        "is_suoliang": False,  # 缩量
        "is_jiayin_zhenyang": False,  # 假阴真阳
        "is_jiayang_zhenyin": False,  # 假阳真阴
        "is_fangliang_yinxian": False,  # 放量阴线
    }

    if yesterday is None:
        return result

    # 倍量：今日量 > 昨日量 × 2
    if today.vol >= yesterday.vol * 2:
        result["is_beidou"] = True

    # 缩量：今日量 < 昨日量 × 0.5
    if today.vol <= yesterday.vol * 0.5:
        result["is_suoliang"] = True

    # 假阴真阳：收 < 开 but 收 > 昨收
    if today.close < today.open and today.close > today.prev_close:
        result["is_jiayin_zhenyang"] = True

    # 假阳真阴：收 > 开 but 收 < 昨收
    if today.close > today.open and today.close < today.prev_close:
        result["is_jiayang_zhenyin"] = True

    # 放量阴线：下跌 + 放量
    if today.close < today.prev_close and today.vol > yesterday.vol * 1.5:
        result["is_fangliang_yinxian"] = True

    return result


def detect_didi(klines: list[DailyData]) -> dict:
    """
    滴滴战法检测（高位连续两根阴线下台阶）

    性质：最高优先级卖出信号，绕过防卖飞直接清仓。
    """
    if len(klines) < 2:
        return {"is_didi": False}

    today = klines[-1]
    yesterday = klines[-2]

    # 两根都是阴线（严格：收盘价 < 开盘价）
    is_yin_1 = yesterday.close < yesterday.open
    is_yin_2 = today.close < today.open

    # 下台阶：第二根收盘 < 第一根最低
    is_down_step = today.close < yesterday.low

    # 量未明显萎缩（今天量 >= 昨天量 × 0.8）
    is_volume_ok = today.vol >= yesterday.vol * 0.8 if yesterday.vol > 0 else False

    # 高位判断（当前 >= 近20天最高价的 80%）
    recent = klines[-20:] if len(klines) >= 20 else klines
    recent_high = max(k.high for k in recent)
    is_high = today.close >= recent_high * 0.8

    if is_yin_1 and is_yin_2 and is_down_step and is_volume_ok and is_high:
        return {
            "is_didi": True,
            "first_low": round(yesterday.low, 2),
            "second_close": round(today.close, 2),
            "volume_ratio": round(today.vol / yesterday.vol, 2) if yesterday.vol > 0 else 0,
            "recent_high": round(recent_high, 2),
        }

    return {"is_didi": False}


def detect_b1_today(klines: list[DailyData]) -> dict:
    """
    B1建仓波检测（只检查最新这天）
    标准：J<13, 振幅<4%, 涨幅-2%~+1.8%, 缩量
    """
    result: dict[str, Any] = {
        "is_b1": False,
        "b1_j_value": 0.0,
        "b1_amplitude": 0.0,
        "b1_pct_chg": 0.0,
        "b1_volume_shrink": False,
        "b1_score": 0.0,
    }
    if len(klines) < 2:
        return result
    today = klines[-1]
    prev = klines[-2]
    _, _, j = calculate_kdj(klines)
    amplitude = (today.high - today.low) / prev.close * 100 if prev.close > 0 else 0
    pct = today.pct_chg
    vol_shrink = today.vol < prev.vol
    score = 0
    if j < 13:
        score += 1
    if amplitude < 4:
        score += 1
    if -2 <= pct <= 1.8:
        score += 1
    if vol_shrink:
        score += 1
    if score >= 3:
        result["is_b1"] = True
    result["b1_j_value"] = round(j, 2)
    result["b1_amplitude"] = round(amplitude, 2)
    result["b1_pct_chg"] = round(pct, 2)
    result["b1_volume_shrink"] = vol_shrink
    result["b1_score"] = score
    return result


def detect_b2_today(klines: list[DailyData]) -> dict:
    """
    B2突破检测（只检查最新这天）
    标准：B1后5天内, 涨幅>=4%, 放量20%+, J<55
    """
    result: dict[str, Any] = {
        "is_b2": False,
        "b2_follows_b1": False,
        "b2_pct_chg": 0.0,
        "b2_j_value": 0.0,
        "b2_volume_up": False,
        "b2_score": 0.0,
    }
    if len(klines) < 10:
        return result
    today = klines[-1]
    prev = klines[-2]
    if not prev or prev.close <= 0:
        return result
    # 检查最近5天是否有B1痕迹
    has_recent_b1 = False
    for i in range(max(1, len(klines) - 5), len(klines)):
        _, _, j_check = calculate_kdj(klines[: i + 1])
        if j_check < 13:
            has_recent_b1 = True
            break
    _, _, j = calculate_kdj(klines)
    pct = today.pct_chg
    vol_up = today.vol > prev.vol * 1.2
    score = 0
    if has_recent_b1:
        score += 1
    if pct >= 4:
        score += 1
    if j < 55:
        score += 1
    if vol_up:
        score += 1
    if has_recent_b1 and pct >= 4 and score >= 3:
        result["is_b2"] = True
    result["b2_follows_b1"] = has_recent_b1
    result["b2_pct_chg"] = round(pct, 2)
    result["b2_j_value"] = round(j, 2)
    result["b2_volume_up"] = vol_up
    result["b2_score"] = score
    return result


def detect_centipede_pattern(klines: list[DailyData]) -> dict:
    """
    蜈蚣图识别 —— 堆量不涨、影线交替、无呼吸节奏的烂股形态

    五大因子（各0-20分，总分0-100）：
    1. 长上影线比例
    2. 长下影线比例
    3. 十字星比例
    4. 量能无规律
    5. 价格无趋势
    """
    result: dict[str, Any] = {
        "is_centipede": False,
        "score": 0,
        "factors": {},
    }

    if len(klines) < 20:
        return result

    recent = klines[-20:]
    factor_scores: dict[str, int] = {}

    # --- 因子1：长上影线比例 ---
    upper_shadow_days = 0
    for k in recent:
        body = abs(k.close - k.open)
        upper_shadow = k.high - k.close
        if body > 0 and upper_shadow > 2 * body:
            upper_shadow_days += 1
    upper_ratio = upper_shadow_days / 20
    if upper_ratio > 0.4:
        factor_scores["长上影线"] = 20
    elif upper_ratio > 0.25:
        factor_scores["长上影线"] = 10
    else:
        factor_scores["长上影线"] = 0

    # --- 因子2：长下影线比例 ---
    lower_shadow_days = 0
    for k in recent:
        body = abs(k.close - k.open)
        lower_shadow = k.close - k.low
        if body > 0 and lower_shadow > 2 * body:
            lower_shadow_days += 1
    lower_ratio = lower_shadow_days / 20
    if lower_ratio > 0.4:
        factor_scores["长下影线"] = 20
    elif lower_ratio > 0.25:
        factor_scores["长下影线"] = 10
    else:
        factor_scores["长下影线"] = 0

    # --- 因子3：十字星比例 ---
    doji_days = 0
    for k in recent:
        if k.open > 0:
            body_pct = abs(k.close - k.open) / k.open
            if body_pct < 0.01:
                doji_days += 1
    doji_ratio = doji_days / 20
    if doji_ratio > 0.3:
        factor_scores["十字星"] = 20
    elif doji_ratio > 0.15:
        factor_scores["十字星"] = 10
    else:
        factor_scores["十字星"] = 0

    # --- 因子4：量能无规律（变异系数） ---
    volumes = [k.vol for k in recent]
    vol_mean = sum(volumes) / len(volumes)
    if vol_mean > 0:
        vol_std = (sum((v - vol_mean) ** 2 for v in volumes) / len(volumes)) ** 0.5
        vol_cv = vol_std / vol_mean
    else:
        vol_cv = 0
    if vol_cv > 0.8:
        factor_scores["量能无规律"] = 20
    elif vol_cv > 0.5:
        factor_scores["量能无规律"] = 10
    else:
        factor_scores["量能无规律"] = 0

    # --- 因子5：价格无趋势（窄幅震荡 + 高波动） ---
    total_change = (recent[-1].close - recent[0].open) / recent[0].open if recent[0].open > 0 else 0
    daily_pcts = [k.pct_chg for k in recent]
    pct_mean = sum(daily_pcts) / len(daily_pcts)
    pct_std = (sum((p - pct_mean) ** 2 for p in daily_pcts) / len(daily_pcts)) ** 0.5
    is_range_bound = abs(total_change) < 0.05
    is_volatile = pct_std > 2.0
    if is_range_bound and is_volatile:
        factor_scores["价格无趋势"] = 20
    elif is_range_bound or is_volatile:
        factor_scores["价格无趋势"] = 10
    else:
        factor_scores["价格无趋势"] = 0

    # --- 汇总 ---
    total_score = sum(factor_scores.values())
    result["score"] = total_score
    result["factors"] = factor_scores
    result["is_centipede"] = total_score >= 60

    return result



# Pinned source: price_patterns/complex_patterns.py sha256=2c640ded837f5b091ebb5fdba6c8b0235a6c41a09985934cf27c740bceffb517
def detect_divergence(klines: list[DailyData], dif_list: list[float]) -> dict:
    """
    顶底背离系统化检测（基于语料标准）

    顶背离：价格创新高但DIF不创新高 → 趋势衰竭，见顶减仓
    底背离：价格创新低但DIF不创新低 → 反转在即，底部建仓

    要求：
    - 对比窗口：最近60个交易日的极值区间
    - 价格容忍度：接近极值1%-2%即视为"同一水平"
    - DIF衰减：DIF未突破前值的90%(顶)或未跌破前值的110%(底)
    """
    result = {
        "is_top_divergence": False,
        "is_bottom_divergence": False,
    }

    if len(klines) < 60 or len(dif_list) < 30:
        return result

    closes = [k.close for k in klines]
    today_close = closes[-1]

    # ====== 顶背离检测 ======
    # 找最近60天内的最高收盘价窗口（排除最后5天，避免与当前比较）
    window_start = max(0, len(closes) - 60)
    window_end = max(0, len(closes) - 10)
    if window_end <= window_start:
        window_end = len(closes) - 5

    if window_end > window_start:
        max_close = max(closes[window_start:window_end])

        # 对应窗口的DIF最大值
        dif_window_start = max(0, window_start)
        dif_window_end = min(len(dif_list), window_end)
        if dif_window_end > dif_window_start:
            max_dif = max(dif_list[dif_window_start:dif_window_end])

            # 当前价格接近或达到最高，但DIF明显低于前高
            price_near_high = today_close >= max_close * 0.98
            dif_weaker = dif_list[-1] < max_dif * 0.9

            if price_near_high and dif_weaker and max_dif > 0:
                result["is_top_divergence"] = True

    # ====== 底背离检测 ======
    if window_end > window_start:
        min_close = min(closes[window_start:window_end])

        dif_window_start = max(0, window_start)
        dif_window_end = min(len(dif_list), window_end)
        if dif_window_end > dif_window_start:
            min_dif = min(dif_list[dif_window_start:dif_window_end])

            # 当前价格接近或达到最低，但DIF明显高于前低
            price_near_low = today_close <= min_close * 1.02
            dif_stronger = dif_list[-1] > min_dif * 1.1

            if price_near_low and dif_stronger and min_dif < 0:
                result["is_bottom_divergence"] = True

    return result


def detect_macd_signals(
    klines: list[DailyData], dif_list: list[float], dea_list: list[float], macd_list: list[float]
) -> dict[str, Any]:
    """
    根据 Z哥 语料检测 MACD 信号

    三大用法:
    1. DIF 上下穿 0 轴 — 判多空区间
    2. 顶/底背离 — 判趋势终结
    3. 金叉空 + 死叉多 — 判陷阱
    """
    signals = {
        "is_dif_positive": False,
        "is_dif_cross_zero": False,
        "is_dif_cross_zero_down": False,
        "is_gold_cross": False,
        "is_dead_cross": False,
        "is_gold_fake": False,
        "is_dead_fake": False,
        "is_top_divergence": False,
        "is_bottom_divergence": False,
        "macd_veto": False,
    }

    if len(dif_list) < 2 or len(dea_list) < 1:
        return signals

    dif_today = dif_list[-1]
    dif_yesterday = dif_list[-2] if len(dif_list) >= 2 else 0
    dea_today = dea_list[-1]
    dea_yesterday = dea_list[-2] if len(dea_list) >= 2 else 0

    # === 用法 1: DIF 0 轴判多空 ===
    signals["is_dif_positive"] = dif_today > 0

    # DIF 上穿 0 轴
    signals["is_dif_cross_zero"] = dif_yesterday <= 0 and dif_today > 0
    # DIF 下穿 0 轴
    signals["is_dif_cross_zero_down"] = dif_yesterday >= 0 and dif_today < 0

    # === 金叉/死叉 ===
    if len(dif_list) >= 3 and len(dea_list) >= 2:
        signals["is_gold_cross"] = dif_yesterday <= dea_yesterday and dif_today > dea_today
        signals["is_dead_cross"] = dif_yesterday >= dea_yesterday and dif_today < dea_today

    # === 用法 3: 金叉空 + 死叉多（多等一天）===
    if len(dif_list) >= 5 and len(dea_list) >= 3:
        # 检查最近 3 天的金叉/死叉变化
        recent_gold = 0
        recent_dead = 0
        for i in range(max(0, len(dif_list) - 4), len(dif_list) - 1):
            di = i
            dei = i - (len(dif_list) - len(dea_list))
            if dei >= 0 and dei < len(dea_list) and dei + 1 < len(dea_list):
                if dif_list[di] > dea_list[dei] and dif_list[di - 1] <= dea_list[dei - 1 if dei > 0 else 0]:
                    recent_gold += 1
                if dif_list[di] < dea_list[dei] and dif_list[di - 1] >= dea_list[dei - 1 if dei > 0 else 0]:
                    recent_dead += 1

        # 金叉空：刚金叉又马上死叉
        if signals["is_dead_cross"] and recent_gold >= 1:
            signals["is_gold_fake"] = True

        # 死叉多：刚死叉又马上金叉
        if signals["is_gold_cross"] and recent_dead >= 1:
            signals["is_dead_fake"] = True

    # === 用法 2: 顶底背离（系统化检测）===
    div = detect_divergence(klines, dif_list)
    signals["is_top_divergence"] = div["is_top_divergence"]
    signals["is_bottom_divergence"] = div["is_bottom_divergence"]

    # === 一票否决权 ===
    # DIF < 0 + 没有底背离 → 一票否决
    if dif_today < 0 and not signals["is_bottom_divergence"]:
        signals["macd_veto"] = True

    return signals


def detect_double_gun(klines: list[DailyData]) -> dict:
    """
    双枪战法检测

    图形特征：两根放量阳柱中间夹一堆缩量阴线
    本质：主力建仓确认 — 第一根试盘，中间洗盘，第二根确认

    规则：
    - 往前找最近一根放量阳线（第二枪），排除今天
    - 再往前找另一根放量阳线（第一枪）
    - 中间夹缩量小阴小阳（3-10天）
    - 第二枪前一日应有B1痕迹（J<13）
    """
    result: dict[str, Any] = {
        "is_double_gun": False,
        "double_gun_vol1": 0.0,
        "double_gun_vol2": 0.0,
        "double_gun_gap_days": 0,
    }
    if len(klines) < 15:
        return result

    n = len(klines)

    # 往前找最近一根放量阳线（第二枪），排除今天
    gun2_idx = None
    for i in range(n - 2, max(0, n - 15), -1):
        if i > 0:
            prev_i = klines[i - 1]
            vol_ratio = klines[i].vol / prev_i.vol if prev_i.vol > 0 else 0
            if klines[i].pct_chg >= 3 and klines[i].close > klines[i].open and vol_ratio >= 1.8:
                gun2_idx = i
                break

    if gun2_idx is None or gun2_idx < 5:
        return result

    # 检查第二枪前一日是否有B1痕迹
    _, _, j_before_gun2 = calculate_kdj(klines[:gun2_idx])
    has_b1_before = j_before_gun2 < 20

    # 从第二枪往前找第一枪
    gun1_idx = None
    for i in range(gun2_idx - 3, max(0, gun2_idx - 12), -1):
        if i > 0:
            prev_i = klines[i - 1]
            vol_ratio = klines[i].vol / prev_i.vol if prev_i.vol > 0 else 0
            if klines[i].pct_chg >= 3 and klines[i].close > klines[i].open and vol_ratio >= 1.8:
                gun1_idx = i
                break

    if gun1_idx is None:
        return result

    gap_days = gun2_idx - gun1_idx

    # 检查中间是否缩量
    mid_vols = []
    for i in range(gun1_idx + 1, gun2_idx):
        if i > 0:
            prev_i = klines[i - 1]
            if prev_i.vol > 0:
                mid_vols.append(klines[i].vol / prev_i.vol)

    if not mid_vols:
        return result

    avg_mid_vol = sum(mid_vols) / len(mid_vols)
    is_shrink_mid = avg_mid_vol < 1.2  # 中间平均量比 < 1.2

    # 计算两枪的量比
    g1_prev = klines[gun1_idx - 1] if gun1_idx > 0 else None
    g2_prev = klines[gun2_idx - 1] if gun2_idx > 0 else None
    vol1: float = klines[gun1_idx].vol / g1_prev.vol if g1_prev and g1_prev.vol > 0 else 0.0
    vol2: float = klines[gun2_idx].vol / g2_prev.vol if g2_prev and g2_prev.vol > 0 else 0.0

    if is_shrink_mid and has_b1_before and 3 <= gap_days <= 10:
        result["is_double_gun"] = True
        result["double_gun_vol1"] = round(vol1, 1)
        result["double_gun_vol2"] = round(vol2, 1)
        result["double_gun_gap_days"] = gap_days

    return result


def detect_sb1_detailed(klines: list[DailyData]) -> dict:
    """
    超级B1独立检测

    形态流程：
    N型上涨 → 缩量回调 → 标准B1触发 → 突然放量大阴线击穿止损位 →
    缩量企稳 + J值大负值 → 反转K线确认 → 入场

    只赌一次，不可重复博弈
    """
    result = {
        "is_sb1_detailed": False,
    }
    if len(klines) < 15:
        return result

    n = len(klines)
    today = klines[-1]
    _, _, j_today = calculate_kdj(klines)

    # 往前找放量大阴线（击穿止损位）
    big_drop_idx = None
    for i in range(n - 2, max(0, n - 10), -1):
        if i > 0:
            prev_i = klines[i - 1]
            vol_ratio = klines[i].vol / prev_i.vol if prev_i.vol > 0 else 0
            # 放量大阴线：跌幅>3%, 量比>1.5, 收阴
            if klines[i].pct_chg <= -3 and vol_ratio >= 1.5 and klines[i].close < klines[i].open:
                big_drop_idx = i
                break

    if big_drop_idx is None:
        return result

    # 大阴线后缩量企稳（1-3天）
    days_after_drop = n - 1 - big_drop_idx
    if days_after_drop < 1 or days_after_drop > 3:
        return result

    # 检查大阴线后是否缩量
    drop_vol = klines[big_drop_idx].vol
    for i in range(big_drop_idx + 1, n):
        if klines[i].vol > drop_vol * 0.7:
            return result  # 没有缩量

    # J值大负值
    if j_today > -5:
        return result

    # 反转K线确认（十字星或小阳）
    body = abs(today.close - today.open)
    prev_close = klines[-2].close if len(klines) > 1 else today.close
    body_pct = body / prev_close * 100 if prev_close > 0 else 0
    is_reversal = body_pct <= 2 or (today.pct_chg > 0 and today.close > today.open)

    if not is_reversal:
        return result

    # 检查大阴线前是否有N型上涨结构
    if big_drop_idx >= 5:
        pre_lows = [klines[i].low for i in range(max(0, big_drop_idx - 10), big_drop_idx)]
        if len(pre_lows) >= 3:
            # 简单判断：大阴线前的低点在抬高
            first_half = pre_lows[: len(pre_lows) // 2]
            second_half = pre_lows[len(pre_lows) // 2 :]
            if min(second_half) >= min(first_half):
                result["is_sb1_detailed"] = True

    return result


def detect_nana_chart(klines: list[DailyData]) -> dict:
    """
    娜娜图检测：完美建仓形态
    条件：股价新高但阳线缩量，次高点阴线也缩量
    """
    result = {"is_nana": False}
    if len(klines) < 20:
        return result
    n = len(klines)
    # 找最近高点区域
    highs = [k.high for k in klines]
    peak_idx = n - 1
    for i in range(n - 2, max(0, n - 30), -1):
        if highs[i] >= highs[peak_idx]:
            peak_idx = i
    # 从峰值往前找第二高
    second_peak = None
    for i in range(peak_idx - 2, max(0, peak_idx - 25), -1):
        if klines[i].high < klines[peak_idx].high * 0.98:
            second_peak = i
            break
    if second_peak is None or peak_idx < 5:
        return result
    # 检查峰值区域是否缩量
    peak_vol = klines[peak_idx].vol
    prev5_avg = sum(k.vol for k in klines[max(0, peak_idx - 5) : peak_idx]) / min(5, peak_idx)
    vol_shrink_at_peak = peak_vol < prev5_avg * 0.8 if prev5_avg > 0 else False
    # 次高点缩量
    second_vol = klines[second_peak].vol
    sec_prev5 = sum(k.vol for k in klines[max(0, second_peak - 5) : second_peak]) / min(5, second_peak)
    vol_shrink_second = second_vol < sec_prev5 * 0.8 if sec_prev5 > 0 else False
    # 底部堆量：找低点区域量是否明显大于峰值区域
    low_idx = min(range(max(0, second_peak - 10), second_peak), key=lambda i: klines[i].low)
    bottom_vol = klines[low_idx].vol
    if vol_shrink_at_peak and vol_shrink_second and bottom_vol > peak_vol * 0.5:
        result["is_nana"] = True
    return result


def detect_golden_bowl(klines: list[DailyData]) -> dict:
    """
    黄金碗检测：价格在白线( zg_white )和黄线( dg_yellow )之间
    条件：白线>黄线(多头排列) + 价格落入碗内
    """
    result: dict[str, Any] = {"is_in_bowl": False, "bowl_upper": 0.0, "bowl_lower": 0.0}
    if len(klines) < 120:
        return result
    white = calculate_zg_white(klines)
    yellow = calculate_dg_yellow(klines)
    if white <= 0 or yellow <= 0:
        return result
    result["bowl_upper"] = round(white, 2)
    result["bowl_lower"] = round(yellow, 2)
    today_close = klines[-1].close
    # 白线>黄线且价格在碗内
    if white > yellow and yellow <= today_close <= white:
        result["is_in_bowl"] = True
    return result


def detect_breathing_structure(klines: list[DailyData]) -> dict:
    """
    呼吸结构检测：放量涨->缩量跌->放量涨 的N型节奏
    """
    result = {"breath_phase": "", "breath_n_type": False}
    if len(klines) < 10:
        return result
    n = len(klines)
    # 分析最近5-7天的量价节奏
    phases = []
    for i in range(max(0, n - 7), n):
        day = klines[i]
        prev = klines[i - 1] if i > 0 else None
        if not prev or prev.vol <= 0:
            continue
        vol_ratio = day.vol / prev.vol
        if day.pct_chg > 0 and vol_ratio > 1:
            phases.append("exhale")  # 放量涨=呼气
        elif day.pct_chg < 0 and vol_ratio < 1:
            phases.append("inhale")  # 缩量跌=吸气
        else:
            phases.append("other")
    # 判断当前阶段
    if len(phases) >= 2:
        if phases[-1] == "exhale":
            result["breath_phase"] = "exhale"
        elif phases[-1] == "inhale":
            result["breath_phase"] = "inhale"
        else:
            result["breath_phase"] = "none"
    # N型结构：最近3个低点依次抬高
    if n >= 10:
        lows = [klines[i].low for i in range(n - 10, n, 3)]
        if len(lows) >= 3 and lows[-1] > lows[-2] > lows[-3]:
            result["breath_n_type"] = True
    return result


def detect_sb1(klines: list[DailyData]) -> dict:
    """
    SB1假摔检测：B1后跌破前低再迅速收回
    条件：1)跌破前低 2)次日反包收回 3)收回放量
    """
    result = {"is_sb1": False}
    if len(klines) < 6:
        return result
    n = len(klines)
    yesterday = klines[-2]
    # 前天是假摔日
    if len(klines) >= 3:
        fake_drop = klines[-3]
        prev_low = min(k.low for k in klines[-8:-3]) if n >= 8 else klines[-4].low
        # 1) 跌破前低
        broken_low = fake_drop.low < prev_low
        # 2) 次日反包收回
        recovered = yesterday.close > prev_low and yesterday.pct_chg > 2
        # 3) 反包放量
        vol_up = yesterday.vol > fake_drop.vol * 1.2
        if broken_low and recovered and vol_up:
            result["is_sb1"] = True
    return result


def detect_b3(klines: list[DailyData]) -> dict:
    """
    B3买点检测：B2后缩量回踩不破B2低点
    条件：1) 前面有B2(大涨>=4%) 2) 缩量小阳/十字星 3) 不破B2低点
    """
    result = {"is_b3": False}
    if len(klines) < 15:
        return result
    n = len(klines)
    today = klines[-1]
    # 往前找B2(大涨>=4%的阳线)
    b2_idx = None
    for i in range(n - 2, max(0, n - 15), -1):
        if klines[i].pct_chg >= 4 and klines[i].close > klines[i].open:
            b2_idx = i
            break
    if b2_idx is None:
        return result
    b2_low = klines[b2_idx].low
    # B2后缩量小阳线
    days_after = n - 1 - b2_idx
    if 2 <= days_after <= 5:
        today_vol_ratio = today.vol / klines[b2_idx].vol if klines[b2_idx].vol > 0 else 0
        not_break_low = today.low >= b2_low * 0.98
        small_candle = abs(today.pct_chg) < 3
        if today_vol_ratio < 0.8 and not_break_low and small_candle:
            result["is_b3"] = True
    return result


def detect_zaihou_chongjian(klines: list[DailyData]) -> dict:
    """
    灾后重建检测 —— 放量金叉后缩量回踩黄线

    来源：advanced-patterns.md
    定义：放量金叉后缩量回踩黄线，交易价值最大，是最后拉升前的震仓动作。

    条件：
    1. 前期有放量上涨（涨幅 > 5%，量 > 前5日均量 × 1.5）
    2. 近期缩量回调（量 < 放量日量的 60%）
    3. 价格回踩黄线（大哥线 = (MA14+MA28+MA57+MA114)/4）附近（±2%）
    4. 黄线趋势向上

    Args:
        klines: K线数据（至少60根）

    Returns:
        {'is_rebuild': bool, 'confidence': float, 'desc': str}
    """
    if len(klines) < 114:
        return {"is_rebuild": False}

    today = klines[-1]

    # 计算黄线（大哥线 = (MA14+MA28+MA57+MA114)/4，与 calculate_dg_yellow 一致）
    closes = [k.close for k in klines]
    ma14 = calculate_ma(closes, 14)
    ma28 = calculate_ma(closes, 28)
    ma57 = calculate_ma(closes, 57)
    ma114 = calculate_ma(closes, 114)
    yellow_line = (ma14 + ma28 + ma57 + ma114) / 4

    # 黄线趋势：近5天黄线 vs 近10天黄线（大哥线公式）
    yellow_5 = (
        calculate_ma(closes[-5:], 14)
        + calculate_ma(closes[-5:], 28)
        + calculate_ma(closes[-5:], 57)
        + calculate_ma(closes[-5:], 114)
    ) / 4
    yellow_10 = (
        calculate_ma(closes[-10:], 14)
        + calculate_ma(closes[-10:], 28)
        + calculate_ma(closes[-10:], 57)
        + calculate_ma(closes[-10:], 114)
    ) / 4
    yellow_up = yellow_5 > yellow_10

    # 查找近期放量上涨日（近15天内）
    recent_15 = klines[-15:]
    fangliang_day = None
    for i, k in enumerate(recent_15):
        if i == 0:
            continue
        prev_5_avg = sum(kl.vol for kl in recent_15[max(0, i - 5) : i]) / 5
        if k.pct_chg > 5 and k.vol > prev_5_avg * 1.5:
            fangliang_day = k
            break

    if fangliang_day is None:
        return {"is_rebuild": False}

    # 缩量条件：今天量 < 放量日量的 60%
    is_suoliang = today.vol < fangliang_day.vol * 0.6

    # 回踩黄线：收盘价在黄线 ±2% 范围内
    near_yellow = abs(today.close - yellow_line) / yellow_line < 0.02 if yellow_line > 0 else False

    if is_suoliang and near_yellow and yellow_up:
        return {
            "is_rebuild": True,
            "confidence": 0.85,
            "yellow_line": round(yellow_line, 2),
            "fangliang_price": round(fangliang_day.close, 2),
            "desc": f"灾后重建：放量({fangliang_day.close:.2f})后缩量回踩黄线({yellow_line:.2f})",
        }

    return {"is_rebuild": False}


def detect_yueyueyushi(klines: list[DailyData]) -> dict:
    """
    跃跃欲试检测 —— 横盘期间放巨大量三次

    来源：advanced-patterns.md
    定义：横盘期间放巨大量，红长绿短、红肥绿瘦，出现至少三次后越往后突破概率越大。
    前提：仅限牛市、未出货的赛赛图。"横有多长竖有多高"。

    条件：
    1. 近20天振幅 < 15%（横盘）
    2. 近20天出现至少3次巨量（量 > 前10日均量 × 2）
    3. 巨量日多为阳线（红肥绿瘦）
    4. 当前未处于明显高位（距20日高点 < 10% 可接受）

    Args:
        klines: K线数据（至少30根）

    Returns:
        {'is_ready': bool, 'count': int, 'confidence': float, 'desc': str}
    """
    if len(klines) < 30:
        return {"is_ready": False}

    recent_20 = klines[-20:]
    high_20 = max(k.high for k in recent_20)
    low_20 = min(k.low for k in recent_20)
    amplitude = (high_20 - low_20) / low_20 if low_20 > 0 else 0

    # 横盘条件
    if amplitude > 0.15:
        return {"is_ready": False}

    # 计算近10日均量
    vols_10 = [k.vol for k in klines[-10:]]
    avg_vol_10 = sum(vols_10) / len(vols_10)

    # 统计巨量次数（量 > 前10日均量 × 2）
    juliang_count = 0
    yang_count = 0
    for k in recent_20:
        if k.vol > avg_vol_10 * 2:
            juliang_count += 1
            if k.close > k.open:
                yang_count += 1

    # 至少3次巨量，且阳线占比 > 50%
    if juliang_count >= 3 and yang_count / juliang_count > 0.5:
        confidence = 0.70 + 0.05 * min(juliang_count - 3, 3)  # 每多一次+5%，上限85%
        return {
            "is_ready": True,
            "count": juliang_count,
            "yang_ratio": round(yang_count / juliang_count, 2),
            "confidence": round(confidence, 2),
            "desc": f"跃跃欲试：横盘振幅{amplitude * 100:.0f}%，{juliang_count}次巨量，阳线占比{yang_count / juliang_count * 100:.0f}%",
        }

    return {"is_ready": False}



# Pinned source: price_patterns/bull_rope.py sha256=78dd0b8b2097e888e409c9a2ddb4da5e807f760ecd4753af253a9c6d632f662e
def detect_bull_rope(klines: list[DailyData]) -> dict:
    """
    牛绳理论量化检测

    核心逻辑（源自 Z 哥语料 trend-lines.md）：
    - 白线在黄线上 = 主力牵着牛绳，任何下跌都是洗盘
    - 白线在黄线下 = 牛绳断了，任何上涨都是反弹

    状态判定：
    - 牵牛：白线 > 黄线 且 白线在上升（white[-1] > white[-3]）
    - 牛绳断：白线 < 黄线
    - 金叉：白线从下方刚上穿黄线（今日白>黄，昨日白<=黄）
    - 死叉：白线从上方刚下穿黄线（今日白<黄，昨日白>=黄）

    Args:
        klines: K线数据（至少120根）

    Returns:
        {
            'status': '牵牛' | '牛绳断' | '金叉' | '死叉',
            'white': 当前白线值,
            'yellow': 当前黄线值,
            'gap_pct': 白黄差距百分比（正=多头缺口）,
            'white_trend': '上升' | '下降' | '横盘',
            'is_bullish': bool,
            'is_bearish': bool,
        }
    """
    result: dict[str, Any] = {
        "status": "牛绳断",
        "white": 0.0,
        "yellow": 0.0,
        "gap_pct": 0.0,
        "white_trend": "横盘",
        "is_bullish": False,
        "is_bearish": True,
    }

    if len(klines) < 120:
        return result

    # 计算最近几天的白线和黄线历史值（需要至少3天来判断交叉和趋势）
    white_values: list[float] = []
    yellow_values: list[float] = []

    for i in range(114, len(klines) + 1):
        sub = klines[:i]
        w = calculate_zg_white(sub)
        y = calculate_dg_yellow(sub)
        if w > 0 and y > 0:
            white_values.append(w)
            yellow_values.append(y)

    if len(white_values) < 3:
        return result

    w_now = white_values[-1]
    w_prev = white_values[-2]
    w_prev2 = white_values[-3]
    y_now = yellow_values[-1]
    y_prev = yellow_values[-2]

    result["white"] = round(w_now, 2)
    result["yellow"] = round(y_now, 2)

    # 白黄差距百分比
    if y_now > 0:
        result["gap_pct"] = round((w_now - y_now) / y_now * 100, 2)

    # 状态判定（优先级：金叉/死叉 > 牵牛/牛绳断）
    is_golden_cross = w_now > y_now and w_prev <= y_prev
    is_death_cross = w_now < y_now and w_prev >= y_prev

    if is_golden_cross:
        result["status"] = "金叉"
    elif is_death_cross:
        result["status"] = "死叉"
    elif w_now > y_now:
        # 白线在黄线上，进一步判断是否上升
        if w_now > w_prev2:
            result["status"] = "牵牛"
        else:
            # 白线在黄线上但走弱，仍算牵牛（牛绳未断）
            result["status"] = "牵牛"
    else:
        result["status"] = "牛绳断"

    # 白线趋势：用最近5天的斜率
    if len(white_values) >= 5:
        slope = calculate_slope(white_values, 5)
        if slope > 0.01:
            result["white_trend"] = "上升"
        elif slope < -0.01:
            result["white_trend"] = "下降"
        else:
            result["white_trend"] = "横盘"
    elif w_now > w_prev2:
        result["white_trend"] = "上升"
    elif w_now < w_prev2:
        result["white_trend"] = "下降"

    # 多空判断
    result["is_bullish"] = result["status"] in ("牵牛", "金叉")
    result["is_bearish"] = result["status"] in ("牛绳断", "死叉")

    return result



# Pinned source: price_patterns/key_candles.py sha256=38a3b58212925ffd1c9827193dc357bf5a623c99a2820190a4acbf4fada3af4c
def detect_violence_k(klines: list[DailyData], lookback: int = 60) -> list[dict]:
    """
    暴力K检测（底部 + 突兀 + 倍量），扫描最近lookback天
    关键K的满配版
    """
    n = len(klines)
    if n < 10:
        return []
    start = max(0, n - lookback)
    scan = klines[start:]
    n = len(scan)
    if n < 10:
        return []

    results = []
    for i in range(max(5, n - 5), n):
        day = scan[i]
        prev = scan[i - 1] if i > 0 else None
        if not prev or prev.close <= 0:
            continue

        body = abs(day.close - day.open)
        body_pct = body / prev.close * 100

        pos_start = max(0, i - 20)
        if i > pos_start:
            recent_low = min(k.low for k in scan[pos_start:i])
            at_bottom = day.low <= recent_low * 1.05
        else:
            at_bottom = False

        body_start = max(0, i - 5)
        prev_bodies = []
        for j in range(body_start, i):
            p = scan[j - 1] if j > 0 else None
            if p and p.close > 0:
                prev_bodies.append(abs(scan[j].close - scan[j].open) / p.close * 100)
        avg_body = sum(prev_bodies) / len(prev_bodies) if prev_bodies else 0
        is_abrupt = body_pct > avg_body * 2 and body_pct >= 5

        vol_start = max(0, i - 5)
        avg_vol = sum(k.vol for k in scan[vol_start:i]) / max(1, i - vol_start)
        vol_ratio = day.vol / avg_vol if avg_vol > 0 else 0
        is_double_vol = vol_ratio >= 2

        if at_bottom and is_abrupt and is_double_vol:
            results.append(
                {
                    "date": day.trade_date,
                    "close": day.close,
                    "pct": day.pct_chg,
                    "type": "大暴力" if vol_ratio >= 3 else "小暴力",
                    "body_pct": round(body_pct, 1),
                    "vol_ratio": round(vol_ratio, 1),
                    "is_latest": (i == n - 1),
                }
            )

    return results



# Pinned source: volume_patterns.py sha256=42141485be6b9f55ca6cf016e2160271e7d20287b2f7284f907b74c119bfc2ce
def detect_chuhuo_wushi(klines: list[DailyData]) -> dict:
    """
    主力出货五种经典方式识别

    来源：sell-discipline.md 3.15
    核心判断尺：涨多了之后的放量阴线。

    返回五种出货方式的检测结果，每种有独立置信度。
    """
    if len(klines) < 20:
        return {"total_score": 0, "patterns": []}

    today = klines[-1]
    recent_20 = klines[-20:]
    recent_10 = klines[-10:]
    recent_high = max(k.high for k in recent_20)
    min(k.low for k in recent_20)

    # 必须处于相对高位（当前 >= 近期高点 × 0.85）
    if today.close < recent_high * 0.85:
        return {"total_score": 0, "patterns": []}

    patterns: list[dict[str, Any]] = []
    vols = [k.vol for k in recent_20]
    avg_vol_5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else sum(vols) / len(vols)
    max_vol_20 = max(vols)

    # ===== 方式一：加速后单日放天量大阴 =====
    # 前10天涨幅 > 20%，当天跌幅 > 5%，天量
    if len(klines) >= 10:
        price_10_days_ago = klines[-10].close
        up_pct_10 = (recent_high - price_10_days_ago) / price_10_days_ago if price_10_days_ago > 0 else 0
        is_tianliang = today.vol >= max_vol_20 * 0.8 or today.vol >= avg_vol_5 * 2
        if up_pct_10 > 0.20 and today.pct_chg < -5 and is_tianliang:
            patterns.append(
                {
                    "type": "方式一：加速后单日放天量大阴",
                    "confidence": 0.95,
                    "desc": f"10日涨{up_pct_10 * 100:.0f}%后，当天跌{abs(today.pct_chg):.1f}%，天量",
                }
            )

    # ===== 方式二：次高点巨量长阴 =====
    # 近5天创过新高，当天挑战高点失败，放量长阴
    high_5d = max(k.high for k in recent_10[:5]) if len(recent_10) >= 5 else recent_high
    is_near_high = today.high >= high_5d * 0.98
    is_big_yin = today.pct_chg < -3 and today.close < today.open
    is_juliang = today.vol >= klines[-2].vol * 1.5 if len(klines) >= 2 else False
    if is_near_high and is_big_yin and is_juliang:
        patterns.append(
            {
                "type": "方式二：次高点巨量长阴",
                "confidence": 0.90,
                "desc": f"挑战高点({high_5d:.2f})失败，放量长阴跌{abs(today.pct_chg):.1f}%",
            }
        )

    # ===== 方式三：阶梯放量下跌 =====
    # 连续3-5根阴线，成交量维持高位，价格阶梯跌
    consecutive_yin = 0
    for i in range(1, min(6, len(klines))):
        k = klines[-i]
        if k.close < k.open:  # 阴线
            consecutive_yin += 1
        else:
            break
    # 检查这N根阴线的量是否维持高位
    if consecutive_yin >= 3:
        yin_vols = [klines[-i].vol for i in range(1, consecutive_yin + 1)]
        yin_vol_avg = sum(yin_vols) / len(yin_vols)
        if yin_vol_avg >= avg_vol_5 * 1.2:
            patterns.append(
                {
                    "type": "方式三：阶梯放量下跌",
                    "confidence": 0.85,
                    "desc": f"连续{consecutive_yin}根阴线放量下跌，平均量{yin_vol_avg / avg_vol_5:.1f}倍",
                }
            )

    # ===== 方式四：双头双放量巨阴 =====
    # 近20天有两个相近高点，每个后都有放量阴线
    if len(recent_20) >= 10:
        highs = [(i, k.high) for i, k in enumerate(recent_20)]
        highs.sort(key=lambda x: x[1], reverse=True)
        top2 = highs[:2]
        if len(top2) == 2:
            h1_idx, h1 = top2[0]
            h2_idx, h2 = top2[1]
            # 两个高点差异 < 5%，且间隔至少3天
            if abs(h1 - h2) / h1 < 0.05 and abs(h1_idx - h2_idx) >= 3:
                # 检查每个高点后是否有放量阴线
                def has_fangliang_yinxian_after(idx) -> bool:
                    """检测 idx 之后 3 天内是否出现放量阴线（量 >= 5 日均量 1.3 倍）。"""
                    for j in range(idx + 1, min(idx + 4, len(recent_20))):
                        k = recent_20[j]
                        if k.close < k.open and k.vol >= avg_vol_5 * 1.3:
                            return True
                    return False

                if has_fangliang_yinxian_after(h1_idx) and has_fangliang_yinxian_after(h2_idx):
                    patterns.append(
                        {
                            "type": "方式四：双头双放量巨阴",
                            "confidence": 0.90,
                            "desc": f"双头({h1:.2f}/{h2:.2f})，均出现放量阴线",
                        }
                    )

    # ===== 方式五：顶部绿肥红瘦 =====
    # 近10天阴量 > 阳量 × 1.5
    yin_vol_total: float = 0.0
    yang_vol_total: float = 0.0
    for k in recent_10:
        if k.close < k.open:
            yin_vol_total += k.vol
        else:
            yang_vol_total += k.vol
    if yang_vol_total > 0 and yin_vol_total / yang_vol_total > 1.5:
        patterns.append(
            {
                "type": "方式五：顶部绿肥红瘦",
                "confidence": 0.80,
                "desc": f"近10天阴量/阳量={yin_vol_total / yang_vol_total:.1f}倍",
            }
        )

    # 总分 = 最高置信度 + 0.1 × (模式数 - 1)
    total_score = max([p["confidence"] for p in patterns], default=0.0)
    total_score += 0.1 * max(0, len(patterns) - 1)
    total_score = min(total_score, 1.0)

    return {"total_score": round(total_score, 2), "patterns": patterns, "is_selling": total_score >= 0.80}



# Pinned source: kirin_detector.py sha256=fce412b92117a209b32406d770d9d229c1ea8229fea70503972b1baa007f3ac2
def _calculate_ma(values: list[float], period: int) -> float:
    """简单移动平均"""
    if len(values) < period:
        return sum(values) / len(values) if values else 0.0
    return sum(values[-period:]) / period


def _calculate_red_green_ratio(klines: list[DailyData], period: int = 20) -> float:
    """
    红肥绿瘦 ratio = 阳线总成交量 / 阴线总成交量

    > 1.5：红肥绿瘦（吸筹/拉升特征）
    < 0.7：绿肥红瘦（派发特征）
    """
    segment = klines[-period:] if len(klines) >= period else klines
    if not segment:
        return 1.0

    red_vol = sum(k.vol for k in segment if k.close > k.open)
    green_vol = sum(k.vol for k in segment if k.close < k.open)

    if green_vol <= 0:
        return 3.0  # 全是阳线
    return red_vol / green_vol


def _detect_n_shape_raise(klines: list[DailyData]) -> tuple[bool, int]:
    """
    N 型逐步抬高检测

    检测最近是否有连续 3 个低点逐步抬高（允许轻微回撤）
    返回：(是否N型抬高, N型确认点索引)
    """
    if len(klines) < 20:
        return False, -1

    # 找最近 3 个局部低点
    lows = []
    for i in range(5, len(klines) - 5):
        if klines[i].low < klines[i - 1].low and klines[i].low < klines[i + 1].low:
            lows.append((i, klines[i].low))

    if len(lows) < 3:
        return False, -1

    # 取最近 3 个局部低点，检查是否逐步抬高
    recent_lows = lows[-3:]
    if recent_lows[0][1] < recent_lows[1][1] * 1.02 and recent_lows[1][1] < recent_lows[2][1] * 1.02:
        return True, recent_lows[0][0]

    return False, -1


def _detect_healthy_breathing(klines: list[DailyData]) -> bool:
    """
    呼吸节奏健康检测：放量涨 → 缩量调

    最近 10 日中，上涨日平均成交量 > 下跌日平均成交量 * 1.2
    """
    if len(klines) < 10:
        return False

    segment = klines[-10:]
    up_vols = [k.vol for k in segment if k.close > k.open]
    down_vols = [k.vol for k in segment if k.close < k.open]

    if not up_vols or not down_vols:
        return False

    avg_up = sum(up_vols) / len(up_vols)
    avg_down = sum(down_vols) / len(down_vols)

    return avg_up > avg_down * 1.2


def _calculate_position_ratio(klines: list[DailyData]) -> dict:
    """
    计算当前价格在 120 日区间中的位置

    返回：{'low': float, 'high': float, 'current': float,
           'from_low_pct': float, 'from_high_pct': float}
    """
    if len(klines) < 60:
        return {"from_low_pct": 50, "from_high_pct": 50}

    period = min(120, len(klines))
    segment = klines[-period:]
    low_price = min(k.low for k in segment)
    high_price = max(k.high for k in segment)
    current = klines[-1].close

    from_low = ((current - low_price) / (high_price - low_price) * 100) if high_price > low_price else 50
    from_high = ((high_price - current) / (high_price - low_price) * 100) if high_price > low_price else 50

    return {
        "low": low_price,
        "high": high_price,
        "current": current,
        "from_low_pct": from_low,
        "from_high_pct": from_high,
    }


def _is_white_above_yellow(klines: list[DailyData]) -> bool:
    """白线是否在黄线之上"""
    try:
        white = calculate_zg_white(klines)
        yellow = calculate_dg_yellow(klines)
        return white > yellow
    except (KeyError, ValueError, AttributeError, TypeError, ArithmeticError) as e:
        # 计算失败 → 当作"白线不在黄线之上"；调用方已经接受 False 兜底。
        logger.warning("[kirin_detector] 白黄线对比计算失败: %s", e)
        return False


def _calculate_pull_speed(klines: list[DailyData]) -> float:
    """计算拉升速度：最近 20 日涨幅"""
    if len(klines) < 20:
        return 0.0
    return (klines[-1].close / klines[-20].close - 1) * 100


def _detect_volume_price_rise(klines: list[DailyData]) -> bool:
    """量价齐升：最近 10 日，收盘价和成交量都呈上升趋势"""
    if len(klines) < 10:
        return False

    segment = klines[-10:]
    # 简单判断：最近 5 日平均收盘价 > 前 5 日平均收盘价
    # 且最近 5 日平均成交量 > 前 5 日平均成交量
    recent_5_close = sum(k.close for k in segment[-5:]) / 5
    prev_5_close = sum(k.close for k in segment[:5]) / 5
    recent_5_vol = sum(k.vol for k in segment[-5:]) / 5
    prev_5_vol = sum(k.vol for k in segment[:5]) / 5

    return recent_5_close > prev_5_close and recent_5_vol > prev_5_vol


def _count_limit_up(klines: list[DailyData], days: int = 20) -> int:
    """最近 days 日涨停次数"""
    segment = klines[-days:] if len(klines) >= days else klines
    return sum(1 for k in segment if k.pct_chg >= 9.9)


def detect_kirin_stage(klines: list[DailyData]) -> dict:
    """
    识别麒麟会（庄家）当前所处阶段

    四阶段：吸筹 → 拉升 → 派发 → 回落
    子类型：铁蝴蝶（传统庄）/ 学院派铁蝴蝶（机构）

    采用评分制，每个阶段 0-100 分，取最高分。

    返回：
    {
        'stage': '吸筹' | '拉升' | '派发' | '回落' | '未知',
        'confidence': float,  # 0-1
        'sub_type': '铁蝴蝶' | '学院派铁蝴蝶' | '未知',
        'scores': {
            'xishou': float,
            'lasheng': float,
            'paifa': float,
            'luoluo': float,
        },
        'indicators': {
            'price_position': str,  # 低位/中位/高位
            'vol_pattern': str,     # 放量/缩量/正常
            'red_green_ratio': float,
            'n_shape': bool,
            'healthy_breathing': bool,
            'white_above_yellow': bool,
            'pull_speed': float,
            'limit_up_count': int,
        },
        'operation': str,  # 关注等B1 / 不追等回调 / 准备走人 / 不抄底 / 观望
    }
    """
    result = {
        "stage": "未知",
        "confidence": 0.0,
        "sub_type": "未知",
        "scores": {},
        "indicators": {},
        "operation": "观望",
    }

    if len(klines) < 60:
        return result

    # ========== 计算辅助指标 ==========
    position = _calculate_position_ratio(klines)
    red_green = _calculate_red_green_ratio(klines, period=20)
    n_shape, n_idx = _detect_n_shape_raise(klines)
    breathing = _detect_healthy_breathing(klines)
    white_above = _is_white_above_yellow(klines)
    pull_speed = _calculate_pull_speed(klines)
    vol_price_rise = _detect_volume_price_rise(klines)
    limit_up_count = _count_limit_up(klines, days=20)
    has_limit_up = limit_up_count > 0

    # 60 日均量
    # _calculate_ma uses only the last 60 observations for this period.
    avg_vol_60 = _calculate_ma([k.vol for k in klines[-60:]], 60)
    recent_avg_vol = _calculate_ma([k.vol for k in klines[-10:]], 10)
    is_high_vol = recent_avg_vol > avg_vol_60 * 1.3 if avg_vol_60 > 0 else False
    is_low_vol = recent_avg_vol < avg_vol_60 * 0.8 if avg_vol_60 > 0 else False

    # 价格位置描述
    from_low_pct = position["from_low_pct"]
    from_high_pct = position["from_high_pct"]
    if from_low_pct < 30:
        price_pos = "低位"
    elif from_low_pct > 70:
        price_pos = "高位"
    else:
        price_pos = "中位"

    # 成交量描述
    if is_high_vol:
        vol_pattern = "放量"
    elif is_low_vol:
        vol_pattern = "缩量"
    else:
        vol_pattern = "正常"

    indicators = {
        "price_position": price_pos,
        "vol_pattern": vol_pattern,
        "red_green_ratio": round(red_green, 2),
        "n_shape": n_shape,
        "healthy_breathing": breathing,
        "white_above_yellow": white_above,
        "pull_speed": round(pull_speed, 2),
        "limit_up_count": limit_up_count,
        "from_low_pct": round(from_low_pct, 1),
        "from_high_pct": round(from_high_pct, 1),
    }
    result["indicators"] = indicators

    # ========== 吸筹阶段评分 ==========
    xishou_score = 0
    # 低位：从低点涨 < 30%
    if from_low_pct < 30:
        xishou_score += 30
    elif from_low_pct < 50:
        xishou_score += 15
    # 放量
    if is_high_vol:
        xishou_score += 20
    # N 型抬高
    if n_shape:
        xishou_score += 20
    # 红肥绿瘦
    if red_green > 1.3:
        xishou_score += 20
    elif red_green > 1.0:
        xishou_score += 10
    # 无涨停（吸筹期一般不拉涨停）
    if not has_limit_up:
        xishou_score += 10

    # ========== 拉升阶段评分 ==========
    lasheng_score = 0
    # 已从低位涨起来
    if from_low_pct > 30:
        lasheng_score += 20
    elif from_low_pct > 20:
        lasheng_score += 10
    # 涨速快
    if pull_speed > 30:
        lasheng_score += 25
    elif pull_speed > 20:
        lasheng_score += 15
    # 有涨停
    if limit_up_count >= 2:
        lasheng_score += 20
    elif has_limit_up:
        lasheng_score += 10
    # 量价齐升
    if vol_price_rise:
        lasheng_score += 15
    # 白线在黄线之上
    if white_above:
        lasheng_score += 10
    # 呼吸节奏健康
    if breathing:
        lasheng_score += 10

    # ========== 派发阶段评分 ==========
    paifa_score = 0
    # 高位
    if from_high_pct < 15:
        paifa_score += 30
    elif from_high_pct < 30:
        paifa_score += 15
    # 高位放量
    if is_high_vol and from_low_pct > 60:
        paifa_score += 20
    # 绿肥红瘦
    if red_green < 0.7:
        paifa_score += 20
    elif red_green < 1.0:
        paifa_score += 10
    # 出货信号
    try:
        chuhuo = detect_chuhuo_wushi(klines)
        if chuhuo.get("total_score", 0) >= 2:
            paifa_score += 30
    except (KeyError, ValueError, AttributeError, TypeError, ArithmeticError) as e:
        # 五式出货检测失败不影响主派发评分。
        logger.warning("[kirin_detector] 五式出货检测失败，跳过加分: %s", e)
        pass

    # ========== 回落阶段评分 ==========
    luoluo_score = 0
    # 从高点跌下来
    if from_high_pct > 20:
        luoluo_score += 30
    elif from_high_pct > 10:
        luoluo_score += 15
    # 缩量
    if is_low_vol:
        luoluo_score += 25
    # 无承接（阳线少）
    recent_red = sum(1 for k in klines[-10:] if k.close > k.open)
    if recent_red < 3:
        luoluo_score += 20
    # 白线跌破黄线
    if not white_above:
        luoluo_score += 15
    # 无涨停
    if not has_limit_up:
        luoluo_score += 10

    scores = {
        "xishou": xishou_score,
        "lasheng": lasheng_score,
        "paifa": paifa_score,
        "luoluo": luoluo_score,
    }
    result["scores"] = scores

    # ========== 确定阶段 ==========
    max_score = max(scores.values())
    if max_score < 30:
        result["stage"] = "未知"
        result["confidence"] = round(max_score / 100, 2)
        result["operation"] = "观望"
        return result

    stage_map = {
        "xishou": ("吸筹", "关注，等B1"),
        "lasheng": ("拉升", "不追，等回调B1"),
        "paifa": ("派发", "准备走人"),
        "luoluo": ("回落", "不抄底"),
    }

    max_stage = max(scores, key=lambda k: scores[k])
    result["stage"] = stage_map[max_stage][0]
    result["confidence"] = round(min(max_score / 100, 1.0), 2)
    result["operation"] = stage_map[max_stage][1]

    # ========== 子类型判断 ==========
    # 铁蝴蝶 vs 学院派铁蝴蝶
    if result["stage"] == "拉升":
        # 拉升快、洗盘狠 = 铁蝴蝶
        # 拉升慢而稳 = 学院派
        if pull_speed > 40:
            result["sub_type"] = "铁蝴蝶"
        elif pull_speed < 25 and breathing:
            result["sub_type"] = "学院派铁蝴蝶"
        else:
            result["sub_type"] = "铁蝴蝶"
    elif result["stage"] == "派发":
        # A 杀快 = 铁蝴蝶，多重顶 = 学院派
        # 简化：看下跌速度
        recent_drop = (klines[-1].close / klines[-5].close - 1) * 100 if len(klines) >= 5 else 0
        if recent_drop < -15:
            result["sub_type"] = "铁蝴蝶"
        else:
            result["sub_type"] = "学院派铁蝴蝶"

    return result



# Optimized, prefix-local equivalents of the pinned source helpers.
# The original functions above remain available to audit; none is imported from
# a personal skill directory at runtime. Prefix state is per symbol and has no
# shared mutable globals, so the existing thread/process backends stay safe.
_source_kdj = calculate_kdj
_source_detect_n_shape_raise = _detect_n_shape_raise


class _Prefix:
    def __init__(self, bars, cache, start=0, stop=None):
        self.bars, self.cache = bars, cache
        self.start = start
        self.stop = len(bars) if stop is None else stop

    def __len__(self):
        return self.stop - self.start

    def __iter__(self):
        return iter(self.bars[self.start:self.stop])

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if step == 1:
                return _Prefix(self.bars, self.cache, self.start + start, self.start + stop)
            return list(self)[key]
        i = key if key >= 0 else len(self) + key
        if not 0 <= i < len(self):
            raise IndexError(key)
        return self.bars[self.start + i]


def calculate_kdj(klines, period=9, k_ma=3, d_ma=3):
    if isinstance(klines, _Prefix) and klines.start == 0 and (period, k_ma, d_ma) == (9, 3, 3):
        if not klines:
            return (50, 50, 50)
        return klines.cache['kdj'][klines.stop - 1]
    return _source_kdj(klines, period, k_ma, d_ma)


def calculate_zg_white(klines):
    if isinstance(klines, _Prefix) and klines.start == 0:
        return klines.cache['white'][klines.stop - 1] if len(klines) >= 10 else 0
    if len(klines) < 10:
        return 0
    closes = [k.close for k in klines]
    ema1 = calculate_ema_series(closes, 10)
    ema2 = calculate_ema_series(ema1, 10)
    return round(ema2[-1], 2) if ema2 else 0


def calculate_dg_yellow(klines):
    if isinstance(klines, _Prefix) and klines.start == 0:
        return klines.cache['yellow'][klines.stop - 1] if len(klines) >= 114 else 0
    if len(klines) < 114:
        return 0
    closes = [k.close for k in klines]
    return round(sum(calculate_ma(closes, n) for n in (14, 28, 57, 114)) / 4, 2)


def _detect_n_shape_raise(klines):
    if isinstance(klines, _Prefix) and klines.start == 0:
        return klines.cache['n_shape'][klines.stop - 1] if klines else (False, -1)
    return _source_detect_n_shape_raise(klines)


def _brick_series(bars):
    """Accepted fanbao kernel: full prefix, Python round and original SMA seed."""
    values = []
    s3 = s5 = s1 = None
    w6, w4 = 1 / 6, 1 / 4
    for i, k in enumerate(bars):
        if i < 3:
            values.append(0)
            continue
        window = bars[i - 3:i + 1]
        high, low = max(x.high for x in window), min(x.low for x in window)
        if high == low:
            v3, v1 = 50.0, -90.0
        else:
            v3 = (k.close - low) / (high - low) * 100
            v1 = (high - k.close) / (high - low) * 100 - 90.0
        if i == 3:
            s3, s5, s1 = v3, v3, v1
        else:
            s3 = v3 * w6 + s3 * (1 - w6)
            s5 = s3 * w6 + s5 * (1 - w6)
            s1 = v1 * w4 + s1 * (1 - w4)
        value = (s5 + 100) - (s1 + 100)
        values.append(round(value - 4 if value > 4 else 0, 2) if i + 1 >= 12 else 0)
    return values


def _strict_fanbao(before, yesterday, today):
    def cents(v):
        scaled = Decimal(str(v)) * 100
        if not math.isfinite(v) or scaled != scaled.to_integral_value():
            raise ValueError('INVALID_BRICK_CENTS')
        return int(scaled)
    b, y, t = map(cents, (before, yesterday, today))
    return y < b and t > y and 3 * (t - y) > 2 * (b - y)


def _kdj_cache(bars):
    """Pinned KDJ recursion over the supplied rows, independent of volume."""
    output = []
    k = d = 50.0
    for i, day in enumerate(bars):
        if i >= 8:
            low = min(x.low for x in bars[i - 8:i + 1])
            high = max(x.high for x in bars[i - 8:i + 1])
            rsv = 50.0 if high == low else (day.close - low) / (high - low) * 100
            k = (2 / 3) * k + (1 / 3) * rsv
            d = (2 / 3) * d + (1 / 3) * k
        output.append((round(k, 2), round(d, 2), round(3 * k - 2 * d, 2)))
    return output


def project_bound_kb_j(symbol, rows):
    """Project only the KB J component from the exact, ordered HLC prefix."""
    if not isinstance(symbol, str) or len(symbol) != 9 or not symbol[:6].isdigit() or symbol[6:] not in {'.SH','.SZ','.BJ'}:
        raise ValueError('KB_ONE_A_SHARE_REQUIRED')
    bars, valid = [], []
    previous = 0
    for row in rows:
        if row.get('ts_code', symbol) != symbol:
            raise ValueError('KB_ONE_SYMBOL_REQUIRED')
        day = int(row['trade_date'])
        if day <= previous:
            raise ValueError('KB_TRADE_DATES_NOT_UNIQUE_SORTED')
        previous = day
        values = [row.get(key) for key in ('high','low','close')]
        finite = [_finite(value) and not isinstance(value, bool) for value in values]
        high, low, close = [float(value) if ok else 0.0 for value, ok in zip(values, finite)]
        good = all(finite) and low <= close <= high
        bars.append(DailyData(symbol, str(day), 0.0, high, low, close, 0.0, 0.0, 0.0, 0.0))
        valid.append(good)
    cache = _kdj_cache(bars)
    prefix_valid = True
    output = []
    for i, row in enumerate(rows):
        prefix_valid = prefix_valid and valid[i]
        output.append({'trade_date':int(row['trade_date']),
                       'kb_b1_j':cache[i][2] if i >= 8 and prefix_valid else None})
    return output


def _cache(bars):
    closes = [x.close for x in bars]
    white, yellow, ming, shapes = [], [], [], []
    kdj = _kdj_cache(bars)
    ema1 = ema2 = closes[0] if closes else 0.0
    lows = []
    alpha = 2 / 11
    for i, day in enumerate(bars):
        if i:
            ema1 = day.close * alpha + ema1 * (1 - alpha)
            ema2 = ema1 * alpha + ema2 * (1 - alpha)
        white.append(round(ema2, 2) if i >= 9 else 0)
        if i >= 113:
            m = sum(sum(closes[i - period + 1:i + 1]) / period for period in (14, 28, 57, 114)) / 4
            ming.append(m)
            yellow.append(round(m, 2))
        else:
            ming.append(None)
            yellow.append(0)
        # Source range(5, len(prefix)-5) adds just index len(prefix)-6.
        q = i - 5
        if q >= 5 and bars[q].low < bars[q - 1].low and bars[q].low < bars[q + 1].low:
            lows.append((q, bars[q].low))
        if i + 1 >= 20 and len(lows) >= 3:
            a, b, c = lows[-3:]
            ascending = a[1] < b[1] * 1.02 and b[1] < c[1] * 1.02
            shapes.append((True, a[0]) if ascending else (False, -1))
        else:
            shapes.append((False, -1))
    dif, dea, macd = precompute_macd_sequence(bars)
    return dict(white=white, yellow=yellow, ming=ming, kdj=kdj, n_shape=shapes,
                brick=_brick_series(bars), dif=dif, dea=dea, macd=macd)


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _rsl_or_none(bars, period):
    if len(bars) < period:
        return None
    recent = bars[-period:]
    low = min(k.low for k in recent)
    high = max(k.close for k in recent)
    if high == low:
        return None
    return round((bars[-1].close - low) / (high - low) * 100, 2)


def _field_spec():
    path = Path(__file__).resolve().parents[1] / 'contracts/a_share_kb_fields_v1.json'
    spec = json.loads(path.read_text())
    fields = spec['fields']
    if spec.get('schema') != 'a_share_kb_fields_v1' or len(fields) != 57 or len({f['name'] for f in fields}) != 57:
        raise ValueError('KB_FIELD_CONTRACT_INVALID')
    return spec


def append_kb_signals(frame):
    """Return original frame plus the 57 contract fields for one ordered symbol.

    Recursive calculations retain the full supplied prefix. Missing or invalid
    inputs remain null, and A/HK classification is determined by the code.
    This function performs no I/O on market data and never changes old columns.
    """
    spec = _field_spec()
    names = [f['name'] for f in spec['fields']]
    result = frame.copy()
    if result.empty:
        for name in names:
            result[name] = pd.Series(index=result.index, dtype=object)
        return result
    required = {'ts_code', 'trade_date', 'open', 'high', 'low', 'close', 'vol', 'pre_close', 'pct_chg'}
    if not required.issubset(result.columns):
        raise ValueError('KB_REQUIRED_INPUT_MISSING:' + ','.join(sorted(required - set(result.columns))))
    codes = set(result.ts_code.astype(str))
    if len(codes) != 1:
        raise ValueError('KB_ONE_SYMBOL_REQUIRED')
    code = next(iter(codes))
    dates = result.trade_date.astype(str).tolist()
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise ValueError('KB_TRADE_DATES_NOT_UNIQUE_SORTED')
    if not (len(code) == 9 and code[:6].isdigit() and code[6:] in {'.SH', '.SZ', '.BJ'}):
        for name in names:
            result[name] = None
        return result
    bars, flags = [], []
    cols = ['open', 'high', 'low', 'close', 'vol', 'pre_close', 'pct_chg']
    for date, values in zip(dates, result[cols].itertuples(index=False, name=None)):
        op, hi, lo, close, vol, prev, pct = values
        finite = [_finite(x) for x in values]
        valid_close = finite[3]
        valid_hlc = all(finite[i] for i in (1, 2, 3)) and lo <= close <= hi
        valid_ohlc = valid_hlc and finite[0] and lo <= op <= hi
        valid_vol = finite[4] and vol > 0
        valid_pct = finite[5] and prev > 0 and finite[6]
        clean = [float(v) if ok else 0.0 for v, ok in zip(values, finite)]
        op, hi, lo, close, vol, prev, pct = clean
        bars.append(DailyData(code, date, op, hi, lo, close, vol, 0.0, pct, prev))
        flags.append((valid_close, valid_hlc, valid_ohlc, valid_vol, valid_pct))
    # Prefix invalid counters prevent an invalid value from being silently
    # repaired or resetting a recursive EMA/KDJ/brick computation.
    bad = [[0] for _ in range(5)]
    for row in flags:
        for j in range(5):
            bad[j].append(bad[j][-1] + (not row[j]))
    def ok(kind, start, end):
        return start >= 0 and bad[kind][end] == bad[kind][start]
    cache = _cache(bars)
    outputs = {name: [] for name in names}
    valid_line_indices = []
    color_count = 0
    prev_color = None
    for i, day in enumerate(bars):
        n = i + 1
        p = _Prefix(bars, cache, 0, n)
        row = dict.fromkeys(names)
        close_prefix = ok(0, 0, n)
        hlc_prefix = ok(1, 0, n)
        line_valid = close_prefix and n >= 114 and cache['white'][i] > 0 and cache['yellow'][i] > 0
        if line_valid:
            valid_line_indices.append(i)
        # MACD is defined by the pinned source EMA/DEA initialization. The
        # 60-day divergence window needs 60 real DIF observations after warmup.
        if close_prefix and n >= 26:
            begin = max(0, n - 60)
            sig = detect_macd_signals(p[begin:n], cache['dif'][begin:n], cache['dea'][begin:n], cache['macd'][begin:n])
            row['kb_macd_dif_positive'] = sig['is_dif_positive']
            if n >= 27:
                for dst, src in [('kb_macd_dif_cross_zero','is_dif_cross_zero'),('kb_macd_dif_cross_zero_down','is_dif_cross_zero_down'),('kb_macd_gold_cross','is_gold_cross'),('kb_macd_dead_cross','is_dead_cross')]:
                    row[dst] = sig[src]
            if n >= 29:
                row['kb_macd_gold_fake'], row['kb_macd_dead_fake'] = sig['is_gold_fake'], sig['is_dead_fake']
            if n >= 85:
                row['kb_macd_top_divergence'], row['kb_macd_bottom_divergence'] = sig['is_top_divergence'], sig['is_bottom_divergence']
            if cache['dif'][i] >= 0:
                row['kb_macd_veto'] = False
            elif n >= 85:
                row['kb_macd_veto'] = not sig['is_bottom_divergence']
        if close_prefix and n >= 116:
            w, y = cache['white'], cache['yellow']
            row['kb_white_cross_up'] = w[i-1] <= y[i-1] and w[i] > y[i]
            row['kb_white_cross_down'] = w[i-1] >= y[i-1] and w[i] < y[i]
        if n >= 120 and line_valid and len(valid_line_indices) >= 3:
            a, b, c = valid_line_indices[-3:]
            w, y = cache['white'], cache['yellow']
            row['kb_bull_rope_status'] = ('金叉' if w[c] > y[c] and w[b] <= y[b] else
                '死叉' if w[c] < y[c] and w[b] >= y[b] else '牵牛' if w[c] > y[c] else '牛绳断')
        if n >= 120 and line_valid:
            w, y = cache['white'][i], cache['yellow'][i]
            row['kb_in_bowl'] = w > y and y <= day.close <= w
        if n >= 10 and ok(1, n-10, n):
            row['kb_breath_n_type'] = detect_breathing_structure(p)['breath_n_type']
        if n >= 10 and ok(3, n-8, n) and ok(4, n-7, n):
            phase = detect_breathing_structure(p)['breath_phase']
            row['kb_breath_phase'] = phase if phase in {'exhale','inhale','none'} else None
        for period, name in ((3,'kb_rsl_short'),(21,'kb_rsl_long')):
            if n >= period and ok(1, n-period, n):
                row[name] = _rsl_or_none(p, period)
        if n >= 22 and row['kb_rsl_short'] is not None and row['kb_rsl_long'] is not None:
            a, b = row['kb_rsl_short'], row['kb_rsl_long']
            row['kb_needle_20'] = a <= 20 and b >= 60
            row['kb_needle_30'] = b > 85 and a < 30
        if n >= 2 and ok(3, n-2, n):
            values = detect_volume_pattern(day, bars[i-1])
            row['kb_beidou'], row['kb_suoliang'] = values['is_beidou'], values['is_suoliang']
            if ok(2, n-1, n) and ok(4, n-1, n):
                row['kb_jiayin_zhenyang'] = values['is_jiayin_zhenyang']
                row['kb_jiayang_zhenyin'] = values['is_jiayang_zhenyin']
                row['kb_fangliang_yinxian'] = values['is_fangliang_yinxian']
        if close_prefix and n >= 121:
            row['kb_brick_trend_up'] = (calculate_slope(cache['ming'][i-6:i+1], 7) > -0.02
                                         and cache['white'][i] > cache['ming'][i])
        if hlc_prefix and n >= 12:
            row['kb_brick_value'] = cache['brick'][i]
        if hlc_prefix and n >= 14:
            row['kb_fanbao'] = _strict_fanbao(*cache['brick'][i-2:i+1])
        if n >= 9:
            color = 1 if cache['brick'][i] >= cache['brick'][i-1] else -1
            color_count = color_count + 1 if color == prev_color else 1
            previous_color = prev_color
            prev_color = color
            if hlc_prefix and n >= 14:
                row['kb_brick_flip_green'] = color == -1 and previous_color == 1
                if color_count <= n - 12:
                    row['kb_brick_consecutive'] = color_count
                    row['kb_brick_action'] = ('止损' if row['kb_brick_flip_green'] else '禁止抄底' if color == -1 else '减仓' if color_count >= 4 else '持有')
                elif color == -1:
                    row['kb_brick_action'] = '禁止抄底'
                elif n - 12 >= 4:
                    row['kb_brick_action'] = '减仓'
        if n >= 9 and hlc_prefix:
            row['kb_b1_j'] = cache['kdj'][i][2]
        if n >= 9 and hlc_prefix and ok(3,n-2,n) and ok(4,n-1,n):
            b1 = detect_b1_today(p)
            for dst, src in [('kb_b1','is_b1'),('kb_b1_score','b1_score'),('kb_b1_j','b1_j_value'),('kb_b1_amplitude','b1_amplitude'),('kb_b1_pct_chg','b1_pct_chg'),('kb_b1_volume_shrink','b1_volume_shrink')]: row[dst] = b1[src]
        if n >= 13 and hlc_prefix and ok(3,n-2,n) and ok(4,n-1,n):
            b2 = detect_b2_today(p)
            for dst, src in [('kb_b2','is_b2'),('kb_b2_score','b2_score'),('kb_b2_j','b2_j_value'),('kb_b2_pct_chg','b2_pct_chg'),('kb_b2_follows_b1','b2_follows_b1'),('kb_b2_volume_up','b2_volume_up')]: row[dst] = b2[src]
        if n >= 15 and ok(2,n-15,n) and ok(3,n-15,n) and ok(4,n-14,n):
            row['kb_b3'] = detect_b3(p)['is_b3']
        if n >= 8 and ok(2,n-8,n) and ok(3,n-3,n) and ok(4,n-2,n-1):
            row['kb_sb1'] = detect_sb1(p)['is_sb1']
        if n >= 15 and hlc_prefix and ok(2,n-15,n) and ok(3,n-10,n) and ok(4,n-10,n):
            row['kb_sb1_detailed'] = detect_sb1_detailed(p)['is_sb1_detailed']
        if n >= 24 and hlc_prefix and ok(2,n-24,n) and ok(3,n-24,n) and ok(4,n-23,n):
            row['kb_double_gun'] = detect_double_gun(p)['is_double_gun']
        if n >= 20 and ok(2,max(0,n-70),n) and ok(3,max(0,n-70),n):
            row['kb_nana'] = detect_nana_chart(p[max(0,n-70):n])['is_nana']
        # SOURCE_IMPLEMENTATION_DEFECT: the pinned source computes its historical
        # yellow line from only five/ten closes although MA14/28/57/114 need a
        # longer prefix.  Its default False is therefore not an observation.
        # Keep the copied source unchanged and leave kb_rebuild unknown.
        if n >= 30 and ok(2,n-20,n) and ok(3,n-20,n) and min(x.low for x in bars[n-20:n]) > 0:
            row['kb_ready'] = detect_yueyueyushi(p)['is_ready']
        if n >= 20 and ok(2,n-20,n) and ok(3,n-2,n):
            row['kb_didi'] = detect_didi(p)['is_didi']
        if n >= 20 and ok(2,n-20,n) and ok(3,n-20,n) and ok(4,n-20,n):
            row['kb_centipede'] = detect_centipede_pattern(p)['is_centipede']
        if n >= 21 and ok(2,n-21,n) and ok(3,n-6,n) and ok(4,n-6,n):
            row['kb_violence_k'] = any(x['is_latest'] for x in detect_violence_k(p))
        if n >= 60 and close_prefix and ok(2,max(0,n-120),n) and ok(3,n-60,n) and ok(4,n-20,n) and bars[n-20].close > 0:
            span = bars[max(0,n-120):n]
            if max(x.high for x in span) > min(x.low for x in span):
                kirin = detect_kirin_stage(p)
                row['kb_kirin_position'] = kirin['indicators']['price_position']
                row['kb_kirin_vol'] = kirin['indicators']['vol_pattern']
                if n >= 114 and hlc_prefix:
                    row['kb_kirin_stage'], row['kb_kirin_conf'] = kirin['stage'], kirin['confidence']
        for name in names:
            outputs[name].append(row[name])
    for name, values in outputs.items():
        result[name] = values
    return result
