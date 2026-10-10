# M02编码任务 · HK三类来源、三日期和真实取得时点

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


只写本模块范围，复用现有原collector/authority与严格reader。不要将主表恢复、价格读取、资格正式确认合并成一个READY。

## 最小候选
1. 明确target_date、HK证券signal_date、eligibility_source_date及各source available/acquired/captured时间、cutoff、原owner/配置/源文件SHA。日期与取得时点独立；现今恢复的资格不能假装历史盘前已知。
2. 先沿已有native master、panel/price history、membership回执读取；分别报告缺项和原拒绝码。价格成功而资格不明时允许研究状态按原语义保留，不伪造formal_eligibility_verified。
3. 新hk_source_daily薄封装现有流程/私有binding。capture_master必须真实MasterBinding与进程内prepare能力；不从feed生成授权，不把反序列化prepared JSON当可发布对象。原SDK原值与规范字段分离，不消除NaN/Decimal/缺失以刷绿。
4. 可复用的membership恢复严格核SDK SHA/producer/plate集合/目标日/七文件；real available_at保持现在，不回填。native_identity_reader必须用正确参考日，不靠股票名称推资格或issuer。
5. 缺真正原件时沿原HK owner现有SDK调用产生source，不额外重复get_market_snapshot；复用Recorder只是观测不增加调用或自动retry。现有Mac OpenD不可用则准确阻断，不新授凭据/权限。
6. 输出M02私有来源binding，M06/M14/M15只读；定义缺源、有效空、未知、过期分别语义。失败不可覆盖旧成功，旧成功展示必须标日期/过期，不冒新日。

## 必要负测
三日期错配、A/HK日历混用、主表/价格/资格互换、unit/规模错误、SDK原值不合法、主表和报价代码范围不符、七文件缺失/篡改/多出、目标资格未知、after-cutoff、恢复available_at被倒填、source/output重叠、symlink、同input重复、失败重试旧成功保留。资格未知不是零只，也不是已获资格。

共享文件包括provider_evidence/snapshot_recording/hk_preselection及所有注册/调度/UI，必须交INTEGRATION_REQUEST；你只改SOURCE_MAP白名单。超跌int64/string问题归M14原owner任务，不在M02放宽其身份门。

## 必须交付
1. 唯一固定candidate commit或完整候选包、base ref、donor→现有V5目标映射；已等价实现不改。
2. before/after完整修改文件、runtime.patch、reverse.patch；每文件Git blob SHA、before SHA256、after SHA256，新增文件before=ABSENT，删除说明用途；不编造未来after值。
3. 依赖/私有输出/输入manifest清单，原算法等价用例与失败用例源码，原始测试命令/环境/退出码/日志；没有真实数据时标NOT_RUN。
4. 共享变更单INTEGRATION_REQUEST：共享目标路径、before SHA、调用方、接口与日期/cutoff/失败语义、向后兼容、验收方法；统一集成者实施，Chat不附共享文件覆盖补丁。
5. MAC_APPLY_AND_ACCEPTANCE：前像检查、隔离应用、必要回归、真实输入/独立读回、API/页面、唯一发布窗口及单模块回滚。部署路径/端口未知时列现场核实项，不猜命令。
6. 五层分别报告代码候选、Mac工程测试、真实业务生产/保存/独立读回、API/原页面、自然接续与回滚。历史测试不相加，不冒称本轮运行。
缺当前Mac active前像不阻挡固定f7cb静态候选；嘻嘻安装前核active SHA。不要要求Chat连Mac，也不要向用户索取已有GitHub材料/整库/凭据。保留V4、8910与BUY门，不交易，不扩大安全权限或凭据。

