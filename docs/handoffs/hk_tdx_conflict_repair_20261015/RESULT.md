# 港股历史修正与预选池恢复

已部署并通过独立线上验收：1210 个双侧锚点确认的异常日 OHLC/amount 修正进入同一 hk_0_2 权威视图；原行情、模型和历史原件保留，没有新底板。trade 未换算或改写。已处理2420行事件/次日派生闭包，以及新增连续性断点后的69行segment标签。

|目标日期|实际可评分输入|新预选池|状态|
|---|---:|---:|---|
|20261015|664|100|回看 HK-only，未生产 A 池|
|20261016|664|100|STRICT_0_2_READY，实际 main/8873/UI已读|

原模型、80 proxy/100 Top100门槛不降；500输入下限由既有canonical合同落实到actual运行路径。API90244、main90252使用 API-r5/shared-r4/main-r2。两日100条真实有限分数、唯一代码/连续rank、同run/proof消费均独立PASS。主控Chrome已刷新确认次日100条；未执行Stage，未声称NATURAL验收。

A15完整对照仅允许HK容器manifest审计引用更新，其余字段/rows完全相等。A16并行更新结果完整保留；保护检查曾因此触发受控回退，随后独立验收精确HK-only恢复并采用当前基线。具体写入者未被无证据归因。8个从未激活的废弃代码候选已同卷移到桌面待删除，现役和原回退版本保留。

耗时中包含可避免的控制脚本错误：proof自洽漏洞、隔离loader/日期合同、部分回滚/CAS边界，以及Path类型/目录准备错误，均保留FAIL并修正；完整A哈希门和并行A更新曾正确触发保护。精简错误及证据SHA见FINAL_RECEIPT，不上传全部attempt材料。

单位、调整方式、历史PIT仍UNKNOWN；未确认字段继续隔离，未宣称全部原冲突消失。保持RESEARCH_ONLY、production_allowed=false、buy_gate_updated=false、orders_sent=false。Git交付等待主控逐文件远端读回，未merge。
