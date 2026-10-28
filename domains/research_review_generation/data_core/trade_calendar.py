"""交易日历 —— 全系统唯一的交易日推导入口"""

from __future__ import annotations

import datetime
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

from .util import china_now, china_today, is_a_share_closed, is_weekend

_REF_STOCK = "sh600000"  # 浦发银行，流动性好、每个交易日都有，用来取真实交易日序列


def _ref_dates(start: str, end: str, *, ctx) -> list[str]:
    """参考股在 [start, end] 区间内的真实交易日（升序，YYYY-MM-DD）。失败返回空表。"""
    try:
        df = ctx.ak_call("stock_zh_a_hist_tx",
            symbol=_REF_STOCK, start_date=start.replace("-", ""), end_date=end.replace("-", "")
        )
        if df is None or "date" not in df.columns:
            return []
        return sorted(str(x) for x in df["date"])
    except Exception:
        return []


def next_trade_date(date: str, *, ctx) -> Optional[str]:
    """date 的次一交易日；来源不可用时返回 None，不猜测节假日。"""
    end = (datetime.datetime.strptime(date, "%Y-%m-%d") + datetime.timedelta(days=12)).strftime("%Y-%m-%d")
    for d in _ref_dates(date, end, ctx=ctx):
        if d > date:
            return d
    return None


def prev_trade_date(date: str, *, ctx) -> Optional[str]:
    """date 的前一交易日；来源不可用时返回 None，不猜测节假日。"""
    start = (datetime.datetime.strptime(date, "%Y-%m-%d") - datetime.timedelta(days=16)).strftime("%Y-%m-%d")
    earlier = [d for d in _ref_dates(start, date, ctx=ctx) if d < date]
    if earlier:
        return earlier[-1]
    return None


def last_trade_dates(n: int = 5, *, ctx) -> list[str]:
    """最近 n 个**已收盘**交易日（升序）。上海时区未收盘的今天会被剔除。"""
    today = china_now(ctx=ctx).date()
    start = (today - datetime.timedelta(days=n * 3 + 12)).strftime("%Y-%m-%d")
    dates = _ref_dates(start, today.strftime("%Y-%m-%d"), ctx=ctx)
    if dates and dates[-1] == china_today(ctx=ctx) and not is_a_share_closed(ctx=ctx):
        dates = dates[:-1]
    return dates[-n:]


def trade_dates_ending_at(end_date: str, n: int = 10, *, ctx) -> list[str]:
    """**以 end_date 为终点**向前取 n 个交易日（升序，含 end_date 本身若它是交易日）"""
    start = (
        datetime.datetime.strptime(end_date, "%Y-%m-%d") - datetime.timedelta(days=n * 3 + 16)
    ).strftime("%Y-%m-%d")
    dates = [d for d in _ref_dates(start, end_date, ctx=ctx) if d <= end_date]
    # 未收盘的今天不算「已定稿」，与 last_trade_dates 口径保持一致
    if dates and dates[-1] == china_today(ctx=ctx) and not is_a_share_closed(ctx=ctx):
        dates = dates[:-1]
    return dates[-n:]


_QUOTE_URL = "http://qt.gtimg.cn/q="
_F_QUOTE_TIME = 30      # 腾讯实时行情的时间戳字段，形如 20260724161450
_QUOTE_DAY_TTL = 120.0
_QUOTE_DAY_BOUNDARIES = ((9, 15), (15, 5))    # 开盘（集合竞价）/ 收盘定稿


def _seconds_to_next_boundary(*, ctx) -> float:
    """距下一个交易状态边界还有几秒（跨天则算到明天那个）"""
    n = china_now(ctx=ctx)
    now_s = (n.hour * 3600 + n.minute * 60 + n.second) + n.microsecond / 1e6
    for h, m in _QUOTE_DAY_BOUNDARIES:
        b = float(h * 3600 + m * 60)
        if b > now_s:
            return b - now_s
    first = float(_QUOTE_DAY_BOUNDARIES[0][0] * 3600 + _QUOTE_DAY_BOUNDARIES[0][1] * 60)
    return 24 * 3600 - now_s + first


