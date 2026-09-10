# Phase 3 研报决策台验收表（20260730）

基线：`v3_graph_baseline_v2`，semantic hash `8b4b933858f0e573b4d9f34423cd7aceeeb09dbf50cc826de0b18b712a4cbdd7`。

Phase 3 已完成 exact-date 归档、显式 latest 入口、带时区的三个时间角色、全量研报股票池和页面缺失态。本表仍将 artifact、API 与页面证据分开：新端点已通过 TestClient 回归，但当前 8872 运行进程未重载，所以实时端点仍为 404；这不影响 `IMPLEMENTED / TESTED / INTEGRATED`，但禁止升级为 `DEPLOYED / UI_VERIFIED / BUSINESS_PARITY_VERIFIED`。

| Feature / 图谱范围 | 冻结 V3 输入 | V3.5 同日归档 | Artifact | API | 页面 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `research.desk`（25 个 task/timeline/windows 节点） | 原始 timeline 1475，daily 205，bridge 205；六字段去重后 336，股票池 205 | 336 篇去重文章、205 只股票；2 处旧运行路径已红线化；BACKFILL 不生成 latest | payload / receipt / manifest 的 payload semantic SHA 一致为 `19a788d6...0000`；旧原始快照在 V3.5 证据根外 | TestClient 覆盖 exact、latest、miss 与模式隔离；实时 8771=200/236 行，8872=404/0 行（进程未重载） | Vue 测试验证 205 只股票、336 篇文章、三时间字段不漂移、miss 结束 loading；内置浏览器尚未实验 | `IMPLEMENTED / TESTED / INTEGRATED / CANNOT_CONFIRM_PARITY` |

## 合同与边界

- exact-date：`GET /api/v3/research/articles?archive_date=YYYYMMDD`，严格按日期读取，缺失返回类型化 `NOT_MATERIALIZED`。
- latest：`GET /api/v3/research/articles/latest`，只读 LIVE 指针；REPLAY/BACKFILL 不更新 latest。
- `published_at`、`collected_at`、`first_seen_at` 统一为带时区 ISO 8601，Vue 按 `Asia/Shanghai` 展示，归档日期不改变。
- 旧 V3 混合 naive/aware 时区语义不可证实；导入时将 naive 时间按 `Asia/Shanghai` 标准化并保留 `CANNOT_CONFIRM`。
- 归档目标限定于 V3.5 `.runtime/data`，symlink/junction 逃逸失败关闭；外部 V3 输入全程只读且校验前后 SHA。

## 机器证据

- 图谱合同：`contracts/migration/research_desk_graph_contract_v1.json`，semantic hash `fff83334d6ca0c00f999378fd8398a9ce03a1b4534db9fcaa4d0f429b5304462`。
- parity receipt：`.runtime/evidence/phase3/parity/20260730/research.desk/research_desk_graph_v1/receipt.json`，semantic hash `4fa8eec75227620ccf2d6d5259780fd535ca4e267df7d9ab8d09a7ac0df5ef94`。
- authority：`.runtime/evidence/phase3/parity/20260730/research.desk/authority.json`，semantic hash `36aada7fdc73222b38a0bd1c25a0a5e41248cc558e75383eb4e3941031e7caa7`。
- 冻结 V3 输入原始 SHA：`8ba8b92b6c85b977caac13390533fbf0aec05bfd4e52045229f0964a159be96c`；导入前后一致。

## 验证

- Python 全量：`254 passed, 1 skipped`。
- Vue：`24 passed`；`vue-tsc --noEmit` 与 `vite build` 通过。
- 只读 Reviewer：最终 P1/P2/P3 均为 0；聚焦回归 `4 passed`。
- 安全边界：`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 未升级的状态

- `DEPLOYED=false`：8872 运行进程尚未加载新 router，exact/latest 实时请求均返回 404。
- `UI_VERIFIED=false`：内置浏览器控制不可用，没有可升级的实际页面证据。
- `business_parity_verified=false`：V3 冻结源 SHA 与 V3.5 归档 SHA 不同，而且当前 V3 API 是后续动态快照，不得用不同采集时点宣称业务等价。
- LIVE 小时研报生产器、Windows Task canary 和五个交易日双跑仍属后续 Phase，本阶段没有提前执行。
