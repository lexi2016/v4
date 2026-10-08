# 每日三路首屏与日期绑定交接

## 完成范围

候选目录：`/workspace/scratch/a154a3323e32/candidate`。基线为固定提交 `0fd5eb374cb155232ed003d5fc4d0d3594252491` 中交接源码组装的比较前像。此文说明前端实现与隔离验证；整个交付包的状态以 [README](../README.md) 和 [结果记录](../evidence/results.json) 为准。未部署或连接真实 Mac。

仅修改以下 6 个前端文件：

- `apps/web/src/api/managerWorkspace.ts`
- `apps/web/src/manager-selection/catalystObservationPanel.ts`
- `apps/web/src/manager-selection/dailyChannels.ts`（新增）
- `apps/web/src/manager-selection/dailyChannels.spec.ts`（新增）
- `apps/web/src/manager-selection/dailyChannels.runtime.spec.ts`（新增）
- `apps/web/src/manager-selection/dailyChannels.testHelper.ts`（新增；全部为合成测试数据）

没有修改 `businessStatus.ts`、Vue view、Stage、股票排序规则或任何行情 producer。逐文件前后 SHA256 位于 [source_manifest.json](../source_manifest.json)。当前 `businessStatus.ts` 的保留 pin 与组装旧文件不符，见 [实际失败记录](../evidence/preflight_web_snapshot.json)。

## 日期合同

| 绑定 | URL 解析优先级 | 用途 |
| --- | --- | --- |
| 计划日 | 有效 `plan_date` → 既有 `initialDate` | GET 的 `date` 与原计划上下文 |
| 来源/选股日 | 有效 `selection_date` → `date` → `initialDate` | GET 的 `selection_date`，只作来源/选股展示，不重写计划日 |
| 公告日 | 有效 `announcement_date` → `publication_date` → `date` → `initialDate` | GET 的 `announcement_date`，以及原公告 owner 日历日查询 |

两个公告别名同时存在时，明确以有效 `announcement_date` 为准。非法日历日期不能通过 API 合同校验，URL 解析保留既有回退行为。只改变计划日输入会更新 URL 的 `plan_date`，保留其余日期参数。

`requestManagerWorkspace(date, signal, view, bindings?)` 新增第 4 个可选参数 `{selection_date?, announcement_date?}`。前三参数调用与无扩展的旧 payload 继续可用。显式独立日期直接请求绑定 GET；旧 URL 首次返回新扩展但默认绑定不同，仅补一次明确绑定 GET，随后才显示结果。

## 首屏及准入

首屏在旧状态区之前新增公告研究、港股通研究、超跌反弹三块，直接展示股票、原始研究理由、实际数据日、运行编号与状态。所选三个日期单列；`data_date` 保留原 owner 的实际日期，不改贴所选日。原始行顺序原样展示，未重算排序、门槛或候选资格。

新 `daily_channels.v1` 校验包含安全字段、3 个唯一 channel、外层/内层日期、真实日历日、nullable 数量、计数与行数关系、合法股票代码、行状态、数据日期、SHA、显式时区、运行引用及轻量 source pointer。公告行绑定各自已消费产品及其 `evidence_run_id`，支持同一 channel 多产品/多 run。计划运行需同原 `plan_product` 与精确 `workspace_plan_attempt` 一致；owner 的签名/封存准入仍由后端负责。

缺失数量显示“未知”，缺失理由或运行编号显示“未提供/待核”。`CANNOT_CONFIRM` 不得声称 0 个候选；只有原 owner 给出的已核空集才展示候选 0。扩展缺失时新增视图展示三路未核实，旧 workspace 仍能解析。正文、理由、代码和按需展开的诊断 JSON 都通过 `textContent` 写入。

每路保留 `natural_run_verified=false`，不把手工动作标成定时或自然验收。手工生成后，新扩展或独立日期路径通过 canonical GET 读取选择日期；旧无扩展 payload 的成功 POST 保持原有复用合同。公告手工更新后也读回当前绑定的工作台。无轮询、无额外 producer。

