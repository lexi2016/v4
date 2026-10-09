# R3 本地落地与 HTTP/UI 验收回执 · 2026-10-09

## 范围与身份

- GOAL：原样落地 Chat R3 commit `9a0c3f318a438b386d69a8385ce644ea18a31dfb`，验真实 HK PyTDX 研究 canary 与同 run consumer/API/UI；不改业务逻辑，不发布到 8873。
- ZIP：`/Users/lexi/Downloads/v4_stage_r3_delivery.zip`，SHA-256 `8529402f09ce0b01b49633302a6a89a6597f84203d472fac467e4dba3e7711e6`。
- 交付身份：parent `3112c1ee8ed2826c5d77b5d0a4f1e2cd5fc95e45`；prefix `handoff/stage-r2-mac-adaptation-20261009-r3`。包验证 PASS：21 production files、166 offline support files，零失败。
- 唯一工作候选：`candidate/mac_apply_20261009_r3_01`。Stage/API/UI source manifests SHA-256 分别为 `88ca1c64f6e80ec91feff01af2e7e9cf235bb16f91cacff400fede0f56430fa2`、`6c5b8adfe6f74d727e976eb08b0f00c18476938906193973cd8666c55b1aed74`、`a909f85fe7cc778c8f169d03133d1925448b80b1e7c172ed92b226c38a47c5f5`。

## 准备、测试与真实 canary

- Stage、API、UI 副本准备均 PASS，候选源字节与允许的 R3 preimage/after SHA 匹配。Full suite PASS：Stage 148、API 82、adaptation 50、Vue 45、实际 Vue 27，共 352；全部 exit 0，零 skip/failure/error/cancelled/todo。机器结果见 `candidate/mac_apply_20261009_r3_01/independent_checks/RESULTS.json`，SHA-256 `26f6a0c4e68edc2c9b9077e00fd374ad8b8b49f4cadd01dd9ffa9c957641127e`。该套件范围标为 isolated source/fixture tests，不等于部署或自然验收。
- `npm run build` 在候选 `ui_app/apps/web` 成功，Vite 7.3.6，118 modules transformed；构建只写候选 dist。候选 build dist 与 HTTP clone dist 的 tree SHA 均为 `295902655ebcdea4ba59b96f570ae909176e7e554ac9c36fe7165b27a84dfdd1`。原 `api_app/apps/web/dist` 保留，tree SHA `4f4222bd917c90d29bf0d418be8e417e695749056f1d3e7a546f398e984fd4c2`。临时候选 `node_modules` symlink 已移除，canonical 与候选 lockfile 同 SHA `3f0b8425f35a7fdeb13cc0e5422b7814b386a6c7559d0e5c6b2f8340bc01be47`。
- 真实 PyTDX canary 为 `20261009 / STAGE_0930_0935`，`RESEARCH_ROWS_WRITTEN`，HK selection run `run-cfbdc9b36a7308da178d193a`，A run `run-2688466a1ae4464ba7237f0b`；A、HK 各选 10 行。Canary manifest SHA-256 `9b5df949141ed1533cb7a71e2c46bebe341bea663f5f966bda16225754e89857`；consumer readback SHA-256 `39be9293afa847b3357c66f86ff608bbdd2d2162cccd702c171ab5d4f4aabc3b`。
- 同 run API consumer 显示 HK 请求/来源 695/695、quote coverage 1.0、10 selected，selection trio `BOUND_TO_VERIFIED_SELECTION_TRIO`，owner history `OWNER_HISTORY_SHA_BOUND`。状态仍是 `PARTIAL_WITH_ROWS`：A 来源 206/216；HK 参考名单日期 20261008、采集时间 2026-10-09 15:38:41+08:00，`stale_universe=true`，HK Connect membership `CANNOT_CONFIRM`，formal D1/PIT 均 false，显示 `OBSERVATION_UNVERIFIED`。执行未独立验证，自然时段 `false`。RESEARCH_ONLY=true；production_allowed、buy_gate_updated、orders_sent 全为 false。

## 隔离 HTTP 与真实浏览器回读

