# 本地 V4 研究面板只读合同

这是本地适配指令，不是新的数据源或 producer。只读取现有面板；不导入
`modules`，不调用 `zt`，不运行采集、同步、账户、通知或服务。

## 输入与适用范围

- 明确 `market`、`asof`、`ts_code`、用户展示窗口、所需指标和复权要求。
- 当前核验合同仅覆盖 `market=A_SHARE`；代码形式为 `000001.SZ`、
  `600000.SH`、`920146.BJ`。不要自行跨市场改写代码。
- 未显式选择 profile 的一般行情研究继续使用当前实际 **RAW 不复权** 口径并明确标注。
  仅 Z哥图形读取可显式请求 `FUTU_QFQ_ASOF`。该 profile 初始只覆盖
  `002612.SZ`、`001283.SZ` 和精确 `asof=20261023`，仅支持调整后 OHLC、BBI、
  `zge_white_line`、`zge_yellow_line` 与 `ma60`；不提供 `J`、B1/B2/B3、成交量或其他
  RAW 标签的 QFQ 声明。无覆盖、缺缓存、asof 不一致、profile/source/factor/cache SHA
  冲突时必须 fail closed，不能回退到 RAW，也不能把 RAW 改名 QFQ。
- 这是绑定同一 RAW selector 行的 **chart-only 派生视图**，不是完整 QFQ 面板、
  新数据 authority 或新的 producer。因子在 2026-10-24 观察，图形 asof 为
  2026-10-23；effective-date cutoff 不证明历史可得性。历史 PIT 未认证，不得用于
  PIT 回测、选股或收益评价。

## 权威入口与身份

当前 scheduler 的数据根为：
`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据`。
这是当前 V4 运行时绑定的共享研究数据位置，不是旧 V3 源码运行授权。

**默认优先读取已有指标与完整信号标签**，selector 入口为：
`data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt`。
已有 `DATA_LAYER_INTERFACE.py` 的纯读函数：
`load_selector_ready(columns=None, start_date=None, end_date=None, ts_codes=None, filters=None, panel_path=None)`。
用 columns 投影和 filters 精确读用户股票/日期，不重新计算已有指标。
其旧 Windows 元数据/文档不能作为当前认证，实际 schema 与当前机器合同优先。

深历史辅助入口为：
`backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt`。
先按 `utf-8-sig` 读取 pointer，再打开其指向的 parquet；不要猜日期目录或硬编码
parquet 目标。深历史读取已有指标列与 OHLCV 供图形/复核，不借此重建缺失标签。
完整历史接口目录当前没有 `BACKTEST_PANEL_INTERFACE.py`，不要编造导入。

当前面板日期、状态、覆盖和 SHA 均为动态值，不在合同中固定为旧日期或旧 receipt。
每次读取从当前 selector pointer 解析实际 parquet，再绑定 footer 日期、同日 receipt、
manifest 和当前 run_dir；身份无法绑定时停止。最近一次已记录的观察是 2026-10-24：
pointer 指向 D23，receipt 状态为 `PARTIAL`，accepted=5496/5800、quarantine=304。
此观察可能过期，不能替代查询时的动态读回。

这些是身份/producer 层证据；读取时不重新全盘计算面板 SHA 或开启全量 passport
审计，不把 receipt 声明 SHA 称为本次重算 SHA。publication/PIT vintage 与完整市场
QFQ 认证为 `CANNOT_CONFIRM`；`formula_authority_status=PASS` 不能抹去整体 PARTIAL。
新版本按现有 passport/FAST_BIND 规则核验变化；身份无法绑定时停止该次读取。

动态绑定顺序：

1. 解析 pointer 后，用现有 pyarrow 读取 parquet footer 的 row-group
   `trade_date` 最大值，归一成 `YYYYMMDD`，得到 `panel_target_date`。
   文件名 `_current_to_(YYYYMMDD)` 只能作候选，必须与 footer 一致；
   不任取路径里的日期。
