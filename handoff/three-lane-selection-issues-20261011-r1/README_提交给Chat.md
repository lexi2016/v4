# V4 三路选股与计划读回问题包

## 用户目标（最终验收，不可降级）

沿用 V4 8873 的既有链路，把公告、港股通、超跌反弹三路各自的真实选股、结果归档、API 和页面读回闭环，并修复计划失效问题。完成后必须三路都能正常执行选股。禁止以美股映射完成、初筛数量、HTTP 200、页面可见或测试通过替代选股完成。缺数据必须指出确切日期、字段、原 owner 和恢复方式，未解决的路不得报完成。

当前交付只是问题包，未实施修复、未部署、未完成三路选股验收。本轮 Writer 在用户切换到打包任务后停止，未修改业务文件、未运行测试。用户将自行向 Chat 提交本包。

## 先读哪些文件

1. 本 README：目标、现象、根因证据、边界与验收。
2. `evidence/workspace-20261009-summary.json`：当前 10/09 API 原响应的明确标识派生摘要；保留原响应 SHA，不冒充原始 HTTP 字节。
3. `evidence/historical-plan-inventory.json`：真实归档文件大小、生成时间、cutoff、run 和 SHA。
4. `evidence/prior-20261012-diagnosis.json`：上一轮 10/12 计划失效调查，仅作为相应日期证据，不能解释为 10/09 状态。
5. `evidence/runtime-before.json`、`SOURCE_MANIFEST.json`：当前 API/scheduler 的配置身份，配置指向源码与 canonical 每文件 SHA 比较；不证明进程当前已加载这些字节。
6. `active_source/`：配置指向的相关模块和已有测试源代码快照；不是完整应用或可直接部署的发行包。未附虚拟环境、构建结果、认证文件、大型行情/计划数据。完整依赖应在原仓库和实际运行环境中使用。

## 运行身份与不可覆盖的基线

- 唯一源码：`/Users/lexi/Desktop/学习/v4_app`，入口 8873；保留既有页面布局、模块和 owner。
- 本次 LaunchAgent 配置指向的 API 源码：`/Users/lexi/Desktop/学习/agents调试/V4_US_MAPPING_DAILY_CHAIN_MAC_20261011_R1/integrated_release/manager-us-mapping-daily-chain-20261011-r1/app`。
- API 配置指定的 release manifest SHA：`3b548f81684bd48e19b9cad8ac824f036163699f8cf53dc3234bc184df9014ad`。运行前须再次读回，而不能视为永久固定事实。
- 已交付美股链路工作分支：`codex/us-mapping-daily-chain-mac-20261011-r1`；此前固定 commit `a1b722e4c82defcb9537d5c05915c6a8072c02d3`。这证明的是该批源交付，不证明三路选股完成，也不保证与全部现役字节相同。
- canonical 与现役的 workspace、history、plan、service、connect_selection、projection 等文件存在差异。按 `SOURCE_MANIFEST.json` 精确核对，不能从旧分支整包覆盖现役 HK/US 修复，也不能覆盖用户未提交改动。
- Scheduler 使用单独的 `hk-auto-d1-20261011-r1` 根；manager hooks 另外指向上述 API release。API、scheduler、Stage 必须分别核身份。Vibe 8910 保持原样。
- Python：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`。使用真实环境做验证，不以不同 Python 的结果替代。

### 开工前必须处理的运行身份冲突

独立核查发现：配置指定的 manifest（文件 SHA 本身匹配 3b548…）内部仍声明 activation_status=NOT_ACTIVATED、deployment_status=false、active_pointer=base，指向旧 hk-0920-auto-ui release；其记载的 API plist SHA 前缀 b2d8… 也与当前配置 8c27… 不同。包内 runtime-before 证明配置内容，不含本次 PID/loaded-module 证据。因此 `active_source/` 文件名仅沿用快照目录命名，本包对“当前进程确已加载全部这些代码”保留 CANNOT_CONFIRM。这可能是不可变候选 manifest 的旧状态元数据，不能据此断言服务未部署或据配置断言已加载。Chat 开工前必须结合进程、启动身份、源码与部署回执解决该冲突，再决定基线；不得盲改 manifest 让状态看起来一致。

## 已固定的两个复现

### A. 当前查看日：10 月 9 日历史模式

页面：`http://127.0.0.1:8873/manager-selection/?date=20261009&plan_date=20261009`

GET：`http://127.0.0.1:8873/api/v4/manager/research/workspace?date=20261009`

