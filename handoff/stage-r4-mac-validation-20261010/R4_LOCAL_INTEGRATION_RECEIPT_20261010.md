# R4 Mac 本地集成回执 · 2026-10-10

## 结论与边界

固定包 ZIP SHA-256 `6876b49eb117990e3d5ab9115e6835acf195005ab0c8ba9a500dcaa803a0b626`、Git commit `57d00a88e3e7cbc586cb1cf7d9452a41cf1d5a7c` 已逐文件核验：268/268 个 Git blob 一致，包内 268 个交付文件验证通过；另有 2 个包外传输元数据，不作为执行权威。源文件 preimage 与 R4 固定值完全匹配。

本批已完成 Step 1–5：生成完整隔离候选，候选 API/UI 与真实同 run API、18 个旧日期语义及 Playwright 页面回读均通过；独立 Reviewer 对隔离候选出具 `REVIEWED / BEHAVIOR_VERIFIED`。冻结的 479 项 Mac 套件为 **413 passed；66 PermissionError cases（8 failures + 58 setup errors）**，所以冻结 PASS_SIGNAL 未满足。**停止在候选验证；没有进行 Step 6/7、服务切换、部署、提交或推送。**

本轮没有修改 `/Users/lexi/Desktop/学习/v4_app` 中的源码/配置，也没有写入现役服务、plist、scheduler、8873、Vibe 8910、Stage 历史或名称来源。一次 Playwright 初始化将唯一新快照写在 `v4_app/.playwright-cli/`；随后已将该确切文件移到 R4 evidence 并移除空目录，`git status -- .playwright-cli` 无输出。

## 分层状态

| 层 | 状态 | 证据 |
|---|---|---|
| IMPLEMENTED | PASS，仅隔离候选准备 | `candidate/mac_apply_20261009_r4_01/` |
| TESTED | FAIL，413/479 | `candidate/mac_apply_20261009_r4_01/independent_checks/RESULTS.json`；`evidence/INDEPENDENT_CHECKS_MAC_SUMMARY.json` |
| API_VERIFIED | PASS，仅 `127.0.0.1:18873` 候选 | `evidence/TEMP_API_TARGET_READBACK_03.json`，HTTP 200；A/HK run 各 10 行，binding 为 `EXACT_APPROVED_RESEARCH_BINDING_VERIFIED` |
| 历史语义 | PASS，18/18 | `evidence/HISTORY_COMPARE_18_03.json`；完整 `unified_rows`（含代码、名称、顺序）和既有运行/状态摘要一致。候选为 8 个旧日期显式增加 `RESEARCH_ONLY=true`，不改变生产、BUY、订单安全值 |
| UI_VERIFIED | PASS，仅隔离候选 | `evidence/PLAYWRIGHT_BROWSER_VERIFICATION_20261010.json`：10/10 DOM 断言、19/19 本机 GET HTTP 200、console 0 errors / 0 warnings；截图 `evidence/PLAYWRIGHT_STAGE_PANEL_20261010.png` |
| REVIEWED / BEHAVIOR_VERIFIED | PASS，仅隔离候选 | 独立 Reviewer：`evidence/review/r2-local-20261009-r4-479-v35env/UI_BEHAVIOR_REVIEW.json`，SHA-256 `d1267dfcd5a4b8393c43743af695426519e805eede5377e0a50415a3a4f15bc4` |
| INTEGRATED / DEPLOYED | NO | 8873 未切换；候选 release manifest `53d6e5f617332cb6d212f200993b8a06dfedf2cafdb28b11a8f76658cb2a5580`，状态 `CANDIDATE_READY_NOT_DEPLOYED` |
| NATURAL_VERIFIED | NO | 这是回补/隔离 canary，不是自然时段验收 |

## 候选与数据证据

