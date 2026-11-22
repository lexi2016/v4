# V4 Main 日更容量路径 A 隔离补正

本轮在 `ec38a53c78a3c483c883f18eec886d7691118194` 上接通日产品和 Top200 的写前守卫。生产迁移与切换继续 `BLOCKED`，自然调度验收为 `NOT_RUN`。Stage/QFQ 原 P1 PASS 沿用。

日产品父进程在提交之前预扣全部在途字节与文件槽位。实际 spawn initializer 每进程只校验一次同一不可变计划及来源 SHA，任务消息只传计划 SHA。子进程在原 serializer 写盘前检查真实 buffer、累计字节、文件数及单文件上界。父进程获取结果之前，先核账并观察实际文件，再归还槽位。失败、取消、启动失败和正常退出排空均保留相应记账边界，损坏或缺失的 worker 回执按完整槽位保守处理。

已接的原入口包括逐股日产品、历史 checkpoint、retained gzip、原图共享 HTML/spec、score/action 的真实 spawn map、V192 既有视图、F10 和原 Top200 staging/publisher。原子替换的临时 inode 在写前额度内。日产品的 native compression 为原文件与压缩暂存及头部块预留三份向上取整额度。不可变同字节复用不再次扣槽位。容量错误越过原本会降级 UNKNOWN/partial 的捕获边界。

日产品正常完成也在两份完整 buffer 就绪后一次预检 index/event 与精确旧字节回滚。可选 statistics 在新 index 下运行，任何容量或 I/O 中断都会先恢复主对，再核对并恢复本任务写入的 statistics 指针，保留已计账的不可变工件。禁用模式维持原调用顺序。

Top200 的常规 `complete_daily_derivatives` 复用已计算历史标签；旧显式 catchup/bootstrap 入口在启用路径 A 时写前拒绝。真实 publisher 在首笔写入前一起检查 immutable、index/event、精确回滚和回执 buffers。非规范化的旧 index/event 在启用模式下写前拒绝。F10 对类别、请求长度、返回文本和 finance 条目设有限上界，原 serializer 对最终落盘 buffer 再次限制。PNG/独立图像导出在启动外部进程前拒绝。

实际公式组选股补件入口 `research_panel_formula_groups_daily` → `workbench_supplements.complete` 已接到同一池的原普通类别 Claim。该完成事件按原日期、公式来源和精确 roster 单独标识，并复用日产品审定上界，不继承已经终结的上游 Claim。公式组与产品输出根均须在原 policy 的批准根中。全部三个大阶段的计划还显式包括原生输入、复权快照和这个补件消费者的留存上界。`consumer_peak_bytes` 列出六个顺序消费者，四字段 `phase_peak_bytes` 保留控制器协议。

`receipt_bytes` 是在首笔业务写入之前保留的固定回执额度，仅完成/失败回执路径可消耗。未抵达业务回执时，原 Claim 的既有预分配控制槽保留实际失败状态。

每阶段上界有 12 个整数配置项。`reviewed_limits` 需绑定所有实际 serializer、QFQ/delta/input 与自然补件 facade 的源码 SHA。测试审定文件明确标记 `ISOLATED_FIXTURE`，锁内 helper 的成功状态为 `PASS_ISOLATED_FIXTURE`。生产控制器明确拒绝该 scope。`ACCEPTED_WRITER_PHASES` 继续为空，生产数值尚待独立认证。`policy.disabled.delta.json` 仍为关闭状态，既有 261 GiB 与全部八条旧预留完整保留。

复验使用已有 `verify_overlay.py`，先核 R4 原冻结字节，再在临时目录按相对路径合并 Python 源码。只复制执行所需源码，不复制运行时、行情或完整面板。命令和实际通过范围见 `WRITER_RECEIPT.json`。完整市场日更、真实 F10 网络与自然调度未运行，独立 Reviewer 需在最终冻结 SHA 上复核。

V192 的单独 `after_preselection` 调度入口超出本轮日产品完成事件范围，覆盖状态保留 `CANNOT_CONFIRM`。日产品内的 `at_numeric_completion` 和其实际 serializers 已接入。本轮没有改动独立预选路径。