def quote_trade_day(*, ctx) -> Optional[str]:
    """参考股**实时行情**里的交易日（YYYY-MM-DD）。判不了返回 None"""
    import time as _time

    now = _time.monotonic()          # 单调时钟：不受系统改时间 / 夏令时影响
    until = ctx.memo.setdefault("quote_day", {}).get("until")
    if isinstance(until, float) and now < until:
        return ctx.memo.setdefault("quote_day", {}).get("day")  # type: ignore[return-value]

    with ctx.lock:            # 单飞：别让开盘前的慢请求覆盖开盘后的新结果
        now = _time.monotonic()
        until = ctx.memo.setdefault("quote_day", {}).get("until")
        if isinstance(until, float) and now < until:
            return ctx.memo.setdefault("quote_day", {}).get("day")  # type: ignore[return-value]

        deadline = now + min(_QUOTE_DAY_TTL, max(0.0, _seconds_to_next_boundary(ctx=ctx)))

        day = None
        try:
            import urllib.request

            raw = ctx.http_get(_QUOTE_URL + _REF_STOCK, timeout=8).content.decode("gbk", "ignore")
            f = raw.split("~")
            ts = f[_F_QUOTE_TIME].strip() if len(f) > _F_QUOTE_TIME else ""
            if len(ts) >= 8 and ts[:8].isdigit():
                day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        except Exception:  # noqa: BLE001  判不了就判不了，交给调用方保守降级
            day = None
        if _time.monotonic() < deadline:
            ctx.memo.setdefault("quote_day", {}).clear()
            ctx.memo.setdefault("quote_day", {}).update({"day": day, "until": deadline})
        else:
            ctx.memo.setdefault("quote_day", {}).clear()
            logger.warning("取行情交易日时跨过了状态边界，本次结果不入缓存")
        return day


def latest_session(*, ctx) -> Optional[str]:
    """最近一个已收盘交易日。三层判据缺一不可："""
    today = china_today(ctx=ctx)
    if not is_weekend(today) and is_a_share_closed(ctx=ctx) and quote_trade_day(ctx=ctx) == today:
        return today
    latest = last_trade_dates(1, ctx=ctx)
    return latest[-1] if latest else None


def is_settled(date: str, *, ctx) -> bool:
    """date 的盘面数据是否已定稿、不会再变 —— 落盘缓存的唯一判据"""
    # A date comparison alone treats Saturday/Sunday (and any future weekday
    # that happens to be before ``today`` in a replay) as a settled session.
    # The live VR pool is allowed to fall back only across real sessions; a
    # weekend pool response is commonly the previous Friday's data with the
    # requested date still echoed back by the provider.
    if is_weekend(date):
        return False
    return date < china_today(ctx=ctx) or date == latest_session(ctx=ctx)


def is_latest_closed_session(date: str, *, ctx) -> bool:
    """date 是否就是最近一个已收盘交易日"""
    return date == latest_session(ctx=ctx)


def live_quotes_are_close_of(date: str, *, ctx) -> tuple[bool, str]:
    """现在去拉实时行情，拿到的值能不能当作 `date` 的**收盘**涨跌幅？

    ⚠️ 这个判据只回答「**实时行情**这条路通不通」。它为 False **不等于**
    那一天算不出来 —— 已收盘的场次走定稿记录（`data.fetch_prev_pool`）照样能算，
    那才是复盘类指标的首选路径。把它当成"整块不可用"的闸，
    会让历史场次永远看不到（复盘系统的基本功能就没了）。
    """
    if date != latest_session(ctx=ctx):
        return False, f"{date} 非最近已收盘交易日；实时行情只有当前值，不能冒充历史收盘"

    qd = quote_trade_day(ctx=ctx)
    if qd is None:
        return False, ("判不出实时行情属于哪个交易日（取数失败），"
                       "保守起见不拿它当收盘用")
    if qd != date:
        # 盘中问昨天，就会走到这里：行情已经跳到今天这一场了
        return False, (f"实时行情当前属于 {qd} 这一场，不能当作 {date} 的收盘表现"
                       f"（{date} 那一场的价已经过去了）"
                       "—— 这只说明**实时行情**这条路不通；已收盘场次改用定稿记录")
    if date == china_today(ctx=ctx) and not is_a_share_closed(ctx=ctx):
        # 同一场、但这场还没结束 → 手里是**今天盘中**的价
        return False, (f"当前是交易时段，实时行情是**今天盘中**的价，"
                       f"不能当作 {date} 的收盘表现 —— 今天这一场要等收盘才有定稿数据")
    return True, ""
