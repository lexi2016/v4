# 经理选股工作台：每天自动选股问题包

## 唯一业务目标

修复 V4 / 8873 经理选股工作台，使其在适用交易日按原调度自动完成 **公告选股、美股映射、超跌选股**，生成按目标日保存、可追溯的研究选股结果，并由普通经理页面展示。用户无需每天手动刷新、重复指定日期或另开会话催跑。

本次请求是围绕上述目标交付可实施的代码和闭环方案；两项底层修复、单个测试通过、数据文件存在或单日手动跑通均不能作为总目标完成。每日结果允许真实的零入选或有证据的部分结果，但必须区分“已评估后零入选”和“未运行／输入缺失”。不能为了每天显示股票而放宽原选股规则或编造候选。

工作入口：`http://127.0.0.1:8873/manager-selection/?date=20261008&announcement_date=20261007&plan_date=20261008`。唯一源码项目为 `/Users/lexi/Desktop/学习/v4_app`。三路研究结果不等于交易执行。

## 最新现状：10/8 尚未完成补选

本机 2026-10-08 23:46（Asia/Shanghai）再次只读查询现役 workspace，精简原字段见 [current_state.json](current_state.json)：

| 业务面 | 实际状态 | 含义 |
| --- | --- | --- |
| 目标日计划 | `NOT_MATERIALIZED`，run_id=null，consumed=false，无 attempt | 10/8 经理计划没有生成 |
| 美股每日映射 | `NOT_RUN`，run_id/session/cutoff=null | 源快照就绪没有接成当日映射运行 |
| 超跌 | `CANNOT_CONFIRM`，main_screen_ready=false | 未完成有效筛选，不能把空数组称零入选 |
| 公告已审研究 | `READY`，1 个产品、87 个研究引用 | 已有成果须保留；不等于当日完整计划已生成 |
| workspace 股票数组 | 空，candidate_count_known=false | 数量未知，不是成功选出 0 只 |

现役配置仍指向 `manager-workbench-r1-mac-20261008-api-r2`。配置身份和原字段在快照内，不能将新候选或 canonical 当作已加载版本。

## 已完成的工作直接复用

