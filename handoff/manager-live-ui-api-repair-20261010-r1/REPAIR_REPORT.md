# V4 Manager 修复候选与验证报告

**结论：已完成可交接的隔离源码候选与定向离线验证；交付状态保持 `PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`。** 本报告不宣称现役故障已修复。需求和历史事实来自 [原问题报告](reference/PROBLEM_REPORT.md) 与 [修复任务](reference/CHAT_REPAIR_REQUEST.md)。最终补丁涉及 7 个产品文件，测试、冻结依赖与日志单独交付。

## 1. 四项问题与当前处理

| 问题 | 本候选的处理 | 离线证据与边界 |
|---|---|---|
| 同一计划随后因 identity 变化拒绝消费 | 在精确 consumed artifact 语义边界排除全局 registry 指纹，保留原始 provenance；贯通 projection、relation、attention 和外层 identity；保持 stale guard | 后端 35 项覆盖 global-only、真实已消费变化、源校验、封存计划读回和差异诊断；没有真实 HTTP/owner 执行 |
| 三路摘要未挂入真实 panel | `catalystObservationPanel.render(value)` 调用已有 daily renderer，使用同一响应的 channel 与日期绑定；摘要紧随计划状态 | 运行真实 mount、API validator 与 renderer；测试 ANNOUNCEMENT/HK_CONNECT/OVERSOLD、缺失/错日/不安全响应及 stale |
| 美股上下两处 scope 易混淆 | 相邻展示“美股评估/完整度”和“每日 US-HK 已审映射（N 项）”；数量来自响应 | 4、7、未知数量均测试；`VALID_EMPTY` 不提升为全市场空结果 |
| 100 行原始观察先于核心结果 | 核心研究结果前置；原 stocks、背景与筛选节点完整放入默认折叠审计区 | 挂载后展开验证全部 100 行及末行原始字段；输入对象与安全字段不变 |

## 2. 历史 stale：能解释到哪一步

原证据记录同一 run `3bc75d1beea24036850b1af0f4d5f395`、产品 SHA `38eaad4b3d8adfd4738fa0bb4e6ef5ab969414447450e485614f384f48aab991` 在紧邻 POST + GET + GET 中为 CURRENT / consumed=true，随后独立 GET 为 STALE_INPUTS_CHANGED / consumed=false。日期、semantic version 和 cutoff 相同，而 saved/current input identity 不同。GET 前后 saved-plan 文件字节不变，说明拒绝消费来自当前输入身份比较，不能以读取改写计划来解释。[来源](reference/PROBLEM_REPORT.md)

原 counterfactual 将 1,970 个 material source refs 的其他字段固定，只替换全局 `manifest_sha256`，projection identity 即变化；40 对已消费 payload/receipt 及对应 manifest entries 仍匹配。这证明 **全局 registry 更新会使未变的已消费材料一起失效** 这一过宽耦合机制。[原根因复核](reference/evidence/root_cause_report_20261010.md)；[原 counterfactual receipt](reference/evidence/global_manifest_identity_counterfactual_receipt.json)

旧 manifest 原始 bytes、后一次完整 GET body 及其他 identity extension 的历史值不齐全，因此无法把那次 live 变化唯一归因到该字段。本次没有新增现场证据，**历史唯一 changed field 继续为 `CANNOT_CONFIRM`**。修复并未绕过 stale、缓存旧 identity 或强制 CURRENT。

## 3. 后端实现与风险控制

新的 `workspace_identity.py` 仅对 `source_refs` / `input_bindings` 中符合完整原 research owner 形状的引用制作语义副本：已校验状态、正确 source ID、绝对 source root、真实日期、精确 payload/receipt 路径、mode/slot、有效 payload/receipt SHA、manifest 路径与安全标记必须一致。原 `payload_sha256` 已来自对应的 exact manifest entry；若另有显式 entry SHA，也必须与 payload 相等。

只在这些合格引用中从语义副本去掉 `manifest_sha256`。其他字段全部保留，原始材料/返回引用仍保留全局 manifest 作为 provenance。缺失、未校验、错误或不安全形状继续包含全局指纹，未获得额外兼容性。原 `source_row`、`original_source_row`、content/body/text 等内容视为不透明原文，里面即使出现 binding 形状也不会被归一化。通用 digest 没有修改，产品 seal 继续覆盖原始完整字节。

