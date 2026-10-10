# 给Chat的任务：M07 A阶段选股

你负责原M07/P3的A阶段选股代码候选，嘻嘻负责Mac落地独验。请读取同包SOURCE_MAP的固定原件，保留V4和原算法。

1. 先整理普通/竞价/尾盘入口矩阵：原collector、原selector、窗口与cutoff、日历、池来源、原store/receipt、普通API/页面。未证活动项写U和最小材料需求，不能用EIGHT_STAGES推断A也有HK第8窗。
2. 复用现有`run_stage_selection`的A普通分支作等价基线，核原live-stage评分、排序和Top10。现有原竞价入口是独立算法路径；先用已附canonical原件设计并编码完整源闭包接线；实际启用前核实活动时窗合同，不把竞价成交额直接当推荐score。
3. 新增A专属daily入口，将精确M05池/实时录制/M04材料身份绑定target/stage/cutoff/code/config/input digest，交已有发布/账本接口保存。需共享接线时只交接口请求。API只读取已提交结果。
4. 记录实际时钟。录制在窗内才可重放；漏录标窗口错过，不能当前行情补早盘或回填captured_at。恢复必须MANUAL_RECOVERY/natural=false，不能把缺窗口变READY_EMPTY。
5. 保留A五价/昨收/量额/盘口、news/research字段校验、市场日历、source status、缺码诊断、formal score/authority guard和安全标志。原reader需要写锁时使用V5私有副本，不写V4根。
6. 交A专属最小diff、测试与Mac步骤。不要修改HK分支、共享前端、gateway、调度、日历或原vendor。

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
