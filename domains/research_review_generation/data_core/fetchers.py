"""Preserved Vibe data calculations, using one explicit V4 raw owner."""
import re
import json
import time
import datetime
import pandas as pd
DELAY_HOST = "https://push2delay.eastmoney.com/api/qt/clist/get"


UT_FUND = "b2884a393a59ad64002292a3e90d46a5"  # 资金流 ut


HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0 Safari/537.36"}


YI = 1e8  # 元 → 亿


ALL_A_FS = ("m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:7,m:1+t:3,"
            "m:0+t:13,m:0+t:81+s:2048")


def _clist(fs, fid, fields, ut=UT_FUND, pz=100, max_pages=80, retries=3, *, ctx):
    """
    通用 clist 抓取, 返回 list[dict].
    注意: push2delay 镜像把单页 pz 硬截到 100, 所以按"实际累计返回数"翻页,
    不能用 page*pz 估算 (否则会提前停)。
    """
    rows = []
    page = 1
    total = None
    while page <= max_pages:
        params = {
            "pn": page, "pz": pz, "po": 1, "np": 1, "ut": ut,
            "fltt": 2, "invt": 2, "fid": fid, "fs": fs,
            "fields": fields, "_": int(time.time() * 1000),
        }
        r = ctx.http_get(DELAY_HOST, params=params, headers=HEADERS, timeout=15,
                         attempts=retries, retry_delay=1.5, validate_json=True)
        data = r.json().get("data")
        if not data or not data.get("diff"):
            break
        diff = data["diff"]
        rows.extend(diff)
        total = data.get("total", 0)
        if len(rows) >= total or len(diff) == 0:
            break
        page += 1
    return rows


def _f(v):
    """安全转 float, '-'/None → None."""
    try:
        if v in ("-", "", None):
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def fetch_zt_pool(date, *, ctx):
    out = {"zt": None, "zb_count": 0, "dt_count": 0, "highest_consec": 0, "ladder": []}
    try:
        zt = ctx.ak_call("stock_zt_pool_em", date=date)
        out["zt"] = zt
        if "连板数" in zt.columns and len(zt):
            out["highest_consec"] = int(zt["连板数"].max())
        # 连板梯队: 按连板数降序
        zt_sorted = zt.sort_values("连板数", ascending=False)
        for _, r in zt_sorted.iterrows():
            out["ladder"].append({
                "code": str(r["代码"]),
                "name": str(r["名称"]),
                "consec_boards": int(r["连板数"]) if pd.notna(r["连板数"]) else 0,
                "sector": str(r.get("所属行业", "")),
                "first_seal_time": str(r.get("首次封板时间", "")),
            })
    except Exception as e:
        out["error_zt"] = f"{type(e).__name__}: {str(e)[:100]}"
    try:
        zb = ctx.ak_call("stock_zt_pool_zbgc_em", date=date)
        out["zb_count"] = len(zb)
    except Exception as e:
        out["error_zb"] = f"{type(e).__name__}: {str(e)[:100]}"
    try:
        dt = ctx.ak_call("stock_zt_pool_dtgc_em", date=date)
        out["dt_count"] = len(dt)
    except Exception as e:
        out["error_dt"] = f"{type(e).__name__}: {str(e)[:100]}"
    return out


