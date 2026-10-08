# Issue28 历史 P2：Mac 本机集成验收

输入：[Chat 固定交付 8a0d6b4](https://github.com/lexi2016/v4/tree/8a0d6b4368bc134466025a12b1cbcc45ff73cceb/handoff/stage-selection-historical-p2-20261008-r1)。ZIP SHA256：32a2d3d221a5532529a3f2949474f923658c218558178954e43370287c93c0f3。CRC、119 成员与117条清单逐文件 SHA 已核对；两份产品后像与远端 blob 相同。

## 已完成

- 两项修复已集成到 `/Users/lexi/Desktop/学习/v4_app` canonical 工作树；原有修改保留。基线 HEAD 55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054 不是干净前像，以逐文件 SHA 为准。
- 历史 eligibility/price 来源日不得晚于 trade_date；物化与读取均校验，合法分日/同日/迟采样观察合同保留。
- 缺 source manifest 或 receipt SHA 时，收盘复盘只追加一次既有 PIT 不确定原因；完整来源对照、模型行、计算状态与安全标志保持。
- 独立 Reviewer：REVIEWED=PASS，38/38 测试通过，0 fail/error/skipped；29项移植合成回归 + 9项新增 canonical 回归。没有把重复执行计为新增用例。
- BEHAVIOR_VERIFIED 仅限这两项冻结目标；INTEGRATED=CANONICAL_WORKING_TREE_ONLY。

## 字节与证据

| 路径 | 前 SHA256 | 后 SHA256 |
|---|---|---|
| infrastructure/preselection_pool_store.py | 028298a05ea44e310487c1159acc8147cf652e23ba716989135b178198795a92 | 9f1606a977d36c063d9c650e54b9861947eb7b692e779837852e3831b7814bef |
| ops/build_close_review.py | a361ae023285392ddf3b0e9674a9c506fae79252cc02c15df221ae09ba28e5aa | 59ac7798bcb1d54bbd11bbc61803997f36881a29cd1b82ecb663166791d5e0f2 |

新增 tests/test_issue28_historical_p2_20261008.py：44ab4b2fb6a146ddb4419e82c157796f3cf5af0f8a6e8aff7c6e066dc3db5944。

Writer receipt：669d63d17ed48de304ce5c0ea72f02bb6ab45a4a50662c9579f2a04ce890df46；actual diff：0faebaa79d61501d8aa6ecab0017a29a0dac056119ce45ffe389712ca3023d66。
独立 Reviewer receipt：9701d75e201dd844a4b9c886694fca303fecfb8c18c741fd239cde4aa18ba334；独立日志：dab2793b4b28da18453c10c2c71581a90df58bfc9d5e31657ab404d802b702d3；JUnit：cfbd89703a206d85876421ea82ae1ac84ff196ea91aa7c6c10ba243ca08f3b27。
完整本机回执保留在 `V4_ISSUE28_HISTORICAL_P2_MAC_20261008/writer/receipt` 与 `reviewer`，只上传源码、测试与精简结果。

## 测试环境与复跑

macOS 26.6.2 arm64，现有 Python 3.14.6、pytest 9.1.1；未安装依赖。真实 canonical 模块，不使用交付 support/sentinel。Writer 的隔离 canary 9/9、候选29/29与集成38/38仅作过程证据；正式 TESTED 来自 Reviewer 独立38项复跑。一次最初测试选择器错误退出4、0项收集，修正后通过，未借此改产品代码。

本包是源码切片，依赖完整本地 canonical 工程，不可整树部署。canonical/tests 新文件复用当前 test_close_review_producer.py 两个原fixture（同字节也在 mac_harness/synthetic_tests/references/tests 下）。在新的证据副本中运行，避免覆盖旧日志：
```bash
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B mac_harness/synthetic_tests/run_mac_suite.py --target integrated --phase focused
```
该命令依赖本机已集成 canonical 两文件及新增测试；mac_harness 保留比较所用两份 before 字节。candidate 模式不在本次上传的复跑合同内。

## 未完成项

DEPLOYED / API_VERIFIED / UI_VERIFIED / NATURAL_VERIFIED = NOT_RUN。所见在线 API owner 为 manager-daily-chain-20261008-r3-api，其 pool/close SHA 分别为 c96db1543e8b28e640b3c2d2a64aaae6a96d9a2a4a2401ca2780519233805171 / 6be84fa7462490d17e174d5e4bf77b476afc0ba7a67d60edddd036655683cf26，与本批 canonical 不同；未操作服务，不把观测当今后不变状态。

stage_selection_root=None，真实 Stage consumer 只可导入未执行；不能宣称 Stage/PIT 全链验收。未重建8/25或其他真实历史数据。嵌套未知字段P2仍延期，原2个失败探针保留但本轮不复跑。旧 R2 发布失败与其他 R1 修复不被本次 PASS 覆盖。Issue28整体保持开放。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
