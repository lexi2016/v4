# HK 三套数据与 V4 统一底板审计

审计日期：2026-10-15  
报告状态：`REVIEWED_PASS — CANNOT_CONFIRM`（独立 Reviewer 已核准本报告；只读复算状态为 `TESTED`，复用独立 `PASS_READ_ONLY_VERIFY` 8/8 回执；运行中 API 实际消费绑定仍待确认）  
仓库基线：`55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`  
分支：`codex/system-consolidation-20260912`  
范围：只读审计和迁移方案；本报告不代表迁移已执行。

## 已知结论状态

只读复算已核对三份原件 SHA 和大小，并产出 717 码成员表、逐码日期覆盖、完整代码差集、行字段差异计数和伴随文件元数据；独立 Reviewer 已复核报告并通过，复算沿用此前独立 `PASS_READ_ONLY_VERIFY` 8/8 回执并标为 `TESTED`。A、B 的代码集合都包含于 C，A/B 交集为 597；这只是集合关系。C 只有 1,303 个交易日，而 B 有 2,139 个交易日；共同代码不代表日期、行情值、字段、单位或 PIT 覆盖。迁移未执行；现役 consumer 绑定仍为 `CANNOT_CONFIRM`。

## 数据集清单

路径必须同时记录传入路径和 `resolve` 后路径。不得把配置引用、目录存在或池标签当成实际读取/消费证据。

| 数据集 | 任务标识 | 原始绝对路径 | `resolve` 路径 | 文件/目录格式 | 字节数 | SHA-256 | 行/记录数及口径 | 代码数及口径 | 字段/类型 | 代码日期范围 | 证据文件/命令 | 状态 |
|---|---:|---|---|---|---:|---|---|---|---|---|---|---|
| 旧研究 feature | A / 613 | `/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260722/20260722_20260722_172235_10744/feature.parquet` | 同原路径 | Parquet | 139,225,381 | `1437f5198e6d7a537bc2a11ad17e86042bb9ca2c894ad341126c0a7c05d0052e` | 174,758 行 | 613 | 208 个字段；完整字段名/type 见 `inventory.json` | `asof_date` 20250408–20260721；`trade_date` 20250409–20260722；各 311 日 | SHA 门禁 + 复算脚本；无 code-date 重复 | `RECOMPUTED` |
| 隔夜 `daily_bars` | B / 691 | `/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/versions/20260912/20260912_operator_d1_overnight/daily_bars.parquet` | 同原路径 | Parquet | 17,142,047 | `17f5b62b6ec0264d48b6ee66ce0cd31aa8c1deb661e3e765b90b780add2eb230` | 1,014,835 行 | 691 | 8 个字段；完整字段名/type 见 `inventory.json` | `date` 20180102–20260911；2,139 日 | SHA 门禁 + 复算脚本；无 code-date 重复 | `RECOMPUTED` |
| 现役 runtime panel | C / 717 | `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2/panels/20261014-3958528f3441/hkconnect_vipdoc_daily_panel.parquet` | 同原路径 | Parquet | 21,117,431 | `3958528f34416925df7d5e5ba4bfdde4e92ad35494b1712eacc20013df59cb37` | 460,097 行 | 717 | 32 个字段；完整字段名/type 见 `inventory.json` | `trade_date` 20110208–20261014；1,303 日 | SHA 门禁 + 复算脚本；无 code-date 重复 | `RECOMPUTED` |

实际 key 字段分别为 A `symbol`、`asof_date`、`trade_date`；B `code`、`date`；C `code_norm`、`trade_date`。其它字段名及 Arrow 类型记录在 `inventory.json`。A 的 `asof_date` 和 `trade_date` 是两个独立日期语义，分析时没有把它们压成单一行情日期。逐码覆盖在 `per_code_coverage.csv`，717 行代码成员在 `code_membership.csv`，全量集合差集在 `code_set_differences.csv`，无原始 OHLCV 值的字段差异计数在 `overlap_conflicts.csv`。

每日行数 min/median/max：A 两个日期字段均为 511/560/613；B 为 186/466/691；C 为 1/511/706。各源代码日期键重复数均为 0。末日行数分别为 A `asof_date=613` / `trade_date=613`，B `date=691`，C `trade_date=690`。这些统计描述各原件本身，不证明源间全历史等价。

## 集合差集、覆盖和重叠冲突

代码差集由脚本固定规则复算：trim/uppercase，剥离可选 `.HK`/`HK.` 包装，纯数字代码左补零到 5 位；保留所有不同代码。三个原件均无标准化后 code-date 重复。代码集合结果如下，完整逐码表见 `code_set_differences.csv`。

