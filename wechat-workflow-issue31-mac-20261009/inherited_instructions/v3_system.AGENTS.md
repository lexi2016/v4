# V3 System 项目规则

全局角色与安全规则由 `/Users/lexi/.codex/AGENTS.md` 统一提供。本文件只定义 `/Users/lexi/Desktop/学习/v3_system` 的运行权威、Git 和迁移边界，不重新指定 Writer 或模型角色。

## 当前运行权威

- 在另有明确切流验收前，8873/8771 与时间线运行源码仍以 `30_runtime/` 为权威。
- `apps/`、`services/`、`packages/`、`ops/`、`artifact-index/` 和 `.runtime/` 是目标承载位；目录存在不等于运行时已经切流。
- producer、artifact/manifest、runtime binding、API 与实际页面必须分别验证；上游 `READY` 或 HTTP 200 不证明阶段已端到端可用。
- Windows Task、Mac launchd、端口、页面 URL、正式池、BUY gate 和业务数据路径不得在目录治理或模型研究批次中顺带改变。

## Git 与迁移

- 本目录是 V3 主 Git 仓库；所有命令使用明确的 `git -C /Users/lexi/Desktop/学习/v3_system` 或已验证 linked worktree。
- 修改前区分用户原有 tracked/untracked 文件和本任务文件；禁止无授权 `reset --hard`、`clean`、覆盖式 checkout、全局 stash、删除 worktree或 `worktree prune`。
- linked worktree 迁移后优先使用 `git worktree repair <现存路径>` 修复元数据，不复制或覆盖工作区内容。
- 每批迁移先确认 producer、consumer、运行引用与回滚点，再处理一个路径变量；保留源目标、SHA、验收和回滚证据。
- canonical、shadow、diagnostic 和 replay 必须分离；实验目录不得写 canonical 状态。
- `.runtime/` 只承载可重建本机状态；正式 receipt、ledger 和 manifest 进入各自合同目录。

## 模型与研究

- 算法路线开放；具体模型研究由所在子目录冻结数据、基线、评价、封存集和允许路径。
- 模型训练不得与 V3 运行故障修复、目录迁移或生产门禁调整混在同一写入批次。
- 训练成功、开发期提升或页面可见不等于生产批准或模型突破。

## 交易安全

- 默认保持 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- 目录治理、研究、回测和修复不授权登录交易账户、创建交易上下文、查询账户/持仓/订单或下单。

## 迁移验收入口

- 根目录合同：`migration/contracts/v3-root-layout.json`。
- 只读校验器：`migration/tools/check_v3_root_layout.py`。
- 治理测试：`tests/governance/test_v3_root_layout_contract.py`。
- 迁移未完成时的 `FAIL` 是真实状态，不得放宽合同制造 PASS。

## 专业角色路由

- 运行故障或阶段空池先用 `market-data-lineage-auditor` 追 producer、
  artifact、runtime、API 和页面；数据修复再追加
  `data-remediation-engineer`。
- 跨模块迁移和工作流变更使用 `architect`、`workflow_architect`；
  页面改动追加 `quant_research_workbench_designer`，验收时按需使用
  `website-ux-auditor` 和 `website-visual-reviewer`。
- 模型、D-1 或开盘问题分别路由到 `model_qa_specialist`、
  `d1-pool-reviewer`、`hkconnect-flow-reviewer` 或
  `opening-second-filter-reviewer`。最终仍由 `reviewer` 或
  `risk-committee-reviewer` 独立复核。
