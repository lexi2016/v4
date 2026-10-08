# V5 独立模块迁移

V5已在现有私有仓库lexi2016/v4建立独立分支v5/module-isolation-20261008，不覆盖V4。此目录目前只有设计与实施计划，不是可运行工程。

## 阅读顺序

1. [来源与实际状态](BASELINE.md)
2. [架构规格与首轮边界](SPEC.md)
3. [首轮详细实施计划](PLAN.md)

首轮只做独立版本组合/发布健康检查，加一个原超跌reader的隔离影子运行。保留原算法、PIT、日期与资格门；V4继续运行。按用户最新分工，由dot在当前工作中编写代码，云端Codex做定向测试，本地Codex只做后续获批部署、原生兼容验证与反馈。

当前状态：实施计划待用户审阅，产品代码/测试/部署均未开始。真实HK02输入缺项仍阻塞对应业务验收；合成数据只能证明工程合同。

本次分支以固定commit c563adc067fcd6a6b95fe756c7618f46d2f4389e为起点，新增文件仅V5/的README、BASELINE、SPEC、PLAN。没有产品代码迁移、merge、部署或其他分支变更。

兼容的云端Python版本可用于开发和合成测试，记录实际解释器与依赖；Mac实际运行环境另做兼容验收，不把此前观察到的3.14.6补丁版本号本身当作禁止开发条件。

不接账户或订单；research_only=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
