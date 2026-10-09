# Mac 落地顺序：隔离准备 → 独立复跑 → 既有发布链 → 同 run API/UI

下列命令由 Mac 执行，Chat 已交付业务逻辑和工具。固定目标是已验收的 R3 `20261009 / STAGE_0930_0935` 两市场研究结果。R4 准备目录必须是新的；失败目录保留作证据，下一次换新目录，不在失败副本上绕过 SHA 或权限检查。

## 1. 固定输入与包校验

把下载 ZIP 解压到 `incoming/`。ZIP 内的 `stage-r3-live-integration-20261009-r4/` 是本包。先使用交付消息的固定 Git commit / ZIP SHA 核对来源，再执行内部清单校验。

```sh
R4_PACKAGE='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/incoming/stage-r3-live-integration-20261009-r4'
R4_WORK='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/candidate/mac_apply_20261009_r4_01'
R4_LIVE_APP='/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app'
R4_API_PLIST='/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist'
R4_SCHEDULER_PLIST='/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist'
R4_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
R4_HISTORY='/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection'
R4_MANIFEST='/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/research_0935/run_manifest.json'

"$R4_PYTHON" -B "$R4_PACKAGE/tools/verify_package.py" --package "$R4_PACKAGE"
mkdir -p '/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R4_MAC_20261009/candidate'
mkdir "$R4_WORK"
```

预期包校验 `PASS`。不要使用 canonical 根替换 `R4_LIVE_APP`；其中当前 App 前像 SHA 必须是 `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5`，当前 UI App 前像必须是 `f43bdb2c7214bce09221757eecb75eea9d5e1c746a3213bb53e6d0c84b751d9c`。其他前像由工具逐项检查。

## 2. 建立隔离源码副本和真实研究读取绑定

```sh
"$R4_PYTHON" -B "$R4_PACKAGE/tools/prepare_canary.py" \
  --package "$R4_PACKAGE" --group api --source-root "$R4_LIVE_APP" \
  --destination "$R4_WORK/api_app"

"$R4_PYTHON" -B "$R4_PACKAGE/tools/prepare_canary.py" \
  --package "$R4_PACKAGE" --group ui --source-root "$R4_LIVE_APP" \
  --destination "$R4_WORK/ui_app"

"$R4_PYTHON" -B "$R4_PACKAGE/tools/prepare_research_binding.py" \
  --manifest-path "$R4_MANIFEST" --history-root "$R4_HISTORY" \
  --api-after-root "$R4_PACKAGE/after/api" --api-source-root "$R4_LIVE_APP" \
  --output-root "$R4_WORK/research_binding"
```

两次源码准备应返回 `CANARY_PREPARED`；绑定准备应返回 `PREPARED_NOT_DEPLOYED`。绑定工具读取真实 Mac run、原 Stage 候选源码、owner/history/selection 三件套后生成两份配置和 `PREPARATION_PROOF.json`，没有测试 fixture 开关。

这些引用必须继续保留原位：R3 的 `research_0935` 输出、`stage_app`、原 R3 package 的 `SOURCE_MAP.json`。已批准 manifest 固定了它们的路径与 SHA；清理或改写它们会使绑定失败。不要复制到 live state 来绕过验证。

## 3. 现役 UI 源码的隔离构建与独立复跑

```sh
"$R4_PYTHON" -B "$R4_PACKAGE/tools/build_stage_ui.py" \
  --package "$R4_PACKAGE" --prepared-ui "$R4_WORK/ui_app" \
  --destination "$R4_WORK/ui_build"

"$R4_PYTHON" -B "$R4_PACKAGE/tools/run_checks.py" \
  --package "$R4_PACKAGE" --api-source-root "$R4_WORK/api_app" \
  --ui-runtime '/Users/lexi/Desktop/学习/v4_app/apps/web' \
  --output "$R4_WORK/independent_checks"
```

构建预期 `UI_BUILD_PREPARED`，产生 `ui_build/BUILD_RECEIPT.json`。工具自行运行 `npm ci`、`npm run build` 并隔离 npm cache，不需要向只读 prepared App 加写权限或链接 canonical 的 node_modules。

独立复跑预期 `RESULTS.json.status=PASS`，每个 suite 的实际用例 ID、数量、零 skip 和源码 SHA 都由包内固定合同检查。`--ui-runtime` 仅使用已安装的 Vue 依赖来编译包内的当前页面，不读取 canonical App.vue 作为被测源码。这里的跨 API/UI fixture 是每次新生成的合成测试数据，不代替真实研究 run 的下一步回读。

## 4. 生成具体的完整发布候选

```sh
"$R4_PYTHON" -B "$R4_PACKAGE/tools/prepare_live_release.py" \
  --package "$R4_PACKAGE" \
  --active-api-plist "$R4_API_PLIST" --scheduler-plist "$R4_SCHEDULER_PLIST" \
  --prepared-ui "$R4_WORK/ui_app" \
  --ui-build-receipt "$R4_WORK/ui_build/BUILD_RECEIPT.json" \
  --binding-proof "$R4_WORK/research_binding/PREPARATION_PROOF.json" \
  --destination "$R4_WORK/integration" \
  --python "$R4_PYTHON" --release-id stage-research-r4-20261009
```