def _fetch_iwencai_zt_reasons(date, *, ctx):
    """
    date: 'YYYYMMDD'
    iwencai 返回 涨停原因[YYYYMMDD] 列, 代码形如 002491.SZ, 取前6位匹配.
    reason 形如 '光纤光缆+产能扩张+数据中心', 已是简洁题材串, 直接用.

    ⚠️ 问的必须是 `date` 那一场，不能问"今日" —— 复盘的常态就是收盘后回看上一场，
    问"今日"会把当天的题材当成被复盘那天的题材，而且看不出来（题材串本身没有日期）。
    返回列名里带着问财实际给的日期（`涨停原因[YYYYMMDD]`），拿它和请求的日期对一遍：
    不一致就当取数失败，宁可没有题材串，也不能把别的交易日的题材塞进这一场。
    """
    if not (len(str(date)) == 8 and str(date).isdigit()):
        return {}, f"日期格式应为 YYYYMMDD, 收到 {date!r}"
    d = str(date)
    query = f"{d[:4]}-{d[4:6]}-{d[6:8]}涨停的股票 涨停原因"

    reasons = {}
    err = None
    try:
        # 翻页拿全部涨停 (单页 limit=50, 一般 1~2 页够)
        for page in range(1, 4):
            df = ctx.iwencai_query(query, page=page, limit=50)
            if df is None or len(df) == 0:
                break
            code_cols = [c for c in df.columns if "代码" in c]
            reason_cols = [c for c in df.columns if "涨停原因" in c]
            if not code_cols or not reason_cols:
                err = f"返回无涨停原因列, cols={list(df.columns)[:6]}"
                break
            # 只认**能验出场次**的列。列名形如 涨停原因[20260729]；验不出来就当失败，
            # 别"匹配不到就放行" —— 那等于在最需要拦的时候（返回了没日期的通用列）
            # 恰好不拦，错场次的题材照样进来。
            dated = {m.group(1): c for c in reason_cols
                     if (m := re.search(r"\[(\d{8})\]", c))}
            if not dated:
                return {}, f"涨停原因列没带日期, 无法确认是哪一场: {reason_cols[:3]}"
            if d not in dated:
                return {}, f"问财返回的是 {sorted(dated)} 的涨停原因, 不是 {d}"
            cc, rc = code_cols[0], dated[d]
            for _, r in df.iterrows():
                code6 = str(r[cc])[:6]
                reason = str(r[rc]).strip()
                if reason and reason.lower() != "nan" and code6 not in reasons:
                    reasons[code6] = _clean_reason(reason)
            if len(df) < 50:
                break
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:90]}"
    return reasons, err


def _set_zt_reason_metadata(metadata: dict | None, *, ctx) -> None:
    ctx.reason_metadata = dict(metadata or {})


def fetch_zt_reasons_with_metadata(date, *, ctx):
    """Return legacy reasons/error plus the provider receipt for cache writers."""
    ctx.reason_metadata = {}
    reasons, err = fetch_zt_reasons(date, ctx=ctx)
    return reasons, err, dict(ctx.reason_metadata)


def fetch_zt_reasons(date, *, ctx):
    """Fetch one exact session, preferring configured Fuyao source.

    Fuyao is selected whenever its key is configured.  The legacy Iwencai
    route remains available when Fuyao is absent.  A configured Fuyao request
    never silently falls back to an older response or to Iwencai after a Fuyao
    error.
    """
    # An approved exact-session reason cache is shared by all higher-level readers.
    token = str(date)
    iso = f"{token[:4]}-{token[4:6]}-{token[6:8]}" if len(token) == 8 else token
    try:
        cached = ctx.cache.read_json(f"cache/zt_reasons/{iso}.json")
    except FileNotFoundError:
        cached = None
    if isinstance(cached, dict) and cached.get("schema") == 1 and cached.get("date") == iso:
        _set_zt_reason_metadata(cached.get("source_provenance", {}), ctx=ctx)
        return dict(cached.get("reasons") or {}), None
    fuyao_key = ctx.fuyao_key.strip()
    if fuyao_key:
        metadata = {
            "schema": "vibe.fuyao.limit_up_reasons.v1",
            "provider": "FUYAO",
            "request_target_date": str(date),
            "complete": False,
        }
        try:
            from .fuyao_sources import fetch_limit_up_reasons

            result = fetch_limit_up_reasons(str(date), api_key=fuyao_key, http_get=ctx.http_get)
            reasons = {
                str(code): _clean_reason(reason)
                for code, reason in result.reasons.items()
            }
            metadata = dict(result.metadata)
            metadata["reason_count"] = len(reasons)
            _set_zt_reason_metadata(metadata, ctx=ctx)
            return reasons, None
        except Exception as exc:  # noqa: BLE001 — source failure is a visible optional gap
            _set_zt_reason_metadata(metadata, ctx=ctx)
            detail = str(exc).replace(fuyao_key, "[REDACTED]")[:120]
            return {}, f"FUYAO_LIMIT_UP_REASON_ERROR: {type(exc).__name__}: {detail}"

    reasons, err = _fetch_iwencai_zt_reasons(date, ctx=ctx)
    _set_zt_reason_metadata({
        "schema": "vibe.iwencai.limit_up_reasons.v1",
        "provider": "IWENCAI",
        "request_target_date": str(date),
        "complete": bool(reasons) and err is None,
        "reason_count": len(reasons),
    }, ctx=ctx)
    return reasons, err


def _clean_reason(text, max_tags=4, max_len=30):
    """题材串清洗: 去空白, 限标签数与长度 (iwencai 多用 '+' 分隔)."""
    text = text.replace("，", "+").replace(",", "+").strip()
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if parts:
        text = "+".join(parts[:max_tags])
    return text[:max_len]


