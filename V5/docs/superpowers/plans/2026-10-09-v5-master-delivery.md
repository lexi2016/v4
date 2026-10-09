# V5 全系统迁移与交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 主实现由根完成；Mac负责独立测试、部署和反馈。只读审查可以并行，禁止同一模块多个写入者。

**Goal:** 在不覆盖V4的前提下，复用原UI、成熟业务逻辑、数据和采集能力，交付可独立升级、每日自动运行、用户能在页面验收的V5。

**Architecture:** 单仓库独立V5目录；业务按owner分模块，每个模块有固定版本、私有输出、独立worker/API和回滚记录。原UI通过薄兼容网关读各模块结果；调度只负责依赖、触发、幂等和恢复，不承载选股算法。

**Tech Stack:** 现有Python与Mac依赖、现有原前端构建和本机浏览器工具；先复用已有能力，不默认引入Kubernetes、消息中间件或新前端框架。

**Spec:** `../../V4_V5_MODULE_AUDIT_20261009.md`、`../../../source_inputs/V5_MODULE_MIGRATION_MAP.md`及用户10月9日08:20“先有整体计划，再按计划推进”的要求。本计划取代初始仅超跌影子运行计划作为交付顺序；历史PLAN.md保留原阶段范围，不当成全系统完成标准。

## Global Constraints

- 原V4服务、源目录、原业务数据及8910保留；V5不覆盖或暗中回退V4 API。
- 优先复用V4已经运行或测试通过的原算法与原测试；架构迁移和策略变更分开。
- 不交易、不发订单、不修改BUY门；研究身份和未验证条件保持原语义。
- A股、香港证券、港股通日历独立；目标日、价格信号日、资格来源日分别记录。
- 失败、未知、真实空结果区分；手动补算、历史回放、自然运行不得互换。
- 根编写唯一产品候选并提交已授权分支；Mac对固定提交独立验证。单一预览发布窗口，禁止两个发布者互相覆盖。
- 用户已要求当前V5范围直接推进；不再把常规修复变成等待许可。系统安全、凭据、交易及范围外行为仍遵守权限边界。

## Review Focus

1. 上游日期漂移或缺数据：保持来源日期，阻断该依赖；不得拿旧池冒充新池。由P1/P3测试覆盖。
2. 重试、跨日及重启：成功结果保留、同输入不重复计算、失败步骤可恢复；由P0/P1运行账本测试覆盖。
3. 单模块升级：其他模块API、产物、原UI路径不变；发布失败可回退。由P0及每次发布canary覆盖。
4. 页面刷新、返回与日期切换：选择保持、错误可见、无隐式生成副作用；由每个里程碑的UI验收覆盖。
5. 部分来源可用：可选lane坏不拖垮独立lane，缺证据不产生正式推荐；由P1/P4逐owner测试覆盖。

## 1. 模块范围：18个业务/数据模块

这些是设计范围，不是18个已实现服务。平台能力单列不凑完成数。

