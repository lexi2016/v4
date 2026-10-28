# 研报工作台代码精简与优化实施计划

这是用户已批准并明确要求实施的四批计划。实施状态以各批实际源码、独立验收和发布回读为准。

## 1．目标、范围与执行方式

目标：在保留现有业务行为和页面流程的前提下，收敛研报代码版本，减少隐式依赖、重复规则和前端重复转换，让后续修改能在明确位置完成。

架构：保留 Vue、FastAPI、文件归档及现有调度体系。API 和调度独立发布，共享研报模块从同一份源码构建，不新增服务、数据库、数据 producer 或依赖框架。

范围：
- 小时研报的输入读取、证据验证、执行、归档和只读查询。
- 研报决策台的请求适配、状态、计数、时间和展示转换。
- 上述模块的必要测试、构建清单和发布验证。

日级产品仅验证兼容性，不重写其业务逻辑。经理选股、公告分析、公众号归档、OCR 生产、行情采集、Vibe 8910 和整个调度系统不纳入本批改造。

主控负责范围、交接、集成、发布及最终状态。唯一 Luna Max Writer 修改允许路径；不同 identity 的 Luna Max Reviewer 复跑相关测试，出具独立验收。四批串行实施，每批独立提交、验收和回退；通过后不重复无变化的检查。

共同约束：保留真实 CANNOT_CONFIRM、日期/市场绑定、manifest/run_id/SHA、原子发布和 latest 防倒退；保持 RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。

## 2．实施批次与具体交付

### 批次一：收敛小时研报源码与发布版本

交付：小时链路有一份可追溯的源码；API 与调度包携带的共同模块内容一致。

- [x] 冻结当前源码及绑定的 API、调度发布包身份，记录目标文件 SHA、已有修改和有效修复。复用上一轮修复证据，仅检查本轮身份变化。
- [x] 对同名文件实际差异归类为业务差异、发布入口差异、机械拆分差异；保留入口差异，将运行包中的有效业务修复回收到源码。
- [x] 修改限于小时 collector、runner、小时 domain、归档 store 的小时方法及必要依赖；store 的 selection、manager overlay 等职责不随本批重构。
- [x] 从冻结源码快照生成共享模块清单，按相对路径记录 SHA；API 和调度从该快照取共同模块，沿用不可变 release 和差量集成机制。
- [x] 必要拆分模块纳入代码身份计算；重试复用绑定实际执行代码，不能只凭主文件未变复用旧验收。
- [x] 先隔离候选验证，不编辑活动 release，不整包覆盖其他模块。

兼容规则：现有 Python 导入入口、CLI 参数、归档路径和 JSON schema 不变；原始输入和历史产物不改写。代码身份变化后沿用 transform-validation 重新验证；同一产物内容相同保留原 payload/receipt，内容冲突拒绝覆盖。

通过条件：共享清单在源码、候选 API、候选调度间完全匹配；小时链路回归通过；非差量发布文件保持原字节。

### 批次二：消除基础层反向依赖，收敛公共校验

交付：store、runner 不再导入 collector 私有函数；共同规则有明确入口，各业务边界独立核验证据。

| 模块 | 职责与接口 |
| --- | --- |
| infrastructure/research_source_evidence.py | read_zsxq_slot_evidence(data_root, business_date, slot)：读取精确时段 status、summary、fetch result，返回内容及实际字节 SHA；无有效证据返回 None |
| domains/research_source_validation.py | 无文件读写的时间解析、slot cutoff、人工物化时间形状判断和阶段输入验证 |

返回对象固定包含 status 路径、status/summary/fetch 内容及三份文件 SHA。每份文件以同一次读取的字节完成解析和计算，不使用跨请求缓存。