API 返回 HTTP 200，但 `stocks=[]`、`focus_symbols=[]`。计划为 `SOURCE_FAILED`，原因 `HISTORY_RUN_BYTES_BOUND_EXCEEDED`。读取模式 `HISTORICAL_AS_OF`，截止 `2026-10-09T09:30:00+08:00`。三路日期绑定 selection=plan=20261009、announcement=20261008。

| 路径 | 当前状态 | 确切缺口 |
|---|---|---|
| 公告 | rows 空，数量未知 | ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED |
| 港股通 | rows 空，数量未知 | TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED |
| 超跌反弹 | rows 空，数量未知 | HISTORY_EXACT_DATE_MARKET_NOT_VERIFIED；planning_market_session 与 screen_target_trade_date 为 null |

### B. 次一交易日计划：10 月 12 日

上一轮 GET 对应 plan_date=20261012，计划 `STALE_INPUTS_CHANGED`、consumed=false、正式名单为空。46 个 material 引用和 15 个 projection 引用，在去除全局 manifest_sha256 后一致：日期、路径、具体 payload SHA、receipt SHA 未变。两项 input identity components 改变。此证据表明全局登记变化参与了身份变化，但尚未独立重算完整污染路径；不得直接对全部 SHA 做忽略处理。

## 五项必须处理的问题

### P1：历史读取按全量计划正文累计，遮蔽正确的历史状态

配置指向的 `v4/manager_research/workspace_history.py`：`select_plan()` 先读 latest，再扫描其他 run；累计 `_MAX_SCAN_BYTES=64*1024*1024`，超过即报上述错误。

真实 `workspace_plans/20261009` 有 7 个 JSON（含 latest），共 147,031,510 字节，单件约 14.8–23.4 MB。所有现存产品的 generated_at 均在 10/10–10/11，晚于 10/09 09:30。这意味着解除大小错误后，也不能把这些事后计划冒充 10/09 当时计划。目录包含 latest 与同一 run 的重复内容。

应沿既有存储合同修复有界查找/索引或选择逻辑，避免为了发现“无合格历史计划”扫描全部重复大正文；具体方案须基于实际代码。继续校验原产品 SHA、日期、cutoff、时点及路径安全，不可仅提高上限，不可删除归档换通过。最终历史模式准确显示“无合格当时计划”；显式现在回看模式才消费事后生成结果。

### P2：公告已有事后分析结果，但三路摘要没有合法读回

10/09 页面下方已有 10/08 Eastmoney 日期目录：392 条、281 个来源代码；研究入选 55、条件观察 32、未入选 121、未评估 73。catalog run `4b69fa03fbfc4c48b1c410239332505e`；catalog SHA `db1335417ba434016b3c4c23b2bcd13813c54af2d262598cda6fc668e086a798`；基础分析 SHA `d7c3feeaa675382f5007b98e55ff8f7e483471060ba1045be942612dc05e9f5b`；选股判定 SHA `66429d73649fd09478a1c4ac243a69f235cbd546a84ac5e0c412161fdf7671b2`。

上述数量、run 和 SHA 是本轮浏览器可访问性树中显示的观察值，最小转录见 `evidence/announcement-ui-observation.json`；包内未附公告原 owner receipt，未独立核实对应产品，Chat 必须按原 owner 复核，不能单凭这些显示值验收。

这些是已显示的事后研究成果，并非 10/09 盘前 PIT，也非 HKEX 官方全量、港股通资格或 BUY 输入。部分入选属于风险/退市事件，不能直接升格为可买入名单。

检查 `workspace_daily_channels.py` 的 publication_date + target_trade_date + CONSUMED 绑定，以及 `ManagerResearchJobService.import_announcement_analysis` / `refresh_announcements` 的原 owner 产物/运行合同。让合法的研究选股结果在匹配日期和显式口径中显示，不按标题重新猜股票，也不把已有55固定写入代码。历史无 PIT 回执继续明确缺口。对未来日常运行，必须实际验证 owner 生成、导入/注册、归档、API与页面同一 run/SHA。

### P3：港股通正式结果与 backfill 混淆，会员/池输入尚未核实

10/09 正式 STAGE_0925 receipt 表示 `selected_rows=0`、`write_performed=false`，错误 `HK D1 status must be STRICT_0_2_READY`。交接材料所谓“10只”来自 backfill `c44b03fa94115911bc4aaa44d2152712` 下 `run-6e62af205e5142401ad186b0`，不能当正式结果或自然运行证据。