2. 读取 `receipts/a-{panel_target_date}.json`。其顶层 `backtest`（完整历史）
   或 `selector`（selector 读取）为绝对路径字符串，必须与本次解析目标一致；
   `target_date` 必须与 footer 一致；同时读取对应 `*_sha256`。
   本地历史查询 `query_asof` 与版本截止 `panel_target_date` 是两个值。
   历史查询仍绑定当前 panel receipt，不能换成 `a-{query_asof}.json`。
3. `run_dir=receipt['formula']['run_dir']`；可与
   `receipt['formula']['authority']['run_dir']` 校验一致。不得硬编码历史日期目录；只读该目录的已有
   `promote_manifest.json` 和 `promoted_parquet_quick_audit.json`，
   校验当前版本身份，不重新生产数据。
4. 这些 receipt 可能较大。仅摘要所需字段与单股记录，不输出原始 JSON。
   任何缺失、冲突或无法归一的日期返回 `CANNOT_CONFIRM_LINEAGE`；
   不选择另一个历史 receipt 凑匹配。

## 单股 accepted / gap

当前单股状态从原 producer 输出读取，不能根据“parquet 有历史行”推断 accepted。

- `receipt['reconciliation']['symbols']` 是5800条对象，字段包括
  `symbol`（六位）、`market`、`classification`、`quarantine`、
  `fetch_status`、`last_date_after`、`path`。
- 可复用较小的原 producer CSV：
  `Path(receipt['sync']['authority']['run_dir']) / 'file_results.csv'`。
  路径随当前 receipt 动态解析，不硬编码历史 run 目录。
  按 symbol 与市场精确匹配；已证 `.SZ -> market=0`、`.SH -> market=1`。
  京市映射不得仅凭数字猜，未核实则返回具体映射缺口。
- Accepted-only manifest 是 `receipt['sync']['formula_input_manifest']`；
  每次读取都按当前 receipt 核对其 `files` 对象及字段
  (`path/relative_path/sha256/fetch_status`)，不沿用历史文件数。
  核对单股的原始 `.day` 路径与来源 SHA，不只按文件名后六位模糊匹配。
- 以下是 2026-10-22 的历史单行示例，不代表当前单票状态：000001.SZ 曾为
  `classification=ACCEPTED`、`quarantine=False`、
  `fetch_status=OK`、`target_date_ready=True`、`last_date_after=20261022`、
  `status=UPDATED`；原输入为 `vipdoc/sz/lday/sz000001.day`，
  SHA-256=`9a48b32aa777308c210734171db744c42903715eaaca1b4c690b034b5121042c`。
  此 producer 的 run_id=`20261022-e663c5e385206afd-1792659603983625000`。
- manifest 缺席不等于停牌或无行情，必须查分类；`QUARANTINED`、`PENDING`、
  缺项、歧义或字段矛盾均返回具体 `CANNOT_CONFIRM`。
  当前 accepted 也不认证历史 asof 的 PIT 可得性。

## 已计算指标与标签优先

当前 selector 有207列，backtest有57列。每次先检查所读 parquet 的真实 schema，
投影当前问题所需的最少列；缺列不是重新算指标的默认触发器。

| 内容 | Selector 已有列 | Backtest 边界 |
|---|---|---|
| BBI、黄白线、J | `BBI`、`zge_white_line`、`zge_yellow_line`、`J`（double） | 已有 `bbi`、`white_line`、`zge_white_line`、`yellow_line`、`zge_yellow_line`、`J`、`zge_j`（float32），按实际 schema 选取，不能只凭别名断言语义等同 |
| KDJ 与 RSI | `kdj_k`、`kdj_d`、`zge_rsi3` | 已有 `K`、`D`；实际列含义以原字段合同为准 |
| MACD 数值 | `macd_dif`、`macd_dea`、`macd_hist`（double） | 同名列及 `macd_bar` 为 float32；具体语义按原字段合同 |
| 均线 | `ma3/ma5/ma6/ma10/ma12/ma14/ma20/ma24/ma28/ma30/ma40/ma57/ma60/ma114` | 有已有均线列及 `ma250`，不要从 OHLCV 重建现成列 |
| B 系列 | `B1`、`B2`、`B3`、`BG`（int8） | 没有 B1/B2/B3/BG；深历史要求这些标签时报告缺口，不用 OHLCV 伪造 |
| 突破/交叉 | `breakout`、`double_breakout`、`break_prev_high`、`white_yellow_death_cross` | 是否存在逐列检查，不假定两层 schema 相同 |
| MACD 形态 | `macd_below_zero_second_gold`、`macd_above_zero_second_gold`、`macd_top_divergence`、`macd_bottom_divergence` | 按原 schema 与合同消费，不替换成自算版本 |
| 砖形与买卖标签 | 实际 `brick_*` 列，以及 `primary_buy_signal`、`secondary_buy_signal`、`sell_signal` | 不给缺失标签造平行 producer |