既有 sequence、目标日/view 与 AbortController 保护均保留，并补齐旧 URL 绑定 GET 的第二个 await 边界：即使 transport 在取消后迟到 resolve，也进入既有取消/超时处理，不显示迟到股票。

## 验证与限制

| 验证 | 结果 | 日志 |
| --- | --- | --- |
| 首批 red 回归 | 17 failed / 1 passed | [初始失败](../evidence/tests/frontend_red.log) |
| 绑定 GET 取消 red 回归 | 1 failed；复现取消后错误显示 READY | [取消失败](../evidence/tests/frontend_cancel_red.log) |
| 最终新增 Vitest/jsdom | **29 passed** | [最终测试](../evidence/tests/frontend_final.log) |
| 涉及的源码与测试严格 tsc | **PASS** | [严格检查](../evidence/tests/scoped_typescript.log) |
| 旧 panel runtime，候选 | 14 passed / 2 缺夹具失败 | [候选旧测试](../evidence/known_failures/frontend_legacy_candidate.log) |
| 相同旧 panel runtime，独立前像复制 | 14 passed / 同 2 缺夹具失败 | [前像旧测试](../evidence/known_failures/frontend_legacy_baseline.log) |
| 完整 npm typecheck | 5 个既有诊断，与前像日志逐字相同 | [候选](../evidence/known_failures/frontend_typecheck_candidate.log)、[前像](../evidence/known_failures/frontend_typecheck_baseline.log) |
| npm build | 缺入口 `daily-research-command/index.html`，0 modules transformed 时失败 | [构建失败](../evidence/known_failures/frontend_build.log) |
| 已跟踪修改的 git diff --check | PASS | 工具输出 |

新增测试覆盖日期 query、别名冲突、legacy 回退、跨日期响应拒绝、schema/安全字段/数量/run 拒绝、3 路首屏、未知与已核空集区分、null 理由/run、多产品 run、literal HTML 不执行、保留原行序、手工 canonical GET、跨计划日迟到响应、取消绑定 GET。

两项旧测试缺件为 `tests/fixtures/manager_current_observation_20261002/FIXTURE_BINDING.json` 与硬编码 Mac 路径 `EASTMONEY_HK_ANN_20260929/integration/workspace_after.json`。完整 typecheck 缺 `issue8R2.ownerObservations.json` 引出 3 条诊断，另有既有 Vue spec 的 2 条 unused `@ts-expect-error`。没有补造这些原始数据或修改测试掩盖问题。

独立复核者另外用实际 Python owner 输出的 5 种合成完整 workspace 校验 TS API：缺公告、已选公告、NOT_ASSESSED 公告、成交量未证实的待核 HK02、盘后已完成面板，均通过其检查，见 [独立审查报告](../evidence/independent_review.md)。

没有获取真实浏览器/Mac 截图，也没有自然时段实际执行证据。jsdom 断言仅证明合成 DOM 形状与请求/显示行为；不能代替真实 owner/scheduler/UI 的现场验收。

## 严格 scoped tsc 精确复现命令

工作目录：`candidate/apps/web`。使用冻结 lock 安装的 `node_modules`，没有临时 tsconfig，也不读取仓库 tsconfig；显式指定全部检查文件和 compiler options。

```sh
./node_modules/.bin/tsc --noEmit --target ES2022 --module ESNext --moduleResolution Bundler --strict --skipLibCheck --types vitest/globals src/api/managerWorkspace.ts src/manager-selection/catalystObservationPanel.ts src/manager-selection/dailyChannels.ts src/manager-selection/dailyChannels.spec.ts src/manager-selection/dailyChannels.runtime.spec.ts src/manager-selection/dailyChannels.testHelper.ts
```

最终同命令执行退出码为 0，输出保存于 [scoped_typescript.log](../evidence/tests/scoped_typescript.log)，成功时输出为空；退出码另记在 [results.json](../evidence/results.json)。
