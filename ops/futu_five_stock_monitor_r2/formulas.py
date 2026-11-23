"""Literal daily formulas. None means UNKNOWN; missing values are never zeroed.

EMA and Chinese SMA seed at the first valid input. Any subsequent missing input
invalidates the recursive tail. MA requires a complete window. Source is QFQ
OpenD daily OHLC, volume in shares, including today's still-forming daily bar.
"""
from math import isfinite
from statistics import fmean
from decimal import Decimal, DecimalException


def number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def ma(values, n):
    return [fmean(values[i-n+1:i+1]) if i >= n-1 and
            all(v is not None for v in values[i-n+1:i+1]) else None
            for i in range(len(values))]


def recursive(values, alpha):
    out, last, started, broken = [], None, False, False
    for value in values:
        if broken or value is None:
            broken = started or broken
            out.append(None)
            continue
        last = value if not started else alpha * value + (1-alpha) * last
        started = True
        out.append(last)
    return out


def indicators(rows):
    close = [number(r.get("close")) for r in rows]
    low = [number(r.get("low")) for r in rows]
    high = [number(r.get("high")) for r in rows]
    volume = [number(r.get("volume")) for r in rows]
    avgs = {n: ma(close, n) for n in (3, 6, 12, 14, 24, 28, 57, 60, 114)}
    blend = lambda ns: [fmean(avgs[n][i] for n in ns) if
                         all(avgs[n][i] is not None for n in ns) else None
                         for i in range(len(rows))]
    white = recursive(recursive(close, 2/11), 2/11)
    rsv = []
    for i, c in enumerate(close):
        ls, hs = low[max(0, i-8):i+1], high[max(0, i-8):i+1]
        if i < 8 or c is None or None in ls or None in hs or max(hs) == min(ls):
            rsv.append(None)
        else:
            rsv.append((c-min(ls))/(max(hs)-min(ls))*100)
    k = recursive(rsv, 1/3)
    d = recursive(k, 1/3)
    j = [3*a-2*b if a is not None and b is not None else None for a,b in zip(k,d)]
    yellow, bbi = blend((14,28,57,114)), blend((3,6,12,24))
    return [dict(close=c, open=number(rows[i].get("open")), low=low[i], high=high[i], volume=volume[i],
                 bbi=bbi[i], white=white[i], yellow=yellow[i], ma60=avgs[60][i],
                 rsv=rsv[i], k=k[i], d=d[i], j=j[i]) for i,c in enumerate(close)]


def rules(features):
    """Evaluate each independent rule using only its own exact dependencies."""
    result = {}
    def evaluate(name, fn):
        try:
            result[name] = bool(fn())
        except (TypeError, ValueError, ZeroDivisionError, IndexError, DecimalException):
            result[name] = None
    def v(field, lag=0):
        value = features[-1-lag][field]
        if value is None:
            raise ValueError("UNKNOWN " + field)
        return Decimal(str(value))
    def avg_volume(lag, count):
        return sum(v("volume", lag+i) for i in range(count))/count
    def change(lag=0):
        return (v("close",lag)/v("close",lag+1)-1)*100
    def all_known(*conditions):
        # Evaluate all dependencies before conjunction, preserving UNKNOWN.
        return all(conditions)
    def guard(lag):
        return v("high",lag+1) if v("low",lag)>v("high",lag+1) else min(v("low",lag),v("close",lag+1))
    evaluate("B1买点候选", lambda: all_known(v("bbi")>v("white"), v("white")>v("yellow"), v("j")<=13))
    evaluate("B2_1006_ORAL_CONTEXT", lambda: v("volume")>=v("volume",1))
    evaluate("B2_151_VOLUME_CONTEXT", lambda: v("volume")>v("volume",1)*Decimal("1.20"))
    evaluate("B2_USER_EXACT_CANDIDATE", lambda: all_known(
        sum(v("j",i)<13 for i in range(3))>0,
        v("volume")>avg_volume(1,4)*Decimal("1.25"), change()>4,
        v("j")<70, v("white")>v("yellow")))
    evaluate("B3买点候选", lambda: all_known(
        v("j",2)<20, v("volume",1)>avg_volume(2,4)*Decimal("1.15"),
        change(1)>3, v("white")>v("yellow"),
        change()>0 or (change()>-3 and (v("volume")/v("volume",1)<Decimal("0.6") or v("volume")/v("volume",1)>Decimal("0.9")))))
    evaluate("守线失守风险", lambda: v("close")<guard(1))
    evaluate("白黄线死叉", lambda: all_known(v("white")<v("yellow"),v("white",1)>v("yellow",1)))
    evaluate("破前低风险", lambda: v("close")/min(v("close",2),v("low",1))<Decimal("0.99"))
    risks = [result[k] for k in ("守线失守风险","白黄线死叉","破前低风险")]
    result["卖点公式完整命中"] = True if True in risks else (None if None in risks else False)
    evaluate("缩量回调观察", lambda: all_known(change()<0,v("volume")<v("volume",1)))
    evaluate("放量阳包阴观察", lambda: all_known(v("volume")>v("volume",1),
        v("close",1)<v("open",1),v("close")>v("open"),
        v("open")<=v("close",1),v("close")>=v("open",1)))
    return result


