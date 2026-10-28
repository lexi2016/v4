# V4 阶段选股修复交接｜2026-10-01

## 1. 接手先看这几条

- **A 股已收尾，不再追加修复或测试。**9/28—9/30 的21个适用阶段在本批验收时均有可见结果；新增29、30日竞价和尾盘补算均已核对产物、接口、页面。结果仍是部分数据、历史恢复，不等于自然时段或完整数据验收。
- **港股未修好，HK修正版未接入实际服务。**源码有一批13文件的r2改动，但独立结论是 `REVIEWED_WITH_P1`，不能直接发布。
- 用户最新要求：**准确修复已查明的问题，禁止钻牛角尖、越修越多；先交接。**为交接已中断实施，Writer确认最新阶段没有新增修改、测试、候选、激活或数据写入；本会话子任务已结束。
- 当前最小后续方向：纠正**港股证券开市、港股通休市时的自然生产链**，依据原有资格快照/as-of合同使用真实输入；不要继续强行重建缺采集时间的9/30历史authority。
- 不要重启A修复，不改Vibe8910，不覆盖其他会话改动，不新增producer或平行数据层。保持 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 2. 工作区与证据目录

源码：`/Users/lexi/Desktop/学习/v4_app`

交接时分支：`codex/system-consolidation-20260912`；HEAD：`55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`。工作区有本批及更早未提交改动，不能用HEAD整体覆盖或回滚。判断HK本批差异用下文冻结patch/preimage，而非整个工作区diff。

本批证据根目录（下文简称R）：

`/Users/lexi/Desktop/学习/agents调试/v4_stage_root_hk_fix_20260928/line_fix_r1/runtime_recovery_20261001`

- 范围与变更记录：`R/coordinator/scope.md`，以末尾最新收敛说明为准。
- 派工记录：`R/coordinator/ledger.json`。
- 已完成状态及HK诊断：`R/coordinator/closeout_and_hk_diagnosis.md`。该文件早于最新API配置变化，当前绑定以下一节为准。

## 3. 实际配置绑定：不要把工作区或候选当已上线

交接时只读读取了三个LaunchAgent plist。**以下是配置文件绑定；本次未重启服务，也未重新做全链验收。**

| 服务 | 交接时配置 |
|---|---|
| API / 页面8873 | `com.lexi.v35.api-only.plist` 已指向 `r4-stage-merged-c3e5357d07f068e79296790e0b968934c34541d579c586282c5e83f56f6a3875` |
| Stage调度 | `com.lexi.stage-center.scheduler.plist` 指向 `20261001-stage-pr16-a1445-a0925-crossday-r1` |
| 原预选池调度owner | `com.lexi.v35.scheduler.plist` 的启动脚本位于 `r9-hk-child-binding-standard-b1f316ac73f0/app` |

**API版本变化须特别注意：**本会话此前接入并验收的是 `20261001-stage-consumer-visibility-r1`。交接读取时已是上述R4合并版本，非本会话执行的切换；没有回退或修改它。先识别当前owner，禁止拿本批旧版本覆盖R4。既有A/API/UI验收记录证明其当时状态，不能冒充对这个R4版本的新验收。

当前API配置SHA：`2ba6b17639d769fe8adf977707b099ec1de1587c65b81eb0675d3ad81323996b`；其配置的release-manifest SHA：`ec5c62cd8a9935c6c2838afd3c02a98ea9fe9d2aaefdae27fb5d462a8c65e3b5`。app位于 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/<上述R4版本>/app`。

Stage app：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/20261001-stage-pr16-a1445-a0925-crossday-r1/app`。

- Stage plist SHA：`9e285d6423b0232a0f10d7d6707e6fd24a9cc067fb16ab7a31cfb8d2ec676b84`
- Stage release-manifest SHA：`5dc3be0b27fb46c9b2cb9b30d0d50ae0424395d69dc0ae3d143af88251fff204`
- Stage按计划触发，空闲无PID不等于故障。不要用API的manifest校验方式替代Stage自己的身份合同。

预选池实际app：`/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/r9-hk-child-binding-standard-b1f316ac73f0/app`。wrapper按自身位置取app root；plist WorkingDirectory是另一旧路径，不能据此误判实际源码。

该调度器的关键有效配置：

- `V35_HK_UNIVERSE_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data`
- `V35_SHARED_DATA_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`
- `V35_DATA_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`
- `V35_SHARED_PACKAGE_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data`
- `V35_RUNTIME_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/runtime`

因此app和shared package是分别绑定的。V4源码owner是模块化文件，而active r9 owner是 `infrastructure/scheduling/executor_registry_preselection.py`。必要接入必须从实际基线做最小移植，不整文件覆盖。

## 4. A股已完成的证据：直接复用，不重新修

