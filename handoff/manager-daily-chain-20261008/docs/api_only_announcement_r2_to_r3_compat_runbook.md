# 10/7 公告分析回读兼容：R2 → R3 API-only 切换

## 目的与已知结果

当前 R2 API 对已存在的 `2026-10-07 / 2026-10-06` 分析产品返回 409。原因是产品内 40 条 reader-content-gap 记录缺少逐条 `selection_status`，虽然相同记录在 `stock_selection.article_decisions` 中均为 `NOT_ASSESSED`。R3 的有限兼容规则只接受这种无新 agent receipt 的旧产品，并继续拒绝新 agent 产品缺少 row marker 或 reader-gap 被选中的情况。原产品 canonical SHA 必须保持 `7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278`；本方案不重导入、不改写产品或源证据。

本次 R3 API release 仅相对 R2 改动 `v4/manager_research/announcement_analysis.py`。R3 app inventory SHA 为 `07ff61bc18f66f7e92eb45f57a20aecf3885eaa79c1bdb705b8f805fdbb95bd8`，外层 manifest SHA 为 `946c49b9c34bd09fbca04644556de3acba1635eb240fa9293f6391e9d46b40e9`。已导入的当前 `2026-10-08 / 2026-10-07` 产品 canonical SHA 为 `8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157`，其 33 个 SELECTED 与 54 个 CONDITIONAL_WATCH 结果需在切换后保持。

Writer 只交付候选 release、helper 和步骤，没有执行切换、回滚、owner import 或页面验收。以下切换由根主控在独立 package review PASS 后执行。

## 1. 切换前只读 preflight

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/candidate/analysis-readback-compat/helpers/switch_api_only_announcement.py" \
  preflight
```

只在返回 `READY_API_ONLY_ANNOUNCEMENT_CUTOVER` 且 `api_release.release_id`、manifest、inventory 均与上列 R3 身份一致时继续。Preflight 还要求 active API plist SHA `b2eb9828645538863571ea9cdb0d830ac76afcafba551faf127a16752db2eee3`、staged R3 plist SHA `72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5`、V4 scheduler plist SHA `c478c87e7866fa50154df674ea7cb570197251aaa5da3014b3666e7f22914da2`、Stage Center scheduler plist SHA `9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5` 与冻结值一致，并核对 disabled plan binding、R2→R3 plist 允许差异、LaunchAgent 当前身份及已登记 10/8 handoff 的源证据。它不写正式研究状态，不执行导入或页面刷新。任一值不同即停止，不调整 pin 以绕过失败。

## 2. 根主控执行 API-only 切换

再次完成第 1 步并核对同一组 SHA 后，由根主控运行：

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/candidate/analysis-readback-compat/helpers/switch_api_only_announcement.py" \
  execute \
  --confirm SWITCH_API_ONLY_TO_R3_ANNOUNCEMENT_COMPAT \
  --expected-current-plist-sha256 b2eb9828645538863571ea9cdb0d830ac76afcafba551faf127a16752db2eee3 \
  --expected-staged-plist-sha256 72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5
```

成功回执应为 `API_ONLY_SWITCHED_ROUTE_VERIFIED`，并读回 R3 app/release/manifest 身份及公告 analysis import route。该动作只 bootout、替换、bootstrap `com.lexi.v35.api-only`；不会执行 owner import，也不要求 reimport 已有产品。V4 scheduler 和 Stage Center scheduler 只读校验并保持原样，plan binding 仍 disabled。切换后保存 operation receipt 和其备份路径。

若 bootout 之后发生任何失败，helper 会先观察实际 LaunchAgent 状态，必要时只恢复原 API plist 并最多 bootstrap 原 API 一次。只有回执为 `ROLLED_BACK_TO_PREIMAGE` 才能确认自动恢复；`ROLLBACK_INCOMPLETE` 表示 API 状态不能确认，立即停止后续 API/UI 操作并保留回执。Stage Center 外部漂移会被记为 `DRIFTED_EXTERNAL_STATE`，脚本不会改写该计划任务。

## 3. API 回读验收

在 `http://127.0.0.1:8873` 对两个明确日期对分别读回。旧产品：

```sh
curl --fail-with-body -sS \
  'http://127.0.0.1:8873/api/v4/manager/research/announcements/analysis?date=20261007&publication_date=2026-10-06'
```

验收要求 HTTP 200、`analysis.status=VERIFIED`、`analysis.product_sha256=7b27fe7d40e9c12db3d56751cc789c6eb84515bb2392fc1b00a3bc4a5fd38278`、580 条记录；40 条 reader-content-gap 的 stock-selection article disposition 均为 `NOT_ASSESSED`。旧产品没有 R3 owner receipt sidecar 是预期状态，不要为补 receipt 而重导入或改写旧产品。

当前产品：

```sh
curl --fail-with-body -sS \
  'http://127.0.0.1:8873/api/v4/manager/research/announcements/analysis?date=20261008&publication_date=2026-10-07'
```

验收要求 HTTP 200、`analysis.status=VERIFIED`、canonical product SHA 保持 `8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157`、owner receipt 仍验证通过，以及 33 个 SELECTED 和 54 个 CONDITIONAL_WATCH 结果不变。记录状态码、日期对、产品/receipt SHA 和实际计数；HTTP 200 单独不算完成。

## 4. 页面验收与回滚

API 两组读回通过后，由根主控重新加载经理选股台对应日期，分别核对 10/7 历史公告分析和 10/8 当前公告分析的产品身份、覆盖及 selection 状态。记录 `API_VERIFIED` 与 `UI_VERIFIED`；如果没有重新加载页面并核读，不得报告 UI 验收通过。自然时段运行另行记录，候选切换不证明自然运行。

如果需要撤回，先保存失败证据并确认 active API plist 仍为 staged R3 SHA，再使用成功切换 receipt 中的原始 plist 备份：

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/candidate/analysis-readback-compat/helpers/switch_api_only_announcement.py" \
  rollback \
  --receipt <successful-operation_receipt.json> \
  --confirm ROLLBACK_API_ONLY_TO_R2_PREIMAGE \
  --expected-current-plist-sha256 72050bf4c7f00c8271cf9226ea866683a8e9e459d2875547b08f69fad30bfdf5
```

Rollback 仅恢复 R2 API plist 并重载原 API，不删除或改写任何 owner 产品。R2 对旧 10/7 产品的兼容缺口会随回滚恢复；10/8 正式产品仍保留原 SHA。若 receipt、备份、active plist、调度器 preimage 或 LaunchAgent 身份不匹配，helper 会失败关闭。

安全标记保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。本方案不激活计划刷新、不改 scheduler、不做交易动作。
