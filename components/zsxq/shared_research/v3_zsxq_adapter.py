# -*- coding: utf-8 -*-
from __future__ import annotations
from .report_subjects import report_title_evidence, bind_report_attachments

import argparse, html, json, os, re, subprocess, sys, time, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any
from urllib.parse import unquote

CST=timezone(timedelta(hours=8))
ASSISTANT_ROOT=Path(os.environ.get("V3_SHARED_RESEARCH_ROOT") or Path(__file__).resolve().parents[1])
PYTHON_EXE=Path(sys.executable)
GROUP_ID="15555851111822"
ZSXQ_CLI=Path(os.environ.get("V3_SHARED_ZSXQ_CLI") or "zsxq-cli")
ZSXQ_WORK=Path(os.environ.get("V3_SHARED_RESEARCH_STATE") or (ASSISTANT_ROOT/"state"))
GROUPS=[
    {"group_id":"15555851111822","name":"小牛研报纪要"},
    {"group_id":"51111814525844","name":"乐晴行业观察"},
]
COOKIE_FILE=ZSXQ_WORK/"secrets"/"zsxq.cookie"
REPORTS_DIR=ZSXQ_WORK/"content"/"zsxq"/"reports"
LATEST_ZSXQ_REPORT=REPORTS_DIR/"latest_zsxq_report.txt"
CURSOR_FILE=ZSXQ_WORK/"state"/"last_fetch.json"
STOCK_DISPLAY_RE=re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,24}\(\d{6}\.(?:SH|SZ|BJ|HK)\)")

def nowc(): return datetime.now(CST)
def wtxt(p:Path,s:str): p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+".tmp"); t.write_text(s,encoding="utf-8"); t.replace(p)
def wjson(p:Path,o:Any): wtxt(p,json.dumps(o,ensure_ascii=False,indent=2))
def rtxt(p:Path,n=2000000):
    try: b=p.read_bytes()
    except Exception: return ""
    for e in ("utf-8-sig","utf-8","gb18030","gbk"):
        try: return b.decode(e,errors="replace")[:n]
        except Exception: pass
    return b.decode(errors="replace")[:n]
def jlog(p:Path,o:dict):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("a",encoding="utf-8") as f: f.write(json.dumps(o,ensure_ascii=False)+"\n")
def sha_file(p:Path):
    try:
        h=hashlib.sha256()
        with p.open("rb") as f:
            for b in iter(lambda:f.read(1048576),b""): h.update(b)
        return h.hexdigest()
    except Exception: return ""
