# 194-R0 最终执行方案 V2

状态：IMPLEMENT_AUTHORIZED_INPUT_PREPARATION_STARTED；用户已批准实施。旧V1保留，本V2作为后续唯一执行冻结。

## 1. 目标、日期与数据边界

研究版固定PUBLICATION_TIME_RECONSTRUCTION/DIRECTION_ONLY；原认证PIT路径不放宽，不把historical_availability_bound设为true。Mac only，沿V4原权威数据派生，无Windows、新producer、UI、BUY或交易。信号日D-1，decision_at=D09:25+08:00，target_date=D，label_end_at=D收盘；label_available_at独立记录。key、split、Top50、暴露日全部按target_date。候选必须是原研究股票池全量192＋原主图全部十路＋有效source OR；B1锁J<=13且BBI>白>黄，不退化192/318，不把Top100作输入。缺全十路依赖则报告未覆盖而非静默部分训练。输入物化后冻结manifest/schema/calendar/代码/标签/价格口径/SHA；原始资料保留，缺失、晚到、非股、重复单列。来源三态hit/confirmed_absent/unknown，unknown显式mask，不能冒充absent；同topic跨槽去重，pool不称独立来源。

## 2. 唯一变量、模型与时间样本外

baseline为192触发＋原主图十路触发共11列；194仅追加复盘、Stage7、研报三类状态及各自与technical_any共振。来源采用hit与unknown显式编码，confirmed_absent才是已知不命中；同pool/rows/dates/Top50、不足不补。两臂LR L2/C=1/seed=194/lbfgs/max_iter=1000/tol=1e-8，train-only scaler，不调参。标签为target_date收盘相对前交易日收盘在同研究股票池Top100，原已接受价格口径与排序规则精确绑定。合格target_date至少20；排序前半向下取整训练，剩余按每5个date expanding评价，末尾短fold保留。train label_available_at必须严格早于fold首decision_at，禁止随机拆行。五个已暴露target_date 2026-10-16/19/20/21/22从train/OOF/finalrefit全部排除，只diagnostic；没有真正sealed数据则明确没有。

## 3. 执行、指标与验收

先登记输入准备RUN_STARTED，输入初始SHA未知如实null，物化后checkpoint冻结，不伪造初始hash。模型日期/schema/unknown/曝光/推理gate配套增量工程测试；旧9项有效PASS不无变更重跑。首OOF fold作小样本真实canary，通过后复用作正式首fold，不重复fit。线程2，检查资源、保存checkpoint；其余fold按同合同执行。主指标paired daily ΔHit@50；5日moving-block bootstrap/2000次/seed194，均值>=1且95%CI下界>0才效果门候选；OOF不足20日不判PASS，通过也仅DIRECTION_ONLY。固定50slots、实际slots、正例分母分开；报共同/新增/丢失命中、缺失日期、失败fold，失败不调门槛。

评价结束后按预定义全部合格非诊断日期refit baseline与194，训练标签须在trained_asof前已可用。安全JSON保存模型、预处理、配置、SHA和版本，往返预测parity；批预测须decision_at严格晚于training_label_available_at_max及trained_asof。未来输入不存在时交历史独立预测与可运行入口，不伪造未来名单。独立SolHigh因子/ML Reviewer按冻结scope验收；receipt和官方registry按阶段追加。

## 4. 分工、路径与停止条件

Root裁决/集成/远端同步；模型Writer独占model194/test_model194/registry_bridge/run194/report194/README/PLAN/SLIM_STATUS及本地除inputs外工件和registry追加；数据Writer独占data194/test_data194及inputs。所有代理GPT-6.1 Sol High，均不spawn。实现路径worktrees/a_share_v194_20261023/research/a_share_v194/，本地产物research/a_share_v194_20261023/。必要源码与slim摘要由Root同步lexi2016/v4分支codex/a-share-v194-20261023，基线ef3aac383ab1b63af11e286769691d039d67d5d7，不上传行情/文章/名单/权重/原registry。不启scheduler；趋势补漏/09:35二筛另立阶段。缺关键feature/label/time字段就停止该依赖，继续可独立工作；健康运行不因等待超时取消。research_only=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。


## 2026-10-24 授权来源修复及后续边界

本轮唯一变量是来源恢复投影：复盘/Stage7原池可追溯成员、研报原发布时间/字面实体与原collector拼接重建，三来源与三语义轴分开，未知不补0，主体false不作新过滤。模型/标签/Top50/拆分/统计门不变。30完整日按原算法15训练+15OOF，8真实fit已独立验收；技术11特征L2基线66对194的94（750slots），共同49/新增45/丢失17，15OOF不足20，不能效果PASS。旧结果与输入字节保留，当前字典改正引用新DATE_POLICY的副本单独交付。

新增逐日导出把结果Top100、冻结tech_192字段自然投影（身份另核）、技术11特征L2 Top50、194 Top50明确区分。所有名单只连冻结标签/保存名单，0新增fit/公式/采集。当前作用是项目隔离sklearn模块而非已经调用因子工厂长历史pipeline。用户另授权长窗口与总并发预算12（未来先8路canary、按吞吐升12），独立LONG_HISTORY_AUTHORITY_PREFLIGHT先查既有20+年源/passport/复权/日历、真实pipeline入口及用户192身份；该preflight本身0fit/0公式/0标签构造，不因扩线程重跑本批。