上表斜线只是列名分隔符，不是一个列名。其他形态字段也必须先查真实 schema；
旧文档中的 `GOLD_BRICK`、`JINZHU`、`b123_score` 当前不存在，不得捏造。

当前原面板的 `formula_source='computed_main_chart_formula_20260515'`，
`field_contract_version='authoritative_field_contract_v0_2_phase1'`。
原合同将 B1/B2/B3/BG 定义为 **context_only 兼容标签**；保留这个命名空间与原值，
不覆盖为上游 skill 的同名定义，不改成评分真值或 BUY 建议。
这些版本也不认证与用户 Futu 公式完全等价。

已核的 canonical producer 由当前 scheduler 的
`V35_RESEARCH_PANEL_A_CANONICAL_FORMULA` 绑定，当前路径：
`/Users/lexi/Library/Application Support/com.lexi.research-panel.local/releases/20260821T073000Z-v35-hk0920-materialization-bridge/app/runtime/v1/build_canonical_formula_research_panel.py`，
SHA-256=`074a038699eae84d093602ee6df551b5279368c5800ad78067902a496c990258`。
同目录 `authoritative_field_contract_v0.csv` 的
SHA-256=`feb845426d7d37aaf63791ff1c799b575b36821d647d0977b890c0b4389b583c`。
该 CSV 对 B1/B2/B3/BG 标记 `allowed_in_current=yes`、
`allowed_in_scoring=no`、`context_only`。

原 producer 的口径为 BBI=(ma3+ma6+ma12+ma24)/4、
white=EMA(EMA(close,10),10)、yellow=(ma14+ma28+ma57+ma114)/4。
这里只说明字段含义，不要求重新计算。合同认可的别名仍须在真实 schema 中存在，
不能为让上游代码运行而复制/重命名/覆盖原值。

已读取的现成单行示例（000001.SZ，20261022）：
`BBI=11.4875`、`zge_white_line=11.5483339548`、
`zge_yellow_line=11.4522384085`、`J=5.9918373329`、`B1/B2/B3/BG=0`。
同一行 `macd_dif=-0.043140396`、`macd_dea=-0.0133164763`、
`macd_hist=-0.0596478394`、`breakout=0`、`primary_buy_signal=0`。
这是原面板值的读取证据，不是本 skill 的重新计算或策略有效性验证。

## Schema 与日期

完整历史 OHLCV 辅助列为 `ts_code, trade_date, open, high, low, close, vol,
amount, pct_chg, market_type, exchange, source`。
backtest 的 `trade_date` 是 `YYYYMMDD` int32，OHLC/vol 为 float32；
selector 的键为 `ts_code:string`、`trade_date:string`（YYYYMMDD），
**没有 `date` 列**；`volume` 为 int64、OHLC 为 float64。
selector 有 `market_type/exchange/name/formula_source/field_contract_version`
字符串列，**没有 `source` 列**；backtest 有 `source` dictionary string，
但没有 `name/formula_source/field_contract_version`，需从对应 producer/字段合同
与 receipt 绑定其元数据，不伪造不存在的行字段。
两者必须区分；不能直接把 selector 的大小写/别名列用于 backtest。

