# M18｜经理决策账本、汇总与计划
日期：2026-10-10。原总计划模块18，P1的消费与保存端。此包给一个独立Chat编码会话使用。当前仅完成固定源码阅读及任务文档，不含产品代码候选；本轮产品测试、Mac操作、部署均未执行。

## 已在运行的唯一候选，先去重
2026-10-10已核：用户已把旧9cac0ff的跨13→18任务交给原Chat，现正修manager same-run/latest及共享UI的只读、日期、取消处理。该Chat是这些修复的既有owner。必须优先接收它的固定候选，不能因为本包拆成M18就平行重写。可将该原Chat直接登记为M18 owner并续交本包；若另开M18 Chat，只能先读候选做交接审查，待明确移交后续修剩余缺口。同一目标文件始终一个写入者。

## 怎么使用
1. 优先给上述既有Chat续交本目录四份文件，先读本页和SOURCE_MAP.md；不要把正在运行的修复重新发给另一Chat并行编码。
2. 粘贴PROMPT_FOR_CHAT.md。Chat负责方案和完整代码候选；嘻嘻统一接收，在现有Mac做落地、测试、普通API与页面验收，问题回传原Chat。
3. 本模块只一个产品写入者。共享UI、gateway、HTTP refresh绑定、调度、发布配置的改动提交统一集成请求，不由18个Chat各自覆盖。

## 模块边界
- 本模块拥有经理消费合同、保存计划、同run终态核验、独立读回与普通页面读模型。按原计划最终消费04—17已提交产物；首批为13/14/15。
- M13拥有公告生产与审核/导入；M14拥有超跌源准入与原两门；M15拥有美股关系与daily产品。M18只收各自产物引用，不替它们采集、不调用模型重判、不重算筛选。未接lane明确缺口。
- 沿用V4原业务语义、日期、身份、BUY门与研究安全字段。保留V4、8910、历史产品及正常服务；不交易，不扩安全权限或凭据访问。
- 原“第一模块13→18”交接已发出且正在编码。现在经理保存/普通同run终态读回归本M18职责，既有Chat继续拥有正在修复的候选，M13交合格产物引用；按已完成候选逐项移交，不另起重复经理实现。

## 固定观察基线与已有结果
- 源码观察F：lexi2016/v4@f7cb731c384ee6890a87d16c19a5b5a621779477。不是Mac当前活动字节声明。
- 原编号/阶段：[总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)；[迁移计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)。旧审计的模块编号不同，不混用。
- F中已有manager_plan.run_manager_plan/publish_workspace_read、current_recovery私有保存、exact terminal reader、daily_manager_assembly和不可变generation，不从零重造。
- F的module_api.do_POST明确405 MODULE_READ_ONLY；前端有refresh函数不证明V5已接HTTP执行入口。真实读/写路径与当前配置必须先定位，共享接线交统一集成。
- 已有报告：392条公告决定为2 event / 0 earnings / 26 observe / 270 not selected / 94 unknown，不是392只入选股票。经理run为5b4feaf7ef7d4d13bec639e90b6d3db0，计划SHA为56556a67ddc1a562e82b38e750be92fcfda070945397cc4eacffd1c79f42bcf0，生成时刻2026-10-10T02:23:24.502381+00:00。本包未读取Mac原件、未重新验这个run。
- 已有current_recovery前端候选e0a6bc36f9563df6a4e0f37d4e16a59e14347227，原patch SHA256 757fff2254cdb714946f6efdeb4675c86bbc97ea41f5df0556bd290348bd9804。其测试依赖未随包附的真实manager-read-publication.json，不得缺fixture补假绿。各文件前像不是单一完整Git基线，先核manifest。
- 旧部署任务回执停在候选启动之前，不能推定61796或当前进程已切换。实际Mac活动代码、端口、输入根、generation由统一落地重新登记。

## 完成标准
不是再交优化建议或孤立helper。交可审查完整候选与精确补丁；在Mac证明同一真实产品→经理保存→同run terminal→普通API→页面的一致性。五层验收全部见ACCEPTANCE.md，本包一律NOT_RUN。已有工程回归和UI报告单列引用，不自动算当前完整通过。