该解释贯穿主 projection、relation-material/card 输入与 attention identity。现役 `research_attention.py` 的准确部署 SHA 没有证据，故产品补丁不替换它：先保留原 pure projector 的业务输出；必要时对语义副本再调用同一 projector，只取其 identity。异常向上传播，没有旧 identity 回退。外层公告输入、reviewed announcement、公告产品 SHA、US payload SHA 和通过原 cutoff 校验的 daily mapping 输入仍以原顺序参与身份。

### 新合同、旧计划和诊断

新身份合同为 `CONSUMED_RESEARCH_ARTIFACTS_V1`。版本参与 projection identity，动态读回和定时复用也要求一致。既有封存计划不迁移、不改写、不重新赋身份；它们可能持续不可消费，直到既有 owner 在授权条件下生成新计划。这是兼容性变化，Mac 应保留历史 run 和失败证据。

新 workspace 保存有界组件摘要，最多 32 个组件。`plan_product.input_identity_diagnostics` 返回 UNCHANGED / CHANGED / CANNOT_CONFIRM、原因、saved/current identity 和版本、总变化数及最多 16 条 component + saved/current SHA。比较两个至多 32-key 的有效 map 时，总变化数允许至多 64。前端显示最多 4 个组件名称，完整有界对象保留在原审计入口。缺失、旧版或不一致证据保持 CANNOT_CONFIRM。诊断不参与授权消费，也不包含原始文章或路径。

### 额外计算成本

上一冻结候选（helper SHA `0346db36ff99e4e323e1256854673ff3d4c8c32977b33c700108af914b605525`）在 1,970 个合成 relation cards/source refs、1 个 issuer、3 次重复下，原 attention 中位耗时 **0.364950816 秒**，修复后该阶段 **0.831324223 秒**，增加 **0.466373407 秒**，约 **2.28 倍该阶段成本**。去掉 identity 后返回业务对象相等，输入未被修改，owner reader/network 调用为零。这不是 API 总耗时或现场性能验收；随后最终 helper 仅增加了非法 mode 类型的保守检查；此处保留原测量，没有重跑或声称测过最终 helper。完整 Mac 环境必须记录实际耗时。[测量原始结果](reports/backend.attention_benchmark.json)；[实现与测试报告](reports/backend.RESULTS.md)

## 4. 前端日期和显示行为

每日摘要与 plan status 同屏前置，stale 不遮蔽独立合法的 channel。每路显示状态、数据日、run/owner/product/input identity、候选/待核数量与 gap 摘要；完整 channel 对象仍可展开。响应缺失、错日或安全验证失败时清除旧内容，不沿用另一日数据。

历史公告目录选择使用独立 URL 参数 `analysis_date`，计划仍保留 `announcement_date` / `publication_date` 的显式绑定。空 `analysis_date` 表示自动目录日期；首次挂载支持旧 announcement_date 回退。读取、刷新、重载均有回归覆盖。这个衔接修复避免目录选择在刷新与重载时悄悄改变 workspace 输入日期，不创建新 owner 或新 producer。

上方 US assessment/completeness 与每日已审 mapping 的标签并列。已审数量动态来自 API；未知不会填成 4。全部原始观察只改变显示位置和默认折叠状态，没有删减 producer 或选股输入。[前端实现报告](reports/frontend.report.md)；[独立前端审查](reports/frontend.review.md)

## 5. 实际验证和未执行项

| 验证层 | 实际结果 | 记录 |
|---|---|---|
| 输入包 CRC、文件清单和证据合同 | PASS；85 个 ZIP 成员 | `reports/input_verify_package.log`、`input_check_evidence_contract.log` |
| 原后端固定快照运行最终用例 | 35 项运行、17 个断言失败、0 errors | `reports/backend.final.red.log` |
| 修复后后端，root 独立最终运行 | 35 PASS、0 failures、0 errors | `reports/backend.final.json`、`.log` |
| 包内原前端运行最终 22 项 | 1 PASS / 21 FAIL，无 setup error | `reports/portable/frontend.before.json` |
| 原前端第一轮挂载 RED | 1 PASS / 13 FAIL，无 setup error | `reports/frontend.red.json`、`.log` |
| 日期与组件诊断 follow-up RED | 14 PASS / 6 FAIL，无 setup error | `reports/frontend.followup.red.json`、`.log` |
| 修复后前端，root 独立最终运行 | 22 PASS / 0 FAIL，无 setup error | `reports/frontend.final.json`、`.log` |
| 原正常 npm test 尝试 | exit 254；缺 package.json，suite NOT_RUN | `reports/frontend.full_suite.json`、`.log` |
| 正式完整后端/前端 suite、类型检查和 Vue/Vite build | NOT_RUN | 上传快照不包含完整运行环境 |
| Mac owner、真实 HTTP/API、浏览器视觉/加载 bundle、自然时段 | NOT_RUN | 本任务明确没有现场执行授权或环境 |

