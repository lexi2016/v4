# Phase 5 运行时治理 Gate 证据（20260801）

文件名保留历史 `blocker` 标识以维持既有引用；当前权威结论已经提升为 `PASS`。Phase 5 完成了图谱任务登记、请求级 `target_date`、单 dispatcher 并发占位、入口 owner 分类和唯一启用的 hourly research runner。未修改旧 V3、Windows Tasks、生产服务或交易边界。

## 机器结论

- 审计合同：`contracts/migration/phase5_runtime_governance_audit_v1.json`
- 审计 semantic hash：`40a46fd9125282a9eafa31561582f5d823c1c0aa8b96e9e28b707dc0532305d7`
- 审计 raw SHA-256：`46d05af1a8231102d4d028d300a6379678212ded10feb8499886066f99a22cb8`
- runtime catalog raw SHA-256：`71b87fe166095dcf3daa991cffb0e9c7459edc11f5d3c81289a5ea81844ee1db`
- 冻结身份：35 个 canonical task、34 个 timeline node、36 个实际 Windows Task、33 个 launcher、69 个 runtime inventory record、90 个 entrypoint。
- task：1 个 exact workload；其余 34 个按用户批准登记为 `disabled / CANNOT_CONFIRM`，不可执行且安全标志全为 false。
- entrypoint：2 个 exact、66 个关联已批准登记、22 个 graph-backed owner-only；`unresolved=0`、`unexplained=0`。12 个独立 ops CLI 仍保持 inventory `REWRITE / PENDING`，没有被冒充为 workload 或已迁移记录。
- runner：唯一启用的 `hourly_research` module 与参数合同可运行；`blocking_gaps=[]`。

## Hourly research 生产器边界

- 权威依据为 `research_desk_graph_contract_v1` 冻结的 hourly orchestrator、源集合、去重字段、时区和 `RESEARCH_ONLY` 约束。
- runner 只读首次取得的冻结 bytes，以 SHA-256 标识输入；不依赖或写入旧 V3，不调用 8771，不执行真实采集。
- 输入必须显式声明相同 `hourly_slot`；`generated_at`、`published_at`、事件、首次发现和最后检查时间不得晚于请求时隙。
- artifact 与 receipt 按 `LIVE|REPLAY|BACKFILL / date / slot` 隔离且不可变；只有 LIVE 更新 latest。
- 全新旧时隙 LIVE 请求在写入前拒绝；内容相同的历史中断工件可以补齐 receipt/manifest，但不得倒退 latest。
- 缺少默认冻结输入时 CLI 返回类型化 `NOT_MATERIALIZED`；未产生业务 artifact。

## 已验证

- 全量 Python：`305 passed, 1 skipped`。skip 为 Windows 临时 symlink 创建权限，不是断言失败。
- Phase 5/runtime/research 聚焦组合：`80 passed`。
- Reviewer 最终独立回归：hourly runner + archive `25 passed`，`P1=0 / P2=0 / P3=0`。
- 审计 builder 重建结果等于提交工件，自哈希匹配，严格 catalog 快照与 raw SHA 绑定。
- 两进程 dispatcher 仍严格为一个 `DRY_RUN_SELECTED`、一个 `CONCURRENCY_SKIPPED`。
- 前端文件在本切片未改变；Phase 5C 冻结结果仍为 Vue `24 passed`、typecheck PASS、build PASS。当前重跑因本地 `node_modules` 顶层链接缺失未形成新结果，不覆盖冻结证据。

## 状态与安全边界

- Phase 5：`IMPLEMENTED / TESTED / INTEGRATED / PASS`，`phase5_complete=true`。
- `DEPLOYED=false`、`UI_VERIFIED=false`、`business_parity_verified=false`。
- 未执行真实业务 runner，未创建 live/replay/backfill 业务数据，未修改 Windows Tasks。
- `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- 旧 V3 全程只读；用户未跟踪方案文档 SHA-256 仍为 `08f3cdf3273074c19b73cb5874b687c78b3b8603d5656413de5ada7a236e7369`。
- 模型分工：Codex/Sol 为主控与唯一正式写入者；Explorer/Reviewer 只读；确定性 Python 负责哈希、计数和测试裁决。
- 下一阶段为 Phase 6 单变量生产级工程优化；生产接管和 Windows Task 切换仍必须等待 Phase 8 五日双跑及用户最终 `GO`。
