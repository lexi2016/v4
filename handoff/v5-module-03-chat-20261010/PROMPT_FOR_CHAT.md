# M03编码任务：原US来源采集与精确三文件接续

你只负责原V5 M03。请读START_HERE及SOURCE_MAP，直接返回最小代码候选和可复查证据，不再交一份泛化整库审查。用户分工是Chat写方案和具体代码，嘻嘻在现有Mac落地并独立验收；不要求你能连Mac。

## 必须先确认
1. 基于f7cb731c384ee6890a87d16c19a5b5a621779477，区分现有cloud_us_collector完整48件采集闭包、原slot dispatcher、39件映射reader、current_us_research消费者。
2. 输出donor函数→现有V5函数→最小目标文件映射。已有等价实现保持；原collector算法、配置标的、provider、US日历/DST、phase窗口、拒绝码不重写。
3. 若us_source_daily.py仍不存在，可在本Chat独占路径新增；不是把总计划的拟新增名宣称已存在。不允许创建第二个采集owner。

## 首个最小候选
- 显式请求携带US session、phase/slot、实际取得时点、cutoff、原owner及输入/配置摘要；根据原市场日历计算session，不拿上海业务日期替代。
- 首先检查现有精确三文件及原reader；已存在合格结果则复用。确缺原件时才由原owner按合法当前窗口采集。晚补保留原MANUAL_RECOVERY身份，禁止把今天时间改成历史窗口。
- 将原collector输出锁在V5私有数据根；沿已有marker/no_symlinks/来源不重叠规则。原reader可能创建锁，需在私有副本读回，不写V4根。
- 核对research/peripherals/{us_session_date}/external_finance.json、receipts/research/peripherals/{us_session_date}/external_finance.json、research/peripherals/manifest.json。保留原三文件格式、payload哈希、receipt字段、capture_id/run_id、phase、source_response_sha256、市场snapshot与取得时间。
- 产出模块私有来源binding及独立exact readback。同输入幂等；成功保留；失败/缺报价/真实有效空/NOT_DUE分别显示，不能强制READY，也不能删除未知行。
- transport遭代理拒绝时保留原错误，不偷偷直连、不换provider、不绕安全边界。只有原流程支持的受控恢复才可执行。

## 写入与协作规则
仅写M03自有入口/测试/文档，必要时最小修改cloud_us_collector.py；共享cloud_transport.py、contracts注册/manifest pin、module_api.py、api_gateway.py、daily_tick.py、daily_dispatch.py、run_ledger.py、daily_owner_adapters.py、UI、manager_plan及M15文件均只提INTEGRATION_REQUEST，不给直接覆盖补丁。
变更请求明确调用方、现有目标SHA、所需函数/入出参、日期/cutoff/拒绝码、向后兼容和验收。统一集成者决定合入。现有vendor闭包只读；若原owner确有缺陷，提交精确最小修复建议及失败证据，不私自替换冻结闭包。

## 必须交付
- 固定candidate commit或完整文件包；原始base ref及逐文件before SHA256、Git blob SHA、after SHA256、增删标记。新文件before=ABSENT，不能伪造after或测试结果。
- before/after完整文件、runtime.patch、reverse.patch；补丁只含白名单。标注代码候选/工程测试/真实业务/API页面/自然接续五层各自状态。
- 针对性测试及原始日志：错session、假READY、三文件缺一/篡改、receipt借run、晚于cutoff、DST双slot、NOT_DUE、重复运行、失败不覆盖成功、未标记/重叠root、source SHA漂移、代理拒绝不fallback。
- SOURCE_TARGET_MAP与DEPENDENCIES，集成变更请求；必要测试无真实数据标NOT_RUN，fixture结果不能写真实采集通过。
- MAC_APPLY_AND_ACCEPTANCE：前像确认、隔离应用、真实适用window、精确三文件回读、M15只读合同、单模块回滚。端口/活动路径不明不得猜覆盖命令。
已有资料足够先写静态候选；仅缺真实运行前像时列部署前检查项，不要求用户搬整库/凭据/全部市场数据。

