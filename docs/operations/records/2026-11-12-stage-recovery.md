# D12阶段选股边界修复与缓存补跑结果

状态：独立Reviewer PASS；本地Stage已激活，六阶段隔离BACKFILL已发布并回读。代表API/UI仍读取原自然列表，PARTIAL真实保留；后续自然运行未验收。证据根：`/Users/lexi/Desktop/学习/agents调试/v4_stage_recovery_20261112`。

## 实际断点

- 14:13用户截图所见前六阶段均有原owner运行/原始/选股回执，A/HK各10条；阶段7截止15:00尚未到，不是已失败。API读取原结果正常。
- 原A采集输入367条，来自有效研报推荐池；不按页面200行截断。v192主预选池缺失，复盘/Stage7/白猫/公众号子池各0条并隔离；不是D11原公式426只的分母。
- 原367含515880通信ETF及000660海力士误标A。原生09:25对000660返回未知股票；不补抓其所谓A股行情。5809原目标清单只能证明正向覆盖，不能当完整交易所证券主表，000660继续UNKNOWN。
- 09:25缓存361行、6缺项；五个BJ是供应商不支持，保留身份。仅42行全部价格/量额字段正数，原快照不是竞价成交认证。晚采不能补成真实09:25。
- 阶段2—6原始缓存366行，缺000660；其中包含ETF。原研究owner的小时包、来源见证、发布和完成回执均已绑定；质量/早报分数原本缺失、ZSXQ原源PARTIAL，不能把累计research_score冒充质量分。
- `OWNER_RECEIPT_SELECTION_TRIOS_BOUND_EXECUTION_UNVERIFIED`表示原owner历史与选股三件套绑定，但D12独立执行认证缺失；不等于选股没有产生，也不自动证明自然/PIT。HK独立认证不由本Writer签发。

## 冻结修复

唯一Writer工作树：`/Users/lexi/.codex/worktrees/stage-recovery-20261112/v4_app`，分支`codex/stage-recovery-20261112`，基线`a060e113e74d9d8b7b31a7f39c59981bf30dc0ab`。

源码范围：`stage_center/a_share_membership.py`、`stage_center/_runner_parts/slot_execution.py`、`tests/test_stage_a_authoritative_membership.py`及本文；候选另带基线已有且字节未改的`contracts/a_share_instruments.py`依赖。

当前active slot与Git基线存在旧差异，已保留exact active prepatch后只加入10行guard接线。`ACTIVE_SLOT_VS_BASELINE.diff`是原部署依赖；`ACTIVE_TO_CANDIDATE_SLOT.diff`才是本轮运行行为差异。Git大diff不能解释为本轮重构。原active包含`collector_capture.py`、原生09:25重建及其他已部署模块，工作树不完整包含其闭包；必须从当前active克隆并最小覆盖，禁止从工作树整包替换。

- 原acquisition367及APPEND_ONLY合同不修改，不发布缩水successor；原数据/自然回执/选股三件套不覆盖。
- 复用既有证券类型规则隔离已知非股票族，和库存日期是否过期独立；不硬编码ETF代码或公司名。
- 绑定D11 generation、原selector锚点SHA、generation manifest SHA、adjustment snapshot SHA、目标日期与candidate current SHA；5809原target inventory含停牌/隔离证券，未用5541日bar清单。未出现于库存的股票族保持UNKNOWN，不由缺失反推退市或非A。
- A请求、选股源及覆盖分母共用同一过滤；HK不变。原367→有效请求366，000660继续缺项；阶段2—6可评分缓存365。09:25原361→360股票观察行。
- 缺失/过期/不匹配库存时，不丢合法股票族、不阻断其他来源；已知非股票族仍隔离，并显示`A_MEMBERSHIP_AUTHORITY_UNKNOWN`。当前环境配置仅D12，未来日期不会误用D11为正向认证；未来配置未备齐会明确UNKNOWN。本次不建新日更producer。

## 候选与针对性验收

候选：`/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-stage-membership-20261112-r1/stage/app`。

`CANDIDATE_PREPARED.json`记录唯一4个运行差异、所有其他入口字节保留、源码匹配及manifest。Main binding保持`558d313e…`原值，API/Main/调度表未更换。

实际候选根运行25项针对性测试通过：证券族、未知身份、BJ/停牌/无当日bar保留、请求/评分/覆盖一致、HK不变、缺失/错误日期/generation/SHA/不完整库存，以及既有slot调用兼容。最终命令见`TEST_RESULTS.json`，结果25 passed / exit0。首次共享pytest临时根收尾碰到其他任务旧garbage EPERM，断言25通过但进程exit1；保留错误，不清理他人临时目录。另一次候选测试ini路径空格拆分造成import失败，改用明确PYTHONPATH后通过。