| 比较 | 交集代码数 | 左侧独有数 | 右侧独有数 | 同代码日期覆盖比较 | 同键值冲突数 | 口径/复算脚本 | 状态 |
|---|---:|---:|---:|---|---:|---|---|
| A 613 ↔ B 691 | 597 | 16 | 94 | A 仅有 16 码；B 仅有 94 码 | 170,145 个 A-asof/B-date 共同键；金额、成交量各 590 行超容差 | 脚本及输入 SHA 在 `audit_manifest.json` | `RECOMPUTED` |
| A 613 ↔ C 717 | 613（A ⊂ C） | 0 | 104 | C 多 104 码 | 174,755 个 A-asof/C-trade 共同键；金额、成交量均无超容差 | 脚本及输入 SHA 在 `audit_manifest.json` | `RECOMPUTED` |
| B 691 ↔ C 717 | 691（B ⊂ C） | 0 | 26 | C 多 26 码 | 437,024 个共同键；6 字段差异计数见下表 | 脚本及输入 SHA 在 `audit_manifest.json` | `RECOMPUTED` |

### 可检查集合明细

- A∩B = A∩B∩C = 597；A 与 B 的并集为 707 码。
- A 减 B（16）：`00909, 01475, 01691, 01773, 02158, 02255, 02291, 02410, 02431, 02562, 02570, 02582, 02587, 02983, 06603, 06955`。
- C 减 B（26）：`00754, 00909, 01475, 01691, 01773, 02158, 02255, 02291, 02410, 02431, 02562, 02570, 02582, 02587, 02627, 02629, 02915, 02922, 02983, 03223, 03228, 06603, 06727, 06955, 09607, 09976`。
- B 减 A（94）和 C 减 A（104）完整逐码清单在 `code_set_differences.csv`；C 减 (A∪B) 另有 10 码，也在同一 CSV。

上述只是代码集合关系，不能推出共同代码各有相同历史行、日期、字段或行情值。完整 A/B/C 同成员矩阵共 717 行，在 `code_membership.csv`。

### 行覆盖差异与字段比较

各源均无重复代码日期键，因此以下 join 数和差集行数对应不同代码日期键，不是去重估算。A 的 join 键明确使用 `asof_date` 对齐 B `date` / C `trade_date`，不将 A `trade_date` 重命名后拼入。

| 对齐键 | 左侧总行 | 右侧总行 | 共同键 | 左侧独有键 | 右侧独有键 | 并集键 |
|---|---:|---:|---:|---:|---:|---:|
| B `code/date` ↔ C `code_norm/trade_date` | 1,014,835 | 460,097 | 437,024 | B 577,811 | C 23,073 | 1,037,908 |
| A `symbol/asof_date` ↔ C `code_norm/trade_date` | 174,758 | 460,097 | 174,755 | A 3 | C 285,342 | 460,100 |
| A `symbol/asof_date` ↔ B `code/date` | 174,758 | 1,014,835 | 170,145 | A 4,613 | B 844,690 | 1,019,448 |

B/C 的 577,811 / 23,073 单边键和 1,037,908 并集为按各自行数减共同键得到的派生计数；不表示合并后的统一底板。按日港股通成员资格也未从这些代码集合推导。

对数值字段按 `rtol=1e-6, atol=1e-6` 做相同行键比较。`overlap_conflicts.csv` 只含每字段的行数/差异计数，不含 OHLCV 值：

| 对比 | 字段 | 共同键/可比行 | 不在容差内 |
|---|---|---:|---:|
| B ↔ C | open | 437,024 | 507 |
| B ↔ C | high | 437,024 | 1,014 |
| B ↔ C | low | 437,024 | 997 |
| B ↔ C | close | 437,024 | 1,178 |
| B ↔ C | amount | 437,024 | 1,355 |
| B ↔ C | trade | 437,024 | 30,337 |
| A `asof_date` ↔ C | `amount_1d` / `amount` | 174,755 | 0（174,754 完全相等，1 仅在容差内） |
| A `asof_date` ↔ C | `volume_1d` / `trade` | 174,755 | 0 |
| A `asof_date` ↔ B | `amount_1d` / `amount` | 170,145 | 590 |
| A `asof_date` ↔ B | `volume_1d` / `trade` | 170,145 | 590 |

B/C `trade` 在 437,024 个共同键中的分组为：两侧非零且完全相等 405,389；C 约为 B 的 100 倍 18,953；两侧非零但不属于上述两组 10,744；两侧均为零 1,298；B 为零/C 非零 11；B 非零/C 为零 629。另有 630 行 B 至少一个 `amount`/`trade` 为正而 C 的两列均为零，其中 2026-07-22 为 622 行、2026-07-06 为 8 行。按 `trade` 与 `amount` 解释出的单位未知，不能批量乘 100 或自动修正。

独立数据审计另报告 A `ret_1d` 与 C `pct_chg×100` 有 49,640 个不近似值；该收益字段的方向、生成时间和 PIT 关系未确认，不与上表原始价量字段作同等语义判断。A 的收益/CCASS PIT 未确认；B 的供应方、币种与量单位，以及 C 的价格币种、`volume_unit_status` 和零成交有效性均 `CANNOT_CONFIRM`。报告不含任何原始行情值。

### 派生文件和历史保全边界