- [x] 精确回执读取迁入 infrastructure，collector、runner、store 共用。
- [x] collector 原私有入口作为过渡包装调用新模块；全仓核引用后在批次四删除无消费者包装。
- [x] 抽取重复时间解析及人工物化判断。来源回执要求显式时区；既有 producer 的无时区时间沿用上海时区解释。页面不能因此升格为已验证。
- [x] 保留 runner、stage reader 各自的 cutoff 和观察时间边界，不机械合并为宽松规则。
- [x] 迁出函数普通导入、明确参数，不依赖 globals() 或 _v4_global。
- [x] 小时 store 读取和发布辅助函数改为普通模块调用；保留类、锁、公开方法，其他 _parts 不批量改写。

明确保留日期、slot、run_id、来源路径、SHA、回执内容校验；owned root 内精确绝对路径兼容；拒绝越界、穿越、跨 run。20261012/1700 人工 READY_EMPTY 仅保留当前恢复边界，不扩展为通用空结果授权。“时间形状符合人工恢复”与“证明允许发布”分开，前者不能授权后者。原始回执没有声明 SHA 时保留诊断，不补造历史声明。

通过条件：小时 store/runner 对 collector 私有读取函数依赖为零；本批迁出函数 globals bridge 为零；有效与无效输入原裁决一致。

### 批次三：收敛页面合同、状态和展示转换

交付：按明确字段展示，缺失值不冒充零，组件复用同一展示转换。

主要路径：apps/web/src/api/research_lane.ts、apps/web/src/composables/useResearchLane.ts、apps/web/src/components/research/ResearchStatusStrip.vue，必要的 ResearchView.vue 与对应测试。

- [x] 合并 HTTP/JSON 读取机制，保留公开签名和研报 legacy 兼容、manager 严格合同两种校验模式。合并传输代码不改变验证强度或请求策略。
- [x] EXACT 日期相等检查、LATEST 实际来源日期展示、requestVersion 防过期覆盖不变；不加请求缓存或扩取消机制。
- [x] 状态条集中生成类型明确的展示对象，标签和字段不散落重复判断。
- [x] “本小时新增”仅接受非负整数 new_item_count；缺失或无效为“未评估”，真实 0 为 0。不以 raw_item_count 或 research_item_count 替代，不加去重统计。
- [x] 财经、AI 计数同样区分有效零和缺失，仅保留已有明确兼容别名，不新增猜测 fallback。
- [x] LIVE_PERIPHERAL_ONLY 显示“小时研报未生成，外围资料可查看”，允许阅读已有外围内容。
- [x] 采集时间、原文时间、恢复执行时间分别表达；时间线复用现有格式规则，保留未知、无时区证据，不加默认时间。
- [x] 状态条派生值响应式计算，payload 改变后更新。
- [x] 保留三栏、筛选、来源栏、公众号入口；仅收敛重复转换，不删除重复展示区域。

不新增/删除 HTTP 路由，不改变归档 schema；新增类型仅用于前端内部展示。缺失计数显示“未评估”是明确允许的行为修正。

通过条件：正常、空、缺失、外围可读、部分完成、错误状态可辨认；切日期无旧响应；缺口和来源信息完整保留。

### 批次四：删除确认无用代码，完成集成交付

- [x] 删除无消费者的 morningFilter；stockTitle() 等出口仅在全仓无消费者且无公开兼容责任时删除，否则保留。
- [x] 删除批次二被替代且无消费者的私有包装/重复实现，退出旧执行路径。
- [x] 保留日级 loader、公众号接口和两个 research router 边界，不因名称相似合并或删除。
- [x] 仅清理由本批引入的无用导入/类型；不全仓格式化、不重命名历史接口、不清旧快照。
- [x] 最新活动 release 明确差量集成，核对非目标模块未替换。
- [x] 独立验收后发布必要 API/调度候选及前端构建，用内置浏览器验证用户原 URL：http://127.0.0.1:8873/?date=20261012&view=research&date_anchor=20260901。
- [x] 必要源码、测试、精简结果同步私有 lexi2016/v4 新分支 codex/research-workbench-simplification-20261012-r1；读回 commit 与关键文件 SHA。排除原始业务数据、凭证、构建目录。〔历史 R1 交付回读为 PASS；2026-10-15 R2 文档收尾不包含在该历史回读中，本轮同步状态见下方收尾记录。〕

## 3．测试与验收矩阵

