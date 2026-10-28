"""Multiline schema and keyword values; called at original assignment time."""
from ._namespace import read_global as _v4_global


def _value_DEFAULT_SUBSCRIPTIONS(_v4_scope, /):
    return (
        (
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
    )


def _value_NEGATIVE_PATTERNS(_v4_scope, /):
    return (
        (
    "price prediction",
    "stocks to buy",
    "stock list",
    "prediction markets",
    "personal finance",
    "simplywall",
    "simply wall st",
)
    )


def _value_SOURCE_TIER_PATTERNS(_v4_scope, /):
    return (
        (
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
    )


def _value_AH_KEYWORDS(_v4_scope, /):
    return (
        (
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
    )


def _value_THEME_LABELS(_v4_scope, /):
    return (
        {
    "china_hk_stocks": "中国资产/A股港股",
    "china_tech_ai_semis": "中国科技/AI/半导体",
    "hk_ipo_new_economy": "港股IPO/新经济",
    "ai_compute_chip": "AI算力/芯片",
    "robotics_autonomous": "机器人/自动驾驶",
    "commercial_space": "商业航天",
    "biopharma_ma": "创新药/并购/临床",
}
    )


def _value_SOURCE_CN_LABELS(_v4_scope, /):
    return (
        {
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
    )


def _value__AI_THEME_RULES(_v4_scope, /):
    return (
        (
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
    )


def _value__AI_IMPLICATIONS(_v4_scope, /):
    return (
        {
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
    )


def _value__AI_IMPACT_CHAINS(_v4_scope, /):
    return (
        {
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
    )


def _value__FINANCE_UNIT_MULTIPLIERS(_v4_scope, /):
    return (
        {
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
    )


def _value__FINANCE_CURRENCY_ALIASES(_v4_scope, /):
    return (
        {
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
    )


def _value___all__(_v4_scope, /):
    return (
        [
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
    )
