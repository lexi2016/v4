# V4 经理工作台 UI/API 修复候选 · 2026-10-10 R1

**交付状态：`PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`。**

本包包含实际源码修改、完整 before/after、可应用的最小补丁、定向回归、独立审查和 Mac 验收交接。修改基于上传的固定 fused 源码及按 SHA 恢复的缺失文件；没有访问 Mac、运行中的 8873、真实 owner state，也没有部署修复。目标/选股日为 **20261009**，公告 publication 日为 **20261008**。原问题证据的回看日为 20261010，不是自然时段验收。

固定约束保持为：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 交付内容与阅读顺序

| 路径 | 用途 |
| --- | --- |
| `runtime.patch` | 8 个运行时文件的补丁：7 个修改、1 个新增 |
| `before/`、`after/` | 修改涉及的完整源码，按项目相对路径保存 |
| `SOURCE_SHA256.json` | 每处修改前后完整 SHA256、恢复来源及应用前提 |
| `reference/` | 未修改的原 source reader、existing-material reader、workspace response validator |
| `MAC_ACCEPTANCE.md` | 隔离应用、真实 owner/API/UI 验收条件及回滚步骤 |
| `docs/BACKEND_REPAIR_NOTES.md` | 身份边界、响应字段、后端测试及限制 |
| `docs/FRONTEND_REPAIR_NOTES.md` | 页面接线、范围文案、浏览器测试及限制 |
| `docs/INDEPENDENT_REVIEW.md` | 独立审查结论及修正过的发现 |
| `tests/`、`test_support/`、`tools/` | 可复跑的隔离回归、固定依赖源码和只读校验工具 |
| `evidence/`、`provenance/` | 命令结果、合成截图、诊断示例和来源记录 |
| `FILE_MANIFEST.json` | 除清单自身以外的包内文件字节数与 SHA256 |

截图和新增诊断示例均明确属于 **synthetic / offline**。原 15 MB live GET body、1,970 条完整 material 数组和 40 对原始 owner artifact bytes 不在上传材料中，也不在本修复包中。

## 1. 同一计划为什么从 CURRENT 变成 stale

原 receipt 能证明：紧邻的 POST + GET + GET 是同一 run/product/date 且为 CURRENT；稍后的独立 GET 仍是同一 run/product/date，但 saved/current input identity 已不同。既有 guard 据此返回 `STALE_INPUTS_CHANGED / consumed=false`，没有证据表明那次 GET 改写了保存计划。

已证实的过宽耦合机制是：每条已消费 V3.5 material 的 source ref 都携带整个 registry 的 `manifest_sha256`，旧身份计算又把这个全局指纹当作 material 语义输入。因此，即使所消费的 payload/receipt 不变，只要清单的其他部分更新，计划身份仍可能变化。上传的历史 counterfactual receipt 记录 1,970 个 refs 和 40 对匹配的 payload/receipt 元数据；本次又在合成 registry 上用实际模块复现并回归这个机制。

**不能据此认定它是历史 live mismatch 的唯一原因。** 旧 manifest bytes、后一次完整 GET body 及所有当时的身份扩展没有保存，具体 live changed field 继续为 `CANNOT_CONFIRM`。本次测试没有假装重现缺失的 1,970 条原始输入。

### 候选如何收窄身份边界

新增 `workspace_identity.py` 只在 `source_refs` / `input_bindings` 中，识别完整、已验证、只读且 research-only 的 `V35_RESEARCH_DATA_ROOT` artifact binding。识别还要求有效 source root/date、slot/mode、精确 payload/receipt 路径和 SHA 字段。只有此类 binding 内的全局 `manifest_sha256` 从**用于哈希的副本**中省略。

以下内容继续影响语义身份：source/root/date/path，已消费 manifest entry/payload SHA，receipt SHA，其他绑定字段，语义 `available_at` 和内容。`source_row`、`original_source_row`、`content` 中同名字段不被递归剥离。未知、不完整、不合法、其他 owner/HK/Stage 的绑定保留原有指纹影响。原始来源对象及全局 manifest SHA 继续作为 provenance 保留；原 reader 的 artifact 验证逻辑未改。

修正覆盖实际 projection、外层 selection/relation 输入、admitted attention-card digest 三处链路，避免只修一层哈希。原 announcement、US payload、Connect scope、cutoff-admitted daily mapping 等身份扩展仍有效。

### 差异诊断与旧计划

新计划保存：

- `input_identity_schema = v4.manager_research.input_identity.v2`；
- `input_identity_components`：各命名 component 的语义 SHA 和原来源引用。

读回增加 `plan_product.input_identity_diagnostics`，输出 `MATCH`、`CHANGED` 或 `CANNOT_CONFIRM`，列明 saved/current identity、变化 component 及其来源。日期和 semantic version 的差异、以及触发 guard 的 cutoff 问题，另列实际比较值；合法的截止时间推进不要求两次 cutoff 字面相等。页面在 stale 状态旁提供摘要及可展开的完整诊断。