def calculate(rows):
    if len(rows)<116:
        return {"status":"UNKNOWN", "reason":"至少116根（114日均线及REF预热）同源日线不足"}
    for row in rows:
        c,o,h,l,vol = [number(row.get(k)) for k in ("close","open","high","low","volume")]
        if any(x is None for x in (c,o,h,l,vol)) or min(c,o,h,l)<=0 or vol<0 or not l<=min(c,o)<=max(c,o)<=h:
            return {"status":"UNKNOWN","reason":"日线缺失、非有限数、单位或OHLC异常"}
    fs = indicators(rows)
    out = rules(fs)
    cur, prev, prev2 = fs[-1],fs[-2],fs[-3]
    pct = (cur["close"]/prev["close"]-1)*100
    yesterday_pct = (prev["close"]/prev2["close"]-1)*100
    volume_base = fmean(r["volume"] for r in fs[-5:-1])
    yesterday_volume_base = fmean(r["volume"] for r in fs[-6:-2])
    line = f"白线={cur['white']}，黄线={cur['yellow']}"
    yesterday_guard = prev2["high"] if prev["low"]>prev2["high"] else min(prev["low"],prev2["close"])
    details = {
        "B1买点候选":f"BBI={cur['bbi']}>白线；白线>黄线；J={cur['j']}<=13；{line}",
        "B2_1006_ORAL_CONTEXT":f"VOL={cur['volume']}>=昨日VOL={prev['volume']}（仅量能语境）",
        "B2_151_VOLUME_CONTEXT":f"VOL={cur['volume']}>昨日VOL={prev['volume']}*1.20（仅量能语境）",
        "B2_USER_EXACT_CANDIDATE":f"近3日J={[r['j'] for r in fs[-3:]]}含J<13；VOL={cur['volume']}>昨日向前4日均量={volume_base}*1.25；今日涨幅={pct:g}%>4；J={cur['j']}<70；{line}",
        "B3买点候选":f"前日J={prev2['j']}<20；昨日VOL={prev['volume']}>前4日均量={yesterday_volume_base}*1.15；昨日涨幅={yesterday_pct:g}%>3；今日涨幅={pct:g}%；VOLR={cur['volume']/prev['volume'] if prev['volume'] else 'UNKNOWN'}，真突破原式成立；{line}",
        "守线失守风险":f"CLOSE={cur['close']}<REF(昨日守线,1)={yesterday_guard}",
        "白黄线死叉":f"{line}；昨日白线={prev['white']}>昨日黄线={prev['yellow']}",
        "破前低风险":f"CLOSE={cur['close']}/MIN(前日CLOSE={prev2['close']},昨日LOW={prev['low']})<0.99",
        "卖点公式完整命中":" OR ".join(k for k in ("守线失守风险","白黄线死叉","破前低风险") if out[k] is True),
        "缩量回调观察":f"今日涨幅={pct:g}%<0；VOL={cur['volume']}<昨日VOL={prev['volume']}",
        "放量阳包阴观察":f"今日阳线实体覆盖昨日阴线实体，VOL={cur['volume']}>昨日VOL={prev['volume']}（辅助观察，非B公式新增门槛）",
    }
    return {"status":"READY", "rules":out, "last":fs[-1], "conditions":details,
            "initialization":"EMA/SMA first valid input; recursive missing tail UNKNOWN"}
