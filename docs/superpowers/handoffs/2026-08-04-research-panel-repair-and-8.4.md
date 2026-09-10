# V3.5 研究面板污染修复与 8.4 状态交接（2026-08-04）

## 1. 交接目的

记录研究面板（selector_ready_panels）历史数据污染的根因、修复过程与当前状态，以及 20260804 数据链的可用性，供下一会话继续推进。

## 2. 污染根因（已彻底查明）

**现象**：selector 面板生成任务（`数据/tools/debug_scripts/data_layer_daily_formula_increment_update_v1/`）自 20260803 起失败，报 `BLOCKED_CURRENT_FORMAL_HISTORY_CORRUPT`，导致 8.3/8.4 无 selector 面板、V3.5 无 A 股主池。

**根因（多证据链确认）**：

1. **6/18 增量生成时市场/代码错配**：688981.SH（中芯国际，约 140 元）的 OHLC bar 被错误写入 000001.SZ（平安银行，约 10 元）行。tdxpy 与 `.day` 原始数据验证：000001.SZ 6/18 真实 close=10.52，面板里=140.7；688981.SH 6/18 OHLC=136.11/144.63/132.88/140.7 与面板中 000001 坏值逐字节一致。
2. **逐日扩散**：面板生成用 "copy current parquet batches" 复制历史，污染从 6/18 起逐日扩散到 6/30、7 月所有面板（selector + backtest 共用）。
3. **8/3 严格审计暴露**：8/3 起 `audit_formal_panel_history`（全量 OHLC 跨日检查）检测到污染 → 硬阻断。此前用轻量审计（只查 schema/日期）未发现。

**污染范围**：2026-06/07 有 11243 行异常、涉及 2933 只股票，集中在日期 20260618/22/23/25/26、20260714/15。`.day` 源在 8/3 17:03 被部分修复（000001 等），但面板 parquet 从未清理。

## 3. 修复内容

### 3.1 修复面板 OHLC（用 .day 权威数据重建）

- 脚本：`数据/tools/debug_scripts/data_layer_daily_formula_increment_update_v1/repair_selector_panel_ohlc.py`（新建）
- 逻辑：构建全量 .day OHLC 索引（993 万条，10 秒），流式对比修复面板所有行的 open/high/low/close/pre_close
- 结果：**修复 21483 行 OHLC**（6 月错配），pre_close 修复 106 万行，保留面板 207 列、trade_date string schema
- 验证：000001.SZ 6/18 从 140.7 → 10.52；000002.SZ 6/18 → 3.06；000006.SZ 6/18 → 8.21（不再错配）

### 3.2 设置修复面板为权威

- 修复面板已复制到正式位置：`数据/selector_ready_panels/data_layer_daily_formula_increment_update_v1_metadata_repair_20260508/selector_ready_current_to_20260731_name_repaired_20260731_170132/selector_ready_current_to_20260731.parquet`
- 原污染版备份：同目录 `selector_ready_current_to_20260731.parquet.polluted_backup_20260804`
- `CURRENT_SELECTOR_READY_PANEL.txt` 指向不变（路径相同，内容已修复），SHA 验证一致
- pointer 备份：`data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt.backup_20260804`

### 3.3 审计逻辑改进（数据层脚本）

`数据/tools/debug_scripts/data_layer_daily_formula_increment_update_v1/data_layer_daily_formula_increment_update_v1.py` 的 `audit_formal_panel_history_frame`：

- **只阻断 `invalid_ohlc`**（OHLC 结构性非法：high<low、close 超范围等）；`cross_day_break`、`preclose_break` 降级为 `edge_warning_count`（不阻断），因为它们是除权/停牌/低浮动股票的正常情况（尤其面板无 `pct_chg_source` 列时）
- **只审计 A 股**（`.SH/.SZ` 结尾），排除 HK、HK_FUND、板块指数等非 A 股行（float 精度导致的 OHLC 微超不误报）
- 验证：修复面板 A 股审计 **PASS**（0 hard issue，1351 edge warning）

## 4. 8.4 数据链状态

| 模块 | 状态 | 说明 |
|---|---|---|
| 研报 | ✅ 物化 | 288 篇、201 股票池，从 8.4 research_lane_snapshot 手动物化 |
| A股主池 | ✅ 物化 | 20 只（signal 20260731→target 20260804），从修复面板生成 |
| 其余六池 | ❌ 未物化 | fupan/stage7/hk/wechat/baimao 的 8.4 上游旧 V3 未产出（旧 V3 今天只生成 `20260804_ashare_readiness`，无预选池链） |
| 八阶段 | ❌ 未物化 | 需完整七池 + 8.4 行情；**8.4 盘中 tdxpy 09:25 竞价数据未积累**，要等收盘后 |

## 5. 下一步

1. **等 8.4 收盘**后（15:00+），物化 8.4 完整七池（若旧 V3 补产出）或从修复面板物化主池，再物化八阶段（tdxpy 回溯 8.4 行情）
2. **验证 selector 生成恢复**：用修复面板重跑 `data_layer_daily_formula_increment_update_v1.py`，确认 8.3/8.4 面板能正常生成
3. **同步修复 backtest 面板**：污染共用，需同样用 .day 重建（repair 脚本支持任意面板路径）

## 6. 冻结边界

- `production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false` 全程保持
- 未触碰旧 V3、Windows Tasks、正式交易配置
- 数据层修复仅改了：面板 parquet（.day 重建）、审计函数（阻断逻辑）、新增修复脚本

## 7. 关键文件

- 修复脚本：`数据/tools/debug_scripts/data_layer_daily_formula_increment_update_v1/repair_selector_panel_ohlc.py`
- tdxpy 重拉脚本：`数据/tools/debug_scripts/data_layer_daily_formula_increment_update_v1/pull_tdx_ohlc_repair_map.py`（诊断用）
- 修复面板：`数据/runtime/repair_20260731_full.parquet`
- 正式修复面板：`数据/selector_ready_panels/.../selector_ready_current_to_20260731.parquet`
- 污染备份：同目录 `*.polluted_backup_20260804`
- 数据层脚本（已改审计）：`数据/tools/debug_scripts/data_layer_daily_formula_increment_update_v1/data_layer_daily_formula_increment_update_v1.py`