`preservation_inventory.csv` 对 A 的 `label.parquet`、`acceptance.json`、`manifest.json`、`summary.json`，B 的 `operator_feature.parquet`、`operator_label.parquet`、`acceptance.json`、`manifest.json`，以及 C 的 `manifest.json` 记录了路径、resolve 路径、字节数和 SHA-256。脚本只对这些伴随文件计算身份哈希；`parsed=false`，没有读标签内容，也没有创建备份。该清单便于后续保全盘点，但不能称为已备份或历史已归档。迁移前须对原件及这些派生产物建立只读保全点并核对 SHA，未经授权不得移动、覆盖或删除。

## 当前依赖与运行绑定

下表区分已转述的运行观察、配置引用和实际消费。前两者都不能替代一次能绑定输入 `run_id`/SHA 的消费者读取回执。

| 组件/入口 | 已核路径/观察 | 证据含义 | 不能据此确认 | 后续补证 |
|---|---|---|---|---|
| 8873 API 进程 | `com.lexi.v35.api-only`，PID `77916`；cwd 为 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/d1-pool-market-api-20261015-r1/app`；`healthz` 返回 200。 | 主控转交的运行身份证据。 | 健康检查与 cwd 不证明 613/691/717 任一套被读取。 | 如需证明本次读取，补充对应请求/manifest/run receipt。 |
| API LaunchAgent 配置 | `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`，SHA-256 `12a490ba972d71587cbd08dbb3efce4c0582b9478df68ea3c73eed7303969db4`。`V35_APP_ROOT=/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/d1-pool-market-api-20261015-r1/app`；`V35_DATA_ROOT=/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data`；`V35_RESEARCH_DATA_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`；`V35_SHARED_DATA_ROOT=/Users/lexi/Library/Application Support/com.lexi.v4.local/state/workspace/v3_shared_data/.runtime/data`；`V4_MANAGER_SCREEN_AUTHORITY_ROOT` 和 `V4_MANAGER_SECURITY_MASTER_ROOT` 当前均为 `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`。 | 主控已核配置 SHA 与上述白名单路径值；reader 使用 manager 专用根，故这些当前指向 v35 的值优先于已指 V4 的 `V35_SHARED_DATA_ROOT`。目标候选根是已存在的 `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/workspace/v3_shared_data/.runtime/data`。 | 配置绑定不单独证明任一文件在本次 API 请求被打开，也不证明其代码集合口径。`V35_RESEARCH_DATA_ROOT` 指小时资讯/全市场数据根，不应为 HK 迁移直接切换。 | 迁移方案需先复制和验 SHA 全部旧 HK assets 与 security-master 依赖，再将两个 manager 专用根切至 V4 根；回读同 SHA manifest 和 reader receipt。 |
| 当前 release reader/API 代码 | release 根目录 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/d1-pool-market-api-20261015-r1/app`。`v4/manager_workbench/inputs/source_bindings.py:134,146,159`；`v4/manager_workbench/inputs/native.py:545,559-564` 按 manifest 的 `panel_relative` 定位 parquet 并校验 SHA；`apps/api/v35_api/app.py:5235` 绑定 authority root。 | 已核对代码位置和读取合同，可用于追踪实际 panel manifest 到 parquet 的路径。 | 本次未给出/读取对应 manifest 与数据 parquet，故不能把该路径认作 613、691 或 717 的确切绑定。 | 数据代理提供 manifest/data 文件路径、SHA、run_id 和本次 reader receipt。 |
| 工作区规范源码候选 | 已实存候选：`/Users/lexi/Desktop/学习/v4_app/v4/manager_workbench/inputs/source_bindings.py`、`v4/manager_workbench/inputs/native.py`、`apps/api/v35_api/app.py`、`ops/_macos_research_panel_daily_parts/hk_market_capture.py`、`hk_capture_gate.py`。`source_bindings.py` 和 `native.py` 当前为未跟踪文件。 | 这些是后续最小 reader/producer 改动的候选入口；候选源码路径已定位。 | 工作区文件与 installed release 的 SHA/内容等价关系尚未核验；候选路径不代表可直接发布，也不证明部署消费者行为。 | 实施前逐文件比对 installed release SHA、规范源码身份和 Git 跟踪状态，冻结实际最小 diff 与回退。 |
| A/B 输入目录指针 | `/Users/lexi/Desktop/学习/数据/港股/hk_connect_research_panels/CURRENT_HK_CONNECT_RESEARCH_PANEL.txt` 指向 A；`CURRENT_HK_CONNECT_DAILY_BARS.txt` 指向 B。别名 `/Users/lexi/Desktop/学习/数据/hk_connect_research_panels` 是指向该 `港股/` 目录的 symlink；实体目录本身非 symlink。 | 这组指针将两个版本化原件放在同一研究数据根下；脚本直接绑定数据原件 SHA，不通过别名猜路径。 | 目录指针存在/指向不证明现役 API 或阶段 reader 消费 A/B。 | 若迁移要改指针，先比对持久化原件清单并独立审批；本轮未读写或切换指针。 |
| C 当前面板指针链 | `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2/panel_latest.json` → `panels/20261014-3958528f3441/manifest.json` → manifest 的 `panel_relative` 指向本报告 C Parquet。 | 当前版本化 C 原件与共享 `hk_0_2` asset/pointer 路径对应。 | 仍不能由 pointer/code alone 证明 8873 本次研究页/选股阶段实际读取 C。 | 需 API/reader request 的 manifest/run_id/Parquet SHA 消费 receipt 与重载 UI 对齐。 |
| 8873 研究页 | `?date=20261015&view=research` 加载小时资讯路由 `/api/v3/research/lane`，`LIVE_HOURLY` 的 `source_root` 为 `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`。 | 已转交的页面与路由观察，说明该页面所见为小时资讯链路。 | 不证明该页面消费了 613 parquet 或其他 HK 日线池。 | HK panel 页面/API 实际消费回执仍待确认。 |
| Scheduler 进程/producer | `com.lexi.v35.scheduler` PID `84949`；cwd 为 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-pool-fupan-isolation-20261015-r1/app`。已转交 producer 流程：`collect_hk_futu_rows → pack_hk_day → vipdoc/ds/lday/71#*.day → run_hk_0_2_authority`。 | scheduler 与产物生成链的代码/配置线索；产物落到共享 HK authority 根。 | 不能证明 overnight 691 是这条流程的输入或输出，也不能证明 691 已被阶段选股消费。 | 追踪对应日期 run receipt 的实际输入代码、脚本版本、输出 manifest/SHA 与 reader receipt。 |
| Scheduler LaunchAgent 配置 | `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist`；主控只读确认文件存在、SHA-256 `317feeec98a924129f7926488b04a634f48fe6db54e53c32273fd5a4e6781e12`，与 runtime agent 同 SHA。`EnvironmentVariables` 中 `HK_TDX=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/hk_tdx`；receipts 为同一父目录下 `receipts`；HK authority 资产为 `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2`。 | 配置和 runtime agent SHA 相符，路径分属多个根。 | 配置值不证明当前读取的文件、manifest 或目标数据集身份，也不闭合自然时段 producer/consumer 链。 | 追踪对应输入/输出 SHA、receipt、manifest 和 reader 消费回执。 |
| B manifest/acceptance | 主控实读 B 目录 `manifest.json` 与 `acceptance.json`：`generation_id=20260912_operator_d1_overnight`，`status=OPERATOR_D1_RESEARCH_READY`，`published_at=2026-09-12T11:42:49`；manifest note 指其 schema 不同于 canonical 208 列 feature。 | 这是 B 原件声明的生成和发布状态，且它自身声明不等同于 canonical feature。 | `known_limits` 明确：历史港股通资格是“当前 691 只回填”且 `CANNOT_CONFIRM`；官方交易日历 `CANNOT_CONFIRM`（序列由报价派生）；open/close 是否为可成交拍卖价 `CANNOT_CONFIRM`。这些声明不是 PIT 或交易语义认可。 | 将已知限制原样挂入覆盖/准入决策；不能据此把 B 当历史成员权威池。 |
| B producer/consumer 定向搜索 | 主控在 V4 的 `apps/domains/infrastructure/ops/stage_center/v4`、`upstreams/shared_research` 搜索 `CURRENT_HK_CONNECT_DAILY_BARS` 与 `operator_d1_overnight`；在 `/Users/lexi/Desktop/学习/数据/tools`、`/Users/lexi/Desktop/学习/数据/ops`、`/Users/lexi/Desktop/学习/数据/v3_shared_data/scripts` 搜索 `operator_d1_overnight` 生成器，均未定位引用/生成器。 | 仅表示这些明确搜索范围内未定位 B 的现役 consumer/producer。 | 不扩展为整台 Mac 无引用或无人使用；691 的实际 consumer/producer 与阶段输入绑定仍未知。 | 由 owner 提供 B 生成 receipt、consumer 请求与实际 manifest/SHA 证据；登记搜索边界。 |
| 旧 HK assets/pointers | `assets/hk_0_2/panel_latest.json`；`assets/hk_0_2/daily_supplements/pointers/{day}.json`。 | 有已核的资产/pointer 路径线索，可按 manifest 继续定位。 | daily supplements pointer 与三套数据的具体关系仍未绑定；存在不证明 API 已读取。 | 读取实际 pointer 目标、manifest、data parquet 和当前请求 receipt。 |
| HK 收盘回执 | `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/receipts/hk-20261014.json`；SHA-256 `8bb35cc73dbac6e326c235a9246a57a6817388f0522f0aa195e23c219bfff988`；mtime `2026-10-14 17:20:03.559706+08`；`READY`，`target_date=20261014`，`row_count=690`，`coverage_rate=1.0`。 | 回执身份、摘要与状态已由主控转交核实。 | 不能据此推断其与 717 相等、691 定义相同或 2026-10-15 已有自然槽结果。 | 需与该回执的 producer 版本、输入清单、manifest/data SHA 做绑定。 |
| 2026-10-15 自然槽 | 检查时目标收盘槽尚未到。 | 尚无该日自然槽结果。 | 不按尚未到时的缺文件判故障。 | 到期后由主控按自然时段证据独立验收。 |
| Manager HK panel reader | 当前代码路径通过 manifest 的 `panel_relative` 定位 parquet 并校验 SHA；旧 HK authority assets/pointers 路径见上。 | reader 实现和配置依赖位置已可追踪。 | 未提供该 reader 当前请求实际绑定的 manifest/data SHA，故消费状态仍未知。 | 当前请求/reader receipt 与实际目标 parquet 的 SHA、run_id。 |
| 旧 daily incremental 产物 | `/Users/lexi/Desktop/学习/数据/stock_research_panels/hkconnect_tdxpy_daily_incremental/RUN_HKCONNECT_DAILY_INCREMENTAL_V1_20260901T135803Z` 被独立审计判为 652 码、`DIAGNOSTIC_ONLY` / `PARTIAL_CANNOT_CONFIRM`。 | 有已知的非完整候选产物状态。 | 不能替代 C 的 717 码 runtime panel，也不能补齐当前业务合同。 | 不纳入本次三套源，也不作为迁移 fallback。 |
| Stage-center | 检查时无 PID。 | 仅记录该次检查未观察到 PID。 | 不据此判定系统故障。 | 若迁移方案需要其消费，先确认 owner、职责和有效调用。 |

