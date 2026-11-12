"""取单只股票 TDX F10，写 {OUT}/f10_cache/{code}.json。

在 v4-mac venv 下运行（该环境有 pytdx，但没有 dotenv）。
被 build_stock_page.py 读取，避免把 pytdx 依赖带进技能计算进程。
"""

import json
import os
import re
import socket
import sys

socket.setdefaulttimeout(20)
from pytdx.hq import TdxHq_API  # noqa: E402

OUT = ("/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates"
       "/junda-single-20261101-8e342a6d64746507/research-panel/kb/f10_cache")


def concepts_from(txt):
    idx = [m.start() for m in re.finditer("【3.概念板块】", txt)]
    if not idx:
        return []
    seg = txt[idx[-1]:]
    out, seen = [], set()
    noise = {"概念名称", "PDF原文地址", "公告日期", "稽查结果", "处理决定", "概念解析"}
    for line in seg.split("\n"):
        line = line.strip()
        if not line.startswith("｜"):
            continue
        p = [x.strip() for x in line.strip("｜").split("｜")]
        if len(p) < 2:
            continue
        name = p[0]
        if not name or name in noise or len(name) > 12 or name in seen:
            continue
        if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", name):
            continue
        seen.add(name)
        out.append({"name": name, "desc": p[1][:160]})
    return out


def grab(txt, label):
    m = re.search(re.escape(label) + r"[^｜]*｜\s*([-0-9.]+)", txt)
    return float(m.group(1)) if m else None


def main(symbol):
    code = symbol.split(".")[0]
    api = TdxHq_API()
    host = None
    for h in [("115.238.90.165", 7709), ("119.147.212.81", 7709), ("101.227.73.20", 7709)]:
        try:
            if api.connect(*h):
                host = h
                break
        except Exception:
            continue
    if host is None:
        print("连接失败")
        return 1
    mk = 1 if code.startswith(("6", "9")) else 0
    cat = api.get_company_info_category(mk, code)
    if not cat:
        print(f"{code} 无 F10")
        api.disconnect()
        return 1
    raw = api.get_company_info_content(mk, code, cat[0]["filename"], cat[0]["start"], cat[0]["length"])
    fi = api.get_finance_info(mk, code) or {}
    api.disconnect()
    txt = (raw if isinstance(raw, str) else raw.decode("gbk", "ignore")).replace("\x00", "")

    payload = {
        "symbol": symbol,
        "host": f"{host[0]}:{host[1]}",
        "concepts": concepts_from(txt),
        "finance": {
            "gudongrenshu": int(fi.get("gudongrenshu") or 0) or None,
            "zongguben": int(fi.get("zongguben") or 0) or None,
            "liutongguben": int(fi.get("liutongguben") or 0) or None,
            "ipo_date": str(fi.get("ipo_date") or "") or None,
            "eps": grab(txt, "每股收益(元)"),
            "bps": grab(txt, "每股净资产(元)"),
            "roe_pct": grab(txt, "净资产收益率(%)"),
        },
        "announcement": (re.search(r"★最新公告:(\d{4}-\d{2}-\d{2})[^｜]*", txt).group(0)
                         if re.search(r"★最新公告:(\d{4}-\d{2}-\d{2})", txt) else None),
    }
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/{code}.json"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    print(f"{code}: {len(payload['concepts'])} 概念  股东 {payload['finance']['gudongrenshu']}  → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "002865.SZ"))
