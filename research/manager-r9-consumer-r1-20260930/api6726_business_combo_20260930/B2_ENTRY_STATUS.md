# B2：已查到的真实入口与一次最小缺口

## 已取得，不再索取

API integration commit `6726a3dcd853246734486dc0a38fb3b5b41230f1` 给出两文件精确 diff、writer/reviewer回执。结合R3B原件可重建 workspace 35c9292d… 与 autorun e785ae1d…；完整SHA匹配。e785 中原 preopen 函数主体保留，新增 morning 函数与其依赖。不能为旧 runner 回退到 ec257948。

统一交接 `bdc95a3f9d6d0313baeff2bf727ea82d122dc820` 的 `source/canonical/` 已存在以下真实字节：

| 相对 app 路径 | 已上传 Git blob | 本轮读到的行为 |
|---|---|---|
| ops/run_manager_announcement_cycle.py | 2aa7c784a216c59ff991e28a87d4b7e96c3b0edc | main 中 plan_target 非空即调用 request_bound_plan_cycle 并 return；下方才是公告采集。不是旧8851的先本地plan后采集结构。 |
| v4/manager_research/plan_owner_dispatch.py | 0c6d30891bc345aa2893b1f2829dcf547a7dd10f | 固定loopback POST到 `/api/v4/manager/research/workspace/scheduled-cycle`；服务端重验binding、full readers、当前日期/窗口，沿原注入service调用run_scheduled_plan_target；无本地窄service fallback。 |
| apps/api/v35_api/manager_research_router.py | 7db8e868bf8db3e0800b8e8fb9da715074db1c1e | 已上传的router源码入口。最终候选是否采用此blob仍需与目标app绑定。 |

这些文件是交接中的 canonical 字节，不是 API 11-pin 回执中已证明采用的三文件。后者只冻结业务10文件+autorun，不提供这三条当前目标映射。不能据此删掉 RPC、恢复窄 service 或把旧 B2 8 项 fixture 当新 main 已验。

## 本次判定

`B2_FINAL_CYCLE_BINDING_REQUIRED`。本包不应用原 `cycle_snapshot.patch`；新 runner 显式请求 cycle/all 时拒绝，而不是降级旧autorun或静默计为通过。原B2源码、断言、8项历史结果完整保留在 original_business 中；本轮未修改、未重跑它们。B1/US33不受影响。

## 一次最小回传

1. 对本轮计划采用的 worker/app 和 API候选，给上述三路径的实际SHA256及与已有blob的对应关系；若全部字节相同，只需要身份映射与根目录用途，不重传源码。不同的只上传对应最终文件；不存在的写明确缺失。无需整个 service.py、整库或整项目。
2. 脱敏声明当前组合的 `enabled`、`plan_material_refresh_only`、`announcement_collection_enabled`、`preopen_plan`、`morning_plan`、`plan_material_refresh`。仅相关布尔／窗口配置，不要原始plist、凭证、URL token或环境值。

基于真实确认入口，最小后续适配是保留原 RPC/服务端重验，确保当轮公告提交在计划消费之前，并在消费前使用新的实际时钟；不改 morning/Vibe/下一交易日分支，不扩大preopen窗口，不做盘后补建。此处是限定方案，尚未编写或验收新的RPC版B2源码。不能把本包的business成功当B2恢复。

R3A的F0/F1九文件缺口与此独立。沿用 dcd72a0… 作者回执、独立review待的分层状态，不拿旧canonical冒充最终F1，不要求本包等17:20。
