# M08 HK阶段选股：独立Chat编码交接

日期：2026-10-10。原18模块中的M08，P3阶段；不是交付批次编号，不新增或重编号模块。

## 本Chat唯一业务目标

把M06 Top100/候选lane、M02实时与资格来源、M04可用研究证据接入原HK阶段owner。覆盖普通four-lane、独立竞价和HK Stage8，私有提交后在原HK阶段页读回；M10消费原七阶段，不能用Stage8补缺失阶段。

## 当前已核与缺口

- S：共享`stage_selection.py::run_stage_selection`调用原`select_hk_four_lane`，只有SYNTHETIC/RECORDED_INPUT_REPLAY，来源身份仍未证。它拒绝`STAGE_0925`和`STAGE_1545_1555`，并禁止传入raw stage_score覆盖。
- S：原`selection.py`的HK竞价两个body、store publication/verification及HK Stage8整组固定canonical原件现已附源码包。缺的是当前V5 stage capsule收录和活动绑定，不是仓库原件；Chat可直接静态设计/编码，不能只解除wrapper拒绝。
- S：固定stage合同的`STAGE_1545_1555`只适用HK_CONNECT。它是阶段模块职责，M17尾盘量价发现是另一独立模块；两者不得相互冒充。
- R：迁移计划报告非竞价回放已有证，竞价/自然链与HK富化仍缺。旧阶段部分有行不等于全部窗口成功。
- U：Mac活动竞价、Stage8 collector/selector/writer、实际窗口/按钮/路由、半日合同、资格与实时源绑定。

## 本模块写入白名单

- `V5/src/v5_shadow/hk_stage_daily.py`：总计划指定的新HK入口，F查询404。只做HK准入、原owner调用、私有产物引用和回执。
- `V5/tests/test_hk_stage_daily.py`、`V5/docs/M08_HK_STAGE_HANDOFF.md`：拟新增的HK专属测试和说明，Mac先核不存在。
- `stage_selection.py`、`tests/test_stage_selection.py`共享，只能提交HK_CONNECT分支/函数的精确建议diff与前像SHA，由统一集成者单写；不能输出跨市场整文件覆盖。

## 依赖只读

M06精确目标日Top100/原lane与排序；M02价格日/信号日/资格来源日、真实成员资格、行情字段/单位/取得时点；M04时点内研究；M10原七阶段reader。M07和M17不写。香港证券交易日、港股通资格/日历和A市场状态分别核，不能用一个is_trading_day替代。

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

本次补交`v5-module08-source-20261010.zip`，包含固定F真实源码字节、当前目标/测试/manifest与canonical原owner资料。普通Chat无需访问私有GitHub即可继续静态审查和编码。未获活动合同只阻断实际启用与自然验收，不阻断已知原件上的方案和最小补丁；不要仅退回缺源清单。详情及未包含的共享依赖见附件README与清单。
