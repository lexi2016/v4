# R4 当前 Issue32 UI 最小接入

本目录只包含当前已加载 Issue32 UI 的三个精确 preimage、三个 after、最小 patch 和隔离测试。没有更改 R3、现役源码、静态产物、数据、服务、8873 或 Vibe 8910。

## 来源与身份

当前来源根按固定 preflight 记录为：

`/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/candidate/issue32_preselection_api_actual_r4/app`

| 路径 | before SHA-256 | after SHA-256 |
| --- | --- | --- |
| `apps/web/src/App.vue` | `f43bdb2c7214bce09221757eecb75eea9d5e1c746a3213bb53e6d0c84b751d9c` | `8f1c00c4b278fd46736d9176d94752539f46e7c04d38fc13129084e6b9164c0f` |
| `apps/web/src/components/review/StageExecutionEvidencePanel.vue` | `07188178bbcd5ae2b01b9d6c1ef9dffd7b94f1b27f0211501cc2464566c5bc8b` | `eca21b9d5674e3a18b09672c43401164ca356fd84fd6c719c14453c006f0ee5d` |
| `apps/web/src/contracts/runtime.ts` | `9a882a174b433488684b05781ade00beb665706e962f753700960a4250d13419` | `b3d437e906f81d08af045f5b0f3990662c64676572376d42edddaf109f3dd980` |

三个操作都是 `modify`。现有 panel 必须通过其 before SHA 检查，不能按 R3 canonical 的 absent/add 处理。

`App.vue` 从固定仓库树 `137431f5de3917ff4526784351f5638e115061e5` 中的 `handoff/hk-close-hk-calendar-20261007/api/apps/web/src/App.vue` 取得，Git blob SHA-1 为 `779bb1fbfbd7ba13687b9ebaf5cd4cc55f890369`。panel 与 runtime 使用已下载的 R2 before，分别核验 Git blob `73d0f6cc417c153e53c73244758424199e35b639`、`9481e8c0562d96698ca7898d81807dc3e2449263`，并逐项与当前 preflight 的 SHA-256 相同。这里证明仓库字节与固定 Mac 回执记录的 preimage 相同，没有宣称本次直接读取 Mac。

## 变更

完整 `App.vue` 从 120,981 字节增至 123,582 字节。接入复用 R3 的结果绑定规则：当前 date/stage、市场、选股 run、artifact、算法 SHA、原 artifact SHA、完整响应行数必须一致，才显示“已计算”或已验证空结果。身份不一致只改变派生的显示判定，原响应、候选行、状态及安全标记不改写。

只在原 `candidateColumnCountLabel` 和 `timelineStageMarketCount` 的现有历史/加载/失败分支之后加入已绑定结果计数。历史回补优先级、原请求 URL、精确日期/阶段检查、WATCH_ONLY 检查、事件和经理导航保持原样。现有 Stage panel 使用经过当前选择身份校验的证据；加载或身份不符时不显示旧证据。

panel 的 after 与已验收 R3 完全同字节，保留结果/执行证据区别、研究名单原日期与采集时间、缺口、资格/D1限制、owner-history 绑定、回放和自然验收未验证。runtime 保留当前任务状态定义，仅扩充 R3 Stage 类型。

RESEARCH_ONLY=true；production_allowed、buy_gate_updated、orders_sent 全为 false。本批无算法或 STRICT 门禁变更。

## 测试

`evidence/UI_REBASE_RECEIPT.json` 保存机器摘要。完整命令从本目录执行：

```sh
STAGE_UI_RUNTIME='/path/to/existing/installed/apps/web' \
STAGE_UI_CONSUMER_FIXTURE='/path/to/existing/R3-independent-checks/full_chain_fixture/consumer_response.json' \
node --disable-warning=ExperimentalWarning --test tests/*.test.mjs
```

如果将测试迁入统一 R4 包，可另外传 `STAGE_UI_SOURCE_ROOT=<R4包>/after/ui/apps/web/src` 和 `STAGE_UI_BEFORE_SOURCE_ROOT=<R4包>/before/ui/apps/web/src`。fixture 是 R3 原 `run_checks.py` 生成的隔离合成 runner/consumer/projection 输出；`workbench_response.json` 必须与其相邻。不能用实际 Mac PyTDX 验收名称描述该 fixture。

本次 Node 24.19.0；Vue/compiler/server-renderer 3.5.40；Babel parser 7.29.7。先在三个原始 preimage 上运行 70 项，57 个预期断言失败、13 个已有行为通过；写入 after 后全部 70 项通过、零 skip。包括完整 live App 的 25 项、R3 legacy panel 的 23 项、R3 research presentation 的 22 项。

完整 live App 经 Vue compiler 编译并运行真实 setup、模板与事件回调。其他页面组件及复盘 HTTP 客户端是明确的测试替身；SSR 不执行浏览器 mount hooks。全 live 函数除了上述两个显示计数函数逐项保持相同，所有原模板事件属性及任务状态类型前缀保持相同。

原样调用 R3 `tools/prepare_canary.py --inspect-only`：本地精确三个 before 为 `PREFLIGHT_OK`，after 为 `ALREADY_AFTER`；旧 R3 canonical before 被拒绝为 `PREFLIGHT_FAILED`。这些结果检查的是精确三文件的本地 source fixture，完整 Mac source set 的 preflight 仍须由 Mac 对当前加载根运行。

## 交接范围

主交付使用 `after/`、`before/`、`UI_SOURCE_MAP_ENTRIES.json`、`current-live-ui.patch`、`tests/` 与精简 `evidence/`。`preflight_package/` 是本地原 guard 验证用镜像，`intake/` 是下载见证，不需要重复上传。原始 RED 日志含重复断言 HTML；同步时使用 `ui_RED_summary.log` 和 `ui_GREEN_summary.log`。

全 Vite build、完整 live 依赖图、当前 8873 HTTP/browser、发布/切换和自然时段验收均为 NOT_RUN。没有用 canonical 构建替代当前 live bundle，也没有生成或猜测新的 static 文件名。统一 API 普通 date/stage 读路径接入后的响应可直接传入本测试 harness 再做同 run 编译 UI 校验。