- 为 HTTP 验证，从 prepared `api_app` 建立 disposable `candidate/api_http_app`；除 `apps/web/dist` 使用上述候选 build 外，clone 与 prepared API 非 dist tree 差异为零。服务只 bind `127.0.0.1:18873`，独立 data root 在 `candidate/api_http_data/data`，实际 PID 37679；浏览器为 Playwright session `r3-http-20261009`，PID 38035。
- API：`GET http://127.0.0.1:18873/api/v3/workbench/stage?date=20261009&stage=STAGE_0930_0935&limit=50` 返回 HTTP 200。嵌套 HK run id 与 canary、consumer readback相同；日期、阶段、trio binding、owner-history binding 和安全 flag 均通过机器断言。
- UI：`http://127.0.0.1:18873/?date=20261009&stage=STAGE_0930_0935` 实际浏览器加载标题 `V3.5`，显示 `本阶段选股结果`、A/HK 各 10 行、A 206/216、HK 695/695、过期名单及资格限制、owner history 已核对、回放/自然时段未验证和全 false 安全 flag。浏览器 Stage API 请求 HTTP 200；console errors/warnings 为 0。24 项机器断言 PASS，见 `evidence/r3_http_20261009/http_ui_verification.json`，SHA-256 `cf9b1ba2a277f4a55025bc05cbc82860d87825a2a96fa3162cf0ff7d143f74b5`。
- 两个临时工具问题均未改候选源码：`cp -a` 的 API clone 保留只读目录模式，首次 dist overlay 遇 `PermissionError`；只在 disposable clone 的 `apps/web` 调整 owner write 位完成 overlay 后恢复原模式。Playwright skill wrapper 因 CRLF 结束符报 `set: pipefail\r: invalid option name`；未改 skill，改用其等价的缓存 `npx --yes --package @playwright/cli playwright-cli` 命令完成回读。
- 页面证据：`evidence/r3_http_20261009/stage_response.json` SHA `d6ff17dff3930f4b52f5d72d80afff7c73f91151a0ea158c220c97c5be954490`；`stage_panel_snapshot.txt` SHA `145fdd5c5aeacbfc745233f9525a56521ff0c2fdbfb3cff70e206c47245d9d08`；`stage_execution_panel.png` SHA `274b3c6bc45fdc161ed4c11eb0dadcba5d458d501bbb0e80cfa133896cc34b74`。请求、console、headers、HTML 与 summary 同目录保存。
- 已通过 Playwright close 关闭 session，并 SIGTERM 结束 PID 37679；随后 `ps` 未见 PID 37679/38035，18873 无 listener。唯一现役 8873 仍由 PID 78617 监听，CWD 为 `V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`；本批未触碰它。

## 独立验收与终态

- 独立 Luna Max Reviewer receipt PASS，状态 `REVIEWED / TESTED / BEHAVIOR_VERIFIED`；receipt `evidence/review/independent_actual_ui_same_run_20261009.json` SHA-256 `4178978125ed28dc802e7ef1ea8972252c94c11cfed8839cc50c5d577c621050`。Reviewer 独立验证 consumer 与实际 UI SSR 同 run；本回执补充真实 loopback HTTP 与浏览器页面路径。
- IMPLEMENTED：R3 候选落地；TESTED：352 与本地 HTTP/UI；REVIEWED、BEHAVIOR_VERIFIED：PASS（见独立 receipt）；API_VERIFIED、UI_VERIFIED：仅隔离候选 loopback；DEPLOYED、INTEGRATED 到 8873：未执行；NATURAL_VERIFIED：false。
- CANNOT_CONFIRM：正式 HK Connect 资格、正式 D1/PIT 与自然运行；动态 external shared-data link 的实际 target/dependency；A-share source completeness。candidate API 与现役 8873 的 source/static 身份不同，本批不替换整份 canonical dist，也不宣称生产/现役验收。

## 本批工作区写入

