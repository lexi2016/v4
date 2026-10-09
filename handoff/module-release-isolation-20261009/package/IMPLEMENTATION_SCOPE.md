# 实施范围与逐文件计划

## GOAL

按唯一 architect 的 DESIGN_ONLY 决定，为 Stage API 和 Manager API 建立彼此独立的受限运行/发布角色，并由稳定 8873 平台按固定路由分流；保留用户入口、算法、研究数据/state owner、安全位与业务 contracts。当前批次只交问题包，不实施。

## 目标边界

- 8873 仍是唯一浏览器入口、静态资源 owner 和 gateway；页面 URL 不变。Stage/Manager 页面源码合并到平台单独发布，不随任一 API module release 覆盖；本方案不引入微前端。
- Stage API 目标 loopback `127.0.0.1:8874` / `com.lexi.v4.stage-api`；Manager API 目标 loopback `127.0.0.1:8875` / `com.lexi.v4.manager-api`。端口需首次安装时重新检查，不能以旧空闲观察强占。
- 每个 API 独立 plist、service label、release root、manifest、binding、锁和角色内 rollback。平台 gateway 保持原 label/root，具有自己的锁和 dispatcher 兼容 rollback。
- 原共享 Stage selection state、研究数据 roots、算法、A/HK 边界、Manager consumer 与 Manager binding 身份不迁移。Stage 生产原 Stage selection；Manager 只能通过现有只读 consumer 读取。
- 模块 app 启动不可重复初始化完整平台副作用；不重复启动 scheduler、producer 或后台写任务。

## Architect 提出的最小目标路径

以下为 architect 冻结的唯一实现 owner 计划路径清单。它们是计划路径，实施前需在当前 canonical 源树确认存在状态及真实 owner；本问题包未创建或更改这些业务文件。`source_manifest.json` 与 `source_snapshot/` 提供实施参考的精确 preimage；固定 Git remote/ref 尚不可确认。

| 路径 | 计划 |
|---|---|
| `apps/api/v35_api/module_proxy.py` | 新增固定 loopback gateway proxy；固定方法/路径白名单、错误语义、timeout 和 header/body 传递合同。 |
| `deployment/api_module_contracts.json` | 新增不可伪造角色表、模块路由合同和所需 SHA pin。 |
| `apps/api/v35_api/app.py` | 最小路由分流集成，保持 gateway 默认行为和静态平台 owner。 |
| `apps/api/v35_api/run.py` | 明确 gateway/stage/manager role 启动合同，拒绝错 role 路由/静态请求。 |
| `ops/api_release_integration.py` | 在受控发布链新增固定角色绑定、独立锁和 rollback 身份；不原地改写冻结的 ISSUE30 guard 快照。 |
| `ops/build_release_candidate.py` | 限定 role profile 和 release manifest。 |
| `ops/release_candidate_sources.py` | 限定候选 source closure，拒绝跨角色路径。 |
| `ops/prepare_api_only_cutover.py` | 在现有受控流程内产出 role-specific activation；不启用整包/任意路径覆盖。 |
| `deployment/com.lexi.v4.stage-api.plist` | 新增 Stage 角色 LaunchAgent。 |
| `deployment/com.lexi.v4.manager-api.plist` | 新增 Manager 角色 LaunchAgent。 |

`apps/api/v35_api/module_proxy.py` 和 `deployment/api_module_contracts.json` 在 architect 原始设计时的 preimage 状态为 `ABSENT`。当前这些路径已有并行实施写入，因此本包将其列为 `PARALLEL_IMPLEMENTATION_IN_PROGRESS/NOT_BASELINE`，不收录当前字节，也不把本包当作并行派工。由唯一实现 owner 核对实际状态与来源后决定如何纳入实施。

`ops/api_release_integration.py` 当前实际 guard 来源于 `V4_ISSUE30_MAC_20261008/package/after/ops/api_release_integration.py`；它和 `V4_ISSUE32_MAC_20261009/tools/api_only_cutover_issue32_r4.py` 都是已冻结版本。ISSUE32 工具硬绑 8873、API-only label/root 和共享锁；不能只换 plist/端口复用。Chat 应基于真实当前代码提交可审查的最小 role 化差异/新候选，明确以后 canonical 落点，并沿原 CAS、前后像、非 delta 保护、锁和回滚流程实现；不得新增平行发布器或通用覆盖开关。

## 改动外路径

- canonical/current API release、运行 plist/LaunchAgents、共享 state/研究数据、`web/dist`、Stage receipt 对应已有 UI 和 Stage canonical 改动、经理 R3 candidate、Vibe 8910、凭证和全局 hooks。
- 本问题包阶段没有业务、服务、绑定、state 或 GitHub 写入。后续候选实现也不代表部署授权。
