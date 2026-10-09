# V4 Stage：当日研究最小修复 R2

本包交付可应用的新增业务代码，目标链路为 **真实预选输入 → 原阶段行情 → 原算法 → 原存储 → 现有 API/Vue 结果**。

代码已完成；最终新独立 canary 的 actual 与 canonical 两套 Stage 各 **115 项通过**，全部候选代码在复跑前后保持相同 SHA，六套补丁正反向逐字节通过。归档依赖使用了明确标注的测试支持，证明范围和 Mac 实采限制见 [TEST_RESULTS.md](TEST_RESULTS.md)；本包不宣称现役已部署或自然运行通过。

- 固定父版本：`0fc3e8304e11700230517616ded0c86f83a4b257`。
- 原问题/实际源码切片：`28ab2d35020adf031f10f38c1040514fc81b6d66`。
- 额外读取 `41a9242d400acec08af3934d1da314b1626a1bcd` 中的 `active_api_issue32/app.py`、`consumer.py` 作为现役 API 源码参考。没有使用 r5c 拆分候选逻辑。
- 责任：Chat 编码；Mac 落地、真实数据测试与验收。无需 Mac 再设计研究准入、collector、算法或 reader 业务逻辑。

## 可落地内容

| 目标 | 文件数 | 完整 after | 补丁选择 |
|---|---:|---|---|
| 实际 Stage | 18：16 修改＋2 新模块 | `after/actual_stage/` | `patches/actual_stage.restored_to_r2.patch` |
| canonical Stage，独立变体 | 18：16 修改＋2 新模块 | `after/canonical_stage/` | `patches/canonical_stage.restored_to_r2.patch` |
| 实际 API / 现有 Vue | 6 修改 | `after/actual_api/` | `patches/actual_api.restored_to_r2.patch` |

同时提供三套 `*.r1_to_r2.patch`。本机 Stage 已恢复 before，因此可以直接使用 `restored_to_r2`，不必先手工应用 R1。`SOURCE_MAP.json` 为每个文件列出原 before、R1、最终 after 的 SHA256、来源固定 ref 和条件前像状态。API actual 文件不会覆盖 canonical API；canonical Stage 的历史分支单独保留。

入口文档：

- `MAC_APPLY.md`：隔离 canary、独立复跑、真实数据运行、既有发布链和同 run API/UI。
- `TEST_RESULTS.md`、`evidence/`：本轮新测试及完整原始日志。
- `SOURCE_GAPS.md`、`SOURCE_GAPS.json`：一次性完整列明尚未读取的当前前像及所需 SHA。

## 1. HK 显式当日研究模式

新增可选 `hk_current_day_research_root`，从 config loader、node entry、RunnerConfig、准入、binding、slot、原 collector、原 builder 一路传递。默认 `None` 继续原 STRICT D1 合同；显式研究输入无效时仅拒绝 HK lane，不会回退冒充 D1，也不会阻止合法 A lane。

新模块 `stage_center/hk_current_day_research.py` 只读四个既有文件，内置本轮用户授权的 20261009 SHA pinset，不生成 producer、权威底板或正式 latest。其生产入口核验文件字节、695 个唯一代码和参考集合。

| 研究身份 | 值 |
|---|---|
| `input_mode` / binding role | `CURRENT_DAY_RESEARCH_ONLY` |
| `universe_as_of` | `20261008` |
| `captured_at` | `2026-10-09T15:38:41+08:00` |
| `stale_universe` | `true` |
| 当前港股通成员资格 | `CANNOT_CONFIRM` |
| 来源声明 | `USER_REPORTED_MAC_ACQUISITION_20261009` |
| `security_snapshot_is_quote` | `false` |

**本轮 15:38 的资料只满足 `STAGE_1545_1555` 的时间准入。** 不能倒填上午或 13:15 阶段。两份 receipt 的原字节 SHA 会核验；其未知内部结构没有被擅自解释为独立资格证明。Chat 没有读到用户 Mac 的四个真实文件，合成测试明确使用独立测试 pinset。

