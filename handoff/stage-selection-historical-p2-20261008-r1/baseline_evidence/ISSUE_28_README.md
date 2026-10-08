# 阶段选股当前问题交接 · 2026-10-08

本包供 Chat 定位和返回最小修复方案。当前目标是整理问题和证据；本轮没有切换 API、运行补采、重跑 Stage、修改业务数据或改变交易门禁。不能把本包当成可直接部署的完整应用。

## 先读结论

- A 股阶段已有结果，但仍是部分数据下的研究观察结果；预选池 API/页面空白另有已定位、已实现但未部署的读取修复。
- HK 当前在阶段输入绑定前失败：`HK D1 split-date eligibility provenance missing`。不是有效筛选后的 0 候选。
- 已准备的 A 池 R2 候选通过隔离业务 canary，**发布独立审查 FAIL / NOT_DEPLOYABLE**。不得直接执行旧发布计划。
- 本地 canonical、实际 API、实际 Stage runner、预选池 scheduler 是不同版本。修复必须绑定真实前像，不可直接覆盖活动 release 或把 main 当运行源码。

## 1. 当前观测，固定在 2026-10-08 09:50:54 +08:00

机器摘要见 [CURRENT_STAGE_STATUS.json](CURRENT_STAGE_STATUS.json)。仅包含计数、身份和错误分类；不含股票行情原始行。

| 阶段 | A 请求 / 来源 / 选择 | 执行模式声明 | HK | 说明 |
|---|---:|---|---|---|
| 09:25 | 178 / 171 / 10 | RECOVERY / LATE_CATCHUP_REPLAY | 输入绑定失败 | 缺 7 只来源；补跑不冒充自然竞价 |
| 09:30–09:35 | 178 / 172 / 10 | NATURAL / DUE | 输入绑定失败 | 声明自然触发，但 `natural_verified=false` |
| 09:35–09:40 | 178 / 172 / 10 | NATURAL / DUE | 输入绑定失败 | 仍是 PARTIAL_WITH_ROWS |
| 09:40–09:45 | 178 / 172 / 10 | RECOVERY / LATE_CATCHUP_REPLAY | 输入绑定失败 | 与自然时段区分 |
| 09:45–10:30、13:00–13:15、14:45–15:00、15:45–15:55 | 尚无对应产物 | 尚无执行回执 | 尚无结果 | **采样时尚未到阶段结束；不算已发生故障** |

前四阶段 API 的执行层均为 `SELECTION_REFERENCES_PARTIALLY_BOUND_EXECUTION_UNVERIFIED`，`execution_verified=false`、`natural_verified=false`。其中 HK 执行回执声明 selected_rows=0，但消费者正式 selected_rows=null、run/artifact=null；不能将声明 0 转成有效空选。

页面只读核对：10/8 深链接可以选中正确日期/阶段，A 阶段显示 10 条；D-1 汇总仍显示 `DATA_BLOCKED_EMPTY` 与 0 行。API 当前版本 badge 为 `manager-daily-chain-20261008-r3-api`。这是一项当前显示缺陷，不等于 A Stage 没有执行。

## 2. 运行身份与代码读取顺序

| 面 | 当前身份 | SHA / 说明 |
|---|---|---|
| canonical | `v4_app`，HEAD `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054` | 工作树有既有修改；以 SOURCE_MANIFEST 中逐文件 SHA 为准 |
| 8873 API | `manager-daily-chain-20261008-r3-api` | manifest `946c49b9c34bd09fbca04644556de3acba1635eb240fa9293f6391e9d46b40e9` |
| API active plist | `com.lexi.v35.api-only` | SHA `72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5` |
| 完整 Stage owner | `com.lexi.stage-center.scheduler`，Issue23 R3 helper app | plist `9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5`；runner `2dbfa90c42cb4bd3b9b78d20bfbd1ac15eba0f3a18dd1105b32decd04a2b5232` |
| 池生产 scheduler | `hk-research-calendar-all-r1-20261007-scheduler` | plist `c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2` |
| A 池 R2 候选 | `a-preselection-source-r2-20261008-api` | manifest `92b0b97b5900da3f2bcb6537d218a49ea05188bb009237e1d229fca9633d0328`；未激活、不可部署 |