- `market_type=A_SHARE`；native `vol/volume` 单位为 **股**，`amount` 为 **元**。
  不除以 100、不乘以 1e4。上游 `dict_to_daily` 直接使用 `row['vol']`。
- 完整 backtest 当前 footer 日期范围为 2021-05-06 至 2026-10-22；
  单票覆盖不同。000001.SZ 当前可得 1264 根，自 2021-08-02 起；
  不能声称上市全历史。
- 默认直接读取指定日/窗口的现成指标与标签，不因展示窗口截断而重算。
  只取 `<=asof` 已有值，不读未来行参与分析。需要辅助 K 线时读原 OHLCV。
  用户另行明确授权新特征研究时，才冻结隔离派生合同；该研究需读取完整可得
  prefix 做 warmup 后再裁窗口，不能覆盖原有列/标签或另建 producer。
- 显式区分 requested asof、实际最后一行日期、数据版本截止。asof 无精确日行
  返回 `STALE_OR_MISSING_ASOF`，不静默换为上一行或抓取补齐。
  用户明确要求“截至非交易日的最后交易日”时才按该语义查已知日历，显示两日期。
- 缺列、缺代码、重复 key、无效值/单位/市场、现成指标为空或隔离/accepted
  身份未确认时，输出具体缺口和 `CANNOT_CONFIRM`，不编造指标或自动更换数据源。

## 复用现有读取配方

解释器使用已验证的 V4 运行环境：
`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python -B`。
不安装上游包。下面是完成上述身份与单股状态检查后的默认单日指标/标签读取形式；
`query_asof`、`code` 来自用户任务，不能默认为“今天”或固定示例股票。

```python
from pathlib import Path
import importlib.util
import pyarrow.parquet as pq

data_root = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据')
interface_dir = data_root / 'data_layer_interface_current'
pointer = interface_dir / 'CURRENT_SELECTOR_READY_PANEL.txt'
panel = Path(pointer.read_text(encoding='utf-8-sig').strip())
# Before this read: bind panel footer/receipt/manifest and exact stock acceptance above.
# query_asof is an explicit YYYYMMDD string; code is an explicit ts_code string.
columns = ['ts_code', 'trade_date', 'exchange', 'market_type', 'BBI',
           'zge_white_line', 'zge_yellow_line', 'J', 'B1', 'B2', 'B3', 'BG',
           'formula_source', 'field_contract_version']
names = set(pq.ParquetFile(panel).schema_arrow.names)
missing = sorted(set(columns) - names)
if missing:
    raise ValueError(f'CANNOT_CONFIRM_MISSING_PANEL_FIELDS: {missing}')
spec = importlib.util.spec_from_file_location(
    'v4_existing_selector_reader', interface_dir / 'DATA_LAYER_INTERFACE.py')
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)  # Existing pure-read interface, not upstream modules.
df = reader.load_selector_ready(
    columns=columns, panel_path=panel,
    filters=[('ts_code', '=', code), ('trade_date', '=', query_asof)],
)
# Require one matching key, A_SHARE and valid existing values; no row => missing/stale.
# Return panel values unchanged with the bound quality/provenance summary.
# For a requested series, filter the explicit date window; do not recalculate columns.
```

### 显式 Futu QFQ 图形 profile

只有用户明确要求 Z哥图形与 Futu 前复权一致时，才使用此 profile。它只接受其
manifest 声明的股票及 `asof_date`；当前为两票 D23。profile 和 derived cache 必须
同时绑定本次解析出的 selector parquet SHA、Futu factor metadata SHA、缓存 SHA、
固定公式 SHA 与用户公式 SHA。未缓存代码、未来/过期 asof、缺少因子、来源或哈希
冲突均返回错误/`CANNOT_CONFIRM`，不退回 RAW。