既有 owner 为 `v35_dispatcher.research_panel_daily_hk`；目标日 membership V2、D-1 canonical Top100、Stage 输入各自校验。检查 `connect_selection.py`、`domains/manager_research_evidence.py`、`stage_center/hk_universe_preflight.py` 及现役 binding。10/12缺件不能直接当10/09缺件；按实际日期查证。复用共享权威面板，补齐可恢复依赖后运行原 owner/Stage，并把真正保存的选股产品接回页面。不能将 backfill 路径改名、复制成正式或以全市场替代 D-1 Top100。

### P4：超跌反弹初筛回放不是完整选股闭环

此前 10/12 计划读到基于10/09的 214 strict / 286 near 研究候选、34待核；明确 `formal_selection_input=false`，不是正式 Stage 或重点名单。当前10/09历史模式连经过验证的 screen date 都没有。

沿现有 HK_0_2 rebound two-gate screen / 选择台账 owner，核实目标行情会话、前60个完整交易日及成交量来源。检查 `research_attention.py`、`workspace_daily_channels.py` 和相关 projection。需要有真实运行身份、逐股判定与原因、输入/产品 SHA、保存/读回，不可简单把 strict 列表改名为正式结果。若既有策略合同只定义研究筛选，应明确其最终研究名单，并与正式 Stage 名单分列；不得新造算法或以显示变更代替 owner 执行。

### P5：全局 manifest 更新导致计划误失效

检查 `workspace_identity.py` 的 `_registry_binding()`、`semantic_value()` 和 identity component 归一化，及 workspace 的 material/projection 组装。保留具体输入 payload/receipt/path/date/PIT 的校验，把确属登记溯源而非语义的全局变化与实际输入变更区分开。

必须用保存产品和当前输入重算复现：仅无关全局登记变化时计划仍可读；任一相关 payload、receipt、目标日期、cutoff或实际选择输入变化时仍能失效。禁止去掉整个失效门禁，禁止靠刷新计划掩盖问题。

## 实施与验收约束

唯一 Luna Max Writer 与不同身份的只读 Luna Max Reviewer；先锁允许路径、基线/SHA、PASS；保留用户修改。小范围修复沿既有 owner，不另造数据底板、长期端口或第二 producer。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。

若要补采历史行情，先读项目 `docs/hk_history_backfill.md`，缓存优先，复用 tdxpy/TDX 权威链；不可默默切换 Futu 额度来源。缺当时证据不能以今天补采伪造历史可用时间。

### 必须逐项交付的验收表

| 编号 | 通过条件 |
|---|---|
| A | 公告原 owner 运行/合法导入 → 同日期真实研究选股及逐股理由 → 产物/receipt → API → 重载页面，run/SHA一致 |
| H | HK 精确会员与 D-1 池合法 → 原算法执行 → 正式结果/receipt → API → 重载页面，不能用backfill冒充 |
| O | 超跌同日期足量历史与量价输入 → 原两门选股执行/完整判定 → 保存 → API → 重载页面，不能只报214 |
| I | 无关 manifest 变化不再误失效；相关输入变化仍拒绝旧计划 |
| R | 10/09历史模式不再报扫描溢出；事后产品不能混进09盘前；现在回看能按真实口径展示已有成果 |
| D | 缺一条来源/一路数据时，其余合法结果仍显示；缺数据与有效零结果分开 |
| N | 下一实际交易日的日常 owner 自动执行、归档和页面读回有自然回执；手动回看通过不能报自然通过 |

正常选股不保证每路每天必有股票；只有完整、合法输入经过原算法实际执行且保存的0只，才能报“有效零结果”。未知/未运行/数据缺失不可写为0。三路未都通过时，整体必须标 PARTIAL/未完成，并列出未通过项；不能以其中一路、US映射或工程测试 PASS 替代整体完成。

### 必须返回的交付物

实际差异与文件前后 SHA；基线/工作分支/commit；针对性复现及独立复跑记录；三路输入、运行、产品和 API/UI 证据；历史/回看/自然三种口径的分别结论；部署/回滚步骤；仍缺的数据及具体恢复责任。不允许只给新ZIP或文字“完成”。

现有测试入口参见 active_source/tests 下 manager_plan_identity、plan_readback_issue24、workspace_targeted_r2、business_completion、selection_ledger 等。按实际修改选针对性测试，新增上述行为回归；本包不声称这些测试已执行。
