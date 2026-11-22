# 本轮写入接入与剩余认证

| 原入口 | 已执行的写前约束 | 隔离证明 |
|---|---|---|
| 日产品 spawn worker / score ProcessPool.map | 初始化一次来源校验；提交预扣全部在途字节和文件数；每股累计硬槽位；结果核账后归还 | 真实 spawn、真实 serializer、失败后 sibling 排空、oversize 写前拒绝、score cache |
| daily row / compaction | canonical raw、单文件限额；原生压缩暂存按三份 4 KiB 对齐 | 累计槽位和 native legacy 回归 |
| history checkpoint / retained gzip | 原 `_publish` / save 入口检查实际 raw；容量失败透传 | 历史 checkpoint、chart block 原回归，容量 catch 负例 |
| shared chart / score_action / V192 / statistics | 复用已有 save 或实际 raw guard；PNG 和独立导出写前拒绝 | 真实 score spawn map 和父进程写入，来源 SHA 绑定 |
| 日产品正常完成 index/event / statistics | 一次预扣主对与原始旧字节回滚，失败后恢复本任务 statistics 指针 | 真实 owner quota 负例、event I/O 故障、statistics 指针后故障与精确恢复 |
| Top200 staging / 原动态 publisher | immutable/index/event、回滚和回执 buffers 一次预检；非规范旧前像写前拒绝 | 原 stage/publish、真实事件写故障恢复、空间不足不写 immutable |
| F10 | 请求长度与返回 bytes/items 限额；实际 `_write` guard；原 index/event 发布回滚预扣 | F10 过大请求不调用 content、过大序列化无落盘 |
| 自然公式组 supplement | 原 complete facade 进入同一普通类别 Claim；精确日期/roster/公式源；批准的输出根；容量失败经两层 facade 透传 | 原公开入口路由到真实 Registry/Claim 和 pointer serializer，来源/authority 用确定性夹具 |
| 当日 attempt / 完成回执 | 首笔业务写入前保留审定 receipt_bytes；attempt/index group 预检 | 业务写尽后仍可写固定失败回执的负例 |

GAP-03 仍要求在独立审核后给出适用生产的具体 reviewed_limits 和完整来源/自然链证据。当前只有 `ISOLATED_FIXTURE` 合同。所有字节/文件硬限额都能执行，但小夹具通过不能证明所有当前市场输入均能在这些候选限额内完成。原 Stage/QFQ 两项 P1 PASS 继续沿用。

V192 单独 after_preselection 路径为范围外 `CANNOT_CONFIRM`，本轮日产品完成路径的通过不覆盖该独立调度入口。
