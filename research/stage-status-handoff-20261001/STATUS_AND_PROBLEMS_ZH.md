# V4 修复进度与页面问题核对｜2026-10-01

## 结论与本轮动作

本轮是问题和代码交接。用户决定由指定 Chat 会话完成代码，Mac 负责后续本地交付与独立验收。本轮只读核对当前页面、55个 GET 回读并复用既有独立测试报告；没有新增业务代码、selection、采集、历史数据写入、服务重启或部署。完整 GET 原响应及 SHA 在 `evidence/api/` 和 `evidence/api_readback_index.json`；它们证明各自读取层，不代表全链行为验收。

当前 8873 显示 R4 merged 身份且 manifest/执行文件核验通过。实际源码、服务 app、shared package 分别绑定，详见 `CURRENT_BINDINGS.json`；未提交 V4 工作区不能整体当作已上线版本。

## 已解决与仍未解决

| 交付面 | 当前证据 | 完成边界 / 下一责任 |
|---|---|---|
| A股9/28—9/30历史可见结果 | 普通 `workbench` GET 三日各7个A适用阶段均10行，合计21个；9/30竞价、尾盘实看UI与当前backfill run一致 | 历史恢复可见，仍PARTIAL/研究观察；A修复收尾，不追加业务修复、生产测试或阶段重跑 |
| A竞价9/29、9/30 | 已有独立原件/补算receipt，当前普通API仍可读 | 历史阶段选股恢复，采集在10/1，缺盘口/其他覆盖，不等于自然/完整验收 |
| A尾盘9/30 | UI的BACKFILL `2fc787c1b8fb4b75b7eb6bb8d74127cb`、runner VERIFIED、SHA `30ec17a1dc48e77d0881b35a330a138afac3ba8a428f227cc6d1b7fac9612bfd` | 已有历史恢复；页面仍展示原旧失败receipt，不能把两者混成同一状态 |
| PR16 A14:45投影新代码 | GitHub独立读回Draft、head `e97b9e33359a13c2fe144e2a6935d14e48c7b31b`；作者17项结构验证报告 | 新代码的Mac独立17项、原4076→811b完整回放NOT_RUN。仅本地接收/隔离验收待办，不再让Chat追加A代码，也不触发selection |
| HK历史9/28 | 普通页八阶段都有旧行；旧价格日9/24应为前一证券日9/25（既有诊断） | 行可见不等于日期正确，仍未完成日期语义验收 |
| HK历史9/29 | 当前普通GET仅竞价10行，其余7阶段0 | 9/29尾盘ExHQ probe failure/completed=0/100只证明该次失败；底层原因不能推成网络/全部阶段同因 |
| HK历史9/30 | 当前普通GET八阶段均0；D1池报master metadata invalid:'20260929' | 真实输入/校验缺口，当前HK确实未恢复；不能将0改标签当完成 |
| HK自然链r2 | 13文件当前字节与冻结after-image一致；既有独立20通过，但REVIEWED_WITH_P1；未进入active服务 | 唯一新编码目标：HK证券开市/港股通休市自然链及合法资格as-of贯通，Chat负责，Mac集成测试 |
| HK下一目标10/8 | 当前API/UI已有100行STRICT_0_2_READY，source run `20261008-hk-connect-d1-top100-0-2-8a0386afb66b`，source SHA `ce4e94229a1f1bf44c22a2390d577dbea3c81f588543221fb1ee12b9464cc040`；所有当前行signal_date=20260930 | 更新旧报告“该Top100不存在”。现存早期预生成快照不证明10/7价格刷新或10/8正式阶段可用；由既有owner在自然HK-only日更新，并由Stage严格检查 |

HK普通工作台当前仍有15个空单元（9/29七个、9/30八个），另有9/28旧价格日问题。自然窗口未到，`NATURAL_SLOT_UNVERIFIED`。

10/8 Top100原件的manifest/receipt时间均为9/30 17:30:43，绑定9/30价量面板和security-master；它确实存在，但不是10/7自然刷新。落盘envelope缺`target_date`与`stage_selection_eligible`，其binding的`stage_reuse_status=CANNOT_CONFIRM`，不能把API的STRICT_0_2_READY升格为正式Stage可用。

## 页面为什么看起来还没好：本次实看

1. **HK的空结果是真缺口。**9/30普通阶段页每个阶段HK=0，D1表直接显示 `HK_0_2_EXACT_INPUT_CONTRACT_INVALID:HK security master verification failed: HK security-master metadata invalid: '20260929'`。源码r2尚未接实际owner/shared/Stage，不应把工作区测试通过当运行服务已修复。
2. **A新恢复与原旧失败并排展示。**9/30尾盘当前BACKFILL runner VERIFIED，同时“阶段执行声明与选股身份”仍显示旧 `DECLARED_ONLY`、旧 `SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH`。这是不同receipt的证据边界，历史失败不应抹掉；如需要简化文案，只能让用户更清楚看到当前恢复与原失败，不改其真实性。
3. **两个接口的读取合同不同。**当前UI由 `apps/web/src/app_shell/useAppShell.ts` 调 `GET /api/v3/workbench/stage`，API调用 `consumer.get(..., allow_backfill=True)`；`GET /api/v3/stage-center/selection`默认`allow_backfill=False`。因此9/30尾盘普通页A10，formal A0；9/28多个阶段同样如此。不是新的A数据丢失证据。完整两路矩阵见 `evidence/current_api_matrix.json`。
4. **任务状态也读取正式产物/同日ledger。**任务页同日4receipt、24配置owner，但多项 `EXECUTION_RECEIPT_MISSING`、正式Stage `SELECTION_ARTIFACT_UNAVAILABLE_OR_INVALID`；`domains/task_status.py`读取consumer默认路径，进程存活仍CANNOT_CONFIRM。配置owner、历史backfill和同日自然receipt是不同证据，不能批量改成绿色。
5. **HK空卡片文案借用了合并状态。**`apps/web/src/App.vue` 的空HK卡片打印 `stageWorkbench.stage.display_status`；当前可出现“港股无可确认候选”下面却是合并的PARTIAL_WITH_ROWS（来自A）。这是可精确定位的展示含混，可用HK自身reason/status显示；不得藉此隐藏源错误或把0宣布为成功。
6. **其余源缺口继续单独显示。**公众号/复盘/分时/白毛缺输入、美股PARTIAL等在页面真实可见；不属于本轮HK根因，不再扩修。这些状态不能全局阻断已有有效A汇总，9/30A来源205、页面分页200，已有结果仍可显示。