后端用临时 JSON 归档运行原 `ResearchArchiveStore.read_exact`、精确 `ResearchLaneSource` 与 `_read_archive`，覆盖 payload/receipt/entry 篡改、missing receipt 和 date mismatch。封存计划测试使用本地文件 transport fixture，但执行真实 `_read_plan`、owner-attempt 校验和 `_readback_plan`。它们是模块/状态转移测试，**不是完整 `_compute_workspace`、真实 HTTP 或实际 owner run**。初始缺依赖 bootstrap 错误另留日志，不计入故障断言复现。

前端运行真实 panel mount 和未改 API validator，只替换 fetch 为合成响应。运行时为 Node 24.19.0 与官方 LinkeDOM 0.18.12，使用记录在案的 select.value / details.open 属性兼容；details toggle 由测试显式触发。它证明 DOM wiring/order/content，不能证明浏览器 layout/paint、原生点击、真实导航或 bundle 身份。迟到响应防护做了静态审查，未专设延迟竞争测试。

两处独立审查边界已补回归：非法 `mode=[]` 在修复前抛出 TypeError，现保留完整指纹；前端 64-total / 16-row 的合法诊断修复前失败，现通过，65-total 仍为 CANNOT_CONFIRM。对应日志为 `reports/backend.red.malformed_mode.log` 和 `reports/frontend.boundary.red.json`。

最终代码的独立整体验查为 **Spec PASS / Code quality APPROVE，无未解决 finding**，对应最终 7 个 runtime 后像和 35/22 用例的加载 SHA；另有 9 项主审窄检查和 4 项最终增量检查。[整体验查报告](reports/integration.review.md)

最终包还通过包内入口重放 before/after、逐文件清单和补丁正反应用检查，详细结果位于 `reports/portable/` 与交付校验命令的实际输出。交付工具与接续说明经独立审查 **APPROVE**；审查发现的应用/回退命令短路问题已修正，失败前像门禁会阻止后续 patch，且在临时目录实测产品字节不变。[交付审查报告](reports/delivery.review.md)

测试模块加载记录保留完整 SHA，测试支持闭包见 `test_support/DEPENDENCY_CLOSURE.json`。

## 6. 源码范围与接续

产品修改仅有：`workspace.py`、`workspace_projection.py`、新增 `workspace_identity.py`，以及 `catalystObservationPanel.ts`、`dailyChannels.ts`、`businessStatus.ts`、`researchAttention.ts`。每个完整前像/后像 SHA 在 [SOURCE_SHA256.json](SOURCE_SHA256.json) 中；API validator、原读取器、owner、scheduler、金融门禁和产物数据不在 runtime.patch 内。

按 [Mac 接续说明](MAC_ACCEPTANCE.md) 在新建的完整候选目录做前像校验和 patch --check，再应用并校验后像。源码不匹配时停止应用，不能把旧 canonical 或测试支持依赖充作现役文件。回退同样限于新的隔离候选或既有独立发布流程。

## 7. 数据和历史证据边界仍然保留

- corrected V3.5 root 下 exact `20261008` HK panel **存在**。未证项是该日 security-master exact entry、目标 Connect membership authority，以及六个 session 的 volume unit/scale 和 provider finality；不能重新写成“panel 缺失”。
- oversold 的 693 行待核与 695 gaps 不会因页面和 identity 修复消失。没有补抓、回填或附加未经证明的单位。
- target `20261008` / publication `20261007` 的 613 Reader + 613 独立 Reviewer + 33 selected + VERIFIED import 是旧日可复用 owner 子链；target `20261009` / publication `20261008` 的最新解析导入仍 NOT_RUN。
- 每日 US VALID_EMPTY 只覆盖已审的 4 项关系。另一 isolated run 的 external_finance READY 但无 market_snapshot 是独立来源缺口，不能替代此 scope 或证明全市场完整。
- 用户报告的 `2026-09-30` 独立成功 receipt 本次未定位，保持 CANNOT_CONFIRM，不据此否定用户报告。

上述事实来自 [原问题报告](reference/PROBLEM_REPORT.md)。整个交付继续保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
