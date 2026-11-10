# A股09:25价格就绪修复交接

Writer targeted PASS；独立 Reviewer 与发布验收待主控执行。机器回执见 `HANDOFF.json`。

业务修复 commits：`536a41c706d0a8c1d33c1e84328a7556a9aa6dbf`、独审P2返修 `e2c3940b329063fcb065a4e37ee5130b95b52d10`。前者的父提交 `f9e0e69fed3cb4d05c12621bb5f45071e9401ec5` 单独固定现役 Stage 允许文件原字节；不能把整工作树作为可部署运行时。发布只对现役 Stage 基线应用最新 `stage_repair.patch` 的六个源码变化，并按 `SOURCE_BASELINE.json` 核对每个 before/after SHA。未改的活动依赖见 `UNCHANGED_DEPENDENCIES.json`。

原生报价的 open 非正/非有限时使用正数 last，明确标为 `NATIVE_LAST_PRICE_OBSERVATION`；open 正数时保持原有选价和评分。缺少正数 last/昨收的 native 行被隔离并报告 `CANNOT_CONFIRM_PRICE_NOT_READY`。真实成交兼容路径不以报价替代无效成交价，缺价/缺昨收同样明确隔离。未就绪 open/high/low/amount/volume 是 UNKNOWN/null；缺成交额的原评分加分项保持中性零，但不声称观测成交额为零。权重、Top10、BUY、安全旗标均未改变。

新增09:25专用算法身份 `15fd78695c5c0b345dcbf6b32f884320b1fb51b3f9b40876bfe83fe9655fa896`，旧身份全部继续允许读取。新身份覆盖 native 价格降级与 legacy 非法价隔离，其他阶段的算法身份未改。API 的现役文件是 monolith，必须只应用 `api_compat.patch` 单行枚举变化，不能覆盖成 Stage 拆分版。准确 API before/after SHA 见 `API_COMPAT_SHA.json`；实际候选位于 `.verification/api/stage_center/selection.py`。

Main 也是真实 reader：其原 `348e19df…` 文件读取新身份产物会报 `selection algorithm SHA mismatch`。本轮只对这个精确原文件提供 `main_compat.patch` 一行允许枚举追加，Main 候选 SHA 为 `6cb42f8a324577ec70e35046660627957280ba00c0f6d76b0dd5257197749345`。不把 API/Stage 文件覆盖 Main。Main/Scheduler 的运行逻辑未改；owner重pin与历史Main29ac兼容声明由主控发布阶段处理，Writer未改运行时绑定。

Main 增量验证入口是 `PYTHONDONTWRITEBYTECODE=1 "$PANEL_PYTHON" docs/handoffs/a925_price_readiness_20261110/verify_main_compat.py`。它仅建立 `.verification/main-before`、`.verification/main-after` 隔离副本，并用既有 `.verification/artifacts` 新产物及 `.verification/main-legacy-fixture` 合成旧产物核读。旧 Main reader 对新产物 RED、get返回0行；兼容后原envelope全行精确读回、get返回10行。旧SHA产物在前后 reader/get 都 PASS，allowlist恰好由原7项增加15fd一项，原Main文件事后仍为原SHA。结果在 `MAIN_COMPAT_BEFORE_RESULT.json`、`MAIN_COMPAT_AFTER_RESULT.json`；源码前后SHA与fixture目录在 `MAIN_COMPAT_SHA.json`。没有重跑已匹配的 Stage/API PASS。

发布 guard 又确认保留原6个历史 owner 并追加旧Main29ac时需要第7项，因此独立提供第7个 Stage 变更文件：`stage_attestation_compat.patch`。它以现役 `infrastructure/manager_input_attestation.py` 的 `bb88782d…` 原字节为基线，**只把历史 owner 上限6改为7**；候选文件SHA为 `cdfadb406984babc623f7b5bedf42e92e44fa2e0b12063d519256ff653960d12`。repo同名文件存在漂移，因此不把repo旧文件覆盖现役。原六文件 `stage_repair.patch`、API/Main兼容patch、15fd算法字节均未变。

