# 当前卡点与最小修复边界

核查日期：2026-10-09。方法：本机 GET 接口、页面只读观察、独立 Stage 路径/回执/源码核查。未触发任何采集或阶段运行。

## 已经完成什么

A股预选输入216行，前五阶段各有10只结果；行情覆盖205/216或206/216。原算法为V3_STAGE_SELECTION_V1。V35来源物化到V4存在来源链，不能误诊成“跨根所以未消费”；页面200条显示上限未截断216条输入。

## 为什么用户仍然看到未确认

1. **HK输入尚未准备好。** 10/9所需10/8资格主表缺失，正式D1池0行。阻断发生在评分前，错误为 `HK D1 status must be STRICT_0_2_READY`。数据缺口必须沿现有producer解决，改状态不能补出真实数据。
2. **A已有结果但行情/字段不完整。** 缺10–11只行情；09:25显示昨收为空却涨幅全0，支撑/压力/失效位相同。接口现象已确认，但采集端还是映射端造成昨收缺项尚待定位；不能宣称已经找到字段根因。保持评分算法，先跟踪输入字段。
3. **运行证据不能与当前结果独立绑定。** 09:40–09:45回执声明NATURAL/DUE并选出10只，但没有recorded_at、完整候选三件套和不可变回执SHA绑定。API因此不能独立确认natural/recovery。修复未来回执写入/读回，不伪造历史时间或把NATURAL字样当验收。
4. **旧HK观察通道不适用于10/9。** 既有通道只适用HK开市但港股通关闭，并仍要求已核验D1 Top100三件套。不能把任意旧研究池塞进来绕过当前缺口。
5. **修复目标路径必须匹配运行身份。** Stage配置指向外置候选app，runner、slot_execution、runner_receipts与canonical字节不同。实际API又是另一app。完整路径/SHA见SOURCE_MANIFEST；只改workspace不会自动更新配置指向的Stage。

## 精确定位

- actual_stage/stage_center/_runner_parts/slot_execution.py：34–81、147–180市场分支；699–702回执payload。
- actual_stage/stage_center/_runner_parts/runner_receipts.py：62–83回执写入。
- actual_stage/stage_center/runner.py：170–200观察输入校验、576–698分支选择。
- actual_stage/stage_center/_runner_parts/hk_input_validation.py：31–44绑定、75–87严格状态/100行门禁。
- actual_api/stage_center/execution_evidence.py：94–105时间/绑定缺失、125–139部分绑定状态。
- 原A算法a_live.py、a_auction.py和selection.py保留；本包没有授权修改算法、权重或池口径。

## 可复现的只读入口

`GET http://127.0.0.1:8873/api/v3/workbench/stage?date=20261009&stage=STAGE_0925&limit=10`

其余阶段标识见CURRENT_API_UI_SUMMARY.json。limit最大50；本次曾以200请求得到422，这是核查参数错误，不是产品故障。

页面：`http://127.0.0.1:8873/?date=20261009&stage=STAGE_0925#hkPreselectGroup`。

## 本机证据定位（原始业务数据不上传）

- 输入审计：/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009/INPUT_AUDIT.json。
- Stage配置：/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist，SHA256 9c7199ca1fcfedc09397255c932d25c6edc15779952bbd5b5bec2671e883d3f5；其config SHA256 ef5f49cb4efc35ec76e718415662cece51abb327b6ea7d5ccaa45df2b91869f7。
- A输入：/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/current/20261009/A_SHARE_STAGE_ACQUISITION_UNIVERSE_V3/current.json，SHA256 34b1bd1bb68dc75294dd5fda447dbaafe754fc979f7d71efa425724ed80bd52e。
- 09:40回执：/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/receipts/20261009/STAGE_0940_0945/receipt.json，SHA256 916afbf4c23ac6c2125098306fd8300b5a48e72f9630d3e368c723309bab2557。

## 状态

问题包 DELIVERED；独立只读诊断完成。此次业务代码IMPLEMENTED/TESTED/INTEGRATED/DEPLOYED均NOT_RUN。已有A结果的API/UI读回已观察；自然验收NATURAL_SLOT_UNVERIFIED。HK正式输入及结果BLOCKED。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。