以上精确依赖来自主控转交的已核配置、代码行、B manifest/acceptance 和 receipt 身份；本 Writer 未读取任何配置凭证。已能确认 V4 目标共享根和工作区源码候选，但本次 manager reader 的 manifest/data SHA 消费 receipt 未提供，所以“实际 reader 已读取 613/691/717 中哪套”及“691 现役精确数据依赖”仍为 `CANNOT_CONFIRM`。主控搜索的列明目录未定位 691 consumer/producer；这不代表全盘无引用。API 配置引用、候选源码文件和 reader 路径都不等于本次请求已消费对应文件。

## 为什么不能直接 union 替换

复算已直接观察到集合和行覆盖差异，以及共同键的字段差异：A/B 代码集合不相同；B/C 有 577,811 个仅 B 的代码日期键和 23,073 个仅 C 的键；B/C 六个日线字段均存在超容差行，`trade` 超容差 30,337 行；还观察到量字段非零值存在约 100 倍关系和 C 两字段均为零的行。它们是需要解释的差异，不能据此判断哪套源错误或自动修正。以下事项仍是待验证的迁移约束：

- 613、691、717 的来源、生成时点、代码规范、证券身份和历史成员资格尚未完成逐项对账；相同代码集合并不代表同一时点或同一证券身份。
- 717 是现役日线池标识，不足以证明该池在过去日期就是当日港股通成员。历史资格必须按实际生效日期映射，代码变化要保留可追溯的 security identity。
- 独立依赖审计指出 691/717 代码集中含 ETF 和临时类代码；该观察不提供每日港股通成员身份，不能把池标签直接解释为历史资格。
- 来源、PIT、复权口径、量价单位或字段语义若未确认，应隔离并保留查询能力，不能无痕转成权威字段。
- 特征、标签和实验副本属于可追溯派生产物；含未来信息的字段不得流入阶段选股输入。
- 粗放拼接会让重复键覆盖、历史日期缺失、旧码误并或来源优先级被隐式决定；须先生成全量差集和按键冲突账本，再定义显式、可回退的解析规则。
- 同一研究入口要求统一 V4 用户面板和既有权威 producer/版本化数据合同；不能用另一个临时底板或第二 producer 填补证据缺口。