验收矩阵：`R/coordinator/after_a_recovery_api_matrix.json`，三天各7个A阶段有结果。

| 日期/阶段 | 新补算run_id | 行数 |
|---|---|---|
| 9/29 09:25 | `8307d433eb6c445db3cad83c266f22ad` | 10；原始131/134 |
| 9/30 09:25 | `5e8d958ee01a4734844c529b67f85535` | 10；原始202/205 |
| 9/29 14:45 | `dc880a6143f94a0d8d5d4747756490e9` | 10 |
| 9/30 14:45 | `2fc787c1b8fb4b75b7eb6bb8d74127cb` | 10 |

竞价数据是对应历史日09:25:00真实成交，采集发生于10/1；缺盘口、部分股票和其他来源覆盖，明确 `RECOVERY_ONLY` / `WATCH_ONLY` / `NO_BUY`。原普通latest/current指针及旧失败回执保留。

独立回执：

- `R/review/stage_a0925_20260929_30_actual_runs_review_20261001.md`，SHA `daf2b58a743f515a3a3b85b9642f6261fe105f7ad130153d06a27dc571487c28`。
- `R/review/stage_a0925_crossday_candidate_composition_review_20261001.md`，SHA `9eeac112afefb1f7622844195f6f32199652f4c2aa06e01108c485e2a315612f`。
- `R/review/a1445_20260929_backfill_api_binding_review_20261001.md`。
- 页面截图：`R/coordinator/ordinary_20260929_0925_recovered.jpg`、`ordinary_20260930_0925_recovered.jpg`、`ordinary_20260929_1445_recovered.jpg`、`ordinary_20260930_1445_recovered.jpg`。

普通页面分开显示“当前历史恢复来源”和“原失败记录”。旧 `execution_evidence=DECLARED_ONLY` 不是当前BACKFILL回执失败；核对市场级 `runner_receipt_verified` 与对应补算编号。不要因此重新修A。

## 5. 港股失败不能混成一个原因

| 范围 | 已证实 | 证据限度 |
|---|---|---|
| 9/28 | 旧D1 price signal_date为9/24，但前一个港股证券交易日是9/25；实际旧owner使用A或HK Connect开市策略，漏掉HK-only日 | 旧可见结果不是正确日期验收，不能只改标签 |
| 9/29尾盘实际补跑 | `PyTDX ExHQ probe execution failed / returned an error`，`completed=0/100` | 回执无更底层provider异常；不能归因为网络/服务器，也不能断言其余全部阶段同因 |
| 9/30竞价、尾盘实际补跑 | `HK D1 status must be STRICT_0_2_READY`；所需9/29精确D1/source未就绪 | 这是输入门禁失败，不足以说明更底层9/29采集原因 |
| 下一开盘验证 | r2强制索取9/30资格源，正式authority缺失，master复用失败 | 与上面历史故障分开；该日期强制是本批实现选择，非用户决定锁 |

9/29尾盘证据：`R/writer/stage_canary_20260929_a1445/canary_receipt.json`。9/30证据：`R/writer/stage_canary_20260930_a1445/canary_receipt.json`、`stage_canary_20260930_a0925_crossday_r1/canary_receipt.json`。

本批最后完整矩阵：HK9/28八个阶段有旧结果但日期待纠正；9/29仅竞价有普通结果；9/30八个阶段为空。即15个HK空单元，另有9/28旧日期语义问题。此为此前矩阵快照，不冒充当前R4新验收。

## 6. 696/689复用失败已定位，历史重建尝试已终止

原owner把配置的universe root与store root分别传给 `ops/ensure_hk_security_master.py`。期望的 `universes/20260930/HK_CONNECT_FULL_MARKET.current.json` 缺失；已检查V35 state无该日匹配pointer，**没有证据是根目录错位**。

特定异常 `HK_CONNECT authority current pointer missing` 触发价格面板fallback。面板含689个有效价格代码；已验证同日security master含696个代码。研究采集回执证明：696为采集/证券行，689为有效价量行，额外7只均因非正OHLC/成交额/成交量被价格面板隔离。不能用价格覆盖代替成员权威，也不能仅凭696这个数量接受来源。

- master run：`49ffde1ebebdc85e4680e701`
- master captured_at：`2026-09-30T17:20:08+08:00`
- master artifact SHA：`754794679937494dc8dc6cdc8dfbd14dfa4b070ea709f551874e39006aa712dd`
- master universe SHA：`162fb3ec7f50a1130f202be9d39461218260e57cc9b1cefb279d629828885e09`
- 689面板codes SHA：`33215df7fd109cba5597f9d4f920e5887e5856f2fa23c7328b8cb597b50332c2`
- 研究采集receipt：`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/receipts/hk-20260930.json`。