- API 源树 SHA-256 `60fe706b851a921562d1e73ce51dc02fded1d1d8d1bc474da497a8c840e45323`；API 候选清单 SHA-256 `1ae9dcc2adf182b2de8ec80e7b0dd4bfdfd7b8465f23db59211510adf460eca1`。UI 源树 SHA-256 `a442c39659e2b3a6f801ae3434e3cb5129a0b2aa94b54648da60afab7093fedd`；UI 候选清单 SHA-256 `028da5e50b4ff937f4f38af45d7d6892f1303d500ca71de2aa5534225f3dc8ad`。
- 研究绑定状态 `PREPARED_NOT_DEPLOYED`；binding SHA-256 `dd8f728d7d6a2e7a55046528c203caa3530977503d5a6fea939569ff88517c55`；run manifest SHA-256 `9b5df949141ed1533cb7a71e2c46bebe341bea663f5f966bda16225754e89857`。
- 现有 UI lock SHA-256 `3f0b8425f35a7fdeb13cc0e5422b7814b386a6c7559d0e5c6b2f8340bc01be47`；隔离 UI build `UI_BUILD_PREPARED`，dist inventory SHA-256 `1bf17da3e2762cb096e9f3557b5853c92dfcfa07ff7e5e3ca033b0edcb1d89ef`。
- 候选 release manifest SHA-256 `53d6e5f617332cb6d212f200993b8a06dfedf2cafdb28b11a8f76658cb2a5580`；历史根保留 19 个交易日，准备时和结束时 `selection_latest.json` SHA-256 均为 `bfb0ad6b3f5d2261c03fd8db71bf27c3912f581807c7904a2e6fc02217785cd0`。
- `20261009 / STAGE_0930_0935`：backfill run `85e29661ecd848fe9b8344ea59279e86`；A run `run-2688466a1ae4464ba7237f0b`，10 个选择、206/216 行来源；HK run `run-cfbdc9b36a7308da178d193a`，10 个选择、695/695 行来源。整体为 `PARTIAL_WITH_ROWS`。
- 第一次临时服务 PID 53680 未传入现役 plist 的名称来源路径，故历史 A 名称不可确认；保留该 `HISTORY_COMPARE_18.json` FAIL 诊断。经主控批准，同端口重启 PID 54109 并传入精确只读 `V35_PRESELECTION_SOURCE_ROOT` 后，10/8、9/11 等历史名称恢复。`HISTORY_COMPARE_18_02.json` 将 8 个新增 `RESEARCH_ONLY=true` 字段按全 JSON 严格比较标为 FAIL；最终 `HISTORY_COMPARE_18_03.json` 按冻结语义字段比较，并记录这些仅增加研究安全标记的日期，18/18 PASS。
- 页面可见 A 206/216（缺 10）、HK 695/695（缺 0）；HK 名单日期 `20261008`、资格状态待确认、非正式 D1。原执行方历史已核对，但执行过程、自然时段、HK Connect 正式资格、D-1/PIT 均未验证。
- 安全标记保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`；`execution_verified=false`、`natural_verified=false`、`write_performed=false`。

## 479 项套件失败与最小后续

Mac 26.6.2 arm64、Python 3.14.6、uid 501 下：API 121/129（8 failures，0 JUnit errors）、UI 70/70、release 152/152、integration 28/86（58 setup errors，0 failures）、review gates 42/42，合计 **413 passed**。其余 **66 PermissionError cases（8 failures + 58 setup errors）**：只读源文件为 `0444`，`copytree` 保留权限后，API/integration 测试再写入其 `tmp_path` 副本。独立 Reviewer 在相同 Mac 权限条件下复现 413/479。详见 `evidence/INDEPENDENT_CHECKS_MAC_SUMMARY.json`（SHA-256 `51b7ef1a06cfc4acf86ec4bf2155234a603dd5a4a86bc8697960fba43903c3aa`）及 `evidence/review/r2-local-20261009-r4-479-v35env/RESULTS.json`（SHA-256 `93892d84751999d65f88dff2aafc1eebceb60c28cc8959e2a3540f35b3216223`）。Linux EUID 0 作者运行不会暴露此权限问题。

唯一允许推进点是让 Chat 做最小测试 fixture 修复，具体要求见同目录 `CHAT_MINIMAL_FIX_REQUEST_R4_479_MAC.md`。修复后须由独立 Reviewer 在正常 macOS uid 501 下复跑并通过全部 479 项，之后再重新评估冻结门禁；本回执不授权部署。

## 临时服务清理与现役身份

Playwright session `r4-http-20261010` 已关闭；临时 API PID 54109 已退出；18873 无 listener。现役 8873 仍为 PID 44968，cwd `/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`。API plist SHA-256 仍为 `c88e4069f6deb467a204b4510824e62b15cb8fc11dfa7892a43e5ec8eaed8ec4`；selection latest SHA 未变。机器清理回执 `evidence/CLEANUP_VERIFICATION_20261010.json` SHA-256 `866e9d06a6a8fe6691f172577ea31f91dc1111bed4b52c33b0b2b90ce4a42438`。

## 主要命令

准备工具均是包内现有脚本，完整参数记录在对应 JSON receipts 中：

```sh
V4_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
R4_PACKAGE='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/incoming/stage-r3-live-integration-20261009-r4'
R4_WORK='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/candidate/mac_apply_20261009_r4_01'
R4_LIVE_APP='/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app'
R3_RUN_MANIFEST='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/research_0935/run_manifest.json'
R4_HISTORY='/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection'
API_PLIST='/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist'
SCHEDULER_PLIST='/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist'