- 候选 build：`candidate/mac_apply_20261009_r3_01/ui_app/apps/web/dist/`（11 files）：`assets/dailyResearchCommand-BaVMW5CH.js`、`assets/dailyResearchCommand-D7J2FMsY.css`、`assets/main-CbbsTC6a.css`、`assets/main-DU5lGlgQ.js`、`assets/managerSelection-Ccgg8luP.js`、`assets/managerSelection-Yq6F4Lqr.css`、`assets/research_lane-t0CPXntR.js`、`assets/runtime-dom.esm-bundler-DbWIV8fp.js`、`daily-research-command/index.html`、`index.html`、`manager-selection/index.html`。
- 隔离测试 clone/data：`candidate/mac_apply_20261009_r3_01/api_http_app/`、`candidate/mac_apply_20261009_r3_01/api_http_data/`；临时服务与浏览器均已关闭。
- Evidence：`evidence/r3_http_20261009/` 下 10 个 API/UI/browser receipt 文件；工具缓存位于 E 内 `tools/npm-cache/` 与 `tools/playwright-browsers/`。canonical source/config、plist、真实 state、8873 service、Vibe 8910、交易权限均未写入。

## 关键命令

```sh
# Prior R3 suite (exact command; result: 352/352 PASS)
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" -B \
  "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/incoming/stage-r2-mac-adaptation-20261009-r3/tools/run_checks.py" \
  --stage-app "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/stage_app" \
  --ui-runtime "/Users/lexi/Desktop/学习/v4_app/apps/web" \
  --output "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/independent_checks"

# UI build (result: Vite 7.3.6, exit 0)
npm run build

# Real PyTDX research canary (result: RESEARCH_ROWS_WRITTEN; natural_verified=false)
"/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" -B \
  "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/incoming/stage-r2-mac-adaptation-20261009-r3/tools/run_current_research_canary.py" \
  --package "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/incoming/stage-r2-mac-adaptation-20261009-r3" \
  --stage-app "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/stage_app" \
  --config "/Users/lexi/Desktop/学习/agents调试/V4_HK_STAGE_RECOVERY_20261003/issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app/stage_center_tick_config.json" \
  --hk-input "/Users/lexi/Desktop/学习/agents调试/V4_HK_INPUT_RESTORE_20261009/candidate/futu_snapshot_current_20261009T153841+0800" \
  --output-root "/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/research_0935" \
  --stage-id STAGE_0930_0935 --execute

# Isolated HTTP Stage GET and browser UI URL
curl -fsS --max-time 30 -D stage_headers.txt -o stage_response.json \
  'http://127.0.0.1:18873/api/v3/workbench/stage?date=20261009&stage=STAGE_0930_0935&limit=50'
# UI: http://127.0.0.1:18873/?date=20261009&stage=STAGE_0930_0935

# Temporary server was started from candidate/api_http_app, using isolated data/root:
/Users/lexi/Library/Application\ Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python \
  -c 'from pathlib import Path; import uvicorn; from apps.api.v35_api.app import create_app; app = create_app(data_root=Path("/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/api_http_data/data"), stage_center_selection_root=Path("/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/candidate/mac_apply_20261009_r3_01/research_0935/selection/backfill/85e29661ecd848fe9b8344ea59279e86")); uvicorn.run(app, host="127.0.0.1", port=18873, log_config=None)'

# Real browser readback (run in E/tools; console error count 0; then close session)
NPM_CONFIG_CACHE="/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/tools/npm-cache" \
PLAYWRIGHT_BROWSERS_PATH="/Users/lexi/Desktop/学习/agents调试/V4_STAGE_RESEARCH_R3_MAC_20261009/tools/playwright-browsers" \
PLAYWRIGHT_CLI_SESSION="r3-http-20261009" \
npx --yes --package @playwright/cli playwright-cli open \
  'http://127.0.0.1:18873/?date=20261009&stage=STAGE_0930_0935' --headed

# Cleanup and confirmation (browser closed via playwright-cli close)
kill -TERM 37679
ps -p 37679,38035 -o pid=,command= || true
lsof -nP -iTCP:18873 -sTCP:LISTEN || true
lsof -nP -iTCP:8873 -sTCP:LISTEN
```