原owner缓存回看准备已完成：`RECOVERY_PREPARED.json`、`prepared_envelopes/`。每个retained collector响应的SHA/身份核对后，19字段投影与原owner验证的raw完全一致；响应诊断本身不被当作授权。使用原production_selection_builders和原小时owner见证读取，不改公式/评分或填补原缺失值。六阶段Top10代码及顺序全部和原结果相同，继续PARTIAL/WATCH_ONLY。

## 实际执行与验收

独立Reviewer对冻结源码、实际候选、25项测试、原生09:25保留、缓存补跑及Stage单独切换命令作出 `REVIEWED/PASS`。证据为 `INDEPENDENT_REVIEW.json`；本PASS不认证PIT、交易资格或缺失上游已恢复。

控制器于北京时间14:44执行受保护操作器：

```sh
PYTHONPATH='/Users/lexi/.codex/worktrees/stage-recovery-20261112/v4_app' '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B '/Users/lexi/Desktop/学习/agents调试/v4_stage_recovery_20261112/activate_stage_membership.py' --execute
```

操作器SHA为 `9ca4be4f62883f94ff55d67a5b577caab802a99dde6d7c8048a91bdda6978b8b`，使用既有owned interprocess lock、空闲/定时窗口检查、冻结SHA、CAS、原子plist替换、顺序检查与受限回退。实际回执 `STAGE_ONLY_CUTOVER_20261112T064409_510123.json` 为 `STAGE_DEPLOYED_LOADED_ENV_VERIFIED`；Stage manifest为 `61bbf480d8833c7e43c5cdfe780a8f23f0d341e799c47dc52e38ec4266ba6aa4`。Main/API plist、PID/启动时间和业务环境均保留，调度字段不变。激活不等于自然执行PASS。

14:44:15发布准备好的六阶段结果，未重新采集或评分：

```sh
# 工作目录为本证据根，避免canonical当前目录优先覆盖PYTHONPATH。
PYTHONPATH='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-stage-membership-20261112-r1/stage/app' '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B '/Users/lexi/Desktop/学习/agents调试/v4_stage_recovery_20261112/prepare_cached_replay.py' --publish
```

`RECOVERY_PUBLISHED.json` 为 `PUBLISHED_ISOLATED_BACKFILL`，run为 `a-membership-d12-cached-r1`，provider/rescore均0。结果通过既有SafeRoot/SelectionStore与owner receipt接口落在 `state/stage/selection/backfill/<run>`、`state/stage/receipts/backfill/<run>`。原367输入、原raw及六份自然receipt SHA保留。`BACKFILL_READBACK.json`实际用候选owner逐项读取六份产物通过：请求366，各10条PARTIAL，Top10代码/顺序与准备及原owner一致。机械六产物核验不等于全部股票数值逐项认证。

API代表09:25、09:35、13:15返回200，A/HK仍各10条，状态PARTIAL。既有consumer优先原已验证列表，BACKFILL只作为缺结果时的显式回看候补；当前无HTTP参数强制展示本run，因此不声称新补跑已替换UI列表。独立无界面Chrome使用临时profile核验同三个页面，无脚本错误，浏览器已关闭；见 `API_AFTER.json`、`UI_AFTER.json`。原窗口CUA两次读取超时，未发送点击/按键，其收尾调用被工具中止；不声称该工具当前控制状态已核验。原窗口、登录与业务服务保留。

一次初始只读store核对因默认cwd引入canonical旧算法而被SHA校验拒绝，未写业务数据；改用明确证据工作目录及候选import路径断言后六份读取全部通过。原错误见 `READBACK_ENVIRONMENT_FAILURE.json`，未放宽SHA校验。

回退仅在Stage空闲且当前plist仍为本批预期SHA时，经同一操作器恢复候选根 `before-stage.plist`；不得覆盖其他人的新版本或停止在途工作。BACKFILL留存，不删除原来源。`MEMBERSHIP_CONFIG.json`及其绑定原件为当前Stage运行依赖，不能当临时垃圾清理。源码同步commit及远端文件SHA另见证据根 `GITHUB_SYNC.json`。

## 保留缺口

未执行：阶段7及本次切换后的自然运行认证、缺失上游源补齐、PIT/竞价成交认证。模型/v192源及其他空子池另按原owner补齐，不能以本轮阶段输入修复宣称恢复。09:25非竞价成交、真实分数字段缺失、000660身份、HK13:15分钟捕获晚于截止等继续CANNOT_CONFIRM。全程`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
