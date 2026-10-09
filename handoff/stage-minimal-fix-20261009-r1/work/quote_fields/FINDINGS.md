# A 股阶段字段：已确认的投影缺陷与仍需本机核对的来源

固定输入为 `28ab2d35020adf031f10f38c1040514fc81b6d66` 的 `handoff/stage-minimal-flow-20261009`。本候选仅修改实际 Stage 的 `a_auction.py`、`a_live.py` 两个结果投影；原算法输入、评分调用、系数、排序和 Top10 都保留。同包 `SOURCE_MANIFEST.json` 声明这两个文件与 canonical 同字节，因此同一补丁可分别应用到匹配 SHA 的两个 owner。没有修改当前 collector、builder、服务、业务数据或既有运行。

## 当前事实与定位

用户包的 `CURRENT_API_UI_SUMMARY.json` 记录：10/9 前五个 A 阶段已经各计算 10 只，09:25 行情为 205/216，其后四阶段为 206/216。09:25 回执诊断是 205 个 ACCEPTED、11 个 EMPTY_PAGE、0 个 READ_ERROR。这证明本次少收到 11 只精确竞价行情，不能由此认定这些股票永久不受供应商覆盖。其余阶段少 10 只的具体代码/原因，需原回执或 source payload。

### 已附 actual 中可以确认的缺陷

1. `before/stage_center/_selection_parts/a_auction.py:46–49` 已用竞价价与昨收计算日涨幅。缺昨收时返回 None；但 `:87` 把 `qmt_gap_pct` 变为 0，`:104` 的末尾 `**card` 又能覆盖先前的 `current_change_pct`。固定提交内的历史 `primitives_io.py:96–109` 显示，通用 card 在该值缺失时会计算 last/open；竞价的 open 与 last 同价时，结果就是错误的观测 0。当前 helper 源码未附，因此其实现只能作为已核字节的参考；本候选在已附 actual 的最终输出处显式恢复日涨幅或 null，不依赖通用 card 的 fallback 行为。

2. `before/stage_center/_selection_parts/a_live.py:27–36` 已把 `qmt.lastClose` 交给原评分输入，但 `:65–97` 的结果字典没有显式输出 `prev_close_price`。通用 card 的 last/open 是阶段涨幅，不能在页面中与昨收日涨幅混用。本候选输出同一 qmt 中已有的昨收，以及 last/昨收的日涨幅；缺基准时输出 null 和原因，不从别处取价格、不修补 qmt、不改变分数。

3. 09:25 支撑、压力、失效位相同不是本轮另造公式的理由。actual auction `:90–92` 本来以竞价价初始化三者，通用 card 使用当前观测 high/low；历史原 collector 的单个竞价成交点也会令 OHLC 相同。当前接口现象与原规则相容。本候选保留这组规则及数值，未把它们改成新的技术价位。

### 只能确认历史参考、不能冒称当前来源的断点

`references/SOURCE_INDEX.json` 保存了从同一固定提交获取的 7 个文件的 Git blob、字节数、SHA256 和角色。

- 10/8 `active_stage_reference/.../selection_builder_registry.py` 的竞价行映射没有传 `prev_close_price`，可独立解释“原 source 有昨收、selector 却没有”的旧断点；对应 Issue28 旧修复是在 builder 加一行原值透传。**本轮未附当前 builder，不能假设该旧字节仍运行，也没有向实际 owner 推送旧 builder。**
- 10/5 Stage `infrastructure/tdx_minute_replay_provider.py:389–408` 的原竞价回放会调用 `get_security_bars(...daily...)` 取得先前收盘；`:411–444` 将其写入 `prev_close_price`。该文件后续分钟归一化 `:450–483` 没有输出昨收。当前 TDX provider 未附，不能把此历史路径说成当前已经验通。
- 10/5 shared `scripts/live_acquisition/pytdx_hq.py:101–155` 的分钟归一化只保留源响应明示的昨收，注释说明该接口的常见 wire 字段为 price/vol。它不把当日价格当昨收。因此得到分钟行情与得到昨收是两件事。
- 10/5 Stage 竞价 collector 及 HQ minute 入口保留了原链的时间检查、显式代码列表、缺行/错误类别。本候选不新增行情 lane、不追加每日历史查询、不降日期/cutoff 校验。

## 最小修改行为