预期 `CANDIDATE_READY_NOT_DEPLOYED`。完整 App 固定生成在：

`$R4_WORK/integration/candidate/stage-research-r4-20261009/app`

回执 `$R4_WORK/integration/PREPARATION_RECEIPT.json` 给出全部 source/delta/manifest/静态 SHA、原历史根和新 Stage 保根计划。原 full builder 的通用计划会隔离经理状态根，被明确标为 `publication_eligible=false`，不可用于本次切换。

## 5. 隔离真实 HTTP / 页面复核

在完成前四步、仍保留上述变量的同一终端中，从完整候选 App 启动临时 API，继续使用既有 `create_app`/uvicorn 入口、`127.0.0.1:18873` 与单独 data root；`stage_center_selection_root` 仍传原 `R4_HISTORY`。R4 配对绑定已经进入该候选，不需要改业务源码或临时修改路由。该命令前台运行；用浏览器或另一个终端做回读，完成后回到这个终端按 Ctrl-C 结束临时服务，再继续发布步骤。

```sh
R4_CANDIDATE_APP="$R4_WORK/integration/candidate/stage-research-r4-20261009/app"
R4_CANARY_DATA="$R4_WORK/http_canary_data"
mkdir "$R4_CANARY_DATA"
cd "$R4_CANDIDATE_APP"
"$R4_PYTHON" -B -c \
  'import sys; from pathlib import Path; import uvicorn; from apps.api.v35_api.app import create_app; app=create_app(data_root=Path(sys.argv[1]),stage_center_selection_root=Path(sys.argv[2])); uvicorn.run(app,host="127.0.0.1",port=18873,log_config=None)' \
  "$R4_CANARY_DATA/data" "$R4_HISTORY"
```

访问：

- API：`http://127.0.0.1:18873/api/v3/workbench/stage?date=20261009&stage=STAGE_0930_0935&limit=50`
- 页面：`http://127.0.0.1:18873/?date=20261009&stage=STAGE_0930_0935`

核对 A/HK 各 10，A 206/216、HK 695/695；A run `run-2688466a1ae4464ba7237f0b`、HK run `run-cfbdc9b36a7308da178d193a` 与 manifest/consumer/API/页面一致。页面应同时显示研究来源限制、owner/history 绑定和“自然时段未验证”，不能把 formal D1 或成员资格标为 READY。

在原 19 个历史日期中抽查已有阶段结果与当前 8873 一致，并保留 API JSON、浏览器截图/断言及加载源码 manifest SHA。验完关闭该终端进程/浏览器，确认 18873 无 listener。不要复用旧 R3 截图作为 R4 的新页面验收。

## 6. 发布与回滚

先结束 18873 临时服务。以下工具使用包内逐字保留的 Issue32 publisher、其原共享锁和原 Issue30 guard；Stage 增量另由本包 guard 验证。它保留当前 manager/history 根，生成不可改写的发布计划和 prepared receipt。原 publisher 的常量、原运维源码不需要在 Mac 手工修改。

先生成计划并完成只读预检：

```sh
R4_PREP_SHA=$("$R4_PYTHON" -B -c 'import hashlib,sys; from pathlib import Path; print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())' "$R4_WORK/integration/PREPARATION_RECEIPT.json")

"$R4_PYTHON" -B "$R4_PACKAGE/tools/stage_api_release.py" prepare \
  --preparation-receipt "$R4_WORK/integration/PREPARATION_RECEIPT.json" \
  --expected-preparation-sha256 "$R4_PREP_SHA" \
  --publisher-path "$R4_PACKAGE/test_support/publication/api_only_cutover_issue32_r4.py" \
  --stage-guard-path "$R4_PACKAGE/release_tools/after/ops/api_release_integration.py" \
  > "$R4_WORK/publication_prepare_result.json"
cat "$R4_WORK/publication_prepare_result.json"

R4_PLAN_PATH=$("$R4_PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan_path"])' "$R4_WORK/publication_prepare_result.json")
R4_PLAN_SHA=$("$R4_PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan_sha256"])' "$R4_WORK/publication_prepare_result.json")
R4_BEFORE_PLIST_SHA=$("$R4_PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["current_plist_sha256"])' "$R4_WORK/publication_prepare_result.json")
R4_STAGED_PLIST_SHA=$("$R4_PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["staged_plist_sha256"])' "$R4_WORK/publication_prepare_result.json")

"$R4_PYTHON" -B "$R4_PACKAGE/tools/stage_api_release.py" plan \
  --plan-path "$R4_PLAN_PATH" --expected-plan-sha256 "$R4_PLAN_SHA"
"$R4_PYTHON" -B "$R4_PACKAGE/tools/stage_api_release.py" preflight \
  --plan-path "$R4_PLAN_PATH" --expected-plan-sha256 "$R4_PLAN_SHA"
```