`verify_attestation_compat.py` 在临时目录构造真实 manifest、inventory、源码文件及其 SHA，执行实际历史绑定解析和 `_release_manifest` 校验：旧6保持通过，7从拒绝变为逐项校验7份manifest并选中第7个，8仍在manifest读取前拒绝；错误SHA、相对路径、重复owner也仍拒绝。当前Stage信任入口和最终publication witness在该边界测试中作桩，不宣称该合成fixture证明真实运行时重新封签。结果/源文件前后SHA见 `STAGE_ATTESTATION_*`；现役源文件前后SHA一致，fixture用后清理。未改6个历史owner条目、11/6 transition、manifest/路径/SHA校验、运行时config或发布绑定。

Futu [官方快照文档](https://openapi.futunn.com/futu-api-doc/en/quote/get-market-snapshot.html)分别定义 last_price 为最新价、open_price 为开盘价、update_time 为更新时间，没有把最新价认证为09:25撮合成交价。将零开盘/量额判为 UNKNOWN 是本次保守解释，不是官方就绪保证。provider 只新增字段覆盖汇总，未改请求、等待、重试或截止时间；原始 SDK 批次和历史原字节保留。

验证结果：

- 原失败回归 RED：15 FAILED / 4 PASSED，3代表均复现 -100%。修复后21个针对性用例通过；改用原始真实昨收后再验受影响4例通过。
- 独审P2返修：补15个真实 provider→immutable snapshot→collector→raw validate→production builder 测试，覆盖5可选字段各自 None/NaN/Inf。返修前15 FAILED，去除 collector 对可选字段非None的错误必需校验后15 PASSED；last/prev_close 正数条件保留。raw 合同、公式和时点不变。其他匹配PASS复用。
- 临时 active Stage 依赖加本批六文件：42 PASSED / 2 FAILED。两失败在未改动 active provider 上也完全相同：既有3次重试与旧 one-call/有限时钟 fixture 不匹配。本批未改这些重试或旧 fixture。
- 11/9全472行旧分与原 trace 精确一致；36命中逐项输出在本地 `LOCAL_ONLY_36_HITS.json`；460条旧 -100% 输入已消除，12条正常 open 分数不变。
- 11/10复用原320条快照：300条旧 -100% 输入已消除，20条正常 open 分数不变。
- `.verification/artifacts` 临时 SelectionStore 发布后，通过 `.verification/api` 的 API 候选实际读取，行、null、价格依据和 field_readiness 全部保留。新语义存储于既有 envelope/source_evidence；CSV 仍为既有投影。
- 原始两日 snapshot 前后 SHA 一致。没有使用 live store 作为发布根；未采 live index 的事前 SHA，因此不宣称具有 live index 前后字节证明。

全量纯函数差异保存在本地 `LOCAL_ONLY_20261109_ALL_ROWS.json` 和 `LOCAL_ONLY_20261110_ALL_ROWS.json`；这些及 `.verification` 不提交。精简摘要在 `PURE_REGRESSION_SUMMARY.json`。离线新排序不代表策略提升或事前 PIT 通过，不更新旧历史成绩。

后续 `a_live` 保留独立 qmt.open/lastPrice，评分采用 safe(open) or safe(lastPrice)，没有本次首个非空0复制到二者的映射路径。本批不改其他阶段、新闻/研究质量、owner、历史回执或作业。

`verify_isolated.py` 是本批离线复核入口，使用 `PANEL_PYTHON` 绝对解释器；普通运行复建临时 overlay 并执行匹配范围。它显式排除已证实的两条原有 fixture 失败；实际首次完整运行的42/2记录保留于 `HANDOFF.json`。`--finish` 用于已完成测试后的纯函数与 API 兼容验证。临时目录仅为本批复核/发布准备保留，待引用结束再清理。

`--optional` 只复核P2受影响的15条完整链路用例。所有后续 pytest 都在临时 overlay 内，并禁用 cacheprovider、设置 PYTHONDONTWRITEBYTECODE=1。首次在未改 active Stage 直接验证旧 fixture 时，pytest 写入了该封签目录的 `.pytest_cache/v/cache/lastfailed` 与 `nodeids`；这是本批测试副作用，主控负责保留证据并CAS恢复，Writer不再修改现役目录，不声称该副作用不存在。

未执行：部署、live publication、服务/计划任务操作、行情查询、作业重放、训练、Git push、真实自然时段/API/UI验收。RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