尝试重建历史authority的结论：完整696 union的capture raw/manifest、研究主receipt、close snapshot及receipt均无绑定的采集时间；run_id也不能提供时间。证券master的时间不是同源完整union capture的时间，禁止借用。精确缺口：**`HK_CAPTURE_RECEIPT_CAPTURED_AT_MISSING`**。

原 `stage_center/hk_universe_preflight.py::ensure_hk_connect_universe` 拒绝非当天采集：`Futu HK universe collection is restricted to the current trade date`。单码恢复工具需要有效parent authority和单码证据，也不适用于本情况。

**历史重放三文件分支没有实施，已撤回。不要继续为9/30补造时间、逐plate归属或authority，不把此缺口当成所有自然链修复的前置条件。**

## 7. HK源码r2现状：未上线，不可直接发布

冻结包：`R/writer/hk_calendar_policy_lane_delta_20261001_r2/`。

- `batch_manifest.json` SHA：`788d25e1c2233b89e03bf3fadea43fc1b736ca27626335d696d02a5f5cfd6c59`
- `batch.patch` SHA：`dfcd98158139f4180db8b7cef04265168d763b0707de22a0198c607b58a5321c`
- `review_receipt.md` SHA：`2b4a3fbb1eb8b81e15dfdf5b31abe312a6ad8159c4792348d0adeb4f86ab941f`
- 交接时逐文件SHA检查：13个工作区文件均仍与r2 after-image一致；后续自然HK-only修正尚未实施。

13文件：

```text
contracts/trading_calendar.py
contracts/runtime_workloads.json
domains/runtime_policy.py
domains/task_status.py
infrastructure/scheduling/_executor_registry_parts/preselection.py
upstreams/v3_shared_data/scripts/materialize_hk_0_2.py
upstreams/v3_shared_data/shared_data/hk_0_2.py
ops/materialize_scheduled_preselection.py
domains/preselection_materializer.py
domains/_preselection_materializer_parts/hk_pool.py
stage_center/_runner_parts/hk_input_validation.py
tests/test_hk_signal_calendar_boundary.py
tests/test_preselection_market_calendar_lanes.py
```

r2已做：仅为preselection增加A_OR_HK_SECURITIES策略；A/HK分市场执行；分别传递HK价格日、资格源日期；原owner参数贯通projector到Stage。r1丢失资格日期的P1已在r2修正。

独立r2测试20/20通过，但**不是整体通过**。独立报告：`R/review/hk_calendar_policy_lane_delta_r2_independent_review_20261001.md`，SHA `16002ef24bfa64e8ffba23e1f8208267a944bf50b6e88f96eed8bac59cef73d5`。

- P1：真实9/30资格来源复用阻塞，未来10/8行为未确认。
- P2：现有“existing target保留”测试仅覆盖HK mock/sentinel，没有真实seed并读回已有A池；未证明存在覆盖bug，但A池保留证据不足。
- 另有6项旧catalog/status测试漂移，不属于本批，禁止为它们扩修。

未激活、不完整的候选保留在V35 releases下 `20261001-hk-preselection-lanes-r2`、`20261001-hk-preselection-shared-r2`，以及V4 releases下 `20261001-stage-hk-projection-r2`。app候选仅局部移植，不能直接启动、发布或当验收版本；也不要擅自删除。

## 8. 下一步最小执行合同

当前停在**原资格as-of合同核对**，未开始自然链修正。Writer最后确认：owner和Stage校验当前硬编码资格源为目标日前一个HK Connect日；原HK0.2物化/读取接口支持显式资格源，并验证该日master日期、真实捕获日期和来源身份。

1. 先确认自然HK-only日真实资格快照的原合同。例如10/7实际采集的合法成员快照能否供10/8使用，应依据真实as-of/有效性和来源身份判断；不能把“必须9/30”当用户冻结要求，也不能直接放松时间校验。
2. 在已有owner/投影/validator允许路径内做最小调整。价格日仍严格取目标前一个HK证券交易日，目标仍按HK Connect日历；如缺自然authority发布依赖，只调用原publisher，不造新producer。
3. 一次集中验证：HK-only原owner→projector→Stage日期与来源合同；保留现有A池；正常双方开市兼容。复用已通过且输入/代码未变的证据，不重复大套测试。
4. 唯一Luna Max Writer实施；独立Luna Max Reviewer针对实际diff/目标行为验收。源修正与实际active打包不同，必要接入从真实active app/shared-package/Stage基线最小移植，不能覆盖R4或用半成品上线。
5. 最小真实入口验证与实际绑定回读后才能报告生效。自然时段未到仍是 `NATURAL_SLOT_UNVERIFIED`。历史源缺失如实列出，不为全绿补造。

停止条件：缺真实来源/时间证据时保留具体数据缺口；不能借此继续创造历史恢复框架。用户最关心的是停止无谓扩修并交付真实有效的最小修复。