- [两项修复代码包，0602f34](https://github.com/lexi2016/v4/blob/0602f34fd10f7daff9bf688a710835d1bda43865/handoff/issue29-manager-daily-repair-20261008/README.md)：同一封存合同下的历史 owner 重验；US reader 异常返回完整 DTO，保留 unknown/null，避免拖垮公告展示。仅两份生产文件、五份测试。
- [本机独立验收，8342862](https://github.com/lexi2016/v4/blob/8342862f05ca9f6516f51b3164b6110651e5af77/handoff/issue29-mac-acceptance-20261008/README.md)：七文件差异、九个保留指纹一致；新增 Python 34 项、前端 13 项通过，限定类型检查通过；组合回归保留既有 HK02 fixture 失败。测试组有重叠，不相加。
- 同一包真实只读重验 9/30 原 run `ba13fba330464300b760fe940ba579a1`，已越过原版本错误，返回 `SOURCE_FAILED / HISTORY_SOURCE_INPUTS_CHANGED`，未消费、未改写原件。它是新的精确拒绝点，不证明旧成果不存在，也不是每日自动化完成。
- [原业务链、owner、日期及历史成果对照](https://github.com/lexi2016/v4/blob/0602f34fd10f7daff9bf688a710835d1bda43865/handoff/issue29-manager-daily-repair-20261008/docs/OWNERS_AND_DATE_RECONCILIATION.md)：保留原公告、US reviewed/daily、超跌回看成果及其原日期范围；不重新做全项目审计。

上述两项补丁尚未部署。本问题包不要求重做同 SHA、同范围已通过的测试；实际新增改动才做对应回归。

## 已证实的断点与需要完成的修复

### 1. 每日调度与计划持久化没有闭环

现役计划绑定为 `enabled=false / PROPOSAL_ONLY`；10/8 没有正式 plan run/attempt。请沿原调度生命周期明确每个阶段的输入就绪条件、调用 owner、目标日、截止时间、超时/失败回执和保存路径，交付使原 `refresh_workspace_plan` 自动执行并读回的有界接线。不能只准备一个 disabled binding 就交付结束。

复用现有 06:30 公告任务、原 PREOPEN/MORNING/EVENING_NEXT_SESSION 设计及已存在 owner，查明是否重复或缺口再调整；不能另造 producer 或把旧的 09:27 安装记录当成当前自然运行。依赖尚未就绪时记录可恢复的阻塞，按原机制有界续跑；同一目标日/时段的重复触发必须幂等，不覆盖历史 run。晚到数据的补算明确标成 late catch-up，不能倒签为盘前已知。

### 2. 美股来源已存在，原每日 owner 未被调用

10/8 对应 US session=10/7 的 `external_finance` payload/receipt/manifest SHA 链已核对；覆盖为固定 33 配置标的、24 行业代理。现役 `service.refresh_us_mapping_research` 已存在，但 `plan_owner_dispatch._us_mapping_dispatch_status` 明确返回 `NOT_ATTEMPTED`，现役 scheduler 无 enabled daily mapping workload。四个 peripheral capture 时段不代表 daily mapping 已跑。

请在原生命周期内有界调用既有 owner，使用原 US 日历、aware cutoff、精确 completed session、原 registry 的 availability，保存同目标日 `runs/<run>.json` 和 `latest.json` 并读回。单独记录 US 失败，不耗尽原计划 deadline，不让故障拖垮公告／超跌已完成结果。不能恢复旧的无界尾部调用。

`us_market_attention`、原材料关系、`us_mapping_research.daily_run`、reviewed 回顾卡分别记录；`HK_CONNECT` 是资格通道，不能改标签或借用数量冒充美股映射。当前 daily 关系范围只是四个 reviewed US ticker，不宣称全市场关系发现；若用户目标超出现有算法范围，明确列出能力缺口，不擅改策略。

### 3. 港股输入跨日接续不完整，超跌未真正完成

- **10/7 已证根因**：17:20 dispatch run `9698f67dad7d4be397d0e16ea47553d7` 在 child 前被旧 `NON_TRADING_DAY` 判断挡住。10/8 已使用后续调度版本，不能再把旧日历错误当作当天仍未修。
- **10/8 已证范围**：dispatch run `b779a11da3bf4d689c51c20bc728ed7f` 和 HK02 面板成功；缺同次 capture→membership→master→V2 的完整发布链，精确 10/8 主表和 V2 产物未找到。已核 producer/master-reader root 相同，不能凭猜测改 root。
- 面板缺精确 10/7，量纲证明仍缺；只补主表不能自动修好超跌规则。盘前与收盘后的合法 source session 不同，不能拿 10/8 收盘数据回填当天盘前。

请沿原 HK child/capture/ensure owner 定位首个失败步骤，修复同一次采集的后续发布与失败回执，再复用既有缓存优先 tdxpy/TDX 链处理必要缺日。证券交易日与 Connect 资格日分别判断；正式资格须用原合法 publication 和真实 available_at，不能用报价集合替代 membership、用 latest 代 exact-date、用猜测单位计算或给旧日期倒签。没有合法历史资格证据的部分继续保留缺口，但必须交付下一交易日自然链的恢复方案与必要代码。

上述本机结论、21 个证据位置和 SHA 见 [精简断点证据](https://github.com/lexi2016/v4/blob/8342862f05ca9f6516f51b3164b6110651e5af77/handoff/issue29-mac-acceptance-20261008/input_readiness/issue29_hk_us_boundary_20261008.json)。原始行情未上传。

### 4. 公告成果要自动进入当日计划与普通页面

已有公告研究产品必须按 target/publication/date/SHA 从原 owner 消费，保留股票、原理由及 SELECTED/WATCH/未评估状态。明确从每日抓取、审核产品就绪到计划引用的接续；未知不能填零，其他通道缺失不应清空已经验证的公告结果。不要因 workspace 某旧字段 NOT_RUN 就重新抓取已经存在的同源产品。

### 5. 历史可读性和页面日期一致性

保留已验的兼容机制；仅针对真实 `HISTORY_SOURCE_INPUTS_CHANGED` 对照原封存输入与重验输入的差异字段/来源，明确是真实来源变化还是当前注入/reader 上下文漂移。若确实不可复现，原拒绝保持，不重封原件，也不让这项历史差异阻断未来每日接续的交付。

普通经理页面须显示三路各自日期、运行状态、选中股票与理由、来源/run 引用、缺口，以及当日计划是否保存。刷新和日期切换不得混用前一天股票；历史回看、手动补算、自然运行分别展示。限定 renderer 单元测试不能替代真实页面验收。

## 发布依赖与范围

[Issue #30](https://github.com/lexi2016/v4/issues/30) 的共享发布保护仍未独立验收：旧整包切换曾覆盖 #28 的预选池修复。该依赖不能省略，也不能把经理任务变成全应用重构。先交付本业务模块最小 delta 和对共享调度入口的明确 ownership；最终由唯一集成 owner 在受保护的新基线上合并验证经理功能和预选池保留。

```text
GOAL: 每个适用交易日自动完成三路研究选股、保存同日计划并由普通页面读回
WRITER: 接手 Chat 指定的一名 Luna Max Writer；同文件集单写入者
REVIEWER: 不同身份的 Luna Max Reviewer，按实际 delta 独立验收
ALLOWED_PATHS: 先按 source_index.json 列模块级实际修改清单；经理模块/必要测试/原调度受限接线；共享入口须唯一 owner 集成
FORBIDDEN_PATHS: 交易与BUY/模型门禁；Vibe8910；平行数据producer/面板；原历史产物；无关Stage逻辑；旧整包覆盖当前release
PASS_SIGNAL: 下方逐层验收完成；自然时段证据未到则工程交付与自然验收分开，不宣告总目标完成
STOP_RULE: 缺凭据、来源事实无法确认或必须改策略时精确报告；不能把缺文件当无数据、解除校验或重复提交方案代替代码
```

本次用户授权本机准备问题包供 Chat 接手；不包含本机继续实施、补采、POST、启停服务、启用任务或部署。Chat 交付代码、测试及本机执行交接；任何正式运行仍按已有共享发布协调和用户授权执行。

## 必须交付与验收

1. **最小代码交付**：每处断点的原 owner → 新行为、actual diff、逐文件前后 SHA、独立分支、依赖与回滚边界。明确本轮没解决的事项；不能只再交“建议接入”的文本。
2. **日期与故障测试**：正常交易日、休市跨日、US/HK 日期差异、输入晚到、单通道失败、重启/重复触发、超时和下一日接续。确认同日原输入被消费、失败能追踪且不污染别路，不硬编码 33/58 等历史入选数量。
3. **真实 10/8 补算验收**：本机通过原 owner 执行带真实执行时间的事后补算/回看，记录 run/cutoff/输入和输出；能运行的通道逐股显示，不能运行的明确原因。当天已缺失的 PIT 证据不能凭晚间重跑补造。
4. **连续业务日验证**：先用固定日期隔离测试/只读历史证明日期推进和幂等，再等至少两个连续适用交易日的原调度自然触发，核每一路 owner receipt→同日 run→计划→API→重新加载普通页面。手动 POST、健康端口和 daemon cycle 不能替代自然结果。
5. **真实 UI 与保留验收**：同一目标日看到股票/原理由/通道结果或有证据的成功零入选；日期切换不串日；US 失败不拖垮公告；保留 #28 预选池修复及既有 Stage、A/HK 边界。
6. **最终报告**：分开 IMPLEMENTED / TESTED / REVIEWED / INTEGRATED / DEPLOYED / API_VERIFIED / UI_VERIFIED / BEHAVIOR_VERIFIED / NATURAL_VERIFIED；直接回答“今天是否补选完成、之后是否每天自动、还有哪个具体阻断”。自然尚未发生标 `NATURAL_SLOT_UNVERIFIED` 并留下验收入口。

## 源码与证据使用方法

本分支继承 `8342862f05ca9f6516f51b3164b6110651e5af77`，因此包含上一轮修复、Mac验收及其祖先交付。`source_index.json` 按当前本机来源及 SHA 指向已有完全相同的仓库文件；缺失字节才放入本包 `source/`。来源分别是 API release、scheduler、HK child、现有 web 源码和隔离候选，不能混称同一个完整可部署应用。本包不是完整依赖闭包，不得整树覆盖部署。

`source_index.json` 的 `metadata_only_dependencies` 仅列不上传的 registry/历史研究 seed 的本机位置和 SHA；云端测试使用既有合成 fixture，真实数据核验留本机。不要伪造这些依赖或复制原始业务数据到公开环境。

研究安全边界：`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