| ID | 模块 | 原实现复用与依赖 | 本版验收目标 |
|---|---|---|---|
| 01 | A行情与公式面板来源 | 原A同步/公式/面板owner | 精确日来源、数据质量及增量接续；不另做同源重复采集 |
| 02 | HK行情、主表与资格来源 | 原HK行情/master/membership owner | 价格与资格独立日期、真实取得时间、缺口可定位 |
| 03 | US行情来源 | 原digest/session/provider | 精确美股交易日、payload/receipt/manifest一致 |
| 04 | 研究情报与归档 | 原小时研究、早报、公众号等lane | 成功原文不被失败重试覆盖；正文/图片/缺口真实披露 |
| 05 | A预选池 | 01/04及原七池算法 | 原池齐全且去重，V192合同兼容，不因可选lane坏全局清空 |
| 06 | HK预选池 | 02及原HK算法/模型 | Top100生成与读回、三日期合同、不得静默回退 |
| 07 | A阶段选股 | 05/实时源/04 | 竞价与普通阶段各按原规则执行，含尾盘和恢复身份 |
| 08 | HK阶段选股 | 06/实时源/04 | 各阶段、竞价、Stage8不漏，市场日历正确 |
| 09 | A收盘复盘 | 01/07/12 | 原模型与复盘产物、16:05/17:10槽、证据缺失独立展示 |
| 10 | HK收盘复盘 | 02/06/08 | 新日计算而非只桥接旧成品，Top20/模型/阶段归因保留PARTIAL |
| 11 | 盘中研究与研究复盘 | 04及已提交市场/阶段证据 | 盘中时点、收盘研究产物、来源引用与读回 |
| 12 | 视频FUPAN | 原视频/ASR/OCR/对齐链 | 节点独立恢复，后续失败不抹掉前置成功 |
| 13 | 公告研究与选股 | 原目录/正文/语义/导入/消费 | 每日来源接续、实际cutoff消费、同run页面与计划 |
| 14 | 超跌研究与选股 | 02的原面板与主表、原两门规则 | 精确历史/量纲准入、strict/near/unknown语义不变 |
| 15 | 美股到港股映射 | 03及原关系/登记、02资格 | 原daily build/persist/readback，关系可用时间、日期和非全市场限制保留 |
| 16 | 经理候选公开资料任务 | 原固定候选、公开资料job | 状态、重试/取消/事件更新；GET不暗中触发生成 |
| 17 | 尾盘量价发现与持续跟踪 | 原尾盘源与跟踪规则 | 不与Stage/超跌混同，独立产物和每日更新 |
| 18 | 经理决策账本、汇总与计划 | 已提交的04—17产物 | 按日期保存、入选理由/缺口可见、幂等刷新及普通经理页展示 |

平台：冻结日历与来源身份、API兼容网关、运行账本与调度、不可变发布/独立回滚、健康及状态视图。

未核清的模型训练入口和8910完整范围列为范围核对项；在有证据前不静默删除，不计入18个已定义模块。若发现独立业务再记录范围变更。

## 2. 当前基线（2026-10-09 08:20 北京）

- 完整业务模块验收：0/18；代码存在、函数测试通过、接口接通不等于模块完成。
- 已接通V5只读API：HK复盘、公告analysis，共2条业务链；原UI文件保留。
- 公告9426a1b：Mac17/17通过，758输入副本与259源码/测试SHA不变；默认/显式日期真实读取成功。仍未证明自然采集、计划消费或UI点击。
- 调度测试5bb44e1：14项实际均因缺模块报错；随后根已写纯计划实现，尚未Mac验证。纯计划通过后也不等于调度已启动。
- 最近全套测试是旧cf1bbc6的225/225；不得把后续零散结果相加声称当前全套通过。
- 原US映射39件源闭包及真实seed/registry已找回，未执行新daily build。
- UI验收专用Mac任务已启动；若工具未暴露，必须保留NOT_RUN，继续修后端可独立工作。

## 3. 执行顺序与里程碑

### P0：把发布和每日执行底座补成可用闭环（先行，不扩成平台重建）

**Files:** 保留并扩展`src/v5_shadow/module_api.py`、`api_gateway.py`；新增`module_artifacts.py`、`run_ledger.py`、`daily_dispatch.py`；收盘计划为已有`daily_close_plan.py`。对应测试在`tests/test_module_artifacts.py`、`test_run_ledger.py`、`test_daily_dispatch.py`、`test_daily_close_plan.py`。

**Interfaces:**
- `plan_close_day(now: str) -> dict`：仅返回固定槽计划，绝不声称输入已验证或已执行。
- `publish_generation(root, module_id, route_records, expected_generation) -> dict`：完整不可变generation、SHA读回、带expected-generation的原子激活。
- `claim_run(root, computation_identity) -> dict` / `finish_run(root, claim, receipt) -> dict`：身份含日期、输入、cutoff、代码/配置/依赖摘要；已成功可复用，进行中不重复启动。
- `dispatch_due(now, schedule, bindings, ledger) -> list`：只调用已绑定模块入口，不含策略算法；记录真实起止、触发身份及输入准入。

- [ ] 先补发布中断、并发CAS失败、旧成功保留、同输入重试及改输入新run的失败测试，再实现。
- [ ] A复盘1605/1710和HK1610来自固定catalog；半日槽未验证就明确阻断，不能猜12:10。先Mac验纯计划，再做真实执行器绑定。
- [ ] API在稳定私有根中读取已校验generation引用；不得靠切目录指针骗过旧进程固定root FD。新代码发布用新进程/独立端口，核实真实身份后切该模块。
- [ ] 区分latest_attempt/latest_success；今日失败可展示旧结果但明确过期，不冒充今日成功。
- [ ] 用一个真实模块验证worker→产物→API→原页面→单模块回滚；不等18模块全写完才做第一次整链。

