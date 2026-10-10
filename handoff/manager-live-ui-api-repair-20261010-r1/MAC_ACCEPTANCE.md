# Mac 接续与验收说明

## 当前边界

本次交付状态为 `PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`。仅完成隔离源码候选、离线合成回归和代码审查。本文件是后续 Mac 验收操作说明，不表示本轮已经在 Mac 执行，也不自动授权部署、访问现役 8873、owner capture/import、行情回填、改日程或改金融门禁。

固定前像来自上传的问题包与三份按问题报告 SHA 找回的源码。不要把 GitHub 分支根、旧 canonical 源码或某个旧 API 副本直接当作现役前像。精确校验以 `SOURCE_SHA256.json` 为准。

## 1. 包内复现

在解压目录执行，结果写入独立临时目录：

```bash
python3 tools/verify_delivery.py &&
python3 tools/run_offline_tests.py --side after --report-dir /tmp/v4-manager-live-ui-api-repair-r1
```

后端使用 Python 标准库 `unittest`。前端离线 DOM runner 需要支持 `node:module.stripTypeScriptTypes` 与 `registerHooks` 的 Node 运行时；本轮实际使用 Node `24.19.0`。它不需要安装 Vitest，也不安装任何生产依赖。

这条命令只生成临时测试源码目录，使用包内合成输入和测试支持依赖。它不触发本机 owner，不访问真实行情或现役 API。前端结果是 DOM integration，不能代替 Vue/Vite 正式构建和真实浏览器验收。

需复现旧页面的失败时：

```bash
python3 tools/run_offline_tests.py --side before --suite frontend --report-dir /tmp/v4-manager-live-ui-api-repair-r1-before
```

旧版命令应非零退出；具体逐项结果以该次报告为准。本轮包内同一最终用例重放：旧前端为 1 PASS / 21 FAIL、无 setup error；旧后端为 35 项运行、17 个断言失败、0 errors。更早的缺依赖 bootstrap 错误另留日志，不计作故障断言复现。

## 2. 在新的完整候选源码副本应用

先通过本机既有发布流程建立新的完整候选 app 副本。不得覆盖现役 app、旧失败候选或历史运行。下面的路径由执行者填写为这个新副本，而非生产目录：

```bash
repair_dir="/absolute/path/to/V4_MANAGER_LIVE_UI_API_REPAIR_20261010_R1"
candidate_app="/absolute/path/to/new-isolated-candidate/app"
python3 "$repair_dir/tools/verify_source_gate.py" --app-root "$candidate_app" --side before &&
git -C "$candidate_app" apply --check "$repair_dir/runtime.patch" &&
git -C "$candidate_app" apply "$repair_dir/runtime.patch" &&
python3 "$repair_dir/tools/verify_source_gate.py" --app-root "$candidate_app" --side after
```

任何前像 SHA、必要原读取器 SHA 或新增文件存在性检查不符，先记录实际差异并停止应用。不要刷新不相关 pins、跳过 SHA 检查或用 `after/` 整目录覆盖 app。`after/` 只含本次修改的完整文件和新模块，不是完整运行目录。

前端测试文件单独放在 `tests/`，不属于 `runtime.patch`；不会改现役原有测试或 API validator。`test_support/` 也不属于产品补丁，不要将其中的旧版本支持文件复制进发布源码。

## 3. 独立本机验收

在 Mac 完整项目与新候选中分别记录解释器、依赖锁文件和目标源码 SHA，并运行原有后端、前端测试以及正式 Vue/Vite 构建。原有 API 字段/安全校验不得删减。检查新 bundle 确实含三路摘要挂载，并将构建 bundle SHA 与浏览器实际加载资源 SHA 对齐。

后续获得独立 owner/API/UI 执行授权后，按下面的验收矩阵取证。不要用本包合成数据替代真实结果，不要为测试而改写历史产物：

| 验收场景 | 必须记录/观察 |
|---|---|
| 新 identity 合同下的同一 owner 计划连续两次 GET | 同一 run/product/date、相同相关输入时消费语义一致；saved plan 字节不被 GET 改写。 |
| 隔离复制上的无关 registry entry 改变 | 已消费 payload、receipt、entry、日期及内容均未变；projection、研究关系、attention 与外层计划身份保持一致。 |
| 隔离复制上的已消费输入改变 | payload/receipt、语义 available_at 或内容改变时 stale 或原校验拒绝；不允许强制 CURRENT。 |
| 有组件证据的新计划变旧 | `plan_product.input_identity_diagnostics` 给出有 saved/current SHA 的变化组件；页面显示摘要，完整有界证据保留在响应中。 |
| 旧计划缺少组件证据 | 明确 `CANNOT_CONFIRM`，不猜测历史 changed field，不自动改写或升级旧计划。 |
| 页面目标 `20261009` / publication `20261008` | 计划消费状态和三路摘要前置；ANNOUNCEMENT/HK_CONNECT/OVERSOLD 的状态、数据日、run/product/source、候选/待核/gap 与同一响应一致。 |
| stale 与来源缺口 | 摘要仍可见，保留 `CANNOT_CONFIRM`、`PARTIAL` 和 gap；不得将数据缺口展示为零候选的成功运行。 |
| 历史公告日期选择 | `analysis_date` 只控制历史目录；计划 `announcement_date`/`publication_date` 绑定保留。读取、刷新和页面重载后各自选择一致。 |
| US scope | 上方为评估/完整度，下方为每日已审 US-HK 范围；真实 4 项时显示 4，不固定写死，不提升为全市场空结果。 |
| 原始观察 | 默认折叠在核心结果后；展开可见原有全部 rows 和末行内容，不改变 producer/选股输入集合。 |
| 金融边界 | `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`。 |

新 identity 合同会使旧合同计划继续不可消费，直到既有 owner 在被授权条件下生成一个新的计划。保留旧 run 和失败证据；不要原地重封旧计划。

包内只证明 registry 指纹过宽耦合这一 contributor。真实历史 live mismatch 的唯一原因、browser-loaded bundle 身份以及自然时段运行仍需各自闭环。额外 attention 语义投影的本机耗时也应记录；本包性能数字只代表离线合成场景。

## 4. 回退

若仅在新隔离候选应用而未切换服务，停止采用该候选即可，现役无须回退。保留候选目录与日志用于复核。

需要在仍保持本次后像字节的新候选上撤销代码时：

```bash
python3 "$repair_dir/tools/verify_source_gate.py" --app-root "$candidate_app" --side after &&
git -C "$candidate_app" apply --reverse --check "$repair_dir/runtime.patch" &&
git -C "$candidate_app" apply --reverse "$repair_dir/runtime.patch" &&
python3 "$repair_dir/tools/verify_source_gate.py" --app-root "$candidate_app" --side before
```

以后若另行授权过部署，服务回滚沿本机既有发布流程切回此前冻结 release；不要用反向 patch 直接修改正在运行的目录。计划数据、owner 产物和业务 state 均不属于本补丁的正向或反向操作。
