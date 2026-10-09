# 阶段选股页面最小修复候选

本子包让页面直接说明各市场是否已有选股结果、取得多少行情、缺口多少，再分别说明回执声明、原执行方历史记录与自然时段验收。最终组件测试 **23/23 通过**，独立测试 **25/25 通过**；这是针对历史前像的源码候选，当前实际页面及静态资源身份尚未取得，未部署、未执行整应用构建或浏览器验收。

## 来源与适用范围

三个前像取自固定提交 [`28ab2d35020adf031f10f38c1040514fc81b6d66`](https://github.com/lexi2016/v4/tree/28ab2d35020adf031f10f38c1040514fc81b6d66/handoff/v4-running-source-20261005/api/apps/web/src) 下的 `handoff/v4-running-source-20261005/api/apps/web/src/`，已核 Git blob、字节数及 SHA256。它们的角色是 **10 月 5 日历史 API/UI 参考**，并不证明当前服务加载了这些文件。来源及完整 SHA 在 `SOURCE_BASELINE.json`、`SOURCE_CHANGES.json`。

这个历史 `App.vue` 在收到 `execution_evidence` 时已经隐藏旧版提示，但交接现场仍出现旧提示。现有证据支持继续核对当前源码、构建产物、静态资源入口与浏览器实际加载版本；仅凭历史源码不能确定是哪一层加载了旧资源。应用前必须满足 `CONDITIONAL_APPLICATION.md` 的精确前像条件，不能直接用历史完整 `App.vue` 覆盖不同版本的现役文件。

## 页面行为

| 输入及证据条件 | 主界面显示 |
|---|---|
| A 股产物已核实，选择 10、行情 205、请求 216 | `A股`、`已计算 10 只`、`行情 205 / 216 只，缺 11 只`，计数来源为选股产物 |
| 产物已核实，但本阶段运行回执缺失 | 仍显示已有结果；运行记录独立标为未记录或待核对 |
| HK 无已核结果，回执明确停在预选输入层 | `预选池未就绪，未进入算法`；行情未知保留未知 |
| 已核实空结果且选择数为真实 0 | `已保存空结果（0 只）`；不会当作缺失 |
| 任一计数为空、负数、小数、非有限数或布尔值 | 对应计数为未知，不补成 0 |
| 行情数大于请求数，或声明缺口与差值冲突 | `行情计数待核对` |
| `selection_results` 顶层存在，但某市场摘要缺失、为空或不允许确认 | 该市场结果待核对，不从旧回执升级成已计算 |
| 旧接口完全不含 `selection_results`，且市场引用为 `BOUND_TO_VERIFIED_SELECTION` | 可显示已核选择数；行情明确标为 `回执记录计数` |
| 旧接口声明有数量，但选择引用未绑定 | 结果待核对；不会把声明数量当作已核结果 |
| 已有 HK 真结果，同时当前回执又报预选阻断 | 保留已有结果，另写明当前回执的预选阻断 |
| 选择产物与运行记录身份冲突 | 保留独立核实的结果，同时明确显示身份冲突 |

“运行方式（回执声明）”“原执行方历史记录”“记录时间”“自然时段验收”分别列出。`NATURAL`、`DUE`、owner 历史 SHA 相符或页面展示结果，均不会使自然验收变为通过。当前 API reader 的认证范围明确不证明自然运行，因此页面保留“自然时段验收：尚未验证”。只有 owner 历史已绑定且记录时间状态为 `OWNER_WRITE_CLOCK_RECORDED` 时才展示该回执的 `recorded_at`；没有旧时间就保留未记录，不按当前时间、阶段时间或运行模式推测。

技术字段完整保留在默认折叠的“查看运行与来源详情”内。`runner_invoked_at` 与来源字段保留在详情中，不与记录时间混同。`STAGE_1545_1555` 只显示 HK 市场。

## 修改量

- `StageExecutionEvidencePanel.vue`：使用既有组件呈现上述结果和证据，未创建新页面。
- `contracts/runtime.ts`：新增 9 行可选接口字段；去掉新增段后，旧文件逐字节保持原样。
- `App.vue`：仅替换一处旧提示文字。后像严格等于前像的一次字符串替换，挂载条件、日期、阶段、按钮与处理逻辑均保持原字节。

`StageSummaryPanel.vue`、选股算法、采集、池准备与执行入口都不在本子包修改范围。补丁为 `runtime_ui_presentation.patch`，完整前后像在 `before/`、`after/`。`evidence/PATCH_ROUNDTRIP.json` 记录了本地 `git apply --check`、应用、逆向检查、逆向恢复均为 0，并逐个核对三个文件与后像/前像完全一致。

## 验证与复现

环境是 **Node 24.19.0、Vue 3.5.13、@vue/compiler-sfc 3.5.13、@vue/server-renderer 3.5.13**。测试使用真实 Vue SFC 编译器、真实 SSR 渲染；测试辅助代码只适配编译产物的静态 import，没有替换组件业务逻辑。断言针对 `<details>` 之外的可见文字，旧组件定位也支持其既有标题结构。

在本目录执行：

```bash
node run_tests.mjs --phase before --out /absolute/new/evidence/before --runtime /absolute/vue/package/root
node run_tests.mjs --phase after --out /absolute/new/evidence/after --runtime /absolute/vue/package/root
```

`--runtime` 所指 package root 需能解析上述三个依赖；当前工作区默认是相邻的 `../ui_runtime`。`--out` 必须是不存在的新目录。包装器先核三个输入文件 SHA，再记录命令、测试运行时间、Node/依赖版本、源码身份、完整 TAP、stderr 和真实编译输出。记录中的时间只属于测试进程，不是业务运行或回执时间。前像命令预期退出 1，后像预期退出 0。

最终 23 项相同测试：前像 **22 FAIL / 1 PASS**（`evidence/final-baseline-red/`），后像 **23 PASS / 0 FAIL**（`evidence/review-p2-green/`）。独立审查探针位于相邻 `../ui_review/`，最终 **25 PASS / 0 FAIL**，并重新跑过作者的 23 项。

独立审查曾发现 1 个 P2：新版摘要 map 缺市场键时错误退回旧 bound 回执。先保存原候选与 **21 PASS / 2 FAIL** 反例，再把兼容识别收紧为“整个顶层字段不存在时才走旧协议”，最终绿灯；原候选、失败日志与修正后证据均保留。初次测试辅助代码曾有 import 别名改写语法错误，修复辅助代码后才开始有效 RED/GREEN；原错误在 `harness_import_failure.log`，没有把它记作产品失败证据。

Node 的 `stripTypeScriptTypes` 会打印 ExperimentalWarning，完整日志中保留。此结果不等于完整 App 构建、TypeScript 全项目检查、浏览器视觉验收、当前静态资源已更新或自然阶段恢复。本子包没有重建缺失行情/资格主表，也没有改真实业务数据或服务。

`RESULTS.json` 是最终结果索引；初始 `red.log`、`green.log` 及早期包装器回跑记录只用于保留演进证据，不能代替最终结果索引。
