"""全市场概念补齐：逐股读 TDX F10 概念板块，与 block 文件取并集。

为什么需要：block_gn.dat / block.dat 单条记录固定 2800 字节、每只 7 字节，
最多只能装 400 只；27 个概念板块、13 个行业板块正好触顶被截断，
5G概念、人工智能、人形机器人、国防军工这些宽口径热门板块全在截断名单里。
F10 是按股票查的，没有这个上限。

产出：
  f10_concepts.parquet        每行 = 代码 × 概念名 × 描述片段
  f10_concept_manifest.json   条数与耗时

RESEARCH_ONLY. 只读 TDX 服务器。
"""

import json
import re
import socket
import sys
import time
from datetime import datetime, timezone

import pandas as pd

socket.setdefaulttimeout(20)

from pytdx.hq import TdxHq_API  # noqa: E402

HOSTS = [("115.238.90.165", 7709), ("119.147.212.81", 7709), ("101.227.73.20", 7709)]
BASE = (
    "/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101"
    "/kb_panel_upgrade_20261101/concept_collect"
)
# 概念板块段落里出现的非概念行
NOISE = {"概念名称", "PDF原文地址", "公告日期", "稽查结果", "处理决定", "概念解析"}


def market_of(code):
    """通达信市场号：1=上海，0=深圳/北京。"""
    return 1 if code[0] in "69" else 0


def parse_concepts(txt):
    idx = [m.start() for m in re.finditer("【3.概念板块】", txt)]
    if not idx:
        return []
    seg = txt[idx[-1] :]
    out = []
    seen = set()
    for line in seg.split("\n"):
        line = line.strip()
        if not line.startswith("｜"):
            continue
        parts = [p.strip() for p in line.strip("｜").split("｜")]
        if len(parts) < 2:
            continue
        name, desc = parts[0], parts[1]
        if not name or name in NOISE or len(name) > 12:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append((name, desc[:200]))
    return out


def connect():
    api = TdxHq_API()
    for host in HOSTS:
        try:
            if api.connect(*host):
                return api, host
        except Exception:
            continue
    return None, None


def main():
    codes = sorted(pd.read_parquet(f"{BASE}/concept_membership.parquet").code.unique())
    print(f"待处理 {len(codes):,} 只")

    api, host = connect()
    if api is None:
        print("连接失败")
        return 1
    print(f"连接 {host[0]}:{host[1]}")

    rows = []
    fails = []
    t0 = time.time()
    for i, code in enumerate(codes, 1):
        try:
            cat = api.get_company_info_category(market_of(code), code)
            if not cat:
                fails.append((code, "NO_F10"))
                continue
            c = cat[0]
            data = api.get_company_info_content(market_of(code), code, c["filename"], c["start"], c["length"])
            txt = (data if isinstance(data, str) else data.decode("gbk", "ignore")).replace("\x00", "")
            for name, desc in parse_concepts(txt):
                rows.append({"code": code, "concept": name, "desc": desc})
        except Exception as exc:
            fails.append((code, type(exc).__name__))
            if len(fails) % 50 == 0:
                api.disconnect()
                api, _ = connect()
        if i % 500 == 0:
            el = time.time() - t0
            print(f"  {i:,}/{len(codes):,}  {el:.0f}s  预计剩余 {el/i*(len(codes)-i)/60:.1f} 分钟")
    api.disconnect()

    df = pd.DataFrame(rows).drop_duplicates(subset=["code", "concept"])
    df.to_parquet(f"{BASE}/f10_concepts.parquet", index=False)
    manifest = {
        "schema": "tdx_f10_concepts.v1",
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "host": f"{host[0]}:{host[1]}",
        "stocks_attempted": len(codes),
        "stocks_with_concepts": int(df.code.nunique()),
        "rows": int(len(df)),
        "concepts": int(df.concept.nunique()),
        "failures": len(fails),
        "elapsed_seconds": round(time.time() - t0, 1),
        "note": "F10 概念板块按股查询，无 400 只上限；描述文本含公告日期，可用于判断题材新旧。",
    }
    with open(f"{BASE}/f10_concept_manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)

    print(f"\n完成：{df.code.nunique():,} 只、{df.concept.nunique()} 个概念、{len(df):,} 条")
    print(f"失败 {len(fails)} 只，耗时 {(time.time()-t0)/60:.1f} 分钟")
    jd = df[df.code == "002865"]
    print(f"钧达 {len(jd)} 个概念: {jd.concept.tolist()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