因此不直接 union 替换：这会把尚未解决的代码日期覆盖、字段差异、来源和单位语义一并固化为隐式规则。

## 建议迁移方案（全部尚未执行）

目标根已由主控核定：复用现存 `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/workspace/v3_shared_data/.runtime/data`，HK authority 沿用其 `assets/hk_0_2` 版本化 manifest/pointer 合同；不新建面板或 producer。旧 C authority 根 `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2` 保持原样可回退，包含 `panel_latest.json`（当前观察目标为 `panels/20261014-3958528f3441/manifest.json`）、全部 `panels/` 和 manifests、`daily_supplements/` 及 pointers、raw caches。迁移采用复制和逐文件 SHA 核验，禁止目录 rename、覆盖或静默 coalesce；目标根已有同名不同 SHA 时先隔离并停止，不覆盖。

A/B 原件及其 feature、label、manifest、acceptance、summary 继续作为不可变历史输入，并逐条登记 provenance；若后续需要研究特征或标签，应作为版本化研究资产挂接，不混入阶段日线输入。所有字段/行冲突未裁决前保留来源并隔离。B 独有 577,811 个键与 C 独有 23,073 个键先进入独立覆盖账本，之后才审议 canonical admission。候选源码路径已定位但未证明与 installed release 字节等价；精确最小 diff、发布可用性和个人 owner 尚未确认。以下使用职责 owner，人员由主控安排。

### Manager shared-root 切换的非 HK/A 硬门