优先复用既有测试，仅为真实缺口及本批行为变化补测试。

| 场景 | 必须保持或达到的结果 |
| --- | --- |
| 正常小时输入 | 文章、股票证据、来源、安全字段一致 |
| 同输入、同代码重试 | 复用已验证产物，不重复构建或覆盖 |
| 同输入、代码身份变化 | 重新验证；相同内容保留产物，冲突拒绝覆盖 |
| 合规 17 点空结果 | READY_EMPTY、人工恢复标记及实际物化时间保留 |
| 缺失、失败、partial、伪空结果 | 不冒充有效空产物 |
| SHA 篡改、跨日期/slot/run、越界路径 | 拒绝读取或发布，明确错误 |
| 晚于 latest 的历史恢复 | 合规恢复可执行，latest 不倒退 |
| 日产品消费空时段 | 既有有效空时段覆盖统计保留 |
| 计数缺失、无效、真实零 | 未评估、未评估、0 |
| 快速切日期、显式 latest | 不混日期，不被旧响应覆盖 |
| 无采集时间、原文无时区 | 未知状态及原始证据保留 |
| OCR/重点消息未生成、partial | 不显示完成或有效零 |
| 公众号、筛选、三栏、窄屏 | 流程可用，无挤压、横向溢出 |

后端按变更面运行 hourly runner、ready-empty recovery、hourly regressions、lane、day materialization、release integration；前端研报视图/请求合同测试、typecheck、build。独立 Reviewer 复跑相关检查。

无关失败记录基线，不顺手修；新增失败必须解决。固定时钟等价比较仅排除预先列明的执行身份字段，不能排除来源时间、状态、来源 SHA、安全字段。

## 4．发布、回退与停止条件

顺序：候选验证 → 独立验收 → 差量集成 → API/调度加载核对 → API 回读 → 内置浏览器。

共同模块来自同一快照，各自入口和其他模块独立。历史输入/产物/回执不改写，不主动重跑全天。回退仅切回上一份已验收代码 release，不删数据、不回退 latest、不用全局 reset/clean/stash。

目标行为变化、日期/PIT 放宽、有效数据丢失、真实缺口隐藏、历史覆盖或非目标模块变化时停止本批，保留复现并回退候选。手工/隔离验证分别记录；真实自然时段发生且证据有效才标 NATURAL_VERIFIED。本计划不新增监控或计划任务。

最终分别报告 IMPLEMENTED、REVIEWED、TESTED、DEPLOYED、API_VERIFIED、UI_VERIFIED 与自然执行状态。

## 5．完成标准与默认决定

1. 共享模块在源码与两个运行包间可逐文件定源，不再独立维护业务补丁副本。
2. 小时 store/runner 不反向依赖 collector 私有函数；迁出逻辑不依赖 globals bridge。
3. 公共规则只有一份实现，各业务边界仍独立验证真实证据。
4. 页面状态、时间、计数语义明确，真实缺口保留，流程通过内置浏览器。
5. 被替代旧实现退出；无关代码和用户已有修改保留。
6. 必要变更独立验收、差量发布、私有仓库读回核验。

默认保持依赖、布局、接口、业务规则；不设行数减少比例，不扩成全系统重构或性能工程。计划保存为 docs/superpowers/plans/2026-10-12-research-workbench-simplification.md。活动 release 身份若变化，以最新实际 base 差量集成并保留无关修复，不把启动时快照冒充活动版本。


## 实施记录（截至 2026-10-13；状态按证据分层）