### P1：优先交付经理三条业务链（13、14、15→18）

这是第一项用户可用里程碑，优先于继续增加回放外壳。

**Files:** 公告已有`announcement_bridge.py`，新增`announcement_daily.py`；超跌保留`legacy_adapter.py`/`worker.py`并新增`rebound_daily.py`；美股新增`us_mapping_daily.py`；汇总新增`manager_plan.py`。各文件只负责其owner，原源码在各自vendor胶囊中固定。

**Interfaces:** 各daily入口接受明确target/cutoff/input_manifest与V5输出根，返回固定run/artifact/receipt身份；`compose_manager_plan(target_date, cutoff, committed_refs)`只消费已提交结果，不直接采集或重算。

- [ ] 13：保留17项结果，完成analysis API与UI读回；再接原目录→正文→语义导入→明确cutoff消费。读取通过不代表每日生产通过。
- [ ] 14：复用原strict/near两门；补真实来源准入、主表/历史/量纲及每日写入，解除OWNER准入缺口，不通过改标签跳过校验。
- [ ] 15：复用39件原闭包、原seed/registry与原build/persist/readback。原US reader会写锁，只在V5私有输入快照执行；不写V4来源根。结果资格仍CANNOT_CONFIRM时保持原值。
- [ ] 18：独立汇总三lane，单lane缺失不隐藏其余结果；每只股票有入选理由、来源日期与不足。按目标日保存并读回同run。
- [ ] Mac验真实10/8恢复重算并标恢复身份；验跨日输入接续；再等真实适用交易日自然触发，不把合成/手动结果拼成自然通过。

**里程碑交付：** 原经理UI能显示真实三lane、计划与理由；每个适用交易日无需人工催跑。若当天缺输入，状态和下一步可见，不能显示假成功。

### P2：补齐来源与预选（01、02、03、05、06）

**Files:** 来源能力围绕已有`capture_master.py`、`input_snapshot.py`、`snapshot_recording.py`、`provider_evidence.py`；按owner新增`a_source_daily.py`、`hk_source_daily.py`、`us_source_daily.py`，预选新增`a_preselection_daily.py`、`hk_preselection_daily.py`，复用现有reader。

- [ ] 优先读取V4已产出数据和原collector；同一来源只有一个采集owner。缺真正原件才按原流程补采，不为API空重复采集。
- [ ] A：原七池来源与V192旧合同兼容，不能伪造新producer字段；原产物与API分别验。
- [ ] HK：目标日/信号日/资格来源日分离；严格Top100原生成owner可运行，错误旧池拒绝，无静默fallback。
- [ ] US：原交易日和抓取窗口、精确payload/receipt/manifest验证；假READY、混session、晚于cutoff均有测试。
- [ ] 连续两日各池正常更新、缺上游时正确阻断、上一日成功可追溯。

P1所需来源准入可与P1并行；P2完整来源接管不得抢先替换V4。计划顺序不要求为了等全来源迁移而停住已有真实输入的业务。

### P3：阶段与收盘整链（07、08、09、10）

**Files:** 保留`stage_selection.py`、`a_close_review.py`、`hk_close_review.py`；按市场新增`a_stage_daily.py`、`hk_stage_daily.py`、`a_close_daily.py`、`hk_close_daily.py`，业务逻辑仍调用原源码。

- [ ] 补竞价、普通stage、HK Stage8/尾盘原入口，不能用一个普通回放函数顶替全部时段。
- [ ] 原实时采集→精确池绑定→阶段结果→收盘归因同日同run；行情缺口与无候选区分。
- [ ] A/H独立时区和日历、半日未核范围明确；源/池错位立即拒绝。
- [ ] 页面切换日期/阶段、刷新和返回不重置选择；研究接口慢不能拖垮普通阶段。
- [ ] 每模块独立升级和回退，另一个市场API持续可用。

### P4：研究及辅助业务（04、11、12、16、17）

**Files:** 各域独立`research_ingest_daily.py`、`research_review_daily.py`、`video_fupan_daily.py`、`manager_jobs.py`、`close_discovery_daily.py`及对应测试，原writer闭包先核再封装。

