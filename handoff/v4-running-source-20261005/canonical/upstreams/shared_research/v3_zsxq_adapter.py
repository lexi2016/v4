"""V4-owned pure ZSXQ topic analyzer closure.

Only ``analyze_recent_topics`` and the helpers it calls are included.  Fetch,
push, cursor, image-download, and legacy state writers intentionally remain
outside this package.
"""


from __future__ import annotations

import argparse, html, json, os, re, subprocess, sys, time, hashlib

from pathlib import Path

from typing import Any

from urllib.parse import unquote

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

def items(block): return [l.rstrip() for l in block.splitlines() if "触发原因：" in l]

def theme(line):
    low=line.lower()
    if any(k in line for k in ["恒锋工具","机床","刀具","拉刀","齿轮刀","工业母机"]):
        return "机械设备/机床/工业母机"
    for name,kws in THEMES:
        if any(k.lower() in low for k in kws): return name
    return "其他待复核线索"

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
    if name in BROKER_PREFIX_NAMES:
        return
    if name in AMBIGUOUS_STOCK_NAMES and source not in {"explicit_code","code"}:
        return
    code=_code_to_ts(code)
    for old in out:
        if old.get("name")==name:
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

def _append_company_display(items: list[str], display: str) -> None:
    base=re.sub(r"[（(]\d{6}\.(?:SH|SZ|BJ)[）)]","",display)
    for i,old in enumerate(items):
        old_base=re.sub(r"[（(]\d{6}\.(?:SH|SZ|BJ)[）)]","",old)
        if old_base==base:
            if "(" in display and "(" not in old:
                items[i]=display
            return
    items.append(display)

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
        attachment_text=" ".join(file_names)
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
            "attachment_file_names":file_names[:8],
            "themes":themes,
            "companies":companies,
            "evidence":evidence,
            "content_head":content[:240],
        }
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
    }

__all__ = ["analyze_recent_topics"]

