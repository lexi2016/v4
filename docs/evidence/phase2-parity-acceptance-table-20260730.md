# Phase 2 图谱复核验收表（20260730）

基线：`v3_graph_baseline_v2`，semantic hash `8b4b933858f0e573b4d9f34423cd7aceeeb09dbf50cc826de0b18b712a4cbdd7`。

本表把 artifact、API、页面三条证据分开记录。V3 与 V3.5 使用的冻结源 SHA 不同，因此三个 feature 的机器 receipt 均为 `CANNOT_CONFIRM`；这不影响对“V3.5 修复是否已实现、测试并集成到当前分支”的判定，但禁止据此宣称跨版本业务等价或生产部署。

| Feature / 图谱范围 | V3 同日结果 | V3.5 同日结果 | Artifact | API | 页面（Playwright fallback） | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| `preselection.pools`（30 个 task/timeline/windows 节点） | 7 池、302 行；另含微信池 43 与白毛研究池 0 | 五个目标池独立：19 / 64 / 70 / 6 / 100；A 去重 147、HK 100 | V3.5 仍是 `legacy_partial_migration` 单次导入，五池为只读兼容投影 | 200 / 200；payload SHA 不同 | 五池标题与 85 条预览行可见；loading 完成、无横向溢出、console 0/0 | `IMPLEMENTED / TESTED / CANNOT_CONFIRM_PARITY`；微信与白毛节点留 Phase 4 |
| `stage.workbench`（21 个 task/timeline/windows 节点） | A 0、HK 10；A source 1/3 | tdxpy exact-date：requested 147、source 146、缺 `A.300333`、candidate 50、selected 50；HK V1.1 Top20 | native stage artifact 为 60 行，V1.1 独立 artifact 为 20 行，API 组合为 70 行 | 200 / 200；A `0→50`、HK `10→20` | A 股票行与 V1.1 标识可见；20 条候选预览；loading 完成、无溢出、console 0/0 | `IMPLEMENTED / TESTED / CANNOT_CONFIRM_PARITY`；旧图仅证明分钟 L0 回放，不能冒充 exact 09:25 成交明细等价 |
| `review.close`（33 个 task/timeline/windows 节点） | A 收盘复盘未生成；HK close `BLOCKED_CLOSE_DATA` | A 观察池 12；HK 全市场 648、收盘 Top20 20、模型池 100、阶段归因 62 | A/HK exact-date artifact 分离，均有 SHA / receipt / manifest | 200 / 200；A `0→12`、HK Top20 `0→20` | A 股复盘入口显示 12 行并呈现 HK 收盘复盘；loading 完成、无溢出、console 0/0 | `IMPLEMENTED / TESTED / CANNOT_CONFIRM_PARITY` |

## 机器证据

- `preselection.pools` receipt：`.runtime/evidence/phase2/parity/20260730/preselection.pools/preselection_pools_graph_v1/receipt.json`，SHA `b0921695005c7164cfba38342e9e3d8e26c0ea0f68969cb2f96328f043ea04c2`。
- `stage.workbench` receipt：`.runtime/evidence/phase2/parity/20260730/stage.workbench/stage_0925_tdxpy_v11_v1/receipt.json`，SHA `523fcef91c9c21eb1ce744398bb96d7ad1d7aee1d803b54896e5eb357e5d6d21`。
- `review.close` receipt：`.runtime/evidence/phase2/parity/20260730/review.close/review_close_ah_v1/receipt.json`，SHA `4613d0a3601e0402d7130da9a8eb6ea6ec00f9a6c5c5e9cab53182805bf56b1c`。
- V3.5 阶段/池截图：`.runtime/evidence/phase2/v35-stage-pools-20260730-1440x900.png`。
- V3.5 A/H 收盘复盘截图：`.runtime/evidence/phase2/v35-review-20260730-1440x900.png`。

## 验证

- Python 全量：`240 passed, 1 skipped`。
- Vue：`20 passed`；`vue-tsc --noEmit` 与 `vite build` 通过。
- Dispatcher 双进程：主控 30/30 轮、只读 Reviewer 10/10 轮；每轮恰好一个 `DRY_RUN_SELECTED` 和一个 `CONCURRENCY_SKIPPED`。
- 只读 Reviewer：P1/P2 为 0。
- 安全边界：`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 未升级的状态

- `DEPLOYED=false`、`UI_VERIFIED=false`、`business_parity_verified=false`。
- 内置浏览器控制不可用，本轮页面证据是 Playwright fallback，不能升级为用户内置浏览器验收。
- `ops.run_dispatcher` 仍为 dry-run；真实 executor、缺失 workload runner 与 Windows Task canary 属于 Phase 5，未提前执行。
- 预选五池仍是只读兼容投影；正式多池物化留待相应垂直切片闭环。
