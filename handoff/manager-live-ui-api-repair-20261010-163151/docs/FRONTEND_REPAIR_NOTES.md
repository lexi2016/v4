# 前端修复候选与离线挂载回归

**状态：PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN。** 四处前端修改基于上传的固定 fused 源码。本说明中的浏览器结果、候选股票、owner 名称、run 和 SHA 均属于合成离线测试；没有新增真实市场、owner 或部署验收证据。

## 1. 已定位的问题与最小修改

原 `dailyChannels.ts` 已有 renderer，`api/managerWorkspace.ts` 已接收并校验 `daily_channels`，但 `catalystObservationPanel.render(value)` 没有导入或调用 renderer。缺失的是实际 panel 的接线，与计划是否 stale 无关。另两处问题分别是 US assessment 与 daily mapping 的标签范围不明确，以及完整股票原始观察排在研究结果之前。

| 生产文件（相对项目根） | 修改及结果 |
| --- | --- |
| `apps/web/src/manager-selection/catalystObservationPanel.ts` | 调用 `renderDailyChannels(host, value.daily_channels, value.date_bindings)`，使用同一个通过现有 API validator 的响应。计划消费状态、stale 输入差异及三路结果在前；原 `stocks/background` 与筛选控件整体保留在默认折叠的原始观察审计区。再次读取重置折叠状态，但不丢失原始行。 |
| `apps/web/src/manager-selection/dailyChannels.ts` | 显示三路实际状态、日期绑定、数据日、owner、run、product/input identity、候选/待核及缺口。未知数量不变成零。缺口摘要显示数量及前三项，全部缺口、source refs 和完整 channel 在展开 JSON 中保留。卡片最小宽度调整为 200px，使 670px 宽测试宿主中三路状态都可见。 |
| `apps/web/src/manager-selection/businessStatus.ts` | 相邻标明“美股评估/完整度”和“每日 US-HK 已审映射（N 项）”。N 来自 `daily_run.coverage.reviewed_us_symbol_count`；缺失则数量未知。明确局部 `VALID_EMPTY` 不等于全市场空集，也不代表上层输入完整。 |
| `apps/web/src/manager-selection/researchAttention.ts` | 下方 daily mapping 使用相同实际 reviewed count；去掉文案中写死的 4/33，保留 `VALID_EMPTY` 与有限已审范围。 |

计划 `STALE_INPUTS_CHANGED` 旁展示原响应的 `consumed` 和有支持证据的变化组件，完整 `plan_product.input_identity_diagnostics` 可展开查看。最终合成例使用后端实际合同中的 `input_identity_schema = v4.manager_research.input_identity.v2` 与 `projection.materials` 组件名。没有支持的变化组件时显示 `CANNOT_CONFIRM`，没有强制 CURRENT 或重新计算身份。输入派生文本继续通过现有 DOM 文本写入方式渲染。

`api/managerWorkspace.ts` 全文件字节保持一致；`dailyChannels.ts` 从文件开头到 `const element =` 前的 13,755 字节验证逻辑保持一致。日期、run、产品/来源 SHA、安全标记、研究用途及拒绝规则没有被旧版 validator 替换。

## 2. 实际测试范围与结果

测试在最小宿主中导入并执行真实 `mountCatalystObservations`，通过实际 workspace request/fetch、JSON parser 和 validator，再检查 DOM、展开行为、刷新及错误清理。TypeScript 仅用 Node `stripTypeScriptTypes` 擦除类型后交给真实 Chromium 执行，相关业务函数没有用 stub 或手写 DOM 代替。测试浏览器的每个页面请求由 `https://fixture.invalid` 路由提供；任何未处理或外部请求会被拒绝并使测试失败。无关的原公告 side-read 路由明确返回合成 503。