`V4_MANAGER_SCREEN_AUTHORITY_ROOT` 和 `V4_MANAGER_SECURITY_MASTER_ROOT` 指向整个 manager shared root，不是 HK 专用子目录。切换会影响旧 root 下所有直接或间接引用的数据，不能只审 HK asset。阶段 0 必须形成完整依赖清单，逐项列出源路径、资产身份、直接/间接 pointer/manifest/raw 依赖、消费者、拟定 V4 target 路径、源文件 SHA 和捕获副本 SHA；范围包括所有非 HK/A 资产及证券主表。切换后逐项确认这些非 HK/A 引用资产的 manifest/文件 SHA 与旧根读回逐字节等价，并确认相应消费者结果不变。

若完整清单、等价核验未完成或任一非 HK/A 依赖仍未知，manager root 切换门不通过：保持两个 manager key 的旧值和旧 pointer，仅可在 V4 根生成不接入 manager reader 的隔离 HK 版本；不得借 HK 迁移扩大或重定向 A 股范围。`V35_RESEARCH_DATA_ROOT` 全程保持原值。只有非 HK/A 硬门、HK canary 和全量对账全部通过并取得所需授权后，才进入阶段 4。

| 阶段 | 目标与动作 | Owner（角色/姓名） | 预期修改文件/工件 | 验收信号 | 回退与历史保全 | 状态 |
|---|---|---|---|---|---|---|
| 0. 归档和冻结输入 | 对旧 C authority 全树、V4 目标根现存内容、security master、scheduler 的 `HK_TDX`/receipt roots，以及 A/B 原件和全部伴随物做逐文件清单、大小/SHA、pointer/manifest/raw 依赖关联。另对两个 manager shared roots 的完整依赖闭包登记所有非 HK/A 资产及证券主表；逐项记录源路径、直接/间接依赖、消费者、拟定 V4 target、源 SHA、捕获副本 SHA。将 C panels/manifests/supplements、raw caches 和所需 security-master assets 复制到 V4 根的版本化候选位置；旧 v35 原件保持原位。 | 数据 owner + V4 数据 owner + HK producer owner；非 HK/A 消费者 owner 提供依赖闭包。 | 清单列出每项资产的身份、源/target、SHA 和 consumer；拟保全目标在 V4 `.runtime/data/assets/hk_0_2` 及版本化子目录；archive run_id 执行前冻结。 | 完整依赖清单中每项有源/target、源/捕获 SHA 和消费者；pointer/manifest/raw closure 可追溯；同名同 SHA 才可去重；异 SHA 隔离；manager root 下无未登记非 HK/A 引用项。 | 不覆盖 V4 根既有字节、不 rename 旧树；冲突或任一非 HK/A 依赖未知即停止，不切 manager roots。旧 C 根、全部版本、A/B feature/label/experiment、证券主表、manifests/receipts/raw caches 保持可查。 | `NOT_RUN` |
| 1. 单码 canary | 选有 security identity 与成员生效日期证据的一码一段窗口，验证来源、PIT/复权、币种/量单位和零成交语义；使用现有唯一 producer 生成独立版本，不能由代码数直接推断历史资格。 | HK producer owner + 数据来源 owner + V4 data owner；Reviewer 复核结果。 | producer 候选：`/Users/lexi/Desktop/学习/v4_app/ops/_macos_research_panel_daily_parts/hk_market_capture.py`、`hk_capture_gate.py`；版本化 canary 输出位于 V4 `assets/hk_0_2` 下新版本，不改 active pointer。 | 输入、producer 版本、manifest/run_id/SHA、逐字段语义及 V4 reader receipt 闭环；无未来标签/特征进入阶段输入。 | 失败仅保留隔离 canary 和 receipt；active pointers 与两套旧根不变；不删除或覆盖输入。 | `NOT_RUN` |
| 2. 全量对账与准入 | 按 security identity 和交易日合同复核全量日期覆盖、重复键及字段语义；给每个来源/字段标记 canonical、挂接研究资产或隔离，未知项保持 `CANNOT_CONFIRM`。 | 数据 owner + V4 数据 owner；独立 Reviewer 审账。 | 本审计差集/覆盖/冲突清单为输入；另建带版本/SHA 的 provenance 与决策账本。A/B features/labels 只作为版本化研究资产候选。 | 每个单边键和冲突均有可追溯 disposition；B-only 577,811、C-only 23,073 键原样保留，未裁决冲突无 silent coalesce；复算可重现。 | 原始 A/B/C 和派生资产只读；未知/淘汰项留在历史可查询区并保留原始 SHA。 | `NOT_RUN` |
| 3. Producer 输出接入 V4 HK asset | canary 及全量语义门通过后，让唯一既有 producer 继续消费已归档的行情采集输入，并把新版本输出写到已存在 V4 `.runtime/data/assets/hk_0_2` 合同。初期只将 scheduler 的 `HK_ASSET` 输出根定向到 V4；`HK_TDX` 和 `RECEIPT` 继续使用其当前 v35 输入/回执路径，只有逐文件归档并证明无缺依赖后才可另行切换。 | HK producer/scheduler owner + V4 数据 owner。 | producer 候选 `ops/_macos_research_panel_daily_parts/{hk_market_capture.py,hk_capture_gate.py}`；scheduler LaunchAgent `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist`；目标 `...v4.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2`。 | 新版本 manifest/pointer 包含来源、日期、代码、run_id、producer、SHA；旧 receipt/raw input 可追溯；一份输入仅由既有 producer 产出。 | 先保留旧 `HK_ASSET` 值、旧 pointer 和旧全树；验证失败恢复旧 `HK_ASSET`/pointer。`HK_TDX` 与 `RECEIPT` 未授权或未归档不改。 | `NOT_RUN` |
| 4. Manager API consumer 切换 | 这一步切换整个 manager shared root。只有阶段 0 完整依赖闭包清单无未知项、所有非 HK/A 资产（含间接 pointer/manifest/raw 与证券主表）已复制并 SHA 校验后才可切换；任一非 HK/A 项无法盘点或验证，则禁止切两个 manager roots，继续旧根或仅生成不接入 manager 的隔离 HK 版本，不扩大 A 范围。 | V4 API/manager owner + security master owner + 各非 HK/A consumer owner；主控准入。 | `/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist` 中 `V4_MANAGER_SCREEN_AUTHORITY_ROOT` 和 `V4_MANAGER_SECURITY_MASTER_ROOT`：两者旧值均为 `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`，目标均为 `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/workspace/v3_shared_data/.runtime/data`。保持 `V35_RESEARCH_DATA_ROOT=/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data` 原值不变。 | 配置 readback 两键指向目标根；所有旧根非 HK/A 引用资产的 manifest/文件 SHA 与捕获副本、旧根读回逐字节等价；相应非 HK/A consumer 结果不变；HK manager reader 返回目标同 SHA manifest 与新 reader receipt。 | 仅在所有门禁通过并另行获准后进行本地 API reload。任一依赖未知、SHA 不等或 consumer 结果变化即不得切换；失败时恢复两个 manager keys 的精确旧值，以及旧 C `panel_latest.json` 原始字节/指向（阶段 0 捕获其 SHA；原观察目标为 `panels/20261014-3958528f3441/manifest.json`）。`V35_RESEARCH_DATA_ROOT` 不变；两根全部数据保留。 | `NOT_RUN` |
| 5. V4 页面与 API 验收 | 在统一 V4 入口通过同一 consumer 重载，核对请求、manifest、API 和页面版本；当前小时资讯页不当作 HK panel 消费证据。 | V4 API owner + 页面 owner；独立 Reviewer 复核。 | 候选 reader/API：`/Users/lexi/Desktop/学习/v4_app/v4/manager_workbench/inputs/source_bindings.py`、`v4/manager_workbench/inputs/native.py`、`apps/api/v35_api/app.py`。候选与 release SHA 等价/可发布尚未确认，执行前冻结最小 diff。 | API、reader 和重载页显示同一 run_id、来源、日期、输入 SHA 和实际完整输入计数；展示截断不截断选择输入。 | 检查失败恢复旧两个 manager 根值和旧 pointer；保留新版本和失败 receipt，旧页面/数据可读。 | `NOT_RUN` |
| 6. 自然时段验收 | 在港股目标自然槽由既有 producer 生成并追踪至 API/UI；离线回放、healthz 或单行展示均不能代替。 | Producer owner + V4 API/UI owner + 独立 Reviewer。 | 不预设新增源码；任何修复另行冻结路径/范围。 | 自然槽 receipt、生产者、输入/输出 SHA、manager consumer、重载页面完整链一致。 | 失败恢复旧 manager 根值与 pointer；保存所有新旧版本和证据；不删除历史。 | `NOT_RUN` |
| 7. 旧路径退役裁决 | 依赖清零、迁移审查与自然时段验收后，仅提交旧根/旧 reader/旧 producer 退役方案供明确授权。 | 主控 + 旧 producer owner + V4 owner。 | 旧 v35 assets/panels/manifests/supplements/raw cache、API plist 与 scheduler LaunchAgent；本次不改。 | 明确生命周期、保留期限、数据可查、恢复步骤且单独授权/审查通过。 | 在退役裁决前长期保持旧根、旧 pointer、原始输入/标签/特征和回执完整可读。 | `NOT_RUN` |

