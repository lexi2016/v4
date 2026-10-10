# M07 A阶段选股：独立Chat编码交接

日期：2026-10-10。原18模块中的M07，P3阶段；不是交付批次编号，不新增或重编号模块。

## 本Chat唯一业务目标

把M05合法汇总池、原实时窗口与M04研究分数，接入原A阶段算法，私有保存后让原阶段A页和M09引用同run。先贯通一条真实普通窗口，再按原合同补全竞价与尾盘；不能拿普通回放代表全阶段。

## 当前已核与缺口

- S：`V5/src/v5_shadow/stage_selection.py::run_stage_selection`接受A/H两市场的SYNTHETIC或RECORDED_INPUT_REPLAY；A分支调用原`select_a_live_stage`。`input_provenance_verified=False`，不是自然执行链。
- S：wrapper拒绝`STAGE_0925`与`STAGE_1545_1555`。固定stage合同最后一项只属于HK，不能把HK Stage8复制成A尾盘；A尾盘实际入口须按原活动合同核。
- S：原`select_a_0925_auction`及其canonical `a_auction.py`、SelectionStore的publication/verification原件已在本次源码附件提供；当前V5 stage capsule manifest尚未收录这些body。Chat可据原件继续静态方案/编码，不能仅解除wrapper拒绝；部署前另核Mac活动绑定。
- R：迁移计划报告非竞价回放已有证，竞价/自然链未齐；旧若干阶段PARTIAL_WITH_ROWS、尾盘CANNOT_CONFIRM、loaded/exit3不等于正常运行。本包未复跑。
- U：Mac现役普通/竞价/尾盘路由、实际窗口录制、writer/发布根和正式score authority绑定。

## 本模块写入白名单

- `V5/src/v5_shadow/a_stage_daily.py`：总计划指定的新增入口；固定F查询404。只负责A市场输入准入、调用、私有产物引用与执行回执，不接管M05采集或改分数。
- `V5/tests/test_a_stage_daily.py`：拟新增的A专属测试，应用前核不存在；`V5/docs/M07_A_STAGE_HANDOFF.md`：拟新增说明。
- 共享`stage_selection.py`及`tests/test_stage_selection.py`：本Chat不得直接写。若确需变更，只给A_SHARE分支/相关函数的最小diff、前像SHA和双市场回归要求，交统一集成者。禁止跨市场整文件替换。

## 依赖只读

M05预选池的精确目标日/集合/排序/输入身份；M01实时来源的真实窗口与行情字段；M04当时已取得的研究分数；M09消费契约。M08和所有共享文件只读。缺正式评分或候选资格授权保留未接入，不以把None改0解决。

## 固定依据与阅读顺序

- [总计划，固定01—18/P0—P5](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行计划，固定证据规则与逐模块退出条件](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- [V5代码观察基线](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)：`f7cb731c384ee6890a87d16c19a5b5a621779477`，不是Mac当前字节证明。

先读本文件，再读SOURCE_MAP.md、PROMPT_FOR_CHAT.md和ACCEPTANCE.md。四文件已构成任务；来源链接是原件定位，不代表已部署。

## 公共边界：只有一个集成写入者

- 所有V4现役代码、数据、服务及8910保留。`handoff/.../canonical`是历史donor，不是部署目录。`V5/vendor/**`与来源manifest只读；闭包不足先登记缺文件/原版本/摘要，由统一集成者补齐，不能在本Chat改原策略或伪造manifest。
- 只写本模块白名单；上游、下游与另一市场全部只读。禁止各Chat分别改`api_gateway.py`、`module_api.py`、`module_artifacts.py`、`run_ledger.py`、`daily_dispatch.py`、`daily_tick.py`、`daily_owner_adapters.py`、`daily_close_plan.py`、共享日历/身份校验/配置、`V5/ui/**`和原`apps/web/**`、`apps/api/**`。不能顺手改`manager_plan.py`或其他模块。
- 需要公共接口时输出接口变更请求：请求ID、模块/owner、固定前像commit+路径+SHA、具体函数/路由、旧/新schema和示例、调用方、日期/状态/安全语义、兼容性、双方测试、发布顺序与回滚。统一集成者单写并返回新的固定基线；本Chat随后rebase最小差异。
- 不新增18套服务器、页面或平行调度。原UI通过只读兼容层读已提交产物；GET、刷新、返回、日期切换不得暗中生成或采集。不要为HTTP空重复采已有成功数据。
- 不交易、不下单、不修改BUY门，不扩凭据、安全权限或网络权限。未知与失败不能填0；合法空须完整可验证输入。研究资格、原拒绝码、PARTIAL/CANNOT_CONFIRM保留。

## 可直接读取的源码附件

本次补交`v5-module07-source-20261010.zip`，包含固定F真实源码字节、当前目标/测试/manifest与canonical原owner资料。普通Chat无需访问私有GitHub即可继续静态审查和编码。未获活动合同只阻断实际启用与自然验收，不阻断已知原件上的方案和最小补丁；不要仅退回缺源清单。详情及未包含的共享依赖见附件README与清单。
