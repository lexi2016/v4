# 经理每日计划缺失：R3 Chat 修复包

目标是修复 V4 经理工作台每日计划没有产出的原 owner 路径，并为 **2026-10-08 事后补算** 与 **2026-10-09 当日计划** 提供可验证的实现和回归测试。现场两次顺序 GET 均 HTTP 200，但 `plan_product=NOT_MATERIALIZED`、`run_id=null`，US daily mapping 为 `NOT_RUN`。

## 交给 Chat 的固定链接

新 R3 包位于私有仓库 `lexi2016/v4` 的分支 `codex/manager-daily-failure-20261009-r3`，路径 `handoff/manager-daily-failure-20261009-r3/`：

[打开 R3 经理每日失败包](https://github.com/lexi2016/v4/tree/codex/manager-daily-failure-20261009-r3/handoff/manager-daily-failure-20261009-r3)

分支父提交为 `66bb05a2e12976775ccb997191ce943bae8cc9a5`。R1/R2 累计候选与独立审查可从[固定 Mac 交接](https://github.com/lexi2016/v4/tree/66bb05a2e12976775ccb997191ce943bae8cc9a5/handoff/manager-automation-r2-mac-20261009)读取。

## 已经证实的边界

当前计划 owner 请求路径存在配置身份冲突：调度 binding `c0fbff...` 启用 plan-only 和每日计划刷新；8873 API 读取的 owner binding `f3b7cb...` 则 `enabled=false`，且 SHA 和 app root 都与调度绑定、现役 API root 不同。静态代码路径表明，若请求到达 API，首先会因 `PLAN_OWNER_BINDING_SHA_MISMATCH` 被拒绝。**具体 10/9 dispatch 是否发起仍为 `CANNOT_CONFIRM`**，因为本次没有读取 owner dispatch receipt。

R1/R2 累计候选独立审查对冻结候选给出 PASS，但现场 API 的经理相关文件仍处于 R1 before；候选 PASS 不等于现场已部署或经理名单已恢复。Issue32 的 `app.py`、`preselection_router.py`、`preselection_service.py` 三个文件必须保留原 SHA，见 `current_vs_candidate.json`。

## Writer 机器校验

在 R3 根目录（含 `package/`、`evidence/`、`tools/` 的目录）运行 `python3 tools/validate_package.py` 得到 PASS。校验回执位于 `evidence/validation_receipt.json`：33 条源码清单记录中，32 个快照逐个与来源比较字节数和 SHA；1 个缺失的 active API 路径明确记录且未造 stub；3 个来源没有预期 SHA 的路径单独标记；JSON、Issue32 三个保护 SHA、研究安全标记均通过，高置信凭证扫描为 0 命中。独立 Reviewer 与 GitHub 同步读回仍待主控完成。

## 阅读顺序

1. [Chat 实施任务](CHAT_TASK.md)
2. [证据说明](EVIDENCE.md) 与 `../evidence/runtime_identity.json`、`../evidence/live_get_projection_20261009.json`
3. [根因矩阵](root_cause_matrix.json)
4. [现役/候选对照](current_vs_candidate.json) 和 [源码清单](source_manifest.json)

所有研究安全标记保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。本包待独立 Reviewer 验收，不代表修复、集成或部署。