本任务未获得执行上述阶段或退役旧 producer 的授权。该表是后续评估用方案，任何实际写入、pointer 切换、服务/计划任务操作都不属于本次交付。

## 可复算回执

| 项目 | 命令/路径 | 输入 SHA | 脚本 SHA | 输出 SHA | 结果 |
|---|---|---|---|---|---|
| 数据路径与元信息清点 | `recompute_hk_pool_audit.py --write-dir <本审计目录>` | A/B/C 见 manifest | `b338c936117b9a48142dc649a30eeb71348c85c4c7fcb1a2bbd8bffdcdf6fbad` | `inventory.json` SHA 在 manifest | `PASS_READ_ONLY_AUDIT_WRITTEN` |
| 逐代码覆盖与成员导出 | 同一只读复算命令 | 同上 | 同上 | `per_code_coverage.csv`、`code_membership.csv` SHA 在 manifest | 717 码；逐字节校验通过 |
| 代码差集和重叠冲突 | 同一只读复算命令 | 同上 | 同上 | 差集与冲突 CSV SHA 在 manifest | `--stdout` `PASS_READ_ONLY_VERIFY`；8/8 |
| 迁移、切换或回退 | 本任务禁止执行 | — | — | — | `NOT_RUN` |

实际执行环境：Python 3.13.12、pandas 2.3.3、NumPy 2.5.2、PyArrow 23.0.1；解释器为 `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/runtime/venvs/v3.5-hk02/bin/python`。完整复算脚本为 `recompute_hk_pool_audit.py`，脚本 SHA 和三份输入 SHA 记录在 `audit_manifest.json`。