def file_meta(p:Path):
    return {"exists":p.exists(),"path":str(p),"size":p.stat().st_size if p.exists() and p.is_file() else None,"mtime":datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") if p.exists() else None,"sha256":sha_file(p)}
def read_cursor_snapshot():
    try: return CURSOR_FILE.read_bytes() if CURSOR_FILE.exists() else None
    except Exception: return None
def restore_cursor_snapshot(snapshot):
    try:
        if snapshot is None:
            if CURSOR_FILE.exists(): CURSOR_FILE.unlink()
        else:
            CURSOR_FILE.parent.mkdir(parents=True,exist_ok=True); CURSOR_FILE.write_bytes(snapshot)
    except Exception: pass
def status_update(kind:str,data:dict):
    p=ZSXQ_WORK/"content"/"zsxq"/"cron_status.json"; old={}
    if p.exists():
        try: old=json.loads(p.read_text(encoding="utf-8"))
        except Exception: old={}
    old.setdefault("fixed_v24_refetch",{}); old["fixed_v24_refetch"][kind]=data; old["updated_at"]=nowc().isoformat(); wjson(p,old)
def _decode_process_output(value):
    if value is None:
        return ""
    if isinstance(value,bytes):
        return value.decode("utf-8",errors="replace").strip()
    return str(value).strip()

def push_text(content:str,timeout=90):
    """The shared Mac collector is permanently research-only/no-push."""
    return {"ok":None,"skipped":True,"reason":"SHARED_RESEARCH_PUSH_DISABLED"}

SEC_RE=re.compile(r"(?m)^([一二三四五六七八九十]+)、([^\n\r]+)\s*$")
THEMES=[
    ("AI算力/AIDC/数据中心/服务器","AI AIDC 算力 智算 云厂商 云服务 云资本开支 CAPEX CSP 数据中心 IDC 服务器 机柜 整机柜 超节点 液冷 冷板 CDU 冷却塔 柴发 燃气发电 备电 UPS 电源 模组 交换机 交换芯片 InfiniBand 以太网 英伟达 NVIDIA GB200 GB300 H100 H200 B200 B300 Meta Google AWS Azure 字节 豆包 阿里 腾讯 百度 盛视 豫能 合盈 秦淮数据 科华数据 数据港 奥飞数据 润泽科技 光环新网".split()),
    ("光通信/CPO/光模块/光纤海缆","光通信 光模块 光器件 光芯片 光引擎 CPO LPO AOC DAC 800G 1.6T 400G 硅光 EML CWDM AWG 光纤 光缆 海缆 海底电缆 通信 光电 亨通 中天 烽火 长飞 永鼎 通鼎 新易盛 中际旭创 天孚通信 剑桥科技 华工科技 源杰科技 太辰光 博创科技 光迅科技".split()),
    ("PCB/铜箔/CCL/电子材料","PCB HDI 载板 ABF CCL 覆铜板 铜箔 HVLP RTF M9 HPCL DTH 玻纤 玻璃纤维 电子布 电子纱 方邦 德福 泰金 海亮 生益科技 胜宏科技 沪电股份 深南电路 景旺电子 鹏鼎控股 超声电子 国际复材 中国巨石 宏和科技 金安国纪 南亚新材 建滔".split()),
    ("半导体设备/材料/先进封装","半导体 晶圆 晶圆厂 设备 刻蚀 薄膜 CVD PVD ALD 量测 检测 清洗 CMP 离子注入 光刻胶 掩膜版 Blank Mask ArF KrF EUV 前驱体 靶材 特气 先进封装 封测 Chiplet 2.5D 3D TSV CoWoS 北方华创 中微公司 拓荆科技 精测电子 中科飞测 华海清科 盛美上海 芯源微 聚和材料 雅克科技 江丰电子 鼎龙股份 安集科技 沪硅产业 清溢光电 路维光电".split()),
    ("存储/DRAM/NAND/HBM/AI存储","存储 DRAM NAND NOR Flash HBM HBM3 HBM4 DDR SSD HDD HAMR 玻璃盘 硬盘 模组 模块 美光 三星 海力士 希捷 西部数据 兆易创新 普冉股份 北京君正 江波龙 德明利 佰维存储 澜起科技 聚辰股份 水晶光电 香农芯创 东芯股份".split()),
    ("电力设备/电网/储能/算电协同","电力 电网 电改 电力设备 特高压 配网 配电 变压器 电表 电网投资 智能电网 虚拟电厂 储能 大储 户储 逆变器 PCS BMS EMS 温控 电芯 电池 新型储能 算电协同 绿电 风电 光伏 核电 火电 燃机 燃气轮机 宁德时代 阳光电源 上能电气 固德威 锦浪科技 科华数据 南网科技 国电南瑞 思源电气 平高电气 许继电气 金盘科技 三星电气 东方电气 上海电气 明阳智能 金风科技".split()),
    ("新能源车/智能驾驶/固态电池","新能源车 汽车 整车 车企 乘用车 商用车 智能驾驶 自动驾驶 NOA L2 L3 激光雷达 毫米波雷达 域控 座舱 线控底盘 空悬 Robotaxi 电池 固态电池 半固态 磷酸铁锂 三元 锂电 隔膜 电解液 正极 负极 比亚迪 宁德时代 亿纬锂能 国轩高科 欣旺达 德赛西威 均胜电子 拓普集团 继峰股份 赛力斯 长安汽车".split()),
    ("华为链/卫星通信/空天地一体化","华为 鸿蒙 昇腾 鲲鹏 欧拉 盘古 Mate Pura 车BU 问界 智界 享界 尊界 卫星通信 卫星互联网 低轨 通感一体 空天地 NTN 6G 5G 大唐 信科移动 烽火通信 复旦微电 国博电子 信维通信 北斗 星网 航天宏图 海格通信 华力创通 震有科技 铖昌科技".split()),
    ("机器人/具身智能/脑机接口","机器人 Humanoid 人形机器人 具身智能 灵巧手 丝杠 导轨 减速器 谐波减速器 RV减速器 伺服 电机 控制器 传感器 力矩传感器 关节 模组 机器视觉 脑机接口 BCI Neuralink 微创 植入 运动控制 埃斯顿 汇川技术 绿的谐波 鸣志电器 柯力传感 五洲新春 北特科技 拓普集团".split()),
    ("军工/航空航天/低空经济","军工 航空 航天 航发 两机 大飞机 商飞 C919 C929 无人机 低空经济 eVTOL 飞行汽车 导弹 雷达 卫星 火箭 商业航天 航材 锻件 钛合金 高温合金 复材 碳纤维 航亚 航宇 派克 应流 万泽 图南 西部超导 中航高科 中航沈飞 中航西飞 航发动力 航发控制".split()),
    ("有色金属/黄金/稀土/大宗","有色 铜 铝 锌 镍 锡 钨 钼 锂 钴 稀土 黄金 白银 贵金属 工业金属 矿 铜矿 金矿 铝土矿 氧化铝 电解铝 碳酸锂 锂矿 盐湖 紫金矿业 洛阳钼业 赤峰黄金 银泰黄金 山东黄金 中金黄金 北方稀土 中国稀土 天齐锂业 赣锋锂业 华友钴业".split()),
    ("油气/煤炭/化工/航运","油价 原油 WTI Brent 布伦特 OPEC 伊朗 霍尔木兹 天然气 LNG 油运 航运 VLCC 煤炭 煤化工 焦煤 焦炭 化工 尿素 甲醇 PTA PX 纯碱 烧碱 轮胎 油服 中海油 中石油 中石化 中煤能源 中国神华 陕西煤业 招商轮船 中远海能 华鲁恒升".split()),
    ("消费/食品饮料/零售出海","消费 食品 饮料 白酒 啤酒 乳制品 调味品 速冻 食品饮料 餐饮 零售 出海 跨境电商 品牌 GMV TP DP 美妆 珠宝 服装 运动 家居 三全食品 伊利股份 贵州茅台 五粮液 泸州老窖 安井食品 百秋网络 名创优品 泡泡玛特".split()),
    ("医药/创新药/医疗器械","医药 创新药 CXO ADC GLP-1 TTR 肿瘤 疫苗 医疗器械 IVD 耗材 手套 医美 中药 生物药 Alnylam AMVUTTRA ONPATTRO 恒瑞医药 药明康德 迈瑞医疗 英科医疗 爱尔眼科 通策医疗 云南白药".split()),
    ("金融/地产/REITs/红利资产","银行 券商 保险 金融 红利 股息 分红 高股息 地产 REITs 物流 园区 租金 物业 存款 社融 息差 交通银行 招商银行 工商银行 中金公司 中信证券 中国平安 保利发展 万科A 华夏基金".split()),
    ("传媒/游戏/IP/AI应用","传媒 游戏 短剧 影视 出版 IP AIGC AI应用 Agent 智能体 多模态 大模型 应用 软件 SaaS 教育 办公 营销 广告 顺网科技 昆仑万维 三七互娱 恺英网络 掌趣科技 万兴科技 金山办公 科大讯飞".split()),
    ("机械设备/机床/工业母机","机械 设备 机床 工业母机 数控 刀具 丝杠 导轨 轴承 液压 机器人设备 自动化 注塑 压铸 纽威数控 海天精工 科德数控 秦川机床 创世纪 华中数控".split()),
    ("家电/消费电子/面板","家电 消费电子 面板 OLED LCD MiniLED MicroLED 电视 白电 黑电 手机 终端 显示 玻璃 基板 TCL科技 京东方A 海信视像 四川长虹 创维集团 立讯精密 歌尔股份 蓝思科技".split()),
    ("其他待复核线索","其他 待复核 线索 综合 未归类 图片 传闻 目标市值 估算 需核实 单方测算".split()),
]

def run_refetch(timeout:int,out:Path,log:Path):
    before=file_meta(LATEST_ZSXQ_REPORT); wjson(out/"zsxq_before_refetch_meta.json",before)
    cmd=[str(PYTHON_EXE),str(ASSISTANT_ROOT/"scripts"/"cron_hourly.py"),"--no-push"]
    env=os.environ.copy(); env.update({"PYTHONIOENCODING":"utf-8","ASSISTANT_DISABLE_FEISHU_PUSH":"1","ASSISTANT_NO_FEISHU_PUSH":"1","NO_PUSH":"1","SKIP_FEISHU":"1","MANUAL_ZSXQ_REFETCH_ONLY":"1","ZSXQ_RENDER_SKIP_FINANCE":"1","ASSISTANT_DISABLE_MINIMAX":"1","ZSXQ_DISABLE_MINIMAX":"1","MINIMAX_DISABLED":"1"})
    jlog(log,{"event":"refetch_start","cmd":cmd,"timeout":timeout,"before":before,"ts":nowc().isoformat()})
    st=time.perf_counter()
    try:
        p=subprocess.run(cmd,cwd=str(ASSISTANT_ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",timeout=timeout,env=env)
        stdout=p.stdout or ""; stderr=p.stderr or ""; returncode=p.returncode; timed_out=False
    except subprocess.TimeoutExpired as e:
        def _text(v):
            if v is None: return ""
            if isinstance(v,bytes): return v.decode("utf-8",errors="replace")
            return str(v)
        stdout=_text(e.stdout); stderr=_text(e.stderr) or f"refetch timeout after {timeout}s"; returncode=124; timed_out=True
    res={"cmd":cmd,"returncode":returncode,"timed_out":timed_out,"elapsed_seconds":round(time.perf_counter()-st,3),"stdout":stdout[:12000],"stderr":stderr[:8000]}
    wjson(out/"zsxq_refetch_result.json",res); (out/"zsxq_refetch_stdout.txt").write_text(stdout,encoding="utf-8",errors="replace"); (out/"zsxq_refetch_stderr.txt").write_text(stderr,encoding="utf-8",errors="replace")
    after=file_meta(LATEST_ZSXQ_REPORT); wjson(out/"zsxq_after_refetch_meta.json",after)
    comp={"before":before,"after":after,"hash_changed":before.get("sha256")!=after.get("sha256"),"mtime_changed":before.get("mtime")!=after.get("mtime"),"size_changed":before.get("size")!=after.get("size"),"returncode":returncode,"timed_out":timed_out}
    wjson(out/"zsxq_refetch_compare.json",comp); jlog(log,{"event":"refetch_done","compare":comp,"ts":nowc().isoformat()})
    return comp,res

def split(text):
    lines=text.replace("\r\n","\n").replace("\r","\n").split("\n"); head=[]; sec={}; cur=None; buf=[]
    for line in lines:
        m=SEC_RE.match(line)
        if m:
            if cur: sec[cur]="\n".join(buf).strip("\n")
            elif buf: head+=buf
            cur=f"{m.group(1)}、{m.group(2).strip()}"; buf=[]
        else: buf.append(line)
    if cur: sec[cur]="\n".join(buf).strip("\n")
    return head,sec
def get(sec,k):
    for a,b in sec.items():
        if k in a: return b
    return ""
def items(block): return [l.rstrip() for l in block.splitlines() if "触发原因：" in l]
def stock(line):
    m=re.search(r"^[\s　]*[🔴🟡⚪]?\s*([^|（(]+)[（(]([0-9]{6}\.(?:SH|SZ|BJ|HK)|[0-9]{6})[）)]",line.strip())
    if not m:
        return ""
    name=m.group(1).strip()
    if name in AMBIGUOUS_STOCK_NAMES:
        return ""
    if name in WEAK_COMPANY_NAMES and WEAK_CONTEXT_RE.search(line):
        return ""
    return f"{name}({m.group(2).strip()})"
def theme(line):
    low=line.lower()
    if any(k in line for k in ["恒锋工具","机床","刀具","拉刀","齿轮刀","工业母机"]):
        return "机械设备/机床/工业母机"
    for name,kws in THEMES:
        if any(k.lower() in low for k in kws): return name
    return "其他待复核线索"
def infer(rows):
    b={}
    for r in rows:
        t=theme(r); x=b.setdefault(t,{"theme":t,"count":0,"stocks":[],"keywords":[]}); x["count"]+=1
        s=stock(r)
        if s and s not in x["stocks"]: x["stocks"].append(s)
        for name,kws in THEMES:
            if name==t:
                for k in kws:
                    if k.lower() in r.lower() and k not in x["keywords"]: x["keywords"].append(k)
    return sorted(b.values(),key=lambda x:(-x["count"],x["theme"]=="其他待复核线索",x["theme"]))
def render_themes(ts):
    if not ts: return "  - 本小时暂无可归纳主线；保留原始线索待人工复核。"
    return "\n".join([f"  {i}. 【{t['theme']}】证据条数：{t['count']}；代表标的：{'、'.join(t['stocks'][:8]) or '无明确标的'}；依据关键词：{'、'.join(t['keywords'][:6]) or '待复核'}" for i,t in enumerate(ts[:6],1)])

def _unique_text(items: list[str]) -> list[str]:
    out=[]
    for item in items:
        item=str(item or "").strip()
        if item and item not in out:
            out.append(item)
    return out

def _standard_stock_pool(ts: list[dict[str,Any]], rows: list[str]) -> list[str]:
    pool=[]
    for t in ts[:6]:
        for s in t.get("stocks",[])[:6]:
            pool.append(s)
    if not pool:
        for row in rows:
            s=stock(row)
            if s:
                pool.append(s)
    return _unique_text(pool)[:12]

def reformat(raw):
    head,sec=split(raw); title=next((x.strip() for x in head if "【ZSXQ" in x),f"【ZSXQ 小时报告】{nowc().strftime('%Y-%m-%d-%H')}")
    summary=get(sec,"本小时新增摘要"); core=get(sec,"核心标的"); clue=get(sec,"线索标的"); obs=get(sec,"观察池"); mapping=get(sec,"港股通")
    rows=items(core)+items(clue)+items(obs); ts=infer(rows); top=ts[0]["theme"] if ts else "待人工复核线索"
    sm="\n".join([x.rstrip() for x in summary.splitlines() if x.strip()]) if summary else "  本小时摘要缺失；保留原报告标的线索，待人工复核。"
    pool=_standard_stock_pool(ts,rows)
    pool_text="、".join(pool) if pool else "本小时暂无明确股票池"
    out=[
        title,
        "================================================",
        "",
        "一、总览：可能利好/重点复核标的",
        sm,
        f"  当前最强主线：{top}",
        f"  可能利好/重点复核股票池：{pool_text}",
        "  说明：以下标的只作为复核入口，不代表确定性结论。",
        "",
        "二、主线方向",
        render_themes(ts),
        "",
        "三、详细依据",
        "【核心标的】",
        core.strip() or "  - 本小时暂无核心标的。",
        "",
        "【线索标的】",
        clue.strip() or "  - 本小时暂无线索标的。",
        "",
        "【观察池/待复核线索】",
        obs.strip() or "  - 本小时暂无观察池线索。",
        "",
        "【港股通/A股映射】",
        mapping.strip() or "  - 本小时暂无明确映射。",
        "",
        "四、复核要点",
        "  核心标的需结合量价状态、公告/研报原文和 overextended_flag 复核，不追高。",
        "  线索标的与观察池标的只作为复核入口，不作为确定性结论。",
        "  本版只做结构重排与主线归纳，未删除原报告中的标的行。",
        "",
        "五、数据来源与免责声明",
        "  来源：ZSXQ pipeline 最新小时报告重排。",
        "  原始底稿：zsxq_work/content/zsxq/reports/latest_zsxq_report.txt。",
        "  免责声明：仅为资讯整理和复核线索，不构成投资建议。",
    ]
    return "\n".join(out).strip()+"\n", {"top_theme":top,"theme_count":len(ts),"themes":ts}
def _quality_failures(c: str) -> list[str]:
    failures=[]
    if len(c)>7000:
        failures.append(f"too_long:{len(c)}")
    repeated={}
    in_theme_section=False
    for line in c.splitlines():
        stripped=line.strip()
        if stripped.startswith("二、主线方向"):
            in_theme_section=True
        elif stripped.startswith("三、"):
            in_theme_section=False
        if "可能利好/重点复核股票池" in line:
            pool_count=len(STOCK_DISPLAY_RE.findall(line))
            if pool_count>10:
                failures.append(f"stock_pool_too_many:{pool_count}")
        if in_theme_section and stripped.startswith("标的/公司："):
            stocks=STOCK_DISPLAY_RE.findall(line)
            if len(stocks)>8:
                failures.append(f"theme_company_line_too_many:{len(stocks)}")
            for stock_name in stocks:
                repeated[stock_name]=repeated.get(stock_name,0)+1
    cross=[name for name,count in repeated.items() if count>=3]
    if cross:
        failures.append("stock_repeated_across_themes:"+",".join(cross[:8]))
    return failures

def validate(c):
    req=["一、总览：可能利好/重点复核标的","二、主线方向","三、详细依据","四、复核要点","五、数据来源","免责声明"]
    recent_req=["一、总览：可能利好/重点复核标的","二、主线方向","三、详细依据","四、复核要点","五、数据来源与剔除说明","免责声明"]
    standard_missing=[f"missing:{r}" for r in req if r not in c]
    recent_missing=[f"missing:{r}" for r in recent_req if r not in c]
    prob=[] if len(recent_missing)<len(standard_missing) and not recent_missing else standard_missing
    if "综合线索" in c: prob.append("generic_mainline")
    prob.extend(_quality_failures(c))
    return not prob,prob
def content_has_effective_zsxq(raw,meta):
    text=raw.replace("\r\n","\n").replace("\r","\n")
    stock_like_count=len(set(re.findall(r"\d{6}\.(?:SH|SZ|BJ|HK)|\d{6}",text)))
    inferred_theme_count=int(meta.get("theme_count") or 0)
    lower=text.lower()
    if stock_like_count<3 and inferred_theme_count<2:
        return False,"low_value_too_few_stocks_or_themes"
    if stock_like_count<=1 and ".pdf" in lower:
        return False,"single_pdf_filename_candidate"
    stock_m=re.search(r"有效股票数[：:]\s*(\d+)",text)
    theme_m=re.search(r"主线数量[：:]\s*(\d+)",text)
    if stock_m and int(stock_m.group(1))<=0: return False,"effective_stock_count_zero"
    if theme_m and int(theme_m.group(1))<=0 and int(meta.get("theme_count") or 0)<=0: return False,"theme_count_zero"
    if int(meta.get("theme_count") or 0)<=0: return False,"no_inferred_theme"
    return True,"ok"

CODE_RE=re.compile(r"(?<!\d)((?:000|001|002|003|300|301|600|601|603|605|688)\d{3})(?!\d)")
AMBIGUOUS_STOCK_NAMES={"机器人"}
WEAK_COMPANY_NAMES={"宏发股份"}
STOP_COMPANY_NAMES={
    "资金流向","风险提示","石油","消费","风险","组合","访华时长","主要活动","简答来说",
    "复盘","现状","短期","中期","长期","核心逻辑","事件","目标市值","基本面","逻辑",
    "本质","北京光华路","炒股养家",
}
WEAK_CONTEXT_RE=re.compile(r"(外资持股|持股比例|公开数据显示|市场综述|资金流向|投资者追捧|例如)")
BROKER_PREFIX_NAMES={
    "长江电子","华安电子","华福大制造","梅森投研","华创机械","浙商科创",
    "申万宏源电子","东方电子","广发交运","高盛中国市场综述","交易台",
    "国泰海通","国金电新","中金医药","中泰传媒互联网","财通商社","天风通信",
    "国联民生","国盛海外",
}
TRADING_SEAT_RE=re.compile(r"(龙虎榜|机构买入|机构卖出|买入.+卖出|卖出.+买入|炒股养家|北京光华路)")
NOISE_TAGS={"#文字观点#","#财联社#","#市场段子#"}

def _clean_zsxq_text(value: Any) -> str:
    text=str(value or "")
    def _tag_title(m):
        title=html.unescape(unquote(m.group(1) or "")).strip()
        return "" if title in NOISE_TAGS else title
    text=re.sub(r'<e\b[^>]*\btitle="([^"]*)"[^>]*/?>',_tag_title,text)
    text=re.sub(r"<br\s*/?>","\n",text)
    text=re.sub(r"<[^>]+>","",text)
    text=html.unescape(text).replace("\r\n","\n").replace("\r","\n")
    for tag in NOISE_TAGS:
        text=text.replace(tag,"")
    text=re.sub(r"[ \t]+\n","\n",text)
    text=re.sub(r"\n{3,}","\n\n",text)
    return text.strip()

def _topic_title(clean_text: str, fallback: str="") -> str:
    text=clean_text.strip() or _clean_zsxq_text(fallback)
    first=next((x.strip() for x in text.splitlines() if x.strip()),"未命名主题")
    first=re.sub(r"^[\[\]【】礼物太阳發发]+","",first).strip()
    return first[:56]

def _code_to_ts(code: str) -> str:
    raw=str(code or "").strip().upper()
    if re.fullmatch(r"\d{6}\.(SH|SZ|BJ)",raw):
        return raw
    if not re.fullmatch(r"\d{6}",raw):
        return raw
    if raw.startswith(("600","601","603","605","688","689")):
        return f"{raw}.SH"
    if raw.startswith(("000","001","002","003","300","301")):
        return f"{raw}.SZ"
    if raw.startswith(("43","83","87","92")):
        return f"{raw}.BJ"
    return raw

def _add_company(out: list[dict[str,str]], seen: set[str], name: str, code: str="", source: str="name") -> None:
    name=re.sub(r"[\s,，;；/]+$","",str(name or "").strip())
    name=re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])","",name)
    if not name or len(name)<2:
        return
    if name in STOP_COMPANY_NAMES:
        return
    if not re.search(r"[\u4e00-\u9fff]",name):
        return
    if re.search(r"\d|月|日|收盘|解读|更新|数据|交易台|团队|观点|主题|方向|板块|行业|客户|供应商",name):
        return
    if name in BROKER_PREFIX_NAMES and source not in {"explicit_code", "title_explicit_code"}:
        return
    if name in AMBIGUOUS_STOCK_NAMES and source not in {"explicit_code","code"}:
        return
    code=_code_to_ts(code)
    for old in out:
        if old.get("name")==name and (not code or not old.get("code") or old.get("code")==code):
            if code and not old.get("code"):
                old["code"]=code
                old["source"]=source
            return
        if code and old.get("code")==code:
            return
    key=f"{name}|{code}"
    if key in seen:
        return
    seen.add(key)
    out.append({"name":name,"code":code,"source":source})

def _load_stock_lookup() -> tuple[dict[str,dict[str,Any]],dict[str,str],str,dict[str,Any]]:
    try:
        import pyarrow.dataset as ds
        panel=Path(os.environ["V3_SHARED_SELECTOR_PANEL"])
        if not panel.is_file():
            raise FileNotFoundError(panel)
        dataset=ds.dataset(panel,format="parquet")
        table=dataset.to_table(columns=["trade_date","ts_code","name"])
        dates=[str(value or "").replace("-","")[:8] for value in table.column("trade_date").to_pylist()]
        latest=max((value for value in dates if re.fullmatch(r"\d{8}",value)),default="")
        master: dict[str,dict[str,Any]]={}
        names: dict[str,str]={}
        for row_date,raw_ts_code,raw_name in zip(dates,table.column("ts_code").to_pylist(),table.column("name").to_pylist()):
            if row_date!=latest:
                continue
            ts_code=str(raw_ts_code or "").strip().upper()
            code=ts_code.split(".")[0]
            name=str(raw_name or "").strip()
            if not re.fullmatch(r"\d{6}\.(SH|SZ|BJ)",ts_code) or len(name)<2:
                continue
            master.setdefault(code,{"symbol":code,"code":code,"ts_code":ts_code,"name":name,"market":"A"})
            names.setdefault(re.sub(r"\s+","",name).upper(),code)
        health={"ok":len(master)>=1000,"source":"mac_selector_panel_latest_date","selector_date":latest,"master_count":len(master),"name_count":len(names)}
        if not health["ok"]:
            raise ValueError(f"selector security master too small: {len(master)}")
        return master,names,"",health
    except Exception as e:
        return {},{},str(e)[:300],{"ok":False,"errors":[str(e)[:300]],"master_count":0,"name_count":0}

def _filter_weak_companies(text: str, companies: list[dict[str,str]]) -> list[dict[str,str]]:
    if not companies:
        return []
    out=[]
    weak_context=bool(WEAK_CONTEXT_RE.search(text))
    for c in companies:
        name=str(c.get("name") or "")
        source=str(c.get("source") or "")
        if name in WEAK_COMPANY_NAMES and weak_context and source not in {"explicit_code","code"}:
            continue
        out.append(c)
    return out

def _extract_companies(text: str, master: dict[str,dict[str,Any]], names: dict[str,str]) -> list[dict[str,str]]:
    out: list[dict[str,str]]=[]
    seen: set[str]=set()
    for m in re.finditer(r"([\u4e00-\u9fffA-Za-z]{2,12})[（(]\s*((?:000|001|002|003|300|301|600|601|603|605|688)\d{3})\s*[）)]",text):
        code=m.group(2)
        info=master.get(code) or {}
        _add_company(out,seen,str(info.get("name") or m.group(1)),str(info.get("ts_code") or _code_to_ts(code)),"explicit_code")
    for code in CODE_RE.findall(text):
        info=master.get(code) or {}
        _add_company(out,seen,str(info.get("name") or code),str(info.get("ts_code") or _code_to_ts(code)),"code")
    if names:
        normalized_text=re.sub(r"\s+","",text).upper()
        matches=0
        for full_name,code in sorted(names.items(),key=lambda item:len(item[0]),reverse=True):
            if len(full_name)<3 or full_name not in normalized_text:
                continue
            info=master.get(code) or {}
            _add_company(out,seen,str(info.get("name") or full_name),str(info.get("ts_code") or _code_to_ts(code)),"stock_master")
            matches+=1
            if matches>=24:
                break
    for section in re.findall(r"(?:组合|相关供应商|供应商|联系人|标的|公司)[:：]([^\n。；]+)",text):
        for part in re.split(r"[、,/，;；\s]+",section):
            part=re.sub(r"^[【\[]|[】\]]$","",part.strip())
            if 2<=len(part)<=8 and not re.search(r"\d|客户|团队|联系|销售|方向|其他",part):
                _add_company(out,seen,part,"","phrase")
    for name in re.findall(r"(?:】|\])\s*([\u4e00-\u9fffA-Za-z]{2,8})[:：]",text):
        _add_company(out,seen,name,"","phrase")
    for bracket in re.findall(r"【([^】]{2,18})】",text):
        candidate=re.split(r"[:：\s&]",bracket.strip())[0]
        if candidate in BROKER_PREFIX_NAMES:
            continue
        norm=re.sub(r"\s+","",candidate).upper()
        code=names.get(norm,"") if names else ""
        if code:
            info=master.get(code) or {}
            _add_company(out,seen,str(info.get("name") or candidate),str(info.get("ts_code") or _code_to_ts(code)),"bracket")
    # Explicit A/H title tokens are retained as textual identities, not inferred
    # from an A-only master. Keep the conflicting old entity separately.
    for subject in [s for line in text.splitlines() for s in report_title_evidence(line)["subjects"]]:
        canonical = subject["code"]
        code = canonical[2:] if canonical.startswith("A.") else canonical
        _add_company(out, seen, subject["name"], code, "title_explicit_code")
    return _filter_weak_companies(text,out)[:18]

def _topic_theme_hits(text: str) -> list[dict[str,Any]]:
    lower=text.lower()
    hits=[]
    mechanical_context=any(k in text for k in ["恒锋工具","机床","刀具","拉刀","齿轮刀","工业母机"])
    ai_hard={"AIDC","算力","智算","云厂商","云服务","数据中心","IDC","服务器","交换机","交换芯片","以太网","英伟达","NVIDIA","GPU","HBM","CPO","光模块","电源","液冷","备电","Google","AWS","Azure"}
    pcb_hard={"PCB","HDI","载板","ABF","CCL","覆铜板","铜箔","电子布","电子纱","生益科技","南亚新材","沪电股份","深南电路","胜宏科技"}
    display_hard={"OLED","LCD","MiniLED","MicroLED","面板","电视","手机","终端","玻璃","基板","TCL科技","京东方A","海信视像"}
    for name,kws in THEMES:
        if name=="其他待复核线索":
            continue
        if name=="电力设备/电网/储能/算电协同" and mechanical_context:
            if not any(k in text for k in ["电网","储能","逆变器","电力设备","算电协同"]):
                continue
        found=[]
        for kw in kws:
            if kw.lower() in lower and kw not in found:
                found.append(kw)
        if found:
            if name=="AI算力/AIDC/数据中心/服务器" and not any(k in found for k in ai_hard):
                continue
            if name=="PCB/铜箔/CCL/电子材料" and not any(k in found for k in pcb_hard):
                continue
            if name=="家电/消费电子/面板" and not any(k in found for k in display_hard):
                continue
            score=len(found)
            if name=="机械设备/机床/工业母机" and mechanical_context:
                score+=6
            hits.append({"theme":name,"keywords":found[:8],"score":score})
    hits.sort(key=lambda x:(-int(x["score"]),x["theme"]))
    return hits[:4]

def _evidence_snippet(text: str, themes: list[dict[str,Any]], companies: list[dict[str,str]]) -> str:
    keys=[c["name"] for c in companies[:6]]
    for t in themes[:3]:
        keys.extend([str(x) for x in t.get("keywords",[])[:4]])
    sents=[s.strip() for s in re.split(r"[。；\n]",text) if s.strip()]
    for sent in sents:
        if any(k and k in sent for k in keys):
            return sent[:150]
    return (sents[0] if sents else text.strip())[:150]

def _company_text(companies: list[dict[str,str]]) -> str:
    if not companies:
        return "主题性观点，无明确公司"
    parts=[]
    for c in companies[:4]:
        code=str(c.get("code") or "")
        parts.append(f"{c['name']}({code})" if code else c["name"])
    return "、".join(parts)+(" 等" if len(companies)>4 else "")

def _display_company(c: dict[str,str]) -> str:
    name=str(c.get("name") or "")
    code=str(c.get("code") or "")
    return f"{name}({code})" if code else name

def _theme_bound_companies(row: dict[str,Any], theme: dict[str,Any]) -> list[dict[str,str]]:
    title=str(row.get("title") or "")
    evidence=str(row.get("evidence") or "")
    content_head=str(row.get("content_head") or "")
    text=f"{title}\n{evidence}\n{content_head}"
    keywords=[str(k) for k in theme.get("keywords",[]) if str(k)]
    theme_hit=any(k in text for k in keywords[:8])
    segments=[s.strip() for s in re.split(r"[。；;\n]",text) if s.strip()]
    bound=[]
    for c in row.get("companies") or []:
        name=str(c.get("name") or "")
        code=str(c.get("code") or "")
        code6=code.split(".")[0] if code else ""
        if name and any(
            (name in seg or (code6 and code6 in seg)) and any(k in seg for k in keywords[:8])
            for seg in segments
        ):
            bound.append(c)
    if bound:
        return bound[:4]
    companies=row.get("companies") or []
    if theme_hit and len(companies)<=2:
        return companies[:2]
    return []

def _recent_stock_pool(analysis: dict[str,Any]) -> list[str]:
    pool=[]
    for t in (analysis.get("themes") or [])[:4]:
        pool.extend((t.get("companies") or [])[:4])
    if not pool:
        for row in (analysis.get("effective_topics") or [])[:5]:
            companies=row.get("companies") or []
            if len(companies)<=3:
                pool.extend(_display_company(c) for c in companies[:3])
    return _unique_text([p for p in pool if p])[:8]

def _append_company_display(items: list[str], display: str) -> None:
    base=re.sub(r"[（(]\d{6}\.(?:SH|SZ|BJ)[）)]","",display)
    for i,old in enumerate(items):
        old_base=re.sub(r"[（(]\d{6}\.(?:SH|SZ|BJ)[）)]","",old)
        if old_base==base:
            if "(" in display and "(" not in old:
                items[i]=display
            return
    items.append(display)

def _ps_single_quote(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"

def _recent_topics_commands(limit: int) -> list[tuple[str,list[str]]]:
    args=["group","+topics","--group-id",GROUP_ID,"--limit",str(limit),"--json"]
    return [("official_oauth_cli",[str(ZSXQ_CLI),*args])]

def _load_cookie_text() -> str:
    return ""

def _api_topic_to_brief(raw: dict[str,Any], group: dict[str,str]) -> dict[str,Any]:
    talk=raw.get("talk") or {}
    owner=talk.get("owner") if isinstance(talk,dict) else {}
    content=talk.get("text") or raw.get("text") or raw.get("content") or ""
    title=re.sub(r"\s+"," ",_clean_zsxq_text(content)).strip()[:80]
    return {
        "topic_id":str(raw.get("topic_id") or raw.get("id") or ""),
        "type":str(raw.get("type") or "talk"),
        "create_time":str(raw.get("create_time") or ""),
        "title":title,
        "content":content,
        "group":{"group_id":group["group_id"],"name":group.get("name") or ""},
        "owner":{
            "user_id":str((owner or {}).get("user_id") or ""),
            "name":str((owner or {}).get("name") or ""),
            "alias":str((owner or {}).get("alias") or ""),
        },
        "counts":raw.get("statistics") or raw.get("counts") or {},
    }

def _fetch_recent_topics_cookie(out: Path, limit: int=20) -> tuple[dict[str,Any] | None, dict[str,Any]]:
    return None,{"ok":False,"mode":"cookie_api_disabled","error":"OFFICIAL_OAUTH_CLI_ONLY","attempts":[]}

def fetch_recent_topics(out: Path, limit: int=20) -> tuple[dict[str,Any] | None, dict[str,Any]]:
    cookie_data,cookie_result=_fetch_recent_topics_cookie(out,limit)
    if cookie_data:
        return cookie_data,cookie_result
    attempts=[]
    for mode,cmd in _recent_topics_commands(limit):
        st=time.perf_counter()
        try:
            p=subprocess.run(cmd,cwd=str(ASSISTANT_ROOT),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding="utf-8",errors="replace",timeout=75)
            attempt={"mode":mode,"ok":p.returncode==0,"returncode":p.returncode,"elapsed_seconds":round(time.perf_counter()-st,3),"stdout":(p.stdout or "")[:4000],"stderr":(p.stderr or "")[:4000],"cmd":cmd}
            attempts.append(attempt)
            if p.returncode!=0:
                continue
            try:
                data=json.loads((p.stdout or "").lstrip("\ufeff"))
            except Exception as e:
                attempt["json_error"]=str(e)[:300]
                continue
            wjson(out/"zsxq_recent_topics.json",data)
            result={"ok":True,"mode":mode,"returncode":p.returncode,"elapsed_seconds":attempt["elapsed_seconds"],"cmd":cmd,"attempts":attempts,"success":bool(data.get("success") or data.get("ok") or data.get("topics_brief")),"count":len(data.get("topics_brief") or [])}
            wjson(out/"zsxq_recent_topics_fetch_result.json",result)
            return data,result
        except Exception as e:
            attempts.append({"mode":mode,"ok":False,"returncode":None,"elapsed_seconds":round(time.perf_counter()-st,3),"error":str(e)[:500],"cmd":cmd})
    result={"ok":False,"returncode":None,"elapsed_seconds":round(sum(float(a.get("elapsed_seconds") or 0) for a in attempts),3),"error":"all recent topics commands failed","cookie_result":cookie_result,"attempts":attempts}
    wjson(out/"zsxq_recent_topics_fetch_result.json",result)
    return None,result

def _topic_image_url(image: dict[str,Any]) -> str:
    for key in ("original","large","thumbnail"):
        node=image.get(key) if isinstance(image.get(key),dict) else {}
        url=str(node.get("url") or "").strip()
        if url:
            return url
    return ""

def _download_image_for_ocr(url: str, target: Path, timeout: int=90) -> tuple[bool,str]:
    cmd=["curl.exe","-L","--fail","--silent","--show-error","--max-time",str(timeout),"--noproxy","","--ssl-no-revoke"]
    proxy=os.environ.get("ZSXQ_PROXY","http://127.0.0.1:7890").strip()
    if proxy and os.environ.get("ZSXQ_DISABLE_PROXY","").strip()!="1":
        cmd.extend(["-x",proxy])
    cmd.extend(["-o",str(target),url])
    env={k:v for k,v in os.environ.items() if k.lower()!="no_proxy"}; env["NO_PROXY"]=""
    try:
        proc=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout+10,env=env)
    except Exception as exc:
        return False,str(exc)[:500]
    if proc.returncode!=0:
        return False,(proc.stderr or proc.stdout or f"curl_rc={proc.returncode}")[:500]
    return target.exists() and target.stat().st_size>0,""

def generate_image_ocr_cache(out: Path, data: dict[str,Any], max_images_per_topic: int=3) -> dict[str,Any]:
    topics=data.get("topics_brief") or data.get("topics") or []
    image_topics=[topic for topic in topics if isinstance(topic,dict) and isinstance(topic.get("images"),list) and topic.get("images")]
    result={"ok":False,"engine":"easyocr(ch_sim,en)","topic_count":len(image_topics),"ready_topic_count":0,"errors":[],"topics":{},"max_images_per_topic":max_images_per_topic}
    if not image_topics:
        result["ok"]=True; wjson(out/"zsxq_image_ocr.json",result); return result
    if os.environ.get("ZSXQ_DISABLE_IMAGE_OCR","").strip()=="1":
        result["error"]="disabled_by_ZSXQ_DISABLE_IMAGE_OCR"; wjson(out/"zsxq_image_ocr.json",result); return result
    try:
        import tempfile
        import numpy as np
        from PIL import Image
        import easyocr
    except Exception as exc:
        result["error"]=f"ocr_dependency_unavailable: {exc}"; wjson(out/"zsxq_image_ocr.json",result); return result
    try:
        reader=easyocr.Reader(["ch_sim","en"],gpu=False,verbose=False)
    except Exception as exc:
        result["error"]=f"ocr_reader_init_failed: {exc}"; wjson(out/"zsxq_image_ocr.json",result); return result
    with tempfile.TemporaryDirectory(prefix="zsxq_ocr_") as tmp:
        tmpdir=Path(tmp)
        for topic in image_topics:
            topic_id=str(topic.get("topic_id") or topic.get("id") or "")
            if not topic_id:
                continue
            image_rows=[]; text_parts=[]
            images=topic.get("images") if isinstance(topic.get("images"),list) else []
            for idx,image in enumerate(images[:max_images_per_topic],1):
                if not isinstance(image,dict):
                    continue
                url=_topic_image_url(image)
                if not url:
                    continue
                local=tmpdir/f"{topic_id}_{idx}.jpg"
                ok,err=_download_image_for_ocr(url,local)
                if not ok:
                    result["errors"].append({"topic_id":topic_id,"index":idx,"error":err})
                    image_rows.append({"index":idx,"url":url,"ocr_text":"","status":"DOWNLOAD_FAILED"})
                    continue
                try:
                    arr=np.array(Image.open(local).convert("RGB"))
                    pieces=reader.readtext(arr,detail=0,paragraph=True)
                    text=re.sub(r"\s+"," ","\n".join(str(piece) for piece in pieces)).strip()
                    status="READY" if text else "EMPTY"
                except Exception as exc:
                    text=""; status="OCR_FAILED"; result["errors"].append({"topic_id":topic_id,"index":idx,"error":str(exc)[:500]})
                if text:
                    text_parts.append(f"图片{idx}：{text}")
                image_rows.append({"index":idx,"url":url,"ocr_text":text,"status":status})
            ocr_text=re.sub(r"\s+"," ","\n".join(text_parts)).strip()
            if ocr_text:
                result["ready_topic_count"]+=1
            result["topics"][topic_id]={"topic_id":topic_id,"image_count":len(images),"ocr_text":ocr_text,"images":image_rows}
    result["ok"]=True
    wjson(out/"zsxq_image_ocr.json",result)
    return result

def analyze_recent_topics(data: dict[str,Any]) -> dict[str,Any]:
    topics=data.get("topics_brief") or data.get("topics") or []
    master,names,lookup_error,lookup_health=_load_stock_lookup()
    effective=[]; noise=[]
    for raw in topics:
        content=_clean_zsxq_text(raw.get("content") or raw.get("text") or raw.get("plain_text") or "")
        files=raw.get("files") or []
        if not isinstance(files,list):
            files=[]
        file_names=[str(item.get("name") or "").strip() for item in files if isinstance(item,dict) and str(item.get("name") or "").strip()]
        attachment_text="\n".join(file_names)
        analysis_text=f"{content}\n{attachment_text}".strip()
        title=_topic_title(content,raw.get("title") or "")
        if file_names and title.startswith("#"):
            title=f"{title}｜{file_names[0][:80]}"
        themes=_topic_theme_hits(analysis_text)
        companies=_extract_companies(analysis_text,master,names)
        topic_id=str(raw.get("topic_id") or raw.get("id") or "")
        reason=""
        compact=re.sub(r"\s+","",content)
        attachment_only=bool(file_names and len(compact)<40)
        if attachment_only and not (themes or companies):
            reason="附件型主题但文件名未识别到产业主线或公司标的"
        elif len(compact)<40 and not attachment_only:
            reason="正文过短或仅标签，无法形成可核验主题"
        elif TRADING_SEAT_RE.search(f"{title}\n{analysis_text[:500]}"):
            reason="交易席位/买卖动向，不纳入小时研报精选"
        elif not themes and not companies:
            reason="未识别到产业主线或公司标的"
        elif len(compact)<80 and not companies:
            reason="正文信息密度不足，保留为噪音"
        evidence=_evidence_snippet(content,themes,companies)
        if attachment_only and not evidence and file_names:
            evidence="附件名："+"；".join(file_names[:3])
        row={
            "topic_id":topic_id,
            "create_time":str(raw.get("create_time") or ""),
            "title":title,
            "content_length":len(compact),
            "attachment_only":attachment_only,
            "attachment_file_count":len(file_names),
            "attachment_file_names":file_names,
            "themes":themes,
            "companies":companies,
            "evidence":evidence,
            "content_head":content[:240],
        }
        row["report_entity_bindings"] = bind_report_attachments(row)
        # Original extraction remains available; binding never rewrites source text.
        if reason:
            row["noise_reason"]=reason
            noise.append(row)
        else:
            effective.append(row)
    buckets: dict[str,dict[str,Any]]={}
    for row in effective:
        for theme_index,t in enumerate(row["themes"][:2]):
            b=buckets.setdefault(t["theme"],{"theme":t["theme"],"topic_ids":[],"companies":[],"keywords":[]})
            if row["topic_id"] not in b["topic_ids"]:
                b["topic_ids"].append(row["topic_id"])
            if theme_index==0:
                for c in _theme_bound_companies(row,t):
                    disp=_display_company(c)
                    _append_company_display(b["companies"],disp)
            for kw in t.get("keywords",[])[:6]:
                if kw not in b["keywords"]:
                    b["keywords"].append(kw)
    theme_rows=sorted(buckets.values(),key=lambda x:(-len(x["topic_ids"]),x["theme"]))
    return {
        "raw_topic_count":len(topics),
        "effective_topic_count":len(effective),
        "noise_topic_count":len(noise),
        "attachment_only_topic_count":sum(1 for row in effective if row.get("attachment_only")),
        "attachment_file_count":sum(int(row.get("attachment_file_count") or 0) for row in effective),
        "theme_count":len(theme_rows),
        "themes":theme_rows,
        "effective_topics":effective,
        "noise_topics":noise,
        "stock_lookup_error":lookup_error,
        "stock_lookup_health":lookup_health,
        "report_subject_policy_sha256":hashlib.sha256(Path(__file__).with_name("report_subjects.py").read_bytes()).hexdigest(),
    }

def build_recent_effective_report(analysis: dict[str,Any]) -> str:
    themes=analysis.get("themes") or []
    pool=_recent_stock_pool(analysis)
    delta=analysis.get("hourly_delta") or {}
    new_topics=delta.get("new_topics") or []
    continued_topics=delta.get("continued_topics") or []
    removed_topics=delta.get("removed_topics") or []
    new_stocks=delta.get("new_stocks") or []
    new_themes=delta.get("new_themes") or []
    top_theme=(themes[0]["theme"] if themes else "待复核")
    pool_text="、".join(pool) if pool else "最新20条暂无明确股票池"
    lines=[
        f"【ZSXQ 小时精选/最近有效补充】{nowc().strftime('%Y-%m-%d %H:%M')}",
        "================================================",
        "",
        "一、总览：可能利好/重点复核标的",
        f"  本小时新增：{len(new_topics)}条有效主题；延续：{len(continued_topics)}条；退出/降级：{len(removed_topics)}条。",
        f"  新增主线：{'、'.join(new_themes[:5]) if new_themes else '无新增主线，主要为既有主线补充'}",
        f"  新增重点复核标的：{'、'.join(new_stocks[:8]) if new_stocks else '暂无新增明确股票池'}",
        f"  对比基准：{delta.get('base_run') or '未找到上一小时有效结果'}",
        "  本小时新增材料：",
    ]
    if new_topics:
        for row in new_topics[:5]:
            lines.append(f"    - {row.get('create_time')}｜{row.get('title')}｜topic_id={row.get('topic_id')}")
    else:
        lines.append("    - 本小时未发现相对上一小时的新有效主题。")
    lines.extend([
        f"  原始主题数：{analysis.get('raw_topic_count',0)}",
        f"  有效主题数：{analysis.get('effective_topic_count',0)}",
        f"  剔除噪音数：{analysis.get('noise_topic_count',0)}",
        f"  当前最强主线：{top_theme}",
        f"  可能利好/重点复核股票池：{pool_text}",
        "  说明：标的来自原文显式名称、代码或本地证券主数据匹配，只作为复核入口。",
        "",
        "二、主线方向",
    ])
    if themes:
        for i,t in enumerate(themes[:6],1):
            lines.append(f"  {i}. {t['theme']} | 主题数：{len(t.get('topic_ids') or [])} | topic_id：{', '.join(t.get('topic_ids',[])[:5])}")
            companies=t.get("companies") or []
            company_text=("、".join(companies[:5])+(" 等" if len(companies)>5 else "")) if companies else "主题性观点，无明确公司"
            lines.append(f"     标的/公司：{company_text}")
            lines.append(f"     依据关键词：{'、'.join(t.get('keywords') or []) or '待复核'}")
    else:
        lines.append("  - 最新20条未形成稳定主线。")
    lines.extend(["","三、详细依据"])
    for i,row in enumerate((analysis.get("effective_topics") or [])[:12],1):
        theme_text="、".join([t["theme"] for t in row.get("themes",[])[:2]]) or "待复核"
        lines.append(f"  {i}. {row['title']}")
        lines.append(f"     topic_id：{row['topic_id']} | 时间：{row['create_time']}")
        lines.append(f"     主线方向：{theme_text}")
        lines.append(f"     标的/公司：{_company_text(row.get('companies') or [])}")
        lines.append(f"     原文依据：{row.get('evidence') or '无'}")
    if not analysis.get("effective_topics"):
        lines.append("  - 最新20条不足以形成有效精选。")
    lines.extend([
        "",
        "四、复核要点",
        "  - PDF-only、图片-only、hashtag-only 不单独生成标的结论；仅保留为低权重线索。",
        "  - 公司/标的来自原文显式名称、代码或本地证券主数据匹配；同名行业词如“机器人”无代码时不当作股票。",
        "  - 本报告不调用 MiniMax 或外部 LLM API，仅做规则抽取和中文结构化。",
        "",
        "五、数据来源与剔除说明",
        f"  数据源：cookie_api groups={','.join(g['group_id'] for g in GROUPS)} --limit 20",
        "  剔除噪音：",
    ])
    for row in (analysis.get("noise_topics") or [])[:10]:
        lines.append(f"  - topic_id={row['topic_id']}：{row.get('noise_reason','低信息密度')}")
    if not analysis.get("noise_topics"):
        lines.append("  - 本轮未剔除噪音主题。")
    lines.append("  免责声明：仅为资讯整理和复核线索，不构成投资建议。")
    return "\n".join(lines).strip()+"\n"

def recent_report_quality(meta: dict[str,Any]) -> tuple[bool,str,dict[str,Any]]:
    effective=int(meta.get("effective_topic_count") or 0)
    themes=int(meta.get("theme_count") or 0)
    attachment_only=int(meta.get("attachment_only_topic_count") or 0)
    attachment_files=int(meta.get("attachment_file_count") or 0)
    stock_count=len(_recent_stock_pool(meta))
    text_len=sum(int(row.get("content_length") or 0) for row in (meta.get("effective_topics") or []) if isinstance(row,dict))
    detail={"effective_topic_count":effective,"theme_count":themes,"clean_stock_count":stock_count,"effective_text_length":text_len,"attachment_only_topic_count":attachment_only,"attachment_file_count":attachment_files}
    if effective<3:
        if attachment_only>=3 and attachment_files>=3:
            return True,"degraded_attachment_only_needs_processing",detail
        return False,"effective_topic_count_less_than_3",detail
    if themes<1 and text_len<800:
        if attachment_only>=3:
            return True,"degraded_attachment_only_needs_processing",detail
        return False,"no_theme_and_effective_text_too_short",detail
    if attachment_only and attachment_only>=max(1,effective//2):
        return True,"degraded_attachment_only_needs_processing",detail
    if stock_count<2:
        detail["stock_pool_warning"]="clean_stock_pool_less_than_2"
        if themes>=3 and text_len>=800:
            return True,"ok",detail
        return True,"degraded_no_clean_stock_pool",detail
    if themes<3:
        return True,"degraded_low_theme_count",detail
    return True,"ok",detail

def recent_report_ok(meta: dict[str,Any]) -> bool:
    ok,_,_=recent_report_quality(meta)
    return ok

def recent_extraction_status(meta: dict[str,Any]) -> dict[str,Any]:
    ok,reason,detail=recent_report_quality(meta)
    degraded=bool(ok and reason!="ok")
    return {
        "fallback_recent_topics_ok":bool(ok),
        "fallback_degraded_used":degraded,
        "fallback_rejected_reason":"" if ok else reason,
        "fallback_quality_reason":reason,
        "stock_mapping_status":"NEED_REVIEW" if degraded or int(detail.get("clean_stock_count") or 0)<2 else "OK",
        "extraction_quality":"DEGRADED_ATTACHMENT_ONLY" if reason=="degraded_attachment_only_needs_processing" else ("DEGRADED" if degraded else ("OK" if ok else "REJECTED")),
        **detail,
    }

def recent_effective_signature(meta: dict[str,Any]) -> str:
    ids=sorted(str(row.get("topic_id") or "") for row in (meta.get("effective_topics") or []) if isinstance(row,dict) and row.get("topic_id"))
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest() if ids else ""

def previous_recent_summary(out: Path) -> tuple[str,dict[str,Any]]:
    try:
        run_logs=out.parent.parent
        current_run=out.parent.name
        for run_dir in sorted([p for p in run_logs.iterdir() if p.is_dir() and p.name<current_run],key=lambda p:p.name,reverse=True):
            summary_path=run_dir/"zsxq"/"zsxq_summary.json"
            if not summary_path.exists():
                continue
            summary=json.loads(rtxt(summary_path))
            if summary.get("effective_topics"):
                return run_dir.name,summary
    except Exception:
        pass
    return "",{}

def enrich_recent_delta(out: Path, meta: dict[str,Any]) -> None:
    base_run,prev=previous_recent_summary(out)
    prev_topics=[row for row in (prev.get("effective_topics") or []) if isinstance(row,dict)]
    curr_topics=[row for row in (meta.get("effective_topics") or []) if isinstance(row,dict)]
    prev_ids={str(row.get("topic_id") or "") for row in prev_topics}
    curr_ids={str(row.get("topic_id") or "") for row in curr_topics}
    prev_stocks=set(_recent_stock_pool(prev))
    curr_stocks=_recent_stock_pool(meta)
    prev_themes={str(row.get("theme") or "") for row in (prev.get("themes") or []) if isinstance(row,dict)}
    curr_themes=[str(row.get("theme") or "") for row in (meta.get("themes") or []) if isinstance(row,dict)]
    meta["hourly_delta"]={
        "base_run":base_run,
        "new_topics":[row for row in curr_topics if str(row.get("topic_id") or "") not in prev_ids],
        "continued_topics":[row for row in curr_topics if str(row.get("topic_id") or "") in prev_ids],
        "removed_topics":[row for row in prev_topics if str(row.get("topic_id") or "") not in curr_ids],
        "new_stocks":[stock for stock in curr_stocks if stock not in prev_stocks],
        "new_themes":[theme for theme in curr_themes if theme and theme not in prev_themes],
    }

def previous_recent_effective_signature(out: Path) -> tuple[str,str]:
    try:
        run_logs=out.parent.parent
        current_run=out.parent.name
        for run_dir in sorted([p for p in run_logs.iterdir() if p.is_dir() and p.name<current_run],key=lambda p:p.name,reverse=True):
            summary_path=run_dir/"zsxq"/"zsxq_summary.json"
            if not summary_path.exists():
                continue
            try:
                summary=json.loads(rtxt(summary_path))
            except Exception:
                continue
            if str(summary.get("action") or "") in ("pushed_recent_effective_supplement","degraded_recent_topics_report"):
                sig=str(summary.get("recent_effective_signature") or "") or recent_effective_signature(summary)
                if sig:
                    return sig,run_dir.name
    except Exception:
        pass
    return "",""

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output-dir",required=True); ap.add_argument("--push",action="store_true"); ap.add_argument("--refetch-timeout",type=int,default=420); args=ap.parse_args()
    st=time.perf_counter(); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True); log=out/"zsxq_event_log.jsonl"; jlog(log,{"event":"start","ts":nowc().isoformat(),"version":"fixed_v24_refetch"})
    cursor_before=read_cursor_snapshot(); wjson(out/"zsxq_cursor_before.json",{"path":str(CURSOR_FILE),"snapshot_exists":cursor_before is not None})
    comp,res=run_refetch(args.refetch_timeout,out,log)
    recent_data,recent_fetch=fetch_recent_topics(out,20)
    recent_meta={}
    recent_content=""
    image_ocr_meta={}
    if recent_data:
        image_ocr_meta=generate_image_ocr_cache(out,recent_data)
        recent_meta=analyze_recent_topics(recent_data)
        recent_meta["image_ocr"]={
            "ok":image_ocr_meta.get("ok"),
            "topic_count":image_ocr_meta.get("topic_count"),
            "ready_topic_count":image_ocr_meta.get("ready_topic_count"),
            "error":image_ocr_meta.get("error") or "",
        }
        recent_meta["recent_effective_signature"]=recent_effective_signature(recent_meta)
        enrich_recent_delta(out,recent_meta)
        recent_meta.update(recent_extraction_status(recent_meta))
        recent_content=build_recent_effective_report(recent_meta)
        wjson(out/"zsxq_recent_effective_meta.json",recent_meta)
        wtxt(out/"zsxq_recent_effective_report.txt",recent_content)
    recent_ok=recent_report_ok(recent_meta)

    def recent_push_action(meta: dict[str,Any]) -> str:
        return "degraded_recent_topics_report" if meta.get("fallback_degraded_used") else "pushed_recent_effective_supplement"

    def skip_duplicate_recent(meta: dict[str,Any], reason: str) -> int:
        wtxt(out/"zsxq_final_push_content.txt",recent_content); wjson(out/"zsxq_meta.json",meta)
        summ={"ok":True,"action":"skipped_recent_effective_duplicate","push_ok":None,"reason":reason,"elapsed_seconds":round(time.perf_counter()-st,3),**meta}
        wjson(out/"zsxq_summary.json",summ); status_update("zsxq",summ); return 0

    def should_skip_duplicate_recent(meta: dict[str,Any]) -> tuple[bool,str]:
        sig=str(meta.get("recent_effective_signature") or "")
        prev_sig,prev_run=previous_recent_effective_signature(out)
        if sig and prev_sig and sig==prev_sig:
            return True,f"recent effective topic set unchanged from {prev_run}; skip duplicate Feishu push"
        return False,""

    def finish_with_content(content: str, meta: dict[str,Any], action: str) -> int:
        wtxt(out/"zsxq_final_push_content.txt",content); wjson(out/"zsxq_meta.json",meta)
        reports=REPORTS_DIR; wtxt(reports/f"{nowc().strftime('%Y%m%d%H')}.zsxq.fixed_v24_refetch.txt",content)
        ok,prob=validate(content); wjson(out/"zsxq_validation.json",{"ok":ok,"problems":prob})
        if not ok:
            restore_cursor_snapshot(cursor_before)
            summ={"ok":False,"action":"failed_validation","problems":prob,"elapsed_seconds":round(time.perf_counter()-st,3),**meta}
            wjson(out/"zsxq_summary.json",summ); status_update("zsxq",summ); return 3
        pr=push_text(content) if args.push else {"ok":None,"skipped":True}
        wjson(out/"zsxq_push_result.json",pr)
        if not args.push or not pr.get("ok"):
            restore_cursor_snapshot(cursor_before)
        if args.push:
            final_action=action
        elif action.startswith("degraded_"):
            final_action="preview_"+action
        else:
            final_action=action.replace("pushed_","preview_",1)
        summ={"ok":bool(pr.get("ok")) if args.push else True,"action":final_action,"push_ok":pr.get("ok"),"elapsed_seconds":round(time.perf_counter()-st,3),**meta}
        wjson(out/"zsxq_summary.json",summ); status_update("zsxq",summ); return 0 if summ["ok"] else 4

    if res["returncode"]!=0 and not comp.get("hash_changed"):
        if recent_ok:
            meta={"mode":"recent_effective_supplement","reason":"refetch_failed_but_zsxq_cli_recent_topics_ok","primary_refetch_failed":True,"refetch_returncode":res["returncode"],"recent_fetch":recent_fetch,**recent_meta}
            dup,dup_reason=should_skip_duplicate_recent(meta)
            if dup:
                restore_cursor_snapshot(cursor_before)
                return skip_duplicate_recent(meta,dup_reason)
            return finish_with_content(recent_content,meta,recent_push_action(meta))
        restore_cursor_snapshot(cursor_before)
        summ={"ok":True,"action":"skipped_refetch_failed","push_ok":None,"primary_refetch_failed":True,"refetch_returncode":res["returncode"],"elapsed_seconds":round(time.perf_counter()-st,3),"reason":"refetch failed and recent topics insufficient","recent_fetch":recent_fetch,**recent_meta}
        wjson(out/"zsxq_summary.json",summ); status_update("zsxq",summ); return 0
    if not comp.get("hash_changed"):
        if recent_ok:
            meta={"mode":"recent_effective_supplement","reason":"pipeline_report_unchanged_but_recent_topics_available","primary_refetch_failed":False,"refetch_returncode":0,"latest_hash":comp["after"]["sha256"],"recent_fetch":recent_fetch,**recent_meta}
            dup,dup_reason=should_skip_duplicate_recent(meta)
            if dup:
                return skip_duplicate_recent(meta,dup_reason)
            return finish_with_content(recent_content,meta,recent_push_action(meta))
        if not args.push: restore_cursor_snapshot(cursor_before)
        summ={"ok":True,"action":"skipped_unchanged","push_ok":None,"refetch_returncode":0,"latest_hash":comp["after"]["sha256"],"elapsed_seconds":round(time.perf_counter()-st,3),"reason":"latest_zsxq_report unchanged after refetch; skip duplicate ZSXQ","recent_fetch":recent_fetch,**recent_meta}
        wjson(out/"zsxq_summary.json",summ); status_update("zsxq",summ); return 0

    raw=rtxt(LATEST_ZSXQ_REPORT); wtxt(out/"zsxq_source_report.txt",raw)
    pipeline_content,pipeline_meta=reformat(raw); wtxt(out/"zsxq_pipeline_reformatted_report.txt",pipeline_content); wjson(out/"zsxq_pipeline_meta.json",pipeline_meta)
    useful,why=content_has_effective_zsxq(raw,pipeline_meta); wjson(out/"zsxq_usefulness_gate.json",{"ok":useful,"reason":why})
    if recent_ok and (not useful or int(recent_meta.get("theme_count") or 0)>int(pipeline_meta.get("theme_count") or 0)):
        meta={"mode":"recent_effective_supplement","primary_refetch_failed":False,"pipeline_useful":useful,"pipeline_reason":why,"pipeline_meta":pipeline_meta,"recent_fetch":recent_fetch,**recent_meta}
        dup,dup_reason=should_skip_duplicate_recent(meta)
        if dup:
            return skip_duplicate_recent(meta,dup_reason)
        return finish_with_content(recent_content,meta,recent_push_action(meta))
    if not useful:
        restore_cursor_snapshot(cursor_before)
        summ={"ok":True,"action":"skipped_no_effective_stocks","push_ok":None,"reason":why,"elapsed_seconds":round(time.perf_counter()-st,3),"recent_fetch":recent_fetch,**pipeline_meta,**recent_meta}
        wjson(out/"zsxq_summary.json",summ); status_update("zsxq",summ); return 0
    meta={"mode":"pipeline_reformat","pipeline_useful":useful,"pipeline_reason":why,"recent_fetch":recent_fetch,**pipeline_meta}
    return finish_with_content(pipeline_content,meta,"pushed_new_report")
if __name__=="__main__": raise SystemExit(main())
