# V4 横切运行一致性审查

审查日期：2026-10-01（北京时间）；证据读取于2026-09-30 UTC。

完成只读横切审查。建议主清单优先收录下面4项确定缺陷、1项需隔离复现的进程风险；另列1项“已有修复未回流canonical”，不要重复研发。

所有源码定位固定于 `bdc95a3f9d6d0313baeff2bf727ea82d122dc820`，下文 canonical/release 均属于 `research/mac-source-handoff-20260930/source/`。未运行任何业务代码、测试或采集，未修改仓库/现场。报告中的“确认”指静态代码和调用链确认，不能等同现场复现或当前部署确认。

## 1. P1：调度前置检查挡住死进程claim恢复

### 证据

- [canonical schedule_selection.py L22–35](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/_run_v35_macos_scheduler_parts/schedule_selection.py#L22-L35)：dispatch.claim.json存在即返回阻断
- [ExecutionLedger L169–240](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/infrastructure/scheduling/execution_ledger.py#L169-L240)：已经有身份复核、完成回执、活PID检查及原子reclaim
- [1555 release due.py L93–102](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/ops/run_v35_macos_scheduler_due.py#L93-L102)：同样提前阻断

### 触发链及影响

普通时槽的 dispatch claim 写完后，尚未写任何 workload claim 即进程退出 → 下次自然唤醒 resolve_due_slot → _slot_blocks_retry直接挡住 → 永远到不了Ledger已有恢复逻辑。这里可选择明确尚无副作用的窗口证明问题，不需要假定所有死进程任务都可重跑。1530专用capture路径需独立判断。

一次中断可使该日该普通时槽一直不再自动执行；前层可能只显示RETRY_BACKOFF/NO_DUE_SLOT，用户不知道需要恢复。

**置信度：确认静态调用链缺陷；现场是否已有这种残留claim待查。**

### 最小修复及验证

把claim是否仍阻断的判断收敛到Ledger已有状态解析；保留身份冲突、活PID、成功回执、请求已发送/未知状态的阻断。只对可证明未执行或可幂等恢复的状态开放reclaim，不无条件删claim。

隔离验证：构造“死PID+仅dispatch claim+无workload claim/receipt”，自然resolve→dispatch能恢复；活PID、成功回执、身份冲突及intraday未知request-state仍不可重跑。

## 2. P1：聚合failure_class丢掉兄弟任务的不可重试语义

### 证据

- [dispatcher.py L143–162](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/infrastructure/scheduling/dispatcher.py#L143-L162)：取首个非空failure_class，不按失败子任务保留决策
- [dispatcher.py L507–558](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/infrastructure/scheduling/dispatcher.py#L507-L558)：聚合FAILED后，对全部failed workload释放claim
- [schedule_selection.py L47–74](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/_run_v35_macos_scheduler_parts/schedule_selection.py#L47-L74)：除intraday专门检查外，只读聚合failure_class决定是否重试
- [1555 release dispatcher.py L29–48](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/infrastructure/scheduling/dispatcher.py#L29-L48)及[L366–400](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/infrastructure/scheduling/dispatcher.py#L366-L400)也保留此模式

### 触发链及影响

最小事件序列：同槽子任务A报NETWORK，后面的B报INVALID_INPUT/CONTRACT → 聚合只记NETWORK → A、B的failed claims都释放 → backoff后整槽重试，B也再次执行。反向排序还会让可恢复A被B的terminal状态一起永久挡住，结果依赖catalog顺序。

不该重试的失败重复执行，或独立可恢复任务被兄弟任务阻塞。1500等混合时槽确实存在多个enabled工作负载，非纯虚构单元场景。

**置信度：确认静态状态机缺陷；具体现场混合失败组合待复现。**

### 最小修复及验证

保留每个workload的retry disposition，仅释放/重试明确可重试的failed workload；成功和terminal子任务保持幂等事实。聚合failure_class只用于摘要，不能覆盖子任务执行决策。

验证NETWORK+CONTRACT、NETWORK+SAFETY、成功+失败三种混合组合交换顺序后，重试集合应完全一致；intraday已请求/未知边界不得被放宽。

## 3. P2：任务状态页把兄弟任务失败错误归给已成功任务

### 证据

- [task_status.py L98–119](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/domains/task_status.py#L98-L119)：按selected_workload_ids选aggregate receipt
- [task_status.py L186–245](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/domains/task_status.py#L186-L245)：L219直接使用aggregate status
- [API runtime_router.py L40–51](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/api/v35_api/runtime_router.py#L40-L51)
- [TaskStatusView.vue L121–129](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/apps/web/src/views/TaskStatusView.vue#L121-L129)
- [manager_api release task_status.py L260–293](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_api/domains/task_status.py#L260-L293)也直接取aggregate status；[1555 release L80–113](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/domains/task_status.py#L80-L113)同样存在

### 触发链及影响

1500的hourly_research成功，fupan_close_materials失败 → dispatcher保留正确子结果，但aggregate FAILED → API把hourly_research也投影为FAILED，前端直接展示。

成功任务被报失败，用户追错任务、重复排障；重试后aggregate DUPLICATE_WORKLOAD_SKIPPED还可能覆盖此前正确成功状态。

**置信度：确认，完整静态API→UI调用链已查。**

### 最小修复及验证

逻辑任务状态取唯一匹配workload_results子结果；aggregate状态单独展示。calendar/no-workload状态才使用明确允许的aggregate分支。缺失、重复子结果应CANNOT_CONFIRM，不能猜成功。

验证真实形状1500 mixed receipt中，一成功一失败分别呈现；重试receipt未再次执行成功子任务时，保留其之前已验证成功，不被聚合skip覆盖。

## 4. P2：损坏的尾回执被忽略，链仍被标为已验证

### 证据

- [execution_ledger.py L457–488](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/infrastructure/scheduling/execution_ledger.py#L457-L488)：JSON损坏/不可读直接continue
- [execution_ledger.py L490–525](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/infrastructure/scheduling/execution_ledger.py#L490-L525)：verify_receipt_chain在上述过滤结果上验证
- [task_status.py L414–453](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/domains/task_status.py#L414-L453)：通过后展示RECEIPT_CHAIN_VERIFIED

### 触发链及影响

最小反例：同槽有效r1→r2，r2文件被截断成非法JSON → list只返回r1 → r1独立前缀满足单head/tail → verify返回true。这里不讨论无法检测的文件删除；文件仍在目录中、只是解析失败，程序本来可以检测。

最新失败/执行事实可能消失，页面反而显示旧前缀“链验证通过”。

**置信度：确认。** canonical、manager_api与Stage两份release的ledger blob相同；1555旧ledger也有相同跳过路径（[L435–449](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/infrastructure/scheduling/execution_ledger.py#L435-L449)、[L468–485](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/infrastructure/scheduling/execution_ledger.py#L468-L485)）。

### 最小修复及验证

严格验证入口枚举全部预期回执文件，把读取/解析/日期身份错误作为验证失败返回；保留宽容list作为浏览功能可以，但不能用于完整性证明。

验证尾文件截断、中间文件损坏、非对象JSON、business_date与路径不符均应RECEIPT_INVALID；正常多slot/mode链仍通过。

## 5. P1候选风险：A同步与formula没有共享总预算，外层超时不拥有整棵子进程

### 证据

- [run_scheduled_slot.py L113–151](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/run_scheduled_slot.py#L113-L151)：外层默认600秒
- [macos_research_panel_daily.py L69–73](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/macos_research_panel_daily.py#L69-L73)：A同步默认540秒
- [panel CLI L77–99](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/_macos_research_panel_daily_parts/cli.py#L77-L99)及[L194–210](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/_macos_research_panel_daily_parts/cli.py#L194-L210)：formula再给独立900秒
- [a_formula_execution.py L147–182](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/_macos_research_panel_daily_parts/a_formula_execution.py#L147-L182)：先同步后formula
- [process_boundary.py L6–17](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/infrastructure/scheduling/_executor_registry_parts/process_boundary.py#L6-L17)：外层subprocess.run超时
- [bounded_execution.py L74–126](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/_macos_research_panel_daily_parts/bounded_execution.py#L74-L126)：formula start_new_session=True，只在panel仍存活并捕获自身TimeoutExpired时清组

### 触发链及影响

同步用500秒，formula还需200秒。其自身预算允许执行，但外层在总600秒先杀panel；formula是独立session，不由外层直接child kill覆盖。

可能超时后仍有formula继续写入或子进程/管道未正常回收；之后调度器认为失败而开始恢复，可能与残余计算交叠。

**置信度：确认预算/取消结构不一致；真实孤儿、迟到写入及平台回收结果待隔离复现，不能宣称现场已发生。**

### 最小修复及验证

只用一个monotonic deadline，将remaining传给同步和formula；外层与嵌套进程形成完整取消所有权，在释放claim前确认受管子进程全部退出。不能仅全局加大timeout。

查重：1555 release已有a_daily_timeout_seconds专用转发（[executor_registry.py L588–597](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/infrastructure/scheduling/executor_registry.py#L588-L597)、[run_scheduled_slot.py L113–124](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/ops/run_scheduled_slot.py#L113-L124)），canonical没有。应复用已有局部能力，仍需解决预算共享与进程取消；其现场配置值未在handoff里证明。

隔离验证：短时模拟外层2秒、内层10秒、子进程定时写标记；超时返回后父/子/孙进程全部退出且不再写入，再允许重试；同时测同步消耗余量后的formula截止时点。

## 已修复但未回流：不要作为新缺陷重复开工

[canonical schedule_selection.py L59–68](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/canonical/ops/_run_v35_macos_scheduler_parts/schedule_selection.py#L59-L68)仍以“任一历史release/fingerprint不同”直接放行，导致旧A失败+新B刚失败、retry_after尚未来到时，当前B仍立即可重试。

但 [1555 release due.py L117–135](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source/releases/manager_scheduler_1555/ops/run_v35_macos_scheduler_due.py#L117-L135) 已按当前identity筛选，修好了这个分支。

应列“P1 canonical/release回流冲突”，复用现有实现，保留canonical新增intraday请求边界检查；不能说1555自然调度仍有此新bug。反例仅影响backoff/legacy cap/未知failure类型，不会绕过前面的显式terminal集合和intraday BLOCK。

针对性验证：保留历史A失败，再添加当前B失败且retry_after在未来，当前B应被backoff挡住；首次B无自己的历史时允许一次新尝试。保留成功/terminal事实和intraday已请求/未知状态的安全语义，不可只盲目筛掉所有旧回执。

## 查重与覆盖边界

- Python3.13.12/3.14.6路由只复用 [Issue8已有定位](https://github.com/lexi2016/v4/issues/8#issuecomment-5916304880)，本次不另开相同缺陷
- 已读两份CHAT_START、[README](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/README.md)、完整[source_inventory](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/source_inventory.json)及[runtime_inventory](https://github.com/lexi2016/v4/blob/bdc95a3f9d6d0313baeff2bf727ea82d122dc820/research/mac-source-handoff-20260930/runtime/runtime_inventory.json)；680 canonical与各owner磁盘引用分开理解
- 已核对scheduler选择、dispatch/ledger、解释器边界、panel A/H路由、A同步主流程/progress/CLI、formula generation consumer、任务API/UI状态投影及冻结日历
- [Stage最新84264c候选](https://github.com/lexi2016/v4/tree/84264c47a99d464d174b8180375c8701883b2bb5/research/stage-ah-execution-r4-20260930)及[Manager最新95426a候选](https://github.com/lexi2016/v4/tree/95426ac3db39f6d86ec2031617c4ac180d40868e/research/manager-r9-consumer-r1-20260930/final_business_20260930)文件清单中，没有上述scheduler/ledger/task_status/A-sync路径的对应修复；这只是未看到该候选覆盖，不代表候选已部署
- 配置现场只证明handoff捕获时manager API PID807、1555 scheduler PID821；不能证明当前进程加载字节或17:20 owner
- 因子工厂只追到V4 formula generation/selector consumer及调用ops/a_formula_increment.py；该动态执行目标与完整因子工厂源码不在这份冻结树中，不能宣称审过训练/计算引擎或完整F5
- 数据更新核读sync_workflow，但未用被排除的raw-market fixtures复现；进度标记timeout保留逻辑还有可疑处，未纳入主清单以避免凑数
- 日历明显固定2026且跨年返回UNKNOWN，这是显式支持范围，当前不作为9月新功能bug
- 没有审完全部680源文件，也没有API现场、自然时槽、跨进程故障注入或部署验收，不应对外写“全代码/全系统验证完成”
