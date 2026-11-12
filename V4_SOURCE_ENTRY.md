# V4 完整源码审查入口 · 2026-11-12

本分支供 Chat 对照当前 V4 源码细化整改。统一候选源码在仓库根；当前 Main、API、Stage 的实际源码及其独立 shared-package 依赖，经逐文件 SHA 核对后映射在 [SOURCE_MATRIX.json](docs/source-baseline-20261112/SOURCE_MATRIX.json)。它包含不同运行角色的源码变体，不代表一个 commit 已能直接替换或部署三个角色。

先读 [本轮整改方案](docs/plans/v4-stock-selection-integration-20261112.md)，再按涉及的角色定位代码。当前业务边界、来源和 BUY 安全继续适用：`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 源码组成

- 基线为 canonical `b4719b0f36fcaec237f34c88aaab56a6996a0296`，通过三方合入最新修复链 `13d0523fc3311ae370b7441747de9c2b5b2a49e3`，不合并 GitHub main，不部署。
- canonical 的 19 个待提交源码/测试全部有逐项落点，见 [PENDING_SOURCE_MATRIX.json](docs/source-baseline-20261112/PENDING_SOURCE_MATRIX.json)：14 个原字节保留，4 个按仓库规则仅规范为 LF；1 个 ownership 测试因合入已接受的 D12 源码而更新严格的固定字节/SHA 期望。原工作区原样保留。
- 11 个当日有效分支的代码差异逐项核对，见 [BRANCH_COVERAGE.json](docs/source-baseline-20261112/BRANCH_COVERAGE.json)。已汇入同一修复链或内容一致的代码直接复用；新增月度研究工具进入根路径。Stage 的专用修复保留准确变体，避免替换 canonical 中不同的历史 HK 处理。
- 历史/试验分支不机械合并。旧分支和其原始证据保持原样；它们不是本次当前源码覆盖的目标。

## 当前角色的准确代码

| 角色 | 选定源码/测试/依赖文件 | 排除的非源码条目 |
| --- | ---: | ---: |
| Main | 888 | 151 |
| API | 1174 | 190 |
| Stage | 870 | 135 |
| SharedPackage | 66 | 36 |
| APIResearchUI（独立研究工作台） | 52 | 438 |
| StageRepairBranch（仅专用差异） | 3 | 0 |

矩阵入口按角色引用 `docs/source-baseline-20261112/roles/` 下的小文件，便于 GitHub/Chat 分次读取，每个文件均小于 1 MiB。每个条目包含原逻辑路径、SHA-256、仓库实际路径和差异分类。与根源码完全一致的内容直接引用根路径，其余仅保存一次必要源码字节，共 1029 个唯一内容文件、22,343,975 字节。文件存于 `docs/source-baseline-20261112/overlays/`，按 SHA 命名，通过矩阵定位；这不是额外 producer 或运行面板。

[差异统计](docs/source-baseline-20261112/DIFFERENCE_SUMMARY.json)按角色引用计数：1341 个同根路径字节一致、234 个与其他根路径字节一致、56 个仅行尾不同、1019 个同路径源码变体、403 个角色专用路径。后两类保持独立，没有推定其业务语义等价。不同角色可重复引用同一内容，故这些计数不能当作独立文件数相加。

只核文件/SHA可运行：

```sh
python3 docs/source-baseline-20261112/materialize_sources.py
```

要阅读某个角色的原目录结构，在仓库外选择一个尚不存在的目录：

```sh
python3 docs/source-baseline-20261112/materialize_sources.py --role API --out /tmp/v4-api-review-source
```

此命令只重建选定审查源码，不提供账户、认证、行情、研究返回、环境、完整 owner 配置或生成的构建物，不启动任何服务。`StageRepairBranch` 只含窄差异；实际 Stage 以 `Stage` 映射为准。`SharedPackage` 是 Main/Stage 的外部导入依赖，单独重建查看。

## 已验证与边界

针对性后端检查有效结果为 247 passed、2 skipped；前端候选 48 项测试、类型检查、构建通过；工作台跳转 4 项 Node 测试通过。1432 份唯一 Python 源码编译检查、38 份独立研究 UI JS/MJS 语法检查通过；选定来源与实际 manifest 源码 SHA 无漂移。初次后端检查的失败及临时路径/旧全局 pytest 清理错误保留在本地证据，后续仅重查失败项，见 [VALIDATION.json](docs/source-baseline-20261112/VALIDATION.json)。

为核当前 API 前端的可编辑源码，用 API 矩阵重建源码并构建，生成 `assets/main-DCRf2b-t.js`，SHA-256 为 `6cc9739e0a88c618c7ee412162a09cab1dda070b57ff4a2b6a6f4c87f5f8a675`，与本轮观测的实际运行 bundle 一致。当前 `App.vue` 对应 manifest 的 `daily_market_chain`，`AShareTop200Panel.vue` 对应 `home_top200_daily_fix`；旧的嵌套 uncommitted 来源已被这些完整源码覆盖。这只证明该 JS 构建产物字节一致，不是三角色部署认证。

未部署、未启停服务/任务、未训练或采集、未更改交易门禁；未重新认证生产语义、PIT 或自然时段结果。现役角色与根候选路径的兼容/部署等价状态为 `CANNOT_CONFIRM`。独立 Reviewer 和最终远端 commit/可读性回执由主控记录；本文件不自授最终验收。

[排除范围](docs/source-baseline-20261112/EXCLUSIONS.json)涵盖凭据、账户/持仓、原始行情/研究数据、缓存、日志、dist、依赖安装目录和历史备份。两份旧源码保留为当前回归测试必需的确定性 oracle，原有未使用的备份只从本隔离候选移除，未改原工作区或旧分支。