"$V4_PYTHON" -B "$R4_PACKAGE/tools/verify_package.py" --package "$R4_PACKAGE"
"$V4_PYTHON" -B "$R4_PACKAGE/tools/prepare_canary.py" --package "$R4_PACKAGE" --group api --source-root "$R4_LIVE_APP" --destination "$R4_WORK/api_app"
"$V4_PYTHON" -B "$R4_PACKAGE/tools/prepare_canary.py" --package "$R4_PACKAGE" --group ui --source-root "$R4_LIVE_APP" --destination "$R4_WORK/ui_app"
"$V4_PYTHON" -B "$R4_PACKAGE/tools/prepare_research_binding.py" --manifest-path "$R3_RUN_MANIFEST" --history-root "$R4_HISTORY" --api-after-root "$R4_PACKAGE/after/api" --api-source-root "$R4_LIVE_APP" --output-root "$R4_WORK/research_binding"
"$V4_PYTHON" -B "$R4_PACKAGE/tools/build_stage_ui.py" --package "$R4_PACKAGE" --prepared-ui "$R4_WORK/ui_app" --destination "$R4_WORK/ui_build"
"$V4_PYTHON" -B "$R4_PACKAGE/tools/run_checks.py" --package "$R4_PACKAGE" --api-source-root "$R4_WORK/api_app" --ui-runtime "/Users/lexi/Desktop/学习/v4_app/apps/web" --output "$R4_WORK/independent_checks"  # exit 3, 413/479
"$V4_PYTHON" -B "$R4_PACKAGE/tools/prepare_live_release.py" --package "$R4_PACKAGE" --active-api-plist "$API_PLIST" --scheduler-plist "$SCHEDULER_PLIST" --prepared-ui "$R4_WORK/ui_app" --ui-build-receipt "$R4_WORK/ui_build/BUILD_RECEIPT.json" --binding-proof "$R4_WORK/research_binding/PREPARATION_PROOF.json" --destination "$R4_WORK/integration" --python "$V4_PYTHON" --release-id stage-research-r4-20261009
```

隔离 API 的实际启动命令以 `env -i` 清洁环境运行候选 release app 的既有 `create_app(...)/uvicorn.run(...)`，bind `127.0.0.1:18873`；data root 是新建的 `candidate/mac_apply_20261009_r4_01/http_canary_data_02/data`，只读读取原 `R4_HISTORY` 和现役 plist 中 `V35_PRESELECTION_SOURCE_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`。服务 PID 为 54109。Playwright CLI session `r4-http-20261010` 打开 `http://127.0.0.1:18873/?date=20261009&stage=STAGE_0930_0935`，检查页面快照、panel、DOM、console 和 network 后关闭。

```sh
R4_ROOT='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009'
NPM_CONFIG_CACHE="$R4_ROOT/tools/npm-cache" PLAYWRIGHT_BROWSERS_PATH='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/tools/playwright-browsers' npx --yes --package @playwright/cli playwright-cli -s=r4-http-20261010 open 'http://127.0.0.1:18873/?date=20261009&stage=STAGE_0930_0935'
NPM_CONFIG_CACHE="$R4_ROOT/tools/npm-cache" PLAYWRIGHT_BROWSERS_PATH='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/tools/playwright-browsers' npx --yes --package @playwright/cli playwright-cli -s=r4-http-20261010 snapshot e475
NPM_CONFIG_CACHE="$R4_ROOT/tools/npm-cache" PLAYWRIGHT_BROWSERS_PATH='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/tools/playwright-browsers' npx --yes --package @playwright/cli playwright-cli -s=r4-http-20261010 screenshot e475 --filename "$R4_ROOT/evidence/PLAYWRIGHT_STAGE_PANEL_20261010.png"
NPM_CONFIG_CACHE="$R4_ROOT/tools/npm-cache" PLAYWRIGHT_BROWSERS_PATH='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/tools/playwright-browsers' npx --yes --package @playwright/cli playwright-cli -s=r4-http-20261010 close
```

上述 Playwright 命令中的 `$R4_ROOT` 即 `/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009`。曾尝试对 element screenshot 加 `--full-page`，Playwright 明确返回 `fullPage cannot be used with element screenshots`；移除该选项后，1214×721 panel PNG 正常生成。DOM 断言执行器使用 `run-code 'async () => { ... }' --json --raw`；准确断言值及网络/console 结果保存在 `PLAYWRIGHT_BROWSER_VERIFICATION_20261010.json`。

## 本轮关键文件

源码实际修改：**无**。R4 内生成的候选完整清单由 package/candidate manifests 管理。主要只读验收产物包括：

- `evidence/TEMP_API_TARGET_READBACK_03.json`
- `evidence/HISTORY_COMPARE_18_03.json`
- `evidence/PLAYWRIGHT_BROWSER_VERIFICATION_20261010.json`
- `evidence/PLAYWRIGHT_STAGE_PANEL_20261010.png`
- `evidence/PLAYWRIGHT_STAGE_PANEL_SNAPSHOT.txt`
- `evidence/CLEANUP_VERIFICATION_20261010.json`
- `evidence/review/r2-local-20261009-r4-479-v35env/UI_BEHAVIOR_REVIEW.json`

Full API payload与截图仅作为本机证据；共享/同步摘要时排除原始 API、行情响应与图片库存。
