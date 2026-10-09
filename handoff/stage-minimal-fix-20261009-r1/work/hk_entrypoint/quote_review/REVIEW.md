# A 行情结果投影：独立源码审查

结论：**PASS_SOURCE_SLICE_WITH_HISTORICAL_SUPPORT**。本轮提供的两个候选文件内，没有发现新增 P0 / P1 / P2。该结论针对源码投影修复，不代表 Mac 实际采集、部署、页面或自然时段验收。

## 核验结果

- 在独立新目录实际复跑作者套件：**65 / 65**，failures/errors/skipped 均为 0。原 stdout、stderr、JUnit、命令及环境保存在 `author_suite/`。
- 另写并实际执行独立反例：**15 / 15**，failures/errors/skipped 均为 0。代码在 `tests/test_independent_projection.py`，JUnit 在 `independent_probes.xml`。
- 两个 before 文件与固定输入 `28ab2d35020adf031f10f38c1040514fc81b6d66` 的实际 Stage 切片一致；该批 actual 与 canonical 的这两个文件本来相同。

| 文件 | before SHA256 | after SHA256 |
|---|---|---|
| `stage_center/_selection_parts/a_auction.py` | `d0a96edcb4d87f223b117917a8f0d68276bd088a88abe8f787d245c8e1c669ad` | `01b00f748daa0ef7b0502805d977d883b20616c2070aa35685744af8f9131af1` |
| `stage_center/_selection_parts/a_live.py` | `b7faa3286df4f0312075c7a4563d3f4deed463d3f10ab2c4902967e8d5d7781d` | `4225b27df7067663da42b635773bf90e94b4601fc2478b8decb5c635f77d86a0` |

## 审查重点

1. **原算法调用保留。** auction 的 price、prev_close、qmt 构造与 `live_stage_quality_score` 调用没有移动或改写。live 的 qmt/candidate、live_score、research_bonus、stage_score 也保留原路径。独立测试在 7 个阶段各给 240 行，捕获每次真实评分函数实参；before/after 的 qmt、candidate、stage 一一相等，240 行都进入原评分函数，最终 Top10 的代码、分数和排名完全相同。
2. **输出修正发生在评分之后。** auction 在通用 card 展开后覆盖正确的 prev_close/day return，避免 `**card` 把缺昨收的日涨幅变成 last/open 的 0。live 使用已经传给算法的 qmt.lastClose，输出 lastPrice/lastClose 的日涨幅；不借未参与评分的外层字段猜补来源。旧 day-change 值与 qmt 冲突时，以该已绑定 qmt 为准。
3. **缺失与真 0 分开。** 数字字符串、空字段别名、非法 primary baseline、布尔值和缺现价均有检查；未知日涨幅保持 null，理由明确；真实昨收等于现价保留数值 0。已知开盘价/昨收的 gap 可以存在，而缺现价的 day change 仍为空，两者不再混同。
4. **排序不受 nullable 展示影响。** a_live 的 qmt_gap_pct 原算法值保留到排序和 Top10 完成后，再将无效输出设 null。原 sort keys、selection cap、algorithm ID/SHA 保留。已核 `selection_envelope` 只复制已排顺序，不在之后再按新 null 字段重排。
5. **原记录及边界保留。** 输入 dict 不被修改，空结果保持原 READY_EMPTY 身份；新增产物投影改变对应产物 run 身份，原已存结果不能覆盖；没有引入 natural/execution verified 字样或交易权限。支撑/压力/失效位未改，保持用户冻结的原算法规则。

## 明确未关闭项

实际采集侧是否取得昨收、10–11 只行情为何缺失，需要当前 collector/provider 和真实原行的定点核查。只凭选择器切片不能归因全部数据缺口，也不能声称完成补采。

此次测试使用 SHA 固定的历史 helper、真实 selection store 实现和明确的测试 namespace shell。完整当前 Stage app 的 import/依赖及当前算法 helper SHA 仍需本机核对；本 reviewer 未连接 Mac。HK 真实 10/8 输入、receipt writer、时钟补丁不属于此专项审查。
