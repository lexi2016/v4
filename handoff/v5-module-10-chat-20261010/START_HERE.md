# M10 HK收盘复盘：独立Chat编码交接

日期：2026-10-10。原18模块中的M10，P3阶段；不是交付批次编号，不新增或重编号模块。

## 本Chat唯一业务目标

把M02新日真实收盘来源、M06原Top100、M08原七阶段，经原Top20/覆盖归因算法和publisher保存，普通review API与HK收盘时间线首项读回同run。已有旧成品桥接作为对照保留；交付必须包含新日计算及下一适用日自然接续。

## 当前已核与缺口

- S：`hk_close_review.py::run_hk_close_review`调用原`build_native_close_review`，只接受录制/合成输入；DECLARED_UNIVERSE_ONLY、来源/PIT未证，缺模型/阶段归因降CANNOT_CONFIRM，保留legacy_status。
- S：`review_bridge.py::run_review_bridge`只读已发布的`close_reviews/<date>.json`、对应receipt、manifest，明确`v5_computation_performed=False`、`natural_verified=False`。真实旧成品读到20/100不证明新日计算或自动更新。
- S：原`collect_close_snapshot`可复用已验同日snapshot，否则只允许当前日期且16:10后新采；原`build_close_review`读取snapshot、exact-date Top100与七阶段并`ReviewStore.publish_native`。这两ops不在当前hk_close算法capsule内，接生产要补完整闭包与活动绑定。
- S：冻结catalog的HK槽是`1610`；`daily_close_plan`对半日只给SCHEDULE_BINDING_UNVERIFIED。`hk_close_review`回放代码虽有12:10半日边界，绝不是已证活动半日采集/触发合同，不能据此启用半日。
- R：44b514a桥接曾Mac6/6、旧副本20/100/0并缺7；旧10/8 16:12:07成功仍缺七阶段；迁移计划最新仍称新计算与七阶段证据未齐。本包未复跑。
- U：当前Mac源/collector绑定、真实成员与资格来源、七阶段完整性、普通review发布根、半日活动合同。

## 本模块写入白名单

- `V5/src/v5_shadow/hk_close_review.py`：必要HK封装/身份兼容，保留回放、来源/PIT未证和缺证语义。
- `V5/src/v5_shadow/hk_close_daily.py`：计划新增点，F查询404；负责HK真实新日准入、原producer保存与独立读回。
- `V5/tests/test_hk_close_review.py`、拟新增`V5/tests/test_hk_close_daily.py`、`V5/docs/M10_HK_CLOSE_HANDOFF.md`，仅HK专属。
- `review_bridge.py`作为已验只读基线不改；共享review envelope/router、gateway、frontend、调度、日历、vendor/manifest及M09只读。需变更通过统一接口请求，不整文件替换混合A/H页面或API。

## 依赖只读

M02收盘集合/价格与成员资格证据；M06目标日Top100完整100行和原顺序；M08原七阶段及完整有效空证明。M08 Stage8另列，不能拿来补七阶段。M09在共用URL下保持独立owner；M17尾盘发现不是本模块来源替代品。

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