保存产品 SHA、安全标记、日期绑定、semantic version、cutoff、同 run owner attempt 等原检查继续生效。缺少新身份组件合同的旧计划保持 stale，并给出 `SAVED_IDENTITY_COMPONENTS_UNAVAILABLE_OWNER_REFRESH_REQUIRED`；GET 不迁移、重写或强制放行旧计划。需要更新时，仍由原 owner 在有效执行上下文中生成新产物，旧 per-run 产物保留。

独立审查还发现旧 `ALREADY_MATERIALIZED` 快捷复用分支可能绕过上述旧计划检查。候选已在 preopen/morning 共用分支补上相同兼容性和 prepared-cutoff 检查，负向旧计划及正向 v2 复用均有回归。没有改 scheduler 文件，也没有执行 scheduler。

## 2. 页面上的三项修正

**接入原有三路结果。** `catalystObservationPanel.render(value)` 现在把同一个已校验 workspace 响应的 `daily_channels` 和 `date_bindings` 交给现有 renderer。三张卡展示状态、计划/选股/公告日期、数据日、owner、run、product/input identity、候选/待核和缺口。未知数量继续显示未知；`CANNOT_CONFIRM` 不变成零候选或已核空集。缺口摘要显示数量和前三项，完整列表保留在详情中。

**明确两种 US 范围。** “美股评估/完整度”说明上层 assessment；“每日 US-HK 已审映射”说明 daily-run 覆盖的已审关系集合。关系数来自响应，没有写死 4。当前历史证据中的 4 项、VALID_EMPTY、0 匹配仍只属于该局部集合，不表示 full-market empty 或完整 US 输入。

**结果优先，原始行保留。** 计划消费状态与输入诊断之后是每日三路结果，再呈现其他研究结果。原始 stocks/background、筛选控件和来源审计放在默认折叠区；所有 100 条合成回归观察完整保留，展开及再次读取均已检查。没有截断、删除 producer 输入或修改选股算法。

## 3. 实际验证与适用范围

| 验证 | 实际结果 | 能证明的范围 |
| --- | --- | --- |
| 原上传包完整性 | 85 个成员 CRC/SHA 与清单匹配；两份问题报告完全一致 | 上传证据没有被本轮改写 |
| 独立 receipt/source 交叉核对 | 44 项断言通过 | 已保存元数据与来源关系一致；不等于重跑 live |
| 后端实际模块回归 | 21 项通过；相同基线 suite 为退出 1、19 个断言失败（含 subcases），无 import/test errors | 语义身份、真实 projection/外层 assembly/readback、旧计划 guard、映射 cutoff 和 attention 变化边界 |
| 前端真实挂载回归 | 23 项通过；最终同套 before 为 23 项预期断言失败。保留初始基线 22 项和后来窄屏 1 项的独立失败记录 | 真实 panel、request/parser/validator、DOM 展示和拒绝路径 |
| 隔离浏览器窄屏 | 670×900 中三路状态可见，原始审计默认折叠 | 合成响应下该组件的布局；不是完整生产页面验收 |
| 独立代码审查 | legacy 快捷复用发现已修正并复测；23 项浏览器用例另加 1 项独立文本注入检查通过，四种窗口尺寸通过 | 被审查的候选字节和所列风险；与实现 suite 的重叠项不重复累计 |
| 补丁往返与源码范围 | 8 处 after 与候选一致；before → after → before 的完整字节匹配，新增文件正确移除 | 临时目录中可应用和可回滚；未向现役源应用 |
| 全仓 Python suite | `python -m pytest -q` 在收集前报 `No module named pytest`，NOT_RUN | 无全仓测试通过结论 |
| 完整前端构建/原工程 suite | NOT_RUN；上传包缺完整工程元数据和依赖锁 | 无 Vite/TypeScript 全量构建通过结论 |
| Mac owner / live API / live UI / 自然时段 | **NOT_RUN** | 无修复后现场成功结论 |

后端环境为 Linux / Python 3.12.14；使用实际源码模块，原 owner-return 边界由明确的合成 fixture 提供。完整 `_compute_workspace` 测试执行实际 projection、Connect gate、event lane、attention、identity assembly 和 sealed readback。缺少存储链的 announcement-owner import 在同一外部边界替换；身份、guard、projection、attention 函数未被 mock，最终测试不使用 AST 摘取。

前端环境为 Node 24 / Playwright / Chromium 153。测试挂载实际组件，并经过真实 workspace fetch/parser/validator；所有 HTTP 响应由隔离路由提供，意外请求被拒绝。TypeScript 用 Node 类型擦除后在 Chromium 执行；这不替代 TypeScript typecheck、Vite 构建或完整 Vue 应用。截图只呈现该组件及最小测试宿主。

