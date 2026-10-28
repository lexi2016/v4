# 2026-09-12 研究复盘接入边界

本批继续以 `/Users/lexi/Desktop/学习/v4_app` 作为唯一源码仓库。研究复盘接入只增加 `/api/v3/review` 的可选 `research_review` 字段和 ReviewView 只读面板，不改变已有 A/HK 复盘字段、阶段池、模型或交易安全边界。

## 精确日期读取

`domains/daily_research_review.py` 只接受一个精确交易日，并从显式配置的 `V4_DAILY_REVIEW_ROOT` 读取 `<YYYY-MM-DD>.json`。调用者也可以给 `load_daily_research_review(..., review_root=...)` 传入显式根目录，便于受控验证。读取器会检查根目录、日期文件名、JSON 的 `target_date` 和 `trade_date`，拒绝符号链接与根目录外路径；缺配置、缺日期文件、日期不一致、格式错误或必要事实字段缺失都返回 `CANNOT_CONFIRM`。`latest.json` 永远不参与查找。

成功投影的字段来自原始复盘的既有语义：市场广度、昨日强势反馈矩阵、赚钱效应、亏钱效应、晋级梯队、梯队缺口、题材树和事件台账。投影计算 SHA 只用于证据身份，不重算市场事实，也没有写入路径。所有返回均保持 `research_only=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

ReviewView 对这些段落保留完整字段可达性：实际数组不做静默行数截断，反馈明细、题材、事件及亏损/赚钱/反复开板分类显示总数；复杂字段、每行隐藏字段、题材成员和各段完整 JSON 均可展开查看。复盘重点（focus）也在同一只读面板中展示。受控前端 fixture 保留实际产物的 14 个广度字段、35 条反馈明细、10 个题材、19 条事件及 11/5/3 分类数量。

## 当前生成责任

已读到的外部生成链是 `vibe-astock/main.py -> duanxian.review_graph -> duanxian.review_store.save`，默认写入 `~/.duanxian-agents/reviews/<date>.json` 与 `latest.json`。V4 本身当前没有对应的研究复盘生成 workload 或 owner，因此成功读取历史产物的状态仍带有 `V4_DAILY_RESEARCH_REVIEW_GENERATOR_NOT_CONNECTED`；这表示“读取可用、未来生成未接管”，不能据此停掉外部生成链，也不能宣称自然调度已迁移。

最终接入前需要由后续全功能调度盘点确定持续生成 owner，并把它绑定到已验证的唯一调度入口。当前 v35 scheduler plist 仍指向旧 release，本批没有修改 plist、scheduler 或服务。BaimaoXRefresh 只保留 v4 已有 `ops/refresh_baimao_x_digest.py` 和 executor handler 的后续核对项；现有运行图尚未证明它已装载 v4 配置。WQ101 在 `contracts/runtime_workloads.json` 中保持 `USER_APPROVED_DISABLED_CANNOT_CONFIRM`、`enabled=false`、`execution_allowed=false`，本批不新增 producer。

## 经理研究状态迁移前置条件

候选 release 的空 manager state 只用于隔离验证，不能替代现有历史。真实切换方案必须在旧 API 停止写入后，由主控按独立审批执行：

1. 记录旧 API 与当前 manager state 根的停止和只写冻结证据。
2. 将当前完整 manager 根复制到候选版本根，保留 `.commits/<YYYYMMDD>/<input_identity>.json`、jobs、materials、products、receipts 等结构；不重算历史哈希，不迁移历史产物语义。
3. 逐日验证候选 API 的 exact-date 结果、`manager-state/.commits` 文件和 `input_identity.json` 与原根兼容，确认新旧进程不会共写同一状态根。
4. 新 API 仅在验证通过后绑定候选状态根；回退重新绑定原状态根，并保留本次迁移 receipt。

本批只完成候选读路径与验证面板，未执行上述停止、复制、启停或调度重绑。
