# V4历史阶段reader最小交付

本目录只含可审查reader修复、软件测试、聚合140格表及最小证据摘要。当前本地R4已加载；4个真实页面风险样本通过，独立最终reader验收通过，见READABILITY_20_DAYS.md。研究来源/PIT仍为CANNOT_CONFIRM，6个真实缺口保留。

`READER_CUMULATIVE_C4_TO_R4.patch`从原c4e474…精确重建最终9e9120…，覆盖R2/R3/R4完整链；仅修改apps/api/v35_api/app.py，consumer.py、前端、交易门禁不改。先核对基线SHA，再由集成owner对其明确目标git apply --check；不能把整份运行时app.py覆盖到旧工作树或含其他用户修改的canonical。

`source/`是四个实际执行helper/tests的原字节交付副本，内部保留原目录相对结构。它们依赖合同中的本机保留运行时与研究证据，未随交付携带原始行情或API响应。`validate_saved_stage.cjs`执行部署原loadStageSnapshot，fetch只返回本地保存字节。

已完成验收复用：R2窄软件8通过；R3最终29通过；R4真实契约代表5通过、保存140份全接受、2负例拒绝、A140不变；R4实际5原响应严格消费全通过。没有重跑Top100/194或重复全140HTTP读取。原R2阶段整体尚有22失败；R3 API140成功但页面失败；不能把早期局部PASS写成整体PASS。

不含原始行情、API响应、selection trios、正式registry、plist、token或完整运行时源码。Git同步/服务操作由主控负责，本包不授权新发布或金融生产。RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。

交付与运行状态分开：实际R4已经由主控本地集成并加载，本包尚待主控Git提交/原授权分支同步；Writer未commit/push。没有新增数据生产或selection/raw/index发布。