- [ ] 原文/图片/OCR失败重试不覆盖成功版本；恢复一篇不等于根本缺陷修复。
- [ ] 视频长任务独立于API与复盘，节点可恢复，缺失明确披露。
- [ ] 公开资料job状态、事件与重试路径可用；读页面不暗触发生成。
- [ ] 盘中研究、尾盘持续跟踪有独立产物，不能用公告/Stage结果冒充。
- [ ] 逐项映射V4真实导航和按钮；占位页不能计迁移完成。

### P5：整体验收与V5交付

- [ ] 当前固定提交全套回归、依赖锁/构建、完整API合同通过；不能拿旧225项结果替代。
- [ ] 18模块逐一完成真实输入、计算/保存/API、页面、调度/跨日、隔离回滚证据。非每日业务按其实际触发合同验收，不强造日任务。
- [ ] 当前内置浏览器真实测试：日期、刷新、前后导航、缺数据、超时、重复点击和恢复路径。
- [ ] 两个连续适用交易日自然运行证据；若周末/节假日，只能等待下一适用日，不能承诺即时完成此项。
- [ ] V5身份/代码版本/数据来源在页面与健康端点可核；用户无需猜地址是不是V4。
- [ ] 交付运行、问题定位及单模块回滚说明。保留V4；迁移完成不自动授权删除V4。

## 4. 页面改动策略

默认复用V4原页面结构。仅在后端合同已稳定后改必要的日期状态、模块版本、数据来源、错误/过期提示及运行任务入口。先修真实功能断点，不重画视觉。

每模块必须列明原页面/URL、API、原源码owner、V5入口和证据；兼容层只做字段/路由转换，不塞采集、选股或调度。A/H共用旧URL时只读合成各自已提交产物。

## 5. 完成计数、节奏与分工

四类状态：代码候选、Mac局部测试通过、已接入页面、完整验收完成。只将最后一类计入“完成X/18”。每次进度同时报固定commit、实跑测试、页面结果、自然运行证据和剩余缺口。

根负责代码、接口合同、优先级与修复；Mac负责固定候选独立测试、原页面交互和单窗口发布；只读审查负责源码依据/缺陷检查。新失败返回原trace后修唯一实现，不让测试者并行写第二版。

每个任务执行循环：失败用例→根实现→固定提交→Mac针对性验证→必要整体回归→接口与页面验收→自然运行证据。小批交付但以完整业务链为里程碑，禁止靠增加wrapper或测试数量冲完成数。

计划不使用缺依据的全系统“今天必上线”承诺。先以P1经理三链作为首个可用交付，再按P2—P4扩展；时间估计以实际固定提交、测试耗时、源缺口和真实交易日窗口更新。常规修复继续自主推进；若范围改变，记录影响而非静默改方向。

## 6. 当前下一批明确动作

1. 保留公告17/17与API接入证据；完成已启动的Mac原UI验收，UI工具缺失不伪报通过。
2. 已写收盘纯计划实现交付Mac14项验证；继而补运行账本和不可变generation发布，优先服务P1。
3. 原US映射39件已齐：写真实build→V5私有保存→独立readback测试和适配，使用真实来源副本及原关系登记。
4. 超跌真实输入准入和经理汇总同时按已有源证据补齐；不把来源不明改成零候选。
5. 更新模块验收清单；V4今早Stage准备风险独立跟踪，不当作V5迁移完成证据。

## 7. 架构参考及采用边界

采用模块数据所有权、固定发布、任务幂等、原子结果发布和旧接口兼容；不照搬云平台部署复杂度。

- Microsoft：领域边界 https://learn.microsoft.com/en-us/azure/architecture/microservices/model/domain-analysis
- Microsoft：数据所有权 https://learn.microsoft.com/en-us/azure/architecture/microservices/design/data-considerations
- Twelve-Factor：构建/发布/运行分离 https://12factor.net/build-release-run
- Airflow：确定输入与任务幂等 https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html#creating-a-task
- Python：原子替换与fsync https://docs.python.org/3/library/os.html#os.replace
- Microsoft：旧新系统兼容层 https://learn.microsoft.com/en-us/azure/architecture/patterns/anti-corruption-layer
- Apple：定时任务与睡眠/关机边界 https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html