证券资料仅作为资料；价格、OHLCV、分钟时间仍来自原 PyTDX ExHQ Stage collector。正式 Stage8 RT_DATA/Futu 活跃名单路线只在正式模式使用。研究模式调用原 `select_hk_four_lane` 的观察路径，保留原评分、权重、排序、Top10；不制造 `LIVE_HKCONNECT_GAINER` lane 或 D1/港股通资格。最终元数据通过原 identity helper 和原 manifest 绑定。

## 2. A 股字段和可选 witness

保留 R1 的输出修复，并把原竞价源的 `prev_close_price` 透传到 09:25 builder；后续分钟源的 `qmt.lastClose` 通路用原 normalizer、SourceResult、builder、原 selector、原 SelectionStore 实测。缺失值保持 `null` 和原因，真实 0 保留。完整输入仍为 216，不受页面 200 行限制；缺少 10/11 只行情是逐股覆盖问题。

原 `ResearchContextError` 校验器不变。可选补充研究材料的 `SOURCE_ARCHIVE_PROJECTION_SHA_MISMATCH` 等错误在消费边界保留为不可确认原因，该材料不参与评分加分，基础合法输入和行情继续运行原算法。候选 current、raw、正式输入和结果存储的完整性约束仍保留。

## 3. 输入、结果、回执、API/UI

原 writer 增加研究输入 binding、原 selection 三件套字节 SHA 和 immutable owner receipt。A 输入声明的 date/run/current 字节 SHA/216 行数，会与原 selection manifest 内的来源标记及 owner history 对照；成功只称 `OWNER_DECLARED_INPUT_BOUND_TO_SELECTION`，不冒称 API 重新读取候选 current 或验证 PIT。

每次调用记录 Stage/node 相关源文件 SHA，写入最终 selection envelope 与 receipt；`selection_source_identities` 保留每个原选股 run 的身份，NOOP 或 scoped retry 不会用新调用来源覆盖旧结果来源。文件哈希及 `runtime_source_stability` 是磁盘观察记录，不是 Python 进程已加载代码、发布或自然触发证明。

现役 `consumer.py` 已传入原 `SelectionStore`，reader 核对 date/stage/market/run/algorithm/raw/三件套/输入/owner history。现有 API 的 HK 展示投影允许明确研究结果显示选中数量，现有 Vue 分开显示选中数、行情覆盖、证券资料时间/旧 universe/资格限制以及执行证据。

现有 `/api/v3/workbench/stage` 支持可选 `market`＋`selection_run_id`，只能读配置中的原 SelectionStore，错误 run 返回 404，不能混用 backfill wrapper。`same_run_probe.py` 同时对照精确 run 请求与页面默认请求，避免 API 单独读对而页面仍读别的结果。

金融标志固定为 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。研究调用最终 writer 强制 `MANUAL_CURRENT_DAY_RESEARCH`，外层标签不能改成 NATURAL。

## 验证和现实边界

新代码和测试结果详见 `TEST_RESULTS.md`。A 原本已经运行，这次没有把已有 Top10 说成算法未执行；15:50/15:55 两次旧失败保留“加载版本未确认、处于临时改动窗口”的限制，不能归因于旧六文件。

归档完整组合中，`raw_store.py` 与 `_raw_store_parts/receipt_identity.py` 有新旧关键字签名不匹配。Linux 整链参考测试使用明确的 **仅接受 False、仍执行原严格时间 validator** 的测试兼容层；它没有进入任何业务 after。`SOURCE_GAPS` 一次列出需读回的实际两文件。Mac 独立复跑工具默认关闭这个兼容层，使用其完整实际 RawStore。

本包没有现役整包部署收据、Mac 实采结果或自然触发验收，因此不宣称现役已恢复。原算法文件的公式/排序 SHA、最终候选 source SHA、每项新测试和补丁可逆性均分别记录；旧 Linux 287 和本地 Writer 14 没有计入本轮验收。
