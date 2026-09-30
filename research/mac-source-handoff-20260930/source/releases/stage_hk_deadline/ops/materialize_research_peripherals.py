"""Materialize V3.5-owned public research peripherals.

The producers in this module are deterministic adapters around two public
discovery surfaces: Google News RSS and the AIHot public timeline page.  They
only preserve source evidence and explicit discovery limitations; no model,
legacy artifact, V3 path, or trading decision is involved.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from infrastructure.data_store import _date, _sha256
from infrastructure.http_transport import (
    FetchResult,
    ProxyAwareHTTPTransport,
    TransportError,
)
from infrastructure.research_peripheral_store import ResearchPeripheralStore


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GOOGLE_TRANSLATE = "https://translate.googleapis.com/translate_a/single"
MYMEMORY_TRANSLATE = "https://api.mymemory.translated.net/get"
AIHOT_URL = "https://aihot.virxact.com/?mark_id=999_reallog_mark_ad%3A999%7CWeiboADNatural"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) v3.5-research-peripherals/1.0"

DEFAULT_SUBSCRIPTIONS: tuple[dict[str, str], ...] = (
    {
        "id": "authority_china_hk",
        "display_name": "A/H authority feed",
        "query": (
            "(site:reuters.com OR site:bloomberg.com OR site:cnbc.com OR site:wsj.com "
            "OR site:ft.com OR site:asia.nikkei.com OR site:scmp.com) "
            "(China stocks OR Hong Kong stocks OR Hang Seng OR Alibaba OR Tencent OR BYD "
            "OR TSMC OR SMIC OR CATL OR Xiaomi OR Zhongji Innolight OR Kingboard Laminates) "
            "(market OR shares OR earnings OR policy OR IPO)"
        ),
        "theme_bucket": "china_hk_stocks",
    },
    {
        "id": "china_hk_stocks",
        "display_name": "China/HK stocks",
        "query": (
            "(Hong Kong stocks OR Hang Seng OR HSI OR China stocks OR Chinese stocks OR ADRs "
            "OR China market OR southbound funds) "
            "(rally OR slump OR earnings OR policy OR IPO OR valuation)"
        ),
        "theme_bucket": "china_hk_stocks",
    },
    {
        "id": "china_tech_ai_semis",
        "display_name": "China tech / AI / semis",
        "query": (
            "(China semiconductor OR China AI chip OR China EV OR China robotics OR China biotech "
            "OR China brokerages OR optical module OR CPO) "
            "(stocks OR shares OR market OR policy OR earnings)"
        ),
        "theme_bucket": "china_tech_ai_semis",
    },
    {
        "id": "hk_ipo_new_economy",
        "display_name": "HK IPO / new economy",
        "query": (
            "(Hong Kong IPO OR HK IPO OR Chinese autonomous driving IPO OR China biotech IPO "
            "OR China robotaxi IPO OR Chinese AI company listing) "
            "(stock OR market OR valuation OR listing)"
        ),
        "theme_bucket": "hk_ipo_new_economy",
    },
    {
        "id": "ai_compute_chip",
        "display_name": "AI compute / chips",
        "query": (
            "(AI data center OR AI buildout OR Nvidia OR memory chip OR semiconductor "
            "OR AI server OR optical module OR custom AI chip OR HBM) "
            "(stocks OR market OR earnings OR investment OR supply chain)"
        ),
        "theme_bucket": "ai_compute_chip",
    },
    {
        "id": "robotics_autonomous",
        "display_name": "Robotics / autonomous driving",
        "query": (
            "(humanoid robot OR robotics OR robotaxi OR Optimus OR autonomous driving "
            "OR embodied AI OR Mobileye OR Boston Dynamics) "
            "(stocks OR market OR company OR investment OR IPO)"
        ),
        "theme_bucket": "robotics_autonomous",
    },
    {
        "id": "commercial_space",
        "display_name": "Commercial space",
        "query": (
            "(SpaceX OR Starlink OR satellite launch OR commercial space OR Rocket Lab "
            "OR space economy) "
            "(stock OR market OR IPO OR valuation OR company OR supply chain)"
        ),
        "theme_bucket": "commercial_space",
    },
    {
        "id": "biopharma_ma",
        "display_name": "Biopharma catalysts",
        "query": (
            "(FDA approval OR biotech acquisition OR pharma deal OR clinical trial OR GLP-1) "
            "(stock OR market OR shares OR valuation OR China biotech)"
        ),
        "theme_bucket": "biopharma_ma",
    },
)

NEGATIVE_PATTERNS = (
    "price prediction",
    "stocks to buy",
    "stock list",
    "prediction markets",
    "personal finance",
    "simplywall",
    "simply wall st",
)
GENERIC_TITLES = frozenset({"stocks", "business politics economy and tech news analysis"})
ALLOWED_NICHE_SOURCES = ("data center dynamics", "space news", "spacenews", "the pharma letter")
SOURCE_TIER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("reuters", "T1: Reuters"),
    ("bloomberg", "T1: Bloomberg"),
    ("financial times", "T1: FT"),
    ("ft.com", "T1: FT"),
    ("wall street journal", "T1: WSJ"),
    ("wsj", "T1: WSJ"),
    ("cnbc", "T1: CNBC"),
    ("nikkei", "T1: Nikkei Asia"),
    ("south china morning post", "T2: SCMP"),
    ("scmp", "T2: SCMP"),
    ("marketwatch", "T2: MarketWatch"),
    ("seeking alpha", "T3: Seeking Alpha"),
    ("tradingview", "T3: TradingView"),
)
AH_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("zhongji innolight", ("300308.SZ 中际旭创", "光模块/CPO", "AI算力链")),
    ("optical module", ("光模块/CPO", "中际旭创/新易盛/天孚通信复核")),
    ("cpo", ("光模块/CPO", "AI算力链")),
    ("kingboard laminates", ("1888.HK 建滔积层板", "覆铜板/PCB材料")),
    ("pcb", ("PCB/覆铜板", "胜宏科技/沪电股份/建滔系复核")),
    ("copper clad", ("覆铜板/PCB材料",)),
    ("alibaba", ("9988.HK 阿里巴巴", "港股互联网")),
    ("tencent", ("0700.HK 腾讯控股", "港股互联网/AI应用")),
    ("byd", ("1211.HK/002594.SZ 比亚迪", "汽车出海")),
    ("xiaomi", ("1810.HK 小米集团", "AI手机/汽车链")),
    ("smic", ("0981.HK/688981.SH 中芯国际", "半导体国产替代")),
    ("tsmc", ("台积电链", "半导体设备/材料")),
    ("catl", ("300750.SZ 宁德时代", "新能源车/储能")),
    ("robotaxi", ("自动驾驶/Robotaxi", "地平线机器人/小马智行/相关传感器链")),
    ("autonomous driving", ("自动驾驶/Robotaxi", "智能驾驶链")),
    ("humanoid", ("人形机器人", "减速器/执行器/传感器链")),
    ("robotics", ("机器人", "执行器/控制器/传感器链")),
    ("spacex", ("商业航天", "卫星互联网/商业航天链")),
    ("starlink", ("卫星互联网", "商业航天链")),
    ("rocket lab", ("商业航天", "港美股航天映射")),
    ("hong kong ipo", ("港股IPO", "新经济上市预期")),
    ("ipo", ("港股IPO", "估值/流动性复核")),
    ("hang seng", ("恒生指数/港股流动性",)),
    ("southbound", ("南向资金", "港股流动性")),
    ("glp-1", ("创新药/GLP-1", "医药商业化")),
    ("fda approval", ("创新药", "临床/FDA催化")),
    ("china biotech", ("港股18A/创新药",)),
)
THEME_LABELS = {
    "china_hk_stocks": "中国资产/A股港股",
    "china_tech_ai_semis": "中国科技/AI/半导体",
    "hk_ipo_new_economy": "港股IPO/新经济",
    "ai_compute_chip": "AI算力/芯片",
    "robotics_autonomous": "机器人/自动驾驶",
    "commercial_space": "商业航天",
    "biopharma_ma": "创新药/并购/临床",
}
SOURCE_CN_LABELS = {
    "Bloomberg.com": "彭博",
    "CNBC": "CNBC",
    "Data Center Dynamics": "Data Center Dynamics",
    "Reuters": "路透",
    "South China Morning Post": "南华早报",
    "SpaceNews": "SpaceNews",
    "The Business Times": "商业时报",
    "The Pharma Letter": "Pharma Letter",
    "WSJ": "华尔街日报",
}


FetchFn = Callable[..., bytes | str]
TranslateFn = Callable[..., str]
OriginalUrlResolver = Callable[..., str]
_DEFAULT_HTTP_TRANSPORT: ProxyAwareHTTPTransport | None = None


def _default_http_transport() -> ProxyAwareHTTPTransport:
    """Create the process transport after launchd environment injection."""
    global _DEFAULT_HTTP_TRANSPORT
    if _DEFAULT_HTTP_TRANSPORT is None:
        _DEFAULT_HTTP_TRANSPORT = ProxyAwareHTTPTransport()
    return _DEFAULT_HTTP_TRANSPORT
_CJK = re.compile(r"[\u3400-\u9fff]")
_CST = timezone(timedelta(hours=8))
_AI_MAX_ITEMS = 8
_AI_RISKS = ("AI 新闻默认作为技术/产业动态，需结合订单、业绩或A/H映射再升级。",)
_AI_THEME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "PCB/电子布/电子材料",
        ("PCB", "电子布", "覆铜板", "CCL", "铜箔", "MSAP", "SAP", "载板", "ABF", "玻璃基板", "电子材料", "电镀"),
    ),
    (
        "存储/DRAM/NAND/HBM/AI存储",
        ("存储", "DRAM", "NAND", "HBM", "SSD", "美光", "海力士", "三星", "江波龙", "兆易创新", "佰维存储"),
    ),
    (
        "光通信/CPO/光模块/光纤海缆",
        ("CPO", "光模块", "光通信", "光纤", "光连接", "光引擎", "光芯片", "1.6T", "800G", "400G", "康宁", "天孚", "中际旭创", "新易盛", "长飞"),
    ),
    (
        "商业航天/卫星/太空光伏",
        ("商业航天", "卫星", "火箭", "太空", "空天", "航天", "低空经济"),
    ),
    (
        "半导体设备/材料/先进封装",
        ("半导体", "硅片", "晶圆", "中芯", "华虹", "先进封装", "CoWoS", "封测", "碳化硅", "电子特气"),
    ),
    (
        "AI算力/AIDC/数据中心/服务器",
        ("AI", "算力", "服务器", "液冷", "数据中心", "AIDC", "GPU", "英伟达", "data center", "chip", "Alphabet", "Microsoft"),
    ),
    (
        "新能源车/智能驾驶/汽车零部件",
        ("智能底盘", "京西智行", "立讯", "汽车", "自动驾驶", "零部件", "固态电池"),
    ),
    (
        "电力设备/储能/算电协同",
        ("储能", "电池", "光伏", "隆基", "鹏辉", "绿电", "电网", "算电协同"),
    ),
    (
        "机器人/具身智能",
        ("机器人", "Humanoid", "Agent", "智能体", "丝杠", "减速器"),
    ),
    (
        "油气/黄金/地缘",
        ("油", "Iran", "Hormuz", "伊朗", "黄金", "LNG"),
    ),
    (
        "医药/创新药",
        ("医药", "创新药", "ASCO", "肿瘤", "MASH", "GLP-1", "ADC"),
    ),
    (
        "中国资产/出海/关税",
        ("China", "中国", "tariff", "关税", "出海"),
    ),
    (
        "金融/利率/加密",
        ("Fed", "rate", "利率", "crypto", "stablecoin", "银行"),
    ),
)
_AI_IMPLICATIONS = {
    "PCB/电子布/电子材料": "复核PCB、电子布、覆铜板、铜箔、电镀和先进封装材料链条。",
    "存储/DRAM/NAND/HBM/AI存储": "复核存储芯片、模组、SSD、HBM及AI服务器存储链条。",
    "AI算力/AIDC/数据中心/服务器": "复核AI算力硬件、服务器、光模块、PCB、半导体设备及港股科技映射。",
    "半导体设备/材料/先进封装": "复核半导体设备、材料、先进封装和国产替代链条。",
    "机器人/具身智能": "复核机器人本体、零部件、工业自动化和具身智能产业链。",
    "光通信/CPO/光模块/光纤海缆": "复核CPO、光模块、光引擎、光纤光缆和AI网络互联产业链。",
    "新能源车/智能驾驶/汽车零部件": "复核智能驾驶、智能底盘、汽车零部件和相关供应链。",
    "电力设备/储能/算电协同": "复核储能、光伏、电池及电力设备链条的订单和盈利弹性。",
    "商业航天/卫星/太空光伏": "复核商业航天、卫星制造、火箭链和空间算力相关催化。",
    "油气/黄金/地缘": "复核油气开采、油服、油运、黄金及通胀预期相关资产。",
    "医药/创新药": "复核创新药、CXO、医疗器械及临床催化剂。",
    "中国资产/出海/关税": "复核中国资产、出口链、关税敏感行业和港股映射。",
    "金融/利率/加密": "复核利率、美元、银行保险、红利资产和高估值科技的估值扰动。",
}
_AI_IMPACT_CHAINS = {
    "PCB/电子布/电子材料": "AI硬件升级/供给紧张 -> PCB与电子材料涨价或放量 -> 产业链盈利弹性复核。",
    "存储/DRAM/NAND/HBM/AI存储": "AI存储需求与价格周期 -> 存储原厂/模组/控制器景气 -> A股映射复核。",
    "AI算力/AIDC/数据中心/服务器": "AI需求/资本开支 -> 算力基础设施 -> 硬件订单与估值映射。",
    "半导体设备/材料/先进封装": "国产替代/封装升级 -> 设备材料需求 -> 订单和盈利弹性复核。",
    "机器人/具身智能": "技术/订单/产业催化 -> 机器人产业链关注度 -> 本体与零部件复核。",
    "光通信/CPO/光模块/光纤海缆": "AI网络带宽需求 -> CPO/光模块/光引擎放量 -> 光通信产业链复核。",
    "新能源车/智能驾驶/汽车零部件": "收购/订单/客户导入 -> 智能驾驶与底盘供应链 -> 汽车零部件标的复核。",
    "电力设备/储能/算电协同": "订单/成本/产能变化 -> 储能与电力设备盈利预期 -> A/H相关标的复核。",
    "商业航天/卫星/太空光伏": "发射/卫星/政策催化 -> 商业航天产业链关注度 -> 制造、材料和算力环节复核。",
    "油气/黄金/地缘": "地缘与航道变量 -> 油价/通胀/避险资产 -> 能源、油运和黄金链条复核。",
    "医药/创新药": "临床/财报/BD事件 -> 管线价值与收入预期 -> 医药链条复核。",
    "中国资产/出海/关税": "政策/关税/外部需求 -> 出口链盈利与风险偏好 -> 中国资产复核。",
    "金融/利率/加密": "利率/监管/风险偏好 -> 美债美元与估值折现率 -> 金融和成长资产复核。",
}
_AI_CATALYST_KEYS = ("收购", "上调", "超预期", "首次覆盖", "订单", "扩产", "融资", "开源", "API", "发布", "关税", "Fed", "Iran")
_AI_NOISY_ENTITY_MARKERS = ("高盛", "天风", "华泰", "长江证券", "国盛", "国投证券", "中信", "中金", "申万", "交易台", "市场综述", "市场终评", "周报", "行业", "团队", "联系", "主要受", "主要在", "其中", "支撑了", "详细情况", "先进封装材料")
_REUSABLE_STATUSES = frozenset({"READY", "READY_EMPTY"})


def reuse_existing_payload(payload: Mapping[str, Any] | None) -> bool:
    """Return whether an exact-date artifact is safe to reuse.

    A ``CANNOT_CONFIRM`` artifact records a failed or incomplete attempt and
    must be retried on the next scheduled run.  Only the two terminal success
    states are reusable; this keeps the ``--reuse-existing`` optimization from
    turning a transient source outage into a stale daily result.
    """
    return isinstance(payload, Mapping) and str(payload.get("status") or "") in _REUSABLE_STATUSES


def _coerce_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(UTC).replace(microsecond=0)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def isoformat_utc(value: datetime | str | None) -> str:
    return _coerce_datetime(value).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _row_url(row: Mapping[str, Any]) -> str:
    return clean_text(row.get("original_url") or row.get("url") or row.get("source_url"))


def _is_article_url(value: Any) -> bool:
    """Accept a publisher article or Google News article redirect only."""
    url = clean_text(value)
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    raw_path = urllib.parse.unquote(parsed.path or "")
    if not raw_path or raw_path == "/" or raw_path.endswith("/"):
        return False
    path = raw_path.rstrip("/")
    if host == "news.google.com":
        parts = [part for part in path.split("/") if part]
        return len(parts) >= 2 and parts[-2] in {"articles", "read"}
    if not path:
        return False
    lower_path = path.lower()
    if re.search(r"/(?:etfs?|symbols?|markets?|categories?|topics?|tags?|search)(?:/|$)", lower_path):
        return False
    if lower_path.rsplit("/", 1)[-1] in {"news", "business", "finance", "stocks", "home", "index"}:
        return False
    return True


def _row_admission_reasons(
    row: Mapping[str, Any],
    *,
    fetched_at: datetime | str | None = None,
    lookback_days: int = 2,
) -> list[str]:
    """Return deterministic source admission failures for one finance row."""
    reasons: list[str] = []
    published_raw = clean_text(row.get("published_at"))
    if not published_raw:
        reasons.append("EXTERNAL_FINANCE_PUBLICATION_DATE_MISSING")
        published = None
    else:
        try:
            published = _coerce_datetime(published_raw)
        except (TypeError, ValueError, OverflowError):
            published = None
            reasons.append("EXTERNAL_FINANCE_PUBLICATION_DATE_INVALID")
    try:
        fetched = _coerce_datetime(fetched_at or row.get("fetched_at"))
    except (TypeError, ValueError, OverflowError):
        fetched = None
    if published is not None and fetched is not None:
        if published > fetched:
            reasons.append("EXTERNAL_FINANCE_PUBLICATION_DATE_AFTER_FETCHED_AT")
        elif fetched - published > timedelta(days=max(0, int(lookback_days))):
            reasons.append("EXTERNAL_FINANCE_ITEM_STALE")

    url = _row_url(row)
    if not url:
        reasons.append("EXTERNAL_FINANCE_ARTICLE_URL_MISSING")
    elif not _is_article_url(url):
        if clean_text(row.get("original_url_status")).upper() == "CANNOT_CONFIRM":
            reasons.append("EXTERNAL_FINANCE_ORIGINAL_URL_UNRESOLVED")
        else:
            reasons.append("EXTERNAL_FINANCE_PAGE_NOT_ARTICLE")
    elif clean_text(row.get("original_url_status")).upper() == "CANNOT_CONFIRM":
        reasons.append("EXTERNAL_FINANCE_ORIGINAL_URL_UNRESOLVED")
    return list(dict.fromkeys(reasons))


def _admit_external_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fetched_at: datetime | str | None = None,
    lookback_days: int = 2,
) -> tuple[list[dict[str, Any]], list[str]]:
    admitted: list[dict[str, Any]] = []
    rejected: list[str] = []
    for row in rows:
        reasons = _row_admission_reasons(
            row,
            fetched_at=fetched_at,
            lookback_days=lookback_days,
        )
        if reasons:
            rejected.extend(reasons)
            continue
        admitted.append(dict(row))
    return admitted, list(dict.fromkeys(rejected))


def _short_text(value: Any, limit: int = 180) -> str:
    text = clean_text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _parse_item_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("+0800", "+08:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(_CST).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(_CST).replace(tzinfo=None)
    except (TypeError, ValueError, OverflowError):
        return None


def _format_cst_time(value: Any) -> str:
    parsed = _parse_item_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S +08:00") if parsed else clean_text(value)


def _keyword_hits(text: str, keyword: str) -> int:
    if keyword.isascii() and keyword.isalpha() and len(keyword) <= 3:
        return len(re.findall(rf"\b{re.escape(keyword.lower())}\b", text.lower()))
    return text.lower().count(keyword.lower())


def _has_keyword(text: str, keyword: str) -> bool:
    return _keyword_hits(text, keyword) > 0


def _clean_markup(value: Any) -> str:
    return clean_text(value)


def _normalize_entity_name(name: str) -> str:
    return re.sub(r"^(?:推荐|看好|关注|强call|强推|子公司)", "", name).strip()


def _is_noise_entity(name: str) -> bool:
    return len(name) < 2 or any(marker in name for marker in _AI_NOISY_ENTITY_MARKERS)


def _detect_named_entities(text: str) -> list[str]:
    normalized = _clean_markup(text)
    seen: list[str] = []
    suffix_pattern = r"([\u4e00-\u9fa5A-Za-z]{2,10}(?:科技|电子|通信|股份|精密|光电|新材|材料|药业|能源|集团|证券|电力))"
    known_names = ("英伟达", "康宁", "海力士", "三星", "美光", "联芸科技", "江波龙", "兆易创新", "兴福电子", "华泰电子")
    for name in known_names:
        if name in normalized and name not in seen:
            seen.append(name)
    for match in re.finditer(suffix_pattern, normalized):
        name = _normalize_entity_name(match.group(1))
        if _is_noise_entity(name):
            continue
        if name not in seen and name not in {"核心要点", "文字观点"} and "等硬科技" not in name:
            if name.startswith(("在", "及", "和")):
                continue
            seen.append(name)
    return seen[:8]


def _detect_stock_focus(text: str, symbols: Sequence[str], entities: Sequence[str]) -> list[str]:
    focus: list[str] = []
    for symbol in symbols:
        if symbol and symbol not in focus:
            focus.append(symbol)
    for raw_name in entities:
        name = _normalize_entity_name(raw_name)
        if _is_noise_entity(name):
            continue
        if not any(name in item for item in focus):
            focus.append(f"{name}(代码待核)")
        if len(focus) >= 8:
            break
    return focus[:8]


def _theme_score_map(text: str) -> Counter[str]:
    normalized = _clean_markup(text)
    scores: Counter[str] = Counter()
    for theme, keywords in _AI_THEME_RULES:
        score = sum(_keyword_hits(normalized.lower(), keyword) for keyword in keywords)
        if theme == "PCB/电子布/电子材料":
            if _has_keyword(normalized, "PCB"):
                score += 3
            if "电子布" in normalized:
                score += 2
        if score:
            scores[theme] = score
    return scores


def _top_theme_candidates(text: str, limit: int = 3) -> list[str]:
    return [theme for theme, _ in _theme_score_map(text).most_common(limit)]


def _infer_theme(text: str) -> str:
    scores = _theme_score_map(text)
    return scores.most_common(1)[0][0] if scores else "其他待复核"


def _infer_implication(text: str) -> str:
    theme = _infer_theme(text)
    return _AI_IMPLICATIONS.get(theme, "作为普通线索保留，需结合原文、公告、量价和第二来源复核。")


def _infer_impact_chain(text: str) -> str:
    theme = _infer_theme(text)
    return _AI_IMPACT_CHAINS.get(theme, "事件事实 -> 产业或市场预期变化 -> 等待第二来源和量价确认。")


def _infer_catalysts(text: str) -> list[str]:
    normalized = _clean_markup(text)
    catalysts = [key for key in _AI_CATALYST_KEYS if key.lower() in normalized.lower()]
    return catalysts[:5] or ["待复核后续公告、订单、业绩或价格信号。"]


def _infer_risks(text: str) -> list[str]:
    normalized = _clean_markup(text)
    risks: list[str] = []
    for pattern in (r"风险提示[:：]?([^。；\n]{2,80})", r"不及预期", r"监管", r"供应", r"价格"):
        match = re.search(pattern, normalized)
        if match:
            risks.append(_short_text(match.group(0), 80))
    return risks[:3] or ["缺少第二来源或量价确认，暂不作为确定性结论。"]


def _priority_score(item: Mapping[str, Any]) -> int:
    if item.get("status_item") or item.get("credibility_warning"):
        return -20
    score = {"L4": 6, "L3": 4, "L2": 2, "L1": 0}.get(str(item.get("evidence_level")), 0)
    if item.get("theme") and item.get("theme") != "其他待复核":
        score += 2
    if item.get("source_type") == "ZSXQ":
        score += 3
    elif item.get("source_type") == "finance":
        score += 1
    if item.get("freshness_label") == "本小时新增":
        score += 4
    if item.get("freshness_label") == "本轮抓取":
        score += 1
    score += min(
        4,
        2
        * sum(
            1
            for key in ("target_price", "rating", "earnings_forecast", "valuation_assumption")
            if item.get(key)
        ),
    )
    if item.get("stock_focus"):
        score += 2
    if item.get("source_url"):
        score += 1
    if len(str(item.get("event_fact") or "")) >= 80:
        score += 1
    if any(marker in clean_text(item.get("title")) for marker in ("周报", "复盘", "舆情热点", "全天涨停复盘", "市场+宏观", "市场综述", "市场终评", "交易台")):
        score -= 4
    if len(item.get("stock_focus") or []) >= 6:
        score -= 2
    return score


def _absolute_http_url(value: Any, fallback: Any = "") -> str:
    candidate = clean_text(value)
    base = clean_text(fallback)
    joined = urllib.parse.urljoin(base, candidate) if candidate else base
    parsed = urllib.parse.urlparse(joined)
    return joined if parsed.scheme in {"http", "https"} and bool(parsed.netloc) else ""


def _score_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def google_rss_url(query: str, lookback_days: int = 2) -> str:
    if lookback_days < 0:
        raise ValueError("lookback_days must be non-negative")
    params = {
        "q": f"{query} when:{lookback_days}d",
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    return f"{GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"


def fetch_url(
    url: str,
    timeout: int = 20,
    *,
    transport: ProxyAwareHTTPTransport | None = None,
) -> bytes:
    """Fetch one public URL through the bounded proxy-aware transport."""
    result = (transport or _default_http_transport()).fetch(url, timeout=timeout)
    return result.body


class _GoogleNewsParamsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.params: dict[str, str] = {}

    def handle_starttag(
        self, tag: str, attrs_list: list[tuple[str, str | None]]
    ) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        if (
            tag == "div"
            and attrs.get("data-n-a-sg")
            and attrs.get("data-n-a-ts")
        ):
            self.params = attrs


def decode_google_news_url(
    source_url: str,
    timeout: int = 15,
    *,
    opener=urllib.request.urlopen,
) -> str:
    """Resolve one Google News discovery URL to the publisher article URL.

    Google News serves signed redirect parameters in the article page.  The
    read-only ``Fbv4je`` endpoint converts those parameters to the publisher
    URL; the result is rejected unless it is a non-Google HTTP(S) URL.
    """
    parsed = urllib.parse.urlsplit(str(source_url or ""))
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.hostname != "news.google.com" or len(parts) < 2 or parts[-2] not in {
        "articles",
        "read",
    }:
        return str(source_url or "")
    token = parts[-1]
    params: dict[str, str] = {}
    for prefix in (
        "https://news.google.com/articles/",
        "https://news.google.com/rss/articles/",
    ):
        request = urllib.request.Request(
            prefix + token,
            headers={"User-Agent": USER_AGENT},
        )
        try:
            with opener(request, timeout=timeout) as response:
                page = response.read().decode("utf-8", errors="replace")
        except (TimeoutError, urllib.error.URLError, OSError):
            continue
        parser = _GoogleNewsParamsParser()
        parser.feed(page)
        if parser.params:
            params = parser.params
            break
    signature = params.get("data-n-a-sg")
    timestamp = params.get("data-n-a-ts")
    if not signature or not timestamp or not timestamp.isdigit():
        raise ValueError("Google News decoding parameters unavailable")
    request_payload = [
        "garturlreq",
        [
            [
                "X",
                "X",
                ["X", "X"],
                None,
                None,
                1,
                1,
                "US:en",
                None,
                1,
                None,
                None,
                None,
                None,
                None,
                0,
                1,
            ],
            "X",
            "X",
            1,
            [1, 1, 1],
            1,
            1,
            None,
            0,
            0,
            None,
            0,
        ],
        token,
        int(timestamp),
        signature,
    ]
    rpc = [
        "Fbv4je",
        json.dumps(request_payload, ensure_ascii=False, separators=(",", ":")),
        None,
        "generic",
    ]
    body = urllib.parse.urlencode(
        {"f.req": json.dumps([[rpc]], ensure_ascii=False, separators=(",", ":"))}
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": USER_AGENT,
        },
    )
    with opener(request, timeout=timeout) as response:
        response_text = response.read().decode("utf-8", errors="replace")
    chunks = response_text.split("\n\n")
    if len(chunks) < 2:
        raise ValueError("Google News decoder response is incomplete")
    records = json.loads(chunks[1])
    decoded = ""
    for record in records:
        if not isinstance(record, list) or len(record) < 3 or not record[2]:
            continue
        inner = json.loads(record[2])
        if isinstance(inner, list) and len(inner) > 1:
            decoded = str(inner[1] or "").strip()
            if decoded:
                break
    final = urllib.parse.urlsplit(decoded)
    if (
        final.scheme not in {"http", "https"}
        or not final.hostname
        or final.hostname == "news.google.com"
    ):
        raise ValueError("Google News decoder did not return a publisher URL")
    return decoded


def _map_ah_relevance(
    title: str, description: str, subscription_id: str
) -> list[str]:
    haystack = f"{title} {description}".lower()
    mapped: list[str] = []
    for needle, labels in AH_KEYWORDS:
        if needle in haystack:
            for label in labels:
                if label not in mapped:
                    mapped.append(label)
    if subscription_id in {
        "authority_china_hk",
        "china_hk_stocks",
        "china_tech_ai_semis",
        "hk_ipo_new_economy",
    } and "A/H股票复核" not in mapped:
        mapped.append("A/H股票复核")
    return mapped[:8]


def _v3_local_chinese_title(row: Mapping[str, Any], mappings: list[str]) -> str:
    title = clean_text(row.get("title"))
    lowered = title.lower()
    source = clean_text(row.get("source_name") or row.get("source"))
    source_cn = SOURCE_CN_LABELS.get(source, source or "外媒")
    theme_bucket = clean_text(row.get("theme_bucket"))
    theme = THEME_LABELS.get(theme_bucket, theme_bucket or "外部财经")
    event_class = clean_text(row.get("external_event_class"))
    if "zhongji innolight" in lowered:
        return "中际旭创据称考虑赴港上市，AI光模块/CPO链需要重点复核"
    if "kingboard laminates" in lowered:
        return "建滔积层板受AI服务器材料重估带动，复核PCB/覆铜板链"
    if "deepseek" in lowered:
        return "DeepSeek相关动态升温，复核中国AI应用和算力链外溢"
    if "humanoid robots" in lowered:
        return "人形机器人产业动态更新，复核执行器、传感器和控制器链"
    if "hang seng index" in lowered:
        return "恒生指数与利率预期变化，复核港股流动性和中国资产风险偏好"
    if event_class == "IPO_LISTING" and mappings:
        return f"海外媒体提示IPO线索，复核{'、'.join(mappings[:3])}"
    if event_class == "EARNINGS" and mappings:
        return f"海外媒体提示业绩线索，复核{'、'.join(mappings[:3])}"
    if event_class == "POLICY_REGULATION" and mappings:
        return f"海外媒体提示政策监管线索，复核{'、'.join(mappings[:3])}"
    if mappings:
        return f"{source_cn}提示{theme}线索，复核{'、'.join(mappings[:3])}"
    return f"{source_cn}提示{theme}线索，保留研究观察"


def _v3_local_summary(row: Mapping[str, Any], mappings: list[str]) -> str:
    source = clean_text(row.get("source_name") or row.get("source"))
    source_cn = SOURCE_CN_LABELS.get(source, source or "Google News RSS")
    theme_bucket = clean_text(row.get("theme_bucket"))
    theme = THEME_LABELS.get(theme_bucket, theme_bucket or "外部财经")
    mapping_text = "、".join(mappings) if mappings else "暂未映射到具体A/H标的，保留主题观察"
    published_at = clean_text(row.get("published_at")) or "发布时间未确认"
    return (
        f"来源：{source_cn}；发布时间：{published_at}；主题：{theme}；"
        f"A/H复核方向：{mapping_text}。英文原题保留在证据字段。"
    )


def _localize_external_row(source_row: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(source_row)
    mappings = _map_ah_relevance(
        clean_text(row.get("title")),
        clean_text(row.get("summary")),
        clean_text(row.get("subscription_id")),
    )
    row["ah_mapping"] = mappings
    row["theme_label"] = THEME_LABELS.get(
        clean_text(row.get("theme_bucket")), clean_text(row.get("theme_bucket"))
    )
    row["title_zh"] = _v3_local_chinese_title(row, mappings)
    row["summary_zh"] = _v3_local_summary(row, mappings)
    row["translation_status"] = "READY"
    row["translation_source"] = "V3_LOCAL_RULES"
    row["cannot_confirm"] = sorted(
        item
        for item in set(row.get("cannot_confirm") or [])
        if item != "ZH_TRANSLATION_FAILED"
    )
    return row


def _normalize_chinese_finance_translation(value: str) -> str:
    text = clean_text(value)
    replacements = (
        ("HK$", "港元"),
        ("US$", "美元"),
        ("亿$", "亿美元"),
        ("$", "美元"),
        ("灵喜游戏", "灵犀游戏"),
        ("英维迪亚", "英伟达"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return text


_WESTERN_AMOUNT_RE = re.compile(
    r"(?:(?P<prefix>US\$|HK\$|C\$|A\$|NZ\$|S\$|USD|HKD|EUR|GBP|CNY|RMB|JPY|JP¥|\$|€|£|¥)\s*"
    r"(?P<prefix_number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<prefix_unit>trillion|billion|million|thousand|tn|bn|mn|k|m|b)?"
    r"|(?P<suffix_number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<suffix_unit>trillion|billion|million|thousand|tn|bn|mn|k|m|b)\s*"
    r"(?P<suffix>USD|HKD|EUR|GBP|CNY|RMB|JPY|JP¥|US\$|HK\$|€|£|¥))",
    re.IGNORECASE,
)
_CHINESE_AMOUNT_RE = re.compile(
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>万亿|十亿|亿|千万|百万|十万|万|千)?\s*"
    r"(?P<currency>美元|美金|港元|港币|欧元|英镑|人民币|日元|日圆|元)"
)
_FINANCE_UNIT_MULTIPLIERS = {
    "trillion": 1_000_000_000_000,
    "tn": 1_000_000_000_000,
    "billion": 1_000_000_000,
    "bn": 1_000_000_000,
    "million": 1_000_000,
    "mn": 1_000_000,
    "thousand": 1_000,
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "万亿": 1_000_000_000_000,
    "十亿": 1_000_000_000,
    "亿": 100_000_000,
    "千万": 10_000_000,
    "百万": 1_000_000,
    "十万": 100_000,
    "万": 10_000,
    "千": 1_000,
}
_FINANCE_CURRENCY_ALIASES = {
    "US$": "USD",
    "$": "USD",
    "USD": "USD",
    "HK$": "HKD",
    "HKD": "HKD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "¥": "CNY",
    "CNY": "CNY",
    "RMB": "CNY",
    "JPY": "JPY",
    "JP¥": "JPY",
    "美元": "USD",
    "美金": "USD",
    "港元": "HKD",
    "港币": "HKD",
    "欧元": "EUR",
    "英镑": "GBP",
    "人民币": "CNY",
    "元": "CNY",
    "日元": "JPY",
    "日圆": "JPY",
}


def _finance_amounts(value: Any) -> list[tuple[str, float]]:
    text = clean_text(value)
    amounts: list[tuple[str, float]] = []
    occupied: list[tuple[int, int]] = []

    def add(start: int, end: int, currency: str, number: str, unit: str = "") -> None:
        if any(start < old_end and end > old_start for old_start, old_end in occupied):
            return
        try:
            numeric = float(number.replace(",", ""))
        except (TypeError, ValueError):
            return
        multiplier = _FINANCE_UNIT_MULTIPLIERS.get(unit.lower(), _FINANCE_UNIT_MULTIPLIERS.get(unit, 1))
        amounts.append((currency, numeric * multiplier))
        occupied.append((start, end))

    for match in _WESTERN_AMOUNT_RE.finditer(text):
        if match.group("prefix_number"):
            raw_currency = match.group("prefix") or ""
            raw_number = match.group("prefix_number")
            raw_unit = match.group("prefix_unit") or ""
        else:
            raw_currency = match.group("suffix") or ""
            raw_number = match.group("suffix_number")
            raw_unit = match.group("suffix_unit") or ""
        currency = _FINANCE_CURRENCY_ALIASES.get(raw_currency.upper(), _FINANCE_CURRENCY_ALIASES.get(raw_currency, ""))
        if currency:
            add(match.start(), match.end(), currency, raw_number, raw_unit)
    for match in _CHINESE_AMOUNT_RE.finditer(text):
        currency = _FINANCE_CURRENCY_ALIASES.get(match.group("currency"), "")
        if currency:
            add(
                match.start(),
                match.end(),
                currency,
                match.group("number"),
                match.group("unit") or "",
            )
    return amounts


def _validate_finance_translation(source: Any, translated: Any) -> bool:
    """Check currency and order of magnitude before admitting translated text."""
    expected = _finance_amounts(source)
    if not expected:
        return True
    actual = _finance_amounts(translated)
    if len(expected) != len(actual):
        return False
    for (expected_currency, expected_value), (actual_currency, actual_value) in zip(expected, actual, strict=True):
        if expected_currency != actual_currency:
            return False
        tolerance = max(0.01, abs(expected_value) * 0.02)
        if abs(expected_value - actual_value) > tolerance:
            return False
    return True


def _resolve_original_row(
    source_row: Mapping[str, Any],
    *,
    resolver: OriginalUrlResolver,
    timeout: int,
) -> dict[str, Any]:
    row = dict(source_row)
    discovery_url = clean_text(
        row.get("discovery_url") or row.get("url") or row.get("source_url")
    )
    row["discovery_url"] = discovery_url
    try:
        resolved = str(resolver(discovery_url, timeout)).strip()
        parsed = urllib.parse.urlsplit(resolved)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.hostname == "news.google.com"
            or not _is_article_url(resolved)
        ):
            raise ValueError("publisher URL is not verified")
        row["original_url"] = resolved
        row["original_url_status"] = "VERIFIED_PUBLISHER_URL"
        row["url"] = resolved
        row["source_url"] = resolved
        row["cannot_confirm"] = sorted(
            item
            for item in set(row.get("cannot_confirm") or [])
            if item != "ORIGINAL_URL_UNRESOLVED"
        )
    except (TimeoutError, TransportError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        row["original_url"] = ""
        row["original_url_status"] = "CANNOT_CONFIRM"
        row["url"] = ""
        row["source_url"] = clean_text(row.get("source_page_url"))
        row["cannot_confirm"] = sorted(
            set(row.get("cannot_confirm") or []) | {"ORIGINAL_URL_UNRESOLVED"}
        )
    return row


def _resolve_original_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    resolver: OriginalUrlResolver,
    timeout: int,
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    workers = max(1, min(int(max_workers), len(rows)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda row: _resolve_original_row(
                    row, resolver=resolver, timeout=timeout
                ),
                rows,
            )
        )


def google_translate_zh(value: str, timeout: int = 20) -> str:
    """Translate public-source text to Simplified Chinese via a read-only endpoint."""
    source_text = str(value or "").strip()
    if not source_text:
        return ""
    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "auto",
            "tl": "zh-CN",
            "dt": "t",
            "q": source_text,
        }
    )
    raw = fetch_url(f"{GOOGLE_TRANSLATE}?{query}", timeout=timeout)
    payload = json.loads(raw.decode("utf-8"))
    segments = payload[0] if isinstance(payload, list) and payload else []
    translated = "".join(
        str(segment[0])
        for segment in segments
        if isinstance(segment, list) and segment and segment[0]
    ).strip()
    if not translated:
        raise ValueError("translation endpoint returned no text")
    return translated


def mymemory_translate_zh(
    value: str,
    timeout: int = 20,
    *,
    opener=urllib.request.urlopen,
) -> str:
    """Translate one public headline through MyMemory's read-only endpoint."""
    source_text = str(value or "").strip()
    if not source_text:
        return ""
    query = urllib.parse.urlencode(
        {"q": source_text[:500], "langpair": "en|zh-CN"}
    )
    request = urllib.request.Request(
        f"{MYMEMORY_TRANSLATE}?{query}", headers={"User-Agent": USER_AGENT}
    )
    with opener(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    translated = clean_text(
        (payload.get("responseData") or {}).get("translatedText")
        if isinstance(payload, Mapping)
        else ""
    )
    if (
        not isinstance(payload, Mapping)
        or int(payload.get("responseStatus") or 0) != 200
        or not translated
        or not _CJK.search(translated)
    ):
        raise ValueError("MyMemory returned no verified Chinese translation")
    return translated


def public_translate_zh(value: str, timeout: int = 20) -> str:
    """Translate a public headline with a bounded provider fallback chain."""
    errors: list[Exception] = []
    for translator in (mymemory_translate_zh, google_translate_zh):
        try:
            return translator(value, timeout)
        except (TimeoutError, TransportError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
            errors.append(error)
    raise ValueError("public translation providers unavailable") from errors[-1]


def _call_translator(translator: TranslateFn, value: str, timeout: int) -> str:
    try:
        return str(translator(value, timeout))
    except TypeError as first_error:
        try:
            return str(translator(value))
        except TypeError:
            raise first_error


def _original_url(row: Mapping[str, Any]) -> str:
    base = clean_text(row.get("source_url"))
    candidate = clean_text(row.get("original_url") or row.get("url") or base)
    return urllib.parse.urljoin(base, candidate) if candidate else ""


def _translate_row(
    source_row: Mapping[str, Any],
    *,
    translate_text: TranslateFn,
    timeout: int,
) -> dict[str, Any]:
    row = dict(source_row)
    if clean_text(row.get("subscription_id")):
        localized = _localize_external_row(row)
        title = clean_text(localized.get("title"))
        try:
            translated_title = _normalize_chinese_finance_translation(
                _call_translator(translate_text, title, timeout)
            )
            if not translated_title or not _CJK.search(translated_title):
                raise ValueError("event title translation is not Chinese")
            if not _validate_finance_translation(title, translated_title):
                raise ValueError("event title translation amount or currency mismatch")
            localized["title_zh"] = clean_text(translated_title)
            localized["summary_zh"] = (
                f"事件：{localized['title_zh']}。"
                + _v3_local_summary(localized, list(localized.get("ah_mapping") or []))
            )
            localized["translation_status"] = "READY"
            localized["translation_source"] = "PUBLIC_MACHINE_TRANSLATION"
            localized["cannot_confirm"] = sorted(
                item
                for item in set(localized.get("cannot_confirm") or [])
                if item != "ZH_TRANSLATION_FAILED"
            )
        except (TimeoutError, TransportError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
            localized.pop("title_zh", None)
            localized.pop("summary_zh", None)
            localized["translation_status"] = "CANNOT_CONFIRM"
            localized["translation_source"] = "V3_LOCAL_RULES_FALLBACK"
            localized["cannot_confirm"] = sorted(
                set(localized.get("cannot_confirm") or [])
                | {
                    "ZH_TRANSLATION_AMOUNT_MISMATCH"
                    if "amount or currency mismatch" in str(error)
                    else "ZH_TRANSLATION_FAILED"
                }
            )
        return localized
    title = clean_text(row.get("title"))
    summary = clean_text(row.get("summary"))
    row["original_url"] = _original_url(row)
    existing_title_zh = clean_text(row.get("title_zh"))
    existing_summary_zh = clean_text(row.get("summary_zh"))
    needs_title = bool(title and not existing_title_zh and not _CJK.search(title))
    needs_summary = bool(summary and not existing_summary_zh and not _CJK.search(summary))
    if not needs_title:
        row["title_zh"] = existing_title_zh or title
    if not needs_summary:
        row["summary_zh"] = existing_summary_zh or summary
    if not needs_title and not needs_summary:
        if (
            existing_title_zh
            and not _validate_finance_translation(title, existing_title_zh)
        ) or (
            existing_summary_zh
            and not _validate_finance_translation(summary, existing_summary_zh)
        ):
            row["translation_status"] = "CANNOT_CONFIRM"
            row["translation_source"] = ""
            row["cannot_confirm"] = sorted(
                set(row.get("cannot_confirm") or []) | {"ZH_TRANSLATION_AMOUNT_MISMATCH"}
            )
            return row
        row["translation_status"] = (
            "READY" if existing_title_zh or existing_summary_zh else "NOT_REQUIRED"
        )
        if existing_title_zh or existing_summary_zh:
            row.setdefault("translation_source", "EXISTING_VERIFIED_TRANSLATION")
        return row

    fields: list[str] = []
    values: list[str] = []
    if needs_title:
        fields.append("title_zh")
        values.append(title)
    if needs_summary:
        fields.append("summary_zh")
        values.append(summary)
    try:
        translated = _call_translator(translate_text, "\n".join(values), timeout)
        pieces = [part.strip() for part in translated.split("\n", len(values) - 1)]
        if len(pieces) != len(values) or any(not part for part in pieces):
            raise ValueError("translation field boundary was not preserved")
        for field, value in zip(fields, pieces, strict=True):
            source_value = title if field == "title_zh" else summary
            if not _validate_finance_translation(source_value, value):
                raise ValueError(f"{field} translation amount or currency mismatch")
            row[field] = value
        row["translation_status"] = "READY"
        row["translation_source"] = "GOOGLE_TRANSLATE_PUBLIC_READ_ONLY"
        row["cannot_confirm"] = sorted(
            item
            for item in set(row.get("cannot_confirm") or [])
            if item != "ZH_TRANSLATION_FAILED"
        )
    except (TimeoutError, TransportError, urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as error:
        row["translation_status"] = "CANNOT_CONFIRM"
        row["translation_source"] = ""
        row["cannot_confirm"] = sorted(
            set(row.get("cannot_confirm") or [])
            | {
                "ZH_TRANSLATION_AMOUNT_MISMATCH"
                if "amount or currency mismatch" in str(error)
                else "ZH_TRANSLATION_FAILED"
            }
        )
    return row


def _translate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    translate_text: TranslateFn,
    timeout: int,
    max_workers: int = 6,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    workers = max(1, min(int(max_workers), len(rows)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(
            executor.map(
                lambda row: _translate_row(
                    row,
                    translate_text=translate_text,
                    timeout=timeout,
                ),
                rows,
            )
        )


def _call_fetcher(fetcher: FetchFn, url: str, timeout: int) -> bytes | str | FetchResult:
    try:
        return fetcher(url, timeout)
    except TypeError as first_error:
        try:
            return fetcher(url)
        except TypeError:
            raise first_error


def _element_text(parent: ET.Element, local_name: str) -> str:
    for child in parent:
        if child.tag.rsplit("}", 1)[-1] == local_name:
            return html.unescape((child.text or "").strip())
    return ""


def _source_of(item: ET.Element) -> tuple[str, str]:
    for child in item:
        if child.tag.rsplit("}", 1)[-1] == "source":
            return clean_text(child.text), str(child.attrib.get("url") or "")
    return "", ""


def parse_rss_date(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0)


def strip_title_source(title: str, source_name: str) -> str:
    normalized = clean_text(title)
    if source_name and normalized.lower().endswith(f" - {source_name.lower()}"):
        normalized = normalized[: -(len(source_name) + 3)].strip()
    return normalized


def normalize_key(title: str) -> str:
    lowered = clean_text(title).lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def source_tier(source_name: str, title: str) -> str:
    haystack = f"{source_name} {title}".lower()
    for needle, tier in SOURCE_TIER_PATTERNS:
        if needle in haystack:
            return tier
    return "T4: Aggregated"


def _tier_score(tier: str) -> int:
    if tier.startswith("T1"):
        return 35
    if tier.startswith("T2"):
        return 25
    if tier.startswith("T3"):
        return 14
    return 6


def _is_negative(title: str, description: str, source_name: str) -> bool:
    haystack = f"{title} {description} {source_name}".lower()
    if any(pattern in haystack for pattern in NEGATIVE_PATTERNS):
        return True
    key = normalize_key(title)
    return key in GENERIC_TITLES or len(key.split()) < 3


def _is_high_signal(row: Mapping[str, Any]) -> bool:
    tier = str(row.get("source_tier") or "")
    source = str(row.get("source_name") or "").lower()
    return tier.startswith(("T1", "T2", "T3")) or any(
        pattern in source for pattern in ALLOWED_NICHE_SOURCES
    )


def _event_class(title: str, description: str) -> str:
    haystack = f"{title} {description}".lower()
    if "ipo" in haystack or "listing" in haystack:
        return "IPO_LISTING"
    if any(word in haystack for word in ("earnings", "profit", "revenue")):
        return "EARNINGS"
    if any(word in haystack for word in ("policy", "tariff", "regulator")):
        return "POLICY_REGULATION"
    if any(word in haystack for word in ("acquisition", "deal", "merger")):
        return "M_A_DEAL"
    return "MARKET_SIGNAL"


def parse_rss_items(
    raw_xml: bytes | str,
    *,
    subscription_id: str,
    theme_bucket: str,
    fetched_at: datetime | str,
    source_url: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    raw = raw_xml.encode("utf-8") if isinstance(raw_xml, str) else raw_xml
    root = ET.fromstring(raw)
    fetched_iso = isoformat_utc(fetched_at)
    fetched_dt = _coerce_datetime(fetched_at)
    rows: list[dict[str, Any]] = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] != "item":
            continue
        raw_title = _element_text(item, "title")
        source_name, source_page = _source_of(item)
        title = strip_title_source(raw_title, source_name)
        description = re.sub(r"<[^>]+>", " ", _element_text(item, "description"))
        description = clean_text(description)
        if not title or _is_negative(title, description, source_name):
            continue
        published_dt = parse_rss_date(_element_text(item, "pubDate"))
        published_iso = isoformat_utc(published_dt) if published_dt else ""
        tier = source_tier(source_name, title)
        age_score = 0
        if published_dt:
            age_hours = max((fetched_dt - published_dt).total_seconds() / 3600, 0)
            age_score = 12 if age_hours <= 6 else 8 if age_hours <= 24 else 3 if age_hours <= 72 else 0
        link = clean_text(_element_text(item, "link"))
        score = _tier_score(tier) + age_score
        stable_id = hashlib.sha256(
            f"{normalize_key(title)}|{source_name}|{published_iso}".encode("utf-8")
        ).hexdigest()[:16]
        rows.append(
            {
                "id": stable_id,
                "title": title,
                "evidence_title_en": title,
                "summary": description or title,
                "published_at": published_iso,
                "fetched_at": fetched_iso,
                "source": source_name or source_page or "Google News RSS",
                "source_name": source_name or source_page or "Google News RSS",
                "source_tier": tier,
                "source_url": source_page or link or source_url,
                "source_page_url": source_page,
                "discovery_url": link or source_url,
                "url": link,
                "original_url": "",
                "original_url_status": "PENDING_RESOLUTION",
                "subscription_id": subscription_id,
                "theme_bucket": theme_bucket,
                "external_event_class": _event_class(title, description),
                "score": score,
                "cannot_confirm": ["GOOGLE_NEWS_RSS_DISCOVERY_ONLY"],
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
        if len(rows) >= max(0, limit):
            break
    return rows


def dedupe_and_rank(
    rows: Sequence[Mapping[str, Any]],
    max_items: int = 36,
    *,
    fetched_at: datetime | str | None = None,
    lookback_days: int = 2,
    rejected_reasons: list[str] | None = None,
) -> list[dict[str, Any]]:
    best_by_key: dict[str, dict[str, Any]] = {}
    for source_row in rows:
        row = dict(source_row)
        reasons = _row_admission_reasons(
            row,
            fetched_at=fetched_at,
            lookback_days=lookback_days,
        )
        if reasons:
            if rejected_reasons is not None:
                rejected_reasons.extend(reasons)
            continue
        if not _is_high_signal(row):
            continue
        key = normalize_key(str(row.get("title") or ""))
        if not key:
            continue
        previous = best_by_key.get(key)
        if previous is None or int(row.get("score") or 0) > int(previous.get("score") or 0):
            best_by_key[key] = row
    return sorted(
        best_by_key.values(),
        key=lambda row: (
            int(row.get("score") or 0),
            str(row.get("published_at") or row.get("fetched_at") or ""),
            str(row.get("id") or ""),
        ),
        reverse=True,
    )[: max(0, max_items)]


def overview_from_details(details: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    overview: list[dict[str, Any]] = []
    seen_theme: set[str] = set()
    for row in details:
        theme = str(row.get("theme_bucket") or "")
        if theme and theme in seen_theme and len(overview) >= 8:
            continue
        if theme:
            seen_theme.add(theme)
        overview.append(
            {
                "id": row.get("id"),
                "title": row.get("title"),
                "title_zh": row.get("title_zh"),
                "summary": row.get("summary"),
                "summary_zh": row.get("summary_zh"),
                "source_name": row.get("source_name"),
                "source_url": row.get("source_url"),
                "url": row.get("url"),
                "original_url": row.get("original_url"),
                "fetched_at": row.get("fetched_at"),
                "published_at": row.get("published_at"),
                "source_tier": row.get("source_tier"),
                "theme_bucket": row.get("theme_bucket"),
                "cannot_confirm": list(row.get("cannot_confirm") or []),
                "translation_status": row.get("translation_status"),
                "translation_source": row.get("translation_source"),
                "recommendation_status": "RESEARCH_ONLY",
            }
        )
        if len(overview) >= 12:
            break
    return overview


def _base_payload(
    *,
    trade_date: str,
    source: str,
    status: str,
    source_url: str,
    fetched_at: str,
    raw_item_count: int,
    item_count: int,
    overview: list[dict[str, Any]],
    details: list[dict[str, Any]],
    items: list[dict[str, Any]],
    cannot_confirm: Sequence[str],
    feed_receipts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": "v3_5.research_peripheral.v1",
        "trade_date": _date(trade_date),
        "source": source,
        "status": status,
        "source_url": source_url,
        "fetched_at": fetched_at,
        "raw_item_count": int(raw_item_count),
        "item_count": int(item_count),
        "overview": overview,
        "details": details,
        "items": items,
        "cannot_confirm": sorted(set(str(item) for item in cannot_confirm if str(item))),
        "write_policy": "read_only",
        "recommendation_status": "RESEARCH_ONLY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if feed_receipts is not None:
        payload["feed_receipts"] = [dict(receipt) for receipt in feed_receipts]
    return payload


def _feed_receipt(
    feed_id: str,
    url: str,
    receipt: Mapping[str, Any] | None = None,
    *,
    error: str | None = None,
) -> dict[str, Any]:
    """Normalize transport evidence into a stable per-feed contract."""
    source = dict(receipt or {})
    elapsed = source.get("elapsed_ms", 0)
    try:
        elapsed_ms = max(0, int(elapsed))
    except (TypeError, ValueError):
        elapsed_ms = 0
    status = source.get("http_status")
    if status is not None:
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None
    return {
        "feed_id": str(feed_id),
        "url": str(url),
        "elapsed_ms": elapsed_ms,
        "http_status": status,
        "error": error if error is not None else source.get("error"),
        "proxy_used": bool(source.get("proxy_used", False)),
        "fallback_used": bool(source.get("fallback_used", False)),
    }


def _fetch_feed(
    fetcher: FetchFn,
    url: str,
    timeout: int,
    *,
    transport: ProxyAwareHTTPTransport | None = None,
) -> tuple[bytes | str, dict[str, Any]]:
    """Fetch one feed and retain transport metadata for its source receipt."""
    if fetcher is fetch_url:
        result = (transport or _default_http_transport()).fetch(url, timeout=timeout)
    else:
        result = _call_fetcher(fetcher, url, timeout)
    if isinstance(result, FetchResult):
        return result.body, dict(result.receipt)
    return result, {
        "elapsed_ms": 0,
        "http_status": None,
        "error": None,
        "proxy_used": False,
        "fallback_used": False,
    }


def build_external_finance_payload(
    trade_date: str,
    *,
    fetched_at: datetime | str | None = None,
    fetch_rss: FetchFn | None = None,
    subscriptions: Sequence[Mapping[str, str]] = DEFAULT_SUBSCRIPTIONS,
    lookback_days: int = 2,
    limit_per_feed: int = 10,
    max_items: int = 36,
    timeout: int = 20,
    translate_text: TranslateFn | None = None,
    resolve_original_url: OriginalUrlResolver | None = None,
    transport: ProxyAwareHTTPTransport | None = None,
) -> dict[str, Any]:
    selected_date = _date(trade_date)
    fetched_dt = _coerce_datetime(fetched_at)
    fetched_iso = isoformat_utc(fetched_dt)
    fetcher = fetch_rss or fetch_url
    rows: list[dict[str, Any]] = []
    cannot_confirm: list[str] = ["GOOGLE_NEWS_RSS_DISCOVERY_ONLY"]
    source_urls: list[str] = []
    feed_receipts: list[dict[str, Any]] = []
    fetch_failures = 0
    for subscription in subscriptions:
        normalized = {str(key): str(value) for key, value in subscription.items()}
        feed_url = google_rss_url(normalized["query"], lookback_days)
        source_urls.append(feed_url)
        try:
            raw_xml, receipt = _fetch_feed(
                fetcher,
                feed_url,
                timeout,
                transport=transport,
            )
            rows.extend(
                parse_rss_items(
                    raw_xml,
                    subscription_id=normalized["id"],
                    theme_bucket=normalized.get("theme_bucket", normalized["id"]),
                    fetched_at=fetched_dt,
                    source_url=feed_url,
                    limit=limit_per_feed,
                )
            )
            feed_receipts.append(_feed_receipt(normalized["id"], feed_url, receipt))
        except TransportError as error:
            fetch_failures += 1
            feed_receipts.append(
                _feed_receipt(
                    normalized["id"],
                    feed_url,
                    getattr(error, "receipt", None),
                    error=(getattr(error, "receipt", {}) or {}).get("error")
                    or f"{type(error).__name__}:{error}",
                )
            )
            cannot_confirm.append(f"EXTERNAL_FINANCE_FETCH_FAILED:{normalized['id']}")
        except (ET.ParseError, TimeoutError, urllib.error.URLError, OSError, ValueError) as error:
            fetch_failures += 1
            feed_receipts.append(
                _feed_receipt(
                    normalized["id"],
                    feed_url,
                    error=f"{type(error).__name__}:{error}",
                )
            )
            cannot_confirm.append(f"EXTERNAL_FINANCE_FETCH_FAILED:{normalized['id']}")
    admission_rejections: list[str] = []
    details = dedupe_and_rank(
        rows,
        max_items=max_items,
        fetched_at=fetched_dt,
        lookback_days=lookback_days,
        rejected_reasons=admission_rejections,
    )
    if resolve_original_url is not None:
        details = _resolve_original_rows(
            details,
            resolver=resolve_original_url,
            timeout=timeout,
        )
        if any(
            row.get("original_url_status") != "VERIFIED_PUBLISHER_URL"
            for row in details
        ):
            cannot_confirm.append("ORIGINAL_URL_INCOMPLETE")
        details, resolved_rejections = _admit_external_rows(
            details,
            fetched_at=fetched_dt,
            lookback_days=lookback_days,
        )
        admission_rejections.extend(resolved_rejections)
    cannot_confirm.extend(admission_rejections)
    translation_incomplete = False
    if translate_text is not None:
        details = _translate_rows(
            details,
            translate_text=translate_text,
            timeout=timeout,
        )
        translation_incomplete = any(
            row.get("translation_status") == "CANNOT_CONFIRM" for row in details
        )
        if translation_incomplete:
            cannot_confirm.append("ZH_TRANSLATION_INCOMPLETE")
    status = (
        "CANNOT_CONFIRM"
        if details and translation_incomplete
        else "READY"
        if details
        else "CANNOT_CONFIRM"
        if fetch_failures or admission_rejections
        else "READY_EMPTY"
    )
    return _base_payload(
        trade_date=selected_date,
        source="external_finance",
        status=status,
        source_url=GOOGLE_NEWS_RSS,
        fetched_at=fetched_iso,
        raw_item_count=len(rows),
        item_count=len(details),
        overview=overview_from_details(details),
        details=details,
        items=[],
        cannot_confirm=cannot_confirm,
        feed_receipts=feed_receipts,
    )


class AIHotParser(HTMLParser):
    """Small deterministic parser for the public AIHot timeline markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, Any]] = []
        self.pending: dict[str, Any] | None = None
        self.current: dict[str, Any] | None = None
        self.capture_stack: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set((attrs.get("class") or "").split())
        if tag == "div" and "timeline-item" in classes:
            self.pending = {
                "time": "",
                "selected": "timeline-item-selected" in classes,
            }
        if self.pending is not None and "timeline-time" in classes:
            self.capture_stack.append((tag, "time"))
        if tag == "article" and self.pending is not None:
            self.current = self.pending
            self.pending = None
            self.current.setdefault("tags", [])
        if self.current is None:
            return
        if tag == "div" and attrs.get("data-item-id"):
            self.current["item_id"] = attrs["data-item-id"]
        elif "timeline-source" in classes:
            self.capture_stack.append((tag, "source"))
        elif "uc-handle" in classes:
            self.capture_stack.append((tag, "handle"))
        elif "timeline-score" in classes:
            self.capture_stack.append((tag, "score"))
        elif tag == "a" and "timeline-title" in classes:
            self.current["url"] = attrs.get("href", "")
            self.capture_stack.append((tag, "title"))
        elif tag == "p" and "timeline-summary" in classes:
            self.capture_stack.append((tag, "summary"))
        elif "tag-static" in classes:
            self.capture_stack.append((tag, "tag"))
        elif "timeline-reason" in classes:
            self.capture_stack.append((tag, "reason"))

    def handle_data(self, data: str) -> None:
        if not self.capture_stack:
            return
        field = self.capture_stack[-1][1]
        target = self.current if self.current is not None else self.pending
        if target is None:
            return
        if field == "tag":
            target.setdefault("_tag_buf", "")
            target["_tag_buf"] += data
            return
        target.setdefault("_text", {})
        target["_text"].setdefault(field, "")
        target["_text"][field] += data

    def handle_endtag(self, tag: str) -> None:
        if self.capture_stack and self.capture_stack[-1][0] == tag:
            _, field = self.capture_stack.pop()
            target = self.current if self.current is not None else self.pending
            if target is not None and field == "tag":
                value = clean_text(target.pop("_tag_buf", ""))
                if value:
                    target.setdefault("tags", []).append(value)
        if tag != "article" or self.current is None:
            return
        text_map = self.current.pop("_text", {})
        for key, value in text_map.items():
            self.current[key] = clean_text(value)
        score_text = str(self.current.get("score") or "").strip()
        self.current["score"] = int(score_text) if score_text.isdigit() else None
        if self.current.get("title") or self.current.get("summary"):
            self.items.append(self.current)
        self.current = None


def parse_aihot_items(
    page_html: str,
    *,
    fetched_at: datetime | str,
    source_url: str,
    limit: int = 30,
) -> list[dict[str, Any]]:
    parser = AIHotParser()
    parser.feed(page_html)
    fetched_iso = isoformat_utc(fetched_at)
    items: list[dict[str, Any]] = []
    for raw in parser.items[: max(0, limit)]:
        item = dict(raw)
        item["source_url"] = source_url
        item["original_url"] = _original_url(item)
        item["fetched_at"] = fetched_iso
        item["cannot_confirm"] = ["AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY"]
        item["recommendation_status"] = "RESEARCH_ONLY"
        item.setdefault("source_name", item.get("source") or item.get("handle") or "AIHot")
        item.setdefault(
            "item_id",
            hashlib.sha256(
                f"{item.get('title','')}|{item.get('url','')}|{item.get('time','')}".encode("utf-8")
            ).hexdigest()[:16],
        )
        items.append(item)
    return items


def build_ai_items(
    raw_items: Sequence[Mapping[str, Any]],
    *,
    fetched_at: datetime | str | None = None,
    source_url: str = AIHOT_URL,
) -> list[dict[str, Any]]:
    """Build the V3-equivalent unified AI records and retain only score Top8.

    The function deliberately consumes already-materialized public rows.  It
    never imports or reads the legacy V3/assistant tree; all transformations
    are deterministic local equivalents of the former ``build_ai_items``
    helpers.
    """
    fallback_fetched = isoformat_utc(fetched_at)
    records: list[dict[str, Any]] = []
    for raw_row in raw_items:
        if not isinstance(raw_row, Mapping):
            continue
        raw = dict(raw_row)
        title = clean_text(raw.get("title")) or "未命名 AI 动态"
        summary = clean_text(raw.get("summary"))
        reason = clean_text(raw.get("reason"))
        tags = [clean_text(tag) for tag in (raw.get("tags") or []) if clean_text(tag)]
        text = f"{title}\n{summary}\n{' '.join(tags)}"
        entities = _detect_named_entities(text)
        symbols = []
        for match in re.finditer(
            r"([\u4e00-\u9fa5A-Za-z]{2,12})[（(](\d{6}\.(?:SH|SZ|BJ|HK))[）)]",
            text,
        ):
            symbol = f"{match.group(1)}({match.group(2)})"
            if symbol not in symbols:
                symbols.append(symbol)
        symbols = symbols[:8]
        article_url = _absolute_http_url(
            raw.get("original_url") or raw.get("url"),
            raw.get("source_url") or source_url,
        )
        page_url = _absolute_http_url(raw.get("source_url"), source_url)
        source_link = article_url or page_url
        source_name = clean_text(raw.get("source") or raw.get("source_name")) or "AIHOT"
        fetched_display = _format_cst_time(raw.get("fetched_at") or fallback_fetched)
        item: dict[str, Any] = {
            "id": f"ai-{raw.get('item_id') or len(records) + 1}",
            "title": title,
            "summary": summary,
            "source_type": "AI",
            "source_name": source_name,
            "fetched_at": fetched_display,
            "published_at": raw.get("time"),
            "symbols": symbols,
            "named_entities": entities,
            "stock_focus": _detect_stock_focus(text, symbols, entities),
            "hk_connect_mapping": [],
            "theme": _infer_theme(text),
            "theme_candidates": _top_theme_candidates(text),
            "evidence_level": "L1",
            "event_fact": _short_text(summary or reason or title, 220),
            "investment_implication": _infer_implication(text),
            "impact_chain": _infer_impact_chain(text),
            "target_price": None,
            "rating": None,
            "earnings_forecast": None,
            "valuation_assumption": None,
            "catalysts": _infer_catalysts(text),
            "risks": list(_AI_RISKS),
            "cross_validation": [],
            "source_url": source_link,
            "original_url": source_link,
            "score": raw.get("score"),
            "tags": tags,
            "freshness_label": "本轮抓取",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "cannot_confirm": sorted(set(raw.get("cannot_confirm") or [])),
        }
        for field in ("title_zh", "summary_zh", "translation_status", "translation_source"):
            if field in raw:
                item[field] = raw[field]
        item["priority_score"] = _priority_score(item)
        records.append(item)
    return sorted(records, key=lambda item: _score_value(item.get("score")), reverse=True)[:_AI_MAX_ITEMS]


def build_ai_news_payload(
    trade_date: str,
    *,
    page_html: str,
    fetched_at: datetime | str | None = None,
    source_url: str = AIHOT_URL,
    limit: int = 30,
    translate_text: TranslateFn | None = None,
    translation_timeout: int = 20,
    feed_receipts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    selected_date = _date(trade_date)
    fetched_iso = isoformat_utc(fetched_at)
    raw_items = parse_aihot_items(
        page_html,
        fetched_at=fetched_iso,
        source_url=source_url,
        limit=limit,
    )
    cannot_confirm = ["AIHOT_PUBLIC_PAGE_DISCOVERY_ONLY"]
    if translate_text is not None:
        raw_items = _translate_rows(
            raw_items,
            translate_text=translate_text,
            timeout=translation_timeout,
        )
        if any(row.get("translation_status") == "CANNOT_CONFIRM" for row in raw_items):
            cannot_confirm.append("ZH_TRANSLATION_INCOMPLETE")
    items = build_ai_items(
        raw_items,
        fetched_at=fetched_iso,
        source_url=source_url,
    )
    status = "READY" if items else "READY_EMPTY"
    return _base_payload(
        trade_date=selected_date,
        source="ai_news",
        status=status,
        source_url=source_url,
        fetched_at=fetched_iso,
        raw_item_count=len(raw_items),
        item_count=len(items),
        overview=[],
        details=[],
        items=items,
        cannot_confirm=cannot_confirm,
        feed_receipts=feed_receipts,
    )


def translate_existing_payload(
    payload: Mapping[str, Any],
    *,
    translate_text: TranslateFn = google_translate_zh,
    timeout: int = 20,
    max_workers: int = 6,
) -> dict[str, Any]:
    """Enrich an existing exact-date payload without refetching source rows."""
    translated = copy.deepcopy(dict(payload))
    source = str(translated.get("source") or "")
    if source == "external_finance":
        details = _translate_rows(
            translated.get("details") or [],
            translate_text=translate_text,
            timeout=timeout,
            max_workers=max_workers,
        )
        translated["details"] = details
        translated["overview"] = overview_from_details(details)
        rows = details
    elif source == "ai_news":
        items = _translate_rows(
            translated.get("items") or [],
            translate_text=translate_text,
            timeout=timeout,
            max_workers=max_workers,
        )
        translated["items"] = items
        rows = items
    else:
        raise ValueError("unsupported research peripheral source")
    gaps = set(translated.get("cannot_confirm") or [])
    gaps.discard("ZH_TRANSLATION_INCOMPLETE")
    if any(row.get("translation_status") == "CANNOT_CONFIRM" for row in rows):
        gaps.add("ZH_TRANSLATION_INCOMPLETE")
    translated["cannot_confirm"] = sorted(gaps)
    return translated


def materialize_existing_translations(
    *,
    data_root: Path,
    trade_date: str,
    source: str,
    translate_text: TranslateFn = google_translate_zh,
    timeout: int = 20,
) -> dict[str, Any]:
    store = ResearchPeripheralStore(data_root)
    payload = store.read_exact(trade_date, source)
    if payload is None:
        raise ValueError(f"research peripheral payload is missing: {source}")
    translated = translate_existing_payload(
        payload,
        translate_text=translate_text,
        timeout=timeout,
    )
    result = store.replace(
        translated,
        expected_sha256=_sha256(payload),
        reason="ADD_ZH_TRANSLATION_AND_ORIGINAL_URL",
    )
    return {"payload": translated, **result}


def _publish_or_hourly_refresh(
    store: ResearchPeripheralStore,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish once, then CAS-refresh the same exact-date source hourly."""
    existing = store.read_exact(str(payload["trade_date"]), str(payload["source"]))
    if existing is None:
        return store.publish(payload)
    if (
        existing.get("status") in _REUSABLE_STATUSES
        and payload.get("status") == "CANNOT_CONFIRM"
    ):
        attempt = store.record_refresh_attempt(
            payload,
            retained_payload=existing,
            reason="FAILED_REFRESH_RETAINED_LAST_READY",
        )
        trade_date = str(existing["trade_date"])
        source = str(existing["source"])
        return {
            "payload": existing,
            "trade_date": trade_date,
            "source": source,
            "payload_path": store._relative(trade_date, source),
            "receipt_path": store._receipt_relative(trade_date, source),
            "payload_sha256": _sha256(existing),
            "item_count": int(existing["item_count"]),
            "retained_previous": True,
            **attempt,
        }
    return store.replace(
        payload,
        expected_sha256=_sha256(existing),
        reason="HOURLY_REFRESH",
    )


def materialize_external_finance(
    *,
    data_root: Path,
    trade_date: str,
    fetch_rss: FetchFn | None = None,
    fetched_at: datetime | str | None = None,
    translate_text: TranslateFn = public_translate_zh,
    resolve_original_url: OriginalUrlResolver = decode_google_news_url,
    **kwargs: Any,
) -> dict[str, Any]:
    payload = build_external_finance_payload(
        trade_date,
        fetch_rss=fetch_rss,
        fetched_at=fetched_at,
        translate_text=translate_text,
        resolve_original_url=resolve_original_url,
        **kwargs,
    )
    result = _publish_or_hourly_refresh(ResearchPeripheralStore(data_root), payload)
    return {"payload": payload, **result}


def materialize_ai_news(
    *,
    data_root: Path,
    trade_date: str,
    fetch_html: FetchFn | None = None,
    fetched_at: datetime | str | None = None,
    source_url: str = AIHOT_URL,
    timeout: int = 30,
    limit: int = 30,
    translate_text: TranslateFn = google_translate_zh,
    transport: ProxyAwareHTTPTransport | None = None,
) -> dict[str, Any]:
    fetched_dt = _coerce_datetime(fetched_at)
    fetcher = fetch_html or fetch_url
    raw_html, receipt = _fetch_feed(
        fetcher,
        source_url,
        timeout,
        transport=transport,
    )
    page_html = raw_html.decode("utf-8", errors="replace") if isinstance(raw_html, bytes) else str(raw_html)
    payload = build_ai_news_payload(
        trade_date,
        page_html=page_html,
        fetched_at=fetched_dt,
        source_url=source_url,
        limit=limit,
        translate_text=translate_text,
        translation_timeout=timeout,
        feed_receipts=(
            [_feed_receipt("aihot", source_url, receipt)]
            if transport is not None or fetch_html is None
            else None
        ),
    )
    result = _publish_or_hourly_refresh(ResearchPeripheralStore(data_root), payload)
    return {"payload": payload, **result}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument(
        "--source",
        choices=("external_finance", "ai_news", "both"),
        default="both",
    )
    parser.add_argument("--ai-url", default=AIHOT_URL)
    parser.add_argument("--lookback-days", type=int, default=2)
    parser.add_argument("--limit-per-feed", type=int, default=10)
    parser.add_argument("--max-items", type=int, default=36)
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--translate-existing",
        action="store_true",
        help="Translate current exact-date artifacts without refetching sources.",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Use validated exact-date artifacts and fetch only missing sources.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    outputs: list[dict[str, Any]] = []
    selected_sources = (
        ("external_finance", "ai_news")
        if args.source == "both"
        else (args.source,)
    )
    if args.reuse_existing:
        store = ResearchPeripheralStore(args.data_root)
        for source in selected_sources:
            payload = store.read_exact(args.trade_date, source)
            if reuse_existing_payload(payload):
                outputs.append(
                    {
                        "payload": payload,
                        "payload_path": f"research/peripherals/{args.trade_date}/{source}.json",
                        "receipt_path": f"receipts/research/peripherals/{args.trade_date}/{source}.json",
                        "reused": True,
                    }
                )
        selected_sources = tuple(
            source
            for source in selected_sources
            if not any(item["payload"]["source"] == source for item in outputs)
        )
    if args.translate_existing:
        for source in selected_sources:
            outputs.append(
                materialize_existing_translations(
                    data_root=args.data_root,
                    trade_date=args.trade_date,
                    source=source,
                    timeout=args.timeout,
                )
            )
    elif "external_finance" in selected_sources:
        outputs.append(
            materialize_external_finance(
                data_root=args.data_root,
                trade_date=args.trade_date,
                lookback_days=args.lookback_days,
                limit_per_feed=args.limit_per_feed,
                max_items=args.max_items,
                timeout=args.timeout,
            )
        )
    if not args.translate_existing and "ai_news" in selected_sources:
        outputs.append(
            materialize_ai_news(
                data_root=args.data_root,
                trade_date=args.trade_date,
                source_url=args.ai_url,
                timeout=args.timeout,
                limit=args.limit,
            )
        )
    print(
        json.dumps(
            {
                "trade_date": args.trade_date,
                "source": args.source,
                "outputs": [
                    {
                        "source": item["payload"]["source"],
                        "status": item["payload"]["status"],
                        "item_count": item["payload"]["item_count"],
                        "payload_path": item["payload_path"],
                        "receipt_path": item["receipt_path"],
                    }
                    for item in outputs
                ],
            },
            ensure_ascii=False,
        )
    )
    safe_status = all(
        item["payload"]["status"] in {"READY", "READY_EMPTY"}
        and "ZH_TRANSLATION_INCOMPLETE" not in item["payload"]["cannot_confirm"]
        for item in outputs
    )
    return 0 if safe_status else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AIHOT_URL",
    "DEFAULT_SUBSCRIPTIONS",
    "GOOGLE_NEWS_RSS",
    "GOOGLE_TRANSLATE",
    "AIHotParser",
    "build_ai_items",
    "build_ai_news_payload",
    "build_external_finance_payload",
    "dedupe_and_rank",
    "google_rss_url",
    "google_translate_zh",
    "materialize_ai_news",
    "materialize_external_finance",
    "materialize_existing_translations",
    "parse_aihot_items",
    "parse_args",
    "parse_rss_date",
    "parse_rss_items",
    "reuse_existing_payload",
    "translate_existing_payload",
]