| 项目 | 实际命令 | 输入 SHA | 脚本 SHA | 结果 |
|---|---|---|---|---|
| 写出只读审计元数据 | `<解释器> -B docs/handoffs/hk_data_unification_audit_20261015/recompute_hk_pool_audit.py --write-dir docs/handoffs/hk_data_unification_audit_20261015` | A/B/C 见 manifest | `b338c936117b9a48142dc649a30eeb71348c85c4c7fcb1a2bbd8bffdcdf6fbad` | `PASS_READ_ONLY_AUDIT_WRITTEN`；8 项可复算产物 |
| 只读重算并逐字节核对既有输出 | `<解释器> -B docs/handoffs/hk_data_unification_audit_20261015/recompute_hk_pool_audit.py --stdout` | 同上 | 同上 | `PASS_READ_ONLY_VERIFY`；8/8 产物一致；未写文件 |
| 输出身份 | `audit_manifest.json` | 同上 | 同上 | 输出 SHA/字节数记录于 manifest；manifest 本身 SHA 在交付回执记录 |
| manifest 本身 | `audit_manifest.json` | — | — | `eaa3121ddcac50631fe7d55a2870b1fb439bbf58caa18895784412f6ac15d589` | SHA-256 |

上表中的 `<解释器>` 指上一段列出的完整 Python 绝对路径。实际执行命令为：

```sh
'/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/runtime/venvs/v3.5-hk02/bin/python' -B docs/handoffs/hk_data_unification_audit_20261015/recompute_hk_pool_audit.py --write-dir docs/handoffs/hk_data_unification_audit_20261015
'/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T081111Z-v35-strict-stage-acquisition-v15/runtime/venvs/v3.5-hk02/bin/python' -B docs/handoffs/hk_data_unification_audit_20261015/recompute_hk_pool_audit.py --stdout
```

脚本没有导出原始行情行；`--write-dir` 只接受审计目录，`--stdout` 只在内存中重算并比较已写产物。

## 交付与验收回执

| 项目 | 状态 | 证据/说明 |
|---|---|---|
| 冻结范围与交付材料 | `REVIEWED` | `SCOPE.md`、本报告及 `REVIEW_RECEIPT.md`；独立 Reviewer 最终 receipt 为 PASS。 |
| 三套数据路径、SHA、大小、真实字段与覆盖 | `REVIEWED` | `inventory.json`、SHA 门禁及独立复核。 |
| 完整代码差集与重叠冲突 | `REVIEWED` | 差集/覆盖/冲突 CSV 与独立复核；B/C 并集为 1,037,908。 |
| 只读复算 | `TESTED` | 复用此前独立 `PASS_READ_ONLY_VERIFY`；8/8 产物逐字节一致；本次状态归档未重跑。 |
| 当前依赖表及 691 精确消费链 | `CANNOT_CONFIRM` | 已有转述只提供配置/运行线索，缺实际 reader receipt。 |
| 迁移实施 | `NOT_RUN` | 本次只形成方案。 |
| 独立 Reviewer | `REVIEWED_PASS` | 首轮两项 P2、第二轮剩余一项 P2 均已闭环；最终 receipt 见 `REVIEW_RECEIPT.md`。 |
| 源码/业务配置/数据/pointer/服务/计划任务改动 | `NOT_RUN` | 本 Writer 的允许路径仅本目录。 |
| commit/push | `NOT_RUN` | 本任务明确禁止。 |

### CANNOT_CONFIRM 清单

- 三套代码是否代表按日期生效的港股通成员身份；证券身份历史映射与 A 的 PIT/CCASS 语义。
- 行情来源与供应方、币种/复权/成交量单位；C 中两字段同为零是否代表有效零成交。
- 691 的现役 producer、准确输入、reader、manifest/run_id/SHA 与阶段选股消费绑定；主控的定向搜索只覆盖依赖表列出的目录，不能推断全盘无人使用。
- 已定位的工作区源码候选与 installed release 之间的逐文件 SHA/字节等价关系、source_bindings/native 的规范 Git 身份及可直接发布性。
- 配置引用是否在本次请求被实际加载，以及研究页之外的 HK 数据是否被当前 API/UI 消费。
- HK producer/consumer 的自然槽 receipt；自然时段验收及后续退役需另行评审/授权。
- 伴随 labels/features 和原始历史产物的真实备份/归档尚未执行；当前清单仅记录其 SHA 与大小。