| 证据 | 退出码与计数 | 含义 |
| --- | --- | --- |
| `evidence/frontend/red-baseline-22.log` | 1；0 pass / 22 fail | 初始 22 项 TDD 测试在原固定源码上均因预期 UI 断言失败；不是浏览器基础设施错误。 |
| `evidence/frontend/red-narrow-1.log` | 1；0 pass / 1 fail | 后增 670×900 用例在布局调整前失败，三路状态均不在首屏内。它是独立的中间阶段记录，不与初始 22 项混作一次执行。 |
| `evidence/frontend/red-packaged-before-23.log` | 1；0 pass / 23 fail | 最终相同 23 项测试通过移包 runner 在 `before/` 上再次确认预期回归失败。 |
| `evidence/frontend/green-after-23.log` | 0；23 pass / 0 fail | 移包后的 `after/`，带可选本地 CJK 字体；同时保存两张合成截图。 |
| `evidence/frontend/green-after-no-font-23.log` | 0；23 pass / 0 fail | 按最终 dependency lock 独立安装后，未设置可选字体，23 项仍通过。 |
| `evidence/frontend/project-suite-not-run.log` | 254；未运行项目 suite | `npm test --prefix candidate/apps/web` 在读取缺失的 `package.json` 时 ENOENT。不能宣称原项目 full suite 或构建通过。 |

所有完整 23 项执行均无 skipped/cancelled。重复执行不累计成更多测试项。最终 suite 包含：

- stale 与 CURRENT 两种计划下的实际三卡挂载；READY、READY_EMPTY、PARTIAL、CANNOT_CONFIRM 的区分；候选、零值、未知值、run、product/source identity 和完整诊断。
- 670×900 首屏三路状态可见，以及 1600×1200 初始桌面视口的摘要位置。
- reviewed count 为 4、7、null 时，上下两处标签范围相符，assessment 与 daily mapping 相邻且独立，不写死四项或宣称 full-market。
- 100 条原始股票观察的顺序、默认折叠、全部 key、最后一行完整 JSON，以及再次读取后仍完整保留。
- 日期变更后使用新响应日期；一次 refresh POST 直接更新计划和 daily 卡片，不额外 GET。
- 12 个真实 validator 负例：workspace 目标日、计划绑定、三路日期绑定、计划 run、source SHA、research-only、production、BUY gate、orders 和 stale-plan 消费引用。既验证原错误码，也验证实际 panel 清空先前候选并显示三路未知状态。
- 缺少 daily/date bindings 的兼容响应，以及没有支持证据的 stale 输入诊断。

## 3. 可复跑入口与固定依赖

下列命令从**解压后的修复包根目录**运行。测试 runner 只把 `test_support/frontend/src` 与选定的四个 `before/after` 文件组装进临时目录，结束时清理临时源码及默认浏览器缓存。无需启动任何服务。

已执行环境：Linux、Node **v24.19.0**、Playwright **1.62.1**、`@sparticuz/chromium` **153.0.0**，实际浏览器版本 **153.0.8010.0**。版本及源文件 SHA 也写入 `evidence/frontend/rendered_source_hashes.json`；其中临时绝对路径仅标识当次执行，源文件可由相对 module 名与 SHA 对照。Node 类型擦除会输出 ExperimentalWarning。

### Linux portable Chromium

```bash
npm ci --prefix test_support/frontend --ignore-scripts --no-audit --no-fund
FRONTEND_PORTABLE_CHROMIUM=1 node tools/run_frontend_tests.mjs after
FRONTEND_PORTABLE_CHROMIUM=1 node tools/run_frontend_tests.mjs before
```

`after` 预期退出 0；`before` 预期退出 1，显示原缺陷。依赖安装仅涉及测试包；不要把 `test_support` 当作现役项目的替换源码。包内不附 `node_modules`、浏览器二进制、字体、缓存或应用 state。

portable helper 从固定 npm 包解压 Chromium、SwiftShader 与最小字体归档；使用 `tar-fs` 的 `chown:false`，避免此环境不支持归档 ownership 操作。每个测试独立启动浏览器，避免 single-process shell 在最后一个 context 关闭后的生命周期问题。测试没有跳过失败、吞掉浏览器错误或解除网络边界。

### Native Playwright Chromium（Mac 等环境的离线测试替代方式）

```bash
npm ci --prefix test_support/frontend --omit=optional --ignore-scripts --no-audit --no-fund
node test_support/frontend/node_modules/playwright/cli.js install chromium
FRONTEND_PORTABLE_CHROMIUM=0 node tools/run_frontend_tests.mjs after
```

这是供后续执行者选择的测试浏览器入口，本轮未在 Mac 执行，也不构成 owner/live API/UI 验收。真实应用构建与 owner 验收条件另见 `MAC_ACCEPTANCE.md`。

### 可选的中文截图字体

普通测试不需要额外字体。为得到本包中的可读中文截图，本轮只在隔离测试目录安装 `@fontsource/noto-sans-sc@5.3.0`；此字体没有加入必需依赖或交付二进制。

