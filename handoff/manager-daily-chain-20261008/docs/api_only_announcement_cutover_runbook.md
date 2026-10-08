# 10/8 公告分析入台：API-only 切换

这条路径只为 2026-10-08 / 2026-10-07 公告的正式 owner 导入开放已审核的 R2 API 路由。`POST /api/v4/manager/research/announcements/analysis/import` 校验固定目录里的登记交接，调用 `ManagerResearchJobService.import_announcement_analysis` 并做 owner readback；路由不读取计划 scheduler binding，也不要求 2026-09-25 plan canary。当前 API plist 使用 disabled plan binding，scheduler plist 保持原样。因此本闭环不启用计划刷新，不改计划任务。

执行人：根主控。当前阶段只交付脚本与步骤，Writer 没有执行切换。

## 1. 切换前只读检查

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/helpers/switch_api_only_announcement.py" \
  preflight
```

唯一可继续的状态是 `READY_API_ONLY_ANNOUNCEMENT_CUTOVER`。脚本重新核对 R2 app manifest 与完整文件 inventory、disabled binding、API/调度器 plist 的冻结 SHA、正式 manager state root、当前 launchd 运行身份和候选 plist 的唯一允许差异。任何 preimage 改动都失败关闭。

同一次只读检查还会通过 R2 `validate_registered_handoff` 校验已登记的正式状态证据：run `3f9d37a643060b57992167f3df05d987`，目标日 `20261008`、公告日 `2026-10-07`，613 条产品。登记 manifest 的 canonical SHA 是 `70ffa628e43d43c451defecb728197cde4bcc437bbfafc3e883ecf0b3327a03e`，其文件 SHA 是 `10b3d551380109ca6dd659e1e2ce1dff13b4dcd9c407f57992b94fc6c4d2dc43`；产品 canonical SHA 是 `8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157`，其文件 SHA 是 `5c4e9e29206ce56a8366e1dd3d5cad965a70491d37a0804a6637113ab9f27790`。正文捕获为 608 条完整、5 条终态失败；失败文章只能保持 `NOT_ASSESSED`。预检只读取和验证这些字节，不做 owner import 或页面刷新。Reviewer 输出按登记记录为 `PASS`，证据状态是 `DECLARED` 且字节绑定；这不证明平台身份认证。若任一 pinned SHA、日期、数量、失败处置或 validator 校验不符，脚本失败关闭。

## 2. 根主控显式执行 API-only 切换

先复跑第 1 步，核对输出仍为同一组 SHA，再执行：

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/helpers/switch_api_only_announcement.py" \
  execute \
  --confirm SWITCH_API_ONLY_TO_R2_ANNOUNCEMENT_OWNER \
  --expected-current-plist-sha256 36b80da4e7cd2d002c0338c7b3788ed01572d89bdaf928f668305af7abdb3ab2 \
  --expected-staged-plist-sha256 b2eb9828645538863571ea9cdb0d830ac76afcafba551faf127a16752db2eee3
```

它先在本任务目录内留下原 plist 的逐字节备份和操作 receipt，然后只卸载、替换、重新加载 `com.lexi.v35.api-only`。成功条件包括 launchd 读回 R2 app/release/manifest 身份，以及本机 OpenAPI 含公告导入 POST 路由。该步骤不导入分析产品。若候选 API 启动或路由检查失败，脚本会尝试自动恢复备份并重新加载原 API；若自动恢复未通过，receipt 会标记 `ROLLBACK_INCOMPLETE`，停止后续导入。

## 3. 由根主控导入已登记的实际 613 条产品并读回

从成功切换输出的 `operation_receipt.json` 保留 backup 与 SHA。用已登记 handoff 的实际 `evidence_run_id` 运行正式 owner import：

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r2-api/app/ops/run_manager_daily_announcement.py" \
  import \
  --evidence-run-id 3f9d37a643060b57992167f3df05d987 \
  --research-state-root "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research" \
  --api-base http://127.0.0.1:8873
```

成功输出必须包含日期对 `20261008 / 2026-10-07`、产品 SHA、owner `available_at` 与 owner receipt SHA。随后执行：

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/manager-daily-chain-20261008-r2-api/app/ops/run_manager_daily_announcement.py" \
  readback \
  --target-date 20261008 \
  --publication-date 2026-10-07 \
  --api-base http://127.0.0.1:8873
```

只有 `OWNER_READBACK_VERIFIED` 且 product/owner receipt SHA 与 import 输出一致，才算正式 owner 导入通过。导入后由根主控重新加载经理选股台的 2026-10-08 日期页，检查公告分析状态、613 条源目录与分析结果的产品 SHA/覆盖关系。API route 或 HTTP 200 本身不证明页面显示完成。

## 4. 回退

如果 API-only 页面通路需要撤回，先停止后续读写，确认当前 API plist SHA 仍为候选 staged SHA，再用成功切换 receipt 指向的原始备份回滚：

```sh
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" \
  "/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/deployment/c1_plan_only/helpers/switch_api_only_announcement.py" \
  rollback \
  --receipt <successful-operation_receipt.json> \
  --confirm ROLLBACK_API_ONLY_TO_RECORDED_PREIMAGE \
  --expected-current-plist-sha256 b2eb9828645538863571ea9cdb0d830ac76afcafba551faf127a16752db2eee3
```

回滚只恢复 API plist 并重载原 API；不会删除已经写入正式 manager store 的 owner 产品，也不触碰 scheduler plist。若 receipt、备份、候选当前 SHA、scheduler SHA 或 launchd 当前身份不一致，脚本拒绝回滚并留下冲突证据。

## 明确边界

- Announcement import 依赖已登记固定路径 handoff、R2 API owner importer/readback；不依赖 scheduler 激活或 plan canary。
- Scheduler、计划 refresh、announcement collection hook 不切换；计划功能仍是未激活状态。
- 不抓取、不重算 reader 判断；沿用登记的 613 条产品和源 SHA。
- 所有研究安全标记保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- Writer 未执行 `execute`、`rollback`、owner import 或 UI 验收。API 切换、owner readback、页面验证需根主控按上述步骤分别记录。
