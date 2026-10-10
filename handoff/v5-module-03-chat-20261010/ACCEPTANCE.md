# M03 · Mac落地与独立验收

本轮只准备任务书，以下是未来执行步骤，不是已运行记录。嘻嘻执行；Chat无Mac连接不构成静态候选阻塞。

## 安装前与精确补丁
1. 在现有Mac确认checkout路径、当前HEAD、Python/依赖锁、现役V4与V5进程身份、模块活动root和所有相关文件的SHA256。历史canonical不等于现役字节。
2. 核candidate固定commit、patch范围、逐文件before/after SHA及依赖清单。前像不符暂停该安装，给原Chat精确差异；不整文件强盖、不修改其他Chat文件。
3. 私有隔离目录/输出root应用，检查SOURCE/OUTPUT不重叠、marker、symlink规则与闭包SHA；不清空现有成功。不用main或现役V4当测试区。
4. 使用项目现有解释器和原依赖；先针对性测试，再按真实共享影响执行必要回归。可定位既有入口为V5/tests/test_cloud_us_collector.py、test_cloud_transport.py；新增test_us_source_daily.py由候选给具体运行命令。原测试代码存在不等于本轮通过，测试使用合成网络时明确标注。

## 真实来源链
5. 记录真实当前时钟、America/New_York session、phase、cutoff、原slot/owner与配置SHA。核当前窗口是否适用；NOT_DUE正常保留，不改时钟强跑。33样本数量不可当覆盖定义。
6. 优先复用原owner已经产生的合格精确三文件。确需抓取时依原既有授权流程在私有root执行，保留raw provider来源哈希及实际取得时点；禁止把回放称自然抓取。
7. 对payload、receipt、manifest逐文件记录路径/大小/SHA256；原ResearchPeripheralStore.read_exact在私有快照独立回读。匹配session/phase/capture_id/run_id/response SHA，确认captured_at不晚于消费cutoff，校验失败明示原拒绝码。
8. 给M15一份来源binding/只读副本，核消费者接受或准确拒绝同来源。M15的行业/个股映射、四键、经理计划不作为M03已完成证据。
9. 共享API/原页面只由统一集成者接入。已有历史research_lane_router.py后缀/us-market已核，完整活动挂载地址未核，需现场查路由，不编造URL。实际点击来源日期、刷新、返回、错session/缺源提示，GET不得触发新采集。
10. 回滚仅本模块候选/指针，核其他模块API、现役V4与8910保持；不将旧成功标签改成今日来源。记录回滚前后run/SHA。

## 连续自然接续
两个连续适用US session：调度真实触发→原provider→三文件→原reader→下游binding。睡眠/重启、重复slot、错日/缺源恢复各保留真实trigger_kind。周末/休市等待适用session，不拿手动补跑代替。

## 五层状态，每次反馈逐层填写
1. 代码候选：本包仅任务书；候选NOT_CREATED
2. Mac工程测试：本轮NOT_RUN，历史报告单列commit/命令/时间
3. 真实业务生产与保存/独立读回：本轮NOT_RUN；已有报价读回为R证据，非自然采集
4. API/原页面接入：本轮NOT_RUN；映射页面不能代替来源链
5. 自然接续与单模块回滚/完整验收：本轮NOT_RUN；无本轮证据不得记完成M03

反馈字段：固定commit、环境/锁、触发类型、target/session/phase/cutoff、实际起止、输入与三文件SHA、原日志、原拒绝码、独立读回、API/页面录证、回滚、未决缺口。失败只反馈同一Chat，不另开第二实现。

