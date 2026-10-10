# M09 A收盘复盘：独立Chat编码交接

日期：2026-10-10。原18模块中的M09，P3阶段；不是交付批次编号，不新增或重编号模块。

## 本Chat唯一业务目标

将M01当日全声明面板、M07阶段证据及M12当时可用正式材料，通过原确定性A收盘模型与原review publisher形成新日结果，私有保存并由普通复盘API/原ReviewView读回。16:05与17:10两个槽分别留证，后槽不能覆盖前槽成功或隐藏材料缺口。

## 当前已核与缺口

- S：`a_close_review.py::run_a_close_review`调用原`domains.a_share_close_model::build_close_model`，输入仅SYNTHETIC/RECORDED_INPUT_REPLAY；artifact状态CANNOT_CONFIRM、legacy_status分列，范围DECLARED_UNIVERSE_ONLY，来源/全市场成员/PIT未证。
- S：原`build_a_share_close_review.py::build_review_from_panel`读取指定panel精确日期，构造原模型与close_chain并使用AShareReviewStore的import/replace。这个生产者不在当前仅三文件的`a_close`模型capsule闭包内，不能把纯model计算称完整正式复盘。
- S：冻结runtime catalog的A槽为`1605`、`1710`；`daily_close_plan.py`只规划不执行，明确run_status=NOT_RUN。模型15:30 as_of标签和wrapper的15:30输入下限不是执行槽，也不是严格15:00 PIT证据。
- R：迁移计划报告A核心回放有证，新日完整正式输出未证；旧17:11:41成功、PARTIAL_STAGE_EVIDENCE及正式多产物缺失按历史保留。
- U：Mac活动全panel/成员完整性、原AShareReviewStore活动版本/根、两个槽真实触发、A/H共用复盘路由的发布隔离、M12正式产物实到情况。

## 本模块写入白名单

- 现有`V5/src/v5_shadow/a_close_review.py`：仅必要的A封装/身份兼容差异，保留原replay限制与来源/PIT未证标志；不得把replay改名生产。
- 新增`V5/src/v5_shadow/a_close_daily.py`：总计划指定，F查询404；负责A生产准入、原producer/保存/读回接线。
- 现有`V5/tests/test_a_close_review.py`、拟新增`V5/tests/test_a_close_daily.py`、`V5/docs/M09_A_CLOSE_HANDOFF.md`：A专属测试/说明。新增先核不存在。
- 原vendor、manifest、共享daily_close_plan/调度、混合review gateway、前端和M10只读；改变公共合同交统一集成者。

## 依赖只读

M01面板/全声明集合与真实时间、M07同日各阶段已提交引用、M12正式视频/ASR/OCR/对齐/缺口产品，及现有P0发布/账本。不能重跑或重写M12；材料缺失只标缺，不抹掉已成功价格模型。M09输出进入后续预选是跨日依赖，不能强行当同日顺序。

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

`v5-module09-source-20261010.zip`已附固定F的现有目标/测试/manifest、模型capsule和原panel producer、review/chain/store相关原字节。Chat无需私有GitHub访问，可继续静态方案、代码和失败用例；仅真实数据/现场绑定在Mac执行前核。原测试所需完整应用依赖与Mac数据没有冒充已附或已验，详见附件README。
