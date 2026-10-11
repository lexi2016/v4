# 03_超跌反弹及计划读回 · 独立修复问题包

## 本包唯一业务目标

同日期合格行情、60个完整交易日和成交量来源进入既有两门筛选，输出真实逐股研究选择台账与最终名单并归档/读回；214初筛数量不能代替选股闭环。另负责两项共用计划读取缺陷和最终三路接入。

本包是共用文件唯一集成者：负责历史扫描溢出、计划语义身份，以及合并01/02已验收的接入补丁；不得代替01/02重写公告或港股通算法。先独立完成本路，再串行集成01/02，不能同时覆盖相同文件。

## 当前复现

页面 http://127.0.0.1:8873/manager-selection/?date=20261009&plan_date=20261009 。GET /api/v4/manager/research/workspace?date=20261009；本路为 OVERSOLD。公告日为20261008、目标日20261009。完整原响应派生摘要附在evidence中；其他路字段仅作上下文，不属于本包实现范围。

### 已查明的本路问题

超跌反弹初筛回放不是完整选股闭环

此前 10/12 计划读到基于10/09的 214 strict / 286 near 研究候选、34待核；明确 `formal_selection_input=false`，不是正式 Stage 或重点名单。当前10/09历史模式连经过验证的 screen date 都没有。

沿现有 HK_0_2 rebound two-gate screen / 选择台账 owner，核实目标行情会话、前60个完整交易日及成交量来源。检查 `research_attention.py`、`workspace_daily_channels.py` 和相关 projection。需要有真实运行身份、逐股判定与原因、输入/产品 SHA、保存/读回，不可简单把 strict 列表改名为正式结果。若既有策略合同只定义研究筛选，应明确其最终研究名单，并与正式 Stage 名单分列；不得新造算法或以显示变更代替 owner 执行。



## 本包另外负责的两项共用缺陷

### P1：历史读取按全量计划正文累计，遮蔽正确的历史状态

配置指向的 `v4/manager_research/workspace_history.py`：`select_plan()` 先读 latest，再扫描其他 run；累计 `_MAX_SCAN_BYTES=64*1024*1024`，超过即报上述错误。

真实 `workspace_plans/20261009` 有 7 个 JSON（含 latest），共 147,031,510 字节，单件约 14.8–23.4 MB。所有现存产品的 generated_at 均在 10/10–10/11，晚于 10/09 09:30。这意味着解除大小错误后，也不能把这些事后计划冒充 10/09 当时计划。目录包含 latest 与同一 run 的重复内容。

应沿既有存储合同修复有界查找/索引或选择逻辑，避免为了发现“无合格历史计划”扫描全部重复大正文；具体方案须基于实际代码。继续校验原产品 SHA、日期、cutoff、时点及路径安全，不可仅提高上限，不可删除归档换通过。最终历史模式准确显示“无合格当时计划”；显式现在回看模式才消费事后生成结果。


### P5：全局 manifest 更新导致计划误失效

检查 `workspace_identity.py` 的 `_registry_binding()`、`semantic_value()` 和 identity component 归一化，及 workspace 的 material/projection 组装。保留具体输入 payload/receipt/path/date/PIT 的校验，把确属登记溯源而非语义的全局变化与实际输入变更区分开。

必须用保存产品和当前输入重算复现：仅无关全局登记变化时计划仍可读；任一相关 payload、receipt、目标日期、cutoff或实际选择输入变化时仍能失效。禁止去掉整个失效门禁，禁止靠刷新计划掩盖问题。


## 源码与协作边界

源码根 /Users/lexi/Desktop/学习/v4_app，统一入口8873，Vibe8910不动。source/为前一问题包配置指向源码的静态摘录；shared_reference/为只读共用接口参考。两者不是完整可部署release。SOURCE_MANIFEST.json保留原配置根、canonical与配置文件SHA；实际加载进程身份仍CANNOT_CONFIRM。配置所指manifest含NOT_ACTIVATED/base旧状态，不能单凭该字段或LaunchAgent配置决定现役基线；实施前核实际进程/部署回执，保留既有HK/US修复和用户修改。

01和02只修改各自业务owner文件；需要改shared_reference内文件时，只交最小接入补丁和合同给03集成，不直接并行覆盖共用文件。03为共用文件唯一Writer。非所列文件发现必须修改时先明确新增ownership，不能悄悄扩展。按01、02各自交付后03串行集成；三包都不单独覆盖式发布整个旧快照。

## 本包验收（不可降级）

1. 原 owner 的合法日期/来源输入经过实际选股，产物有运行编号、输入与产品SHA、逐股理由；选股规则和BUY边界不变。
2. 保存后重新读取API，重载页面，结果/日期/run/SHA一致。01/02依赖03共用修复未集成时，只能报本路实现/待集成，不能提前报页面闭环。
3. 缺数据明确日期、字段、owner与恢复办法；一路缺件不能遮住其他有效路。输入完整且算法实际执行后0只允许；未知/未运行/缺数据不能写为0。
4. 当时历史、现在回看、未来自然运行分别验收；事后资料不能冒充20261009 09:30之前可得。历史无法恢复不等于可以放弃日常链路修复。
5. 下一实际交易日的自动owner生成、归档、API与页面读回必须验证；未到自然时段标NATURAL_SLOT_UNVERIFIED，手动不能代替自然。
6. Luna Max唯一Writer与不同身份独立Reviewer。提交实际diff、前后SHA、针对性测试独立复跑、真实产物与UI证据及缺口。映射、初筛、HTTP200、测试或报告均不能替代选股完成。

## 全局结案

各包只裁定自己的状态。只有三路均通过，且03的历史读取、计划身份及最终页面集成通过，整体才可结案。03还须验证无关global manifest变化不误失效，而相关输入/date/cutoff变化继续拒绝旧计划。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。复用既有权威数据和TDX缓存/补采链，不建producer、不伪造历史PIT。没有数据必须报告，不能造股票填名单。

本次是拆包交接，未实施新修复、未测试业务、未部署。原整包审查PASS不自动等于三个新包业务验收PASS。
