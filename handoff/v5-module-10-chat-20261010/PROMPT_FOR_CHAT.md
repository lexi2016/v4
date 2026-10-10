# 给Chat的任务：M10 HK收盘复盘

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


你负责原M10/P3的HK收盘复盘候选，只交方案和代码，嘻嘻负责Mac落地独验。以旧成品桥接作为兼容对照，目标是原新日collector→原算法→原publisher→普通read/API/页面。

1. 将已有`run_review_bridge`、录制`run_hk_close_review`和真实新日生产分别列明。不要用bridge输出或合成600行称新日计算；列原collector/CloseSnapshotStore、PreselectionPoolStore、stage reader、ReviewStore的完整调用闭包和活动root。
2. 复用原Top20排序、Top100/七阶段覆盖、逐股归因。完整输入下逐股票/顺序/指标/分类等价；保留当前V5对缺模型/阶段的CANNOT_CONFIRM投影，不能把原legacy布尔/分类直接宣称证据齐全。None缺阶段与已证空集合不同。
3. 新HK daily入口按真实target/capture/available/cutoff、成员/资格来源日、M06/M08输入manifest、code/config/calendar身份形成计算run，V5私有保存、独立readback。来源不完整不以数量>=600冒充完整Connect集合；缺prev_close/重复/混日不能静默丢弃后称全量。
4. 全天槽固定1610来自已核catalog；15:xx/旧1608不能作为新触发。半日当前无活动合同，保持SCHEDULE_BINDING_UNVERIFIED，不能因回放代码含12:10即新造1210采集/调度。证券日历与Connect资格分离。
5. 新采只在真实当天合适窗口使用原owner；历史日仅复用已存在且可验证的原快照。不得今天采报价填旧日或倒填日期/时间。既有成功snapshot原owner支持幂等复用，不为页面空重复采集。
6. 只有统一集成者可改共享review API/前端/调度；本Chat提交精确接口请求，并证明HK单模块更新/回滚不会覆盖A复盘。同一旧URL不代表共用生产owner。

## 公共边界：只有一个集成写入者

- 所有V4现役代码、数据、服务及8910保留。`handoff/.../canonical`是历史donor，不是部署目录。`V5/vendor/**`与来源manifest只读；闭包不足先登记缺文件/原版本/摘要，由统一集成者补齐，不能在本Chat改原策略或伪造manifest。
- 只写本模块白名单；上游、下游与另一市场全部只读。禁止各Chat分别改`api_gateway.py`、`module_api.py`、`module_artifacts.py`、`run_ledger.py`、`daily_dispatch.py`、`daily_tick.py`、`daily_owner_adapters.py`、`daily_close_plan.py`、共享日历/身份校验/配置、`V5/ui/**`和原`apps/web/**`、`apps/api/**`。不能顺手改`manager_plan.py`或其他模块。
- 需要公共接口时输出接口变更请求：请求ID、模块/owner、固定前像commit+路径+SHA、具体函数/路由、旧/新schema和示例、调用方、日期/状态/安全语义、兼容性、双方测试、发布顺序与回滚。统一集成者单写并返回新的固定基线；本Chat随后rebase最小差异。
- 不新增18套服务器、页面或平行调度。原UI通过只读兼容层读已提交产物；GET、刷新、返回、日期切换不得暗中生成或采集。不要为HTTP空重复采已有成功数据。
- 不交易、不下单、不修改BUY门，不扩凭据、安全权限或网络权限。未知与失败不能填0；合法空须完整可验证输入。研究资格、原拒绝码、PARTIAL/CANNOT_CONFIRM保留。

## 必须交回的内容

1. 差异诊断与donor→V5目标映射，列真实断点、已有能力、未取得的活动合同。每项依据给固定commit/文件/函数，不把计划中“应有”写成“现有”。
2. 本模块可独立审阅的最小代码候选：精确unified diff、原文件SHA-256/不存在证明、候选commit或包SHA、文件清单、每项修改理由。禁止覆盖其他Chat的返回；共享文件只交函数级建议与接口请求。
3. 原算法等价表：同一不可变真实输入上的代码集合、顺序、分数、理由、有效空、未知、原拒绝码逐项比较。预先列出仅允许的封装/身份/私有存储/展示差异。原实现失败要保留trace，不能换算法绕过。
4. 失败用例先行的测试源码、精准命令、测试所需真实工件字段、预计结果。可以静态设计/编码；未实际执行写NOT_RUN。Chat不得声称代替Mac完成测试、部署、真实行情或页面验收。
5. Mac落地和回滚步骤、依赖/输入缺口最小清单、给统一集成者的接口变更请求。非阻塞依赖可继续；阻塞时指出精确行动、路径、缺合同或工件，不请用户重复整理已有材料。

Chat只交方案、代码候选和可复核解释；嘻嘻负责在现有Mac上核前像、落地、独立测试、API/原页面验收和问题回传。若依赖Chat尚未返回，使用已核接口或明显标注的契约测试，不假造其结果。
