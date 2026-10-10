# 云编码断连：2026-10-10只读诊断

结论：现有证据与“通知对应原VM冷重启/原执行器进程重启/原V5服务丢失”不符；没有足够平台连接日志确定断连原因。不得把idle timeout、七天VM恢复窗口或服务主动重启当作此次根因。

采样前产品/交付源码已固定30861db7545da2a2036a0e3525a804ae9379f307，并push、fetch、逐字读回关键文件。本次未重启进程、修改配置、扩大权限、新建环境或触碰独立桌面预览。未读秘密、完整环境变量、会话目录或SSH日志；进程只读comm/stat，不读cmdline/environ。

## 已核时间线（均UTC）

| 时间 | 证据与含义 |
|---|---|
| 08:56:53 | 当前/proc/stat btime=1791622613；可见内核启动时间，非控制平面生命周期日志 |
| 08:56:53.950 | 当前PID1 tail的start_ticks=95，HZ=100 |
| 08:57:04.200 | 当前执行器codex PID473的start_ticks=1120；本次工具执行的sandbox进程仍以473为祖先 |
| 09:18:42 | 父线程确认收到第一次disconnected通知，非本机内核事件 |
| 09:20:31 | 前轮实际shell/Git/HTTP成功，原2923/2924/2925尚在；见INCREMENTAL.md。距通知109秒只代表此时已能执行，不能当断连时长 |
| 09:25:53 | 代理为已提交V5变更主动重启三个候选进程；不是VM重启证据 |
| 09:50:52 | 父线程确认收到第二次disconnected通知 |
| 09:51:20 | 前轮实际执行确认6919/6920/6921及未提交源码仍在；距通知28秒不是已证明的断连时长 |
| 10:04:16 | 本轮之前主动启动新版独立19096包，非断连恢复/原服务重启 |
| 10:06:33.300—.342 | 当前同次资源/进程采样；uptime4180.15秒，原服务PID及start_ticks不变 |
| 10:06:51.549 | 定向日志可见性采样；平台日志未获得 |

本次boot_id=4097fd66-9e2f-4f8b-9dd2-600e1b6ba925。没有两次通知前的boot_id样本，不能伪称已做事件前后boot_id逐字比较。现有uptime、早于事件的PID/starttime和历史实际执行共同支持原运行环境连续保留；无法由此排除透明暂停/恢复、宿主迁移或控制平面/客户端连接短暂中断。

服务身份：6919(manager18897) start_ticks174001；6920(announcement18898)、6921(gateway18896)均174002，对应09:25:53.010/.020。新版launcher11864、子进程11865/11866/11867始于10:04:16.310/.370。两gateway只读auto GET均200、48172字节、SHA133a1f218d533028b1c04372839a80bdefda9740acc263a59d3928fc4272e9e0，与已保存响应相同。这是API存活证据，不代替UI或真实业务验收。

## 资源证据与边界

当前可见cgroup路径0::/，memory.events及memory.events.local全部low/high/max/oom/oom_kill/oom_group_kill=0。memory.max=17179869184（16GiB），current=950484992，peak=4077928448字节。可见层无OOM计数证据，不能据此排除不可见宿主/平台侧资源事件或计数器生命周期变化。

/workspace 32G总量、651M已用、30G可用、3%；inode2%。/tmp 8.8G总量、7.3M已用、8.8G可用、inode1%。当前不是空间/inode耗尽；没有事件时刻历史采样，不声称证明当时所有资源正常。

## 日志检查及权限缺口

- journalctl限定09:10:00—10:06:30，筛disconnect/reconnect/WebSocket/heartbeat/idle/OOM/killed/restart，exit1：No journal files were found；journal目录空，list-boots同样无数据。不是“查到无断连”。
- dmesg --level=err,warn，exit1：read kernel buffer failed: Operation not permitted。没有提权重试。
- 只尝试readlink执行器/proc/473/fd/1、fd/2，两者Permission denied；未尝试读取pipe、其他进程内存或禁读会话目录。
- 可见/var/log/runit仅ssh；不读其内容，它不能替代云编码控制平面日志。
- 本任务自有应用日志按连接异常关键词筛选无命中；这些日志主要为启动与测试输出，不记录平台连接生命周期，因此无命中不能证明无连接故障。
- 没有暴露可用的平台连接诊断工具。需要平台侧提供两次通知附近的session/transport关闭原因、WebSocket close code、heartbeat、idle策略实际触发记录、VM suspend/resume/termination及执行器重启事件，才能进一步归因。不要提供token或全量会话内容。

未发生自动审批拒绝；上述是只读操作返回的OS权限不足或日志不存在，未申请扩权。官方七天状态恢复窗口不是此次idle timeout原因证据；本报告未自行推定该原因。

准确本地输出：/workspace/v5-evidence/disconnect-20261010/readonly-sample.json、log-access-sample.json、service-readonly-check.json。SHA/字节索引见disconnect-evidence-index.json。已有V5真实链工作固定于ROUND3.md；数据授权、原公告路径闭包、US正常网络许可及超跌原历史/资格仍是实质依赖，不以本诊断消除。
