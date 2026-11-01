# 已部署：API r4 + Stage / 开盘预采 r3

本轮用户明确授权上线、页面点击验收、失败回滚，以及将确认未使用的旧代码迁到待删除。业务候选保持原封存字节；本轮新增固定三目标切换工具、回滚回归及精简实测回执。

## 实际切换与独立验收

- 主 Stage、A 开盘预采、API 三个 loaded 身份及 plist 均核回批准候选；Main、HK deadline 和其他保护服务保持。
- API PID 13758，healthz / readyz HTTP200，运行身份为 `MANIFEST_EXECUTION_FILES_VERIFIED`。`process_status=CANNOT_CONFIRM` 保留，没有升格成进程来源认证。
- 整体切换24.42秒，健康中断最长上界11.8821秒，随后恢复；没有发生实际回滚。回滚首个目标失败后继续恢复其余可归属目标的分支已用两个隔离 mock 验证。
- 面板在切换前由其原任务更新为488项资产，当前清单SHA为 `f5c4b58901f7c40ae905df96e787b93ffa1b5e840c74650ca5bcc559efc204a3`。仅本批操作保护前像采用此精确generation，原候选和资产未改。488项及外置绑定前后核回。
- 独立操作审核、部署后服务及诊断留存审核、页面声明与实际手工任务核验均为 `REVIEWED/PASS`，无本批剩余发布阻断。

## 内置浏览器实际点击

- 10/30 的09:25、09:35、15:00和港股末阶段均实际点击。早段显示事后补选10条及真实快照时刻；下午A股10条；原失败、观察与非原时点标记保留。
- SOP实际显示新文档SHA `e7b8ac64ba04c37067869a4660a6313569b4571036762633836a62af97050b58`，含原始返回留存、CAS恢复和r4手动配置。
- 手动补采真实POST和任务GET均HTTP200，任务 `9bc918c3dc454f21b557f8e0d17a96d2` 由新API PID13758处理，绑定r3 Stage和新manual配置。最终为 `CANNOT_CONFIRM / HK_STAGE8_EXACT_RTDATA_REPLAY_UNAVAILABLE`：10/30没有原时段RT_DATA回放，晚间不能补成原时点。未启动Stage子进程，未声称恢复数据。
- 初次加载只有一个批量时间轴请求；多次日期/阶段交互累计6个batch响应均200。控制台error/warn为空、未见Runtime异常；两次导航取消及一次返回控制超时均保留，后用明确导航恢复原用户页。
- 原用户标签已恢复 `/?date=20261102&stage=STAGE_0925`，11/2未到期保持等待。实际CDP DOM核回指针锁为空、无对话框、焦点BODY，控制操作结束；未关闭用户标签。
- 研究面板页面、请求和资产保留已核。URL来源日10/30时面板显示观察日11/2、来源10/30，沿用其现行观察/来源映射，不把本轮验收扩为面板全部图表或日期口径认证；面板改造代码未改。

## 原始数据与补数边界

部署后的原Stage脚本只读诊断10/30 09:25，确认原532、有效531、隔离A.261029，原receipt SHA未变。对HK8运行该通用诊断时，其A股Observation结构校验返回 `SNAPSHOT_RECOVERY_EXACT_A_IDENTITY`；原失败保留，HK8补采以专用入口回执为准。

实际部署的留存函数在真实raw根下单独 `.retention_acceptance` 目录执行了一次真实缺失文件诊断，写2份文件共3,804字节，原异常同对象重抛，真实当前时钟和SHA可读，明确 `authorizes_selection=false`。未调用网络/provider，未写正式RawStore、selection、receipt或index。原raw1654、receipt1495、selection1780文件的size/mtime/mode统计树及内容抽样保持，另核源snapshot与指定原receipt SHA；不声称全量内容哈希。

自然窗口和新provider采集留存仍为 `NOT_RUN`。历史上未收到的原始数据不能补造，失败留证不等于行情原值存在。

## 可逆清理与回滚材料

994份配置/清单元数据盘点后，只迁移无运行引用的旧 `stage-four-repairs-20261101-r2` 候选和未被消费的9月源码备份。共2项、约210MB、3729个目录/文件项，内容SHA、权限、inode及mtime前后相同，没有删除。

待删除位置：`~/Library/Application Support/com.lexi.v4.local/待删除/20261101-stage-four-release/`。完整清单在该目录 `MIGRATION_RECEIPT.json`；路径绑定的旧候选只能恢复原空路径后使用。r3旧API因组装工具仍读取其封存manual配置而保留；现役、原回滚、面板依赖、其他任务工作树和仍被import的legacy模块保留。

源码旧备份仅在canonical分支原有，部署分支此前没有此文件。其删除记录用独立清理分支 `codex/v4-unused-source-20261101` 保存，基于原canonical HEAD，只包含备份删除与迁移回执；采用私有Git index，未暂存或覆盖研究面板的并行修改，不合并任何分支。

原三份plist和冻结计划另有永久控制备份：`~/Library/Application Support/com.lexi.v4.local/rollback/stage-four-release-20261101-r2/`，7份控制文件67,039字节，SHA和权限核回。它不是业务数据快照；其中reference-only脚本不能直接执行。原执行工作树、原release及 `/private/tmp/v4-stage-four-release-20261101-r2/` 控制路径保留。

精确回滚命令见 `OPERATIONAL_RESULT.json`，plan SHA `cd227c3d43705163744e9f06cd35280a4c6bd4bd83e98681b6e961c178b545fe`。回滚前仍需重核当前身份、空闲和保护generation；不覆盖并行发布、不删除新raw/失败记录、不重置attempt预算。

## 证据

`OPERATIONAL_RESULT.json`、`OPERATIONAL_PREFLIGHT.json`、`OPERATIONAL_PANEL_GENERATION.json`、`OPERATIONAL_DIAGNOSE.json`、`OPERATIONAL_RETENTION.json`、`LIVE_UI_RECEIPT.json`、`QUARANTINE_RESULT.json`。原FAIL和后续PASS均保留；原始数据、完整备份、运行目录和截图不上传Git。