截图及DOM：`evidence/ui_20260930_1445.jpg`、`ui_20260930_0925.txt`、`ui_20260930_1445.txt`、`ui_task_status.*`、`ui_20261008_preselection.*`。初次打开时“读取中”不是最后结论，记录以上加载完成后的结果。没有点击运行/恢复/强制物化。

## HK确定根因与停止过度修复的界限

原预选owner使用A或HK Connect开市策略，漏HK-only证券日；r2拆分市场和价格日/资格日，但把资格source强迫定为目标前一HK Connect日（10/8例为9/30），同时读入master要求capture日期等于该日。9/30正式authority pointer缺失，价格panel fallback只有689有效价量代码，而同日master696成员，故exact-source复用失败。696不是自动有效权威，689价格覆盖不是成员权威。7只价量不合格必须沿原隔离规则保留。

完整历史union capture缺原绑定时间，`HK_CAPTURE_RECEIPT_CAPTURED_AT_MISSING`。master自身17:20时间不能借给union；不做历史authority重建、补时间、逐plate还原或第二producer。自然日的原publisher/成员snapshot as-of合同要独立核对。10/7实际合法快照是否可供10/8使用必须从真实来源身份、有效性和PIT证明，不能仅删capture校验。

原publisher已存在：active r9的普通Stage tick调用`stage_center.hk_universe_preflight.ensure_hk_connect_universe`，该入口只接受当下上海日期，按原HK Connect plates读取全成员并记录真实`captured_at`。preselection owner没有调用此入口，而其master步骤只传`--reuse-only`。同时active owner仍把同一个business_date传给panel、master与materializer，Stage仍以前一Connect日验证价格；r2尚未贯通这些活动基线。10/7 authority/master目前不存在是未来自然源未到，不是要求今天重建历史数据。

独立源码判断及细节见 `evidence/hk_source_audit.md`。r2独立P2是现有A池保全证据不足，未证明覆盖bug：只补真实seed→HK-only原链→读回A池字节/内容保全的目标测试。

## 实際运行基线与接入要求

- API8873：`r4-stage-merged-c3e5357d07f068e79296790e0b968934c34541d579c586282c5e83f56f6a3875`；API配置SHA `2ba6b17639d769fe8adf977707b099ec1de1587c65b81eb0675d3ad81323996b`，manifest SHA `ec5c62cd8a9935c6c2838afd3c02a98ea9fe9d2aaefdae27fb5d462a8c65e3b5`。保持这个owner，不能覆盖成旧consumer版本。
- Stage：`20261001-stage-pr16-a1445-a0925-crossday-r1`；配置SHA `9e285d6423b0232a0f10d7d6707e6fd24a9cc067fb16ab7a31cfb8d2ec676b84`。按计划触发，当前无PID不证明失败。context实际SHA `3bfaae2b13bc8fdb7658e38047f505a8e4c74c1ce5cfb762d38c912bba23e89e`，与PR16 before/after均不同，必须隔离逐hunk适配，不能原地覆盖。
- preselection app：`r9-hk-child-binding-standard-b1f316ac73f0`，实际owner是单体`infrastructure/scheduling/executor_registry_preselection.py`；wrapper按自身路径取app，plist WorkingDirectory另一旧路径不能直接认成root错位。
- shared package独立：`20260923-hk02-owner-rebase-r2/app/upstreams/v3_shared_data`。实际数据root有v35 state与v4 state的显式绑定，见历史交接和CURRENT_BINDINGS；不猜root、不搬数据。

`source/canonical/`是当前相关源码，`source/active/`是实际三基线及API相关原件，`frozen_r2/`是本批patch/preimage。只提交这些显式路径及证据，不提交整个dirty diff。包是源码交接，不能作为完整app直接启动。三个已有半成品HK r2 candidate保持原样，不上线、不删除。

## 一次接续与验收

Chat先依据包内合同做HK最小修复，返还canonical/active各基线的精确patch、before/after及SHA、目标测试完整源码与实际日志、下载ZIP和固定GitHub提交。Mac再做隔离组装、现有服务Python独立目标测试、最小实际入口验证，最后才报告分层状态。原A阶段与不变测试直接复用，不增加6项旧catalog/status漂移修复。

编码验收：HK-only owner→publisher（必要时）→shared materializer→V4 projector→Stage的price/signal与eligibility身份和as-of全程一致；前一HK证券日价格严格、目标Connect日严格；未来来源/错身份/缺真实capture/价格旧日拒绝；已有A真实池保全；正常双方开市兼容。自然源未到或历史源缺失，保留具体data gap。

`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；本轮readyz读回三个安全值均false。PR16保持Draft；新交接不合并、不部署。Chat意见和作者PASS不是Mac独立TESTED/BEHAVIOR_VERIFIED，更不是NATURAL_VERIFIED。
