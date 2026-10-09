# 首次实现/迁移前的现场确认项

这些是安装或实现期要从当前 owner/配置核对的事实，不改变 architect 已冻结的产品边界。发现与冻结方案冲突时先交主控裁决，不自行扩范围。

1. **端口与 label**：安装时确认 `127.0.0.1:8874` 和 `:8875` 可用；确认没有已有服务占用且 launchd label 唯一。端口冲突不能静默换成任意值。
2. **真实 source owner**：对照当前 canonical repo、ISSUE30 受保护 release guard 和 ISSUE32 cutover 的实际字节；确定新 role-aware candidate 的 canonical 落点与来源 SHA。不要原地写冻结 snapshot，也不要仅凭路径名推断当前 source。
3. **完整角色清单**：把 `ROUTE_CONTRACT.md` 与当前 app/router 注册逐项对比；核实 Stage router 的所有实际方法/路径、Manager 静态路径优先于 `/{target_trade_date}`，未知 API 和平台其它既有 routes 的处理不变。
4. **启动依赖与副作用**：实际启动 Stage/Manager role 时确认不会加载或启动 scheduler、producer、后台写任务。仅凭模块入口的 role 参数不构成证明。
5. **数据与 binding owner**：原 Stage selection/read roots 和 Manager research roots 原样继承；确认 read/write 方向。API C1 disabled 与 scheduler R2 enabled binding 不得因隔离补丁被改写；`plan_owner` 缺失问题走单独 owner task。
6. **角色 rollback 和首次迁移回退**：实现后为 each role 预先冻结 rollback manifest、gateway compatible version 和完整迁移失败恢复步骤。不得用当前整包工具假装 manager-only 发布。
7. **自然验证范围**：工程验收不能替代自然运行、Stage 选股结果、Manager 日常计划 owner 或香港真实日期数据检查；按现有业务 gate 单独记录。

## 本次包的来源闭环状态

- `source_manifest.json` 和 `source_snapshot/` 收录 20 个精确源码/配置原始字节及 SHA-256、文件大小、Git blob SHA-1；固定 remote/ref 为 `CANNOT_CONFIRM`。
- `deployment/com.lexi.v4.manager-api.plist` 与 `deployment/com.lexi.v4.stage-api.plist` 当前 canonical preimage 为 `ABSENT`，已在 manifest 明确记录。
- `apps/api/v35_api/module_proxy.py` 与 `deployment/api_module_contracts.json` 的设计前状态为 `ABSENT`；当前并行实施字节标记为 `PARALLEL_IMPLEMENTATION_IN_PROGRESS/NOT_BASELINE`，不进入快照或 ZIP。
- 初次独立包审查仍保留 `../review/` 的 FAIL receipt；增量快照只修复其指出的 source-preimage 可移植性缺口，必须由独立 Reviewer 重新检查，不能将 Writer verifier 结果称为 `REVIEWED: PASS`。
