# 面板两个空池的证据缺口与修复计划（2026-11-03）

## 现象

面板在 2026-11-03 显示：

- A股 D-1 复盘继续观察池：`CANNOT_CONFIRM · A_D1_FUPAN_WATCHLIST_EVIDENCE_MISSING`，0 行。
- A股 D-1 Stage7/分时复盘池：`CANNOT_CONFIRM · A_D1_STAGE7_FENSHI_EVIDENCE_MISSING`，0 行。

池接口的其他池正常：A 股 D-1 候选池 135 行、研报推荐池 200 行、港股通 Top100 100 行；总 438 行。空池不是面板渲染问题。

## 根因链（只读核对）

1. **V4 池读取端行为正确。** `domains/_preselection_parts/review_fupan.py` 与 `review_stage7.py` 只有在 Review Core 返回“精确目标日期、READY/PARTIAL、有行、安全标志干净”时才替换本地缺失占位；否则保留 CANNOT_CONFIRM。没有伪造行。
2. **两个上游 D-1 产物本身是 CANNOT_CONFIRM：**
   - `fupan_store/runs/20261102/D1_FUPAN_REVIEW_POOL_V1/.../artifact.json`：
     `REVIEW_BUNDLE_VERIFY_FAILED: exact-date review bundle pointer missing: 20261030`（target 20261102，signal 20261030）。
   - `stage7_store/runs/20261102/D1_STAGE7_REPLAY_POOL_V1/.../artifact.json`：
     `SOURCE_LOAD_FAILED: StoreError: no latest run for 20261030 / A_SHARE_1MIN_STAGE_1445_1500`。
3. **复盘核心链自 2026-10-26 后停供：** review-core 状态目录的 `stage7_pools`、`fupan_pools` 最新只到 `20261026`；`review_bundle`、`asr`、`audio`、`media`、`review`、`local_review` 均无当前产物。
4. **复盘日任务处于失败/阻塞状态：**
   - `com.lexi.review-core.daily` 的子进程反复报 `ModuleNotFoundError: No module named 'review_core'`（子解释器/ PYTHONPATH 与该 release 组件不匹配）。
   - 最近一次 stdout 回执为 `status=BLOCKED`，`selector_validation.ready=false`，`reason=SELECTOR_POINTER_METADATA_MISSING`；指针指向的 parquet 文件存在，但复盘核心要求的指针元数据缺失。
5. **与 21:40 物化器的关系：** 昨日 `daily_materialize(2140)` 因过期槽位饥饿未执行；即使执行，它只“验证”七池，不能凭空补齐上游 review-core 证据。两件事都要修，但不是同一根因。

## 修复计划（独立批次，需冻结范围与独立复核）

1. 修复 selector 指针元数据（用既有 selector producer 重新产出，不手写元数据）。
2. 修复 review-core daily 子进程解释器/PYTHONPATH 与 release 组件的匹配。
3. 用既有 review-core producer 对缺失日期（至少 20261030、20261102）做精确日期补跑，生成 review bundle、Stage7 1 分钟源与 D-1 池。
4. 重新物化目标日期（20261103）的七池，核对行数/来源/安全标志。
5. 独立复核后更新面板读回；任何一步无真实输入即保持 `CANNOT_CONFIRM`，禁止用占位或手填行。

## 边界

- 本诊断只读，没有改池、改收据、改 review-core 数据或启停任何服务/计划任务。
- `daily_materialize` 与 review-core 属于不同链；r10 已修复调度器选择逻辑，但不会自动补历史复盘数据。
- 现有交易安全标志保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。