`source/canonical` 是当前本地源码切片；`source/active_stage_reference` 和 `source/active_producer_reference` 是实际运行前像的只读切片；`source/blocked_candidate_ops` 是未通过发布审查的工具。所有字节见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。实际 producer 的 materializer 是单文件形态，没有 canonical 的 `_preselection_materializer_parts/hk_pool.py`；不要整文件覆盖跨版本结构。

另有 deadline-only Stage 任务，不能把它当全阶段 owner。定时任务观测到无 PID 本身不证明停服，需结合触发时间、退出状态和对应回执。

## 3. P1：港股 10/8 精确日期输入缺少分日期来源链

**现象：**前四阶段均在 `_build_hk_stage_binding` 被拒绝，原因完全相同；没有 HK selection run/artifact。

**已核实输入：**目标目录中的 `hkconnect_d1_top100.json` 有 100 个唯一代码，但每行 `signal_date=20260930`，顶层日期/资格字段没有给出可接受绑定，也没有 `historical_provenance`。10/8 合同要求价格信号来源 10/7、Connect 资格来源 9/30。标注 `STRICT_0_2_READY` 不足以证明该合同。

原件身份（原始数据不上传）：artifact `62d7716c51978a8e2b55c8aa423ae72691da1385fb80b97df35da714addee09b`；manifest `cc476019362896f89b37ca12b0f5d7c606fe188ef3b0a33b7c8224df21aa8de6`；receipt `1871468dda045659d1786b46576ec6290b92df667bcda7c5b325a62a0af01b28`。10/8 输入独立审查 receipt SHA `504cc7f6ea2f7b19798f9449e12bee7692bc1a431347842832626bf2a47b7b29`。

**根因边界：**已证明产物不符合日期来源合同；尚未证明 10/7 原始行情完全不存在。canonical 已有 `eligibility_source_date` 和 provenance 支持，需要追实际 scheduler → materializer 调用参数 → 原共享数据 owner → 目标产物之间的断点。不得只删 validator，也不得在旧产物上伪造字段。

**代码：**本包 canonical 的 `domains/_preselection_materializer_parts/hk_pool.py`、`ops/materialize_scheduled_preselection.py`、`upstreams/v3_shared_data/shared_data/hk_0_2.py`；对照 active producer 单文件 materializer；Stage 的 `runner.py` 和 `_runner_parts/hk_input_validation.py`。

**验收：**原 owner 的真实来源及两种日期可追溯到 run/artifact/manifest/receipt/SHA/capture；原严格 validator 接受合法三件套、拒绝旧日/缺来源；单阶段 canary 后由原 Stage 产生实际 selection，8873 API/UI 读回同一 run/SHA。合法输入下真空选与输入缺失必须可区分。若原始来源确实没有，报告缺口；使用既有 TDX 链路补采也不得伪造当时捕获/PIT。

## 4. P1：A 股预选池 API 读取断点已修源码，尚未发布

**现象：**Stage 读取到 178 个完整汇总代码，预选池接口却仍为空。生产产物在已配置的 `V35_PRESELECTION_SOURCE_ROOT`；API 路由先前漏传该参数，随后 HK-only fallback 无法补回 A。

**已有成果：**canonical 源码修复独立 7 项新测试 + 3 项定向回归通过；R2 在保留经理台 R3 的 1013 项 app inventory 中仅改变 `apps/api/v35_api/app.py` 两处。独立隔离 canary 返回 178 唯一 A、148 source-only、30 unified、100 独立 HK，15 个来源文件字节不变。不是重新生成池，也不是 HK Stage 输入验收。

