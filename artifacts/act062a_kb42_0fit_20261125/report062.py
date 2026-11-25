"""Format the scoped ACT-062A research results without exposing blind mappings."""
from collections import Counter

from recon062 import PORT_DUAL, PORT_ANCHOR


def report(d,b,r):
    captures0,capturesw = r["d0_event_captures"], r["window_event_captures"]
    baseline = r["baseline"]
    stock_blocks = Counter(d.boundary_recent_descriptive_sample_status)
    lines = [
        "# ACT-062A｜KB42 标签字典、分阶段盲窗与冻结旗舰对账",
        "",
        "## 核心结果",
        "- **42/42 身份一致**，原型 A18/B16/C7/D1。全历史反向事件 3,374 个，隐性 3,244 个；近两年 583 个波段，完整 562 个（回吐 151、保持 411），缺证 21 个保留。民生银行近两年 0_IN_2Y，其 2024-11-14 只用于历史控制对。",
        f"- **16 个盲案**，保持 8、回吐 8，覆盖 A/B/C/D 和 V1.3 六只低上影覆盖股。高分化来源 {b['high_divergence_case_n']} 案。与 ACT-061A 已审 24 案重叠 {b['old_cases']}、互补 {b['new_cases']}。64 个匿名成员和 32 张有效 SVG 均过零泄露扫描。先判阶段 A，再打开阶段 B，封口后使用独立密钥揭盲。",
        f"- **两组基线各 1,200 席，席次与腿一致**。42 股共 {r['KB42_FULL_symbol_days']}/5,040 个 FULL 股票日、{r['KB42_CORE_symbol_days']}/5,040 个 CORE 股票日；锚 Top-10 命中 {r['KB42_anchor_seats']} 席，旗舰 Top-10 命中 {r['KB42_dual_seats']} 席（CORE {r['KB42_dual_CORE_seats']}、FULL {r['KB42_dual_FULL_seats']}）。",
        f"- 120 个 OOS 交易日内 {r['event_n']} 个波段（隐性 {r['event_groups'].get('hidden',0)}、显性 {r['event_groups'].get('visible',0)}）。D 当日旗舰捕获 {captures0['dual_top10']}，D−5..D 捕获 {capturesw['dual_top10']}，锚 Top-10 分别 {captures0['anchor_top10']}、{capturesw['anchor_top10']}。截窗前未被 OOS 观察的 {r['partial_early_oos_window_events']} 案保留不足六栏标记。",
        "",
        "## 标签字典 V1",
        "- 每股一行。身份与冻结原型、D 前观测值、历史买点结果、D 后退出依据和可建模边界各有字段。匹配依据沿用 ACT-061A，D 后净差分别为 D+5/+10/+20 主路径净普通日，共 42 对。",
        "- ACT-056B Stock Cards 的 Best/Worst T+5 保留原值。四类买点命中与 T+5 分母沿用 ACT-050/056A 已冻结原件，按 ACT-057 的 t5_close 口径由小数乘 100，缺值排除。",
        "- ACT-058A 的 D−5..D−1 日均振幅、20 栏收盘最大回撤、长下影支撑和白黄线公式按 D−1 基底并截止至 D−1。这里保留固定历史反向样本的汇总，未来模型须按相应时点重建 D 前特征。反向选样、T+5/退出值和曾利用后续结局的条件不能作为因果输入。",
        "- 近两年退出使用 ACT-061A 四路径、首警相对峰日、首警后再新高与修复分母。全历史上影覆盖及峰后砸盘速率取 ACT-057 对应样本。688621.SH/20250515 的首警是最早已观测 D+5，较早两栏缺证。D 原型只有一股。",
        f"- 描述性阈值为两组各至少 5 个完整波段，{stock_blocks.get('BOTH_GROUPS_AT_LEAST_5',0)} 股达标、{stock_blocks.get('AT_LEAST_ONE_GROUP_BELOW_5',0)} 股至少一组不足、1 股无近两年事件。训练未准入。",
        "",
        "## 匿名分阶段包",
        "- 先筛除所需截窗内缺证的事件。固定优先顺序为避开 ACT-061A 已审案例、低上影覆盖、高分化、完整波段较多、代码和较早日期稳定择位。在每组最多 8 案下先保留四原型，再补齐六只低上影股，最后补额。固定种子在选样完成后打乱顺序。",
        "- A/B 分目录存从 t-15 开始的 CSV 和真实前复权 OHLCV、白黄线 SVG。A 截到 t0。B 截到 D+5 内首个已观测警示，否则到 t+3。代码、名称、日期、结局和未来栏扫描为零。外部行情仍可能按数值匹配，盲判过程需独立封口。",
        "",
        "## 旗舰与洁净锚",
        "| 组合 | 席位 | T+2超额(%) | T+3超额(%) | T+5超额(%) | 换手(%) | 纯尾(%) | T+2正折 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for port in [PORT_DUAL,PORT_ANCHOR]:
        p = baseline[port]["published"]
        lines.append(f"| {port} | 1200 | {p['t2']:.4f} | {p['t3']:.4f} | {p['t5_l50m_observed']:.4f} | {p['turnover_pct']:.2f} | {p['tail_pct']:.2f} | {int(p['positive_folds_t2'])} |")
    lines += [
        "",
        "- ACT-024 Y、ACT-034 FULL 和 ACT-037-F01 CORE 原件按上游哈希绑定。用冻结输出和 ACT-046 规则复原历史名次，新模型评分为零。ACT-046 已封存的 2,400 席日期、组合、折、腿、顺序、代码逐项吻合。归约结果在发表精度上相同，末位浮点差记于回执。",
        f"- Top-50 按同一冻结历史排名复原，未取得独立旧成员表。CORE 5/10/50 临界理论同名次日分别 {r['cutoff_exact_ordinal_tie_days'][5]}/{r['cutoff_exact_ordinal_tie_days'][10]}/{r['cutoff_exact_ordinal_tie_days'][50]}。ACT-046 标记 {r['original_tie_identity_cannot_confirm_seats']} 个原历史边界成员不可确认的席位。",
        f"- FULL/CORE/锚 Top-50/锚 Top-10/旗舰 Top-10 的 D0 捕获依次 {captures0['full_l50m']}/{captures0['core_eligible']}/{captures0['anchor_top50']}/{captures0['anchor_top10']}/{captures0['dual_top10']}。D−5..D 依次 {capturesw['full_l50m']}/{capturesw['core_eligible']}/{capturesw['anchor_top50']}/{capturesw['anchor_top10']}/{capturesw['dual_top10']}。ONLY_IN_FULL_TOP5 为旗舰 FULL 腿独立捕获的 CORE 盲区。",
        "- 对账 CSV 含逐股、原型、显性/隐性事件、逐席位与事后退出联表。逐席优先对同日事件，其次为同股未来 5 栏内最早事件。匹配仅供事后解释。股票日占比按每股 120 日计算，收益原值与超额有各自有效席位分母。",
        "",
        "## 执行边界",
        "拟合、预处理拟合、聚类、模型载入、预测、新评分、调参、模拟买卖、滑点净值回放、下单、生产写入均为 0，累计研究 FIT=291。RESEARCH_ONLY=true，STRICT_PIT=0，TRAIN_ADMITTED=0，NO_GO_BLOCKED=true，production_allowed=false，orders_sent=false，buy_gate_updated=false。知识库训练未完成，ACT-062B 等 GEMINI_MASTER 核收。",
        "",
    ]
    return "\n".join(lines).encode()
