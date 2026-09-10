# Phase 4 图谱功能处置验收（20260801）

基线：`v3_graph_baseline_v2`，semantic hash `8b4b933858f0e573b4d9f34423cd7aceeeb09dbf50cc826de0b18b712a4cbdd7`。处置合同：`phase4_feature_disposition_v1.json`，semantic hash `ea48a3a131215c20f0ac8826fb2c12b91491dad6d94a0090e2627bc905305458`。

Phase 4 已将 inventory v2 的 11 个 feature 全部绑定到冻结图谱、当前 V3.5 owner、测试和现有 parity receipt。裁决为 5 个 `KEEP`、4 个 `COMPAT`、2 个 `REMOVE 提案`。`REMOVE` 仍需用户单独批准，本阶段没有删除旧 V3 或 V3.5 文件。

| Feature | 裁决 | 当前 V3.5 处置 | 真实缺口 |
| --- | --- | --- | --- |
| `navigation.dates` | `KEEP` | date catalog API 与页面日期导航已可达 | inventory feature 节点未对齐，仅能用已冻结 API/API-ref 节点证明 |
| `preselection.pools` | `KEEP` | V3 的 7 个池独立呈现：19 / 64 / 70 / 6 / 0 / 100 / 43；公众号池为独立 `RESEARCH_ONLY` 覆盖层 | 8872 进程尚未加载；内置浏览器未验收，白毛池保持 0 行 `CANNOT_CONFIRM` |
| `stage.workbench` | `KEEP` | 八阶段、tdxpy 09:25 和 V1.1 开盘参考已封存 | 旧 `DATA_FUPAN` 按钮无 click handler 的图谱缺口仍保留 |
| `stage.model_review_close` | `COMPAT` | 页面标签使用统一 close-review payload | 无独立 API，旧 feature 节点未对齐，不宣称等价 |
| `review.close` | `COMPAT` | A/H exact-date 收盘复盘只读投影已可达 | B站下载、ASR、OCR、stockdict、gap/guard、publish 全链未迁移 |
| `research.desk` | `KEEP` | exact/latest、336 篇研报、205 只股票及时区合同已完成 | LIVE 小时研报 producer 与 8872 进程重载未执行 |
| `runtime.status` | `KEEP` | 同日 catalog/receipt 状态与页面 `cannot_confirm` 已可见 | 已启用 workload 尚缺 LIVE receipt；inventory feature 节点未对齐 |
| `tasks.registry` | `COMPAT` | 严格内部 catalog 可通过任务状态页查看 | 35 个旧任务的唯一 owner 全量映射属于 Phase 5 |
| `orphan.loadConsole` | `COMPAT` | V3.5 主页只承接日期、阶段、预选、研报、复盘与任务状态 | 冻结 V4 页的 `loadConsole` 有1个定义和2个可达调用；trading overview/signals/gates/run-cards 未迁移 |
| `orphan.loadMorningLane` | `REMOVE` 提案 | 未建平行实现 | 冻结 V3 HTML 仅1个定义、0个可达调用；需用户批准才能终态删除 |
| `orphan.loadWechatLane` | `REMOVE` 提案 | 未建平行实现 | 冻结 V3 HTML 仅1个定义、0个可达调用；需用户批准才能终态删除 |

## 防误判门禁

- `loadConsole` 不再被冒充为全局不可达：测试直接读取 Phase 0 冻结的 V3/V4 HTML 与 `main.py`，校验原始 SHA、路由、定义数和调用数。
- 两个删除提案只限定到冻结 `fupan_dashboard_v3.html` 中的死定义，不是对同名业务语义的猜测。
- 四份 parity receipt 逐份验证文件存在、canonical 自哈希、声明 SHA、feature 身份、graph hash、`CANNOT_CONFIRM` verdict 和三个安全标志。
- 非空 inventory feature 的 evidence graph nodes 必须属于该 feature；空 feature 只允许用已冻结 API/API-ref 节点支持局部可达性。

## 验证与状态

- 当前 Python 全量：`361 passed, 1 skipped`；Phase 4 原聚焦回归：`47 passed`，预选池新增机器 receipt 另行封存。
- Vue：`24 passed`；`vue-tsc --noEmit` 与 `vite build` 通过。
- 只读 Explorer 完成 11 feature 路径审计；只读 Reviewer 最终 P1/P2/P3 均为 0。
- 本阶段状态为 `IMPLEMENTED / TESTED / INTEGRATED / PASS_WITH_DECLARED_CANNOT_CONFIRM`。
- 仍为 `DEPLOYED=false`、`UI_VERIFIED=false`、`business_parity_verified=false`。
- 安全边界保持 `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