- 批次一独立验收为复合链：初审 `reviewer/task-1/review.json` SHA-256 `f721b43634e3f033e941f724e9503f1b0464047fa5a376bddac7bbf125170ee4` 报两个 P1（scheduler 缺少 `infrastructure.trading_safety` 依赖；API READY_EMPTY store reader 依赖不存在的 collector helper）；R2 复核 `reviewer/task-1-r2/review.json` SHA-256 `5ca28ab9225d0c7838f38525739a07f91916e64c50dccec04e86309680aa84ac` 独立重建 API/scheduler candidate 并分别以 23 项测试和 READY_EMPTY 精确读取关闭两项问题。整批状态为 PASS_COMPOSITE。共同模块 bundle SHA `b7d0ecc71b63e8309ce4202a25da65e9d05889d5f8503bb3c79d6a20775a6c19`。
- 批次二独立验收为复合链：初审 `reviewer/task-2/review.json` SHA-256 `17447b5f7b3b47aafa531f25fa5b630daf9240a3bd09f7fed13eb2e2a614b6e6` 因 scheduler candidate 丢失 manual READY_EMPTY 授权参数报 FAIL（P1）；闭环复核 `reviewer/task-2-r2/review.json` SHA-256 `f9afe1409b90087f97c32e3da5ad990f3202dc95caae03d921aa328ce0eb81d9` 针对该调用点、发布/拒绝和 latest 不回退复核 PASS 并关闭该问题。整批状态为 PASS_COMPOSITE；52 项源码测试和 API、scheduler candidate 各 33 项通过。
- 批次三独立复核：REVIEWED / BEHAVIOR_VERIFIED PASS；receipt `reviewer/task-3/review.json`，SHA-256 `ed6020863a58f2b20a89475e74d4a0512c6d578b15e8c376f748ef3f7c62ace7`。人工物化时刻仍为 CANNOT_CONFIRM：lane contract 只有 `source_generated_at`/`source_binding`，没有 `materialized_at`/`execution_origin`。
- 批次四源码改动移除确认未使用的 `morningFilter` 和 canonical/API 中无消费者的 collector 过渡包装 `_read_status_artifacts`。兼容入口、日级 loader、公众号接口及两个 research router 保留。当前 scheduler collector wrapper 仍有两个真实调用点，按已接受的 R2 兼容例外委托共享 reader；不声明全仓引用归零。完整源码/候选适配、before/after SHA 与验证命令见 `evidence/writer/task-4-report.json`、`task-4-changed-files.json`、`task-4-allowed-file-inventory.json`、`task-4-runtime-adapter-inventory.json` 和 `task-4-diff.patch`。
- 批次四候选组合验证：`evidence/writer/task-4-candidate-verification-r4-final3.json` SHA-256 `feacea6cf63d1a81a1efc90eb8439053a8ed0a44dc93f9a722f7fdb9377ef21a` 为 PASS；API/scheduler shared bundle SHA 均为 `57c89f9c0561723fb17532590ae53b779a97b075625c97102d1522933542fb65`。此为候选验收，不替代本批独立 Reviewer verdict。
- 批次四定向源码测试：109 passed，1 项已知外围 fixture 缺少 `captured_at` 的无关用例按冻结范围 deselect；前端研报测试 38 passed，Vite build PASS。`npm run typecheck` 保留批次三已知的四个未改文件诊断（managerWorkspace.attention.spec.ts 两个 TS18048，ManagerSelectionView.spec.ts 两个 TS2578）；无新类型错误。
- 最终 API 候选基于 `announcement-preopen-20261012-r4`，scheduler 候选基于 `research-hourly-empty-20261012-r4`。本批仅生成隔离候选；API/调度发布、API 回读、浏览器 UI、私有 GitHub 同步和自然时段状态由主控按批准计划完成/记录。自然执行只在真实发生且证据有效时记录，不等待或新增监控。

## 2026-10-15 文档收尾与当前核对

本节只整理既有四批实现和本轮读回证据，不记录新的业务代码实施。完整只读完成度审计为 `.superpowers/sdd/2026-10-12-research-workbench-simplification/resume-audit.md` 与同名 JSON；审计结论是四批源码已实现、当前 API 与 scheduler 各有 9/9 个共享模块 SHA 匹配 canonical，没有已证实的四批代码缺口。

