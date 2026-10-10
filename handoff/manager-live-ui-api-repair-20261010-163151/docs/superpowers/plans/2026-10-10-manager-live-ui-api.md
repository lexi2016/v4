# V4 经理工作台 UI/API 修复实施计划

> **For agentic workers:** Use superpowers:systematic-debugging, test-driven-development, and dispatching-parallel-agents for the independent backend and frontend tasks. Root integrates and performs fresh independent review. Steps use checkbox syntax for tracking.

**Goal:** 在固定部署源码上修复已证实的语义身份过宽耦合和页面接线缺陷，交付可落地候选与回归证据。

**Architecture:** 保留现有 owner、消费者、研究门禁和三路结果合同。仅从语义身份中剥离已验证 consumed-artifact 绑定内的全局 registry provenance，保存可定位的身份组成；前端使用同一已校验 workspace 响应展示现有三路结果。

**Tech Stack:** Python 3 标准库；现有 TypeScript DOM 组件；Node 24 与离线 Chromium/Playwright 回归。

**Spec:** 上传包 `PROBLEM_REPORT.md`、`CHAT_REPAIR_REQUEST.md`，完整内容原样保留；固定关联源码提交 `c0fc35c7b39502f49e43c2e75139dad7822091cf`。

## Global Constraints

- 目标日 `20261009`，公告 publication 日 `20261008`；回看/人工执行日 `20261010`。
- `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- 不访问真实 8873、不执行 Mac owner、不采集或回填市场数据、不改运行状态、服务或调度、不部署。
- 不创建第二 producer，不改 Stage、BUY、Vibe8910、选股规则或 HK/US 池合同。
- 真实 live changed field、真实加载 bundle、真实 owner/API/UI 与自然时段修复验收继续 `CANNOT_CONFIRM`；候选交付 `PROPOSAL_ONLY / LIVE_API_UI_NOT_RUN`。
- 固定上传源码不可改写；所有修改在独立 candidate 副本中。保留旧计划，身份格式变更不得将旧计划强制升级为 CURRENT。

## Review Focus

- 同名 `manifest_sha256` 出现在业务正文、HK资格或不完整来源绑定时，不能误删其语义影响。
- 全局 registry 变化必须同时穿过 projection 和外层研究关系 identity，不得只修一个 hash 入口。
- 输入身份相同而日期、cutoff、semantic version 或 owner attempt 不合法时，仍拒绝消费，并准确说明原因。
- 原始观察和待核行数大于首屏容量时，展开区仍能查看完整集合；折叠不改变 producer 输入。
- 三路数据日、run、product、safety 字段不合格时，前端保留拒绝状态；未知数量不得变成零，四项关系不得写死或被解读为全市场。

## Task 1: 固定证据和补齐源码

**Files:** 只读 `input_snapshot/package/`；新增 `recovery_sources/RECOVERY_MANIFEST.json` 与逐 blob 源码。

- [x] 校验 ZIP CRC、全部成员/清单 SHA、独立 receipt 关系及独立报告一致性。
- [x] 从固定 Git 提交恢复缺失的三份源码，核对 Git blob 和报告 SHA，拒绝错误的 canonical 变体。
- [x] 记录补齐依赖的真实来源、范围和无法证明的现场事实。

## Task 2: consumed-artifact 语义身份与 readback

**Files:** `v4/manager_research/workspace_projection.py`、`workspace.py`，必要时新增单一职责的身份工具模块；后端定向测试。

**Interfaces:** 保留 `build_workspace`、`_readback_plan` 与 `plan_product.status/consumed/run_id/sha256`；新增 workspace 身份组成和 `plan_product.input_identity_diagnostics`。诊断提供状态、saved/current hash、changed_components 和来源，格式与前端交接。

- [x] 写并运行原版失败用例：仅全局清单改变导致 projection/outer identity 和同 run readback 改变。
- [x] 对明确 verified V35 artifact binding 做窄范围语义规范化，保留 provenance 原件与其他身份扩展。
- [x] 写并运行 payload/receipt/available_at/source content/date/cutoff/safety/legacy negative regressions。
- [x] 保留 state guard；为真实变动保存 source-backed component 差异，旧证据不足时输出 CANNOT_CONFIRM。
- [x] 运行修复后测试，保存命令、stdout/stderr、退出码，标清实际模块与边界测试覆盖。

## Task 3: 页面接线和范围说明

**Files:** `apps/web/src/manager-selection/catalystObservationPanel.ts`、`dailyChannels.ts`、`businessStatus.ts`、`researchAttention.ts`；离线真实挂载测试。

**Interfaces:** 从同一个已验证 `ManagerWorkspace` 读取 `daily_channels`、日期绑定、plan_product 诊断和原 US coverage。保留 `apps/web/src/api/managerWorkspace.ts` 完整验证器。

- [x] 用真实 mounted panel 证明三路摘要缺失、研究结果落后于 raw rows、US scope 文案不清。
- [x] 接入现有 renderer，前置计划状态和三路结果，展示明确的状态、日期、run/product、candidate/pending、gap。
- [x] 区分 US 关系评估/完整度与每日已审映射；数量来自实际 response，不写死。
- [x] 原始观察移入默认折叠的完整审计区，保持所有行可展开。
- [x] 验证未知/已核空集/有结果、日期错配、safety 异常、stale/current、动态关系数量、完整展开和纯文本渲染。

## Task 4: 独立审查与交付

**Files:** `runtime.patch`、`before/`、`after/`、`SOURCE_SHA256.json`、测试/结果、`README.md`、`MAC_ACCEPTANCE.md`、回滚说明。

- [x] 独立复核两条修改链以及共同响应合同；发现问题后按失败用例修复。
- [x] 重放正向与反向 patch，验证修改字节、原验证器和保护路径未变。
- [x] 交付隔离落地/验收命令；生产行为与自然时段验证明确 NOT_RUN，不执行部署。
- [ ] 保存新修复包；按固定项目 AGENTS 授权将必要源码、测试和精简结果同步到独立 GitHub 工作分支并读回。

## Execution Rulings

- 已有任务明确授权代码提案与测试，直接执行；不为可逆实现选择另行请求确认。
- 本任务从 ZIP 固定快照开始，未改活动仓库；以独立 candidate 目录及逐文件所有权隔离代替不存在的仓库 worktree。
- 测试环境为 Linux；缺失的框架不能冒充已安装。使用可复现的标准库/离线浏览器测试，完整项目套件无法运行时如实记录阻断。
- 后端报告内投影 SHA 引用与最终包内投影不同：保留原证据，记录这一引用漂移，不重写原报告以伪造一致。
