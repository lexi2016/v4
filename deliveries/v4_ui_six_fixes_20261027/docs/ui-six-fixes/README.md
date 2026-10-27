# 2026-10-27 六项显示修复候选

本批只修改预选池显示名、分页提示、HK1555 缺回执显示契约、任务页美股回执 reader、PDF 同卡状态投影和经理紧凑摘要生成时间。候选不是部署或自然运行验收。

- 显示名称：原 security-master owner 新增 `DISPLAY_NAME_ONLY` 独立发布；20261027 观察与 20261026 信号日分开。87 个 TDX security-list 名称及 3 个官方发行人 PDF 身份原件，90/90；不修改 selector registry、预选池、排名、分数、资格、PIT 或 BUY。
- API 在分页前对所有显示数组投影名称，并复用原 Stage consumer 的日期、pool trio SHA、冲突和坏源检查。`920575.SH` 原始字段保留，另列 `display_identity.ts_code=920575.BJ`。
- 分页剩余与源缺失分开；HTTP200 的精确 HK-only 缺回执保持 `CANNOT_CONFIRM`，不伪造 A 行或成功零值。
- `V4_TASK_STATUS_US_LEDGER_ROOT` 仅供 `us_market_digest`；独立 LIVE ledger 的日期/链失败保持未知。Main reader 及 producer 不改。
- PDF 只在原有日期/文档 ID 和请求版本校验后用详情状态、页数和完成时间更新同一卡片；经理时间来自原 snapshot.generated_at。

针对性验证：Python 32 个唯一测试通过；前端 19 个唯一测试通过；actual API 前端基线的 Vite 构建通过。候选只读回放三页 200/200/82，90/90 目标名称通过，剔除显示字段后与现役接口相同；预选池 trio SHA 前后相同。

全量 `vue-tsc` 有 30 个错误，全部位于未改动的实际前端基线文件，逐项 SHA 证据留存。不扩大本批修复；全量类型检查不是 PASS。

原 canonical 前端构建已因与现役基线不同而封存禁止部署。最终候选使用实际 API 前端树，仅四处显示修复；经理页等八个构建输出与现役字节相同。

原始页面、发行人 PDF、SDK 响应和过程日志保留在本机证据目录，不进入 Git。回执 run_id `d04b77052fb9acbc82707796`，仅认证显示名来源；`selector_certified=false`、`pit_certified=false`。独立 Reviewer、部署、API/UI 与自然运行由主控后续验收。
