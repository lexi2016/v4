# V4 修复与正式页面点击验收 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 执行方法已由用户指定：子代理使用 Luna Max / Sol High，主控集成；本文件是计划，不代表已实施、已部署或已完成点击验收。

**Goal:** 收束 Claude 已有候选，按单一机制修复，并以实际 8873 发布版本的真实页面点击验证用户行为。

**Architecture:** 保留 V4 唯一入口、既有 API、producer 和发布链。先对应源码与运行组件，再以独立小补丁修复；隔离故障注入验证后台正确性，正式浏览器点击验证发布后的用户行为，两类证据均不可互相替代。

**Tech Stack:** Vue / TypeScript / Vite / Vitest；Python / FastAPI；现有 scheduler、Stage、manifest / receipt 合同。

**Spec:** 用户 2026-10-29 本轮要求“列修复计划、正式页面点击验收、子代理 Luna Max 与 Sol High”，以及下述冻结需求。既有交付参考：[类型小修回执](/Users/lexi/Desktop/学习/agents调试/v4_budget_finish_20261029T124742Z/实施结果.md)。

**最新 DECISION_LOCK（用户后续纠正）：只在电脑使用，窄屏修复没有必要。P8与所有375px/移动端验收取消；不得再投入窄屏、为其发布或申请管理员权限。保留历史候选与失败证据，仅桌面真实功能进入后续优先范围。**

**维护与清理要求（用户本轮补充）：小修复用既有模块，不叠加通用框架、依赖、平行 producer、历史面板或长期临时服务。验收后清理本批已无依赖的候选、构建、软链接及一次性脚本；仅保留必要源码、有效测试、精简验收/失败证据及仍需使用的回滚材料。用户原始数据、其他任务变更和既有系统不纳入泛化删除。**

## 冻结需求与当前证据

- 唯一源码根：`/Users/lexi/Desktop/学习/v4_app`；正式用户入口：`http://127.0.0.1:8873/`。
- 计划基线：`7ed00ca916a55a55a0bea95944c004cb6570b6f1`；当前分支 `claude/v4-typecheck-budget-20261029`。这是工作区身份，不是现役 release 身份。
- 已有类型补丁仅修改两份测试；回执记录 typecheck PASS、定向测试 109 PASS / 3 FAIL，基线复现同三失败。复用匹配证据，不重做已有差异独审。
- **正式经理入口存在组件错位：** `apps/web/manager-selection/index.html` → `src/manager-selection/main.ts` → `src/manager-workbench/Workbench.vue`；旧 `ManagerSelectionView.vue` 测试不能代表该正式页面。
- root `/` 由 `App.vue` 提供阶段、研报、复盘入口；`/daily-research-command/` 是独立构建入口。正式运行发布单元仍需 P0 实测对应。
- Claude 的“20 条”目前只有聊天摘要与有限本地产物，未获得完整逐条 ID/复现清单。下表覆盖已知主题；不得声称已逐项认证全部 20 条，也不继续扩展查新。
- `18873` 为遗留临时只读预览，本轮只读检查仍监听；正式验收不使用它。其停止状态不能标完成。
- 本轮仅编写计划，业务修复、部署、正式点击均 `NOT_RUN`。

## Global Constraints