- 批次一：初审有两个 P1，R2 分别关闭 scheduler 缺依赖与 API READY_EMPTY reader 缺 collector helper；独立重建的两个 candidate 各 23 项通过，且 API READY_EMPTY 精确读取通过。两份 verdict 组成 PASS_COMPOSITE。当前计划外 25 个源码/测试路径中，22 个 SHA 与历史基线相同；其余 3 个前端文件绑定到后续独立接受的 active-base runtime projection，不作为未审变更。当前 9 个共享模块在 API 与 scheduler app root 均逐项匹配 canonical。
- 批次二：初审 `reviewer/task-2/review.json` SHA-256 `17447b5f7b3b47aafa531f25fa5b630daf9240a3bd09f7fed13eb2e2a614b6e6` 曾报 P1 FAIL，发现 scheduler candidate 的 manual READY_EMPTY 授权参数丢失；R2 闭环复核 `reviewer/task-2-r2/review.json` SHA-256 `f9afe1409b90087f97c32e3da5ad990f3202dc95caae03d921aa328ce0eb81d9` 针对该调用链及 latest 不回退复核 PASS。两份复核组成整批 PASS_COMPOSITE。迁出的 store/helper 范围不依赖 globals bridge；本批没有重写未迁移的 domain entity extraction。
- 批次三：历史 Reviewer、38 项前端测试与 build PASS。页面保留未知时间与缺失值；源记录缺 capture/fetch 时刻及时区，人工物化时刻也没有独立字段可证明，相关时间语义保留 CANNOT_CONFIRM。
- 批次四：初审 `reviewer/task-4/review.json` SHA-256 `a94c55ba6c510323bd33e713c8c55d99434d9c91314f71de0d70450a93183dbe` 曾因 runtime wrapper 适配差异报 P2 FAIL；R2 闭环复核 `reviewer/task-4-r2/review.json` SHA-256 `cdb64361ddab587f6e218bcd5f4c33f6daca655029392a905726d47e5f855960` 修复并接受 API wrapper 移除、scheduler 两个真实调用点保留兼容委托，复核 PASS；R3 `reviewer/task-4-r3/review.json` SHA-256 `d91766f08c9a5e96071f2f847fa63e6e7b312ba264eb932328fae42c73bddb92` 只对 READY_EMPTY v1 回执兼容做窄复核 PASS。三份 verdict 共同组成 PASS_COMPOSITE，R3 窄 PASS 不替代初审与闭环复核。`stockTitle()` 因公开兼容责任无法排除而保留；不扩展到整个 domain globals 清理。

历史实施、独立复核、测试、集成、部署、API 回读、UI 回读分别保留各自的 PASS 证据；这轮没有业务源码改动、部署或重启。当前证据：`.superpowers/sdd/2026-10-12-research-workbench-simplification/api-readback-current.json`、`ui-verification-current.json` 和 `runtime-process-readback.json`。当前 API 回读含原 20261012/1700 hourly response SHA-256 `22186513df8c44a25068f996479143d23a7e3f9ede28d7b4965acf9570403909` 与日产品 SHA-256 `888e973d083d27457cde4b617748dc8a9b0ea6491d4d77b26edf22fae330ace6`，均与历史回读相同；LATEST 指向 20261015/1500。实际浏览器加载原 URL，核对 10-15、7 个非公众号筛选、EXACT/LATEST、换日与 1280/768 窄屏，未见横向溢出或 console error；本轮 UI 状态为 UI_VERIFIED。

运行身份读回显示 API listener PID 49933 位于 `hk-auto-execution-audit-api-20261015-r1/app`，scheduler PID 49678 位于 `hk-pool-fupan-isolation-20261015-r1/app`。API manifest 的 `activation_status=NOT_ACTIVATED` 与进程 cwd 实证不一致，保留为元数据差异，不据此覆盖进程证据。当前研究来源时间语义仍为 CANNOT_CONFIRM；自然时段仍为 NATURAL_SLOT_UNVERIFIED。

历史 R1 私有 GitHub 交付有独立读回 PASS。主控已创建 `codex/research-workbench-simplification-20261015-r2`，起点为 `e0e676161c394eaa822110b184e2927bbcea6953`；本计划与 handoff 的文档 commit 尚未推送，远端文件 SHA readback 待完成。本 handoff 与 receipt 只证明当前本地文档 closeout 和本轮 API/UI 读回。