| 输入 | 输出昨收 | 输出日涨幅 | 缺项原因 |
|---|---:|---:|---|
| 昨收 100、当前/竞价 105 | 100 | 5 | null |
| 昨收 100、当前/竞价 100 | 100 | 0 | null |
| 昨收不存在/null/空字符串 | null | null | `PREV_CLOSE_PRICE_MISSING` |
| 昨收为 0、负数、非法数值或 boolean | null | null | `PREV_CLOSE_PRICE_INVALID` |
| 昨收有效、当前价缺失或非法 | 原昨收 | null | `AUCTION_PRICE_MISSING_OR_INVALID` 或 `LAST_PRICE_MISSING_OR_INVALID` |

这里只规范对外观测字段。原评分公式对缺项的既有中性项，以及对非法输入的旧计算行为没有改动；这不是对非法源数据的质量认可。对非正昨收等反例，before/after 分数和排名仍逐项一致。

live 的 `qmt_gap_pct` 可能参与旧 09:25 排序，因此原排序输入保持，待既有排序及 Top10 完成后才将无法观察的 gap 输出为 null。两个来源的 `current_change_pct_basis` 分别明确为 `AUCTION_PRICE_VS_PREV_CLOSE`、`LAST_PRICE_VS_PREV_CLOSE`。选股结果的最终行发生变化，原 immutable identity helper 因而给新候选生成新的 run/artifact ID；同一旧 slot 仍拒绝被覆盖。

## 已执行的验证

- 首次 63 项：原前像 **50 FAIL / 13 PASS**，改后 **63 PASS**。完整原日志保留为 `red.log`、`green.log`。
- 补齐 gap 排序和缺当前价的边界后，同一完整套件 65 项：前像 **52 FAIL / 13 PASS**，后像 **65 PASS**，均无收集错误或跳过。原始 stdout、stderr、JUnit、命令及 Python/平台见 `evidence/before_final`、`evidence/after_final`。
- 7 个适用 A 阶段分别使用 216 请求、205/206 合成行情，确认原选中代码、score、stage_score、rank 和算法 SHA 全部不变。最高分样本位于第 200 行以后，能捕获误用页面上限的问题。
- `ALGORITHM_INVARIANTS.json` 记录 28 项 AST 对比：原 qmt/candidate 输入、评分赋值、排序/截取赋值及影响排序的原行字段不变；`selection.py`、实际 `contracts.py` 字节保留。算法 SHA 仍为 `eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2`。
- 原 SelectionStore 的真实文件写入、读回、nullable JSON、新旧 run 冲突、旧文件字节保护通过。两文件补丁应用、前后字节核对和反向还原通过。

**验证范围：Linux 中的实际 selector 源码切片，使用 13 个已 pin 的支持文件，其中 selection/contracts 为本轮 actual，其余为历史依赖及明确的测试 namespace 接缝。不是完整当前 owner 导入，也不是 Mac、8873 API/UI 或自然时段验收。**

## 本机落地与字段链验收

先按 `SOURCE_CHANGES.json` 核 actual owner 与 canonical 的两个前像 SHA；从当前完整 actual app 建隔离候选，在候选内应用 `runtime_quote_projection.patch`，然后读回后像 SHA。`support/` 与 `references/` 仅用于复现/审查，不得覆盖到运行 app。

可复跑本包源切片测试：

```bash
python3 run_tests.py --phase after --output /绝对路径/新的验收目录
```

完整 owner 验收须另用其现役依赖运行同样断言。沿同一日期、同一代码逐个比对原 provider payload → collector SourceResult → selection builder 行/qmt → 新候选结果 envelope。若 SourceResult 有昨收但 builder/qmt 丢失，再把当前 builder 的实际字节补齐后应用原值透传修复；若 provider/source 本身缺失，则保留 null 与具体来源原因，不通过新行情来源或跨日期值补齐。

已有 10/9 原 run 保留原字节和原解释；不要重置 settled slot 或把新字段塞进旧 manifest。真实单阶段调用、候选发布、API/UI 与自然时段入口沿主交付的实际运行合同执行。回退是将当前指针恢复到保留的旧 owner/release；未发布的源码候选可按补丁反向还原，两种动作均不重写历史业务数据。

当前状态：结果投影候选 IMPLEMENTED/TESTED；当前采集字段链、完整 owner、Mac、部署、API/UI、自然时段均未验收。少 10–11 只行情和真实缺昨收的数据尚未补齐。
