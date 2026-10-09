# 事实、推断与缺口

证据时间：经理 live readback 为 2026-10-09 14:33 +08；Stage 侧以固定 `CURRENT_STATE_RECEIPT` 为准。运行身份会变化，实际实施或首次迁移前必须按 owner 流程重读 plist、PID、manifest、binding、源码 SHA 和静态页面字节。

## 已证事实

- 8873 的 `com.lexi.v35.api-only` PID 78617 指向 `issue32_preselection_api_actual_r4/app`，LaunchAgent 的 app root 与 pinned manifest SHA `16675f...` 相符。同一 app 注册 `/api/v3/manager/stage-selection`、经理 research/workbench routers，并从相同应用树挂 `web/dist`。源码 SHA 和摘录见 `manager_evidence/current_runtime_identity.json`、`manager_evidence/source_extracts_20261009.md`。
- Scheduler 是另一个 LaunchAgent/PID 83677，运行 `issue32-preselection-scheduler-mac-20261009-r1/app`，manifest SHA `6ccaa8...`；其 Python runtime 来自 `20260904...strict-stage-acquisition-v15/runtime`。API 树内 daemon/launcher 文件是保留副本，不是当前 scheduler app 根里的文件。
- Manager binding 不一致：API 侧 disabled C1，SHA `f3b7cb...`、`plan_owner_present=false`；scheduler 侧 enabled R2，SHA `c0fbff...`、`plan_owner_present=false`，其 worker root 为 `manager-us-mapping-daily-20261006-r2/app`。隔离实施不应顺手改写/收敛业务 binding。
- API 和 scheduler 指向同一个 Stage selection state 根；两者配置的研究数据根路径不同，不能把它们当成一个数据底板。Stage selection consumer 是 Manager 的只读边界；state 的 owner 和写入者不变。
- Stage API、经理 API、8873 静态 UI 当前处在同一 API app 发布根。Stage receipt 还确认共享 UI 源文件 `apps/web/src/App.vue`、`apps/web/src/contracts/runtime.ts` 有已有改动，Stage evidence panel 在历史包中缺失，当前页面字节未读回。
- Issue32 `api_only_cutover_issue32_r4.py` 是整 API app / API plist 切换工具，不是 Manager-only 发布工具；其源码没有在本轮执行。Stage scheduler 当前 `not running`, last exit 3；没有证据把该状态归因于 Manager 发布。
- Manager R3 candidate 保留为候选：receipt SHA `30113d...`，writer 结果 `66/0`、`36/0`、`18/0`，review pending、shared release not run。旧 HK suite `12/3` failure 继续记录。此处不重跑业务 suites。
- Stage receipt 显示 Stage 本批没有改源码；6 个运行文件匹配其记录的 before SHA，但部分 canonical 和 UI 历史前像不匹配。Stage 本机 test/build/canary/deploy 均 `NOT_RUN`。
- 五条 shared policy path 的结果是 `PASS_POLICY_ONLY`，没有自动应用，未增加 broad prefix；这不是行为验收或生产授权。

## 推断

- 当前完整 API app 根替换会同时影响 Stage API、经理 API 和 8873 静态 UI，形成发布耦合；仅拆源码目录不会自动拆开共用 state、worker binding、进程、路由和平台静态资源。
- 独立 scheduler app 根和 API app 根分开，但 scheduler 仍绑定 Manager worker，并与 API 共用 Stage selection state。应以 owner、写入方向和各自 manifest/binding 验收，而不是以目录分开作为隔离证明。
- 页面仍应归 8873 平台 owner，单独构建发布；任一 API 模块包不得替换共享 `web/dist`。

这些推断说明边界风险，不证明发生过哪一次覆盖。

## `CANNOT_CONFIRM` / 待现场复验

- 历史 Stage→Manager 或 Manager→Stage 覆盖事故的精确 before/after 和因果链。
- Python 进程内已 import 的模块字节；当前证据只证明 LaunchAgent 配置、PID、cwd、manifest pin 和磁盘源码 SHA。
- 8873 当前真正加载的静态资产字节、stage 页面自然读回和自然时段选股结果。
- Stage 独立 API 候选是否可通过本机测试；Managers R3 是否经独立 review；任何真实 shared-root 发布或用户行为改善。
- 安装时 8874/8875 是否可用，以及完整 role-specific release flow 是否实现。

## 固定安全边界

`RESEARCH_ONLY=true`，`production_allowed=false`，`buy_gate_updated=false`，`orders_sent=false`。包内无交易、生产、改状态或发布动作。Stage 香港日期输入缺失仍按原数据合同处理；模块隔离不得改变 A/HK 分池、算法或权威数据 owner。