def fetch_lhb(date, top=15, *, ctx):
    rows = []
    try:
        df = ctx.ak_call("stock_lhb_detail_em", start_date=date, end_date=date)
        if len(df):
            df = df.sort_values("龙虎榜净买额", ascending=False)
            # 机构净买: 该接口无独立机构净买列, 从「解读」推断不可靠 → 填 null
            for _, r in df.head(top).iterrows():
                rows.append({
                    "code": str(r["代码"]),
                    "name": str(r["名称"]),
                    "net_buy": round(_f(r["龙虎榜净买额"]) / YI, 2)
                    if _f(r["龙虎榜净买额"]) is not None else None,
                    "reason": str(r.get("上榜原因", ""))[:40],
                    "inst_net": None,  # 该接口不直接提供机构净买额
                })
    except Exception as e:
        return [{"error": f"{type(e).__name__}: {str(e)[:100]}"}]
    return rows


def fetch_turnover_top20(top=20, *, ctx):
    """返回 [{code,name,price,change_pct,amount(亿),sector}], 按成交额降序."""
    rows = _clist(ALL_A_FS, "f6", "f12,f14,f2,f3,f6,f100",
                  ut=UT_FUND, pz=top, max_pages=1, ctx=ctx)
    out = []
    for r in rows[:top]:
        amt = _f(r.get("f6"))
        sector = str(r.get("f100", "")).strip()
        out.append({
            "code": str(r.get("f12", "")),
            "name": str(r.get("f14", "")),
            "price": _f(r.get("f2")),
            "change_pct": _f(r.get("f3")),
            "amount": round(amt / YI, 2) if amt is not None else None,
            "sector": sector if sector and sector != "-" else None,
        })
    return out


def fetch_sector_flow(sector_t, *, ctx):
    """
    sector_t: '2'=行业, '3'=概念
    一次性拿全部板块的 今日/5日/10日 主力净额 + 涨跌幅 + 领涨股.
    返回 list[dict]: bk_code/name/change_pct/inflow_raw/in5_raw/in10_raw/lead_stock
    """
    fs = f"m:90 t:{sector_t}"
    # 今日: fid=f62, 带涨跌幅 f3 + 领涨股 f128
    today_rows = _clist(fs, "f62", "f12,f14,f3,f62,f128",
                        ut=UT_FUND, pz=100, max_pages=10, ctx=ctx)
    # 5日累计主力净额: f164
    five_rows = _clist(fs, "f164", "f12,f164", ut=UT_FUND, pz=100, max_pages=10, ctx=ctx)
    # 10日累计主力净额: f174
    ten_rows = _clist(fs, "f174", "f12,f174", ut=UT_FUND, pz=100, max_pages=10, ctx=ctx)

    five_map = {str(r.get("f12")): _f(r.get("f164")) for r in five_rows}
    ten_map = {str(r.get("f12")): _f(r.get("f174")) for r in ten_rows}

    out = []
    for r in today_rows:
        bk = str(r.get("f12", ""))
        out.append({
            "bk_code": bk,
            "name": str(r.get("f14", "")),
            "change_pct": _f(r.get("f3")),
            "inflow_raw": _f(r.get("f62")),   # 今日主力净额(元)
            "in5_raw": five_map.get(bk),       # 5日累计(元)
            "in10_raw": ten_map.get(bk),       # 10日累计(元)
            "lead_stock": str(r.get("f128", "")),
        })
    return out


def enrich_trend(sector_list):
    for s in sector_list:
        s["inflow_today"] = round(s["inflow_raw"] / YI, 2) \
            if s["inflow_raw"] is not None else None
        s["inflow_5d"] = round(s["in5_raw"] / YI, 2) \
            if s["in5_raw"] is not None else None
        s["inflow_10d"] = round(s["in10_raw"] / YI, 2) \
            if s["in10_raw"] is not None else None
        # 近似"连续流入档位": 今日/5日/10日 同为正各记 1 (0~3),
        # 非真实逐日连板天数, 是三窗口一致性代理.
        t, f5, f10 = s["inflow_today"], s["inflow_5d"], s["inflow_10d"]
        consec = None
        if t is not None and f5 is not None and f10 is not None:
            consec = sum(1 for x in (t, f5, f10) if x > 0)
        s["consec_inflow_days"] = consec