```bash
npm install --prefix /tmp/manager-regression-fonts --ignore-scripts --no-audit --no-fund --save-exact @fontsource/noto-sans-sc@5.3.0
FRONTEND_PORTABLE_CHROMIUM=1 \
FRONTEND_CJK_FONT_ROOT=/tmp/manager-regression-fonts/node_modules/@fontsource/noto-sans-sc \
FRONTEND_ARTIFACT_DIR=/tmp/manager-regression-screenshots \
node tools/run_frontend_tests.mjs after
```

`FRONTEND_RUNTIME_DEPS` 可指向另一个已按本包 lock 安装的测试依赖前缀；默认是包内 `test_support/frontend`。`FRONTEND_BROWSER_CACHE` 可显式指定测试缓存目录，否则由 runner 创建并删除。`FRONTEND_CJK_FONT_ROOT` 与 `FRONTEND_ARTIFACT_DIR` 都可省略。截图是最小宿主中的实际组件，不包含完整 Vue 页面、部署导航或 browser-loaded bundle 验证。

本轮实际移包命令（从包含 `delivery/` 的工作目录执行）记录在 `evidence/frontend/verification_results.json`。带字体执行使用既有隔离 Chromium 依赖与运行时 Playwright；无字体及 before 执行使用从最终 `package-lock.json` 新装的独立依赖目录，版本一致。

## 4. 文件来源与冻结 SHA

`test_support/frontend/src` 中三份文件直接复制自不可变基线：workspace API validator、announcement observation、announcement analysis。缺少的两份 runtime import 按固定 Git commit `c0fc35c7b39502f49e43c2e75139dad7822091cf` 的具体 blob 只读恢复，完整 provenance 见 `test_support/frontend/SOURCE_PROVENANCE.json`。

| 恢复的测试依赖 | Git blob | SHA256 |
| --- | --- | --- |
| `api/managerAnnouncementAnalysis.ts` | `c69bacde41c0af509be6816d2835eea5111dd021` | `f30ec19c2c5b21f79ecfe3a3a23b1cf9d59bc5f5f48d117c7db4bcce39f3e5b5` |
| `manager-selection/adapters/workspaceDecision.ts` | `0871bfde4fcd9d8917b95006b5f5d743b81c696c` | `4a6aa2c3cd6ef7570008e253732237484b8a5a9821f8c8f095bc5f795fa63c47` |

| 冻结的生产文件 | after SHA256 |
| --- | --- |
| `catalystObservationPanel.ts` | `bff5c7765930651e933658b48bf11728f6f609b7a3b8576432a57123cfb83d50` |
| `dailyChannels.ts` | `c4983a1bb3f23ea4ee3cfc598b805f2dc765a525b263156a4d7f6428767d24c4` |
| `businessStatus.ts` | `1435695fc9a7c209a7e4c2ed215a428931c72c3d3401665bca1484fe75265dfa` |
| `researchAttention.ts` | `6d93d766c93da20130a5f0ac673820e6d27267c563742420ce6fbe2718adf4b6` |

完整前后 SHA、测试文件 SHA，以及两个 validator 不变证明见 `evidence/frontend/source_sha256.json`。API validator SHA 为 `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f`；daily validation 前缀 SHA 为 `21646e72222200d64095fe6f0e7a9116f30a082eedba8c13ef95bb599907df67`。

## 5. 未覆盖的验收与事实边界

原上传快照没有完整 `package.json`、tsconfig、Vite 工程及依赖锁。原 `catalystObservationPanel.runtime.spec.ts` 还依赖 Vitest、`@testing-library/vue` 和一个 Mac 绝对路径下的历史 fixture。因此本轮没有运行原工程 focused/full suite，没有 TypeScript typecheck 或完整应用构建结论，也没有将缺少的 Mac fixture 编造为已验证数据。

本轮 frontend 实作只改变四个展示文件，并在隔离目录写入代码提案与测试证据。真实 owner、8873、市场/公告 capture/import、scheduler、Mac state、BUY/production gate、生产部署均未运行或修改。历史 live mismatch 的唯一 changed field、实际浏览器 bundle SHA、目标日公告/会员资格/六日量纲及 provider finality、full-market US coverage 和自然时段验收仍需按原证据边界标记 `CANNOT_CONFIRM` 或 `NOT_RUN`。前端通过这些回归不能使上述数据缺口变成已完成。