```python
# query_asof 必须是用户指定日期；先解析当前 pointer 并完成 receipt/manifest 绑定。
qfq_columns = [
    'open', 'high', 'low', 'close', 'BBI',
    'zge_white_line', 'zge_yellow_line', 'ma60',
]
qfq_meta = reader.get_panel_meta(
    panel_path=panel, profile='FUTU_QFQ_ASOF', asof=query_asof,
)
qfq_df = reader.load_selector_ready(
    columns=qfq_columns,
    filters=[('ts_code', '=', code)],
    ts_codes=[code],
    panel_path=panel,
    profile='FUTU_QFQ_ASOF',
    asof=query_asof,
)
profile_meta = qfq_df.attrs['profile_metadata']
# qfq_meta['read_profile'] 与 profile_meta 应披露相同的 source/factor/cache/formula SHA。
# 仅绘制上述 QFQ 支持字段；量能及 B1/B2/B3/J 等 RAW 字段不叠到此 QFQ 图上。
# 请求日期窗口只在完整历史 warmup 的派生缓存计算后切片；不能只取114条算 EMA。
```

因子观察时间为 2026-10-24，profile 图形 asof 为 2026-10-23。窗口和有效日条件
没有认证历史可得性，结果只支持该 profile 的 chart view；不得用于回测、选股、收益
或全市场一致性结论。`profile_meta` 至少保留 profile/asof、因子来源与 vintage、
factor metadata SHA、source panel path/SHA、derived cache SHA、公式 SHA、支持字段、
成交量 basis、`chart_only=true` 与 `historical_pit_certified=false`。

深历史另从已绑定 backtest pointer 使用现有 pandas/pyarrow 读取所需真实列，
其 `trade_date` 过滤值必须为 int。例如请求黄白线历史可读
`ts_code/trade_date/bbi/zge_white_line/zge_yellow_line/J/source`，不要求不存在的
`B1/B2/B3/BG`。OHLCV 图形仅追加需要的原列，不启动其他指标 producer。

这段配方不调用上游 datasource、不初始化数据库、不写缓存，也不隐式请求行情。
如后续任务确实要调用上游计算器，必须先单独核实其 import/数据读取副作用，
不能把 `modules` 导入当作纯指标计算捷径。

## 每日更新与当前新鲜度

每日更新由现有 V4 执行器负责，skill 只读取其结果，不新增采集器或定时任务。
已核当前实际 release `stage-input-recovery-20261023-producer-r2/app` 的
`contracts/runtime_workloads.json` 中：`research_panel_daily_a` enabled=true，
owner=`v35_dispatcher.research_panel_daily_a`，run_policy=`A_SHARE_TRADE_DAY`，
slots=`['1700']`，stage=`POST_CLOSE`；HK 是独立17:20轨道，不能混用。
运行证据显示既有 KeepAlive dispatcher 在运行并按分钟检查 due slot；
2026-10-24 00:29 的 cycle450 为 `NO_DUE_SLOT`。
这些只证明调度配置和当时执行器状态，不证明当日数据更新成功。

截至 2026-10-24 最近一次已记录观察为 selector D23、`status=PARTIAL`、
accepted=5496/5800、quarantine=304；运行结果与指针可能继续变化。每次面板查询
都重新读当前实际截止、对应 receipt 和最新更新尝试，并说明所需 asof 与实际日期。
不能把“每天配置更新”写成“D23 已成功”或把明确失败说成“未检查”。
不由 skill 修复、补跑、重启或新增更新任务；缺口按具体事实报告。

## 输出要求

结果至少保留：market、ts_code、requested asof、actual_last_date、history_start、
行数、实际 RAW 或显式 QFQ profile 口径、native 单位、pointer 和已解析 panel 路径、receipt 路径、
来源依据（selector 的 formula_source/字段版本和 canonical producer；QFQ view 还须保留
factor vintage/basis/source panel SHA/derived cache SHA/profile ID/支持列及 PIT 状态；
backtest 的实际 source 行值）、manifest/run_dir、声明 SHA、accepted/quarantine 状态、
整体 PARTIAL/REBUILD_REQUIRED 及 PIT 限制。

面板可读只支持相应数据口径的研究，不构成公式身份、预测胜率、晋升或交易许可。
`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