只有 `STAGE_PUBLICATION_PREPARED_NOT_DEPLOYED` 和 `STAGE_PUBLICATION_PREFLIGHT_PASS` 才继续。此时已经有具体可审阅的 candidate、当前/目标 plist SHA、真实研究绑定、历史读前像与回滚备份合同。下面的 `execute` 才会通过既有 API-only 发布链切换 8873；调度器不参与本次切换。

```sh
"$R4_PYTHON" -B "$R4_PACKAGE/tools/stage_api_release.py" execute \
  --plan-path "$R4_PLAN_PATH" --expected-plan-sha256 "$R4_PLAN_SHA" \
  --confirmation SWITCH_API_ONLY_TO_STAGE_RESEARCH_R4_20261009 \
  --expected-current-sha256 "$R4_BEFORE_PLIST_SHA" \
  --expected-staged-sha256 "$R4_STAGED_PLIST_SHA" \
  > "$R4_WORK/publication_execute_result.json"
R4_EXECUTE_EXIT=$?
cat "$R4_WORK/publication_execute_result.json"
test "$R4_EXECUTE_EXIT" -eq 0
```

成功必须是 `STAGE_API_SWITCHED_AND_READBACK_VERIFIED`，并保留输出中的 `receipt_path`、**文件字节 SHA** `receipt_sha256` 和 `runtime_verification`。工具限时等待 API 就绪，核验加载身份、完整 plist SHA、研究两市场与统一列表、原 selection 证据、静态字节和既有历史语义；HTTP 核验不等于浏览器验收，继续第 7 步。

失败会非零退出。发生切换动作后的错误将尝试原发布器的恢复流程；`recovery_status=ROLLED_BACK_TO_PREIMAGE` 表示已恢复前像，不能记作发布成功。若为 `ROLLBACK_INCOMPLETE`，输出包含回执路径、SHA 与当前指针观测值；保留原 plan/备份/回执，使用下列续跑入口。未知来源的当前指针、篡改的回执或不匹配 SHA 会拒绝恢复，不能改常量或跳过 guard。

需要主动回滚，或继续一次未完成恢复时，使用最近一次操作结果：初次为 `publication_execute_result.json`；若已执行过一次回滚，则使用那次 `publication_rollback_result.json`。先把变量指向该文件，再按同一计划执行：

```sh
R4_OPERATION_RESULT="$R4_WORK/publication_execute_result.json"
R4_RECEIPT_PATH=$("$R4_PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["receipt_path"])' "$R4_OPERATION_RESULT")
R4_RECEIPT_SHA=$("$R4_PYTHON" -B -c 'import json,sys; print(json.load(open(sys.argv[1]))["receipt_sha256"])' "$R4_OPERATION_RESULT")
R4_CURRENT_PLIST_SHA=$("$R4_PYTHON" -B -c 'import hashlib,sys; from pathlib import Path; p=Path(sys.argv[1]); print(hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else "ABSENT")' "$R4_API_PLIST")

"$R4_PYTHON" -B "$R4_PACKAGE/tools/stage_api_release.py" rollback \
  --plan-path "$R4_PLAN_PATH" --expected-plan-sha256 "$R4_PLAN_SHA" \
  --receipt-path "$R4_RECEIPT_PATH" --expected-receipt-sha256 "$R4_RECEIPT_SHA" \
  --confirmation ROLLBACK_STAGE_RESEARCH_R4_TO_RECORDED_PREIMAGE \
  --expected-current-sha256 "$R4_CURRENT_PLIST_SHA" \
  > "$R4_WORK/publication_rollback_result.json"
R4_ROLLBACK_EXIT=$?
cat "$R4_WORK/publication_rollback_result.json"
test "$R4_ROLLBACK_EXIT" -eq 0
```

回滚合格状态为 `ROLLED_BACK_TO_PREIMAGE`；核对原 release/PID/CWD 与 8873 恢复。回滚入口使用已签名 prepared 合同与记录的备份，即使候选已损坏也不要求重新通过候选构建。每次操作另建不可覆盖的 operation 目录；若再次续跑，另存终端结果文件，保留每次失败记录。

## 7. 8873 同一 run 终验

切换后用同一路由和 query 在 `127.0.0.1:8873` 重新读 API、强制刷新页面，并把实际 PID/CWD、release id、release manifest SHA、API after SHA、静态 inventory SHA、绑定 SHA、两市场 run/SHA 一起记录。

合格状态是“本次固定 R3 研究结果已被现役 R4 API/UI 读取”；它不等于正式 HK D1、历史资格/PIT 或自然时段已恢复。用户批准的研究模式与 STRICT 状态应各自清楚显示。手工复验继续标记回放，不得标 `NATURAL`。

如果某一步失败，保留命令、具体文件/预期及实际 SHA、完整错误与生成回执。业务代码已经由 Chat 交付，Mac 只回传实际前像/运行证据，不需写新业务逻辑或与另一 Mac 会话协调。

所有步骤保持 `RESEARCH_ONLY=true`，`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