重复执行同一组测试属于复核，不累计为更多测试项。原始失败日志、修复后日志、移包后的复跑结果及环境说明均随包保留。

## 4. 源码应用前提

关联 Git 基线为 `lexi2016/v4@c0fc35c7b39502f49e43c2e75139dad7822091cf`。它用于恢复固定文件；本候选的实际 before 是上传 fused snapshot 加准确恢复的缺失文件，并非把该 Git commit 的整个目录宣称为当前 live 源码。

上传材料物理缺少的 `research_lane_source.py`、`existing_materials.py`、`workspace_projection.py` 已按报告中的 SHA 找回。`existing_materials.py` 使用匹配的 **API 版本**，没有替换成不同的 canonical 版本。前两份保持原字节。

另有 `research_attention.py` 的两行修改：其 before 来自固定提交的 API 文件，SHA256 为 `3f5385ed850b0336cb85ad85cac3aeab44d2908620c636a4cfc19f5fdf3619aa`。**报告未独立固定这份文件的 live 字节**，所以这是明确的应用前提。如果 Mac 文件不匹配，须先核对差异和 owner 版本，不能盲目覆盖。

`SOURCE_SHA256.json` 列出所有 8 处完整前后 SHA，以及两个原 reader 和 workspace validator 的不变前提。`test_support/` 仅是隔离测试依赖，不能复制到现役项目作为整套替代源。

## 5. 尚未闭合的数据事实

| 项目 | 本轮保留的结论 |
| --- | --- |
| ANNOUNCEMENT，target 20261009 / publication 20261008 | `CANNOT_CONFIRM`；目标日解析导入仍 NOT_RUN |
| 前一日公告链 | 613 Reader / 613 独立 Reviewer / 33 selected / VERIFIED import 属于 target 20261008 / publication 20261007；不能挪用为本目标日结果 |
| HK_CONNECT | `CANNOT_CONFIRM`；target-date V2 membership authority 未闭合 |
| V3.5 panel | 修正 root 后 exact 20261008 panel **存在**；不能继续说 panel 缺失 |
| security master | exact 20261008 entry、对应 pointer/universe 缺口仍在 |
| OVERSOLD | `PARTIAL`；693 行待核、695 个 screen gaps；六个 session 为 10/02、05、06、07、08、09 |
| 六日行情语义 | volume unit/scale `NOT_PROVEN`；provider finality `NOT_ATTESTED_BY_PROVIDER` |
| US daily mapping | 4 项已审关系、VALID_EMPTY、0 匹配是有限 scope；不等于全市场覆盖 |
| 另一条 corrected isolated owner run | external_finance payload READY 但无 market_snapshot；不能覆盖部署 run 的 daily mapping 事实 |
| 用户报告的 2026-09-30 独立成功 | 本次材料未找到独立 receipt，继续 `CANNOT_CONFIRM`；不否定用户报告 |
| 浏览器实际 bundle / 修复后现场行为 | 实际加载 SHA、owner/API/UI、自然时段验证仍未完成 |

这些缺口不会因 UI 接线或身份边界修正自动消失。本包未采集、回填、导入市场或公告数据，未增加第二 producer，也未改变 Stage、BUY、Vibe8910 或 HK/US 池合同。

## 6. 本地复核入口

从解压后的包根目录运行：

```bash
python3 -B tools/verify_delivery.py --patch-roundtrip
python3 -B tools/run_backend_tests.py --source-image after
```

前端运行依赖、固定版本、环境变量和 portable/native browser 入口见 `docs/FRONTEND_REPAIR_NOTES.md`。Linux 安装所列测试依赖后，入口为 `FRONTEND_PORTABLE_CHROMIUM=1 node tools/run_frontend_tests.mjs after`。无需为这些离线测试启动 8873 或任何 owner。后端 `--source-image before`、前端位置参数 `before` 用于查看同一套回归在原版上的失败，预期非零退出。

真实项目的只读 SHA 前提检查、隔离目录中的应用/回滚，以及交给 Mac 执行者的验收记录要求见 `MAC_ACCEPTANCE.md`。

## Git 交接

遵循固定项目 AGENTS 中已确认的每轮同步规则，本轮使用新的独立工作分支 `chat/manager-live-ui-api-20261010-163151`，交接目录 `handoff/manager-live-ui-api-repair-20261010-163151`。同步只包含必要候选源码、测试、来源清单和精简结果；不合并、不部署、不改变既有分支。最终远端读回结果在 `GIT_SYNC_RECEIPT.json` 和随附交付报告中记录；该 receipt 在远端核验之后生成，因此不在它所描述的 commit 内。