- `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- A 股有效可追溯汇总行可进入阶段选股；缺失、空或 partial 子池不全局阻断，坏来源局部隔离。A/HK 分离，来源 SHA / 日期 / 去重 / 完整输入保持。
- 不修改 BUY、交易、原始行情、凭证权限、Vibe 8910；不建第二面板、第二 producer 或通用恢复平台。
- 每个重叠文件集同一时刻只有一名 Writer；新实现用独立 `codex/` 工作分支和 managed worktree，保留原冻结分支和用户变更。
- 业务小补丁针对性检查后默认一次独立只读 Reviewer；不把准备、源码、单例、打包另拆多轮审批。不因同代码重复复查。
- 代码变更按既有授权同步 `lexi2016/v4` 对应分支并读回 commit / 关键文件 SHA；认证失败保留 `NOT_SYNCED`，不搜索密钥、不改认证、不冒称已同步。
- 计划不执行 merge、deploy、启停服务、计划任务变更或生产故障注入。实施时正式发布沿用用户当时授权及唯一发布 owner。
- 用户最新决定（2026-10-29）：“不用管预算问题”。取消本轮 13 USD 收束条件，不再查账或以旧预算停止；历史计价与未知项仍保留，不据此声称平台费用或余额。

## Review Focus

1. 旧组件测试与正式入口不一致：P0 / P1 / U2 确认消费者，不以旧测试升格正式 UI。
2. 父进程退出而子进程仍运行、已产生副作用但汇总回执未写：P3 用隔离进程与持久化证据核验恢复决策。
3. 同一瞬间的 UTC / 上海表示、HK 半日下午与 A 股仍开市：P4 验证时间窗口和市场分别准入。
4. 翻页中数据更新、旧日期慢响应、刷新缓存命中旧资源：P2 / P6 / P7 核验版本、日期、快照及页面状态。
5. 缺失输入、partial、NaN、空详情：P4 / P5 / U3 / U9 保留拒绝或未知状态，不能补零、误升 READY 或显示旧股。

## 模型能力与 ownership

| 工作 | Writer / 执行者 | 独立验收 | 路由依据 |
|---|---|---|---|
| 来源路径、运行组件、发布文件对应与机械清单 | Luna Max | 主控核对；有证据冲突时交 Sol High | 局部只读，先确定实际 owner |
| 测试交互修正、小范围 CSS、明确资源路径修复 | Luna Max | 另一身份 Luna Max；触及发布边界时 Sol High | 有界、可复现、影响局部 |
| claim / 锁 / 子进程 / 完成凭证 | Sol High | 另一身份 Sol High | 并发与恢复存在跨模块状态风险 |
| 日期窗口、字段适配、分页快照、导航与缓存状态 | Sol High | 另一身份 Sol High | 跨消费者合同和异步状态 |
| 正式页面点击和窄屏量测 | 唯一 Luna Max 浏览器执行者 | 复用该补丁 Reviewer 核验点击证据；高风险由 Sol High | 操作串行，浏览器不被多个代理争抢 |
| 集成、发布范围、最终状态裁决 | 主控 | 消费以上对应独审结果 | 主控不代写业务代码、不重复审查 |

- Luna Max：`gpt-6-luna` / `reasoning_effort=max`；角色 `luna_writer` / `reviewer` 或适用的只读通用入口。
- Sol High：`gpt-6.1-sol` / `reasoning_effort=high`；角色 `sol_high` / `sol_high_reviewer`。
- Writer 和 Reviewer 必须是不同代理身份；Sol 写的复杂补丁由另一 Sol 审，不能自审。Luna 一次有证据返修仍无法闭环，释放 ownership 后带最小复现移交 Sol；健康等待不换模型。
- 实施最多并行两个不重叠 Writer；scheduler / ledger / Stage 等共享链串行。浏览器始终只有一个控制者。
- 本次计划辅助：Luna Max 通用只读子任务 `ui_acceptance_plan`，Sol High 只读子任务 `reliability_plan`。两者 final 已收到并消费；均未改源码、运行测试或接管浏览器。请求配置与角色定义已核对；工具未提供后端模型身份认证，不能额外声称 runtime model 已独立证明。此为计划输入，不是业务修复 Reviewer PASS。

## 修复顺序与独立交付表

P0 完成后，先选择已证实影响现役用户路径的最高优先项；其余保持 backlog。P3 的四个机制分别做小补丁，不合并成一次恢复框架重写；P4 的时区与半日窗口也分别提交和验收。

| 批次 | 唯一目标与最小改动 | 主要路径 / ownership 边界 | Writer → Reviewer | 通过条件 |
|---|---|---|---|---|
| P0 必做前置 | 对应 canonical / API / scheduler / Stage / web，给每个候选标实际消费者及现役相关性 | 只读启动入口、release 清单、精确目标文件 SHA、`apps/web/vite.config.ts`、两个经理入口组件 | Luna → 主控；冲突交 Sol | 每个拟修目标有 commit、release、启动入口、消费者；未知者 `CANNOT_CONFIRM`，不改错副本 |
| P1 原三失败 | 标题对齐正式入口合同；请求断言按必要端点/日期/重复请求；旧待核历史测试先展开再断言，保留切日失败清空断言 | `apps/web/src/views/ManagerSelectionView.spec.ts`、`apps/web/manager-selection/index.html`、对应正式入口测试；仅证实缺陷才改业务 | Luna → 独立 Luna | 原三失败分别说明过期断言或实际缺陷；两文件定向检查通过且断言未削弱；明确旧组件与正式 Workbench 的覆盖差别 |
| P2 发布资源 | 仅修现役确有失败的 HTML / JS / JSON / 图片依赖，保留安全白名单 | `apps/api/v35_api/app.py` 静态发布与已定位的前端引用；测试 `tests/test_static_cache_headers.py` | Luna → Sol | 同一发布单元的必要资源加载成功；刷新/重进仍匹配版本，无未解释 404；安全拒绝行为仍成立；完成 U1 / U5 |
| P3a claim | 消除初次 claim 可见但内容未完整写入的窗口，优先复用既有 SafeRoot 完整写入与不覆盖发布能力 | `infrastructure/scheduling/execution_ledger.py`、`infrastructure/owned_io.py`、`tests/test_runtime_dispatcher.py` | Sol → 独立 Sol | 隔离测试覆盖发布前中断、短写、部分写入、并发竞争及文件/目录持久化边界；不会读取半成品、覆盖其他 owner 或获得两个执行权 |
| P3b 恢复锁 | 回收互斥能在 owner 异常退出后安全处理；活 owner 不被偷锁 | `execution_ledger.py`、`infrastructure/interprocess_lock.py`、`stage_center/_runner_parts/slot_lock.py` 中本批确有缺陷的单一路径 | Sol → 独立 Sol | 隔离测试覆盖锁持有者退出、活 owner、竞争恢复和异常退出；没有永久等待，也不删他人活锁 |
| P3c 父死子活 | 补既有执行链的实际工作所有权与恢复判断，父退出不盲目重新启动活子进程 | `execution_ledger.py`、`infrastructure/scheduling/_executor_registry_parts/process_boundary.py` 及其针对性测试 | Sol → 独立 Sol | 隔离测试令子进程持有执行哨兵，终止父进程后以同身份重入，最大同时执行数仍为 1；子仍活、已结束、副作用已发生但凭证缺失分别明确处理；完成 U8 |
| P3d 完成凭证 | 逐工作项完成后持久留证，恢复不因整批回执未写而重复已完成项 | `execution_ledger.py`、`dispatcher.py`；仅证实重试元数据缺陷才改 `manager_capture_retry.py` | Sol → 独立 Sol | A 项成功、B 项前/中父退出，恢复后 A 调用次数仍为 1；错日期/市场/run_id/SHA 凭证拒绝；完成但凭证未提交窗口明确保留未知；重试元数据中断先复核，已有前置阻断、缺时间戳处理仍保留；完成 U8 |
| P4 时间窗口 | 同一瞬间时区表示等价；HK 半日收盘后不进入下午窗口，A 市场独立；不重写已正确识别半日的日历 | `stage_center/scheduler.py`、`calendar.py`、`runner.py` 对应委派入口；`tests/test_trading_calendar_policy.py` | Sol → 独立 Sol | UTC / 上海成对测试结果一致；半日早盘/午后边界、仅一市场开市各自正确；正式历史点击 U1 / U6 另记结果，不称自然认证 |
| P5 输入合同 | 修已复现的适配字段丢失；对真实参数入口复核有限值拒绝 | 实际 producer→adapter→Stage 消费路径；`stage_center/_runner_parts/selection_input_validation.py`、`infrastructure/owned_io.py` 仅按 P0/P5 复现冻结 | Sol → 独立 Sol；单纯有限值局部缺口可 Luna 写 | 必要字段、来源、日期、SHA、完整行数守恒；有效 A 行不被 partial 子池全局阻断；NaN / ±Inf 入口拒绝。`owned_io.py` 已有 finite 校验、SlotLock 固定 timeout=0；无反例就复用并关闭相应候选，不制造改动 |
| P6 研报传输与展示 | 针对仍复现的超量传输/挂载修最小路径；复用已有 PDF 正文按需加载，列表固定快照分页与详情身份对应 | `apps/web/src/views/ResearchView.vue`、`components/research/ResearchFeedPane.vue`、`ResearchFeedCard.vue`、`apps/web/src/api/research_lane.ts` 及其实际后端 owner | Sol → 独立 Sol | 列表/正文/分页分别验证；分页无重复遗漏且来源快照固定；切日旧响应不覆盖新页；完整选股输入未被分页截断；完成 U5 |
| P7 导航与缓存 | 日期/阶段/视图在刷新和历史导航后保持；同日重入复盘触发必要更新；名单与独立详情入口身份一致 | `apps/web/src/app_shell/useAppShell.ts`、`App.vue`、`manager-workbench/Workbench.vue`、`useWorkbench.ts`；每次只修一个已复现机制 | Sol → 独立 Sol | 刷新/后退/前进恢复一致；同日复盘不是未失效旧缓存；股票详情保持 code/date/run_id；完成 U2 / U3 / U6 / U7 |
| P8 窄屏 | 仅修长诊断/证据内容引发的文档级横向溢出 | 对应工作台与 `apps/web/src/components/daily-research-command/DailyResearchHourlyDiagnostic.vue`、实际 CSS | Luna → 独立 Luna | 375px 真实视口下，展开长内容后 document scrollWidth ≤ clientWidth + 1px，文字与操作可读；不截断完整证据；完成 U9 |
| P9 发布后交付 | 集成对应已审补丁，核验正式运行版本并逐项点击受影响链路 | 已授权的唯一正式发布链；只读点击与精简证据目录 | 主控集成；唯一 Luna 点击；对应独立 Reviewer 收束 | 对应补丁离线验收、独审、同步、部署、API 和 U 项点击状态分别有证据；正式点击缺失时不得报该用户行为修复完成 |

“25 条默认 / 50 条上限 / 500 KiB 列表 / 约 60 张卡片”沿用为 P6 候选性能目标，尚非当前实现或量测结论。P6 先冻结真实列表接口、快照语义及量测场景；若采用这些值，分别以响应字节数、页大小、实际挂载数验收。已有 PDF 按需详情不得再造一套；当前不存在的总 feed 分页属于拟实现行为，不能写成已经存在的按钮。

## 正式页面点击验收矩阵

所有 U 项必须使用 **实际 8873 正式页面**。18873、preview、临时端口、截图静态文件、jsdom、直接 API 返回都不能代替。路径和按钮以部署后实际 DOM 为准；若与表不一致，保留证据并核对 release，不盲点。

样本冻结：从已有日期目录与已保存 run 中选最多 3 个代表场景，优先正常 A/HK 日、已知 partial / 缺项日、已有 HK 半日日；每场景记录日期、市场、run_id / manifest / SHA 和选样原因。没有所需真实数据记 `CANNOT_CONFIRM`，不补抓或伪造数据。UI 只读点击，不点击“执行/采集/生成/重算”等会写业务状态的控件。

| ID | 正式入口与真实点击步骤 | 必须看到的结果 | 证据及缺口 |
|---|---|---|---|
| U1 阶段 | `/` → “阶段”选择器或时间线 → `13:00-13:15` → “刷新快照” | date/stage 一致，实际阶段为 `STAGE_1300_1315`；A/HK 各自状态、partial、观察行不误升格 | 前后截图、URL、对应请求或同参数 API 回读；这是历史/手动读取，不是 13:15 自然运行 |
| U2 名单诊断 | `/manager-selection/?date=YYYYMMDD` → “今日名单” → 指定股票“查看详情” | 同一 code/date/run_id；依据、待确认条件、失效条件、风险可读；切另一股票不残留旧内容 | 冻结一只实际行与版本，点击前后截图、详情身份；“完整诊断”按实际控件名“查看详情”定位 |
| U3 独立详情 | 直接进入“个股详情”标签；再回名单选择股票并重进详情 | 空选明确“未选择”；选择后各详情入口身份一致；不能以内联诊断成功代替独立标签验收 | 分别保留空选/选中截图；若正式路由仍未接通，记 FAIL 或 CANNOT_CONFIRM 并归 P7 |
| U4 行业目录 | `/` 的全局行业图 → 其“刷新”；经理工作台 → “美股映射资料库” → 选择可用条件 → 有数据时“下一页” | 目录、查询条件、日期/来源一致；分页范围改变且无跨快照错配；原生板块/历史主题边界仍可见 | 目录入口与分页分别给结果；样本无下一页数据时不冒称翻页通过 |
| U5 研报阅读 | `/` → “研报决策台” → “按所选日期” → 切“全部/股票/公众号”；存在可读 PDF 时点“查看完整 OCR 正文”再“收起 OCR 正文” | 所选日、实际来源日一致；正文按对应 document_id / 日期读取，展开收起可用；P6 增加的总 feed 分页需在正式页面点击首/次/末页 | PDF 正文、普通股票研报卡、公众号分页分开报告；当前无普通股票卡详情按钮，不伪造“详情已接通”；已有“查看 latest”只在显式点击后显示实际来源日 |
| U6 复盘重入 | `/` → “A股复盘” → 阶段时间线首个港股收盘复盘入口 → 离开再同日重入 → “刷新快照” | 市场、日期、标题一致；重入与刷新按失效合同更新；不显示前一市场或旧日数据 | 分别截图与记录读取时间/版本；不存在独立“港股复盘”导航 tab，不虚构按钮；没有新产物时只验触发读取，不称内容已经更新 |
| U7 历史导航 | U1/U2/U6 中受影响页面改变日期/阶段/视图 → 浏览器刷新 → 后退 → 前进 | URL、选中控件、页面内容、请求身份一致；新页不会被旧慢响应覆盖 | 每步 URL 与截图；必须实际浏览器操作，不能只验证 history mock |
| U8 恢复展示 | `/` → “任务状态” → 读取修复覆盖的真实任务/阶段结果 | 等待、完成、失败、未知状态与已保存 receipt 一致；不把父进程消失当成功或可重跑 | 正式页面只读；kill、锁冲突、半写入等故障仅在隔离测试注入，UI 点击不能单独证明恢复算法正确 |
| U9 窄屏 | `/`、`/manager-selection/`、`/daily-research-command/?date=YYYYMMDD` 中受影响代表页设 375px → 展开最长已有诊断/证据 | 无文档级横向溢出；按钮可点击、正文可读，必要内层滚动不推宽整页 | 视口截图、scrollWidth / clientWidth 量测。无真实长文本则该场景 CANNOT_CONFIRM |
| U10 旧待核组件 | 仅当 P0 证明正式现役确有该组件消费者时，进入其真实入口 → 展开“待核历史” → 切日验证旧内容清空 | 延迟渲染符合合同，切日失败不留旧股票 | 当前正式经理入口是 Workbench，旧组件只由测试覆盖；当前标 `CANNOT_CONFIRM`。不为凑验收新增入口或强行挂载旧组件 |

## 每个代码补丁的执行清单

以下清单随每个独立补丁执行一次；不是对准备、打包再加独审。只选择上表该批次的精确目标文件，未列入实际 allowlist 的路径不得修改。

- [ ] 从 P0 结果冻结 GOAL、Writer、独立 Reviewer、基线 commit、精确 ALLOWED_PATHS / FORBIDDEN_PATHS、PASS_SIGNAL、STOP_RULE；记录未部署依赖与目标文件前 SHA。
- [ ] 固定最小复现或复用同字节有效失败证据。时间/并发问题使用隔离目录与进程；不在正式服务注入。
- [ ] Writer 仅改一个机制，保留原始数据与用户变更；按表中条件写有意义的回归断言。
- [ ] 执行针对性检查。前端使用已验证环境：`npm --prefix /Users/lexi/Desktop/学习/v4_app/apps/web run typecheck`；P1 用 `npm --prefix /Users/lexi/Desktop/学习/v4_app/apps/web run test -- src/api/managerWorkspace.attention.spec.ts src/views/ManagerSelectionView.spec.ts`；正式 Workbench 的新增目标测试单列。其他批次只选相关测试，不默认全量。
- [ ] Python 使用 P0 核实的绝对 `PANEL_PYTHON` 或既有项目环境；记录解释器身份和精确 `-m pytest` 测试路径，不假设 PATH 中 Python 正确。
- [ ] 独立 Reviewer 一次核验冻结差异、针对性结果与直接风险；实质变更或新失败才复核受影响部分，已有匹配 PASS 复用。
- [ ] 逐项路径提交、同步已授权仓库并读回。独立验收、同步、部署分别记状态；同步失败不覆盖原错误。
- [ ] 在正式发布范围具备授权后，由唯一发布 owner 集成并部署对应已审版本；读回运行身份、前端资源和关键 API。
- [ ] 唯一浏览器执行者在实际 8873 完成该补丁对应 U 项；原先匹配的 U 项不因另一无关补丁重复全部验收。修改共同入口/资源时补必要入口冒烟。
- [ ] 保存一个精简 receipt：batch、URL、release/commit、关键文件 SHA、date/market/stage/code/run_id、点击步骤、预期/实际、截图路径、量测与结果。浏览器请求可观测时记录真实请求；仅 API 同参数回读时明确是独立回读，不称抓包。
- [ ] 结束本批 GUI 控制，按工具真实当前会话信息解除按住/拖拽/菜单等控制并核验输入已交还；工具不支持或失败则保留未解决状态。不得用 REPL reset 冒充释放核验。
- [ ] 收束本批自建可再生临时项，保留成功交付、原始数据、失败证据和 checkpoint；输出下一步或停止，不扩范围。

## 唯一完成判据与停止规则

页面相关补丁只有对应 `IMPLEMENTED + TESTED + REVIEWED + INTEGRATED + DEPLOYED + API_VERIFIED + UI_VERIFIED` 都有匹配版本证据时，才报“该正式页面行为修复完成”。GitHub `REMOTE_SYNC` 单列；后台恢复正确性另需隔离故障注入及独审，不能靠点击推断。没有正式部署/点击，最多报候选补丁已验收。

`NATURAL_VERIFIED` 独立保留，当前 `NOT_RUN`；正式页面可点、历史日期回看、手动刷新均不构成自然交易时段认证。自然时段认证若后续进入范围，再冻结真实时段与任务回执，不为本计划新增定时监控。

同输入无新证据不盲试；实际 owner 不明、需要扩大权限/业务范围、健康长任务无新进度或新实质失败时，保留证据并按合同收束/诊断。预算停止条件已被用户取消。条件性候选未复现时标 `NOT_REPRODUCED` 或 `CANNOT_CONFIRM`，不为了完成表格制造业务修改。

## 本次计划交付状态

- `PLAN_WRITTEN`：完成；仅本文件新增，未改源码/测试/配置/服务。
- `IMPLEMENTATION / DEPLOYMENT / FORMAL_UI_CLICK / NATURAL_VERIFIED`：`NOT_RUN`。
- 旧类型补丁回执中的 Haiku / Luna-Sol 身份文字不一致，实际模型身份待原始派工证据澄清，不影响本轮按明确配置派工。
- 后续执行者必须先读本计划与 P0 实际映射，不能从旧报告直接写入现役。