已上传源码及测试：[已冻结 A 池修复](https://github.com/lexi2016/v4/tree/4ad7cc52257b49470b3004ebfee9649af43189dd/handoff/a-preselection-source-20261008)。app 前像 `90a2bf6390c6c0e219aa3d9bb22bc3b3630ecb2d447df494ae69425933424ed7`，后像 `435dcedd3beb43bf4a0ccb35ff6fc033ba536a940990c36f5f23358f5492b590`。

**待做：**先解决下一节发布阻断，再基于届时实际 API owner 做最小合并，保留经理台更新。部署后读回 10/8 A=178 与 HK=100，重载原页面；部分/空子池不得全局阻断、显示分页不得截断完整 Stage 输入。

**P2 回归缺口：**非空本地池缺 HK 时的精确日期 HK fallback 尚未覆盖。需构造隔离本地 A 池，确认补 HK 不抹掉 A。两个旧 HK fixture 在进入 API 前因缺 historical provenance 失败，不能报回归全绿。

## 5. P1：R2 发布路径有两项独立失败，禁止直接安装

独立 receipt SHA：`f1ec7528fea04ab2d26fbb6f7d68f61cabbceae82a187cca9cc6443d0f3d92de`。状态：`REVIEWED=FAIL`、`DEPLOYABLE=NOT_DEPLOYABLE`，业务 canary PASS 只适用于隔离 API。

1. **外部 CAS guard 未冻结 SHA。** `api_candidate_install_r2.py:331` 与 `api_candidate_recovery.py:296` 动态导入外部 guard，19 项 scope/plan 中没有 guard pin。实际 guard SHA `264ad2d3f5535e17f6e7471dc12d7e00452104b505795857e9f0637c0a29e816`。修复须将它纳入安装、恢复和 review 的精确绑定，并在使用前拒绝漂移。
2. **双重 link 失败可能遗失 active 路径。** guard 把 baseline 移入隐藏 claim 后，候选 link 和恢复 link 均抛 OSError 时，active plist 不存在，只在 claim 中保留原字节；错误未返回 claim 路径、没有 drift receipt，恢复 helper 又因 `active plist is missing` 拒绝。独立临时故障注入已复现，实际服务未操作。需提供可追溯、不覆盖他人文件的 claim 恢复路径及双失败/恢复测试。

`source/blocked_candidate_ops` 和 `source/external_guard_reference` 给出实际代码。旧 17 项 recovery 模块测试 + 8 个 gate 拒绝探针已通过且复用；新增 9 项 install-plan 测试也通过，但没有覆盖上述故障，不能代替修复后的独立验收。不要再造通用部署框架，只修已复现路径。

## 6. A 股数据、评分与运行证据问题

### 6.1 P1：09:25 昨收字段在适配和持久化之间丢失

**已复现代码缺陷：**171 行原始竞价 artifact 的 `prev_close_price` 全部非空，SHA `9aee2d53b77c5f943e6fb209414eb565530e527e5286d0047fe238edaa781953`。但 canonical 和实际 Stage 的 `_live_collectors_parts/selection_builder_registry.py` 在构造 09:25 行时漏传该字段。选择结果 CSV schema 又没有 `prev_close_price` / `current_change_pct`，结果 artifact SHA `831c088700aae19352b60e2fae3231ed362a5624a4226c5ccc53d02d7d98b6e4`。API 10 条所选行因此昨收为 null、涨幅为 0。

`_selection_parts/a_auction.py` 缺昨收时不能计算真实涨幅，而 `qmt_gap_pct` 的 0.0 回退被后续使用。这个 0 不是观测到的平盘。需要同时追 adapter → selector → artifact schema/codec → API 的字段保留，不只改页面显示。

**代码/前像：**实际 builder SHA `5b315c482723f4bbfb187e36241ea422f2a59518a2056be037d1fdbe2f00eb22`，canonical `8b3552498b125ae90c56964799f3cf0e644a077243f7be4c37ea23261214379a`；其余 `a_auction.py`、`artifact_codec.py`、`schema_values.py` 两侧相同，清单给出复用映射。

**验收：**小型离线 fixture 明确给昨收 100、竞价价 105，经过真实 adapter 与持久化读回后仍有原昨收且涨幅为 5%；缺昨收时相关百分比为 null 并带缺失原因，不显示 0%。保留原排名算法边界；若字段恢复改变分数或排名，必须说明实际变化并定向验证，不偷偷重跑/覆盖已保存的 10/8 结果。

### 6.2 P2：A 来源覆盖缺 6–7 只，尚不能归因为单一行情映射 bug

09:25 为 171/178，之后三个盘中阶段为 172/178。缺失代码在本机完整 API/receipt 中，上传摘要只保留数量。某些证券类型或代码映射值得定点检查，但本轮未逐只证明失败根因；不得凭代码形态就改市场或把空返回判定为没有行情。

**验收：**沿既有采集链逐个保留请求市场/规范化代码、返回/错误/时间窗口、缺失原因；恢复的行必须符合精确日期和窗口。不能以“178 次请求完成”当作 178 个有效来源；不能用部分缺失阻断有效 A 汇总池，更不能抹掉缺失或伪造成 100% 覆盖。

### 6.3 P2：研究/新闻评分供给稀疏，字段合同与权威归属未闭环

10/8 09:00:25 的小时归档确实存在，9 个 stock-pool rows、9 个 article rows，SHA `a777dd2fe42d1d135443046e7eb12f87651432b6b94d901ddd82ba8bd3827168`；源 witness SHA `837bc4a2e45307b5f915d4a253fbd9364bfd6b7957ccc9a2d98fe47ebdd80416`。其 schema 是 `v3_5.research_archive.v1`，来源记录仍指向 V3.5 module。不能仅因路径被读取就认定已验收为 V4 权威共享数据。

输入相对 178 只候选较稀疏；研究行暴露 `item_quality`，loader 期望数值 `quality_score`，且代码明确没有把 stock-pool 的 `research_score` 当别名。witness 的 morning-news article_count 为 0。这能解释一部分缺失，尚不足以宣称是映射 bug；候选与来源的精确交集本轮 NOT_RUN。

**待做/验收：**先确认既有 owner、日期/取得时间、不可变 manifest 绑定以及 numeric quality 字段的真实语义，再决定最小映射或供给修复。不可擅自 `research_score→quality_score`、把类别 `item_quality` 当数字或缺值填零。保留不覆盖代码的逐项缺失理由；不能为补分另建 producer。

### 6.4 P2：自然运行和逐次执行代码身份仍未验收

前四阶段有不同 NATURAL/RECOVERY 声明，但消费者都没有独立验证自然运行。当前回执未闭合不可变运行历史、记录时钟、独立 receipt SHA 与实际加载代码指纹；API 运行身份中的 `process_status=CANNOT_CONFIRM` 也不能解读为已证明服务故障。

小时源 manifest 声明 09:00:59 cutoff 和 original-slot capture，但 `natural_execution_verified=false`。当前可变 manifest 的字节与早先 Stage 证据记载 SHA 不同；此路径不能提供那次执行的历史 manifest 字节。需在原合同内绑定不可变原件，不能修改历史回执使它“看起来通过”。

**验收：**区分 per-market selection 引用核验、节点运行、自然时段、补跑和 UI 显示；同一 run 的输入/代码/配置/执行回执身份可核对。没有原始自然证据时保留 `NATURAL_SLOT_UNVERIFIED`。正常缺证据状态本身不是需删除的防护。

**PIT 扫描边界：**已检查 snapshot、候选 artifact、raw/selection CSV schema、小时 payload 和 witness，未见 `label_` / `future_` / `target_` / `post_event` 字段；所见 `target_date` 用于日期身份检查。这不是完整传递链的泄漏认证，不能据此宣称 PIT 全面安全，也不应仅凭字段名猜测已发生泄漏。

## 7. 历史收盘修复与旧问题的边界

历史收盘源适配的三个 canonical 文件仍保留已审后像：`infrastructure/preselection_pool_store.py`、`ops/build_close_review.py`、`tests/test_close_review_producer.py`，见清单。独立 receipt SHA `6ad5f2f26619a998f6ec78cbb384b0cd8935c87c7302229b8e4c4d82b77987e8`：51 focused PASS，扩展 70 PASS / 3 FAIL，三项在基线同样失败。`DEPLOYED=false`、API/UI CANNOT_CONFIRM、自然时段 NOT_RUN。不要重写已通过源码，不要用源码通过冒充日期数据恢复。

历史日期仍有来源边界：8/25 缺 manifest/receipt/provenance；9/30 捕获晚于目标收盘；10/7 在当时精确查验根下未找到上游原始来源。原有三项 P2 是：validator 未强制 provenance 日期不晚于目标日；嵌套 provenance map 未严格拒绝未知字段；8/25 输出缺明确的 source/PIT 不确定标记。它们没有导致已封存 canary 被升格为 READY，也不能靠填默认值解除。

| 旧 Issue | 本次怎么处理 |
|---|---|
| [#10](https://github.com/lexi2016/v4/issues/10) | 仅 9/30 盘中观察恢复，不是 10/8 放宽 D-1 授权；未闭环部分保留原范围 |
| [#11](https://github.com/lexi2016/v4/issues/11) | 旧 9/30 A 竞价重试耗尽；10/8 竞价已有 10 行，不能把旧症状套到今天 |
| [#21](https://github.com/lexi2016/v4/issues/21) | 今天深链接已能选择日期/阶段；其他历史观察行、HK-only 导航本轮未复跑，CANNOT_CONFIRM，不当作当前全部复现 |
| [#23](https://github.com/lexi2016/v4/issues/23) | 旧 runner pin 已过时；当前 Stage runner 与现行 pin 相符。canonical 后续字节不同，下一次构建需精确绑定，尚未运行 builder，不声称新的打包失败 |
| [#8](https://github.com/lexi2016/v4/issues/8) | 经理台属于另一个 owner，已有 R3 更新；本任务不得按旧 issue 覆盖其版本 |

## 8. 给 Chat 的交付合同

最小只读复现入口：

- `GET /api/v3/preselection-pools?date=20261008&limit=200`：当前空结果；候选隔离返回 178 A / 100 HK。
- `GET /api/v3/workbench/stage?date=20261008&stage=STAGE_0925&limit=10`：A 昨收/涨幅字段及 171/178 覆盖；HK 失败原因在 `execution_evidence.markets.HK_CONNECT.reasons`。
- `GET /api/v3/workbench/stage?date=20261008&stage=STAGE_0935_0940&limit=10`：A 172/178、研究缺失分类、HK 来源阻断、运行声明与验收字段。
- `GET /api/v1/runs/date-list?date=20261008`：读取 `runtime_identity`，与发布 manifest/pin 分开核对。
- 原页面 `http://127.0.0.1:8873/?date=20261008&stage=STAGE_0935_0940`：重载后核日期、阶段、结果计数与缺失态；不要点击“强制重新物化”来做只读复现。

上述状态是本次采样，不承诺后续自动运行保持相同。根因调查是只读，A/HK 专家未新增执行测试或业务动作；不能把这次审查记为修复 TESTED。既有测试与候选失败在前文分别列明。

按输入阻断、数据语义、发布阻断分批给最小 diff，每批写明实际前像 SHA、canonical/运行版对应关系、验证命令和 NOT_RUN 项。先复用已有通过证据；只复验改变的代码、输入或范围。Luna Max 唯一 Writer，本机适配后由不同身份 Reviewer 独立验收。未经验收不得修改活动 release。

HK 先修原 producer/来源绑定，A 先修确证的数据语义问题并复用预选池既有修复；发布工具只处理本包独立 P1。API、UI、自然时段分开报告。历史输入无法重建时保留 CANNOT_CONFIRM，不许补造 capture time、日期或来源标签。

保持 V4/8873 唯一入口、既有共享权威数据层、A/HK 分离；A 全池汇总非空即允许阶段处理，坏来源隔离，不要求所有子池齐全。不动 Vibe8910、模型/BUY、经理台或无关计划任务。不建第二 producer；历史行情沿用已有缓存优先 TDX/tdxpy 路径。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。

本包排除凭证、完整 plist/绑定配置、账户持仓、原始行情、完整业务响应、全量运行库存、dist、venv、node_modules。源码切片不构成完整依赖闭包；需要更多文件时按 SOURCE_MANIFEST 中所属实际 owner 定点补齐。
